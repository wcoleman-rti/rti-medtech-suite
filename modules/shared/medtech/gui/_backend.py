"""Shared NiceGUI backend contract for DDS-driven GUI modules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from nicegui import app


class GuiBackend(ABC):
    """Abstract base class for NiceGUI backends that own DDS resources.

    Lifecycle:
        ``__init__`` registers ``start`` and ``close`` with NiceGUI's
        app hooks and adds the instance to the class-level registry.
        ``start`` must call ``_mark_ready()`` once DDS participants are
        active so the ``/ready`` health probe can report truthfully.

        If NiceGUI has already started when ``__init__`` runs (e.g. lazy
        instantiation during a sub-page render), ``start()`` is scheduled
        immediately as a background task instead of queued in on_startup.
    """

    _registry: ClassVar[list[GuiBackend]] = []

    def __init__(self) -> None:
        self._ready: bool = False
        GuiBackend._registry.append(self)
        try:
            app.on_startup(self.start)
        except RuntimeError:
            # App already running — start immediately on the live event loop.
            from nicegui import background_tasks

            background_tasks.create(self.start())
        try:
            app.on_shutdown(self.close)
        except RuntimeError:
            pass  # shutdown hook unavailable after start; DDS released on exit

    @property
    @abstractmethod
    def name(self) -> str:
        """Logging identifier for the backend."""

    @abstractmethod
    async def start(self) -> None:
        """Launch background tasks once the NiceGUI event loop is active."""

    @abstractmethod
    async def close(self) -> None:
        """Release DDS resources and stop any background work."""

    # ------------------------------------------------------------------
    # Readiness tracking (used by the /ready health probe)
    # ------------------------------------------------------------------

    def _mark_ready(self) -> None:
        """Mark this backend as ready.  Call from ``start()`` once DDS is up."""
        self._ready = True

    def is_ready(self) -> bool:
        """Return True if ``_mark_ready()`` has been called on this backend."""
        return self._ready

    # ------------------------------------------------------------------
    # Registry (used by the /ready health probe to enumerate all backends)
    # ------------------------------------------------------------------

    @classmethod
    def registry(cls) -> list[GuiBackend]:
        """Return all registered GuiBackend instances."""
        return list(cls._registry)

    @classmethod
    def _clear_registry(cls) -> None:
        """Reset the registry.  Only for test isolation."""
        cls._registry.clear()
