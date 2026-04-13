# UI Design System

Design language and visual conventions for all Medtech Suite GUI
applications. Every widget, overlay, and custom-painted element must
conform to these rules.

---

## Design Language

**Modern Clinical — Glass + Flat Hybrid.**

Influences: Material Design 4 (semantic token architecture, elevation
layers), Apple HIG 2024 (dark-mode depth, focus rings, color
temperature), Vercel/Geist design system (token-first approach, modern
simplicity), Figma component architecture (variable fonts, glassmorphism
surfaces), contemporary Dribbble/Framer motion trends (soft UI accents,
spring animations). Adapted for a medical/industrial context with a
refined RTI brand palette.

The primary departure from the previous Material Design 3 Flat Modern
variant: **floating overlays and HUD panels now use glassmorphism**
(backdrop blur + frosted glass surfaces), while data-bearing elements
remain flat. This creates a clear visual hierarchy between ambient
chrome and actionable content.

---

## Core Principles

| # | Principle | Rule |
|---|-----------|------|
| 1 | **Flat fills on data elements, glass on chrome** | Interactive and data-bearing elements use solid flat color fills. Floating overlays, HUD panels, and navigation surfaces use glassmorphism (backdrop blur + translucent fill). Gradients are permitted *only* for ambient backgrounds. |
| 2 | **Variable rounded corners** | Large floating panels: 16 px radius. Data cards and modals: 8 px radius. Small elements (cells, badges): 4 px radius. Status chips and pills: 12 px radius. Pill-shaped elements: radius = height / 2. |
| 3 | **Layered elevation** | Three semantic elevation tiers: `shadow-sm` (subtle cards), `shadow-md` (data cards), `shadow-lg` (floating panels). Glassmorphism panels add a 1 px translucent border (`rgba(255,255,255,0.12)` dark / `rgba(0,0,0,0.06)` light) for edge definition. No opaque 1 px strokes on panel edges. |
| 4 | **Color as information** | Color encodes meaning (heatmap, status). Decorative color is minimized. Use the perceptually uniform heatmap ramp for continuous data and the semantic palette for discrete states. |
| 5 | **Generous whitespace** | Minimum 12 px internal padding on panels. Minimum 8 px gap between grouped elements. |
| 6 | **Touch-friendly targets** | Minimum 44 × 44 px tap targets per Apple/Google HIG. Interactive elements that are too small on touch screens must provide a larger hit-test area. |
| 7 | **Progressive disclosure** | Default state shows minimal information. Detail is revealed on tap/click (expand-in-place pattern). No hover-dependent interactions (touch compatibility). |
| 8 | **Consistent design tokens** | All visual values (colors, spacing, radii, shadows, opacities, transitions) are defined in the centralized design token system. No hardcoded values in component code. |
| 9 | **Accessible by default** | WCAG AAA contrast ratios for clinical text. Visible focus rings for keyboard navigation. `prefers-reduced-motion` support. Color-blind-friendly palette option. |
| 10 | **Purposeful motion** | Transitions convey state change, not decoration. All animations respect `prefers-reduced-motion`. Critical clinical elements (E-STOP, alarms) use attention-drawing pulse animations. |

---

## Color Palette

### Brand Colors (refined from RTI)

Brand colors are slightly desaturated from the original RTI palette for
reduced eye fatigue in prolonged clinical monitoring, while remaining
clearly recognizable as RTI brand tones.

| Token | Hex | Usage |
|-------|-----|-------|
| `rti-blue` | `#004A8A` | Primary brand, base elements (desaturated from #004C97) |
| `rti-orange` | `#E68A00` | Accent, positive heatmap extreme (warmer from #ED8B00) |
| `rti-gray` | `#63666A` | Neutral text, disabled states |
| `rti-light-blue` | `#00B5E2` | Interactive highlights, selection glow |
| `rti-green` | `#059669` | Healthy/connected/positive status (modern teal-green) |
| `rti-light-gray` | `#BBBCBC` | Secondary labels |

### Neutral Scale

A 5-level neutral ramp provides fine-grained hierarchy for text,
dividers, and backgrounds. Both the light and dark themes select
from this scale.

| Token | Hex | Usage |
|-------|-----|-------|
| `neutral-950` | `#0F1419` | Darkest text, highest emphasis |
| `neutral-800` | `#1E293B` | High-emphasis dark surfaces |
| `neutral-700` | `#374151` | Primary body text (light theme) |
| `neutral-500` | `#6B7280` | Secondary labels, muted icons |
| `neutral-300` | `#D1D5DB` | Dividers, borders |
| `neutral-100` | `#F1F5F9` | Subtle card backgrounds |
| `neutral-50` | `#F9FAFB` | Page background (light theme) |

### Semantic Colors

| Token | Hex | Usage |
|-------|-----|-------|
| `success` | `#059669` | Operational, healthy, connected (= rti-green) |
| `warning` | `#D97706` | Warning, caution, pending |
| `critical` | `#DC2626` | Errors, E-STOP, alarms, interlock |
| `info` | `#0284C7` | Informational, nominal, links |
| `error-red` | `#DC2626` | Alias for `critical` — backward compatibility |
| `heatmap-cold` | `#1565C0` | Negative heatmap extreme |
| `heatmap-zero-dark` | `#263238` | Near-zero value (dark theme) |
| `heatmap-zero-light` | `#78909C` | Near-zero value (light theme) |
| `heatmap-hot` | `#E68A00` | Positive heatmap extreme (= rti-orange) |

### Clinical Severity Mapping

| Severity | Color Token | Hex |
|----------|-------------|-----|
| Normal / Operational | `success` | `#059669` |
| Warning / Caution | `warning` | `#D97706` |
| Critical / E-STOP / Alarm | `critical` | `#DC2626` |
| Info / Nominal | `info` | `#0284C7` |
| Disconnected / Unknown | `neutral-500` | `#6B7280` |

### Theme Palettes

Each theme (dark / light) defines these tokens:

| Token | Dark | Light |
|-------|------|-------|
| `bg-top` | `#0D1B2A` | `#F1F5F9` |
| `bg-bottom` | `#1B2838` | `#F9FAFB` |
| `surface` | `#1E293B` | `#FFFFFF` |
| `grid` | `rgba(255,255,255,0.05)` | `rgba(0,0,0,0.05)` |
| `arm` | `rgba(200,210,220,0.78)` | `rgba(80,90,100,0.78)` |
| `hud-bg` | `rgba(13,27,42,0.65)` | `rgba(255,255,255,0.65)` |
| `hud-border` | `rgba(255,255,255,0.12)` | `rgba(0,0,0,0.06)` |
| `hud-label` | `#BBBCBC` | `#6B7280` |
| `hud-value` | `#00B5E2` | `#004A8A` |
| `glass-blur` | `12px` | `10px` |

---

## Typography

### Font Stack

| Role | Font Family | Fallback | Notes |
|------|-------------|----------|-------|
| Headlines, panel titles, navigation | **Inter** | sans-serif | Variable font (weight 400–700); replaces Roboto Condensed for improved hinting and modern appearance |
| Body text, data values, table content | **Inter** | sans-serif | Same variable font across headline and body roles for visual unity |
| Monospace (data values, log output, raw DDS data) | **Roboto Mono** | monospace | Prevents layout jitter when numeric values change |

Fonts are bundled as application resources (`.ttf`/`.woff2` files under
`resources/fonts/`) and loaded at startup via `@font-face` CSS injection.
No system font dependency. No external CDN requests.

### Semantic Type Scale

All text uses semantic size tokens — not arbitrary pixel values.

| Token | Size | Weight | Line Height | Usage |
|-------|------|--------|-------------|-------|
| `heading-1` | 32 px | 700 (bold) | 1.2 | Page titles |
| `heading-2` | 24 px | 700 | 1.3 | Section headers |
| `heading-3` | 18 px | 600 (semibold) | 1.4 | Card titles, panel headers |
| `body-large` | 16 px | 500 (medium) | 1.5 | Primary content, descriptions |
| `body` | 14 px | 400 (regular) | 1.6 | Default body text |
| `body-small` | 12 px | 400 | 1.5 | Secondary labels, timestamps |
| `label` | 12 px | 600 | 1.4 | Form labels, chip text |
| `mono-data` | 13 px | 700 | 1.4 | Numeric data values (Roboto Mono) |
| `mono-small` | 11 px | 400 | 1.4 | HUD small labels (Roboto Mono) |

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

### Floating HUD Panels (Glassmorphism)

- Translucent background (`hud-bg` at 65% opacity) with backdrop blur
  (`backdrop-filter: blur(12px)` dark / `blur(10px)` light).
- 16 px rounded corners (elevated panel radius).
- 1 px translucent border (`hud-border`) for edge definition against
  the blurred background. No opaque strokes.
- Layered shadow: `shadow-lg` tier (`0 8px 24px rgba(0,0,0,0.12)`).
- 12 px internal padding.

### Status Indicators (Modern)

- **Connection**: Pulsing dot (green = live, gray = disconnected) with
  smooth scale animation (`transform: scale(0.92) ↔ scale(1.0)`,
  600 ms cycle).
- **State chips**: 12 px border radius, icon + label, semantic
  background tint at 10% opacity with full-opacity text. Dark and
  light themes use distinct tint/text color pairs.
- **Critical pulse**: E-STOP and alarm indicators use a pulsing
  `box-shadow` ring animation:
  ```css
  @keyframes pulse-critical {
    0%, 100% { box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.6); }
    50% { box-shadow: 0 0 0 10px rgba(220, 38, 38, 0); }
  }
  ```
- **Skeleton loaders**: During initial data fetch and DDS discovery,
  empty cards show a pulse-animated placeholder (neutral-300 → neutral-100
  shimmer, 1.5 s cycle) instead of "waiting for data" text.
- Interlock: flat red overlay + flat red banner (unchanged).
- Mode: pill badge (rounded rect, color fill at 16% + color border).

### Procedure Controller (Card-Based Orchestration UI)

- **Tile grid**: CSS Grid with `repeat(auto-fill, minmax(200px, 1fr))` —
  responsive, wraps automatically. No tables.
- **Host cards / Service cards**: `ui.card()` with Tailwind utility classes
  (`bg-white`, `shadow-md`, `rounded-lg`). Touch target ≥ 48 × 48 px via
  `min-h-12 min-w-12`.
- **Selection**: Single-selection tracking via reactive state variable.
  Selected tile highlighted by conditional Tailwind class binding.
- **Stat cards**: KPI summary row (Hosts Online, Services Running,
  Warnings). Clickable to switch between Host View and Service View.
- **View toggle**: Reactive state variable controls which grid is visible.
- **Floating overlays**: `ui.dialog()` for config dialogs;
  `ui.notify()` for transient RPC feedback.

### DDS Threading Patterns (Python GUI)

- **Data reception**: `async for sample in reader.take_async()` or
  `reader.take_data_async()` — runs as asyncio coroutine on the
  NiceGUI event loop; launched via `background_tasks.create(coroutine)`.
- **Status monitoring**: `StatusCondition` + `WaitSet.wait_async()`.
  **Do not use `dispatch_async()` + `set_handler()`** — the handler
  runs on a DDS internal thread, which is unsafe for NiceGUI UI
  operations. `wait_async()` resumes on the event loop thread.
- **RPC calls**: Use native async `Requester` API —
  `send_request()` (non-blocking write) + `await wait_for_replies_async()`
  \+ `take_replies()`. No `ThreadPoolExecutor` needed.
- **UI consistency sweep**: `ui.timer(0.5, callback)` — periodic rebuild
  of views from in-memory state dicts. Does not re-read from DDS (avoids
  sample-stealing race with `take_data_async`).
- **Host removal on liveliness loss**: Cache `publication_handle →
  host_id` mapping from `SampleInfo`. On `LIVELINESS_CHANGED` with
  `not_alive_count_change > 0`, look up the dead host and remove it
  plus associated services and stale RPC requesters.

---

## Design Token Architecture

All visual values are centralized in `medtech.gui._tokens` (Python) and
injected into CSS via `ui.add_head_html()`. Components reference tokens
by name — never hardcoded hex values, pixel sizes, or timing strings.

```python
DESIGN_TOKENS = {
    "color": {
        "brand": {
            "primary": "#004A8A",
            "accent": "#E68A00",
        },
        "semantic": {
            "success": "#059669",
            "warning": "#D97706",
            "critical": "#DC2626",
            "info": "#0284C7",
        },
        "neutral": {
            "950": "#0F1419",
            "800": "#1E293B",
            "700": "#374151",
            "500": "#6B7280",
            "300": "#D1D5DB",
            "100": "#F1F5F9",
            "50": "#F9FAFB",
        },
    },
    "spacing": {
        "xs": "4px",
        "sm": "8px",
        "md": "12px",
        "lg": "16px",
        "xl": "24px",
        "2xl": "32px",
    },
    "radius": {
        "sm": "4px",
        "md": "8px",
        "lg": "12px",
        "xl": "16px",
        "pill": "9999px",
    },
    "shadow": {
        "sm": "0 1px 3px rgba(0,0,0,0.06)",
        "md": "0 4px 8px rgba(0,0,0,0.08)",
        "lg": "0 8px 24px rgba(0,0,0,0.12)",
    },
    "opacity": {
        "glass_bg": 0.65,
        "shadow": 0.12,
        "selection_glow": 0.18,
        "disabled": 0.40,
        "card_fill": 0.10,
        "card_fill_active": 0.18,
        "tile_fill": 0.16,
    },
    "transition": {
        "fast": "150ms ease-out",
        "default": "200ms cubic-bezier(0.34, 1.56, 0.64, 1)",
        "slow": "300ms ease-out",
    },
    "blur": {
        "glass_dark": "12px",
        "glass_light": "10px",
    },
}
```

The existing `BRAND_COLORS`, `OPACITY`, and `THEME_PALETTE` dicts in
`_colors.py` must be updated to derive from or align with these tokens.
During the transition, both systems may coexist; the token system is the
authoritative source.

---

## Animation & Motion

### Transition Classes

All interactive elements apply CSS transitions via design tokens:

| Context | Transition | Duration |
|---------|-----------|----------|
| Button hover/active | `all` | `fast` (150 ms ease-out) |
| Card hover elevation | `box-shadow, transform` | `default` (200 ms spring) |
| Theme switch | `background-color, color` | `slow` (300 ms ease-out) |
| Page content swap | `opacity` | `fast` (150 ms ease-out) |
| Status chip color change | `background-color, color` | `default` (200 ms) |

### Attention Animations

| Element | Animation | Duration | Trigger |
|---------|-----------|----------|---------|
| Connection dot | Scale pulse (0.92 ↔ 1.0) + opacity (0.55 ↔ 1.0) | 600 ms | Connected state |
| E-STOP indicator | `pulse-critical` box-shadow ring | 1 s loop | EMERGENCY_STOP mode |
| New alert card | Slide-in from top + fade-in | 300 ms | New CRITICAL alert |
| Skeleton loader | Shimmer (neutral-300 → neutral-100) | 1.5 s loop | Data loading state |
| Card hover | `transform: scale(1.02)` + shadow-lg | 200 ms | Pointer hover |

### Reduced Motion Support

All animations must be wrapped in a `prefers-reduced-motion` media query:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

This CSS is injected globally by `init_theme()`.

---

## Accessibility

### Contrast Requirements

- **Clinical text** (vitals values, alert messages, procedure status):
  WCAG AAA (7:1 contrast ratio minimum).
- **Secondary labels** (timestamps, metadata): WCAG AA (4.5:1 minimum).
- **Large text** (heading-1, heading-2): WCAG AA (3:1 minimum).

### Focus Indicators

All interactive elements must show a visible focus ring on keyboard
navigation (`focus-visible`):

```css
:focus-visible {
  outline: 2px solid #0284C7;
  outline-offset: 2px;
  border-radius: inherit;
}
```

This ensures keyboard-only users can navigate the full interface.

### Color-Blind Support

The semantic palette is designed to be distinguishable under the three
most common color vision deficiencies (deuteranopia, protanopia,
tritanopia). Additionally, a **High Contrast** theme option may be
offered via the theme cycle (system → light → dark → HC → system).

Status indicators must **never rely solely on color** — each status
includes an icon and/or text label alongside the color encoding.

---

## Prohibited Patterns

| Pattern | Reason |
|---------|--------|
| Radial or linear gradients on data elements | Violates flat-fill principle |
| 1 px opaque border strokes on floating panels | Use glassmorphism border or elevation shadow instead |
| Hover-only interactions | Not touch-compatible |
| Fixed pixel sizes for scalable elements | Must scale with widget dimensions |
| Decorative drop shadows heavier than 12% opacity | Visual noise |
| Hardcoded hex colors in component code | Must reference design tokens or `BRAND_COLORS` |
| Hardcoded pixel spacing in component code | Must reference spacing tokens |
| Animations without `prefers-reduced-motion` guard | Accessibility violation |
| Color-only status encoding (no icon/label) | Color-blind users cannot distinguish |

---

## NiceGUI Implementation Patterns

Hard-won patterns from building the Procedure Controller UI. All
NiceGUI-based GUI modules must follow these conventions to maintain
visual and behavioral consistency.

### Shared Module Imports

All apps **must** import colors, icons, theme, and widgets from the
shared `medtech.gui` package. No inline hex colors, icon name strings,
or one-off theme setup.

```python
from medtech.gui import (
    BRAND_COLORS,       # color palette tokens
    ICONS,              # icon name mapping
    OPACITY,            # opacity tokens
    init_theme,         # brand palette, fonts, static routes, favicon
    create_header,      # header bar with logo, title, theme toggle, connection dot
    create_status_chip, # colored chip for state labels
    create_empty_state, # centered icon + message for empty views
    create_stat_card,   # KPI card with value, label, icon
)
```

### Tile Grid Layout

Use CSS Grid — not flexbox `flex-wrap` — for uniform tile grids.
This handles equal sizing and reflow automatically.

```python
with ui.element("div").classes("w-full").style(
    "display: grid;"
    " grid-template-columns: repeat(auto-fill, minmax(19rem, 1fr));"
    " gap: 1rem;"
    " align-content: start;"
):
    for item in items:
        _render_tile(item)
```

- Host tiles: `minmax(21rem, 1fr)`.
- Service tiles: `minmax(19rem, 1fr)`.
- Nested/compact tiles: `minmax(16rem, 1fr)`.
- Always include `align-content: start` to pin tiles top-left.

### Tile Selection & Detail Panes

Selected-item expansion renders a **detail card below the tile grid**,
not inline within the tile (which disrupts grid flow) or as a full-row
grid span.

- Tiles remain uniform in size regardless of selection state.
- Selected tile gets a glow ring (`box-shadow` with `selection_glow`
  opacity) and a slightly higher fill alpha (`card_fill_active`).
- Detail pane is a separate `ui.card()` rendered after the grid
  `div`, containing expanded content (nested tiles, status chips,
  metadata).

### Quasar Button Props

| Visual style | Quasar props | Use case |
|--------------|-------------|----------|
| Ghost / secondary | `flat round` | Icon-only action buttons |
| Filled active | `unelevated color=primary` | Active filter pill, primary action |
| Filled tonal (inactive) | `flat` | Inactive filter pill |
| Destructive | `flat round color=negative` | Stop button |
| Primary action | `flat round color=primary` | Start/play button |

**Never use `outline`** — it produces an exaggerated border that
violates Core Principle #3 (elevation via shadow, not borders).

### Touch Target Constant

All interactive icon buttons must enforce the 44 × 44 px minimum
(Core Principle #6). Define a module-level constant and apply it
to every action button:

```python
_ACTION_BTN_STYLE = "min-width: 44px; min-height: 44px;"
```

For toolbar buttons that also need elevation:

```python
_TOOLBAR_BTN_STYLE = (
    f"box-shadow: 0 2px 8px rgba(0,0,0,{OPACITY['shadow']});"
    " min-width: 44px; min-height: 44px;"
)
```

### Snapshot-Based `@ui.refreshable`

Never let `ui.timer()` call `.refresh()` unconditionally — this
causes full DOM rebuilds and visible flicker on every tick.

Instead, snapshot the relevant data on each timer tick, compare to
the previous snapshot, and only call `.refresh()` when the data has
actually changed:

```python
_last_snapshot = None

def _check_and_refresh():
    nonlocal _last_snapshot
    snapshot = _build_snapshot(backend)
    if snapshot != _last_snapshot:
        _last_snapshot = snapshot
        refreshable_section.refresh()

ui.timer(0.5, _check_and_refresh)
```

### Theme Cycling

Theme toggle is a **three-state cycle** (not a binary switch):
system → light → dark → system. Rendered as a single icon button
whose icon reflects the current mode (`contrast` / `light_mode` /
`dark_mode`). Persisted in `app.storage.user[NICEGUI_THEME_MODE_KEY]`.

### Transient Feedback via `ui.notify()`

RPC results, action confirmations, and query results (capabilities,
health) use `ui.notify()` — not persistent result cards or dialogs.

```python
ui.notify(
    f"Capabilities — {host_id}\n{result}",
    type="info",
    position="top",
    close_button="Dismiss",
    timeout=8000,
)
```

Reserve `ui.dialog()` for multi-field input (e.g., service
configuration) and destructive confirmations.

### Static Images in Constrained Containers

Use `ui.html()` with a raw `<img>` tag for images in headers,
toolbars, and other constrained containers. `ui.image()` applies
responsive sizing that can interfere with inline layout. See INC-073.

```python
ui.html(
    f'<img src="/images/{logo.name}" style="height: 2rem; width: auto;" alt="RTI">'
)
```

Always register the static files route in `init_theme()`:

```python
app.add_static_files("/images", _resource_dir() / "images")
```

### Async Event Handlers

Pass `async def` functions directly to `.on()` or `on_click`.
**Never use `asyncio.create_task()`** for NiceGUI event handlers —
it escapes NiceGUI's slot context tracking. See INC-074.

```python
# Correct
async def _on_start(hid=host_id, sid=service_id):
    await backend.start_service(hid, sid)
    refresh_ui()

ui.button(icon=ICONS["play"]).on("click.stop", _on_start)

# WRONG — loses slot context
ui.button(icon=ICONS["play"]).on(
    "click", lambda: asyncio.create_task(backend.start_service(...))
)
```

### Icon Dictionary Convention

The `ICONS` dict in `medtech.gui._icons` is the single source of
truth for icon name mappings. Rules:

- Every Material Icon used in the UI must have an entry in `ICONS`.
- Use semantic keys (`"play"`, `"health"`, `"host"`) not icon names.
- Two concepts may map to the same glyph but must have distinct keys
  (e.g., `"update": "settings"` and `"settings": "tune"`).
- Ruff rule `F601` catches duplicate keys at lint time.

---

## Applicability

These conventions apply to:

- `modules/shared/medtech/gui/_theme.py`
- `modules/shared/medtech/gui/_widgets.py`
- `modules/shared/medtech/gui/_colors.py`
- `modules/shared/medtech/gui/_icons.py`
- `modules/shared/medtech/gui/_backend.py`
- `modules/hospital-dashboard/procedure_controller/controller.py`
- `modules/hospital-dashboard/dashboard/dashboard.py`
- `modules/surgical-procedure/digital_twin/_robot_widget.py`
- All future NiceGUI GUI modules
