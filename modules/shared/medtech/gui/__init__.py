"""Shared NiceGUI utilities for medtech-suite GUI applications."""

from medtech.gui._backend import GuiBackend
from medtech.gui._colors import BRAND_COLORS
from medtech.gui._icons import ICONS
from medtech.gui._theme import (
    NICEGUI_QUASAR_CONFIG,
    NICEGUI_STORAGE_SECRET_DEFAULT,
    NICEGUI_STORAGE_SECRET_ENV,
    create_header,
    init_theme,
)
from medtech.gui._tokens import DESIGN_TOKENS
from medtech.gui._widgets import (
    ConnectionDot,
    create_empty_state,
    create_section_header,
    create_stat_card,
    create_status_chip,
)

__all__ = [
    "BRAND_COLORS",
    "ConnectionDot",
    "DESIGN_TOKENS",
    "GuiBackend",
    "ICONS",
    "NICEGUI_QUASAR_CONFIG",
    "NICEGUI_STORAGE_SECRET_DEFAULT",
    "NICEGUI_STORAGE_SECRET_ENV",
    "create_empty_state",
    "create_header",
    "create_section_header",
    "create_stat_card",
    "create_status_chip",
    "init_theme",
]
