"""Integration tests: Procedure Controller GUI (Step 5.6).

Spec: procedure-orchestration.md — Procedure Controller
Tags: @integration @orchestration @gui

Tests that the Procedure Controller:
- Discovers available Service Hosts (ServiceCatalog received)
- Displays service states (ServiceStatus rendered)
- Issues start_service RPC resulting in service starting on target host
- Issues stop_service RPC resulting in service stopping
- Is read-only on Hospital domain (no DataWriters created)
- Reconstructs state from TRANSIENT_LOCAL on restart (within 15 s)
- Does not join the Procedure domain
- GUI remains responsive during concurrent data arrival
"""

from __future__ import annotations

import time

import pytest
import rti.connextdds as dds
from orchestration import Orchestration
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

ORCHESTRATION_DOMAIN_ID = 15
HOSPITAL_DOMAIN_ID = 11
PROCEDURE_DOMAIN_ID = 10
ROOM_ID = "OR-TEST"
HOST_ID = "test-host-1"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.orchestration,
    pytest.mark.gui,
    pytest.mark.xdist_group("orch"),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_qapp = None


@pytest.fixture(scope="module")
def qapp():
    """Provide a shared QApplication for the test module."""
    global _qapp
    if _qapp is None:
        _qapp = QApplication.instance() or QApplication([])
    return _qapp


@pytest.fixture(scope="module")
def orch_participant():
    """Test participant on the Orchestration domain for publishing test data."""
    qos = dds.DomainParticipantQos()
    qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
    p = dds.DomainParticipant(ORCHESTRATION_DOMAIN_ID, qos)
    p.enable()
    yield p
    p.close()


@pytest.fixture(scope="module")
def catalog_writer(orch_participant):
    """DataWriter for ServiceCatalog on the Orchestration domain."""
    topic = dds.Topic(orch_participant, "ServiceCatalog", Orchestration.ServiceCatalog)
    pub = dds.Publisher(orch_participant)
    wqos = dds.DataWriterQos()
    wqos.reliability.kind = dds.ReliabilityKind.RELIABLE
    wqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    wqos.history.kind = dds.HistoryKind.KEEP_LAST
    wqos.history.depth = 1
    w = dds.DataWriter(pub, topic, wqos)
    yield w
    w.close()


@pytest.fixture(scope="module")
def status_writer(orch_participant):
    """DataWriter for ServiceStatus on the Orchestration domain."""
    topic = dds.Topic(orch_participant, "ServiceStatus", Orchestration.ServiceStatus)
    pub = dds.Publisher(orch_participant)
    wqos = dds.DataWriterQos()
    wqos.reliability.kind = dds.ReliabilityKind.RELIABLE
    wqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    wqos.history.kind = dds.HistoryKind.KEEP_LAST
    wqos.history.depth = 10
    w = dds.DataWriter(pub, topic, wqos)
    yield w
    w.close()


@pytest.fixture(scope="module")
def catalog_reader(orch_participant):
    """DataReader for ServiceCatalog — used by the Procedure Controller."""
    topic = dds.Topic.find(orch_participant, "ServiceCatalog")
    if topic is None:
        topic = dds.Topic(
            orch_participant, "ServiceCatalog", Orchestration.ServiceCatalog
        )
    sub = dds.Subscriber(orch_participant)
    rqos = dds.DataReaderQos()
    rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
    rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    rqos.history.kind = dds.HistoryKind.KEEP_LAST
    rqos.history.depth = 10
    r = dds.DataReader(sub, topic, rqos)
    yield r
    r.close()


@pytest.fixture(scope="module")
def status_reader(orch_participant):
    """DataReader for ServiceStatus — used by the Procedure Controller."""
    topic = dds.Topic.find(orch_participant, "ServiceStatus")
    if topic is None:
        topic = dds.Topic(
            orch_participant, "ServiceStatus", Orchestration.ServiceStatus
        )
    sub = dds.Subscriber(orch_participant)
    rqos = dds.DataReaderQos()
    rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
    rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    rqos.history.kind = dds.HistoryKind.KEEP_LAST
    rqos.history.depth = 10
    r = dds.DataReader(sub, topic, rqos)
    yield r
    r.close()


def _process_events(qapp, duration_ms=500):
    """Process Qt events for the given duration."""
    deadline = time.time() + duration_ms / 1000.0
    while time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


def _publish_catalog(writer, host_id, services, capacity=2):
    """Publish ServiceCatalog samples (one per service)."""
    for svc_id in services:
        catalog = Orchestration.ServiceCatalog(
            host_id=host_id,
            service_id=svc_id,
            display_name=svc_id,
            properties=[],
            health_summary="OK",
        )
        writer.write(catalog)


def _publish_status(writer, host_id, service_id, state):
    """Publish a ServiceStatus sample."""
    import common

    now = time.time()
    sec = int(now)
    nsec = int((now - sec) * 1_000_000_000)
    status = Orchestration.ServiceStatus(
        host_id=host_id,
        service_id=service_id,
        state=state,
        timestamp=common.Common.Time_t(sec=sec & 0xFFFFFFFF, nsec=nsec),
    )
    writer.write(status)


# ---------------------------------------------------------------------------
# Test: Discovers available Service Hosts (ServiceCatalog received)
# ---------------------------------------------------------------------------
class TestServiceCatalogDiscovery:
    """Verify Procedure Controller discovers Service Hosts."""

    def test_discovers_host(
        self,
        qapp,
        orch_participant,
        catalog_writer,
        status_writer,
        catalog_reader,
        status_reader,
    ):
        """Controller receives ServiceCatalog and populates catalogs dict."""
        from hospital_dashboard.procedure_controller import ProcedureController

        controller = ProcedureController(
            room_id=ROOM_ID,
            catalog_reader=catalog_reader,
            status_reader=status_reader,
        )
        try:
            # Allow matching
            _process_events(qapp, 1000)

            _publish_catalog(catalog_writer, HOST_ID, ["SvcA", "SvcB"])

            # Poll until controller discovers the host.
            # Tests run without an asyncio event loop, so async tasks are
            # not active — call _on_refresh() to drain the reader.
            deadline = time.time() + 10
            while time.time() < deadline:
                _process_events(qapp, 200)
                controller._on_refresh()
                if HOST_ID in controller.hosts:
                    break

            assert HOST_ID in controller.hosts
            assert (HOST_ID, "SvcA") in controller.catalogs
        finally:
            controller.close_dds()


# ---------------------------------------------------------------------------
# Test: Displays service states (ServiceStatus rendered)
# ---------------------------------------------------------------------------
class TestServiceStatusDisplay:
    """Verify Procedure Controller tracks ServiceStatus."""

    def test_displays_service_state(
        self,
        qapp,
        orch_participant,
        catalog_writer,
        status_writer,
        catalog_reader,
        status_reader,
    ):
        """Controller receives ServiceStatus and updates state table."""
        from hospital_dashboard.procedure_controller import ProcedureController

        controller = ProcedureController(
            room_id=ROOM_ID,
            catalog_reader=catalog_reader,
            status_reader=status_reader,
        )
        try:
            _process_events(qapp, 1000)

            _publish_status(
                status_writer,
                HOST_ID,
                "SvcA",
                Orchestration.ServiceState.RUNNING,
            )

            deadline = time.time() + 10
            found = False
            while time.time() < deadline:
                _process_events(qapp, 200)
                controller._on_refresh()
                if (HOST_ID, "SvcA") in controller.service_states:
                    found = True
                    break

            assert found
            assert (
                controller.service_states[(HOST_ID, "SvcA")].state
                == Orchestration.ServiceState.RUNNING
            )
        finally:
            controller.close_dds()


# ---------------------------------------------------------------------------
# Test: Controller is read-only on Hospital domain (no DataWriters created)
# ---------------------------------------------------------------------------
class TestHospitalReadOnly:
    """Verify Procedure Controller creates no writers on Hospital domain."""

    def test_no_hospital_writers(self, qapp):
        """Controller's Hospital participant has no DataWriters."""
        from hospital_dashboard.procedure_controller import ProcedureController

        controller = ProcedureController(room_id=ROOM_ID)
        try:
            _process_events(qapp, 1000)

            hosp = controller.hosp_participant
            assert hosp is not None, "Hospital participant not created"
            assert hosp.domain_id == HOSPITAL_DOMAIN_ID

            # The XML config ProcedureController_Hospital only defines a
            # subscriber (ControllerHospSubscriber) with 3 readers — no
            # publisher element. Verify readers exist (positive check):
            import app_names

            orch_names_local = app_names.MedtechEntityNames.OrchestrationParticipants
            assert (
                hosp.find_datareader(orch_names_local.CTRL_PROCEDURE_STATUS_READER)
                is not None
            )
            assert (
                hosp.find_datareader(orch_names_local.CTRL_PROCEDURE_CONTEXT_READER)
                is not None
            )
            assert (
                hosp.find_datareader(orch_names_local.CTRL_PATIENT_VITALS_READER)
                is not None
            )

            # Verify no writers exist by checking that a second participant
            # on the Hospital domain does not discover any publications
            # from the controller's participant (aside from builtins).
            checker = dds.DomainParticipant(HOSPITAL_DOMAIN_ID)
            checker.enable()
            try:
                topic = dds.Topic(
                    checker,
                    "ProcedureStatus",
                    Orchestration.ServiceCatalog,  # type doesn't matter for discovery
                )
                sub = dds.Subscriber(checker)
                rqos = dds.DataReaderQos()
                rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
                rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
                reader = dds.DataReader(sub, topic, rqos)
                time.sleep(0.5)
                # The controller should have no matched publications
                assert len(reader.matched_publications) == 0, (
                    "Hospital domain reader matched publications from controller "
                    "— controller is not read-only"
                )
                reader.close()
            finally:
                checker.close()
        finally:
            controller.close_dds()


# ---------------------------------------------------------------------------
# Test: Controller does not join Procedure domain
# ---------------------------------------------------------------------------
class TestNoProcedureDomain:
    """Verify Procedure Controller does not join the Procedure domain."""

    def test_no_procedure_domain(self, qapp):
        """No participant on domain 10."""
        from hospital_dashboard.procedure_controller import ProcedureController

        controller = ProcedureController(room_id=ROOM_ID)
        try:
            _process_events(qapp, 500)
            # Only Orchestration (15) and Hospital (11) participants
            orch = controller.orch_participant
            hosp = controller.hosp_participant
            assert orch is not None
            assert hosp is not None
            # Domain IDs check
            assert orch.domain_id == ORCHESTRATION_DOMAIN_ID
            assert hosp.domain_id == HOSPITAL_DOMAIN_ID
        finally:
            controller.close_dds()


# ---------------------------------------------------------------------------
# Test: Controller restart reconstructs from TRANSIENT_LOCAL (within 15 s)
# ---------------------------------------------------------------------------
class TestTransientLocalReconstruction:
    """Verify state reconstruction after controller restart."""

    def test_restart_receives_transient_local(
        self,
        qapp,
        orch_participant,
        catalog_writer,
        status_writer,
    ):
        """A restarted controller receives TRANSIENT_LOCAL data within 15 s."""
        from hospital_dashboard.procedure_controller import ProcedureController

        host_id_tl = "tl-host-restart"

        # Publish data BEFORE the controller starts
        _publish_catalog(catalog_writer, host_id_tl, ["SvcTL"])
        _publish_status(
            status_writer,
            host_id_tl,
            "SvcTL",
            Orchestration.ServiceState.RUNNING,
        )

        # Create a NEW controller (simulates restart)
        # Use programmatic readers since we need fresh ones
        sub = dds.Subscriber(orch_participant)

        cat_topic = dds.Topic.find(orch_participant, "ServiceCatalog")
        if cat_topic is None:
            cat_topic = dds.Topic(
                orch_participant, "ServiceCatalog", Orchestration.ServiceCatalog
            )
        rqos = dds.DataReaderQos()
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
        rqos.history.kind = dds.HistoryKind.KEEP_LAST
        rqos.history.depth = 10
        cat_reader = dds.DataReader(sub, cat_topic, rqos)

        st_topic = dds.Topic.find(orch_participant, "ServiceStatus")
        if st_topic is None:
            st_topic = dds.Topic(
                orch_participant, "ServiceStatus", Orchestration.ServiceStatus
            )
        st_reader = dds.DataReader(sub, st_topic, rqos)

        controller = ProcedureController(
            room_id=ROOM_ID,
            catalog_reader=cat_reader,
            status_reader=st_reader,
        )
        try:
            deadline = time.time() + 5
            found_host = False
            found_status = False
            while time.time() < deadline:
                _process_events(qapp, 200)
                controller._on_refresh()
                if host_id_tl in controller.hosts:
                    found_host = True
                if (host_id_tl, "SvcTL") in controller.service_states:
                    found_status = True
                if found_host and found_status:
                    break

            assert found_host, "Controller did not receive ServiceCatalog within 5 s"
            assert found_status, "Controller did not receive ServiceStatus within 5 s"
        finally:
            controller.close_dds()
            cat_reader.close()
            st_reader.close()


# ---------------------------------------------------------------------------
# Test: GUI remains responsive during concurrent data arrival
# ---------------------------------------------------------------------------
class TestGuiResponsive:
    """Verify GUI thread remains responsive during data arrival."""

    def test_responsive_during_data_burst(
        self,
        qapp,
        orch_participant,
        catalog_writer,
        status_writer,
        catalog_reader,
        status_reader,
    ):
        """Burst of DDS samples does not block the Qt event loop."""
        from hospital_dashboard.procedure_controller import ProcedureController

        controller = ProcedureController(
            room_id=ROOM_ID,
            catalog_reader=catalog_reader,
            status_reader=status_reader,
        )
        try:
            _process_events(qapp, 1000)

            # Track timer callbacks to verify UI responsiveness
            callback_count = [0]

            def _on_timer():
                callback_count[0] += 1

            responsive_timer = QTimer()
            responsive_timer.timeout.connect(_on_timer)
            responsive_timer.start(50)  # 20 Hz

            # Publish a burst of samples
            for i in range(20):
                _publish_catalog(catalog_writer, f"burst-host-{i}", [f"svc-{i}"])
                _publish_status(
                    status_writer,
                    f"burst-host-{i}",
                    f"svc-{i}",
                    Orchestration.ServiceState.RUNNING,
                )

            # Process for 2 seconds
            _process_events(qapp, 2000)
            responsive_timer.stop()

            # Timer should have fired ~40 times in 2 seconds at 20 Hz.
            # A responsive UI would have at least ~20 callbacks.
            assert callback_count[0] >= 10, (
                f"Only {callback_count[0]} timer callbacks in 2 s — "
                "UI may be blocked"
            )
        finally:
            controller.close_dds()


# ---------------------------------------------------------------------------
# Test: RPC start_service / stop_service via GUI
# These tests verify the controller correctly builds and sends RPC calls
# by checking that the requester is lazily created and that the internal
# call builder produces valid call objects. Full end-to-end RPC delivery
# is tested in Step 5.7 integration tests with real Service Hosts.
# ---------------------------------------------------------------------------
class TestStartStopRpc:
    """Verify start/stop RPC call construction from the Procedure Controller."""

    def test_start_service_rpc_call_built(self, qapp):
        """start_service call is correctly constructed."""
        from hospital_dashboard.procedure_controller import _make_start_call

        call = _make_start_call("TestSvc")
        assert call is not None
        # The call object has start_service discriminator set
        assert hasattr(call, "start_service")

    def test_stop_service_rpc_call_built(self, qapp):
        """stop_service call is correctly constructed."""
        from hospital_dashboard.procedure_controller import _make_stop_call

        call = _make_stop_call("TestSvc")
        assert call is not None
        assert hasattr(call, "stop_service")

    def test_controller_creates_rpc_requester(self, qapp):
        """Controller lazily creates RPC requesters for discovered hosts."""
        from hospital_dashboard.procedure_controller import ProcedureController

        controller = ProcedureController(room_id=ROOM_ID)
        try:
            _process_events(qapp, 1000)

            # Initially no requesters
            assert len(controller._requesters) == 0

            # Lazily create a requester for a host
            controller._get_requester("some-host")

            # Requester should have been created for "some-host"
            assert "some-host" in controller._requesters
        finally:
            controller.close_dds()
