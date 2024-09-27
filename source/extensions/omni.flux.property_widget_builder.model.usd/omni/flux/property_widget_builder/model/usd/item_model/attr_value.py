"""
* SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
* SPDX-License-Identifier: Apache-2.0
*
* Licensed under the Apache License, Version 2.0 (the "License");
* you may not use this file except in compliance with the License.
* You may obtain a copy of the License at
*
* https://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing, software
* distributed under the License is distributed on an "AS IS" BASIS,
* WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
* See the License for the specific language governing permissions and
* limitations under the License.
"""

import abc
from copy import deepcopy
from typing import Any, Callable, List, Optional

import carb
import omni.client
import omni.kit.commands
import omni.kit.undo
import omni.usd
from omni.flux.property_widget_builder.widget import ItemValueModel as _ItemValueModel
from omni.flux.property_widget_builder.widget import Serializable as _Serializable
from omni.flux.utils.common import Event as _Event
from omni.flux.utils.common import EventSubscription as _EventSubscription
from omni.flux.utils.common import path_utils as _path_utils
from pxr import Gf, Sdf

from ..mapping import MULTICHANNEL_BUILDER_TABLE, TYPE_BUILDER_TABLE, VEC_TYPES, VecType
from ..utils import get_default_attribute_value as _get_default_attribute_value
from ..utils import get_item_attributes as _get_item_attributes
from ..utils import get_metadata as _get_metadata
from ..utils import get_type_name as _get_type_name
from ..utils import is_item_overriden as _is_item_overriden


class UsdAttributeBase(_Serializable, abc.ABC):
    """
    The model mixin to watch USD attribute paths.
    """

    def __init__(
        self,
        context_name: str,
        attribute_paths: List[Sdf.Path],
        read_only: bool = False,
        not_implemented: bool = False,
    ):
        """
        Base model of a USD attribute value.

        Subclasses should call `init_attributes` at the end of their init.

        Args:
            context_name: the context name
            attribute_paths:  the path(s) of the attribute
            read_only: if the attribute is read only or not
            not_implemented: if the attribute is not yet implemented for proper view (in code)
        """
        super().__init__()
        self._context_name = context_name
        self._stage = omni.usd.get_context(context_name).get_stage()
        self._attribute_paths = attribute_paths
        self._read_only = read_only
        self._is_mixed = False

        self._type_name = self.get_type_name(self.metadata)
        self._override_value_type = TYPE_BUILDER_TABLE.get(self._type_name)

        self._value = None  # The value that will be represented by the widget
        self._values = []  # The values of all the attribute paths
        self._summary_limit = 25  # max amount of values to display in a tooltip
        self._not_implemented = not_implemented
        self._ignore_refresh = False
        self._attributes = None

    def init_attributes(self):
        # cache the attributes
        self._attributes = _get_item_attributes(self.stage, self.attribute_paths)
        # initial read of attribute values
        self._on_usd_changed()

    def register_serializer_hooks(self, serializer):
        super().register_serializer_hooks(serializer)

        @serializer.register_serialize_hook(lambda x: isinstance(x, VEC_TYPES), key="Gf.Vec*")
        def serialize_vec(value: VecType) -> dict[str, str | list[float]]:
            return {"type": value.__class__.__name__, "value": list(value)}

        @serializer.register_deserialize_hook(lambda x: isinstance(x, VEC_TYPES), key="Gf.Vec*")
        def deserialize_vec(value: dict[str, str | list[float]]) -> VecType:
            return getattr(Gf, value["type"])(*value["value"])

        @serializer.register_serialize_hook(Sdf.AssetPath)
        def serialize_asset_path(value: Sdf.AssetPath) -> str:
            return value.resolvedPath.replace("\\", "/")

        @serializer.register_deserialize_hook(Sdf.AssetPath)
        def deserialize_asset_path(value: str) -> str:
            return omni.client.normalize_url(
                omni.usd.make_path_relative_to_current_edit_target(value, stage=self.stage)
            ).replace("\\", "/")

    @property
    def context_name(self):
        return self._context_name

    @property
    def attribute_paths(self):
        return self._attribute_paths

    @property
    def stage(self):
        return self._stage

    @property
    def metadata(self):
        if not self._stage:
            carb.log_error("Can't find the stage")
            return {}
        return _get_metadata(self._context_name, self._attribute_paths)

    @property
    def read_only(self):
        return self._read_only

    @property
    def attributes(self):
        return self._attributes

    @property
    @abc.abstractmethod
    def is_default(self):
        """If the value model has the default USD value"""
        pass

    @property
    def is_overriden(self):
        """If the value model has an override"""
        return _is_item_overriden(self.stage, self.attributes)

    @property
    def is_mixed(self):
        """Tell us if the model is "mixed". Meaning that the value has multiple values from multiple USD prims"""
        return self._is_mixed

    def get_tool_tip(self):
        """Get the tooltip that best represents the current value"""
        summary = ""
        more = ""
        should_use_separate_lines = len(str(self.get_value())) > 10

        if self.is_mixed:
            summary += "Mixed Values: "
            if should_use_separate_lines:
                summary += "\n"
        else:
            return self._get_value_as_string()

        values = self._values
        if len(self._values) > self._summary_limit:
            values = self._values[: self._summary_limit]
            more = "..."
        separator = "\n" if should_use_separate_lines else ", "
        value_text = separator.join(str(v) for v in values)
        return summary + value_text + more

    @staticmethod
    def get_type_name(metadata):
        return _get_type_name(metadata)

    @abc.abstractmethod
    def reset_default_value(self):
        """Reset the model's value back to the USD default"""
        pass

    @abc.abstractmethod
    def _get_attribute_value(self, attr) -> Any:
        pass

    @abc.abstractmethod
    def _set_attribute_value(self, attr, new_value):
        pass

    def _get_value_as_string(self) -> str:
        if self._is_mixed:
            return "<Mixed>"  # string field is able to give useful information for this case
        if self._value is None:
            return ""
        value = self.get_value()
        if value is None:
            return ""
        # isinstance check for metadata that may have different value than type
        if self._type_name == Sdf.ValueTypeNames.Asset or isinstance(value, Sdf.AssetPath):
            # get path string to remove @...@ for display
            return str(value.path)
        return str(value)

    def _get_value_as_float(self) -> float:
        if self._value is None:
            return 0.0
        return float(self.get_value())

    def _get_value_as_bool(self) -> bool:
        if self._value is None:
            return False
        return bool(self.get_value())

    def _get_value_as_int(self) -> int:
        if self._value is None:
            return 0
        return int(self.get_value())

    def _set_internal_value(self, new_value):
        """Set internal value from a widget value"""
        self._value = new_value

    def _read_value_from_usd(self):
        """
        Return:
            True if the cached value was updated; false otherwise
        """
        if not self._stage:
            assert self._value is None
            return False

        last_value = None
        values_read = 0
        value_was_set = False
        is_mixed = False
        self._values = []
        for attribute_path in self._attribute_paths:
            prim = self._stage.GetPrimAtPath(attribute_path.GetPrimPath())
            if prim.IsValid():
                attr = prim.GetAttribute(attribute_path.name)
                if attr.IsValid() and not attr.IsHidden():
                    value = self._get_attribute_value(attr)
                    if values_read == 0:
                        # If this is the first prim with this attribute, use it for the cached value.
                        last_value = value
                        if self._value is None or value != self._value:
                            self._value = value  # we can set directly from the _get_attribute_value value
                            value_was_set = True
                    else:
                        if last_value is not None and last_value != value:
                            is_mixed = True
                    values_read += 1
                    self._values.append(value)

        if is_mixed != self._is_mixed:
            value_was_set = True
        self._is_mixed = is_mixed
        return value_was_set

    def _on_usd_changed(self):
        """Called with when an attribute in USD is changed"""
        self._read_value_from_usd()

    @abc.abstractmethod
    def _on_dirty(self):
        pass

    def refresh(self):
        if self._ignore_refresh:
            return
        self._on_usd_changed()
        self._on_dirty()

    def _skip_set_value(self, value):
        if self.read_only or self._not_implemented:
            return True
        if (
            value is None
            or value == "."
            or (
                isinstance(value, str)
                and value.strip() == ""
                and self._type_name not in [Sdf.ValueTypeNames.String, Sdf.ValueTypeNames.Asset]
            )
        ):
            return True
        return False

    def _set_value(self, value):
        """Override of ui.AbstractValueModel._set_value()"""
        if self._skip_set_value(value):
            return False

        new_value = value
        if self._override_value_type is not None:
            try:
                new_value = self._override_value_type(value)
            except ValueError:
                carb.log_warn(f"Failed to use override type: {self._override_value_type} with value: {value}")

        self._set_internal_value(new_value)

        if not self._stage:
            return False

        need_refresh = False
        for attribute_path in self._attribute_paths:
            prim = self._stage.GetPrimAtPath(attribute_path.GetPrimPath())
            if prim.IsValid():
                attr = prim.GetAttribute(attribute_path.name)
                if not attr.IsValid():
                    continue
                current_value = self._get_attribute_value(attr)
                if current_value != self._value:
                    need_refresh = True
                    self._ignore_refresh = True
                    self._set_attribute_value(attr, self._value)
                    self._ignore_refresh = False
        if need_refresh:
            self.refresh()
            return True
        # value was not changed, but we do want to refresh the delegate
        self._on_dirty()
        return False


class UsdAttributeValueModel(UsdAttributeBase, _ItemValueModel):
    """
    The value model to watch USD attribute paths.
    """

    def __init__(
        self,
        context_name: str,
        attribute_paths: List[Sdf.Path],
        channel_index: int,
        read_only: bool = False,
        not_implemented: bool = False,
    ):
        """
        Value model of an attribute value

        Args:
            context_name: the context name
            attribute_paths:  the path(s) of the attribute
            channel_index: the channel index of the attribute
            read_only: if the attribute is read only or not
            not_implemented: if the attribute is not yet implemented for proper view (in code)
        """
        super().__init__(
            context_name,
            attribute_paths,
            read_only=read_only,
            not_implemented=not_implemented,
        )
        self._channel_index = channel_index
        # should we treat value as a "multi" value or by channel.
        self._is_multichannel = MULTICHANNEL_BUILDER_TABLE.get(self._type_name, False)
        self._has_wrong_value = False
        self.init_attributes()

    def get_value(self):
        """Get the value for serialization and external consumption."""
        if self._value is None:
            return None  # not set yet...
        # TODO: Store path object in self._value instead.
        if self._type_name == Sdf.ValueTypeNames.Asset:
            # NOTE: Sdf.AssetPath are supported in the serializer
            return self.get_attributes_raw_value(self._channel_index)
        if self._is_multichannel:
            return self._value[self._channel_index]
        return self._value

    def _set_internal_value(self, new_value):
        """Inverse of get_value. Prep widget value for storing in self._value."""
        if self._is_multichannel:
            # may not always be a dict, since this is a USD type
            self._value[self._channel_index] = new_value
        else:
            self._value = new_value

    @property
    def is_default(self):
        """If the value model has the default USD value"""
        for index, attribute in enumerate(self.attributes):
            if not attribute:
                continue
            default_value = _get_default_attribute_value(attribute)
            if default_value is None:
                continue
            if default_value != self.get_attributes_raw_value(index):
                return False
        return True

    def reset_default_value(self):
        """Reset the model's value back to the USD default"""
        self.block_set_value(False)  # be sure that we set the value
        for index, attribute in enumerate(self.attributes):
            if not attribute:
                continue
            default_value = _get_default_attribute_value(attribute)
            if default_value is None:
                continue
            # If the item is subscriptable, get the right value
            if self._is_multichannel:
                self.set_value(default_value[index])
            else:
                if self._type_name == Sdf.ValueTypeNames.Asset:
                    default_value = default_value.path
                self.set_value(default_value)

    def begin_edit(self):
        super().begin_edit()
        # In the case where widget A is currently editing, then user clicks directly
        # on Widget B to start editing, B's begin_edit will come through before A's end_edit.
        # Refresh to ensure that the cached _value is up-to-date, in the case that model updates are suppressed during
        # edit
        if self._read_value_from_usd():
            self._value_changed()

    def end_edit(self):
        # we set back to the USD value
        if self._has_wrong_value and self._read_value_from_usd():
            self._value_changed()
        super().end_edit()

    # TODO: Remove usages after dealing with Asset path type. Most cases would be better served with get_value().
    def get_attributes_raw_value(self, element_current_idx) -> Optional[Any]:
        prim = self._stage.GetPrimAtPath(self._attribute_paths[element_current_idx].GetPrimPath())
        if prim.IsValid():
            attr = prim.GetAttribute(self._attribute_paths[element_current_idx].name)
            if attr.IsValid() and not attr.IsHidden():
                return attr.Get()
        return None

    def _get_attribute_value(self, attr):
        value = attr.Get()
        if value is not None and self._type_name == Sdf.ValueTypeNames.Asset:
            return value.path
        return value

    def _set_attribute_value(self, attr, new_value):
        attribute_path = str(attr.GetPath())
        if self._type_name == Sdf.ValueTypeNames.Asset:  # noqa SIM102
            if isinstance(new_value, str):
                # Force textures to always use forward slashes, and check that the path is valid
                new_value = new_value.strip()
                if self.metadata and self.metadata.get("colorSpace"):
                    edit_target_layer = self._stage.GetEditTarget().GetLayer()
                    is_valid = new_value == "" or _path_utils.is_file_path_valid(new_value, layer=edit_target_layer)
                    if not is_valid:
                        self._has_wrong_value = True
                        return
                    absolute_path = omni.client.normalize_url(edit_target_layer.ComputeAbsolutePath(new_value))
                    new_value = Sdf.AssetPath(new_value.replace("\\", "/"), absolute_path.replace("\\", "/"))
            elif isinstance(new_value, Sdf.AssetPath):
                if self.metadata and self.metadata.get("colorSpace"):
                    edit_target_layer = self._stage.GetEditTarget().GetLayer()
                    if not _path_utils.is_file_path_valid(new_value.path, layer=edit_target_layer):
                        self._has_wrong_value = True
                        return
            else:
                raise NotImplementedError(f"Unknown type {new_value}")
        self._has_wrong_value = False

        # OM-75480: For props inside session layer, it will always change specs
        # in the session layer to avoid shadowing. Why it needs to be def is that
        # session layer is used for several runtime data for now as built-in cameras,
        # MDL material params, and etc. Not all of them create runtime prims inside
        # session layer. For those that are not defined inside session layer, we should
        # avoid leaving delta inside other sublayers as they are shadowed and useless after
        # stage close.
        target_layer, _ = omni.usd.find_spec_on_session_or_its_sublayers(
            self._stage, attr.GetPath().GetPrimPath(), lambda spec: spec.specifier == Sdf.SpecifierDef
        )
        if not target_layer:
            target_layer = self._stage.GetEditTarget().GetLayer()

        omni.kit.commands.execute(
            "ChangeProperty",
            prop_path=attribute_path,
            value=new_value,
            target_layer=target_layer,
            prev=None,
            usd_context_name=self._context_name,
        )

    def _on_dirty(self):
        self._value_changed()


class UsdAttributeValueModelVirtual(UsdAttributeValueModel):
    def __init__(
        self,
        context_name: str,
        attribute_paths: List[Sdf.Path],
        channel_index: int,
        default_value: List[Any],
        value_type_name: Sdf.ValueTypeNames,
        create_callback: Optional[Callable[[Any], None]] = None,
        read_only: bool = False,
        not_implemented: bool = False,
    ):
        self._default_value = default_value
        self._create_callback = create_callback
        self._type_name = value_type_name

        self.__on_attribute_created = _Event()

        super().__init__(context_name, attribute_paths, channel_index, read_only, not_implemented)

    @property
    def is_overriden(self):
        """Virtual attributes are never overriden. When they are they become real attributes"""
        return False

    @property
    def is_default(self):
        """Virtual attributes are always default. When they are overriden they become real attributes"""
        return True

    @property
    def is_mixed(self):
        """Virtual attributes are always default. When they are overriden they become real attributes"""
        return False

    @property
    def metadata(self):
        return {Sdf.PrimSpec.TypeNameKey: str(self._type_name)}

    def get_attributes_raw_value(self, element_current_idx):
        return None

    def end_edit(self):
        # If it's the default value, no need to create anything
        if self._value == self._default_value:
            return
        super().end_edit()
        # If a create_callback is set, use that
        if self._create_callback:
            self._create_callback(self._value)
        # Otherwise use the default creation
        else:
            for path in self.attribute_paths:
                if not path.IsPropertyPath():
                    continue
                prim = self._stage.GetPrimAtPath(path.GetPrimPath())
                omni.kit.commands.execute(
                    "CreateUsdAttributeCommand",
                    prim=prim,
                    attr_name=path.name,
                    attr_type=self._type_name,
                    attr_value=self._value if self._is_multichannel else self._value[self._channel_index],
                )
        # Notify the parent to refresh the tree
        self.__on_attribute_created(self.attribute_paths)

    def reset_default_value(self):
        pass

    def _read_value_from_usd(self):
        if self._value != self._default_value:
            self._value = deepcopy(self._default_value)
            return True
        return False

    def subscribe_attribute_created(self, function):
        """
        Return the object that will automatically unsubscribe when destroyed.
        """
        return _EventSubscription(self.__on_attribute_created, function)
