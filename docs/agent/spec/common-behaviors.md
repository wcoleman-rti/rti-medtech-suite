# Spec: Common Behaviors

Cross-cutting behavioral specifications that apply to multiple modules. These test the DDS infrastructure, shared data model, partition isolation, durability, QoS enforcement, content filtering, and Routing Service bridging.

---

## Summary of Concrete Requirements

| Requirement | Value |
|-------------|-------|
| Domain partition format | `room/<room_id>/procedure/<procedure_id>` |
| `OperatorInput` deadline (DDS Deadline QoS) | 4 ms — enforced on both writer and reader; detects stream interruption per instance |
| `RobotState` deadline (DDS Deadline QoS) | 20 ms — enforced on both writer and reader; detects stream interruption per instance |
| `WaveformData` deadline (DDS Deadline QoS) | 40 ms — enforced on both writer and reader; detects stream interruption per instance |
| `CameraFrame` deadline (DDS Deadline QoS) | 66 ms — enforced on both writer and reader; detects stream interruption per instance |
| `PatientVitals` deadline (DDS Deadline QoS) | 2 s — enforced on both writer and reader; detects periodic-snapshot interruption per instance |
| `OperatorInput` lifespan (DDS Lifespan QoS) | 20 ms — samples older than 20 ms discarded before delivery |
| General liveliness lease duration | 2 s |
| `SafetyInterlock` liveliness lease duration | 500 ms — tighter lease for safety-critical write-on-change topic (via `Liveliness500ms` snippet) |
| Domain tag isolation | All three tag pairs (`control`/`clinical`, `control`/`operational`, `clinical`/`operational`) are mutually isolated; no cross-tag discovery or data exchange |
| Cross-domain data flow | Procedure domain data reaches Hospital domain only via Routing Service; no direct cross-domain discovery |
| Monitoring Library 2.0 | Enabled on every DomainParticipant via XML — no code-level opt-in |
| Observability stack independence | Removing the `observability` Docker Compose profile does not affect functional behavior |
| GUI shared stylesheet | `resources/styles/medtech.qss` loaded at startup by all PySide6 applications |
| GUI header bar | RTI Blue (`#004C97`) background, white text, RTI logo left-aligned |
| GUI severity color — Critical | Red `#D32F2F` |
| `@performance` test Docker tolerance multiplier | 10× (timing thresholds relaxed by factor of 10 in Docker simulation) |
| `@performance` test native tolerance multiplier | 1× (timing thresholds as specified) |
| Routing Service unavailability | Subscribers continue with cached data; no crash; auto-resume on RS restart |
| Cloud Discovery Service unavailability | Application starts successfully; logs WARNING; discovers when Cloud Discovery Service becomes available |
| Write-on-change publication model | Topics designated write-on-change publish only on state transitions; absence of samples is normal (liveliness detects writer health) |
| Continuous-stream publication model | Topics designated continuous-stream publish at their configured fixed rate regardless of value change |

*This table must be updated whenever a concrete value in the scenarios below is added or changed.*

---

## Discovery & Partition Isolation

### Scenario: Participants in the same partition discover each other `@integration` `@partition`

**Given** participant A and participant B are both on the Procedure domain with domain partition `room/OR-3/procedure/proc-001`
**When** both participants create publishers/subscribers for the same topic
**Then** their DataWriters and DataReaders match and can exchange data

### Scenario: Participants in different partitions do NOT discover each other `@integration` `@partition`

**Given** participant A is on the Procedure domain with partition `room/OR-3/procedure/proc-001`
**And** participant B is on the Procedure domain with partition `room/OR-5/procedure/proc-002`
**When** both create DataWriters/DataReaders for the same topic (e.g., `PatientVitals`)
**Then** their endpoints do not match
**And** no data is exchanged between them

### Scenario: Wildcard partition receives from all matching partitions `@integration` `@partition`

**Given** participant A is publishing on the Procedure domain with partition `room/OR-3/procedure/proc-001`
**And** participant B is publishing on the Procedure domain with partition `room/OR-5/procedure/proc-002`
**And** an aggregator participant uses partition `room/*`
**When** both participants publish `PatientVitals`
**Then** the aggregator receives vitals from both OR-3 and OR-5

### Scenario: Domain partition is assigned at startup from configuration `@integration` `@partition`

**Given** a surgical application is launched with environment variable `PARTITION=room/OR-7/procedure/proc-099`
**When** the application creates its DomainParticipant
**Then** the participant's domain partition is set to `room/OR-7/procedure/proc-099`
**And** the application operates identically to any other instance in any other room

---

## Domain Isolation

### Scenario: Procedure domain `control` tag is isolated from `clinical` tag `@integration` `@isolation`

**Given** a publisher on the Procedure domain with domain tag `control` publishing `RobotCommand`
**And** a subscriber on the Procedure domain with domain tag `clinical` subscribing to `RobotCommand`
**When** the publisher sends a sample
**Then** the subscriber does NOT receive it
**And** the two participants do not discover each other

### Scenario: Procedure domain `control` tag is isolated from `operational` tag `@integration` `@isolation`

**Given** a publisher on the Procedure domain with domain tag `control` publishing `RobotCommand`
**And** a subscriber on the Procedure domain with domain tag `operational` subscribing to `RobotCommand`
**When** the publisher sends a sample
**Then** the subscriber does NOT receive it
**And** the two participants do not discover each other

### Scenario: Procedure domain `clinical` tag is isolated from `operational` tag `@integration` `@isolation`

**Given** a publisher on the Procedure domain with domain tag `clinical` publishing `PatientVitals`
**And** a subscriber on the Procedure domain with domain tag `operational` subscribing to `PatientVitals`
**When** the publisher sends a sample
**Then** the subscriber does NOT receive it
**And** the two participants do not discover each other

### Scenario: Procedure domain and Hospital domain do not discover each other `@integration` `@isolation`

**Given** a participant on the Procedure domain (any tag) on `hospital-net`
**And** a participant on the Hospital domain on the same `hospital-net`
**When** both participants are running and sufficient discovery time has elapsed (≥ 15 s)
**Then** neither participant discovers the other's endpoints
**And** no data published on the Procedure domain is received by the Hospital domain participant (or vice versa) without Routing Service

### Scenario: Cross-domain data only flows through Routing Service `@e2e` `@routing`

**Given** a publisher on the Procedure domain publishing `PatientVitals`
**And** a subscriber on the Hospital domain subscribing to `PatientVitals`
**And** Routing Service is configured to bridge `PatientVitals` from the Procedure domain to the Hospital domain
**When** the publisher sends a vitals sample
**Then** the Hospital domain subscriber receives it via Routing Service
**And** without Routing Service running, the Hospital domain subscriber receives nothing

---

## QoS Enforcement

### Scenario: Deadline violation is detected when publisher stops `@integration`

**Given** a publisher sending `PatientVitals` with a 2-second deadline
**And** a subscriber expecting the same deadline
**When** the publisher stops publishing for more than 2 seconds
**Then** the subscriber's deadline missed status is triggered

### Scenario: Liveliness lost is detected when participant crashes `@integration`

**Given** a publisher with automatic liveliness and a 2-second lease duration
**And** a subscriber monitoring liveliness
**When** the publisher process terminates unexpectedly
**Then** the subscriber detects liveliness lost within the lease duration

### Scenario: Lifespan prevents delivery of stale data `@integration`

**Given** a publisher writing `OperatorInput` with a 20 ms lifespan
**When** a sample ages beyond 20 ms before being read
**Then** the sample is not delivered to the reader

### Scenario: KEEP_LAST 1 delivers only the most recent sample `@integration`

**Given** a publisher publishing `PatientVitals` at 10 Hz with KEEP_LAST 1 history
**When** the subscriber reads after 5 samples have been published
**Then** only the most recent sample is available

---

## Durability

### Scenario: TRANSIENT_LOCAL delivers historical data to late joiner `@integration` `@durability`

**Given** a publisher has published 5 samples of `ProcedureContext` with TRANSIENT_LOCAL durability and KEEP_LAST 1
**When** a new subscriber joins the same domain and partition
**Then** the subscriber immediately receives the most recent `ProcedureContext` sample (1 of 5)

### Scenario: VOLATILE does not deliver historical data `@integration` `@durability`

**Given** a publisher has published samples of `RobotCommand` with VOLATILE durability
**When** a new subscriber joins
**Then** the subscriber receives no historical samples
**And** only samples published after the subscriber joined are delivered

---

## Content Filtering

### Scenario: Content-filtered topic delivers only matching instances `@integration` `@filtering`

**Given** a publisher publishing `PatientVitals` for patient-001 and patient-002
**When** a subscriber creates a content-filtered topic with filter `patient.id = 'patient-001'`
**Then** the subscriber receives only vitals for patient-001
**And** vitals for patient-002 are not delivered

### Scenario: Content filter reduces network traffic `@integration` `@filtering`

**Given** a publisher on a remote host (Docker container) publishing for multiple patients
**When** a subscriber creates a writer-side content filter for a single patient
**Then** only matching samples traverse the network
**And** non-matching samples are filtered at the writer side

---

## Routing Service

### Scenario: Routing Service bridges configured topics `@e2e` `@routing`

**Given** Routing Service is configured to bridge `PatientVitals` and `AlarmMessages` from the Procedure domain to the Hospital domain
**When** publishers on the Procedure domain publish both topics
**Then** subscribers on the Hospital domain receive both topics

### Scenario: Routing Service does NOT bridge unconfigured topics `@e2e` `@routing`

**Given** Routing Service is configured to bridge only `PatientVitals` and `AlarmMessages`
**When** a publisher on the Procedure domain publishes `CameraFrame`
**Then** no `CameraFrame` data appears on the Hospital domain

> **Parameterization note:** `CameraFrame` is one example. This test must be parameterized
> across **all non-bridged Procedure domain topics**: `RobotCommand`, `SafetyInterlock`,
> `OperatorInput`, `WaveformData`, and `CameraFrame`. Of these, `RobotCommand` and
> `SafetyInterlock` are safety-critical — verifying they are not exposed on the Hospital
> domain is the highest-priority negative case.

### Scenario: Hospital domain subscribers handle Routing Service unavailability `@e2e` `@routing`

**Given** Routing Service is configured to bridge topics from the Procedure domain to the Hospital domain
**And** Hospital domain subscribers (dashboard, ClinicalAlerts engine) are running
**When** Routing Service is stopped
**Then** Hospital domain subscribers stop receiving new data from the Procedure domain

---

## Publication Model Compliance

### Scenario: Write-on-change topics detect writer health via liveliness, not data rate `@integration`

**Given** a publisher on a write-on-change topic (e.g., `DeviceTelemetry`) with TRANSIENT_LOCAL durability and automatic liveliness (2 s lease)
**And** the publisher's state is stable (no changes for 30 s)
**When** a subscriber checks the writer's health
**Then** the writer is reported as alive via liveliness (no `LIVELINESS_LOST` callback)
**And** the subscriber has not received new samples during the stable period (because no state change occurred)
**And** the subscriber's last received sample is the most recent state (from the last write-on-change publication)

### Scenario: Write-on-change publisher detects failure via liveliness loss `@integration`

**Given** a publisher on a write-on-change topic with automatic liveliness (2 s lease)
**And** a subscriber monitoring liveliness
**When** the publisher process is killed
**Then** the subscriber detects `LIVELINESS_LOST` within the 2 s lease period
**And** the subscriber distinguishes this from normal silence (no data because state is stable)

### Scenario: Continuous-stream topic absence triggers deadline miss `@integration`

**Given** a publisher on a continuous-stream topic (e.g., `OperatorInput`) with 4 ms Deadline QoS
**And** a subscriber expecting the same deadline
**When** the publisher stops publishing
**Then** the subscriber's deadline missed status is triggered within the deadline period
**And** this correctly indicates a stream interruption (unlike write-on-change, where silence is normal)
**And** previously received TRANSIENT_LOCAL data remains valid in subscriber caches
**And** no subscriber crashes or enters an error state
**And** when Routing Service is restarted, data flow resumes automatically within the initialization time budget

### Scenario: Routing Service preserves data integrity across bridge `@e2e` `@routing`

**Given** Routing Service bridges `PatientVitals` from the Procedure domain to the Hospital domain
**When** a vitals sample with specific values (HR=72, SpO2=98) is published on the Procedure domain
**Then** the sample received on the Hospital domain contains identical values (HR=72, SpO2=98)

---

## Exclusive Ownership / Failover

### Scenario: Higher-strength writer is preferred `@integration` `@failover`

**Given** writer A publishes `DeviceTelemetry` for device-001 with ownership strength 100
**And** writer B publishes `DeviceTelemetry` for device-001 with ownership strength 50
**When** both writers are alive
**Then** subscribers receive data only from writer A

### Scenario: Failover to backup on primary failure `@integration` `@failover`

**Given** writer A (strength 100) and writer B (strength 50) both publish `DeviceTelemetry` for device-001
**And** subscribers are currently receiving from writer A
**When** writer A's liveliness expires
**Then** subscribers automatically begin receiving from writer B
**And** no application-level intervention is required

### Scenario: Primary reclaims ownership on recovery `@integration` `@failover`

**Given** writer B (strength 50) has taken over after writer A (strength 100) failed
**When** writer A recovers and resumes publishing with strength 100
**Then** subscribers automatically switch back to receiving from writer A

---

## Service Degradation

### Scenario: Application starts without Cloud Discovery Service `@integration`

**Given** an application is configured with Cloud Discovery Service as its initial peer
**When** the application starts and Cloud Discovery Service is not running
**Then** the application starts successfully without crashing
**And** the application logs a WARNING indicating discovery service is unreachable
**And** when Cloud Discovery Service becomes available, discovery completes within the initialization time budget

---

## Observability

### Scenario: Monitoring Library 2.0 publishes telemetry for every participant `@integration` `@observability`

**Given** a DomainParticipant is created with the project QoS profile (Monitoring Library 2.0 enabled via XML)
**And** Collector Service is running on `hospital-net`
**When** the participant starts publishing or subscribing
**Then** Collector Service receives telemetry (metrics, entity status, discovery events) from that participant
**And** the telemetry appears in Prometheus within 30 seconds

### Scenario: Deadline-missed event is visible in Prometheus `@e2e` `@observability`

**Given** a subscriber expecting `PatientVitals` with a 2-second deadline
**And** the observability stack is running (`--profile observability`)
**When** the publisher stops for more than 2 seconds
**Then** a deadline-missed metric is recorded in Prometheus for that DataReader
**And** the Grafana system overview dashboard reflects the anomaly

### Scenario: Grafana dashboard displays system health overview `@e2e` `@observability`

**Given** the full Docker Compose environment is running with `--profile observability`
**And** multiple surgical instances and the Hospital Dashboard are active
**When** a user opens the Grafana system overview dashboard
**Then** per-participant metrics (matched endpoints, sample counts, latency) are visible
**And** user-category log events from the Connext Logging API appear in the Grafana Loki log panel (forwarded via Monitoring Library 2.0 and Collector Service)

### Scenario: Observability stack removal does not affect functional behavior `@e2e` `@observability`

**Given** the full Docker Compose environment is running without `--profile observability`
**When** all surgical, dashboard, and ClinicalAlerts applications are operating
**Then** all functional spec scenarios pass identically to when observability is enabled
**And** no errors are logged due to the absence of Collector Service

---

## Performance Test Environment Tolerance

### Scenario: Performance thresholds are relaxed in Docker simulation `@performance`

**Given** the test environment is detected as Docker (via `MEDTECH_ENV=docker` environment variable or container detection)
**When** a `@performance`-tagged test evaluates a timing threshold
**Then** the threshold is multiplied by a tolerance factor of 10×
**And** the test passes if the measured value is within the relaxed threshold
**And** the unrelaxed (native) threshold is logged for reference

The 10× multiplier applies to the following timing requirements and no others:

| Requirement | Native Threshold | Docker (10×) | Source |
|-------------|-----------------|--------------|--------|
| `OperatorInput` delivery deadline | 4 ms | 40 ms | surgical-procedure.md |
| `OperatorInput` lifespan (stale discard) | 20 ms | 200 ms | surgical-procedure.md |
| `RobotState` delivery deadline | 20 ms | 200 ms | surgical-procedure.md |
| `WaveformData` delivery deadline | 40 ms | 400 ms | surgical-procedure.md |
| `SafetyInterlock` response (robot → safe-stopped) | 40 ms | 400 ms | surgical-procedure.md |
| `SafetyInterlock` liveliness lease | 500 ms | 5 s | surgical-procedure.md |
| `CameraFrame` delivery deadline | 66 ms | 660 ms | surgical-procedure.md |
| `RobotState` publication period | 10 ms | 100 ms | surgical-procedure.md |
| `PatientVitals` deadline | 2 s | 20 s | surgical-procedure.md |
| Device gateway liveliness lease | 2 s | 20 s | surgical-procedure.md |
| Procedure system initialization (all matched + TRANSIENT_LOCAL) | 5 s | 50 s | surgical-procedure.md |
| Restarted component re-integration | 5 s | 50 s | surgical-procedure.md |
| Risk score publication latency | 500 ms | 5 s | clinical-alerts.md |
| ClinicalAlerts engine initialization (matched + first data) | 15 s | 150 s | clinical-alerts.md |
| Dashboard initialization (matched + state displayed) | 15 s | 150 s | hospital-dashboard.md |
| Alert feed display latency | 2 s | 20 s | hospital-dashboard.md |

Requirements **not** subject to the 10× multiplier:

- **`@benchmark` regression thresholds** (Tier 1 ≤ +20%, Tier 2 ≤ −10%, etc.) — these are relative to a recorded baseline, not absolute values. The baseline itself is recorded in the same environment, so the multiplier is already baked in. See [performance-baseline.md](performance-baseline.md).
- **Functional correctness checks** — e.g., "alarm clears when vital returns to normal", "late joiner receives TRANSIENT_LOCAL state". These are pass/fail with no timing element.
- **`OperatorInput` publication rate (500 Hz)**, **`RobotState` publication rate (100 Hz)**, **`WaveformData` publication rate (50 Hz)**, **`CameraFrame` publication rate (30 Hz)**, and **`PatientVitals` publication rate (1 Hz)** — the rate is a configuration input, not a measured outcome. The *deadline* on these rates is subject to the multiplier (see table above).

> **Rationale:** Docker simulation disables shared memory and routes all traffic through the
> Docker virtual network stack, introducing significantly higher latency than a dedicated
> surgical LAN. Timing requirements (e.g., 4 ms `OperatorInput` delivery, 40 ms interlock
> response) describe the production target. Docker CI must validate functional correctness
> and ordering — not bare-metal latency. The 10× multiplier prevents false failures in CI
> while preserving the production values as the documented requirement.

---

## GUI Design Standard Compliance

### Scenario: GUI application loads shared theme stylesheet `@gui`

**Given** a PySide6 GUI application (Hospital Dashboard or Digital Twin Display) is launched
**When** the application initializes its main window
**Then** the shared stylesheet `resources/styles/medtech.qss` is loaded and applied
**And** the window header bar uses RTI Blue (`#004C97`) background with white text

### Scenario: GUI application displays RTI logo in header `@gui`

**Given** a PySide6 GUI application is launched
**When** the main window is rendered
**Then** the RTI logo is visible in the header bar, left-aligned
**And** the logo asset is loaded from `resources/images/rti-logo.png` or `rti-logo.svg`

### Scenario: GUI application loads bundled fonts `@gui`

**Given** a PySide6 GUI application is launched
**When** the application registers fonts via `QFontDatabase`
**Then** Roboto Condensed, Montserrat, and Roboto Mono are available for widget rendering
**And** no system font dependency is required

### Scenario: Severity colors follow the semantic mapping `@gui`

**Given** a PySide6 GUI application displays a status indicator
**When** the status changes to Normal, Warning, Critical, Info, or Disconnected
**Then** the indicator uses the corresponding semantic color: Green (`#A4D65E`), Orange (`#ED8B00`), Red (`#D32F2F`), Light Blue (`#00B5E2`), or Light Gray (`#BBBCBC`) respectively
