"""Brand and semantic color constants for medtech-suite GUI apps.

Color palette and opacity tokens defined by docs/agent/vision/ui-design-system.md.
Values are derived from the centralized design token system in ``_tokens.py``.
"""

from __future__ import annotations

from medtech.gui._tokens import DESIGN_TOKENS

_brand = DESIGN_TOKENS["color"]["brand"]  # type: ignore[index]
_semantic = DESIGN_TOKENS["color"]["semantic"]  # type: ignore[index]
_neutral = DESIGN_TOKENS["color"]["neutral"]  # type: ignore[index]
_opacity = DESIGN_TOKENS["opacity"]

BRAND_COLORS = {
    "blue": _brand["primary"],
    "orange": _brand["accent"],
    "green": _semantic["success"],
    "gray": "#63666A",
    "light_blue": "#00B5E2",
    "red": _semantic["critical"],
    "amber": _semantic["warning"],
    "light_gray": "#BBBCBC",
    "dark_gray": _neutral["800"],
}

OPACITY = {
    "overlay_bg": _opacity["glass_bg"],
    "shadow": _opacity["shadow"],
    "selection_glow": _opacity["selection_glow"],
    "disabled": _opacity["disabled"],
    "card_fill": _opacity["card_fill"],
    "card_fill_active": _opacity["card_fill_active"],
    "tile_fill": _opacity["tile_fill"],
}

THEME_PALETTE = {
    "dark": {
        "bg_top": "#0D1B2A",
        "bg_bottom": "#1B2838",
        "surface": _neutral["800"],
        "grid": "rgba(255,255,255,0.05)",
        "arm": "#C8D2DC",
        "hud_bg": "rgba(13,27,42,0.65)",
        "hud_border": "rgba(255,255,255,0.12)",
        "hud_label": "#BBBCBC",
        "hud_value": "#00B5E2",
        "glass_blur": "12px",
    },
    "light": {
        "bg_top": "#F1F5F9",
        "bg_bottom": "#F9FAFB",
        "surface": "#FFFFFF",
        "grid": "rgba(0,0,0,0.05)",
        "arm": "#505A64",
        "hud_bg": "rgba(255,255,255,0.65)",
        "hud_border": "rgba(0,0,0,0.06)",
        "hud_label": _neutral["500"],
        "hud_value": _brand["primary"],
        "glass_blur": "10px",
    },
}

STATUS_COLORS = {
    "RUNNING": ("#E8F5E9", _semantic["success"]),
    "STARTED": ("#E8F5E9", _semantic["success"]),
    "ACTIVE": ("#E8F5E9", _semantic["success"]),
    "OPERATIONAL": ("#E8F5E9", _semantic["success"]),
    "READY": ("#E3F2FD", _brand["primary"]),
    "IDLE": ("#F5F5F5", "#63666A"),
    "STOPPED": ("#FFEBEE", _semantic["critical"]),
    "ERROR": ("#FFEBEE", _semantic["critical"]),
    "E-STOP": ("#FFEBEE", _semantic["critical"]),
    "EMERGENCY_STOP": ("#FFEBEE", _semantic["critical"]),
    "PAUSED": ("#FFF3E0", _semantic["warning"]),
    "WARNING": ("#FFF3E0", _semantic["warning"]),
    "PENDING": ("#FFF3E0", _semantic["warning"]),
    "STARTING": ("#E3F2FD", _semantic["info"]),
    "STOPPING": ("#FFF3E0", _semantic["warning"]),
    "DISCONNECTED": ("#ECEFF1", _neutral["500"]),
    "UNKNOWN": ("#ECEFF1", _neutral["500"]),
}

STATUS_COLORS_DARK = {
    "RUNNING": ("#1B3A26", "#66BB6A"),
    "STARTED": ("#1B3A26", "#66BB6A"),
    "ACTIVE": ("#1B3A26", "#66BB6A"),
    "OPERATIONAL": ("#1B3A26", "#66BB6A"),
    "READY": ("#0D2744", "#42A5F5"),
    "IDLE": ("#2D3139", "#BBBCBC"),
    "STOPPED": ("#3B1515", "#EF5350"),
    "ERROR": ("#3B1515", "#EF5350"),
    "E-STOP": ("#3B1515", "#EF5350"),
    "EMERGENCY_STOP": ("#3B1515", "#EF5350"),
    "PAUSED": ("#3B2510", "#FFA726"),
    "WARNING": ("#3B2510", "#FFA726"),
    "PENDING": ("#3B2510", "#FFA726"),
    "STARTING": ("#0D2744", "#42A5F5"),
    "STOPPING": ("#3B2510", "#FFA726"),
    "DISCONNECTED": ("#2D3139", BRAND_COLORS["light_gray"]),
    "UNKNOWN": ("#2D3139", _neutral["500"]),
}
