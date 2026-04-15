"""Room-level GUI navigation pill — discovers sibling GUIs via ServiceCatalog.

Creates a lightweight read-only participant on the Orchestration databus
(Domain 11, partition ``procedure``) and subscribes to ``ServiceCatalog``.
Filters by ``room_id`` matching the current room to build a live dict of
``{display_name: gui_url}`` for sibling GUIs.

No upward link to the hospital dashboard — room-level services have
visibility at and below their level only.
"""

from __future__ import annotations

import asyncio
from typing import Any

import app_names
import rti.asyncio  # noqa: F401 — enables async DDS methods
import rti.connextdds as dds
from medtech.dds import initialize_connext
from medtech.gui._icons import ICONS
from medtech.log import ModuleName, init_logging
from nicegui import background_tasks, ui

_nav_names = app_names.MedtechEntityNames.RoomNav

log = init_logging(ModuleName.HOSPITAL_DASHBOARD)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


class RoomNav:
    """Discovers sibling GUI services in the same room via ServiceCatalog."""

    def __init__(
        self,
        room_id: str,
        *,
        catalog_reader: dds.DataReader | None = None,
    ) -> None:
        self._room_id = room_id
        self._catalog_reader = catalog_reader
        self._participant: dds.DomainParticipant | None = None
        self._siblings: dict[str, str] = {}  # display_name → gui_url
        self._task: asyncio.Task[Any] | None = None
        self._running = False

        if self._catalog_reader is None:
            self._init_dds()

    @property
    def room_id(self) -> str:
        return self._room_id

    @property
    def siblings(self) -> dict[str, str]:
        """Live map of discovered sibling GUI services: display_name → gui_url."""
        return dict(self._siblings)

    def _init_dds(self) -> None:
        initialize_connext()
        provider = dds.QosProvider.default
        participant = provider.create_participant_from_config(_nav_names.ROOM_NAV)
        if participant is None:
            raise RuntimeError("Failed to create RoomNav participant")

        qos = participant.qos
        qos.partition.name = ["procedure"]
        participant.qos = qos
        participant.enable()
        self._participant = participant

        reader = participant.find_datareader(_nav_names.SERVICE_CATALOG_READER)
        if reader is None:
            raise RuntimeError(f"Reader not found: {_nav_names.SERVICE_CATALOG_READER}")
        self._catalog_reader = dds.DataReader(reader)

    async def start(self) -> None:
        """Begin receiving ServiceCatalog samples."""
        self._running = True
        self._task = background_tasks.create(self._receive_service_catalog())

    async def close(self) -> None:
        """Stop receiving and release DDS resources."""
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

        if self._catalog_reader is not None:
            try:
                self._catalog_reader.close()
            except Exception:
                log.exception("Error closing RoomNav catalog reader")

        if self._participant is not None:
            try:
                self._participant.close()
            except Exception:
                log.exception("Error closing RoomNav participant")
            self._participant = None

    async def _receive_service_catalog(self) -> None:
        async for sample in self._catalog_reader.take_data_async():
            self._update_catalog(sample)

    def _update_catalog(self, sample: Any) -> None:
        """Process a ServiceCatalog sample and update siblings map."""
        props = getattr(sample, "properties", []) or []
        prop_map = {_text(p.name): _text(p.current_value) for p in props}
        room_id = prop_map.get("room_id", "")
        if room_id != self._room_id:
            return
        gui_url = prop_map.get("gui_url", "")
        display_name = _text(getattr(sample, "display_name", ""))
        if gui_url and display_name:
            self._siblings[display_name] = gui_url
        elif display_name and display_name in self._siblings:
            # Service lost its gui_url — remove from nav
            del self._siblings[display_name]

    def render_nav_pill(self, active_label: str = "") -> None:
        """Render floating navigation pill for room-level GUI discovery.

        Parameters
        ----------
        active_label:
            The ``display_name`` of the currently active GUI.  That button
            receives a highlight style.
        """
        _NAV_PILL_CSS = (
            "position: fixed; top: 18px; left: 50%; transform: translateX(-50%);"
            " z-index: 100; pointer-events: auto;"
            " max-width: 95vw; white-space: nowrap;"
        )
        with (
            ui.row()
            .classes(
                "items-center gap-2 px-4 py-2 rounded-full glass-panel flex-nowrap"
            )
            .style(_NAV_PILL_CSS)
        ):
            ui.label(self._room_id).classes("type-h3 mr-2")

            @ui.refreshable
            def _render_buttons() -> None:
                for name, url in sorted(self._siblings.items()):
                    classes = "rounded-full px-4 transition-fast"
                    if name == active_label:
                        classes += " bg-primary text-white"
                    ui.button(
                        name,
                        icon=ICONS.get("open_in_new", "open_in_new"),
                        on_click=lambda u=url: ui.navigate.to(u),
                    ).props("flat no-caps size=md").classes(classes)

            _render_buttons()

            ui.timer(1.0, _render_buttons.refresh)
