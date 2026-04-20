"""Digital Twin Service — host-managed GUI service lifecycle.

Implements medtech.GuiService and embeds the DigitalTwinBackend directly in the
host process. The host owns the NiceGUI runtime and this service contributes
Digital Twin state + URLs to orchestration.
"""

from __future__ import annotations

import asyncio
import time

from medtech.gui_runtime import NiceGuiRuntime
from medtech.gui_service import GuiService
from medtech.log import ModuleName, init_logging
from medtech.service import ServiceState
from surgical_procedure.digital_twin.digital_twin import _ensure_room_nav, _get_backend

log = init_logging(ModuleName.SURGICAL_PROCEDURE)


class DigitalTwinService(GuiService):
    """Procedure-scoped digital twin GUI service.

    The underlying page routes are registered by the digital_twin module and the
    backend lifecycle is managed in-process (no subprocess launch).
    """

    def __init__(
        self,
        room_id: str,
        procedure_id: str,
        *,
        host_id: str = "operator-host",
        gui_runtime: NiceGuiRuntime,
    ) -> None:
        super().__init__(
            gui_runtime,
            canonical_path=f"/twin/{room_id}",
            claimed_paths=("/twin/{room_id}",),
        )
        self._room_id = room_id
        self._procedure_id = procedure_id
        self._host_id = host_id
        self._svc_state = ServiceState.STOPPED
        self._stop_event: asyncio.Event | None = None
        self._backend = _get_backend(room_id, procedure_id)
        urls = self.gui_urls()
        if urls:
            self._backend.gui_url = urls[0]
        _ensure_room_nav(room_id, self.gui_runtime.external_base_url)

    @property
    def name(self) -> str:
        return "DigitalTwinService"

    @property
    def state(self) -> ServiceState:
        return self._svc_state

    async def run(self) -> None:
        """Run until stopped while backend is hosted by NiceGUI runtime."""
        self._stop_event = asyncio.Event()
        try:
            self._svc_state = ServiceState.STARTING

            # DigitalTwinBackend start() is scheduled by GuiBackend via NiceGUI
            # startup hooks. Wait briefly for readiness to become true.
            deadline = time.monotonic() + 10.0
            while not self._backend.is_ready() and time.monotonic() < deadline:
                await asyncio.sleep(0.1)

            if not self._backend.is_ready():
                log.warning(
                    "DigitalTwin backend not ready yet; continuing and awaiting stop"
                )

            self._svc_state = ServiceState.RUNNING
            urls = self.gui_urls()
            log.notice(
                f"DigitalTwinService running: room={self._room_id}, "
                f"procedure={self._procedure_id}, gui_url={urls[0] if urls else 'n/a'}"
            )
            await self._stop_event.wait()

        except Exception as ex:
            self._svc_state = ServiceState.FAILED
            log.error(f"DigitalTwinService failed: {ex}")
            raise
        finally:
            if self._svc_state != ServiceState.FAILED:
                self._svc_state = ServiceState.STOPPING
            try:
                await self._backend.close()
            except Exception as ex:
                log.warning(f"DigitalTwinService backend close failed: {ex}")
            if self._svc_state != ServiceState.FAILED:
                self._svc_state = ServiceState.STOPPED
            log.notice("DigitalTwinService stopped")

    def stop(self) -> None:
        """Signal service loop to exit."""
        if self._stop_event is not None:
            self._stop_event.set()
