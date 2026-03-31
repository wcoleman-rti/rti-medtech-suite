"""Reusable modern UI widget helpers for medtech-suite GUIs."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

# ---------------------------------------------------------------------------
# Color-coded status chip (#1)
# ---------------------------------------------------------------------------

# Semantic state → (light bg, light fg, dark bg, dark fg)
_STATE_COLORS: dict[str, tuple[str, str, str, str]] = {
    "RUNNING": ("#E8F5E9", "#2E7D32", "#1B3A26", "#66BB6A"),
    "STARTED": ("#E8F5E9", "#2E7D32", "#1B3A26", "#66BB6A"),
    "ACTIVE": ("#E8F5E9", "#2E7D32", "#1B3A26", "#66BB6A"),
    "OPERATIONAL": ("#E8F5E9", "#2E7D32", "#1B3A26", "#66BB6A"),
    "READY": ("#E3F2FD", "#004C97", "#0D2744", "#42A5F5"),
    "IDLE": ("#F5F5F5", "#63666A", "#2D3139", "#BBBCBC"),
    "STOPPED": ("#FFEBEE", "#C62828", "#3B1515", "#EF5350"),
    "ERROR": ("#FFEBEE", "#C62828", "#3B1515", "#EF5350"),
    "EMERGENCY_STOP": ("#FFEBEE", "#C62828", "#3B1515", "#EF5350"),
    "PAUSED": ("#FFF3E0", "#E65100", "#3B2510", "#FFA726"),
    "WARNING": ("#FFF3E0", "#E65100", "#3B2510", "#FFA726"),
    "PENDING": ("#FFF3E0", "#E65100", "#3B2510", "#FFA726"),
    "STARTING": ("#E3F2FD", "#004C97", "#0D2744", "#42A5F5"),
    "STOPPING": ("#FFF3E0", "#E65100", "#3B2510", "#FFA726"),
    "DISCONNECTED": ("#ECEFF1", "#BBBCBC", "#2D3139", "#63666A"),
    "UNKNOWN": ("#ECEFF1", "#63666A", "#2D3139", "#63666A"),
}

_DEFAULT_CHIP_COLORS = ("#ECEFF1", "#63666A", "#2D3139", "#63666A")


def _is_dark_theme() -> bool:
    """Check if the current effective theme is dark."""
    try:
        from medtech_gui._theme import ThemeManager

        mgr = ThemeManager.instance()
        if mgr is not None:
            return mgr.effective_theme == "dark"
    except ImportError:
        pass
    return False


def create_status_chip(state_text: str) -> QLabel:
    """Return a QLabel styled as a colored pill badge for *state_text*."""
    colors = _STATE_COLORS.get(state_text.upper(), _DEFAULT_CHIP_COLORS)
    dark = _is_dark_theme()
    bg = colors[2] if dark else colors[0]
    fg = colors[3] if dark else colors[1]
    chip = QLabel(state_text)
    chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
    chip.setStyleSheet(
        f"background-color: {bg}; color: {fg}; border-radius: 10px; "
        f"padding: 4px 14px; font-family: 'Roboto Condensed'; "
        f"font-size: 12px; font-weight: bold; min-height: 20px;"
    )
    chip.setFixedHeight(26)
    return chip


# ---------------------------------------------------------------------------
# Summary stat card (#2)
# ---------------------------------------------------------------------------


def create_stat_card(
    value: str, label: str, icon: str = "", accent_color: str = "#004C97"
) -> QFrame:
    """Return a KPI card widget showing *value*, *label*, and optional *icon*.

    Parameters
    ----------
    value:
        Large number or short text (e.g. "3").
    label:
        Descriptor below the value (e.g. "Hosts Online").
    icon:
        Unicode glyph displayed to the left (e.g. "\u2764").
    accent_color:
        Hex color for the left border accent and value text.
    """
    card = QFrame()
    card.setObjectName("statCard")
    card.setStyleSheet(
        card.styleSheet()
        + f"QFrame#statCard {{ border-left: 4px solid {accent_color}; }}"
    )

    layout = QHBoxLayout(card)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(10)

    if icon:
        icon_lbl = QLabel(icon)
        icon_lbl.setObjectName("statIcon")
        layout.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)

    text_col = QVBoxLayout()
    text_col.setSpacing(2)

    val_lbl = QLabel(value)
    val_lbl.setObjectName("statValue")
    val_lbl.setStyleSheet(f"color: {accent_color};")
    text_col.addWidget(val_lbl)

    desc_lbl = QLabel(label)
    desc_lbl.setObjectName("statLabel")
    text_col.addWidget(desc_lbl)

    layout.addLayout(text_col)
    layout.addStretch()
    return card


# ---------------------------------------------------------------------------
# Section header with icon glyph (#6)
# ---------------------------------------------------------------------------


def create_section_header(title: str, icon: str = "") -> QWidget:
    """Return a styled section header with optional icon glyph."""
    dark = _is_dark_theme()
    accent = "#00B5E2" if dark else "#004C97"

    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 4)
    layout.setSpacing(6)

    if icon:
        icon_lbl = QLabel(icon)
        icon_lbl.setObjectName("sectionIcon")
        layout.addWidget(icon_lbl)

    title_lbl = QLabel(title)
    title_lbl.setStyleSheet(
        f"font-family: 'Roboto Condensed'; font-size: 15px; "
        f"font-weight: bold; color: {accent}; background-color: transparent;"
    )
    layout.addWidget(title_lbl)
    layout.addStretch()
    return container


# ---------------------------------------------------------------------------
# Empty-state placeholder (#7)
# ---------------------------------------------------------------------------


def create_empty_state(message: str, icon: str = "\u25CB") -> QLabel:
    """Return a centered placeholder label for empty tables/panels."""
    lbl = QLabel(f"{icon}  {message}")
    lbl.setObjectName("emptyState")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lbl


# ---------------------------------------------------------------------------
# Animated connection dot (#4)
# ---------------------------------------------------------------------------


class ConnectionDot(QWidget):
    """A small animated dot that pulses green when connected or turns red."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self.setObjectName("connDot")
        self._connected: bool = False
        self._opacity: float = 1.0

        # Pulse animation timer
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse_tick)
        self._pulse_direction = -1
        self._pulse_timer.start(60)

    # -- public API -------------------------------------------------------

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self.update()

    @property
    def connected(self) -> bool:
        return self._connected

    # -- animation ---------------------------------------------------------

    def _pulse_tick(self) -> None:
        if not self._connected:
            self._opacity = 1.0
            self.update()
            return
        self._opacity += self._pulse_direction * 0.04
        if self._opacity <= 0.35:
            self._pulse_direction = 1
        elif self._opacity >= 1.0:
            self._pulse_direction = -1
        self.update()

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._connected:
            color = QColor(164, 214, 94, int(255 * self._opacity))
        else:
            color = QColor(211, 47, 47)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        m = 2
        p.drawEllipse(m, m, self.width() - m * 2, self.height() - m * 2)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(14, 14)
