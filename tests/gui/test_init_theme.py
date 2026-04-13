"""Tests for medtech.gui NiceGUI helpers — Step N.2 test gate.

Tags: @gui @unit
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from medtech.gui import BRAND_COLORS, ICONS, NICEGUI_QUASAR_CONFIG
from medtech.gui import _theme as theme_module
from medtech.gui import _widgets as widgets_module
from medtech.gui._backend import GuiBackend
from medtech.gui._colors import STATUS_COLORS, STATUS_COLORS_DARK

pytestmark = [pytest.mark.gui, pytest.mark.unit]


@dataclass
class FakeElement:
    kind: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    styles: list[str] = field(default_factory=list)
    class_calls: list[tuple[Any, ...]] = field(default_factory=list)
    props_calls: list[str] = field(default_factory=list)
    events: list[tuple[str, Any]] = field(default_factory=list)
    value: Any = None

    def __enter__(self) -> "FakeElement":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def classes(self, *args: Any, **kwargs: Any) -> "FakeElement":
        self.class_calls.append(args)
        return self

    def style(self, value: str) -> "FakeElement":
        self.styles.append(value)
        return self

    def props(self, value: str) -> "FakeElement":
        self.props_calls.append(value)
        return self

    def bind_value(self, *args: Any, **kwargs: Any) -> "FakeElement":
        self.events.append(("bind_value", args))
        return self

    def on(self, event_name: str, handler: Any) -> "FakeElement":
        self.events.append((event_name, handler))
        return self

    def bind_visibility_from(self, *args: Any, **kwargs: Any) -> "FakeElement":
        return self

    def set_value(self, value: Any) -> None:
        self.value = value


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any], FakeElement]] = []

    def record(self, kind: str, *args: Any, **kwargs: Any) -> FakeElement:
        element = FakeElement(
            kind=kind, args=args, kwargs=kwargs, value=kwargs.get("value")
        )
        self.calls.append((kind, args, kwargs, element))
        return element


def _patch_theme_ui(monkeypatch: pytest.MonkeyPatch, recorder: Recorder) -> None:
    monkeypatch.setattr(
        theme_module.app,
        "colors",
        lambda **kwargs: recorder.record("colors", **kwargs),
    )
    monkeypatch.setattr(
        theme_module.app,
        "add_static_files",
        lambda url_path, local_directory, **kwargs: recorder.record(
            "add_static_files", url_path, local_directory, **kwargs
        ),
    )
    monkeypatch.setattr(
        theme_module.ui,
        "add_head_html",
        lambda code, *, shared=False: recorder.record(
            "add_head_html", code, shared=shared
        ),
    )
    monkeypatch.setattr(
        theme_module.ui,
        "header",
        lambda *args, **kwargs: recorder.record("header", *args, **kwargs),
    )
    monkeypatch.setattr(
        theme_module.ui,
        "image",
        lambda *args, **kwargs: recorder.record("image", *args, **kwargs),
    )
    monkeypatch.setattr(
        theme_module.ui,
        "html",
        lambda *args, **kwargs: recorder.record("html", *args, **kwargs),
    )
    monkeypatch.setattr(
        theme_module.ui,
        "label",
        lambda *args, **kwargs: recorder.record("label", *args, **kwargs),
    )
    monkeypatch.setattr(
        theme_module.ui,
        "space",
        lambda *args, **kwargs: recorder.record("space", *args, **kwargs),
    )
    monkeypatch.setattr(
        theme_module.ui,
        "dark_mode",
        lambda *args, **kwargs: recorder.record("dark_mode", *args, **kwargs),
    )
    monkeypatch.setattr(
        theme_module.ui,
        "button",
        lambda *args, **kwargs: recorder.record("button", *args, **kwargs),
    )
    monkeypatch.setattr(
        theme_module.ui,
        "icon",
        lambda *args, **kwargs: recorder.record("icon", *args, **kwargs),
    )


def _patch_widget_ui(monkeypatch: pytest.MonkeyPatch, recorder: Recorder) -> None:
    monkeypatch.setattr(
        widgets_module.ui,
        "chip",
        lambda *args, **kwargs: recorder.record("chip", *args, **kwargs),
    )
    monkeypatch.setattr(
        widgets_module.ui,
        "card",
        lambda *args, **kwargs: recorder.record("card", *args, **kwargs),
    )
    monkeypatch.setattr(
        widgets_module.ui,
        "row",
        lambda *args, **kwargs: recorder.record("row", *args, **kwargs),
    )
    monkeypatch.setattr(
        widgets_module.ui,
        "column",
        lambda *args, **kwargs: recorder.record("column", *args, **kwargs),
    )
    monkeypatch.setattr(
        widgets_module.ui,
        "icon",
        lambda *args, **kwargs: recorder.record("icon", *args, **kwargs),
    )
    monkeypatch.setattr(
        widgets_module.ui,
        "label",
        lambda *args, **kwargs: recorder.record("label", *args, **kwargs),
    )
    monkeypatch.setattr(
        widgets_module.ui,
        "timer",
        lambda interval, callback, *, active=True, once=False, immediate=True: recorder.record(
            "timer", interval, callback, active=active, once=once, immediate=immediate
        ),
    )


class TestGuiBackend:
    def test_abc_requires_all_members(self):
        with pytest.raises(TypeError):
            GuiBackend()

    def test_hooks_register_on_construction(self, monkeypatch: pytest.MonkeyPatch):
        startups: list[Any] = []
        shutdowns: list[Any] = []
        monkeypatch.setattr(theme_module.app, "on_startup", startups.append)
        monkeypatch.setattr(theme_module.app, "on_shutdown", shutdowns.append)

        class DemoBackend(GuiBackend):
            @property
            def name(self) -> str:
                return "demo"

            async def start(self) -> None:
                return None

            def close(self) -> None:
                return None

        backend = DemoBackend()

        assert len(startups) == 1
        assert len(shutdowns) == 1
        assert startups[0].__self__ is backend
        assert shutdowns[0].__self__ is backend
        assert backend.name == "demo"


class TestThemeInitialization:
    def test_init_theme_applies_brand_palette_and_static_fonts(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        recorder = Recorder()
        _patch_theme_ui(monkeypatch, recorder)
        monkeypatch.setattr(theme_module, "_fonts_dir", lambda: Path("/tmp/fonts"))
        header = FakeElement("header")
        monkeypatch.setattr(theme_module, "create_header", lambda **kwargs: header)

        result = theme_module.init_theme()

        assert result is header
        colors_call = next(call for call in recorder.calls if call[0] == "colors")
        assert colors_call[2]["primary"] == BRAND_COLORS["blue"]
        assert colors_call[2]["accent"] == BRAND_COLORS["orange"]
        assert colors_call[2]["positive"] == BRAND_COLORS["green"]
        assert colors_call[2]["negative"] == BRAND_COLORS["red"]

        static_call = next(
            call for call in recorder.calls if call[0] == "add_static_files"
        )
        assert static_call[1][0] == "/fonts"
        assert static_call[1][1] == Path("/tmp/fonts")

        head_calls = [call for call in recorder.calls if call[0] == "add_head_html"]
        font_call = next(c for c in head_calls if "@font-face" in c[1][0])
        assert font_call[2]["shared"] is True

    def test_header_shell_includes_branding(self, monkeypatch: pytest.MonkeyPatch):
        recorder = Recorder()
        _patch_theme_ui(monkeypatch, recorder)
        monkeypatch.setattr(
            theme_module, "_logo_path", lambda: Path("/tmp/rti-logo.png")
        )
        monkeypatch.setattr(
            theme_module,
            "ConnectionDot",
            lambda *, connected=True: recorder.record(
                "connection_dot", connected=connected
            ),
        )

        class _FakeStorage:
            user = {"theme_mode": "system"}

        monkeypatch.setattr(theme_module.app, "storage", _FakeStorage())

        header = theme_module.create_header(title="Hospital Dashboard", connected=False)

        assert header.kind == "header"
        assert header.connection_dot.kind == "connection_dot"
        assert any(
            call[0] == "html" and "rti-logo.png" in call[1][0]
            for call in recorder.calls
        )
        assert any(
            call[0] == "label" and call[1][0] == "Hospital Dashboard"
            for call in recorder.calls
        )
        assert any(call[0] == "button" for call in recorder.calls)


class TestWidgetHelpers:
    def test_status_chip_uses_palette(self, monkeypatch: pytest.MonkeyPatch):
        recorder = Recorder()
        _patch_widget_ui(monkeypatch, recorder)

        chip = widgets_module.create_status_chip("running")

        assert chip.kind == "chip"
        assert chip.kwargs["color"] == STATUS_COLORS["RUNNING"][0]
        assert chip.kwargs["text_color"] == STATUS_COLORS["RUNNING"][1]

    def test_status_chip_supports_dark_palette(self, monkeypatch: pytest.MonkeyPatch):
        recorder = Recorder()
        _patch_widget_ui(monkeypatch, recorder)

        chip = widgets_module.create_status_chip("stopped", dark=True)

        assert chip.kwargs["color"] == STATUS_COLORS_DARK["STOPPED"][0]
        assert chip.kwargs["text_color"] == STATUS_COLORS_DARK["STOPPED"][1]

    def test_stat_card_builds_card_with_bound_value_label(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        recorder = Recorder()
        _patch_widget_ui(monkeypatch, recorder)

        card = widgets_module.create_stat_card(
            7, "Hosts Online", ICONS["dashboard"], BRAND_COLORS["blue"]
        )

        assert card.kind == "card"
        assert any("border-left" in style for style in card.styles)
        assert card.value_label.kind == "label"
        assert card.value_label.args[0] == "7"
        assert any(call[0] == "icon" for call in recorder.calls)

    def test_section_header_and_empty_state(self, monkeypatch: pytest.MonkeyPatch):
        recorder = Recorder()
        _patch_widget_ui(monkeypatch, recorder)

        header = widgets_module.create_section_header("Vitals", ICONS["vitals"])
        empty = widgets_module.create_empty_state("No data")

        assert header.kind == "row"
        assert empty.kind == "column"
        assert any(
            call[0] == "label" and call[1][0] == "Vitals" for call in recorder.calls
        )
        assert any(
            call[0] == "label" and call[1][0] == "No data" for call in recorder.calls
        )

    def test_connection_dot_uses_timer(self, monkeypatch: pytest.MonkeyPatch):
        recorder = Recorder()
        _patch_widget_ui(monkeypatch, recorder)

        dot = widgets_module.ConnectionDot(False)

        assert dot.kind == "icon"
        assert any(call[0] == "timer" for call in recorder.calls)


class TestConstants:
    def test_quasar_icon_set_constant(self):
        assert NICEGUI_QUASAR_CONFIG["iconSet"] == "material-icons-outlined"


# ---------------------------------------------------------------------------
# Inter font integration tests (@ui-modernization Step M.2)
# ---------------------------------------------------------------------------


class TestInterFont:
    """Inter font loads from local static files; semantic type scale defined."""

    def test_font_css_includes_inter(self):
        """_font_css() includes @font-face declaration for Inter."""
        css = theme_module._font_css()
        assert "'Inter'" in css

    def test_font_css_body_uses_inter(self):
        """Body font-family is Inter, not Roboto Condensed."""
        css = theme_module._font_css()
        assert "body { font-family: 'Inter'" in css

    def test_font_css_brand_heading_uses_inter(self):
        """Brand heading uses Inter."""
        css = theme_module._font_css()
        assert ".brand-heading { font-family: 'Inter'" in css

    def test_font_css_still_includes_roboto_mono(self):
        """Roboto Mono is still available for .mono class."""
        css = theme_module._font_css()
        assert "'Roboto Mono'" in css
        assert ".mono { font-family: 'Roboto Mono'" in css

    def test_font_css_retains_roboto_condensed(self):
        """Roboto Condensed font-face is retained for backward compatibility."""
        css = theme_module._font_css()
        assert "'Roboto Condensed'" in css

    def test_type_scale_css_has_all_classes(self):
        """_type_scale_css() defines all semantic type scale classes."""
        css = theme_module._type_scale_css()
        for cls in (
            ".type-h1",
            ".type-h2",
            ".type-h3",
            ".type-body-lg",
            ".type-body",
            ".type-body-sm",
            ".type-label",
            ".type-mono",
            ".type-mono-sm",
        ):
            assert cls in css, f"Missing type scale class: {cls}"

    def test_type_h1_specs(self):
        """type-h1 is 32px bold."""
        css = theme_module._type_scale_css()
        assert "font-size: 32px" in css
        assert "font-weight: 700" in css

    def test_type_mono_uses_roboto_mono(self):
        """type-mono uses Roboto Mono font family."""
        css = theme_module._type_scale_css()
        assert ".type-mono { font-family: 'Roboto Mono'" in css

    def test_init_theme_injects_type_scale(self, monkeypatch: pytest.MonkeyPatch):
        """init_theme() injects type scale CSS into head HTML."""
        recorder = Recorder()
        _patch_theme_ui(monkeypatch, recorder)
        monkeypatch.setattr(theme_module, "_fonts_dir", lambda: Path("/tmp/fonts"))
        monkeypatch.setattr(
            theme_module, "create_header", lambda **kw: FakeElement("header")
        )

        theme_module.init_theme()

        head_calls = [call for call in recorder.calls if call[0] == "add_head_html"]
        type_scale_injected = any(
            ".type-h1" in c[1][0] for c in head_calls if len(c[1]) > 0
        )
        assert type_scale_injected, "init_theme() must inject type scale CSS"


# ---------------------------------------------------------------------------
# Glassmorphism overlay tests (@ui-modernization Step M.3)
# ---------------------------------------------------------------------------


class TestGlassmorphism:
    """Glassmorphism CSS custom properties and .glass-panel utility class."""

    def test_glass_panel_class_defined(self):
        """_glassmorphism_css() defines the .glass-panel class."""
        css = theme_module._glassmorphism_css()
        assert ".glass-panel" in css

    def test_glass_panel_backdrop_filter(self):
        """Glass panel uses backdrop-filter: blur()."""
        css = theme_module._glassmorphism_css()
        assert "backdrop-filter: blur(var(--glass-blur))" in css

    def test_glass_panel_webkit_prefix(self):
        """-webkit-backdrop-filter is included for Safari."""
        css = theme_module._glassmorphism_css()
        assert "-webkit-backdrop-filter: blur(var(--glass-blur))" in css

    def test_glass_panel_border_radius_16(self):
        """Glass panels have 16px border radius."""
        css = theme_module._glassmorphism_css()
        assert "border-radius: 16px" in css

    def test_glass_panel_translucent_border(self):
        """Glass panel border uses custom property."""
        css = theme_module._glassmorphism_css()
        assert "border: 1px solid var(--glass-border)" in css

    def test_dark_mode_custom_properties(self):
        """Dark mode sets --glass-bg with dark translucent color."""
        css = theme_module._glassmorphism_css()
        assert "--glass-bg: rgba(13,27,42,0.65)" in css

    def test_light_mode_custom_properties(self):
        """Light mode sets --glass-bg with white translucent color."""
        css = theme_module._glassmorphism_css()
        assert "--glass-bg: rgba(255,255,255,0.65)" in css

    def test_dark_blur_12px(self):
        """Dark mode glass blur is 12px."""
        css = theme_module._glassmorphism_css()
        assert "body.dark" in css
        assert "--glass-blur: 12px" in css

    def test_light_blur_10px(self):
        """Light mode glass blur is 10px."""
        css = theme_module._glassmorphism_css()
        assert "--glass-blur: 10px" in css

    def test_graceful_degradation(self):
        """Fallback for browsers without backdrop-filter support."""
        css = theme_module._glassmorphism_css()
        assert "@supports not (backdrop-filter: blur(1px))" in css
        assert "rgba(13,27,42,0.92)" in css
        assert "rgba(255,255,255,0.92)" in css

    def test_init_theme_injects_glassmorphism(self, monkeypatch: pytest.MonkeyPatch):
        """init_theme() injects glassmorphism CSS into head HTML."""
        recorder = Recorder()
        _patch_theme_ui(monkeypatch, recorder)
        monkeypatch.setattr(theme_module, "_fonts_dir", lambda: Path("/tmp/fonts"))
        monkeypatch.setattr(
            theme_module, "create_header", lambda **kw: FakeElement("header")
        )

        theme_module.init_theme()

        head_calls = [call for call in recorder.calls if call[0] == "add_head_html"]
        glass_injected = any(
            ".glass-panel" in c[1][0] for c in head_calls if len(c[1]) > 0
        )
        assert glass_injected, "init_theme() must inject glassmorphism CSS"

    def test_stat_card_glass_kwarg(self, monkeypatch: pytest.MonkeyPatch):
        """create_stat_card(glass=True) adds .glass-panel class."""
        recorder = Recorder()
        _patch_widget_ui(monkeypatch, recorder)

        widgets_module.create_stat_card(42, "Test", glass=True)

        card_calls = [c for c in recorder.calls if c[0] == "card"]
        assert len(card_calls) >= 1
        card_el = card_calls[0][3]
        class_str = " ".join(str(c) for c in card_el.class_calls)
        assert "glass-panel" in class_str


# ---------------------------------------------------------------------------
# Modern status indicator tests (@ui-modernization Step M.4)
# ---------------------------------------------------------------------------


class TestModernStatusIndicators:
    """Status chips with icon prefix, skeleton loaders, pulse-critical."""

    def test_status_chip_has_icon(self, monkeypatch: pytest.MonkeyPatch):
        """create_status_chip() includes icon kwarg."""
        recorder = Recorder()
        _patch_widget_ui(monkeypatch, recorder)

        chip = widgets_module.create_status_chip("OPERATIONAL")
        assert chip.kwargs.get("icon") == "check_circle"

    def test_status_chip_estop_icon(self, monkeypatch: pytest.MonkeyPatch):
        """E-STOP status gets stop_circle icon."""
        recorder = Recorder()
        _patch_widget_ui(monkeypatch, recorder)

        chip = widgets_module.create_status_chip("E-STOP")
        assert chip.kwargs.get("icon") == "stop_circle"

    def test_status_chip_idle_icon(self, monkeypatch: pytest.MonkeyPatch):
        """IDLE status gets remove_circle_outline icon."""
        recorder = Recorder()
        _patch_widget_ui(monkeypatch, recorder)

        chip = widgets_module.create_status_chip("IDLE")
        assert chip.kwargs.get("icon") == "remove_circle_outline"

    def test_status_chip_disconnected_icon(self, monkeypatch: pytest.MonkeyPatch):
        """DISCONNECTED status gets wifi_off icon."""
        recorder = Recorder()
        _patch_widget_ui(monkeypatch, recorder)

        chip = widgets_module.create_status_chip("DISCONNECTED")
        assert chip.kwargs.get("icon") == "wifi_off"

    def test_status_chip_unknown_icon(self, monkeypatch: pytest.MonkeyPatch):
        """Unknown status gets help_outline icon."""
        recorder = Recorder()
        _patch_widget_ui(monkeypatch, recorder)

        chip = widgets_module.create_status_chip("FOOBAR")
        assert chip.kwargs.get("icon") == "help_outline"

    def test_status_chip_border_radius(self, monkeypatch: pytest.MonkeyPatch):
        """Status chips have 12px border radius."""
        recorder = Recorder()
        _patch_widget_ui(monkeypatch, recorder)

        chip = widgets_module.create_status_chip("RUNNING")
        assert any("border-radius: 12px" in s for s in chip.styles)

    def test_skeleton_card_returns_card(self, monkeypatch: pytest.MonkeyPatch):
        """create_skeleton_card() returns a card element."""
        recorder = Recorder()
        _patch_widget_ui(monkeypatch, recorder)

        card = widgets_module.create_skeleton_card()
        assert card.kind == "card"

    def test_skeleton_card_shimmer_class(self, monkeypatch: pytest.MonkeyPatch):
        """create_skeleton_card() has skeleton-shimmer class."""
        recorder = Recorder()
        _patch_widget_ui(monkeypatch, recorder)

        card = widgets_module.create_skeleton_card()
        class_str = " ".join(str(c) for c in card.class_calls)
        assert "skeleton-shimmer" in class_str

    def test_skeleton_card_height(self, monkeypatch: pytest.MonkeyPatch):
        """create_skeleton_card(height=...) sets custom height."""
        recorder = Recorder()
        _patch_widget_ui(monkeypatch, recorder)

        card = widgets_module.create_skeleton_card(height="120px")
        assert any("120px" in s for s in card.styles)

    def test_pulse_critical_css_defined(self):
        """_status_animations_css() defines pulse-critical animation."""
        css = theme_module._status_animations_css()
        assert "@keyframes pulse-critical" in css
        assert ".pulse-critical" in css

    def test_skeleton_shimmer_css_defined(self):
        """_status_animations_css() defines skeleton shimmer animation."""
        css = theme_module._status_animations_css()
        assert "@keyframes shimmer" in css
        assert ".skeleton-shimmer" in css

    def test_dark_skeleton_shimmer(self):
        """Dark mode has its own shimmer gradient."""
        css = theme_module._status_animations_css()
        assert "body.dark .skeleton-shimmer" in css

    def test_init_theme_injects_status_animations(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """init_theme() injects status animations CSS."""
        recorder = Recorder()
        _patch_theme_ui(monkeypatch, recorder)
        monkeypatch.setattr(theme_module, "_fonts_dir", lambda: Path("/tmp/fonts"))
        monkeypatch.setattr(
            theme_module, "create_header", lambda **kw: FakeElement("header")
        )

        theme_module.init_theme()

        head_calls = [call for call in recorder.calls if call[0] == "add_head_html"]
        anim_injected = any(
            "pulse-critical" in c[1][0] for c in head_calls if len(c[1]) > 0
        )
        assert anim_injected, "init_theme() must inject status animation CSS"

    def test_status_icon_mapping_complete(self):
        """All documented statuses have icon mappings."""
        for status in (
            "OPERATIONAL",
            "E-STOP",
            "EMERGENCY_STOP",
            "PAUSED",
            "IDLE",
            "DISCONNECTED",
            "UNKNOWN",
            "RUNNING",
            "STARTED",
            "ACTIVE",
            "READY",
            "STOPPED",
            "ERROR",
        ):
            icon = widgets_module._status_icon(status)
            assert icon != "", f"No icon for {status}"
