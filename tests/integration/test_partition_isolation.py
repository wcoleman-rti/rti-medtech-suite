"""Integration tests: Partition isolation.

Spec: common-behaviors.md — Discovery & Partition Isolation
Tags: @integration @partition
"""

import time

import monitoring
import pytest
import rti.connextdds as dds
from conftest import wait_for_data, wait_for_discovery

pytestmark = [pytest.mark.integration, pytest.mark.partition]

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
        p1 = participant_factory(domain_id=TEST_DOMAIN, partition=partition)
        p2 = participant_factory(domain_id=TEST_DOMAIN, partition=partition)

        topic1 = dds.Topic(p1, "TestVitals", PatientVitals)
        topic2 = dds.Topic(p2, "TestVitals", PatientVitals)

        w = writer_factory(p1, topic1)
        r = reader_factory(p2, topic2)

        assert wait_for_discovery(
            w, r
        ), "Same-partition endpoints should discover each other"

    def test_same_partition_exchanges_data(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        partition = "room/OR-3/procedure/proc-001"
        p1 = participant_factory(domain_id=TEST_DOMAIN, partition=partition)
        p2 = participant_factory(domain_id=TEST_DOMAIN, partition=partition)

        topic1 = dds.Topic(p1, "TestExchange", PatientVitals)
        topic2 = dds.Topic(p2, "TestExchange", PatientVitals)

        w = writer_factory(p1, topic1)
        r = reader_factory(p2, topic2)

        assert wait_for_discovery(w, r)

        w.write(_make_vitals("patient-001", 72))

        assert wait_for_data(r, timeout_sec=5), "Should receive data in same partition"
        data = r.take_data()[0]
        assert data.patient_id == "patient-001"
        assert data.heart_rate == 72


class TestDifferentPartitions:
    """Endpoints in different partitions do NOT match."""

    def test_different_partitions_no_match(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        p1 = participant_factory(
            domain_id=TEST_DOMAIN,
            partition="room/OR-3/procedure/proc-001",
        )
        p2 = participant_factory(
            domain_id=TEST_DOMAIN,
            partition="room/OR-5/procedure/proc-002",
        )

        topic1 = dds.Topic(p1, "TestIsolated", PatientVitals)
        topic2 = dds.Topic(p2, "TestIsolated", PatientVitals)

        w = writer_factory(p1, topic1)
        r = reader_factory(p2, topic2)

        # Give discovery time, then confirm no match
        time.sleep(0.5)
        assert not w.matched_subscriptions, "Different partitions should not match"
        assert not r.matched_publications, "Different partitions should not match"

    def test_different_partitions_no_data(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        p1 = participant_factory(
            domain_id=TEST_DOMAIN,
            partition="room/OR-3/procedure/proc-001",
        )
        p2 = participant_factory(
            domain_id=TEST_DOMAIN,
            partition="room/OR-5/procedure/proc-002",
        )

        topic1 = dds.Topic(p1, "TestNoData", PatientVitals)
        topic2 = dds.Topic(p2, "TestNoData", PatientVitals)

        w = writer_factory(p1, topic1)
        r = reader_factory(p2, topic2)

        time.sleep(0.5)

        w.write(_make_vitals("patient-001", 99))

        time.sleep(0.5)
        valid = r.read_data()
        assert len(valid) == 0, "No data should cross partition boundary"


class TestWildcardPartition:
    """Wildcard partition receives from all matching partitions."""

    def test_wildcard_receives_from_multiple(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        p1 = participant_factory(
            domain_id=TEST_DOMAIN,
            partition="room/OR-3/procedure/proc-001",
        )
        p2 = participant_factory(
            domain_id=TEST_DOMAIN,
            partition="room/OR-5/procedure/proc-002",
        )
        p_agg = participant_factory(
            domain_id=TEST_DOMAIN,
            partition="room/*",
        )

        topic1 = dds.Topic(p1, "TestWildcard", PatientVitals)
        topic2 = dds.Topic(p2, "TestWildcard", PatientVitals)
        topic_agg = dds.Topic(p_agg, "TestWildcard", PatientVitals)

        w1 = writer_factory(p1, topic1)
        w2 = writer_factory(p2, topic2)
        r = reader_factory(p_agg, topic_agg)

        assert wait_for_discovery(w1, r), "Wildcard should match OR-3"
        assert wait_for_discovery(w2, r), "Wildcard should match OR-5"

        # Prime each connection: write one sample per writer and wait for it
        # to arrive at the reader before the assertion burst.  Under parallel
        # CI load best-effort packets can be dropped in the discovery window;
        # confirming arrival ensures wildcard routing is fully settled.
        w1.write(_make_vitals("prime-OR-3"))
        w2.write(_make_vitals("prime-OR-5"))
        cond_prime = dds.ReadCondition(
            r,
            dds.DataState(
                dds.SampleState.NOT_READ, dds.ViewState.ANY, dds.InstanceState.ALIVE
            ),
        )
        assert wait_for_data(
            r, timeout_sec=5, conditions=[(cond_prime, 2)]
        ), "Priming samples from both writers should arrive"
        r.take()  # drain priming samples

        # QueryConditions — one per expected source key.  Both must be
        # satisfied for the test to pass.  Best-effort delivery may drop
        # individual samples, so we write a burst per writer.
        cond_or3 = dds.QueryCondition(
            dds.Query(r, "patient_id = 'from-OR-3'"),
            dds.DataState.new_data,
        )
        cond_or5 = dds.QueryCondition(
            dds.Query(r, "patient_id = 'from-OR-5'"),
            dds.DataState.new_data,
        )

        burst = 5
        for i in range(burst):
            w1.write(_make_vitals("from-OR-3", i))
            w2.write(_make_vitals("from-OR-5", i))

        assert wait_for_data(
            r, timeout_sec=5, conditions=[(cond_or3, 1), (cond_or5, 1)]
        ), "Should receive from both OR-3 and OR-5"
