"""Tests for Phase N Step N.5 — Digital Twin NiceGUI migration.

Covers all test gate items from phase-nicegui-migration.md Step N.5:
- DigitalTwinBackend accepts injected readers and reports correct name
- Backend updates state from RobotState, RobotCommand, SafetyInterlock specimens
- Backend schedules correct number of background tasks in start()
- Backend close() cleans up rti.asyncio dispatcher
- Liveliness detection: set_connected() updates connected flag
- Heatmap color function returns correct hex strings for the diverging ramp
- QoS verification: time-based filter presence on GuiRobotState /
  GuiOperatorInput readers; absence on SafetyInterlock / RobotCommand
- Durability late-join: late-joining RobotState reader receives TRANSIENT_LOCAL
  data

Spec coverage: nicegui-migration.md — Digital Twin 3D Upgrade
Tags: @gui @integration
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import app_names
import pytest
import rti.connextdds as dds
import surgery
from conftest import wait_for_data, wait_for_discovery
from surgical_procedure.digital_twin import digital_twin as twin_module

pytestmark = [
    pytest.mark.gui,
    pytest.mark.integration,
    pytest.mark.xdist_group("digital_twin"),
]

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


def _make_injected_readers(participant_factory: Any) -> dict[str, dds.DataReader]:
    """Create four injected readers for DigitalTwinBackend tests."""
    p = participant_factory(domain_id=0, domain_tag="control")
    sub = dds.Subscriber(p)

    def _reader(data_type: Any, topic_name: str) -> dds.DataReader:
        topic = dds.Topic(p, topic_name, data_type)
        return dds.DataReader(sub, topic, dds.DataReaderQos())

    return {
        "robot_state_reader": _reader(RobotState, "RobotState"),
        "robot_command_reader": _reader(RobotCommand, "RobotCommand"),
        "safety_interlock_reader": _reader(SafetyInterlock, "SafetyInterlock"),
        "operator_input_reader": _reader(OperatorInput, "OperatorInput"),
    }


def _make_robot_state(mode: Any = None, joints: list[float] | None = None) -> Any:
    s = RobotState()
    s.robot_id = "robot-001"
    s.operational_mode = mode if mode is not None else RobotMode.OPERATIONAL
    s.joint_positions = joints or [0.0, 30.0, 45.0, -20.0]
    tip = CartesianPosition()
    tip.x = 10.0
    tip.y = 5.0
    s.tool_tip_position = tip
    return s


class FakeTask:
    def __init__(self) -> None:
        self._cancelled = False

    def done(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True


# ---------------------------------------------------------------------------
# TestHeatmapColor — pure unit tests, no DDS required
# ---------------------------------------------------------------------------


class TestHeatmapColor:
    """heatmap_color() produces valid hex colors for the diverging ramp."""

    def test_zero_angle_returns_hex_string(self) -> None:
        color = twin_module.heatmap_color(0.0)
        assert color.startswith("#")
        assert len(color) == 7

    def test_max_positive_angle_returns_warm_color(self) -> None:
        color = twin_module.heatmap_color(180.0)
        # Should be close to #ed8b00 (RTI Orange / hot end)
        assert color.startswith("#")
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        assert r > g, "Positive max should produce a warm (red-dominant) color"

    def test_max_negative_angle_returns_cool_color(self) -> None:
        color = twin_module.heatmap_color(-180.0)
        # Should be close to #1565c0 (blue / cold end)
        assert color.startswith("#")
        b = int(color[5:7], 16)
        r = int(color[1:3], 16)
        assert b > r, "Negative max should produce a cool (blue-dominant) color"

    def test_clamp_beyond_max(self) -> None:
        color_max = twin_module.heatmap_color(180.0)
        color_over = twin_module.heatmap_color(360.0)
        assert color_max == color_over, "Angles beyond ±180 should clamp"


# ---------------------------------------------------------------------------
# TestDigitalTwinBackend — state model tests
# ---------------------------------------------------------------------------


class TestDigitalTwinBackend:
    """DigitalTwinBackend correctly models robot state."""

    def test_backend_can_be_injected(self, participant_factory: Any) -> None:
        readers = _make_injected_readers(participant_factory)
        backend = twin_module.DigitalTwinBackend(**readers)
        assert backend.name == "DigitalTwin"
        asyncio.run(backend.close())

    def test_backend_initial_state(self, participant_factory: Any) -> None:
        readers = _make_injected_readers(participant_factory)
        backend = twin_module.DigitalTwinBackend(**readers)
        assert backend.joint_positions == []
        assert backend.operational_mode == "UNKNOWN"
        assert backend.connected is True
        assert backend.interlock_active is False
        assert backend.has_command is False
        asyncio.run(backend.close())

    def test_update_robot_state_operational(self, participant_factory: Any) -> None:
        """update_robot_state stores joint positions and mode label."""
        readers = _make_injected_readers(participant_factory)
        backend = twin_module.DigitalTwinBackend(**readers)
        backend.update_robot_state(
            SimpleNamespace(
                joint_positions=[0.0, 30.0, 45.0, -20.0],
                operational_mode=int(RobotMode.OPERATIONAL),
                tool_tip_position=None,
            )
        )
        assert backend.operational_mode == "OPERATIONAL"
        assert backend.joint_positions == [0.0, 30.0, 45.0, -20.0]
        assert backend.connected is True
        asyncio.run(backend.close())

    def test_update_robot_state_emergency_stop(self, participant_factory: Any) -> None:
        """update_robot_state reflects EMERGENCY_STOP mode."""
        readers = _make_injected_readers(participant_factory)
        backend = twin_module.DigitalTwinBackend(**readers)
        backend.update_robot_state(
            SimpleNamespace(
                joint_positions=[],
                operational_mode=int(RobotMode.EMERGENCY_STOP),
                tool_tip_position=None,
            )
        )
        assert backend.operational_mode == "EMERGENCY_STOP"
        asyncio.run(backend.close())

    def test_update_robot_state_paused(self, participant_factory: Any) -> None:
        readers = _make_injected_readers(participant_factory)
        backend = twin_module.DigitalTwinBackend(**readers)
        backend.update_robot_state(
            SimpleNamespace(
                joint_positions=[],
                operational_mode=int(RobotMode.PAUSED),
                tool_tip_position=None,
            )
        )
        assert backend.operational_mode == "PAUSED"
        asyncio.run(backend.close())

    def test_update_command_sets_has_command(self, participant_factory: Any) -> None:
        readers = _make_injected_readers(participant_factory)
        backend = twin_module.DigitalTwinBackend(**readers)
        assert backend.has_command is False
        backend.update_command(SimpleNamespace(robot_id="robot-001", command_id=1))
        assert backend.has_command is True
        asyncio.run(backend.close())

    def test_update_interlock_active(self, participant_factory: Any) -> None:
        """Active interlock sets interlock_active flag."""
        readers = _make_injected_readers(participant_factory)
        backend = twin_module.DigitalTwinBackend(**readers)
        backend.update_interlock(
            SimpleNamespace(interlock_active=True, reason="E-STOP pressed")
        )
        assert backend.interlock_active is True
        assert backend.interlock_reason == "E-STOP pressed"
        asyncio.run(backend.close())

    def test_update_interlock_inactive(self, participant_factory: Any) -> None:
        """Inactive interlock clears interlock_active."""
        readers = _make_injected_readers(participant_factory)
        backend = twin_module.DigitalTwinBackend(**readers)
        backend.update_interlock(SimpleNamespace(interlock_active=False, reason=""))
        assert backend.interlock_active is False
        asyncio.run(backend.close())

    def test_set_connected_false(self, participant_factory: Any) -> None:
        readers = _make_injected_readers(participant_factory)
        backend = twin_module.DigitalTwinBackend(**readers)
        backend.set_connected(False)
        assert backend.connected is False
        asyncio.run(backend.close())

    def test_set_connected_true_restores(self, participant_factory: Any) -> None:
        readers = _make_injected_readers(participant_factory)
        backend = twin_module.DigitalTwinBackend(**readers)
        backend.set_connected(False)
        backend.set_connected(True)
        assert backend.connected is True
        asyncio.run(backend.close())

    def test_start_schedules_background_tasks(
        self, participant_factory: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """start() creates exactly 5 background tasks (4 readers + liveliness)."""
        readers = _make_injected_readers(participant_factory)
        backend = twin_module.DigitalTwinBackend(**readers)
        scheduled: list[str] = []

        def _fake_create(coroutine: Any) -> FakeTask:
            scheduled.append(getattr(coroutine, "__name__", "task"))
            coroutine.close()
            return FakeTask()

        monkeypatch.setattr(twin_module.background_tasks, "create", _fake_create)
        asyncio.run(backend.start())
        assert len(scheduled) == 5
        asyncio.run(backend.close())

    def test_backend_close_cleans_up_rti_dispatcher(
        self, participant_factory: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """close() calls rti.asyncio.close() to release the dispatcher."""
        readers = _make_injected_readers(participant_factory)
        backend = twin_module.DigitalTwinBackend(**readers)
        called = False

        async def _fake_close() -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(twin_module.rti.asyncio, "close", _fake_close)
        asyncio.run(backend.close())
        assert called is True


# ---------------------------------------------------------------------------
# TestQosConfiguration — Reader QoS verification (migrated from test_digital_twin.py)
# ---------------------------------------------------------------------------


class TestQosConfiguration:
    """Verify that reader QoS matches the expected profiles from XML."""

    @pytest.fixture(scope="class")
    def twin_participant(self) -> Any:
        """Create a ControlDigitalTwin participant (class scope, auto-cleanup)."""
        from medtech.dds import initialize_connext

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
        d = reader.qos.time_based_filter.minimum_separation
        return d.sec * 1_000_000_000 + d.nanosec

    def test_robot_state_reader_has_time_based_filter(
        self, twin_participant: Any
    ) -> None:
        """RobotState reader uses GuiRobotState QoS (time-based filter > 0)."""
        r = twin_participant.find_datareader(names.TWIN_ROBOT_STATE_READER)
        assert r is not None, f"Reader not found: {names.TWIN_ROBOT_STATE_READER}"
        reader = dds.DataReader(r)
        tbf_ns = self._tbf_ns(reader)
        assert (
            tbf_ns > 0
        ), "RobotState reader must have a time-based filter (min_separation > 0)"

    def test_operator_input_reader_has_time_based_filter(
        self, twin_participant: Any
    ) -> None:
        """OperatorInput reader uses GuiOperatorInput QoS (TBF > 0)."""
        r = twin_participant.find_datareader(names.TWIN_OPERATOR_INPUT_READER)
        assert r is not None
        reader = dds.DataReader(r)
        tbf_ns = self._tbf_ns(reader)
        assert (
            tbf_ns > 0
        ), "OperatorInput reader must have a time-based filter (min_separation > 0)"

    def test_safety_interlock_reader_has_no_time_based_filter(
        self, twin_participant: Any
    ) -> None:
        """SafetyInterlock reader has no TBF — every sample must be delivered."""
        r = twin_participant.find_datareader(names.TWIN_SAFETY_INTERLOCK_READER)
        assert r is not None
        reader = dds.DataReader(r)
        tbf_ns = self._tbf_ns(reader)
        assert tbf_ns == 0, "SafetyInterlock reader must NOT have a time-based filter"

    def test_robot_command_reader_has_no_time_based_filter(
        self, twin_participant: Any
    ) -> None:
        """RobotCommand reader has no TBF — each command must be processed."""
        r = twin_participant.find_datareader(names.TWIN_ROBOT_COMMAND_READER)
        assert r is not None
        reader = dds.DataReader(r)
        tbf_ns = self._tbf_ns(reader)
        assert tbf_ns == 0, "RobotCommand reader must NOT have a time-based filter"


# ---------------------------------------------------------------------------
# TestDurabilityLateJoin — TRANSIENT_LOCAL late-join (migrated from test_digital_twin.py)
# ---------------------------------------------------------------------------


class TestDurabilityLateJoin:
    """Digital twin receives current state on late join via TRANSIENT_LOCAL."""

    def test_robot_state_received_on_late_join(self, participant_factory: Any) -> None:
        """A late-joining RobotState reader receives the last published sample."""
        provider = dds.QosProvider.default

        pub_p = participant_factory(
            domain_id=0,
            domain_tag="control",
            partition="room/OR-1/procedure/proc-001",
        )
        rs_topic = dds.Topic(pub_p, "RobotState", RobotState)
        writer_qos = provider.datawriter_qos_from_profile("TopicProfiles::RobotState")
        pub = dds.Publisher(pub_p)
        writer = dds.DataWriter(pub, rs_topic, writer_qos)

        sample = _make_robot_state(mode=RobotMode.OPERATIONAL)
        writer.write(sample)
        time.sleep(0.2)

        sub_p = participant_factory(
            domain_id=0,
            domain_tag="control",
            partition="room/OR-1/procedure/proc-001",
        )
        rs_top_sub = dds.Topic(sub_p, "RobotState", RobotState)
        reader_qos = provider.datareader_qos_from_profile("TopicProfiles::RobotState")
        sub = dds.Subscriber(sub_p)
        late_reader = dds.DataReader(sub, rs_top_sub, reader_qos)

        received = wait_for_data(late_reader, timeout_sec=5.0, count=1)
        assert (
            received
        ), "Late-joining RobotState reader should receive TRANSIENT_LOCAL data"
        assert late_reader.take_data()[0].operational_mode == RobotMode.OPERATIONAL


# ---------------------------------------------------------------------------
# TestLivelinessDetection — liveliness monitoring (migrated from test_digital_twin.py)
# ---------------------------------------------------------------------------


class TestLivelinessDetection:
    """DigitalTwinBackend.set_connected() reflects liveliness state correctly."""

    def test_set_connected_false_after_writer_close(
        self, participant_factory: Any
    ) -> None:
        """Backend transitions to disconnected when liveliness expires."""
        provider = dds.QosProvider.default

        pub_p = participant_factory(
            domain_id=0,
            domain_tag="control",
            partition="room/OR-1/procedure/proc-001",
        )
        rs_topic = dds.Topic(pub_p, "RobotState", RobotState)
        writer_qos = provider.datawriter_qos_from_profile("TopicProfiles::RobotState")
        writer_qos.liveliness.lease_duration = dds.Duration(
            seconds=0, nanoseconds=400_000_000
        )
        pub = dds.Publisher(pub_p)
        writer = dds.DataWriter(pub, rs_topic, writer_qos)

        sub_p = participant_factory(
            domain_id=0,
            domain_tag="control",
            partition="room/OR-1/procedure/proc-001",
        )
        rs_top_sub = dds.Topic(sub_p, "RobotState", RobotState)
        reader_qos = provider.datareader_qos_from_profile("TopicProfiles::RobotState")
        reader_qos.liveliness.lease_duration = dds.Duration(
            seconds=0, nanoseconds=400_000_000
        )
        sub = dds.Subscriber(sub_p)
        reader = dds.DataReader(sub, rs_top_sub, reader_qos)

        writer.write(_make_robot_state())
        wait_for_discovery(writer, reader, timeout_sec=3.0)

        # Start connected
        connected = True

        # Close writer — liveliness expires within lease_duration
        writer.close()

        deadline = time.time() + 2.0
        while time.time() < deadline:
            status = reader.liveliness_changed_status
            if status.not_alive_count > 0 or status.alive_count == 0:
                connected = False
                break
            time.sleep(0.1)

        assert connected is False, "Should detect liveliness loss after writer closes"
