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
    NICEGUI_STORAGE_SECRET_DEFAULT,
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

_LIVELINESS_POLL_INTERVAL = 0.5  # seconds — same cadence as digital twin


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


def _robot_mode_label(mode_value: Any) -> str:
    """Map a ``Surgery.RobotMode`` enum integer to a STATUS_COLORS-compatible string."""
    if isinstance(mode_value, str):
        return mode_value
    _map = {
        int(surgery.Surgery.RobotMode.OPERATIONAL): "OPERATIONAL",
        int(surgery.Surgery.RobotMode.EMERGENCY_STOP): "E-STOP",
        int(surgery.Surgery.RobotMode.PAUSED): "PAUSED",
        int(surgery.Surgery.RobotMode.IDLE): "IDLE",
        int(surgery.Surgery.RobotMode.UNKNOWN): "UNKNOWN",
    }
    return _map.get(int(mode_value), "UNKNOWN")


def _robot_mode_color(mode_value: Any) -> str:
    """Map a ``Surgery.RobotMode`` value (int or str) to a brand color hex."""
    if isinstance(mode_value, str):
        return {
            "OPERATIONAL": BRAND_COLORS["green"],
            "E-STOP": BRAND_COLORS["red"],
            "EMERGENCY_STOP": BRAND_COLORS["red"],
            "PAUSED": BRAND_COLORS["amber"],
            "IDLE": BRAND_COLORS["gray"],
            "DISCONNECTED": BRAND_COLORS["light_gray"],
        }.get(str(mode_value).upper(), BRAND_COLORS["gray"])
    _map = {
        int(surgery.Surgery.RobotMode.OPERATIONAL): BRAND_COLORS["green"],
        int(surgery.Surgery.RobotMode.EMERGENCY_STOP): BRAND_COLORS["red"],
        int(surgery.Surgery.RobotMode.PAUSED): BRAND_COLORS["amber"],
        int(surgery.Surgery.RobotMode.IDLE): BRAND_COLORS["gray"],
        int(surgery.Surgery.RobotMode.UNKNOWN): BRAND_COLORS["gray"],
    }
    return _map.get(int(mode_value), BRAND_COLORS["gray"])


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
    robot_disconnected: bool = False
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
        self._robot_id_to_procedure: dict[str, str] = {}
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
            background_tasks.create(self._monitor_robot_liveliness()),
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
        # Support both real DDS RobotState samples (robot_id key, operational_mode field)
        # and test SimpleNamespace shims (procedure_id, mode).
        robot_id = _text(getattr(sample, "robot_id", ""))
        procedure_id = _text(getattr(sample, "procedure_id", ""))
        if not procedure_id:
            procedure_id = self._robot_id_to_procedure.get(robot_id, robot_id)
        if robot_id and procedure_id:
            self._robot_id_to_procedure[robot_id] = procedure_id
        entry = self._get_or_create_procedure(procedure_id)
        entry.robot_disconnected = False
        # Prefer operational_mode (real IDL field), fall back to mode / state (test shim)
        raw_mode = getattr(
            sample,
            "operational_mode",
            getattr(sample, "mode", getattr(sample, "state", "")),
        )
        if raw_mode is None:
            raw_mode = ""
        if isinstance(raw_mode, str):
            entry.robot_state = raw_mode or "Unknown"
            entry.robot_color = _robot_mode_color(raw_mode or "UNKNOWN")
        else:
            entry.robot_state = _robot_mode_label(raw_mode)
            entry.robot_color = _robot_mode_color(raw_mode)

    def mark_robot_disconnected(self, robot_id: str) -> None:
        """Mark the robot associated with *robot_id* as disconnected (liveliness lost)."""
        procedure_id = self._robot_id_to_procedure.get(robot_id)
        targets: list[ProcedureEntry] = []
        if procedure_id:
            entry = self.procedures.get(procedure_id)
            if entry is not None:
                targets.append(entry)
        else:
            # robot_id unknown — mark all known procedures as disconnected
            targets = list(self.procedures.values())
        for entry in targets:
            entry.robot_disconnected = True
            entry.robot_state = "Disconnected"
            entry.robot_color = BRAND_COLORS["light_gray"]

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

    async def _monitor_robot_liveliness(self) -> None:
        """Periodically check RobotState writer liveliness and mark robots disconnected."""
        while self._running:
            status = self._robot_state_reader.liveliness_changed_status
            if status.alive_count == 0 and status.not_alive_count > 0:
                for robot_id in list(self._robot_id_to_procedure.keys()):
                    self.mark_robot_disconnected(robot_id)
                if not self._robot_id_to_procedure:
                    # No known robot_id yet — mark all existing procedures
                    self.mark_robot_disconnected("")
            await asyncio.sleep(_LIVELINESS_POLL_INTERVAL)

    def select_patient_filter(self, patient_id: str) -> None:
        """Activate a content-filtered topic on PatientVitals for *patient_id*.

        Creates a ``ContentFilteredTopic`` with expression ``patient_id = %0``
        and replaces the existing patient vitals reader so only data for the
        selected patient reaches the reader cache.  No-op when operating with
        injected readers (e.g., in unit tests).
        """
        if self._participant is None:
            return
        if "'" in patient_id or "\\" in patient_id:
            log.warning(
                "select_patient_filter: invalid patient_id characters — ignoring"
            )
            return
        try:
            old_reader = self._patient_vitals_reader
            subscriber = old_reader.subscriber
            topic = dds.Topic.find(self._participant, "PatientVitals")
            if topic is None:
                log.warning("PatientVitals topic not found — cannot activate filter")
                return
            cft_name = f"PatientVitals_filtered_{patient_id}"
            cft = dds.ContentFilteredTopic(
                topic,
                cft_name,
                dds.Filter(f"patient_id = '{patient_id}'"),
            )
            self._patient_vitals_reader = dds.DataReader(subscriber, cft)
            old_reader.close()
            log.info("Content filter activated for patient_id=%s", patient_id)
        except Exception:
            log.exception(
                "Failed to activate content filter for patient %s", patient_id
            )

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


@ui.page("/dashboard", dark=True, title="Hospital Dashboard — Medtech Suite")
def dashboard_page() -> None:
    """Render the hospital dashboard page (standalone with self-contained shell)."""
    init_theme()
    create_header(title="Hospital Dashboard")
    controller_url = os.environ.get("MEDTECH_CONTROLLER_URL", "")
    if controller_url:
        with ui.row().classes("w-full px-4 pt-2 items-center"):
            ui.link("← Return to Controller", controller_url).classes(
                "text-sm text-blue-400 hover:text-blue-300"
            )
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
                            with ui.card().classes("w-full gap-1 p-4 hover-elevate"):
                                with ui.row().classes("w-full items-center gap-2"):
                                    create_status_chip(entry.phase)
                                    ui.label(entry.room or entry.procedure_id).classes(
                                        "type-h3"
                                    )
                                    ui.space()
                                    ui.label(entry.phase).classes("type-body")
                                ui.label(
                                    f"Patient: {entry.patient_name or '—'}"
                                ).classes("type-body-sm text-gray-500")
                                ui.label(
                                    f"Type: {entry.procedure_type or '—'}"
                                ).classes("type-body-sm text-gray-500")
                                ui.label(f"Surgeon: {entry.surgeon or '—'}").classes(
                                    "type-body-sm text-gray-500"
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

                            @ui.refreshable
                            def render_robot_status() -> None:
                                procs = _procedure_cards()
                                if not procs:
                                    create_empty_state("No robot data")
                                    return
                                with ui.column().classes("w-full gap-2"):
                                    for entry in procs:
                                        is_estop = (
                                            entry.robot_state
                                            in ("E-STOP", "EMERGENCY_STOP")
                                            and not entry.robot_disconnected
                                        )
                                        card_classes = "w-full p-3"
                                        if is_estop:
                                            card_classes += (
                                                " animate-pulse border-2 border-red-600"
                                            )
                                        with ui.card().classes(card_classes):
                                            with ui.row().classes(
                                                "w-full items-center gap-2"
                                            ):
                                                ui.label(
                                                    entry.room or entry.procedure_id
                                                ).classes("type-h3")
                                                create_status_chip(entry.robot_state)

                            render_robot_status()
                        with ui.tab_panel("Resources"):

                            @ui.refreshable
                            def render_resource_panel() -> None:
                                resources = list(current_backend.resources.values())
                                if not resources:
                                    create_empty_state("No resource data")
                                    return
                                rows = [
                                    {
                                        "name": r.name,
                                        "kind": r.kind,
                                        "status": r.status,
                                        "location": r.location,
                                    }
                                    for r in resources
                                ]
                                ui.aggrid(
                                    {
                                        "columnDefs": [
                                            {
                                                "field": "name",
                                                "headerName": "Resource",
                                            },
                                            {"field": "kind", "headerName": "Kind"},
                                            {
                                                "field": "status",
                                                "headerName": "Status",
                                            },
                                            {
                                                "field": "location",
                                                "headerName": "Location",
                                            },
                                        ],
                                        "rowData": rows,
                                    }
                                ).classes("w-full h-64")

                            render_resource_panel()

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
                    card_classes = "w-full gap-1 p-3 animate-slide-in"
                    if alert.severity.upper() == "CRITICAL":
                        card_classes += " pulse-critical"
                    with ui.card().classes(card_classes):
                        ui.label(f"{alert.severity} · {alert.room or '—'}").classes(
                            "type-h3"
                        )
                        ui.label(alert.patient_name or "—").classes("type-body")
                        ui.label(alert.category or "").classes(
                            "type-body-sm text-gray-500"
                        )
                        ui.label(alert.message or "").classes("type-body")

        render_alert_feed()

        ui.timer(
            0.5,
            lambda: (
                render_procedure_list.refresh(),
                render_alert_feed.refresh(),
                render_robot_status.refresh(),
                render_resource_panel.refresh(),
            ),
        )


def main() -> None:
    storage_secret = os.environ.get(
        NICEGUI_STORAGE_SECRET_ENV, NICEGUI_STORAGE_SECRET_DEFAULT
    )

    _current_backend()
    try:
        ui.run(
            root=dashboard_page,
            storage_secret=storage_secret,
            reload=False,
            title="Hospital Dashboard — Medtech Suite",
            favicon="/images/favicon.ico",
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
