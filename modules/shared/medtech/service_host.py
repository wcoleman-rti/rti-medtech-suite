"""medtech.service_host — Generic Service Host for orchestration.

Provides the reusable ServiceHost class that all concrete service hosts
(robot, clinical, operational) share.  A concrete host only needs to
provide a service registry and call ``make_service_host()``.

C++ and Python service host implementations mirror each other:
  C++ — medtech::make_service_host<N>()  (service_host.hpp / .cpp)
  Py  — medtech.service_host.make_service_host()  (this module)

Key types are keyed by service_id (str, matching Common::EntityId).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from typing import Callable

import app_names
import common
import rti.connextdds as dds
import rti.rpc
from medtech.dds import initialize_connext
from medtech.service import Service, ServiceState
from orchestration import Orchestration

orch_names = app_names.MedtechEntityNames.OrchestrationParticipants
Time_t = common.Common.Time_t

# ---------------------------------------------------------------------------
# ServiceFactory — creates a medtech.Service.
#
# Accepts the full Orchestration.ServiceRequest so the host can pass
# both the service_id and any configuration properties to each service
# it creates.  All other context (room_id, procedure_id, device IDs,
# logger, …) is captured in the closure at registration time.
# ---------------------------------------------------------------------------
ServiceFactory = Callable[[Orchestration.ServiceRequest], Service]
"""Callable(req: Orchestration.ServiceRequest) -> Service"""


@dataclasses.dataclass
class ServiceRegistration:
    """Bundles a factory with its catalog metadata."""

    factory: ServiceFactory
    display_name: str
    properties: list  # list[Orchestration.PropertyDescriptor]


ServiceRegistryMap = dict[str, ServiceRegistration]
"""Registry map keyed by service_id (Common::EntityId)."""


# ---------------------------------------------------------------------------
# ServiceHostControlImpl — RPC handler (Python ABC implementation).
# ---------------------------------------------------------------------------
class _ServiceHostControlImpl(Orchestration.ServiceHostControl):
    """Generic RPC implementation dispatching to a service registry.

    Each method is called by the rti.rpc.Service dispatch loop on a
    background asyncio task.  Mirrors the C++ ServiceHostControlImpl.
    """

    def __init__(
        self,
        host_id: str,
        capacity: int,
        registry: ServiceRegistryMap,
    ) -> None:
        self._host_id = host_id
        self._capacity = capacity
        self._registry = registry
        self._slots: dict[str, _ServiceSlot] = {}
        self._log = logging.getLogger(f"medtech.service_host.{host_id}")

    def start_service(
        self, req: Orchestration.ServiceRequest
    ) -> Orchestration.OperationResult:
        svc_id: str = req.service_id
        result = Orchestration.OperationResult()

        if svc_id not in self._registry:
            result.code = Orchestration.OperationResultCode.INVALID_SERVICE
            result.message = f"Unknown service: {svc_id}"
            self._log.info("start_service rejected: INVALID_SERVICE (%s)", svc_id)
            return result

        slot = self._slots.get(svc_id)
        if slot is not None:
            st = slot.service.state
            if st not in (ServiceState.STOPPED, ServiceState.FAILED):
                result.code = Orchestration.OperationResultCode.ALREADY_RUNNING
                result.message = "Service is already running"
                self._log.info("start_service rejected: ALREADY_RUNNING (%s)", svc_id)
                return result
            # Clear stale slot
            del self._slots[svc_id]

        try:
            service = self._registry[svc_id].factory(req)
            task = asyncio.ensure_future(service.run())
            self._slots[svc_id] = _ServiceSlot(service=service, task=task)

            result.code = Orchestration.OperationResultCode.OK
            result.message = "Service started"
            self._log.info("start_service: OK (service_id=%s)", svc_id)
        except Exception:
            self._log.exception("start_service: INTERNAL_ERROR")
            result.code = Orchestration.OperationResultCode.INTERNAL_ERROR
            result.message = "Failed to start service"
        return result

    def stop_service(self, service_id: str) -> Orchestration.OperationResult:
        svc_id: str = service_id
        result = Orchestration.OperationResult()

        slot = self._slots.get(svc_id)
        if slot is None or slot.service.state == ServiceState.STOPPED:
            result.code = Orchestration.OperationResultCode.NOT_RUNNING
            result.message = "Service is not running"
            self._log.info("stop_service rejected: NOT_RUNNING (%s)", svc_id)
            return result

        slot.service.stop()
        # Keep slot so the status polling loop can detect the STOPPED
        # transition and publish ServiceStatus.  start_service clears
        # stale STOPPED/FAILED slots before creating a new service.

        result.code = Orchestration.OperationResultCode.OK
        result.message = "Service stopped"
        self._log.info("stop_service: OK (service_id=%s)", svc_id)
        return result

    def update_service(
        self, req: Orchestration.ServiceRequest
    ) -> Orchestration.OperationResult:
        result = Orchestration.OperationResult()
        result.code = Orchestration.OperationResultCode.OK
        result.message = "Configuration accepted (no-op in V1.0)"
        self._log.info("update_service: OK (service_id=%s)", req.service_id)
        return result

    def get_capabilities(self) -> Orchestration.CapabilityReport:
        report = Orchestration.CapabilityReport()
        report.capacity = self._capacity
        self._log.info(
            "get_capabilities: capacity=%d",
            self._capacity,
        )
        return report

    def get_health(self) -> Orchestration.HealthReport:
        report = Orchestration.HealthReport()
        report.alive = True
        if not self._slots:
            report.summary = "No services running"
        else:
            parts = [
                f"{sid}: {int(slot.service.state)}" for sid, slot in self._slots.items()
            ]
            report.summary = "; ".join(parts)
        report.diagnostics = ""
        return report

    def service_states(self) -> dict[str, ServiceState]:
        """Return current state for every running service."""
        return {sid: slot.service.state for sid, slot in self._slots.items()}

    def registered_service_ids(self) -> list[str]:
        """Return registry-registered service IDs."""
        return list(self._registry.keys())

    @property
    def registry(self) -> ServiceRegistryMap:
        """Read-only access to the registry for catalog publishing."""
        return self._registry

    async def stop_all(self) -> None:
        """Stop all running services."""
        for slot in self._slots.values():
            slot.service.stop()
        tasks = [slot.task for slot in self._slots.values() if slot.task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._slots.clear()


class _ServiceSlot:
    """A running service instance and its asyncio task."""

    __slots__ = ("service", "task")

    def __init__(self, service: Service, task: asyncio.Task | None) -> None:
        self.service = service
        self.task = task


# ---------------------------------------------------------------------------
# ServiceHost — generic medtech.Service wrapping the orchestration layer.
# ---------------------------------------------------------------------------
class ServiceHost(Service):
    """Generic orchestration host managing services via RPC.

    Creates an Orchestration domain participant, registers the RPC service,
    publishes ServiceCatalog and ServiceStatus, and blocks in run().
    Configured via ServiceRegistryMap — the only variation point between
    robot, clinical, and operational service hosts.
    """

    def __init__(
        self,
        host_id: str,
        host_name: str,
        capacity: int,
        registry: ServiceRegistryMap,
    ) -> None:
        if len(registry) > capacity:
            raise ValueError(
                f"ServiceHost(capacity={capacity}): registered "
                f"{len(registry)} services — exceeds capacity"
            )

        self._host_id = host_id
        self._host_name = host_name
        self._capacity = capacity
        self._state_val = ServiceState.STOPPED
        self._stop_event: asyncio.Event | None = None
        self._log = logging.getLogger(f"medtech.service_host.{host_id}")

        # -- Create Orchestration domain participant from XML --
        initialize_connext()
        provider = dds.QosProvider.default
        self._participant = provider.create_participant_from_config(
            orch_names.ORCHESTRATION
        )

        self._log.info("Orchestration participant created")

        # -- Look up pub/sub entities --
        catalog_any = self._participant.find_datawriter(
            orch_names.SERVICE_CATALOG_WRITER
        )
        status_any = self._participant.find_datawriter(orch_names.SERVICE_STATUS_WRITER)
        if catalog_any is None:
            raise RuntimeError(f"Writer not found: {orch_names.SERVICE_CATALOG_WRITER}")
        if status_any is None:
            raise RuntimeError(f"Writer not found: {orch_names.SERVICE_STATUS_WRITER}")
        self._catalog_writer = dds.DataWriter(catalog_any)
        self._status_writer = dds.DataWriter(status_any)
        self._log.info("Orchestration DataWriters found")

        # -- Create the RPC implementation --
        self._rpc_impl = _ServiceHostControlImpl(host_id, capacity, registry)

    async def run(self) -> None:
        self._state_val = ServiceState.STARTING
        self._stop_event = asyncio.Event()

        # Enable the orchestration participant
        self._participant.enable()

        # -- Set up the RPC service --
        rpc_service = rti.rpc.Service(
            service_instance=self._rpc_impl,
            participant=self._participant,
            service_name=f"ServiceHostControl/{self._host_id}",
        )
        self._log.info("RPC service registered: ServiceHostControl/%s", self._host_id)

        # -- Publish initial ServiceCatalog (one instance per service) --
        self._publish_service_catalog()

        # -- Publish initial ServiceStatus (STOPPED) for each service --
        for svc_id in self._rpc_impl.registered_service_ids():
            self._publish_service_status(svc_id, ServiceState.STOPPED)

        self._state_val = ServiceState.RUNNING
        self._log.info("%s running (host_id=%s)", self._host_name, self._host_id)

        # -- Run RPC + status polling concurrently --
        rpc_task = asyncio.ensure_future(rpc_service.run(close_on_cancel=False))
        try:
            last_published_states: dict[str, ServiceState] = {}
            while not self._stop_event.is_set():
                await asyncio.sleep(0.1)

                states = self._rpc_impl.service_states()
                for svc_id, state in states.items():
                    if last_published_states.get(svc_id) != state:
                        self._publish_service_status(svc_id, state)
                        last_published_states[svc_id] = state
        finally:
            # -- Shutdown --
            self._state_val = ServiceState.STOPPING
            self._log.info("%s shutting down", self._host_name)

            await self._rpc_impl.stop_all()
            rpc_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(rpc_task), timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
            try:
                rpc_service.close()
            except Exception:
                pass

            self._state_val = ServiceState.STOPPED

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    @property
    def name(self) -> str:
        return self._host_name

    @property
    def state(self) -> ServiceState:
        return self._state_val

    # -- Private helpers --

    def _publish_service_catalog(self) -> None:
        for svc_id, reg in self._rpc_impl.registry.items():
            catalog = Orchestration.ServiceCatalog(
                host_id=self._host_id,
                service_id=svc_id,
                display_name=reg.display_name,
                properties=list(reg.properties),
                health_summary="OK",
            )
            self._catalog_writer.write(catalog)
            self._log.info("Published ServiceCatalog for %s/%s", self._host_id, svc_id)

    def _publish_service_status(self, service_id: str, svc_state: ServiceState) -> None:
        now = time.time()
        sec = int(now)
        nsec = int((now - sec) * 1_000_000_000)

        status = Orchestration.ServiceStatus(
            host_id=self._host_id,
            service_id=service_id,
            state=svc_state,
            timestamp=Time_t(sec=sec & 0xFFFFFFFF, nsec=nsec),
        )
        self._status_writer.write(status)
        self._log.info("Published ServiceStatus: %d for %s", int(svc_state), service_id)


def make_service_host(
    host_id: str,
    host_name: str,
    capacity: int,
    registry: ServiceRegistryMap,
) -> ServiceHost:
    """Create a ServiceHost with the given registry and capacity.

    Usage::

        registry = {
            "RobotControllerService": ServiceRegistration(
                factory=lambda req: make_robot(req, room, proc, log),
                display_name="Robot Controller",
                properties=[],
            ),
        }
        host = make_service_host(
            "robot-host-or1",
            "RobotServiceHost", 1, registry
        )
        await host.run()
    """
    return ServiceHost(host_id, host_name, capacity, registry)
