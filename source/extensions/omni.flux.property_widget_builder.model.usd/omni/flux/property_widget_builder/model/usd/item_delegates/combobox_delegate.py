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

__all__ = ("ComboboxField",)

import omni.ui as ui
from omni.flux.property_widget_builder.delegates.base import AbstractField


class ComboboxField(AbstractField):
    def build_ui(self, item) -> list[ui.Widget]:
        with ui.HStack(height=ui.Pixel(24)):
            ui.Spacer(width=ui.Pixel(8))
            with ui.VStack():
                ui.Spacer(height=ui.Pixel(2))
                widgets = [ui.ComboBox(item.value_models[0], style_type_name_override=self.style_name)]
                self.set_dynamic_tooltip_fn(widgets[0], item.value_models[0])
                ui.Spacer(height=ui.Pixel(2))
        return widgets
