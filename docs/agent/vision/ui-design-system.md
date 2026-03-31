# UI Design System

Design language and visual conventions for all Medtech Suite GUI
applications. Every widget, overlay, and custom-painted element must
conform to these rules.

---

## Design Language

**Material Design 3 (Material You) — Flat Modern variant.**

Influences: Google Material 3, Apple HIG touch-target guidelines,
Fluent Design elevation model. Adapted for a medical/industrial
context with the RTI brand palette.

---

## Core Principles

| # | Principle | Rule |
|---|-----------|------|
| 1 | **Flat fills, no gradients on data elements** | Interactive and data-bearing elements use solid flat color fills. Gradients are permitted *only* for ambient backgrounds (e.g., the full-widget top→bottom background gradient). |
| 2 | **Rounded corners everywhere** | Panels and cards: 8 px radius. Small elements (cells, badges, pills): 4 px radius. Pill-shaped elements: radius = height / 2. |
| 3 | **Elevation via shadow, not borders** | Floating panels (HUD, overlays) use a soft shadow (larger semi-transparent rect behind) instead of border lines. No 1 px strokes on panel edges. |
| 4 | **Color as information** | Color encodes meaning (heatmap, status). Decorative color is minimized. Use the diverging heatmap ramp for continuous data and the semantic palette for discrete states. |
| 5 | **Generous whitespace** | Minimum 12 px internal padding on panels. Minimum 8 px gap between grouped elements. |
| 6 | **Touch-friendly targets** | Minimum 44 × 44 px tap targets per Apple/Google HIG. Interactive elements that are too small on touch screens must provide a larger hit-test area. |
| 7 | **Progressive disclosure** | Default state shows minimal information. Detail is revealed on tap/click (expand-in-place pattern). No hover-dependent interactions (touch compatibility). |
| 8 | **Consistent opacity tokens** | Background overlays: 85% opacity. Shadows: 15% opacity. Selection glow: 18% opacity. Disabled elements: 40% opacity. |

---

## Color Palette

### Brand Colors (from RTI)

| Token | Hex | Usage |
|-------|-----|-------|
| `rti-blue` | `#004C97` | Primary brand, base elements |
| `rti-orange` | `#ED8B00` | Accent, positive heatmap extreme |
| `rti-gray` | `#63666A` | Neutral text, disabled states |
| `rti-light-blue` | `#00B5E2` | Interactive highlights, selection glow |
| `rti-green` | `#A4D65E` | Healthy/connected/positive status |
| `rti-light-gray` | `#BBBCBC` | Secondary labels |

### Semantic Colors

| Token | Hex | Usage |
|-------|-----|-------|
| `error-red` | `#D32F2F` | Errors, interlock, disconnected |
| `heatmap-cold` | `#1565C0` | Negative heatmap extreme |
| `heatmap-zero-dark` | `#263238` | Near-zero value (dark theme) |
| `heatmap-zero-light` | `#78909C` | Near-zero value (light theme) |
| `heatmap-hot` | `#ED8B00` | Positive heatmap extreme (= rti-orange) |

### Theme Palettes

Each theme (dark / light) defines these tokens:

| Token | Dark | Light |
|-------|------|-------|
| `bg-top` | `#0D1B2A` | `#E8EDF2` |
| `bg-bottom` | `#1B2838` | `#F7F8FA` |
| `grid` | `rgba(255,255,255,0.05)` | `rgba(0,0,0,0.05)` |
| `arm` | `rgba(200,210,220,0.78)` | `rgba(80,90,100,0.78)` |
| `hud-bg` | `rgba(13,27,42,0.85)` | `rgba(255,255,255,0.85)` |
| `hud-label` | `#BBBCBC` | `#63666A` |
| `hud-value` | `#00B5E2` | `#004C97` |

---

## Typography

| Role | Font | Weight | Size |
|------|------|--------|------|
| Headlines / labels | Roboto Condensed | Bold | 9–16 pt (context-dependent) |
| Body / values | Roboto Mono | Bold | 7–11 pt (scales with widget) |
| HUD small labels | Roboto Condensed | Regular | 7–9 pt |

All monospace data values use `Roboto Mono` to prevent layout jitter
when numeric values change.

---

## Component Patterns

### Heatmap Strip

- Row of square cells, one per joint, with 3 px gap.
- Cell size scales with widget width (18–38 px).
- Color: diverging `heatmap-cold` → `heatmap-zero` → `heatmap-hot`.
- Values hidden by default; shown inside cells when row is expanded.
- Text color auto-selects white or dark based on cell luminance.

### Robot Arm (2D Digital Twin)

- **Capsule segments**: Flat rounded-cap lines, width ~32% of segment
  radius. Each capsule colored by its joint's heatmap value.
- **Joint knuckles**: Small flat circles (~65% of capsule width) at
  each articulation point. Slightly lighter (dark theme) or darker
  (light theme) than the capsule color.
- **Base**: Flat `rti-blue` circle, no gradient.
- **Tool tip**: Flat `rti-green` circle with soft shadow ring.
- **Selection glow**: Semi-transparent `rti-light-blue` stroke
  following the arm path (same geometry, wider pen).

### Floating HUD Panels

- Semi-transparent background (`hud-bg` at 85% opacity).
- 8 px rounded corners.
- Elevation shadow instead of border (offset blurred rect at 15%
  opacity).
- 12 px internal padding.

### Status Indicators

- Connection: colored dot (green = live, gray = disconnected).
- Expanded: colored pill badge with fixed-width monospace coordinates.
- Interlock: flat red overlay + flat red banner.
- Disconnected: flat muted overlay + centered label.
- Mode: pill badge (rounded rect, color fill at 16% + color border).

### Procedure Controller (Card-Based Orchestration UI)

- **Tile grid**: Fixed-size tappable tiles (200 × 160 px) in a
  FlowLayout that wraps to the next row. No tables.
- **Host cards / Service cards**: QSS-styled `QFrame` with `hostCard`
  or `serviceCard` object name. Touch target ≥ 48 × 48 px.
- **Selection**: Single-selection tracking. Selected tile highlighted
  via QSS dynamic property `selected`. Floating action overlay appears
  at bottom center with context-appropriate buttons.
- **Stat cards**: KPI summary row (Hosts Online, Services Running,
  Warnings). Tappable to switch between Host View and Service View.
- **View toggle**: Stacked widget with two views. Active toggle button
  uses `viewToggleActive` object name; inactive uses `viewToggle`.
- **Floating overlays**: Action overlay (bottom-center) and result card
  (centered) use QSS `actionOverlay` / `resultCard` object names.
  Repositioned on window resize.

### DDS Threading Patterns (Python GUI)

- **Data reception**: `async for sample in reader.take_async()` or
  `reader.take_data_async()` — runs as asyncio coroutine on the
  QtAsyncio event loop thread.
- **Status monitoring**: `StatusCondition` + `WaitSet.wait_async()`.
  **Do not use `dispatch_async()` + `set_handler()`** — the handler
  runs on a DDS internal thread, which is unsafe for Qt widget
  operations. `wait_async()` resumes on the event loop thread.
- **RPC calls**: Use native async `Requester` API —
  `send_request()` (non-blocking write) + `await wait_for_replies_async()`
  \+ `take_replies()`. No `ThreadPoolExecutor` needed.
- **UI consistency sweep**: Periodic asyncio task (~2 Hz) rebuilding
  views from in-memory state dicts. Does not re-read from DDS (avoids
  sample-stealing race with `take_data_async`).
- **Host removal on liveliness loss**: Cache `publication_handle →
  host_id` mapping from `SampleInfo`. On `LIVELINESS_CHANGED` with
  `not_alive_count_change > 0`, look up the dead host and remove it
  plus associated services and stale RPC requesters.

---

## Prohibited Patterns

| Pattern | Reason |
|---------|--------|
| Radial or linear gradients on data elements | Violates flat-fill principle |
| 1 px border strokes on floating panels | Use elevation shadow instead |
| Hover-only interactions | Not touch-compatible |
| Fixed pixel sizes for scalable elements | Must scale with widget dimensions |
| Decorative drop shadows heavier than 15% opacity | Visual noise |

---

## Applicability

These conventions apply to:

- `modules/surgical-procedure/digital_twin/_robot_widget.py`
- `modules/hospital-dashboard/procedure_controller/procedure_controller.py`
- `modules/shared/medtech_gui/_theme.py`
- `modules/shared/medtech_gui/_widgets.py`
- `resources/styles/medtech.qss`
- `resources/styles/medtech-dark.qss`
- All future GUI modules
