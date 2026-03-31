"""End-to-end orchestration lifecycle tests (Step 5.7).

Spec: procedure-orchestration.md — full lifecycle, domain isolation,
      liveliness, partition isolation, orchestration failure resilience
Tags: @integration @orchestration @acceptance

Tests the full multi-host orchestration lifecycle:
1. Controller discovers all four Service Hosts
2. Controller starts services on each host via RPC
3. Services reach RUNNING state
4. Controller stops services; state returns to STOPPED
5. Service Host crash → liveliness loss detection
6. Orchestration failure does not disrupt Procedure domain data
7. Partition isolation: OR-1 host not discoverable by OR-3 controller
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
    wait_for_all_states,
    wait_for_data,
    wait_for_replier,
)
from orchestration import Orchestration
from rti.rpc import Requester

pytestmark = [
    pytest.mark.integration,
    pytest.mark.orchestration,
    pytest.mark.xdist_group("orch_e2e"),
]

ORCHESTRATION_DOMAIN_ID = 15
PROCEDURE_DOMAIN_ID = 10

# Host identifiers for E2E test
ROBOT_HOST_ID = "robot-host-e2e"
CLINICAL_HOST_ID = "clinical-host-e2e"
OPERATIONAL_HOST_ID = "operational-host-e2e"
OPERATOR_HOST_ID = "operator-host-e2e"

ROOM_ID = "OR-E2E"
PROCEDURE_ID = "proc-e2e"

# Service IDs per host
ROBOT_SERVICES = ["RobotControllerService"]
CLINICAL_SERVICES = ["BedsideMonitorService", "DeviceTelemetryService"]
OPERATIONAL_SERVICES = ["CameraService", "ProcedureContextService"]
OPERATOR_SERVICES = ["OperatorConsoleService"]

ALL_HOST_IDS = [ROBOT_HOST_ID, CLINICAL_HOST_ID, OPERATIONAL_HOST_ID, OPERATOR_HOST_ID]
ALL_SERVICES = {
    ROBOT_HOST_ID: ROBOT_SERVICES,
    CLINICAL_HOST_ID: CLINICAL_SERVICES,
    OPERATIONAL_HOST_ID: OPERATIONAL_SERVICES,
    OPERATOR_HOST_ID: OPERATOR_SERVICES,
}


# ---------------------------------------------------------------------------
# Process management helpers
# ---------------------------------------------------------------------------


def _start_python_host(module, host_id):
    """Start a Python service host subprocess."""
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
    """Start the C++ robot service host subprocess."""
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
    """Send SIGTERM and wait, then SIGKILL if needed."""
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _wait_for_catalog(host_ids, timeout=5):
    """Wait until ServiceCatalog samples from all host_ids appear."""
    qos = dds.DomainParticipantQos()
    qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
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
def all_service_hosts():
    """Start all four Service Hosts and yield once catalogs are published."""
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

    # Verify all started
    time.sleep(1)
    for hid, proc in procs.items():
        assert (
            proc.poll() is None
        ), f"{hid} exited immediately with code {proc.returncode}"

    # Wait for all to publish ServiceCatalog
    assert _wait_for_catalog(
        ALL_HOST_IDS, timeout=20
    ), "Not all Service Hosts published ServiceCatalog within 20 s"

    yield procs

    for proc in procs.values():
        _terminate_proc(proc)


@pytest.fixture(scope="module")
def orch_participant():
    """Orchestration domain participant for E2E tests."""
    qos = dds.DomainParticipantQos()
    qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
    p = dds.DomainParticipant(ORCHESTRATION_DOMAIN_ID, qos)
    p.enable()
    yield p
    p.close()


@pytest.fixture(scope="module")
def catalog_reader(orch_participant):
    """DataReader for ServiceCatalog."""
    topic = dds.Topic(orch_participant, "ServiceCatalog", Orchestration.ServiceCatalog)
    rqos = dds.DataReaderQos()
    rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
    rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    rqos.history.kind = dds.HistoryKind.KEEP_LAST
    rqos.history.depth = 10
    r = dds.DataReader(dds.Subscriber(orch_participant), topic, rqos)
    yield r
    r.close()


@pytest.fixture(scope="module")
def status_reader(orch_participant):
    """DataReader for ServiceStatus."""
    topic = dds.Topic(orch_participant, "ServiceStatus", Orchestration.ServiceStatus)
    rqos = dds.DataReaderQos()
    rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
    rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    rqos.history.kind = dds.HistoryKind.KEEP_LAST
    rqos.history.depth = 20
    r = dds.DataReader(dds.Subscriber(orch_participant), topic, rqos)
    yield r
    r.close()


def _make_requester(orch_participant, host_id):
    """Create an RPC requester for a specific host."""
    return Requester(
        request_type=Orchestration.ServiceHostControl.call_type,
        reply_type=Orchestration.ServiceHostControl.return_type,
        participant=orch_participant,
        service_name=f"ServiceHostControl/{host_id}",
    )


# ---------------------------------------------------------------------------
# Tests: Discovery
# ---------------------------------------------------------------------------


class TestMultiHostDiscovery:
    """Scenario: Controller discovers all four Service Hosts."""

    def test_all_hosts_publish_catalog(self, all_service_hosts, catalog_reader):
        """All four Service Hosts publish ServiceCatalog entries."""
        # Poll until all E2E host IDs appear (other test groups may also
        # publish on this domain, so filter by expected host IDs).
        deadline = time.monotonic() + 15.0
        discovered_hosts: set[str] = set()
        while time.monotonic() < deadline:
            for sample in catalog_reader.read_data():
                if sample.host_id in ALL_HOST_IDS:
                    discovered_hosts.add(sample.host_id)
            if discovered_hosts >= set(ALL_HOST_IDS):
                break
            time.sleep(0.2)
        for hid in ALL_HOST_IDS:
            assert hid in discovered_hosts, f"Host {hid} not discovered"

    def test_all_services_registered(self, all_service_hosts, catalog_reader):
        """Each host advertises the correct services in its catalog."""
        # Read all available samples (filter to E2E hosts only)
        all_samples = catalog_reader.read_data()
        valid = [s for s in all_samples if s.host_id in ALL_HOST_IDS]
        catalog_map: dict[str, set[str]] = {}
        for s in valid:
            catalog_map.setdefault(s.host_id, set()).add(s.service_id)

        for hid, expected_services in ALL_SERVICES.items():
            assert hid in catalog_map, f"No catalog entries for {hid}"
            for svc_id in expected_services:
                assert (
                    svc_id in catalog_map[hid]
                ), f"Service {svc_id} not advertised by {hid}"


# ---------------------------------------------------------------------------
# Tests: Full Lifecycle (start all, then stop all)
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    """Scenario: Start services on each host → RUNNING → stop → STOPPED."""

    def test_start_all_services(
        self, all_service_hosts, orch_participant, status_reader
    ):
        """Start all services on all hosts via RPC and reach RUNNING."""
        for hid, service_ids in ALL_SERVICES.items():
            req = _make_requester(orch_participant, hid)
            try:
                assert wait_for_replier(
                    req, timeout_sec=15
                ), f"RPC requester did not discover replier for {hid}"
                for svc_id in service_ids:
                    call = make_start_call(svc_id)
                    reply = send_rpc(req, call)
                    assert (
                        reply is not None
                    ), f"No reply for start_service {svc_id} on {hid}"
                    result = reply.start_service.result.return_
                    assert (
                        result.code == Orchestration.OperationResultCode.OK
                    ), f"start_service {svc_id} on {hid} failed: {result.message}"
            finally:
                req.close()

        # Verify all services reach RUNNING (batch wait)
        expected = {
            (hid, svc_id): Orchestration.ServiceState.RUNNING
            for hid, svc_ids in ALL_SERVICES.items()
            for svc_id in svc_ids
        }
        missed = wait_for_all_states(status_reader, expected, timeout_sec=20)
        assert not missed, f"Services did not reach RUNNING: {missed}"

    def test_stop_all_services(
        self, all_service_hosts, orch_participant, status_reader
    ):
        """Stop all services on all hosts via RPC and reach STOPPED."""
        for hid, service_ids in ALL_SERVICES.items():
            req = _make_requester(orch_participant, hid)
            try:
                assert wait_for_replier(
                    req, timeout_sec=10
                ), f"RPC requester did not discover replier for {hid}"
                for svc_id in service_ids:
                    call = make_stop_call(svc_id)
                    reply = send_rpc(req, call)
                    assert (
                        reply is not None
                    ), f"No reply for stop_service {svc_id} on {hid}"
                    result = reply.stop_service.result.return_
                    assert (
                        result.code == Orchestration.OperationResultCode.OK
                    ), f"stop_service {svc_id} on {hid} failed: {result.message}"
            finally:
                req.close()

        # Verify all services reach STOPPED (batch wait)
        expected = {
            (hid, svc_id): Orchestration.ServiceState.STOPPED
            for hid, svc_ids in ALL_SERVICES.items()
            for svc_id in svc_ids
        }
        missed = wait_for_all_states(status_reader, expected, timeout_sec=20)
        assert not missed, f"Services did not reach STOPPED: {missed}"


# ---------------------------------------------------------------------------
# Tests: Liveliness Loss Detection
# ---------------------------------------------------------------------------


class TestLivelinessDetection:
    """Scenario: Service Host crash → liveliness lost detected."""

    def test_liveliness_lost_on_host_kill(self):
        """When a Service Host is killed, liveliness loss is detected
        within the 2 s lease period."""
        host_id = "liveliness-test-host"

        # Create the monitoring reader FIRST, before starting the host,
        # so we are guaranteed to discover and match the host's writer.
        qos = dds.DomainParticipantQos()
        qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
        dp = dds.DomainParticipant(ORCHESTRATION_DOMAIN_ID, qos)
        dp.enable()
        topic = dds.Topic(dp, "ServiceCatalog", Orchestration.ServiceCatalog)
        rqos = dds.DataReaderQos()
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
        rqos.liveliness.kind = dds.LivelinessKind.AUTOMATIC
        rqos.liveliness.lease_duration = dds.Duration(2, 0)
        reader = dds.DataReader(dds.Subscriber(dp), topic, rqos)

        # Start a dedicated host for this destructive test
        proc = _start_python_host("surgical_procedure.operator_service_host", host_id)
        try:
            # Wait until we receive ServiceCatalog data from THIS host
            # (not just any host on the domain).
            deadline = time.monotonic() + 15.0
            found = False
            while time.monotonic() < deadline and not found:
                for sample in reader.take_data():
                    if sample.host_id == host_id:
                        found = True
                        break
                if not found:
                    time.sleep(0.2)
            assert found, f"Reader never received data from {host_id}"

            # Record the alive count before the kill
            _ = reader.liveliness_changed_status  # clear status bits

            # Kill the host process (SIGKILL — ungraceful)
            proc.kill()
            proc.wait()

            # Wait for liveliness lost — use LIVELINESS_CHANGED status
            liveliness_cond = dds.StatusCondition(reader)
            liveliness_cond.enabled_statuses = dds.StatusMask.LIVELINESS_CHANGED
            ws_live = dds.WaitSet()
            ws_live += liveliness_cond

            detected = False
            deadline = time.monotonic() + 10.0  # Max 10 s (2 s lease + margin)
            while time.monotonic() < deadline:
                remaining = max(0.1, deadline - time.monotonic())
                try:
                    ws_live.wait(dds.Duration(int(remaining), 0))
                except dds.TimeoutError:
                    pass
                status = reader.liveliness_changed_status
                if status.not_alive_count > 0:
                    detected = True
                    break

            assert detected, "Liveliness loss not detected within 10 s after host kill"
        finally:
            dp.close()
            if proc.poll() is None:
                _terminate_proc(proc)


# ---------------------------------------------------------------------------
# Tests: Orchestration Failure Does Not Disrupt Procedure Domain
# ---------------------------------------------------------------------------


class TestOrchestrationFailureIsolation:
    """Scenario: Orchestration failure does not disrupt surgical data."""

    def test_procedure_data_unaffected_by_controller_crash(self, all_service_hosts):
        """When a simulated Procedure Controller crashes, Procedure domain
        data continues flowing.

        We simulate the controller by creating an Orchestration participant
        (like the Procedure Controller does), then close it abruptly, and
        verify that Procedure domain writers/readers remain matched.
        """
        # Create a mock controller participant on the Orchestration domain
        ctrl_qos = dds.DomainParticipantQos()
        ctrl_qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = (
            "1400"
        )
        ctrl_dp = dds.DomainParticipant(ORCHESTRATION_DOMAIN_ID, ctrl_qos)
        ctrl_dp.enable()

        # Create Procedure domain participants (writer + reader)
        import surgery

        proc_part = "room/OR-E2E/procedure/proc-e2e"
        proc_qos = dds.DomainParticipantQos()
        proc_qos.partition.name = [proc_part]
        proc_dp = dds.DomainParticipant(PROCEDURE_DOMAIN_ID, proc_qos)
        proc_dp.enable()

        topic = dds.Topic(proc_dp, "RobotState", surgery.Surgery.RobotState)
        wqos = dds.DataWriterQos()
        wqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        writer = dds.DataWriter(dds.Publisher(proc_dp), topic, wqos)

        rqos = dds.DataReaderQos()
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        reader = dds.DataReader(dds.Subscriber(proc_dp), topic, rqos)

        # Wait for writer/reader match
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            pub_matched = writer.publication_matched_status.current_count > 0
            sub_matched = reader.subscription_matched_status.current_count > 0
            if pub_matched and sub_matched:
                break
            time.sleep(0.05)
        assert (
            writer.publication_matched_status.current_count > 0
            and reader.subscription_matched_status.current_count > 0
        ), "Procedure domain writer/reader did not match"

        # "Crash" the controller — close abruptly
        ctrl_dp.close()

        # Verify Procedure domain still works
        time.sleep(0.5)
        assert (
            writer.publication_matched_status.current_count > 0
        ), "Procedure domain writer lost match after orchestration crash"
        assert (
            reader.subscription_matched_status.current_count > 0
        ), "Procedure domain reader lost match after orchestration crash"

        proc_dp.close()


# ---------------------------------------------------------------------------
# Tests: Partition Isolation
# ---------------------------------------------------------------------------


class TestPartitionIsolation:
    """Scenario: Orchestration partition scopes communication to an OR."""

    def test_or1_not_visible_to_or3_controller(self):
        """A controller with partition room/OR-3 does not receive
        ServiceCatalog from a host with partition room/OR-1."""
        # Start a host on OR-1 partition
        env = os.environ.copy()
        env["HOST_ID"] = "partition-test-host"
        env["ROOM_ID"] = "OR-1"
        env["PROCEDURE_ID"] = "proc-part"

        proc = subprocess.Popen(
            ["python", "-m", "surgical_procedure.operator_service_host"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            assert _wait_for_catalog(
                ["partition-test-host"], timeout=15
            ), "Partition test host did not publish catalog"

            # Create a reader on OR-3 partition
            qos = dds.DomainParticipantQos()
            qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
            qos.partition.name = ["room/OR-3"]
            dp = dds.DomainParticipant(ORCHESTRATION_DOMAIN_ID, qos)
            dp.enable()
            topic = dds.Topic(dp, "ServiceCatalog", Orchestration.ServiceCatalog)
            rqos = dds.DataReaderQos()
            rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
            rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
            reader = dds.DataReader(dds.Subscriber(dp), topic, rqos)

            # Verify no data from OR-1 using negative wait
            cond = dds.QueryCondition(
                dds.Query(reader, "host_id = 'partition-test-host'"),
                dds.DataState.any_data,
            )
            assert not wait_for_data(reader, timeout_sec=1, conditions=[(cond, 1)]), (
                "OR-3 controller received ServiceCatalog from OR-1 host — "
                "partition isolation is broken"
            )

            dp.close()
        finally:
            _terminate_proc(proc)


# ---------------------------------------------------------------------------
# Tests: State Reconstruction via TRANSIENT_LOCAL
# ---------------------------------------------------------------------------


class TestStateReconstruction:
    """Scenario: Controller reconstructs state on restart via
    TRANSIENT_LOCAL."""

    def test_late_joining_reader_receives_state(self, all_service_hosts):
        """A new Orchestration domain reader receives TRANSIENT_LOCAL
        ServiceCatalog and ServiceStatus from running hosts."""
        qos = dds.DomainParticipantQos()
        qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
        dp = dds.DomainParticipant(ORCHESTRATION_DOMAIN_ID, qos)
        dp.enable()

        cat_topic = dds.Topic(dp, "ServiceCatalog", Orchestration.ServiceCatalog)
        rqos = dds.DataReaderQos()
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
        cat_reader = dds.DataReader(dds.Subscriber(dp), cat_topic, rqos)

        status_topic = dds.Topic(dp, "ServiceStatus", Orchestration.ServiceStatus)
        status_reader = dds.DataReader(dds.Subscriber(dp), status_topic, rqos)

        # Wait for TRANSIENT_LOCAL delivery
        assert wait_for_data(
            cat_reader, timeout_sec=15, count=1
        ), "Late-joining reader did not receive ServiceCatalog"

        assert wait_for_data(
            status_reader, timeout_sec=15, count=1
        ), "Late-joining reader did not receive ServiceStatus"

        dp.close()
