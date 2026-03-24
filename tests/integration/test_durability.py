"""Integration tests: Durability.

Spec: common-behaviors.md — Durability
Tags: @integration @durability

Tests TRANSIENT_LOCAL late joiner and VOLATILE no-history behaviors
using generated types (ProcedureContext, RobotCommand).
"""

import time

import pytest
import rti.connextdds as dds
import surgery
from conftest import wait_for_data, wait_for_discovery

pytestmark = [pytest.mark.integration, pytest.mark.durability]

TEST_DOMAIN = 0
ProcedureContext = surgery.Surgery.ProcedureContext
RobotCommand = surgery.Surgery.RobotCommand


class TestTransientLocalLateJoiner:
    """TRANSIENT_LOCAL delivers historical data to late joiners."""

    def test_late_joiner_receives_most_recent(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        """Given 5 samples with TRANSIENT_LOCAL + KEEP_LAST 1,
        a late-joining subscriber receives exactly 1 (most recent)."""
        p1 = participant_factory(domain_id=TEST_DOMAIN)
        p2 = participant_factory(domain_id=TEST_DOMAIN)

        topic1 = dds.Topic(p1, "DurabilityContext", ProcedureContext)
        topic2 = dds.Topic(p2, "DurabilityContext", ProcedureContext)

        wqos = dds.DataWriterQos()
        wqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        wqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
        wqos.history.kind = dds.HistoryKind.KEEP_LAST
        wqos.history.depth = 1

        w = writer_factory(p1, topic1, qos=wqos)

        # Publish 5 samples (same key) before the reader exists
        for i in range(5):
            sample = ProcedureContext()
            sample.procedure_id = "proc-001"  # same key → one DDS instance
            sample.room = f"OR-{i + 1}"
            w.write(sample)
            time.sleep(0.01)

        # Wait for writer cache to settle
        time.sleep(0.2)

        # Late joiner subscribes
        rqos = dds.DataReaderQos()
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        rqos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
        rqos.history.kind = dds.HistoryKind.KEEP_LAST
        rqos.history.depth = 1

        r = reader_factory(p2, topic2, qos=rqos)
        assert wait_for_discovery(w, r, timeout_sec=10)
        time.sleep(1)

        received = r.take()
        valid = [s for s in received if s.info.valid]
        assert (
            len(valid) == 1
        ), f"Late joiner should receive exactly 1 sample, got {len(valid)}"
        assert valid[0].data.procedure_id == "proc-001"
        assert valid[0].data.room == "OR-5", "Should receive the most recent sample"


class TestVolatileNoHistory:
    """VOLATILE does not deliver historical data."""

    def test_late_joiner_gets_no_history(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        """Given samples published with VOLATILE durability,
        a late-joining subscriber receives no historical samples."""
        p1 = participant_factory(domain_id=TEST_DOMAIN)
        p2 = participant_factory(domain_id=TEST_DOMAIN)

        topic1 = dds.Topic(p1, "VolatileCommand", RobotCommand)
        topic2 = dds.Topic(p2, "VolatileCommand", RobotCommand)

        wqos = dds.DataWriterQos()
        wqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        wqos.durability.kind = dds.DurabilityKind.VOLATILE

        w = writer_factory(p1, topic1, qos=wqos)

        # Publish samples before the reader exists
        for i in range(3):
            sample = RobotCommand()
            sample.command_id = i + 1
            sample.robot_id = "robot-1"
            w.write(sample)
            time.sleep(0.01)

        time.sleep(0.5)

        # Late joiner subscribes
        rqos = dds.DataReaderQos()
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        rqos.durability.kind = dds.DurabilityKind.VOLATILE

        r = reader_factory(p2, topic2, qos=rqos)
        assert wait_for_discovery(w, r, timeout_sec=10)
        time.sleep(1)

        received = r.read()
        valid = [s for s in received if s.info.valid]
        assert (
            len(valid) == 0
        ), "VOLATILE late joiner should receive no historical samples"

    def test_receives_after_join(
        self,
        participant_factory,
        writer_factory,
        reader_factory,
    ):
        """After joining, subscriber receives newly published samples."""
        p1 = participant_factory(domain_id=TEST_DOMAIN)
        p2 = participant_factory(domain_id=TEST_DOMAIN)

        topic1 = dds.Topic(p1, "VolatileNew", RobotCommand)
        topic2 = dds.Topic(p2, "VolatileNew", RobotCommand)

        wqos = dds.DataWriterQos()
        wqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        wqos.durability.kind = dds.DurabilityKind.VOLATILE

        rqos = dds.DataReaderQos()
        rqos.reliability.kind = dds.ReliabilityKind.RELIABLE
        rqos.durability.kind = dds.DurabilityKind.VOLATILE

        w = writer_factory(p1, topic1, qos=wqos)
        r = reader_factory(p2, topic2, qos=rqos)
        assert wait_for_discovery(w, r, timeout_sec=10)

        sample = RobotCommand()
        sample.command_id = 99
        sample.robot_id = "robot-1"
        w.write(sample)

        received = wait_for_data(r, timeout_sec=5)
        assert len(received) >= 1, "Should receive samples published after join"
        assert received[0].data.command_id == 99
