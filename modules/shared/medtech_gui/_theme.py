"""Shared GUI theme initialization for medtech-suite PySide6 applications."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel

_REQUIRED_FONT_FAMILIES = {"Roboto Condensed", "Montserrat", "Roboto Mono"}


def _resource_dir() -> Path:
    """Resolve the shared resource directory.

    Checks ``MEDTECH_RESOURCE_DIR`` (set by install/setup.bash),
    then falls back to ``<repo>/install/share/resources/``.
    """
    env = os.environ.get("MEDTECH_RESOURCE_DIR")
    if env:
        return Path(env)
    # Fallback: assume typical install tree relative to repo root
    here = Path(__file__).resolve()
    repo = here.parents[3]  # modules/shared/medtech_gui/ -> repo root
    return repo / "install" / "share" / "resources"


def _load_stylesheet(app: QApplication, res: Path) -> None:
    qss_path = res / "styles" / "medtech.qss"
    if qss_path.is_file():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))


def _register_fonts(res: Path) -> set[str]:
    """Register all .ttf fonts and return the set of loaded family names."""
    fonts_dir = res / "fonts"
    registered: set[str] = set()
    for ttf in sorted(fonts_dir.glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(ttf))
        if font_id >= 0:
            for family in QFontDatabase.applicationFontFamilies(font_id):
                registered.add(family)
    return registered


def _create_header(res: Path) -> QFrame:
    """Create the dark header bar with RTI logo and title text."""
    header = QFrame()
    header.setObjectName("headerBar")

    layout = QHBoxLayout(header)
    layout.setContentsMargins(8, 4, 8, 4)

    # Logo
    logo_path = res / "images" / "rti-logo.png"
    if logo_path.is_file():
        logo_label = QLabel()
        pixmap = QPixmap(str(logo_path))
        scaled = pixmap.scaledToHeight(36, Qt.TransformationMode.SmoothTransformation)
        logo_label.setPixmap(scaled)
        layout.addWidget(logo_label)

    # Title
    title = QLabel("Medtech Suite")
    title.setObjectName("headerTitle")
    layout.addWidget(title)
    layout.addStretch()

    return header


def init_theme(app: QApplication) -> QFrame:
    """Load the shared medtech theme and return the header widget.

    - Applies ``medtech.qss`` stylesheet to *app*
    - Registers bundled fonts (Roboto Condensed, Montserrat, Roboto Mono)
    - Returns a :class:`QFrame` header bar with RTI logo and title

    Parameters
    ----------
    app:
        The running QApplication instance.

    Returns
    -------
    QFrame
        The header bar widget, ready to be placed in a layout.
    """
    res = _resource_dir()
    _load_stylesheet(app, res)
    _register_fonts(res)
    return _create_header(res)
