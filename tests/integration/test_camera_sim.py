"""Tests for Phase 2 Step 2.4 — Camera Simulator.

Covers all test gate items from phase-2-surgical.md Step 2.4:
- Camera frame metadata published at configured rate
- Best-effort delivery: subscriber continues on frame loss without stalling

Spec coverage: surgical-procedure.md — Camera Feed
"""

from __future__ import annotations

import time

import imaging
import pytest
import rti.connextdds as dds
from surgical_procedure.camera_sim.camera_simulator import CameraSimulator

CameraFrame = imaging.Imaging.CameraFrame


# -----------------------------------------------------------------------
# Unit tests — CameraSimulator object construction
# -----------------------------------------------------------------------


class TestCameraSimulatorUnit:
    """Unit tests for CameraSimulator construction and tick logic."""

    def test_default_frame_rate(self):
        """Camera simulator defaults to 30 Hz."""
        sim = CameraSimulator(
            room_id="OR-1",
            procedure_id="proc-001",
        )
        assert sim.frame_rate_hz == 30
        sim.participant.close()

    def test_custom_frame_rate(self):
        """Camera simulator accepts custom frame rate."""
        sim = CameraSimulator(
            room_id="OR-1",
            procedure_id="proc-001",
            frame_rate_hz=15,
        )
        assert sim.frame_rate_hz == 15
        sim.participant.close()

    def test_tick_returns_camera_frame(self):
        """tick() returns a CameraFrame with correct fields."""
        sim = CameraSimulator(
            room_id="OR-1",
            procedure_id="proc-001",
            camera_id="cam-1",
        )
        sim.start()
        frame = sim.tick()

        assert frame.camera_id == "cam-1"
        assert frame.frame_id.startswith("cam-1-")
        assert frame.format == "jpeg"
        assert len(frame.data) > 0
        assert frame.timestamp.sec > 0

        sim.participant.close()

    def test_tick_increments_sequence(self):
        """Successive tick() calls produce incrementing frame IDs."""
        sim = CameraSimulator(
            room_id="OR-1",
            procedure_id="proc-001",
            camera_id="cam-1",
        )
        sim.start()

        f1 = sim.tick()
        f2 = sim.tick()
        f3 = sim.tick()

        assert f1.frame_id == "cam-1-00000000"
        assert f2.frame_id == "cam-1-00000001"
        assert f3.frame_id == "cam-1-00000002"

        sim.participant.close()


# -----------------------------------------------------------------------
# Integration tests — DDS publishing and subscription
# -----------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.streaming
class TestCameraSimulatorIntegration:
    """Integration tests for CameraSimulator DDS publishing."""

    @pytest.fixture
    def camera(self):
        """Create a CameraSimulator and start it."""
        sim = CameraSimulator(
            room_id="OR-1",
            procedure_id="proc-001",
            camera_id="cam-int-1",
            frame_rate_hz=30,
        )
        sim.start()
        yield sim
        sim.participant.close()

    @pytest.fixture
    def frame_reader(self, camera):
        """Create a DataReader for CameraFrame in the same partition."""
        p = dds.DomainParticipant.default_participant_qos
        p.partition.name = ["room/OR-1/procedure/proc-001"]
        p.property["dds.domain_participant.domain_tag"] = "operational"
        dp = dds.DomainParticipant(10, p)

        provider = dds.QosProvider.default
        reader_qos = provider.datareader_qos_from_profile("TopicProfiles::CameraFrame")
        topic = dds.Topic(dp, "CameraFrame", CameraFrame)
        sub = dds.Subscriber(dp)
        reader = dds.DataReader(sub, topic, reader_qos)
        dp.enable()
        yield reader
        dp.close()

    def test_frame_metadata_published(self, camera, frame_reader):
        """spec: Camera frame metadata published at configured rate
        @integration @streaming

        Verifies that CameraFrame samples are delivered with correct
        metadata: camera_id, frame_id (sequence), timestamp,
        resolution reference, and image format.
        """
        # Wait for discovery
        time.sleep(2.0)

        # Publish multiple frames
        published = []
        for _ in range(5):
            published.append(camera.tick())
            time.sleep(0.01)

        # Wait for delivery (best-effort — some may be lost)
        time.sleep(0.5)
        samples = [s for s in frame_reader.take() if s.info.valid]
        assert len(samples) >= 1, "No CameraFrame samples received"

        sample = samples[-1].data
        assert sample.camera_id == "cam-int-1"
        assert sample.frame_id.startswith("cam-int-1-")
        assert sample.format == "jpeg"
        assert len(sample.data) > 0
        assert sample.timestamp.sec > 0

    def test_frame_rate_publication(self, camera, frame_reader):
        """spec: CameraFrame samples are published at 30 Hz
        @integration @streaming

        Publishes frames at the configured rate and verifies that
        the achieved publication timing is within tolerance.
        The reader has KEEP_LAST depth=4 (Stream QoS), so we must
        read periodically during publication to collect all frames.
        """
        # Wait for discovery
        time.sleep(2.0)

        frame_count = 30
        interval = 1.0 / camera.frame_rate_hz
        received = []
        start = time.monotonic()
        for i in range(frame_count):
            camera.tick()
            # Drain reader periodically to avoid overwriting history
            for s in frame_reader.take():
                if s.info.valid:
                    received.append(s.data)
            elapsed = time.monotonic() - start
            next_tick = (i + 1) * interval
            sleep_time = next_tick - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
        wall_time = time.monotonic() - start

        # 30 frames at 30 Hz should take ~1 second
        assert 0.8 <= wall_time <= 1.5, f"30 frames took {wall_time:.3f}s"

        # Final drain
        time.sleep(0.2)
        for s in frame_reader.take():
            if s.info.valid:
                received.append(s.data)

        # Best-effort on localhost — should get most frames
        assert (
            len(received) >= 10
        ), f"Expected >=10 frames received, got {len(received)}"

    def test_best_effort_no_stall(self, camera, frame_reader):
        """spec: Best-effort delivery — subscriber continues on frame
        loss without stalling @integration @streaming

        Verifies that the subscriber can read whatever frames arrive
        without blocking or accumulating a retransmission backlog.
        CameraFrame uses Stream QoS (BEST_EFFORT) so the reader
        never waits for retransmission.
        """
        # Wait for discovery
        time.sleep(2.0)

        # Verify QoS is BEST_EFFORT on the reader side
        reader_qos = frame_reader.qos
        assert (
            reader_qos.reliability.kind == dds.ReliabilityKind.BEST_EFFORT
        ), "CameraFrame reader should use BEST_EFFORT reliability"

        # Publish a burst of frames rapidly
        for _ in range(20):
            camera.tick()

        # Small delay — not waiting for retransmission
        time.sleep(0.3)

        # take() should return immediately (non-blocking) with whatever
        # arrived — no stall, no retransmission wait
        t0 = time.monotonic()
        list(frame_reader.take())
        take_time = time.monotonic() - t0

        # take() should complete nearly instantly (< 100 ms)
        assert take_time < 0.1, f"take() took {take_time:.3f}s — possible stall"

        # Second take should also return immediately (empty or near-empty)
        t0 = time.monotonic()
        _ = list(frame_reader.take())
        take_time_2 = time.monotonic() - t0
        assert take_time_2 < 0.1, f"Second take() took {take_time_2:.3f}s"
