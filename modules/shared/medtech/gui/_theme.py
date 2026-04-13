"""NiceGUI theming and shared app-shell helpers for medtech-suite."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from medtech.gui._colors import BRAND_COLORS, OPACITY
from medtech.gui._icons import ICONS
from medtech.gui._widgets import ConnectionDot
from nicegui import app, ui

NICEGUI_QUASAR_CONFIG = {"iconSet": "material-icons-outlined"}
NICEGUI_STORAGE_SECRET_ENV = "MEDTECH_NICEGUI_STORAGE_SECRET"
NICEGUI_STORAGE_SECRET_DEFAULT = "medtech-dev-not-for-production"
NICEGUI_THEME_MODE_KEY = "theme_mode"
NICEGUI_THEME_MODES = ("system", "light", "dark")


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
        _font_face_css("Inter", "Inter.ttf", weight=400),
        _font_face_css("Inter", "Inter-Italic.ttf", weight=400),
        _font_face_css("Roboto Condensed", "RobotoCondensed.ttf", weight=400),
        _font_face_css("Roboto Condensed", "RobotoCondensed-Italic.ttf", weight=400),
        _font_face_css("Roboto Mono", "RobotoMono.ttf", weight=400),
        _font_face_css("Roboto Mono", "RobotoMono-Italic.ttf", weight=400),
        "body { font-family: 'Inter', sans-serif; }",
        ".mono { font-family: 'Roboto Mono', monospace; font-weight: 700; }",
        ".brand-heading { font-family: 'Inter', sans-serif; font-weight: 700; }",
    ]
    return "<style>" + " ".join(lines) + "</style>"


def _type_scale_css() -> str:
    """Return CSS classes for the semantic type scale."""
    return (
        "<style>"
        ".type-h1 { font-size: 32px; font-weight: 700; line-height: 1.2; }"
        ".type-h2 { font-size: 24px; font-weight: 700; line-height: 1.3; }"
        ".type-h3 { font-size: 18px; font-weight: 600; line-height: 1.4; }"
        ".type-body-lg { font-size: 16px; font-weight: 500; line-height: 1.5; }"
        ".type-body { font-size: 14px; font-weight: 400; line-height: 1.6; }"
        ".type-body-sm { font-size: 12px; font-weight: 400; line-height: 1.5; }"
        ".type-label { font-size: 12px; font-weight: 600; line-height: 1.4; }"
        ".type-mono { font-family: 'Roboto Mono', monospace; font-size: 13px; font-weight: 700; }"
        ".type-mono-sm { font-family: 'Roboto Mono', monospace; font-size: 11px; font-weight: 400; }"
        "</style>"
    )


def _glassmorphism_css() -> str:
    """Return CSS custom properties and the ``.glass-panel`` utility class.

    Dark and light mode each get their own ``--glass-bg``, ``--glass-border``,
    and ``--glass-blur`` custom properties.  The ``.glass-panel`` class applies
    the translucent backdrop-blur effect with a 16 px radius.
    """
    return (
        "<style>"
        # Dark-mode custom properties
        "body.dark {"
        "  --glass-bg: rgba(13,27,42,0.65);"
        "  --glass-border: rgba(255,255,255,0.12);"
        "  --glass-blur: 12px;"
        "}"
        # Light-mode custom properties (also default)
        "body:not(.dark) {"
        "  --glass-bg: rgba(255,255,255,0.65);"
        "  --glass-border: rgba(0,0,0,0.06);"
        "  --glass-blur: 10px;"
        "}"
        # Utility class
        ".glass-panel {"
        "  background: var(--glass-bg);"
        "  backdrop-filter: blur(var(--glass-blur));"
        "  -webkit-backdrop-filter: blur(var(--glass-blur));"
        "  border: 1px solid var(--glass-border);"
        "  border-radius: 16px;"
        "  box-shadow: 0 8px 32px rgba(0,0,0,0.12);"
        "}"
        # Graceful degradation — no backdrop-filter → opaque fallback
        "@supports not (backdrop-filter: blur(1px)) {"
        "  body.dark .glass-panel { background: rgba(13,27,42,0.92); }"
        "  body:not(.dark) .glass-panel { background: rgba(255,255,255,0.92); }"
        "}"
        "</style>"
    )


def _theme_mode_value(mode: str | None) -> bool | None:
    if mode == "light":
        return False
    if mode == "dark":
        return True
    return None


def _theme_mode_label(mode: str | None) -> str:
    normalized = mode if mode in NICEGUI_THEME_MODES else "system"
    return normalized.capitalize()


def init_theme(_app: Any | None = None, *, title: str = "Medtech Suite") -> Any:
    """Apply RTI branding and return the shared header shell."""
    app.config.quasar_config.update(NICEGUI_QUASAR_CONFIG)
    app.colors(
        primary=BRAND_COLORS["blue"],
        secondary=BRAND_COLORS["gray"],
        accent=BRAND_COLORS["orange"],
        positive=BRAND_COLORS["green"],
        negative=BRAND_COLORS["red"],
        info=BRAND_COLORS["light_blue"],
        warning=BRAND_COLORS["amber"],
    )
    app.add_static_files("/fonts", _fonts_dir())
    app.add_static_files("/images", _resource_dir() / "images")
    ui.add_head_html(
        '<link rel="icon" type="image/x-icon" href="/images/favicon.ico">',
        shared=True,
    )
    ui.add_head_html(_font_css(), shared=True)
    ui.add_head_html(_type_scale_css(), shared=True)
    ui.add_head_html(_glassmorphism_css(), shared=True)
    ui.add_head_html(
        "<style>"
        "body { transition: background-color 0.3s ease, color 0.3s ease; }"
        "</style>",
        shared=True,
    )
    return create_header(title=title)


def create_header(
    title: str = "Medtech Suite",
    *,
    connected: bool = True,
    show_toggle: bool = True,
) -> Any:
    """Create the reusable header shell with logo, title, toggle, and status dot."""
    header = (
        ui.header()
        .classes("items-center gap-4 px-4 py-3 bg-primary text-white")
        .style(f"box-shadow: 0 4px 12px rgba(0,0,0,{OPACITY['shadow']});")
    )
    with header:
        logo = _logo_path()
        ui.html(
            f'<img src="/images/{logo.name}" style="height: 2rem; width: auto;" alt="RTI">'
        )
        ui.label(title).classes("text-2xl font-bold brand-heading")
        ui.space()
        if show_toggle:
            stored_mode = app.storage.user.get(NICEGUI_THEME_MODE_KEY, "system")
            dark_mode = ui.dark_mode(_theme_mode_value(stored_mode))

            def _cycle_to(new_value: bool | None) -> None:
                dark_mode.set_value(new_value)
                if new_value is True:
                    mode = "dark"
                elif new_value is False:
                    mode = "light"
                else:
                    mode = "system"
                app.storage.user[NICEGUI_THEME_MODE_KEY] = mode

            with ui.button(on_click=lambda: _cycle_to(None)).props(
                "flat round"
            ).classes("text-white").bind_visibility_from(
                dark_mode, "value", value=True
            ):
                ui.icon(ICONS["dark_mode"]).classes("text-xl")
            with ui.button(on_click=lambda: _cycle_to(True)).props(
                "flat round"
            ).classes("text-white").bind_visibility_from(
                dark_mode, "value", value=False
            ):
                ui.icon(ICONS["light_mode"]).classes("text-xl")
            with ui.button(on_click=lambda: _cycle_to(False)).props(
                "flat round"
            ).classes("text-white").bind_visibility_from(
                dark_mode, "value", backward=lambda v: v is None
            ):
                ui.icon(ICONS["auto_mode"]).classes("text-xl")
        header.connection_dot = ConnectionDot(connected=connected)
    return header
