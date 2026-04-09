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

# Operating table dimensions and world position.
# Table is 2.2 m long × 0.85 m wide — large relative to the arm.
_TABLE_X = 1.10  # half-length (2.2 m total)
_TABLE_Y = 0.425  # half-width  (0.85 m total)
_TABLE_SLAB_H = 0.08  # top slab thickness
_TABLE_TOP_Z = 0.80  # table surface height (z)
# Pedestal column (narrow square section connecting foot platform to slab)
_TABLE_COL_S = 0.22  # column square side
# Foot platform (wide low base with caster-style appearance)
_TABLE_FOOT_W = 0.80  # foot platform full length (X)
_TABLE_FOOT_D = 0.36  # foot platform full depth (Y)
_TABLE_FOOT_H = 0.08  # foot platform height
_TABLE_FOOT_R = 0.035  # foot platform corner radius
# Surface Z above which arm segment knuckle centres must stay when over the
# table footprint.  = mattress top (0.90) + max joint sphere radius (0.130)
# + safety margin (0.02) ≈ 1.05 m.
# Using a hard literal is intentional — this is a scene-layout constant.
_TABLE_SURFACE_Z = 1.05
_TABLE_CX = 0.0  # table centred at world origin X
_TABLE_CY = 0.65  # table offset in Y

# Pre-defined arm mount slots around the table.
# Each slot has a stable (ox, oy) world position and a human-readable label.
# _build_scene uses slot 0 for the single-arm case.  When multi-arm support
# is added each slot maps to its own DigitalTwinBackend instance.
_ARM_SLOTS: list[dict] = [
    {"id": "arm-1", "ox": 0.30, "oy": -0.45, "label": "Near-right"},
    {"id": "arm-2", "ox": -0.50, "oy": -0.45, "label": "Near-left"},
    {"id": "arm-3", "ox": 0.30, "oy": 1.75, "label": "Far-right"},
    {"id": "arm-4", "ox": -0.50, "oy": 1.75, "label": "Far-left"},
]
# Backwards-compatible single-arm offset (slot 0)
_ARM_OX = _ARM_SLOTS[0]["ox"]
_ARM_OY = _ARM_SLOTS[0]["oy"]
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
        # that would bring that sample up to _TABLE_SURFACE_Z (linear solve),
        # and take the strictest (highest) requirement across all samples.
        _ty_min = _TABLE_CY - _TABLE_Y
        _ty_max = _TABLE_CY + _TABLE_Y
        _tx_min = _TABLE_CX - _TABLE_X
        _tx_max = _TABLE_CX + _TABLE_X
        _min_z_local = _TABLE_SURFACE_Z - _ARM_BASE_Z
        for _si in range(8):
            _t = _si / 7.0
            _sx = pos[0] + _t * (kx - pos[0])
            _sy = pos[1] + _t * (ky - pos[1])
            _sz_world = (pos[2] + _t * (kz - pos[2])) + _ARM_BASE_Z
            if (
                _tx_min <= _sx + ox <= _tx_max
                and _ty_min <= _sy + oy <= _ty_max
                and _sz_world < _TABLE_SURFACE_Z
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


@ui.page("/twin/{room_id}")
def twin_page(room_id: str) -> None:
    """Render the digital twin 3D visualization page for *room_id* (full-page with header)."""
    init_theme()
    create_header(title=f"Digital Twin — {room_id}")
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
        ui.label(f"Room: {room_id}").classes("text-lg font-bold")
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
) -> tuple[list[Any], list[Any], Any, Any, Any, Any, float]:
    """Construct one arm instance in *scene* at world offset (ox, oy).

    Returns (arm_segs, jnt_spheres, shoulder_sphere, tool_sphere, nib, instr_dot, nib_half).
    shoulder_sphere is returned separately so the theme-change handler can
    recolor it (along with jnt_spheres) without rebuilding the scene.
    Extracting arm construction here means adding a second (or Nth) arm
    later is a single extra ``_build_arm()`` call in ``_build_scene``.
    """
    B = _ARM_BASE_Z
    geo = _compute_arm_geometry(init_joints, ox, oy)

    # ── Mobile cart base ───────────────────────────────────────────────────
    cart_w, cart_d, cart_h = 0.55, 0.45, 0.18
    _cart_color = "#546E7A"  # grey-scale
    _post_color = "#78909C"  # lighter for corner posts
    scene.box(cart_w, cart_d, cart_h).move(ox, oy, cart_h / 2).material(
        color=_cart_color
    )
    # Corner posts — cylinders at each vertical edge give a modern rounded-edge
    # appearance (industrial equipment / medical cart aesthetic).
    _post_r = 0.028
    for _csx, _csy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
        scene.cylinder(_post_r, _post_r, cart_h, 16).move(
            ox + _csx * (cart_w / 2), oy + _csy * (cart_d / 2), cart_h / 2
        ).rotate(math.pi / 2, 0, 0).material(color=_post_color)
    # Corner wheels
    for wx, wy in [
        (ox - cart_w / 2 + 0.07, oy - cart_d / 2 + 0.07),
        (ox + cart_w / 2 - 0.07, oy - cart_d / 2 + 0.07),
        (ox - cart_w / 2 + 0.07, oy + cart_d / 2 - 0.07),
        (ox + cart_w / 2 - 0.07, oy + cart_d / 2 - 0.07),
    ]:
        scene.sphere(0.055).move(wx, wy, 0.055).material(color="#263238")
    # Riser column — 24 segments for smoother silhouette
    col_h = B - cart_h
    scene.cylinder(0.08, 0.08, col_h, 24).move(ox, oy, cart_h + col_h / 2).rotate(
        math.pi / 2, 0, 0
    ).material(color=_cart_color)
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
    return arm_segs, jnt_spheres, shoulder_sphere, tool_sphere, nib, instr_dot, nib_half


def _make_arm_updater(
    arm_segs: list[Any],
    jnt_spheres: list[Any],
    tool_sphere: Any,
    nib: Any,
    instr_dot: Any,
    nib_half: float,
    ox: float,
    oy: float,
    get_joints: Any,
) -> Any:
    """Return an ``update()`` callable that repositions one arm's scene objects.

    Each arm closure captures its own (ox, oy, get_joints) independently,
    so N arms can each call their updater at 10 Hz without interfering.
    ``get_joints`` is a zero-argument callable returning ``list[float]``.
    """
    B = _ARM_BASE_Z

    def update() -> None:
        joints = get_joints() or _NO_SIGNAL_POSE
        g = _compute_arm_geometry(joints, ox, oy)
        for i, (seg, jsph, cfg) in enumerate(
            zip(arm_segs, jnt_spheres, _JOINT_CONFIGS)
        ):
            angle = joints[i] if i < len(joints) else 0.0
            gi = g[i]
            seg.move(gi["cx"] + ox, gi["cy"] + oy, gi["cz"] + B).rotate(
                gi["rx"], gi["ry"], gi["rz"]
            ).material(color=heatmap_color(angle))
            jsph.move(gi["kx"] + ox, gi["ky"] + oy, gi["kz"] + B)
        tip = g[-1]
        fwd = tip["fwd"]
        rx, ry, rz = _euler_from_direction(*fwd)
        tool_sphere.move(tip["tip_x"] + ox, tip["tip_y"] + oy, tip["tip_z"] + B)
        nib.move(
            tip["tip_x"] + fwd[0] * nib_half + ox,
            tip["tip_y"] + fwd[1] * nib_half + oy,
            tip["tip_z"] + fwd[2] * nib_half + B,
        ).rotate(rx, ry, rz)
        instr_dot.move(
            tip["tip_x"] + fwd[0] * nib_half * 2 + ox,
            tip["tip_y"] + fwd[1] * nib_half * 2 + oy,
            tip["tip_z"] + fwd[2] * nib_half * 2 + B,
        )

    return update


def _build_scene(
    current_backend: DigitalTwinBackend,
    mode_badge: Any,
) -> None:
    """Build the 3D scene and attach the update timer.

    The 3D scene uses a fixed dark background regardless of the app UI theme.
    This is standard for surgical/simulation viewports (da Vinci, Stryker, etc.)
    and avoids the NiceGUI v3 limitation where ui.scene's Three.js renderer
    background is set once in mounted() and cannot be updated reactively.

    The arm is constructed via ``_build_arm()`` / ``_make_arm_updater()``.
    To add more arms in a future step, add entries to ``_ARM_SLOTS`` and
    call ``_build_arm()`` + ``_make_arm_updater()`` once per slot, passing
    each slot's backend's ``joint_positions`` getter.
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

        # ── Operating table ────────────────────────────────────────────────
        # Shape: OR table profile from reference image — narrow center column
        # rising from a wide low foot platform to support the table slab.
        _t_steel = "#607D8B"
        _t_col_h = _TABLE_TOP_Z - _TABLE_SLAB_H * 0.5 - _TABLE_FOOT_H

        # Foot platform with rounded corners (cross-box + 4 corner cylinders)
        for _bw, _bd in [
            (_TABLE_FOOT_W - 2 * _TABLE_FOOT_R, _TABLE_FOOT_D),
            (_TABLE_FOOT_W, _TABLE_FOOT_D - 2 * _TABLE_FOOT_R),
        ]:
            scene.box(_bw, _bd, _TABLE_FOOT_H).move(
                _TABLE_CX, _TABLE_CY, _TABLE_FOOT_H / 2
            ).material(color=_t_steel)
        for _tsx, _tsy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
            scene.cylinder(_TABLE_FOOT_R, _TABLE_FOOT_R, _TABLE_FOOT_H, 16).move(
                _TABLE_CX + _tsx * (_TABLE_FOOT_W / 2 - _TABLE_FOOT_R),
                _TABLE_CY + _tsy * (_TABLE_FOOT_D / 2 - _TABLE_FOOT_R),
                _TABLE_FOOT_H / 2,
            ).rotate(math.pi / 2, 0, 0).material(color=_t_steel)

        # Center pedestal column — narrow square section
        scene.box(_TABLE_COL_S, _TABLE_COL_S, _t_col_h).move(
            _TABLE_CX, _TABLE_CY, _TABLE_FOOT_H + _t_col_h / 2
        ).material(color=_t_steel)

        # Table top slab
        scene.box(_TABLE_X * 2, _TABLE_Y * 2, _TABLE_SLAB_H).move(
            _TABLE_CX, _TABLE_CY, _TABLE_TOP_Z
        ).material(color="#ECEFF1", opacity=0.95)
        # Mattress
        scene.box(_TABLE_X * 1.92, _TABLE_Y * 1.84, 0.06).move(
            _TABLE_CX, _TABLE_CY, _TABLE_TOP_Z + _TABLE_SLAB_H / 2 + 0.03
        ).material(color="#B0BEC5", opacity=0.95)
        # Head-rest block
        scene.box(0.28, _TABLE_Y * 1.7, 0.08).move(
            _TABLE_CX - _TABLE_X + 0.14,
            _TABLE_CY,
            _TABLE_TOP_Z + _TABLE_SLAB_H / 2 + 0.04,
        ).material(color="#90A4AE")

        # ── Arm (slot 0) ───────────────────────────────────────────────────
        slot = _ARM_SLOTS[0]
        (
            arm_segs,
            jnt_spheres,
            shoulder_sphere,
            tool_sphere,
            nib,
            instr_dot,
            nib_half,
        ) = _build_arm(
            scene, slot["ox"], slot["oy"], init_joints, joint_color=_SCENE_JOINT
        )

    arm_update = _make_arm_updater(
        arm_segs,
        jnt_spheres,
        tool_sphere,
        nib,
        instr_dot,
        nib_half,
        slot["ox"],
        slot["oy"],
        lambda: current_backend.joint_positions,
    )

    def update_scene() -> None:
        arm_update()
        mode_badge.set_text(current_backend.operational_mode)

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

    # Root redirect: navigating to / sends the browser to the room-specific page.
    @ui.page("/")
    def _root() -> None:
        ui.navigate.to(f"/twin/{room_id}")

    try:
        ui.run(
            storage_secret=storage_secret,
            reload=False,
        )
    except KeyboardInterrupt:
        pass


if __name__ in {"__main__", "__mp_main__"}:
    main()


__all__ = [
    "DigitalTwinBackend",
    "heatmap_color",
    "main",
    "twin_content",
    "twin_page",
]
