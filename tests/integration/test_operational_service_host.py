"""Integration tests: Operational Service Host (Step 5.5).

Spec: procedure-orchestration.md — Service Host Framework (Python)
Tags: @integration @orchestration

Tests that the Operational Service Host:
- Publishes HostCatalog on startup (TRANSIENT_LOCAL)
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
    # Wait for HostCatalog publication instead of fixed sleep
    qos = dds.DomainParticipantQos()
    qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
    probe_dp = dds.DomainParticipant(ORCHESTRATION_DOMAIN_ID, qos)
    probe_dp.enable()
    topic = dds.Topic(probe_dp, "HostCatalog", Orchestration.HostCatalog)
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
    assert ready, "operational-service-host did not publish HostCatalog within 10 s"
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
    """DataReader for HostCatalog on the Orchestration domain."""
    topic = dds.Topic(orch_participant, "HostCatalog", Orchestration.HostCatalog)
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


def _wait_for_data(reader, timeout_sec=10.0, min_count=1):
    """Wait until reader has at least min_count valid samples."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        samples = reader.read()
        valid = [s for s in samples if s.info.valid]
        if len(valid) >= min_count:
            return valid
        time.sleep(0.2)
    return []


def _wait_for_replier(requester, timeout_sec=10.0):
    """Wait until the requester has matched at least one replier."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if requester.matched_replier_count > 0:
            return True
        time.sleep(0.2)
    return False


def _send_rpc(requester, call):
    """Send an RPC call and return the reply."""
    request_id = requester.send_request(call)
    replies = requester.receive_replies(
        max_wait=dds.Duration(seconds=10),
        related_request_id=request_id,
    )
    for reply, info in replies:
        if info.valid:
            return reply
    return None


_CallType = Orchestration.ServiceHostControl.call_type


def _make_start_call(service_id: str) -> object:
    """Build RPC call for start_service."""
    call = _CallType()
    _in = _CallType.in_structs[-522153841][1]()
    _in.req = Orchestration.ServiceRequest(service_id=service_id, configuration="")
    call.start_service = _in
    return call


def _make_stop_call(service_id: str) -> object:
    """Build RPC call for stop_service."""
    call = _CallType()
    _in = _CallType.in_structs[123337698][1]()
    _in.req = Orchestration.ServiceRequest(service_id=service_id, configuration="")
    call.stop_service = _in
    return call


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOperationalHostCatalog:
    """Verify HostCatalog publication on startup."""

    def test_host_catalog_published(self, operational_service_host, catalog_reader):
        """Operational Service Host publishes HostCatalog with services."""
        samples = _wait_for_data(catalog_reader, timeout_sec=15)
        assert len(samples) >= 1, "No HostCatalog samples received"
        matching = [s for s in samples if s.data.host_id == HOST_ID]
        assert matching, f"No HostCatalog for {HOST_ID}"
        catalog = matching[0].data
        assert "CameraService" in catalog.supported_services
        assert "ProcedureContextService" in catalog.supported_services
        assert catalog.capacity == 2


class TestOperationalServiceStatus:
    """Verify ServiceStatus publication."""

    def test_initial_status_stopped(self, operational_service_host, status_reader):
        """Operational Service Host publishes initial ServiceStatus STOPPED."""
        deadline = time.time() + 15
        svc_ids: set[str] = set()
        while time.time() < deadline:
            samples = status_reader.read()
            for s in samples:
                if s.info.valid and s.data.host_id == HOST_ID:
                    svc_ids.add(s.data.service_id)
                    assert s.data.state == Orchestration.ServiceState.STOPPED
            if len(svc_ids) >= 2:
                break
            time.sleep(0.2)
        assert "CameraService" in svc_ids
        assert "ProcedureContextService" in svc_ids


class TestOperationalRpcControl:
    """Verify ServiceHostControl RPC operations."""

    def test_rpc_discovery(self, operational_service_host, rpc_requester):
        """RPC requester discovers the ServiceHostControl replier."""
        found = _wait_for_replier(rpc_requester, timeout_sec=15)
        assert found, f"Requester did not discover ServiceHostControl/{HOST_ID}"

    def test_get_capabilities(self, operational_service_host, rpc_requester):
        """get_capabilities returns both operational services."""
        _wait_for_replier(rpc_requester, timeout_sec=10)
        call = Orchestration.ServiceHostControl.call_type()
        call.get_capabilities = Orchestration.ServiceHostControl.call_type.in_structs[
            -385927898
        ][1]()
        reply = _send_rpc(rpc_requester, call)
        assert reply is not None, "No reply received for get_capabilities"
        result = reply.get_capabilities.result.return_
        assert "CameraService" in result.supported_services
        assert "ProcedureContextService" in result.supported_services
        assert result.capacity == 2

    def test_start_camera_service(
        self, operational_service_host, rpc_requester, status_reader
    ):
        """start_service starts CameraService."""
        _wait_for_replier(rpc_requester, timeout_sec=10)
        call = _make_start_call("CameraService")
        reply = _send_rpc(rpc_requester, call)
        assert reply is not None
        result = reply.start_service.result.return_
        assert result.code == Orchestration.OperationResultCode.OK

        deadline = time.time() + 15
        found_running = False
        while time.time() < deadline:
            samples = status_reader.take()
            for s in samples:
                if (
                    s.info.valid
                    and s.data.host_id == HOST_ID
                    and s.data.service_id == "CameraService"
                    and s.data.state == Orchestration.ServiceState.RUNNING
                ):
                    found_running = True
                    break
            if found_running:
                break
            time.sleep(0.2)
        assert found_running, "CameraService never reached RUNNING"

    def test_start_procedure_context(
        self, operational_service_host, rpc_requester, status_reader
    ):
        """start_service starts ProcedureContextService."""
        _wait_for_replier(rpc_requester, timeout_sec=10)
        call = _make_start_call("ProcedureContextService")
        reply = _send_rpc(rpc_requester, call)
        assert reply is not None
        result = reply.start_service.result.return_
        assert result.code == Orchestration.OperationResultCode.OK

        deadline = time.time() + 15
        found_running = False
        while time.time() < deadline:
            samples = status_reader.take()
            for s in samples:
                if (
                    s.info.valid
                    and s.data.host_id == HOST_ID
                    and s.data.service_id == "ProcedureContextService"
                    and s.data.state == Orchestration.ServiceState.RUNNING
                ):
                    found_running = True
                    break
            if found_running:
                break
            time.sleep(0.2)
        assert found_running, "ProcedureContextService never reached RUNNING"

    def test_start_already_running(self, operational_service_host, rpc_requester):
        """start_service on already-running service returns ALREADY_RUNNING."""
        _wait_for_replier(rpc_requester, timeout_sec=10)
        call = _make_start_call("CameraService")
        reply = _send_rpc(rpc_requester, call)
        assert reply is not None
        result = reply.start_service.result.return_
        assert result.code == Orchestration.OperationResultCode.ALREADY_RUNNING

    def test_stop_camera_service(
        self, operational_service_host, rpc_requester, status_reader
    ):
        """stop_service stops CameraService."""
        _wait_for_replier(rpc_requester, timeout_sec=10)
        call = _make_stop_call("CameraService")
        reply = _send_rpc(rpc_requester, call)
        assert reply is not None
        result = reply.stop_service.result.return_
        assert result.code == Orchestration.OperationResultCode.OK

        deadline = time.time() + 10
        found_stopped = False
        while time.time() < deadline:
            samples = status_reader.take()
            for s in samples:
                if (
                    s.info.valid
                    and s.data.host_id == HOST_ID
                    and s.data.service_id == "CameraService"
                    and s.data.state == Orchestration.ServiceState.STOPPED
                ):
                    found_stopped = True
                    break
            if found_stopped:
                break
            time.sleep(0.2)
        assert found_stopped, "CameraService never reached STOPPED"

    def test_stop_non_running(self, operational_service_host, rpc_requester):
        """stop_service on non-running service returns NOT_RUNNING."""
        _wait_for_replier(rpc_requester, timeout_sec=10)
        call = _make_stop_call("CameraService")
        reply = _send_rpc(rpc_requester, call)
        assert reply is not None
        result = reply.stop_service.result.return_
        assert result.code == Orchestration.OperationResultCode.NOT_RUNNING

    def test_stop_procedure_context(
        self, operational_service_host, rpc_requester, status_reader
    ):
        """stop_service stops ProcedureContextService."""
        _wait_for_replier(rpc_requester, timeout_sec=10)
        call = _make_stop_call("ProcedureContextService")
        reply = _send_rpc(rpc_requester, call)
        assert reply is not None
        result = reply.stop_service.result.return_
        assert result.code == Orchestration.OperationResultCode.OK

        deadline = time.time() + 10
        found_stopped = False
        while time.time() < deadline:
            samples = status_reader.take()
            for s in samples:
                if (
                    s.info.valid
                    and s.data.host_id == HOST_ID
                    and s.data.service_id == "ProcedureContextService"
                    and s.data.state == Orchestration.ServiceState.STOPPED
                ):
                    found_stopped = True
                    break
            if found_stopped:
                break
            time.sleep(0.2)
        assert found_stopped, "ProcedureContextService never reached STOPPED"
