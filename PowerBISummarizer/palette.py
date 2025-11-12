"""
Centralized color and typography definitions for the PowerBISummarizer plugin.

The palette closely follows Power BI / Excel styling guidelines so the rest
of the codebase can import consistent tokens instead of hardcoding values.
"""

from collections import ChainMap

COLORS = {
    "color_app_bg": "#F5F6FA",
    "color_surface": "#FFFFFF",
    "color_border": "#E6E8EF",
    "color_text_primary": "#1D2A4B",
    "color_text_secondary": "#59657E",
    "color_primary": "#F2C811",
    "color_primary_hover": "#E6BB0E",
    "color_secondary": "#2D71F7",
    "color_success": "#2FB26A",
    "color_warning": "#F2994A",
    "color_error": "#EB5757",
    "color_table_zebra": "#FAFBFD",
    "color_table_selection": "#FFF3C2",
    "color_splitter": "#E6E8EF",
    "color_shadow": "rgba(29, 42, 75, 0.06)",
}

TYPOGRAPHY = {
    "font_family": "Montserrat",
    "font_base_size": 11,
    "font_title_size": 20,
    "font_subtitle_size": 15,
    "font_section_size": 15,
    "font_body_size": 12,
    "font_small_size": 10,
}

MISC = {
    "radius_surface": 16,
    "radius_button": 14,
    "radius_input": 12,
    "radius_table": 10,
    "button_height": 36,
    "input_height": 34,
    "tab_height": 38,
}


def palette_context():
    """
    Helper that merges all dictionaries so template formatting can use
    the keys as `${color_app_bg}`, `${font_title_size}`, etc.
    """

    return ChainMap({}, COLORS, TYPOGRAPHY, MISC)
