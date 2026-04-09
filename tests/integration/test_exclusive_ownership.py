"""Integration tests: Exclusive Ownership / Failover.

Spec: common-behaviors.md — Exclusive Ownership / Failover
Tags: @integration @failover

Tests exclusive ownership strength preference, failover to backup on
primary failure, and primary reclaim on recovery using DeviceTelemetry.
"""

import time

import devices
import pytest
import rti.connextdds as dds
from conftest import wait_for_data, wait_for_discovery

pytestmark = [pytest.mark.integration, pytest.mark.failover]

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
    """Create DataWriterQos with exclusive ownership and given strength.

    Uses AUTOMATIC liveliness with a 2 s lease to match the application
    QoS profile (Snippets::LivelinessStandard).
    """
    qos = dds.DataWriterQos()
    qos.ownership.kind = dds.OwnershipKind.EXCLUSIVE
    qos.ownership_strength.value = strength
    qos.reliability.kind = dds.ReliabilityKind.RELIABLE
    qos.liveliness.kind = dds.LivelinessKind.AUTOMATIC
    qos.liveliness.lease_duration = dds.Duration.from_seconds(2.0)
    return qos


def _make_exclusive_reader_qos() -> dds.DataReaderQos:
    """Create DataReaderQos with exclusive ownership.

    Uses AUTOMATIC liveliness with a 2 s lease to match the application
    QoS profile (Snippets::LivelinessStandard).
    """
    qos = dds.DataReaderQos()
    qos.ownership.kind = dds.OwnershipKind.EXCLUSIVE
    qos.reliability.kind = dds.ReliabilityKind.RELIABLE
    qos.liveliness.kind = dds.LivelinessKind.AUTOMATIC
    qos.liveliness.lease_duration = dds.Duration.from_seconds(2.0)
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

        assert wait_for_discovery(w_a, r)
        assert wait_for_discovery(w_b, r)

        # Prime w_a's exclusive ownership: write one sample and wait for the
        # reader to actually receive it.  Only once the reader has confirmed
        # a sample from w_a is ownership definitively established, eliminating
        # the race window between discovery and arbitration.
        w_a.write(_make_telemetry("device-001", battery=90.0))
        assert wait_for_data(
            r, timeout_sec=2.0
        ), "Reader did not receive priming sample from w_a"
        r.take()  # drain the priming sample

        # Now write from both writers for the ownership-stability assertion
        w_a.write(_make_telemetry("device-001", battery=90.0))
        w_b.write(_make_telemetry("device-001", battery=50.0))
        time.sleep(0.3)

        received = r.take_data()
        assert len(received) >= 1, "Should receive at least one sample"
        # Only writer A's data should be delivered (battery=90)
        batteries = [s.battery_percent for s in received]
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

        assert wait_for_discovery(w_a, r)
        assert wait_for_discovery(w_b, r)

        # Prime w_a's exclusive ownership: write one sample and confirm it
        # arrives before testing ownership stability.  Matches the pattern in
        # TestHigherStrengthPreferred — ownership arbitration only becomes
        # deterministic once the reader has received at least one sample from
        # the stronger writer (see commit 1ae79ed).
        w_a.write(_make_telemetry("device-001", battery=90.0))
        assert wait_for_data(
            r, timeout_sec=2.0
        ), "Priming sample from primary should arrive"
        r.take()  # drain priming sample

        # Confirm primary is still delivering and secondary is filtered
        w_a.write(_make_telemetry("device-001", battery=90.0))
        time.sleep(0.05)
        w_b.write(_make_telemetry("device-001", battery=50.0))

        received = wait_for_data(r, timeout_sec=5)
        assert received, "Should initially receive from primary"
        samples = r.take_data()
        assert any(
            s.battery_percent == 90.0 for s in samples
        ), "Should initially receive from primary (battery=90)"

        # Drain the reader
        r.take()

        # Kill primary (simulates crash) — AUTOMATIC liveliness detects
        # the closed participant and the reader switches ownership to B.
        p_a.close()

        # Wait for liveliness expiry (2 s lease + margin)
        time.sleep(3.0)

        # Backup keeps publishing
        for _ in range(3):
            w_b.write(_make_telemetry("device-001", battery=55.0))
            time.sleep(0.2)

        received = r.take_data()
        assert len(received) >= 1, "Backup should deliver data after primary failure"
        assert any(
            s.battery_percent == 55.0 for s in received
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

        assert wait_for_discovery(w_a, r)
        assert wait_for_discovery(w_b, r)

        # Primary writes, then "fails" (close participant)
        w_a.write(_make_telemetry("device-001", battery=90.0))
        time.sleep(0.2)
        p_a.close()

        # Wait for liveliness expiry then let backup take over
        time.sleep(3.0)
        for _ in range(3):
            w_b.write(_make_telemetry("device-001", battery=55.0))
            time.sleep(0.2)

        r.take()  # Drain

        # Primary recovers — new participant + writer with same strength
        p_a2 = participant_factory(domain_id=TEST_DOMAIN)
        topic_a2 = dds.Topic(p_a2, "ReclaimTest", DeviceTelemetry)
        w_a2 = writer_factory(
            p_a2,
            topic_a2,
            qos=_make_exclusive_writer_qos(100),
        )
        assert wait_for_discovery(w_a2, r)

        # Both write — primary should reclaim
        w_a2.write(_make_telemetry("device-001", battery=95.0))
        time.sleep(0.1)
        w_b.write(_make_telemetry("device-001", battery=55.0))
        time.sleep(0.5)

        received = r.take_data()
        assert len(received) >= 1, "Should receive data after recovery"
        # Last sample should be from recovered primary
        last = received[-1]
        assert last.battery_percent == 95.0, (
            f"Recovered primary should reclaim ownership, "
            f"got battery={last.battery_percent}"
        )
