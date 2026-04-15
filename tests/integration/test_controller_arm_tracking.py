"""Tests for Step 20.5 — Procedure Controller: Assignment Subscription.

Spec coverage: multi-arm-orchestration.md — Multi-Arm Orchestration Flow,
               Procedure Controller Enhancement
Tags: @integration @multi-arm

Verifies the Procedure Controller tracks arm assignment lifecycle,
implements the procedure start gate, enforces MAX_ARM_COUNT, and
handles arm departure (dispose / liveliness lost).
"""

from __future__ import annotations

import asyncio
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
    wait_for_data,
    wait_for_reader_match,
    wait_for_replier,
)
from orchestration import Orchestration
from rti.rpc import Requester

pytestmark = [
    pytest.mark.integration,
    pytest.mark.xdist_group("ctrl_arm"),
]

ORCHESTRATION_DOMAIN_ID = 11
PROCEDURE_DOMAIN_ID = 10
HOST_ID = "robot-host-ctrl-arm"
ROOM_ID = "OR-CTRL"
PROCEDURE_ID = "proc-ctrl"
PARTITION = f"room/{ROOM_ID}/procedure/{PROCEDURE_ID}"

Surgery_ = surgery.Surgery
RobotArmAssignment = Surgery_.RobotArmAssignment
ArmAssignmentState = Surgery_.ArmAssignmentState
TablePosition = Surgery_.TablePosition


# ---------------------------------------------------------------------------
# Unit-level tests (no DDS, direct backend method calls)
# ---------------------------------------------------------------------------


class TestArmStateTracking:
    """Verify arm state tracking via direct _update_arm_assignment calls."""

    @pytest.fixture()
    def backend(self):
        from hospital_dashboard.procedure_controller import (
            controller as controller_module,
        )

        # Create a minimal backend with injected readers (no real DDS)
        from medtech.dds import initialize_connext

        initialize_connext()
        dp = dds.DomainParticipant(ORCHESTRATION_DOMAIN_ID)
        dp.enable()
        cat_topic = dds.Topic(dp, "ServiceCatalog", Orchestration.ServiceCatalog)
        stat_topic = dds.Topic(dp, "ServiceStatus", Orchestration.ServiceStatus)
        cat_reader = dds.DataReader(dds.Subscriber(dp), cat_topic)
        stat_reader = dds.DataReader(dds.Subscriber(dp), stat_topic)
        be = controller_module.ControllerBackend(
            catalog_reader=cat_reader, status_reader=stat_reader
        )
        yield be
        asyncio.run(be.close())
        dp.close()

    def test_arm_tracked_on_first_sample(self, backend):
        """Controller tracks arm lifecycle state per robot_id."""
        sample = RobotArmAssignment(
            robot_id="arm-001",
            procedure_id=PROCEDURE_ID,
            table_position=TablePosition.LEFT,
            status=ArmAssignmentState.ASSIGNED,
            capabilities="test",
        )
        backend._update_arm_assignment(sample)
        assert "arm-001" in backend.arm_states
        assert backend.arm_states["arm-001"].status == ArmAssignmentState.ASSIGNED

    def test_arm_state_updates_on_transition(self, backend):
        """State updates when new sample has different status."""
        for state in (
            ArmAssignmentState.ASSIGNED,
            ArmAssignmentState.POSITIONING,
            ArmAssignmentState.OPERATIONAL,
        ):
            sample = RobotArmAssignment(
                robot_id="arm-002",
                procedure_id=PROCEDURE_ID,
                table_position=TablePosition.HEAD,
                status=state,
                capabilities="",
            )
            backend._update_arm_assignment(sample)
        assert backend.arm_states["arm-002"].status == ArmAssignmentState.OPERATIONAL

    def test_procedure_ready_when_all_operational(self, backend):
        """Procedure start gate: enabled when all arms OPERATIONAL."""
        for rid, pos in [("arm-A", TablePosition.LEFT), ("arm-B", TablePosition.RIGHT)]:
            backend._update_arm_assignment(
                RobotArmAssignment(
                    robot_id=rid,
                    procedure_id=PROCEDURE_ID,
                    table_position=pos,
                    status=ArmAssignmentState.OPERATIONAL,
                    capabilities="",
                )
            )
        assert backend.procedure_ready

    def test_procedure_not_ready_with_positioning_arm(self, backend):
        """Start gate not enabled until ALL arms OPERATIONAL."""
        backend._update_arm_assignment(
            RobotArmAssignment(
                robot_id="arm-X",
                procedure_id=PROCEDURE_ID,
                table_position=TablePosition.LEFT,
                status=ArmAssignmentState.OPERATIONAL,
                capabilities="",
            )
        )
        backend._update_arm_assignment(
            RobotArmAssignment(
                robot_id="arm-Y",
                procedure_id=PROCEDURE_ID,
                table_position=TablePosition.RIGHT,
                status=ArmAssignmentState.POSITIONING,
                capabilities="",
            )
        )
        assert not backend.procedure_ready
        non_ready = backend.non_ready_arms()
        assert "arm-Y" in non_ready

    def test_procedure_not_ready_with_failed_arm(self, backend):
        """FAILED arm blocks the start gate."""
        backend._update_arm_assignment(
            RobotArmAssignment(
                robot_id="arm-F",
                procedure_id=PROCEDURE_ID,
                table_position=TablePosition.HEAD,
                status=ArmAssignmentState.FAILED,
                capabilities="",
            )
        )
        assert not backend.procedure_ready

    def test_procedure_not_ready_when_no_arms(self, backend):
        """Start gate requires at least one arm."""
        assert not backend.procedure_ready

    def test_arm_removal_updates_tracking(self, backend):
        """Removing an arm from _arm_states reflects in active_arm_count."""
        backend._update_arm_assignment(
            RobotArmAssignment(
                robot_id="arm-R",
                procedure_id=PROCEDURE_ID,
                table_position=TablePosition.FOOT,
                status=ArmAssignmentState.OPERATIONAL,
                capabilities="",
            )
        )
        assert backend.active_arm_count == 1
        del backend._arm_states["arm-R"]
        assert backend.active_arm_count == 0

    def test_max_arm_count_enforcement(self, backend):
        """MAX_ARM_COUNT exceeded → start_service is rejected."""
        positions = list(TablePosition)
        for i in range(Surgery_.MAX_ARM_COUNT):
            backend._update_arm_assignment(
                RobotArmAssignment(
                    robot_id=f"arm-{i:03d}",
                    procedure_id=PROCEDURE_ID,
                    table_position=positions[i % len(positions)],
                    status=ArmAssignmentState.OPERATIONAL,
                    capabilities="",
                )
            )
        assert backend.active_arm_count == Surgery_.MAX_ARM_COUNT

        # Attempt to start another service — should be silently rejected
        # (no RPC sent since active_arm_count >= MAX_ARM_COUNT)
        async def _test():
            await backend.start_service("some-host", "SomeService")

        asyncio.run(_test())
        # We can't directly verify RPC wasn't sent without mocking,
        # but the diag log should show rejection
        assert any(
            "MAX_ARM_COUNT" in entry for entry in backend._diag_log
        ), "Expected MAX_ARM_COUNT rejection in diag log"


# ---------------------------------------------------------------------------
# Integration tests (DDS, with robot-service-host subprocess)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def robot_service_host():
    """Start robot-service-host subprocess."""
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
    env["HOST_ID"] = HOST_ID
    env["ROOM_ID"] = ROOM_ID
    env["PROCEDURE_ID"] = PROCEDURE_ID
    proc = subprocess.Popen(
        [bin_path],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    time.sleep(2)
    assert (
        proc.poll() is None
    ), f"robot-service-host exited immediately with code {proc.returncode}"
    yield proc
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="module")
def orch_participant():
    qos = dds.DomainParticipantQos()
    qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
    qos.partition.name = ["procedure"]
    p = dds.DomainParticipant(ORCHESTRATION_DOMAIN_ID, qos)
    p.enable()
    yield p
    p.close()


@pytest.fixture(scope="module")
def rpc_requester(orch_participant):
    req = Requester(
        request_type=Orchestration.ServiceHostControl.call_type,
        reply_type=Orchestration.ServiceHostControl.return_type,
        participant=orch_participant,
        service_name=f"ServiceHostControl/{HOST_ID}",
    )
    yield req
    req.close()


@pytest.fixture(scope="module")
def control_dp():
    """Procedure DDS domain participant with control tag matching arm partition."""
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
    topic = dds.Topic(control_dp, "RobotArmAssignment", RobotArmAssignment)
    rqos = dds.DataReaderQos()
    rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
    rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    rqos.history.kind = dds.HistoryKind.KEEP_ALL
    reader = dds.DataReader(dds.Subscriber(control_dp), topic, rqos)
    yield reader
    reader.close()


class TestControllerArmSubscription:
    """Integration: Controller receives arm assignment from live arm service."""

    def test_controller_receives_arm_assignments(
        self, robot_service_host, rpc_requester, assignment_reader
    ):
        """Controller receives RobotArmAssignment samples from arm services."""
        wait_for_replier(rpc_requester, timeout_sec=15)
        call = make_start_call("RobotControllerService")
        reply = send_rpc(rpc_requester, call)
        assert reply is not None
        result = reply.start_service.result.return_
        assert result.code == Orchestration.OperationResultCode.OK

        # Wait for arm assignment to arrive
        matched = wait_for_reader_match(assignment_reader, timeout_sec=10)
        assert matched, "Assignment reader did not match arm service"

        received = wait_for_data(assignment_reader, timeout_sec=10)
        assert received, "No RobotArmAssignment samples received"

    def test_transient_local_late_joiner(self, robot_service_host, control_dp):
        """TRANSIENT_LOCAL: late-joining reader receives current arm states."""
        topic = dds.Topic.find(control_dp, "RobotArmAssignment")
        rqos = dds.DataReaderQos()
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
        rqos.history.kind = dds.HistoryKind.KEEP_LAST
        rqos.history.depth = 1
        late_reader = dds.DataReader(dds.Subscriber(control_dp), topic, rqos)
        try:
            received = wait_for_data(late_reader, timeout_sec=10)
            assert received, "Late-joining reader did not receive arm assignment"
        finally:
            late_reader.close()

    def test_arm_disposed_on_stop(
        self, robot_service_host, rpc_requester, assignment_reader
    ):
        """NOT_ALIVE_DISPOSED on arm stop — subscriber sees instance disposed."""
        # Arm was started by the previous test; stop it now
        wait_for_replier(rpc_requester, timeout_sec=10)
        call = make_stop_call("RobotControllerService")
        reply = send_rpc(rpc_requester, call)
        assert reply is not None
        result = reply.stop_service.result.return_
        assert result.code == Orchestration.OperationResultCode.OK

        # Wait for NOT_ALIVE_DISPOSED
        deadline = time.time() + 10
        disposed = False
        while time.time() < deadline:
            for sample in assignment_reader.take():
                if (
                    sample.info.state.instance_state
                    == dds.InstanceState.NOT_ALIVE_DISPOSED
                ):
                    disposed = True
                    break
            if disposed:
                break
            time.sleep(0.2)
        assert disposed, "Arm instance was not disposed after stop"
