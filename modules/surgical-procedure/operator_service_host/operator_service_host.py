"""Operator Service Host — manages OperatorConsoleService and DigitalTwinService.

Registers two services and delegates to the generic
``medtech.service_host.make_service_host()``.  This module is the
Python equivalent of the C++ robot_service_host.hpp pattern:
a thin registry wrapper, no subclassing.
"""

from __future__ import annotations

from medtech.gui_runtime import NiceGuiRuntime
from medtech.gui_service_host import GuiServiceHost, make_gui_service_host
from medtech.service_host import ServiceRegistration, ServiceRegistryMap, req_property
from surgical_procedure.digital_twin import DigitalTwinService
from surgical_procedure.operator_sim import OperatorConsoleService


def make_operator_service_host(
    host_id: str,
    room_id: str,
    robot_id: str = "robot-001",
    gui_runtime: NiceGuiRuntime | None = None,
) -> GuiServiceHost:
    """Create an Operator Service Host (capacity=2).

    Manages:
      - OperatorConsoleService
      - DigitalTwinService (procedure-scoped, launched when procedure starts)
    """
    if gui_runtime is None:
        gui_runtime = NiceGuiRuntime.from_env()

    registry: ServiceRegistryMap = {
        "OperatorConsoleService": ServiceRegistration(
            factory=lambda req: OperatorConsoleService(
                room_id=req_property(req, "room_id", room_id),
                procedure_id=req_property(req, "procedure_id"),
                robot_id=robot_id,
            ),
            display_name="Operator Console",
            properties=[],
        ),
        "DigitalTwinService": ServiceRegistration(
            factory=lambda req: DigitalTwinService(
                room_id=req_property(req, "room_id", room_id),
                procedure_id=req_property(req, "procedure_id"),
                host_id=host_id,
                gui_runtime=gui_runtime,
            ),
            display_name="Digital Twin",
            properties=[],
        ),
    }
    return make_gui_service_host(
        host_id,
        "OperatorServiceHost",
        2,
        registry,
        gui_runtime,
    )
