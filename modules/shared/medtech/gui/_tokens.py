"""Centralized design token system for medtech-suite GUI.

Token values defined by docs/agent/vision/ui-design-system.md § Design Token
Architecture.  All visual values (colors, spacing, radii, shadows, opacities,
transitions, blur) are defined here.  Components reference tokens by name —
never hardcoded hex values, pixel sizes, or timing strings.
"""

from __future__ import annotations

DESIGN_TOKENS: dict[str, dict[str, object]] = {
    "color": {
        "brand": {
            "primary": "#004A8A",
            "accent": "#E68A00",
        },
        "semantic": {
            "success": "#059669",
            "warning": "#D97706",
            "critical": "#DC2626",
            "info": "#0284C7",
        },
        "neutral": {
            "950": "#0F1419",
            "800": "#1E293B",
            "700": "#374151",
            "500": "#6B7280",
            "300": "#D1D5DB",
            "100": "#F1F5F9",
            "50": "#F9FAFB",
        },
    },
    "spacing": {
        "xs": "4px",
        "sm": "8px",
        "md": "12px",
        "lg": "16px",
        "xl": "24px",
        "2xl": "32px",
    },
    "radius": {
        "sm": "4px",
        "md": "8px",
        "lg": "12px",
        "xl": "16px",
        "pill": "9999px",
    },
    "shadow": {
        "sm": "0 1px 3px rgba(0,0,0,0.06)",
        "md": "0 4px 8px rgba(0,0,0,0.08)",
        "lg": "0 8px 24px rgba(0,0,0,0.12)",
    },
    "opacity": {
        "glass_bg": 0.65,
        "shadow": 0.12,
        "selection_glow": 0.18,
        "disabled": 0.40,
        "card_fill": 0.10,
        "card_fill_active": 0.18,
        "tile_fill": 0.16,
    },
    "transition": {
        "fast": "150ms ease-out",
        "default": "200ms cubic-bezier(0.34, 1.56, 0.64, 1)",
        "slow": "300ms ease-out",
    },
    "blur": {
        "glass_dark": "12px",
        "glass_light": "10px",
    },
}
