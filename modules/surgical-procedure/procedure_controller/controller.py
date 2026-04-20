"""Procedure Controller - NiceGUI web application for orchestration.

This module provides the NiceGUI migration target for the Procedure Controller
workflow. It keeps the controller state in a backend object owned by NiceGUI's
lifecycle hooks and renders host/service views from cached DDS samples.
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import app_names
import rti.asyncio  # noqa: F401 - enables async DDS methods
import rti.connextdds as dds
import rti.rpc
from fastapi import HTTPException
from medtech.dds import initialize_connext
from medtech.gui import (
    BRAND_COLORS,
    ICONS,
    NICEGUI_STORAGE_SECRET_DEFAULT,
    NICEGUI_STORAGE_SECRET_ENV,
    GuiBackend,
    create_empty_state,
    create_status_chip,
    init_theme,
)
from medtech.gui._colors import OPACITY
from medtech.gui._theme import NICEGUI_THEME_MODE_KEY, _theme_mode_value
from medtech.log import ModuleName, init_logging
from nicegui import app, background_tasks, run, ui
from orchestration import Orchestration
from surgery import Surgery

dash_names = app_names.MedtechEntityNames.OrchestrationParticipants
surg_names = app_names.MedtechEntityNames.SurgicalParticipants

log = init_logging(ModuleName.HOSPITAL_DASHBOARD)

_RPC_TIMEOUT = dds.Duration(seconds=10)
_UI_REFRESH_INTERVAL = 0.5

_SERVICE_STATE_COLORS = {
    "RUNNING": BRAND_COLORS["green"],
    "STARTING": BRAND_COLORS["blue"],
    "STOPPING": BRAND_COLORS["amber"],
    "STOPPED": BRAND_COLORS["gray"],
    "FAILED": BRAND_COLORS["red"],
    "UNKNOWN": BRAND_COLORS["light_gray"],
}


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    value = hex_color.lstrip("#")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return f"rgba({red}, {green}, {blue}, {alpha})"


@dataclass
class _ViewState:
    mode: str = "hosts"
    service_filter: str = "ALL"
    selected_host_id: str | None = None
    selected_service_key: tuple[str, str] | None = None
    procedure_filter: str | None = None  # None = "All procedures"


class ControllerBackend(GuiBackend):
    """NiceGUI backend that owns Procedure Controller DDS resources."""

    def __init__(
        self,
        room_id: str = "OR-1",
        *,
        catalog_reader: dds.DataReader | None = None,
        status_reader: dds.DataReader | None = None,
    ) -> None:
        self._room_id = room_id
        self._running = False
        self._tasks: list[asyncio.Task[Any]] = []
        self._requesters: dict[str, rti.rpc.Requester] = {}
        self._orch_participant: dds.DomainParticipant | None = None
        self._proc_op_participant: dds.DomainParticipant | None = None
        self._proc_control_participant: dds.DomainParticipant | None = None
        self._arm_assignment_reader: dds.DataReader | None = None
        self._procedure_status_writer: dds.DataWriter | None = None
        self._service_catalog_writer: dds.DataWriter | None = None
        self._last_procedure_phase: Surgery.ProcedurePhase | None = None
        self._gui_url: str = ""
        self._twin_url: str = ""
        self._default_procedure_id: str = ""
        self._catalog_reader = catalog_reader
        self._status_reader = status_reader

        self._catalogs: dict[tuple[str, str], Orchestration.ServiceCatalog] = {}
        self._service_states: dict[tuple[str, str], Orchestration.ServiceStatus] = {}
        self._pub_handle_to_host: dict[dds.InstanceHandle, str] = {}
        self._arm_states: dict[str, Surgery.RobotArmAssignment] = {}
        self._view = _ViewState()
        self._diag_log: list[str] = []
        self._max_log_entries = 200

        self.status_message: str = "Discovering service hosts..."

        if self._catalog_reader is None or self._status_reader is None:
            self._init_dds()

        super().__init__()

    @property
    def name(self) -> str:
        return "ProcedureController"

    @property
    def view_mode(self) -> str:
        return self._view.mode

    def show_hosts_view(self) -> None:
        self._view.mode = "hosts"
        self._view.service_filter = "ALL"
        self._clear_selection()

    def show_services_view(self, filter_state: str = "ALL") -> None:
        self._view.mode = "services"
        self._view.service_filter = filter_state
        self._clear_selection()

    def show_diagnostics_view(self) -> None:
        self._view.mode = "diagnostics"
        self._clear_selection()

    def _log_diag(self, message: str) -> None:
        import datetime

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._diag_log.append(f"[{ts}] {message}")
        if len(self._diag_log) > self._max_log_entries:
            self._diag_log = self._diag_log[-self._max_log_entries :]

    def _clear_selection(self) -> None:
        self._view.selected_host_id = None
        self._view.selected_service_key = None

    def _service_matches_filter(
        self, status: Orchestration.ServiceStatus | None
    ) -> bool:
        filter_state = self._view.service_filter
        if filter_state == "ALL":
            return True
        if status is None:
            return False
        return _state_name(status.state).upper() == filter_state

    def service_filter_label(self) -> str:
        labels = {
            "ALL": "All services",
            "RUNNING": "Running only",
            "STOPPED": "Stopped only",
            "FAILED": "Failed only",
        }
        return labels.get(self._view.service_filter, "All services")

    def visible_catalog_items(
        self,
    ) -> list[tuple[tuple[str, str], Orchestration.ServiceCatalog]]:
        items: list[tuple[tuple[str, str], Orchestration.ServiceCatalog]] = []
        for key, catalog in self._catalogs.items():
            # Hide the controller's own nav entry — it is this page
            if catalog.display_name == "Procedure Controller":
                continue
            status = self._service_states.get(key)
            if not self._service_matches_filter(status):
                continue
            if self._view.procedure_filter is not None:
                proc_id = _catalog_property(catalog, "procedure_id")
                if proc_id != self._view.procedure_filter:
                    continue
            items.append((key, catalog))
        return items

    def running_service_count(self) -> int:
        return sum(
            1
            for status in self._service_states.values()
            if _state_name(status.state).upper() in ("RUNNING", "STARTED", "ACTIVE")
        )

    def known_procedure_ids(self) -> list[str]:
        """Sorted list of distinct procedure_id values seen in ServiceCatalog.

        Only includes services that are currently deployed in a procedure
        (non-empty procedure_id property).
        """
        procs: set[str] = set()
        for catalog in self._catalogs.values():
            pid = _catalog_property(catalog, "procedure_id")
            if pid:
                procs.add(pid)
        return sorted(procs)

    # --- Procedure lifecycle ---------------------------------------------------

    def _publish_procedure_status(
        self, procedure_id: str, phase: Surgery.ProcedurePhase, message: str = ""
    ) -> None:
        """Publish ProcedureStatus on the Procedure operational databus (write-on-change)."""
        if self._procedure_status_writer is None:
            return
        if self._last_procedure_phase == phase:
            return  # write-on-change: skip if state unchanged
        status = Surgery.ProcedureStatus(
            procedure_id=procedure_id,
            phase=phase,
            status_message=message,
        )
        self._procedure_status_writer.write(status)
        self._last_procedure_phase = phase
        log.notice(
            f"ProcedureStatus published: procedure={procedure_id}, "
            f"phase={phase.name}, message={message}"
        )
        self._log_diag(f"ProcedureStatus → {phase.name}: {message}")

    @property
    def active_procedure_id(self) -> str:
        """Return the active procedure_id for this room, or '' if none."""
        for catalog in self._catalogs.values():
            rid = _catalog_property(catalog, "room_id")
            if rid and rid != self._room_id:
                continue
            pid = _catalog_property(catalog, "procedure_id")
            if pid:
                return pid
        return ""

    def idle_services(
        self,
    ) -> list[tuple[tuple[str, str], Orchestration.ServiceCatalog]]:
        """Services in this room with empty procedure_id (available for deployment)."""
        items: list[tuple[tuple[str, str], Orchestration.ServiceCatalog]] = []
        for key, catalog in self._catalogs.items():
            rid = _catalog_property(catalog, "room_id")
            if rid and rid != self._room_id:
                continue
            pid = _catalog_property(catalog, "procedure_id")
            if not pid:
                items.append((key, catalog))
        return sorted(items)

    def procedure_services(
        self,
    ) -> list[tuple[tuple[str, str], Orchestration.ServiceCatalog]]:
        """Services currently deployed in the active procedure."""
        active = self.active_procedure_id
        if not active:
            return []
        items: list[tuple[tuple[str, str], Orchestration.ServiceCatalog]] = []
        for key, catalog in self._catalogs.items():
            if catalog.display_name == "Procedure Controller":
                continue
            pid = _catalog_property(catalog, "procedure_id")
            if pid == active:
                items.append((key, catalog))
        return sorted(items)

    def generate_procedure_id(self) -> str:
        """Return the deployment-time procedure_id if set, else generate one."""
        if self._default_procedure_id:
            return self._default_procedure_id
        return f"{self._room_id}-{int(time.time() * 1000)}"

    async def start_procedure(
        self,
        service_keys: list[tuple[str, str]],
        procedure_id: str,
    ) -> None:
        """Start a new procedure: send start_service RPCs with procedure_id.

        Also automatically deploys DigitalTwinService to any OperatorServiceHost,
        as the digital twin is a procedure-scoped service that displays procedure state.
        """
        self._publish_procedure_status(
            procedure_id, Surgery.ProcedurePhase.PRE_OP, "Deploying services"
        )

        # Collect user-selected services
        for host_id, service_id in service_keys:
            props: list[tuple[str, str]] = [
                ("procedure_id", procedure_id),
                ("room_id", self._room_id),
            ]
            await self._do_rpc(
                host_id, _make_start_call(service_id, props), "start_service"
            )

        # Auto-deploy DigitalTwinService to any available operator service host
        # Find an operator service host (usually operator-host-{room_id})
        for (host_id, service_id), catalog in self.catalogs.items():
            # Look for operator service host by its display type/id pattern
            if "operator" in host_id.lower() or "operator" in service_id.lower():
                # Check if this host has OperatorConsoleService (identifier of operator host)
                if service_id == "OperatorConsoleService":
                    # Deploy digital twin to this host
                    props: list[tuple[str, str]] = [
                        ("procedure_id", procedure_id),
                        ("room_id", self._room_id),
                    ]
                    try:
                        await self._do_rpc(
                            host_id,
                            _make_start_call("DigitalTwinService", props),
                            "start_service",
                        )
                        self._log_diag(
                            f"DigitalTwinService deployed to {host_id} for procedure {procedure_id}"
                        )
                    except Exception as ex:
                        self._log_diag(f"Failed to deploy DigitalTwinService: {ex}")
                    break  # Only deploy to the first operator host found

    async def add_to_procedure(
        self,
        service_keys: list[tuple[str, str]],
    ) -> None:
        """Add services to the active procedure."""
        active = self.active_procedure_id
        if not active:
            return
        for host_id, service_id in service_keys:
            props: list[tuple[str, str]] = [("procedure_id", active)]
            await self._do_rpc(
                host_id, _make_start_call(service_id, props), "start_service"
            )

    async def stop_procedure(self) -> None:
        """Stop all services in the active procedure."""
        active = self.active_procedure_id
        if active:
            self._publish_procedure_status(
                active, Surgery.ProcedurePhase.COMPLETING, "Stopping services"
            )
        for (host_id, service_id), _catalog in self.procedure_services():
            await self.stop_service(host_id, service_id)
        if active:
            self._publish_procedure_status(
                active, Surgery.ProcedurePhase.COMPLETED, "Procedure ended"
            )
            self._last_procedure_phase = None  # reset for next procedure

    def set_procedure_filter(self, procedure_id: str | None) -> None:
        """Set the procedure filter (None = all procedures)."""
        self._view.procedure_filter = procedure_id

    @property
    def arm_states(self) -> dict[str, Surgery.RobotArmAssignment]:
        """Current arm assignment states keyed by robot_id."""
        return dict(self._arm_states)

    @property
    def active_arm_count(self) -> int:
        """Number of currently tracked (non-disposed) arms."""
        return len(self._arm_states)

    @property
    def procedure_ready(self) -> bool:
        """True when at least one arm is tracked and all are OPERATIONAL."""
        if not self._arm_states:
            return False
        return all(
            arm.status == Surgery.ArmAssignmentState.OPERATIONAL
            for arm in self._arm_states.values()
        )

    def non_ready_arms(self) -> dict[str, str]:
        """Return {robot_id: state_name} for tracked arms not yet OPERATIONAL."""
        result: dict[str, str] = {}
        for robot_id, arm in self._arm_states.items():
            if arm.status != Surgery.ArmAssignmentState.OPERATIONAL:
                result[robot_id] = str(arm.status).rsplit(".", 1)[-1]
        return result

    async def start_service(
        self,
        host_id: str,
        service_id: str,
        table_position: str = "",
    ) -> None:
        if self.active_arm_count >= Surgery.MAX_ARM_COUNT:
            self._log_diag(
                f"start_service rejected: MAX_ARM_COUNT ({Surgery.MAX_ARM_COUNT}) exceeded"
            )
            return
        props: list[tuple[str, str]] = []
        if table_position:
            props.append(("table_position", table_position))
        await self._do_rpc(
            host_id, _make_start_call(service_id, props), "start_service"
        )

    async def stop_service(self, host_id: str, service_id: str) -> None:
        await self._do_rpc(host_id, _make_stop_call(service_id), "stop_service")

    async def update_service(
        self,
        host_id: str,
        service_id: str,
        properties: list | None = None,
    ) -> None:
        await self._do_rpc(
            host_id, _make_update_call(service_id, properties), "update_service"
        )

    async def host_capabilities(self, host_id: str) -> str:
        return await self._do_rpc_display(
            host_id, _make_get_capabilities_call(), "get_capabilities"
        )

    async def host_health(self, host_id: str) -> str:
        return await self._do_rpc_display(
            host_id, _make_get_health_call(), "get_health"
        )

    async def start_all_services(self) -> None:
        # Auto-assign table positions to robot arm hosts (round-robin).
        _auto_positions = [
            "RIGHT",
            "LEFT",
            "RIGHT_HEAD",
            "LEFT_HEAD",
            "RIGHT_FOOT",
            "LEFT_FOOT",
            "HEAD",
            "FOOT",
        ]
        robot_idx = 0
        for host_id, service_id in sorted(self.catalogs):
            if service_id == "RobotControllerService":
                pos = _auto_positions[robot_idx % len(_auto_positions)]
                await self.start_service(host_id, service_id, table_position=pos)
                robot_idx += 1
            else:
                await self.start_service(host_id, service_id)

    async def stop_all_services(self) -> None:
        for host_id, service_id in sorted(self.catalogs):
            await self.stop_service(host_id, service_id)

    def _init_dds(self) -> None:
        initialize_connext()
        provider = dds.QosProvider.default

        self._orch_participant = provider.create_participant_from_config(
            dash_names.PROCEDURE_CONTROLLER_ORCHESTRATION
        )
        if self._orch_participant is None:
            raise RuntimeError(
                "Failed to create Procedure Controller orchestration participant"
            )

        # Set room-scoped partition BEFORE enable() — static deployment-time property
        orch_qos = self._orch_participant.qos
        orch_qos.partition.name = [f"room/{self._room_id}"]
        self._orch_participant.qos = orch_qos

        self._orch_participant.enable()

        def _find_orch_reader(entity_name: str) -> dds.DataReader:
            reader = self._orch_participant.find_datareader(entity_name)
            if reader is None:
                raise RuntimeError(f"Reader not found: {entity_name}")
            return dds.DataReader(reader)

        self._catalog_reader = _find_orch_reader(dash_names.CTRL_SERVICE_CATALOG_READER)
        self._status_reader = _find_orch_reader(dash_names.CTRL_SERVICE_STATUS_READER)

        # ServiceCatalog writer — advertise room GUI endpoints
        catalog_writer_any = self._orch_participant.find_datawriter(
            dash_names.CTRL_SERVICE_CATALOG_WRITER
        )
        if catalog_writer_any is not None:
            self._service_catalog_writer = dds.DataWriter(catalog_writer_any)

        self._proc_op_participant = provider.create_participant_from_config(
            surg_names.PROCEDURE_CONTROLLER_PROCEDURE_OPERATIONAL
        )
        if self._proc_op_participant is None:
            raise RuntimeError(
                "Failed to create Procedure Controller procedure-operational participant"
            )
        proc_op_qos = self._proc_op_participant.qos
        proc_op_qos.partition.name = [f"room/{self._room_id}/procedure/*"]
        self._proc_op_participant.qos = proc_op_qos
        self._proc_op_participant.enable()

        # ProcedureStatus writer — controller is the lifecycle authority
        status_writer_any = self._proc_op_participant.find_datawriter(
            surg_names.CTRL_PROCEDURE_STATUS_WRITER
        )
        if status_writer_any is not None:
            self._procedure_status_writer = dds.DataWriter(status_writer_any)

        self._proc_control_participant = provider.create_participant_from_config(
            surg_names.PROCEDURE_CONTROLLER_PROCEDURE_CONTROL
        )
        if self._proc_control_participant is None:
            raise RuntimeError(
                "Failed to create Procedure Controller procedure-control participant"
            )

        proc_qos = self._proc_control_participant.qos
        proc_qos.partition.name = [f"room/{self._room_id}/procedure/*"]
        self._proc_control_participant.qos = proc_qos
        self._proc_control_participant.enable()

        arm_reader = self._proc_control_participant.find_datareader(
            surg_names.CTRL_ROBOT_ARM_ASSIGNMENT_READER
        )
        if arm_reader is not None:
            self._arm_assignment_reader = dds.DataReader(arm_reader)

    async def start(self) -> None:
        self._running = True
        self._tasks = [
            background_tasks.create(self._receive_service_catalog()),
            background_tasks.create(self._receive_service_status()),
            background_tasks.create(self._monitor_liveliness()),
            background_tasks.create(self._ui_consistency_sweep()),
        ]
        if self._arm_assignment_reader is not None:
            self._tasks.append(background_tasks.create(self._receive_arm_assignments()))
        if self._service_catalog_writer is not None:
            self._tasks.append(background_tasks.create(self._publish_gui_catalog()))
        self._mark_ready()

    async def close(self) -> None:
        self._running = False
        tasks = [
            task
            for task in self._tasks
            if isinstance(task, asyncio.Task) and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

        for requester in self._requesters.values():
            with suppress(Exception):
                requester.close()
        self._requesters.clear()

        for reader in [
            self._catalog_reader,
            self._status_reader,
            self._arm_assignment_reader,
        ]:
            if reader is not None:
                with suppress(Exception):
                    reader.close()

        for participant in (
            self._orch_participant,
            self._proc_op_participant,
            self._proc_control_participant,
        ):
            if participant is not None:
                with suppress(Exception):
                    participant.close()

        self._orch_participant = None
        self._proc_op_participant = None
        self._proc_control_participant = None
        self._arm_assignment_reader = None

        await rti.asyncio.close()

    def _known_host_ids(self) -> set[str]:
        return {host_id for host_id, _ in self._catalogs}

    def _services_by_host(self) -> dict[str, dict[str, Orchestration.ServiceCatalog]]:
        result: dict[str, dict[str, Orchestration.ServiceCatalog]] = {}
        for (host_id, service_id), catalog in self._catalogs.items():
            result.setdefault(host_id, {})[service_id] = catalog
        return result

    def _get_or_create_requester(self, host_id: str) -> rti.rpc.Requester:
        if host_id not in self._requesters:
            if self._orch_participant is None:
                raise RuntimeError("No Orchestration participant available")
            self._requesters[host_id] = rti.rpc.Requester(
                request_type=Orchestration.ServiceHostControl.call_type,
                reply_type=Orchestration.ServiceHostControl.return_type,
                participant=self._orch_participant,
                service_name=f"ServiceHostControl/{host_id}",
            )
        return self._requesters[host_id]

    def _update_catalog(self, catalog: Orchestration.ServiceCatalog) -> None:
        key = (catalog.host_id, catalog.service_id)
        is_new = key not in self._catalogs
        self._catalogs[key] = catalog
        self.status_message = f"Discovered {len(self._known_host_ids())} host(s)"
        if is_new:
            self._log_diag(
                f"Discovered service {catalog.service_id} on {catalog.host_id}"
            )

    def _update_service_status(self, status: Orchestration.ServiceStatus) -> None:
        key = (status.host_id, status.service_id)
        prev = self._service_states.get(key)
        self._service_states[key] = status
        new_state = _state_name(status.state)
        if prev is None or prev.state != status.state:
            self._log_diag(f"{status.service_id}@{status.host_id} → {new_state}")

        # Transition to IN_PROGRESS when first procedure service reaches RUNNING
        if (
            status.state == Orchestration.ServiceState.RUNNING
            and self._last_procedure_phase == Surgery.ProcedurePhase.PRE_OP
        ):
            active = self.active_procedure_id
            if active:
                self._publish_procedure_status(
                    active,
                    Surgery.ProcedurePhase.IN_PROGRESS,
                    "Procedure started",
                )

    def _remove_host(self, host_id: str) -> None:
        for key in [key for key in self._catalogs if key[0] == host_id]:
            del self._catalogs[key]
        for key in [key for key in self._service_states if key[0] == host_id]:
            del self._service_states[key]
        requester = self._requesters.pop(host_id, None)
        if requester is not None:
            with suppress(Exception):
                requester.close()
        if self._view.selected_host_id == host_id:
            self._view.selected_host_id = None
            self._view.selected_service_key = None
        self.status_message = f"Host {host_id} disconnected"
        self._log_diag(f"Host {host_id} lost liveliness — removed")

    async def _receive_service_catalog(self) -> None:
        async for sample in self._catalog_reader.take_async():
            if sample.info.valid:
                self._pub_handle_to_host[sample.info.publication_handle] = (
                    sample.data.host_id
                )
                self._update_catalog(sample.data)

    async def _receive_service_status(self) -> None:
        async for sample in self._status_reader.take_data_async():
            self._update_service_status(sample)

    async def _receive_arm_assignments(self) -> None:
        async for sample in self._arm_assignment_reader.take_async():
            if sample.info.valid:
                self._update_arm_assignment(sample.data)
            elif sample.info.state.instance_state in (
                dds.InstanceState.NOT_ALIVE_DISPOSED,
                dds.InstanceState.NOT_ALIVE_NO_WRITERS,
            ):
                try:
                    key_holder = self._arm_assignment_reader.key_value(
                        sample.info.instance_handle
                    )
                except dds.InvalidArgumentError:
                    continue  # instance already purged from reader cache
                rid = key_holder.robot_id
                if rid in self._arm_states:
                    del self._arm_states[rid]
                    reason = (
                        "disposed"
                        if sample.info.state.instance_state
                        == dds.InstanceState.NOT_ALIVE_DISPOSED
                        else "no writers"
                    )
                    self._log_diag(f"Arm {rid} removed ({reason})")

    def _update_arm_assignment(self, data: Surgery.RobotArmAssignment) -> None:
        prev = self._arm_states.get(data.robot_id)
        self._arm_states[data.robot_id] = data
        status_name = str(data.status).rsplit(".", 1)[-1]
        if prev is None:
            self._log_diag(
                f"Arm {data.robot_id} tracked: {status_name} "
                f"at {str(data.table_position).rsplit('.', 1)[-1]}"
            )
        elif prev.status != data.status:
            self._log_diag(f"Arm {data.robot_id} → {status_name}")

    def _make_gui_catalog(
        self, display_name: str, gui_url: str
    ) -> Orchestration.ServiceCatalog:
        """Build a ServiceCatalog entry advertising a room GUI endpoint."""
        props = [
            Orchestration.PropertyDescriptor(
                name="room_id",
                current_value=self._room_id,
                description="Room this GUI belongs to",
                required=False,
            ),
            Orchestration.PropertyDescriptor(
                name="gui_url",
                current_value=gui_url,
                description="GUI endpoint URL",
                required=False,
            ),
        ]
        return Orchestration.ServiceCatalog(
            host_id=f"controller-{self._room_id}",
            service_id=display_name,
            display_name=display_name,
            properties=props,
            health_summary="OK",
        )

    async def _publish_gui_catalog(self) -> None:
        """Periodically publish ServiceCatalog entries for room GUI endpoints.

        For the digital twin, append the active procedure_id as a query parameter
        so the twin initializes its backend with the correct procedure context.
        """
        while self._running:
            entries: list[Orchestration.ServiceCatalog] = []
            if self._gui_url:
                entries.append(
                    self._make_gui_catalog("Procedure Controller", self._gui_url)
                )
            if self._twin_url:
                active = self.active_procedure_id
                twin_url = self._twin_url
                # Append procedure_id query parameter if a procedure is active
                if active:
                    sep = "&" if "?" in twin_url else "?"
                    twin_url = f"{twin_url}{sep}procedure_id={active}"
                entries.append(self._make_gui_catalog("Digital Twin", twin_url))
            for entry in entries:
                self._service_catalog_writer.write(entry)
            await asyncio.sleep(5.0)  # re-publish periodically for late joiners

    async def _monitor_liveliness(self) -> None:
        status_condition = dds.StatusCondition(self._catalog_reader)
        status_condition.enabled_statuses = dds.StatusMask.LIVELINESS_CHANGED
        waitset = dds.WaitSet()
        waitset += status_condition
        try:
            while self._running:
                try:
                    await waitset.wait_async(dds.Duration(seconds=1))
                except dds.TimeoutError:
                    continue

                changes = self._catalog_reader.status_changes
                if dds.StatusMask.LIVELINESS_CHANGED not in changes:
                    continue

                status = self._catalog_reader.liveliness_changed_status
                if status.not_alive_count_change > 0:
                    host_id = self._pub_handle_to_host.pop(
                        status.last_publication_handle, None
                    )
                    if host_id is not None:
                        self._remove_host(host_id)
        finally:
            waitset -= status_condition

    async def _ui_consistency_sweep(self) -> None:
        while self._running:
            await asyncio.sleep(_UI_REFRESH_INTERVAL)

    def _on_refresh(self) -> None:
        try:
            for sample in self._catalog_reader.take():
                if sample.info.valid:
                    self._pub_handle_to_host[sample.info.publication_handle] = (
                        sample.data.host_id
                    )
                    self._update_catalog(sample.data)
        except dds.AlreadyClosedError:
            pass

        try:
            for sample in self._status_reader.take():
                if sample.info.valid:
                    self._update_service_status(sample.data)
        except dds.AlreadyClosedError:
            pass

        if self._arm_assignment_reader is not None:
            try:
                for sample in self._arm_assignment_reader.take():
                    if sample.info.valid:
                        self._update_arm_assignment(sample.data)
                    elif sample.info.state.instance_state in (
                        dds.InstanceState.NOT_ALIVE_DISPOSED,
                        dds.InstanceState.NOT_ALIVE_NO_WRITERS,
                    ):
                        key_holder = self._arm_assignment_reader.key_value(
                            sample.info.instance_handle
                        )
                        self._arm_states.pop(key_holder.robot_id, None)
            except dds.AlreadyClosedError:
                pass

    async def _do_rpc(self, host_id: str, call: object, op_name: str) -> None:
        try:
            requester = self._get_or_create_requester(host_id)
            if not await requester.wait_for_service_async(_RPC_TIMEOUT):
                self._log_diag(f"RPC {op_name} → {host_id}: service not available")
                return

            request_id = await run.io_bound(requester.send_request, call)
            if not await requester.wait_for_replies_async(
                max_wait=_RPC_TIMEOUT,
                related_request_id=request_id,
            ):
                self._log_diag(f"RPC {op_name} → {host_id}: timeout")
                return

            replies = await run.io_bound(
                requester.take_replies, related_request_id=request_id
            )
            result = None
            for reply, info in replies:
                if info.valid:
                    result = _extract_rpc_result(reply, op_name)
                    break
            self._log_diag(f"RPC {op_name} → {host_id}: {result or 'no valid reply'}")
        except Exception as exc:
            self._log_diag(f"RPC {op_name} → {host_id}: error — {exc}")

    async def _do_rpc_display(self, host_id: str, call: object, op_name: str) -> str:
        try:
            requester = self._get_or_create_requester(host_id)
            if not await requester.wait_for_service_async(_RPC_TIMEOUT):
                msg = f"RPC {op_name} → {host_id}: service not available"
                self._log_diag(msg)
                return msg

            request_id = await run.io_bound(requester.send_request, call)
            if not await requester.wait_for_replies_async(
                max_wait=_RPC_TIMEOUT,
                related_request_id=request_id,
            ):
                msg = f"RPC {op_name} → {host_id}: timeout"
                self._log_diag(msg)
                return msg

            replies = await run.io_bound(
                requester.take_replies, related_request_id=request_id
            )
            result = None
            for reply, info in replies:
                if info.valid:
                    result = _extract_rpc_result(reply, op_name)
                    break
            msg = f"RPC {op_name} → {host_id}: {result or 'no valid reply'}"
            self._log_diag(msg)
            return msg
        except Exception as exc:
            msg = f"RPC {op_name} → {host_id}: error — {exc}"
            self._log_diag(msg)
            return msg

    async def start_selected(self) -> None:
        if self._view.selected_service_key is None:
            return
        host_id, service_id = self._view.selected_service_key
        await self._do_rpc(host_id, _make_start_call(service_id), "start_service")

    async def stop_selected(self) -> None:
        if self._view.selected_service_key is None:
            return
        host_id, service_id = self._view.selected_service_key
        await self._do_rpc(host_id, _make_stop_call(service_id), "stop_service")

    async def capabilities_selected(self) -> None:
        if self._view.selected_host_id is None:
            return
        await self._do_rpc_display(
            self._view.selected_host_id,
            _make_get_capabilities_call(),
            "get_capabilities",
        )

    async def health_selected(self) -> None:
        if self._view.selected_host_id is None:
            return
        await self._do_rpc_display(
            self._view.selected_host_id,
            _make_get_health_call(),
            "get_health",
        )

    def select_host(self, host_id: str) -> None:
        self._view.mode = "hosts"
        self._view.selected_host_id = (
            None if self._view.selected_host_id == host_id else host_id
        )
        self._view.selected_service_key = None

    def select_service(self, host_id: str, service_id: str) -> None:
        self._view.mode = "services"
        self._view.service_filter = "ALL"
        key = (host_id, service_id)
        if self._view.selected_service_key == key:
            self._view.selected_host_id = None
            self._view.selected_service_key = None
            return
        self._view.selected_host_id = host_id
        self._view.selected_service_key = key

    def toggle_service_selection(self, host_id: str, service_id: str) -> None:
        """Toggle service selection without switching to service view."""
        key = (host_id, service_id)
        if self._view.selected_service_key == key:
            self._view.selected_service_key = None
        else:
            self._view.selected_service_key = key

    @property
    def catalogs(self) -> dict[tuple[str, str], Orchestration.ServiceCatalog]:
        return dict(self._catalogs)

    @property
    def service_count(self) -> int:
        """Number of real services (excludes the controller's own entry)."""
        return sum(
            1
            for c in self._catalogs.values()
            if c.display_name != "Procedure Controller"
        )

    @property
    def hosts(self) -> set[str]:
        return self._known_host_ids()

    @property
    def service_states(self) -> dict[tuple[str, str], Orchestration.ServiceStatus]:
        return dict(self._service_states)

    @property
    def orch_participant(self) -> dds.DomainParticipant | None:
        return self._orch_participant

    @property
    def hosp_participant(self) -> dds.DomainParticipant | None:
        return None

    @property
    def proc_op_participant(self) -> dds.DomainParticipant | None:
        return self._proc_op_participant

    @property
    def proc_control_participant(self) -> dds.DomainParticipant | None:
        return self._proc_control_participant

    def close_dds(self) -> None:
        self._running = False
        self._requesters.clear()
        for participant in (
            self._orch_participant,
            self._proc_op_participant,
            self._proc_control_participant,
        ):
            if participant is not None:
                with suppress(Exception):
                    participant.close()
        self._orch_participant = None
        self._proc_op_participant = None
        self._proc_control_participant = None
        self._arm_assignment_reader = None


backend: ControllerBackend | None = None

# Per-room controller backends (lazy, like DigitalTwinBackend)
_controller_backends: dict[str, ControllerBackend] = {}


def _get_backend(room_id: str) -> ControllerBackend:
    """Return (or create on first access) the ControllerBackend for *room_id*."""
    if room_id not in _controller_backends:
        _controller_backends[room_id] = ControllerBackend(room_id=room_id)
    return _controller_backends[room_id]


def _current_backend() -> ControllerBackend:
    global backend
    if backend is None:
        backend = ControllerBackend()
    return backend


_room_nav_instance: Any = None


def _configured_room_id() -> str:
    """Return the room identity configured for this controller instance."""
    return os.environ.get("ROOM_ID", "") or "OR-1"


@ui.page("/controller", title="Procedure Controller — Medtech Suite")
def controller_page() -> None:
    """Render the controller page (standalone with self-contained shell)."""
    init_theme(header=False)
    stored_mode = app.storage.user.get(NICEGUI_THEME_MODE_KEY, "system")
    ui.dark_mode(_theme_mode_value(stored_mode))
    _room_nav_instance.render_nav_pill(active_label="Procedure Controller")
    controller_content()


@ui.page("/controller/{room_id}", title="Procedure Controller — Medtech Suite")
def controller_page_for_room(room_id: str) -> None:
    """Render controller only when URL room_id matches this container's room."""
    if room_id != _configured_room_id():
        raise HTTPException(status_code=404, detail="Controller room not found")
    controller_page()


def controller_content_for_room(room_id: str) -> None:
    """Render controller content for a specific room.  Per-room sub_pages variant."""
    current_backend = _get_backend(room_id)
    _render_controller_ui(current_backend)


def controller_content() -> None:
    """Render controller content (legacy singleton).  Call from SPA sub_pages."""
    current_backend = _current_backend()
    _render_controller_ui(current_backend)


def _render_controller_ui(current_backend: ControllerBackend) -> None:
    """Shared controller UI rendering for both singleton and per-room backends."""

    # Mutable state for the "Start Procedure" selection dialog.
    _selected_for_procedure: set[tuple[str, str]] = set()

    def refresh_ui() -> None:
        render_summary_cards.refresh()
        render_procedure_bar.refresh()
        render_main_view.refresh()

    def _set_hosts_view() -> None:
        current_backend.show_hosts_view()
        refresh_ui()

    def _set_services_view() -> None:
        current_backend.show_services_view()
        refresh_ui()

    def _set_diagnostics_view() -> None:
        current_backend.show_diagnostics_view()
        refresh_ui()

    @ui.refreshable
    def render_summary_cards() -> None:
        with ui.row().classes(
            "w-full grid grid-cols-[repeat(auto-fit,minmax(14rem,1fr))] gap-4"
        ):
            _render_summary_card(
                title="Hosts",
                value=str(len(current_backend.hosts)),
                icon=ICONS["host"],
                color=BRAND_COLORS["blue"],
                active=current_backend.view_mode == "hosts",
                on_click=_set_hosts_view,
            )
            _render_summary_card(
                title="Services",
                value=str(current_backend.service_count),
                icon=ICONS["service"],
                color=BRAND_COLORS["green"],
                active=current_backend.view_mode == "services",
                on_click=_set_services_view,
            )
            _render_summary_card(
                title="Diagnostics",
                value=str(len(current_backend._diag_log)),
                icon=ICONS["info"],
                color=BRAND_COLORS["orange"],
                active=current_backend.view_mode == "diagnostics",
                on_click=_set_diagnostics_view,
            )

    @ui.refreshable
    def render_main_view() -> None:
        if current_backend.view_mode == "diagnostics":
            _render_diagnostics_view(current_backend)
        elif current_backend.view_mode == "services":
            _render_service_grid(current_backend, refresh_ui)
        else:
            _render_host_grid(current_backend, refresh_ui)

    @ui.refreshable
    def render_procedure_bar() -> None:
        _render_procedure_action_bar(
            current_backend, _selected_for_procedure, refresh_ui
        )

    with ui.column().classes("w-full gap-4 p-4"):
        render_summary_cards()

        render_procedure_bar()

        status_label = ui.label(current_backend.status_message).classes(
            "type-body-sm text-gray-500"
        )

        render_main_view()

        _last_snapshot: dict[str, Any] = {}

        def _take_snapshot() -> dict[str, Any]:
            return {
                "hosts": frozenset(current_backend.hosts),
                "catalog_keys": frozenset(current_backend.catalogs.keys()),
                "state_values": tuple(
                    (k, getattr(v, "state", None))
                    for k, v in sorted(current_backend.service_states.items())
                ),
                "running": current_backend.running_service_count(),
                "view_mode": current_backend.view_mode,
                "filter": current_backend._view.service_filter,
                "proc_filter": current_backend._view.procedure_filter,
                "selected_host": current_backend._view.selected_host_id,
                "selected_svc": current_backend._view.selected_service_key,
                "status_msg": current_backend.status_message,
                "diag_count": len(current_backend._diag_log),
                "active_proc": current_backend.active_procedure_id,
            }

        def _check_and_refresh() -> None:
            snap = _take_snapshot()
            if snap == _last_snapshot.get("snap"):
                return
            _last_snapshot["snap"] = snap
            status_label.set_text(current_backend.status_message)
            render_summary_cards.refresh()
            render_procedure_bar.refresh()
            render_main_view.refresh()

        ui.timer(_UI_REFRESH_INTERVAL, _check_and_refresh)


def _render_procedure_action_bar(
    current_backend: ControllerBackend,
    selected_for_procedure: set[tuple[str, str]],
    refresh_ui: Any,
) -> None:
    """Procedure lifecycle bar: Start / Add Services / Stop Procedure."""
    active = current_backend.active_procedure_id

    if active:
        # Active procedure indicator + Add Services + Stop Procedure
        proc_services = current_backend.procedure_services()
        with (
            ui.card()
            .classes("w-full rounded-lg p-4")
            .style(
                f"background: {_hex_to_rgba(BRAND_COLORS['green'], OPACITY['card_fill'])};"
                f" box-shadow: 0 2px 8px rgba(0,0,0,{OPACITY['shadow']});"
            )
        ):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.row().classes("items-center gap-3"):
                    ui.icon(ICONS["check"], color=BRAND_COLORS["green"]).classes(
                        "text-3xl"
                    )
                    with ui.column().classes("gap-0"):
                        ui.label("Active Procedure").classes("type-label text-gray-500")
                        ui.label(active).classes("type-h3 brand-heading mono")
                    ui.badge(
                        f"{len(proc_services)} service(s)",
                        color=BRAND_COLORS["blue"],
                    ).props("rounded").classes("text-sm")
                with ui.row().classes("gap-2"):

                    async def _add_services() -> None:
                        _open_service_selection_dialog(
                            current_backend,
                            selected_for_procedure,
                            refresh_ui,
                            mode="add",
                        )

                    async def _stop_proc() -> None:
                        await current_backend.stop_procedure()
                        refresh_ui()

                    ui.button("Add Services", icon=ICONS["start_all"]).props(
                        "unelevated color=primary"
                    ).on("click", _add_services)
                    ui.button("Stop Procedure", icon=ICONS["stop_all"]).props(
                        "unelevated color=negative"
                    ).on("click", _stop_proc)
    else:
        # No active procedure — show Start Procedure button
        with (
            ui.card()
            .classes("w-full rounded-lg p-4")
            .style(
                f"background: {_hex_to_rgba(BRAND_COLORS['blue'], OPACITY['card_fill'])};"
                f" box-shadow: 0 2px 8px rgba(0,0,0,{OPACITY['shadow']});"
            )
        ):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.row().classes("items-center gap-3"):
                    ui.icon(ICONS["service"], color=BRAND_COLORS["blue"]).classes(
                        "text-3xl"
                    )
                    ui.label("No active procedure").classes(
                        "type-body-lg text-gray-500"
                    )

                def _start_proc() -> None:
                    _open_service_selection_dialog(
                        current_backend,
                        selected_for_procedure,
                        refresh_ui,
                        mode="start",
                    )

                ui.button("Start Procedure", icon=ICONS["play"]).props(
                    "unelevated color=primary"
                ).on("click", _start_proc)


def _open_service_selection_dialog(
    current_backend: ControllerBackend,
    selected_for_procedure: set[tuple[str, str]],
    refresh_ui: Any,
    *,
    mode: str,
) -> None:
    """Open a dialog to select idle services for start/add procedure."""
    idle = current_backend.idle_services()
    selected_for_procedure.clear()

    async def _deploy() -> None:
        keys = list(selected_for_procedure)
        if not keys:
            dlg.close()
            return
        if mode == "start":
            proc_id = current_backend.generate_procedure_id()
            await current_backend.start_procedure(keys, proc_id)
        else:
            await current_backend.add_to_procedure(keys)
        selected_for_procedure.clear()
        dlg.close()
        refresh_ui()

    label = "Start Procedure" if mode == "start" else "Add to Procedure"
    with (
        ui.dialog() as dlg,
        ui.card()
        .classes("min-w-[36rem] max-w-[52rem] rounded-lg p-6 glass-panel")
        .style("box-shadow: 0 4px 24px rgba(0,0,0,0.25);"),
    ):
        ui.label(label).classes("type-h2 brand-heading")
        ui.label("Select services to deploy").classes("type-body-sm text-gray-500")
        ui.separator()
        if idle:
            # Tile grid — each service as a selectable card (like mini service view)
            tile_refs: dict[tuple[str, str], ui.card] = {}
            with (
                ui.element("div")
                .classes("w-full")
                .style(
                    "display: grid;"
                    " grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));"
                    " gap: 0.75rem; max-height: 50vh; overflow-y: auto;"
                    " padding: 0.25rem;"
                )
            ):
                for (host_id, service_id), catalog in idle:
                    display = getattr(catalog, "display_name", "") or service_id
                    key = (host_id, service_id)

                    def _make_toggle(
                        k: tuple[str, str] = key,
                    ) -> None:
                        if k in selected_for_procedure:
                            selected_for_procedure.discard(k)
                        else:
                            selected_for_procedure.add(k)
                        _refresh_tile_styles()

                    tile = (
                        ui.card()
                        .classes(
                            "cursor-pointer rounded-lg p-4 transition"
                            " hover:shadow-lg hover-elevate"
                        )
                        .style(
                            f"border-left: 4px solid {BRAND_COLORS['gray']};"
                            f" background: {_hex_to_rgba(BRAND_COLORS['gray'], OPACITY['tile_fill'])};"
                            " box-shadow: 0 2px 8px rgba(0,0,0,0.15);"
                        )
                        .on("click", _make_toggle)
                    )
                    tile_refs[key] = tile
                    with tile:
                        with ui.column().classes("gap-1 items-center"):
                            ui.icon(
                                ICONS["service"], color=BRAND_COLORS["gray"]
                            ).classes("text-3xl")
                            ui.label(display).classes(
                                "type-body brand-heading text-center"
                            )
                            ui.label(host_id).classes(
                                "type-body-sm text-gray-500 text-center"
                            )

            def _refresh_tile_styles() -> None:
                for k, card in tile_refs.items():
                    if k in selected_for_procedure:
                        card.style(
                            f"border-left: 4px solid {BRAND_COLORS['green']};"
                            f" background: {_hex_to_rgba(BRAND_COLORS['green'], OPACITY['card_fill_active'])};"
                            f" box-shadow: 0 0 0 2px {_hex_to_rgba(BRAND_COLORS['light_blue'], OPACITY['selection_glow'])},"
                            " 0 4px 12px rgba(0,0,0,0.22);"
                        )
                    else:
                        card.style(
                            f"border-left: 4px solid {BRAND_COLORS['gray']};"
                            f" background: {_hex_to_rgba(BRAND_COLORS['gray'], OPACITY['tile_fill'])};"
                            " box-shadow: 0 2px 8px rgba(0,0,0,0.15);"
                        )

        else:
            ui.label("No idle services available.").classes(
                "type-body-sm text-gray-500 italic"
            )
        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            ui.button("Cancel", on_click=dlg.close).props("flat")
            ui.button("Deploy", on_click=_deploy).props("unelevated color=primary")
    dlg.open()


def _render_summary_card(
    *,
    title: str,
    value: str,
    icon: str,
    color: str,
    active: bool,
    on_click: Any,
) -> None:
    fill_alpha = OPACITY["card_fill_active"] if active else OPACITY["card_fill"]
    glow_style = (
        f"box-shadow: 0 0 0 3px {_hex_to_rgba(BRAND_COLORS['light_blue'], OPACITY['selection_glow'])}, 0 2px 8px rgba(0,0,0,{OPACITY['shadow']});"
        if active
        else f"box-shadow: 0 2px 8px rgba(0,0,0,{OPACITY['shadow']});"
    )
    with (
        ui.card()
        .classes(
            "min-h-32 cursor-pointer rounded-lg p-5 transition hover:shadow-lg hover-elevate"
        )
        .style(f"background: {_hex_to_rgba(color, fill_alpha)}; {glow_style}")
        .on("click", on_click)
    ):
        with ui.row().classes("items-center gap-4"):
            ui.icon(icon, color=color).classes("text-5xl")
            with ui.column().classes("gap-0"):
                ui.label(title).classes(
                    "text-base uppercase tracking-wide text-gray-500 brand-heading"
                )
                ui.label(value).classes("text-4xl font-bold mono")


def _render_host_grid(current_backend: ControllerBackend, refresh_ui: Any) -> None:
    if not current_backend.hosts:
        create_empty_state("Searching for service hosts...", ICONS["dashboard"])
        return
    services_by_host = current_backend._services_by_host()
    with (
        ui.element("div")
        .classes("w-full")
        .style(
            "display: grid; grid-template-columns: repeat(auto-fill, minmax(21rem, 1fr)); gap: 1rem; align-content: start;"
        )
    ):
        for host_id, services in sorted(services_by_host.items()):
            _render_host_tile(current_backend, refresh_ui, host_id, services)
    # Detail pane below the grid for the selected host
    selected_host = current_backend._view.selected_host_id
    if selected_host and selected_host in services_by_host:
        _render_host_detail(
            current_backend, refresh_ui, selected_host, services_by_host[selected_host]
        )


def _render_service_grid(current_backend: ControllerBackend, refresh_ui: Any) -> None:
    visible_items = current_backend.visible_catalog_items()
    _TOOLBAR_BTN_STYLE = (
        f"box-shadow: 0 2px 8px rgba(0,0,0,{OPACITY['shadow']}); "
        f"min-width: 44px; min-height: 44px;"
    )
    with ui.column().classes("w-full gap-4"):
        with ui.row().classes("w-full items-center justify-between gap-3"):
            with ui.row().classes("gap-2 items-center flex-wrap"):
                # Procedure filter chips
                known_procs = current_backend.known_procedure_ids()
                if known_procs:
                    ui.label("Procedure:").classes("type-label text-gray-400")
                    for pid in [None] + known_procs:  # type: ignore[list-item]
                        label = "All" if pid is None else pid
                        active_proc = current_backend._view.procedure_filter == pid
                        ui.button(
                            label,
                            on_click=lambda p=pid: (
                                current_backend.set_procedure_filter(p),
                                refresh_ui(),
                            ),
                        ).props(
                            f"{'unelevated color=secondary' if active_proc else 'flat'} dense"
                        ).classes(
                            "text-xs"
                        )
            with ui.row().classes("gap-2"):
                for fval, ficon, ftip in [
                    ("ALL", ICONS["filter"], "All"),
                    ("RUNNING", ICONS["check"], "Running"),
                    ("STOPPED", ICONS["stop"], "Stopped"),
                    ("FAILED", ICONS["error"], "Failed"),
                ]:
                    active = current_backend._view.service_filter == fval
                    ui.button(
                        icon=ficon,
                        on_click=lambda v=fval: (
                            current_backend.show_services_view(v),
                            refresh_ui(),
                        ),
                    ).props(
                        f"{'unelevated color=primary' if active else 'flat'} round"
                    ).classes(
                        "text-xl"
                    ).style(
                        _TOOLBAR_BTN_STYLE
                    ).tooltip(
                        ftip
                    )
        if not visible_items:
            create_empty_state("No matching services", ICONS["service"])
        else:
            with (
                ui.element("div")
                .classes("w-full")
                .style(
                    "display: grid; grid-template-columns: repeat(auto-fill, minmax(19rem, 1fr)); gap: 1rem; align-content: start;"
                )
            ):
                for (host_id, service_id), catalog in sorted(visible_items):
                    status = current_backend.service_states.get((host_id, service_id))
                    _render_service_tile(
                        current_backend,
                        refresh_ui,
                        host_id,
                        service_id,
                        catalog,
                        status,
                        compact=False,
                    )
            # Detail pane below grid for selected service
            sel = current_backend._view.selected_service_key
            if sel:
                sel_catalog = current_backend.catalogs.get(sel)
                sel_status = current_backend.service_states.get(sel)
                if sel_catalog:
                    _render_service_detail(
                        current_backend,
                        sel[0],
                        sel[1],
                        sel_catalog,
                        sel_status,
                    )


_ACTION_BTN_STYLE = "min-width: 44px; min-height: 44px;"


def _render_host_tile(
    current_backend: ControllerBackend,
    refresh_ui: Any,
    host_id: str,
    services: dict[str, Orchestration.ServiceCatalog],
) -> None:
    selected = current_backend._view.selected_host_id == host_id
    fill_alpha = OPACITY["card_fill_active"] if selected else OPACITY["tile_fill"]
    glow_style = (
        f"box-shadow: 0 0 0 3px {_hex_to_rgba(BRAND_COLORS['light_blue'], OPACITY['selection_glow'])}, 0 4px 12px rgba(0,0,0,0.22);"
        if selected
        else "box-shadow: 0 2px 10px rgba(0,0,0,0.18);"
    )
    # When selected, span the full grid row so tiles reflow below
    card_style = (
        f"background: {_hex_to_rgba(BRAND_COLORS['blue'], fill_alpha)}; {glow_style}"
    )
    with (
        ui.card()
        .classes(
            "w-full rounded-lg p-6 transition cursor-pointer hover:shadow-lg hover-elevate"
        )
        .style(card_style)
        .on(
            "click",
            lambda hid=host_id: (current_backend.select_host(hid), refresh_ui()),
        )
    ):
        # --- Collapsed: icon + name + badge, centered row of action buttons ---
        with ui.column().classes("w-full items-center gap-3"):
            with ui.row().classes("items-center gap-3"):
                ui.icon(ICONS["host"], color=BRAND_COLORS["blue"]).classes("text-4xl")
                ui.label(host_id).classes("type-h3 brand-heading")
                ui.badge(str(len(services)), color=BRAND_COLORS["orange"]).props(
                    "rounded"
                ).classes("text-base").style(
                    "min-width: 28px; min-height: 28px; font-weight: 700;"
                    " display: inline-flex; align-items: center; justify-content: center;"
                )
            with ui.row().classes("gap-2"):

                async def _caps_click(hid: str = host_id) -> None:
                    await _host_action_notify(current_backend, "capabilities", hid)

                async def _health_click(hid: str = host_id) -> None:
                    await _host_action_notify(current_backend, "health", hid)

                ui.button(icon=ICONS["capabilities"]).props("flat round").classes(
                    "text-xl"
                ).style(_ACTION_BTN_STYLE).tooltip("Capabilities").on(
                    "click.stop",
                    _caps_click,
                )
                ui.button(icon=ICONS["health"]).props("flat round").classes(
                    "text-xl"
                ).style(_ACTION_BTN_STYLE).tooltip("Health").on(
                    "click.stop",
                    _health_click,
                )


def _service_state_color(status: Orchestration.ServiceStatus | None) -> str:
    if status is None:
        return _SERVICE_STATE_COLORS["UNKNOWN"]
    return _SERVICE_STATE_COLORS.get(
        _state_name(status.state).upper(), _SERVICE_STATE_COLORS["UNKNOWN"]
    )


def _render_service_tile(
    current_backend: ControllerBackend,
    refresh_ui: Any,
    host_id: str,
    service_id: str,
    catalog: Orchestration.ServiceCatalog,
    status: Orchestration.ServiceStatus | None,
    *,
    compact: bool,
) -> None:
    selected = current_backend._view.selected_service_key == (host_id, service_id)
    state_name = _state_name(status.state) if status is not None else "UNKNOWN"
    is_running = state_name.upper() in ("RUNNING", "STARTING")
    action_type = "update" if is_running else "start"
    border_color = _service_state_color(status)
    fill_alpha = OPACITY["card_fill_active"] if selected else OPACITY["tile_fill"]
    background_color = _hex_to_rgba(border_color, fill_alpha)
    glow_style = (
        f"box-shadow: 0 0 0 3px {_hex_to_rgba(BRAND_COLORS['light_blue'], OPACITY['selection_glow'])}, 0 4px 12px rgba(0,0,0,0.22);"
        if selected
        else "box-shadow: 0 2px 10px rgba(0,0,0,0.18);"
    )

    def _on_tile_click(hid: str = host_id, sid: str = service_id) -> None:
        if compact:
            current_backend.toggle_service_selection(hid, sid)
        else:
            current_backend.select_service(hid, sid)
        refresh_ui()

    # When selected, span the full grid row so tiles reflow below
    card_style = f"border-left: 6px solid {border_color}; background: {background_color}; {glow_style}"
    with (
        ui.card()
        .classes(
            "w-full rounded-lg p-5 transition cursor-pointer hover:shadow-lg hover-elevate"
        )
        .style(card_style)
        .on("click", _on_tile_click)
    ):
        # --- Collapsed: centered icon + name, centered action row ---
        with ui.column().classes("w-full items-center gap-3"):
            with ui.row().classes("items-center gap-3"):
                ui.icon(ICONS["service"], color=border_color).classes("text-4xl")
                display = getattr(catalog, "display_name", "") or service_id
                ui.label(display).classes("type-h3 brand-heading")
            with ui.row().classes("gap-2"):
                is_stopped = state_name.upper() in ("STOPPED", "FAILED", "UNKNOWN")

                async def _start_click(
                    hid: str = host_id, sid: str = service_id
                ) -> None:
                    await current_backend.start_service(hid, sid)
                    refresh_ui()

                async def _configure_click(
                    hid: str = host_id, sid: str = service_id
                ) -> None:
                    await _open_service_config_dialog(
                        current_backend, action_type, hid, sid, refresh_ui
                    )

                async def _stop_click(
                    hid: str = host_id, sid: str = service_id
                ) -> None:
                    await _service_action(
                        current_backend.stop_service(hid, sid), refresh_ui
                    )

                if is_stopped:
                    ui.button(icon=ICONS["play"]).props(
                        "flat round color=primary"
                    ).classes("text-xl").style(_ACTION_BTN_STYLE).tooltip("Start").on(
                        "click.stop",
                        _start_click,
                    )
                if is_running:
                    ui.button(icon=ICONS["stop"]).props(
                        "flat round color=negative"
                    ).classes("text-xl").style(_ACTION_BTN_STYLE).tooltip("Stop").on(
                        "click.stop",
                        _stop_click,
                    )
                    gui_url = _catalog_property(catalog, "gui_url")
                    if gui_url:
                        ui.button("Open").props(
                            "unelevated color=positive dense"
                        ).classes("text-xs").tooltip(gui_url).on(
                            "click.stop",
                            lambda u=gui_url: ui.navigate.to(u, new_tab=True),
                        )
                ui.button(icon=ICONS["update"]).props("flat round").classes(
                    "text-xl"
                ).style(_ACTION_BTN_STYLE).tooltip("Configure").on(
                    "click.stop",
                    _configure_click,
                )


def _render_host_detail(
    current_backend: ControllerBackend,
    refresh_ui: Any,
    host_id: str,
    services: dict[str, Orchestration.ServiceCatalog],
) -> None:
    """Detail pane rendered below the host grid for the selected host."""
    with (
        ui.card()
        .classes("w-full rounded-lg p-5")
        .style(
            f"background: {_hex_to_rgba(BRAND_COLORS['blue'], OPACITY['card_fill'])};"
            f" box-shadow: 0 2px 10px rgba(0,0,0,0.18);"
        )
    ):
        ui.label(f"{host_id} — Services").classes(
            "text-lg font-bold brand-heading mb-2"
        )
        with (
            ui.element("div")
            .classes("w-full")
            .style(
                "display: grid; grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr)); gap: 0.75rem;"
            )
        ):
            for service_id, catalog in sorted(services.items()):
                status = current_backend.service_states.get((host_id, service_id))
                _render_service_tile(
                    current_backend,
                    refresh_ui,
                    host_id,
                    service_id,
                    catalog,
                    status,
                    compact=True,
                )


def _render_service_detail(
    current_backend: ControllerBackend,
    host_id: str,
    service_id: str,
    catalog: Orchestration.ServiceCatalog,
    status: Orchestration.ServiceStatus | None,
) -> None:
    """Detail pane rendered below the service grid for the selected service."""
    state_name = _state_name(status.state) if status is not None else "UNKNOWN"
    border_color = _service_state_color(status)
    with (
        ui.card()
        .classes("w-full rounded-lg p-5")
        .style(
            f"border-left: 6px solid {border_color};"
            f" background: {_hex_to_rgba(border_color, OPACITY['card_fill'])};"
            f" box-shadow: 0 2px 10px rgba(0,0,0,0.18);"
        )
    ):
        display = getattr(catalog, "display_name", "") or service_id
        with ui.row().classes("w-full items-center gap-4"):
            create_status_chip(state_name)
            ui.label(display).classes("type-h3 brand-heading")
        with ui.column().classes("gap-1 mt-2"):
            ui.label(f"Host: {host_id}").classes("type-body-lg brand-heading")
            health = getattr(catalog, "health_summary", "") or ""
            if health:
                ui.label(health).classes("type-body text-gray-500")


def _render_diagnostics_view(current_backend: ControllerBackend) -> None:
    log_view = ui.log(max_lines=200).classes("w-full h-96 mono")
    for entry in current_backend._diag_log:
        log_view.push(entry)
    if not current_backend._diag_log:
        log_view.push(
            "No diagnostic events yet. Actions and state changes will appear here."
        )


async def _host_action_notify(
    current_backend: ControllerBackend,
    action_type: str,
    host_id: str,
) -> None:
    """Flash host capabilities or health as a notification."""
    if action_type == "capabilities":
        result = await current_backend.host_capabilities(host_id)
    else:
        result = await current_backend.host_health(host_id)
    ui.notify(
        f"{action_type.capitalize()} — {host_id}\n{result}",
        type="info",
        position="top",
        close_button="Dismiss",
        timeout=8000,
    )


async def _open_service_config_dialog(
    current_backend: ControllerBackend,
    action_type: str,
    host_id: str,
    service_id: str,
    refresh_ui: Any,
) -> None:
    """Open a property-driven config dialog for start/update service RPC.

    Reads ``PropertyDescriptor`` entries from the cached
    ``ServiceCatalog.properties`` so the user sees named fields with
    current/default values instead of a freeform text area.
    """
    catalog = current_backend.catalogs.get((host_id, service_id))
    descriptors: list = []
    if catalog is not None:
        descriptors = list(getattr(catalog, "properties", None) or [])

    # Mutable dict holding the live input values keyed by property name.
    field_values: dict[str, str] = {}
    for desc in descriptors:
        name = getattr(desc, "name", "")
        current = getattr(desc, "current_value", "") or ""
        default = getattr(desc, "default_value", None) or ""
        field_values[name] = current if current else default

    async def _submit() -> None:
        properties: list = []
        for desc in descriptors:
            name = getattr(desc, "name", "")
            value = field_values.get(name, "")
            if value:
                properties.append(Orchestration.ServiceProperty(name=name, value=value))
        if action_type == "update":
            await current_backend.update_service(
                host_id, service_id, properties or None
            )
        else:
            await current_backend.start_service(host_id, service_id)
        dlg.close()
        refresh_ui()

    submit_label = "Update" if action_type == "update" else "Start"
    with (
        ui.dialog() as dlg,
        ui.card()
        .classes("min-w-[28rem] rounded-lg p-6 glass-panel")
        .style("box-shadow: 0 4px 24px rgba(0,0,0,0.25);"),
    ):
        ui.label("Configure Service").classes("type-h2 brand-heading")
        ui.label(f"{service_id} on {host_id}").classes("type-body-sm text-gray-500")
        ui.separator()

        if descriptors:
            for desc in descriptors:
                name = getattr(desc, "name", "")
                description = getattr(desc, "description", "") or ""
                required = getattr(desc, "required", False)
                label_text = f"{name} *" if required else name

                inp = (
                    ui.input(
                        label=label_text,
                        value=field_values.get(name, ""),
                        placeholder=getattr(desc, "default_value", None) or "",
                    )
                    .classes("w-full mono")
                    .props("outlined dense")
                )
                if description:
                    inp.tooltip(description)
                inp.on_value_change(
                    lambda e, n=name: field_values.__setitem__(n, e.value)
                )
        else:
            ui.label("No configurable properties advertised.").classes(
                "type-body-sm text-gray-500 italic"
            )

        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            ui.button("Cancel", on_click=dlg.close).props("flat")
            ui.button(submit_label, on_click=_submit).props("unelevated color=primary")
    dlg.open()


async def _host_action(action: Any, refresh_ui: Any) -> None:
    await action
    refresh_ui()


async def _service_action(action: Any, refresh_ui: Any) -> None:
    await action
    refresh_ui()


async def _service_bulk_action(action: Any, refresh_ui: Any) -> None:
    await action
    refresh_ui()


def main() -> None:
    global _room_nav_instance
    storage_secret = os.environ.get(
        NICEGUI_STORAGE_SECRET_ENV, NICEGUI_STORAGE_SECRET_DEFAULT
    )

    from medtech.gui._theme import _resource_dir

    favicon_path = _resource_dir() / "images" / "favicon.ico"

    room_id = os.environ.get("ROOM_ID", "") or "OR-1"

    # Set GUI URLs on the backend for ServiceCatalog advertisement
    global backend
    backend = ControllerBackend(room_id=room_id)
    current_backend = backend
    ctrl_self_url = os.environ.get("MEDTECH_GUI_EXTERNAL_URL", "")
    if ctrl_self_url:
        current_backend._gui_url = f"{ctrl_self_url.rstrip('/')}/controller/{room_id}"
    procedure_id = os.environ.get("PROCEDURE_ID", "")
    if procedure_id:
        current_backend._default_procedure_id = procedure_id

    from surgical_procedure.room_nav import RoomNav

    _room_nav_instance = RoomNav(room_id)

    # Register self so the pill always shows the current page as selected.
    ctrl_self_url = os.environ.get("MEDTECH_GUI_EXTERNAL_URL", "")
    if ctrl_self_url:
        _room_nav_instance.add_static_sibling(
            "Procedure Controller", f"{ctrl_self_url.rstrip('/')}/controller"
        )

    app.on_startup(_room_nav_instance.start)
    app.on_shutdown(_room_nav_instance.close)

    try:
        ui.run(
            root=controller_page,
            storage_secret=storage_secret,
            reload=False,
            title="Procedure Controller — Medtech Suite",
            favicon=str(favicon_path) if favicon_path.is_file() else None,
        )
    except KeyboardInterrupt:
        pass


ProcedureController = ControllerBackend


def _rpc_in_type(op_name: str):
    """Look up the In struct type for an RPC operation by name."""
    ct = Orchestration.ServiceHostControl.call_type
    for _hash, (name, cls) in ct.in_structs.items():
        if name == op_name:
            return cls
    raise ValueError(f"Unknown RPC operation: {op_name}")


def _make_start_call(
    service_id: str, properties: list[tuple[str, str]] | None = None
) -> object:
    call_type = Orchestration.ServiceHostControl.call_type
    call = call_type()
    _in = _rpc_in_type("start_service")()
    svc_props = []
    for name, value in properties or []:
        svc_props.append(Orchestration.ServiceProperty(name=name, value=value))
    _in.req = Orchestration.ServiceRequest(service_id=service_id, properties=svc_props)
    call.start_service = _in
    return call


def _make_stop_call(service_id: str) -> object:
    call_type = Orchestration.ServiceHostControl.call_type
    call = call_type()
    _in = _rpc_in_type("stop_service")()
    _in.service_id = service_id
    call.stop_service = _in
    return call


def _make_get_capabilities_call() -> object:
    call_type = Orchestration.ServiceHostControl.call_type
    call = call_type()
    call.get_capabilities = _rpc_in_type("get_capabilities")()
    return call


def _make_get_health_call() -> object:
    call_type = Orchestration.ServiceHostControl.call_type
    call = call_type()
    call.get_health = _rpc_in_type("get_health")()
    return call


def _make_update_call(service_id: str, properties: list | None = None) -> object:
    call_type = Orchestration.ServiceHostControl.call_type
    call = call_type()
    _in = _rpc_in_type("update_service")()
    _in.req = Orchestration.ServiceRequest(
        service_id=service_id, properties=properties or []
    )
    call.update_service = _in
    return call


def _extract_rpc_result(reply: object, op_name: str) -> str:
    try:
        branch = getattr(reply, op_name)
        result = branch.result.return_
        if op_name in {"start_service", "stop_service"}:
            return f"{result.code} - {result.message}"
        if op_name == "get_capabilities":
            return f"capacity={result.capacity}"
        if op_name == "get_health":
            return f"alive={result.alive}, summary={result.summary}"
        return str(result)
    except Exception as exc:
        return f"parse error: {exc}"


def _catalog_property(catalog: Orchestration.ServiceCatalog, name: str) -> str:
    """Return the current_value of a named PropertyDescriptor, or '' if absent."""
    for prop in getattr(catalog, "properties", None) or []:
        if getattr(prop, "name", None) == name:
            return getattr(prop, "current_value", "") or ""
    return ""


def _state_name(state: Orchestration.ServiceState) -> str:
    names = {
        Orchestration.ServiceState.STOPPED: "STOPPED",
        Orchestration.ServiceState.STARTING: "STARTING",
        Orchestration.ServiceState.RUNNING: "RUNNING",
        Orchestration.ServiceState.STOPPING: "STOPPING",
        Orchestration.ServiceState.FAILED: "FAILED",
        Orchestration.ServiceState.UNKNOWN: "UNKNOWN",
    }
    return names.get(state, f"?({int(state)})")


__all__ = [
    "ControllerBackend",
    "ProcedureController",
    "backend",
    "controller_content",
    "controller_page",
    "main",
    "_make_get_capabilities_call",
    "_make_get_health_call",
    "_make_start_call",
    "_make_stop_call",
    "_make_update_call",
]
