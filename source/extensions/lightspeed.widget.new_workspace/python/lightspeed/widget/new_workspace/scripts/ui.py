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

from pathlib import Path

import omni.ui as ui  # TODO: menu, switch to the new method when Kit switched
from lightspeed.widget.game_captures.scripts.ui import GameCapturesViewer
from lightspeed.widget.game_captures.scripts.utils import get_captures_directory
from omni.flux.utils.widget.file_pickers.file_picker import open_file_picker as _open_file_picker

from .utils import ReplacementPathUtils


class GameWorkspaceViewer(GameCapturesViewer):
    @property
    def default_attr(self):
        result = super().default_attr
        result.update(
            {
                "_use_existing_layer": None,
                "_replacement_layer_usd_field": None,
                "_enhancement_layer_usd_path_label": None,
            }
        )
        return result

    @property
    def style(self):
        style = super().style
        style.update(
            {
                "Image::SavePath": {"color": 0x90FFFFFF},
                "Image::SavePath:hovered": {"color": 0xFFFFFFFF},
                "Rectangle::SubBackground1": {
                    "background_color": 0x00333333,
                    "border_width": 1.0,
                    "border_color": 0x20FFFFFF,
                },
            }
        )
        return style

    def create_ui(self):
        """Create the main UI"""
        with ui.Frame(style=self.style):
            with ui.VStack():
                super().create_ui()
                with ui.ZStack(height=0):
                    ui.Rectangle(name="SubBackground0")
                    with ui.VStack():
                        ui.Spacer(height=8)
                        with ui.HStack():
                            ui.Spacer(width=8)
                            with ui.VStack(spacing=8):
                                row_height = 24
                                sub_width = ui.Pixel(50)
                                sub_label_width = ui.Pixel(100)
                                with ui.ZStack(height=0):
                                    ui.Rectangle(name="SubBackground1")
                                    with ui.VStack():
                                        ui.Spacer(height=8)
                                        with ui.HStack():
                                            ui.Spacer(width=8)
                                            with ui.VStack(spacing=8):
                                                with ui.HStack(height=row_height):
                                                    ui.Label(
                                                        "Use existing enhancements layer",
                                                        tooltip=(
                                                            "If true, you can import an existing " "enhancements layer."
                                                        ),
                                                    )
                                                    self._use_existing_layer = ui.RadioCollection(width=36)
                                                    ui.RadioButton(radio_collection=self._use_existing_layer, text="No")
                                                    ui.RadioButton(
                                                        radio_collection=self._use_existing_layer, text="Yes"
                                                    )
                                                    self._use_existing_layer.model.add_value_changed_fn(
                                                        self.__update_use_existing_layer
                                                    )

                                                with ui.VStack(spacing=8):
                                                    with ui.HStack(height=row_height, spacing=8):
                                                        ui.Spacer(width=sub_width)
                                                        self._enhancement_layer_usd_path_label = ui.Label(
                                                            "USD Path to create", width=sub_label_width
                                                        )
                                                        self._replacement_layer_usd_field = ui.StringField()
                                                        self._replacement_layer_usd_field.model.add_value_changed_fn(
                                                            self.__update_replacement_layer_usd_field
                                                        )
                                                        ui.Image(
                                                            str(
                                                                self._get_icon_path(
                                                                    "folder_open", from_base_extension=False
                                                                )
                                                            ),
                                                            width=row_height,
                                                            name="SavePath",
                                                            mouse_released_fn=lambda x, y, b, m: self._on_existing_layer_usd_file(  # noqa E501
                                                                b, m
                                                            ),
                                                        )

                                            ui.Spacer(width=8)
                                        ui.Spacer(height=8)

                            ui.Spacer(width=8)
                        ui.Spacer(height=8)

    def __update_use_existing_layer(self, value_model):
        value = self._use_existing_layer.model.get_value_as_bool()
        self._core.set_current_use_existing_layer(value)
        self._enhancement_layer_usd_path_label.text = "USD Path to read" if value else "USD Path to create"

    def __update_replacement_layer_usd_field(self, value_model):
        value = self._replacement_layer_usd_field.model.get_value_as_string()
        self._core.set_current_replacement_layer_usd_path(value if value else None)
        current_game = self._core.get_current_game_capture_folder()
        replacement_path_utils = ReplacementPathUtils()
        replacement_path_utils.append_path_to_recent_file(value, current_game.title)

    def _on_existing_layer_usd_file(self, b, m):
        if b != 0:
            return

        current_game = self._core.get_current_game_capture_folder()
        captures_dir = get_captures_directory(current_game)
        replacement_path_utils = ReplacementPathUtils()
        data = replacement_path_utils.get_recent_file_data()
        if current_game.title in data:
            current_directory = str(Path(data[current_game.title]["last_path"]).resolve().parent)
        else:
            current_directory = captures_dir

        bookmarks = {current_game.title: str(Path(current_game.path).resolve().parent)}

        _open_file_picker(
            "Directory picker",
            self._set_existing_layer_usd_str_field,
            lambda *args: None,
            current_file=current_directory,
            select_directory=True,
            bookmarks=bookmarks,
        )

    def _set_existing_layer_usd_str_field(self, path):
        if not path:
            return
        self._replacement_layer_usd_field.model.set_value(path)

    @property
    def calling_extension_path(self):
        current_path = Path(__file__).parent
        for _ in range(4):
            current_path = current_path.parent
        return current_path
