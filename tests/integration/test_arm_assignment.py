"""Tests for Step 20.4 — Robot Arm Assignment Publishing.

Spec coverage: multi-arm-orchestration.md — Arm Assignment Lifecycle
Tags: @integration @multi-arm

Verifies the robot arm service publishes RobotArmAssignment lifecycle
transitions (ASSIGNED → POSITIONING → OPERATIONAL) and disposes the
instance on shutdown.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time

import pytest
import rti.connextdds as dds
import surgery
from conftest import wait_for_data, wait_for_reader_match

pytestmark = [
    pytest.mark.integration,
    pytest.mark.xdist_group("arm_assignment"),
]

PROCEDURE_DOMAIN_ID = 10
ROOM_ID = "OR-ARM"
PROCEDURE_ID = "proc-arm"
PARTITION = f"room/{ROOM_ID}/procedure/{PROCEDURE_ID}"

RobotArmAssignment = surgery.Surgery.RobotArmAssignment
ArmAssignmentState = surgery.Surgery.ArmAssignmentState
TablePosition = surgery.Surgery.TablePosition


def _start_robot_controller(table_position="LEFT"):
    """Start the standalone C++ robot controller with TABLE_POSITION."""
    bin_path = os.path.join(
        os.environ.get("MEDTECH_INSTALL", "install"), "bin", "robot-controller"
    )
    if not os.path.isfile(bin_path):
        bin_path = os.path.join(
            "build",
            "modules",
            "surgical-procedure",
            "robot_controller",
            "robot-controller",
        )
    env = os.environ.copy()
    env["ROBOT_ID"] = "arm-test-001"
    env["ROOM_ID"] = ROOM_ID
    env["PROCEDURE_ID"] = PROCEDURE_ID
    env["TABLE_POSITION"] = table_position
    return subprocess.Popen(
        [bin_path],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _terminate_proc(proc, timeout=3):
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="module")
def control_dp():
    """Procedure DDS domain participant with 'control' tag and matching partition."""
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
def robot_controller(assignment_reader):
    """Start robot-controller subprocess and wait for assignment match."""
    proc = _start_robot_controller(table_position="LEFT")
    time.sleep(1)
    assert (
        proc.poll() is None
    ), f"robot-controller exited immediately with code {proc.returncode}"
    yield proc
    _terminate_proc(proc)


class TestArmAssignmentLifecycle:
    """Verifies RobotArmAssignment lifecycle from robot-controller."""

    def test_01_arm_publishes_assigned(self, robot_controller, assignment_reader):
        """Arm publishes ASSIGNED within 5s of startup."""
        matched = wait_for_reader_match(assignment_reader, timeout_sec=10)
        assert matched, "RobotArmAssignment reader did not match robot-controller"

        received = wait_for_data(assignment_reader, timeout_sec=5)
        assert received, "No RobotArmAssignment samples received"

    def test_02_arm_transitions_to_operational(
        self, robot_controller, assignment_reader
    ):
        """Arm transitions through ASSIGNED → POSITIONING → OPERATIONAL.

        The writer uses KEEP_LAST 1, so earlier states may be overwritten
        before the reader discovers the writer. The test verifies that the
        arm reaches OPERATIONAL and that at least POSITIONING was observed
        (the 2s positioning delay makes it likely to be caught).
        Also verifies table_position is LEFT on all received samples.
        """
        # Wait up to 10s for the arm to reach OPERATIONAL
        deadline = time.time() + 10
        states_seen = set()
        positions_seen = set()
        while time.time() < deadline:
            samples = assignment_reader.take()
            for sample in samples:
                if sample.info.valid:
                    states_seen.add(sample.data.status)
                    positions_seen.add(sample.data.table_position)
            if ArmAssignmentState.OPERATIONAL in states_seen:
                break
            time.sleep(0.2)

        assert (
            ArmAssignmentState.OPERATIONAL in states_seen
        ), f"Never saw OPERATIONAL state; states seen: {states_seen}"
        # POSITIONING has a 2s hold time, making it very likely to be observed
        assert (
            ArmAssignmentState.POSITIONING in states_seen
        ), f"Never saw POSITIONING state; states seen: {states_seen}"
        # All samples should have table_position=LEFT
        assert positions_seen == {
            TablePosition.LEFT
        }, f"Expected only LEFT position, got {positions_seen}"

    def test_03_steady_state_no_extra_writes(self, robot_controller, assignment_reader):
        """No samples published when arm is in steady state (write-on-change)."""
        # Drain any remaining samples
        assignment_reader.take()
        time.sleep(2)
        samples = assignment_reader.take()
        valid_samples = [s for s in samples if s.info.valid]
        assert (
            len(valid_samples) == 0
        ), f"Expected no new samples in steady state, got {len(valid_samples)}"

    def test_04_dispose_on_shutdown(self, robot_controller, assignment_reader):
        """dispose() is called on shutdown; subscriber sees NOT_ALIVE_DISPOSED."""
        _terminate_proc(robot_controller)
        # Wait for dispose notification
        deadline = time.time() + 10
        disposed = False
        while time.time() < deadline:
            samples = assignment_reader.take()
            for sample in samples:
                if not sample.info.valid:
                    state = sample.info.state
                    if state.instance_state == dds.InstanceState.NOT_ALIVE_DISPOSED:
                        disposed = True
                        break
            if disposed:
                break
            time.sleep(0.2)
        assert disposed, "Did not see NOT_ALIVE_DISPOSED after shutdown"
