"""Shared GUI theme initialization for medtech-suite PySide6 applications."""

from __future__ import annotations

import enum
import os
from pathlib import Path
from typing import Optional

from medtech_gui._widgets import ConnectionDot
from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QFontDatabase, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton

_REQUIRED_FONT_FAMILIES = {"Roboto Condensed", "Montserrat", "Roboto Mono"}

# Icons for the three theme modes (basic Unicode — renders in all fonts)
_THEME_ICONS = {
    "light": "\u2600",  # sun
    "dark": "\u263E",  # crescent moon
    "system": "\u25D0",  # circle with left half black
}


class ThemeMode(enum.Enum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class ThemeManager(QObject):
    """Manages light / dark / system theme switching for medtech-suite GUIs.

    Singleton per QApplication — call ``ThemeManager.instance()`` to get
    the active manager after ``init_theme()`` has been called.

    Signals
    -------
    theme_changed(str)
        Emitted with ``"light"`` or ``"dark"`` whenever the effective
        theme changes.
    """

    theme_changed = Signal(str)

    _instance: Optional["ThemeManager"] = None

    def __init__(self, app: QApplication, res: Path) -> None:
        super().__init__(app)
        self._app = app
        self._res = res
        self._effective: str = "dark"
        self._toggle_btn: Optional[QPushButton] = None

        # Cache stylesheet contents
        self._light_qss = self._read_qss("medtech.qss")
        self._dark_qss = self._read_qss("medtech-dark.qss")

        # Restore persisted mode (default: system)
        settings = QSettings("RTI", "MedtechSuite")
        saved = settings.value("theme/mode", "system")
        try:
            self._mode = ThemeMode(saved)
        except ValueError:
            self._mode = ThemeMode.SYSTEM

        ThemeManager._instance = self

    @classmethod
    def instance(cls) -> Optional["ThemeManager"]:
        return cls._instance

    # -- Public API -------------------------------------------------------

    @property
    def mode(self) -> ThemeMode:
        return self._mode

    @property
    def effective_theme(self) -> str:
        return self._effective

    def set_mode(self, mode: ThemeMode) -> None:
        """Set the theme mode and apply the corresponding stylesheet."""
        self._mode = mode
        self._apply()

    def cycle(self) -> None:
        """Cycle through light → dark → system → light."""
        order = [ThemeMode.LIGHT, ThemeMode.DARK, ThemeMode.SYSTEM]
        idx = order.index(self._mode)
        self.set_mode(order[(idx + 1) % len(order)])

    # -- Internal ---------------------------------------------------------

    def _read_qss(self, filename: str) -> str:
        path = self._res / "styles" / filename
        if path.is_file():
            return path.read_text(encoding="utf-8")
        return ""

    def _detect_system_preference(self) -> str:
        """Detect OS dark mode preference via QPalette brightness."""
        try:
            hints = self._app.styleHints()
            scheme = hints.colorScheme()
            if hasattr(scheme, "name"):
                name = scheme.name.lower()
                if "light" in name:
                    return "light"
                return "dark"
        except AttributeError:
            pass
        # Fallback: check palette window color brightness
        palette = self._app.palette()
        bg = palette.color(QPalette.ColorRole.Window)
        # Luminance formula — light only if clearly bright
        lum = 0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()
        return "light" if lum >= 128 else "dark"

    def _apply(self) -> None:
        if self._mode == ThemeMode.SYSTEM:
            effective = self._detect_system_preference()
        elif self._mode == ThemeMode.DARK:
            effective = "dark"
        else:
            effective = "light"

        qss = self._dark_qss if effective == "dark" else self._light_qss
        self._app.setStyleSheet(qss)
        self._effective = effective

        # Update toggle button icon
        if self._toggle_btn is not None:
            self._toggle_btn.setText(_THEME_ICONS[self._mode.value])
            self._toggle_btn.setToolTip(f"Theme: {self._mode.value.title()}")

        self.theme_changed.emit(effective)

        # Persist the selected mode
        settings = QSettings("RTI", "MedtechSuite")
        settings.setValue("theme/mode", self._mode.value)

    def _set_toggle_btn(self, btn: QPushButton) -> None:
        self._toggle_btn = btn


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


def _load_stylesheet(app: QApplication, res: Path) -> ThemeManager:
    """Create the ThemeManager and apply the initial theme."""
    mgr = ThemeManager(app, res)
    mgr._apply()
    return mgr


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


def _create_header(res: Path, mgr: ThemeManager) -> tuple[QFrame, ConnectionDot]:
    """Create the dark header bar with RTI logo, title, theme toggle, and connection dot."""
    header = QFrame()
    header.setObjectName("headerBar")

    layout = QHBoxLayout(header)
    layout.setContentsMargins(16, 8, 16, 8)

    # Logo — use white-reversed variant for the dark header background
    logo_path = res / "images" / "rti-logo-white.png"
    if logo_path.is_file():
        logo_label = QLabel()
        pixmap = QPixmap(str(logo_path))
        scaled = pixmap.scaledToHeight(42, Qt.TransformationMode.SmoothTransformation)
        logo_label.setPixmap(scaled)
        layout.addWidget(logo_label)

    # Title
    title = QLabel("Medtech Suite")
    title.setObjectName("headerTitle")
    layout.addWidget(title)
    layout.addStretch()

    # Theme toggle button
    toggle_btn = QPushButton(_THEME_ICONS[mgr.mode.value])
    toggle_btn.setObjectName("themeToggle")
    toggle_btn.setToolTip(f"Theme: {mgr.mode.value.title()}")
    toggle_btn.clicked.connect(mgr.cycle)
    mgr._set_toggle_btn(toggle_btn)
    layout.addWidget(toggle_btn)

    # Spacer
    spacer = QLabel("  ")
    spacer.setStyleSheet("background-color: transparent;")
    layout.addWidget(spacer)

    # Connection dot (animated green/red indicator)
    conn_dot = ConnectionDot()
    conn_label = QLabel("Connected")
    conn_label.setStyleSheet(
        "color: #FFFFFF; font-size: 12px; font-family: 'Montserrat'; "
        "background-color: transparent;"
    )
    layout.addWidget(conn_dot)
    layout.addWidget(conn_label)

    return header, conn_dot


def init_theme(app: QApplication) -> QFrame:
    """Load the shared medtech theme and return the header widget.

    - Applies the current theme stylesheet to *app* (light/dark/system)
    - Registers bundled fonts (Roboto Condensed, Montserrat, Roboto Mono)
    - Returns a :class:`QFrame` header bar with RTI logo, title, theme
      toggle button, and connection dot

    The header includes:
    - :class:`ConnectionDot` accessible via ``header.findChild(ConnectionDot)``
    - Theme toggle button accessible via ``header.findChild(QPushButton, "themeToggle")``
    - :class:`ThemeManager` accessible via ``ThemeManager.instance()``

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
    mgr = _load_stylesheet(app, res)
    _register_fonts(res)
    header, _dot = _create_header(res, mgr)
    return header
