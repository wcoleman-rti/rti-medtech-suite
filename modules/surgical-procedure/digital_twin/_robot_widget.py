"""2D robot visualization widget for the digital twin display.

Renders:
- Segmented arm schematic from joint angles (``RobotState.joint_positions``)
- Tool-tip position indicator from ``RobotState.tool_tip_position``
- Operational mode label (OPERATIONAL, PAUSED, EMERGENCY_STOP, IDLE)
- Active ``RobotCommand`` annotation (target position, trajectory indicator)
- Safety interlock overlay: red banner + "INTERLOCK ACTIVE"
- Disconnected overlay: gray fill + "DISCONNECTED" label

All state mutations call ``self.update()`` to schedule a repaint.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

# RTI brand colors
_COLOR_RTI_BLUE = QColor("#004C97")
_COLOR_RTI_ORANGE = QColor("#ED8B00")
_COLOR_RTI_GREEN = QColor("#A4D65E")
_COLOR_RTI_GRAY = QColor("#63666A")
_COLOR_RTI_LIGHT_GRAY = QColor("#BBBCBC")

# Semantic colors
_COLOR_INTERLOCK_RED = QColor(220, 50, 50, 220)  # semi-transparent
_COLOR_DISCONNECTED = QColor(100, 100, 100, 180)

# Joint arm lengths in widget-space (fraction of min dimension)
_JOINT_SEGMENT_LENGTH = 0.14

# Mode display strings
_MODE_LABELS = {
    0: "UNKNOWN",
    1: "IDLE",
    2: "OPERATIONAL",
    3: "PAUSED",
    4: "EMERGENCY_STOP",
}


class RobotWidget(QWidget):
    """2D robot arm visualization widget.

    Designed for dependency-injection testability: all state is updated
    via public setter methods. No DDS types are imported here — callers
    pass data objects whose attributes are read by name.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._robot_state = None
        self._command = None
        self._interlock = None
        self._connected: bool = True

        self.setMinimumSize(300, 300)
        self.setObjectName("robotWidget")

    # ------------------------------------------------------------------ #
    # Public state setters (called from async DDS receivers or tests)     #
    # ------------------------------------------------------------------ #

    def update_robot_state(self, state) -> None:
        """Store the latest RobotState and trigger a repaint."""
        self._robot_state = state
        self._connected = True
        self.update()

    def update_command(self, cmd) -> None:
        """Store the latest RobotCommand and trigger a repaint."""
        self._command = cmd
        self.update()

    def update_interlock(self, interlock) -> None:
        """Store the latest SafetyInterlock and trigger a repaint."""
        self._interlock = interlock
        self.update()

    def set_connected(self, connected: bool) -> None:
        """Set writer liveliness state; triggers repaint."""
        self._connected = connected
        self.update()

    # ------------------------------------------------------------------ #
    # Read-only accessors (for test assertions)                           #
    # ------------------------------------------------------------------ #

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def has_robot_state(self) -> bool:
        return self._robot_state is not None

    @property
    def has_command(self) -> bool:
        return self._command is not None

    @property
    def interlock_active(self) -> bool:
        return self._interlock is not None and getattr(
            self._interlock, "interlock_active", False
        )

    @property
    def operational_mode(self) -> str:
        if self._robot_state is None:
            return "UNKNOWN"
        mode_val = getattr(self._robot_state, "operational_mode", 0)
        # Handles both int and IntEnum
        return _MODE_LABELS.get(int(mode_val), "UNKNOWN")

    # ------------------------------------------------------------------ #
    # QPainter rendering                                                   #
    # ------------------------------------------------------------------ #

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w // 2, h // 2
        radius = min(w, h) * _JOINT_SEGMENT_LENGTH

        # Background
        painter.fillRect(0, 0, w, h, QColor("#1A1A2E"))

        if self._connected:
            self._draw_robot_arm(painter, cx, cy, radius)
            if self._command is not None:
                self._draw_command_annotation(painter, cx, cy, radius)
        else:
            self._draw_disconnected(painter, w, h)
            return

        # Interlock overlay (drawn on top of everything including arm)
        if self.interlock_active:
            self._draw_interlock_overlay(painter, w, h)

        # Mode label (bottom-right)
        self._draw_mode_label(painter, w, h)

    def _draw_robot_arm(self, p: QPainter, cx: int, cy: int, r: float) -> None:
        """Draw segmented arm from joint positions."""
        joint_positions = []
        if self._robot_state is not None:
            joint_positions = list(getattr(self._robot_state, "joint_positions", []))

        # Base circle
        p.setPen(QPen(_COLOR_RTI_BLUE, 2))
        p.setBrush(QBrush(_COLOR_RTI_BLUE))
        base_r = max(8, int(r * 0.5))
        p.drawEllipse(cx - base_r, cy - base_r, base_r * 2, base_r * 2)

        # Draw segments from joint angles (up to 6 joints)
        joints = joint_positions[:6] if joint_positions else [0.0, 0.0, 0.0]
        arm_pen = QPen(_COLOR_RTI_LIGHT_GRAY, 3)
        joint_pen = QPen(_COLOR_RTI_ORANGE, 2)
        p.setPen(arm_pen)

        x, y = float(cx), float(cy)
        cumulative_angle = 0.0
        for i, angle in enumerate(joints):
            cumulative_angle += angle
            rad = math.radians(cumulative_angle)
            x2 = x + r * math.cos(rad)
            y2 = y - r * math.sin(rad)
            # Segment line
            p.setPen(arm_pen)
            p.drawLine(int(x), int(y), int(x2), int(y2))
            # Joint dot
            p.setPen(joint_pen)
            p.setBrush(QBrush(_COLOR_RTI_ORANGE))
            jr = max(4, int(r * 0.25))
            p.drawEllipse(int(x) - jr, int(y) - jr, jr * 2, jr * 2)
            x, y = x2, y2

        # Tool-tip indicator
        if self._robot_state is not None:
            tip = getattr(self._robot_state, "tool_tip_position", None)
            if tip is not None:
                tip_x = cx + int(getattr(tip, "x", 0) * 0.5)
                tip_y = cy - int(getattr(tip, "y", 0) * 0.5)
                p.setPen(QPen(_COLOR_RTI_GREEN, 2))
                p.setBrush(QBrush(_COLOR_RTI_GREEN))
                tp_r = max(5, int(r * 0.3))
                p.drawEllipse(tip_x - tp_r, tip_y - tp_r, tp_r * 2, tp_r * 2)

    def _draw_command_annotation(self, p: QPainter, cx: int, cy: int, r: float) -> None:
        """Draw RobotCommand target position annotation."""
        target = getattr(self._command, "target_position", None)
        if target is None:
            return
        tx = cx + int(getattr(target, "x", 0) * 0.5)
        ty = cy - int(getattr(target, "y", 0) * 0.5)
        # Dashed circle around target
        pen = QPen(_COLOR_RTI_ORANGE, 2, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        ar = max(10, int(r * 0.6))
        p.drawEllipse(tx - ar, ty - ar, ar * 2, ar * 2)
        # Cross-hair
        p.drawLine(tx - ar, ty, tx + ar, ty)
        p.drawLine(tx, ty - ar, tx, ty + ar)

    def _draw_interlock_overlay(self, p: QPainter, w: int, h: int) -> None:
        """Draw a prominent red interlock banner."""
        # Semi-transparent red overlay
        p.fillRect(0, 0, w, h, _COLOR_INTERLOCK_RED)
        # Banner
        banner_h = max(40, h // 8)
        p.fillRect(0, h - banner_h, w, banner_h, QColor(200, 20, 20, 240))
        font = QFont("Montserrat", 14, QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QPen(QColor("white")))
        p.drawText(
            QRect(0, h - banner_h, w, banner_h),
            Qt.AlignmentFlag.AlignCenter,
            "⚠ INTERLOCK ACTIVE",
        )

    def _draw_disconnected(self, p: QPainter, w: int, h: int) -> None:
        """Draw the disconnected state overlay (grayed out)."""
        p.fillRect(0, 0, w, h, _COLOR_DISCONNECTED)
        font = QFont("Montserrat", 16, QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QPen(QColor("#BBBCBC")))
        p.drawText(
            QRect(0, 0, w, h),
            Qt.AlignmentFlag.AlignCenter,
            "DISCONNECTED",
        )

    def _draw_mode_label(self, p: QPainter, w: int, h: int) -> None:
        """Draw the operational mode label in the corner."""
        mode = self.operational_mode
        color_map = {
            "OPERATIONAL": _COLOR_RTI_GREEN,
            "PAUSED": _COLOR_RTI_ORANGE,
            "EMERGENCY_STOP": QColor(220, 50, 50),
            "IDLE": _COLOR_RTI_LIGHT_GRAY,
            "UNKNOWN": _COLOR_RTI_GRAY,
        }
        color = color_map.get(mode, _COLOR_RTI_GRAY)
        font = QFont("Roboto Condensed", 10, QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QPen(color))
        margin = 8
        label_rect = QRect(margin, h - 28, w - margin * 2, 24)
        p.drawText(
            label_rect,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            mode,
        )
