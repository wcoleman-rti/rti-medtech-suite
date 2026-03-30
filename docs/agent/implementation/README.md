# Implementation

This directory contains the **phased implementation plan** for the medtech suite. Each phase file describes the work, its dependencies, the test gates that must pass before proceeding, and enough context to resume if a session is interrupted.

---

## Test Policy

These rules apply to all phases without exception:

1. **Every spec scenario has a test.** Implementation is not complete until its spec scenarios pass as automated tests.
2. **Tests are never deleted.** A test represents a behavioral contract. If it breaks, the code is wrong.
3. **Tests are never disabled.** No `@skip`, `DISABLED_`, `xfail`, or equivalent. A failing test blocks the phase.
4. **Fix the code, not the test.** If a test fails, the implementation is fixed to match the spec. If the *desired behavior* genuinely changes, the spec is updated first (with justification), then the test is updated to match the new spec.
5. **Tests run in CI and locally.** All tests must pass via a single command from the project root: `bash scripts/ci.sh`. This script is the authoritative quality gate sequence — see `docs/agent/workflow.md` Section 3 (Test Commands Reference) for the full command table.
6. **Performance baselines are committed artifacts.** At the completion of each implementation phase, after all functional tests and quality gates pass, the implementing agent runs the performance benchmark harness and commits the resulting baseline file. A performance regression that exceeds the defined thresholds in [vision/performance-baseline.md](../vision/performance-baseline.md) blocks the phase, the same as a failing functional test.
7. **Docker test execution.** Integration and E2E tests that run in Docker must use images built via the multi-stage Dockerfile (`docker/medtech-app.Dockerfile`), not host-mounted install trees. The `x-dev-volumes` pattern in `docker-compose.yml` is a local development convenience and must not be used in CI or as the basis for test results.
8. **Module acceptance tests.** Every phase that delivers a user-facing module or integrated system capability must include at least one `@acceptance` test that exercises the module's primary workflow end-to-end in Docker Compose. The test must: (a) start all required components, (b) execute the intended user workflow programmatically, (c) verify an observable outcome that proves the workflow completed, and (d) fail if any required component is absent or non-functional. Acceptance tests are distinct from spec scenario tests — they validate that the **composed module works**, not that individual behaviors are correct. A phase cannot be marked complete if its acceptance test is missing or failing.

---

## Phase Dependencies

Phases are grouped by release milestone. All phases within a milestone must be complete before that version can be cut. See [vision/versioning.md](../vision/versioning.md) for release criteria.

> **Implementation order:** Execute phases in **milestone order**, which now
> matches phase numbering: V1.0 phases (1–5) → V1.1 phase (6) →
> V1.2 phase (20) → V2.0 phases (7–14) → V2.1 phase (21) →
> V3.0 phases (15–19).

```
── V1.0.0 ──────────────────────────────────────────────────────────────────

Phase 1: Foundation
    │
    ├──► Revision: DDS Consistency Alignment (depends on Phase 1 + Phase 2 Steps 2.1–2.2)
    │
    ├──► Phase 2: Surgical Procedure (Steps 2.3+ depend on Revision)
    │        │
    │        └──► Phase 5: Procedure Orchestration + IDL Breaking Changes
    │                  (Foxglove translatability, Timestamp_t, ImageFormat enum)
    │                  Service interface, dual-mode services, Service Host,
    │                  Procedure Controller, Orchestration domain, DDS RPC
    │                  │
    │                  ├──► Phase 3: Hospital Dashboard
    │                  │        │    (services born as medtech::Service)
    │                  │        │
    │                  │        └── Step 3.1 (Routing Service) ──► Phase 4: Clinical Alerts
    │                  │
    │                  (Phase 4 depends on Phase 3 Step 3.1 for Routing Service;
    │                   Phase 4 can proceed in parallel with Phase 3 Steps 3.2–3.8)

── V1.1.0 ──────────────────────────────────────────────────────────────────

Phase 6: Recording & Replay          (depends on: Phases 1–5)
         + Foxglove Data Model Translatability (Tier 1)

── V1.2.0 ──────────────────────────────────────────────────────────────────

Phase 20: Dynamic Multi-Arm           (depends on: Phases 1–5)
          Orchestration

    (Phase 20 can proceed in parallel with Phase 6)

── V2.0.0 ──────────────────────────────────────────────────────────────────

Phase 7: Security                    (depends on: Phases 1–5)
Phase 8: EHR Gateway                 (depends on: Phase 7)
Phase 9: LIS Gateway                 (depends on: Phase 7)
Phase 10: AIMS Gateway               (depends on: Phase 7)
Phase 11: OR Scheduling Gateway      (depends on: Phase 7)
Phase 12: Alarm Management Gateway   (depends on: Phase 7)
Phase 13: Device Gateway (bidir)     (depends on: Phase 7)
Phase 14: Foxglove Bridge            (depends on: Phase 6)

    (Phases 8–13 can proceed in parallel after Phase 7)
    (Phase 14 can proceed in parallel with Phases 7–13)

── V2.1.0 ──────────────────────────────────────────────────────────────────

Phase 21: Teleoperation /             (depends on: Phases 1–5, Phase 7)
          Remote Operator

── V3.0.0 ──────────────────────────────────────────────────────────────────

Phase 15: Instrument Tracking        (depends on: Phase 8, Phase 13)
Phase 16: PACS / Imaging Gateway     (depends on: Phase 6)
Phase 17: Inter-OR / WAN Bridging    (depends on: Phases 1–7)
Phase 18: ClinicalAlerts High Availability      (depends on: Phase 4)
Phase 19: Cloud Command Center       (depends on: Phase 17)
```

*Phase files for V1.1 and beyond do not yet exist unless linked above or in the Phase Files tables below. They will be created when the corresponding milestone is approved for implementation. Each requires operator approval before authoring begins.*

---

## Resumption Guide

If an implementation session is interrupted, use this checklist to resume:

1. Read the **current phase file** to identify where work stopped
2. Run the **test suite** — passing tests indicate completed work; failing tests indicate in-progress work
3. Check **git status/log** for uncommitted changes
4. Continue from the first failing or unimplemented test gate in the current phase

---

## Phase Files

### V1.0.0 Phases (current)

| File | Phase | Depends On | Key Deliverables |
|------|-------|------------|------------------|
| [phase-1-foundation.md](phase-1-foundation.md) | Foundation | — | CMake build, IDL types, QoS profiles, Docker infra, Observability stack, Python venv, test harness, shared GUI bootstrap (`medtech_gui`), Logging initialization utility (Connext Logging API + Monitoring Library 2.0 forwarding), CI pipeline, performance benchmark harness, DDS design review (rti-chatbot-mcp), QoS compatibility checker, tool scaffolding |
| [revision-dds-consistency.md](revision-dds-consistency.md) | DDS Consistency Alignment | Phase 1, Phase 2 Steps 2.1–2.2 | `app_names.idl` entity name constants, `dds_init.py` relocation, retrofit generated constants, architecture audit, expanded CI anti-pattern checks, `@consistency` spec tests |
| [phase-2-surgical.md](phase-2-surgical.md) | Surgical Procedure | Phase 1, Revision | Robot sim, vitals sim (simulation model with scenario profiles), camera sim, procedure context, device telemetry (write-on-change), digital twin display, partition isolation, diagnostic tools (medtech-diag, partition-inspector) |
| [revision-docker-build-workflow.md](revision-docker-build-workflow.md) | Docker Build Workflow | Phase 1 | Multi-stage Dockerfile, in-container compilation, compose update, CI Docker gates, doc guardrails |
| [phase-5-orchestration.md](phase-5-orchestration.md) | Procedure Orchestration | Phase 2 | IDL breaking changes (Foxglove translatability: `Timestamp_t`, `ImageFormat` enum, `CameraFrame` streamlined), `medtech::Service` interface (C++ / Python ABC), dual-mode participant, Service Host framework (C++ and Python), Procedure Controller GUI (PySide6), Orchestration domain (Domain 15), `ServiceHostControl` DDS RPC, `HostCatalog` + `ServiceStatus` pub/sub, `@orchestration` test coverage |
| [phase-3-dashboard.md](phase-3-dashboard.md) | Hospital Dashboard | Phase 5 | PySide6 GUI, Routing Service config, multi-OR aggregation, alert feed, robot status — services implement `medtech::Service` |
| [phase-4-alerts.md](phase-4-alerts.md) | Clinical Alerts & Decision Support | Phase 5, Phase 3 Step 3.1 | Risk scoring engine, alert generation, cross-domain subscription, configurable thresholds — service implements `medtech::Service` |

> **Prerequisite:** Phase 5 spec file [spec/procedure-orchestration.md](../spec/procedure-orchestration.md) must be operator-approved before implementation begins.

### V1.0.0 Release Gate

After all V1.0.0 phases (1–5, plus 3–4) are complete, a **final regression gate** must pass before the V1.0.0 version is cut:

- [ ] Full test suite passes (`bash scripts/ci.sh`) — zero failures, zero skips, zero expected-failures
- [ ] Full Docker Compose environment runs end-to-end: 2+ surgical instances + Routing Service + Dashboard + ClinicalAlerts engine + Orchestration (Service Hosts + Procedure Controller)
- [ ] All quality gates from [workflow.md](../workflow.md) Section 7 pass (build, install, lint, QoS checks, domain ID checks, logging checks)
- [ ] All spec scenarios from all five phases pass simultaneously in the Docker Compose environment
- [ ] All `@orchestration` spec scenarios pass
- [ ] Procedure Controller discovers, starts, stops, and monitors services across all three Service Host types
- [ ] Orchestration domain is fully isolated from Procedure and Hospital domains
- [ ] No open incidents in `docs/agent/incidents.md`
- [ ] All module/service READMEs pass markdownlint and section-order lint
- [ ] Performance benchmark passes against the Phase 5 baseline
- [ ] `tests/performance/baselines/v1.0.0.json` is committed

### V1.1.0 Phases (planned)

| Phase | Depends On | Key Deliverables |
|-------|------------|------------------|
| Phase 6: Recording & Replay *(file not yet authored)* | Phases 1–5 | RTI Recording Service config, RTI Replay Service config, Foxglove data model translatability (Tier 1 — `RobotState` field updates, `Common::Quaternion`/`Vector3`/`Pose` helpers, `RobotFrameTransform` topic), `@recording`/`@replay` test coverage |

> **Prerequisite:** Phase 6 requires `spec/recording-replay.md` to be authored and operator-approved before implementation begins. The spec file does not yet exist.

### V1.2.0 Phases (planned)

| Phase | Depends On | Key Deliverables |
|-------|------------|------------------|
| Phase 20: Dynamic Multi-Arm Orchestration *(file not yet authored)* | Phases 1–5 | `RobotArmAssignment` topic (IDL, QoS), `ArmAssignmentState`/`TablePosition` enums, multi-arm table positioning, Procedure Controller `control`-tag participant expansion, digital twin multi-arm rendering, `@multi-arm` test coverage |

> **Prerequisite:** Phase 20 requires [spec/multi-arm-orchestration.md](../spec/multi-arm-orchestration.md) to be operator-approved before implementation begins.

### V2.0.0 Phases (planned)

| Phase | Depends On | Key Deliverables |
|-------|------------|------------------|
| [phase-7-security.md](phase-7-security.md) | Phases 1–5 | Connext Security Plugins, governance docs, participant certs, permissions, CRL, PSK, origin authentication |
| Phase 8: EHR Gateway *(file not yet authored)* | Phase 7 | FHIR bridge sim, `ProcedureContext` seeding, procedure progression reporting |
| Phase 9: LIS Gateway *(file not yet authored)* | Phase 7 | `LabResult` topic, ClinicalAlerts integration for lab-triggered alerts |
| Phase 10: AIMS Gateway *(file not yet authored)* | Phase 7 | Multi-topic read-only subscriber, intraoperative record reconstruction |
| Phase 11: OR Scheduling Gateway *(file not yet authored)* | Phase 7 | Partition assignment and context seeding from schedule |
| Phase 12: Alarm Management Gateway *(file not yet authored)* | Phase 7 | Alert routing sink, decoupled subscriber pattern |
| Phase 13: Device Gateway (bidirectional) *(file not yet authored)* | Phase 7 | Pump/anesthesia command/control, exclusive ownership failover |
| [phase-14-foxglove-bridge.md](phase-14-foxglove-bridge.md) | Phase 6 | Foxglove IDL compilation, Transformation plugin, WebSocket Adapter plugin, MCAP Storage plugin, Routing Service Foxglove routes, Recording Service MCAP config, `@foxglove` test coverage |

### V2.1.0 Phases (planned)

| Phase | Depends On | Key Deliverables |
|-------|------------|------------------|
| Phase 21: Teleoperation / Remote Operator *(file not yet authored)* | Phases 1–5, Phase 7 (Security) | `EXCLUSIVE_OWNERSHIP_QOS` on `OperatorInput`, ownership strength tiering via RS, safe-hold mode, ControlAuthority state machine, AUTOMATIC liveliness + DEADLINE failover, Routing Service control-tag bridge, `@teleop` test coverage |

> **Prerequisite:** Phase 21 requires V2.0 (Security, Phase 7) to be complete and [spec/teleoperation.md](../spec/teleoperation.md) to be operator-approved before implementation begins.

### V3.0.0 Phases (planned)

| Phase | Depends On | Key Deliverables |
|-------|------------|------------------|
| Phase 15: Instrument Tracking *(file not yet authored)* | Phases 8, 13 | Tool events, tray composition, TRANSIENT_LOCAL count boards |
| Phase 16: PACS / Imaging Gateway *(file not yet authored)* | Phase 6 | DICOM bridge sim, image metadata state, frame stream |
| Phase 17: Inter-OR / WAN Bridging *(file not yet authored)* | Phases 1–7 | Routing Service WAN config, inter-facility domain bridging |
| Phase 18: ClinicalAlerts High Availability *(file not yet authored)* | Phase 4 | Primary/backup ClinicalAlerts engine, Cloud Discovery Service HA, multi-segment discovery |
| Phase 19: Cloud Command Center *(file not yet authored)* | Phase 17 | Cloud/Enterprise domain, WAN Routing Service (Real-Time WAN Transport — `UDPv4_WAN`), Connext Security Plugins on WAN, Cloud Discovery Service cross-site, Command Center dashboard, facility-level partitions, `FacilityStatus`/`AggregatedAlerts`/`ResourceUtilization`/`OperationalKPIs` topics |
