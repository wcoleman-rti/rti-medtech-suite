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

        wqos = dds.DataWriterQos()
        wqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        rqos = dds.DataReaderQos()
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE

        w = writer_factory(p1, topic1, qos=wqos)
        r = reader_factory(p2, topic2, qos=rqos)

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

        # Use RELIABLE QoS: this test validates partition *matching* semantics,
        # not delivery probability.  RELIABLE guarantees that once discovery
        # is confirmed, every written sample reaches the reader — eliminating
        # the load-induced flakiness that plagued the BEST_EFFORT variant.
        wqos = dds.DataWriterQos()
        wqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        rqos = dds.DataReaderQos()
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE

        w1 = writer_factory(p1, topic1, qos=wqos)
        w2 = writer_factory(p2, topic2, qos=wqos)
        r = reader_factory(p_agg, topic_agg, qos=rqos)

        assert wait_for_discovery(w1, r), "Wildcard should match OR-3"
        assert wait_for_discovery(w2, r), "Wildcard should match OR-5"

        # QueryConditions — one per expected source key.
        cond_or3 = dds.QueryCondition(
            dds.Query(r, "patient_id = 'from-OR-3'"),
            dds.DataState.new_data,
        )
        cond_or5 = dds.QueryCondition(
            dds.Query(r, "patient_id = 'from-OR-5'"),
            dds.DataState.new_data,
        )

        w1.write(_make_vitals("from-OR-3"))
        w2.write(_make_vitals("from-OR-5"))

        assert wait_for_data(
            r, timeout_sec=5, conditions=[(cond_or3, 1), (cond_or5, 1)]
        ), "Should receive from both OR-3 and OR-5"
