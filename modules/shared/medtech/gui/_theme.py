"""NiceGUI theming and shared app-shell helpers for medtech-suite."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nicegui import app, ui

from medtech.gui._colors import BRAND_COLORS
from medtech.gui._widgets import ConnectionDot

NICEGUI_QUASAR_CONFIG = {"iconSet": "material-symbols-outlined"}
NICEGUI_STORAGE_SECRET_ENV = "MEDTECH_NICEGUI_STORAGE_SECRET"


def _resource_dir() -> Path:
    env = os.environ.get("MEDTECH_RESOURCE_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    return here.parents[4] / "install" / "share" / "resources"


def _fonts_dir() -> Path:
    return _resource_dir() / "fonts"


def _logo_path() -> Path:
    resources = _resource_dir() / "images"
    for filename in ("rti-logo-white.png", "rti-logo.png", "rti-logo.svg"):
        candidate = resources / filename
        if candidate.is_file():
            return candidate
    return resources / "rti-logo.png"


def _font_face_css(font_family: str, filename: str, *, weight: int = 400) -> str:
    return (
        "@font-face {"
        f"font-family: '{font_family}';"
        f"src: url('/fonts/{filename}') format('truetype');"
        f"font-weight: {weight};"
        "font-style: normal;"
        "font-display: swap;"
        "}"
    )


def _font_css() -> str:
    lines = [
        _font_face_css("Roboto Condensed", "RobotoCondensed.ttf", weight=400),
        _font_face_css("Roboto Condensed", "RobotoCondensed-Italic.ttf", weight=400),
        _font_face_css("Montserrat", "Montserrat.ttf", weight=400),
        _font_face_css("Montserrat", "Montserrat-Italic.ttf", weight=400),
        _font_face_css("Roboto Mono", "RobotoMono.ttf", weight=400),
        _font_face_css("Roboto Mono", "RobotoMono-Italic.ttf", weight=400),
        "body { font-family: 'Roboto Condensed', sans-serif; }",
        ".mono { font-family: 'Roboto Mono', monospace; }",
        ".brand-heading { font-family: 'Montserrat', sans-serif; }",
    ]
    return "<style>" + " ".join(lines) + "</style>"


def init_theme(_app: Any | None = None) -> Any:
    """Apply RTI branding and return the shared header shell."""
    app.colors(
        primary=BRAND_COLORS["blue"],
        secondary=BRAND_COLORS["gray"],
        accent=BRAND_COLORS["orange"],
        positive=BRAND_COLORS["green"],
        negative=BRAND_COLORS["red"],
        info=BRAND_COLORS["light_blue"],
        warning=BRAND_COLORS["orange"],
    )
    app.add_static_files("/fonts", _fonts_dir())
    ui.add_head_html(_font_css(), shared=True)
    return create_header()


def create_header(
    title: str = "Medtech Suite",
    *,
    connected: bool = True,
    show_toggle: bool = True,
) -> Any:
    """Create the reusable header shell with logo, title, toggle, and status dot."""
    header = ui.header(elevated=True).classes(
        "items-center gap-4 px-4 py-2 bg-primary text-white"
    )
    with header:
        ui.image(_logo_path()).classes("h-8 w-auto")
        ui.label(title).classes("text-xl font-bold brand-heading")
        ui.space()
        if show_toggle:
            dark_mode = ui.dark_mode()

            def _sync_theme(event: Any) -> None:
                dark_mode.value = bool(event.value)

            ui.switch("Dark", value=False, on_change=_sync_theme)
        header.connection_dot = ConnectionDot(connected=connected)
    return header
