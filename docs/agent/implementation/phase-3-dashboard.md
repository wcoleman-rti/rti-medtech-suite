# Phase 3: Hospital Dashboard

**Goal:** Implement the PySide6 hospital dashboard GUI that displays real-time procedure status, patient vitals, alerts, and robot state across all active ORs. Configure Routing Service to bridge surgical domain data to the hospital domain.

**Depends on:** Phase 2 (Surgical Procedure)
**Can parallel with:** Phase 4 (Clinical Alerts)
**Spec coverage:** [hospital-dashboard.md](../spec/hospital-dashboard.md) (Procedure List, Vitals Overview, Alert Feed, Robot Status, GUI Threading), [common-behaviors.md](../spec/common-behaviors.md) (Routing Service)

---

## Step 3.1 — Routing Service Configuration

### Routing Service Participant Topology

Routing Service must bridge topics that span all three Procedure-domain tags
(`control`, `clinical`, `operational`) into the Hospital domain. Because a
DomainParticipant can have at most one domain tag (see
[system-architecture.md — Domain Tag Participant Model](../vision/system-architecture.md)),
Routing Service requires **four DomainParticipants**:

| Participant Name (XML) | Domain | Domain Tag | Role |
|------------------------|--------|------------|------|
| `RS::ProcedureControl` | 10 | `control` | Input — reads `RobotState` |
| `RS::ProcedureClinical` | 10 | `clinical` | Input — reads `PatientVitals`, `AlarmMessages`, `DeviceTelemetry` |
| `RS::ProcedureOperational` | 10 | `operational` | Input — reads `ProcedureStatus`, `ProcedureContext` |
| `RS::Hospital` | 11 | — | Output — writes all bridged topics |

All four participants are defined in the Routing Service XML configuration
file. Each Procedure-side participant references a distinct participant QoS
profile that sets the appropriate `<domain_tag>` (e.g.,
`Participant::ProcedureControl`). The Hospital-side participant has no domain
tag.

### Work

- Author Routing Service XML configuration for bridging:
  - Procedure domain → Hospital domain: `ProcedureStatus`, `ProcedureContext`, `PatientVitals`, `AlarmMessages`, `DeviceTelemetry`

> **Note:** `DeviceTelemetry` is bridged to the Hospital domain for future dashboard
> consumption (device status panels) and potential ClinicalAlerts integration. V1 dashboard does not
> display device telemetry directly — it is available on the Hospital domain for later
> phases or custom subscribers.
  - Procedure domain (`control` tag) → Hospital domain: `RobotState` (read-only)
- Configure separate sessions per traffic class (StatusSession, StreamingSession)
- Configure Routing Service partition handling per [system-architecture.md](../vision/system-architecture.md): input side uses wildcard partition `room/*/procedure/*`; output side preserves source partition so Hospital domain consumers see the same partition strings
- Add Routing Service container to `docker-compose.yml` on both `surgical-net` and `hospital-net` (dual-homed)
- Verify data flows from surgical containers to hospital network

### Test Gate (spec: common-behaviors.md — Routing Service)

- [ ] Routing Service bridges configured topics from the Procedure domain to the Hospital domain
- [ ] Unconfigured topics (e.g., `CameraFrame`) do NOT appear on the Hospital domain
- [ ] Data integrity preserved across bridge (values match)
- [ ] Robot state from the Procedure domain (`control` tag) appears on the Hospital domain (read-only)

---

## Step 3.2 — Dashboard Application Skeleton

### Work

- Create PySide6 application skeleton in `modules/hospital-dashboard/`
- Load shared GUI theme: apply `resources/styles/medtech.qss`, register bundled fonts, display RTI logo in header bar (see `vision/technology.md` GUI Design Standard)
- Implement DDS worker thread:
  - Creates DomainParticipant on the Hospital domain
  - QoS is loaded automatically via the default QosProvider (`NDDS_QOS_PROFILES`)
  - Uses QtAsyncio for data reception (never block the main/UI thread)
  - Emits Qt signals with normalized data for UI consumption
- Implement main window layout:
  - Procedure list panel (left)
  - Detail panel (right) — vitals, alerts, robot status for selected procedure
  - Alert feed panel (bottom)
- Verify UI launches, DDS thread starts, no data yet (placeholder displays)

### Test Gate

- [ ] Application launches without errors
- [ ] DDS participant is created on the Hospital domain with correct QoS
- [ ] UI renders placeholder layout with all panels visible
- [ ] DDS worker thread does not block the Qt main thread

---

## Step 3.3 — Procedure List View

### Work

- Subscribe to `ProcedureStatus` (bridged from the Procedure domain via Routing Service — same IDL type `Surgery::ProcedureStatus` on both domains)
- Populate procedure list widget with real-time data
- Auto-add new procedures as they are discovered
- Status indicators (color-coded): in-progress, completing, alert

### Test Gate (spec: hospital-dashboard.md — Procedure List)

- [ ] Dashboard displays all active procedures
- [ ] New procedure appears automatically when a new surgical instance starts
- [ ] Completed procedure status is updated in display

---

## Step 3.4 — Vitals Overview

### Work

- Subscribe to patient vitals data (bridged to the Hospital domain)
- Display summarized vitals per procedure (HR, SpO2, BP)
- Color-code vitals by severity thresholds
- Support late-joining: dashboard shows vitals immediately on startup

### Test Gate (spec: hospital-dashboard.md — Vitals Overview)

- [ ] Summarized vitals shown per procedure
- [ ] Vitals are color-coded by severity (normal/warning/critical)
- [ ] Dashboard receives vitals on startup via durability

---

## Step 3.5 — Alert Feed

### Work

- Subscribe to `ClinicalAlert` on the Hospital domain
- Display unified alert feed across all ORs
- Implement filtering: by severity, by room
- New alerts appear in real-time with visual distinction

### Test Gate (spec: hospital-dashboard.md — Alert Feed)

- [ ] Alerts from all ORs appear in unified feed
- [ ] Feed is filterable by severity
- [ ] Feed is filterable by room
- [ ] New alerts appear within 2 seconds with visual highlight

---

## Step 3.6 — Robot Status Display

### Work

- Subscribe to `RobotState` (bridged from the Procedure domain)
- Display robot status per OR with color-coded indicators
- Detect E-STOP and disconnection (liveliness lost)

### Test Gate (spec: hospital-dashboard.md — Robot Status)

- [ ] Robot state displayed per OR with correct mode indicator
- [ ] Emergency stop is prominently displayed (red, flashing)
- [ ] Robot disconnect detected via liveliness (gray indicator)

---

## Step 3.6b — Resource Panel

### Work

- Create a resource status simulator service (`services/resource-simulator/`) on the Hospital domain that publishes `ResourceAvailability` samples for ORs, beds, equipment, and staff with `State` pattern QoS (RELIABLE, TRANSIENT_LOCAL, KEEP_LAST 1)
- Subscribe to `ResourceAvailability` in the dashboard
- Display a resource panel showing availability by kind, name, location, and status
- Support late-joining: dashboard shows current resource state on startup via TRANSIENT_LOCAL durability
- Add resource simulator container to `docker-compose.yml` on `hospital-net`

### Test Gate (spec: hospital-dashboard.md — Resource Panel)

- [ ] Dashboard displays current resource availability
- [ ] Resource availability updates in real-time when simulator publishes changes
- [ ] Dashboard receives resource state on startup via durability

---

## Step 3.7 — Content Filtering & Detail View

### Work

- Implement content-filtered topic for per-room drill-down
- When user selects a procedure, create filtered subscription for that patient
- Verify filter reduces processing to only the selected patient

### Test Gate (spec: hospital-dashboard.md — GUI Threading)

- [ ] DDS data processing does not block UI (burst test)
- [ ] Content-filtered topic delivers only matching patient data

---

## Step 3.8 — Module README & Documentation Compliance

### Work

- Author `modules/hospital-dashboard/README.md` following all seven required sections per [vision/documentation.md](../vision/documentation.md)
- Author `services/routing/README.md` following the same structure (Routing Service is first deployed in this phase)
- Verify both READMEs pass `markdownlint` and the section-order lint script

### Test Gate (spec: documentation.md)

- [ ] `markdownlint modules/hospital-dashboard/README.md services/routing/README.md` — zero errors
- [ ] `python tests/lint/check_readme_sections.py` — all required sections present and in order
- [ ] Architecture sections document all DDS entities and threading model

---

## Step 3.9 — Full E2E Integration

### Work

- Run full Docker Compose environment: 2+ surgical instances + Routing Service + Dashboard
- Verify all dashboard features with live simulated data
- Run complete hospital-dashboard.md spec suite

### Test Gate

- [ ] All hospital-dashboard.md spec scenarios pass in Docker Compose environment
- [ ] Dashboard operates correctly with 2+ concurrent surgical instances

---

## Step 3.10 — Performance Baseline Recording

### Work

- Run the performance benchmark harness with the full Phase 3 Docker Compose environment (2 surgical instances + Routing Service + Dashboard + observability stack): `python tests/performance/benchmark.py --record --phase phase-3`
- Compare against the Phase 2 baseline — verify no regressions from adding Routing Service and the Dashboard
- Routing Service latency (L5) and Hospital domain throughput metrics are now meaningful for the first time
- If any metric regresses beyond the defined threshold, investigate before recording the new baseline
- Commit `tests/performance/baselines/phase-3.json` alongside the Phase 3 completion commit

### Test Gate (spec: performance-baseline.md — Regression Detection, Phase Gate Integration)

- [ ] Benchmark harness runs successfully with the full Phase 3 environment
- [ ] All Tier 1 and Tier 2 metrics are within regression thresholds of the Phase 2 baseline (or are NEW)
- [ ] Routing Service latency (L5) is collected and has a valid value
- [ ] Baseline file `tests/performance/baselines/phase-3.json` is produced and committed
