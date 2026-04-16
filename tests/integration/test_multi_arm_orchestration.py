"""Tests for Step 20.7 — Multi-Arm Orchestration Flow Integration.

Spec coverage: multi-arm-orchestration.md — Full orchestration flow
Tags: @integration @multi-arm

Verifies the end-to-end flow:
1. start_service RPC with table_position property
2. Robot service host starts arm with correct position
3. Arm publishes ASSIGNED → POSITIONING → OPERATIONAL
4. stop_service removes arm (dispose)
5. Multiple arms at distinct positions coexist
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
    wait_for_reader_match,
    wait_for_replier,
    wait_for_status,
)
from orchestration import Orchestration
from rti.rpc import Requester

pytestmark = [
    pytest.mark.integration,
    pytest.mark.xdist_group("subprocess_dds"),
]

ORCHESTRATION_DOMAIN_ID = 11
PROCEDURE_DOMAIN_ID = 10
ROOM_ID = "OR-MARM"
PROCEDURE_ID = "proc-marm"
HOST_ID_1 = "robot-host-marm-1"
HOST_ID_2 = "robot-host-marm-2"
SERVICE_ID = "RobotControllerService"
PARTITION = f"room/{ROOM_ID}/procedure/{PROCEDURE_ID}"

RobotArmAssignment = surgery.Surgery.RobotArmAssignment
ArmAssignmentState = surgery.Surgery.ArmAssignmentState
TablePosition = surgery.Surgery.TablePosition


# ---------------------------------------------------------------------------
# Helpers
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def orch_dp():
    """Orchestration databus participant."""
    qos = dds.DomainParticipantQos()
    qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
    qos.partition.name = [f"room/{ROOM_ID}"]
    dp = dds.DomainParticipant(ORCHESTRATION_DOMAIN_ID, qos)
    dp.enable()
    yield dp
    dp.close()


@pytest.fixture(scope="module")
def control_dp():
    """Procedure DDS domain participant with 'control' tag."""
    qos = dds.DomainParticipantQos()
    qos.property["dds.domain_participant.domain_tag"] = "control"
    qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
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


def _make_rpc_requester(orch_dp, host_id):
    """Create an RPC requester for a specific host."""
    return Requester(
        request_type=Orchestration.ServiceHostControl.call_type,
        reply_type=Orchestration.ServiceHostControl.return_type,
        participant=orch_dp,
        service_name=f"ServiceHostControl/{host_id}",
    )


@pytest.fixture(scope="module")
def robot_host_1(assignment_reader, status_reader, orch_dp):
    """Start first robot service host."""
    proc = _start_robot_host(HOST_ID_1, "arm-marm-1")
    time.sleep(1)
    assert proc.poll() is None, f"Host 1 exited immediately: {proc.returncode}"
    yield proc
    _terminate_proc(proc)


@pytest.fixture(scope="module")
def robot_host_2(assignment_reader, status_reader, orch_dp):
    """Start second robot service host."""
    proc = _start_robot_host(HOST_ID_2, "arm-marm-2")
    time.sleep(1)
    assert proc.poll() is None, f"Host 2 exited immediately: {proc.returncode}"
    yield proc
    _terminate_proc(proc)


@pytest.fixture(scope="module")
def requester_1(orch_dp, robot_host_1):
    """RPC requester for host 1."""
    req = _make_rpc_requester(orch_dp, HOST_ID_1)
    yield req
    req.close()


@pytest.fixture(scope="module")
def requester_2(orch_dp, robot_host_2):
    """RPC requester for host 2."""
    req = _make_rpc_requester(orch_dp, HOST_ID_2)
    yield req
    req.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStartServiceWithTablePosition:
    """start_service RPC passes table_position to the arm service."""

    def test_01_start_arm_with_table_position(
        self, robot_host_1, requester_1, status_reader, assignment_reader
    ):
        """Start arm with table_position=RIGHT, verify it reaches OPERATIONAL."""
        wait_for_replier(requester_1, timeout_sec=10)

        call = make_start_call(
            SERVICE_ID,
            properties=[
                ("room_id", ROOM_ID),
                ("procedure_id", PROCEDURE_ID),
                ("table_position", "RIGHT"),
            ],
        )
        reply = send_rpc(requester_1, call)
        assert reply is not None, "No reply for start_service"
        result = reply.start_service.result.return_
        assert result.code == Orchestration.OperationResultCode.OK

        # Wait for RUNNING on orchestration
        assert wait_for_status(
            status_reader,
            HOST_ID_1,
            SERVICE_ID,
            Orchestration.ServiceState.RUNNING,
        ), "Service never reached RUNNING"

        # Wait for arm to reach OPERATIONAL on procedure control
        wait_for_reader_match(assignment_reader, timeout_sec=10)
        deadline = time.time() + 15
        final_state = None
        final_position = None
        while time.time() < deadline:
            samples = assignment_reader.take()
            for s in samples:
                if s.info.valid:
                    final_state = s.data.status
                    final_position = s.data.table_position
            if final_state == ArmAssignmentState.OPERATIONAL:
                break
            time.sleep(0.3)

        assert (
            final_state == ArmAssignmentState.OPERATIONAL
        ), f"Arm never reached OPERATIONAL; last state: {final_state}"
        assert (
            final_position == TablePosition.RIGHT
        ), f"Expected RIGHT position, got {final_position}"

    def test_02_stop_arm_disposes_assignment(
        self, robot_host_1, requester_1, status_reader, assignment_reader
    ):
        """stop_service disposes the arm assignment, remaining arms unaffected."""
        call = make_stop_call(SERVICE_ID)
        reply = send_rpc(requester_1, call)
        assert reply is not None
        result = reply.stop_service.result.return_
        assert result.code == Orchestration.OperationResultCode.OK

        # Wait for dispose
        deadline = time.time() + 10
        disposed = False
        while time.time() < deadline:
            samples = assignment_reader.take()
            for s in samples:
                if not s.info.valid:
                    if (
                        s.info.state.instance_state
                        == dds.InstanceState.NOT_ALIVE_DISPOSED
                    ):
                        disposed = True
                        break
            if disposed:
                break
            time.sleep(0.2)

        assert disposed, "Did not see NOT_ALIVE_DISPOSED after stop"


class TestMultiArmCoexistence:
    """Multiple arms at distinct positions coexist correctly."""

    def test_01_start_two_arms_at_distinct_positions(
        self,
        robot_host_1,
        robot_host_2,
        requester_1,
        requester_2,
        status_reader,
        assignment_reader,
    ):
        """Start two arms at different table positions; both reach OPERATIONAL."""
        wait_for_replier(requester_1, timeout_sec=10)
        wait_for_replier(requester_2, timeout_sec=10)

        # Start arm 1 at LEFT
        call1 = make_start_call(
            SERVICE_ID,
            properties=[
                ("room_id", ROOM_ID),
                ("procedure_id", PROCEDURE_ID),
                ("table_position", "LEFT"),
            ],
        )
        reply1 = send_rpc(requester_1, call1)
        assert reply1 is not None
        r1 = reply1.start_service.result.return_
        assert r1.code == Orchestration.OperationResultCode.OK

        # Start arm 2 at RIGHT
        call2 = make_start_call(
            SERVICE_ID,
            properties=[
                ("room_id", ROOM_ID),
                ("procedure_id", PROCEDURE_ID),
                ("table_position", "RIGHT"),
            ],
        )
        reply2 = send_rpc(requester_2, call2)
        assert reply2 is not None
        r2 = reply2.start_service.result.return_
        assert r2.code == Orchestration.OperationResultCode.OK

        # Wait for both to reach OPERATIONAL
        deadline = time.time() + 15
        operational_robots: set[str] = set()
        positions: dict[str, int] = {}
        while time.time() < deadline:
            samples = assignment_reader.take()
            for s in samples:
                if s.info.valid:
                    rid = str(s.data.robot_id)
                    if s.data.status == ArmAssignmentState.OPERATIONAL:
                        operational_robots.add(rid)
                    positions[rid] = s.data.table_position
            if len(operational_robots) >= 2:
                break
            time.sleep(0.3)

        assert len(operational_robots) >= 2, (
            f"Expected 2 OPERATIONAL arms, got {len(operational_robots)}: "
            f"{operational_robots}"
        )

        # Verify distinct positions
        position_values = set(positions.values())
        assert (
            len(position_values) >= 2
        ), f"Expected distinct positions, got {positions}"

    def test_02_stop_one_arm_other_unaffected(
        self,
        robot_host_1,
        robot_host_2,
        requester_1,
        assignment_reader,
    ):
        """Stopping one arm doesn't affect the other."""
        # Stop arm 1
        call = make_stop_call(SERVICE_ID)
        reply = send_rpc(requester_1, call)
        assert reply is not None
        result = reply.stop_service.result.return_
        assert result.code == Orchestration.OperationResultCode.OK

        # Wait for dispose and track which robot_ids were disposed.
        deadline = time.time() + 10
        disposed_robots: set[str] = set()
        while time.time() < deadline:
            samples = assignment_reader.take()
            for s in samples:
                if not s.info.valid:
                    if (
                        s.info.state.instance_state
                        == dds.InstanceState.NOT_ALIVE_DISPOSED
                    ):
                        key = assignment_reader.key_value(s.info.instance_handle)
                        disposed_robots.add(str(key.robot_id))
            if disposed_robots:
                break
            time.sleep(0.2)

        assert (
            len(disposed_robots) == 1
        ), f"Expected exactly 1 disposed arm, got {disposed_robots}"

        # Wait briefly to confirm no second dispose arrives for arm 2.
        time.sleep(2)
        extra_samples = assignment_reader.take()
        for s in extra_samples:
            if not s.info.valid:
                if s.info.state.instance_state == dds.InstanceState.NOT_ALIVE_DISPOSED:
                    key = assignment_reader.key_value(s.info.instance_handle)
                    disposed_robots.add(str(key.robot_id))

        assert (
            len(disposed_robots) == 1
        ), f"Expected only 1 disposed arm after wait, got {disposed_robots}"
