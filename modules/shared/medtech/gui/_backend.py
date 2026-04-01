"""Shared NiceGUI backend contract for DDS-driven GUI modules."""

from __future__ import annotations

from abc import ABC, abstractmethod

from nicegui import app


class GuiBackend(ABC):
    """Abstract base class for NiceGUI backends that own DDS resources."""

    def __init__(self) -> None:
        app.on_startup(self.start)
        app.on_shutdown(self.close)

    @property
    @abstractmethod
    def name(self) -> str:
        """Logging identifier for the backend."""

    @abstractmethod
    async def start(self) -> None:
        """Launch background tasks once the NiceGUI event loop is active."""

    @abstractmethod
    def close(self) -> None:
        """Release DDS resources and stop any background work."""
