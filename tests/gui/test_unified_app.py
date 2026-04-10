"""Tests for the unified NiceGUI application — Step N.6 test gate.

Covers:
- Health and readiness probe endpoints
- GuiBackend registry and readiness tracking
- SPA shell page structure (header + drawer + sub_pages)
- GuiBackend self-registration lifecycle hooks

Spec: nicegui-migration.md — Page Routing, SPA Navigation, Health & Readiness Probes
Tags: @gui @unit @deployment
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from medtech.gui._backend import GuiBackend

pytestmark = [pytest.mark.gui, pytest.mark.unit]


# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------


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
    children: list[Any] = field(default_factory=list)
    text: str = ""

    def __enter__(self) -> "FakeElement":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
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

    def on(self, event_name: str, handler: Any) -> "FakeElement":
        self.events.append((event_name, handler))
        return self

    def bind_visibility_from(self, *args: Any, **kwargs: Any) -> "FakeElement":
        return self

    def set_text(self, value: str) -> None:
        self.text = value


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def record(self, kind: str, *args: Any, **kwargs: Any) -> FakeElement:
        element = FakeElement(kind=kind, args=args, kwargs=kwargs)
        self.calls.append((kind, args, kwargs))
        return element

    def kinds(self) -> list[str]:
        return [c[0] for c in self.calls]


# ---------------------------------------------------------------------------
# GuiBackend registry and readiness tracking
# ---------------------------------------------------------------------------


class TestGuiBackendReadiness:
    """GuiBackend.is_ready() and _mark_ready() track readiness state."""

    def setup_method(self) -> None:
        """Clear the registry before each test."""
        GuiBackend._clear_registry()

    def teardown_method(self) -> None:
        GuiBackend._clear_registry()

    def test_backend_not_ready_before_start(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backend is not ready immediately after construction."""
        monkeypatch.setattr("nicegui.app.on_startup", lambda fn: None)
        monkeypatch.setattr("nicegui.app.on_shutdown", lambda fn: None)

        class ReadinessBackend(GuiBackend):
            @property
            def name(self) -> str:
                return "readiness-test"

            async def start(self) -> None:
                self._mark_ready()

            async def close(self) -> None:
                pass

        b = ReadinessBackend()
        assert not b.is_ready()

    def test_backend_ready_after_mark_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backend is ready after _mark_ready() is called."""
        monkeypatch.setattr("nicegui.app.on_startup", lambda fn: None)
        monkeypatch.setattr("nicegui.app.on_shutdown", lambda fn: None)

        class ReadinessBackend(GuiBackend):
            @property
            def name(self) -> str:
                return "readiness-test"

            async def start(self) -> None:
                self._mark_ready()

            async def close(self) -> None:
                pass

        b = ReadinessBackend()
        b._mark_ready()
        assert b.is_ready()

    def test_registry_tracks_all_instances(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GuiBackend.registry() returns all registered instances."""
        monkeypatch.setattr("nicegui.app.on_startup", lambda fn: None)
        monkeypatch.setattr("nicegui.app.on_shutdown", lambda fn: None)

        class RegBackend(GuiBackend):
            @property
            def name(self) -> str:
                return "reg-test"

            async def start(self) -> None:
                pass

            async def close(self) -> None:
                pass

        b1 = RegBackend()
        b2 = RegBackend()
        registry = GuiBackend.registry()
        assert b1 in registry
        assert b2 in registry
        assert len(registry) == 2

    def test_clear_registry_resets_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_clear_registry() empties the registry — for test isolation."""
        monkeypatch.setattr("nicegui.app.on_startup", lambda fn: None)
        monkeypatch.setattr("nicegui.app.on_shutdown", lambda fn: None)

        class ClearBackend(GuiBackend):
            @property
            def name(self) -> str:
                return "clear-test"

            async def start(self) -> None:
                pass

            async def close(self) -> None:
                pass

        ClearBackend()
        assert len(GuiBackend.registry()) == 1
        GuiBackend._clear_registry()
        assert len(GuiBackend.registry()) == 0

    def test_registry_returns_copy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """registry() returns a snapshot; modifying it does not affect the class."""
        monkeypatch.setattr("nicegui.app.on_startup", lambda fn: None)
        monkeypatch.setattr("nicegui.app.on_shutdown", lambda fn: None)

        class SnapBackend(GuiBackend):
            @property
            def name(self) -> str:
                return "snap"

            async def start(self) -> None:
                pass

            async def close(self) -> None:
                pass

        b = SnapBackend()
        snapshot = GuiBackend.registry()
        snapshot.clear()
        assert b in GuiBackend.registry()


# ---------------------------------------------------------------------------
# _backends_ready() helper
# ---------------------------------------------------------------------------


class TestBackendsReady:
    """_backends_ready() reflects registry readiness correctly."""

    def setup_method(self) -> None:
        GuiBackend._clear_registry()

    def teardown_method(self) -> None:
        GuiBackend._clear_registry()

    def test_true_when_registry_empty(self) -> None:
        """No backends → ready (vacuously)."""
        from medtech.gui.app import _backends_ready

        assert _backends_ready() is True

    def test_false_when_any_backend_not_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns False if any registered backend has not marked ready."""
        monkeypatch.setattr("nicegui.app.on_startup", lambda fn: None)
        monkeypatch.setattr("nicegui.app.on_shutdown", lambda fn: None)
        from medtech.gui.app import _backends_ready

        class PendingBackend(GuiBackend):
            @property
            def name(self) -> str:
                return "pending"

            async def start(self) -> None:
                pass

            async def close(self) -> None:
                pass

        PendingBackend()  # not yet ready
        assert _backends_ready() is False

    def test_true_when_all_backends_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns True when every registered backend has marked ready."""
        monkeypatch.setattr("nicegui.app.on_startup", lambda fn: None)
        monkeypatch.setattr("nicegui.app.on_shutdown", lambda fn: None)
        from medtech.gui.app import _backends_ready

        class ReadyBackend(GuiBackend):
            @property
            def name(self) -> str:
                return "all-ready"

            async def start(self) -> None:
                self._mark_ready()

            async def close(self) -> None:
                pass

        b = ReadyBackend()
        b._mark_ready()
        assert _backends_ready() is True

    def test_false_when_some_ready_some_not(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns False when at least one backend is not yet ready."""
        monkeypatch.setattr("nicegui.app.on_startup", lambda fn: None)
        monkeypatch.setattr("nicegui.app.on_shutdown", lambda fn: None)
        from medtech.gui.app import _backends_ready

        class MixedBackend(GuiBackend):
            @property
            def name(self) -> str:
                return "mixed"

            async def start(self) -> None:
                pass

            async def close(self) -> None:
                pass

        b1 = MixedBackend()
        MixedBackend()  # b2 — not yet ready
        b1._mark_ready()
        assert _backends_ready() is False


# ---------------------------------------------------------------------------
# Health and readiness probe endpoints
# ---------------------------------------------------------------------------


class TestHealthProbe:
    """GET /health — liveness probe."""

    def test_health_returns_200(self) -> None:
        """health() returns HTTP 200."""
        from medtech.gui.app import health

        response = asyncio.run(health())
        assert response.status_code == 200

    def test_health_returns_ok_body(self) -> None:
        """health() response body contains {'status': 'ok'}."""
        import json

        from medtech.gui.app import health

        response = asyncio.run(health())
        body = json.loads(response.body)
        assert body == {"status": "ok"}


class TestReadinessProbe:
    """GET /ready — readiness probe."""

    def setup_method(self) -> None:
        GuiBackend._clear_registry()

    def teardown_method(self) -> None:
        GuiBackend._clear_registry()

    def test_ready_200_when_no_backends(self) -> None:
        """Returns 200 when no backends are registered (vacuously ready)."""
        from medtech.gui.app import ready

        response = asyncio.run(ready())
        assert response.status_code == 200

    def test_ready_503_when_backend_not_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns 503 when a registered backend has not marked ready."""
        monkeypatch.setattr("nicegui.app.on_startup", lambda fn: None)
        monkeypatch.setattr("nicegui.app.on_shutdown", lambda fn: None)
        from medtech.gui.app import ready

        class SlowBackend(GuiBackend):
            @property
            def name(self) -> str:
                return "slow"

            async def start(self) -> None:
                pass  # never marks ready in this test

            async def close(self) -> None:
                pass

        SlowBackend()
        response = asyncio.run(ready())
        assert response.status_code == 503

    def test_ready_503_body_contains_not_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """503 response body contains {'status': 'not ready'}."""
        import json

        monkeypatch.setattr("nicegui.app.on_startup", lambda fn: None)
        monkeypatch.setattr("nicegui.app.on_shutdown", lambda fn: None)
        from medtech.gui.app import ready

        class UnreadyBackend(GuiBackend):
            @property
            def name(self) -> str:
                return "unready"

            async def start(self) -> None:
                pass

            async def close(self) -> None:
                pass

        UnreadyBackend()
        response = asyncio.run(ready())
        body = json.loads(response.body)
        assert body == {"status": "not ready"}

    def test_ready_200_when_all_backends_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns 200 when all backends have marked ready."""
        import json

        monkeypatch.setattr("nicegui.app.on_startup", lambda fn: None)
        monkeypatch.setattr("nicegui.app.on_shutdown", lambda fn: None)
        from medtech.gui.app import ready

        class InstantBackend(GuiBackend):
            @property
            def name(self) -> str:
                return "instant"

            async def start(self) -> None:
                self._mark_ready()

            async def close(self) -> None:
                pass

        b = InstantBackend()
        b._mark_ready()
        response = asyncio.run(ready())
        assert response.status_code == 200
        body = json.loads(response.body)
        assert body == {"status": "ready"}


# ---------------------------------------------------------------------------
# SPA shell page structure
# ---------------------------------------------------------------------------


class TestShellPage:
    """shell_page() renders header, navigation drawer, and sub_pages."""

    def _patch_nicegui(
        self, monkeypatch: pytest.MonkeyPatch, recorder: Recorder
    ) -> None:
        """Patch the ui and app objects referenced by app.py."""
        import medtech.gui.app as app_module

        monkeypatch.setattr(
            app_module.ui,
            "left_drawer",
            lambda *a, **kw: recorder.record("left_drawer", *a, **kw),
        )
        monkeypatch.setattr(
            app_module.ui, "label", lambda *a, **kw: recorder.record("label", *a, **kw)
        )
        monkeypatch.setattr(
            app_module.ui,
            "button",
            lambda *a, **kw: recorder.record("button", *a, **kw),
        )
        monkeypatch.setattr(
            app_module.ui, "icon", lambda *a, **kw: recorder.record("icon", *a, **kw)
        )
        monkeypatch.setattr(
            app_module.ui,
            "column",
            lambda *a, **kw: recorder.record("column", *a, **kw),
        )
        monkeypatch.setattr(
            app_module.ui,
            "sub_pages",
            lambda *a, **kw: recorder.record("sub_pages", *a, **kw),
        )
        monkeypatch.setattr(
            app_module.ui,
            "dark_mode",
            lambda *a, **kw: recorder.record("dark_mode", *a, **kw),
        )
        monkeypatch.setattr(app_module.init_theme, "__call__", lambda *a, **kw: None)

        def _fake_storage_get(key: str, default: Any = None) -> Any:
            return default

        monkeypatch.setattr(
            app_module.app,
            "storage",
            type("S", (), {"user": {"get": _fake_storage_get}})(),
        )

    def test_shell_page_creates_left_drawer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """shell_page() creates a ui.left_drawer for navigation."""
        import medtech.gui.app as app_module

        recorder = Recorder()

        calls_recorded: list[str] = []
        monkeypatch.setattr(
            app_module.ui,
            "left_drawer",
            lambda *a, **kw: (
                calls_recorded.append("left_drawer"),
                recorder.record("left_drawer", *a, **kw),
            )[1],
        )
        monkeypatch.setattr(
            app_module.ui, "label", lambda *a, **kw: recorder.record("label", *a, **kw)
        )
        monkeypatch.setattr(
            app_module.ui,
            "button",
            lambda *a, **kw: recorder.record("button", *a, **kw),
        )
        monkeypatch.setattr(
            app_module.ui, "icon", lambda *a, **kw: recorder.record("icon", *a, **kw)
        )
        monkeypatch.setattr(
            app_module.ui,
            "column",
            lambda *a, **kw: recorder.record("column", *a, **kw),
        )
        monkeypatch.setattr(
            app_module.ui,
            "sub_pages",
            lambda *a, **kw: recorder.record("sub_pages", *a, **kw),
        )
        monkeypatch.setattr(
            app_module.ui, "dark_mode", lambda *a, **kw: FakeElement("dark_mode")
        )
        monkeypatch.setattr(
            app_module, "init_theme", lambda *a, **kw: FakeElement("header")
        )

        class FakeStorage:
            user: dict[str, Any] = field(default_factory=dict)

            def get(self, key: str, default: Any = None) -> Any:
                return default

        fake_user_storage_obj = type("US", (), {"get": lambda self, k, d=None: d})()

        monkeypatch.setattr(
            app_module.app,
            "storage",
            type("S", (), {"user": fake_user_storage_obj})(),
        )

        app_module.shell_page()

        assert "left_drawer" in calls_recorded

    def test_shell_page_registers_sub_pages(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """shell_page() calls ui.sub_pages() with route dict."""
        import medtech.gui.app as app_module

        sub_pages_calls: list[dict[str, Any]] = []

        monkeypatch.setattr(
            app_module.ui, "left_drawer", lambda *a, **kw: FakeElement("drawer")
        )
        monkeypatch.setattr(
            app_module.ui, "label", lambda *a, **kw: FakeElement("label")
        )
        monkeypatch.setattr(
            app_module.ui, "button", lambda *a, **kw: FakeElement("button")
        )
        monkeypatch.setattr(app_module.ui, "icon", lambda *a, **kw: FakeElement("icon"))
        monkeypatch.setattr(
            app_module.ui, "column", lambda *a, **kw: FakeElement("column")
        )
        monkeypatch.setattr(
            app_module.ui,
            "sub_pages",
            lambda routes, **kw: sub_pages_calls.append({"routes": routes})
            or FakeElement("sub_pages"),
        )
        monkeypatch.setattr(
            app_module.ui, "dark_mode", lambda *a, **kw: FakeElement("dark_mode")
        )
        monkeypatch.setattr(
            app_module, "init_theme", lambda *a, **kw: FakeElement("header")
        )

        fake_user_storage_obj = type("US", (), {"get": lambda self, k, d=None: d})()
        monkeypatch.setattr(
            app_module.app,
            "storage",
            type("S", (), {"user": fake_user_storage_obj})(),
        )

        app_module.shell_page()

        assert len(sub_pages_calls) == 1
        routes = sub_pages_calls[0]["routes"]
        assert "/dashboard" in routes
        assert "/controller" in routes
        assert "/twin/{room_id}" in routes

    def test_shell_page_sub_pages_use_content_functions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """sub_pages routes point to the content-only builder functions."""
        import medtech.gui.app as app_module
        from hospital_dashboard.dashboard.dashboard import dashboard_content
        from hospital_dashboard.procedure_controller.controller import (
            controller_content,
        )
        from surgical_procedure.digital_twin.digital_twin import twin_content

        captured_routes: dict[str, Any] = {}

        monkeypatch.setattr(
            app_module.ui, "left_drawer", lambda *a, **kw: FakeElement("drawer")
        )
        monkeypatch.setattr(
            app_module.ui, "label", lambda *a, **kw: FakeElement("label")
        )
        monkeypatch.setattr(
            app_module.ui, "button", lambda *a, **kw: FakeElement("button")
        )
        monkeypatch.setattr(app_module.ui, "icon", lambda *a, **kw: FakeElement("icon"))
        monkeypatch.setattr(
            app_module.ui, "column", lambda *a, **kw: FakeElement("column")
        )
        monkeypatch.setattr(
            app_module.ui,
            "sub_pages",
            lambda routes, **kw: captured_routes.update(routes)
            or FakeElement("sub_pages"),
        )
        monkeypatch.setattr(
            app_module.ui, "dark_mode", lambda *a, **kw: FakeElement("dark_mode")
        )
        monkeypatch.setattr(
            app_module, "init_theme", lambda *a, **kw: FakeElement("header")
        )

        fake_user_storage_obj = type("US", (), {"get": lambda self, k, d=None: d})()
        monkeypatch.setattr(
            app_module.app,
            "storage",
            type("S", (), {"user": fake_user_storage_obj})(),
        )

        app_module.shell_page()

        assert captured_routes["/dashboard"] is dashboard_content
        assert captured_routes["/controller"] is controller_content
        assert captured_routes["/twin/{room_id}"] is twin_content

    def test_shell_page_navigation_drawer_has_three_items(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Navigation drawer contains entries for Dashboard, Controller, and Digital Twin."""
        import medtech.gui.app as app_module

        button_calls: list[tuple[Any, ...]] = []

        monkeypatch.setattr(
            app_module.ui, "left_drawer", lambda *a, **kw: FakeElement("drawer")
        )
        monkeypatch.setattr(
            app_module.ui, "label", lambda *a, **kw: FakeElement("label")
        )
        monkeypatch.setattr(
            app_module.ui,
            "button",
            lambda *a, **kw: (button_calls.append(kw), FakeElement("button"))[1],
        )
        monkeypatch.setattr(app_module.ui, "icon", lambda *a, **kw: FakeElement("icon"))
        monkeypatch.setattr(
            app_module.ui, "column", lambda *a, **kw: FakeElement("column")
        )
        monkeypatch.setattr(
            app_module.ui, "sub_pages", lambda *a, **kw: FakeElement("sub_pages")
        )
        monkeypatch.setattr(
            app_module.ui, "dark_mode", lambda *a, **kw: FakeElement("dark_mode")
        )
        monkeypatch.setattr(
            app_module, "init_theme", lambda *a, **kw: FakeElement("header")
        )

        fake_user_storage_obj = type("US", (), {"get": lambda self, k, d=None: d})()
        monkeypatch.setattr(
            app_module.app,
            "storage",
            type("S", (), {"user": fake_user_storage_obj})(),
        )

        app_module.shell_page()

        # Three nav items (Dashboard, Controller, Digital Twin) + any sub-buttons
        assert len(button_calls) >= 3


# ---------------------------------------------------------------------------
# GuiBackend lifecycle hook registration (self-registration contract)
# ---------------------------------------------------------------------------


class TestGuiBackendLifecycleHooks:
    """GuiBackend __init__ self-registers start() and close() with NiceGUI hooks."""

    def setup_method(self) -> None:
        GuiBackend._clear_registry()

    def teardown_method(self) -> None:
        GuiBackend._clear_registry()

    def test_start_registered_on_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """start() is registered with app.on_startup on construction."""
        startups: list[Any] = []
        monkeypatch.setattr("nicegui.app.on_startup", startups.append)
        monkeypatch.setattr("nicegui.app.on_shutdown", lambda fn: None)

        class HookBackend(GuiBackend):
            @property
            def name(self) -> str:
                return "hook-test"

            async def start(self) -> None:
                self._mark_ready()

            async def close(self) -> None:
                pass

        b = HookBackend()
        assert any(fn.__self__ is b for fn in startups)

    def test_close_registered_on_shutdown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """close() is registered with app.on_shutdown on construction."""
        shutdowns: list[Any] = []
        monkeypatch.setattr("nicegui.app.on_startup", lambda fn: None)
        monkeypatch.setattr("nicegui.app.on_shutdown", shutdowns.append)

        class HookBackend2(GuiBackend):
            @property
            def name(self) -> str:
                return "hook-test-2"

            async def start(self) -> None:
                self._mark_ready()

            async def close(self) -> None:
                pass

        b = HookBackend2()
        assert any(fn.__self__ is b for fn in shutdowns)

    def test_no_manual_start_needed_in_unified_app(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unified app never manually calls start() — hooks fire automatically."""
        # Verify that app.py does not contain explicit start() calls
        import inspect

        import medtech.gui.app as app_module

        source = inspect.getsource(app_module.main)
        assert "start()" not in source, (
            "main() must not call start() manually — "
            "GuiBackend self-registers with app.on_startup"
        )
