"""Operator console simulator — OperatorInput, RobotCommand, SafetyInterlock.

Publishes simulated joystick/haptic input on the Procedure domain
(control tag) using the ControlOperator participant. Sends an initial
RobotCommand to transition the robot from IDLE to OPERATIONAL, then
continuously publishes OperatorInput with sinusoidal motion.

SafetyInterlock is published once at startup (inactive) and can be
toggled via ``set_interlock()``.

Follows the canonical application architecture in vision/dds-consistency.md §3.
Uses generated entity name constants from app_names.idl.
"""

from __future__ import annotations

import asyncio
import math
import time

import app_names
import rti.connextdds as dds
import surgery
from medtech.dds import initialize_connext
from medtech.log import ModuleName, init_logging
from medtech.service import Service, ServiceState

names = app_names.MedtechEntityNames.SurgicalParticipants

RobotCommand = surgery.Surgery.RobotCommand
OperatorInput = surgery.Surgery.OperatorInput
SafetyInterlock = surgery.Surgery.SafetyInterlock
CartesianPosition = surgery.Surgery.CartesianPosition

log = init_logging(ModuleName.SURGICAL_PROCEDURE)


class OperatorConsoleService(Service):
    """Simulated operator console publishing control-tag topics.

    Owns its DomainParticipant (created from XML configuration
    SurgicalParticipants::ControlOperator) and looks up writers by
    entity name.
    Implements medtech.Service for orchestration lifecycle management.
    """

    DEFAULT_INPUT_RATE_HZ = 50

    def __init__(
        self,
        room_id: str,
        procedure_id: str,
        operator_id: str = "operator-001",
        robot_id: str = "robot-001",
        input_rate_hz: int = DEFAULT_INPUT_RATE_HZ,
        *,
        participant: dds.DomainParticipant | None = None,
    ) -> None:
        self._operator_id = operator_id
        self._robot_id = robot_id
        self._input_rate_hz = input_rate_hz
        self._command_seq = 0
        self._t0 = 0.0
        self._svc_state = ServiceState.STOPPED
        self._stop_event: asyncio.Event | None = None

        # --- DDS entities (dual-mode participant) ---
        if participant is None:
            initialize_connext()
            provider = dds.QosProvider.default
            self._participant = provider.create_participant_from_config(
                names.CONTROL_OPERATOR
            )
            partition = f"room/{room_id}/procedure/{procedure_id}"
            qos = self._participant.qos
            qos.partition.name = [partition]
            self._participant.qos = qos
        else:
            self._participant = participant

        self._input_writer = dds.DataWriter(
            self._participant.find_datawriter(names.OPERATOR_INPUT_WRITER)
        )
        self._cmd_writer = dds.DataWriter(
            self._participant.find_datawriter(names.ROBOT_COMMAND_WRITER)
        )
        self._interlock_writer = dds.DataWriter(
            self._participant.find_datawriter(names.SAFETY_INTERLOCK_WRITER)
        )

    def start(self) -> None:
        """Enable participant and begin DDS discovery."""
        self._participant.enable()
        self._t0 = time.monotonic()
        log.notice(
            f"OperatorConsole enabled: operator={self._operator_id}, "
            f"robot={self._robot_id}, rate={self._input_rate_hz} Hz"
        )

    def send_command(
        self,
        x: float = 0.5,
        y: float = 0.3,
        z: float = 0.1,
    ) -> None:
        """Publish a RobotCommand (transitions robot IDLE → OPERATIONAL)."""
        self._command_seq += 1
        cmd = RobotCommand(
            robot_id=self._robot_id,
            command_id=self._command_seq,
            target_position=CartesianPosition(x=x, y=y, z=z),
        )
        self._cmd_writer.write(cmd)
        log.informational(
            f"RobotCommand sent: id={self._command_seq}, " f"target=({x}, {y}, {z})"
        )

    def set_interlock(self, active: bool, reason: str = "") -> None:
        """Publish a SafetyInterlock state change."""
        interlock = SafetyInterlock(
            robot_id=self._robot_id,
            interlock_active=active,
            reason=reason,
        )
        self._interlock_writer.write(interlock)
        log.notice(
            f"SafetyInterlock: active={active}"
            + (f", reason={reason}" if reason else "")
        )

    def tick(self) -> OperatorInput:
        """Generate and publish one OperatorInput sample.

        Returns the published sample for testing/inspection.
        Produces gentle sinusoidal motion across all axes.
        """
        t = time.monotonic() - self._t0
        inp = OperatorInput(
            operator_id=self._operator_id,
            robot_id=self._robot_id,
            x_axis=math.sin(t * 0.5) * 2.0,
            y_axis=math.cos(t * 0.3) * 1.5,
            z_axis=math.sin(t * 0.7) * 1.0,
            roll=math.sin(t * 0.4) * 0.8,
            pitch=math.cos(t * 0.6) * 0.6,
            yaw=math.sin(t * 0.2) * 0.5,
        )
        self._input_writer.write(inp)
        return inp

    @property
    def input_rate_hz(self) -> int:
        return self._input_rate_hz

    def close(self) -> None:
        """Close the participant and release DDS resources."""
        if self._participant is not None:
            try:
                self._participant.close()
            except dds.AlreadyClosedError:
                pass
            self._participant = None
        log.informational("OperatorConsole: stopped")

    # --- medtech.Service interface ---

    async def run(self) -> None:
        self._svc_state = ServiceState.STARTING
        self._stop_event = asyncio.Event()
        self.start()

        # Allow discovery, then publish initial state
        await asyncio.sleep(2)
        self.set_interlock(active=False)
        self.send_command()

        self._svc_state = ServiceState.RUNNING

        interval = 1.0 / self._input_rate_hz
        while not self._stop_event.is_set():
            self.tick()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

        self._svc_state = ServiceState.STOPPING
        self.close()
        self._svc_state = ServiceState.STOPPED

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    @property
    def name(self) -> str:
        return "OperatorConsole"

    @property
    def state(self) -> ServiceState:
        return self._svc_state
