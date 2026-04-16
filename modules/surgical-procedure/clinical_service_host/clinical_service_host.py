"""Clinical Service Host — manages BedsideMonitor and DeviceTelemetry.

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
    req_property,
)
from surgical_procedure.device_telemetry_sim import DeviceTelemetryService
from surgical_procedure.vitals_sim import BedsideMonitorService


def make_clinical_service_host(
    host_id: str,
    room_id: str,
) -> ServiceHost:
    """Create a Clinical Service Host (capacity=2).

    Manages:
      - BedsideMonitorService
      - DeviceTelemetryService
    """
    registry: ServiceRegistryMap = {
        "BedsideMonitorService": ServiceRegistration(
            factory=lambda req: BedsideMonitorService(
                room_id=req_property(req, "room_id", room_id),
                procedure_id=req_property(req, "procedure_id"),
            ),
            display_name="Bedside Monitor",
            properties=[],
        ),
        "DeviceTelemetryService": ServiceRegistration(
            factory=lambda req: DeviceTelemetryService(
                room_id=req_property(req, "room_id", room_id),
                procedure_id=req_property(req, "procedure_id"),
            ),
            display_name="Device Telemetry",
            properties=[],
        ),
    }
    return make_service_host(host_id, "ClinicalServiceHost", 2, registry)
