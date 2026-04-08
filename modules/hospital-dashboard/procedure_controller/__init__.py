"""procedure_controller — Procedure Controller GUI."""

# Expose RPC call builders for testing
from .nicegui_controller import ControllerBackend, controller_page, main

try:  # pragma: no cover - legacy Qt controller is optional during NiceGUI migration
    from .procedure_controller import (  # noqa: F401
        ProcedureController,
        _make_get_capabilities_call,
        _make_get_health_call,
        _make_start_call,
        _make_stop_call,
        _make_update_call,
    )
except ImportError:  # PySide6 is not installed in the NiceGUI migration environment
    from .nicegui_controller import (  # noqa: F401
        _make_get_capabilities_call,
        _make_get_health_call,
        _make_start_call,
        _make_stop_call,
        _make_update_call,
    )

    ProcedureController = ControllerBackend

__all__ = [
    "ControllerBackend",
    "ProcedureController",
    "controller_page",
    "main",
]
