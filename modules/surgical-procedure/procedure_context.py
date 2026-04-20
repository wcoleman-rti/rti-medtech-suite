"""Procedure Context publisher.

Publishes ProcedureContext on the Procedure DDS domain
(operational tag) with State pattern QoS and TRANSIENT_LOCAL durability.

The participant and all writers are created from XML configuration
(SurgicalParticipants::OperationalPub). Writers are looked up by entity
name using find_datawriter().

Configuration is read from constructor parameters (atomic IDs).
Implements medtech.Service for orchestration lifecycle management.

Note: ProcedureStatus is published by the Procedure Controller, not here.
The controller is the semantic authority for procedure lifecycle transitions.
"""

from __future__ import annotations

import asyncio
import time

import app_names
import common
import rti.connextdds as dds
import surgery
from medtech.dds import initialize_connext
from medtech.log import ModuleName, init_logging
from medtech.service import Service, ServiceState

names = app_names.MedtechEntityNames.SurgicalParticipants

ProcedureContext = surgery.Surgery.ProcedureContext
EntityIdentity = common.Common.EntityIdentity
Time_t = common.Common.Time_t


log = init_logging(ModuleName.SURGICAL_PROCEDURE)


class ProcedureContextService(Service):
    """Publishes ProcedureContext using write-on-change model.

    Uses State pattern QoS (TRANSIENT_LOCAL, RELIABLE, KEEP_LAST 1)
    so late-joining subscribers receive the current state immediately.

    Owns its DomainParticipant (created from XML configuration
    SurgicalParticipants::OperationalPub) and looks up writers by name.
    Implements medtech.Service for orchestration lifecycle management.
    """

    def __init__(
        self,
        room_id: str,
        procedure_id: str,
        *,
        participant: dds.DomainParticipant | None = None,
        domain_id: int | None = None,
    ) -> None:
        self._room_id = room_id
        self._state_val = ServiceState.STOPPED
        self._stop_event: asyncio.Event | None = None

        # --- DDS entities (dual-mode participant) ---
        if participant is None:
            initialize_connext()
            provider = dds.QosProvider.default
            params = (
                dds.DomainParticipantConfigParams(domain_id=domain_id)
                if domain_id is not None
                else dds.DomainParticipantConfigParams()
            )
            self._participant = provider.create_participant_from_config(
                names.OPERATIONAL_PUB, params
            )
            partition = f"room/{room_id}/procedure/{procedure_id}"
            qos = self._participant.qos
            qos.partition.name = [partition]
            self._participant.qos = qos
        else:
            self._participant = participant

        # Look up XML-created writers by entity name
        ctx_any = self._participant.find_datawriter(names.PROCEDURE_CONTEXT_WRITER)

        if ctx_any is None:
            raise RuntimeError(f"Writer not found: {names.PROCEDURE_CONTEXT_WRITER}")

        self._context_writer = dds.DataWriter(ctx_any)

        self._procedure_id = procedure_id
        self._last_context: ProcedureContext | None = None

    def start(self) -> None:
        """Enable the participant to initiate DDS discovery.

        Call after construction, once all setup is complete.
        """
        self._participant.enable()
        log.notice(f"ProcedureContextPublisher enabled: procedure={self._procedure_id}")

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

    @property
    def procedure_id(self) -> str:
        """Return the procedure ID."""
        return self._procedure_id

    # --- medtech.Service interface ---

    async def run(self) -> None:
        self._state_val = ServiceState.STARTING
        self._stop_event = asyncio.Event()
        self.start()
        self.publish_context(room=self._room_id)
        self._state_val = ServiceState.RUNNING

        await self._stop_event.wait()

        self._state_val = ServiceState.STOPPING
        self._state_val = ServiceState.STOPPED

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    @property
    def name(self) -> str:
        return "ProcedureContextService"

    @property
    def state(self) -> ServiceState:
        return self._state_val


if __name__ == "__main__":
    import os
    import signal

    room_id = os.environ.get("ROOM_ID", "OR-1")
    procedure_id = os.environ.get("PROCEDURE_ID", "proc-001")

    pub = ProcedureContextService(room_id=room_id, procedure_id=procedure_id)

    loop = asyncio.new_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, pub.stop)
    loop.run_until_complete(pub.run())
