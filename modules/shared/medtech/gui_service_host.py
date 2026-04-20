"""medtech.gui_service_host — GUI-capable ServiceHost specialization."""

from __future__ import annotations

from medtech.gui_runtime import NiceGuiRuntime
from medtech.gui_service import GuiService
from medtech.service import Service, ServiceState
from medtech.service_host import ServiceHost, ServiceRegistryMap


class GuiServiceHost(ServiceHost):
    """ServiceHost that owns a process-local NiceGUI runtime."""

    def __init__(
        self,
        host_id: str,
        host_name: str,
        capacity: int,
        registry: ServiceRegistryMap,
        gui_runtime: NiceGuiRuntime,
    ) -> None:
        self._gui_runtime = gui_runtime
        super().__init__(
            host_id,
            host_name,
            capacity,
            registry,
            start_service_validator=self._validate_gui_service_start,
        )

    @property
    def gui_runtime(self) -> NiceGuiRuntime:
        return self._gui_runtime

    @staticmethod
    def _validate_gui_service_start(
        service_id: str,
        service: Service,
        running_slots: dict[str, object],
    ) -> None:
        """Ensure no two running GUI services claim overlapping routes."""
        if not isinstance(service, GuiService):
            return

        new_paths = set(service.claimed_paths)
        if not new_paths:
            return

        for existing_id, slot in running_slots.items():
            existing_service = getattr(slot, "service", None)
            if (
                existing_service is None
                or not isinstance(existing_service, GuiService)
                or existing_service.state in (ServiceState.STOPPED, ServiceState.FAILED)
            ):
                continue

            overlap = new_paths.intersection(existing_service.claimed_paths)
            if overlap:
                overlap_list = ", ".join(sorted(overlap))
                raise RuntimeError(
                    f"GUI route conflict for {service_id}: {overlap_list} "
                    f"already claimed by {existing_id}"
                )


def make_gui_service_host(
    host_id: str,
    host_name: str,
    capacity: int,
    registry: ServiceRegistryMap,
    gui_runtime: NiceGuiRuntime,
) -> GuiServiceHost:
    """Create a GUI-capable ServiceHost with the given runtime."""
    return GuiServiceHost(host_id, host_name, capacity, registry, gui_runtime)
