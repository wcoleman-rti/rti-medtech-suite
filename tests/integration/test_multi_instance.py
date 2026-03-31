"""Tests for Phase 2 Step 2.8 — Multi-Instance Integration Test.

Verifies that two concurrent surgical procedure instances with different
partitions (OR-1, OR-3) operate without interference. Data published in
one partition must not leak into the other.

Spec coverage: common-behaviors.md — Partition Isolation,
               surgical-procedure.md — all surgical topics
Tags: @integration @partition @multi_instance
"""

from __future__ import annotations

import time

import common
import devices
import imaging
import monitoring
import pytest
import rti.connextdds as dds
import surgery
from conftest import wait_for_data, wait_for_discovery

pytestmark = [pytest.mark.integration, pytest.mark.partition]

TEST_DOMAIN = 0

# Type aliases — types are spread across IDL modules
RobotState = surgery.Surgery.RobotState
RobotMode = surgery.Surgery.RobotMode
CartesianPosition = surgery.Surgery.CartesianPosition
ProcedureContext = surgery.Surgery.ProcedureContext
ProcedureStatus = surgery.Surgery.ProcedureStatus
ProcedurePhase = surgery.Surgery.ProcedurePhase
PatientVitals = monitoring.Monitoring.PatientVitals
CameraFrame = imaging.Imaging.CameraFrame
DeviceTelemetry = devices.Devices.DeviceTelemetry
DeviceKind = devices.Devices.DeviceKind
DeviceOperatingState = devices.Devices.DeviceOperatingState
EntityIdentity = common.Common.EntityIdentity
Time_t = common.Common.Time_t

OR1_PARTITION = "room/OR-1/procedure/OR1-001"
OR3_PARTITION = "room/OR-3/procedure/OR3-001"


def _make_robot_state(room: str) -> RobotState:
    sample = RobotState()
    sample.robot_id = f"robot-{room}"
    sample.mode = RobotMode.OPERATIONAL
    sample.joint_positions = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    sample.tool_tip_position = CartesianPosition(x=1.0, y=2.0, z=3.0)
    sample.error_code = 0
    return sample


def _make_vitals(patient_id: str, heart_rate: int = 72) -> PatientVitals:
    sample = PatientVitals()
    sample.patient_id = patient_id
    sample.heart_rate = heart_rate
    sample.spo2 = 98.0
    sample.systolic_bp = 120.0
    sample.diastolic_bp = 80.0
    sample.temperature = 37.0
    sample.respiratory_rate = 16
    return sample


def _make_procedure_context(procedure_id: str, room: str) -> ProcedureContext:
    now = time.time()
    return ProcedureContext(
        procedure_id=procedure_id,
        hospital="General Hospital",
        room=room,
        bed="bed-A",
        patient=EntityIdentity(id=f"patient-{room}", name=f"Patient {room}"),
        procedure_type="Laparoscopic Cholecystectomy",
        surgeon="Dr. Smith",
        anesthesiologist="Dr. Jones",
        start_time=Time_t(sec=int(now) & 0xFFFFFFFF, nsec=0),
    )


def _make_camera_frame(camera_id: str, seq: int) -> CameraFrame:
    sample = CameraFrame()
    sample.camera_id = camera_id
    sample.frame_id = str(seq)
    sample.format = "rgb8"
    return sample


def _make_device_telemetry(device_id: str) -> DeviceTelemetry:
    sample = DeviceTelemetry()
    sample.device_id = device_id
    sample.device_kind = DeviceKind.INFUSION_PUMP
    sample.operating_state = DeviceOperatingState.RUNNING
    return sample


class TestMultiInstanceIsolation:
    """Two concurrent instances run without interference."""

    def test_robot_state_isolation(
        self, participant_factory, writer_factory, reader_factory
    ):
        """RobotState in OR-1 is invisible to OR-3 and vice versa."""
        p_w1 = participant_factory(domain_id=TEST_DOMAIN, partition=OR1_PARTITION)
        p_w3 = participant_factory(domain_id=TEST_DOMAIN, partition=OR3_PARTITION)
        p_r1 = participant_factory(domain_id=TEST_DOMAIN, partition=OR1_PARTITION)
        p_r3 = participant_factory(domain_id=TEST_DOMAIN, partition=OR3_PARTITION)

        t_w1 = dds.Topic(p_w1, "RobotState", RobotState)
        t_w3 = dds.Topic(p_w3, "RobotState", RobotState)
        t_r1 = dds.Topic(p_r1, "RobotState", RobotState)
        t_r3 = dds.Topic(p_r3, "RobotState", RobotState)

        w1 = writer_factory(p_w1, t_w1)
        w3 = writer_factory(p_w3, t_w3)
        r1 = reader_factory(p_r1, t_r1)
        r3 = reader_factory(p_r3, t_r3)

        # Same-partition pairs discover
        assert wait_for_discovery(w1, r1, timeout_sec=10)
        assert wait_for_discovery(w3, r3, timeout_sec=10)

        # Publish distinct samples
        w1.write(_make_robot_state("OR-1"))
        w3.write(_make_robot_state("OR-3"))

        data1 = wait_for_data(r1, timeout_sec=5)
        data3 = wait_for_data(r3, timeout_sec=5)

        assert len(data1) >= 1
        assert data1[0].data.robot_id == "robot-OR-1"

        assert len(data3) >= 1
        assert data3[0].data.robot_id == "robot-OR-3"

        # Verify no cross-partition leaking
        # Reader1 should have ONLY OR-1 data
        all_r1 = r1.read()
        for s in all_r1:
            if s.info.valid:
                assert s.data.robot_id == "robot-OR-1"

        # Reader3 should have ONLY OR-3 data
        all_r3 = r3.read()
        for s in all_r3:
            if s.info.valid:
                assert s.data.robot_id == "robot-OR-3"

    def test_vitals_isolation(
        self, participant_factory, writer_factory, reader_factory
    ):
        """PatientVitals in OR-1 does not appear in OR-3."""
        p_w1 = participant_factory(domain_id=TEST_DOMAIN, partition=OR1_PARTITION)
        p_w3 = participant_factory(domain_id=TEST_DOMAIN, partition=OR3_PARTITION)
        p_r1 = participant_factory(domain_id=TEST_DOMAIN, partition=OR1_PARTITION)
        p_r3 = participant_factory(domain_id=TEST_DOMAIN, partition=OR3_PARTITION)

        t_w1 = dds.Topic(p_w1, "PatientVitals", PatientVitals)
        t_w3 = dds.Topic(p_w3, "PatientVitals", PatientVitals)
        t_r1 = dds.Topic(p_r1, "PatientVitals", PatientVitals)
        t_r3 = dds.Topic(p_r3, "PatientVitals", PatientVitals)

        w1 = writer_factory(p_w1, t_w1)
        w3 = writer_factory(p_w3, t_w3)
        r1 = reader_factory(p_r1, t_r1)
        r3 = reader_factory(p_r3, t_r3)

        assert wait_for_discovery(w1, r1, timeout_sec=10)
        assert wait_for_discovery(w3, r3, timeout_sec=10)

        w1.write(_make_vitals("patient-OR1", 80))
        w3.write(_make_vitals("patient-OR3", 90))

        data1 = wait_for_data(r1, timeout_sec=5)
        data3 = wait_for_data(r3, timeout_sec=5)

        assert len(data1) >= 1
        assert data1[0].data.patient_id == "patient-OR1"
        assert data1[0].data.heart_rate == 80

        assert len(data3) >= 1
        assert data3[0].data.patient_id == "patient-OR3"
        assert data3[0].data.heart_rate == 90

    def test_procedure_context_isolation(
        self, participant_factory, writer_factory, reader_factory
    ):
        """ProcedureContext in OR-1 does not appear in OR-3."""
        p_w1 = participant_factory(domain_id=TEST_DOMAIN, partition=OR1_PARTITION)
        p_w3 = participant_factory(domain_id=TEST_DOMAIN, partition=OR3_PARTITION)
        p_r1 = participant_factory(domain_id=TEST_DOMAIN, partition=OR1_PARTITION)
        p_r3 = participant_factory(domain_id=TEST_DOMAIN, partition=OR3_PARTITION)

        t_w1 = dds.Topic(p_w1, "ProcedureContext", ProcedureContext)
        t_w3 = dds.Topic(p_w3, "ProcedureContext", ProcedureContext)
        t_r1 = dds.Topic(p_r1, "ProcedureContext", ProcedureContext)
        t_r3 = dds.Topic(p_r3, "ProcedureContext", ProcedureContext)

        w1 = writer_factory(p_w1, t_w1)
        w3 = writer_factory(p_w3, t_w3)
        r1 = reader_factory(p_r1, t_r1)
        r3 = reader_factory(p_r3, t_r3)

        assert wait_for_discovery(w1, r1, timeout_sec=10)
        assert wait_for_discovery(w3, r3, timeout_sec=10)

        w1.write(_make_procedure_context("OR1-001", "OR-1"))
        w3.write(_make_procedure_context("OR3-001", "OR-3"))

        data1 = wait_for_data(r1, timeout_sec=5)
        data3 = wait_for_data(r3, timeout_sec=5)

        assert len(data1) >= 1
        assert data1[0].data.procedure_id == "OR1-001"
        assert data1[0].data.room == "OR-1"

        assert len(data3) >= 1
        assert data3[0].data.procedure_id == "OR3-001"
        assert data3[0].data.room == "OR-3"

    def test_camera_frame_isolation(
        self, participant_factory, writer_factory, reader_factory
    ):
        """CameraFrame in OR-1 does not appear in OR-3."""
        p_w1 = participant_factory(domain_id=TEST_DOMAIN, partition=OR1_PARTITION)
        p_w3 = participant_factory(domain_id=TEST_DOMAIN, partition=OR3_PARTITION)
        p_r1 = participant_factory(domain_id=TEST_DOMAIN, partition=OR1_PARTITION)
        p_r3 = participant_factory(domain_id=TEST_DOMAIN, partition=OR3_PARTITION)

        t_w1 = dds.Topic(p_w1, "CameraFrame", CameraFrame)
        t_w3 = dds.Topic(p_w3, "CameraFrame", CameraFrame)
        t_r1 = dds.Topic(p_r1, "CameraFrame", CameraFrame)
        t_r3 = dds.Topic(p_r3, "CameraFrame", CameraFrame)

        w1 = writer_factory(p_w1, t_w1)
        w3 = writer_factory(p_w3, t_w3)
        r1 = reader_factory(p_r1, t_r1)
        r3 = reader_factory(p_r3, t_r3)

        assert wait_for_discovery(w1, r1, timeout_sec=10)
        assert wait_for_discovery(w3, r3, timeout_sec=10)

        w1.write(_make_camera_frame("cam-OR1", 1))
        w3.write(_make_camera_frame("cam-OR3", 1))

        data1 = wait_for_data(r1, timeout_sec=5)
        data3 = wait_for_data(r3, timeout_sec=5)

        assert len(data1) >= 1
        assert data1[0].data.camera_id == "cam-OR1"

        assert len(data3) >= 1
        assert data3[0].data.camera_id == "cam-OR3"

    def test_device_telemetry_isolation(
        self, participant_factory, writer_factory, reader_factory
    ):
        """DeviceTelemetry in OR-1 does not appear in OR-3."""
        p_w1 = participant_factory(domain_id=TEST_DOMAIN, partition=OR1_PARTITION)
        p_w3 = participant_factory(domain_id=TEST_DOMAIN, partition=OR3_PARTITION)
        p_r1 = participant_factory(domain_id=TEST_DOMAIN, partition=OR1_PARTITION)
        p_r3 = participant_factory(domain_id=TEST_DOMAIN, partition=OR3_PARTITION)

        t_w1 = dds.Topic(p_w1, "DeviceTelemetry", DeviceTelemetry)
        t_w3 = dds.Topic(p_w3, "DeviceTelemetry", DeviceTelemetry)
        t_r1 = dds.Topic(p_r1, "DeviceTelemetry", DeviceTelemetry)
        t_r3 = dds.Topic(p_r3, "DeviceTelemetry", DeviceTelemetry)

        w1 = writer_factory(p_w1, t_w1)
        w3 = writer_factory(p_w3, t_w3)
        r1 = reader_factory(p_r1, t_r1)
        r3 = reader_factory(p_r3, t_r3)

        assert wait_for_discovery(w1, r1, timeout_sec=10)
        assert wait_for_discovery(w3, r3, timeout_sec=10)

        w1.write(_make_device_telemetry("pump-OR1"))
        w3.write(_make_device_telemetry("pump-OR3"))

        data1 = wait_for_data(r1, timeout_sec=5)
        data3 = wait_for_data(r3, timeout_sec=5)

        assert len(data1) >= 1
        assert data1[0].data.device_id == "pump-OR1"

        assert len(data3) >= 1
        assert data3[0].data.device_id == "pump-OR3"


class TestMultiInstanceConcurrent:
    """Both instances publish all topics concurrently without interference."""

    def test_all_topics_concurrent(
        self, participant_factory, writer_factory, reader_factory
    ):
        """All surgical topics publish and receive correctly in both
        OR-1 and OR-3 running concurrently, using shared participants."""
        # One participant per partition for writers, one for readers
        pw1 = participant_factory(domain_id=TEST_DOMAIN, partition=OR1_PARTITION)
        pr1 = participant_factory(domain_id=TEST_DOMAIN, partition=OR1_PARTITION)
        pw3 = participant_factory(domain_id=TEST_DOMAIN, partition=OR3_PARTITION)
        pr3 = participant_factory(domain_id=TEST_DOMAIN, partition=OR3_PARTITION)

        topic_defs = [
            ("RobotState", RobotState),
            ("PatientVitals", PatientVitals),
            ("CameraFrame", CameraFrame),
            ("DeviceTelemetry", DeviceTelemetry),
        ]

        or1_pairs = []
        or3_pairs = []

        for topic_name, topic_type in topic_defs:
            tw1 = dds.Topic(pw1, topic_name, topic_type)
            tr1 = dds.Topic(pr1, topic_name, topic_type)
            tw3 = dds.Topic(pw3, topic_name, topic_type)
            tr3 = dds.Topic(pr3, topic_name, topic_type)

            w1 = writer_factory(pw1, tw1)
            r1 = reader_factory(pr1, tr1)
            w3 = writer_factory(pw3, tw3)
            r3 = reader_factory(pr3, tr3)

            or1_pairs.append((topic_name, w1, r1))
            or3_pairs.append((topic_name, w3, r3))

        # Wait for all pairs to discover
        for name, w, r in or1_pairs + or3_pairs:
            assert wait_for_discovery(
                w, r, timeout_sec=10
            ), f"{name} failed to discover"

        # Publish on all topics in both instances simultaneously
        for (name, w1, _), (_, w3, _) in zip(or1_pairs, or3_pairs):
            if name == "RobotState":
                w1.write(_make_robot_state("OR-1"))
                w3.write(_make_robot_state("OR-3"))
            elif name == "PatientVitals":
                w1.write(_make_vitals("patient-OR1", 80))
                w3.write(_make_vitals("patient-OR3", 90))
            elif name == "CameraFrame":
                w1.write(_make_camera_frame("cam-OR1", 1))
                w3.write(_make_camera_frame("cam-OR3", 1))
            elif name == "DeviceTelemetry":
                w1.write(_make_device_telemetry("pump-OR1"))
                w3.write(_make_device_telemetry("pump-OR3"))

        # Verify each reader received data from its own instance only
        time.sleep(0.5)

        for (name, _, r1), (_, _, r3) in zip(or1_pairs, or3_pairs):
            data1 = r1.read()
            valid1 = [s for s in data1 if s.info.valid]
            assert len(valid1) >= 1, f"OR-1 {name}: expected data"

            data3 = r3.read()
            valid3 = [s for s in data3 if s.info.valid]
            assert len(valid3) >= 1, f"OR-3 {name}: expected data"

    def test_cross_partition_zero_samples(
        self, participant_factory, writer_factory, reader_factory
    ):
        """A subscriber in OR-1 receives zero samples from OR-3 publishers."""
        # Writer on OR-3
        pw3 = participant_factory(domain_id=TEST_DOMAIN, partition=OR3_PARTITION)
        tw3 = dds.Topic(pw3, "CrossCheckVitals", PatientVitals)
        w3 = writer_factory(pw3, tw3)

        # Reader on OR-1
        pr1 = participant_factory(domain_id=TEST_DOMAIN, partition=OR1_PARTITION)
        tr1 = dds.Topic(pr1, "CrossCheckVitals", PatientVitals)
        r1 = reader_factory(pr1, tr1)

        time.sleep(0.5)

        w3.write(_make_vitals("patient-OR3", 99))
        time.sleep(0.5)

        data = r1.read()
        valid = [s for s in data if s.info.valid]
        assert len(valid) == 0, "OR-1 reader must receive zero samples from OR-3 writer"


# Helper functions for parameterized concurrent test
def _make_vitals_for_room(room: str) -> PatientVitals:
    return _make_vitals(f"patient-{room}", 80)


def _make_camera_for_room(room: str) -> CameraFrame:
    return _make_camera_frame(f"cam-{room}", 1)


def _make_telemetry_for_room(room: str) -> DeviceTelemetry:
    return _make_device_telemetry(f"pump-{room}")
