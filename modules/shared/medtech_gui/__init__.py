"""Shared GUI bootstrap for all PySide6 applications in medtech-suite.

Usage::

    from medtech_gui import init_theme

    app = QApplication(sys.argv)
    header = init_theme(app)
"""

from medtech_gui._theme import init_theme

__all__ = ["init_theme"]
