"""Integration tests: Partition isolation.

Spec: common-behaviors.md — Discovery & Partition Isolation
Tags: @integration @partition
"""

import time

import monitoring
import rti.connextdds as dds
from conftest import wait_for_data, wait_for_discovery

TEST_DOMAIN = 0
PatientVitals = monitoring.Monitoring.PatientVitals


def _make_vitals(patient_id: str, heart_rate: int = 72) -> PatientVitals:
    """Create a PatientVitals sample with the given key."""
    sample = PatientVitals()
    sample.patient_id = patient_id
    sample.heart_rate = heart_rate
    return sample


class TestSamePartition:
    """Endpoints in the same partition discover each other."""

    def test_same_partition_discovers(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        partition = "room/OR-3/procedure/proc-001"
        p1 = participant_factory(domain_id=TEST_DOMAIN)
        p2 = participant_factory(domain_id=TEST_DOMAIN)

        topic1 = dds.Topic(p1, "TestVitals", PatientVitals)
        topic2 = dds.Topic(p2, "TestVitals", PatientVitals)

        w = writer_factory(p1, topic1, partition=partition)
        r = reader_factory(p2, topic2, partition=partition)

        assert wait_for_discovery(
            w, r, timeout_sec=10
        ), "Same-partition endpoints should discover each other"

    def test_same_partition_exchanges_data(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        partition = "room/OR-3/procedure/proc-001"
        p1 = participant_factory(domain_id=TEST_DOMAIN)
        p2 = participant_factory(domain_id=TEST_DOMAIN)

        topic1 = dds.Topic(p1, "TestExchange", PatientVitals)
        topic2 = dds.Topic(p2, "TestExchange", PatientVitals)

        w = writer_factory(p1, topic1, partition=partition)
        r = reader_factory(p2, topic2, partition=partition)

        assert wait_for_discovery(w, r, timeout_sec=10)

        w.write(_make_vitals("patient-001", 72))

        received = wait_for_data(r, timeout_sec=5)
        assert len(received) >= 1, "Should receive data in same partition"
        assert received[0].data.patient_id == "patient-001"
        assert received[0].data.heart_rate == 72


class TestDifferentPartitions:
    """Endpoints in different partitions do NOT match."""

    def test_different_partitions_no_match(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        p1 = participant_factory(domain_id=TEST_DOMAIN)
        p2 = participant_factory(domain_id=TEST_DOMAIN)

        topic1 = dds.Topic(p1, "TestIsolated", PatientVitals)
        topic2 = dds.Topic(p2, "TestIsolated", PatientVitals)

        w = writer_factory(
            p1,
            topic1,
            partition="room/OR-3/procedure/proc-001",
        )
        r = reader_factory(
            p2,
            topic2,
            partition="room/OR-5/procedure/proc-002",
        )

        # Give discovery time, then confirm no match
        time.sleep(2)
        assert not w.matched_subscriptions, "Different partitions should not match"
        assert not r.matched_publications, "Different partitions should not match"

    def test_different_partitions_no_data(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        p1 = participant_factory(domain_id=TEST_DOMAIN)
        p2 = participant_factory(domain_id=TEST_DOMAIN)

        topic1 = dds.Topic(p1, "TestNoData", PatientVitals)
        topic2 = dds.Topic(p2, "TestNoData", PatientVitals)

        w = writer_factory(
            p1,
            topic1,
            partition="room/OR-3/procedure/proc-001",
        )
        r = reader_factory(
            p2,
            topic2,
            partition="room/OR-5/procedure/proc-002",
        )

        time.sleep(2)

        w.write(_make_vitals("patient-001", 99))

        time.sleep(0.5)
        received = r.read()
        valid = [s for s in received if s.info.valid]
        assert len(valid) == 0, "No data should cross partition boundary"


class TestWildcardPartition:
    """Wildcard partition receives from all matching partitions."""

    def test_wildcard_receives_from_multiple(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        p1 = participant_factory(domain_id=TEST_DOMAIN)
        p2 = participant_factory(domain_id=TEST_DOMAIN)
        p_agg = participant_factory(domain_id=TEST_DOMAIN)

        topic1 = dds.Topic(p1, "TestWildcard", PatientVitals)
        topic2 = dds.Topic(p2, "TestWildcard", PatientVitals)
        topic_agg = dds.Topic(p_agg, "TestWildcard", PatientVitals)

        w1 = writer_factory(
            p1,
            topic1,
            partition="room/OR-3/procedure/proc-001",
        )
        w2 = writer_factory(
            p2,
            topic2,
            partition="room/OR-5/procedure/proc-002",
        )
        r = reader_factory(p_agg, topic_agg, partition="room/*")

        assert wait_for_discovery(w1, r, timeout_sec=10), "Wildcard should match OR-3"
        assert wait_for_discovery(w2, r, timeout_sec=10), "Wildcard should match OR-5"

        w1.write(_make_vitals("from-OR-3", 1))
        w2.write(_make_vitals("from-OR-5", 2))

        received = wait_for_data(r, timeout_sec=5, count=2)
        ids = {s.data.patient_id for s in received}
        assert "from-OR-3" in ids, "Should receive from OR-3"
        assert "from-OR-5" in ids, "Should receive from OR-5"
