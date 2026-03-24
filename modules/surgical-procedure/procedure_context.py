"""Procedure Context and Status publisher.

Publishes ProcedureContext and ProcedureStatus on the Procedure domain
(operational tag) with State pattern QoS and TRANSIENT_LOCAL durability.

The participant and all writers are created from XML configuration
(SurgicalParticipants::OperationalPub). Writers are looked up by entity
name using find_datawriter().

Configuration is read from environment variables or defaults.
"""

from __future__ import annotations

import os
import time

import common
import rti.connextdds as dds
import surgery
from medtech_logging import ModuleName, init_logging

ProcedureContext = surgery.Surgery.ProcedureContext
ProcedureStatus = surgery.Surgery.ProcedureStatus
ProcedurePhase = surgery.Surgery.ProcedurePhase
EntityIdentity = common.Common.EntityIdentity
Time_t = common.Common.Time_t


log = init_logging(ModuleName.SURGICAL_PROCEDURE)


class ProcedureContextPublisher:
    """Publishes ProcedureContext and ProcedureStatus using write-on-change model.

    Both topics use State pattern QoS (TRANSIENT_LOCAL, RELIABLE, KEEP_LAST 1)
    so late-joining subscribers receive the current state immediately.

    The participant is created from XML configuration
    (SurgicalParticipants::OperationalPub) and writers are looked up by name.
    """

    def __init__(self, participant: dds.DomainParticipant) -> None:
        # Look up XML-created writers by entity name
        self._context_writer = dds.DataWriter(
            participant.find_datawriter("OperationalPublisher::ProcedureContextWriter")
        )
        self._status_writer = dds.DataWriter(
            participant.find_datawriter("OperationalPublisher::ProcedureStatusWriter")
        )

        self._procedure_id = os.environ.get("PROCEDURE_ID", "proc-001")
        self._last_context: ProcedureContext | None = None
        self._last_phase: ProcedurePhase | None = None

    def publish_context(
        self,
        hospital: str = "",
        room: str = "",
        bed: str = "",
        patient_id: str = "",
        patient_name: str = "",
        procedure_type: str = "",
        surgeon: str = "",
        anesthesiologist: str = "",
    ) -> None:
        """Publish a ProcedureContext sample (write-on-change)."""
        now = time.time()
        sec = int(now)
        nsec = int((now - sec) * 1_000_000_000)

        ctx = ProcedureContext(
            procedure_id=self._procedure_id,
            hospital=hospital,
            room=room,
            bed=bed,
            patient=EntityIdentity(id=patient_id, name=patient_name),
            procedure_type=procedure_type,
            surgeon=surgeon,
            anesthesiologist=anesthesiologist,
            start_time=Time_t(sec=sec & 0xFFFFFFFF, nsec=nsec),
        )
        self._context_writer.write(ctx)
        self._last_context = ctx
        log.notice(
            f"ProcedureContext published: procedure={self._procedure_id}, "
            f"room={room}"
        )

    def publish_status(self, phase: ProcedurePhase, message: str = "") -> None:
        """Publish a ProcedureStatus sample (write-on-change)."""
        status = ProcedureStatus(
            procedure_id=self._procedure_id,
            phase=phase,
            status_message=message,
        )
        self._status_writer.write(status)
        self._last_phase = phase
        log.notice(
            f"ProcedureStatus published: procedure={self._procedure_id}, "
            f"phase={phase}"
        )

    @property
    def context_writer(self) -> dds.DataWriter:
        """Return the ProcedureContext DataWriter."""
        return self._context_writer

    @property
    def status_writer(self) -> dds.DataWriter:
        """Return the ProcedureStatus DataWriter."""
        return self._status_writer

    @property
    def procedure_id(self) -> str:
        """Return the procedure ID."""
        return self._procedure_id
