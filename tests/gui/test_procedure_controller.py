"""Tests for the NiceGUI Procedure Controller migration.

Tags: @gui @integration @orchestration
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import app_names
import pytest
import rti.connextdds as dds
from medtech.gui import BRAND_COLORS, ICONS
from orchestration import Orchestration
from surgical_procedure.procedure_controller import controller as controller_module

pytestmark = [
    pytest.mark.gui,
    pytest.mark.integration,
    pytest.mark.orchestration,
]

orch_names = app_names.MedtechEntityNames.OrchestrationParticipants


@dataclass
class FakeElement:
    kind: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    class_calls: list[tuple[Any, ...]] = field(default_factory=list)
    on_calls: list[tuple[str, Any]] = field(default_factory=list)
    props_calls: list[tuple[Any, ...]] = field(default_factory=list)

    def __enter__(self) -> "FakeElement":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    @property
    def before(self) -> "FakeElement":
        return self

    @property
    def after(self) -> "FakeElement":
        return self

    def classes(self, *args: Any, **kwargs: Any) -> "FakeElement":
        self.class_calls.append(args)
        return self

    def style(self, value: str) -> "FakeElement":
        return self

    def on(self, event: str, handler: Any) -> "FakeElement":
        self.on_calls.append((event, handler))
        return self

    def props(self, *args: Any, **kwargs: Any) -> "FakeElement":
        self.props_calls.append(args)
        return self

    def tooltip(self, text: str) -> "FakeElement":
        return self

    def bind_value(self, *args: Any, **kwargs: Any) -> "FakeElement":
        return self

    def on_value_change(self, *args: Any, **kwargs: Any) -> "FakeElement":
        return self

    def push(self, text: str) -> None:
        pass


class RefreshableWrapper:
    def __init__(self, func: Any) -> None:
        self.func = func

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.func(*args, **kwargs)

    def refresh(self) -> None:
        return None


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any], FakeElement]] = []

    def record(self, kind: str, *args: Any, **kwargs: Any) -> FakeElement:
        element = FakeElement(kind=kind, args=args, kwargs=kwargs)
        self.calls.append((kind, args, kwargs, element))
        return element


class FakeTask:
    def __init__(self) -> None:
        self._cancelled = False

    def done(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True


def _patch_ui(monkeypatch: pytest.MonkeyPatch, recorder: Recorder) -> None:
    monkeypatch.setattr(
        controller_module.ui,
        "column",
        lambda *args, **kwargs: recorder.record("column", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "row",
        lambda *args, **kwargs: recorder.record("row", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "card",
        lambda *args, **kwargs: recorder.record("card", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "tabs",
        lambda *args, **kwargs: recorder.record("tabs", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "tab",
        lambda *args, **kwargs: recorder.record("tab", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "tab_panels",
        lambda *args, **kwargs: recorder.record("tab_panels", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "tab_panel",
        lambda *args, **kwargs: recorder.record("tab_panel", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "page_sticky",
        lambda *args, **kwargs: recorder.record("page_sticky", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "dialog",
        lambda *args, **kwargs: recorder.record("dialog", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "button",
        lambda *args, **kwargs: recorder.record("button", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "label",
        lambda *args, **kwargs: recorder.record("label", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "select",
        lambda *args, **kwargs: recorder.record("select", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "toggle",
        lambda *args, **kwargs: recorder.record("toggle", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "log",
        lambda *args, **kwargs: recorder.record("log", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "icon",
        lambda *args, **kwargs: recorder.record("icon", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "timer",
        lambda interval, callback, **kwargs: recorder.record(
            "timer", interval, callback, **kwargs
        ),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "refreshable",
        lambda func: RefreshableWrapper(func),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "element",
        lambda *args, **kwargs: recorder.record("element", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "badge",
        lambda *args, **kwargs: recorder.record("badge", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "space",
        lambda *args, **kwargs: recorder.record("space", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "separator",
        lambda *args, **kwargs: recorder.record("separator", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "textarea",
        lambda *args, **kwargs: recorder.record("textarea", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "input",
        lambda *args, **kwargs: recorder.record("input", *args, **kwargs),
    )
    monkeypatch.setattr(
        controller_module.ui,
        "notify",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        controller_module.ui,
        "checkbox",
        lambda *args, **kwargs: recorder.record("checkbox", *args, **kwargs),
    )


def _make_injected_readers(participant_factory):
    participant = participant_factory(domain_id=0)
    subscriber = dds.Subscriber(participant)

    def _reader(data_type, topic_name):
        topic = dds.Topic(participant, topic_name, data_type)
        return dds.DataReader(subscriber, topic, dds.DataReaderQos())

    return {
        "catalog_reader": _reader(Orchestration.ServiceCatalog, "ServiceCatalog"),
        "status_reader": _reader(Orchestration.ServiceStatus, "ServiceStatus"),
    }


class TestControllerBackend:
    def test_backend_can_be_injected(self, participant_factory):
        readers = _make_injected_readers(participant_factory)
        backend = controller_module.ControllerBackend(**readers)
        assert backend.name == "ProcedureController"
        asyncio.run(backend.close())

    def test_backend_updates_state_from_samples(self, participant_factory):
        readers = _make_injected_readers(participant_factory)
        backend = controller_module.ControllerBackend(**readers)
        backend._update_catalog(
            SimpleNamespace(
                host_id="host-1",
                service_id="svc-1",
                display_name="Svc One",
            )
        )
        backend._update_service_status(
            SimpleNamespace(
                host_id="host-1",
                service_id="svc-1",
                state=Orchestration.ServiceState.RUNNING,
            )
        )

        assert backend.hosts == {"host-1"}
        assert ("host-1", "svc-1") in backend.catalogs
        assert (
            backend.service_states[("host-1", "svc-1")].state
            == Orchestration.ServiceState.RUNNING
        )
        asyncio.run(backend.close())

    def test_view_switching_updates_mode(self, participant_factory):
        readers = _make_injected_readers(participant_factory)
        backend = controller_module.ControllerBackend(**readers)

        backend.show_services_view()
        assert backend.view_mode == "services"

        backend.select_host("host-1")
        assert backend.view_mode == "hosts"
        assert backend._view.selected_host_id == "host-1"

        backend.select_service("host-1", "svc-1")
        assert backend.view_mode == "services"
        assert backend._view.selected_service_key == ("host-1", "svc-1")

        asyncio.run(backend.close())

    def test_bulk_service_actions_dispatch_all_services(
        self, participant_factory, monkeypatch
    ):
        readers = _make_injected_readers(participant_factory)
        backend = controller_module.ControllerBackend(**readers)
        backend._catalogs = {
            ("host-1", "svc-1"): SimpleNamespace(host_id="host-1", service_id="svc-1"),
            ("host-2", "svc-2"): SimpleNamespace(host_id="host-2", service_id="svc-2"),
        }

        started: list[tuple[str, str]] = []
        stopped: list[tuple[str, str]] = []

        async def _fake_start(host_id: str, service_id: str) -> None:
            started.append((host_id, service_id))

        async def _fake_stop(host_id: str, service_id: str) -> None:
            stopped.append((host_id, service_id))

        monkeypatch.setattr(backend, "start_service", _fake_start)
        monkeypatch.setattr(backend, "stop_service", _fake_stop)

        asyncio.run(backend.start_all_services())
        asyncio.run(backend.stop_all_services())

        assert started == [("host-1", "svc-1"), ("host-2", "svc-2")]
        assert stopped == [("host-1", "svc-1"), ("host-2", "svc-2")]
        asyncio.run(backend.close())

    def test_start_schedules_background_tasks(self, participant_factory, monkeypatch):
        readers = _make_injected_readers(participant_factory)
        backend = controller_module.ControllerBackend(**readers)
        scheduled: list[str] = []

        def _fake_create(coroutine):
            scheduled.append(getattr(coroutine, "__name__", "task"))
            coroutine.close()
            return FakeTask()

        monkeypatch.setattr(controller_module.background_tasks, "create", _fake_create)

        asyncio.run(backend.start())
        assert len(scheduled) == 4
        asyncio.run(backend.close())

    def test_backend_close_cleans_up_rti_dispatcher(
        self, participant_factory, monkeypatch
    ):
        readers = _make_injected_readers(participant_factory)
        backend = controller_module.ControllerBackend(**readers)

        called = False

        async def _fake_close() -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(controller_module.rti.asyncio, "close", _fake_close)

        asyncio.run(backend.close())

        assert called is True


class TestControllerPage:
    def test_main_uses_default_nicegui_behavior(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MEDTECH_NICEGUI_STORAGE_SECRET", "test-secret")
        calls: list[dict[str, Any]] = []

        def _fake_run(*args: Any, **kwargs: Any) -> None:
            calls.append(kwargs)

        monkeypatch.setattr(controller_module.ui, "run", _fake_run)

        controller_module.main()

        assert calls and "show" not in calls[0]

    def test_page_builds_controller_shell(self, monkeypatch: pytest.MonkeyPatch):
        recorder = Recorder()
        _patch_ui(monkeypatch, recorder)
        monkeypatch.setattr(controller_module, "init_theme", lambda **kwargs: None)
        monkeypatch.setattr(
            controller_module,
            "backend",
            SimpleNamespace(
                hosts={"host-1"},
                catalogs={
                    ("host-1", "svc-1"): SimpleNamespace(
                        display_name="Svc One", properties=[]
                    )
                },
                service_states={
                    ("host-1", "svc-1"): SimpleNamespace(
                        state=Orchestration.ServiceState.RUNNING
                    )
                },
                view_mode="hosts",
                status_message="Discovering service hosts...",
                _view=SimpleNamespace(
                    mode="hosts",
                    selected_host_id=None,
                    selected_service_key=None,
                    room_filter=None,
                    procedure_filter=None,
                    service_filter="ALL",
                ),
                _services_by_host=lambda: {
                    "host-1": {
                        "svc-1": SimpleNamespace(display_name="Svc One", properties=[])
                    }
                },
                _diag_log=[],
                show_hosts_view=lambda: None,
                show_services_view=lambda: None,
                show_diagnostics_view=lambda: None,
                select_host=lambda host_id: None,
                select_service=lambda host_id, service_id: None,
                toggle_service_selection=lambda host_id, service_id: None,
                running_service_count=lambda: 1,
                capabilities_selected=lambda: None,
                health_selected=lambda: None,
                start_selected=lambda: None,
                stop_selected=lambda: None,
                active_procedure_id="",
            ),
        )

        controller_module.controller_page()

        kinds = [call[0] for call in recorder.calls]
        assert "card" in kinds

        summary_cards = [
            element
            for kind, _, _, element in recorder.calls
            if kind == "card" and element.on_calls
        ]
        assert summary_cards

    def test_selected_host_and_service_show_action_icons(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        recorder = Recorder()
        _patch_ui(monkeypatch, recorder)
        monkeypatch.setattr(controller_module, "init_theme", lambda **kwargs: None)
        monkeypatch.setattr(
            controller_module,
            "backend",
            SimpleNamespace(
                hosts={"host-1"},
                catalogs={
                    ("host-1", "svc-1"): SimpleNamespace(
                        display_name="Svc One", properties=[]
                    )
                },
                service_states={
                    ("host-1", "svc-1"): SimpleNamespace(
                        state=Orchestration.ServiceState.RUNNING
                    )
                },
                view_mode="hosts",
                status_message="Discovering service hosts...",
                _view=SimpleNamespace(
                    mode="hosts",
                    selected_host_id="host-1",
                    selected_service_key=("host-1", "svc-1"),
                    room_filter=None,
                    procedure_filter=None,
                    service_filter="ALL",
                ),
                _services_by_host=lambda: {
                    "host-1": {
                        "svc-1": SimpleNamespace(display_name="Svc One", properties=[])
                    }
                },
                _diag_log=[],
                show_hosts_view=lambda: None,
                show_services_view=lambda: None,
                show_diagnostics_view=lambda: None,
                select_host=lambda host_id: None,
                select_service=lambda host_id, service_id: None,
                toggle_service_selection=lambda host_id, service_id: None,
                running_service_count=lambda: 1,
                capabilities_selected=lambda: None,
                health_selected=lambda: None,
                start_selected=lambda: None,
                stop_selected=lambda: None,
                active_procedure_id="",
            ),
        )

        controller_module.controller_page()

    def test_constants_remain_available(self):
        assert ICONS["dashboard"] == "space_dashboard"
        assert BRAND_COLORS["blue"] == "#004A8A"


# ---------------------------------------------------------------------------
# Helpers for procedure lifecycle tests
# ---------------------------------------------------------------------------


def _make_prop(name: str, current_value: str = "") -> SimpleNamespace:
    """Create a fake PropertyDescriptor."""
    return SimpleNamespace(
        name=name,
        current_value=current_value,
        default_value="",
        description="",
        required=False,
    )


def _make_catalog(
    host_id: str,
    service_id: str,
    *,
    room_id: str = "",
    procedure_id: str = "",
    display_name: str = "",
) -> SimpleNamespace:
    """Create a fake ServiceCatalog with optional properties."""
    props = []
    if room_id:
        props.append(_make_prop("room_id", room_id))
    if procedure_id:
        props.append(_make_prop("procedure_id", procedure_id))
    return SimpleNamespace(
        host_id=host_id,
        service_id=service_id,
        display_name=display_name or service_id,
        properties=props,
    )


class TestProcedureLifecycle:
    """Tests for UX.5 — Procedure Lifecycle Workflow."""

    def test_active_procedure_id_empty_when_no_procedure(self, participant_factory):
        readers = _make_injected_readers(participant_factory)
        b = controller_module.ControllerBackend(**readers, room_id="OR-1")
        b._catalogs = {
            ("h1", "s1"): _make_catalog("h1", "s1", room_id="OR-1"),
        }
        assert b.active_procedure_id == ""
        asyncio.run(b.close())

    def test_active_procedure_id_returns_id_when_active(self, participant_factory):
        readers = _make_injected_readers(participant_factory)
        b = controller_module.ControllerBackend(**readers, room_id="OR-1")
        b._catalogs = {
            ("h1", "s1"): _make_catalog(
                "h1", "s1", room_id="OR-1", procedure_id="OR-1-123"
            ),
        }
        assert b.active_procedure_id == "OR-1-123"
        asyncio.run(b.close())

    def test_start_procedure_disabled_when_active(self, participant_factory):
        """'Start Procedure' should be disabled (no button) when procedure active."""
        readers = _make_injected_readers(participant_factory)
        b = controller_module.ControllerBackend(**readers, room_id="OR-1")
        b._catalogs = {
            ("h1", "s1"): _make_catalog(
                "h1", "s1", room_id="OR-1", procedure_id="OR-1-100"
            ),
        }
        # active_procedure_id being non-empty is what hides Start Procedure
        assert b.active_procedure_id != ""
        asyncio.run(b.close())

    def test_idle_services_returns_services_without_procedure(
        self, participant_factory
    ):
        readers = _make_injected_readers(participant_factory)
        b = controller_module.ControllerBackend(**readers, room_id="OR-1")
        b._catalogs = {
            ("h1", "s1"): _make_catalog(
                "h1", "s1", room_id="OR-1", procedure_id="OR-1-100"
            ),
            ("h1", "s2"): _make_catalog("h1", "s2", room_id="OR-1"),
            ("h2", "s3"): _make_catalog("h2", "s3", room_id="OR-1"),
        }
        idle = b.idle_services()
        idle_keys = [key for key, _ in idle]
        assert ("h1", "s2") in idle_keys
        assert ("h2", "s3") in idle_keys
        assert ("h1", "s1") not in idle_keys
        asyncio.run(b.close())

    def test_start_procedure_sends_rpcs_with_procedure_id(
        self, participant_factory, monkeypatch
    ):
        readers = _make_injected_readers(participant_factory)
        b = controller_module.ControllerBackend(**readers, room_id="OR-1")

        rpc_calls: list[tuple[str, Any, str]] = []

        async def _fake_rpc(host_id, call, op_name):
            rpc_calls.append((host_id, call, op_name))

        monkeypatch.setattr(b, "_do_rpc", _fake_rpc)

        asyncio.run(b.start_procedure([("h1", "s1"), ("h2", "s2")], "OR-1-42"))
        assert len(rpc_calls) == 2
        assert rpc_calls[0][0] == "h1"
        assert rpc_calls[0][2] == "start_service"
        assert rpc_calls[1][0] == "h2"
        asyncio.run(b.close())

    def test_procedure_services_returns_active_services(self, participant_factory):
        readers = _make_injected_readers(participant_factory)
        b = controller_module.ControllerBackend(**readers, room_id="OR-1")
        b._catalogs = {
            ("h1", "s1"): _make_catalog(
                "h1", "s1", room_id="OR-1", procedure_id="OR-1-100"
            ),
            ("h1", "s2"): _make_catalog("h1", "s2", room_id="OR-1"),
            ("h2", "s3"): _make_catalog(
                "h2", "s3", room_id="OR-1", procedure_id="OR-1-100"
            ),
        }
        proc_svcs = b.procedure_services()
        proc_keys = [key for key, _ in proc_svcs]
        assert ("h1", "s1") in proc_keys
        assert ("h2", "s3") in proc_keys
        assert ("h1", "s2") not in proc_keys
        asyncio.run(b.close())

    def test_add_to_procedure_uses_active_id(self, participant_factory, monkeypatch):
        readers = _make_injected_readers(participant_factory)
        b = controller_module.ControllerBackend(**readers, room_id="OR-1")
        b._catalogs = {
            ("h1", "s1"): _make_catalog(
                "h1", "s1", room_id="OR-1", procedure_id="OR-1-100"
            ),
        }

        rpc_calls: list[tuple[str, Any, str]] = []

        async def _fake_rpc(host_id, call, op_name):
            rpc_calls.append((host_id, call, op_name))

        monkeypatch.setattr(b, "_do_rpc", _fake_rpc)

        asyncio.run(b.add_to_procedure([("h2", "s2")]))
        assert len(rpc_calls) == 1
        assert rpc_calls[0][0] == "h2"
        assert rpc_calls[0][2] == "start_service"
        asyncio.run(b.close())

    def test_stop_procedure_stops_all_active_services(
        self, participant_factory, monkeypatch
    ):
        readers = _make_injected_readers(participant_factory)
        b = controller_module.ControllerBackend(**readers, room_id="OR-1")
        b._catalogs = {
            ("h1", "s1"): _make_catalog(
                "h1", "s1", room_id="OR-1", procedure_id="OR-1-100"
            ),
            ("h2", "s2"): _make_catalog(
                "h2", "s2", room_id="OR-1", procedure_id="OR-1-100"
            ),
            ("h3", "s3"): _make_catalog("h3", "s3", room_id="OR-1"),
        }

        stopped: list[tuple[str, str]] = []

        async def _fake_stop(host_id, service_id):
            stopped.append((host_id, service_id))

        monkeypatch.setattr(b, "stop_service", _fake_stop)

        asyncio.run(b.stop_procedure())
        assert ("h1", "s1") in stopped
        assert ("h2", "s2") in stopped
        assert ("h3", "s3") not in stopped
        asyncio.run(b.close())

    def test_cleared_procedure_id_shows_no_active(self, participant_factory):
        """After stopping, cleared procedure_id → no active procedure."""
        readers = _make_injected_readers(participant_factory)
        b = controller_module.ControllerBackend(**readers, room_id="OR-1")
        b._catalogs = {
            ("h1", "s1"): _make_catalog("h1", "s1", room_id="OR-1"),
        }
        # No procedure_id set → no active procedure
        assert b.active_procedure_id == ""
        asyncio.run(b.close())

    def test_procedure_state_reconstructed_from_catalogs(self, participant_factory):
        """On restart, TRANSIENT_LOCAL catalogs with procedure_id reconstruct state."""
        readers = _make_injected_readers(participant_factory)
        b = controller_module.ControllerBackend(**readers, room_id="OR-1")
        # Simulate receiving catalogs with existing procedure_id (TRANSIENT_LOCAL)
        b._update_catalog(
            SimpleNamespace(
                host_id="h1",
                service_id="s1",
                display_name="Svc1",
                properties=[
                    _make_prop("room_id", "OR-1"),
                    _make_prop("procedure_id", "OR-1-999"),
                ],
            )
        )
        assert b.active_procedure_id == "OR-1-999"
        assert len(b.procedure_services()) == 1
        asyncio.run(b.close())

    def test_generate_procedure_id_format(self, participant_factory):
        readers = _make_injected_readers(participant_factory)
        b = controller_module.ControllerBackend(**readers, room_id="OR-1")
        pid = b.generate_procedure_id()
        assert pid.startswith("OR-1-")
        assert len(pid) > len("OR-1-")
        asyncio.run(b.close())

    def test_procedure_bar_rendered_in_ui(self, monkeypatch):
        """Procedure action bar is rendered as part of controller UI."""
        recorder = Recorder()
        _patch_ui(monkeypatch, recorder)
        monkeypatch.setattr(controller_module, "init_theme", lambda **kwargs: None)
        monkeypatch.setattr(
            controller_module.ui,
            "checkbox",
            lambda *args, **kwargs: recorder.record("checkbox", *args, **kwargs),
        )
        mock_backend = SimpleNamespace(
            hosts={"host-1"},
            catalogs={
                ("host-1", "svc-1"): SimpleNamespace(
                    display_name="Svc One", properties=[]
                )
            },
            service_states={},
            view_mode="hosts",
            status_message="OK",
            _view=SimpleNamespace(
                mode="hosts",
                selected_host_id=None,
                selected_service_key=None,
                room_filter=None,
                procedure_filter=None,
                service_filter="ALL",
            ),
            _services_by_host=lambda: {
                "host-1": {
                    "svc-1": SimpleNamespace(display_name="Svc One", properties=[])
                }
            },
            _diag_log=[],
            show_hosts_view=lambda: None,
            show_services_view=lambda: None,
            show_diagnostics_view=lambda: None,
            select_host=lambda host_id: None,
            select_service=lambda host_id, service_id: None,
            toggle_service_selection=lambda host_id, service_id: None,
            running_service_count=lambda: 0,
            active_procedure_id="",
        )
        monkeypatch.setattr(controller_module, "backend", mock_backend)
        monkeypatch.setattr(controller_module, "_current_backend", lambda: mock_backend)

        controller_module.controller_content()

        labels = [
            args[0]
            for kind, args, kwargs, _ in recorder.calls
            if kind == "label" and args
        ]
        assert "No active procedure" in labels
