"""Clinical Service Host — manages BedsideMonitor and DeviceTelemetry.

Registers two service factories and delegates to the generic
``medtech.service_host.make_service_host()``.  This module is the
Python equivalent of the C++ robot_service_host.hpp pattern:
a thin factory wrapper, no subclassing.
"""

from __future__ import annotations

from medtech.service_host import ServiceFactoryMap, ServiceHost, make_service_host
from surgical_procedure.device_telemetry_sim import DeviceTelemetryService
from surgical_procedure.vitals_sim import BedsideMonitorService


def make_clinical_service_host(
    host_id: str,
    room_id: str,
    procedure_id: str,
) -> ServiceHost:
    """Create a Clinical Service Host (capacity=2).

    Manages:
      - BedsideMonitorService
      - DeviceTelemetryService
    """
    factories: ServiceFactoryMap = {
        "BedsideMonitorService": lambda svc_id: BedsideMonitorService(
            room_id=room_id,
            procedure_id=procedure_id,
        ),
        "DeviceTelemetryService": lambda svc_id: DeviceTelemetryService(
            room_id=room_id,
            procedure_id=procedure_id,
        ),
    }
    return make_service_host(host_id, "ClinicalServiceHost", 2, factories)
