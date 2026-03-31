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

        # ---- DDS readers ----
        injected = all(
            r is not None
            for r in (
                procedure_status_reader,
                patient_vitals_reader,
                alarm_messages_reader,
                robot_state_reader,
                clinical_alert_reader,
                resource_availability_reader,
            )
        )
        if injected:
            self._procedure_status_reader = dds.DataReader(procedure_status_reader)
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
            "Select a procedure to view details", "\u25CB"
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
        log.notice("Dashboard async data reception started")
        # Data reception tasks will be added in Steps 3.3–3.6b
        # For now, just keep the event loop alive
        while self._running:
            await asyncio.sleep(1.0)

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
