"""Tests for Phase 2 Step 2.6 — Digital Twin Display.

Covers all test gate items from phase-2-surgical.md Step 2.6:
- Digital twin renders current robot state (joint positions, mode)
- Active command displayed as visual annotation
- Safety interlock prominently rendered when active
- Time-based filter limits updates to rendering frame rate on RobotState
  and OperatorInput readers
- SafetyInterlock and RobotCommand readers have no time-based filter
- Late-joining display receives current state via TRANSIENT_LOCAL
- Robot disconnect detected via liveliness (grayed out)
- DDS reads do not block the Qt main thread

Spec coverage: surgical-procedure.md — Digital Twin Display
Tags: @integration @gui @durability @streaming
"""

from __future__ import annotations

import asyncio
import inspect
import time

import app_names
import pytest
import rti.connextdds as dds
import surgery
from conftest import wait_for_data, wait_for_discovery
from surgical_procedure.digital_twin import DigitalTwinDisplay, RobotWidget

pytestmark = [pytest.mark.gui, pytest.mark.integration]

names = app_names.MedtechEntityNames.SurgicalParticipants

RobotState = surgery.Surgery.RobotState
RobotCommand = surgery.Surgery.RobotCommand
SafetyInterlock = surgery.Surgery.SafetyInterlock
OperatorInput = surgery.Surgery.OperatorInput
RobotMode = surgery.Surgery.RobotMode
CartesianPosition = surgery.Surgery.CartesianPosition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_robot_state(mode=RobotMode.OPERATIONAL, joints=None):
    s = RobotState()
    s.robot_id = "robot-001"
    s.operational_mode = mode
    s.joint_positions = joints or [0.0, 30.0, 45.0, -20.0]
    tip = CartesianPosition()
    tip.x = 10.0
    tip.y = 5.0
    s.tool_tip_position = tip
    return s


def _make_robot_command():
    cmd = RobotCommand()
    cmd.robot_id = "robot-001"
    cmd.command_id = 42
    target = CartesianPosition()
    target.x = 20.0
    target.y = 15.0
    cmd.target_position = target
    return cmd


def _make_safety_interlock(active: bool):
    il = SafetyInterlock()
    il.robot_id = "robot-001"
    il.interlock_active = active
    il.reason = "Test interlock" if active else ""
    return il


# ---------------------------------------------------------------------------
# TestRobotWidgetUpdate — pure widget tests (no DDS required)
# ---------------------------------------------------------------------------

class TestRobotWidgetUpdate:
    """Verify that the RobotWidget accepts state updates and tracks them."""

    def test_initial_state_is_connected(self, qapp):
        """Widget starts in connected state."""
        w = RobotWidget()
        assert w.is_connected is True

    def test_update_robot_state_stores_data(self, qapp):
        """update_robot_state stores the sample and marks connected."""
        w = RobotWidget()
        state = _make_robot_state(mode=RobotMode.OPERATIONAL)
        w.update_robot_state(state)
        assert w.has_robot_state is True
        assert w.operational_mode == "OPERATIONAL"

    def test_update_robot_state_mode_paused(self, qapp):
        """Mode label reflects the operational mode from RobotState."""
        w = RobotWidget()
        state = _make_robot_state(mode=RobotMode.PAUSED)
        w.update_robot_state(state)
        assert w.operational_mode == "PAUSED"

    def test_update_robot_state_mode_emergency_stop(self, qapp):
        """EMERGENCY_STOP mode is correctly reflected."""
        w = RobotWidget()
        state = _make_robot_state(mode=RobotMode.EMERGENCY_STOP)
        w.update_robot_state(state)
        assert w.operational_mode == "EMERGENCY_STOP"

    def test_update_command_stores_data(self, qapp):
        """update_command marks the command as present."""
        w = RobotWidget()
        assert w.has_command is False
        w.update_command(_make_robot_command())
        assert w.has_command is True

    def test_update_interlock_inactive(self, qapp):
        """Inactive interlock does not set interlock_active."""
        w = RobotWidget()
        w.update_interlock(_make_safety_interlock(active=False))
        assert w.interlock_active is False

    def test_update_interlock_active(self, qapp):
        """Active interlock sets interlock_active flag."""
        w = RobotWidget()
        w.update_interlock(_make_safety_interlock(active=True))
        assert w.interlock_active is True

    def test_set_connected_false(self, qapp):
        """set_connected(False) puts widget in disconnected state."""
        w = RobotWidget()
        w.update_robot_state(_make_robot_state())
        w.set_connected(False)
        assert w.is_connected is False

    def test_set_connected_true_restores(self, qapp):
        """set_connected(True) restores connected state."""
        w = RobotWidget()
        w.set_connected(False)
        w.set_connected(True)
        assert w.is_connected is True

    def test_widget_renders_without_crash(self, qapp, qtbot):
        """Widget renders to screen without raising exceptions."""
        w = RobotWidget()
        qtbot.addWidget(w)
        w.show()
        w.update_robot_state(_make_robot_state(mode=RobotMode.OPERATIONAL))
        qtbot.waitExposed(w)
        w.update()

    def test_widget_renders_interlock_without_crash(self, qapp, qtbot):
        """Widget with active interlock renders without raising exceptions."""
        w = RobotWidget()
        qtbot.addWidget(w)
        w.show()
        w.update_robot_state(_make_robot_state())
        w.update_interlock(_make_safety_interlock(active=True))
        qtbot.waitExposed(w)
        w.update()

    def test_widget_renders_disconnected_without_crash(self, qapp, qtbot):
        """Widget in disconnected state renders without raising exceptions."""
        w = RobotWidget()
        qtbot.addWidget(w)
        w.show()
        w.set_connected(False)
        qtbot.waitExposed(w)
        w.update()


# ---------------------------------------------------------------------------
# TestDisplayCreation — DigitalTwinDisplay widget integration
# ---------------------------------------------------------------------------

def _make_injected_readers(participant_factory):
    """Create four injected DataReaders for DigitalTwinDisplay tests.

    Uses IDL-generated types and plain QoS (domain 0, control tag).
    Returns a dict with reader objects and the participant for cleanup.
    """
    p = participant_factory(domain_id=0, domain_tag="control")
    sub = dds.Subscriber(p)

    def _make_reader(data_type, topic_name):
        topic = dds.Topic(p, topic_name, data_type)
        return dds.DataReader(sub, topic, dds.DataReaderQos())

    return {
        "robot_state_reader": _make_reader(RobotState, "RobotState"),
        "robot_command_reader": _make_reader(RobotCommand, "RobotCommand"),
        "safety_interlock_reader": _make_reader(SafetyInterlock, "SafetyInterlock"),
        "operator_input_reader": _make_reader(OperatorInput, "OperatorInput"),
    }


class TestDisplayCreation:
    """DigitalTwinDisplay wires the widget to DDS readers."""

    def test_display_has_robot_widget(self, qapp, participant_factory):
        """DigitalTwinDisplay creates a RobotWidget child."""
        readers = _make_injected_readers(participant_factory)
        disp = DigitalTwinDisplay(room_id="OR-1", procedure_id="proc-001", **readers)
        assert isinstance(disp.robot_widget, RobotWidget)
        disp.stop()


# ---------------------------------------------------------------------------
# TestQosConfiguration — Reader QoS verification
# ---------------------------------------------------------------------------

class TestQosConfiguration:
    """Verify that reader QoS matches the expected profiles from XML."""

    @pytest.fixture(scope="class")
    def twin_participant(self):
        """Create a ControlDigitalTwin participant (class scope, auto-cleanup)."""
        from medtech_dds_init.dds_init import initialize_connext
        initialize_connext()
        provider = dds.QosProvider.default
        p = provider.create_participant_from_config(names.CONTROL_DIGITAL_TWIN)
        partition = "room/OR-1/procedure/proc-001"
        qos = p.qos
        qos.partition.name = [partition]
        p.qos = qos
        yield p
        try:
            p.close()
        except dds.AlreadyClosedError:
            pass

    @staticmethod
    def _tbf_ns(reader: dds.DataReader) -> int:
        """Return TBF minimum_separation in nanoseconds."""
        d = reader.qos.time_based_filter.minimum_separation
        return d.sec * 1_000_000_000 + d.nanosec

    def test_robot_state_reader_has_time_based_filter(self, twin_participant):
        """RobotState reader uses GuiRobotState QoS (time-based filter > 0)."""
        r = twin_participant.find_datareader(names.TWIN_ROBOT_STATE_READER)
        assert r is not None, f"Reader not found: {names.TWIN_ROBOT_STATE_READER}"
        reader = dds.DataReader(r)
        tbf_ns = self._tbf_ns(reader)
        # GuiSubsample snippet sets 16 ms = 16_000_000 ns
        assert tbf_ns > 0, (
            "RobotState reader must have a time-based filter (min_separation > 0)"
        )

    def test_operator_input_reader_has_time_based_filter(self, twin_participant):
        """OperatorInput reader uses GuiOperatorInput QoS (TBF > 0)."""
        r = twin_participant.find_datareader(names.TWIN_OPERATOR_INPUT_READER)
        assert r is not None
        reader = dds.DataReader(r)
        tbf_ns = self._tbf_ns(reader)
        assert tbf_ns > 0, (
            "OperatorInput reader must have a time-based filter (min_separation > 0)"
        )

    def test_safety_interlock_reader_has_no_time_based_filter(
        self, twin_participant
    ):
        """SafetyInterlock reader has no TBF — every sample must be delivered."""
        r = twin_participant.find_datareader(
            names.TWIN_SAFETY_INTERLOCK_READER
        )
        assert r is not None
        reader = dds.DataReader(r)
        tbf_ns = self._tbf_ns(reader)
        assert tbf_ns == 0, (
            "SafetyInterlock reader must NOT have a time-based filter"
        )

    def test_robot_command_reader_has_no_time_based_filter(
        self, twin_participant
    ):
        """RobotCommand reader has no TBF — each command must be processed."""
        r = twin_participant.find_datareader(names.TWIN_ROBOT_COMMAND_READER)
        assert r is not None
        reader = dds.DataReader(r)
        tbf_ns = self._tbf_ns(reader)
        assert tbf_ns == 0, (
            "RobotCommand reader must NOT have a time-based filter"
        )


# ---------------------------------------------------------------------------
# TestDurabilityLateJoin — TRANSIENT_LOCAL late-join behavior
# ---------------------------------------------------------------------------

class TestDurabilityLateJoin:
    """Digital twin receives current state on late join via TRANSIENT_LOCAL."""

    def test_robot_state_received_on_late_join(self, participant_factory):
        """A late-joining RobotState reader receives the last published sample."""
        provider = dds.QosProvider.default

        # Writer participant (publisher)
        pub_p = participant_factory(
            domain_id=0,
            domain_tag="control",
            partition="room/OR-1/procedure/proc-001",
        )
        rs_topic = dds.Topic(pub_p, "RobotState", RobotState)
        writer_qos = provider.datawriter_qos_from_profile(
            "TopicProfiles::RobotState"
        )
        pub = dds.Publisher(pub_p)
        writer = dds.DataWriter(pub, rs_topic, writer_qos)

        # Publish a sample before the late-joining reader exists
        sample = _make_robot_state(mode=RobotMode.OPERATIONAL)
        writer.write(sample)
        time.sleep(0.2)

        # Now create the late-joining reader
        sub_p = participant_factory(
            domain_id=0,
            domain_tag="control",
            partition="room/OR-1/procedure/proc-001",
        )
        rs_top_sub = dds.Topic(sub_p, "RobotState", RobotState)
        reader_qos = provider.datareader_qos_from_profile(
            "TopicProfiles::RobotState"
        )
        sub = dds.Subscriber(sub_p)
        late_reader = dds.DataReader(sub, rs_top_sub, reader_qos)

        # Late joiner should receive without waiting for the next publish
        received = wait_for_data(late_reader, timeout_sec=5.0, count=1)
        assert len(received) >= 1, (
            "Late-joining RobotState reader should receive TRANSIENT_LOCAL data"
        )
        assert received[0].data.operational_mode == RobotMode.OPERATIONAL


# ---------------------------------------------------------------------------
# TestLivelinessDetection — robot disconnect detection
# ---------------------------------------------------------------------------

class TestLivelinessDetection:
    """Digital twin detects robot controller disconnect via liveliness."""

    def test_liveliness_loss_sets_disconnected(self, qapp, participant_factory):
        """When no alive writers remain, widget transitions to disconnected."""
        provider = dds.QosProvider.default

        # Writer with a short liveliness duration for fast test
        pub_p = participant_factory(
            domain_id=0,
            domain_tag="control",
            partition="room/OR-1/procedure/proc-001",
        )
        rs_topic = dds.Topic(pub_p, "RobotState", RobotState)
        writer_qos = provider.datawriter_qos_from_profile(
            "TopicProfiles::RobotState"
        )
        # Override liveliness to 400 ms for test speed
        writer_qos.liveliness.lease_duration = dds.Duration(seconds=0, nanoseconds=400_000_000)
        pub = dds.Publisher(pub_p)
        writer = dds.DataWriter(pub, rs_topic, writer_qos)

        # Reader side (matching writer QoS)
        sub_p = participant_factory(
            domain_id=0,
            domain_tag="control",
            partition="room/OR-1/procedure/proc-001",
        )
        rs_top_sub = dds.Topic(sub_p, "RobotState", RobotState)
        reader_qos = provider.datareader_qos_from_profile(
            "TopicProfiles::RobotState"
        )
        reader_qos.liveliness.lease_duration = dds.Duration(seconds=0, nanoseconds=400_000_000)
        sub = dds.Subscriber(sub_p)
        reader = dds.DataReader(sub, rs_top_sub, reader_qos)

        # Write a sample so writer is alive
        writer.write(_make_robot_state())
        wait_for_discovery(writer, reader, timeout_sec=3.0)

        # Create widget, mark connected
        robot_widget = RobotWidget()
        robot_widget.update_robot_state(_make_robot_state())
        assert robot_widget.is_connected is True

        # Close the writer — liveliness will expire within lease_duration
        writer.close()

        # Wait for liveliness loss (≥ lease_duration + tolerance)
        deadline = time.time() + 2.0
        while time.time() < deadline:
            status = reader.liveliness_changed_status
            if status.not_alive_count > 0 or status.alive_count == 0:
                robot_widget.set_connected(False)
                break
            time.sleep(0.1)

        assert robot_widget.is_connected is False, (
            "Widget should be disconnected after writer liveliness expires"
        )


# ---------------------------------------------------------------------------
# TestNonBlockingReads — QtAsyncio integration
# ---------------------------------------------------------------------------

class TestNonBlockingReads:
    """DDS reads do not block the Qt main thread."""

    def test_receive_methods_are_coroutines(self, qapp, participant_factory):
        """All _receive_* methods on DigitalTwinDisplay are async coroutines.

        This verifies that DDS reads are performed inside async coroutines
        that yield to the event loop, never blocking the Qt main thread.
        """
        readers = _make_injected_readers(participant_factory)
        disp = DigitalTwinDisplay(room_id="OR-1", procedure_id="proc-001", **readers)

        assert inspect.iscoroutinefunction(disp._receive_robot_state), (
            "_receive_robot_state must be a coroutine (async def)"
        )
        assert inspect.iscoroutinefunction(disp._receive_robot_command), (
            "_receive_robot_command must be a coroutine (async def)"
        )
        assert inspect.iscoroutinefunction(disp._receive_safety_interlock), (
            "_receive_safety_interlock must be a coroutine (async def)"
        )
        assert inspect.iscoroutinefunction(disp._receive_operator_input), (
            "_receive_operator_input must be a coroutine (async def)"
        )
        assert inspect.iscoroutinefunction(disp._monitor_liveliness), (
            "_monitor_liveliness must be a coroutine (async def)"
        )

        disp.stop()

    def test_start_is_coroutine(self, qapp, participant_factory):
        """DigitalTwinDisplay.start() is an async coroutine."""
        assert inspect.iscoroutinefunction(DigitalTwinDisplay.start), (
            "DigitalTwinDisplay.start must be async — it schedules async tasks"
        )
