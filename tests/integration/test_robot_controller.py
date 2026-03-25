"""Tests for Step 2.2 — Robot Simulator DDS QoS behaviors.

Spec coverage: surgical-procedure.md — Robot Teleop & Control
Tags: @integration @streaming @command

Tests the DDS QoS behavior for control topics (RobotState, OperatorInput,
RobotCommand, SafetyInterlock) using in-process writer/reader pairs.
The robot controller state machine logic is tested separately via C++ GTest
(test_robot_controller.cpp).
"""

from __future__ import annotations

import time

import pytest
import rti.connextdds as dds
import surgery
from conftest import wait_for_data, wait_for_discovery

pytestmark = [pytest.mark.integration]

# Type aliases
RobotState = surgery.Surgery.RobotState
RobotCommand = surgery.Surgery.RobotCommand
SafetyInterlock = surgery.Surgery.SafetyInterlock
OperatorInput = surgery.Surgery.OperatorInput
RobotMode = surgery.Surgery.RobotMode


class TestRobotStateQoS:
    """Tests for RobotState DDS QoS behavior."""

    def test_robot_state_published_with_correct_fields(
        self, participant_factory, writer_factory, reader_factory
    ):
        """Robot state is published with all required fields.

        Spec: RobotState samples contain joint positions, operational mode,
              and error state.
        """
        partition = "room/OR-1/procedure/rsf-test"
        writer_p = participant_factory(
            domain_id=0, domain_tag="control", partition=partition
        )
        reader_p = participant_factory(
            domain_id=0, domain_tag="control", partition=partition
        )
        provider = dds.QosProvider.default

        topic_w = dds.Topic(writer_p, "RobotState", RobotState)
        topic_r = dds.Topic(reader_p, "RobotState", RobotState)

        writer_qos = provider.datawriter_qos_from_profile("TopicProfiles::RobotState")
        reader_qos = provider.datareader_qos_from_profile("TopicProfiles::RobotState")

        writer = writer_factory(writer_p, topic_w, qos=writer_qos)
        reader = reader_factory(reader_p, topic_r, qos=reader_qos)

        assert wait_for_discovery(writer, reader, timeout_sec=10)

        state = RobotState(
            robot_id="robot-001",
            joint_positions=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
            tool_tip_position=surgery.Surgery.CartesianPosition(x=1.0, y=2.0, z=3.0),
            operational_mode=RobotMode.OPERATIONAL,
            error_state=0,
        )
        writer.write(state)

        received = wait_for_data(reader, timeout_sec=5)
        assert len(received) >= 1
        data = received[0].data
        assert data.robot_id == "robot-001"
        assert len(data.joint_positions) == 7
        assert abs(data.joint_positions[0] - 0.1) < 1e-9
        assert data.operational_mode == RobotMode.OPERATIONAL
        assert data.error_state == 0
        assert abs(data.tool_tip_position.x - 1.0) < 1e-9

    def test_robot_state_late_joiner_receives_state(
        self, participant_factory, writer_factory, reader_factory
    ):
        """Late joiner receives current RobotState via TRANSIENT_LOCAL.

        Spec: RobotState uses State QoS with TRANSIENT_LOCAL durability.
        """
        partition = "room/OR-2/procedure/rslj-test"
        writer_p = participant_factory(
            domain_id=0, domain_tag="control", partition=partition
        )
        provider = dds.QosProvider.default

        topic_w = dds.Topic(writer_p, "RobotState", RobotState)
        writer_qos = provider.datawriter_qos_from_profile("TopicProfiles::RobotState")
        writer = writer_factory(writer_p, topic_w, qos=writer_qos)

        # Publish BEFORE reader exists
        state = RobotState(
            robot_id="robot-late",
            joint_positions=[0.0] * 7,
            operational_mode=RobotMode.IDLE,
            error_state=0,
        )
        writer.write(state)
        time.sleep(0.5)

        # Late-joining reader
        reader_p = participant_factory(
            domain_id=0, domain_tag="control", partition=partition
        )
        topic_r = dds.Topic(reader_p, "RobotState", RobotState)
        reader_qos = provider.datareader_qos_from_profile("TopicProfiles::RobotState")
        reader = reader_factory(reader_p, topic_r, qos=reader_qos)

        received = wait_for_data(reader, timeout_sec=5)
        assert len(received) >= 1
        assert received[0].data.robot_id == "robot-late"


class TestOperatorInputQoS:
    """Tests for OperatorInput DDS QoS behavior."""

    def test_operator_input_delivery(
        self, participant_factory, writer_factory, reader_factory
    ):
        """Operator input is delivered to subscriber.

        Spec: OperatorInput published with TopicProfiles::OperatorInput QoS
              is delivered to subscriber in the same partition.
        """
        partition = "room/OR-3/procedure/oi-test"
        writer_p = participant_factory(
            domain_id=0, domain_tag="control", partition=partition
        )
        reader_p = participant_factory(
            domain_id=0, domain_tag="control", partition=partition
        )
        provider = dds.QosProvider.default

        topic_w = dds.Topic(writer_p, "OperatorInput", OperatorInput)
        topic_r = dds.Topic(reader_p, "OperatorInput", OperatorInput)
        w_qos = provider.datawriter_qos_from_profile("TopicProfiles::OperatorInput")
        r_qos = provider.datareader_qos_from_profile("TopicProfiles::OperatorInput")

        writer = writer_factory(writer_p, topic_w, qos=w_qos)
        reader = reader_factory(reader_p, topic_r, qos=r_qos)

        assert wait_for_discovery(writer, reader, timeout_sec=10)

        op_input = OperatorInput(
            operator_id="op-001",
            robot_id="robot-001",
            x_axis=5.0,
            y_axis=-3.0,
            z_axis=1.0,
            roll=0.5,
            pitch=-0.3,
            yaw=0.1,
        )
        writer.write(op_input)

        # OperatorInput has a 20 ms lifespan — poll with short interval
        deadline = time.time() + 5.0
        received = []
        while time.time() < deadline:
            samples = reader.take()
            valid = [s for s in samples if s.info.valid]
            if valid:
                received = valid
                break
            time.sleep(0.002)  # 2 ms poll — must beat 20 ms lifespan
        assert len(received) >= 1, "No OperatorInput received"
        data = received[0].data
        assert data.operator_id == "op-001"
        assert abs(data.x_axis - 5.0) < 1e-9

    def test_stale_operator_input_discarded_by_lifespan(
        self, participant_factory, writer_factory, reader_factory
    ):
        """Stale operator input (expired lifespan) is not applied.

        Spec: Given OperatorInput with Lifespan20ms snippet (lifespan = 20 ms)
              When the robot controller reads a sample older than 20 ms
              Then the sample is discarded by DDS before delivery.

        Verified by writing a sample, waiting well beyond the lifespan,
        and confirming take() returns no valid samples.
        """
        partition = "room/OR-3/procedure/lifespan-test"
        writer_p = participant_factory(
            domain_id=0, domain_tag="control", partition=partition
        )
        reader_p = participant_factory(
            domain_id=0, domain_tag="control", partition=partition
        )
        provider = dds.QosProvider.default

        topic_w = dds.Topic(writer_p, "OperatorInput", OperatorInput)
        topic_r = dds.Topic(reader_p, "OperatorInput", OperatorInput)
        w_qos = provider.datawriter_qos_from_profile("TopicProfiles::OperatorInput")
        r_qos = provider.datareader_qos_from_profile("TopicProfiles::OperatorInput")

        writer = writer_factory(writer_p, topic_w, qos=w_qos)
        reader = reader_factory(reader_p, topic_r, qos=r_qos)

        assert wait_for_discovery(writer, reader, timeout_sec=10)

        op_input = OperatorInput(
            operator_id="op-stale",
            robot_id="robot-001",
            x_axis=1.0,
        )
        writer.write(op_input)

        # Wait well beyond 20 ms lifespan
        time.sleep(0.2)

        # Any samples should have expired — take() returns nothing valid
        samples = reader.take()
        valid = [s for s in samples if s.info.valid]
        assert (
            len(valid) == 0
        ), f"Expected 0 valid samples after lifespan expiry, got {len(valid)}"


class TestSafetyInterlockQoS:
    """Tests for SafetyInterlock DDS QoS behavior."""

    def test_safety_interlock_delivery_reliable(
        self, participant_factory, writer_factory, reader_factory
    ):
        """Safety interlock uses reliable delivery with State QoS.

        Spec: SafetyInterlock uses State QoS (RELIABLE, TRANSIENT_LOCAL).
        """
        partition = "room/OR-4/procedure/si-test"
        writer_p = participant_factory(
            domain_id=0, domain_tag="control", partition=partition
        )
        reader_p = participant_factory(
            domain_id=0, domain_tag="control", partition=partition
        )
        provider = dds.QosProvider.default

        topic_w = dds.Topic(writer_p, "SafetyInterlock", SafetyInterlock)
        topic_r = dds.Topic(reader_p, "SafetyInterlock", SafetyInterlock)
        w_qos = provider.datawriter_qos_from_profile("TopicProfiles::SafetyInterlock")
        r_qos = provider.datareader_qos_from_profile("TopicProfiles::SafetyInterlock")

        writer = writer_factory(writer_p, topic_w, qos=w_qos)
        reader = reader_factory(reader_p, topic_r, qos=r_qos)

        assert wait_for_discovery(writer, reader, timeout_sec=10)

        interlock = SafetyInterlock(
            robot_id="robot-001",
            interlock_active=True,
            reason="E-stop pressed",
        )
        writer.write(interlock)

        received = wait_for_data(reader, timeout_sec=5)
        assert len(received) >= 1
        data = received[0].data
        assert data.interlock_active == True  # noqa: E712 — DDS returns int
        assert data.reason == "E-stop pressed"


class TestRobotCommandQoS:
    """Tests for RobotCommand DDS QoS behavior."""

    def test_robot_command_reliable_ordered(
        self, participant_factory, writer_factory, reader_factory
    ):
        """Robot commands are delivered reliably and in order.

        Spec: RobotCommand with Command QoS (RELIABLE, VOLATILE, KEEP_LAST 1)
              delivers commands in publication order.
        """
        partition = "room/OR-5/procedure/cmd-test"
        writer_p = participant_factory(
            domain_id=0, domain_tag="control", partition=partition
        )
        reader_p = participant_factory(
            domain_id=0, domain_tag="control", partition=partition
        )
        provider = dds.QosProvider.default

        topic_w = dds.Topic(writer_p, "RobotCommand", RobotCommand)
        topic_r = dds.Topic(reader_p, "RobotCommand", RobotCommand)
        w_qos = provider.datawriter_qos_from_profile("TopicProfiles::RobotCommand")
        r_qos = provider.datareader_qos_from_profile("TopicProfiles::RobotCommand")

        writer = writer_factory(writer_p, topic_w, qos=w_qos)
        reader = reader_factory(reader_p, topic_r, qos=r_qos)

        assert wait_for_discovery(writer, reader, timeout_sec=10)

        # Send 3 commands with different keys to avoid KEEP_LAST 1 overlap
        for i in range(3):
            cmd = RobotCommand(
                robot_id=f"robot-{i:03d}",
                command_id=i + 1,
                target_position=surgery.Surgery.CartesianPosition(
                    x=float(i), y=float(i * 10), z=0.0
                ),
            )
            writer.write(cmd)

        time.sleep(0.5)
        samples = reader.take()
        valid = [s for s in samples if s.info.valid]

        # Should receive all 3 (different keys = distinct instances)
        assert len(valid) >= 3, f"Expected 3 commands, got {len(valid)}"
        # Verify ordering by checking command_ids are ascending
        ids = [s.data.command_id for s in valid]
        assert ids == sorted(ids), f"Commands out of order: {ids}"

    def test_operator_input_deadline_qos_enforced(
        self, participant_factory, writer_factory, reader_factory
    ):
        """OperatorInput deadline QoS is enforced by DDS.

        Spec: 4 ms deadline enforced by DDS Deadline QoS —
              REQUESTED_DEADLINE_MISSED status on the reader indicates
              a stream interruption.

        We verify the deadline QoS is configured by checking that when
        no OperatorInput arrives for longer than the deadline period,
        the reader's REQUESTED_DEADLINE_MISSED status count increments.
        """
        partition = "room/OR-6/procedure/deadline-test"
        writer_p = participant_factory(
            domain_id=0, domain_tag="control", partition=partition
        )
        reader_p = participant_factory(
            domain_id=0, domain_tag="control", partition=partition
        )
        provider = dds.QosProvider.default

        topic_w = dds.Topic(writer_p, "OperatorInput", OperatorInput)
        topic_r = dds.Topic(reader_p, "OperatorInput", OperatorInput)
        w_qos = provider.datawriter_qos_from_profile("TopicProfiles::OperatorInput")
        r_qos = provider.datareader_qos_from_profile("TopicProfiles::OperatorInput")

        writer = writer_factory(writer_p, topic_w, qos=w_qos)
        reader = reader_factory(reader_p, topic_r, qos=r_qos)

        assert wait_for_discovery(writer, reader, timeout_sec=10)

        # Write one sample to start the deadline clock
        op_input = OperatorInput(
            operator_id="op-deadline",
            robot_id="robot-001",
            x_axis=1.0,
        )
        writer.write(op_input)

        # Wait well past the 4 ms deadline without sending more
        time.sleep(0.5)

        status = reader.requested_deadline_missed_status
        assert status.total_count >= 1, (
            f"Expected deadline miss after 500 ms silence, "
            f"got total_count={status.total_count}"
        )
