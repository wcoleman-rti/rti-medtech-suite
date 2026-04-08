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
