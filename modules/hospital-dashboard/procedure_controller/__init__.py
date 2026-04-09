"""procedure_controller — Procedure Controller GUI."""

# Expose RPC call builders for testing
from .controller import (  # noqa: F401
    ControllerBackend,
    _make_get_capabilities_call,
    _make_get_health_call,
    _make_start_call,
    _make_stop_call,
    _make_update_call,
    controller_page,
    main,
)

__all__ = [
    "ControllerBackend",
    "controller_page",
    "main",
]
