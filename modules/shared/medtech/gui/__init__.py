"""Shared GUI bootstrap for all PySide6 applications in medtech-suite.

Usage::

    from medtech.gui import init_theme

    app = QApplication(sys.argv)
    header = init_theme(app)
"""

from medtech.gui._theme import ThemeManager, ThemeMode, init_theme
from medtech.gui._widgets import (
    ConnectionDot,
    create_empty_state,
    create_section_header,
    create_stat_card,
    create_status_chip,
)

__all__ = [
    "ConnectionDot",
    "ThemeManager",
    "ThemeMode",
    "create_empty_state",
    "create_section_header",
    "create_stat_card",
    "create_status_chip",
    "init_theme",
]
