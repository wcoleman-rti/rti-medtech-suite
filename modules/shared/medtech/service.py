"""medtech.service — Abstract service interface for orchestration.

All DDS service classes implement this ABC. The Service Host framework
uses it to manage services uniformly regardless of domain or internal
complexity.

ServiceState comes from the IDL-generated Orchestration module — no
hand-written enum duplicate exists.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from orchestration import Orchestration

ServiceState = Orchestration.ServiceState  # re-export for convenience


class Service(ABC):
    """Abstract base for all medtech-suite DDS services."""

    @abstractmethod
    async def run(self) -> None:
        """Run the service event loop.

        Awaits until stop() is called or an unrecoverable error occurs.
        The Service Host gathers this coroutine — the service does not
        manage the event loop.
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """Signal the service to stop.

        Non-blocking, safe to call from any context.
        run() must return promptly after stop().
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Service identifier for orchestration and logging."""
        ...

    @property
    @abstractmethod
    def state(self) -> ServiceState:
        """Current lifecycle state (IDL-generated enum).

        Polled by the Service Host for status reporting on the
        Orchestration domain.
        """
        ...
