"""Integration tests: QoS enforcement.

Spec: common-behaviors.md — QoS Enforcement
Tags: @integration

Tests for deadline missed, liveliness lost, lifespan expiry, and KEEP_LAST.
"""

import time

import monitoring
import pytest
import rti.connextdds as dds
from conftest import wait_for_data, wait_for_discovery

pytestmark = [pytest.mark.integration]

TEST_DOMAIN = 0
PatientVitals = monitoring.Monitoring.PatientVitals


def _make_vitals(patient_id: str, heart_rate: int = 72) -> PatientVitals:
    """Create a PatientVitals sample with the given key."""
    sample = PatientVitals()
    sample.patient_id = patient_id
    sample.heart_rate = heart_rate
    return sample


def _make_qos_with_deadline(base_qos, deadline_sec):
    """Add deadline to a QoS object."""
    base_qos.deadline.period = dds.Duration(
        int(deadline_sec),
        int((deadline_sec % 1) * 1_000_000_000),
    )
    return base_qos


def _make_qos_with_lifespan(base_qos, lifespan_sec):
    """Add lifespan to a writer QoS."""
    base_qos.lifespan.duration = dds.Duration(
        int(lifespan_sec),
        int((lifespan_sec % 1) * 1_000_000_000),
    )
    return base_qos


def _make_qos_reliable_transient(base_qos):
    """Make QoS reliable + transient local."""
    base_qos.reliability.kind = dds.ReliabilityKind.RELIABLE
    base_qos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
    return base_qos


class TestDeadline:
    """Deadline violation detected when publisher stops."""

    def test_deadline_missed_on_timeout(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        """When publisher stops, subscriber's deadline-missed status triggers."""
        deadline_sec = 1.0

        p1 = participant_factory(domain_id=TEST_DOMAIN)
        p2 = participant_factory(domain_id=TEST_DOMAIN)

        topic1 = dds.Topic(p1, "DeadlineTest", PatientVitals)
        topic2 = dds.Topic(p2, "DeadlineTest", PatientVitals)

        wqos = _make_qos_with_deadline(dds.DataWriterQos(), deadline_sec)
        wqos = _make_qos_reliable_transient(wqos)

        rqos = _make_qos_with_deadline(dds.DataReaderQos(), deadline_sec)
        rqos = _make_qos_reliable_transient(rqos)

        w = writer_factory(p1, topic1, qos=wqos)
        r = reader_factory(p2, topic2, qos=rqos)

        assert wait_for_discovery(w, r, timeout_sec=10)

        w.write(_make_vitals("patient-001", 72))
        wait_for_data(r, timeout_sec=5, count=1)

        # Stop publishing and wait for deadline to expire
        time.sleep(deadline_sec * 2.5)

        status = r.requested_deadline_missed_status
        assert (
            status.total_count > 0
        ), "Deadline missed should be detected when publisher stops"


class TestLiveliness:
    """Liveliness lost detected when participant goes away."""

    def test_liveliness_lost_on_close(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        """When writer's participant closes, reader detects liveliness lost."""
        lease_sec = 1.0

        p1 = participant_factory(domain_id=TEST_DOMAIN)
        p2 = participant_factory(domain_id=TEST_DOMAIN)

        topic1 = dds.Topic(p1, "LivelinessTest", PatientVitals)
        topic2 = dds.Topic(p2, "LivelinessTest", PatientVitals)

        wqos = dds.DataWriterQos()
        wqos.liveliness.kind = dds.LivelinessKind.MANUAL_BY_PARTICIPANT
        wqos.liveliness.lease_duration = dds.Duration.from_seconds(lease_sec)
        wqos.reliability.kind = dds.ReliabilityKind.RELIABLE

        rqos = dds.DataReaderQos()
        rqos.liveliness.kind = dds.LivelinessKind.MANUAL_BY_PARTICIPANT
        rqos.liveliness.lease_duration = dds.Duration.from_seconds(lease_sec)
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE

        w = writer_factory(p1, topic1, qos=wqos)
        r = reader_factory(p2, topic2, qos=rqos)

        assert wait_for_discovery(w, r, timeout_sec=10)

        p1.assert_liveliness()
        w.write(_make_vitals("test", 1))
        wait_for_data(r, timeout_sec=5)

        # Confirm liveliness is alive before close
        assert r.liveliness_changed_status.alive_count >= 1

        # Close writer's participant (simulates crash — stops liveliness)
        p1.close()

        # Poll for liveliness/match loss. When a participant is closed,
        # the writer transitions directly from alive→unmatched (not through
        # a stable "not_alive" state), so we detect via alive_count dropping
        # to 0 or subscription_matched_status.current_count dropping to 0.
        deadline = time.time() + lease_sec * 4 + 2
        detected = False
        while time.time() < deadline:
            lc = r.liveliness_changed_status
            sm = r.subscription_matched_status
            if lc.alive_count == 0 or sm.current_count == 0:
                detected = True
                break
            time.sleep(0.2)

        assert detected, (
            "Liveliness/match loss should be detected when writer's "
            "participant closes"
        )


class TestLifespan:
    """Lifespan prevents delivery of stale data."""

    def test_stale_sample_not_delivered(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        """A sample older than its lifespan is not delivered to the reader."""
        lifespan_sec = 0.2  # 200 ms

        p1 = participant_factory(domain_id=TEST_DOMAIN)
        p2 = participant_factory(domain_id=TEST_DOMAIN)

        topic1 = dds.Topic(p1, "LifespanTest", PatientVitals)
        topic2 = dds.Topic(p2, "LifespanTest", PatientVitals)

        wqos = _make_qos_with_lifespan(dds.DataWriterQos(), lifespan_sec)
        wqos = _make_qos_reliable_transient(wqos)

        rqos = _make_qos_reliable_transient(dds.DataReaderQos())

        w = writer_factory(p1, topic1, qos=wqos)

        # Write sample BEFORE reader exists
        w.write(_make_vitals("stale", 99))

        # Wait for lifespan to expire
        time.sleep(lifespan_sec * 3)

        # Now create reader — stale sample should NOT be delivered
        r = reader_factory(p2, topic2, qos=rqos)
        wait_for_discovery(w, r, timeout_sec=10)
        time.sleep(1)

        received = r.read()
        valid = [s for s in received if s.info.valid]
        assert len(valid) == 0, "Stale sample (beyond lifespan) should not be delivered"


class TestKeepLast:
    """KEEP_LAST 1 delivers only the most recent sample."""

    def test_keep_last_1_most_recent_only(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        p1 = participant_factory(domain_id=TEST_DOMAIN)
        p2 = participant_factory(domain_id=TEST_DOMAIN)

        topic1 = dds.Topic(p1, "KeepLastTest", PatientVitals)
        topic2 = dds.Topic(p2, "KeepLastTest", PatientVitals)

        wqos = dds.DataWriterQos()
        wqos.history.kind = dds.HistoryKind.KEEP_LAST
        wqos.history.depth = 1
        wqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        wqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL

        rqos = dds.DataReaderQos()
        rqos.history.kind = dds.HistoryKind.KEEP_LAST
        rqos.history.depth = 1
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL

        w = writer_factory(p1, topic1, qos=wqos)

        # Write 5 samples with the same key before reader joins
        for i in range(5):
            w.write(_make_vitals("patient-001", i + 1))
            time.sleep(0.01)

        # Small delay, then create reader
        time.sleep(0.1)
        r = reader_factory(p2, topic2, qos=rqos)
        assert wait_for_discovery(w, r, timeout_sec=10)
        time.sleep(1)

        received = r.take()
        valid = [s for s in received if s.info.valid]
        assert (
            len(valid) == 1
        ), f"KEEP_LAST 1 should deliver exactly 1 sample, got {len(valid)}"
        assert (
            valid[0].data.heart_rate == 5
        ), "Should receive the most recent sample (heart_rate=5)"
