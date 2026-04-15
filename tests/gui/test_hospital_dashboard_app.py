"""Tests for the hospital dashboard NiceGUI application.

Covers:
- Health and readiness probe endpoints
- GuiBackend registry and readiness tracking
- SPA shell page structure (nav pill + sub_pages)
- GuiBackend self-registration lifecycle hooks
- SPA navigation: active-nav highlighting, page title
- Page title helper function

Spec: nicegui-migration.md — Page Routing, SPA Navigation, Health & Readiness Probes
Tags: @gui @unit @deployment @ui-modernization
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

    def clear(self) -> None:
        self.children.clear()


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
        from hospital_dashboard.dashboard.dashboard import _backends_ready

        assert _backends_ready() is True

    def test_false_when_any_backend_not_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns False if any registered backend has not marked ready."""
        monkeypatch.setattr("nicegui.app.on_startup", lambda fn: None)
        monkeypatch.setattr("nicegui.app.on_shutdown", lambda fn: None)
        from hospital_dashboard.dashboard.dashboard import _backends_ready

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
        from hospital_dashboard.dashboard.dashboard import _backends_ready

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
        from hospital_dashboard.dashboard.dashboard import _backends_ready

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
        from hospital_dashboard.dashboard.dashboard import health

        response = asyncio.run(health())
        assert response.status_code == 200

    def test_health_returns_ok_body(self) -> None:
        """health() response body contains {'status': 'ok'}."""
        import json

        from hospital_dashboard.dashboard.dashboard import health

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
        from hospital_dashboard.dashboard.dashboard import ready

        response = asyncio.run(ready())
        assert response.status_code == 200

    def test_ready_503_when_backend_not_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns 503 when a registered backend has not marked ready."""
        monkeypatch.setattr("nicegui.app.on_startup", lambda fn: None)
        monkeypatch.setattr("nicegui.app.on_shutdown", lambda fn: None)
        from hospital_dashboard.dashboard.dashboard import ready

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
        from hospital_dashboard.dashboard.dashboard import ready

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
        from hospital_dashboard.dashboard.dashboard import ready

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
    """shell_page() renders floating nav pill + full-screen sub_pages."""

    def _patch_shell(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
        """Patch all NiceGUI widgets used by shell_page() and return call log."""
        import hospital_dashboard.dashboard.dashboard as app_module

        log: dict[str, list[Any]] = {
            "row": [],
            "label": [],
            "button": [],
            "icon": [],
            "column": [],
            "sub_pages": [],
            "dark_mode": [],
            "html": [],
            "separator": [],
            "timer": [],
        }

        def _make_fake(kind: str) -> Any:
            def factory(*a: Any, **kw: Any) -> FakeElement:
                log[kind].append({"args": a, "kwargs": kw})
                return FakeElement(kind)

            return factory

        for widget in (
            "row",
            "label",
            "button",
            "icon",
            "column",
            "sub_pages",
            "html",
            "separator",
        ):
            monkeypatch.setattr(app_module.ui, widget, _make_fake(widget))

        monkeypatch.setattr(
            app_module.ui, "dark_mode", lambda *a, **kw: FakeElement("dark_mode")
        )
        monkeypatch.setattr(
            app_module.ui,
            "timer",
            lambda *a, **kw: (log["timer"].append({"args": a, "kwargs": kw}), None)[1],
        )

        # Mock ui.refreshable decorator to be a no-op passthrough
        def _fake_refreshable(fn: Any) -> Any:
            fn.refresh = lambda: None
            return fn

        monkeypatch.setattr(app_module.ui, "refreshable", _fake_refreshable)

        # Mock init_theme to avoid real NiceGUI calls
        monkeypatch.setattr(
            app_module, "init_theme", lambda *a, **kw: FakeElement("row")
        )

        # Mock ConnectionDot
        monkeypatch.setattr(
            app_module, "ConnectionDot", lambda **kw: FakeElement("dot")
        )

        # Mock ui.context to avoid sub_pages_router access
        monkeypatch.setattr(
            app_module.ui,
            "context",
            type("FakeCtx", (), {"client": type("FakeClient", (), {})()})(),
        )

        fake_user_storage_obj = type("US", (), {"get": lambda self, k, d=None: d})()
        monkeypatch.setattr(
            app_module.app,
            "storage",
            type("S", (), {"user": fake_user_storage_obj})(),
        )

        return log

    def test_shell_page_creates_nav_pill(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """shell_page() creates a ui.row for the floating navigation pill."""
        import hospital_dashboard.dashboard.dashboard as app_module

        log = self._patch_shell(monkeypatch)
        app_module.shell_page()
        assert len(log["row"]) >= 1

    def test_shell_page_no_header_or_drawer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """shell_page() does not create ui.header or ui.left_drawer."""
        import hospital_dashboard.dashboard.dashboard as app_module

        self._patch_shell(monkeypatch)
        # Also patch header/left_drawer to detect if they're called
        header_calls: list[Any] = []
        drawer_calls: list[Any] = []
        monkeypatch.setattr(
            app_module.ui,
            "header",
            lambda *a, **kw: header_calls.append(1) or FakeElement("header"),
        )
        monkeypatch.setattr(
            app_module.ui,
            "left_drawer",
            lambda *a, **kw: drawer_calls.append(1) or FakeElement("drawer"),
        )
        app_module.shell_page()
        assert len(header_calls) == 0
        assert len(drawer_calls) == 0

    def test_shell_page_registers_sub_pages(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """shell_page() calls ui.sub_pages() with dashboard-only route dict."""
        import hospital_dashboard.dashboard.dashboard as app_module

        log = self._patch_shell(monkeypatch)
        app_module.shell_page()

        assert len(log["sub_pages"]) == 1
        routes = log["sub_pages"][0]["args"][0]
        assert "/dashboard" in routes
        # Controller and twin routes are no longer in the hospital app
        assert "/controller/{room_id}" not in routes
        assert "/twin/{room_id}" not in routes

    def test_shell_page_sub_pages_use_content_functions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """sub_pages routes point to the content-only builder functions."""
        import hospital_dashboard.dashboard.dashboard as app_module
        from hospital_dashboard.dashboard.dashboard import dashboard_content

        log = self._patch_shell(monkeypatch)
        app_module.shell_page()

        routes = log["sub_pages"][0]["args"][0]
        assert routes["/dashboard"] is dashboard_content

    def test_shell_page_nav_pill_has_static_buttons(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Navigation pill contains a Dashboard button."""
        import hospital_dashboard.dashboard.dashboard as app_module

        log = self._patch_shell(monkeypatch)
        app_module.shell_page()

        # Static nav button (Dashboard) + theme toggle buttons
        assert len(log["button"]) >= 1

    def test_shell_page_root_redirect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Root '/' route redirects to '/dashboard' via sub_pages."""
        import hospital_dashboard.dashboard.dashboard as app_module

        log = self._patch_shell(monkeypatch)
        app_module.shell_page()

        routes = log["sub_pages"][0]["args"][0]
        assert "/" in routes


# ---------------------------------------------------------------------------
# Page title helper tests (@ui-modernization)
# ---------------------------------------------------------------------------


class TestPageTitleForPath:
    """_page_title_for_path() returns correct breadcrumb titles."""

    def test_dashboard_path(self) -> None:
        from hospital_dashboard.dashboard.dashboard import _page_title_for_path

        assert _page_title_for_path("/dashboard") == "Dashboard"

    def test_unknown_path_returns_home(self) -> None:
        from hospital_dashboard.dashboard.dashboard import _page_title_for_path

        assert _page_title_for_path("/unknown") == "Home"

    def test_root_returns_home(self) -> None:
        from hospital_dashboard.dashboard.dashboard import _page_title_for_path

        assert _page_title_for_path("/") == "Home"


# ---------------------------------------------------------------------------
# Static nav items tests (@ui-modernization)
# ---------------------------------------------------------------------------


class TestStaticNavItems:
    """_STATIC_NAV_ITEMS contains the expected Tier 1 navigation entries."""

    def test_static_nav_has_dashboard(self) -> None:
        from hospital_dashboard.dashboard.dashboard import _STATIC_NAV_ITEMS

        paths = [item[0] for item in _STATIC_NAV_ITEMS]
        assert "/dashboard" in paths

    def test_controller_is_per_room_not_static(self) -> None:
        from hospital_dashboard.dashboard.dashboard import _STATIC_NAV_ITEMS

        paths = [item[0] for item in _STATIC_NAV_ITEMS]
        assert "/controller" not in paths

    def test_static_nav_count(self) -> None:
        from hospital_dashboard.dashboard.dashboard import _STATIC_NAV_ITEMS

        assert len(_STATIC_NAV_ITEMS) == 1


# ---------------------------------------------------------------------------
# main() passes shell_page as root to ui.run (@ui-modernization)
# ---------------------------------------------------------------------------


class TestMainUsesRoot:
    """main() passes shell_page as root= kwarg to ui.run()."""

    def test_main_calls_ui_run_with_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ui.run() is called with root=shell_page."""
        import hospital_dashboard.dashboard.dashboard as app_module

        run_calls: list[dict[str, Any]] = []

        monkeypatch.setattr("nicegui.app.on_startup", lambda fn: None)
        monkeypatch.setattr("nicegui.app.on_shutdown", lambda fn: None)

        monkeypatch.setattr(
            app_module.app,
            "add_static_files",
            lambda *a, **kw: None,
        )

        def fake_run(*a: Any, **kw: Any) -> None:
            run_calls.append(kw)
            raise KeyboardInterrupt

        monkeypatch.setattr(app_module.ui, "run", fake_run)

        # Patch module-level backend factories to avoid DDS init
        monkeypatch.setattr(
            "hospital_dashboard.dashboard.dashboard._current_backend",
            lambda: None,
        )

        app_module.main()

        assert len(run_calls) == 1
        assert run_calls[0].get("root") is app_module.shell_page


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

        import hospital_dashboard.dashboard.dashboard as app_module

        source = inspect.getsource(app_module.main)
        assert "start()" not in source, (
            "main() must not call start() manually — "
            "GuiBackend self-registers with app.on_startup"
        )
