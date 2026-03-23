# Spec: Clinical Alerts & Decision Support Module

Behavioral specifications for the Clinical Decision Support (ClinicalAlerts module) engine that subscribes to patient vitals and procedure context, computes risk scores, and publishes clinical alerts.

The ClinicalAlerts engine subscribes to Procedure domain data via Routing Service and publishes results on the Hospital domain.

---

## Summary of Concrete Requirements

| Requirement | Value |
|-------------|-------|
| Hemorrhage risk CRITICAL alert threshold | ≥ 0.7 (score range 0.0–1.0) |
| HR CRITICAL direct alert threshold | > 150 bpm |
| Risk score publication latency | ≤ 500 ms after receiving the triggering vitals sample |
| Duplicate alert suppression | No re-alert for the same condition at the same severity level |
| Alert deduplication scope | Per patient, per condition type |
| `RiskScore` durability | TRANSIENT_LOCAL — late-joining dashboards receive current scores |
| ClinicalAlerts engine initialization — participants matched and first data received | ≤ 15 s from process start on `hospital-net` |
| ClinicalAlerts engine restart re-integration | ≤ 15 s from restart to resuming risk score publication |
| Routing Service unavailability | ClinicalAlerts engine continues running; no crash; resumes scoring when RS restarts |
| Stale RiskScore identification | Consumers compare publication timestamp to current time |
| Hemorrhage risk model | Deterministic: given the same vitals input, always produces the same score |
| Hemorrhage risk — HR weight | 0.4 (normalized: (HR − 60) / (200 − 60), clamped 0–1) |
| Hemorrhage risk — systolic BP weight | 0.6 (normalized: (120 − SBP) / (120 − 40), clamped 0–1; higher blood pressure indicates lower hemorrhage risk — values above 120 mmHg clamp to 0 contribution because hemorrhage is a blood-loss event and hypertension is not a contributing factor) |
| Hemorrhage risk score formula | `score = 0.4 * hr_norm + 0.6 * sbp_norm`, clamped to [0.0, 1.0] |

*This table must be updated whenever a concrete value in the scenarios below is added or changed.*

---

## Risk Scoring

### Scenario: Risk score is computed from vitals `@integration`

**Given** the ClinicalAlerts engine is subscribed to `PatientVitals` on the Hospital domain (bridged from the Procedure domain)
**And** the engine has a configured risk model (e.g., hemorrhage risk)
**When** a `PatientVitals` sample is received for a patient
**Then** the engine computes a risk score and publishes a `RiskScore` sample within 500 ms of receiving the triggering sample
**And** the `RiskScore` sample contains patient ID, score kind, score value, confidence, and rationale

### Scenario: Risk score updates when vitals change `@integration`

**Given** the ClinicalAlerts engine has published a hemorrhage risk score of 0.3 for a patient
**When** a new `PatientVitals` sample indicates a significant drop in systolic BP
**Then** the engine publishes an updated `RiskScore` with an increased hemorrhage risk value
**And** the rationale includes the contributing vital sign changes

### Scenario: Risk score is computed per patient `@integration` `@filtering`

**Given** the ClinicalAlerts engine is processing vitals for patients in OR-1 and OR-3
**When** vitals arrive for both patients
**Then** independent `RiskScore` samples are published keyed by each patient's ID
**And** the score for one patient does not influence the score for another

### Scenario: Risk score is durable for late-joining dashboards `@integration` `@durability`

**Given** the ClinicalAlerts engine has published `RiskScore` with TRANSIENT_LOCAL durability
**When** the hospital dashboard joins the Hospital domain after scores have been computed
**Then** the dashboard immediately receives the most recent `RiskScore` for each patient

### Scenario: Risk score is deterministic given same inputs `@unit`

**Given** the hemorrhage risk model with weights HR=0.4, SBP=0.6
**When** the model receives vitals with HR=130 and systolic BP=80
**Then** the score is computed as `0.4 * ((130-60)/(200-60)) + 0.6 * ((120-80)/(120-40))` = 0.4 * 0.5 + 0.6 * 0.5 = 0.5
**And** repeating the computation with the same inputs produces the identical score

---

## Alert Generation

### Scenario: Alert is generated when risk exceeds threshold `@integration`

**Given** the ClinicalAlerts engine has configured alert threshold: hemorrhage risk ≥ 0.7 = CRITICAL
**When** a computed risk score meets or exceeds the threshold
**Then** a `ClinicalAlert` sample is published on the Hospital domain
**And** the alert contains severity CRITICAL, category CLINICAL, the triggering patient ID, and a human-readable message

### Scenario: Alert is generated on vital sign threshold violation `@unit`

**Given** the ClinicalAlerts engine has direct vital sign alert rule: HR > 150 bpm = CRITICAL
**When** a `PatientVitals` sample contains HR = 165 bpm
**Then** a `ClinicalAlert` with severity CRITICAL is published
**And** the alert message identifies the specific vital sign and value

### Scenario: No duplicate alerts for sustained condition `@integration`

**Given** a CRITICAL alert has been published for patient A's hemorrhage risk
**When** subsequent vitals samples continue to show elevated risk at the same level
**Then** the ClinicalAlerts engine does not publish duplicate alerts for the same condition
**And** a new alert is only published if severity changes or a distinct condition is detected

### Scenario: Alert clears when condition resolves `@integration`

**Given** a CRITICAL hemorrhage risk alert is active for a patient
**When** the patient's vitals return to safe ranges and the risk score drops below threshold
**Then** the ClinicalAlerts engine publishes an updated `ClinicalAlert` indicating resolution
**And** the alert severity is downgraded or the alert transitions to an INFO/resolved state

---

## Cross-Domain Subscription

### Scenario: ClinicalAlerts engine receives vitals via Routing Service `@e2e` `@routing`

**Given** the ClinicalAlerts engine subscribes to vitals on the Hospital domain
**And** Routing Service bridges `PatientVitals` from the Procedure domain to the Hospital domain
**When** a bedside monitor publishes vitals on the Procedure domain
**Then** the ClinicalAlerts engine receives the vitals sample on the Hospital domain

### Scenario: ClinicalAlerts engine receives procedure context for patient correlation `@e2e` `@routing`

**Given** the ClinicalAlerts engine subscribes to `ProcedureContext` on the Hospital domain
**And** Routing Service bridges it from the Procedure domain
**When** a procedure starts and publishes its context
**Then** the ClinicalAlerts engine can correlate patient vitals with the procedure and room

### Scenario: ClinicalAlerts engine uses content filter for subscribed patient set `@integration` `@filtering`

**Given** the ClinicalAlerts engine is configured to monitor a specific subset of patients
**When** the engine creates a content-filtered topic on `PatientVitals` filtering by `patient.id`
**Then** only vitals for the configured patient IDs are delivered to the reader
**And** other patients' vitals do not consume processing resources in the ClinicalAlerts engine

---

## Configuration

### Scenario: Risk model thresholds are configurable `@unit`

**Given** the ClinicalAlerts engine reads risk thresholds from a configuration file
**When** the configuration specifies hemorrhage_risk_critical_threshold = 0.8
**Then** the engine uses 0.8 as the critical threshold for hemorrhage alert generation

### Scenario: Alert rules are configurable `@unit`

**Given** the ClinicalAlerts engine reads vital sign alert rules from a configuration file
**When** the configuration specifies HR critical threshold = 160 (instead of default 150)
**Then** a CRITICAL HR alert is generated only when HR > 160

---

## System Initialization

### Scenario: ClinicalAlerts engine reaches operational state within time budget `@integration` `@performance`

**Given** the Routing Service bridge and ClinicalAlerts engine are started in sequence on `hospital-net`
**When** the ClinicalAlerts engine process starts
**Then** all DomainParticipant endpoints have matched (including Routing Service as the vitals source) within 15 s
**And** the ClinicalAlerts engine receives its first bridged `PatientVitals` sample within 15 s of start
**And** TRANSIENT_LOCAL state (`ProcedureContext`, existing `RiskScore` instances) is delivered within the same 15 s window

### Scenario: Restarted ClinicalAlerts engine re-integrates within time budget `@integration` `@performance`

**Given** the ClinicalAlerts engine is running and actively computing risk scores
**When** the ClinicalAlerts engine process is stopped and restarted
**Then** the restarted engine has re-matched all expected endpoints within 15 s of restart
**And** resumes publishing `RiskScore` samples within 15 s of restart

---

## Degraded Mode

### Scenario: ClinicalAlerts engine handles Routing Service unavailability `@e2e`

**Given** the ClinicalAlerts engine is running and receiving vitals via Routing Service
**When** Routing Service is stopped
**Then** the ClinicalAlerts engine stops receiving new vitals
**And** the engine does not crash or enter an error state
**And** previously published `RiskScore` samples remain available via TRANSIENT_LOCAL durability
**And** when Routing Service restarts, the ClinicalAlerts engine resumes receiving vitals and publishing updated scores within the initialization time budget

### Scenario: Stale risk scores are identifiable on ClinicalAlerts engine restart `@integration` `@durability`

**Given** the ClinicalAlerts engine has published `RiskScore` samples with TRANSIENT_LOCAL durability
**When** the ClinicalAlerts engine is stopped and a dashboard joins the Hospital domain
**Then** the dashboard receives the last known `RiskScore` samples via durability
**And** the samples carry their original publication timestamps
**And** the consumer can distinguish stale scores from fresh ones by comparing the timestamp to the current time
