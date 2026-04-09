"""Brand and semantic color constants for medtech-suite GUI apps.

Color palette and opacity tokens defined by docs/agent/vision/ui-design-system.md.
"""

from __future__ import annotations

BRAND_COLORS = {
    "blue": "#004C97",
    "orange": "#ED8B00",
    "green": "#A4D65E",
    "gray": "#63666A",
    "light_blue": "#00B5E2",
    "red": "#D32F2F",
    "amber": "#FFA726",
    "light_gray": "#BBBCBC",
    "dark_gray": "#2D3139",
}

OPACITY = {
    "overlay_bg": 0.85,
    "shadow": 0.15,
    "selection_glow": 0.18,
    "disabled": 0.40,
    "card_fill": 0.10,
    "card_fill_active": 0.18,
    "tile_fill": 0.16,
}

THEME_PALETTE = {
    "dark": {
        "bg_top": "#0D1B2A",
        "bg_bottom": "#1B2838",
        "grid": "rgba(255,255,255,0.05)",
        "arm": "#C8D2DC",        # rgba(200,210,220,0.78) per ui-design-system.md
        "hud_bg": "rgba(13,27,42,0.85)",
        "hud_label": "#BBBCBC",
        "hud_value": "#00B5E2",
    },
    "light": {
        "bg_top": "#E8EDF2",
        "bg_bottom": "#F7F8FA",
        "grid": "rgba(0,0,0,0.05)",
        "arm": "#505A64",        # rgba(80,90,100,0.78) per ui-design-system.md
        "hud_bg": "rgba(255,255,255,0.85)",
        "hud_label": "#63666A",
        "hud_value": "#004C97",
    },
}

STATUS_COLORS = {
    "RUNNING": ("#E8F5E9", "#2E7D32"),
    "STARTED": ("#E8F5E9", "#2E7D32"),
    "ACTIVE": ("#E8F5E9", "#2E7D32"),
    "OPERATIONAL": ("#E8F5E9", "#2E7D32"),
    "READY": ("#E3F2FD", BRAND_COLORS["blue"]),
    "IDLE": ("#F5F5F5", BRAND_COLORS["gray"]),
    "STOPPED": ("#FFEBEE", "#C62828"),
    "ERROR": ("#FFEBEE", "#C62828"),
    "EMERGENCY_STOP": ("#FFEBEE", "#C62828"),
    "PAUSED": ("#FFF3E0", "#E65100"),
    "WARNING": ("#FFF3E0", "#E65100"),
    "PENDING": ("#FFF3E0", "#E65100"),
    "STARTING": ("#E3F2FD", BRAND_COLORS["blue"]),
    "STOPPING": ("#FFF3E0", "#E65100"),
    "DISCONNECTED": ("#ECEFF1", BRAND_COLORS["gray"]),
    "UNKNOWN": ("#ECEFF1", BRAND_COLORS["gray"]),
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
    "EMERGENCY_STOP": ("#3B1515", "#EF5350"),
    "PAUSED": ("#3B2510", "#FFA726"),
    "WARNING": ("#3B2510", "#FFA726"),
    "PENDING": ("#3B2510", "#FFA726"),
    "STARTING": ("#0D2744", "#42A5F5"),
    "STOPPING": ("#3B2510", "#FFA726"),
    "DISCONNECTED": ("#2D3139", BRAND_COLORS["light_gray"]),
    "UNKNOWN": ("#2D3139", BRAND_COLORS["gray"]),
}
