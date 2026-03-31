"""Procedure Controller — PySide6 GUI for orchestrating surgical services.

Subscribes to ServiceCatalog and ServiceStatus on the Orchestration domain
(Domain 15) via async DDS reads (``rti.asyncio`` / ``take_data_async``).
Issues RPC commands to Service Hosts via ServiceHostControl client stubs
on a worker thread. Reads scheduling context from the Hospital domain
(read-only).

Threading model:
  - DDS reads via async coroutines on the QtAsyncio event loop
  - RPC calls via native async Requester API (no thread pool)
  - No DDS writes on the UI thread (Procedure Controller has no writers)
  - Liveliness monitored via StatusCondition + WaitSet (event-driven)
  - Periodic UI consistency sweep rebuilds views from cached state (2 Hz)

Touch-friendly UI:
  - No tables — hosts and services rendered as large tappable cards
  - Two views: Host View (drill into host → services → actions) and
    Service View (flat list of services across all hosts)
  - Stat cards in the header bar are tappable to switch views
  - Refresh button for user-initiated data drain
  - All touch targets are at least 48×48 px (WCAG 2.5.8)

Follows the canonical application architecture in vision/dds-consistency.md §5.
Uses generated entity name constants from app_names.idl.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import app_names
import rti.connextdds as dds
import rti.rpc
from medtech.dds import initialize_connext
from medtech.gui import (
    ConnectionDot,
    create_empty_state,
    create_stat_card,
    create_status_chip,
    init_theme,
)
from medtech.log import ModuleName, init_logging
from orchestration import Orchestration
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

orch_names = app_names.MedtechEntityNames.OrchestrationParticipants

log = init_logging(ModuleName.HOSPITAL_DASHBOARD)

# RPC timeout
_RPC_TIMEOUT = dds.Duration(seconds=10)

# UI consistency sweep interval (seconds)
_UI_SWEEP_INTERVAL = 0.5

# View mode constants
_HOST_VIEW = 0
_SERVICE_VIEW = 1


class ProcedureController(QMainWindow):
    """PySide6 main window for orchestrating surgical services.

    Creates two DomainParticipants:
      - Orchestration domain: ServiceCatalog + ServiceStatus subscribers,
        ServiceHostControl RPC client
      - Hospital domain: read-only subscriber for scheduling context

    DDS data reception runs as async coroutines (QtAsyncio / rti.asyncio)
    so the Qt main thread is never blocked by DDS reads. The UI updates
    only when new data arrives (event-driven).

    Parameters
    ----------
    room_id:
        Operating room (e.g. "OR-1"). Sets the partition string.
    catalog_reader, status_reader:
        Optional pre-created DataReader objects for dependency injection
        in tests. When both are supplied, no DomainParticipants are
        created internally.
    """

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
        self._running = False
        self._tasks: list[asyncio.Task] = []

        # State tracking
        self._catalogs: dict[tuple[str, str], Orchestration.ServiceCatalog] = {}
        self._service_states: dict[tuple[str, str], Orchestration.ServiceStatus] = {}
        self._pub_handle_to_host: dict[dds.InstanceHandle, str] = {}

        # Single-selection tracking (only one item selected at a time)
        self._selected_host_id: Optional[str] = None
        self._selected_svc_key: Optional[tuple[str, str]] = None

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
        self._orch_participant.enable()

        self._catalog_reader = dds.DataReader(
            self._orch_participant.find_datareader(
                orch_names.CTRL_SERVICE_CATALOG_READER
            )
        )
        self._status_reader = dds.DataReader(
            self._orch_participant.find_datareader(
                orch_names.CTRL_SERVICE_STATUS_READER
            )
        )
        if self._catalog_reader is None:
            raise RuntimeError(
                f"Reader not found: {orch_names.CTRL_SERVICE_CATALOG_READER}"
            )
        if self._status_reader is None:
            raise RuntimeError(
                f"Reader not found: {orch_names.CTRL_SERVICE_STATUS_READER}"
            )

        log.notice("Orchestration participant created")

        # -- Hospital domain participant (read-only) --
        self._hosp_participant = provider.create_participant_from_config(
            orch_names.PROCEDURE_CONTROLLER_HOSPITAL
        )
        hosp_partition = f"room/{room_id}/procedure/*"
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
        root_layout = QVBoxLayout(central)
        root_layout.setSpacing(0)
        root_layout.setContentsMargins(0, 0, 0, 0)

        # Shared GUI header (RTI logo + theme + connection dot)
        app = QApplication.instance()
        if app is not None:
            header = init_theme(app)
            root_layout.addWidget(header)
            self._conn_dot = header.findChild(ConnectionDot)
        else:
            self._conn_dot = None

        # Content area — click background to deselect
        content = _ClickableWidget(on_click=self._deselect_all)
        content.setObjectName("contentArea")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 16)
        content_layout.setSpacing(16)

        # -- Stat cards row (tappable to switch views) --
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(12)
        self._stat_hosts = create_stat_card("0", "Hosts Online", "\u2302", "#004C97")
        self._stat_hosts.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stat_hosts.setToolTip("Tap to switch to Host View")
        self._stat_hosts.mousePressEvent = lambda _: self._switch_view(_HOST_VIEW)

        self._stat_services = create_stat_card(
            "0", "Services Running", "\u2699", "#A4D65E"
        )
        self._stat_services.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stat_services.setToolTip("Tap to switch to Service View")
        self._stat_services.mousePressEvent = lambda _: self._switch_view(_SERVICE_VIEW)

        self._stat_warnings = create_stat_card("0", "Warnings", "\u26A0", "#ED8B00")
        stats_layout.addWidget(self._stat_hosts)
        stats_layout.addWidget(self._stat_services)
        stats_layout.addWidget(self._stat_warnings)
        stats_layout.addStretch()

        # Refresh button
        self._btn_refresh = QPushButton("\u21BB  Refresh")
        self._btn_refresh.setObjectName("infoTile")
        self._btn_refresh.setToolTip("Refresh all data from DDS")
        self._btn_refresh.clicked.connect(self._on_refresh)
        stats_layout.addWidget(self._btn_refresh)

        content_layout.addLayout(stats_layout)

        # -- View mode toggle bar --
        toggle_bar = QHBoxLayout()
        toggle_bar.setSpacing(8)

        self._btn_host_view = QPushButton("\u2302  Host View")
        self._btn_host_view.setObjectName("viewToggleActive")
        self._btn_host_view.clicked.connect(lambda: self._switch_view(_HOST_VIEW))

        self._btn_svc_view = QPushButton("\u2699  Service View")
        self._btn_svc_view.setObjectName("viewToggle")
        self._btn_svc_view.clicked.connect(lambda: self._switch_view(_SERVICE_VIEW))

        toggle_bar.addWidget(self._btn_host_view)
        toggle_bar.addWidget(self._btn_svc_view)
        toggle_bar.addStretch()

        self._btn_start_all = QPushButton("\u25B6  Start All")
        self._btn_start_all.setObjectName("viewToggle")
        self._btn_start_all.setVisible(False)
        self._btn_start_all.clicked.connect(self._on_start_all)

        self._btn_stop_all = QPushButton("\u25A0  Stop All")
        self._btn_stop_all.setObjectName("viewToggle")
        self._btn_stop_all.setVisible(False)
        self._btn_stop_all.clicked.connect(self._on_stop_all)

        toggle_bar.addWidget(self._btn_start_all)
        toggle_bar.addWidget(self._btn_stop_all)
        content_layout.addLayout(toggle_bar)

        # -- Stacked widget: Host View (0) / Service View (1) --
        self._view_stack = QStackedWidget()

        # Host view — scrollable tile grid
        self._host_scroll = QScrollArea()
        self._host_scroll.setWidgetResizable(True)
        self._host_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._host_container = QWidget()
        self._host_flow = FlowLayout(self._host_container, hspacing=12, vspacing=12)
        self._host_scroll.setWidget(self._host_container)
        self._host_empty = create_empty_state(
            "Searching for service hosts\u2026", "\u25CE"
        )
        self._host_page = QStackedWidget()
        self._host_page.addWidget(self._host_empty)
        self._host_page.addWidget(self._host_scroll)
        self._view_stack.addWidget(self._host_page)

        # Service view — scrollable tile grid
        self._svc_scroll = QScrollArea()
        self._svc_scroll.setWidgetResizable(True)
        self._svc_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._svc_container = QWidget()
        self._svc_flow = FlowLayout(self._svc_container, hspacing=12, vspacing=12)
        self._svc_scroll.setWidget(self._svc_container)
        self._svc_empty = create_empty_state("No services reported yet", "\u2261")
        self._svc_page = QStackedWidget()
        self._svc_page.addWidget(self._svc_empty)
        self._svc_page.addWidget(self._svc_scroll)
        self._view_stack.addWidget(self._svc_page)

        content_layout.addWidget(self._view_stack, stretch=1)
        root_layout.addWidget(content, stretch=1)

        # -- Floating action overlay (bottom-center, above status bar) --
        self._action_overlay = QFrame(self)
        self._action_overlay.setObjectName("actionOverlay")
        self._action_overlay.setVisible(False)
        self._overlay_layout = QHBoxLayout(self._action_overlay)
        self._overlay_layout.setContentsMargins(20, 12, 20, 12)
        self._overlay_layout.setSpacing(12)

        # -- Floating result card (center, for health/capabilities) --
        self._result_card = QFrame(self)
        self._result_card.setObjectName("resultCard")
        self._result_card.setVisible(False)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Discovering service hosts\u2026")

        self.resize(900, 700)

    # ------------------------------------------------------------------ #
    # View switching                                                       #
    # ------------------------------------------------------------------ #

    def _switch_view(self, view: int) -> None:
        """Switch between Host View and Service View."""
        self._deselect_all()
        self._view_stack.setCurrentIndex(view)
        if view == _HOST_VIEW:
            self._btn_host_view.setObjectName("viewToggleActive")
            self._btn_svc_view.setObjectName("viewToggle")
            self._btn_start_all.setVisible(False)
            self._btn_stop_all.setVisible(False)
        else:
            self._btn_host_view.setObjectName("viewToggle")
            self._btn_svc_view.setObjectName("viewToggleActive")
            self._btn_start_all.setVisible(True)
            self._btn_stop_all.setVisible(True)
        # Force style refresh after objectName change
        self._btn_host_view.style().unpolish(self._btn_host_view)
        self._btn_host_view.style().polish(self._btn_host_view)
        self._btn_svc_view.style().unpolish(self._btn_svc_view)
        self._btn_svc_view.style().polish(self._btn_svc_view)

    # ------------------------------------------------------------------ #
    # Selection management                                                 #
    # ------------------------------------------------------------------ #

    def _select_host(self, host_id: str) -> None:
        """Select a host tile and show action overlay."""
        if self._selected_host_id == host_id:
            self._deselect_all()
            return
        self._selected_host_id = host_id
        self._selected_svc_key = None
        self._show_action_overlay()
        self._update_tile_highlights()

    def _select_service(self, host_id: str, service_id: str) -> None:
        """Select a service tile and show action overlay."""
        svc_key = (host_id, service_id)
        if self._selected_svc_key == svc_key:
            self._deselect_all()
            return
        self._selected_svc_key = svc_key
        self._selected_host_id = host_id
        self._show_action_overlay()
        self._update_tile_highlights()

    def _deselect_all(self) -> None:
        """Clear selection and hide action overlay."""
        self._selected_host_id = None
        self._selected_svc_key = None
        self._action_overlay.setVisible(False)
        self._update_tile_highlights()

    def _update_tile_highlights(self) -> None:
        """Update the 'selected' dynamic property on all tiles for QSS."""
        for container in (self._host_container, self._svc_container):
            for child in container.findChildren(QFrame):
                obj_name = child.objectName()
                if obj_name == "hostCard":
                    is_sel = child.property("hostId") == self._selected_host_id
                    child.setProperty("selected", is_sel)
                elif obj_name == "serviceCard":
                    h = child.property("hostId")
                    s = child.property("serviceId")
                    is_sel = self._selected_svc_key == (h, s)
                    child.setProperty("selected", is_sel)
                else:
                    continue
                child.style().unpolish(child)
                child.style().polish(child)

    # ------------------------------------------------------------------ #
    # Action overlay positioning                                           #
    # ------------------------------------------------------------------ #

    def _show_action_overlay(self) -> None:
        """Show the floating action overlay with context-appropriate buttons."""
        # Clear previous buttons
        while self._overlay_layout.count():
            item = self._overlay_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if self._selected_svc_key:
            # Service selected: show Start/Configure + Stop
            host_id, svc_id = self._selected_svc_key
            status = self._service_states.get(self._selected_svc_key)
            is_running = status is not None and _state_name(status.state).upper() in (
                "RUNNING",
                "STARTED",
                "ACTIVE",
            )
            if is_running:
                btn_cfg = QPushButton("\u2699  Update")
                btn_cfg.setObjectName("infoTile")
                btn_cfg.clicked.connect(self._on_update_selected)
                self._overlay_layout.addWidget(btn_cfg)
            else:
                btn_start = QPushButton("\u25B6  Start")
                btn_start.setObjectName("actionTile")
                btn_start.clicked.connect(self._on_start_selected)
                self._overlay_layout.addWidget(btn_start)

            btn_stop = QPushButton("\u25A0  Stop")
            btn_stop.setObjectName("stopTile")
            btn_stop.clicked.connect(self._on_stop_selected)
            self._overlay_layout.addWidget(btn_stop)
        elif self._selected_host_id:
            # Host selected: show Health + Capabilities
            btn_health = QPushButton("\u2764  Health")
            btn_health.setObjectName("infoTile")
            btn_health.clicked.connect(self._on_health_selected)
            self._overlay_layout.addWidget(btn_health)

            btn_caps = QPushButton("\u2699  Capabilities")
            btn_caps.setObjectName("infoTile")
            btn_caps.clicked.connect(self._on_capabilities_selected)
            self._overlay_layout.addWidget(btn_caps)

        self._action_overlay.setVisible(True)
        self._position_action_overlay()

    def _position_action_overlay(self) -> None:
        """Center the action overlay at the bottom of the window."""
        overlay = self._action_overlay
        # Force the layout to recalculate after adding/removing buttons
        overlay.layout().activate()
        QApplication.processEvents()
        ow = max(overlay.sizeHint().width(), 200)
        oh = max(overlay.sizeHint().height(), 52)
        x = (self.width() - ow) // 2
        y = self.height() - oh - 40
        overlay.setGeometry(x, y, ow, oh)
        overlay.raise_()

    # ------------------------------------------------------------------ #
    # Tile builders                                                        #
    # ------------------------------------------------------------------ #

    def _build_host_tile(
        self, host_id: str, services: dict[str, Orchestration.ServiceCatalog]
    ) -> QFrame:
        """Build a fixed-size tappable tile for a service host."""
        tile = QFrame()
        tile.setObjectName("hostCard")
        tile.setProperty("hostId", host_id)
        tile.setFixedSize(_TILE_W, _TILE_H)
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(14, 12, 14, 12)
        tile_layout.setSpacing(4)

        name_lbl = QLabel(f"\u2302  {host_id}")
        name_lbl.setObjectName("cardTitle")
        name_lbl.setWordWrap(True)
        tile_layout.addWidget(name_lbl)

        svc_count = len(services)
        count_lbl = QLabel(f"{svc_count} service{'s' if svc_count != 1 else ''}")
        count_lbl.setObjectName("cardMeta")
        tile_layout.addWidget(count_lbl)

        # Aggregate health from individual ServiceCatalog entries
        summaries = [
            cat.health_summary for cat in services.values() if cat.health_summary
        ]
        if summaries:
            health_lbl = QLabel("; ".join(summaries))
            health_lbl.setObjectName("cardDescription")
            health_lbl.setWordWrap(True)
            tile_layout.addWidget(health_lbl)

        tile_layout.addStretch()
        tile.setCursor(Qt.CursorShape.PointingHandCursor)
        tile.mousePressEvent = lambda ev, hid=host_id: (
            ev.accept(),
            self._select_host(hid),
        )
        return tile

    def _build_service_tile(
        self,
        host_id: str,
        service_id: str,
        status: Optional[Orchestration.ServiceStatus],
        show_host: bool = False,
    ) -> QFrame:
        """Build a fixed-size tappable tile for a service."""
        tile = QFrame()
        tile.setObjectName("serviceCard")
        tile.setProperty("hostId", host_id)
        tile.setProperty("serviceId", service_id)
        tile.setFixedSize(_TILE_W, _TILE_H)
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(14, 12, 14, 12)
        tile_layout.setSpacing(4)

        name_lbl = QLabel(f"\u2699  {service_id}")
        name_lbl.setObjectName("cardTitle")
        name_lbl.setMaximumHeight(36)
        name_lbl.setWordWrap(False)
        tile_layout.addWidget(name_lbl)

        if show_host:
            host_lbl = QLabel(f"Host: {host_id}")
            host_lbl.setObjectName("cardMeta")
            tile_layout.addWidget(host_lbl)

        if status is not None:
            state_name = _state_name(status.state)
            chip = create_status_chip(state_name)
            tile_layout.addWidget(chip)
        else:
            tile_layout.addWidget(create_status_chip("UNKNOWN"))

        tile_layout.addStretch()
        tile.setCursor(Qt.CursorShape.PointingHandCursor)
        tile.mousePressEvent = lambda ev, h=host_id, s=service_id: (
            ev.accept(),
            self._select_service(h, s),
        )
        return tile

    # ------------------------------------------------------------------ #
    # View rebuilders (called only on data change)                         #
    # ------------------------------------------------------------------ #

    def _rebuild_host_view(self) -> None:
        """Rebuild the Host View tile grid from current state."""
        host_services = self._services_by_host()
        if not host_services:
            self._host_page.setCurrentIndex(0)
            return
        self._host_page.setCurrentIndex(1)

        _clear_flow(self._host_flow)

        for host_id in sorted(host_services):
            tile = self._build_host_tile(host_id, host_services[host_id])
            self._host_flow.addWidget(tile)

        self._update_tile_highlights()

    def _rebuild_service_view(self) -> None:
        """Rebuild the Service View tile grid from current state."""
        if not self._service_states:
            self._svc_page.setCurrentIndex(0)
            return
        self._svc_page.setCurrentIndex(1)

        _clear_flow(self._svc_flow)

        for (host_id, svc_id), status in sorted(self._service_states.items()):
            tile = self._build_service_tile(host_id, svc_id, status, show_host=True)
            self._svc_flow.addWidget(tile)

        self._update_tile_highlights()

    def _refresh_stat_cards(self) -> None:
        """Update the summary KPI stat cards."""
        host_val = self._stat_hosts.findChild(QLabel, "statValue")
        if host_val is not None:
            host_val.setText(str(len(self._services_by_host())))

        running = sum(
            1
            for s in self._service_states.values()
            if _state_name(s.state).upper() in ("RUNNING", "STARTED", "ACTIVE")
        )
        svc_val = self._stat_services.findChild(QLabel, "statValue")
        if svc_val is not None:
            svc_val.setText(str(running))

        warnings = sum(
            1
            for s in self._service_states.values()
            if _state_name(s.state).upper() in ("WARNING", "PAUSED", "ERROR")
        )
        warn_val = self._stat_warnings.findChild(QLabel, "statValue")
        if warn_val is not None:
            warn_val.setText(str(warnings))

    # ------------------------------------------------------------------ #
    # Async DDS receive loops                                              #
    # ------------------------------------------------------------------ #

    async def _receive_service_catalog(self) -> None:
        """Consume ServiceCatalog samples asynchronously.

        Uses ``take_async()`` (not ``take_data_async()``) so we can
        capture the publication handle from SampleInfo for each writer.
        This mapping lets ``_monitor_liveliness`` identify *which* host
        died when a writer loses liveliness.
        """
        async for sample in self._catalog_reader.take_async():
            if sample.info.valid:
                self._pub_handle_to_host[sample.info.publication_handle] = (
                    sample.data.host_id
                )
                self._update_catalog(sample.data)

    async def _receive_service_status(self) -> None:
        """Consume ServiceStatus samples asynchronously."""
        async for data in self._status_reader.take_data_async():
            self._update_service_status(data)

    async def _monitor_liveliness(self) -> None:
        """Monitor ServiceCatalog writer liveliness via StatusCondition.

        Uses ``wait_async`` (not ``dispatch_async``) so that the
        liveliness-change processing runs inline on the asyncio/Qt
        event-loop thread.  ``dispatch_async`` invokes the handler on a
        DDS internal thread, which is unsafe for Qt widget operations.
        """
        status_cond = dds.StatusCondition(self._catalog_reader)
        status_cond.enabled_statuses = dds.StatusMask.LIVELINESS_CHANGED

        waitset = dds.WaitSet()
        waitset += status_cond
        try:
            while self._running:
                try:
                    await waitset.wait_async(dds.Duration(seconds=1))
                except dds.TimeoutError:
                    continue

                # Back on the event-loop thread — safe to touch Qt widgets
                changed = self._catalog_reader.status_changes
                if dds.StatusMask.LIVELINESS_CHANGED not in changed:
                    continue
                # Reading the status resets the condition trigger
                st = self._catalog_reader.liveliness_changed_status
                if self._conn_dot is not None:
                    self._conn_dot.set_connected(st.alive_count > 0)

                if st.not_alive_count_change > 0:
                    # Identify the dead host via cached handle mapping
                    host_id = self._pub_handle_to_host.pop(
                        st.last_publication_handle, None
                    )
                    if host_id is not None:
                        self._remove_host(host_id)
                    # Fallback: if no writers remain, purge all hosts
                    if st.alive_count == 0 and self._catalogs:
                        for hid in list(self._known_host_ids()):
                            self._remove_host(hid)
                        self._pub_handle_to_host.clear()
        finally:
            waitset -= status_cond

    def _known_host_ids(self) -> set[str]:
        """Derive unique host IDs from the catalog keys."""
        return {host_id for host_id, _ in self._catalogs}

    def _services_by_host(self) -> dict[str, dict[str, Orchestration.ServiceCatalog]]:
        """Group catalog entries by host_id."""
        result: dict[str, dict[str, Orchestration.ServiceCatalog]] = {}
        for (host_id, svc_id), cat in self._catalogs.items():
            result.setdefault(host_id, {})[svc_id] = cat
        return result

    def _update_catalog(self, catalog: Orchestration.ServiceCatalog) -> None:
        """Process a ServiceCatalog sample and update the UI."""
        key = (catalog.host_id, catalog.service_id)
        self._catalogs[key] = catalog
        self._rebuild_host_view()
        self._refresh_stat_cards()
        if self._conn_dot is not None:
            self._conn_dot.set_connected(True)
        host_count = len(self._known_host_ids())
        self._status_bar.showMessage(f"Discovered {host_count} host(s)", 3000)
        log.informational(
            f"ServiceCatalog received: host_id={catalog.host_id}, "
            f"service_id={catalog.service_id}"
        )

    def _remove_host(self, host_id: str) -> None:
        """Remove a host and its services after liveliness loss."""
        dead_catalog_keys = [k for k in self._catalogs if k[0] == host_id]
        for k in dead_catalog_keys:
            del self._catalogs[k]
        dead_keys = [k for k in self._service_states if k[0] == host_id]
        for k in dead_keys:
            del self._service_states[k]
        # Close stale RPC requester for this host
        req = self._requesters.pop(host_id, None)
        if req is not None:
            try:
                req.close()
            except Exception:
                pass
        # Clear selection if it pointed at the dead host
        if self._selected_host_id == host_id:
            self._deselect_all()
        self._rebuild_host_view()
        self._rebuild_service_view()
        self._refresh_stat_cards()
        self._status_bar.showMessage(f"Host {host_id} disconnected", 5000)
        log.warning(f"Host {host_id} lost liveliness \u2014 removed")

    def _update_service_status(self, status: Orchestration.ServiceStatus) -> None:
        """Process a ServiceStatus sample and update the UI."""
        key = (status.host_id, status.service_id)
        self._service_states[key] = status
        self._rebuild_host_view()
        self._rebuild_service_view()
        self._refresh_stat_cards()

    # ------------------------------------------------------------------ #
    # Lifecycle (async)                                                    #
    # ------------------------------------------------------------------ #

    async def _ui_consistency_sweep(self) -> None:
        """Periodic UI rebuild from in-memory state.

        Catches any missed visual updates without re-reading from DDS
        (avoids sample-stealing race with take_data_async). Runs at
        ~2 Hz — lightweight since it only touches cached dicts.
        """
        while self._running:
            await asyncio.sleep(_UI_SWEEP_INTERVAL)
            self._rebuild_host_view()
            self._rebuild_service_view()
            self._refresh_stat_cards()

    async def start(self) -> None:
        """Start all async DDS receive tasks."""
        self._running = True
        loop = asyncio.get_event_loop()
        self._tasks = [
            loop.create_task(self._receive_service_catalog()),
            loop.create_task(self._receive_service_status()),
            loop.create_task(self._monitor_liveliness()),
            loop.create_task(self._ui_consistency_sweep()),
        ]
        log.informational("ProcedureController: async DDS receive tasks started")

    def stop(self) -> None:
        """Signal async tasks to stop and schedule async cleanup."""
        self._running = False
        asyncio.ensure_future(self._async_cleanup())

    async def _async_cleanup(self) -> None:
        """Cancel tasks, await their unwinding, then close participants."""
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        self._close_participants()

    def _on_refresh(self) -> None:
        """User-initiated refresh: drain both readers synchronously."""
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
        self._status_bar.showMessage("Refreshed", 2000)

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

    async def _do_rpc(self, host_id: str, call: object, op_name: str) -> None:
        """Execute a single RPC call using native async Requester API.

        Uses ``send_request`` (non-blocking write) followed by
        ``await wait_for_replies_async`` and ``take_replies`` so the
        Qt/asyncio event loop is never blocked.  No thread pool needed.
        """
        try:
            req = self._get_requester(host_id)
            ok = await req.wait_for_service_async(_RPC_TIMEOUT)
            if not ok:
                msg = f"{host_id}: service not available"
            else:
                request_id = req.send_request(call)
                ok = await req.wait_for_replies_async(
                    max_wait=_RPC_TIMEOUT,
                    related_request_id=request_id,
                )
                if not ok:
                    msg = f"{host_id}: timeout \u2014 no reply received"
                else:
                    replies = req.take_replies(related_request_id=request_id)
                    result = None
                    for reply, info in replies:
                        if info.valid:
                            result = _extract_rpc_result(reply, op_name)
                            break
                    msg = (
                        f"{host_id}: {result}"
                        if result
                        else (f"{host_id}: no valid reply")
                    )
        except Exception as exc:
            msg = f"{host_id}: error \u2014 {exc}"

        self._status_bar.showMessage(f"{op_name}: {msg}", 5000)
        log.informational(f"RPC {op_name}: {msg}")
        # Drain latest DDS data so service states are current
        self._on_refresh()
        # Refresh the action overlay to reflect new state
        if self._selected_svc_key or self._selected_host_id:
            self._show_action_overlay()

    async def _do_rpc_batch(self, calls: list[tuple[str, object, str]]) -> None:
        """Execute a batch of RPC calls sequentially via the executor."""
        for host_id, call, op_name in calls:
            await self._do_rpc(host_id, call, op_name)

    # ------------------------------------------------------------------ #
    # RPC action handlers (from action bar)                                #
    # ------------------------------------------------------------------ #

    def _on_start_selected(self) -> None:
        """Start the selected service."""
        if self._selected_svc_key:
            host_id, svc_id = self._selected_svc_key
            self._on_start(host_id, svc_id)

    def _on_stop_selected(self) -> None:
        """Stop the selected service."""
        if self._selected_svc_key:
            host_id, svc_id = self._selected_svc_key
            self._on_stop(host_id, svc_id)

    def _on_update_selected(self) -> None:
        """Update the selected service."""
        if self._selected_svc_key:
            host_id, svc_id = self._selected_svc_key
            self._on_update(host_id, svc_id)

    def _on_capabilities_selected(self) -> None:
        """Query capabilities of the selected host."""
        if self._selected_host_id:
            self._on_capabilities(self._selected_host_id)

    def _on_health_selected(self) -> None:
        """Query health of the selected host."""
        if self._selected_host_id:
            self._on_health(self._selected_host_id)

    def _on_start_all(self) -> None:
        """Start all discovered services across all hosts."""
        calls = []
        for host_id, svc_id in self._catalogs:
            calls.append((host_id, _make_start_call(svc_id), "start_service"))
        if calls:
            self._status_bar.showMessage(f"Starting {len(calls)} service(s)\u2026")
            asyncio.get_event_loop().create_task(self._do_rpc_batch(calls))

    def _on_stop_all(self) -> None:
        """Stop all discovered services across all hosts."""
        calls = []
        for host_id, svc_id in self._catalogs:
            calls.append((host_id, _make_stop_call(svc_id), "stop_service"))
        if calls:
            self._status_bar.showMessage(f"Stopping {len(calls)} service(s)\u2026")
            asyncio.get_event_loop().create_task(self._do_rpc_batch(calls))

    def _on_start(self, host_id: str, service_id: str) -> None:
        """Handle Start action for a specific service."""
        call = _make_start_call(service_id)
        self._status_bar.showMessage(f"Starting {service_id} on {host_id}\u2026")
        asyncio.get_event_loop().create_task(
            self._do_rpc(host_id, call, "start_service")
        )

    def _on_stop(self, host_id: str, service_id: str) -> None:
        """Handle Stop action for a specific service."""
        call = _make_stop_call(service_id)
        self._status_bar.showMessage(f"Stopping {service_id} on {host_id}\u2026")
        asyncio.get_event_loop().create_task(
            self._do_rpc(host_id, call, "stop_service")
        )

    def _on_update(self, host_id: str, service_id: str) -> None:
        """Handle Update action for a specific service."""
        call = _make_update_call(service_id)
        self._status_bar.showMessage(f"Updating {service_id} on {host_id}\u2026")
        asyncio.get_event_loop().create_task(
            self._do_rpc(host_id, call, "update_service")
        )

    def _on_capabilities(self, host_id: str) -> None:
        """Handle Capabilities query for a host."""
        call = _make_get_capabilities_call()
        self._status_bar.showMessage(f"Querying capabilities of {host_id}\u2026")
        asyncio.get_event_loop().create_task(
            self._do_rpc_display(host_id, call, "get_capabilities")
        )

    def _on_health(self, host_id: str) -> None:
        """Handle Health query for a host."""
        call = _make_get_health_call()
        self._status_bar.showMessage(f"Querying health of {host_id}\u2026")
        asyncio.get_event_loop().create_task(
            self._do_rpc_display(host_id, call, "get_health")
        )

    async def _do_rpc_display(self, host_id: str, call: object, op_name: str) -> None:
        """Execute an RPC and show the result in a floating card."""
        try:
            req = self._get_requester(host_id)
            ok = await req.wait_for_service_async(_RPC_TIMEOUT)
            if not ok:
                self._show_result_card(host_id, op_name, "Service not available")
                return

            request_id = req.send_request(call)
            ok = await req.wait_for_replies_async(
                max_wait=_RPC_TIMEOUT,
                related_request_id=request_id,
            )
            if not ok:
                self._show_result_card(host_id, op_name, "No reply received")
                return

            replies = req.take_replies(related_request_id=request_id)
            result = None
            for reply, info in replies:
                if info.valid:
                    branch = getattr(reply, op_name)
                    result = branch.result.return_
                    break

            if result is None:
                self._show_result_card(host_id, op_name, "No reply received")
            elif op_name == "get_capabilities":
                self._show_result_card(
                    host_id,
                    "Capabilities",
                    None,
                    [
                        ("Capacity", str(result.capacity)),
                    ],
                )
            elif op_name == "get_health":
                self._show_result_card(
                    host_id,
                    "Health",
                    None,
                    [
                        ("Alive", "\u25CF  Yes" if result.alive else "\u25CB  No"),
                        ("Summary", result.summary or "\u2014"),
                        ("Diagnostics", result.diagnostics or "\u2014"),
                    ],
                )
            else:
                self._show_result_card(host_id, op_name, str(result))
        except Exception as exc:
            self._show_result_card(host_id, op_name, f"Error: {exc}")

    # ------------------------------------------------------------------ #
    # Result card overlay                                                  #
    # ------------------------------------------------------------------ #

    def _show_result_card(
        self,
        host_id: str,
        title: str,
        message: Optional[str] = None,
        rows: Optional[list[tuple[str, str]]] = None,
    ) -> None:
        """Show a floating result card with structured RPC response data."""
        card = self._result_card

        # Clear previous content
        old_layout = card.layout()
        if old_layout is not None:
            while old_layout.count():
                item = old_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
                sub = item.layout()
                if sub is not None:
                    while sub.count():
                        si = sub.takeAt(0)
                        sw = si.widget()
                        if sw is not None:
                            sw.deleteLater()
        else:
            old_layout = QVBoxLayout(card)
            old_layout.setContentsMargins(24, 20, 24, 20)
            old_layout.setSpacing(12)

        layout = old_layout

        # Header row: title + close button
        header = QHBoxLayout()
        title_lbl = QLabel(f"\u2302  {host_id} \u2014 {title}")
        title_lbl.setObjectName("cardTitle")
        header.addWidget(title_lbl)
        header.addStretch()
        close_btn = QPushButton("\u2715")
        close_btn.setObjectName("resultClose")
        close_btn.setFixedSize(32, 32)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self._dismiss_result_card)
        header.addWidget(close_btn)
        layout.addLayout(header)

        if message:
            msg_lbl = QLabel(message)
            msg_lbl.setObjectName("cardDescription")
            msg_lbl.setWordWrap(True)
            layout.addWidget(msg_lbl)

        if rows:
            for label, value in rows:
                row = QHBoxLayout()
                row.setSpacing(12)
                key_lbl = QLabel(label)
                key_lbl.setObjectName("cardMeta")
                key_lbl.setMinimumWidth(90)
                val_lbl = QLabel(value)
                val_lbl.setObjectName("cardDescription")
                val_lbl.setWordWrap(True)
                row.addWidget(key_lbl)
                row.addWidget(val_lbl, stretch=1)
                layout.addLayout(row)

        card.setVisible(True)
        self._position_result_card()

    def _dismiss_result_card(self) -> None:
        """Hide the result card overlay."""
        self._result_card.setVisible(False)

    def _position_result_card(self) -> None:
        """Center the result card in the window."""
        card = self._result_card
        card.adjustSize()
        cw = min(card.sizeHint().width(), self.width() - 40)
        ch = min(card.sizeHint().height(), self.height() - 100)
        cw = max(cw, 320)
        ch = max(ch, 120)
        x = (self.width() - cw) // 2
        y = (self.height() - ch) // 2
        card.setGeometry(x, y, cw, ch)
        card.raise_()

    # ------------------------------------------------------------------ #
    # Public accessors (for testing)                                       #
    # ------------------------------------------------------------------ #

    @property
    def catalogs(self) -> dict[tuple[str, str], Orchestration.ServiceCatalog]:
        """Currently discovered service catalogs."""
        return dict(self._catalogs)

    @property
    def hosts(self) -> set[str]:
        """Currently discovered host IDs."""
        return self._known_host_ids()

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

    def _close_participants(self) -> None:
        """Close DDS participants and RPC requesters."""
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

    def close_dds(self) -> None:
        """Close DDS resources (legacy compat + test cleanup)."""
        self._running = False
        self._close_participants()

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt override
        """Reposition floating overlays on window resize."""
        super().resizeEvent(event)
        if hasattr(self, "_action_overlay") and self._action_overlay.isVisible():
            self._position_action_overlay()
        if hasattr(self, "_result_card") and self._result_card.isVisible():
            self._position_result_card()

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt override
        """Qt close event: cancel async tasks (DDS cleanup in __main__)."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Layout utilities
# ---------------------------------------------------------------------------

# Tile dimensions (touch-friendly: min 48 px targets, enough for content)
_TILE_W = 200
_TILE_H = 160


def _clear_flow(layout: "FlowLayout") -> None:
    """Remove all widgets from a FlowLayout."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


class _ClickableWidget(QWidget):
    """QWidget that calls *on_click* when clicked on empty space."""

    def __init__(
        self, on_click: Optional[object] = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._on_click = on_click

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._on_click is not None:
            self._on_click()
        super().mousePressEvent(event)


class FlowLayout(QLayout):
    """A flow layout that arranges widgets left-to-right, wrapping to the
    next row when the container width is exceeded.

    Based on the Qt C++ FlowLayout example, adapted for PySide6.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        hspacing: int = 12,
        vspacing: int = 12,
    ) -> None:
        super().__init__(parent)
        self._hspacing = hspacing
        self._vspacing = vspacing
        self._items: list[QWidgetItem] = []

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        row_height = 0

        for item in self._items:
            sz = item.sizeHint()
            next_x = x + sz.width() + self._hspacing
            if next_x - self._hspacing > effective.right() and row_height > 0:
                x = effective.x()
                y = y + row_height + self._vspacing
                next_x = x + sz.width() + self._hspacing
                row_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), sz))
            x = next_x
            row_height = max(row_height, sz.height())

        return y + row_height - rect.y() + m.bottom()


# ---------------------------------------------------------------------------
# RPC call builders
# ---------------------------------------------------------------------------

_CallType = Orchestration.ServiceHostControl.call_type


def _make_start_call(service_id: str) -> object:
    """Build RPC call for start_service."""
    call = _CallType()
    _in = _CallType.in_structs[-522153841][1]()
    _in.req = Orchestration.ServiceRequest(service_id=service_id, properties=[])
    call.start_service = _in
    return call


def _make_stop_call(service_id: str) -> object:
    """Build RPC call for stop_service."""
    call = _CallType()
    _in = _CallType.in_structs[123337698][1]()
    _in.service_id = service_id
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


def _make_update_call(service_id: str, properties: list | None = None) -> object:
    """Build RPC call for update_service."""
    call = _CallType()
    _in = _CallType.in_structs[312505061][1]()
    _in.req = Orchestration.ServiceRequest(
        service_id=service_id, properties=properties or []
    )
    call.update_service = _in
    return call


def _extract_rpc_result(reply: object, op_name: str) -> str:
    """Extract a human-readable result from an RPC reply."""
    try:
        branch = getattr(reply, op_name)
        result = branch.result.return_
        if op_name == "start_service":
            return f"{result.code} \u2014 {result.message}"
        elif op_name == "stop_service":
            return f"{result.code} \u2014 {result.message}"
        elif op_name == "update_service":
            return f"{result.code} \u2014 {result.message}"
        elif op_name == "get_capabilities":
            return f"capacity={result.capacity}"
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
