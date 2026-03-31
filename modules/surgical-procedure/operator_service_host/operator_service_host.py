"""Operator Service Host — manages OperatorConsoleService.

Registers one service factory and delegates to the generic
``medtech.service_host.make_service_host()``.  This module is the
Python equivalent of the C++ robot_service_host.hpp pattern:
a thin factory wrapper, no subclassing.
"""

from __future__ import annotations

from medtech.service_host import ServiceFactoryMap, ServiceHost, make_service_host
from surgical_procedure.operator_sim import OperatorConsoleService


def make_operator_service_host(
    host_id: str,
    room_id: str,
    procedure_id: str,
) -> ServiceHost:
    """Create an Operator Service Host (capacity=1).

    Manages:
      - OperatorConsoleService
    """
    factories: ServiceFactoryMap = {
        "OperatorConsoleService": lambda svc_id: OperatorConsoleService(
            room_id=room_id,
            procedure_id=procedure_id,
        ),
    }
    return make_service_host(host_id, "OperatorServiceHost", 1, factories)
