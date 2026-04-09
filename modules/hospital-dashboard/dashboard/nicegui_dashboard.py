"""Hospital Dashboard — NiceGUI web application for facility-wide monitoring.

The dashboard subscribes to the Hospital domain and renders procedure status,
patient vitals, clinical alerts, robot state, and resource availability in a
browser-based UI.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

import app_names
import rti.asyncio  # noqa: F401 - enables async DDS methods
import rti.connextdds as dds
import surgery
from medtech.dds import initialize_connext
from medtech.gui import (
    BRAND_COLORS,
    ICONS,
    NICEGUI_STORAGE_SECRET_ENV,
    GuiBackend,
    create_empty_state,
    create_header,
    create_section_header,
    create_stat_card,
    create_status_chip,
    init_theme,
)
from medtech.log import ModuleName, init_logging
from nicegui import background_tasks, ui

dash_names = app_names.MedtechEntityNames.HospitalDashboard

log = init_logging(ModuleName.HOSPITAL_DASHBOARD)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _nested_text(value: Any, *attributes: str) -> str:
    current = value
    for attribute in attributes:
        if current is None:
            return ""
        current = getattr(current, attribute, None)
    return _text(current)


def _phase_text(phase_value: Any) -> str:
    phase_map = {
        int(surgery.Surgery.ProcedurePhase.UNKNOWN): "Unknown",
        int(surgery.Surgery.ProcedurePhase.PRE_OP): "Pre-Op",
        int(surgery.Surgery.ProcedurePhase.IN_PROGRESS): "In Progress",
        int(surgery.Surgery.ProcedurePhase.COMPLETING): "Completing",
        int(surgery.Surgery.ProcedurePhase.COMPLETED): "Completed",
        int(surgery.Surgery.ProcedurePhase.ALERT): "Alert",
    }
    return phase_map.get(int(phase_value), "Unknown")


def _phase_color(phase_value: Any) -> str:
    phase_map = {
        int(surgery.Surgery.ProcedurePhase.PRE_OP): BRAND_COLORS["blue"],
        int(surgery.Surgery.ProcedurePhase.IN_PROGRESS): BRAND_COLORS["green"],
        int(surgery.Surgery.ProcedurePhase.COMPLETING): BRAND_COLORS["amber"],
        int(surgery.Surgery.ProcedurePhase.COMPLETED): BRAND_COLORS["light_gray"],
        int(surgery.Surgery.ProcedurePhase.ALERT): BRAND_COLORS["red"],
    }
    return phase_map.get(int(phase_value), BRAND_COLORS["gray"])


@dataclass
class ProcedureEntry:
    procedure_id: str
    room: str = ""
    patient_name: str = ""
    procedure_type: str = ""
    surgeon: str = ""
    phase: str = "Unknown"
    phase_color: str = BRAND_COLORS["gray"]
    status_message: str = ""
    vitals: dict[str, Any] = field(default_factory=dict)
    robot_state: str = "Unknown"
    robot_color: str = BRAND_COLORS["gray"]
    resource_name: str = ""
    resource_kind: str = ""
    resource_status: str = ""
    resource_location: str = ""


@dataclass
class AlertEntry:
    alert_id: str
    severity: str
    room: str
    patient_name: str
    category: str
    message: str
    highlighted: bool = False
    visible: bool = True


@dataclass
class ResourceEntry:
    name: str
    kind: str
    status: str
    location: str


class DashboardBackend(GuiBackend):
    """NiceGUI backend that owns the Hospital dashboard DDS resources."""

    def __init__(
        self,
        *,
        procedure_status_reader: dds.DataReader | None = None,
        procedure_context_reader: dds.DataReader | None = None,
        patient_vitals_reader: dds.DataReader | None = None,
        alarm_messages_reader: dds.DataReader | None = None,
        robot_state_reader: dds.DataReader | None = None,
        clinical_alert_reader: dds.DataReader | None = None,
        resource_availability_reader: dds.DataReader | None = None,
    ) -> None:
        self.procedures: dict[str, ProcedureEntry] = {}
        self.alerts: list[AlertEntry] = []
        self.resources: dict[str, ResourceEntry] = {}
        self.selected_procedure_id: str = ""
        self.severity_filter: str = "ALL"
        self.room_filter: str = "ALL"
        self._patient_to_procedure: dict[str, str] = {}
        self._tasks: list[asyncio.Task[Any]] = []
        self._participant: dds.DomainParticipant | None = None
        self._running = False

        self._procedure_status_reader = procedure_status_reader
        self._procedure_context_reader = procedure_context_reader
        self._patient_vitals_reader = patient_vitals_reader
        self._alarm_messages_reader = alarm_messages_reader
        self._robot_state_reader = robot_state_reader
        self._clinical_alert_reader = clinical_alert_reader
        self._resource_reader = resource_availability_reader

        if not self._all_readers_injected:
            self._init_dds()

        super().__init__()

    @property
    def name(self) -> str:
        return "HospitalDashboard"

    @property
    def _all_readers_injected(self) -> bool:
        return all(
            reader is not None
            for reader in (
                self._procedure_status_reader,
                self._procedure_context_reader,
                self._patient_vitals_reader,
                self._alarm_messages_reader,
                self._robot_state_reader,
                self._clinical_alert_reader,
                self._resource_reader,
            )
        )

    def _init_dds(self) -> None:
        initialize_connext()
        provider = dds.QosProvider.default
        participant = provider.create_participant_from_config(
            dash_names.HOSPITAL_DASHBOARD
        )
        if participant is None:
            raise RuntimeError("Failed to create Hospital dashboard participant")

        qos = participant.qos
        qos.partition.name = ["room/*/procedure/*"]
        participant.qos = qos
        participant.enable()
        self._participant = participant

        def _find_reader(entity_name: str) -> dds.DataReader:
            reader = participant.find_datareader(entity_name)
            if reader is None:
                raise RuntimeError(f"Reader not found: {entity_name}")
            return dds.DataReader(reader)

        self._procedure_status_reader = _find_reader(dash_names.PROCEDURE_STATUS_READER)
        self._procedure_context_reader = _find_reader(
            dash_names.PROCEDURE_CONTEXT_READER
        )
        self._patient_vitals_reader = _find_reader(dash_names.PATIENT_VITALS_READER)
        self._alarm_messages_reader = _find_reader(dash_names.ALARM_MESSAGES_READER)
        self._robot_state_reader = _find_reader(dash_names.ROBOT_STATE_READER)
        self._clinical_alert_reader = _find_reader(dash_names.CLINICAL_ALERT_READER)
        self._resource_reader = _find_reader(dash_names.RESOURCE_AVAILABILITY_READER)

    async def start(self) -> None:
        self._running = True
        self._tasks = [
            background_tasks.create(self._receive_procedure_status()),
            background_tasks.create(self._receive_procedure_context()),
            background_tasks.create(self._receive_patient_vitals()),
            background_tasks.create(self._receive_alarm_messages()),
            background_tasks.create(self._receive_robot_state()),
            background_tasks.create(self._receive_clinical_alerts()),
            background_tasks.create(self._receive_resource_availability()),
        ]
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

        for reader_name in (
            "_procedure_status_reader",
            "_procedure_context_reader",
            "_patient_vitals_reader",
            "_alarm_messages_reader",
            "_robot_state_reader",
            "_clinical_alert_reader",
            "_resource_reader",
        ):
            reader = getattr(self, reader_name, None)
            if reader is None:
                continue
            try:
                reader.close()
            except Exception:
                log.exception("Error closing %s", reader_name)

        if self._participant is not None:
            try:
                self._participant.close()
            except Exception:
                log.exception("Error closing Hospital dashboard participant")
            self._participant = None
            log.notice("Hospital dashboard participant closed")

        await rti.asyncio.close()

    def _get_or_create_procedure(self, procedure_id: str) -> ProcedureEntry:
        entry = self.procedures.get(procedure_id)
        if entry is None:
            entry = ProcedureEntry(procedure_id=procedure_id)
            self.procedures[procedure_id] = entry
            if not self.selected_procedure_id:
                self.selected_procedure_id = procedure_id
        return entry

    def update_procedure_status(self, sample: Any) -> None:
        procedure_id = _text(getattr(sample, "procedure_id", ""))
        entry = self._get_or_create_procedure(procedure_id)
        phase_value = getattr(sample, "phase", 0)
        entry.phase = _phase_text(phase_value)
        entry.phase_color = _phase_color(phase_value)
        entry.status_message = _text(getattr(sample, "status_message", ""))

    def update_procedure_context(self, sample: Any) -> None:
        procedure_id = _text(getattr(sample, "procedure_id", ""))
        entry = self._get_or_create_procedure(procedure_id)
        entry.room = _text(getattr(sample, "room", ""))
        entry.patient_name = _nested_text(sample, "patient", "name")
        entry.procedure_type = _text(getattr(sample, "procedure_type", ""))
        entry.surgeon = _text(getattr(sample, "surgeon", ""))
        patient_id = _nested_text(sample, "patient", "id")
        if patient_id:
            self._patient_to_procedure[patient_id] = procedure_id

    def update_patient_vitals(self, sample: Any) -> None:
        patient_id = _text(getattr(sample, "patient_id", ""))
        procedure_id = self._patient_to_procedure.get(patient_id, patient_id)
        entry = self._get_or_create_procedure(procedure_id)
        entry.vitals = {
            "heart_rate": getattr(sample, "heart_rate", None),
            "spo2": getattr(sample, "spo2", None),
            "systolic_bp": getattr(sample, "systolic_bp", None),
            "diastolic_bp": getattr(sample, "diastolic_bp", None),
        }

    def update_alarm_message(self, sample: Any) -> None:
        procedure_id = _text(getattr(sample, "procedure_id", ""))
        entry = self._get_or_create_procedure(procedure_id)
        entry.status_message = _text(getattr(sample, "message", ""))

    def update_robot_state(self, sample: Any) -> None:
        procedure_id = _text(getattr(sample, "procedure_id", ""))
        entry = self._get_or_create_procedure(procedure_id)
        mode = _text(getattr(sample, "mode", getattr(sample, "state", ""))) or "Unknown"
        entry.robot_state = mode
        entry.robot_color = {
            "OPERATIONAL": BRAND_COLORS["green"],
            "E-STOP": BRAND_COLORS["red"],
            "EMERGENCY_STOP": BRAND_COLORS["red"],
            "PAUSED": BRAND_COLORS["amber"],
            "IDLE": BRAND_COLORS["gray"],
            "DISCONNECTED": BRAND_COLORS["light_gray"],
        }.get(mode.upper(), BRAND_COLORS["gray"])

    def update_clinical_alert(self, sample: Any) -> None:
        severity = _text(getattr(sample, "severity", "UNKNOWN")) or "UNKNOWN"
        alert = AlertEntry(
            alert_id=_text(getattr(sample, "alert_id", "")),
            severity=severity,
            room=_text(getattr(sample, "room", "")),
            patient_name=_nested_text(sample, "patient", "name"),
            category=_text(getattr(sample, "category", "")),
            message=_text(getattr(sample, "message", "")),
        )
        self.alerts.insert(0, alert)
        if severity.upper() == "CRITICAL":
            alert.highlighted = True
            ui.notification(alert.message or "CRITICAL alert", type="negative")

    def update_resource_availability(self, sample: Any) -> None:
        resource = ResourceEntry(
            name=_text(getattr(sample, "name", getattr(sample, "resource_name", ""))),
            kind=_text(getattr(sample, "kind", getattr(sample, "resource_kind", ""))),
            status=_text(
                getattr(sample, "status", getattr(sample, "availability_status", ""))
            ),
            location=_text(getattr(sample, "location", "")),
        )
        self.resources[resource.name or resource.kind] = resource

    async def _receive_procedure_status(self) -> None:
        async for sample in self._procedure_status_reader.take_data_async():
            self.update_procedure_status(sample)

    async def _receive_procedure_context(self) -> None:
        async for sample in self._procedure_context_reader.take_data_async():
            self.update_procedure_context(sample)

    async def _receive_patient_vitals(self) -> None:
        async for sample in self._patient_vitals_reader.take_data_async():
            self.update_patient_vitals(sample)

    async def _receive_alarm_messages(self) -> None:
        async for sample in self._alarm_messages_reader.take_data_async():
            self.update_alarm_message(sample)

    async def _receive_robot_state(self) -> None:
        async for sample in self._robot_state_reader.take_data_async():
            self.update_robot_state(sample)

    async def _receive_clinical_alerts(self) -> None:
        async for sample in self._clinical_alert_reader.take_data_async():
            self.update_clinical_alert(sample)

    async def _receive_resource_availability(self) -> None:
        async for sample in self._resource_reader.take_data_async():
            self.update_resource_availability(sample)

    def filtered_alerts(self) -> list[AlertEntry]:
        alerts = list(self.alerts)
        if self.severity_filter != "ALL":
            alerts = [
                alert
                for alert in alerts
                if alert.severity.upper() == self.severity_filter
            ]
        if self.room_filter != "ALL":
            alerts = [alert for alert in alerts if alert.room == self.room_filter]
        return alerts


backend: DashboardBackend | Any | None = None


def _current_backend() -> DashboardBackend:
    global backend
    if backend is None:
        backend = DashboardBackend()
    return backend


def _procedure_cards() -> list[ProcedureEntry]:
    current_backend = _current_backend()
    return sorted(
        current_backend.procedures.values(),
        key=lambda entry: (entry.room or entry.procedure_id, entry.procedure_id),
    )


@ui.page("/dashboard", dark=True)
def dashboard_page() -> None:
    """Render the hospital dashboard page (full-page with header)."""
    init_theme()
    create_header(title="Hospital Dashboard")
    dashboard_content()


def dashboard_content() -> None:
    """Render dashboard content.  Call this from the SPA shell's sub_pages."""

    current_backend = _current_backend()

    with ui.column().classes("w-full gap-4 p-4"):
        with ui.splitter().classes("w-full h-[44rem]") as splitter:
            with splitter.before:
                with ui.column().classes("w-full gap-3"):
                    create_section_header("Active Procedures", ICONS["procedures"])

                    @ui.refreshable
                    def render_procedure_list() -> None:
                        if not current_backend.procedures:
                            create_empty_state("Waiting for procedure data…")
                            return
                        for entry in _procedure_cards():
                            with ui.card().classes("w-full gap-1 p-4"):
                                with ui.row().classes("w-full items-center gap-2"):
                                    create_status_chip(entry.phase)
                                    ui.label(entry.room or entry.procedure_id).classes(
                                        "text-lg font-bold"
                                    )
                                    ui.space()
                                    ui.label(entry.phase).classes("text-sm")
                                ui.label(
                                    f"Patient: {entry.patient_name or '—'}"
                                ).classes("text-sm text-gray-500")
                                ui.label(
                                    f"Type: {entry.procedure_type or '—'}"
                                ).classes("text-sm text-gray-500")
                                ui.label(f"Surgeon: {entry.surgeon or '—'}").classes(
                                    "text-sm text-gray-500"
                                )

                    render_procedure_list()

            with splitter.after:
                with ui.column().classes("w-full gap-3"):
                    create_section_header("Detail Panel", ICONS["vitals"])
                    ui.tabs().classes("w-full")
                    with ui.tab_panels().classes("w-full"):
                        with ui.tab_panel("Vitals"):
                            create_stat_card(
                                "—", "Heart Rate", ICONS["vitals"], BRAND_COLORS["blue"]
                            )
                            ui.echart({"series": []}).classes("w-full h-48")
                        with ui.tab_panel("Robot"):
                            create_stat_card(
                                "Unknown",
                                "Robot State",
                                ICONS["robot"],
                                BRAND_COLORS["green"],
                            )
                        with ui.tab_panel("Resources"):
                            create_stat_card(
                                "0",
                                "Resources",
                                ICONS["dashboard"],
                                BRAND_COLORS["orange"],
                            )

        with ui.row().classes("w-full items-center gap-3"):
            ui.select(
                ["ALL", "INFO", "WARNING", "CRITICAL"],
                value=current_backend.severity_filter,
                label="Severity",
            )
            ui.select(
                ["ALL"],
                value=current_backend.room_filter,
                label="Room",
            )

        create_section_header("Alert Feed", ICONS["alerts"])

        @ui.refreshable
        def render_alert_feed() -> None:
            alerts = current_backend.filtered_alerts()
            if not alerts:
                create_empty_state("No alerts")
                return
            with ui.scroll_area().classes("w-full h-72"):
                for alert in alerts:
                    with ui.card().classes("w-full gap-1 p-3"):
                        ui.label(f"{alert.severity} · {alert.room or '—'}").classes(
                            "font-bold"
                        )
                        ui.label(alert.patient_name or "—").classes("text-sm")
                        ui.label(alert.category or "").classes("text-xs text-gray-500")
                        ui.label(alert.message or "").classes("text-sm")

        render_alert_feed()

        ui.timer(
            0.5, lambda: (render_procedure_list.refresh(), render_alert_feed.refresh())
        )


def main() -> None:
    storage_secret = os.environ.get(NICEGUI_STORAGE_SECRET_ENV)
    if not storage_secret:
        raise RuntimeError(
            f"{NICEGUI_STORAGE_SECRET_ENV} must be set before starting the dashboard"
        )

    _current_backend()
    try:
        ui.run(
            root=dashboard_page,
            storage_secret=storage_secret,
            reload=False,
        )
    except KeyboardInterrupt:
        pass


HospitalDashboard = DashboardBackend


__all__ = [
    "AlertEntry",
    "DashboardBackend",
    "HospitalDashboard",
    "ProcedureEntry",
    "ResourceEntry",
    "backend",
    "dashboard_content",
    "dashboard_page",
    "main",
]
