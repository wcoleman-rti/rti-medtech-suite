"""Integration tests: Operational Service Host (Step 5.5).

Spec: procedure-orchestration.md — Service Host Framework (Python)
Tags: @integration @orchestration

Tests that the Operational Service Host:
- Publishes ServiceCatalog on startup (TRANSIENT_LOCAL)
- Responds to ServiceHostControl RPC
- Starts/stops CameraService and ProcedureContextService via RPC
- Publishes ServiceStatus transitions (write-on-change)
- Returns ALREADY_RUNNING / NOT_RUNNING on duplicate/invalid ops
"""

import os
import signal
import subprocess
import time

import pytest
import rti.connextdds as dds
from conftest import (
    make_start_call,
    make_stop_call,
    send_rpc,
    wait_for_replier,
    wait_for_status,
)
from orchestration import Orchestration
from rti.rpc import Requester

pytestmark = [
    pytest.mark.integration,
    pytest.mark.orchestration,
    pytest.mark.xdist_group("orch"),
]

ORCHESTRATION_DOMAIN_ID = 15
HOST_ID = "operational-host-test"
ROOM_ID = "OR-1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def operational_service_host():
    """Start the operational-service-host as a subprocess."""
    env = os.environ.copy()
    env["HOST_ID"] = HOST_ID
    env["ROOM_ID"] = ROOM_ID
    env["PROCEDURE_ID"] = "proc-test"

    proc = subprocess.Popen(
        ["python", "-m", "surgical_procedure.operational_service_host"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    # Wait for ServiceCatalog publication instead of fixed sleep
    qos = dds.DomainParticipantQos()
    qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
    probe_dp = dds.DomainParticipant(ORCHESTRATION_DOMAIN_ID, qos)
    probe_dp.enable()
    topic = dds.Topic(probe_dp, "ServiceCatalog", Orchestration.ServiceCatalog)
    rqos = dds.DataReaderQos()
    rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
    rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    probe_reader = dds.DataReader(dds.Subscriber(probe_dp), topic, rqos)
    # Wait for discovery, then for TRANSIENT_LOCAL historical data
    cond = dds.StatusCondition(probe_reader)
    cond.enabled_statuses = dds.StatusMask.SUBSCRIPTION_MATCHED
    ws = dds.WaitSet()
    ws += cond
    ready = False
    try:
        ws.wait(dds.Duration(10))
        probe_reader.wait_for_historical_data(dds.Duration(5))
        ready = True
    except dds.TimeoutError:
        pass
    probe_dp.close()
    assert (
        proc.poll() is None
    ), f"operational-service-host exited immediately with code {proc.returncode}"
    assert ready, "operational-service-host did not publish ServiceCatalog within 10 s"
    yield proc
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="module")
def orch_participant():
    """Create a test participant on the Orchestration domain.

    Transport QoS matches BuiltinQosSnippetLib::Transport.UDP.AvoidIPFragmentation
    used by the XML-configured Orchestration participant.
    """
    qos = dds.DomainParticipantQos()
    qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
    p = dds.DomainParticipant(ORCHESTRATION_DOMAIN_ID, qos)
    p.enable()
    yield p
    p.close()


@pytest.fixture(scope="module")
def catalog_reader(orch_participant):
    """DataReader for ServiceCatalog on the Orchestration domain."""
    topic = dds.Topic(orch_participant, "ServiceCatalog", Orchestration.ServiceCatalog)
    sub = dds.Subscriber(orch_participant)
    rqos = dds.DataReaderQos()
    rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
    rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    rqos.history.kind = dds.HistoryKind.KEEP_LAST
    rqos.history.depth = 1
    r = dds.DataReader(sub, topic, rqos)
    yield r
    r.close()


@pytest.fixture(scope="module")
def status_reader(orch_participant):
    """DataReader for ServiceStatus on the Orchestration domain."""
    topic = dds.Topic(orch_participant, "ServiceStatus", Orchestration.ServiceStatus)
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
def rpc_requester(orch_participant):
    """RPC requester for ServiceHostControl."""
    req = Requester(
        request_type=Orchestration.ServiceHostControl.call_type,
        reply_type=Orchestration.ServiceHostControl.return_type,
        participant=orch_participant,
        service_name=f"ServiceHostControl/{HOST_ID}",
    )
    yield req
    req.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOperationalServiceCatalog:
    """Verify ServiceCatalog publication on startup."""

    def test_service_catalog_published(self, operational_service_host, catalog_reader):
        """Operational Service Host publishes ServiceCatalog for each service."""
        deadline = time.monotonic() + 15.0
        service_ids: set[str] = set()
        while time.monotonic() < deadline:
            for s in catalog_reader.read():
                if s.info.valid and s.data.host_id == HOST_ID:
                    service_ids.add(s.data.service_id)
            if len(service_ids) >= 2:
                break
            time.sleep(0.2)
        assert "CameraService" in service_ids
        assert "ProcedureContextService" in service_ids


class TestOperationalServiceStatus:
    """Verify ServiceStatus publication."""

    def test_initial_status_stopped(self, operational_service_host, status_reader):
        """Operational Service Host publishes initial ServiceStatus STOPPED."""
        cond = dds.StatusCondition(status_reader)
        cond.enabled_statuses = dds.StatusMask.DATA_AVAILABLE
        ws = dds.WaitSet()
        ws += cond

        deadline = time.monotonic() + 15
        svc_ids: set[str] = set()
        while True:
            samples = status_reader.read()
            for s in samples:
                if s.info.valid and s.data.host_id == HOST_ID:
                    svc_ids.add(s.data.service_id)
                    assert s.data.state == Orchestration.ServiceState.STOPPED
            if len(svc_ids) >= 2:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                ws.wait(
                    dds.Duration(int(remaining), int((remaining % 1) * 1_000_000_000))
                )
            except dds.TimeoutError:
                break
        assert "CameraService" in svc_ids
        assert "ProcedureContextService" in svc_ids


class TestOperationalRpcControl:
    """Verify ServiceHostControl RPC operations."""

    def test_rpc_discovery(self, operational_service_host, rpc_requester):
        """RPC requester discovers the ServiceHostControl replier."""
        found = wait_for_replier(rpc_requester, timeout_sec=15)
        assert found, f"Requester did not discover ServiceHostControl/{HOST_ID}"

    def test_get_capabilities(self, operational_service_host, rpc_requester):
        """get_capabilities returns both operational services."""
        wait_for_replier(rpc_requester, timeout_sec=10)
        call = Orchestration.ServiceHostControl.call_type()
        call.get_capabilities = Orchestration.ServiceHostControl.call_type.in_structs[
            -385927898
        ][1]()
        reply = send_rpc(rpc_requester, call)
        assert reply is not None, "No reply received for get_capabilities"
        result = reply.get_capabilities.result.return_
        assert result.capacity == 2

    def test_start_camera_service(
        self, operational_service_host, rpc_requester, status_reader
    ):
        """start_service starts CameraService."""
        wait_for_replier(rpc_requester, timeout_sec=10)
        call = make_start_call("CameraService")
        reply = send_rpc(rpc_requester, call)
        assert reply is not None
        result = reply.start_service.result.return_
        assert result.code == Orchestration.OperationResultCode.OK

        assert wait_for_status(
            status_reader,
            HOST_ID,
            "CameraService",
            Orchestration.ServiceState.RUNNING,
        ), "CameraService never reached RUNNING"

    def test_start_procedure_context(
        self, operational_service_host, rpc_requester, status_reader
    ):
        """start_service starts ProcedureContextService."""
        wait_for_replier(rpc_requester, timeout_sec=10)
        call = make_start_call("ProcedureContextService")
        reply = send_rpc(rpc_requester, call)
        assert reply is not None
        result = reply.start_service.result.return_
        assert result.code == Orchestration.OperationResultCode.OK

        assert wait_for_status(
            status_reader,
            HOST_ID,
            "ProcedureContextService",
            Orchestration.ServiceState.RUNNING,
        ), "ProcedureContextService never reached RUNNING"

    def test_start_already_running(self, operational_service_host, rpc_requester):
        """start_service on already-running service returns ALREADY_RUNNING."""
        wait_for_replier(rpc_requester, timeout_sec=10)
        call = make_start_call("CameraService")
        reply = send_rpc(rpc_requester, call)
        assert reply is not None
        result = reply.start_service.result.return_
        assert result.code == Orchestration.OperationResultCode.ALREADY_RUNNING

    def test_stop_camera_service(
        self, operational_service_host, rpc_requester, status_reader
    ):
        """stop_service stops CameraService."""
        wait_for_replier(rpc_requester, timeout_sec=10)
        call = make_stop_call("CameraService")
        reply = send_rpc(rpc_requester, call)
        assert reply is not None
        result = reply.stop_service.result.return_
        assert result.code == Orchestration.OperationResultCode.OK

        assert wait_for_status(
            status_reader,
            HOST_ID,
            "CameraService",
            Orchestration.ServiceState.STOPPED,
            timeout_sec=10.0,
        ), "CameraService never reached STOPPED"

    def test_stop_non_running(self, operational_service_host, rpc_requester):
        """stop_service on non-running service returns NOT_RUNNING."""
        wait_for_replier(rpc_requester, timeout_sec=10)
        call = make_stop_call("CameraService")
        reply = send_rpc(rpc_requester, call)
        assert reply is not None
        result = reply.stop_service.result.return_
        assert result.code == Orchestration.OperationResultCode.NOT_RUNNING

    def test_stop_procedure_context(
        self, operational_service_host, rpc_requester, status_reader
    ):
        """stop_service stops ProcedureContextService."""
        wait_for_replier(rpc_requester, timeout_sec=10)
        call = make_stop_call("ProcedureContextService")
        reply = send_rpc(rpc_requester, call)
        assert reply is not None
        result = reply.stop_service.result.return_
        assert result.code == Orchestration.OperationResultCode.OK

        assert wait_for_status(
            status_reader,
            HOST_ID,
            "ProcedureContextService",
            Orchestration.ServiceState.STOPPED,
            timeout_sec=10.0,
        ), "ProcedureContextService never reached STOPPED"
