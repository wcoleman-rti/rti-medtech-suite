# Spec: Hospital Dashboard Module

Behavioral specifications for the facility-wide NiceGUI web dashboard that displays real-time procedure status, patient vitals, alerts, and robot state across all active surgical rooms.

The dashboard subscribes to the Hospital domain. All data arrives via Routing Service from the Procedure domain.

---

## Summary of Concrete Requirements

| Requirement | Value |
|-------------|-------|
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

## Procedure List

### Scenario: Dashboard displays all active procedures `@e2e` `@gui`

**Given** the hospital dashboard is running and subscribed to `ProcedureStatus` on the Hospital domain
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

**Given** the dashboard is subscribed to vitals summary data on the Hospital domain
**And** two procedures are active with patients
**When** vitals data is bridged from the Procedure domain via Routing Service
**Then** each procedure row in the dashboard shows current HR, SpO2, and BP for its patient

### Scenario: Vitals are color-coded by severity `@e2e` `@gui`

**Given** the dashboard is displaying vitals for a patient
**When** the patient's HR exceeds 100 bpm (warning threshold)
**Then** the HR display changes to the warning color (yellow/amber)
**When** the patient's HR exceeds 120 bpm (critical threshold)
**Then** the HR display changes to the critical color (red)

### Scenario: Dashboard receives vitals on startup via durability `@e2e` `@durability`

**Given** surgical procedures have been publishing vitals for several minutes
**When** the hospital dashboard starts and joins the Hospital domain
**Then** the dashboard immediately displays current vitals for all active patients
**And** does not show a blank or "waiting for data" state for already-active procedures

---

## Alert Feed

### Scenario: Alerts from all ORs appear in unified alert feed `@e2e` `@gui`

**Given** the dashboard is subscribed to `ClinicalAlert` on the Hospital domain
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
**When** a new CRITICAL alert is published on the Hospital domain
**Then** the alert appears in the feed within 2 seconds of publication
**And** the new alert is visually distinguished (e.g., highlight, animation)

---

## Robot Status

### Scenario: Dashboard shows robot state per OR `@e2e` `@gui`

**Given** the dashboard receives `RobotState` (read-only, bridged from the Procedure domain (`control` tag) via Routing Service)
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

**Given** the hospital dashboard is subscribed to `ResourceAvailability` on the Hospital domain
**And** the resource status simulator is publishing availability for ORs, beds, and staff
**When** the dashboard is running
**Then** the dashboard displays a resource panel showing each resource's name, kind, availability status, and location

### Scenario: Resource availability updates in real-time `@e2e` `@gui`

**Given** the dashboard is displaying resource availability
**When** the resource status simulator publishes an updated `ResourceAvailability` sample (e.g., OR-5 becomes unavailable)
**Then** the dashboard updates the resource panel to reflect the new status

### Scenario: Dashboard receives resource state on startup via durability `@e2e` `@durability`

**Given** the resource status simulator has been publishing `ResourceAvailability` with TRANSIENT_LOCAL durability
**When** the hospital dashboard starts and joins the Hospital domain
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

**Given** the Hospital domain, Routing Service bridge, and all active procedure instances are running
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
