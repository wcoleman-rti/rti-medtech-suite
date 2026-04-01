"""Hospital Dashboard — PySide6 GUI for facility-wide surgical monitoring.

Subscribes to the Hospital domain (Domain 11) and displays real-time
procedure status, patient vitals, clinical alerts, robot state, and
resource availability across all active operating rooms.

All data arrives via Routing Service from the Procedure domain, except
native Hospital topics (ClinicalAlert, ResourceAvailability).

Threading model:
  - DDS reads via async coroutines on the QtAsyncio event loop
  - No DDS writes (dashboard is read-only)
  - No blocking waits on the UI thread
  - Widget updates via Qt signals from async data reception

Follows the canonical application architecture in vision/dds-consistency.md §3.
Uses generated entity name constants from app_names.idl.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import app_names
import rti.connextdds as dds
import surgery
from medtech.dds import initialize_connext
from medtech.gui import (
    ConnectionDot,
    create_empty_state,
    create_section_header,
    init_theme,
)
from medtech.log import ModuleName, init_logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

dash_names = app_names.MedtechEntityNames.HospitalDashboard

log = init_logging(ModuleName.HOSPITAL_DASHBOARD)

# Liveliness poll interval (seconds)
_LIVELINESS_POLL_INTERVAL = 0.5

# Phase → color mapping (RTI palette + severity)
_PHASE_COLORS: dict[int, str] = {
    int(surgery.Surgery.ProcedurePhase.PRE_OP): "#004C97",  # RTI Blue
    int(surgery.Surgery.ProcedurePhase.IN_PROGRESS): "#A4D65E",  # RTI Green
    int(surgery.Surgery.ProcedurePhase.COMPLETING): "#FFA300",  # RTI Light Orange
    int(surgery.Surgery.ProcedurePhase.COMPLETED): "#BBBCBC",  # RTI Gray
    int(surgery.Surgery.ProcedurePhase.ALERT): "#D32F2F",  # Critical Red
}
_DEFAULT_PHASE_COLOR = "#BBBCBC"

# Phase → display text
_PHASE_TEXT: dict[int, str] = {
    int(surgery.Surgery.ProcedurePhase.UNKNOWN): "Unknown",
    int(surgery.Surgery.ProcedurePhase.PRE_OP): "Pre-Op",
    int(surgery.Surgery.ProcedurePhase.IN_PROGRESS): "In Progress",
    int(surgery.Surgery.ProcedurePhase.COMPLETING): "Completing",
    int(surgery.Surgery.ProcedurePhase.COMPLETED): "Completed",
    int(surgery.Surgery.ProcedurePhase.ALERT): "Alert",
}


# Vitals severity thresholds (spec: hospital-dashboard.md)
_HR_WARNING = 100.0  # bpm — yellow/amber
_HR_CRITICAL = 120.0  # bpm — red
_SPO2_WARNING = 94.0  # % — below this is warning
_SPO2_CRITICAL = 90.0  # % — below this is critical
_SBP_WARNING_HIGH = 160.0  # mmHg — above this is warning
_SBP_CRITICAL_HIGH = 180.0  # mmHg — above this is critical
_SBP_WARNING_LOW = 90.0  # mmHg — below this is warning

_COLOR_NORMAL = "#A4D65E"  # RTI Green
_COLOR_WARNING = "#ED8B00"  # RTI Orange
_COLOR_CRITICAL = "#D32F2F"  # Critical Red


def _vitals_color(value: float, warn_above: float, crit_above: float) -> str:
    """Return severity color for a vital sign (higher = worse)."""
    if value >= crit_above:
        return _COLOR_CRITICAL
    if value >= warn_above:
        return _COLOR_WARNING
    return _COLOR_NORMAL


def _vitals_color_low(value: float, warn_below: float, crit_below: float) -> str:
    """Return severity color for a vital sign (lower = worse)."""
    if value <= crit_below:
        return _COLOR_CRITICAL
    if value <= warn_below:
        return _COLOR_WARNING
    return _COLOR_NORMAL


def _bp_color(systolic: float) -> str:
    """Return severity color for blood pressure."""
    if systolic >= _SBP_CRITICAL_HIGH or systolic < 70.0:
        return _COLOR_CRITICAL
    if systolic >= _SBP_WARNING_HIGH or systolic <= _SBP_WARNING_LOW:
        return _COLOR_WARNING
    return _COLOR_NORMAL


class VitalsRow(QFrame):
    """Widget showing HR, SpO2, and BP for one patient/procedure.

    All values are color-coded by severity thresholds from the spec.
    """

    def __init__(self, patient_id: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.patient_id = patient_id
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("vitalsRow")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(16)

        self._patient_label = QLabel(patient_id)
        self._patient_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(self._patient_label)

        self._hr_label = QLabel("HR: —")
        self._hr_label.setFixedWidth(100)
        layout.addWidget(self._hr_label)

        self._spo2_label = QLabel("SpO2: —")
        self._spo2_label.setFixedWidth(100)
        layout.addWidget(self._spo2_label)

        self._bp_label = QLabel("BP: —/—")
        self._bp_label.setFixedWidth(120)
        layout.addWidget(self._bp_label)

        layout.addStretch()

    def update_vitals(
        self,
        hr: float,
        spo2: float,
        systolic: float,
        diastolic: float,
    ) -> None:
        """Update displayed vitals with color-coded severity."""
        hr_color = _vitals_color(hr, _HR_WARNING, _HR_CRITICAL)
        self._hr_label.setText(f"HR: {hr:.0f}")
        self._hr_label.setStyleSheet(f"color: {hr_color}; font-weight: bold;")

        spo2_color = _vitals_color_low(spo2, _SPO2_WARNING, _SPO2_CRITICAL)
        self._spo2_label.setText(f"SpO2: {spo2:.0f}%")
        self._spo2_label.setStyleSheet(f"color: {spo2_color}; font-weight: bold;")

        bp_c = _bp_color(systolic)
        self._bp_label.setText(f"BP: {systolic:.0f}/{diastolic:.0f}")
        self._bp_label.setStyleSheet(f"color: {bp_c}; font-weight: bold;")


class ProcedureCard(QFrame):
    """Widget for a single procedure in the procedure list.

    Shows room, patient, procedure type, surgeon, and current status
    with a color-coded status indicator.
    """

    def __init__(self, procedure_id: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.procedure_id = procedure_id
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("procedureCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # Top row: status indicator + room
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        self._status_dot = QLabel("\u25CF")
        self._status_dot.setFixedWidth(16)
        self._status_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_dot.setStyleSheet(
            f"color: {_DEFAULT_PHASE_COLOR}; font-size: 14px;"
        )
        top_row.addWidget(self._status_dot)

        self._room_label = QLabel("—")
        self._room_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        top_row.addWidget(self._room_label, stretch=1)

        self._phase_label = QLabel("Unknown")
        self._phase_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._phase_label.setStyleSheet(
            f"color: {_DEFAULT_PHASE_COLOR}; font-weight: bold;"
        )
        top_row.addWidget(self._phase_label)

        layout.addLayout(top_row)

        # Detail row: patient, procedure type, surgeon
        self._patient_label = QLabel("Patient: —")
        self._patient_label.setStyleSheet("color: #666666; font-size: 11px;")
        layout.addWidget(self._patient_label)

        self._type_label = QLabel("Type: —")
        self._type_label.setStyleSheet("color: #666666; font-size: 11px;")
        layout.addWidget(self._type_label)

        self._surgeon_label = QLabel("Surgeon: —")
        self._surgeon_label.setStyleSheet("color: #666666; font-size: 11px;")
        layout.addWidget(self._surgeon_label)

    def update_status(self, phase_int: int, status_message: str) -> None:
        """Update the phase indicator and status text."""
        color = _PHASE_COLORS.get(phase_int, _DEFAULT_PHASE_COLOR)
        text = _PHASE_TEXT.get(phase_int, "Unknown")
        self._status_dot.setStyleSheet(f"color: {color}; font-size: 14px;")
        self._phase_label.setText(text)
        self._phase_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def update_context(
        self, room: str, patient_name: str, procedure_type: str, surgeon: str
    ) -> None:
        """Update the procedure context fields."""
        self._room_label.setText(room if room else "—")
        self._patient_label.setText(
            f"Patient: {patient_name}" if patient_name else "Patient: —"
        )
        self._type_label.setText(
            f"Type: {procedure_type}" if procedure_type else "Type: —"
        )
        self._surgeon_label.setText(f"Surgeon: {surgeon}" if surgeon else "Surgeon: —")


class HospitalDashboard(QMainWindow):
    """PySide6 main window for facility-wide hospital monitoring.

    Creates one DomainParticipant on the Hospital domain (11) and
    subscribes to all bridged topics + native Hospital topics.

    DDS data reception runs as async coroutines (QtAsyncio / rti.asyncio)
    so the Qt main thread is never blocked by DDS reads. The UI updates
    only when new data arrives (event-driven).

    Parameters
    ----------
    procedure_status_reader, procedure_context_reader, ...:
        Optional pre-created DataReader objects for dependency injection
        in tests. When all are supplied, no DomainParticipant is created
        internally.
    """

    def __init__(
        self,
        *,
        procedure_status_reader: Optional[dds.DataReader] = None,
        procedure_context_reader: Optional[dds.DataReader] = None,
        patient_vitals_reader: Optional[dds.DataReader] = None,
        alarm_messages_reader: Optional[dds.DataReader] = None,
        robot_state_reader: Optional[dds.DataReader] = None,
        clinical_alert_reader: Optional[dds.DataReader] = None,
        resource_availability_reader: Optional[dds.DataReader] = None,
    ) -> None:
        super().__init__()
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._participant: Optional[dds.DomainParticipant] = None
        self._procedure_cards: dict[str, ProcedureCard] = {}
        self._vitals_rows: dict[str, VitalsRow] = {}
        self._patient_to_procedure: dict[str, str] = {}

        # ---- DDS readers ----
        injected = all(
            r is not None
            for r in (
                procedure_status_reader,
                procedure_context_reader,
                patient_vitals_reader,
                alarm_messages_reader,
                robot_state_reader,
                clinical_alert_reader,
                resource_availability_reader,
            )
        )
        if injected:
            self._procedure_status_reader = dds.DataReader(procedure_status_reader)
            self._procedure_context_reader = dds.DataReader(procedure_context_reader)
            self._patient_vitals_reader = dds.DataReader(patient_vitals_reader)
            self._alarm_messages_reader = dds.DataReader(alarm_messages_reader)
            self._robot_state_reader = dds.DataReader(robot_state_reader)
            self._clinical_alert_reader = dds.DataReader(clinical_alert_reader)
            self._resource_reader = dds.DataReader(resource_availability_reader)
        else:
            self._init_dds()

        # ---- Qt UI ----
        self.setWindowTitle("Medtech Suite — Hospital Dashboard")
        self._setup_ui()

    # ------------------------------------------------------------------ #
    # DDS initialization                                                   #
    # ------------------------------------------------------------------ #

    def _init_dds(self) -> None:
        """Create the HospitalDashboard participant and find readers."""
        initialize_connext()

        provider = dds.QosProvider.default
        self._participant = provider.create_participant_from_config(
            dash_names.HOSPITAL_DASHBOARD
        )

        # Wildcard partition for facility-wide aggregation
        partition = "room/*/procedure/*"
        qos = self._participant.qos
        qos.partition.name = [partition]
        self._participant.qos = qos
        self._participant.enable()

        def _find_reader(entity_name: str) -> dds.DataReader:
            r = self._participant.find_datareader(entity_name)
            if r is None:
                raise RuntimeError(f"Reader not found: {entity_name}")
            return dds.DataReader(r)

        self._procedure_status_reader = _find_reader(dash_names.PROCEDURE_STATUS_READER)
        self._procedure_context_reader = _find_reader(
            dash_names.PROCEDURE_CONTEXT_READER
        )
        self._patient_vitals_reader = _find_reader(dash_names.PATIENT_VITALS_READER)
        self._alarm_messages_reader = _find_reader(dash_names.ALARM_MESSAGES_READER)
        self._robot_state_reader = _find_reader(dash_names.ROBOT_STATE_READER)
        self._clinical_alert_reader = _find_reader(dash_names.CLINICAL_ALERT_READER)
        self._resource_reader = _find_reader(dash_names.RESOURCE_AVAILABILITY_READER)

        log.notice(f"Hospital dashboard participant created, partition={partition}")

    # ------------------------------------------------------------------ #
    # Qt widget setup                                                      #
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        """Build the main window layout with all panels."""
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setSpacing(0)
        root_layout.setContentsMargins(0, 0, 0, 0)

        # Shared GUI header (RTI logo + theme + connection dot)
        app_instance = None
        try:
            from PySide6.QtWidgets import QApplication

            app_instance = QApplication.instance()
        except Exception:
            pass

        if app_instance is not None:
            header = init_theme(app_instance)
            root_layout.addWidget(header)
            self._conn_dot = header.findChild(ConnectionDot)
        else:
            self._conn_dot = None

        # Main content area — horizontal splitter
        content = QWidget()
        content.setObjectName("contentArea")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(8)

        # Top area: procedure list (left) + detail panel (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("mainSplitter")

        # ── Left panel: Procedure list ──
        left_panel = QFrame()
        left_panel.setObjectName("procedureListPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        left_layout.addWidget(create_section_header("Active Procedures", "\u2302"))

        self._procedure_list_scroll = QScrollArea()
        self._procedure_list_scroll.setWidgetResizable(True)
        self._procedure_list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._procedure_list_container = QWidget()
        self._procedure_list_layout = QVBoxLayout(self._procedure_list_container)
        self._procedure_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._procedure_list_layout.setSpacing(6)
        self._procedure_list_scroll.setWidget(self._procedure_list_container)

        self._procedure_list_empty = create_empty_state(
            "Waiting for procedure data\u2026", "\u25CE"
        )
        self._procedure_list_stack = QStackedWidget()
        self._procedure_list_stack.addWidget(self._procedure_list_empty)
        self._procedure_list_stack.addWidget(self._procedure_list_scroll)
        left_layout.addWidget(self._procedure_list_stack, stretch=1)

        splitter.addWidget(left_panel)

        # ── Right panel: Detail view (vitals + robot status) ──
        right_panel = QFrame()
        right_panel.setObjectName("detailPanel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        right_layout.addWidget(create_section_header("Vitals & Status", "\u2764"))

        self._vitals_container = QWidget()
        self._vitals_layout = QVBoxLayout(self._vitals_container)
        self._vitals_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._vitals_layout.setSpacing(6)

        self._detail_empty = create_empty_state(
            "Waiting for vitals data\u2026", "\u2764"
        )
        self._detail_stack = QStackedWidget()
        self._detail_stack.addWidget(self._detail_empty)
        self._detail_stack.addWidget(self._vitals_container)
        right_layout.addWidget(self._detail_stack, stretch=1)

        # Robot status section
        right_layout.addWidget(create_section_header("Robot Status", "\u2699"))

        self._robot_status_container = QWidget()
        self._robot_status_layout = QVBoxLayout(self._robot_status_container)
        self._robot_status_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._robot_status_layout.setSpacing(6)

        self._robot_empty = create_empty_state("No robot data received", "\u25CB")
        self._robot_stack = QStackedWidget()
        self._robot_stack.addWidget(self._robot_empty)
        self._robot_stack.addWidget(self._robot_status_container)
        right_layout.addWidget(self._robot_stack, stretch=1)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        content_layout.addWidget(splitter, stretch=3)

        # ── Bottom panel: Alert feed ──
        alert_panel = QFrame()
        alert_panel.setObjectName("alertFeedPanel")
        alert_layout = QVBoxLayout(alert_panel)
        alert_layout.setContentsMargins(8, 8, 8, 8)
        alert_layout.setSpacing(8)

        alert_layout.addWidget(create_section_header("Alert Feed", "\u26A0"))

        self._alert_feed_scroll = QScrollArea()
        self._alert_feed_scroll.setWidgetResizable(True)
        self._alert_feed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._alert_feed_container = QWidget()
        self._alert_feed_layout = QVBoxLayout(self._alert_feed_container)
        self._alert_feed_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._alert_feed_layout.setSpacing(4)
        self._alert_feed_scroll.setWidget(self._alert_feed_container)

        self._alert_empty = create_empty_state("No alerts", "\u2714")
        self._alert_stack = QStackedWidget()
        self._alert_stack.addWidget(self._alert_empty)
        self._alert_stack.addWidget(self._alert_feed_scroll)
        alert_layout.addWidget(self._alert_stack, stretch=1)

        content_layout.addWidget(alert_panel, stretch=1)

        # ── Resource panel (right side of alert area) ──
        # Will be populated in Step 3.6b

        root_layout.addWidget(content, stretch=1)

        self.resize(1200, 800)

    # ------------------------------------------------------------------ #
    # Async DDS data reception                                             #
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """Start async data reception coroutines."""
        self._running = True
        loop = asyncio.get_event_loop()
        self._tasks = [
            loop.create_task(self._receive_procedure_status()),
            loop.create_task(self._receive_procedure_context()),
            loop.create_task(self._receive_patient_vitals()),
        ]
        log.notice("Dashboard async data reception started")

    # ------------------------------------------------------------------ #
    # Procedure list management                                            #
    # ------------------------------------------------------------------ #

    def _get_or_create_card(self, procedure_id: str) -> ProcedureCard:
        """Get an existing card or create a new one for the procedure."""
        if procedure_id in self._procedure_cards:
            return self._procedure_cards[procedure_id]
        card = ProcedureCard(procedure_id)
        self._procedure_cards[procedure_id] = card
        self._procedure_list_layout.addWidget(card)
        # Switch from empty state to populated list
        self._procedure_list_stack.setCurrentIndex(1)
        return card

    async def _receive_procedure_status(self) -> None:
        """Consume ProcedureStatus samples and update procedure cards."""
        async for data in self._procedure_status_reader.take_data_async():
            pid = str(data.procedure_id)
            card = self._get_or_create_card(pid)
            card.update_status(int(data.phase), str(data.status_message))

    async def _receive_procedure_context(self) -> None:
        """Consume ProcedureContext samples and update procedure cards."""
        async for data in self._procedure_context_reader.take_data_async():
            pid = str(data.procedure_id)
            card = self._get_or_create_card(pid)
            patient_id = str(data.patient.id)
            card.update_context(
                room=str(data.room),
                patient_name=str(data.patient.name),
                procedure_type=str(data.procedure_type),
                surgeon=str(data.surgeon),
            )
            # Map patient_id → procedure_id for vitals correlation
            self._patient_to_procedure[patient_id] = pid

    # ------------------------------------------------------------------ #
    # Vitals management                                                    #
    # ------------------------------------------------------------------ #

    def _get_or_create_vitals_row(self, patient_id: str) -> VitalsRow:
        """Get or create a VitalsRow for the given patient."""
        if patient_id in self._vitals_rows:
            return self._vitals_rows[patient_id]
        row = VitalsRow(patient_id)
        self._vitals_rows[patient_id] = row
        self._vitals_layout.addWidget(row)
        # Switch from empty state to populated vitals
        self._detail_stack.setCurrentIndex(1)
        return row

    async def _receive_patient_vitals(self) -> None:
        """Consume PatientVitals samples and update vitals display."""
        async for data in self._patient_vitals_reader.take_data_async():
            patient_id = str(data.patient_id)
            row = self._get_or_create_vitals_row(patient_id)
            row.update_vitals(
                hr=float(data.heart_rate),
                spo2=float(data.spo2),
                systolic=float(data.systolic_bp),
                diastolic=float(data.diastolic_bp),
            )

    def close_dds(self) -> None:
        """Cancel tasks and close the DDS participant."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._participant is not None:
            self._participant.close()
            self._participant = None
            log.notice("Hospital dashboard participant closed")

    # ------------------------------------------------------------------ #
    # Public accessors for testing                                         #
    # ------------------------------------------------------------------ #

    @property
    def participant(self) -> Optional[dds.DomainParticipant]:
        return self._participant

    @property
    def procedure_status_reader(self) -> dds.DataReader:
        return self._procedure_status_reader

    @property
    def procedure_context_reader(self) -> dds.DataReader:
        return self._procedure_context_reader

    @property
    def patient_vitals_reader(self) -> dds.DataReader:
        return self._patient_vitals_reader

    @property
    def alarm_messages_reader(self) -> dds.DataReader:
        return self._alarm_messages_reader

    @property
    def robot_state_reader(self) -> dds.DataReader:
        return self._robot_state_reader

    @property
    def clinical_alert_reader(self) -> dds.DataReader:
        return self._clinical_alert_reader

    @property
    def resource_reader(self) -> dds.DataReader:
        return self._resource_reader

    @property
    def procedure_cards(self) -> dict[str, ProcedureCard]:
        return self._procedure_cards

    @property
    def vitals_rows(self) -> dict[str, VitalsRow]:
        return self._vitals_rows

    @property
    def patient_to_procedure(self) -> dict[str, str]:
        return self._patient_to_procedure
