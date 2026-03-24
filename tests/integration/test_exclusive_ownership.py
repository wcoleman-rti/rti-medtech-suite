"""Integration tests: Exclusive Ownership / Failover.

Spec: common-behaviors.md — Exclusive Ownership / Failover
Tags: @integration @failover

Tests exclusive ownership strength preference, failover to backup on
primary failure, and primary reclaim on recovery using DeviceTelemetry.
"""

import time

import devices
import rti.connextdds as dds
from conftest import wait_for_data, wait_for_discovery

TEST_DOMAIN = 0
DeviceTelemetry = devices.Devices.DeviceTelemetry


def _make_telemetry(
    device_id: str,
    battery: float = 100.0,
) -> DeviceTelemetry:
    """Create a DeviceTelemetry sample with the given key."""
    sample = DeviceTelemetry()
    sample.device_id = device_id
    sample.battery_percent = battery
    return sample


def _make_exclusive_writer_qos(strength: int) -> dds.DataWriterQos:
    """Create DataWriterQos with exclusive ownership and given strength."""
    qos = dds.DataWriterQos()
    qos.ownership.kind = dds.OwnershipKind.EXCLUSIVE
    qos.ownership_strength.value = strength
    qos.reliability.kind = dds.ReliabilityKind.RELIABLE
    qos.liveliness.kind = dds.LivelinessKind.MANUAL_BY_PARTICIPANT
    qos.liveliness.lease_duration = dds.Duration.from_seconds(1.0)
    return qos


def _make_exclusive_reader_qos() -> dds.DataReaderQos:
    """Create DataReaderQos with exclusive ownership."""
    qos = dds.DataReaderQos()
    qos.ownership.kind = dds.OwnershipKind.EXCLUSIVE
    qos.reliability.kind = dds.ReliabilityKind.RELIABLE
    qos.liveliness.kind = dds.LivelinessKind.MANUAL_BY_PARTICIPANT
    qos.liveliness.lease_duration = dds.Duration.from_seconds(1.0)
    return qos


class TestHigherStrengthPreferred:
    """Higher-strength writer is preferred when both are alive."""

    def test_subscriber_receives_from_stronger_writer(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        """Given writer A (strength 100) and writer B (strength 50),
        subscribers receive data only from writer A."""
        p_a = participant_factory(domain_id=TEST_DOMAIN)
        p_b = participant_factory(domain_id=TEST_DOMAIN)
        p_r = participant_factory(domain_id=TEST_DOMAIN)

        topic_a = dds.Topic(p_a, "OwnershipTest", DeviceTelemetry)
        topic_b = dds.Topic(p_b, "OwnershipTest", DeviceTelemetry)
        topic_r = dds.Topic(p_r, "OwnershipTest", DeviceTelemetry)

        w_a = writer_factory(
            p_a,
            topic_a,
            qos=_make_exclusive_writer_qos(100),
        )
        w_b = writer_factory(
            p_b,
            topic_b,
            qos=_make_exclusive_writer_qos(50),
        )
        r = reader_factory(p_r, topic_r, qos=_make_exclusive_reader_qos())

        p_a.assert_liveliness()
        p_b.assert_liveliness()

        assert wait_for_discovery(w_a, r, timeout_sec=10)
        assert wait_for_discovery(w_b, r, timeout_sec=10)

        # Both writers publish for the same device (same key)
        w_a.write(_make_telemetry("device-001", battery=90.0))
        p_a.assert_liveliness()
        time.sleep(0.1)
        w_b.write(_make_telemetry("device-001", battery=50.0))
        p_b.assert_liveliness()
        time.sleep(0.5)

        received = r.take()
        valid = [s for s in received if s.info.valid]
        assert len(valid) >= 1, "Should receive at least one sample"
        # Only writer A's data should be delivered (battery=90)
        batteries = [s.data.battery_percent for s in valid]
        assert all(
            b == 90.0 for b in batteries
        ), f"All samples should be from strong writer (90.0), got {batteries}"


class TestFailoverToBackup:
    """Failover to backup writer when primary fails."""

    def test_backup_takes_over_on_primary_failure(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        """Given writer A (strength 100) fails, subscribers automatically
        begin receiving from writer B (strength 50)."""
        p_a = participant_factory(domain_id=TEST_DOMAIN)
        p_b = participant_factory(domain_id=TEST_DOMAIN)
        p_r = participant_factory(domain_id=TEST_DOMAIN)

        topic_a = dds.Topic(p_a, "FailoverTest", DeviceTelemetry)
        topic_b = dds.Topic(p_b, "FailoverTest", DeviceTelemetry)
        topic_r = dds.Topic(p_r, "FailoverTest", DeviceTelemetry)

        w_a = writer_factory(
            p_a,
            topic_a,
            qos=_make_exclusive_writer_qos(100),
        )
        w_b = writer_factory(
            p_b,
            topic_b,
            qos=_make_exclusive_writer_qos(50),
        )
        r = reader_factory(p_r, topic_r, qos=_make_exclusive_reader_qos())

        p_a.assert_liveliness()
        p_b.assert_liveliness()

        assert wait_for_discovery(w_a, r, timeout_sec=10)
        assert wait_for_discovery(w_b, r, timeout_sec=10)

        # Confirm primary is delivering
        w_a.write(_make_telemetry("device-001", battery=90.0))
        p_a.assert_liveliness()
        time.sleep(0.1)
        w_b.write(_make_telemetry("device-001", battery=50.0))
        p_b.assert_liveliness()

        received = wait_for_data(r, timeout_sec=5)
        assert any(
            s.data.battery_percent == 90.0 for s in received
        ), "Should initially receive from primary (battery=90)"

        # Drain the reader
        r.take()

        # Kill primary (simulates crash)
        p_a.close()

        # Keep backup alive and publishing
        for _ in range(5):
            p_b.assert_liveliness()
            w_b.write(_make_telemetry("device-001", battery=55.0))
            time.sleep(0.5)

        received = r.take()
        valid = [s for s in received if s.info.valid]
        assert len(valid) >= 1, "Backup should deliver data after primary failure"
        assert any(
            s.data.battery_percent == 55.0 for s in valid
        ), "Should receive backup writer's data (battery=55)"


class TestPrimaryReclaim:
    """Primary reclaims ownership on recovery."""

    def test_primary_reclaims_after_recovery(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        """Given writer B has taken over, when writer A recovers,
        subscribers switch back to writer A."""
        p_a = participant_factory(domain_id=TEST_DOMAIN)
        p_b = participant_factory(domain_id=TEST_DOMAIN)
        p_r = participant_factory(domain_id=TEST_DOMAIN)

        topic_a = dds.Topic(p_a, "ReclaimTest", DeviceTelemetry)
        topic_b = dds.Topic(p_b, "ReclaimTest", DeviceTelemetry)
        topic_r = dds.Topic(p_r, "ReclaimTest", DeviceTelemetry)

        w_a = writer_factory(
            p_a,
            topic_a,
            qos=_make_exclusive_writer_qos(100),
        )
        w_b = writer_factory(
            p_b,
            topic_b,
            qos=_make_exclusive_writer_qos(50),
        )
        r = reader_factory(p_r, topic_r, qos=_make_exclusive_reader_qos())

        p_a.assert_liveliness()
        p_b.assert_liveliness()

        assert wait_for_discovery(w_a, r, timeout_sec=10)
        assert wait_for_discovery(w_b, r, timeout_sec=10)

        # Primary writes, then "fails" (close participant)
        w_a.write(_make_telemetry("device-001", battery=90.0))
        p_a.assert_liveliness()
        time.sleep(0.2)
        p_a.close()

        # Backup takes over
        for _ in range(3):
            p_b.assert_liveliness()
            w_b.write(_make_telemetry("device-001", battery=55.0))
            time.sleep(0.5)

        r.take()  # Drain

        # Primary recovers — new participant + writer with same strength
        p_a2 = participant_factory(domain_id=TEST_DOMAIN)
        topic_a2 = dds.Topic(p_a2, "ReclaimTest", DeviceTelemetry)
        w_a2 = writer_factory(
            p_a2,
            topic_a2,
            qos=_make_exclusive_writer_qos(100),
        )
        p_a2.assert_liveliness()
        assert wait_for_discovery(w_a2, r, timeout_sec=10)

        # Both write — primary should reclaim
        w_a2.write(_make_telemetry("device-001", battery=95.0))
        p_a2.assert_liveliness()
        time.sleep(0.1)
        w_b.write(_make_telemetry("device-001", battery=55.0))
        p_b.assert_liveliness()
        time.sleep(0.5)

        received = r.take()
        valid = [s for s in received if s.info.valid]
        assert len(valid) >= 1, "Should receive data after recovery"
        # Last sample should be from recovered primary
        last = valid[-1]
        assert last.data.battery_percent == 95.0, (
            f"Recovered primary should reclaim ownership, "
            f"got battery={last.data.battery_percent}"
        )
