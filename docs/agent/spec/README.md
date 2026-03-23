# Specifications

This directory contains **Given/When/Then (GWT) behavioral specifications** for every testable behavior in the medtech suite. Each spec file maps to a module or cross-cutting concern.

---

## Conventions

### GWT Format

Every scenario follows this structure:

```
### Scenario: <descriptive name>

**Given** <precondition(s)>
**When** <action or event>
**Then** <observable outcome(s)>
```

### Rules

1. **Every scenario becomes a test.** If a behavior is worth specifying, it is worth testing.
2. **Scenarios are immutable once implemented.** If a test fails, the implementation is fixed — not the spec or the test. A spec may only be changed if the *desired behavior* changes, and such changes require explicit justification.
3. **Scenarios are self-contained.** Each scenario states its own preconditions. No implicit ordering or shared mutable state between scenarios.
4. **Scenarios reference the data model.** Topic names, type names, QoS profile names, and partition formats used in scenarios must match those defined in [vision/data-model.md](../vision/data-model.md).
5. **Configuration is never embedded in tests.** Any configuration artifact required by a test — QoS XML, domain library XML, participant XML, governance files, permissions files, transport profiles — must live in a dedicated file under the project's `interfaces/` or `tests/` directory structure and be loaded by the test at runtime. Tests must not contain inline XML strings, hardcoded QoS structs, or any configuration that belongs in a file.
6. **Summary sections are mandatory and must be kept current.** Every spec file must contain a *Summary of Concrete Requirements* section immediately before the first scenario section. The summary must enumerate the key concrete requirements (rates, deadlines, thresholds, timing constraints, behavioral invariants) defined in the scenarios below. When a scenario is added or a concrete value is changed, the Summary must be updated in the same change. A spec change that updates scenarios without updating the summary is incomplete.
7. **Developer/diagnostic tools are exempt from GWT specs.** Internal developer tools (`medtech-diag`, `partition-inspector`, `qos-checker`) are validated by unit and smoke tests in their implementation phase — they do not require formal GWT spec scenarios. This exemption applies only to tools whose sole consumers are developers and operators, not to any user-facing module.

### Tagging

Scenarios are tagged to enable selective test execution. Tags also communicate which milestone a scenario belongs to — agents and CI pipelines can filter by tag to run only the scenarios in scope for a given release.

| Tag | Meaning | Milestone |
|-----|---------|----------|
| `@unit` | Can be tested with a single component in isolation | All |
| `@integration` | Requires two or more DDS participants | All |
| `@e2e` | Requires the full Docker Compose environment | All |
| `@gui` | Involves PySide6 GUI verification | V1.0+ |
| `@streaming` | Involves high-rate data paths | V1.0+ |
| `@command` | Involves command/response patterns | V1.0+ |
| `@partition` | Tests partition-based isolation | V1.0+ |
| `@durability` | Tests late-joiner / durability behavior | V1.0+ |
| `@failover` | Tests exclusive ownership failover | V1.0+ |
| `@filtering` | Tests content-filtered topics | V1.0+ |
| `@routing` | Tests Routing Service bridging | V1.0+ |
| `@performance` | Validates latency, throughput, or deadline enforcement requirements (e.g. control-path round-trip time, waveform streaming rate) | V1.0+ |
| `@recording` | Verifies RTI Recording Service captures data correctly and completely | V1.1+ |
| `@replay` | Verifies RTI Replay Service replays samples correctly and subscribers process them as expected | V1.1+ |
| `@security` | Validates security behavior: authentication, access control, governance enforcement, origin authentication, CRL, PSK. Requires Connext Security Plugins and governance files to be present. | V2.0+ |
| `@wan` | Tests WAN transport (Real-Time WAN Transport — `UDPv4_WAN`), cross-site bridging, and Cloud Discovery Service multi-site federation | V3.0+ |
| `@cloud` | Tests Cloud/Enterprise domain topics, facility-level partitions, and WAN Routing Service aggregation | V3.0+ |
| `@observability` | Tests Monitoring Library 2.0 telemetry delivery, Collector Service integration, Prometheus metrics, and Grafana dashboard visibility | V1.0+ |
| `@benchmark` | Tests performance benchmark harness: metric collection, baseline comparison, regression detection, threshold enforcement | V1.0+ |
| `@simulation` | Tests simulation fidelity: scenario profiles, cross-signal correlation, temporal realism, seeded reproducibility | V1.0+ |

---

## Documents

| File | Module / Concern | Milestone | Description |
|------|------------------|-----------|-------------|
| [surgical-procedure.md](surgical-procedure.md) | Surgical Procedure | V1.0 | Robot teleop, camera, vitals, alarms, procedure context, multi-instance isolation |
| [hospital-dashboard.md](hospital-dashboard.md) | Hospital Dashboard | V1.0 | Real-time procedure list, vitals overview, alert feed, robot status display |
| [clinical-alerts.md](clinical-alerts.md) | Clinical Alerts & Decision Support | V1.0 | Risk scoring, alert generation, cross-domain subscription |
| [common-behaviors.md](common-behaviors.md) | Cross-cutting | V1.0 | Discovery, partition isolation, durability, QoS enforcement, content filtering, Routing Service |
| [documentation.md](documentation.md) | Documentation Standard | V1.0 | README structure compliance, markdownlint rules, required sections, CI enforcement |
| [security.md](security.md) | Security | V2.0 | Authentication, access control, topic encryption/signing, CRL, PSK, origin authentication, governance enforcement |
| [performance-baseline.md](performance-baseline.md) | Performance Baseline | V1.0 | Benchmark harness, metric collection, baseline recording, regression detection, threshold enforcement |

*When V1.1 and V2 implementation begins, new spec files will be added for Recording/Replay and each integration gateway module. V3 will add specs for instrument tracking, imaging, inter-OR communication, ClinicalAlerts HA, and the Cloud Command Center. Each new file must follow the conventions above and will require operator approval before scenarios are authored (per the Approval Rule in [docs/agent/README.md](../README.md)).*
