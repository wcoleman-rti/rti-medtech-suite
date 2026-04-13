"""Digital twin — NiceGUI web application for surgical robot 3D visualization.

Subscribes to the Procedure domain (control tag) and renders a live 3D
robot visualization in the browser.  Data reception uses rti.asyncio async
generators so DDS reads never block the NiceGUI event loop.

Subscriptions:
  - RobotState              (GuiRobotState QoS — TBF 100 ms)
  - OperatorInput           (GuiOperatorInput QoS — TBF 100 ms)
  - SafetyInterlock         (SafetyInterlock QoS — no TBF, safety-critical)
  - RobotCommand            (RobotCommand QoS — no TBF, command delivery)
  - RobotArmAssignment      (RobotArmAssignment QoS — state-based, every sample)

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
    NICEGUI_STORAGE_SECRET_DEFAULT,
    NICEGUI_STORAGE_SECRET_ENV,
    GuiBackend,
    create_header,
    init_theme,
)
from medtech.gui._colors import THEME_PALETTE
from medtech.gui._theme import NICEGUI_THEME_MODE_KEY, _theme_mode_value
from medtech.log import ModuleName, init_logging
from nicegui import app, background_tasks, ui

names = app_names.MedtechEntityNames.SurgicalParticipants

log = init_logging(ModuleName.SURGICAL_PROCEDURE)

RobotState = surgery.Surgery.RobotState
RobotCommand = surgery.Surgery.RobotCommand
SafetyInterlock = surgery.Surgery.SafetyInterlock
OperatorInput = surgery.Surgery.OperatorInput
RobotArmAssignment = surgery.Surgery.RobotArmAssignment
ArmAssignmentState = surgery.Surgery.ArmAssignmentState
TablePosition = surgery.Surgery.TablePosition
RobotMode = surgery.Surgery.RobotMode
MAX_ARM_COUNT: int = surgery.Surgery.MAX_ARM_COUNT

# Heatmap angle range (degrees → full color saturation)
_HEATMAP_ANGLE_MAX = 180.0

# Liveliness poll interval (seconds)
_LIVELINESS_POLL_INTERVAL = 0.5

# 3D arm geometry — per-segment config (upper arm → tool shaft)
# link_r: link cylinder radius
# length:  link length
# jnt_r:   joint housing sphere radius
# axis:    rotation axis in the joint’s local frame
#          "X" — pitch (bends arm toward/away from viewer, gaining Y depth)
#          "Z" — yaw  (sweeps arm left/right in the XZ plane)
_JOINT_CONFIGS = [
    {"link_r": 0.075, "length": 0.65, "jnt_r": 0.130, "axis": "X"},  # shoulder — pitch
    {"link_r": 0.060, "length": 0.52, "jnt_r": 0.108, "axis": "X"},  # elbow — pitch
    {"link_r": 0.045, "length": 0.36, "jnt_r": 0.085, "axis": "Z"},  # wrist — yaw
    {"link_r": 0.028, "length": 0.20, "jnt_r": 0.062, "axis": "X"},  # tool — pitch
]
_NUM_JOINTS = len(_JOINT_CONFIGS)
# Z offset: arm shoulder height above the ground plane.
# Raised to 0.78 m so the shoulder is close to table surface (~0.90 m),
# letting J0 sweep the arm mostly horizontally across the operative field
# rather than diagonally upward before even reaching the table.
_ARM_BASE_Z = 0.78

# ---------------------------------------------------------------------------
# OperatingTable — encapsulates table geometry and arm position derivation
# ---------------------------------------------------------------------------


class OperatingTable:
    """3D operating table model that derives arm mount positions.

    All arm world-coordinates are computed from the table's center and
    dimensions, so nothing about arm placement is hard-coded independently
    of the table geometry.

    Parameters match the physical OR table: 2.2 m × 0.85 m slab at 0.80 m
    height, centered at ``(cx, cy)`` in world-space.
    """

    def __init__(
        self,
        cx: float = 0.0,
        cy: float = 0.65,
        half_length: float = 1.10,
        half_width: float = 0.425,
        surface_z: float = 0.80,
        slab_h: float = 0.08,
    ) -> None:
        self.cx = cx
        self.cy = cy
        self.half_length = half_length
        self.half_width = half_width
        self.surface_z = surface_z
        self.slab_h = slab_h

        # Derived geometry
        self.col_side = 0.22  # pedestal column square side
        self.foot_w = 0.80  # foot platform full length (X)
        self.foot_d = 0.36  # foot platform full depth (Y)
        self.foot_h = 0.08  # foot platform height
        self.foot_r = 0.035  # foot platform corner radius

        # Arm standoff: distance from table edge to arm cart center.
        # This single value controls how far the carts sit from the table.
        self._arm_standoff = 0.90

        # Z above which arm joints must stay when over the table footprint.
        # mattress top (surface_z + slab_h/2 + 0.10) + max joint sphere
        # radius (0.130) + safety margin (0.02)
        self.clearance_z = surface_z + slab_h / 2 + 0.10 + 0.130 + 0.02

    def get_position(self, pos: TablePosition) -> tuple[float, float]:
        """Return (x, y) world-space mount coordinates for *pos*.

        Positions are derived from the table center and dimensions:
        - Cardinal (HEAD/FOOT/LEFT/RIGHT): centered on the respective edge
        - Diagonal (RIGHT_HEAD etc.): at the table corner, offset outward
        """
        cx, cy = self.cx, self.cy
        hx, hy = self.half_length, self.half_width
        s = self._arm_standoff

        return {
            TablePosition.RIGHT: (cx, cy - hy - s),
            TablePosition.LEFT: (cx, cy + hy + s),
            TablePosition.HEAD: (cx - hx - s, cy),
            TablePosition.FOOT: (cx + hx + s, cy),
            TablePosition.RIGHT_HEAD: (cx - hx * 0.72, cy - hy - s),
            TablePosition.LEFT_HEAD: (cx - hx * 0.72, cy + hy + s),
            TablePosition.RIGHT_FOOT: (cx + hx * 0.72, cy - hy - s),
            TablePosition.LEFT_FOOT: (cx + hx * 0.72, cy + hy + s),
        }[pos]

    @property
    def positions(self) -> list[TablePosition]:
        """All valid arm positions (every TablePosition except UNKNOWN)."""
        return [p for p in TablePosition if p != TablePosition.UNKNOWN]

    @property
    def x_min(self) -> float:
        return self.cx - self.half_length

    @property
    def x_max(self) -> float:
        return self.cx + self.half_length

    @property
    def y_min(self) -> float:
        return self.cy - self.half_width

    @property
    def y_max(self) -> float:
        return self.cy + self.half_width


# Default table used by the 3D scene
DEFAULT_TABLE = OperatingTable()

# Default position for single-arm / no-assignment fallback
DEFAULT_POSITION = TablePosition.RIGHT

# Round-robin order when an assignment has UNKNOWN position
POSITION_ROUND_ROBIN: list[TablePosition] = [
    TablePosition.RIGHT,
    TablePosition.LEFT,
    TablePosition.RIGHT_HEAD,
    TablePosition.LEFT_HEAD,
    TablePosition.RIGHT_FOOT,
    TablePosition.LEFT_FOOT,
    TablePosition.HEAD,
    TablePosition.FOOT,
]
# Fallback display pose (radians) shown only when no DDS data has arrived yet.
# Arm pitched ~20° toward table (J0 small negative), elbow bent — working posture.
_NO_SIGNAL_POSE = [-0.35, 1.10, 0.20, -0.20]

# Per-joint angle limits in radians [min, max].
# Prevents the arm from passing through the ground plane and enforces
# realistic joint ranges matching typical surgical robot kinematics.
_JOINT_LIMITS = [
    (-1.20, 0.40),  # J0 shoulder pitch: -69° (toward table) to +23° (backward)
    (0.20, 2.20),  # J1 elbow pitch:    +11° to +126° (keeps arm above table)
    (-1.50, 1.50),  # J2 wrist yaw:      ±86°
    (-1.00, 1.00),  # J3 tool pitch:     ±57°
]
# Link and joint base colors are now resolved at runtime from THEME_PALETTE["arm"]
# per ui-design-system.md.  The constants are kept as fallbacks for the no-DM case.
_LINK_COLOR_DARK = THEME_PALETTE["dark"]["arm"]  # #C8D2DC
_LINK_COLOR_LIGHT = THEME_PALETTE["light"]["arm"]  # #505A64

# Mode → color mapping (RobotMode enum keys)
MODE_COLORS: dict[RobotMode, str] = {
    RobotMode.OPERATIONAL: BRAND_COLORS["green"],
    RobotMode.PAUSED: BRAND_COLORS["amber"],
    RobotMode.EMERGENCY_STOP: BRAND_COLORS["red"],
    RobotMode.IDLE: BRAND_COLORS["gray"],
    RobotMode.UNKNOWN: BRAND_COLORS["light_gray"],
}

# Color mapping for ArmAssignmentState lifecycle indicators
ARM_STATE_COLORS: dict[ArmAssignmentState, str] = {
    ArmAssignmentState.OPERATIONAL: BRAND_COLORS["green"],
    ArmAssignmentState.POSITIONING: BRAND_COLORS["amber"],
    ArmAssignmentState.FAILED: BRAND_COLORS["red"],
    ArmAssignmentState.IDLE: BRAND_COLORS["gray"],
    ArmAssignmentState.ASSIGNED: BRAND_COLORS["gray"],
    ArmAssignmentState.UNKNOWN: BRAND_COLORS["gray"],
}


def heatmap_color(angle: float) -> str:
    """Map a joint angle to a diverging blue→neutral→orange hex color."""
    t = max(-1.0, min(1.0, angle / _HEATMAP_ANGLE_MAX))
    # cold=blue (#1565C0), zero=#78909C (lightened for sleeker arm), hot=orange
    cold = (21, 101, 192)
    zero = (120, 144, 156)  # was (38,50,56); matches heatmap-zero-light token
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


def _rotate_vec_rodrigues(
    vec: tuple[float, float, float],
    axis: tuple[float, float, float],
    angle_rad: float,
) -> tuple[float, float, float]:
    """Rotate *vec* around unit *axis* by *angle_rad* (Rodrigues formula)."""
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    ax, ay, az = axis
    vx, vy, vz = vec
    dot = ax * vx + ay * vy + az * vz
    cx_ = ay * vz - az * vy
    cy_ = az * vx - ax * vz
    cz_ = ax * vy - ay * vx
    return (
        vx * c + cx_ * s + ax * dot * (1 - c),
        vy * c + cy_ * s + ay * dot * (1 - c),
        vz * c + cz_ * s + az * dot * (1 - c),
    )


def _euler_from_direction(
    dx: float, dy: float, dz: float
) -> tuple[float, float, float]:
    """Return (rx, 0, rz) Euler angles for NiceGUI’s ZYX rotation order that
    orient the default Y-up cylinder axis to point in direction (dx, dy, dz).

    NiceGUI’s rotate_R / rotation_matrix_from_euler uses R = Rz * Ry * Rx.
    Column 1 of that matrix (the mapped Y-axis) with ry=0 is:
      col_y = [-sin(rz)*cos(rx),  cos(rz)*cos(rx),  sin(rx)]
    Setting col_y = normalise(dx,dy,dz) gives:
      rx = asin(dz)
      rz = atan2(dx, dy)
    """
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length < 1e-9:
        return 0.0, 0.0, 0.0
    dx /= length
    dy /= length
    dz /= length
    rx = math.asin(max(-1.0, min(1.0, dz)))
    rz = math.atan2(-dx, dy)
    return rx, 0.0, rz


def _compute_arm_geometry(
    joint_angles: list[float],
    ox: float = 0.0,
    oy: float = 0.0,
) -> list[dict]:
    """3-D forward kinematics for the arm chain.

    Each joint’s rotation axis is defined in *_JOINT_CONFIGS*:
      “X” (pitch) — rotates around the link’s local right axis, bending the
                      arm toward/away from the viewer (gaining Y depth).
      "Z" (yaw)   — rotates around the link's local forward axis, sweeping
                      the arm left/right in the XZ plane.

    Returns one dict per segment with:
      cx, cy, cz   — world-space cylinder centre (.move() target)
      rx, ry, rz   — XYZ Euler angles to orient the cylinder (.rotate() target)
      kx, ky, kz   — world-space joint knuckle position
      fwd          — forward unit-vector leaving this joint (tuple)
      angle        — this segment’s joint angle in degrees (for heatmap)
    Plus a trailing dict with tip_x/tip_y/tip_z/fwd for the instrument tip.
    """
    result = []
    pos = [0.0, 0.0, 0.0]
    # Initial orthonormal frame — arm starts growing along the Z (up) axis.
    # NiceGUI uses Z-up (ground plane = XY, z = 0).
    #   fwd — direction the next link extends along
    #   rgt — local "right" axis  ("X" joints rotate around this — pitch)
    #   upv — local "forward" axis ("Z" joints rotate around this — yaw)
    fwd: tuple[float, float, float] = (0.0, 0.0, 1.0)
    rgt: tuple[float, float, float] = (1.0, 0.0, 0.0)
    upv: tuple[float, float, float] = (0.0, 1.0, 0.0)

    for i, cfg in enumerate(_JOINT_CONFIGS):
        # joint_positions are in radians (robot_controller uses k_scale in rad/unit)
        angle_rad = joint_angles[i] if i < len(joint_angles) else 0.0
        angle_deg = math.degrees(angle_rad)  # for heatmap only

        # Select local axis and rotate the entire frame by the joint angle.
        local_axis = rgt if cfg["axis"] == "X" else upv
        fwd = _rotate_vec_rodrigues(fwd, local_axis, angle_rad)
        rgt = _rotate_vec_rodrigues(rgt, local_axis, angle_rad)
        upv = _rotate_vec_rodrigues(upv, local_axis, angle_rad)

        kx = pos[0] + fwd[0] * cfg["length"]
        ky = pos[1] + fwd[1] * cfg["length"]
        kz = pos[2] + fwd[2] * cfg["length"]

        # Guard: clamp knuckle Z so no segment drops below the ground plane (z = 0)
        kz = max(kz, -_ARM_BASE_Z + 0.05)

        # Table surface guard — sample 8 evenly-spaced points along the segment
        # (including both endpoints) so that an arm approaching from the side
        # is caught even when neither endpoint is inside the table footprint.
        # For each sample inside the footprint that is too low, compute the kz
        # that would bring that sample up to clearance_z (linear solve),
        # and take the strictest (highest) requirement across all samples.
        _ty_min = DEFAULT_TABLE.y_min
        _ty_max = DEFAULT_TABLE.y_max
        _tx_min = DEFAULT_TABLE.x_min
        _tx_max = DEFAULT_TABLE.x_max
        _min_z_local = DEFAULT_TABLE.clearance_z - _ARM_BASE_Z
        for _si in range(8):
            _t = _si / 7.0
            _sx = pos[0] + _t * (kx - pos[0])
            _sy = pos[1] + _t * (ky - pos[1])
            _sz_world = (pos[2] + _t * (kz - pos[2])) + _ARM_BASE_Z
            if (
                _tx_min <= _sx + ox <= _tx_max
                and _ty_min <= _sy + oy <= _ty_max
                and _sz_world < DEFAULT_TABLE.clearance_z
            ):
                if _t > 1e-6:
                    kz = max(kz, pos[2] + (_min_z_local - pos[2]) / _t)
                else:
                    kz = max(kz, _min_z_local)

        # Cylinder centre = midpoint of (previous knuckle → current knuckle),
        # recomputed after clamping so it stays consistent with kz.
        cx = (pos[0] + kx) * 0.5
        cy = (pos[1] + ky) * 0.5
        cz = (pos[2] + kz) * 0.5
        rx_e, ry_e, rz_e = _euler_from_direction(*fwd)

        result.append(
            {
                "cx": cx,
                "cy": cy,
                "cz": cz,
                "rx": rx_e,
                "ry": ry_e,
                "rz": rz_e,
                "kx": kx,
                "ky": ky,
                "kz": kz,
                "fwd": fwd,
                "angle": angle_deg,
            }
        )
        pos = [kx, ky, kz]

    result.append({"tip_x": pos[0], "tip_y": pos[1], "tip_z": pos[2], "fwd": fwd})
    return result


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
        arm_assignment_reader: dds.DataReader | None = None,
    ) -> None:
        self.room_id = room_id
        self.procedure_id = procedure_id

        # ---- State model ------------------------------------------------
        self.joint_positions: list[float] = []
        self.operational_mode: RobotMode = RobotMode.UNKNOWN
        self.mode_color: str = MODE_COLORS[RobotMode.UNKNOWN]
        self.tool_tip: Any | None = None
        self.connected: bool = True
        self.interlock_active: bool = False
        self.interlock_reason: str = ""
        self.has_command: bool = False

        # ---- Per-robot state (keyed by robot_id) -------------------------
        self.robot_states: dict[str, dict[str, Any]] = {}

        # ---- Multi-arm tracking ------------------------------------------
        self.arm_assignments: dict[str, RobotArmAssignment] = {}

        # ---- Internal -------------------------------------------------------
        self._running: bool = False
        self._tasks: list[asyncio.Task[Any]] = []
        self._participant: dds.DomainParticipant | None = None

        # ---- Readers (injected or created below) --------------------------
        self._robot_state_reader = robot_state_reader
        self._robot_command_reader = robot_command_reader
        self._safety_interlock_reader = safety_interlock_reader
        self._operator_input_reader = operator_input_reader
        self._arm_assignment_reader = arm_assignment_reader

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
                self._arm_assignment_reader,
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
        self._arm_assignment_reader = _find_reader(
            names.TWIN_ROBOT_ARM_ASSIGNMENT_READER
        )

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
            background_tasks.create(self._receive_arm_assignments()),
            background_tasks.create(self._monitor_liveliness()),
        ]
        self._mark_ready()
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
            "_arm_assignment_reader",
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
        """Store the latest RobotState sample and update derived fields.

        Per-robot joint data is stored in ``robot_states[robot_id]`` so
        each arm in the scene can be wired to its own telemetry stream.
        The legacy ``joint_positions`` / ``operational_mode`` fields are
        kept pointing at the most-recently-received sample for backwards
        compatibility with single-arm workflows.
        """
        robot_id = str(getattr(sample, "robot_id", ""))
        joints = getattr(sample, "joint_positions", None)
        joint_list = list(joints) if joints else []
        mode = RobotMode(int(getattr(sample, "operational_mode", 0)))

        # Per-robot tracking
        if robot_id:
            self.robot_states[robot_id] = {
                "joint_positions": joint_list,
                "operational_mode": mode,
                "mode_color": MODE_COLORS.get(mode, BRAND_COLORS["gray"]),
                "tool_tip": getattr(sample, "tool_tip_position", None),
            }

        # Legacy single-robot fields (latest wins)
        self.joint_positions = joint_list
        self.operational_mode = mode
        self.mode_color = MODE_COLORS.get(mode, BRAND_COLORS["gray"])
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

    def get_robot_joints(self, robot_id: str) -> list[float]:
        """Return the latest joint_positions for *robot_id*, or empty list."""
        state = self.robot_states.get(robot_id)
        return state["joint_positions"] if state else []

    def update_arm_assignment(self, sample: Any) -> None:
        """Track an arm assignment sample by robot_id."""
        robot_id = str(getattr(sample, "robot_id", ""))
        if not robot_id:
            return
        self.arm_assignments[robot_id] = sample
        status = ArmAssignmentState(int(getattr(sample, "status", 0)))
        log.informational(f"DigitalTwin: arm {robot_id} → {status.name}")

    def remove_arm(self, robot_id: str) -> None:
        """Remove an arm from tracking (disposed or liveliness lost)."""
        if robot_id in self.arm_assignments:
            del self.arm_assignments[robot_id]
            log.informational(f"DigitalTwin: arm {robot_id} removed")

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

    async def _receive_arm_assignments(self) -> None:
        """Receive RobotArmAssignment samples, tracking arrivals and disposals."""
        async for data, info in self._arm_assignment_reader.take_async():
            if info.valid:
                self.update_arm_assignment(data)
            elif info.state.instance_state in (
                dds.InstanceState.NOT_ALIVE_DISPOSED,
                dds.InstanceState.NOT_ALIVE_NO_WRITERS,
            ):
                try:
                    key_holder = self._arm_assignment_reader.key_value(
                        info.instance_handle
                    )
                    robot_id = str(getattr(key_holder, "robot_id", ""))
                    if robot_id:
                        self.remove_arm(robot_id)
                except dds.InvalidArgumentError:
                    pass  # instance already purged from reader cache

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


@ui.page("/twin/{room_id}", title="Digital Twin — Medtech Suite")
def twin_page(room_id: str) -> None:
    """Render the digital twin 3D visualization page for *room_id* (standalone with self-contained shell)."""
    init_theme()
    create_header(title=f"Digital Twin — {room_id}")
    controller_url = os.environ.get("MEDTECH_CONTROLLER_URL", "")
    if controller_url:
        with ui.row().classes("w-full px-4 pt-2 items-center"):
            ui.link("← Return to Controller", controller_url).classes(
                "text-sm text-blue-400 hover:text-blue-300"
            )
    twin_content(room_id)


def twin_content(room_id: str) -> None:
    """Render digital twin content.  Call this from the SPA shell's sub_pages."""
    current_backend = _get_backend(room_id)

    # Restore the user's stored theme preference
    stored_mode = app.storage.user.get(NICEGUI_THEME_MODE_KEY, "system")
    dark_mode = ui.dark_mode(_theme_mode_value(stored_mode))  # noqa: F841

    # ---- Mode badge at top of content area --------------------------------
    with ui.row().classes("w-full items-center gap-3 px-4 pt-2"):
        ui.icon(ICONS["robot"]).classes("text-2xl")
        ui.label(f"Room: {room_id}").classes("type-h3")
        ui.space()
        mode_badge = ui.badge(
            current_backend.operational_mode,
            color=current_backend.mode_color,
        ).classes("text-base px-3 py-1")

    # ---- 3D scene ---------------------------------------------------------
    _build_scene(current_backend, mode_badge)


def _build_arm(
    scene: Any,
    ox: float,
    oy: float,
    init_joints: list[float],
    joint_color: str = _LINK_COLOR_DARK,
) -> tuple[list[Any], list[Any], Any, Any, Any, Any, float, list[Any]]:
    """Construct one arm instance in *scene* at world offset (ox, oy).

    Returns (arm_segs, jnt_spheres, shoulder_sphere, tool_sphere, nib,
             instr_dot, nib_half, base_parts).
    ``base_parts`` collects the cart/riser/wheels so callers can toggle
    their visibility along with the arm segments.
    """
    B = _ARM_BASE_Z
    geo = _compute_arm_geometry(init_joints, ox, oy)

    base_parts: list[Any] = []

    # ── Mobile cart base ───────────────────────────────────────────────────
    cart_w, cart_d, cart_h = 0.55, 0.45, 0.18
    _cart_color = "#546E7A"  # grey-scale
    _post_color = "#78909C"  # lighter for corner posts
    base_parts.append(
        scene.box(cart_w, cart_d, cart_h)
        .move(ox, oy, cart_h / 2)
        .material(color=_cart_color)
    )
    # Corner posts — cylinders at each vertical edge give a modern rounded-edge
    # appearance (industrial equipment / medical cart aesthetic).
    _post_r = 0.028
    for _csx, _csy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
        base_parts.append(
            scene.cylinder(_post_r, _post_r, cart_h, 16)
            .move(ox + _csx * (cart_w / 2), oy + _csy * (cart_d / 2), cart_h / 2)
            .rotate(math.pi / 2, 0, 0)
            .material(color=_post_color)
        )
    # Corner wheels
    for wx, wy in [
        (ox - cart_w / 2 + 0.07, oy - cart_d / 2 + 0.07),
        (ox + cart_w / 2 - 0.07, oy - cart_d / 2 + 0.07),
        (ox - cart_w / 2 + 0.07, oy + cart_d / 2 - 0.07),
        (ox + cart_w / 2 - 0.07, oy + cart_d / 2 - 0.07),
    ]:
        base_parts.append(
            scene.sphere(0.055).move(wx, wy, 0.055).material(color="#263238")
        )
    # Riser column — 24 segments for smoother silhouette
    col_h = B - cart_h
    base_parts.append(
        scene.cylinder(0.08, 0.08, col_h, 24)
        .move(ox, oy, cart_h + col_h / 2)
        .rotate(math.pi / 2, 0, 0)
        .material(color=_cart_color)
    )
    # Shoulder actuator housing
    shoulder_sphere = scene.sphere(0.13).move(ox, oy, B).material(color=joint_color)

    # ── Link segments — 32-segment cylinders with slight taper ────────────
    # Tapered profile (r_bottom → r_top * 0.82) mirrors real cobot arm links
    # that narrow toward the distal joint.  32 segments makes the silhouette
    # visibly smooth vs the previous 16.
    arm_segs = []
    for i, cfg in enumerate(_JOINT_CONFIGS):
        g = geo[i]
        angle = init_joints[i] if i < len(init_joints) else 0.0
        r_base = cfg["link_r"]
        r_tip = r_base * 0.82
        seg = (
            scene.cylinder(r_tip, r_base, cfg["length"], 32)
            .move(g["cx"] + ox, g["cy"] + oy, g["cz"] + B)
            .rotate(g["rx"], g["ry"], g["rz"])
            .material(color=heatmap_color(angle))
        )
        arm_segs.append(seg)

    # ── Joint spheres ──────────────────────────────────────────────────────
    jnt_spheres = []
    for i, cfg in enumerate(_JOINT_CONFIGS):
        g = geo[i]
        jnt_spheres.append(
            scene.sphere(cfg["jnt_r"])
            .move(g["kx"] + ox, g["ky"] + oy, g["kz"] + B)
            .material(color=joint_color)
        )

    # ── Tool tip + nib ─────────────────────────────────────────────────────
    # Nib is tapered to a near-point (surgical needle profile): fat at the
    # wrist end, almost nothing at the instrument tip.
    tip = geo[-1]
    nib_fwd = tip["fwd"]
    nib_half = 0.14
    nib_rx, nib_ry, nib_rz = _euler_from_direction(*nib_fwd)
    tool_sphere = (
        scene.sphere(0.050)
        .move(tip["tip_x"] + ox, tip["tip_y"] + oy, tip["tip_z"] + B)
        .material(color=BRAND_COLORS["green"])
    )
    nib = (
        scene.cylinder(0.002, 0.014, nib_half * 2, 16)  # tapered needle
        .move(
            tip["tip_x"] + nib_fwd[0] * nib_half + ox,
            tip["tip_y"] + nib_fwd[1] * nib_half + oy,
            tip["tip_z"] + nib_fwd[2] * nib_half + B,
        )
        .rotate(nib_rx, nib_ry, nib_rz)
        .material(color="#E0E6EE")
    )
    instr_dot = (
        scene.sphere(0.016)  # smaller tip bead for slim needle
        .move(
            tip["tip_x"] + nib_fwd[0] * nib_half * 2 + ox,
            tip["tip_y"] + nib_fwd[1] * nib_half * 2 + oy,
            tip["tip_z"] + nib_fwd[2] * nib_half * 2 + B,
        )
        .material(color=BRAND_COLORS["orange"])
    )
    return (
        arm_segs,
        jnt_spheres,
        shoulder_sphere,
        tool_sphere,
        nib,
        instr_dot,
        nib_half,
        base_parts,
    )


def _update_arm_direct(
    arm_obj: dict[str, Any],
    ox: float,
    oy: float,
    joints: list[float],
) -> None:
    """Reposition one arm's scene objects to reflect *joints*.

    Takes the joint list as an explicit argument so the caller can bind
    per-robot telemetry each frame.
    """
    B = _ARM_BASE_Z
    g = _compute_arm_geometry(joints, ox, oy)
    seg_colors: list[str] = arm_obj.get("seg_colors", [""] * len(arm_obj["arm_segs"]))
    for i, (seg, jsph, cfg) in enumerate(
        zip(arm_obj["arm_segs"], arm_obj["jnt_spheres"], _JOINT_CONFIGS)
    ):
        angle = joints[i] if i < len(joints) else 0.0
        gi = g[i]
        seg.move(gi["cx"] + ox, gi["cy"] + oy, gi["cz"] + B).rotate(
            gi["rx"], gi["ry"], gi["rz"]
        )
        new_color = heatmap_color(angle)
        if new_color != seg_colors[i]:
            seg.material(color=new_color)
            seg_colors[i] = new_color
        jsph.move(gi["kx"] + ox, gi["ky"] + oy, gi["kz"] + B)
    tip = g[-1]
    fwd = tip["fwd"]
    rx, ry, rz = _euler_from_direction(*fwd)
    nib_half = arm_obj["nib_half"]
    arm_obj["tool_sphere"].move(tip["tip_x"] + ox, tip["tip_y"] + oy, tip["tip_z"] + B)
    arm_obj["nib"].move(
        tip["tip_x"] + fwd[0] * nib_half + ox,
        tip["tip_y"] + fwd[1] * nib_half + oy,
        tip["tip_z"] + fwd[2] * nib_half + B,
    ).rotate(rx, ry, rz)
    arm_obj["instr_dot"].move(
        tip["tip_x"] + fwd[0] * nib_half * 2 + ox,
        tip["tip_y"] + fwd[1] * nib_half * 2 + oy,
        tip["tip_z"] + fwd[2] * nib_half * 2 + B,
    )


def _build_scene(
    current_backend: DigitalTwinBackend,
    mode_badge: Any,
) -> None:
    """Build the 3D scene and attach the update timer.

    One arm is pre-built per ``TablePosition`` from surgery.idl (8 total,
    matching ``MAX_ARM_COUNT``).  All arms start hidden; visibility is
    driven by the ``RobotArmAssignment`` samples the backend receives.
    Each arm's updater reads per-robot joint data from
    ``current_backend.robot_states[robot_id]``, so every arm gets live
    heatmap-colored telemetry.

    When no assignments exist, all arms remain hidden — the scene shows
    only the operating table until robot services publish assignments.
    """
    init_joints = _NO_SIGNAL_POSE
    # Fixed dark scene palette — independent of the app light/dark toggle.
    _SCENE_BG = THEME_PALETTE["dark"]["bg_bottom"]  # #1B2838
    _SCENE_JOINT = THEME_PALETTE["dark"]["arm"]  # #C8D2DC
    with ui.scene(
        width=860,
        height=580,
        camera=ui.scene.perspective_camera(fov=40),
        background_color=_SCENE_BG,
    ).classes("w-full") as scene:
        scene.move_camera(
            x=3.5,
            y=-2.8,
            z=2.8,
            look_at_x=0.2,
            look_at_y=0.60,
            look_at_z=1.0,
            up_x=0.0,
            up_y=0.0,
            up_z=1.0,
            duration=0,
        )

        # ── Operating table (rendered from DEFAULT_TABLE geometry) ──────
        t = DEFAULT_TABLE
        _t_steel = "#607D8B"
        _t_col_h = t.surface_z - t.slab_h * 0.5 - t.foot_h

        # Foot platform with rounded corners (cross-box + 4 corner cylinders)
        for _bw, _bd in [
            (t.foot_w - 2 * t.foot_r, t.foot_d),
            (t.foot_w, t.foot_d - 2 * t.foot_r),
        ]:
            scene.box(_bw, _bd, t.foot_h).move(t.cx, t.cy, t.foot_h / 2).material(
                color=_t_steel
            )
        for _tsx, _tsy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
            scene.cylinder(t.foot_r, t.foot_r, t.foot_h, 16).move(
                t.cx + _tsx * (t.foot_w / 2 - t.foot_r),
                t.cy + _tsy * (t.foot_d / 2 - t.foot_r),
                t.foot_h / 2,
            ).rotate(math.pi / 2, 0, 0).material(color=_t_steel)

        # Center pedestal column — narrow square section
        scene.box(t.col_side, t.col_side, _t_col_h).move(
            t.cx, t.cy, t.foot_h + _t_col_h / 2
        ).material(color=_t_steel)

        # Table top slab
        scene.box(t.half_length * 2, t.half_width * 2, t.slab_h).move(
            t.cx, t.cy, t.surface_z
        ).material(color="#ECEFF1", opacity=0.95)
        # Mattress
        scene.box(t.half_length * 1.92, t.half_width * 1.84, 0.06).move(
            t.cx, t.cy, t.surface_z + t.slab_h / 2 + 0.03
        ).material(color="#B0BEC5", opacity=0.95)
        # Head-rest block
        scene.box(0.28, t.half_width * 1.7, 0.08).move(
            t.cx - t.half_length + 0.14,
            t.cy,
            t.surface_z + t.slab_h / 2 + 0.04,
        ).material(color="#90A4AE")

        # ── Arms — one per TablePosition from surgery.idl ──────────────
        # Keyed by TablePosition enum so assignment mapping is direct.
        arm_objects: dict[TablePosition, dict[str, Any]] = {}
        for pos in t.positions:
            ox, oy = t.get_position(pos)
            (
                arm_segs,
                jnt_spheres,
                shoulder_sphere,
                tool_sphere,
                nib,
                instr_dot,
                nib_half,
                base_parts,
            ) = _build_arm(scene, ox, oy, init_joints, joint_color=_SCENE_JOINT)
            arm_objects[pos] = {
                "position": pos,
                "ox": ox,
                "oy": oy,
                "arm_segs": arm_segs,
                "jnt_spheres": jnt_spheres,
                "shoulder_sphere": shoulder_sphere,
                "tool_sphere": tool_sphere,
                "nib": nib,
                "instr_dot": instr_dot,
                "nib_half": nib_half,
                "base_parts": base_parts,
                "seg_colors": [""] * len(arm_segs),
            }

    # All arms start hidden; update_scene shows those with assignments.

    # ---- Arm assignment overlay (HTML below scene) -------------------------
    arm_status_container = ui.column().classes("w-full px-4 gap-1 glass-panel")

    def _position_for_assignment(assignment: Any) -> TablePosition | None:
        """Return the TablePosition for an assignment, or None if UNKNOWN."""
        tp = TablePosition(int(getattr(assignment, "table_position", 0)))
        return tp if tp != TablePosition.UNKNOWN else None

    def _assign_positions(
        assignments: dict[str, Any],
    ) -> dict[str, TablePosition]:
        """Map robot_ids to TablePosition enum values.

        Arms with a known table_position use it directly.
        Arms with UNKNOWN get the next free position via round-robin.
        """
        pos_map: dict[str, TablePosition] = {}
        used: set[TablePosition] = set()
        # First pass: arms with known positions
        for robot_id in sorted(assignments):
            tp = _position_for_assignment(assignments[robot_id])
            if tp is not None and tp not in used:
                pos_map[robot_id] = tp
                used.add(tp)
        # Second pass: round-robin for UNKNOWN positions
        rr_idx = 0
        for robot_id in sorted(assignments):
            if robot_id in pos_map:
                continue
            while rr_idx < len(POSITION_ROUND_ROBIN):
                candidate = POSITION_ROUND_ROBIN[rr_idx]
                rr_idx += 1
                if candidate not in used:
                    pos_map[robot_id] = candidate
                    used.add(candidate)
                    break
        return pos_map

    def _build_arm_overlay() -> None:
        """Rebuild the arm status overlay from current assignments."""
        arm_status_container.clear()
        assignments = current_backend.arm_assignments
        if not assignments:
            return
        with arm_status_container:
            ui.label("Arm Assignments").classes("type-label mt-2")
            for robot_id, assignment in sorted(assignments.items()):
                status = ArmAssignmentState(int(getattr(assignment, "status", 0)))
                color = ARM_STATE_COLORS.get(status, BRAND_COLORS["gray"])
                tp = TablePosition(int(getattr(assignment, "table_position", 0)))
                caps = str(getattr(assignment, "capabilities", ""))
                with ui.expansion(
                    f"{robot_id} — {status.name}",
                    icon="precision_manufacturing",
                ).classes("w-full").props(f'header-style="color: {color}"'):
                    ui.label(f"Position: {tp.name}").classes("type-body-sm")
                    ui.label(f"State: {status.name}").classes("type-body-sm")
                    if caps:
                        ui.label(f"Capabilities: {caps}").classes("type-body-sm")

    def _set_arm_visibility(arm_obj: dict[str, Any], visible: bool) -> None:
        """Set material opacity on all arm parts (including base) to show/hide."""
        opacity = 1.0 if visible else 0.0
        for part in arm_obj["base_parts"]:
            part.material(opacity=opacity)
        for seg in arm_obj["arm_segs"]:
            seg.material(opacity=opacity)
        for jsph in arm_obj["jnt_spheres"]:
            jsph.material(opacity=opacity)
        arm_obj["shoulder_sphere"].material(opacity=opacity)
        arm_obj["tool_sphere"].material(opacity=opacity)
        arm_obj["nib"].material(opacity=opacity)
        arm_obj["instr_dot"].material(opacity=opacity)

    # Track previous assignment state for visibility delta
    _prev_arm_count = [0]

    _prev_estop = [False]

    def update_scene() -> None:
        mode_badge.set_text(current_backend.operational_mode.name)
        is_estop = current_backend.operational_mode == RobotMode.EMERGENCY_STOP
        if is_estop and not _prev_estop[0]:
            mode_badge.classes(add="pulse-critical")
        elif not is_estop and _prev_estop[0]:
            mode_badge.classes(remove="pulse-critical")
        _prev_estop[0] = is_estop

        assignments = current_backend.arm_assignments
        pos_map = _assign_positions(assignments)
        active: set[TablePosition] = set(pos_map.values())

        # Show/hide arms based on active positions
        for pos in arm_objects:
            _set_arm_visibility(arm_objects[pos], pos in active)

        # Build reverse map: position → robot_id for joint lookup
        pos_to_robot: dict[TablePosition, str] = {v: k for k, v in pos_map.items()}

        # Update visible arms with per-robot telemetry
        for pos in active:
            robot_id = pos_to_robot.get(pos, "")
            joints = current_backend.get_robot_joints(robot_id)
            arm_obj = arm_objects[pos]
            _update_arm_direct(
                arm_obj, arm_obj["ox"], arm_obj["oy"], joints or _NO_SIGNAL_POSE
            )

        # Rebuild overlay when arm count changes
        arm_count = len(assignments)
        if arm_count != _prev_arm_count[0]:
            _prev_arm_count[0] = arm_count
            _build_arm_overlay()

    ui.timer(0.1, update_scene)


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #


def main() -> None:
    """Standalone launch entry point."""
    storage_secret = os.environ.get(
        NICEGUI_STORAGE_SECRET_ENV, NICEGUI_STORAGE_SECRET_DEFAULT
    )

    room_id = os.environ.get("ROOM_ID", "OR-1")
    _get_backend(room_id)

    # Root redirect: navigating to / sends the browser to the room-specific page.
    @ui.page("/")
    def _root() -> None:
        ui.navigate.to(f"/twin/{room_id}")

    try:
        ui.run(
            storage_secret=storage_secret,
            reload=False,
            title="Digital Twin — Medtech Suite",
            favicon="/images/favicon.ico",
        )
    except KeyboardInterrupt:
        pass


if __name__ in {"__main__", "__mp_main__"}:
    main()


__all__ = [
    "ARM_STATE_COLORS",
    "DEFAULT_TABLE",
    "DigitalTwinBackend",
    "MODE_COLORS",
    "OperatingTable",
    "heatmap_color",
    "main",
    "twin_content",
    "twin_page",
]
