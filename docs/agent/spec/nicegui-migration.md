# Spec: NiceGUI Migration

> **Status: COMPLETE (Steps N.1–N.5).** The PySide6 → NiceGUI migration
> has been fully implemented for all three GUI applications. All
> `@gui` tests have been rewritten with NiceGUI `User` fixtures.
> PySide6 and pytest-qt have been removed. This spec remains
> **authoritative** — its scenarios are ongoing behavioral contracts
> that must continue to pass. Steps N.6–N.8 are tracked separately
> in the migration phase file.
>
> For the evolving visual design modernization (glassmorphism,
> design tokens, animation, accessibility), see the new scenarios in
> [hospital-dashboard.md](hospital-dashboard.md) and
> [surgical-procedure.md](surgical-procedure.md) tagged
> `@ui-modernization`.

Behavioral specifications for the PySide6 → NiceGUI migration. These scenarios
validate that migrated GUI applications preserve existing behavior and leverage
new NiceGUI capabilities.

Existing specs ([hospital-dashboard.md](hospital-dashboard.md),
[clinical-alerts.md](clinical-alerts.md)) remain authoritative for domain
behavior. This spec covers **migration-specific** concerns: framework
integration, multi-client behavior, theming, and DDS event loop unification.

---

## Summary of Concrete Requirements

| Requirement | Value |
|-------------|-------|
| NiceGUI server startup to first page render | ≤ 3 s |
| DDS participant creation timing | During `GuiBackend.__init__()` (synchronous, module-level); `app.on_startup` triggers `start()` for background reader loops |
| UI update latency (DDS sample → browser render) | ≤ 200 ms (WebSocket push) |
| Maximum concurrent browser clients (dashboard) | ≥ 10 without degradation |
| Dark/light theme switch latency | ≤ 100 ms (client-side, no server round-trip) |
| Page route patterns | `/dashboard`, `/controller`, `/twin/{room_id}`, `/alerts` |
| Static asset serving | Local fonts + images via `app.add_static_files()` — no external CDN |
| Test migration coverage | Every existing `@gui` test has a NiceGUI equivalent before PySide6 removal |

---

## Event Loop Integration

### Scenario: DDS async reads run on NiceGUI's asyncio event loop `@integration`

**Given** a NiceGUI application with a `GuiBackend` subclass that creates a DomainParticipant during construction
**And** DataReaders using `rti.asyncio` async iteration
**When** DDS samples arrive on a subscribed topic
**Then** the async reader coroutine receives the samples on the same asyncio event loop as NiceGUI
**And** UI elements can be updated directly from the reader coroutine without cross-thread signaling

### Scenario: DDS participant lifecycle follows app lifecycle `@integration`

**Given** a NiceGUI application with a `GuiBackend` subclass that creates a DomainParticipant during construction
**When** the application is shut down via `app.shutdown()` or SIGTERM
**Then** the `GuiBackend.close()` method (triggered by `app.on_shutdown`) closes the DomainParticipant and all associated entities
**And** no DDS resources leak after shutdown

### Scenario: Long-running DDS operations do not block UI `@integration`

**Given** a NiceGUI application processing high-rate DDS data (100 Hz RobotState)
**When** the UI requests a page render or handles a click event
**Then** the UI remains responsive (event handlers execute within 100 ms)
**And** DDS reads are interleaved with UI updates via cooperative async scheduling

---

## GuiBackend ABC Contract

### Scenario: GuiBackend enforces abstract method implementation `@unit`

**Given** the `GuiBackend` ABC defines abstract methods `start()`, `close()`, and property `name`
**When** a developer subclasses `GuiBackend` without implementing all three
**Then** instantiation raises `TypeError`
**And** the error message identifies the missing abstract members

### Scenario: GuiBackend registers NiceGUI lifecycle hooks on construction `@unit`

**Given** a concrete `GuiBackend` subclass with DDS init in its `__init__`
**When** the subclass calls `super().__init__()` as its last `__init__` line
**Then** `app.on_startup` is registered with the subclass's `start()` method
**And** `app.on_shutdown` is registered with the subclass's `close()` method
**And** no duplicate hooks are registered

### Scenario: GuiBackend start() runs only after event loop is active `@integration`

**Given** a `GuiBackend` subclass instantiated at module level (DDS init is synchronous)
**When** NiceGUI starts the uvicorn server and the asyncio event loop begins
**Then** the `start()` method is called via the registered `app.on_startup` hook
**And** `background_tasks.create()` calls within `start()` succeed (event loop is running)

---

## Multi-Client Behavior

### Scenario: Multiple browser clients see the same DDS data `@integration` `@gui`

**Given** the hospital dashboard is running as a NiceGUI web app
**And** two browser clients are connected to `/dashboard`
**When** a new `ProcedureStatus` sample arrives via DDS
**Then** both clients display the updated procedure within 2 seconds
**And** each client maintains independent UI state (scroll position, selected filters)

### Scenario: Client disconnect does not affect other clients `@integration`

**Given** three browser clients are connected to the dashboard
**When** one client closes the browser tab
**Then** the remaining two clients continue displaying live data
**And** `app.on_disconnect` is called for the disconnected client only

### Scenario: Late-joining client receives current state `@gui` `@durability`

**Given** the dashboard has been running and displaying data for several minutes
**When** a new browser client connects to `/dashboard`
**Then** the client immediately sees current procedure status, vitals, and alerts
**And** does not show a blank or "loading" state for already-active procedures

---

## Theming & Branding

### Scenario: RTI brand colors are applied globally `@gui` `@unit`

**Given** the NiceGUI app starts with `app.colors(primary='#004A8A', accent='#E68A00', ...)`
**When** any page renders
**Then** primary-colored elements use RTI Blue (#004A8A)
**And** accent-colored elements use RTI Orange (#E68A00)

### Scenario: Dark mode toggle works without page reload `@gui`

**Given** a dashboard page is rendered in dark mode
**When** the user toggles the dark mode switch
**Then** the page transitions to light mode within 100 ms
**And** all elements update their appearance (background, text, borders)
**And** no server round-trip is required for the theme switch

### Scenario: Custom fonts are loaded from local static files `@gui` `@unit`

**Given** Inter and Roboto Mono are served via `app.add_static_files('/fonts', ...)`
**When** a page renders
**Then** headline and body labels use Inter (variable weight)
**And** numeric value labels use Roboto Mono Bold
**And** no external font CDN requests are made

### Scenario: Material Symbols (outlined) is the sole icon set `@gui` `@unit`

**Given** the NiceGUI app starts with `quasar_config={'iconSet': 'material-symbols-outlined'}`
**When** any `ui.icon()` element renders
**Then** the icon uses the Material Symbols Outlined font family
**And** no other icon libraries (Font Awesome, Bootstrap Icons, Material Icons) are loaded

---

## Persistent User Settings

### Scenario: Theme preference persists across browser sessions `@gui`

**Given** a user toggles dark mode to "light" on the dashboard
**When** the user closes the browser tab and reopens `/dashboard` later
**Then** the page renders in light mode (preference recalled from `app.storage.user`)
**And** the preference persists across server restarts

### Scenario: Filter state persists within a browser tab `@gui`

**Given** a user sets the severity filter to "CRITICAL" on the dashboard
**When** the user navigates to `/controller` and returns to `/dashboard`
**Then** the severity filter is still set to "CRITICAL" (restored from `app.storage.tab`)

### Scenario: Storage requires secret for session signing `@deployment`

**Given** the NiceGUI application calls `ui.run(storage_secret='...')`
**When** `app.storage.user` or `app.storage.tab` is accessed
**Then** the session cookie is signed with the provided secret
**And** unsigned or tampered cookies are rejected

---

## Page Routing

### Scenario: Dashboard is accessible at /dashboard `@gui`

**Given** the NiceGUI application is running
**When** a browser navigates to `/dashboard`
**Then** the hospital dashboard page renders with procedure list, vitals, alerts, and robot status panels

### Scenario: Digital twin accepts room parameter `@gui`

**Given** the NiceGUI application is running
**When** a browser navigates to `/twin/OR-3`
**Then** the digital twin page renders with DDS subscriptions filtered to room OR-3
**And** the page title includes the room identifier

### Scenario: SPA navigation does not reload the page shell `@integration` `@gui`

**Given** the hospital app uses `ui.sub_pages()` for client-side routing
**And** a user is viewing `/dashboard`
**When** the user navigates to `/alerts` via the navigation pill
**Then** only the content area is swapped (no full page reload)
**And** the header bar, connection dot, and navigation pill persist
**And** the WebSocket connection remains open (no reconnection)
**And** all `GuiBackend` instances remain active — no DDS reinitialization

### Scenario: Browser refresh at sub-page preserves the app shell `@gui` `@ui-modernization`

**Given** the hospital app is running and the user is viewing `/dashboard`
**When** the user refreshes the browser (F5 or Ctrl+R)
**Then** the page re-renders with the full SPA shell (nav pill, connection dot)
**And** the dashboard content is displayed in the content area
**And** the navigation pill is fully functional

### Scenario: Direct URL entry renders full app shell `@gui` `@ui-modernization`

**Given** the hospital app is running
**When** a user pastes `http://localhost:8080/dashboard` directly into the browser address bar
**Then** the page renders with the full SPA shell (nav pill, connection dot)
**And** the dashboard content is displayed in the content area

### Scenario: Active nav item is highlighted in nav pill `@gui` `@ui-modernization`

**Given** the hospital app is running with the navigation pill visible
**When** the user navigates to `/dashboard`
**Then** the "Dashboard" button in the nav pill is visually highlighted (active state)
**And** other nav items are in their default (inactive) state

### Scenario: Breadcrumb shows current page context `@gui` `@ui-modernization`

**Given** the hospital app header displays a breadcrumb or dynamic title
**When** the user navigates to `/dashboard`
**Then** the header shows "Medtech Suite › Dashboard" (or equivalent contextual title)

### Scenario: Shared link to hospital sub-page works for new visitors `@gui` `@ui-modernization`

**Given** the hospital dashboard app is running
**When** a new browser session opens `/dashboard` for the first time (no prior navigation)
**Then** the full SPA shell renders with nav pill and dashboard content

### Scenario: Discovered room appears as room card on dashboard `@gui` `@ui-modernization`

**Given** the hospital dashboard Room Overview is displayed with no active rooms
**When** a per-room Routing Service bridges a `ServiceCatalog` sample with `gui_url = "http://localhost:8091/controller/OR-3"` to Domain 20
**Then** a new room card appears in the Room Overview within 5 seconds
**And** the card shows the room's `room_id` (e.g., "OR-3") and aggregated status

### Scenario: Room card opens room GUI in new browser tab `@gui` `@ui-modernization`

**Given** the Room Overview shows a room card for "OR-3" with `gui_url` `http://localhost:8091/controller/OR-3`
**When** the user clicks the room card's `open_in_new` button
**Then** a new browser tab opens with the full `gui_url`
**And** the hospital dashboard tab remains unchanged

### Scenario: Room disposal removes room card `@gui` `@ui-modernization`

**Given** the Room Overview shows a room card for "OR-3"
**When** that room's `ServiceCatalog` samples are disposed (NOT_ALIVE_NO_WRITERS or explicit dispose)
**Then** the room card is removed within 5 seconds

### Scenario: Room-level nav pill discovers sibling GUIs `@gui` `@ui-modernization`

**Given** a room GUI (e.g., Procedure Controller for OR-1) is open in its own browser tab
**And** the `medtech.gui.room_nav` module has created a read-only Orchestration participant
**When** a sibling service in the same room publishes a `ServiceCatalog` sample with `gui_url`
**Then** a new button appears in the floating nav pill within 5 seconds
**And** clicking the button navigates to the sibling's `gui_url` in the same tab

### Scenario: Room GUI has no upward hospital link `@gui` `@ui-modernization`

**Given** a room GUI (controller or twin) is open in a standalone browser tab
**When** the page finishes rendering
**Then** there is no link, button, or navigation element pointing to the hospital dashboard
**And** the user returns to the hospital level by closing the browser tab

> **Note:** The `/alerts` route (Clinical Alerts Dashboard) is a **new capability**
> enabled by the migration, not a 1:1 PySide6 replacement. Its behavioral spec
> will be defined in a future extension of [clinical-alerts.md](clinical-alerts.md)
> when the visual alerts frontend is scoped. It is not required for migration
> completion.

---

## Component Migration Parity

### Scenario: Status chips render with correct colors per state `@gui` `@unit`

**Given** the `create_status_chip()` helper is reimplemented using `ui.chip()`
**When** a chip is created for each state (RUNNING, STOPPED, ERROR, EMERGENCY_STOP, etc.)
**Then** each chip displays the correct background color matching the current design system
**And** dark mode and light mode each have their own color mapping

### Scenario: Stat cards display KPI values with live binding `@gui`

**Given** the stat card component is reimplemented using `ui.card()` with `bind_text_from()`
**When** the underlying data model updates (e.g., Hosts Online count changes)
**Then** the stat card value updates automatically without manual refresh

### Scenario: Alert feed with real-time append `@gui`

**Given** the alert feed is implemented with `ui.scroll_area()` containing alert cards
**When** a new `ClinicalAlert` sample arrives
**Then** a new alert card is prepended to the feed
**And** the feed auto-scrolls to show the new alert (if user is at top)
**And** if the user has scrolled down, the scroll position is preserved

---

## Digital Twin 3D Upgrade

### Scenario: Robot arm renders in 3D scene `@gui`

**Given** the digital twin page uses `ui.scene()` for robot visualization
**When** `RobotState` samples arrive with joint angles
**Then** 3D cylinder segments rotate to match joint positions
**And** each segment is colored by its heatmap value (cold → neutral → hot)

### Scenario: User can orbit and zoom the 3D view `@gui`

**Given** the 3D robot scene is displayed
**When** the user drags to orbit or scrolls to zoom
**Then** the camera moves smoothly
**And** DDS data continues updating the robot pose during interaction

### Scenario: Safety interlock overlay appears in 3D scene `@gui`

**Given** the robot is displayed in the 3D scene
**When** a `SafetyInterlock` sample indicates an active interlock
**Then** a prominent red overlay or notification appears
**And** the robot visualization shows the interlock state

---

## Docker & Deployment

### Scenario: GUI application runs in Docker without Qt dependencies `@deployment`

**Given** a Docker image built from the updated `runtime-python.Dockerfile`
**And** the image does NOT contain libgl1, libglib2.0, libxkbcommon0, libegl1, or libdbus
**When** the container starts the NiceGUI application
**Then** the web server listens on port 8080
**And** a browser on the host network can access the dashboard

### Scenario: Hospital dashboard container serves dashboard pages `@deployment`

**Given** the hospital Docker container is running the NiceGUI dashboard app
**When** a browser accesses `/dashboard`
**Then** the dashboard page renders correctly
**And** the container does NOT serve `/controller` or `/twin` routes (those are served by room containers)

---

## Health & Readiness Probes

### Scenario: Liveness probe returns 200 when process is alive `@deployment`

**Given** the NiceGUI application is running
**When** a client sends `GET /health`
**Then** the response status is 200
**And** the body contains `{"status": "ok"}`

### Scenario: Readiness probe returns 503 when backends are not connected `@deployment`

**Given** the NiceGUI application has started but DDS backends have not yet completed `start()`
**When** a client sends `GET /ready`
**Then** the response status is 503
**And** the body contains `{"status": "not ready"}`

### Scenario: Readiness probe returns 200 when all backends are connected `@deployment`

**Given** all `GuiBackend` instances have completed `start()` and DDS participants are active
**When** a client sends `GET /ready`
**Then** the response status is 200
**And** the body contains `{"status": "ready"}`

---

## Test Migration

### Scenario: pytest-qt tests have NiceGUI equivalents `@meta`

**Given** the existing test files: `test_hospital_dashboard.py`, `test_digital_twin.py`, `test_init_theme.py`
**When** the migration is complete
**Then** each `@gui` test case has a corresponding NiceGUI test using `User` or `Screen` fixture
**And** the `@gui` marker semantics are preserved
**And** `pytest-qt` is removed from `requirements.txt`

### Scenario: DDS reader injection still works for test isolation `@unit`

**Given** a NiceGUI page function that accepts optional DataReader parameters
**When** a test provides pre-created mock DataReaders
**Then** the page uses the injected readers instead of creating its own
**And** test assertions verify UI state based on injected data
