"""Digital twin display — PySide6 main window for surgical robot visualization.

Subscribes to the Procedure domain (control tag) and renders a live 2D
robot visualization. Data reception uses QtAsyncio + rti.asyncio async
generators so DDS reads never block the Qt main thread.

Subscriptions:
  - RobotState        (GuiRobotState QoS — TBF 100 ms)
  - OperatorInput     (GuiOperatorInput QoS — TBF 100 ms)
  - SafetyInterlock   (SafetyInterlock QoS — no TBF, safety-critical)
  - RobotCommand      (RobotCommand QoS — no TBF, command delivery)

Connectivity monitoring: a periodic liveliness check coroutine polls
``reader.liveliness_changed_status`` and calls
``_robot_widget.set_connected(False)`` when no alive writers remain.

All QoS is loaded from XML (NDDS_QOS_PROFILES). No programmatic QoS
except partition, which is set from runtime context after participant
creation per vision/data-model.md.

Follows the canonical application architecture in vision/dds-consistency.md §3.
Uses generated entity name constants from app_names.idl.
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

import app_names
import rti.asyncio  # enables take_data_async() on DataReader
import rti.connextdds as dds
import surgery
from medtech_dds_init.dds_init import initialize_connext
from medtech_logging import ModuleName, init_logging
from medtech_gui import init_theme
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from ._robot_widget import RobotWidget

names = app_names.MedtechEntityNames.SurgicalParticipants

RobotState = surgery.Surgery.RobotState
RobotCommand = surgery.Surgery.RobotCommand
SafetyInterlock = surgery.Surgery.SafetyInterlock
OperatorInput = surgery.Surgery.OperatorInput

log = init_logging(ModuleName.SURGICAL_PROCEDURE)

# Liveliness poll interval (seconds)
_LIVELINESS_POLL_INTERVAL = 0.5


class DigitalTwinDisplay(QMainWindow):
    """PySide6 main window displaying the surgical robot digital twin.

    DDS data reception runs as async coroutines (QtAsyncio / rti.asyncio)
    so the Qt main thread is never blocked by DDS reads.

    Parameters
    ----------
    room_id:
        Procedure room (e.g. "OR-1"). Sets the partition string.
    procedure_id:
        Procedure identifier. Sets the partition string.
    robot_state_reader, robot_command_reader,
    safety_interlock_reader, operator_input_reader:
        Optional pre-created DataReader objects for dependency injection
        in tests. When all four are supplied, no DomainParticipant is
        created internally.  When any is omitted, all are created from
        the ``ControlDigitalTwin`` participant configuration.
    """

    def __init__(
        self,
        room_id: str = "OR-1",
        procedure_id: str = "proc-001",
        *,
        robot_state_reader: Optional[dds.DataReader] = None,
        robot_command_reader: Optional[dds.DataReader] = None,
        safety_interlock_reader: Optional[dds.DataReader] = None,
        operator_input_reader: Optional[dds.DataReader] = None,
    ) -> None:
        super().__init__()
        self._room_id = room_id
        self._procedure_id = procedure_id
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._participant: Optional[dds.DomainParticipant] = None

        # ---- DDS readers ------------------------------------------------
        injected = all(
            r is not None
            for r in (
                robot_state_reader,
                robot_command_reader,
                safety_interlock_reader,
                operator_input_reader,
            )
        )
        if injected:
            self._robot_state_reader = dds.DataReader(robot_state_reader)
            self._robot_command_reader = dds.DataReader(robot_command_reader)
            self._safety_interlock_reader = dds.DataReader(
                safety_interlock_reader
            )
            self._operator_input_reader = dds.DataReader(operator_input_reader)
        else:
            self._init_dds(room_id, procedure_id)

        # ---- Qt widgets -------------------------------------------------
        self.setWindowTitle("Medtech Suite — Surgical Robot Digital Twin")
        self._setup_ui()

    # ------------------------------------------------------------------ #
    # DDS initialization                                                   #
    # ------------------------------------------------------------------ #

    def _init_dds(self, room_id: str, procedure_id: str) -> None:
        """Create the ControlDigitalTwin participant and find readers."""
        initialize_connext()

        provider = dds.QosProvider.default
        self._participant = provider.create_participant_from_config(
            names.CONTROL_DIGITAL_TWIN
        )

        partition = f"room/{room_id}/procedure/{procedure_id}"
        qos = self._participant.qos
        qos.partition.name = [partition]
        self._participant.qos = qos

        def _find_reader(entity_name: str) -> dds.DataReader:
            r = self._participant.find_datareader(entity_name)
            if r is None:
                raise RuntimeError(f"Reader not found: {entity_name}")
            return dds.DataReader(r)

        self._robot_state_reader = _find_reader(names.TWIN_ROBOT_STATE_READER)
        self._robot_command_reader = _find_reader(
            names.TWIN_ROBOT_COMMAND_READER
        )
        self._safety_interlock_reader = _find_reader(
            names.TWIN_SAFETY_INTERLOCK_READER
        )
        self._operator_input_reader = _find_reader(
            names.TWIN_OPERATOR_INPUT_READER
        )

    # ------------------------------------------------------------------ #
    # Qt widget setup                                                       #
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # Shared GUI header (RTI logo + theme)
        app = self._qt_app()
        if app is not None:
            header = init_theme(app)
            layout.addWidget(header)

        self._robot_widget = RobotWidget()
        layout.addWidget(self._robot_widget, stretch=1)
        self.resize(640, 500)

    @staticmethod
    def _qt_app():
        from PySide6.QtWidgets import QApplication
        return QApplication.instance()

    # ------------------------------------------------------------------ #
    # Async DDS receive loops                                              #
    # ------------------------------------------------------------------ #

    async def _receive_robot_state(self) -> None:
        """Consume RobotState samples asynchronously."""
        async for data in self._robot_state_reader.take_data_async():
            self._robot_widget.update_robot_state(data)

    async def _receive_robot_command(self) -> None:
        """Consume RobotCommand samples asynchronously."""
        async for data in self._robot_command_reader.take_data_async():
            self._robot_widget.update_command(data)

    async def _receive_safety_interlock(self) -> None:
        """Consume SafetyInterlock samples asynchronously."""
        async for data in self._safety_interlock_reader.take_data_async():
            self._robot_widget.update_interlock(data)

    async def _receive_operator_input(self) -> None:
        """Consume OperatorInput samples asynchronously (for telemetry)."""
        async for data in self._operator_input_reader.take_data_async():
            # OperatorInput is received for diagnostics / future rendering.
            # Current implementation logs at TRACE level only.
            pass

    async def _monitor_liveliness(self) -> None:
        """Periodically check RobotState writer liveliness."""
        while self._running:
            status = self._robot_state_reader.liveliness_changed_status
            if status.alive_count == 0 and status.not_alive_count > 0:
                self._robot_widget.set_connected(False)
            elif status.alive_count > 0:
                self._robot_widget.set_connected(True)
            await asyncio.sleep(_LIVELINESS_POLL_INTERVAL)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """Start all async DDS receive tasks."""
        self._running = True
        loop = asyncio.get_event_loop()
        self._tasks = [
            loop.create_task(self._receive_robot_state()),
            loop.create_task(self._receive_robot_command()),
            loop.create_task(self._receive_safety_interlock()),
            loop.create_task(self._receive_operator_input()),
            loop.create_task(self._monitor_liveliness()),
        ]
        log.informational("DigitalTwinDisplay: async DDS receive tasks started")

    def stop(self) -> None:
        """Cancel all async tasks and close the participant."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        if self._participant is not None:
            try:
                self._participant.close()
            except dds.AlreadyClosedError:
                pass
            self._participant = None
        log.informational("DigitalTwinDisplay: stopped")

    def closeEvent(self, event) -> None:  # noqa: N802
        self.stop()
        super().closeEvent(event)

    # ------------------------------------------------------------------ #
    # Read-only accessors (for tests)                                      #
    # ------------------------------------------------------------------ #

    @property
    def robot_widget(self) -> RobotWidget:
        return self._robot_widget

    @property
    def robot_state_reader(self) -> dds.DataReader:
        return self._robot_state_reader

    @property
    def robot_command_reader(self) -> dds.DataReader:
        return self._robot_command_reader

    @property
    def safety_interlock_reader(self) -> dds.DataReader:
        return self._safety_interlock_reader

    @property
    def operator_input_reader(self) -> dds.DataReader:
        return self._operator_input_reader
