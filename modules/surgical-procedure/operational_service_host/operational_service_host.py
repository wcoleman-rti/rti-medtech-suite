"""Operational Service Host — manages CameraService and ProcedureContextService.

Registers two services and delegates to the generic
``medtech.service_host.make_service_host()``.  This module is the
Python equivalent of the C++ robot_service_host.hpp pattern:
a thin registry wrapper, no subclassing.
"""

from __future__ import annotations

from medtech.service_host import (
    ServiceHost,
    ServiceRegistration,
    ServiceRegistryMap,
    make_service_host,
)
from surgical_procedure.camera_sim import CameraService
from surgical_procedure.procedure_context_service import ProcedureContextService


def make_operational_service_host(
    host_id: str,
    room_id: str,
    procedure_id: str,
) -> ServiceHost:
    """Create an Operational Service Host (capacity=2).

    Each service creates its own DomainParticipant and applies
    partitions internally (dual-mode pattern), matching the C++
    service host architecture where the host only owns the
    Orchestration participant.

    Manages:
      - CameraService
      - ProcedureContextService
    """
    registry: ServiceRegistryMap = {
        "CameraService": ServiceRegistration(
            factory=lambda req: CameraService(
                room_id=room_id,
                procedure_id=procedure_id,
            ),
            display_name="Camera",
            properties=[],
        ),
        "ProcedureContextService": ServiceRegistration(
            factory=lambda req: ProcedureContextService(
                room_id=room_id,
                procedure_id=procedure_id,
            ),
            display_name="Procedure Context",
            properties=[],
        ),
    }
    return make_service_host(host_id, "OperationalServiceHost", 2, registry)
