"""Integration tests: Domain isolation.

Spec: common-behaviors.md — Domain Isolation
Tags: @integration @isolation

Tests that different domain IDs and domain tags provide isolation.
Uses domain 0 as the test domain (reserved for testing) with different
domain tags, and verifies cross-domain isolation via distinct domain IDs.
"""

import time

import monitoring
import pytest
import rti.connextdds as dds
from conftest import wait_for_discovery

pytestmark = [pytest.mark.integration, pytest.mark.isolation]

TEST_DOMAIN_A = 0
TEST_DOMAIN_B = 1  # Second test domain for cross-domain isolation
PatientVitals = monitoring.Monitoring.PatientVitals


class TestDomainTagIsolation:
    """Procedure domain tag isolation: control/clinical/operational."""

    @pytest.mark.parametrize(
        "tag_a,tag_b",
        [
            ("control", "clinical"),
            ("control", "operational"),
            ("clinical", "operational"),
        ],
        ids=[
            "control-vs-clinical",
            "control-vs-operational",
            "clinical-vs-operational",
        ],
    )
    def test_different_tags_no_discovery(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
        tag_a,
        tag_b,
    ):
        """Participants with different domain tags on the same domain ID
        do not discover each other."""
        p1 = participant_factory(domain_id=TEST_DOMAIN_A, domain_tag=tag_a)
        p2 = participant_factory(domain_id=TEST_DOMAIN_A, domain_tag=tag_b)

        topic1 = dds.Topic(p1, f"TagTest_{tag_a}_{tag_b}", PatientVitals)
        topic2 = dds.Topic(p2, f"TagTest_{tag_a}_{tag_b}", PatientVitals)

        w = writer_factory(p1, topic1)
        r = reader_factory(p2, topic2)

        # Wait and verify no discovery
        time.sleep(0.5)
        assert (
            not w.matched_subscriptions
        ), f"Tag '{tag_a}' writer should not match tag '{tag_b}' reader"
        assert (
            not r.matched_publications
        ), f"Tag '{tag_b}' reader should not match tag '{tag_a}' writer"

    def test_same_tag_discovers(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        """Participants with matching domain tags discover each other."""
        tag = "control"
        p1 = participant_factory(domain_id=TEST_DOMAIN_A, domain_tag=tag)
        p2 = participant_factory(domain_id=TEST_DOMAIN_A, domain_tag=tag)

        topic1 = dds.Topic(p1, "SameTagTest", PatientVitals)
        topic2 = dds.Topic(p2, "SameTagTest", PatientVitals)

        w = writer_factory(p1, topic1)
        r = reader_factory(p2, topic2)

        assert wait_for_discovery(
            w, r, timeout_sec=10
        ), "Same domain tag should discover"


class TestCrossDomainIsolation:
    """Participants on different domain IDs do not discover each other."""

    def test_different_domains_no_discovery(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        p1 = participant_factory(domain_id=TEST_DOMAIN_A)
        p2 = participant_factory(domain_id=TEST_DOMAIN_B)

        topic1 = dds.Topic(p1, "CrossDomainTest", PatientVitals)
        topic2 = dds.Topic(p2, "CrossDomainTest", PatientVitals)

        w = writer_factory(p1, topic1)
        r = reader_factory(p2, topic2)

        # Wait for discovery timeout
        time.sleep(0.5)
        assert not w.matched_subscriptions, "Cross-domain endpoints should not match"
        assert not r.matched_publications, "Cross-domain endpoints should not match"

    def test_different_domains_no_data_exchange(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        p1 = participant_factory(domain_id=TEST_DOMAIN_A)
        p2 = participant_factory(domain_id=TEST_DOMAIN_B)

        topic1 = dds.Topic(p1, "CrossDomainData", PatientVitals)
        topic2 = dds.Topic(p2, "CrossDomainData", PatientVitals)

        w = writer_factory(p1, topic1)
        r = reader_factory(p2, topic2)

        time.sleep(0.5)

        sample = PatientVitals()
        sample.patient_id = "cross-domain-msg"
        sample.heart_rate = 42
        w.write(sample)

        time.sleep(0.5)
        received = r.read()
        valid = [s for s in received if s.info.valid]
        assert len(valid) == 0, "No data should cross domain boundaries"
