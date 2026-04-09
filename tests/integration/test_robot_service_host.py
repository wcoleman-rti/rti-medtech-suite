"""Integration tests: Robot Service Host (Step 5.4).

Spec: procedure-orchestration.md — Service Host Framework
Tags: @integration @orchestration

Tests that the Robot Service Host:
- Publishes ServiceCatalog on startup (TRANSIENT_LOCAL)
- Responds to ServiceHostControl RPC at the correct service_name
- Starts/stops the RobotControllerService via RPC
- Publishes ServiceStatus transitions (write-on-change)
- Returns ALREADY_RUNNING / NOT_RUNNING on duplicate/invalid ops
- Maintains Orchestration / Procedure domain isolation
"""

import os
import signal
import subprocess

import pytest
import rti.connextdds as dds
from conftest import (
    make_start_call,
    make_stop_call,
    send_rpc,
    wait_for_data,
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
PROCEDURE_DOMAIN_ID = 10
HOST_ID = "robot-host-test"
ROOM_ID = "OR-1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def robot_service_host():
    """Start the robot-service-host binary as a subprocess and yield it.

    Waits for the process to publish ServiceCatalog, then tears it down
    after the module.
    """
    bin_path = os.path.join(
        os.environ.get("MEDTECH_INSTALL", "install"), "bin", "robot-service-host"
    )
    if not os.path.isfile(bin_path):
        # Fall back to build directory
        bin_path = os.path.join(
            "build",
            "modules",
            "surgical-procedure",
            "robot_service_host",
            "robot-service-host",
        )
    env = os.environ.copy()
    env["HOST_ID"] = HOST_ID
    env["ROOM_ID"] = ROOM_ID
    env["PROCEDURE_ID"] = "proc-test"

    proc = subprocess.Popen(
        [bin_path],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    # Wait for ServiceCatalog publication instead of fixed sleep
    qos = dds.DomainParticipantQos()
    qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
    qos.partition.name = ["procedure"]
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
    ), f"robot-service-host exited immediately with code {proc.returncode}"
    assert ready, "robot-service-host did not publish ServiceCatalog within 10 s"
    yield proc
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=3)
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
    qos.partition.name = ["procedure"]
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


class TestServiceCatalog:
    """Verify ServiceCatalog publication on startup."""

    def test_service_catalog_published(self, robot_service_host, catalog_reader):
        """Robot Service Host publishes ServiceCatalog with correct host_id
        and service_id."""
        cond = dds.QueryCondition(
            dds.Query(
                catalog_reader,
                f"host_id = '{HOST_ID}'"
                " AND service_id = 'RobotControllerService'"
                " AND display_name = 'Robot Controller'",
            ),
            dds.DataState.any_data,
        )
        assert wait_for_data(
            catalog_reader, timeout_sec=15, conditions=[(cond, 1)]
        ), f"No ServiceCatalog for {HOST_ID}/RobotControllerService"

    def test_service_catalog_transient_local(
        self, robot_service_host, orch_participant
    ):
        """A late-joining reader receives ServiceCatalog via TRANSIENT_LOCAL."""
        # Reuse existing topic (already created by catalog_reader fixture)
        topic = dds.Topic.find(orch_participant, "ServiceCatalog")
        sub = dds.Subscriber(orch_participant)
        rqos = dds.DataReaderQos()
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
        rqos.history.kind = dds.HistoryKind.KEEP_LAST
        rqos.history.depth = 1
        late_reader = dds.DataReader(sub, topic, rqos)
        try:
            cond = dds.QueryCondition(
                dds.Query(
                    late_reader,
                    f"host_id = '{HOST_ID}'"
                    " AND service_id = 'RobotControllerService'"
                    " AND display_name = 'Robot Controller'",
                ),
                dds.DataState.any_data,
            )
            assert wait_for_data(
                late_reader, timeout_sec=10, conditions=[(cond, 1)]
            ), f"Late-joining reader did not receive ServiceCatalog for {HOST_ID}"
        finally:
            late_reader.close()


class TestServiceStatus:
    """Verify ServiceStatus publication."""

    def test_initial_status_stopped(self, robot_service_host, status_reader):
        """Robot Service Host publishes initial ServiceStatus with STOPPED."""
        cond = dds.QueryCondition(
            dds.Query(
                status_reader,
                f"host_id = '{HOST_ID}'" " AND service_id = 'RobotControllerService'",
            ),
            dds.DataState.any_data,
        )
        assert wait_for_data(
            status_reader, timeout_sec=15, conditions=[(cond, 1)]
        ), f"No ServiceStatus for {HOST_ID}"
        status = status_reader.select().condition(cond).read_data()[0]
        assert status.state == Orchestration.ServiceState.STOPPED


class TestRpcServiceControl:
    """Verify ServiceHostControl RPC operations."""

    def test_rpc_discovery(self, robot_service_host, rpc_requester):
        """RPC requester discovers the ServiceHostControl replier."""
        found = wait_for_replier(rpc_requester, timeout_sec=15)
        assert found, f"RPC requester did not discover ServiceHostControl/{HOST_ID}"

    def test_get_capabilities(self, robot_service_host, rpc_requester):
        """get_capabilities returns supported services."""
        wait_for_replier(rpc_requester, timeout_sec=10)
        call = Orchestration.ServiceHostControl.call_type()
        # get_capabilities takes no parameters — use the In struct directly
        # The union discriminator selects get_capabilities when set
        call.get_capabilities = Orchestration.ServiceHostControl.call_type.in_structs[
            -385927898
        ][1]()
        reply = send_rpc(rpc_requester, call)
        assert reply is not None, "No reply received for get_capabilities"
        result = reply.get_capabilities.result.return_
        assert result.capacity >= 1

    def test_get_health(self, robot_service_host, rpc_requester):
        """get_health returns alive=True."""
        wait_for_replier(rpc_requester, timeout_sec=10)
        call = Orchestration.ServiceHostControl.call_type()
        call.get_health = Orchestration.ServiceHostControl.call_type.in_structs[
            -1076937166
        ][1]()
        reply = send_rpc(rpc_requester, call)
        assert reply is not None, "No reply received for get_health"
        result = reply.get_health.result.return_
        assert result.alive

    def test_stop_non_running_returns_not_running(
        self, robot_service_host, rpc_requester
    ):
        """stop_service on a non-running service returns NOT_RUNNING."""
        wait_for_replier(rpc_requester, timeout_sec=10)
        call = make_stop_call("RobotControllerService")
        reply = send_rpc(rpc_requester, call)
        assert reply is not None, "No reply received for stop_service"
        result = reply.stop_service.result.return_
        assert result.code == Orchestration.OperationResultCode.NOT_RUNNING

    def test_start_service_ok(self, robot_service_host, rpc_requester, status_reader):
        """start_service creates and starts the RobotControllerService."""
        wait_for_replier(rpc_requester, timeout_sec=10)
        call = make_start_call("RobotControllerService")
        reply = send_rpc(rpc_requester, call)
        assert reply is not None, "No reply received for start_service"
        assert (
            reply.discriminator != 0
        ), f"RPC returned remote exception (remoteEx={reply.remoteEx})"
        result = reply.start_service.result.return_
        assert result.code == Orchestration.OperationResultCode.OK

        # Wait for RUNNING state to be published via ServiceStatus
        assert wait_for_status(
            status_reader,
            HOST_ID,
            "RobotControllerService",
            Orchestration.ServiceState.RUNNING,
        ), "ServiceStatus never reached RUNNING"

    def test_start_already_running_returns_already_running(
        self, robot_service_host, rpc_requester
    ):
        """start_service on an already-running service returns ALREADY_RUNNING."""
        # Service was started by the previous test (module-scoped host)
        wait_for_replier(rpc_requester, timeout_sec=10)
        call = make_start_call("RobotControllerService")
        reply = send_rpc(rpc_requester, call)
        assert reply is not None, "No reply received for start_service"
        result = reply.start_service.result.return_
        assert result.code == Orchestration.OperationResultCode.ALREADY_RUNNING

    def test_stop_service_ok(self, robot_service_host, rpc_requester, status_reader):
        """stop_service stops the running service and publishes STOPPED."""
        wait_for_replier(rpc_requester, timeout_sec=10)
        call = make_stop_call("RobotControllerService")
        reply = send_rpc(rpc_requester, call)
        assert reply is not None, "No reply received for stop_service"
        result = reply.stop_service.result.return_
        assert result.code == Orchestration.OperationResultCode.OK

        # Verify STOPPED state published
        assert wait_for_status(
            status_reader,
            HOST_ID,
            "RobotControllerService",
            Orchestration.ServiceState.STOPPED,
            timeout_sec=10.0,
        ), "ServiceStatus never reached STOPPED after stop"


class TestDomainIsolation:
    """Verify Orchestration domain is isolated from Procedure domain."""

    def test_orchestration_isolated_from_procedure(self, robot_service_host):
        """A Procedure domain participant does not discover Orchestration
        entities."""
        proc_qos = dds.DomainParticipant.default_participant_qos
        proc_qos.partition.name = [f"room/{ROOM_ID}/procedure/proc-test"]
        proc_participant = dds.DomainParticipant(PROCEDURE_DOMAIN_ID, proc_qos)
        proc_participant.enable()

        try:
            # Create a reader on the Procedure domain for ServiceCatalog topic
            # — this topic should not exist on domain 10
            topic = dds.Topic(
                proc_participant,
                "ServiceCatalog",
                Orchestration.ServiceCatalog,
            )
            sub = dds.Subscriber(proc_participant)
            rqos = dds.DataReaderQos()
            rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
            rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
            reader = dds.DataReader(sub, topic, rqos)

            # Should receive nothing — domains are isolated
            assert not wait_for_data(
                reader, timeout_sec=1
            ), "Procedure domain received ServiceCatalog — isolation broken"
            reader.close()
        finally:
            proc_participant.close()
