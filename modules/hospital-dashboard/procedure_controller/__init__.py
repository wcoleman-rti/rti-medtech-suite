"""procedure_controller — Procedure Controller GUI."""

# Expose RPC call builders for testing
from .procedure_controller import (  # noqa: F401
    ProcedureController,
    _make_get_capabilities_call,
    _make_get_health_call,
    _make_start_call,
    _make_stop_call,
)

__all__ = ["ProcedureController"]
