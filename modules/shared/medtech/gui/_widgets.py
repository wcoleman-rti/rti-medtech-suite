"""Reusable NiceGUI widget helpers for medtech-suite applications."""

from __future__ import annotations

from typing import Any

from medtech.gui._colors import BRAND_COLORS, OPACITY, STATUS_COLORS, STATUS_COLORS_DARK
from medtech.gui._icons import ICONS
from nicegui import ui

# Mapping from status text to Material Icons Outlined name.
_STATUS_ICONS: dict[str, str] = {
    "OPERATIONAL": "check_circle",
    "RUNNING": "check_circle",
    "STARTED": "check_circle",
    "ACTIVE": "check_circle",
    "READY": "radio_button_checked",
    "E-STOP": "stop_circle",
    "EMERGENCY_STOP": "stop_circle",
    "STOPPED": "stop_circle",
    "ERROR": "error",
    "PAUSED": "pause_circle",
    "IDLE": "remove_circle_outline",
    "DISCONNECTED": "wifi_off",
    "UNKNOWN": "help_outline",
}


def _state_colors(state_text: str, *, dark: bool = False) -> tuple[str, str]:
    palette = STATUS_COLORS_DARK if dark else STATUS_COLORS
    return palette.get(state_text.upper(), palette["UNKNOWN"])


def _status_icon(state_text: str) -> str:
    """Return the Material icon name for a given status text."""
    return _STATUS_ICONS.get(state_text.upper(), "help_outline")


def create_status_chip(state_text: str, *, dark: bool = False) -> Any:
    """Return a colored NiceGUI chip for a status label with icon prefix."""
    bg, fg = _state_colors(state_text, dark=dark)
    chip = ui.chip(state_text, color=bg, text_color=fg, icon=_status_icon(state_text))
    chip.classes("font-semibold")
    chip.style("border-radius: 12px;")
    return chip


def create_stat_card(
    value: Any,
    label: str,
    icon: str = "",
    color: str = BRAND_COLORS["blue"],
    *,
    glass: bool = False,
) -> Any:
    """Return a KPI card with a value label and optional icon."""
    card = ui.card().classes("w-full p-4 rounded-lg")
    if glass:
        card.classes("glass-panel")
    card.style(
        f"border-left: 4px solid {color};"
        f" box-shadow: 0 2px 8px rgba(0,0,0,{OPACITY['shadow']});"
    )
    with card:
        with ui.row(align_items="center").classes("w-full gap-3"):
            if icon:
                ui.icon(icon, color=color).classes("text-2xl")
            with ui.column(align_items="start").classes("gap-0"):
                value_label = ui.label(str(value)).classes("text-2xl font-bold")
                value_label.style(f"color: {color};")
                ui.label(label).classes("text-sm text-gray-500")
    card.value_label = value_label
    return card


def create_section_header(text: str, icon: str = "") -> Any:
    """Return a labeled row for section headings."""
    row = ui.row(align_items="center").classes("gap-2 w-full")
    with row:
        if icon:
            ui.icon(icon, color=BRAND_COLORS["blue"]).classes("text-xl")
        ui.label(text).classes("text-lg font-bold brand-heading")
    return row


def create_empty_state(text: str, icon: str = ICONS["empty_state"]) -> Any:
    """Return a centered empty-state column with icon and text."""
    column = ui.column(align_items="center").classes("w-full gap-2 text-center")
    with column:
        ui.icon(icon, color=BRAND_COLORS["gray"]).classes("text-4xl")
        ui.label(text).classes("text-sm text-gray-500")
    return column


def create_skeleton_card(*, height: str = "80px") -> Any:
    """Return a card with shimmer animation as a loading placeholder."""
    card = ui.card().classes("w-full rounded-lg skeleton-shimmer")
    card.style(f"height: {height}; overflow: hidden;")
    return card


def ConnectionDot(connected: bool = True) -> Any:
    """Return a pulsing connection indicator."""
    dot = ui.icon(ICONS["connection"]).classes("text-lg transition-all")
    state = {"pulse": True}

    def _apply() -> None:
        if connected:
            state["pulse"] = not state["pulse"]
            opacity = "1.0" if state["pulse"] else "0.55"
            dot.style(
                f"color: {BRAND_COLORS['green']}; opacity: {opacity}; transform: scale({1.0 if state['pulse'] else 0.92});"
            )
        else:
            dot.style(f"color: {BRAND_COLORS['gray']}; opacity: 1.0;")

    _apply()
    ui.timer(0.6, _apply, active=True)
    return dot
