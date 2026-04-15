# Spec: Hospital Dashboard Module

Behavioral specifications for the facility-wide NiceGUI web dashboard that provides hospital-level situational awareness. The primary view organizes information by **room** — each active room is displayed as a summary card with deployment status, procedure indicator, and aggregate metrics. Users drill into room-specific views (controller, digital twin, etc.) by opening the room's GUI in a **new browser tab** (room GUIs are served by per-room containers, not the hospital container).

The dashboard subscribes to the Hospital Integration databus (Hospital Integration databus). All room data arrives via Routing Service from the Procedure and Orchestration databuss. Room discovery uses RS-bridged `ServiceCatalog` from the Orchestration databus.

---

## Summary of Concrete Requirements

| Requirement | Value |
|-------------|-------|
| Room discovery source | RS-bridged `ServiceCatalog` from the Orchestration databus via per-room MedtechBridge — `room_id` and `gui_url` properties |
| Cross-plane navigation icon | `open_in_new` (Material Icons) on all links that open a new browser tab |
| New CRITICAL alert maximum display latency | ≤ 2 s from DDS publication |
| Vitals HR warning color threshold | HR > 100 bpm (yellow/amber) |
| Vitals HR critical color threshold | HR > 120 bpm (red) |
| Robot state liveliness lease (disconnect detection) | 2 s |
| Procedure list update | Automatic on new `ProcedureStatus` sample — no manual refresh required |
| UI thread protection | DDS reads and writes run as asyncio coroutines on the NiceGUI event loop via `background_tasks.create()`; blocking waits (`WaitSet.wait()`, synchronous `take()`) are prohibited; UI updates are driven by `ui.timer()` or `@ui.refreshable` on the asyncio event loop thread |
| Dashboard initialization — participants matched and initial state displayed | ≤ 15 s from process start on `hospital-net` |
| Dashboard restart re-integration | ≤ 15 s from restart to displaying current state for all active procedures |
| Routing Service unavailability | Dashboard continues displaying last known values; stale indicator shown; no crash |
| Routing Service recovery | Dashboard resumes live display within initialization time budget after RS restart |

*This table must be updated whenever a concrete value in the scenarios below is added or changed.*

---

## Room Overview (primary view)

### Scenario: Dashboard displays discovered rooms as cards `@e2e` `@gui`

**Given** the hospital dashboard is running and subscribed to RS-bridged `ServiceCatalog` on the Hospital Integration databus
**And** two rooms have active Service Hosts (OR-1 and OR-3)
**When** `ServiceCatalog` samples with `room_id` properties arrive via Routing Service
**Then** the dashboard displays a room card for each discovered room
**And** each card shows the room name (e.g., "OR-1")

### Scenario: Room card shows active procedure indicator `@e2e` `@gui`

**Given** the dashboard is displaying room cards for OR-1 and OR-3
**And** OR-1 has services deployed with a non-empty `procedure_id` in their `ServiceCatalog` entries
**And** OR-3 has no active procedure (`procedure_id` is empty for all its services)
**When** the room cards are rendered
**Then** OR-1's card shows an active procedure indicator (e.g., procedure type, phase badge)
**And** OR-3's card shows an idle/no-procedure state

### Scenario: Room card shows aggregate service metrics `@e2e` `@gui`

**Given** the dashboard is displaying a room card for OR-1
**And** OR-1 has 6 services in its `ServiceCatalog` and 4 are in `RUNNING` state
**When** `ServiceStatus` samples arrive via Routing Service
**Then** the room card shows service counts (e.g., "4/6 running")

### Scenario: Room card shows alert/warning count `@e2e` `@gui`

**Given** the dashboard is displaying room cards
**And** OR-1 has 2 active CRITICAL alerts and 1 WARNING alert
**When** alert data arrives via Routing Service
**Then** OR-1's room card shows the alert/warning counts with appropriate severity colors

### Scenario: New room appears automatically `@e2e` `@gui`

**Given** the dashboard is displaying room cards for OR-1 and OR-3
**When** a new OR (OR-5) is deployed and its `ServiceCatalog` entries arrive via Routing Service
**Then** a new room card for OR-5 appears without requiring manual refresh

### Scenario: Room card links to room-level GUIs in new browser tab `@e2e` `@gui`

**Given** the dashboard is displaying a room card for OR-1
**And** OR-1's `ServiceCatalog` entries include `gui_url` properties (e.g., controller at `http://localhost:8091/controller/OR-1`, twin at `http://localhost:8081/twin/OR-1`)
**When** the user views OR-1's room card
**Then** the card shows action links/buttons for each discovered GUI (e.g., "Controller", "Twin")
**And** each link includes the `open_in_new` icon (Material Icons) indicating a new tab/window will open
**And** clicking a link opens the GUI URL in a new browser tab

### Scenario: Room card without running GUIs shows no action links `@e2e` `@gui`

**Given** the dashboard is displaying a room card for OR-1
**And** OR-1's `ServiceCatalog` entries have no `gui_url` properties (GUI services not yet started)
**When** the room card is rendered
**Then** no GUI action links are shown for OR-1

---

## Active Procedures (secondary view)

### Scenario: Active Procedures view filters to rooms with running procedures `@e2e` `@gui`

**Given** the dashboard has discovered rooms OR-1, OR-3, and OR-5
**And** OR-1 and OR-3 have active procedures, OR-5 is idle
**When** the user switches to the "Active Procedures" view
**Then** only OR-1 and OR-3 are displayed
**And** each entry shows room, patient, procedure type, surgeon, phase, and elapsed time

---

## Procedure List

### Scenario: Dashboard displays all active procedures `@e2e` `@gui`

**Given** the hospital dashboard is running and subscribed to `ProcedureStatus` on the Hospital Integration databus
**And** two surgical procedure instances are active (OR-1 and OR-3)
**When** both procedures publish `ProcedureStatus` via Routing Service
**Then** the dashboard displays both procedures in the procedure list
**And** each entry shows room, patient, procedure type, surgeon, and current status

### Scenario: New procedure appears automatically `@e2e` `@gui`

**Given** the dashboard is running with one active procedure displayed
**When** a new surgical procedure instance starts in OR-5
**And** its `ProcedureStatus` arrives via Routing Service
**Then** the dashboard adds OR-5 to the procedure list without requiring manual refresh

### Scenario: Completed procedure is updated in display `@e2e` `@gui`

**Given** the dashboard shows procedure in OR-1 as "In Progress"
**When** the procedure publishes status "Completing"
**Then** the dashboard updates OR-1's status indicator accordingly

---

## Vitals Overview

### Scenario: Dashboard shows summarized vitals per procedure `@e2e` `@gui`

**Given** the dashboard is subscribed to vitals summary data on the Hospital Integration databus
**And** two procedures are active with patients
**When** vitals data is bridged from the Procedure databuses via Routing Service
**Then** each procedure row in the dashboard shows current HR, SpO2, and BP for its patient

### Scenario: Vitals are color-coded by severity `@e2e` `@gui`

**Given** the dashboard is displaying vitals for a patient
**When** the patient's HR exceeds 100 bpm (warning threshold)
**Then** the HR display changes to the warning color (yellow/amber)
**When** the patient's HR exceeds 120 bpm (critical threshold)
**Then** the HR display changes to the critical color (red)

### Scenario: Dashboard receives vitals on startup via durability `@e2e` `@durability`

**Given** surgical procedures have been publishing vitals for several minutes
**When** the hospital dashboard starts and joins the Hospital Integration databus
**Then** the dashboard immediately displays current vitals for all active patients
**And** does not show a blank or "waiting for data" state for already-active procedures

---

## Alert Feed

### Scenario: Alerts from all ORs appear in unified alert feed `@e2e` `@gui`

**Given** the dashboard is subscribed to `ClinicalAlert` on the Hospital Integration databus
**When** alerts are generated for patients in OR-1 and OR-3
**Then** all alerts appear in the centralized alert feed
**And** each alert shows severity, category, room, patient, and message

### Scenario: Alert feed is filterable by severity `@e2e` `@gui`

**Given** the alert feed contains alerts of mixed severity (INFO, WARNING, CRITICAL)
**When** the user selects "CRITICAL only" filter
**Then** only CRITICAL alerts are displayed
**And** the filter can be cleared to show all alerts again

### Scenario: Alert feed is filterable by room `@e2e` `@gui`

**Given** the alert feed contains alerts from OR-1 and OR-3
**When** the user selects room filter "OR-1"
**Then** only alerts from OR-1 are displayed

### Scenario: New alerts appear in real-time `@e2e` `@gui`

**Given** the dashboard alert feed is visible
**When** a new CRITICAL alert is published on the Hospital Integration databus
**Then** the alert appears in the feed within 2 seconds of publication
**And** the new alert is visually distinguished (e.g., highlight, animation)

---

## Robot Status

### Scenario: Dashboard shows robot state per OR `@e2e` `@gui`

**Given** the dashboard receives `RobotState` (read-only, bridged from the Procedure control databus via Routing Service)
**When** a robot in OR-3 is in OPERATIONAL mode
**Then** the dashboard shows OR-3's robot status as "Operational" with a green indicator

### Scenario: Robot emergency stop is prominently displayed `@e2e` `@gui`

**Given** the dashboard is showing robot status for OR-3
**When** the robot state changes to EMERGENCY_STOP
**Then** the dashboard immediately updates OR-3's robot status to "E-STOP" with a red indicator
**And** the status change is visually prominent (e.g., flashing, enlarged)

### Scenario: Robot disconnect is detected via liveliness `@e2e` `@gui`

**Given** the dashboard is showing robot status for OR-3
**When** the robot state writer's liveliness expires (no heartbeat for 2 s)
**Then** the dashboard shows OR-3's robot status as "Disconnected" with a gray indicator

---

## Resource Panel

### Scenario: Dashboard displays current resource availability `@e2e` `@gui`

**Given** the hospital dashboard is subscribed to `ResourceAvailability` on the Hospital Integration databus
**And** the resource status simulator is publishing availability for ORs, beds, and staff
**When** the dashboard is running
**Then** the dashboard displays a resource panel showing each resource's name, kind, availability status, and location

### Scenario: Resource availability updates in real-time `@e2e` `@gui`

**Given** the dashboard is displaying resource availability
**When** the resource status simulator publishes an updated `ResourceAvailability` sample (e.g., OR-5 becomes unavailable)
**Then** the dashboard updates the resource panel to reflect the new status

### Scenario: Dashboard receives resource state on startup via durability `@e2e` `@durability`

**Given** the resource status simulator has been publishing `ResourceAvailability` with TRANSIENT_LOCAL durability
**When** the hospital dashboard starts and joins the Hospital Integration databus
**Then** the dashboard immediately displays current resource availability for all published resources

---

## GUI Threading & DDS Integration

### Scenario: DDS data processing does not block the UI `@gui`

**Given** the dashboard is running with active data subscriptions
**When** a burst of data arrives simultaneously (vitals + alerts + robot state)
**Then** the UI remains responsive (no freeze or stutter)
**And** DDS reads run as asyncio coroutines via `take_data_async()` / `background_tasks.create()` (never blocking waits on the event loop)
**And** DDS writes use DataWriters configured with the `NonBlockingWrite` QoS snippet on the asyncio event loop
**And** no blocking waits (`WaitSet.wait()`, synchronous tight-loop `take()`) occur on the event loop thread

### Scenario: Content-filtered topics reduce unnecessary processing `@integration` `@filtering`

**Given** the dashboard user has drilled into OR-3's detail view
**When** a content-filtered topic is active for `patient.id` matching OR-3's patient
**Then** the reader receives only data for that patient
**And** data for other patients does not reach the reader's cache

---

## System Initialization

### Scenario: Dashboard reaches operational state within time budget `@e2e` `@performance`

**Given** the Hospital Integration databus, Routing Service bridge, and all active procedure instances are running
**When** the hospital dashboard process starts
**Then** all DomainParticipant endpoints have matched within 15 s of start
**And** current `ProcedureStatus`, `PatientVitals`, `ClinicalAlert`, and `RobotState` data is displayed within 15 s (received via TRANSIENT_LOCAL durability or active bridging)
**And** no procedure entry appears blank or shows a "waiting for data" placeholder after the 15 s window

### Scenario: Restarted dashboard re-integrates within time budget `@e2e` `@performance`

**Given** the hospital dashboard is running and displaying data for active procedures
**When** the dashboard process is stopped and restarted
**Then** the restarted dashboard displays current state for all active procedures within 15 s of restart
**And** no manual interaction is required to trigger data display

---

## Degraded Mode

### Scenario: Dashboard displays stale-data indicator when Routing Service is unavailable `@e2e` `@gui`

**Given** the hospital dashboard is running and displaying live data
**When** Routing Service is stopped and no new data arrives
**Then** the dashboard continues to display the last known values
**And** a visual indicator (e.g., grayed timestamp, "stale" badge) marks data as not recently updated
**And** the dashboard does not crash or freeze

### Scenario: Dashboard recovers when Routing Service restarts `@e2e` `@gui`

**Given** the dashboard is in a degraded state (no data arriving from Routing Service)
**When** Routing Service is restarted
**Then** the dashboard resumes displaying live data within the initialization time budget
**And** stale-data indicators are removed

---

## Visual Design & Theming

### Scenario: Dashboard uses glassmorphism for floating overlay panels `@gui` `@ui-modernization`

**Given** the hospital dashboard is running
**When** any floating overlay (alert detail popover, filter dropdown, HUD panel) is displayed
**Then** the overlay uses a translucent background with backdrop blur (glassmorphism)
**And** the overlay has a 16 px border radius and a 1 px translucent border for edge definition
**And** content behind the overlay is visibly blurred, creating a depth hierarchy

### Scenario: Dashboard applies design token system for all visual values `@gui` `@ui-modernization`

**Given** the hospital dashboard renders any page
**When** colors, spacing, radii, shadows, or transitions are applied to elements
**Then** all values are derived from the centralized design token system (`DESIGN_TOKENS` or `BRAND_COLORS`)
**And** no hardcoded hex colors, pixel sizes, or timing strings appear in component-level code

### Scenario: Skeleton loaders appear during initial data discovery `@gui` `@ui-modernization`

**Given** the hospital dashboard is starting and DDS endpoints have not yet matched
**When** the dashboard page renders before data is available
**Then** procedure cards, vitals rows, and resource entries display skeleton placeholder animations (shimmer effect)
**And** skeleton loaders are replaced by real data once DDS samples arrive
**And** no blank or "waiting for data" text is shown during the discovery window

### Scenario: Status chips include icon alongside color `@gui` `@ui-modernization`

**Given** the dashboard displays status indicators for procedures, robots, or resources
**When** any status chip is rendered (OPERATIONAL, E-STOP, PAUSED, IDLE, DISCONNECTED, etc.)
**Then** the chip includes both a semantic icon and color-coded background tint
**And** the status is distinguishable without relying solely on color (color-blind accessible)

### Scenario: Critical alerts use attention-drawing pulse animation `@gui` `@ui-modernization`

**Given** the dashboard alert feed is visible
**When** a new CRITICAL alert appears
**Then** the alert card slides in with a fade-in animation (300 ms)
**And** CRITICAL severity alerts display a pulsing red border ring animation until acknowledged or scrolled past
**And** the animation respects `prefers-reduced-motion` browser settings

### Scenario: Card hover shows elevated state `@gui` `@ui-modernization`

**Given** the dashboard is displaying procedure cards or resource tiles
**When** the user hovers over a card (pointer device)
**Then** the card smoothly scales to 1.02× and shadow increases to the `shadow-lg` tier (200 ms transition)
**And** the hover state does not shift adjacent card positions (transform only, no layout reflow)

### Scenario: Inter font renders for all non-monospace text `@gui` `@ui-modernization`

**Given** the dashboard has loaded and fonts are available
**When** any page renders
**Then** headline labels, section headers, and body text use the Inter font family
**And** numeric data values use Roboto Mono
**And** no external font CDN requests are made (fonts loaded from local static files)

### Scenario: Focus-visible rings appear on keyboard navigation `@gui` `@a11y`

**Given** the dashboard is rendered in a browser
**When** a user navigates interactive elements using the Tab key
**Then** each focused element displays a visible 2 px blue (`info` color) outline ring
**And** the ring does not appear on mouse/touch interactions (only `focus-visible`)

### Scenario: Reduced motion preference disables animations `@gui` `@a11y`

**Given** the user's browser has `prefers-reduced-motion: reduce` enabled
**When** the dashboard renders
**Then** all CSS animations (pulse, shimmer, slide-in) are suppressed
**And** transitions complete near-instantly (≤ 1 ms)
**And** the dashboard remains fully functional without motion

### Scenario: Dashboard uses semantic type scale `@gui` `@ui-modernization`

**Given** the dashboard renders text content
**When** headings, body text, labels, and data values are displayed
**Then** each text element uses a size from the semantic type scale (heading-1 through mono-small)
**And** no arbitrary font sizes outside the type scale are used
