"""Operational Service Host — manages CameraService and ProcedureContextService.

Registers two service factories and delegates to the generic
``medtech.service_host.make_service_host()``.  This module is the
Python equivalent of the C++ robot_service_host.hpp pattern:
a thin factory wrapper, no subclassing.
"""

from __future__ import annotations

import app_names
import rti.connextdds as dds
from medtech.service_host import ServiceFactoryMap, ServiceHost, make_service_host
from medtech_dds_init.dds_init import initialize_connext
from surgical_procedure.camera_sim import CameraService
from surgical_procedure.procedure_context_service import ProcedureContextService

names = app_names.MedtechEntityNames.SurgicalParticipants


def make_operational_service_host(
    host_id: str,
    room_id: str,
    procedure_id: str,
) -> ServiceHost:
    """Create an Operational Service Host (capacity=2).

    Both CameraService and ProcedureContextService use the same XML
    participant config (OperationalPub), so a single shared participant
    is created lazily on first factory call and reused by the second.

    Manages:
      - CameraService
      - ProcedureContextService
    """
    shared_participant: list[dds.DomainParticipant | None] = [None]

    def _get_shared_participant() -> dds.DomainParticipant:
        if shared_participant[0] is None:
            initialize_connext()
            provider = dds.QosProvider.default
            p = provider.create_participant_from_config(names.OPERATIONAL_PUB)
            partition = f"room/{room_id}/procedure/{procedure_id}"
            qos = p.qos
            qos.partition.name = [partition]
            p.qos = qos
            shared_participant[0] = p
        return shared_participant[0]

    factories: ServiceFactoryMap = {
        "CameraService": lambda svc_id: CameraService(
            room_id=room_id,
            procedure_id=procedure_id,
            participant=_get_shared_participant(),
        ),
        "ProcedureContextService": lambda svc_id: ProcedureContextService(
            room_id=room_id,
            procedure_id=procedure_id,
            participant=_get_shared_participant(),
        ),
    }
    return make_service_host(host_id, "OperationalServiceHost", 2, factories)
