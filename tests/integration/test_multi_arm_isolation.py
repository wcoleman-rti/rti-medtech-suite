"""Tests for Step 20.8 — Isolation, Correlation, and Regression Tests.

Spec coverage: multi-arm-orchestration.md — Isolation, Correlation
Tags: @integration @multi-arm @isolation

Verifies:
- RobotArmAssignment on control tag is NOT discoverable by clinical/operational
- robot_id correlates RobotArmAssignment with RobotState
- procedure_id in RobotArmAssignment correlates with ProcedureContext
"""

from __future__ import annotations

import os
import signal
import subprocess
import time

import pytest
import rti.connextdds as dds
import surgery
from conftest import wait_for_reader_match

pytestmark = [
    pytest.mark.integration,
    pytest.mark.xdist_group("multi_arm_isolation"),
]

PROCEDURE_DOMAIN_ID = 10
ORCHESTRATION_DOMAIN_ID = 11
ROOM_ID = "OR-ISO"
PROCEDURE_ID = "proc-iso"
PARTITION = f"room/{ROOM_ID}/procedure/{PROCEDURE_ID}"

RobotArmAssignment = surgery.Surgery.RobotArmAssignment
RobotState = surgery.Surgery.RobotState
ArmAssignmentState = surgery.Surgery.ArmAssignmentState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _start_robot_controller(robot_id: str, table_position: str = "LEFT"):
    """Start a standalone robot-controller subprocess."""
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
    env["ROBOT_ID"] = robot_id
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
def state_reader(control_dp):
    """RobotState reader on the control tag."""
    topic = dds.Topic(control_dp, "RobotState", RobotState)
    rqos = dds.DataReaderQos()
    rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
    rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    rqos.history.kind = dds.HistoryKind.KEEP_ALL
    reader = dds.DataReader(dds.Subscriber(control_dp), topic, rqos)
    yield reader
    reader.close()


@pytest.fixture(scope="module")
def robot_proc(assignment_reader, state_reader):
    """Start a robot-controller for isolation/correlation tests."""
    proc = _start_robot_controller("arm-iso-001", table_position="RIGHT")
    time.sleep(1)
    assert (
        proc.poll() is None
    ), f"Robot controller exited immediately: {proc.returncode}"
    yield proc
    _terminate_proc(proc)


# ---------------------------------------------------------------------------
# Isolation Tests
# ---------------------------------------------------------------------------


class TestControlTagIsolation:
    """RobotArmAssignment on control tag is NOT discoverable by other tags."""

    def test_clinical_tag_cannot_discover_arm_assignment(self):
        """A clinical-tag subscriber on the Procedure DDS domain cannot discover
        RobotArmAssignment published on the control tag."""
        qos = dds.DomainParticipantQos()
        qos.property["dds.domain_participant.domain_tag"] = "clinical"
        qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
        qos.partition.name = [PARTITION]
        dp = dds.DomainParticipant(PROCEDURE_DOMAIN_ID, qos)
        dp.enable()
        try:
            topic = dds.Topic(dp, "RobotArmAssignment", RobotArmAssignment)
            rqos = dds.DataReaderQos()
            rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
            rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
            reader = dds.DataReader(dds.Subscriber(dp), topic, rqos)

            # Wait 3s — should NOT discover any writers
            matched = wait_for_reader_match(reader, timeout_sec=3)
            assert not matched, (
                "Clinical-tag subscriber should NOT match control-tag "
                "RobotArmAssignment writers"
            )
            reader.close()
        finally:
            dp.close()

    def test_operational_tag_cannot_discover_arm_assignment(self):
        """An operational-tag subscriber cannot discover control-tag
        RobotArmAssignment writers."""
        qos = dds.DomainParticipantQos()
        qos.property["dds.domain_participant.domain_tag"] = "operational"
        qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
        qos.partition.name = [PARTITION]
        dp = dds.DomainParticipant(PROCEDURE_DOMAIN_ID, qos)
        dp.enable()
        try:
            topic = dds.Topic(dp, "RobotArmAssignment", RobotArmAssignment)
            rqos = dds.DataReaderQos()
            rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
            rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
            reader = dds.DataReader(dds.Subscriber(dp), topic, rqos)

            matched = wait_for_reader_match(reader, timeout_sec=3)
            assert not matched, (
                "Operational-tag subscriber should NOT match control-tag "
                "RobotArmAssignment writers"
            )
            reader.close()
        finally:
            dp.close()


# ---------------------------------------------------------------------------
# Correlation Tests
# ---------------------------------------------------------------------------


class TestRobotIdCorrelation:
    """robot_id correlates RobotArmAssignment with RobotState."""

    def test_robot_id_matches_across_topics(
        self, robot_proc, assignment_reader, state_reader
    ):
        """robot_id in RobotArmAssignment matches robot_id in RobotState."""
        # Wait for assignment data
        wait_for_reader_match(assignment_reader, timeout_sec=10)
        deadline = time.time() + 10
        arm_robot_id = None
        while time.time() < deadline:
            samples = assignment_reader.take()
            for s in samples:
                if s.info.valid:
                    arm_robot_id = str(s.data.robot_id)
                    break
            if arm_robot_id:
                break
            time.sleep(0.2)

        assert arm_robot_id is not None, "No RobotArmAssignment received"

        # Wait for RobotState data
        wait_for_reader_match(state_reader, timeout_sec=10)
        deadline = time.time() + 10
        state_robot_id = None
        while time.time() < deadline:
            samples = state_reader.take()
            for s in samples:
                if s.info.valid:
                    state_robot_id = str(s.data.robot_id)
                    break
            if state_robot_id:
                break
            time.sleep(0.2)

        assert state_robot_id is not None, "No RobotState received"

        # The robot-controller prepends "robot-" to the ROBOT_ID env for
        # its internal controller name. The RobotArmAssignment.robot_id
        # should match what was set by the service.
        assert arm_robot_id == state_robot_id, (
            f"robot_id mismatch: assignment={arm_robot_id}, " f"state={state_robot_id}"
        )

    def test_procedure_id_matches_context(self, robot_proc, assignment_reader):
        """procedure_id in RobotArmAssignment matches the expected procedure."""
        # Drain and wait for fresh data
        assignment_reader.take()
        # The robot-controller uses PROCEDURE_ID from env → proc-iso
        deadline = time.time() + 5
        proc_id = None
        while time.time() < deadline:
            samples = assignment_reader.read()
            for s in samples:
                if s.info.valid:
                    proc_id = str(s.data.procedure_id)
                    break
            if proc_id:
                break
            time.sleep(0.2)

        assert (
            proc_id == PROCEDURE_ID
        ), f"Expected procedure_id={PROCEDURE_ID}, got {proc_id}"
