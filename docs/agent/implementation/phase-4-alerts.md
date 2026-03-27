# Phase 4: Clinical Alerts & Decision Support

**Goal:** Implement the Clinical Decision Support (ClinicalAlerts module) engine that subscribes to patient vitals and procedure context via Routing Service, computes risk scores, generates clinical alerts, and publishes results on the hospital domain.

**Depends on:** Phase 5 (Procedure Orchestration), Phase 3 Step 3.1 (Routing Service), [revision-dds-consistency.md](revision-dds-consistency.md)
**Can parallel with:** Phase 3 Steps 3.2–3.8 (Dashboard GUI)
**Spec coverage:** [clinical-alerts.md](../spec/clinical-alerts.md) (Risk Scoring, Alert Generation, Cross-Domain Subscription, Configuration), [common-behaviors.md](../spec/common-behaviors.md) (DDS Consistency Compliance)

> **DDS Consistency:** All steps in this phase must follow the application
> architecture pattern in [vision/dds-consistency.md §3](../vision/dds-consistency.md),
> use generated entity name constants from `app_names.idl`, and pass the
> [new module checklist](../vision/dds-consistency.md) (§9).

> **Parallelism note:** Steps 4.1–4.3 (ClinicalAlerts engine skeleton, risk scoring, alert generation)
> do not require Routing Service and can proceed independently of Phase 3 Step 3.1.
> Step 4.4 onward requires Phase 3 Step 3.1 to be complete (Routing Service running and
> bridging Procedure → Hospital domain topics).

---

## Step 4.1 — ClinicalAlerts Engine Skeleton

### Work

- Create ClinicalAlerts engine application (Python) in `modules/clinical-alerts/`
- Implement DomainParticipant on the Hospital domain
- QoS is loaded automatically via the default QosProvider (`NDDS_QOS_PROFILES`)
- Subscribe to `PatientVitals` and `ProcedureContext` (bridged from the Procedure domain via Routing Service)
- Publish `RiskScore` and `ClinicalAlert` on the Hospital domain
- Configuration loading: read risk thresholds and alert rules from config file (YAML or JSON)

### Test Gate

- [ ] ClinicalAlerts engine starts and creates DDS participant on the Hospital domain
- [ ] Engine subscribes to vitals and procedure context
- [ ] Engine creates publishers for `RiskScore` and `ClinicalAlert`
- [ ] Configuration file is loaded and thresholds are applied

---

## Step 4.2 — Risk Scoring Logic

### Work

- Implement pluggable risk scoring framework
  - Each risk model (hemorrhage, sepsis, etc.) is a configurable scoring function
  - Models consume vitals and produce a score (0.0–1.0), confidence, and rationale
- Implement the V1 hemorrhage risk model per [spec/clinical-alerts.md](../spec/clinical-alerts.md):
  - Formula: `score = 0.4 * hr_norm + 0.6 * sbp_norm` (see spec Summary of Concrete Requirements for normalization)
  - The model must be deterministic: same inputs → same score
  - Weights and normalization ranges are loaded from the configuration file (not hardcoded)
- Publish `RiskScore` with `State` pattern QoS (TRANSIENT_LOCAL for late joiners)

### Test Gate (spec: clinical-alerts.md — Risk Scoring)

- [ ] Risk score is computed from vitals
- [ ] Risk score updates when vitals change
- [ ] Risk score is computed independently per patient
- [ ] Risk score is durable for late-joining dashboards

---

## Step 4.3 — Alert Generation Logic

### Work

- Implement alert generation rules:
  - Threshold-based: vital sign exceeds configured limit → alert
  - Risk-based: risk score exceeds configured threshold → alert
- Implement deduplication: no duplicate alerts for sustained conditions
- Implement alert resolution: alerts clear when condition resolves
- Publish `ClinicalAlert` with `State` pattern QoS

### Test Gate (spec: clinical-alerts.md — Alert Generation)

- [ ] Alert generated when risk exceeds threshold
- [ ] Alert generated on vital sign threshold violation
- [ ] No duplicate alerts for sustained condition
- [ ] Alert clears when condition resolves

---

## Step 4.4 — Cross-Domain Subscription

### Work

- Verify ClinicalAlerts engine receives vitals and context via Routing Service
- Implement content-filtered topic for patient-set narrowing
- Verify end-to-end flow: bedside monitor → Procedure domain → Routing Service → Hospital domain → ClinicalAlerts engine

### Test Gate (spec: clinical-alerts.md — Cross-Domain Subscription)

- [ ] ClinicalAlerts engine receives vitals via Routing Service
- [ ] ClinicalAlerts engine receives procedure context for patient correlation
- [ ] Content filter delivers only configured patient subset

---

## Step 4.5 — Configuration

### Work

- Implement configurable thresholds for risk models and alert rules
- Config file (YAML or JSON) with documented schema
- Verify different configurations produce different alert behavior

### Test Gate (spec: clinical-alerts.md — Configuration)

- [ ] Risk model thresholds are configurable
- [ ] Alert rules are configurable
- [ ] Changed thresholds produce correct alert behavior changes

---

## Step 4.6 — Module README & Documentation Compliance

### Work

- Author `modules/clinical-alerts/README.md` following all seven required sections per [vision/documentation.md](../vision/documentation.md)
- Verify the README passes `markdownlint` and the section-order lint script

### Test Gate (spec: documentation.md)

- [ ] `markdownlint modules/clinical-alerts/README.md` — zero errors
- [ ] `python tests/lint/check_readme_sections.py` — all required sections present and in order
- [ ] Architecture section documents all DDS entities and threading model

---

## Step 4.7 — Full E2E Integration

### Work

- Run full Docker Compose: surgical instances + Routing Service + ClinicalAlerts engine + Dashboard
- Verify ClinicalAlerts engine alerts appear on the hospital dashboard alert feed
- Verify risk scores appear in dashboard vitals detail view
- Run complete clinical-alerts.md spec suite

### Test Gate

- [ ] All clinical-alerts.md spec scenarios pass in Docker Compose environment
- [ ] ClinicalAlerts engine alerts are visible on hospital dashboard
- [ ] Risk scores are visible on hospital dashboard
- [ ] System operates correctly with 2+ concurrent surgical instances

---

## Step 4.8 — Performance Baseline Recording

### Work

- Run the performance benchmark harness with the complete V1.0.0 Docker Compose environment (2 surgical instances + Routing Service + Dashboard + ClinicalAlerts engine + observability stack): `python tests/performance/benchmark.py --record --phase phase-4`
- Compare against the Phase 3 baseline — verify no regressions from adding the ClinicalAlerts engine
- The ClinicalAlerts engine adds Hospital domain subscribers and publishers (`RiskScore`, `ClinicalAlert`); verify participant count and endpoint count changes are reflected
- If `R1` or `R2` differ from Phase 3 baseline (expected — new participants), verify the change is justified and record the updated baseline
- Commit `tests/performance/baselines/phase-4.json` alongside the Phase 4 completion commit
- Also record the V1.0.0 release baseline: `python tests/performance/benchmark.py --record --phase v1.0.0`
- Commit `tests/performance/baselines/v1.0.0.json` alongside the V1.0.0 release tag

### Test Gate (spec: performance-baseline.md — Regression Detection, Phase Gate Integration)

- [ ] Benchmark runs successfully with the complete V1.0.0 environment
- [ ] All Tier 1 and Tier 2 metrics are within regression thresholds of the Phase 3 baseline (or are justified NEW/changed)
- [ ] Tier 3 resource metrics reflect expected participant/endpoint count changes from ClinicalAlerts engine addition
- [ ] `T6` (deadline missed) = 0 in the complete V1.0.0 environment
- [ ] Baseline files `phase-4.json` and `v1.0.0.json` are produced and committed
