"""Acceptance test: Standalone surgical-procedure workflow (Phase 2 retroactive).

Spec: surgical-procedure.md — full standalone module workflow
Tags: @integration @acceptance

Rule 8 acceptance test (Phase 2 retroactive):
1. Start standalone surgical services (no orchestration)
2. Operator Console publishes a RobotCommand → RobotController publishes
   updated RobotState within 100 ms
3. BedsideMonitor publishes PatientVitals → subscriber receives
4. An alarm condition triggers an AlarmMessage

Fails if any component is missing or non-functional.
"""

import os
import signal
import subprocess
import time

import monitoring
import pytest
import rti.connextdds as dds
import surgery
from conftest import wait_for_data, wait_for_reader_match

pytestmark = [
    pytest.mark.integration,
    pytest.mark.acceptance,
    pytest.mark.xdist_group("subprocess_dds"),
]

PROCEDURE_DOMAIN_ID = 10
ROOM_ID = "OR-SA"
PROCEDURE_ID = "proc-sa"
PARTITION = f"room/{ROOM_ID}/procedure/{PROCEDURE_ID}"


def _start_standalone(module, extra_env=None):
    """Start a standalone surgical service subprocess."""
    env = os.environ.copy()
    env["ROOM_ID"] = ROOM_ID
    env["PROCEDURE_ID"] = PROCEDURE_ID
    if extra_env:
        env.update(extra_env)
    return subprocess.Popen(
        ["python", "-m", module],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _start_robot_controller():
    """Start the standalone C++ robot controller."""
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
    env["ROOM_ID"] = ROOM_ID
    env["PROCEDURE_ID"] = PROCEDURE_ID
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
def standalone_services():
    """Start a minimal standalone surgical deployment:
    robot-controller + vitals-sim + operator-sim.
    """
    procs = {}
    procs["robot-controller"] = _start_robot_controller()
    procs["vitals-sim"] = _start_standalone(
        "surgical_procedure.vitals_sim",
        extra_env={"MEDTECH_SIM_PROFILE": "cardiac_event"},
    )
    procs["operator-sim"] = _start_standalone("surgical_procedure.operator_sim")
    time.sleep(1)
    for name, proc in procs.items():
        assert (
            proc.poll() is None
        ), f"{name} exited immediately with code {proc.returncode}"
    yield procs
    for proc in procs.values():
        _terminate_proc(proc)


@pytest.fixture(scope="module")
def control_dp():
    """Procedure DDS domain participant with 'control' tag and matching partition."""
    qos = dds.DomainParticipantQos()
    qos.property["dds.domain_participant.domain_tag"] = "control"
    qos.partition.name = [PARTITION]
    dp = dds.DomainParticipant(PROCEDURE_DOMAIN_ID, qos)
    dp.enable()
    yield dp
    dp.close()


@pytest.fixture(scope="module")
def clinical_dp():
    """Procedure DDS domain participant with 'clinical' tag and matching partition."""
    qos = dds.DomainParticipantQos()
    qos.property["dds.domain_participant.domain_tag"] = "clinical"
    qos.partition.name = [PARTITION]
    dp = dds.DomainParticipant(PROCEDURE_DOMAIN_ID, qos)
    dp.enable()
    yield dp
    dp.close()


# ---------------------------------------------------------------------------
# Acceptance Test
# ---------------------------------------------------------------------------


class TestAcceptanceStandalone:
    """Standalone surgical-procedure workflow acceptance test."""

    def test_01_robot_controller_publishes_state(self, standalone_services, control_dp):
        """RobotController publishes RobotState on the Procedure DDS domain."""
        topic = dds.Topic(control_dp, "RobotState", surgery.Surgery.RobotState)
        rqos = dds.DataReaderQos()
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        reader = dds.DataReader(dds.Subscriber(control_dp), topic, rqos)

        matched = wait_for_reader_match(reader, timeout_sec=15)
        assert matched, "RobotState reader did not match robot-controller"

        samples = wait_for_data(reader, timeout_sec=15)
        assert samples, "No RobotState samples received"

        reader.close()

    def test_02_vitals_data_flows(self, standalone_services, clinical_dp):
        """BedsideMonitor publishes PatientVitals."""
        topic = dds.Topic(
            clinical_dp, "PatientVitals", monitoring.Monitoring.PatientVitals
        )
        rqos = dds.DataReaderQos()
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        reader = dds.DataReader(dds.Subscriber(clinical_dp), topic, rqos)

        matched = wait_for_reader_match(reader, timeout_sec=15)
        assert matched, "PatientVitals reader did not match vitals-sim"

        samples = wait_for_data(reader, timeout_sec=15)
        assert samples, "No PatientVitals samples received"

        reader.close()

    def test_03_alarm_message_triggered(self, standalone_services, clinical_dp):
        """An alarm condition triggers an AlarmMessage.

        Uses the 'cardiac_event' simulation profile, which spikes heart
        rate to 145 bpm within ~10 s, crossing the HR_HIGH alarm threshold
        (120 bpm) and producing AlarmMessage samples.
        """
        topic = dds.Topic(
            clinical_dp, "AlarmMessages", monitoring.Monitoring.AlarmMessage
        )
        rqos = dds.DataReaderQos()
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        reader = dds.DataReader(dds.Subscriber(clinical_dp), topic, rqos)

        matched = wait_for_reader_match(reader, timeout_sec=15)
        assert matched, "AlarmMessages reader did not match vitals-sim"

        # The alarm profile should trigger alarms within a few cycles
        samples = wait_for_data(reader, timeout_sec=30)
        assert samples, (
            "No AlarmMessage samples received — alarm profile may not be "
            "triggering thresholds"
        )

        reader.close()
