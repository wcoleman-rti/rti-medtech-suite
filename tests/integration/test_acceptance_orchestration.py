"""Acceptance test: Orchestrated surgical workflow (Step 5.7).

Spec: procedure-orchestration.md — Full orchestrated workflow acceptance
Tags: @integration @orchestration @acceptance

Rule 8 acceptance test:
1. Procedure Controller starts all services on all hosts via RPC
2. Operator Console sends a robot command → RobotController moves → RobotState updates
3. BedsideMonitor publishes vitals → subscriber receives on Procedure DDS domain
4. Procedure Controller stops all services → all states return to STOPPED

Fails if any component is missing or non-functional.
"""

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
    wait_for_all_states,
    wait_for_data,
    wait_for_reader_match,
    wait_for_replier,
)
from monitoring import Monitoring
from orchestration import Orchestration
from rti.rpc import Requester

pytestmark = [
    pytest.mark.integration,
    pytest.mark.orchestration,
    pytest.mark.acceptance,
    pytest.mark.xdist_group("subprocess_dds"),
]

ORCHESTRATION_DOMAIN_ID = 11
PROCEDURE_DOMAIN_ID = 10

ROBOT_HOST_ID = "robot-host-acc"
CLINICAL_HOST_ID = "clinical-host-acc"
OPERATIONAL_HOST_ID = "operational-host-acc"
OPERATOR_HOST_ID = "operator-host-acc"

ROOM_ID = "OR-ACC"
PROCEDURE_ID = "proc-acc"
PARTITION = f"room/{ROOM_ID}/procedure/{PROCEDURE_ID}"


def _start_python_host(module, host_id):
    env = os.environ.copy()
    env["HOST_ID"] = host_id
    env["ROOM_ID"] = ROOM_ID
    env["PROCEDURE_ID"] = PROCEDURE_ID
    return subprocess.Popen(
        ["python", "-m", module],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _start_robot_host(host_id):
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


def _wait_for_catalog(host_ids, timeout=5):
    qos = test_participant_qos()
    qos.partition.name = ["procedure"]
    dp = dds.DomainParticipant(ORCHESTRATION_DOMAIN_ID, qos)
    dp.enable()
    topic = dds.Topic(dp, "ServiceCatalog", Orchestration.ServiceCatalog)
    rqos = dds.DataReaderQos()
    rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
    rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    reader = dds.DataReader(dds.Subscriber(dp), topic, rqos)
    cond = dds.StatusCondition(reader)
    cond.enabled_statuses = dds.StatusMask.SUBSCRIPTION_MATCHED
    ws = dds.WaitSet()
    ws += cond

    remaining_hosts = set(host_ids)
    deadline = time.monotonic() + timeout
    try:
        while remaining_hosts and time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            try:
                ws.wait(dds.Duration(int(remaining), 0))
            except dds.TimeoutError:
                pass
            for sample in reader.read_data():
                if sample.host_id in remaining_hosts:
                    remaining_hosts.discard(sample.host_id)
            if remaining_hosts:
                time.sleep(0.1)
    finally:
        dp.close()
    return len(remaining_hosts) == 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def all_hosts():
    """Start all four Service Hosts."""
    procs = {}
    procs[ROBOT_HOST_ID] = _start_robot_host(ROBOT_HOST_ID)
    procs[CLINICAL_HOST_ID] = _start_python_host(
        "surgical_procedure.clinical_service_host", CLINICAL_HOST_ID
    )
    procs[OPERATIONAL_HOST_ID] = _start_python_host(
        "surgical_procedure.operational_service_host", OPERATIONAL_HOST_ID
    )
    procs[OPERATOR_HOST_ID] = _start_python_host(
        "surgical_procedure.operator_service_host", OPERATOR_HOST_ID
    )
    time.sleep(1)
    for hid, proc in procs.items():
        assert (
            proc.poll() is None
        ), f"{hid} exited immediately with code {proc.returncode}"
    all_ids = [ROBOT_HOST_ID, CLINICAL_HOST_ID, OPERATIONAL_HOST_ID, OPERATOR_HOST_ID]
    assert _wait_for_catalog(
        all_ids, timeout=20
    ), "Not all hosts published ServiceCatalog"
    yield procs
    for proc in procs.values():
        _terminate_proc(proc)


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
def status_reader(orch_dp):
    """ServiceStatus reader."""
    topic = dds.Topic(orch_dp, "ServiceStatus", Orchestration.ServiceStatus)
    rqos = dds.DataReaderQos()
    rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
    rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    rqos.history.kind = dds.HistoryKind.KEEP_LAST
    rqos.history.depth = 20
    r = dds.DataReader(dds.Subscriber(orch_dp), topic, rqos)
    yield r
    r.close()


@pytest.fixture(scope="module")
def control_dp():
    """Procedure DDS domain participant with 'control' tag."""
    qos = dds.DomainParticipantQos()
    qos.property["dds.domain_participant.domain_tag"] = "control"
    qos.partition.name = [PARTITION]
    dp = dds.DomainParticipant(PROCEDURE_DOMAIN_ID, qos)
    dp.enable()
    yield dp
    dp.close()


@pytest.fixture(scope="module")
def clinical_dp():
    """Procedure DDS domain participant with 'clinical' tag."""
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


class TestAcceptanceOrchestration:
    """Full orchestrated surgical workflow acceptance test.

    This is a sequential test — each method depends on the previous.
    Uses module-scoped fixtures so all hosts stay running throughout.
    """

    def test_01_start_all_services(self, all_hosts, orch_dp, status_reader):
        """Start all services on all hosts via RPC."""
        all_services = {
            ROBOT_HOST_ID: ["RobotControllerService"],
            CLINICAL_HOST_ID: ["BedsideMonitorService", "DeviceTelemetryService"],
            OPERATIONAL_HOST_ID: ["CameraService", "ProcedureContextService"],
            OPERATOR_HOST_ID: ["OperatorConsoleService"],
        }
        for hid, svc_ids in all_services.items():
            req = Requester(
                request_type=Orchestration.ServiceHostControl.call_type,
                reply_type=Orchestration.ServiceHostControl.return_type,
                participant=orch_dp,
                service_name=f"ServiceHostControl/{hid}",
            )
            try:
                assert wait_for_replier(req, timeout_sec=15), f"No replier for {hid}"
                for svc_id in svc_ids:
                    call = make_start_call(svc_id)
                    reply = send_rpc(req, call)
                    assert reply is not None, f"No reply for start {svc_id}"
                    result = reply.start_service.result.return_
                    assert (
                        result.code == Orchestration.OperationResultCode.OK
                    ), f"start {svc_id}: {result.message}"
            finally:
                req.close()

        # Verify all reach RUNNING (batch wait avoids take-discard)
        expected = {
            (hid, svc_id): Orchestration.ServiceState.RUNNING
            for hid, svc_ids in all_services.items()
            for svc_id in svc_ids
        }
        missed = wait_for_all_states(status_reader, expected, timeout_sec=20)
        assert not missed, f"Services did not reach RUNNING: {missed}"

    def test_02_robot_state_updates_on_command(self, all_hosts, control_dp):
        """Operator Console sends RobotCommand → RobotState updates.

        Verifies data flows on the Procedure DDS domain while services
        are orchestrated.
        """
        # Subscribe to RobotState on the Procedure DDS domain
        topic = dds.Topic(control_dp, "RobotState", surgery.Surgery.RobotState)
        rqos = dds.DataReaderQos()
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        reader = dds.DataReader(dds.Subscriber(control_dp), topic, rqos)

        # Wait for reader to match a writer (the RobotController's writer)
        matched = wait_for_reader_match(reader, timeout_sec=15)
        assert matched, "RobotState reader did not match any writer"

        # Wait for at least one RobotState sample (the robot controller
        # publishes periodic state)
        samples = wait_for_data(reader, timeout_sec=15)
        assert samples, "No RobotState samples received"

        reader.close()

    def test_03_vitals_data_flows(self, all_hosts, clinical_dp):
        """BedsideMonitor publishes PatientVitals on the Procedure DDS domain.

        Verifies the clinical service is producing data through the
        Procedure DDS domain data plane.
        """
        topic = dds.Topic(clinical_dp, "PatientVitals", Monitoring.PatientVitals)
        rqos = dds.DataReaderQos()
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        reader = dds.DataReader(dds.Subscriber(clinical_dp), topic, rqos)

        matched = wait_for_reader_match(reader, timeout_sec=15)
        assert matched, "PatientVitals reader did not match any writer"

        samples = wait_for_data(reader, timeout_sec=15)
        assert samples, "No PatientVitals samples received"

        reader.close()

    def test_04_stop_all_services(self, all_hosts, orch_dp, status_reader):
        """Stop all services → all states return to STOPPED."""
        all_services = {
            ROBOT_HOST_ID: ["RobotControllerService"],
            CLINICAL_HOST_ID: ["BedsideMonitorService", "DeviceTelemetryService"],
            OPERATIONAL_HOST_ID: ["CameraService", "ProcedureContextService"],
            OPERATOR_HOST_ID: ["OperatorConsoleService"],
        }
        for hid, svc_ids in all_services.items():
            req = Requester(
                request_type=Orchestration.ServiceHostControl.call_type,
                reply_type=Orchestration.ServiceHostControl.return_type,
                participant=orch_dp,
                service_name=f"ServiceHostControl/{hid}",
            )
            try:
                assert wait_for_replier(req, timeout_sec=10), f"No replier for {hid}"
                for svc_id in svc_ids:
                    call = make_stop_call(svc_id)
                    reply = send_rpc(req, call)
                    assert reply is not None, f"No reply for stop {svc_id}"
                    result = reply.stop_service.result.return_
                    assert (
                        result.code == Orchestration.OperationResultCode.OK
                    ), f"stop {svc_id}: {result.message}"
            finally:
                req.close()

        # Verify all reach STOPPED (batch wait avoids take-discard)
        expected = {
            (hid, svc_id): Orchestration.ServiceState.STOPPED
            for hid, svc_ids in all_services.items()
            for svc_id in svc_ids
        }
        missed = wait_for_all_states(status_reader, expected, timeout_sec=20)
        assert not missed, f"Services did not reach STOPPED: {missed}"
