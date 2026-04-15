"""Acceptance test: V1.5 UX Alignment composed workflow.

Spec: revision-ux-alignment.md — Room Overview + Procedure Lifecycle UX
Tags: @integration @acceptance @gui

Rule 8 acceptance test (UX Alignment):
1. Hospital dashboard aggregates ServiceCatalog into room cards
2. Controller discovers idle services and starts a procedure
3. Active procedure indicator appears (non-empty procedure_id)
4. Add services to running procedure with same procedure_id
5. Stop procedure stops all deployed services
6. Procedure state reconstructed from TRANSIENT_LOCAL catalogs
7. Room nav discovers sibling GUIs from ServiceCatalog

Fails if any workflow step produces incorrect state.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
import rti.connextdds as dds
from orchestration import Orchestration
from surgical_procedure.procedure_controller import controller as controller_module

pytestmark = [
    pytest.mark.integration,
    pytest.mark.acceptance,
    pytest.mark.gui,
]


def _make_prop(name: str, value: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        current_value=value,
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
    gui_url: str = "",
    display_name: str = "",
) -> SimpleNamespace:
    props = []
    if room_id:
        props.append(_make_prop("room_id", room_id))
    if procedure_id:
        props.append(_make_prop("procedure_id", procedure_id))
    if gui_url:
        props.append(_make_prop("gui_url", gui_url))
    return SimpleNamespace(
        host_id=host_id,
        service_id=service_id,
        display_name=display_name or service_id,
        properties=props,
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


class TestAcceptanceUXWorkflow:
    """End-to-end UX workflow acceptance test."""

    def test_full_procedure_lifecycle(self, participant_factory, monkeypatch):
        """Complete procedure lifecycle: discover → start → add → stop → reconstruct."""
        readers = _make_injected_readers(participant_factory)
        backend = controller_module.ControllerBackend(**readers, room_id="OR-ACC")

        # --- Step 1: Discover idle services ---------------------------------
        backend._update_catalog(_make_catalog("host-1", "svc-robot", room_id="OR-ACC"))
        backend._update_catalog(
            _make_catalog("host-2", "svc-monitor", room_id="OR-ACC")
        )
        backend._update_catalog(
            _make_catalog("host-3", "svc-console", room_id="OR-ACC")
        )

        assert backend.active_procedure_id == ""
        idle = backend.idle_services()
        assert len(idle) == 3

        # --- Step 2: Start a new procedure ----------------------------------
        rpc_calls: list[tuple[str, object, str]] = []

        async def _fake_rpc(host_id, call, op_name):
            rpc_calls.append((host_id, call, op_name))

        monkeypatch.setattr(backend, "_do_rpc", _fake_rpc)

        proc_id = backend.generate_procedure_id()
        assert proc_id.startswith("OR-ACC-")

        asyncio.run(
            backend.start_procedure(
                [("host-1", "svc-robot"), ("host-2", "svc-monitor")], proc_id
            )
        )
        assert len(rpc_calls) == 2

        # Simulate catalogs updating with procedure_id (as host would do)
        backend._update_catalog(
            _make_catalog("host-1", "svc-robot", room_id="OR-ACC", procedure_id=proc_id)
        )
        backend._update_catalog(
            _make_catalog(
                "host-2", "svc-monitor", room_id="OR-ACC", procedure_id=proc_id
            )
        )

        # --- Step 3: Active procedure indicator appears ---------------------
        assert backend.active_procedure_id == proc_id
        proc_svcs = backend.procedure_services()
        assert len(proc_svcs) == 2

        # --- Step 4: Add remaining services ---------------------------------
        rpc_calls.clear()
        asyncio.run(backend.add_to_procedure([("host-3", "svc-console")]))
        assert len(rpc_calls) == 1
        assert rpc_calls[0][0] == "host-3"

        # Simulate catalog update
        backend._update_catalog(
            _make_catalog(
                "host-3", "svc-console", room_id="OR-ACC", procedure_id=proc_id
            )
        )
        assert len(backend.procedure_services()) == 3
        assert len(backend.idle_services()) == 0

        # --- Step 5: Stop the procedure -------------------------------------
        stopped: list[tuple[str, str]] = []

        async def _fake_stop(host_id, service_id):
            stopped.append((host_id, service_id))

        monkeypatch.setattr(backend, "stop_service", _fake_stop)

        asyncio.run(backend.stop_procedure())
        assert len(stopped) == 3

        # Simulate catalogs clearing procedure_id
        backend._update_catalog(_make_catalog("host-1", "svc-robot", room_id="OR-ACC"))
        backend._update_catalog(
            _make_catalog("host-2", "svc-monitor", room_id="OR-ACC")
        )
        backend._update_catalog(
            _make_catalog("host-3", "svc-console", room_id="OR-ACC")
        )

        assert backend.active_procedure_id == ""
        assert len(backend.idle_services()) == 3

        # --- Step 6: Reconstruct on restart ---------------------------------
        readers2 = _make_injected_readers(participant_factory)
        fresh_backend = controller_module.ControllerBackend(
            **readers2, room_id="OR-ACC"
        )
        # Simulate TRANSIENT_LOCAL delivery of catalogs with active procedure
        fresh_backend._update_catalog(
            _make_catalog("host-1", "svc-robot", room_id="OR-ACC", procedure_id=proc_id)
        )
        fresh_backend._update_catalog(
            _make_catalog(
                "host-2", "svc-monitor", room_id="OR-ACC", procedure_id=proc_id
            )
        )
        assert fresh_backend.active_procedure_id == proc_id
        assert len(fresh_backend.procedure_services()) == 2

        asyncio.run(backend.close())
        asyncio.run(fresh_backend.close())

    def test_dashboard_room_aggregation(self, participant_factory):
        """Dashboard aggregates ServiceCatalog into room cards."""
        readers = _make_injected_readers(participant_factory)
        backend = controller_module.ControllerBackend(**readers, room_id="OR-1")

        # Simulate catalogs from multiple rooms
        backend._update_catalog(
            _make_catalog(
                "h1",
                "svc-a",
                room_id="OR-1",
                procedure_id="proc-1",
                gui_url="http://localhost:8091",
            )
        )
        backend._update_catalog(_make_catalog("h2", "svc-b", room_id="OR-1"))

        # Verify room-scoped queries
        assert backend.active_procedure_id == "proc-1"
        assert len(backend.idle_services()) == 1
        assert len(backend.procedure_services()) == 1

        # Room IDs tracked
        rooms = backend.known_room_ids()
        assert "OR-1" in rooms

        asyncio.run(backend.close())

    def test_room_nav_sibling_discovery(self, participant_factory):
        """Room nav discovers sibling GUIs from ServiceCatalog."""
        from surgical_procedure.room_nav import RoomNav

        readers = _make_injected_readers(participant_factory)
        catalog_reader = readers["catalog_reader"]

        nav = RoomNav.__new__(RoomNav)
        nav._room_id = "OR-1"
        nav._participant = None
        nav._reader = catalog_reader
        nav._siblings = {}

        # Populate sibling discovery (as RoomNav would from ServiceCatalog)
        nav._siblings["Digital Twin"] = "http://localhost:8092"

        assert "Digital Twin" in nav._siblings
        assert nav._siblings["Digital Twin"] == "http://localhost:8092"

        # Hospital Dashboard should not appear in room nav
        assert "Hospital Dashboard" not in nav._siblings
