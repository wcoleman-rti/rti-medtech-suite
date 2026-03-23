# Implementation

This directory contains the **phased implementation plan** for the medtech suite. Each phase file describes the work, its dependencies, the test gates that must pass before proceeding, and enough context to resume if a session is interrupted.

---

## Test Policy

These rules apply to all phases without exception:

1. **Every spec scenario has a test.** Implementation is not complete until its spec scenarios pass as automated tests.
2. **Tests are never deleted.** A test represents a behavioral contract. If it breaks, the code is wrong.
3. **Tests are never disabled.** No `@skip`, `DISABLED_`, `xfail`, or equivalent. A failing test blocks the phase.
4. **Fix the code, not the test.** If a test fails, the implementation is fixed to match the spec. If the *desired behavior* genuinely changes, the spec is updated first (with justification), then the test is updated to match the new spec.
5. **Tests run in CI and locally.** All tests must be runnable with a single command from the project root.
6. **Performance baselines are committed artifacts.** At the completion of each implementation phase, after all functional tests and quality gates pass, the implementing agent runs the performance benchmark harness and commits the resulting baseline file. A performance regression that exceeds the defined thresholds in [vision/performance-baseline.md](../vision/performance-baseline.md) blocks the phase, the same as a failing functional test.

---

## Phase Dependencies

Phases are grouped by release milestone. All phases within a milestone must be complete before that version can be cut. See [vision/versioning.md](../vision/versioning.md) for release criteria.

> **Implementation order:** Execute phases in **milestone order** — not strictly by
> phase number. The correct implementation sequence across milestones is:
> V1.0 phases (1–4) → V1.1 phases (Phase 6) → V2.0 phases (Phase 5, 7–12) →
> V3.0 phases (13–17). Phase 5 (Security) belongs to V2.0.0 and must not begin
> until Phase 6 (Recording & Replay, V1.1.0) is complete, despite its lower number.

```
── V1.0.0 ──────────────────────────────────────────────────────────────────

Phase 1: Foundation
    │
    ├──► Phase 2: Surgical Procedure
    │        │
    │        ├──► Phase 3: Hospital Dashboard
    │        │        │
    │        │        └── Step 3.1 (Routing Service) ──► Phase 4: Clinical Alerts & Decision Support
    │        │
    │        (Phase 4 depends on Phase 3 Step 3.1 for Routing Service;
    │         Phase 4 can proceed in parallel with Phase 3 Steps 3.2–3.8)

── V1.1.0 ──────────────────────────────────────────────────────────────────

Phase 6: Recording & Replay          (depends on: Phases 1–4)

── V2.0.0 ──────────────────────────────────────────────────────────────────

Phase 5: Security                    (depends on: Phases 1–4)
Phase 7: EHR Gateway                 (depends on: Phase 5)
Phase 8: LIS Gateway                 (depends on: Phase 5)
Phase 9: AIMS Gateway                (depends on: Phase 5)
Phase 10: OR Scheduling Gateway      (depends on: Phase 5)
Phase 11: Alarm Management Gateway   (depends on: Phase 5)
Phase 12: Device Gateway (bidir)     (depends on: Phase 5)

    (Phases 7–12 can proceed in parallel after Phase 5)

── V3.0.0 ──────────────────────────────────────────────────────────────────

Phase 13: Instrument Tracking        (depends on: Phase 7, Phase 12)
Phase 14: PACS / Imaging Gateway     (depends on: Phase 5)
Phase 15: Inter-OR / WAN Bridging    (depends on: Phases 1–5)
Phase 16: ClinicalAlerts High Availability      (depends on: Phase 4)
Phase 17: Cloud Command Center       (depends on: Phase 15)
```

*Phase files for V1.1 and beyond do not yet exist. They will be created when the corresponding milestone is approved for implementation. Each requires operator approval before authoring begins.*

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
| [phase-2-surgical.md](phase-2-surgical.md) | Surgical Procedure | Phase 1 | Robot sim, vitals sim (simulation model with scenario profiles), camera sim, procedure context, device telemetry (write-on-change), digital twin display, partition isolation, diagnostic tools (medtech-diag, partition-inspector) |
| [phase-3-dashboard.md](phase-3-dashboard.md) | Hospital Dashboard | Phase 2 | PySide6 GUI, Routing Service config, multi-OR aggregation, alert feed, robot status |
| [phase-4-alerts.md](phase-4-alerts.md) | Clinical Alerts & Decision Support | Phase 2, Phase 3 Step 3.1 | Risk scoring engine, alert generation, cross-domain subscription, configurable thresholds |

### V1.0.0 Release Gate

After all V1.0.0 phases (1–4) are complete, a **final regression gate** must pass before the V1.0.0 version is cut:

- [ ] Full test suite passes (`pytest tests/` — zero failures, zero skips, zero expected-failures)
- [ ] Full Docker Compose environment runs end-to-end: 2+ surgical instances + Routing Service + Dashboard + ClinicalAlerts engine
- [ ] All quality gates from [workflow.md](../workflow.md) Section 7 pass (build, install, lint, QoS checks, domain ID checks, logging checks)
- [ ] All spec scenarios from all four phases pass simultaneously in the Docker Compose environment
- [ ] No open incidents in `docs/agent/incidents.md`
- [ ] All module/service READMEs pass markdownlint and section-order lint
- [ ] Performance benchmark passes against the Phase 3 baseline (or records the V1.0.0 baseline if this is the first complete run)
- [ ] `tests/performance/baselines/v1.0.0.json` is committed

### V1.1.0 Phases (planned)

| Phase | Depends On | Key Deliverables |
|-------|------------|------------------|
| Phase 6: Recording & Replay *(file not yet authored)* | Phases 1–4 | RTI Recording Service config, RTI Replay Service config, `@recording`/`@replay` test coverage |

> **Prerequisite:** Phase 6 requires `spec/recording-replay.md` to be authored and operator-approved before implementation begins. The spec file does not yet exist. An implementing agent must draft the spec (covering `@recording` and `@replay` scenarios) and obtain approval before starting Phase 6 work.

### V2.0.0 Phases (planned)

| Phase | Depends On | Key Deliverables |
|-------|------------|------------------|
| [phase-5-security.md](phase-5-security.md) | Phases 1–4 | Connext Security Plugins, governance docs, participant certs, permissions, CRL, PSK, origin authentication |
| Phase 7: EHR Gateway *(file not yet authored)* | Phase 5 | FHIR bridge sim, `ProcedureContext` seeding, procedure progression reporting |
| Phase 8: LIS Gateway *(file not yet authored)* | Phase 5 | `LabResult` topic, ClinicalAlerts integration for lab-triggered alerts |
| Phase 9: AIMS Gateway *(file not yet authored)* | Phase 5 | Multi-topic read-only subscriber, intraoperative record reconstruction |
| Phase 10: OR Scheduling Gateway *(file not yet authored)* | Phase 5 | Partition assignment and context seeding from schedule |
| Phase 11: Alarm Management Gateway *(file not yet authored)* | Phase 5 | Alert routing sink, decoupled subscriber pattern |
| Phase 12: Device Gateway (bidirectional) *(file not yet authored)* | Phase 5 | Pump/anesthesia command/control, exclusive ownership failover |

### V3.0.0 Phases (planned)

| Phase | Depends On | Key Deliverables |
|-------|------------|------------------|
| Phase 13: Instrument Tracking *(file not yet authored)* | Phases 7, 12 | Tool events, tray composition, TRANSIENT_LOCAL count boards |
| Phase 14: PACS / Imaging Gateway *(file not yet authored)* | Phase 5 | DICOM bridge sim, image metadata state, frame stream |
| Phase 15: Inter-OR / WAN Bridging *(file not yet authored)* | Phases 1–5 | Routing Service WAN config, inter-facility domain bridging |
| Phase 16: ClinicalAlerts High Availability *(file not yet authored)* | Phase 4 | Primary/backup ClinicalAlerts engine, Cloud Discovery Service HA, multi-segment discovery |
| Phase 17: Cloud Command Center *(file not yet authored)* | Phase 15 | Cloud/Enterprise domain, WAN Routing Service (Real-Time WAN Transport — `UDPv4_WAN`), Connext Security Plugins on WAN, Cloud Discovery Service cross-site, Command Center dashboard, facility-level partitions, `FacilityStatus`/`AggregatedAlerts`/`ResourceUtilization`/`OperationalKPIs` topics |
