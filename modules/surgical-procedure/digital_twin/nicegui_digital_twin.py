"""Digital twin — NiceGUI web application for surgical robot 3D visualization.

Subscribes to the Procedure domain (control tag) and renders a live 3D
robot visualization in the browser.  Data reception uses rti.asyncio async
generators so DDS reads never block the NiceGUI event loop.

Subscriptions:
  - RobotState        (GuiRobotState QoS — TBF 100 ms)
  - OperatorInput     (GuiOperatorInput QoS — TBF 100 ms)
  - SafetyInterlock   (SafetyInterlock QoS — no TBF, safety-critical)
  - RobotCommand      (RobotCommand QoS — no TBF, command delivery)

Connectivity monitoring: a liveliness coroutine polls
``reader.liveliness_changed_status`` and updates ``connected`` state.

All QoS is loaded from XML (NDDS_QOS_PROFILES). No programmatic QoS
except partition, which is set from runtime context after participant
creation per vision/data-model.md.

Follows the canonical application architecture in vision/dds-consistency.md §3.
Uses generated entity name constants from app_names.idl.
"""

from __future__ import annotations

import asyncio
import math
import os
from typing import Any

import app_names
import rti.asyncio  # noqa: F401 - enables async DDS methods
import rti.connextdds as dds
import surgery
from medtech.dds import initialize_connext
from medtech.gui import (
    BRAND_COLORS,
    ICONS,
    NICEGUI_QUASAR_CONFIG,
    NICEGUI_STORAGE_SECRET_ENV,
    GuiBackend,
    create_header,
    init_theme,
)
from medtech.log import ModuleName, init_logging
from nicegui import background_tasks, ui

names = app_names.MedtechEntityNames.SurgicalParticipants

log = init_logging(ModuleName.SURGICAL_PROCEDURE)

RobotState = surgery.Surgery.RobotState
RobotCommand = surgery.Surgery.RobotCommand
SafetyInterlock = surgery.Surgery.SafetyInterlock
OperatorInput = surgery.Surgery.OperatorInput

# Heatmap angle range (degrees → full color saturation)
_HEATMAP_ANGLE_MAX = 180.0

# Liveliness poll interval (seconds)
_LIVELINESS_POLL_INTERVAL = 0.5

# 3D arm geometry
_SEGMENT_LENGTH = 0.5
_NUM_JOINTS = 4

# Mode label map (matches RobotMode enum values)
_MODE_LABELS: dict[int, str] = {
    0: "UNKNOWN",
    1: "IDLE",
    2: "OPERATIONAL",
    3: "PAUSED",
    4: "EMERGENCY_STOP",
}

_MODE_COLORS: dict[str, str] = {
    "OPERATIONAL": BRAND_COLORS["green"],
    "PAUSED": BRAND_COLORS["amber"],
    "EMERGENCY_STOP": BRAND_COLORS["red"],
    "E-STOP": BRAND_COLORS["red"],
    "IDLE": BRAND_COLORS["gray"],
    "UNKNOWN": BRAND_COLORS["light_gray"],
}


def heatmap_color(angle: float) -> str:
    """Map a joint angle to a diverging blue→neutral→orange hex color.

    Mirrors the heatmap in the legacy PySide6 RobotWidget.
    """
    t = max(-1.0, min(1.0, angle / _HEATMAP_ANGLE_MAX))
    # cold=blue (#1565C0), zero=dark (#263238), hot=orange (#ED8B00)
    cold = (21, 101, 192)
    zero = (38, 50, 56)
    hot = (237, 139, 0)
    if t >= 0:
        r = int(zero[0] + (hot[0] - zero[0]) * t)
        g = int(zero[1] + (hot[1] - zero[1]) * t)
        b = int(zero[2] + (hot[2] - zero[2]) * t)
    else:
        at = -t
        r = int(zero[0] + (cold[0] - zero[0]) * at)
        g = int(zero[1] + (cold[1] - zero[1]) * at)
        b = int(zero[2] + (cold[2] - zero[2]) * at)
    return f"#{r:02x}{g:02x}{b:02x}"


def _joint_segment_position(
    joint_angles: list[float], joint_index: int
) -> tuple[float, float, float]:
    """Compute the (x, y, z) centre of joint segment ``joint_index``.

    Each joint rotates accumulatively around the Z axis in the X-Y plane.
    The base is at the origin; segments fan out upward/sideward.
    """
    x, y = 0.0, 0.0
    cumulative_angle = 0.0
    for i in range(joint_index + 1):
        angle_deg = joint_angles[i] if i < len(joint_angles) else 0.0
        cumulative_angle += math.radians(angle_deg)
        dx = math.sin(cumulative_angle) * _SEGMENT_LENGTH
        dy = math.cos(cumulative_angle) * _SEGMENT_LENGTH
        if i == joint_index:
            # Centre of this segment is halfway along
            half_dx = math.sin(cumulative_angle) * _SEGMENT_LENGTH * 0.5
            half_dy = math.cos(cumulative_angle) * _SEGMENT_LENGTH * 0.5
            return x + half_dx, y + half_dy, 0.0
        x += dx
        y += dy
    return x, y, 0.0


def _knuckle_position(
    joint_angles: list[float], joint_index: int
) -> tuple[float, float, float]:
    """Compute the (x, y, z) position of the knuckle at the end of joint segment ``joint_index``."""
    x, y = 0.0, 0.0
    cumulative_angle = 0.0
    for i in range(joint_index + 1):
        angle_deg = joint_angles[i] if i < len(joint_angles) else 0.0
        cumulative_angle += math.radians(angle_deg)
        dx = math.sin(cumulative_angle) * _SEGMENT_LENGTH
        dy = math.cos(cumulative_angle) * _SEGMENT_LENGTH
        x += dx
        y += dy
    return x, y, 0.0


class DigitalTwinBackend(GuiBackend):
    """NiceGUI backend that owns the DigitalTwin DDS resources for one room.

    DDS participants are created once per room and reused across client
    connections.  The participant is scoped to the room partition at
    creation time.

    Parameters
    ----------
    room_id:
        Procedure room (e.g. ``"OR-1"``). Sets the partition string.
    procedure_id:
        Procedure identifier. Sets the partition string.
    robot_state_reader, robot_command_reader,
    safety_interlock_reader, operator_input_reader:
        Optional pre-created DataReader objects for dependency injection
        in tests.  When all four are supplied, no DomainParticipant is
        created internally.
    """

    def __init__(
        self,
        room_id: str = "OR-1",
        procedure_id: str = "proc-001",
        *,
        robot_state_reader: dds.DataReader | None = None,
        robot_command_reader: dds.DataReader | None = None,
        safety_interlock_reader: dds.DataReader | None = None,
        operator_input_reader: dds.DataReader | None = None,
    ) -> None:
        self.room_id = room_id
        self.procedure_id = procedure_id

        # ---- State model ------------------------------------------------
        self.joint_positions: list[float] = []
        self.operational_mode: str = "UNKNOWN"
        self.mode_color: str = _MODE_COLORS["UNKNOWN"]
        self.tool_tip: Any | None = None
        self.connected: bool = True
        self.interlock_active: bool = False
        self.interlock_reason: str = ""
        self.has_command: bool = False

        # ---- Internal -------------------------------------------------------
        self._running: bool = False
        self._tasks: list[asyncio.Task[Any]] = []
        self._participant: dds.DomainParticipant | None = None

        # ---- Readers (injected or created below) --------------------------
        self._robot_state_reader = robot_state_reader
        self._robot_command_reader = robot_command_reader
        self._safety_interlock_reader = safety_interlock_reader
        self._operator_input_reader = operator_input_reader

        if not self._all_readers_injected:
            self._init_dds(room_id, procedure_id)

        super().__init__()

    # ---------------------------------------------------------------------- #
    # GuiBackend contract                                                     #
    # ---------------------------------------------------------------------- #

    @property
    def name(self) -> str:
        return "DigitalTwin"

    # ---------------------------------------------------------------------- #
    # Private helpers                                                         #
    # ---------------------------------------------------------------------- #

    @property
    def _all_readers_injected(self) -> bool:
        return all(
            r is not None
            for r in (
                self._robot_state_reader,
                self._robot_command_reader,
                self._safety_interlock_reader,
                self._operator_input_reader,
            )
        )

    def _init_dds(self, room_id: str, procedure_id: str) -> None:
        """Create the ControlDigitalTwin participant and locate readers."""
        initialize_connext()
        provider = dds.QosProvider.default
        participant = provider.create_participant_from_config(
            names.CONTROL_DIGITAL_TWIN
        )
        if participant is None:
            raise RuntimeError("Failed to create ControlDigitalTwin participant")

        partition = f"room/{room_id}/procedure/{procedure_id}"
        qos = participant.qos
        qos.partition.name = [partition]
        participant.qos = qos
        participant.enable()
        self._participant = participant

        def _find_reader(entity_name: str) -> dds.DataReader:
            reader = participant.find_datareader(entity_name)
            if reader is None:
                raise RuntimeError(f"Reader not found: {entity_name}")
            return dds.DataReader(reader)

        self._robot_state_reader = _find_reader(names.TWIN_ROBOT_STATE_READER)
        self._robot_command_reader = _find_reader(names.TWIN_ROBOT_COMMAND_READER)
        self._safety_interlock_reader = _find_reader(names.TWIN_SAFETY_INTERLOCK_READER)
        self._operator_input_reader = _find_reader(names.TWIN_OPERATOR_INPUT_READER)

    # ---------------------------------------------------------------------- #
    # Async lifecycle                                                         #
    # ---------------------------------------------------------------------- #

    async def start(self) -> None:
        """Launch all background DDS reader tasks."""
        self._running = True
        self._tasks = [
            background_tasks.create(self._receive_robot_state()),
            background_tasks.create(self._receive_robot_command()),
            background_tasks.create(self._receive_safety_interlock()),
            background_tasks.create(self._receive_operator_input()),
            background_tasks.create(self._monitor_liveliness()),
        ]
        log.informational("DigitalTwinBackend: async DDS receive tasks started")

    async def close(self) -> None:
        """Cancel background tasks and release DDS resources."""
        self._running = False
        live_tasks = [
            t for t in self._tasks if isinstance(t, asyncio.Task) and not t.done()
        ]
        for task in live_tasks:
            task.cancel()
        if live_tasks:
            await asyncio.gather(*live_tasks, return_exceptions=True)
        self._tasks.clear()

        for reader_attr in (
            "_robot_state_reader",
            "_robot_command_reader",
            "_safety_interlock_reader",
            "_operator_input_reader",
        ):
            reader = getattr(self, reader_attr, None)
            if reader is not None:
                try:
                    reader.close()
                except Exception:
                    pass

        if self._participant is not None:
            try:
                self._participant.close()
            except Exception:
                pass
            self._participant = None
            log.notice("DigitalTwin participant closed")

        await rti.asyncio.close()

    # ---------------------------------------------------------------------- #
    # Public state mutators (called from async readers or tests)             #
    # ---------------------------------------------------------------------- #

    def update_robot_state(self, sample: Any) -> None:
        """Store the latest RobotState sample and update derived fields."""
        joints = getattr(sample, "joint_positions", None)
        self.joint_positions = list(joints) if joints else []
        mode_val = int(getattr(sample, "operational_mode", 0))
        self.operational_mode = _MODE_LABELS.get(mode_val, "UNKNOWN")
        self.mode_color = _MODE_COLORS.get(self.operational_mode, BRAND_COLORS["gray"])
        self.tool_tip = getattr(sample, "tool_tip_position", None)
        self.connected = True

    def update_command(self, sample: Any) -> None:
        """Record that a RobotCommand sample was received."""
        self.has_command = True

    def update_interlock(self, sample: Any) -> None:
        """Store the latest SafetyInterlock sample."""
        self.interlock_active = bool(getattr(sample, "interlock_active", False))
        self.interlock_reason = str(getattr(sample, "reason", ""))

    def set_connected(self, connected: bool) -> None:
        """Set writer liveliness state; triggers no repaint here (UI timer handles it)."""
        self.connected = connected

    # ---------------------------------------------------------------------- #
    # Async DDS receive loops                                                #
    # ---------------------------------------------------------------------- #

    async def _receive_robot_state(self) -> None:
        async for data in self._robot_state_reader.take_data_async():
            self.update_robot_state(data)

    async def _receive_robot_command(self) -> None:
        async for data in self._robot_command_reader.take_data_async():
            self.update_command(data)

    async def _receive_safety_interlock(self) -> None:
        async for data in self._safety_interlock_reader.take_data_async():
            self.update_interlock(data)
            if self.interlock_active:
                ui.notification(
                    f"SAFETY INTERLOCK ACTIVE: {self.interlock_reason or 'INTERLOCK'}",
                    type="negative",
                    timeout=None,
                )

    async def _receive_operator_input(self) -> None:
        async for _data in self._operator_input_reader.take_data_async():
            pass

    async def _monitor_liveliness(self) -> None:
        """Periodically check RobotState writer liveliness."""
        while self._running:
            status = self._robot_state_reader.liveliness_changed_status
            if status.alive_count == 0 and status.not_alive_count > 0:
                self.connected = False
            elif status.alive_count > 0:
                self.connected = True
            await asyncio.sleep(_LIVELINESS_POLL_INTERVAL)


# --------------------------------------------------------------------------- #
# Module-level backend registry (one backend per room_id)                     #
# --------------------------------------------------------------------------- #

_twin_backends: dict[str, DigitalTwinBackend] = {}


def _get_backend(room_id: str) -> DigitalTwinBackend:
    """Return (or create on first access) the DigitalTwinBackend for *room_id*."""
    global _twin_backends
    if room_id not in _twin_backends:
        _twin_backends[room_id] = DigitalTwinBackend(room_id=room_id)
    return _twin_backends[room_id]


# --------------------------------------------------------------------------- #
# NiceGUI page                                                                #
# --------------------------------------------------------------------------- #


@ui.page("/twin/{room_id}", dark=True)
def twin_page(room_id: str) -> None:
    """Render the digital twin 3D visualization page for *room_id*."""
    current_backend = _get_backend(room_id)
    init_theme()
    create_header(title=f"Digital Twin — {room_id}")

    # ---- Mode badge at top of content area --------------------------------
    with ui.row().classes("w-full items-center gap-3 px-4 pt-2"):
        ui.icon(ICONS["robot"]).classes("text-2xl")
        ui.label(f"Room: {room_id}").classes("text-lg font-bold")
        ui.space()
        mode_badge = ui.badge(
            current_backend.operational_mode,
            color=current_backend.mode_color,
        ).classes("text-base px-3 py-1")

    # ---- 3D scene ---------------------------------------------------------
    _build_scene(current_backend, mode_badge)


def _build_scene(current_backend: DigitalTwinBackend, mode_badge: Any) -> None:
    """Build the 3D scene and attach the update timer."""
    with ui.scene(width=860, height=560).classes("w-full") as scene:
        # Robot base
        base = scene.sphere(0.15).move(0, 0, 0).material(color=BRAND_COLORS["blue"])

        # Arm segments and knuckle spheres
        arm_segments = []
        knuckles = []
        for i in range(_NUM_JOINTS):
            cx, cy, _ = _joint_segment_position([], i)
            seg = (
                scene.cylinder(0.05, _SEGMENT_LENGTH)
                .move(cx, cy, 0.0)
                .material(color=heatmap_color(0.0))
            )
            arm_segments.append(seg)

            kx, ky, _ = _knuckle_position([], i)
            knk = (
                scene.sphere(0.07)
                .move(kx, ky, 0.0)
                .material(color=BRAND_COLORS["gray"])
            )
            knuckles.append(knk)

        # Tool tip
        tx, ty, _ = _knuckle_position([], _NUM_JOINTS - 1)
        tool_tip_sphere = (
            scene.sphere(0.1).move(tx, ty, 0.0).material(color=BRAND_COLORS["green"])
        )

        # Mode overlay text (starts hidden — updated in timer)
        mode_text = scene.text(
            current_backend.operational_mode, style="font-size: 1.2em"
        )
        mode_text.move(-2.0, -1.5, 0.0)

    # Suppress unused variable warnings — referenced in update_scene closure
    _ = base

    def update_scene() -> None:
        """Refresh 3D objects and badges from current backend state (10 Hz)."""
        joints = current_backend.joint_positions

        for i, (seg, knk) in enumerate(zip(arm_segments, knuckles)):
            angle = joints[i] if i < len(joints) else 0.0
            cx, cy, _ = _joint_segment_position(joints, i)
            kx, ky, _ = _knuckle_position(joints, i)
            seg.move(cx, cy, 0.0).material(color=heatmap_color(angle))
            knk.move(kx, ky, 0.0)

        # Update tool tip position
        if len(joints) > 0:
            tip_x, tip_y, _ = _knuckle_position(
                joints, min(len(joints), _NUM_JOINTS) - 1
            )
            tool_tip_sphere.move(tip_x, tip_y, 0.0)

        # Update mode badge and scene text
        mode_badge.set_text(current_backend.operational_mode)
        mode_text.move(-2.0, -1.5, 0.0)

    ui.timer(0.1, update_scene)


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #


def main() -> None:
    """Standalone launch entry point."""
    storage_secret = os.environ.get(NICEGUI_STORAGE_SECRET_ENV)
    if not storage_secret:
        raise RuntimeError(
            f"{NICEGUI_STORAGE_SECRET_ENV} must be set before starting the digital twin"
        )

    room_id = os.environ.get("ROOM_ID", "OR-1")
    _get_backend(room_id)

    try:
        ui.run(
            root=twin_page,
            storage_secret=storage_secret,
            reload=False,
            quasar_config=NICEGUI_QUASAR_CONFIG,
        )
    except KeyboardInterrupt:
        pass


if __name__ in {"__main__", "__mp_main__"}:
    main()


__all__ = [
    "DigitalTwinBackend",
    "heatmap_color",
    "main",
    "twin_page",
]
