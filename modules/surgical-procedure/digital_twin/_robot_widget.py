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

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

# RTI brand colors
_COLOR_RTI_BLUE = QColor("#004C97")
_COLOR_RTI_ORANGE = QColor("#ED8B00")
_COLOR_RTI_GREEN = QColor("#A4D65E")
_COLOR_RTI_GRAY = QColor("#63666A")
_COLOR_RTI_LIGHT_GRAY = QColor("#BBBCBC")
_COLOR_RTI_LIGHT_BLUE = QColor("#00B5E2")

# Semantic colors
_COLOR_INTERLOCK_RED = QColor(211, 47, 47, 200)  # semi-transparent
_COLOR_DISCONNECTED = QColor(60, 63, 66, 200)

# Joint arm lengths in widget-space (fraction of min dimension)
_JOINT_SEGMENT_LENGTH = 0.14

# Heatmap color ramp: blue (negative) → neutral → orange (positive)
_HEATMAP_COLD = QColor("#1565C0")  # strong negative
_HEATMAP_ZERO = QColor("#263238")  # near zero (dark theme neutral)
_HEATMAP_HOT = QColor("#ED8B00")  # strong positive
_HEATMAP_ZERO_LIGHT = QColor(
    "#78909C"
)  # near zero (light theme neutral — blue-gray 400)
_HEATMAP_ANGLE_MAX = 180.0  # angle mapped to full saturation


def _heatmap_color(angle: float, dark: bool = True) -> QColor:
    """Map a joint angle to a diverging blue→neutral→orange color."""
    t = max(-1.0, min(1.0, angle / _HEATMAP_ANGLE_MAX))
    zero = _HEATMAP_ZERO if dark else _HEATMAP_ZERO_LIGHT
    if t >= 0:
        r = int(zero.red() + (_HEATMAP_HOT.red() - zero.red()) * t)
        g = int(zero.green() + (_HEATMAP_HOT.green() - zero.green()) * t)
        b = int(zero.blue() + (_HEATMAP_HOT.blue() - zero.blue()) * t)
    else:
        at = -t
        r = int(zero.red() + (_HEATMAP_COLD.red() - zero.red()) * at)
        g = int(zero.green() + (_HEATMAP_COLD.green() - zero.green()) * at)
        b = int(zero.blue() + (_HEATMAP_COLD.blue() - zero.blue()) * at)
    return QColor(r, g, b)


# Theme-dependent color palettes
_PALETTE_DARK = {
    "bg_top": QColor("#0D1B2A"),
    "bg_bottom": QColor("#1B2838"),
    "grid": QColor(255, 255, 255, 12),
    "arm": QColor(200, 210, 220, 200),
    "hud_bg": QColor(13, 27, 42, 216),  # 85% opacity
    "hud_shadow": QColor(0, 0, 0, 38),  # 15% opacity
    "hud_label": QColor(187, 188, 188),
    "hud_value": QColor(0, 181, 226),
    "disc_bg": QColor(45, 48, 52, 220),
    "disc_text": QColor("#BBBCBC"),
}

_PALETTE_LIGHT = {
    "bg_top": QColor("#E8EDF2"),
    "bg_bottom": QColor("#F7F8FA"),
    "grid": QColor(0, 0, 0, 12),
    "arm": QColor(80, 90, 100, 200),
    "hud_bg": QColor(255, 255, 255, 216),  # 85% opacity
    "hud_shadow": QColor(0, 0, 0, 38),  # 15% opacity
    "hud_label": QColor(99, 102, 106),
    "hud_value": QColor(0, 76, 151),
    "disc_bg": QColor(210, 212, 215, 220),
    "disc_text": QColor("#63666A"),
}

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
        self._palette = _PALETTE_DARK  # default
        self._selected_arm: int | None = None  # tap-to-select arm index
        self._arm_row_rects: list[QRectF] = []  # hit-test rects per arm row
        self._arm_canvas_rects: list[QRectF] = []  # hit-test rects per arm on canvas

        self.setMinimumSize(300, 300)
        self.setObjectName("robotWidget")

        # Listen for theme changes
        try:
            from medtech_gui._theme import ThemeManager

            mgr = ThemeManager.instance()
            if mgr is not None:
                mgr.theme_changed.connect(self._on_theme_changed)
                self._on_theme_changed(mgr.effective_theme)
        except ImportError:
            pass

    def _on_theme_changed(self, theme: str) -> None:
        """Switch rendering palette when the application theme changes."""
        self._palette = _PALETTE_LIGHT if theme == "light" else _PALETTE_DARK
        self.update()

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
    # Touch / click interaction                                           #
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """Tap-to-select a heatmap arm row (or deselect on miss)."""
        pos = event.position() if hasattr(event, "position") else event.pos()
        hit = False
        # Check heatmap rows
        for idx, rect in enumerate(self._arm_row_rects):
            if rect.contains(pos):
                self._selected_arm = idx if self._selected_arm != idx else None
                hit = True
                break
        # Check arm canvas regions
        if not hit:
            for idx, rect in enumerate(self._arm_canvas_rects):
                if rect.contains(pos):
                    self._selected_arm = idx if self._selected_arm != idx else None
                    hit = True
                    break
        if not hit:
            self._selected_arm = None
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

        # Gradient background (theme-aware)
        pal = self._palette
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, pal["bg_top"])
        bg.setColorAt(1.0, pal["bg_bottom"])
        painter.fillRect(0, 0, w, h, bg)

        # Subtle grid pattern
        self._draw_grid(painter, w, h)

        if self._connected:
            self._draw_robot_arm(painter, cx, cy, radius)
            if self._command is not None:
                self._draw_command_annotation(painter, cx, cy, radius)
            # HUD overlay with live telemetry (#3)
            self._draw_hud(painter, w, h)
        else:
            self._draw_disconnected(painter, w, h)
            return

        # Interlock overlay (drawn on top of everything including arm)
        if self.interlock_active:
            self._draw_interlock_overlay(painter, w, h)

        # Mode label (bottom-right)
        self._draw_mode_label(painter, w, h)

    def _draw_grid(self, p: QPainter, w: int, h: int) -> None:
        """Draw a subtle reference grid behind the robot."""
        pen = QPen(self._palette["grid"], 1)
        p.setPen(pen)
        spacing = max(40, min(w, h) // 10)
        for x in range(0, w, spacing):
            p.drawLine(x, 0, x, h)
        for y in range(0, h, spacing):
            p.drawLine(0, y, w, y)

    def _draw_robot_arm(self, p: QPainter, cx: int, cy: int, r: float) -> None:
        """Draw segmented arm from joint positions."""
        joint_positions = []
        if self._robot_state is not None:
            joint_positions = list(getattr(self._robot_state, "joint_positions", []))

        # Base shadow (soft elevation ring)
        base_r = max(10, int(r * 0.55))
        shadow_r = base_r + 4
        shadow_col = QColor(0, 76, 151, 38)  # 15% opacity
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(shadow_col))
        p.drawEllipse(cx - shadow_r, cy - shadow_r, shadow_r * 2, shadow_r * 2)

        # Base circle — flat fill
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_COLOR_RTI_BLUE))
        p.drawEllipse(cx - base_r, cy - base_r, base_r * 2, base_r * 2)

        # Draw segments from joint angles (up to 7 joints)
        joints = joint_positions[:7] if joint_positions else [0.0, 0.0, 0.0]
        is_dark = self._palette is _PALETTE_DARK
        selected = self._selected_arm == 0

        # Capsule thickness — thinner segments with visible joint knuckles
        cap_w = max(6, int(r * 0.32))
        knuckle_r = max(4, int(cap_w * 0.65))

        # Track bounding box of all joint positions for hit-testing
        pts_x: list[float] = [float(cx)]
        pts_y: list[float] = [float(cy)]

        # Pre-compute segment endpoints
        segments: list[tuple[float, float, float, float]] = []
        x, y = float(cx), float(cy)
        cumulative_angle = 0.0
        for angle in joints:
            cumulative_angle += angle
            rad = math.radians(cumulative_angle)
            x2 = x + r * math.cos(rad)
            y2 = y - r * math.sin(rad)
            segments.append((x, y, x2, y2))
            pts_x.append(x2)
            pts_y.append(y2)
            x, y = x2, y2

        # Selection glow pass — wider semi-transparent stroke under the arm
        if selected:
            glow_col = QColor(_COLOR_RTI_LIGHT_BLUE)
            glow_col.setAlpha(45)
            glow_pen = QPen(glow_col, cap_w + 14)
            glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(glow_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for sx, sy, sx2, sy2 in segments:
                p.drawLine(int(sx), int(sy), int(sx2), int(sy2))

        # Capsule segments — flat heatmap-colored pills
        for i, (sx, sy, sx2, sy2) in enumerate(segments):
            jc = _heatmap_color(joints[i], is_dark)
            cap_pen = QPen(jc, cap_w)
            cap_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(cap_pen)
            p.drawLine(int(sx), int(sy), int(sx2), int(sy2))

        # Joint knuckles — small flat circles at each joint point
        # Drawn on top so they sit above the capsule overlap
        for i, (sx, sy, _sx2, _sy2) in enumerate(segments):
            jc = _heatmap_color(joints[i], is_dark)
            knuckle_col = jc.lighter(140) if is_dark else jc.darker(120)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(knuckle_col))
            p.drawEllipse(
                int(sx) - knuckle_r,
                int(sy) - knuckle_r,
                knuckle_r * 2,
                knuckle_r * 2,
            )
        # End-effector knuckle at the tip of the last segment
        if segments:
            _, _, ex, ey = segments[-1]
            last_jc = _heatmap_color(joints[-1], is_dark)
            end_col = last_jc.lighter(140) if is_dark else last_jc.darker(120)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(end_col))
            p.drawEllipse(
                int(ex) - knuckle_r,
                int(ey) - knuckle_r,
                knuckle_r * 2,
                knuckle_r * 2,
            )

        # Store arm bounding rect for tap hit-testing (arm index 0)
        pad_bbox = r * 0.4
        self._arm_canvas_rects = [
            QRectF(
                min(pts_x) - pad_bbox,
                min(pts_y) - pad_bbox,
                max(pts_x) - min(pts_x) + pad_bbox * 2,
                max(pts_y) - min(pts_y) + pad_bbox * 2,
            )
        ]

        # Tool-tip indicator — flat green dot with shadow
        if self._robot_state is not None:
            tip = getattr(self._robot_state, "tool_tip_position", None)
            if tip is not None:
                tip_x = cx + int(getattr(tip, "x", 0) * 0.5)
                tip_y = cy - int(getattr(tip, "y", 0) * 0.5)
                tp_r = max(6, int(r * 0.35))
                # Shadow ring (15% opacity)
                shadow_col = QColor(164, 214, 94, 38)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(shadow_col))
                sr = tp_r + 4
                p.drawEllipse(tip_x - sr, tip_y - sr, sr * 2, sr * 2)
                # Flat dot
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(_COLOR_RTI_GREEN))
                p.drawEllipse(tip_x - tp_r, tip_y - tp_r, tp_r * 2, tp_r * 2)

    def _draw_command_annotation(self, p: QPainter, cx: int, cy: int, r: float) -> None:
        """Draw RobotCommand target position annotation."""
        target = getattr(self._command, "target_position", None)
        if target is None:
            return
        tx = cx + int(getattr(target, "x", 0) * 0.5)
        ty = cy - int(getattr(target, "y", 0) * 0.5)
        ar = max(12, int(r * 0.65))

        # Flat shadow ring around target (15% opacity)
        shadow_col = QColor(237, 139, 0, 38)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(shadow_col))
        sr = ar + 6
        p.drawEllipse(tx - sr, ty - sr, sr * 2, sr * 2)

        # Dashed circle around target
        pen = QPen(_COLOR_RTI_ORANGE, 2, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(tx - ar, ty - ar, ar * 2, ar * 2)

        # Cross-hair with rounded caps
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(tx - ar, ty, tx + ar, ty)
        p.drawLine(tx, ty - ar, tx, ty + ar)

    def _draw_interlock_overlay(self, p: QPainter, w: int, h: int) -> None:
        """Draw a prominent red interlock banner."""
        # Semi-transparent red overlay
        p.fillRect(0, 0, w, h, _COLOR_INTERLOCK_RED)

        # Flat banner at bottom
        banner_h = max(48, h // 7)
        banner_rect = QRect(0, h - banner_h, w, banner_h)
        p.fillRect(banner_rect, QColor(211, 47, 47, 240))

        font = QFont("Roboto Condensed", 16, QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QPen(QColor("white")))
        p.drawText(
            banner_rect,
            Qt.AlignmentFlag.AlignCenter,
            "\u26A0  INTERLOCK ACTIVE",
        )

    def _draw_disconnected(self, p: QPainter, w: int, h: int) -> None:
        """Draw the disconnected state overlay (grayed out)."""
        pal = self._palette
        # Flat muted fill
        p.fillRect(0, 0, w, h, pal["disc_bg"])

        # Disconnected icon — broken circle
        icon_r = min(w, h) // 8
        cx, cy = w // 2, h // 2 - 20
        pen = QPen(pal["disc_text"], 4, Qt.PenStyle.DashDotLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(cx - icon_r, cy - icon_r, icon_r * 2, icon_r * 2)

        # Label below icon
        font = QFont("Roboto Condensed", 18, QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QPen(pal["disc_text"]))
        label_rect = QRect(0, cy + icon_r + 12, w, 36)
        p.drawText(
            label_rect,
            Qt.AlignmentFlag.AlignCenter,
            "DISCONNECTED",
        )

    # ------------------------------------------------------------------ #
    # Heatmap strip rendering                                              #
    # ------------------------------------------------------------------ #

    _HEAT_CELL_MIN = 18  # minimum cell size
    _HEAT_CELL_MAX = 38  # maximum cell size
    _HEAT_GAP = 3  # gap between cells
    _HEAT_RADIUS = 4  # rounded corner radius
    _ARM_LABEL_W = 22  # width reserved for arm label ("A1")
    _DOT_R = 5  # connection dot radius
    _DOT_GAP = 8  # gap between last cell and connection dot

    def _heat_cell_size(self, widget_w: int) -> int:
        """Compute heatmap cell size scaled to widget width."""
        # Scale linearly: 22px at 600w, grows to max at ~1200w
        t = max(0.0, min(1.0, (widget_w - 400) / 800))
        return int(
            self._HEAT_CELL_MIN + t * (self._HEAT_CELL_MAX - self._HEAT_CELL_MIN)
        )

    def _draw_heatmap_row(
        self,
        p: QPainter,
        joints: list[float],
        x0: int,
        y0: int,
        is_dark: bool,
        expanded: bool = False,
        cs: int = 22,
    ) -> int:
        """Draw one arm's heatmap row. Returns the row width (cells only)."""
        gap = self._HEAT_GAP
        cr = self._HEAT_RADIUS

        for i, angle in enumerate(joints):
            cx = x0 + i * (cs + gap)
            rect = QRectF(cx, y0, cs, cs)

            # Cell background — heatmap color
            color = _heatmap_color(angle, is_dark)
            path = QPainterPath()
            path.addRoundedRect(rect, cr, cr)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            p.drawPath(path)

            # Value inside cell — only when row is expanded
            if expanded and cs >= 18:
                font_sz = max(6, cs // 3)
                val_font = QFont("Roboto Mono", font_sz, QFont.Weight.Bold)
                p.setFont(val_font)
                lum = color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114
                txt_color = QColor("white") if lum < 140 else QColor("#1B2838")
                p.setPen(QPen(txt_color))
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{angle:.0f}")

        return len(joints) * (cs + gap) - gap

    # ------------------------------------------------------------------ #
    # HUD overlay                                                          #
    # ------------------------------------------------------------------ #

    def _draw_hud(self, p: QPainter, w: int, h: int) -> None:
        """Draw floating heatmap rows (one per arm) with expand-on-tap."""
        if self._robot_state is None:
            return

        pal = self._palette
        is_dark = self._palette is _PALETTE_DARK

        # For now: single arm from RobotState. Multi-arm will be a list.
        arms = [list(getattr(self._robot_state, "joint_positions", []))[:7]]

        cs = self._heat_cell_size(w)
        gap = self._HEAT_GAP
        pad = 12
        margin = 12
        label_w = self._ARM_LABEL_W
        dot_r = self._DOT_R
        dot_gap = self._DOT_GAP

        lbl_font_sz = max(7, cs // 3)
        label_font = QFont("Roboto Condensed", lbl_font_sz, QFont.Weight.Bold)
        pill_font_sz = max(6, cs // 3)
        pill_font = QFont("Roboto Mono", pill_font_sz, QFont.Weight.Bold)

        row_rects: list[QRectF] = []
        y_cursor = margin

        for arm_idx, joints in enumerate(arms):
            n = max(len(joints), 1)
            heatmap_w = n * (cs + gap) - gap
            expanded = self._selected_arm == arm_idx

            # Row content width: label + heatmap + dot/pill
            pill_x_offset = label_w + heatmap_w + dot_gap
            if expanded:
                # Pre-measure pill width with a fixed-width template
                p.setFont(pill_font)
                pill_template = " -99.9  -99.9  -99.9"
                pill_tw = p.fontMetrics().horizontalAdvance(pill_template)
                pill_total = pill_tw + 12
                content_w = pill_x_offset + pill_total
            else:
                content_w = pill_x_offset + dot_r * 2
            row_w = content_w + pad * 2

            # Compute expanded section height
            expand_h = 0
            if expanded:
                expand_h = 14  # J-column headers only

            row_h = pad + cs + pad + expand_h

            # ---- row shadow (elevation) ----
            row_rect = QRectF(margin, y_cursor, row_w, row_h)
            row_rects.append(row_rect)
            shadow_rect = row_rect.adjusted(2, 2, 2, 2)
            shadow_path = QPainterPath()
            shadow_path.addRoundedRect(shadow_rect, 8, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(pal["hud_shadow"]))
            p.drawPath(shadow_path)

            # ---- row background ----
            bg_path = QPainterPath()
            bg_path.addRoundedRect(row_rect, 8, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(pal["hud_bg"]))
            p.drawPath(bg_path)

            # ---- arm label (left side, vertically centered on cells) ----
            x_inner = margin + pad
            y_cells = y_cursor + pad
            p.setFont(label_font)
            p.setPen(QPen(pal["hud_label"]))
            lbl = f"A{arm_idx + 1}"
            fm = p.fontMetrics()
            p.drawText(
                x_inner,
                int(y_cells + cs / 2 + fm.ascent() / 2 - 1),
                lbl,
            )

            # ---- heatmap cells ----
            hx = x_inner + label_w
            self._draw_heatmap_row(p, joints, hx, int(y_cells), is_dark, expanded, cs)

            # ---- connection pill (right of heatmap, vertically centered) ----
            # Collapsed: small colored dot. Expanded: pill with tip coords.
            pill_col = _COLOR_RTI_GREEN if self._connected else QColor("#63666A")
            pill_x = hx + heatmap_w + dot_gap

            if expanded:
                # Fixed-width coordinate string: each axis 6 chars → stable width
                tip = getattr(self._robot_state, "tool_tip_position", None)
                if tip is not None:
                    tx = getattr(tip, "x", 0)
                    ty = getattr(tip, "y", 0)
                    tz = getattr(tip, "z", 0)
                    tip_str = f"{tx:6.1f} {ty:6.1f} {tz:6.1f}"
                else:
                    tip_str = "   N/A    N/A    N/A"
                p.setFont(pill_font)
                pfm = p.fontMetrics()
                pill_tw = pfm.horizontalAdvance(tip_str)
                pill_h = cs  # same height as heatmap cells
                pill_w = pill_tw + 12  # 6px padding each side
                pill_rect = QRectF(pill_x, y_cells, pill_w, pill_h)
                pill_path = QPainterPath()
                pill_path.addRoundedRect(pill_rect, pill_h / 2, pill_h / 2)
                # Fill with status color (dimmed)
                fill = QColor(pill_col)
                fill.setAlpha(50)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(fill))
                p.drawPath(pill_path)
                # Text
                txt_c = pal["hud_value"]
                p.setPen(QPen(txt_c))
                p.drawText(
                    pill_rect,
                    Qt.AlignmentFlag.AlignCenter,
                    tip_str,
                )
                # Widen the row background to encompass the pill
                row_w = max(row_w, pill_x + pill_w + pad - margin)
            else:
                # Small dot
                dot_cx = pill_x + dot_r
                dot_cy = int(y_cells + cs / 2)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(pill_col))
                p.drawEllipse(dot_cx - dot_r, dot_cy - dot_r, dot_r * 2, dot_r * 2)

            # ---- expanded section (below cells): J-headers only ----
            if expanded:
                ey = int(y_cells + cs + 4)

                # Column headers (J1 … Jn)
                jhdr_sz = max(6, cs // 3)
                p.setFont(QFont("Roboto Condensed", jhdr_sz))
                p.setPen(QPen(pal["hud_label"]))
                for ji in range(len(joints)):
                    jx = hx + ji * (cs + gap)
                    jlbl = f"J{ji + 1}"
                    jlw = p.fontMetrics().horizontalAdvance(jlbl)
                    p.drawText(jx + (cs - jlw) // 2, ey + 10, jlbl)

            y_cursor += row_h + 4  # gap between arm rows

        self._arm_row_rects = row_rects

    def _draw_mode_label(self, p: QPainter, w: int, h: int) -> None:
        """Draw the operational mode label as a pill badge."""
        mode = self.operational_mode
        color_map = {
            "OPERATIONAL": _COLOR_RTI_GREEN,
            "PAUSED": _COLOR_RTI_ORANGE,
            "EMERGENCY_STOP": QColor("#D32F2F"),
            "IDLE": _COLOR_RTI_LIGHT_GRAY,
            "UNKNOWN": _COLOR_RTI_GRAY,
        }
        color = color_map.get(mode, _COLOR_RTI_GRAY)

        font = QFont("Roboto Condensed", 11, QFont.Weight.Bold)
        p.setFont(font)
        metrics = p.fontMetrics()
        text_w = metrics.horizontalAdvance(mode) + 24
        text_h = metrics.height() + 12
        margin = 12

        # Pill background
        pill_x = w - text_w - margin
        pill_y = h - text_h - margin
        pill_rect = QRectF(pill_x, pill_y, text_w, text_h)
        pill_path = QPainterPath()
        pill_path.addRoundedRect(pill_rect, text_h / 2, text_h / 2)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 40)))
        p.drawPath(pill_path)

        # Text
        p.setPen(QPen(color))
        p.drawText(
            QRect(int(pill_x), int(pill_y), int(text_w), int(text_h)),
            Qt.AlignmentFlag.AlignCenter,
            mode,
        )
