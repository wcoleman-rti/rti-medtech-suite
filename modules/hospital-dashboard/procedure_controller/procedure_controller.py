"""Procedure Controller — PySide6 GUI for orchestrating surgical services.

Subscribes to HostCatalog and ServiceStatus on the Orchestration domain
(Domain 15) via polling reads on a QTimer. Issues RPC commands to Service
Hosts via ServiceHostControl client stubs on a worker thread. Reads
scheduling context from the Hospital domain (read-only).

Threading model:
  - DDS polling reads on the Qt UI thread (QTimer, 10 Hz)
  - RPC calls on a dedicated worker thread (threading.Thread)
  - No DDS writes on the UI thread (Procedure Controller has no writers)

Follows the canonical application architecture in vision/dds-consistency.md §5.
Uses generated entity name constants from app_names.idl.
"""

from __future__ import annotations

import threading
from typing import Optional

import app_names
import rti.connextdds as dds
import rti.rpc
from medtech_dds_init.dds_init import initialize_connext
from medtech_gui import init_theme
from medtech_logging import ModuleName, init_logging
from orchestration import Orchestration
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

orch_names = app_names.MedtechEntityNames.OrchestrationParticipants

log = init_logging(ModuleName.HOSPITAL_DASHBOARD)

# Polling interval for DDS reads (milliseconds)
_POLL_INTERVAL_MS = 100  # 10 Hz

# RPC timeout
_RPC_TIMEOUT = dds.Duration(seconds=10)


class ProcedureController(QMainWindow):
    """PySide6 main window for orchestrating surgical services.

    Creates two DomainParticipants:
      - Orchestration domain: HostCatalog + ServiceStatus subscribers,
        ServiceHostControl RPC client
      - Hospital domain: read-only subscriber for scheduling context

    DDS polling reads run on the Qt UI thread via QTimer (non-blocking).
    RPC calls run on worker threads to avoid blocking the UI.

    Parameters
    ----------
    room_id:
        Operating room (e.g. "OR-1"). Sets the partition string.
    catalog_reader, status_reader:
        Optional pre-created DataReader objects for dependency injection
        in tests. When both are supplied, no DomainParticipants are
        created internally.
    """

    # Qt signal to deliver RPC results from worker thread to UI thread
    _rpc_result_signal = Signal(str, str)

    def __init__(
        self,
        room_id: str = "OR-1",
        *,
        catalog_reader: Optional[dds.DataReader] = None,
        status_reader: Optional[dds.DataReader] = None,
    ) -> None:
        super().__init__()
        self._room_id = room_id
        self._orch_participant: Optional[dds.DomainParticipant] = None
        self._hosp_participant: Optional[dds.DomainParticipant] = None
        self._requesters: dict[str, rti.rpc.Requester] = {}

        # State tracking
        self._hosts: dict[str, Orchestration.HostCatalog] = {}
        self._service_states: dict[tuple[str, str], Orchestration.ServiceStatus] = {}

        # ---- DDS setup ----
        injected = catalog_reader is not None and status_reader is not None
        if injected:
            self._catalog_reader = dds.DataReader(catalog_reader)
            self._status_reader = dds.DataReader(status_reader)
        else:
            self._init_dds(room_id)

        # ---- Qt UI ----
        self.setWindowTitle("Medtech Suite — Procedure Controller")
        self._setup_ui()

        # ---- RPC result signal ----
        self._rpc_result_signal.connect(self._on_rpc_result)

        # ---- Polling timer ----
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_dds)
        self._poll_timer.start(_POLL_INTERVAL_MS)

    # ------------------------------------------------------------------ #
    # DDS initialization                                                   #
    # ------------------------------------------------------------------ #

    def _init_dds(self, room_id: str) -> None:
        """Create Orchestration + Hospital participants and find readers."""
        initialize_connext()
        provider = dds.QosProvider.default

        # -- Orchestration domain participant --
        self._orch_participant = provider.create_participant_from_config(
            orch_names.PROCEDURE_CONTROLLER_ORCHESTRATION
        )
        partition = f"room/{room_id}"
        qos = self._orch_participant.qos
        qos.partition.name = [partition]
        self._orch_participant.qos = qos
        self._orch_participant.enable()

        self._catalog_reader = dds.DataReader(
            self._orch_participant.find_datareader(orch_names.CTRL_HOST_CATALOG_READER)
        )
        self._status_reader = dds.DataReader(
            self._orch_participant.find_datareader(
                orch_names.CTRL_SERVICE_STATUS_READER
            )
        )
        if self._catalog_reader is None:
            raise RuntimeError(
                f"Reader not found: {orch_names.CTRL_HOST_CATALOG_READER}"
            )
        if self._status_reader is None:
            raise RuntimeError(
                f"Reader not found: {orch_names.CTRL_SERVICE_STATUS_READER}"
            )

        log.notice(f"Orchestration participant created, partition={partition}")

        # -- Hospital domain participant (read-only) --
        self._hosp_participant = provider.create_participant_from_config(
            orch_names.PROCEDURE_CONTROLLER_HOSPITAL
        )
        hosp_partition = f"room/{room_id}"
        hosp_qos = self._hosp_participant.qos
        hosp_qos.partition.name = [hosp_partition]
        self._hosp_participant.qos = hosp_qos
        self._hosp_participant.enable()

        log.notice(
            f"Hospital participant created (read-only), partition={hosp_partition}"
        )

    # ------------------------------------------------------------------ #
    # Qt widget setup                                                      #
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # Shared GUI header (RTI logo + theme)
        app = QApplication.instance()
        if app is not None:
            header = init_theme(app)
            layout.addWidget(header)

        # Content area
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 8, 12, 8)

        # -- Hosts table --
        host_group = QGroupBox("Service Hosts")
        host_layout = QVBoxLayout(host_group)
        self._host_table = QTableWidget(0, 4)
        self._host_table.setHorizontalHeaderLabels(
            ["Host ID", "Host Type", "Capacity", "Services"]
        )
        self._host_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._host_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._host_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._host_table.setAlternatingRowColors(True)
        host_layout.addWidget(self._host_table)
        content_layout.addWidget(host_group)

        # -- Services table --
        svc_group = QGroupBox("Service States")
        svc_layout = QVBoxLayout(svc_group)
        self._svc_table = QTableWidget(0, 3)
        self._svc_table.setHorizontalHeaderLabels(["Service ID", "Host", "State"])
        self._svc_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._svc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._svc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._svc_table.setAlternatingRowColors(True)
        svc_layout.addWidget(self._svc_table)
        content_layout.addWidget(svc_group)

        # -- Action buttons --
        btn_layout = QHBoxLayout()
        self._btn_start = QPushButton("Start Service")
        self._btn_stop = QPushButton("Stop Service")
        self._btn_capabilities = QPushButton("Capabilities")
        self._btn_health = QPushButton("Health")
        self._btn_start.clicked.connect(self._on_start_clicked)
        self._btn_stop.clicked.connect(self._on_stop_clicked)
        self._btn_capabilities.clicked.connect(self._on_capabilities_clicked)
        self._btn_health.clicked.connect(self._on_health_clicked)
        btn_layout.addWidget(self._btn_start)
        btn_layout.addWidget(self._btn_stop)
        btn_layout.addWidget(self._btn_capabilities)
        btn_layout.addWidget(self._btn_health)
        btn_layout.addStretch()
        content_layout.addLayout(btn_layout)

        layout.addWidget(content, stretch=1)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Discovering service hosts...")

        self.resize(800, 600)

    # ------------------------------------------------------------------ #
    # DDS polling (UI thread — non-blocking)                               #
    # ------------------------------------------------------------------ #

    def _poll_dds(self) -> None:
        """Poll DDS readers on the UI thread (non-blocking)."""
        # -- HostCatalog --
        try:
            for sample in self._catalog_reader.take():
                if sample.info.valid:
                    self._update_host(sample.data)
        except dds.AlreadyClosedError:
            return

        # -- ServiceStatus --
        try:
            for sample in self._status_reader.take():
                if sample.info.valid:
                    self._update_service_status(sample.data)
        except dds.AlreadyClosedError:
            return

    def _update_host(self, catalog: Orchestration.HostCatalog) -> None:
        """Process a HostCatalog sample and update the hosts table."""
        host_id = catalog.host_id
        self._hosts[host_id] = catalog
        self._refresh_host_table()
        self._status_bar.showMessage(f"Discovered {len(self._hosts)} host(s)", 3000)
        log.informational(f"HostCatalog received: host_id={host_id}")

    def _update_service_status(self, status: Orchestration.ServiceStatus) -> None:
        """Process a ServiceStatus sample and update the services table."""
        key = (status.host_id, status.service_id)
        self._service_states[key] = status
        self._refresh_svc_table()

    def _refresh_host_table(self) -> None:
        """Rebuild the hosts table from current state."""
        self._host_table.setRowCount(len(self._hosts))
        for row, (host_id, catalog) in enumerate(sorted(self._hosts.items())):
            self._host_table.setItem(row, 0, QTableWidgetItem(host_id))
            self._host_table.setItem(row, 1, QTableWidgetItem(catalog.health_summary))
            self._host_table.setItem(row, 2, QTableWidgetItem(str(catalog.capacity)))
            self._host_table.setItem(
                row, 3, QTableWidgetItem(", ".join(catalog.supported_services))
            )

    def _refresh_svc_table(self) -> None:
        """Rebuild the services table from current state."""
        self._svc_table.setRowCount(len(self._service_states))
        for row, ((host_id, svc_id), status) in enumerate(
            sorted(self._service_states.items())
        ):
            self._svc_table.setItem(row, 0, QTableWidgetItem(svc_id))
            self._svc_table.setItem(row, 1, QTableWidgetItem(host_id))
            state_name = _state_name(status.state)
            item = QTableWidgetItem(state_name)
            self._svc_table.setItem(row, 2, item)

    # ------------------------------------------------------------------ #
    # RPC operations (worker thread)                                       #
    # ------------------------------------------------------------------ #

    def _get_requester(self, host_id: str) -> rti.rpc.Requester:
        """Get or create an RPC requester for a specific Service Host."""
        if host_id not in self._requesters:
            if self._orch_participant is None:
                raise RuntimeError("No Orchestration participant available")
            req = rti.rpc.Requester(
                request_type=Orchestration.ServiceHostControl.call_type,
                reply_type=Orchestration.ServiceHostControl.return_type,
                participant=self._orch_participant,
                service_name=f"ServiceHostControl/{host_id}",
            )
            self._requesters[host_id] = req
            log.informational(f"RPC requester created for host {host_id}")
        return self._requesters[host_id]

    def _send_rpc_async(
        self,
        host_id: str,
        call: object,
        op_name: str,
    ) -> None:
        """Send an RPC call on a worker thread, emit signal on completion."""

        def _worker() -> None:
            try:
                req = self._get_requester(host_id)
                request_id = req.send_request(call)
                replies = req.receive_replies(
                    max_wait=_RPC_TIMEOUT,
                    related_request_id=request_id,
                )
                for reply, info in replies:
                    if info.valid:
                        result = _extract_rpc_result(reply, op_name)
                        self._rpc_result_signal.emit(
                            op_name,
                            f"{host_id}: {result}",
                        )
                        return
                self._rpc_result_signal.emit(
                    op_name, f"{host_id}: timeout — no reply received"
                )
            except Exception as exc:
                self._rpc_result_signal.emit(op_name, f"{host_id}: error — {exc}")

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _on_rpc_result(self, op_name: str, message: str) -> None:
        """Handle RPC result delivered from worker thread via signal."""
        self._status_bar.showMessage(f"{op_name}: {message}", 5000)
        log.informational(f"RPC {op_name}: {message}")

    def _selected_service(self) -> tuple[str, str] | None:
        """Return (host_id, service_id) from the service table selection."""
        rows = self._svc_table.selectionModel().selectedRows()
        if not rows:
            # Fall back to host table selection
            host_rows = self._host_table.selectionModel().selectedRows()
            if not host_rows:
                self._status_bar.showMessage("Select a service or host first", 3000)
                return None
            host_id = self._host_table.item(host_rows[0].row(), 0).text()
            catalog = self._hosts.get(host_id)
            if catalog and catalog.supported_services:
                return host_id, catalog.supported_services[0]
            self._status_bar.showMessage("No services on selected host", 3000)
            return None
        row = rows[0].row()
        svc_id = self._svc_table.item(row, 0).text()
        host_id = self._svc_table.item(row, 1).text()
        return host_id, svc_id

    def _selected_host(self) -> str | None:
        """Return host_id from host table selection."""
        rows = self._host_table.selectionModel().selectedRows()
        if not rows:
            self._status_bar.showMessage("Select a host first", 3000)
            return None
        return self._host_table.item(rows[0].row(), 0).text()

    def _on_start_clicked(self) -> None:
        """Handle Start Service button click."""
        sel = self._selected_service()
        if sel is None:
            return
        host_id, svc_id = sel
        call = _make_start_call(svc_id)
        self._status_bar.showMessage(f"Starting {svc_id} on {host_id}...")
        self._send_rpc_async(host_id, call, "start_service")

    def _on_stop_clicked(self) -> None:
        """Handle Stop Service button click."""
        sel = self._selected_service()
        if sel is None:
            return
        host_id, svc_id = sel
        call = _make_stop_call(svc_id)
        self._status_bar.showMessage(f"Stopping {svc_id} on {host_id}...")
        self._send_rpc_async(host_id, call, "stop_service")

    def _on_capabilities_clicked(self) -> None:
        """Handle Capabilities button click."""
        host_id = self._selected_host()
        if host_id is None:
            return
        call = _make_get_capabilities_call()
        self._status_bar.showMessage(f"Querying capabilities of {host_id}...")
        self._send_rpc_async(host_id, call, "get_capabilities")

    def _on_health_clicked(self) -> None:
        """Handle Health button click."""
        host_id = self._selected_host()
        if host_id is None:
            return
        call = _make_get_health_call()
        self._status_bar.showMessage(f"Querying health of {host_id}...")
        self._send_rpc_async(host_id, call, "get_health")

    # ------------------------------------------------------------------ #
    # Public accessors (for testing)                                       #
    # ------------------------------------------------------------------ #

    @property
    def hosts(self) -> dict[str, Orchestration.HostCatalog]:
        """Currently discovered hosts."""
        return dict(self._hosts)

    @property
    def service_states(
        self,
    ) -> dict[tuple[str, str], Orchestration.ServiceStatus]:
        """Currently tracked service states."""
        return dict(self._service_states)

    @property
    def orch_participant(self) -> Optional[dds.DomainParticipant]:
        """Orchestration domain participant (for test inspection)."""
        return self._orch_participant

    @property
    def hosp_participant(self) -> Optional[dds.DomainParticipant]:
        """Hospital domain participant (for test inspection)."""
        return self._hosp_participant

    # ------------------------------------------------------------------ #
    # Cleanup                                                              #
    # ------------------------------------------------------------------ #

    def close_dds(self) -> None:
        """Close DDS resources."""
        self._poll_timer.stop()
        for req in self._requesters.values():
            try:
                req.close()
            except Exception:
                pass
        self._requesters.clear()
        if self._orch_participant is not None:
            try:
                self._orch_participant.close()
            except dds.AlreadyClosedError:
                pass
            self._orch_participant = None
        if self._hosp_participant is not None:
            try:
                self._hosp_participant.close()
            except dds.AlreadyClosedError:
                pass
            self._hosp_participant = None
        log.informational("ProcedureController: DDS resources closed")

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt override
        """Qt close event: clean up DDS before window closes."""
        self.close_dds()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# RPC call builders
# ---------------------------------------------------------------------------

_CallType = Orchestration.ServiceHostControl.call_type


def _make_start_call(service_id: str) -> object:
    """Build RPC call for start_service."""
    call = _CallType()
    _in = _CallType.in_structs[-522153841][1]()
    _in.req = Orchestration.ServiceRequest(service_id=service_id, configuration="")
    call.start_service = _in
    return call


def _make_stop_call(service_id: str) -> object:
    """Build RPC call for stop_service."""
    call = _CallType()
    _in = _CallType.in_structs[123337698][1]()
    _in.req = Orchestration.ServiceRequest(service_id=service_id, configuration="")
    call.stop_service = _in
    return call


def _make_get_capabilities_call() -> object:
    """Build RPC call for get_capabilities."""
    call = _CallType()
    call.get_capabilities = _CallType.in_structs[-385927898][1]()
    return call


def _make_get_health_call() -> object:
    """Build RPC call for get_health."""
    call = _CallType()
    call.get_health = _CallType.in_structs[-1076937166][1]()
    return call


def _extract_rpc_result(reply: object, op_name: str) -> str:
    """Extract a human-readable result from an RPC reply."""
    try:
        branch = getattr(reply, op_name)
        result = branch.result.return_
        if op_name == "start_service":
            return f"{result.code} — {result.message}"
        elif op_name == "stop_service":
            return f"{result.code} — {result.message}"
        elif op_name == "get_capabilities":
            return (
                f"services={result.supported_services}, " f"capacity={result.capacity}"
            )
        elif op_name == "get_health":
            return f"alive={result.alive}, summary={result.summary}"
        return str(result)
    except Exception as exc:
        return f"parse error: {exc}"


def _state_name(state: Orchestration.ServiceState) -> str:
    """Return a human-readable name for a ServiceState enum value."""
    _names = {
        Orchestration.ServiceState.STOPPED: "STOPPED",
        Orchestration.ServiceState.STARTING: "STARTING",
        Orchestration.ServiceState.RUNNING: "RUNNING",
        Orchestration.ServiceState.STOPPING: "STOPPING",
        Orchestration.ServiceState.FAILED: "FAILED",
        Orchestration.ServiceState.UNKNOWN: "UNKNOWN",
    }
    return _names.get(state, f"?({int(state)})")
