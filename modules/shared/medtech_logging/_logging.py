"""Logging initialization using the RTI Connext Logging API.

Verbosity is configured entirely via QoS XML (participant_factory_qos
LOGGING policy). This module never sets verbosity programmatically.

All log messages are routed through ``ModuleLogger``, a thin wrapper
around ``dds.Logger`` that auto-prefixes messages with the module
name.  If the logging backend is swapped in the future, only this
module needs to change — call sites remain untouched.
"""

from enum import Enum

import rti.connextdds as dds


class ModuleName(str, Enum):
    """Recognised module names — values match module directory names."""

    SURGICAL_PROCEDURE = "surgical-procedure"
    HOSPITAL_DASHBOARD = "hospital-dashboard"
    CLINICAL_ALERTS = "clinical-alerts"


class ModuleLogger:
    """Thin wrapper around ``dds.Logger`` that auto-prefixes messages.

    Every severity method delegates to the corresponding
    ``dds.Logger.instance`` method with a ``[module-name]`` prefix.
    Swapping the backend means changing only this class.
    """

    def __init__(self, module_name: ModuleName) -> None:
        self._prefix = f"[{module_name.value}] "
        self._logger = dds.Logger.instance

    def emergency(self, msg: str) -> None:
        self._logger.emergency(self._prefix + msg)

    def alert(self, msg: str) -> None:
        self._logger.alert(self._prefix + msg)

    def critical(self, msg: str) -> None:
        self._logger.critical(self._prefix + msg)

    def error(self, msg: str) -> None:
        self._logger.error(self._prefix + msg)

    def warning(self, msg: str) -> None:
        self._logger.warning(self._prefix + msg)

    def notice(self, msg: str) -> None:
        self._logger.notice(self._prefix + msg)

    def informational(self, msg: str) -> None:
        self._logger.informational(self._prefix + msg)

    def debug(self, msg: str) -> None:
        self._logger.debug(self._prefix + msg)


def init_logging(module_name: ModuleName) -> ModuleLogger:
    """Create a ``ModuleLogger`` for the given module.

    Messages are automatically prefixed with ``[<module-name>]``.
    Verbosity is controlled entirely by QoS XML — this function
    never sets it programmatically.
    """
    if not isinstance(module_name, ModuleName):
        raise TypeError(
            f"Expected a ModuleName enum member, got {type(module_name).__name__!r}"
        )
    return ModuleLogger(module_name)
