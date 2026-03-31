"""Tests for Step 2.1 — Procedure Context & Status Publisher.

Spec coverage: surgical-procedure.md — Procedure Context
Tags: @integration @durability
"""

from __future__ import annotations

import time

import common
import pytest
import rti.connextdds as dds
import surgery
from conftest import wait_for_data, wait_for_discovery

pytestmark = [pytest.mark.integration]

# Type aliases
ProcedureContext = surgery.Surgery.ProcedureContext
ProcedureStatus = surgery.Surgery.ProcedureStatus
ProcedurePhase = surgery.Surgery.ProcedurePhase
EntityIdentity = common.Common.EntityIdentity
Time_t = common.Common.Time_t


def _make_context(
    procedure_id: str = "proc-001",
    hospital: str = "General Hospital",
    room: str = "OR-3",
    bed: str = "bed-A",
    patient_id: str = "patient-42",
    patient_name: str = "John Doe",
    procedure_type: str = "Laparoscopic Cholecystectomy",
    surgeon: str = "Dr. Smith",
    anesthesiologist: str = "Dr. Jones",
) -> ProcedureContext:
    """Create a ProcedureContext sample."""
    now = time.time()
    return ProcedureContext(
        procedure_id=procedure_id,
        hospital=hospital,
        room=room,
        bed=bed,
        patient=EntityIdentity(id=patient_id, name=patient_name),
        procedure_type=procedure_type,
        surgeon=surgeon,
        anesthesiologist=anesthesiologist,
        start_time=Time_t(sec=int(now) & 0xFFFFFFFF, nsec=0),
    )


def _make_status(
    procedure_id: str = "proc-001",
    phase: ProcedurePhase = ProcedurePhase.IN_PROGRESS,
    message: str = "Procedure in progress",
) -> ProcedureStatus:
    """Create a ProcedureStatus sample."""
    return ProcedureStatus(
        procedure_id=procedure_id,
        phase=phase,
        status_message=message,
    )


class TestProcedureContext:
    """Tests for ProcedureContext publication (spec: surgical-procedure.md)."""

    def test_context_published_at_startup(
        self, participant_factory, writer_factory, reader_factory
    ):
        """Procedure context is published at startup with all required fields.

        Spec: Given a surgical procedure instance starting in room OR-3
              When the procedure application initializes
              Then a ProcedureContext sample is published containing hospital,
              room, bed, patient ID, procedure type, surgeon, and start time.
        """
        partition = "room/OR-3/procedure/proc-001"
        writer_p = participant_factory(
            domain_id=0, domain_tag="operational", partition=partition
        )
        reader_p = participant_factory(
            domain_id=0, domain_tag="operational", partition=partition
        )

        provider = dds.QosProvider.default
        topic_w = dds.Topic(writer_p, "ProcedureContext", ProcedureContext)
        topic_r = dds.Topic(reader_p, "ProcedureContext", ProcedureContext)

        writer_qos = provider.datawriter_qos_from_profile(
            "TopicProfiles::ProcedureContext"
        )
        reader_qos = provider.datareader_qos_from_profile(
            "TopicProfiles::ProcedureContext"
        )

        writer = writer_factory(writer_p, topic_w, qos=writer_qos)
        reader = reader_factory(reader_p, topic_r, qos=reader_qos)

        assert wait_for_discovery(
            writer,
            reader,
        ), "Writer did not discover reader"

        ctx = _make_context()
        writer.write(ctx)

        received = wait_for_data(reader, timeout_sec=5)
        assert received, "No ProcedureContext sample received"
        data = reader.take_data()[0]
        assert data.procedure_id == "proc-001"
        assert data.hospital == "General Hospital"
        assert data.room == "OR-3"
        assert data.bed == "bed-A"
        assert data.patient.id == "patient-42"
        assert data.patient.name == "John Doe"
        assert data.procedure_type == "Laparoscopic Cholecystectomy"
        assert data.surgeon == "Dr. Smith"
        assert data.anesthesiologist == "Dr. Jones"
        assert data.start_time.sec > 0

    def test_late_joiner_receives_context(
        self, participant_factory, writer_factory, reader_factory
    ):
        """Late-joining subscriber receives procedure context immediately.

        Spec: Given a ProcedureContext has been published with TRANSIENT_LOCAL
              When a new subscriber joins in the same partition
              Then the subscriber receives the ProcedureContext immediately.
        """
        partition = "room/OR-5/procedure/proc-002"
        writer_p = participant_factory(
            domain_id=0, domain_tag="operational", partition=partition
        )

        provider = dds.QosProvider.default
        topic_w = dds.Topic(writer_p, "ProcedureContext", ProcedureContext)
        writer_qos = provider.datawriter_qos_from_profile(
            "TopicProfiles::ProcedureContext"
        )
        writer = writer_factory(writer_p, topic_w, qos=writer_qos)

        # Publish context BEFORE reader exists
        ctx = _make_context(
            procedure_id="proc-002",
            hospital="City Hospital",
            room="OR-5",
            bed="bed-B",
            patient_id="patient-99",
            patient_name="Jane Doe",
            procedure_type="Appendectomy",
            surgeon="Dr. Adams",
            anesthesiologist="Dr. Baker",
        )
        writer.write(ctx)

        # Now create the late-joining reader
        reader_p = participant_factory(
            domain_id=0, domain_tag="operational", partition=partition
        )
        topic_r = dds.Topic(reader_p, "ProcedureContext", ProcedureContext)
        reader_qos = provider.datareader_qos_from_profile(
            "TopicProfiles::ProcedureContext"
        )
        reader = reader_factory(reader_p, topic_r, qos=reader_qos)

        received = wait_for_data(reader, timeout_sec=5)
        assert received, "Late joiner did not receive ProcedureContext"
        data = reader.take_data()[0]
        assert data.procedure_id == "proc-002"
        assert data.room == "OR-5"

    def test_context_update_reflects_changes(
        self, participant_factory, writer_factory, reader_factory
    ):
        """Procedure context update reflects changes.

        Spec: Given a published ProcedureContext for an active procedure
              When the metadata is updated (e.g., additional surgeon joins)
              Then a new ProcedureContext sample is published with updated info
              And subscribers see the updated context as current state (KEEP_LAST 1).
        """
        partition = "room/OR-7/procedure/proc-003"
        writer_p = participant_factory(
            domain_id=0, domain_tag="operational", partition=partition
        )
        reader_p = participant_factory(
            domain_id=0, domain_tag="operational", partition=partition
        )

        provider = dds.QosProvider.default
        topic_w = dds.Topic(writer_p, "ProcedureContext", ProcedureContext)
        topic_r = dds.Topic(reader_p, "ProcedureContext", ProcedureContext)

        writer_qos = provider.datawriter_qos_from_profile(
            "TopicProfiles::ProcedureContext"
        )
        reader_qos = provider.datareader_qos_from_profile(
            "TopicProfiles::ProcedureContext"
        )

        writer = writer_factory(writer_p, topic_w, qos=writer_qos)
        reader = reader_factory(reader_p, topic_r, qos=reader_qos)

        assert wait_for_discovery(writer, reader)

        # Publish initial context
        ctx1 = _make_context(procedure_id="proc-003", surgeon="Dr. Chen")
        writer.write(ctx1)
        writer.wait_for_acknowledgments(dds.Duration(5))

        # Consume initial sample
        reader.take()

        # Update context (new surgeon)
        ctx2 = _make_context(procedure_id="proc-003", surgeon="Dr. Chen, Dr. Williams")
        writer.write(ctx2)

        received = wait_for_data(reader, timeout_sec=5)
        assert received, "Did not receive updated ProcedureContext"
        data = reader.take_data()[0]
        assert data.surgeon == "Dr. Chen, Dr. Williams"


class TestProcedureStatus:
    """Tests for ProcedureStatus publication (spec: surgical-procedure.md)."""

    def test_status_published_with_running_status(
        self, participant_factory, writer_factory, reader_factory
    ):
        """ProcedureStatus is published with running status and is durable.

        Spec: Given a surgical procedure instance publishing ProcedureStatus
              When the procedure is active
              Then ProcedureStatus samples are published with the current running
              status and a late-joining subscriber receives the most recent status
              via TRANSIENT_LOCAL durability.
        """
        partition = "room/OR-1/procedure/proc-010"
        writer_p = participant_factory(
            domain_id=0, domain_tag="operational", partition=partition
        )

        provider = dds.QosProvider.default
        topic_w = dds.Topic(writer_p, "ProcedureStatus", ProcedureStatus)
        writer_qos = provider.datawriter_qos_from_profile(
            "TopicProfiles::ProcedureStatus"
        )
        writer = writer_factory(writer_p, topic_w, qos=writer_qos)

        # Publish in-progress status
        status = _make_status(procedure_id="proc-010")
        writer.write(status)

        # Late-joining reader
        reader_p = participant_factory(
            domain_id=0, domain_tag="operational", partition=partition
        )
        topic_r = dds.Topic(reader_p, "ProcedureStatus", ProcedureStatus)
        reader_qos = provider.datareader_qos_from_profile(
            "TopicProfiles::ProcedureStatus"
        )
        reader = reader_factory(reader_p, topic_r, qos=reader_qos)

        received = wait_for_data(reader, timeout_sec=5)
        assert received, "Late joiner did not receive ProcedureStatus"
        data = reader.take_data()[0]
        assert data.procedure_id == "proc-010"
        assert data.status_message == "Procedure in progress"

    def test_status_lifecycle_transition(
        self, participant_factory, writer_factory, reader_factory
    ):
        """Procedure status transitions through lifecycle.

        Spec: Given a surgical procedure publishing ProcedureStatus
              When the procedure progresses from in-progress to completing
              Then a new ProcedureStatus sample is published with "completing"
              And subscribers see the updated status (KEEP_LAST 1).
        """
        partition = "room/OR-2/procedure/proc-011"
        writer_p = participant_factory(
            domain_id=0, domain_tag="operational", partition=partition
        )
        reader_p = participant_factory(
            domain_id=0, domain_tag="operational", partition=partition
        )

        provider = dds.QosProvider.default
        topic_w = dds.Topic(writer_p, "ProcedureStatus", ProcedureStatus)
        topic_r = dds.Topic(reader_p, "ProcedureStatus", ProcedureStatus)

        writer_qos = provider.datawriter_qos_from_profile(
            "TopicProfiles::ProcedureStatus"
        )
        reader_qos = provider.datareader_qos_from_profile(
            "TopicProfiles::ProcedureStatus"
        )

        writer = writer_factory(writer_p, topic_w, qos=writer_qos)
        reader = reader_factory(reader_p, topic_r, qos=reader_qos)

        assert wait_for_discovery(writer, reader)

        # Publish IN_PROGRESS
        writer.write(_make_status(procedure_id="proc-011", message="In progress"))
        writer.wait_for_acknowledgments(dds.Duration(5))
        reader.take()  # consume initial

        # Transition to COMPLETING
        writer.write(
            _make_status(
                procedure_id="proc-011",
                phase=ProcedurePhase.COMPLETING,
                message="Completing",
            )
        )

        received = wait_for_data(reader, timeout_sec=5)
        assert received, "Did not receive updated ProcedureStatus"
        data = reader.take_data()[0]
        assert data.procedure_id == "proc-011"
        assert data.status_message == "Completing"
