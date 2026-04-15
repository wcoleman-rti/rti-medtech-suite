"""Acceptance test: Multi-Arm Orchestration workflow (Phase 20).

Spec: phase-20-multi-arm.md — Step 20.9
Tags: @integration @acceptance @multi_arm

Rule 8 acceptance test:
1. Start two Robot Service Hosts (distinct ROBOT_IDs in same room)
2. Issue start_service RPCs for arm-1 at LEFT and arm-2 at RIGHT
3. Both arms reach OPERATIONAL with correct RobotArmAssignment data
4. Both arms publish RobotState on the Procedure DDS domain
5. Stop one arm → dispose() → remaining arm continues unaffected
6. Fails if any component is absent or non-functional
"""

from __future__ import annotations

import os
import signal
import subprocess
import time

import pytest
import rti.connextdds as dds
import surgery
from conftest import (
    make_start_call,
    make_stop_call,
    send_rpc,
    test_participant_qos,
    wait_for_reader_match,
    wait_for_replier,
    wait_for_status,
)
from orchestration import Orchestration
from rti.rpc import Requester

pytestmark = [
    pytest.mark.integration,
    pytest.mark.acceptance,
    pytest.mark.multi_arm,
    pytest.mark.xdist_group("subprocess_dds"),
]

ORCHESTRATION_DOMAIN_ID = 11
PROCEDURE_DOMAIN_ID = 10
ROOM_ID = "OR-MACC"
PROCEDURE_ID = "proc-macc"
HOST_ID_A = "robot-host-macc-a"
HOST_ID_B = "robot-host-macc-b"
ROBOT_ID_A = "arm-macc-a"
ROBOT_ID_B = "arm-macc-b"
SERVICE_ID = "RobotControllerService"
PARTITION = f"room/{ROOM_ID}/procedure/{PROCEDURE_ID}"

RobotArmAssignment = surgery.Surgery.RobotArmAssignment
ArmAssignmentState = surgery.Surgery.ArmAssignmentState
TablePosition = surgery.Surgery.TablePosition
RobotState = surgery.Surgery.RobotState


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------


def _start_robot_host(host_id: str, robot_id: str):
    """Start a robot-service-host subprocess."""
    bin_path = os.path.join(
        os.environ.get("MEDTECH_INSTALL", "install"), "bin", "robot-service-host"
    )
    if not os.path.isfile(bin_path):
        bin_path = os.path.join(
            "build",
            "modules",
            "surgical-procedure",
            "robot_service_host",
            "robot-service-host",
        )
    env = os.environ.copy()
    env["HOST_ID"] = host_id
    env["ROBOT_ID"] = robot_id
    env["ROOM_ID"] = ROOM_ID
    env["PROCEDURE_ID"] = PROCEDURE_ID
    return subprocess.Popen(
        [bin_path],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _terminate_proc(proc, timeout=5):
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _make_requester(participant, host_id):
    """Create an RPC requester for a specific host."""
    return Requester(
        request_type=Orchestration.ServiceHostControl.call_type,
        reply_type=Orchestration.ServiceHostControl.return_type,
        participant=participant,
        service_name=f"ServiceHostControl/{host_id}",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def orch_dp():
    """Orchestration databus participant."""
    qos = test_participant_qos()
    qos.partition.name = ["procedure"]
    dp = dds.DomainParticipant(ORCHESTRATION_DOMAIN_ID, qos)
    dp.enable()
    yield dp
    dp.close()


@pytest.fixture(scope="module")
def control_dp():
    """Procedure DDS domain participant with 'control' tag."""
    qos = test_participant_qos()
    qos.property["dds.domain_participant.domain_tag"] = "control"
    qos.partition.name = [PARTITION]
    dp = dds.DomainParticipant(PROCEDURE_DOMAIN_ID, qos)
    dp.enable()
    yield dp
    dp.close()


@pytest.fixture(scope="module")
def assignment_reader(control_dp):
    """RobotArmAssignment reader on the control tag."""
    topic = dds.Topic(control_dp, "RobotArmAssignment", RobotArmAssignment)
    rqos = dds.DataReaderQos()
    rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
    rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    rqos.history.kind = dds.HistoryKind.KEEP_ALL
    reader = dds.DataReader(dds.Subscriber(control_dp), topic, rqos)
    yield reader
    reader.close()


@pytest.fixture(scope="module")
def state_reader(control_dp):
    """RobotState reader on the control tag."""
    topic = dds.Topic(control_dp, "RobotState", RobotState)
    rqos = dds.DataReaderQos()
    rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
    rqos.history.kind = dds.HistoryKind.KEEP_LAST
    rqos.history.depth = 10
    reader = dds.DataReader(dds.Subscriber(control_dp), topic, rqos)
    yield reader
    reader.close()


@pytest.fixture(scope="module")
def status_reader(orch_dp):
    """ServiceStatus reader on the orchestration domain."""
    topic = dds.Topic(orch_dp, "ServiceStatus", Orchestration.ServiceStatus)
    rqos = dds.DataReaderQos()
    rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
    rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    rqos.history.kind = dds.HistoryKind.KEEP_ALL
    reader = dds.DataReader(dds.Subscriber(orch_dp), topic, rqos)
    yield reader
    reader.close()


@pytest.fixture(scope="module")
def robot_hosts(assignment_reader, state_reader, status_reader, orch_dp):
    """Start both robot service hosts and yield once alive."""
    proc_a = _start_robot_host(HOST_ID_A, ROBOT_ID_A)
    proc_b = _start_robot_host(HOST_ID_B, ROBOT_ID_B)
    time.sleep(1)
    assert proc_a.poll() is None, f"Host A exited immediately: {proc_a.returncode}"
    assert proc_b.poll() is None, f"Host B exited immediately: {proc_b.returncode}"
    yield {"a": proc_a, "b": proc_b}
    _terminate_proc(proc_a)
    _terminate_proc(proc_b)


@pytest.fixture(scope="module")
def requester_a(orch_dp, robot_hosts):
    """RPC requester for host A."""
    req = _make_requester(orch_dp, HOST_ID_A)
    yield req
    req.close()


@pytest.fixture(scope="module")
def requester_b(orch_dp, robot_hosts):
    """RPC requester for host B."""
    req = _make_requester(orch_dp, HOST_ID_B)
    yield req
    req.close()


# ---------------------------------------------------------------------------
# Acceptance Test
# ---------------------------------------------------------------------------


# Module-scoped tracking for positions observed during start tests.
_observed_positions: dict[str, int] = {}


class TestAcceptanceMultiArm:
    """Multi-arm orchestration acceptance test — full workflow."""

    def test_01_start_arm_a_at_left(
        self, robot_hosts, requester_a, status_reader, assignment_reader
    ):
        """Start arm A at LEFT position, verify OPERATIONAL."""
        wait_for_replier(requester_a, timeout_sec=15)

        call = make_start_call(SERVICE_ID, properties=[("table_position", "LEFT")])
        reply = send_rpc(requester_a, call)
        assert reply is not None, "No reply for start_service on host A"
        result = reply.start_service.result.return_
        assert (
            result.code == Orchestration.OperationResultCode.OK
        ), f"start_service A failed: {result.message}"

        assert wait_for_status(
            status_reader, HOST_ID_A, SERVICE_ID, Orchestration.ServiceState.RUNNING
        ), "Host A service never reached RUNNING"

        # Wait for arm to reach OPERATIONAL
        deadline = time.time() + 15
        final_state = None
        while time.time() < deadline:
            for s in assignment_reader.take():
                if s.info.valid and str(s.data.robot_id) == ROBOT_ID_A:
                    final_state = s.data.status
                    _observed_positions[ROBOT_ID_A] = s.data.table_position
            if final_state == ArmAssignmentState.OPERATIONAL:
                break
            time.sleep(0.3)

        assert (
            final_state == ArmAssignmentState.OPERATIONAL
        ), f"Arm A never reached OPERATIONAL; last state: {final_state}"

    def test_02_start_arm_b_at_right(
        self, robot_hosts, requester_b, status_reader, assignment_reader
    ):
        """Start arm B at RIGHT position, verify OPERATIONAL."""
        wait_for_replier(requester_b, timeout_sec=15)

        call = make_start_call(SERVICE_ID, properties=[("table_position", "RIGHT")])
        reply = send_rpc(requester_b, call)
        assert reply is not None, "No reply for start_service on host B"
        result = reply.start_service.result.return_
        assert (
            result.code == Orchestration.OperationResultCode.OK
        ), f"start_service B failed: {result.message}"

        assert wait_for_status(
            status_reader, HOST_ID_B, SERVICE_ID, Orchestration.ServiceState.RUNNING
        ), "Host B service never reached RUNNING"

        deadline = time.time() + 15
        final_state = None
        while time.time() < deadline:
            for s in assignment_reader.take():
                if s.info.valid and str(s.data.robot_id) == ROBOT_ID_B:
                    final_state = s.data.status
                    _observed_positions[ROBOT_ID_B] = s.data.table_position
            if final_state == ArmAssignmentState.OPERATIONAL:
                break
            time.sleep(0.3)

        assert (
            final_state == ArmAssignmentState.OPERATIONAL
        ), f"Arm B never reached OPERATIONAL; last state: {final_state}"

    def test_03_both_arms_publish_robot_state(self, robot_hosts, state_reader):
        """Both arms publish RobotState on the Procedure DDS domain."""
        wait_for_reader_match(state_reader, timeout_sec=10)

        deadline = time.time() + 15
        robot_ids_seen: set[str] = set()
        while time.time() < deadline:
            for s in state_reader.take():
                if s.info.valid:
                    robot_ids_seen.add(str(s.data.robot_id))
            if ROBOT_ID_A in robot_ids_seen and ROBOT_ID_B in robot_ids_seen:
                break
            time.sleep(0.3)

        assert (
            ROBOT_ID_A in robot_ids_seen
        ), f"Arm A ({ROBOT_ID_A}) not publishing RobotState"
        assert (
            ROBOT_ID_B in robot_ids_seen
        ), f"Arm B ({ROBOT_ID_B}) not publishing RobotState"

    def test_04_both_arms_at_distinct_positions(self, robot_hosts):
        """Both arms report distinct table positions in their assignments."""
        # Positions were captured during tests 01 and 02 (write-on-change
        # topic: samples are consumed by take() and not re-published).
        assert ROBOT_ID_A in _observed_positions, "No position recorded for arm A"
        assert ROBOT_ID_B in _observed_positions, "No position recorded for arm B"
        assert _observed_positions[ROBOT_ID_A] != _observed_positions[ROBOT_ID_B], (
            f"Arms should have distinct positions: "
            f"A={_observed_positions[ROBOT_ID_A]}, "
            f"B={_observed_positions[ROBOT_ID_B]}"
        )

    def test_05_stop_arm_a_disposes_assignment(
        self, robot_hosts, requester_a, assignment_reader
    ):
        """Stopping arm A disposes its RobotArmAssignment."""
        call = make_stop_call(SERVICE_ID)
        reply = send_rpc(requester_a, call)
        assert reply is not None, "No reply for stop_service on host A"
        result = reply.stop_service.result.return_
        assert result.code == Orchestration.OperationResultCode.OK

        deadline = time.time() + 10
        disposed = False
        while time.time() < deadline:
            for s in assignment_reader.take():
                if not s.info.valid:
                    if (
                        s.info.state.instance_state
                        == dds.InstanceState.NOT_ALIVE_DISPOSED
                    ):
                        key = assignment_reader.key_value(s.info.instance_handle)
                        if str(key.robot_id) == ROBOT_ID_A:
                            disposed = True
                            break
            if disposed:
                break
            time.sleep(0.2)

        assert disposed, "Arm A assignment not disposed after stop"

    def test_06_remaining_arm_unaffected(self, robot_hosts, state_reader):
        """After stopping arm A, arm B continues publishing RobotState."""
        # RobotState publishes at 100 Hz, so we expect fresh samples
        # from arm B even after arm A was stopped.
        deadline = time.time() + 10
        arm_b_alive = False
        while time.time() < deadline:
            for s in state_reader.take():
                if s.info.valid and str(s.data.robot_id) == ROBOT_ID_B:
                    arm_b_alive = True
                    break
            if arm_b_alive:
                break
            time.sleep(0.3)

        assert (
            arm_b_alive
        ), "Arm B not still publishing RobotState after arm A was stopped"
