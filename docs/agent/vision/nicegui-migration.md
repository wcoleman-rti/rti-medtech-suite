# NiceGUI Migration — Vision & Technical Architecture

> **Status: COMPLETE.** The PySide6 → NiceGUI migration is fully
> implemented. All GUI applications (Hospital Dashboard, Procedure
> Controller, Digital Twin) run on NiceGUI. PySide6 and pytest-qt
> have been removed from the project. This document is retained as
> the **authoritative architectural reference** for the NiceGUI
> integration patterns, `GuiBackend` ABC contract, DDS event loop
> model, and multi-page architecture. It is no longer a migration
> plan — it is a living architectural specification.
>
> For the evolving visual design language (colors, typography,
> animations, glassmorphism), see
> [ui-design-system.md](ui-design-system.md).

## Rationale

Replace PySide6 (Qt 6 desktop bindings) with [NiceGUI](https://nicegui.io/) as
the GUI framework for all Python-based UI applications. NiceGUI is a
Python-first web UI framework built on FastAPI + Vue/Quasar that renders in
the browser. This migration delivers:

| Benefit | Detail |
|---------|--------|
| **No native Qt dependencies** | Eliminates libgl1, libglib2.0, libxkbcommon0, libegl1, libdbus, libfontconfig from Docker images and developer machines |
| **Native async/await** | NiceGUI runs on a standard asyncio event loop — identical to `rti.asyncio`. No QtAsyncio shim needed |
| **Browser-based rendering** | GUI applications become web apps accessible from any device on the network — no X11 forwarding, no `QT_QPA_PLATFORM=offscreen` |
| **Multi-client by default** | Multiple users can monitor the same dashboard simultaneously via separate browser tabs/devices |
| **Rich data visualization** | Built-in ECharts, Plotly, Matplotlib, AG Grid, 3D scene (three.js), and Leaflet map elements |
| **Declarative layout** | Quasar component library with Tailwind CSS styling — replaces QSS stylesheets |
| **Integrated testing** | `User` fixture (fast, in-process) and `Screen` fixture (headless browser) — replaces `pytest-qt` |
| **App lifecycle hooks** | `app.on_startup`, `app.on_shutdown`, `app.on_connect`, `app.on_disconnect` for clean DDS participant management |
| **Native dark mode** | `ui.dark_mode()` and per-page `dark=True` — replaces `ThemeManager` + dual QSS |
| **Real-time updates** | `ui.timer()`, `@ui.refreshable`, property binding, and WebSocket push — replaces `QTimer` + signal/slot |
| **3D digital twin** | `ui.scene()` (three.js) enables interactive 3D robot visualization — upgrades the current QPainter 2D renderer |

---

## Technology Stack Update

### Replaced

| Component | Current | Action |
|-----------|---------|--------|
| PySide6 6.7.* | Qt 6 desktop bindings | **Remove** |
| pytest-qt 4.4.* | Qt widget testing | **Remove** |
| QtAsyncio | Qt ↔ asyncio bridge | **Remove** (NiceGUI uses native asyncio) |
| QSS stylesheets | `medtech.qss`, `medtech-dark.qss` | **Remove** — replaced by Tailwind + Quasar theming |

### Added

| Component | Version | Purpose |
|-----------|---------|---------|
| nicegui | latest stable | Web-based UI framework |
| nicegui[highcharts] | (optional) | Highcharts integration for advanced charting |

### Unchanged

| Component | Version |
|-----------|---------|
| rti.connext | 7.6.0 |
| Python | 3.10+ |
| pytest / pytest-asyncio | existing versions |

---

## Architecture Changes

### Event Loop Unification

**Before (PySide6):**
```
Qt Event Loop (main thread)
  └── QtAsyncio shim
       └── asyncio coroutines
            └── rti.asyncio DDS reads
```

**After (NiceGUI):**
```
asyncio Event Loop (uvicorn / main thread)
  ├── NiceGUI UI updates (WebSocket push)
  ├── rti.asyncio DDS reads (native async for)
  ├── ui.timer() periodic tasks
  └── background_tasks for CPU/IO bound work
```

The removal of the QtAsyncio bridging layer eliminates a class of
threading hazards. DDS async reads (`async for sample in reader.take_async()`)
run directly on the same asyncio event loop as the UI — no cross-thread
signaling required.

### Application Model

Each GUI application becomes a NiceGUI web app served via uvicorn:

| Aspect | PySide6 (current) | NiceGUI (target) |
|--------|-------------------|-------------------|
| Entry point | `QApplication` + `sys.exit(app.exec())` | `ui.run()` (starts uvicorn) |
| Main window | `QMainWindow` subclass | `@ui.page('/')` decorator function |
| Widget tree | `QWidget` parent/child hierarchy | Declarative `with` blocks (`ui.card`, `ui.row`, `ui.column`) |
| State updates | Qt signals/slots, `QTimer` | `ui.timer()`, `@ui.refreshable`, `binding.bind_from()` |
| Theming | QSS + `ThemeManager` singleton | `ui.dark_mode()`, `ui.colors()`, Tailwind CSS classes |
| Custom painting | `QPainter` on `QWidget.paintEvent` | `ui.scene()` (3D), `ui.echart()`, `ui.plotly()`, or custom Vue component |
| Packaging | Desktop executable | Web server (Docker container) or `nicegui-pack` for native window |
| Multi-user | One user per process | Multi-client via browser sessions |

### DDS Integration Pattern

GUI applications follow the same **service-oriented architecture** and
**DDS Consistency Contract** ([dds-consistency.md](dds-consistency.md)) as all
other Python modules:

1. Participants are **created from XML** via `create_participant_from_config()` —
   never constructed with bare domain IDs.
2. DataReaders/DataWriters are **looked up by entity name** from `app_names.idl`
   constants after participant creation, with safe exception handling on lookup
   failure.
3. `initialize_connext()` (from `medtech.dds`) is called before any participant
   is created.

The key difference from non-GUI services is that NiceGUI provides
`app.on_startup` / `app.on_shutdown` lifecycle hooks for DDS resource
management. Following NiceGUI best practices
([Action & Events](https://nicegui.io/documentation/section_action_events),
[examples](https://github.com/zauberzeug/nicegui/tree/main/examples)),
these hooks should delegate to proper class methods — not inline lambdas —
to keep startup/shutdown logic testable and maintainable.

#### `GuiBackend` ABC — Shared Base for GUI-DDS Integration

**Why not inherit from `Service`?** The `medtech.service.Service` ABC is
designed for ServiceHost-managed orchestration — services that are started,
stopped, and polled via RPC. GUI backends have a different lifecycle: they
are created in `app.on_startup` and torn down in `app.on_shutdown`, managed
by NiceGUI, not by the orchestration layer. No `run()` gather, no `state`
polling, no RPC control.

**Why a separate ABC?** GUI backends still need the same structural
consistency that `Service` provides for orchestrated services. Without a
shared interface, each of the three GUI modules could diverge in lifecycle
method naming, shutdown cleanup, and logging conventions. A `GuiBackend`
ABC enforces a consistent contract — just as `Service` does — so the
unified app and standalone apps can manage all backends uniformly.

Like `Service`, `GuiBackend` is a **pure skeleton** — all abstract, no
domain logic. It does not own a participant, create DDS resources, or
provide helper methods. Each concrete backend is free to create as many
participants as it needs (e.g., the Procedure Controller may need both
Hospital and Orchestration domain participants).

Unlike `Service`, `GuiBackend` provides **minimal NiceGUI lifecycle wiring**
in its `__init__`: it registers `app.on_startup(self.start)` and
`app.on_shutdown(self.close)`. This is not domain logic — it is invariant
plumbing that connects the abstract methods to NiceGUI's hook system. Every
concrete backend would otherwise repeat these two lines verbatim. The
pattern follows the NiceGUI `global_worker` example, where the class
self-registers its lifecycle hooks during construction.

This means concrete backends are instantiated at module level (or in an
earlier startup hook). DDS initialization (`initialize_connext()`,
`create_participant_from_config()`) is synchronous and runs during
construction. The `start()` method — which launches `background_tasks` —
runs later when the event loop is active, triggered by NiceGUI's startup
hook automatically.

> **Deployment-level participant model:** Under the A2 hybrid architecture,
> GUI backends join only the domain(s) at their deployment level:
>
> - **Hospital Dashboard** (`medtech-gui` on `hospital-net`) — one participant
>   on Domain 20 (Hospital integration). Receives all data via per-room RS bridge.
> - **Procedure Controller** (`medtech-controller` on `orchestration-net`) — one
>   participant on Domain 11 (Orchestration, room-scoped). Room-level deployment.
> - **Digital Twin** (`medtech-twin` on `surgical-net`) — one participant on
>   Domain 10 (`control` tag). Room-level deployment.
>
> No GUI backend spans deployment levels. The dashboard does NOT join
> orchestration or procedure domains — it discovers rooms and services via
> `ServiceCatalog` data bridged from Domain 11 → Domain 20 by the per-room
> Routing Service.

| Aspect | `Service` (orchestration) | `GuiBackend` (NiceGUI) |
|--------|---------------------------|------------------------|
| Lifecycle owner | `ServiceHost` via RPC | NiceGUI `app.on_startup` / `app.on_shutdown` |
| Abstract methods | `run()`, `stop()`, `name`, `state` | `start()`, `close()`, `name` |
| Concrete logic | — | `__init__` registers `on_startup` / `on_shutdown` hooks |
| DDS init | Each service handles its own | Each backend handles its own |
| State reporting | `ServiceState` enum polled by Host | None — UI pages read state attributes directly |

Lives in `medtech.gui` alongside the existing widget and theme code.

```python
"""medtech.gui.backend — Abstract base for NiceGUI DDS backends.

Mirrors medtech.service.Service for orchestrated services but with a
NiceGUI-managed lifecycle.  Pure skeleton with minimal NiceGUI plumbing:
__init__ registers app.on_startup / app.on_shutdown hooks that delegate
to the abstract start() and close() methods.

Each concrete backend handles its own participant creation, entity
lookup, and DDS resource management.

Pattern reference:
  - NiceGUI global_worker example (self-registering lifecycle hooks)
  - NiceGUI modularization/class_example (class-based page registration)
  - medtech.service.Service (orchestration-side equivalent)
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from nicegui import app


class GuiBackend(ABC):
    """Abstract base for all NiceGUI DDS backend classes.

    Construction triggers DDS initialization (synchronous) and
    registers NiceGUI lifecycle hooks.  The start() method runs
    when the event loop is active; close() runs on shutdown.

    Concrete subclasses create their own participants, readers,
    and background loops.
    """

    def __init__(self) -> None:
        """Register NiceGUI lifecycle hooks.

        Subclasses must call ``super().__init__()`` — typically as the
        last line of their ``__init__``, after DDS setup is complete.
        """
        app.on_startup(self.start)
        app.on_shutdown(self.close)

    @abstractmethod
    async def start(self) -> None:
        """Launch background reader tasks.

        Called automatically by NiceGUI on startup (event loop is
        active).  Each concrete backend creates
        ``background_tasks.create()`` calls for its unique reader loops.
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Close all DDS resources (participants, readers, writers).

        Called automatically by NiceGUI on shutdown.  Non-blocking.
        Backends with multiple participants close all of them here.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier for logging."""
        ...
```

#### Canonical Concrete Backend (Hospital Dashboard)

Each GUI module subclasses `GuiBackend` and handles its own DDS setup — same
as `Service` subclasses. The ABC enforces method shape and wires the lifecycle
hooks; the subclass owns all DDS resources. Backends are instantiated at
module level — DDS init is synchronous, and `start()` runs later when the
event loop is active.

```python
"""Hospital Dashboard DDS backend.

Follows:
  - GuiBackend ABC (medtech.gui.backend)
  - dds-consistency.md §1–§3 (init sequence, XML creation, entity lookup)
  - NiceGUI Action & Events best practices
  - NiceGUI global_worker / modularization examples
"""
from __future__ import annotations

import logging

import app_names
import rti.asyncio  # noqa: F401 — enable async DDS
import rti.connextdds as dds
from medtech.dds import initialize_connext
from medtech.gui.backend import GuiBackend
from nicegui import background_tasks, ui

dash_names = app_names.MedtechEntityNames.HospitalDashboard
log = logging.getLogger("medtech.dashboard")


class DashboardBackend(GuiBackend):
    """Hospital Dashboard DDS backend.

    UI pages read from the public state attributes which are
    updated by per-reader background coroutines.
    """

    @property
    def name(self) -> str:
        return "HospitalDashboard"

    def __init__(self) -> None:
        # ---- Shared UI state (read by pages, written by DDS loops) ----
        self.procedures: dict = {}
        self.vitals: dict = {}
        self.alerts: list = []

        # ---- DDS init (dds-consistency.md §1) ----
        initialize_connext()
        provider = dds.QosProvider.default

        # ---- Participant from XML (dds-consistency.md §2) ----
        participant = provider.create_participant_from_config(
            dash_names.HOSPITAL_DASHBOARD
        )
        if participant is None:
            raise RuntimeError("Failed to create DomainParticipant")

        self._participant = participant

        # ---- Partition ----
        qos = self._participant.qos
        qos.partition.name = ["room/*/procedure/*"]
        self._participant.qos = qos

        # ---- Entity lookup (dds-consistency.md §3) ----
        # Validate each lookup inline — same pattern as BedsideMonitor.
        # Each reader is a named attribute because each reader loop has
        # unique processing logic (different types, different state updates).
        procedure_any = self._participant.find_datareader(
            dash_names.PROCEDURE_STATUS_READER
        )
        if procedure_any is None:
            raise RuntimeError(
                f"Reader not found: {dash_names.PROCEDURE_STATUS_READER}"
            )
        self._procedure_status_reader = dds.DataReader(procedure_any)

        vitals_any = self._participant.find_datareader(
            dash_names.PATIENT_VITALS_READER
        )
        if vitals_any is None:
            raise RuntimeError(
                f"Reader not found: {dash_names.PATIENT_VITALS_READER}"
            )
        self._patient_vitals_reader = dds.DataReader(vitals_any)

        alerts_any = self._participant.find_datareader(
            dash_names.CLINICAL_ALERT_READER
        )
        if alerts_any is None:
            raise RuntimeError(
                f"Reader not found: {dash_names.CLINICAL_ALERT_READER}"
            )
        self._clinical_alert_reader = dds.DataReader(alerts_any)

        self._participant.enable()
        log.info("Dashboard backend initialized")

        # ---- Register lifecycle hooks (GuiBackend) ----
        super().__init__()

    # ------------------------------------------------------------------ #
    # Background reader loops — one per topic, each with unique logic     #
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        background_tasks.create(self._read_procedure_status())
        background_tasks.create(self._read_patient_vitals())
        background_tasks.create(self._read_clinical_alerts())

    async def _read_procedure_status(self) -> None:
        async for data in self._procedure_status_reader.take_data_async():
            self.procedures[data.procedure_id] = data

    async def _read_patient_vitals(self) -> None:
        async for data in self._patient_vitals_reader.take_data_async():
            self.vitals[data.patient_id] = data

    async def _read_clinical_alerts(self) -> None:
        async for data in self._clinical_alert_reader.take_data_async():
            self.alerts.append(data)

    # ------------------------------------------------------------------ #
    # Shutdown                                                             #
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        self._participant.close()
        log.info("Dashboard backend closed")


# ---- Module-level instantiation (DDS init is synchronous) ----
# GuiBackend.__init__ registers app.on_startup(start) and
# app.on_shutdown(close) automatically.
backend = DashboardBackend()


@ui.page('/dashboard', dark=True)
def dashboard():
    with ui.header():
        ui.image('/static/rti-logo.png').classes('h-8')
        ui.label('Hospital Dashboard').classes('text-xl font-bold')
        ui.space()
        dark = ui.dark_mode()
        ui.switch('Dark').bind_value(dark, 'value')

    # UI reads from backend.procedures, backend.vitals, etc.
    # via @ui.refreshable sections and ui.timer() periodic sweeps.
    ...
```

#### NiceGUI Action & Events Best Practices

The pattern above follows NiceGUI's documented best practices for long-running
I/O integration:

| NiceGUI Feature | DDS Usage |
|-----------------|-----------|
| **`app.on_startup` / `app.on_shutdown`** | Create and close DDS participants. Use named async functions, not lambdas, so startup/shutdown logic is testable and debuggable. |
| **`background_tasks.create()`** | Launch one `async for data in reader.take_data_async()` loop per reader. Each reader gets its own background task with topic-specific processing logic. NiceGUI cancels background tasks on shutdown automatically. Use `@background_tasks.await_on_shutdown` for graceful DDS cleanup. |
| **`ui.timer(interval, callback)`** | Periodic UI rebuild from DDS state dicts (e.g., 2 Hz sweep). Callback can be sync or async. Use `active` parameter to pause when no client is connected. |
| **`@ui.refreshable`** | Declarative UI sections that rebuild when `refresh()` is called after DDS state changes. Preferred over manual element updates for complex layouts. |
| **Async event handlers** | For user-driven DDS I/O (button click → write command, trigger RPC). NiceGUI supports `async def on_click` natively ([docs](https://nicegui.io/documentation/section_action_events#async_event_handlers)). Since `rti.connext` provides async APIs (`write()` is non-blocking, RPC has `send_request_async()` / `wait_for_replies_async()`), use async handlers directly — no thread overhead. |
| **`run.io_bound(fn, ...)`** | Fallback for truly synchronous/blocking DDS calls that lack an async API. Wraps the call in a thread to keep the event loop responsive. Prefer async handlers when an async DDS API exists. |
| **`Event[T]()`** | Distribute DDS-sourced events (e.g., new alert) to multiple UI subscribers across pages. Replaces Qt signals. |
| **`app.on_exception`** | Global handler for DDS-related exceptions in background tasks. Log via `medtech.log` and display `ui.notification(type='negative')`. |
| **`ui.on_exception`** | Per-page handler for DDS read failures after page render. Show error dialog or fallback state. |

> **Reference:** [NiceGUI Action & Events docs](https://nicegui.io/documentation/section_action_events),
> [NiceGUI examples](https://github.com/zauberzeug/nicegui/tree/main/examples)
> (especially `modularization`, `device_control`, `global_worker`, `ros2`,
> `websockets`)

### Multi-Page Architecture

NiceGUI's page routing enables structured navigation within each deployment-level
application. Under the A2 hybrid architecture, the hospital-level and room-level
GUIs are **separate NiceGUI instances** running on different Docker networks —
they are not merged into a single SPA.

#### Hospital Dashboard App (`medtech-gui` on `hospital-net`)

| Route | Module | Notes |
|-------|--------|-------|
| `/` | Landing / redirect to dashboard | |
| `/dashboard` | Hospital Dashboard | Domain 20 — procedure overview, vitals, alerts |
| `/alerts` | Clinical Alerts Dashboard | (new — visual frontend for alerts engine) |

The dashboard app uses `ui.sub_pages()` for SPA-style client-side routing between
its own pages. Room-level GUIs (controller, twin) are discovered via
`ServiceCatalog` data bridged from Domain 11 → Domain 20 by the per-room Routing
Service. They are always opened in **new browser tabs** (cross-origin navigation)
because they run on different hosts/networks.

#### Room-Level Standalone Apps

| App | Container | Network | Route | Domain |
|-----|-----------|---------|-------|--------|
| Procedure Controller | `medtech-controller-<room>` | `orchestration-net` | `/controller` | Domain 11 |
| Digital Twin | `medtech-twin-<room>` | `surgical-net` | `/twin` | Domain 10 (`control` tag) |

Each room-level app is a self-contained NiceGUI instance with its own header
bar, theme, and static assets. The controller and twin run as `@ui.page()`
entry points (not sub-pages of a shell) because they are standalone processes.

This replaces the earlier design where a single unified SPA served all three
GUI modules. The split aligns with the A2 hybrid architecture constraint that
no application spans deployment levels.

#### Critical: Shell-First Routing (Hospital Dashboard App)

The root shell function must be passed **directly to `ui.run()`** — not
registered via `@ui.page("/")`. This ensures the shell handles **all** URL
paths, including sub-page paths on browser refresh or direct link entry:

```python
def shell_page() -> None:
    init_theme(title="Hospital Dashboard")
    with ui.left_drawer(fixed=True):
        # Dashboard navigation + discovered room GUIs
        ...
    ui.sub_pages({
        "/dashboard": dashboard_content,
        "/alerts": alerts_content,
        "/": lambda: ui.navigate.to("/dashboard"),
    })

ui.run(shell_page, storage_secret=..., reload=False)
```

**Dashboard sub-pages must NOT register standalone `@ui.page()` at their
sub-page routes** when running in the hospital app. Standalone `@ui.page()`
handlers conflict with `ui.sub_pages()` routing. Module `*_content()`
functions are the entry points for `ui.sub_pages()`.

#### Split-Deployment Navigation Model

GUI services run in **separate containers** across deployment planes.
The hospital dashboard runs in the hospital container on `hospital-net`;
the Procedure Controller and Digital Twin run in per-room containers
dual-homed on `surgical-net` + `orchestration-net`. Each NiceGUI instance
owns its own WebSocket connection and asyncio event loop — there is no
shared SPA shell across planes.

Navigation follows three patterns:

| Direction | Mechanism | Behavior |
|-----------|-----------|----------|
| **Hospital → Room** (downward) | Room cards on the dashboard with `open_in_new` icon | Opens room GUI in a new browser tab |
| **Room ↔ Room** (horizontal, same level) | `medtech.gui.room_nav` shared module — floating nav pill with sibling buttons | Same-tab navigation via `ui.navigate.to(gui_url)` |
| **Room → Hospital** (upward) | **Not permitted** — close the browser tab | Room GUIs have no upward visibility to hospital-level infrastructure |

**Room-level GUI self-sufficiency:** Each room GUI (controller, twin)
renders a **self-contained page** with:
- Its own header bar (RTI logo, title, theme toggle)
- A floating nav pill (from `medtech.gui.room_nav`) showing sibling
  room GUIs discovered via `ServiceCatalog` on the Orchestration domain
- Full theme and font support (each NiceGUI instance serves its own
  static assets)

The `gui_url` property in `ServiceCatalog` provides the full HTTP
endpoint URL for each GUI service. The hospital dashboard reads bridged
`ServiceCatalog` data (Domain 11 → 20 via per-room RS) and renders
**room cards** in the Room Overview view — one card per discovered room,
each with an `open_in_new` button that opens the room GUI in a new tab.

#### Room-Level Horizontal Navigation (`medtech.gui.room_nav`)

The shared `medtech.gui.room_nav` module provides same-level navigation
between room GUIs. It creates a **read-only Orchestration domain
participant** that subscribes to `ServiceCatalog` filtered by the
current `room_id`, then renders a floating nav pill with buttons for
each discovered sibling GUI service in the same room.

```python
# Conceptual room_nav module (simplified)
def create_room_nav(room_id: str) -> None:
    """Render floating nav pill with sibling GUI buttons."""
    # Read-only Orchestration participant discovers ServiceCatalog
    # entries matching this room_id
    siblings = _discover_siblings(room_id)  # [{name, gui_url}, ...]

    with ui.row().classes("fixed bottom-4 ..."):
        for sib in siblings:
            ui.button(sib["name"], on_click=lambda url=sib["gui_url"]: ui.navigate.to(url))
```

This module is deployment-agnostic — it works identically on Docker,
physical hardware, or mixed environments. Any future room-level GUI
(Foxglove Viewer, camera feed, etc.) automatically appears in the nav
pill when its Service Host advertises a `gui_url` — with zero
configuration changes.

#### Hospital Dashboard Room Discovery

The hospital dashboard discovers rooms via **bridged `ServiceCatalog`**
data (Domain 11 → Domain 20 via per-room RS). The `DashboardBackend`
subscribes to `ServiceCatalog` on Domain 20 and extracts `room_id` and
`gui_url` properties. The Room Overview view renders one card per
discovered room, showing room status, active procedure info, and an
`open_in_new` button to open the room GUI in a new browser tab.

Room GUIs are always cross-origin from the hospital dashboard. There is
no same-origin in-app navigation to room GUIs from the hospital level.

---

## Module Mapping: PySide6 → NiceGUI

### Shared GUI Module (`modules/shared/medtech/gui/`)

| Current Component | NiceGUI Replacement |
|-------------------|-------------------|
| `ThemeManager` / `ThemeMode` | `ui.dark_mode()` + `ui.colors()` with RTI brand palette |
| `init_theme()` (font registration, QSS loading) | `ui.add_head_html()` for Google Fonts / custom CSS, or `app.add_static_files()` for local fonts |
| `ConnectionDot` (animated QWidget) | `ui.icon('circle')` with Tailwind classes + `ui.timer()` for pulse animation, or `ui.badge()` |
| `create_status_chip()` | `ui.chip()` or `ui.badge()` with color props per state |
| `create_stat_card()` | `ui.card()` with `ui.label()` for value/title + Tailwind border-left accent |
| `create_section_header()` | `ui.label().classes('text-lg font-bold')` with optional `ui.icon()` |
| `create_empty_state()` | `ui.label().classes('text-center text-gray-500')` in `ui.column().classes('items-center')` |
| QSS `medtech.qss` / `medtech-dark.qss` | Tailwind utility classes + `ui.colors(primary='#004C97', accent='#ED8B00', ...)` |

### Hospital Dashboard (`modules/hospital-dashboard/dashboard/`)

| Current Component | NiceGUI Replacement |
|-------------------|-------------------|
| `HospitalDashboard(QMainWindow)` | `@ui.page('/dashboard')` function |
| `QSplitter` (procedure list / detail) | `ui.splitter()` |
| `QStackedWidget` (detail views) | `ui.tab_panels()` or conditional `@ui.refreshable` |
| `QScrollArea` (alert feed) | `ui.scroll_area()` or `ui.log()` for append-only feed |
| `VitalsRow(QFrame)` | `ui.card()` with `ui.row()`, colored `ui.badge()` for HR/SpO2/BP |
| `QComboBox` (severity/room filter) | `ui.select()` with `on_change` |
| `QTimer` (2 Hz state sweep) | `ui.timer(0.5, rebuild_ui)` |
| Qt signals for data delivery | `@ui.refreshable` + dict state, or `binding.bind_from()` |

#### New Capabilities Enabled

- **`ui.echart()` / `ui.plotly()`** — live vitals trend charts (sparklines, rolling window)
- **`ui.aggrid()`** — sortable, filterable procedure table with column resize
- **`ui.notification()`** — browser push notifications for CRITICAL alerts
- **`ui.timeline()`** — alert history timeline view
- **`app.storage.tab`** — per-user filter state persistence across page reloads

### Procedure Controller (`modules/hospital-dashboard/procedure_controller/`)

| Current Component | NiceGUI Replacement |
|-------------------|-------------------|
| `ProcedureController(QMainWindow)` | `@ui.page('/controller')` function |
| FlowLayout tile grid (custom) | `ui.grid(columns=4)` or flex `ui.row().classes('flex-wrap')` |
| Host/Service cards (`QFrame`) | `ui.card()` with `on_click` handler |
| `QStackedWidget` (Host View / Service View) | `ui.tabs()` / `ui.tab_panels()` |
| Floating action overlay | `ui.page_sticky()` or `ui.dialog()` |
| Result card overlay | `ui.dialog()` with `ui.card()` |
| Stat cards row | `ui.row()` of `ui.card()` elements with `bind_text_from()` |
| RPC calls on daemon threads | `await run.io_bound(requester.send_request, ...)` |

#### New Capabilities Enabled

- **`ui.stepper()`** — guided procedure start/stop wizard
- **`ui.chip()`** — inline status pills with color transitions
- **Touch/mobile support** — Quasar components are touch-optimized by default

### Digital Twin Display (`modules/surgical-procedure/digital_twin/`)

| Current Component | NiceGUI Replacement |
|-------------------|-------------------|
| `DigitalTwinDisplay(QMainWindow)` | `@ui.page('/twin/{room_id}')` with path parameter |
| `RobotWidget(QWidget)` + `QPainter` | **`ui.scene()`** (three.js 3D scene) — major upgrade |
| Capsule segments, joint knuckles | `scene.cylinder()`, `scene.sphere()` with `.material(color)` |
| Heatmap coloring | `.material(heatmap_color(value))` per joint object |
| Safety interlock overlay | `ui.notification()` (persistent, color='negative') or overlay `ui.label` |
| Mode badge | `ui.badge()` bound to robot mode state |
| Tap-to-select arm | `on_click` handler on scene objects |

#### New Capabilities Enabled

- **3D visualization** — full 3D robot arm with orbit controls, zoom, pan
- **`scene.gltf()`** — load actual robot CAD models (GLTF/GLB format)
- **`scene.stl()`** — import STL meshes for realistic rendering
- **Multi-angle views** — orthographic / perspective camera switching
- **`ui.scene_view()`** — multiple synchronized viewports (top, side, iso)
- **`ui.joystick()`** — on-screen virtual joystick for teleoperation demo

---

## Design System Translation

### Color Palette → Quasar Theme

```python
# In app startup or shared module
from nicegui import app

app.colors(
    primary='#004A8A',    # rti-blue
    secondary='#63666A',  # rti-gray
    accent='#E68A00',     # rti-orange
    positive='#059669',   # rti-green
    negative='#DC2626',   # error-red
    info='#00B5E2',       # rti-light-blue
    warning='#E68A00',    # rti-orange (reused)
)
```

### Typography → Google Fonts / Static

```python
ui.add_head_html('''
<link href="https://fonts.googleapis.com/css2?family=Roboto+Condensed:wght@400;700&family=Roboto+Mono:wght@700&display=swap" rel="stylesheet">
<style>
  body { font-family: 'Roboto Condensed', sans-serif; }
  .mono { font-family: 'Roboto Mono', monospace; font-weight: bold; }
</style>
''')
```

Or use `app.add_static_files('/fonts', 'resources/fonts/')` for offline /
air-gapped deployments (preserving current bundled font strategy).

### Dark / Light Theme

```python
# Per-page
@ui.page('/dashboard', dark=True)

# Dynamic toggle
dark = ui.dark_mode()
ui.switch('Dark Mode').bind_value(dark, 'value')
```

Replaces `ThemeManager`, `ThemeMode` enum, `QSettings` persistence,
`QFontDatabase.addApplicationFont()`, and dual QSS stylesheet loading.

### Persistent User Settings (`app.storage`)

NiceGUI provides [built-in persistent storage](https://nicegui.io/documentation/storage)
that replaces `QSettings` for user preference persistence. Storage tiers:

| Storage | Scope | Persists across restarts | Use case |
|---------|-------|--------------------------|----------|
| `app.storage.user` | Per user (cookie ID), all tabs | Yes | Theme preference (dark/light/system), locale, accessibility settings |
| `app.storage.tab` | Per browser tab | Yes (30 day default) | Filter state (severity, room), selected procedure, scroll position |
| `app.storage.general` | All users | Yes | Shared app configuration, feature flags |
| `app.storage.client` | Per page visit | No (discarded on reload) | Transient UI state, connection objects |

Requires `storage_secret` in `ui.run()` for `user` and `browser` storage
(signs the session cookie). Storage files default to `.nicegui/` in the
working directory; override via `NICEGUI_STORAGE_PATH` env var in Docker.

```python
# Theme preference persisted per user across tabs and restarts
@ui.page('/dashboard')
def dashboard():
    stored_theme = app.storage.user.get('theme', 'dark')
    dark = ui.dark_mode(stored_theme == 'dark')

    def on_theme_change(e):
        app.storage.user['theme'] = 'dark' if e.value else 'light'

    ui.switch('Dark Mode', value=stored_theme == 'dark',
              on_change=on_theme_change)

# Filter state persisted per tab
@ui.page('/dashboard')
async def dashboard():
    await ui.context.client.connected()
    severity = app.storage.tab.get('severity_filter', 'ALL')
    ui.select(['ALL', 'CRITICAL', 'WARNING', 'INFO'],
              value=severity,
              on_change=lambda e: app.storage.tab.update(severity_filter=e.value))

# Entry point
ui.run(storage_secret='...')  # required for app.storage.user
```

Replaces:
- `QSettings` for persistent preference storage
- `ThemeManager` in-memory state + `QSettings` serialization
- Manual cookie management or local storage JavaScript

### Component Pattern Mapping

| Design System Pattern | PySide6 Implementation | NiceGUI Implementation |
|-----------------------|----------------------|----------------------|
| Rounded corners (8px / 4px) | QSS `border-radius` | Tailwind `rounded-lg` / `rounded` |
| Elevation via shadow | QSS `box-shadow` or QPainter | Quasar `shadow-md` or Tailwind `shadow-lg` |
| 44×44 px touch targets | Manual sizing | Quasar default (Material Design compliant) |
| Progressive disclosure | Custom expand/collapse | `ui.expansion()` element |
| Status pills / chips | `create_status_chip()` QFrame | `ui.chip(color=..., text_color=...)` |
| Stat cards | `create_stat_card()` custom QFrame | `ui.card()` with Tailwind `border-l-4 border-[color]` |
| Heatmap strip | QPainter custom row | `ui.echart()` heatmap series or custom `ui.html()` |
| Floating HUD | QPainter semi-transparent rect | `ui.page_sticky()` or `ui.card().classes('bg-opacity-85')` |

### Iconography

**WSL2 rendering fix:** PySide6/Qt icon rendering under WSL2 was unreliable —
missing glyphs, fallback squares, and font registration failures caused by
the lack of a native display server and incomplete fontconfig in the WSL
environment. NiceGUI renders entirely in the browser, so icon fonts load
via standard web mechanisms (CSS `@font-face`) with no platform dependencies.
This eliminates the class of WSL2 icon rendering issues entirely.

**Icon set:** NiceGUI's `ui.icon()` element uses
[Quasar's icon system](https://quasar.dev/vue-components/icon).
All medtech-suite GUI modules **must** use
[Material Symbols](https://fonts.google.com/icons?icon.set=Material+Symbols)
(outlined variant) as the sole icon set. Material Symbols is the successor
to Material Icons — more icons, variable font axes (weight, fill, grade,
optical size), and a consistent design language. No other icon libraries
(Font Awesome, Bootstrap Icons, etc.) are permitted.

```python
# Required quasar_config — set in the unified app entry point
ui.run(
    quasar_config={
        'iconSet': 'material-symbols-outlined',
    },
)

# Usage — always use the sym_o_ prefix
ui.icon('sym_o_monitor_heart').classes('text-3xl text-primary')   # vitals
ui.icon('sym_o_emergency').classes('text-3xl text-negative')      # alerts
ui.icon('sym_o_surgical').classes('text-3xl text-accent')         # procedures
ui.icon('sym_o_precision_manufacturing').classes('text-3xl')      # robot/twin
ui.icon('sym_o_dashboard').classes('text-3xl')                    # dashboard
```

Key icons to define in the shared GUI module (Step N.2) for consistent usage
across all pages:

| Concept | Suggested Icon | Fallback (Material Icons) |
|---------|---------------|--------------------------|
| Vitals / heart rate | `sym_o_monitor_heart` | `favorite` |
| Alert / alarm | `sym_o_emergency` | `warning` |
| Procedure / surgery | `sym_o_surgical` | `local_hospital` |
| Robot / digital twin | `sym_o_precision_manufacturing` | `smart_toy` |
| Dashboard overview | `sym_o_dashboard` | `dashboard` |
| Connection status | `sym_o_wifi` / `sym_o_wifi_off` | `wifi` / `wifi_off` |
| Dark/light mode | `sym_o_dark_mode` / `sym_o_light_mode` | `dark_mode` / `light_mode` |
| Settings | `sym_o_settings` | `settings` |
| Filter | `sym_o_filter_list` | `filter_list` |
| Patient | `sym_o_person` | `person` |

---

## Docker Impact

### Before (PySide6)

```dockerfile
# runtime-python.Dockerfile
RUN apt-get install -y libgl1 libglib2.0-0 libfontconfig1 \
    libxkbcommon0 libdbus-1-3 libegl1
ENV QT_QPA_PLATFORM=offscreen
```

### After (NiceGUI)

```dockerfile
# runtime-python.Dockerfile
# No Qt platform dependencies needed
# NiceGUI serves via HTTP — no display server required
ENV NICEGUI_STORAGE_PATH=/data/nicegui
EXPOSE 8080
```

The Docker image shrinks significantly. GUI applications are accessible via
`http://<container-ip>:8080` from any browser on the network.

---

## Testing Strategy

### Replace pytest-qt with NiceGUI Testing

| Current (pytest-qt) | Target (NiceGUI) |
|---------------------|-------------------|
| `qtbot.addWidget(widget)` | `User` fixture (simulated) or `Screen` fixture (browser) |
| `QApplication` sandbox | NiceGUI test client (in-process) |
| `qtbot.waitSignal()` | `await user.should_see()` or timer-based assertions |
| Widget hierarchy assertions | `user.find(ui.label).containing('text')` |
| `@gui` marker | `@gui` marker (unchanged semantics) |

### Test Patterns

```python
# Fast in-process test (replaces qtbot)
from nicegui.testing import User

async def test_dashboard_shows_procedures(user: User):
    # Navigate to dashboard page
    await user.open('/dashboard')

    # Verify UI renders expected content
    await user.should_see('Hospital Dashboard')
    user.find(ui.card).containing('OR-1')
```

```python
# Headless browser test (for complex interactions)
from nicegui.testing import Screen

def test_alert_filter(screen: Screen):
    screen.open('/dashboard')
    screen.click('CRITICAL only')
    screen.should_contain('CRITICAL')
    screen.should_not_contain('INFO')
```

### Preserved Test Semantics

- DDS `DataReader` injection for test isolation (unchanged — GUI constructors
  still accept pre-created readers)
- `@gui`, `@dashboard`, `@unit`, `@integration` markers (unchanged)
- `xdist_group` for test parallelism (unchanged)

---

## Migration Scope & Risk

### In Scope

- All 3 GUI applications: Hospital Dashboard, Procedure Controller, Digital Twin Display
- Shared GUI module (`medtech.gui`)
- GUI tests (3 files + integration tests)
- Docker runtime image (`runtime-python.Dockerfile`)
- Dependencies (`requirements.txt`, `pyproject.toml`)
- Agent docs: technology.md, ui-design-system.md, coding-standards.md, specs, phases

### Out of Scope

- C++ applications (no GUI dependency)
- Non-GUI Python services (ClinicalAlerts engine, simulators)
- DDS infrastructure (QoS, IDL, domain XML, Routing Service)
- CMake build system (Qt was never used in C++ builds)

### Risk Assessment

| Risk | Mitigation |
|------|-----------|
| NiceGUI event loop conflicts with rti.asyncio | Both use standard asyncio — no conflict expected. Validate in Phase N.1 |
| 3D scene performance for 100 Hz robot state | `ui.scene()` fps cap (default 20) matches current QPainter approach; `ui.timer(0.1)` for DDS polling |
| Custom QPainter rendering fidelity | Three.js 3D scene is a strict upgrade; heatmap coloring via material colors |
| Multi-user state isolation | NiceGUI pages are per-client; DDS state dicts use `app.storage.tab` |
| Air-gapped / offline deployment | Bundle static assets via `app.add_static_files()`; no CDN dependency |
| Test coverage regression | Migrate tests 1:1 with NiceGUI `User`/`Screen` fixtures before removing pytest-qt |
| Learning curve | NiceGUI's declarative API is simpler than PySide6 — net reduction in code |

---

## Additional NiceGUI Capabilities to Leverage

Beyond the core migration (PySide6 → NiceGUI 1:1 replacements), the following
NiceGUI features are a natural fit for the medtech-suite and should be adopted
during or shortly after the migration.

### `ui.sub_pages()` — Single-Page App Navigation

The current Multi-Page Architecture (§ above) uses `@ui.page()` per module,
which causes **full page reloads** when navigating between dashboard,
controller, and digital twin. `ui.sub_pages()` enables true SPA navigation
where the application shell — header bar, navigation drawer, connection status
dot, and DDS backend — **persists across page transitions**. Only the content
area is swapped in-place via client-side routing, with no WebSocket
reconnection or DDS reinitialization.

```python
@ui.page('/')
def root():
    # Persistent shell — survives sub-page navigation
    with ui.header():
        ui.image('/static/rti-logo.png').classes('h-8')
        ui.label('MedTech Suite').classes('text-xl font-bold')
        ui.space()
        connection_dot()
        dark_mode_toggle()

    with ui.left_drawer() as drawer:
        ui.link('Dashboard', '/dashboard')
        ui.link('Controller', '/controller')
        ui.link('Digital Twin', '/twin/OR-1')
        ui.link('Alerts', '/alerts')

    # Content area — swapped without full reload
    ui.sub_pages({
        '/dashboard': dashboard_page,
        '/controller': controller_page,
        '/twin/{room_id}': digital_twin_page,
        '/alerts': alerts_page,
    })
```

This implements the route table from the Multi-Page Architecture section as a
true SPA. URL parameters (e.g., `{room_id}`) are passed to builder
functions automatically. The `on_path_changed` callback can be used to
update navigation highlights. See the
[NiceGUI sub_pages docs](https://nicegui.io/documentation/sub_pages) and
the `single_page_app` example.

### `ui.interactive_image()` — Surgical Camera Feed

The `CameraFrame` topic (from `camera_sim`) publishes frame metadata and
image data. `ui.interactive_image()` is designed for exactly this:

- **Non-flickering updates** — if the source URL changes faster than the
  browser can load, intermediate frames are automatically skipped, adapting
  to available bandwidth
- **SVG annotation overlays** — layer surgical annotations (instrument
  bounding boxes, measurement lines, ROI markers) over the camera feed
  without re-transmitting the image
- **Multiple layers** — separate overlay layers (e.g., instrument tracking
  vs. annotation) can be updated independently for performance
- **Mouse event handlers** — click coordinates map to image coordinates
  for interactive annotation or ROI selection

```python
# Camera feed with surgical instrument overlay
feed = ui.interactive_image(size=(1280, 720), cross=True)
annotation_layer = feed.add_layer()

async def _read_camera_frames():
    async for frame in camera_reader.take_data_async():
        feed.set_source(f'data:image/jpeg;base64,{frame.image_b64}')

async def _read_instrument_detections():
    async for det in detection_reader.take_data_async():
        annotation_layer.content = (
            f'<rect x="{det.x}" y="{det.y}" '
            f'width="{det.w}" height="{det.h}" '
            f'fill="none" stroke="lime" stroke-width="2" />'
        )
```

This enables a future Camera View page (`/camera/{room_id}`) in the unified
app. See the
[NiceGUI interactive_image docs](https://nicegui.io/documentation/interactive_image)
and the `opencv_webcam` example.

### FastAPI REST Endpoints — Health Probes

NiceGUI is built on FastAPI. The unified app can expose REST endpoints
alongside the UI without any additional framework — just import `app` and
add routes. This is critical for Docker health checks and Kubernetes
liveness/readiness probes.

```python
from nicegui import app

@app.get('/health')
def health():
    """Liveness probe — is the process alive?"""
    return {'status': 'ok'}

@app.get('/ready')
def ready():
    """Readiness probe — are DDS backends connected?"""
    all_ready = all(
        b._participant is not None
        for b in [dashboard_backend, controller_backend]
    )
    if not all_ready:
        from fastapi.responses import JSONResponse
        return JSONResponse({'status': 'not ready'}, status_code=503)
    return {'status': 'ready'}
```

Update `docker/medtech-app.Dockerfile` `HEALTHCHECK` to use
`curl http://localhost:8080/health`. See the
[NiceGUI FastAPI example](https://github.com/zauberzeug/nicegui/tree/main/examples/fastapi).

### `ui.tree()` — ServiceHost Hierarchy

The Procedure Controller currently renders hosts and services as flat card
grids. `ui.tree()` maps naturally to the `ServiceHost → Service` hierarchy
with expand/collapse, selection callbacks, and live node updates:

```python
ui.tree([
    {
        'id': 'host-OR1',
        'label': 'OR-1 Host',
        'children': [
            {'id': 'svc-vitals', 'label': 'BedsideMonitor (RUNNING)'},
            {'id': 'svc-camera', 'label': 'CameraService (RUNNING)'},
            {'id': 'svc-robot',  'label': 'RobotController (STARTING)'},
        ],
    },
], on_select=lambda e: show_service_detail(e.value))
```

This can complement or replace the card grid for the host/service view,
depending on information density requirements.

### `ui.circular_progress()` — Procedure & Resource Gauges

Compact radial gauges for at-a-glance metrics:

- **Procedure completion** — phase progress (prep → active → closing → complete)
- **Resource utilization** — OR capacity, equipment availability percentage
- **Vitals severity** — aggregate patient risk score as a colored ring

```python
ui.circular_progress(value=0.75, show_value=True, color='positive')
    .bind_value_from(backend, 'procedure_progress')
```

These pair well with `create_stat_card()` in the shared GUI module.

### `ui.log()` — DDS Event Audit Trail

An append-only log view that pushes new lines without retransmitting history.
Ideal for:

- **Alert feed panel** — raw alert stream with severity coloring
- **DDS debug panel** — sample-level trace of all topics (dev/debug mode)
- **Orchestration log** — service state transitions

```python
event_log = ui.log(max_lines=500).classes('w-full h-48 font-mono text-xs')

async def _read_alerts():
    async for alert in alert_reader.take_data_async():
        event_log.push(
            f'[{alert.timestamp}] {alert.severity}: {alert.message}'
        )
```

More efficient than rebuilding a `ui.scroll_area()` of cards for
high-frequency event streams.
