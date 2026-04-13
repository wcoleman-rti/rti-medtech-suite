"""Tests for the design token system — Step M.1 test gate.

Covers:
- DESIGN_TOKENS importable and contains all required keys
- BRAND_COLORS values match updated token palette
- OPACITY values align with token values
- THEME_PALETTE includes new tokens (surface, hud-border, glass-blur)
- Backward compatibility: existing color references still resolve

Spec: hospital-dashboard.md, surgical-procedure.md — @ui-modernization
Tags: @gui @unit @ui-modernization
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.gui, pytest.mark.unit]


class TestDesignTokens:
    """DESIGN_TOKENS dict contains all required keys and values."""

    def test_importable(self) -> None:
        from medtech.gui._tokens import DESIGN_TOKENS

        assert isinstance(DESIGN_TOKENS, dict)

    def test_top_level_keys(self) -> None:
        from medtech.gui._tokens import DESIGN_TOKENS

        expected = {
            "color",
            "spacing",
            "radius",
            "shadow",
            "opacity",
            "transition",
            "blur",
        }
        assert expected == set(DESIGN_TOKENS.keys())

    def test_color_brand_keys(self) -> None:
        from medtech.gui._tokens import DESIGN_TOKENS

        brand = DESIGN_TOKENS["color"]["brand"]  # type: ignore[index]
        assert brand["primary"] == "#004A8A"
        assert brand["accent"] == "#E68A00"

    def test_color_semantic_keys(self) -> None:
        from medtech.gui._tokens import DESIGN_TOKENS

        semantic = DESIGN_TOKENS["color"]["semantic"]  # type: ignore[index]
        assert semantic["success"] == "#059669"
        assert semantic["warning"] == "#D97706"
        assert semantic["critical"] == "#DC2626"
        assert semantic["info"] == "#0284C7"

    def test_color_neutral_scale(self) -> None:
        from medtech.gui._tokens import DESIGN_TOKENS

        neutral = DESIGN_TOKENS["color"]["neutral"]  # type: ignore[index]
        assert "950" in neutral
        assert "800" in neutral
        assert "700" in neutral
        assert "500" in neutral
        assert "300" in neutral
        assert "100" in neutral
        assert "50" in neutral

    def test_spacing_keys(self) -> None:
        from medtech.gui._tokens import DESIGN_TOKENS

        spacing = DESIGN_TOKENS["spacing"]
        for key in ("xs", "sm", "md", "lg", "xl", "2xl"):
            assert key in spacing

    def test_radius_keys(self) -> None:
        from medtech.gui._tokens import DESIGN_TOKENS

        radius = DESIGN_TOKENS["radius"]
        for key in ("sm", "md", "lg", "xl", "pill"):
            assert key in radius

    def test_shadow_keys(self) -> None:
        from medtech.gui._tokens import DESIGN_TOKENS

        shadow = DESIGN_TOKENS["shadow"]
        for key in ("sm", "md", "lg"):
            assert key in shadow

    def test_opacity_glass_bg(self) -> None:
        from medtech.gui._tokens import DESIGN_TOKENS

        assert DESIGN_TOKENS["opacity"]["glass_bg"] == 0.65  # type: ignore[index]

    def test_opacity_shadow(self) -> None:
        from medtech.gui._tokens import DESIGN_TOKENS

        assert DESIGN_TOKENS["opacity"]["shadow"] == 0.12  # type: ignore[index]

    def test_transition_keys(self) -> None:
        from medtech.gui._tokens import DESIGN_TOKENS

        transition = DESIGN_TOKENS["transition"]
        for key in ("fast", "default", "slow"):
            assert key in transition

    def test_blur_keys(self) -> None:
        from medtech.gui._tokens import DESIGN_TOKENS

        blur = DESIGN_TOKENS["blur"]
        assert blur["glass_dark"] == "12px"
        assert blur["glass_light"] == "10px"

    def test_exported_from_gui_init(self) -> None:
        from medtech.gui import DESIGN_TOKENS

        assert isinstance(DESIGN_TOKENS, dict)
        assert "color" in DESIGN_TOKENS


class TestBrandColorsTokenAlignment:
    """BRAND_COLORS values match updated token palette."""

    def test_blue_is_brand_primary(self) -> None:
        from medtech.gui._colors import BRAND_COLORS
        from medtech.gui._tokens import DESIGN_TOKENS

        assert BRAND_COLORS["blue"] == DESIGN_TOKENS["color"]["brand"]["primary"]  # type: ignore[index]

    def test_orange_is_brand_accent(self) -> None:
        from medtech.gui._colors import BRAND_COLORS
        from medtech.gui._tokens import DESIGN_TOKENS

        assert BRAND_COLORS["orange"] == DESIGN_TOKENS["color"]["brand"]["accent"]  # type: ignore[index]

    def test_green_is_semantic_success(self) -> None:
        from medtech.gui._colors import BRAND_COLORS
        from medtech.gui._tokens import DESIGN_TOKENS

        assert BRAND_COLORS["green"] == DESIGN_TOKENS["color"]["semantic"]["success"]  # type: ignore[index]

    def test_red_is_semantic_critical(self) -> None:
        from medtech.gui._colors import BRAND_COLORS
        from medtech.gui._tokens import DESIGN_TOKENS

        assert BRAND_COLORS["red"] == DESIGN_TOKENS["color"]["semantic"]["critical"]  # type: ignore[index]

    def test_amber_is_semantic_warning(self) -> None:
        from medtech.gui._colors import BRAND_COLORS
        from medtech.gui._tokens import DESIGN_TOKENS

        assert BRAND_COLORS["amber"] == DESIGN_TOKENS["color"]["semantic"]["warning"]  # type: ignore[index]

    def test_dark_gray_is_neutral_800(self) -> None:
        from medtech.gui._colors import BRAND_COLORS
        from medtech.gui._tokens import DESIGN_TOKENS

        assert BRAND_COLORS["dark_gray"] == DESIGN_TOKENS["color"]["neutral"]["800"]  # type: ignore[index]

    def test_gray_unchanged(self) -> None:
        from medtech.gui._colors import BRAND_COLORS

        assert BRAND_COLORS["gray"] == "#63666A"

    def test_light_blue_unchanged(self) -> None:
        from medtech.gui._colors import BRAND_COLORS

        assert BRAND_COLORS["light_blue"] == "#00B5E2"

    def test_light_gray_unchanged(self) -> None:
        from medtech.gui._colors import BRAND_COLORS

        assert BRAND_COLORS["light_gray"] == "#BBBCBC"


class TestOpacityTokenAlignment:
    """OPACITY values align with token values."""

    def test_overlay_bg_is_glass_bg(self) -> None:
        from medtech.gui._colors import OPACITY

        assert OPACITY["overlay_bg"] == 0.65

    def test_shadow_is_token_shadow(self) -> None:
        from medtech.gui._colors import OPACITY

        assert OPACITY["shadow"] == 0.12


class TestThemePaletteTokenAlignment:
    """THEME_PALETTE includes new tokens (surface, hud-border, glass-blur)."""

    def test_dark_has_surface(self) -> None:
        from medtech.gui._colors import THEME_PALETTE

        assert "surface" in THEME_PALETTE["dark"]

    def test_light_has_surface(self) -> None:
        from medtech.gui._colors import THEME_PALETTE

        assert "surface" in THEME_PALETTE["light"]

    def test_dark_has_hud_border(self) -> None:
        from medtech.gui._colors import THEME_PALETTE

        assert "hud_border" in THEME_PALETTE["dark"]

    def test_light_has_hud_border(self) -> None:
        from medtech.gui._colors import THEME_PALETTE

        assert "hud_border" in THEME_PALETTE["light"]

    def test_dark_has_glass_blur(self) -> None:
        from medtech.gui._colors import THEME_PALETTE

        assert THEME_PALETTE["dark"]["glass_blur"] == "12px"

    def test_light_has_glass_blur(self) -> None:
        from medtech.gui._colors import THEME_PALETTE

        assert THEME_PALETTE["light"]["glass_blur"] == "10px"

    def test_dark_hud_bg_opacity_065(self) -> None:
        from medtech.gui._colors import THEME_PALETTE

        assert "0.65" in THEME_PALETTE["dark"]["hud_bg"]

    def test_light_hud_bg_opacity_065(self) -> None:
        from medtech.gui._colors import THEME_PALETTE

        assert "0.65" in THEME_PALETTE["light"]["hud_bg"]
