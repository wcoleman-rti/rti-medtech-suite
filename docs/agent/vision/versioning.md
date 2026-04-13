# Versioning & Release Policy

This document defines what constitutes a release, how version numbers are assigned, and what scope is planned for each milestone. It is the authoritative reference for all versioning decisions in the medtech suite.

See [capabilities.md](capabilities.md) for the detailed capability descriptions behind each milestone.

---

## Version Scheme

The medtech suite follows a **Major.Minor.Patch** scheme:

```
V<Major>.<Minor>.<Patch>
e.g. V1.0.0, V1.1.0, V2.0.0
```

| Increment | When to use | Triggers |
|-----------|-------------|----------|
| **Major** | A new capability milestone is delivered. New modules, integration gateways, or Connext features are introduced. All specs from all prior milestones continue to pass. | New module, new integration gateway, or new Connext service demonstrated |
| **Minor** | Additive change within a milestone. New scenarios/specs, new IDL types, new QoS profiles, new test coverage. No interface-breaking changes. | New spec scenarios, new topics, new QoS profiles, new utility capabilities that don't change existing interfaces |
| **Patch** | Non-functional correction. Bug fixes, documentation corrections, test fixes, configuration corrections. No new capability or interface changes. | Test fix, doc correction, config fix, dependency update |

---

## Release Criteria

A version may only be cut when **all** of the following are true:

1. **All spec scenarios for the targeted milestone scope pass as automated tests.** No scenario may be pending, skipped, disabled, or marked expected-fail (`@skip`, `xfail`, `DISABLED_`, or equivalent).
2. **No tests from any prior milestone are failing or disabled.** Regression is not permitted across versions.
3. **All implementation phase test gates for the targeted milestone pass.** Each phase file defines explicit test gates; all must be green.
4. **The Docker simulation demo runs end-to-end without errors.** For milestones up to V1.3, `docker compose up` for the targeted scope completes and all services reach healthy state. For V1.4+, `medtech launch` (the CLI-driven demo path) completes and all services reach healthy state.
5. **All IDL and QoS files are consistent with the data model.** Generated code is buildable from clean; no uncommitted generated files exist in the source tree.
6. **No open spec change is pending operator approval.** All proposed vision/spec/implementation doc changes from the development cycle have been resolved.

---

## Milestone Roadmap

### V1.0.0 — Core DDS Demo

**Implementation phases:** 1 (Foundation), 2 (Surgical Procedure), 5 (Procedure Orchestration), 3 (Hospital Dashboard), 4 (Clinical Alerts & Decision Support)

**Theme:** Establish the full live DDS data bus — multi-domain isolation, domain tags, domain partitions, Routing Service cross-domain bridge, ClinicalAlerts (Clinical Decision Support), Cloud Discovery Service, and service-oriented procedure orchestration. No security, no external integrations.

| Module / Capability | Connext Features Demonstrated |
|---------------------|-------------------------------|
| Surgical Procedure (multi-instance) | Domain tags, domain partitions, `control`/`clinical`/`operational` QoS patterns, exclusive ownership failover |
| Procedure Orchestration | DDS RPC, Orchestration domain, `medtech::Service` interface, dual-mode services, Service Host framework |
| Hospital Dashboard (NiceGUI) | Hospital domain subscription, TRANSIENT_LOCAL late-join, content-filtered topics, asyncio DDS integration |
| Clinical Alerts & Decision Support | Risk scoring, alert generation, cross-domain subscription via Routing Service |
| Routing Service | Selective Procedure → Hospital topic bridging, multiple sessions by traffic class |
| Cloud Discovery Service | Multicast-free discovery on `hospital-net` and `orchestration-net` |
| CMake unified build | C++17, Python, rtiddsgen C++11/Python, `RTIConnextDDS::cpp2_api`, build-dir generated code |

---

### V1.1.0 — Recording & Replay

**Theme:** Add zero-code compliance capture across the live DDS bus. No structural changes to V1.0 modules.

| Module / Capability | Connext Features Demonstrated |
|---------------------|-------------------------------|
| RTI Recording Service | Passive multi-domain capture of all DDS traffic (including Orchestration domain) |
| RTI Replay Service | Deterministic replay into subscriber applications |
| Recording Service integration tests | `@recording` and `@replay` spec scenarios |

---

### V1.2.0 — Dynamic Multi-Arm Orchestration

**Theme:** Extend the procedure orchestration model to support dynamic spawning, spatial assignment, and positioning of multiple robot arm services around a surgical table.

| Module / Capability | Connext Features Demonstrated |
|---------------------|-------------------------------|
| `RobotArmAssignment` topic | Write-on-change state with `dispose()` for instance removal, TRANSIENT_LOCAL for late-joining controllers |
| Multi-arm lifecycle | Keyed instances per `robot_id`, liveliness-based arm health detection |
| Table position assignment | Spatial assignment as DDS state data, correlated with `RobotState` via shared `robot_id` key |
| Procedure Controller expansion | Multi-domain participant model: Orchestration + Procedure `control` + Hospital |
| Digital twin enhancement | Table layout visualization with per-arm status indicators |

---

### V1.3.0 — UI Modernization

**Implementation phases:** Phase UI-M (UI Modernization)

**Theme:** Modernize the visual design of all GUI applications with a cohesive design system. Visual-only changes — no DDS, IDL, QoS, or architectural modifications.

| Module / Capability | Features |
|---------------------|----------|
| Design token system, Inter font, glassmorphism, status indicators, animations, semantic type scale | Visual design modernization across all GUI modules |

---

### V1.4.0 — Distributed Simulation & CLI

**Implementation phases:** Phase SIM (Distributed Simulation & CLI)

**Theme:** Developer-facing infrastructure for hands-on exploration. Split-GUI Docker deployment and `medtech` CLI.

| Module / Capability | Features |
|---------------------|----------|
| Split-GUI Docker deployment | Per-OR twin containers on `surgical-net`, central GUI on `hospital-net`, per-hospital Collector Service (`rticom/collector-service`) as base infrastructure, all containers via `docker run` |
| Multi-hospital simulation | Named hospitals with isolated private networks, NAT routers (`iptables MASQUERADE`), shared `wan-net`, per-hospital subnet/port allocation |
| `medtech` CLI | `build`, `run hospital [--name]`, `run or [--name] [--hospital]`, `launch`, `status`, `status --topology`, `stop` — unified `--name` across all multi-instance commands |
| Topology visualization | `medtech status --topology` (ASCII); optional [DockGraph](https://github.com/dockgraph/dockgraph) sidecar at `http://localhost:7800` |
| Simulation scenarios | Distributed (default), multi-site, unified (fallback), minimal |

---

### V2.0.0 — Security & Hospital Integration Gateways

**Implementation phases:** 7 (Security), plus new gateway modules (Phases 8–13)

**Theme:** Harden the data bus with Connext Security Plugins and introduce simulated external hospital system integrations. Demonstrates the open pub/sub model for hospital IT interoperability.

| Module / Capability | Connext Features Demonstrated |
|---------------------|-------------------------------|
| Security — Connext Security Plugins | Domain governance, topic-level encryption/signing, participant identity (leaf certs), permissions, CRL, PSK, origin authentication, file polling for cert rotation |
| EHR Gateway (Epic/FHIR bridge sim) | Bidirectional: seeds `ProcedureContext` from EHR; reports procedure progression back |
| LIS Gateway (lab results) | Inbound: publishes `LabResult` on `clinical` tag; feeds ClinicalAlerts alert logic |
| AIMS Gateway (anesthesia record) | Read-only multi-topic subscriber; demonstrates aggregated record reconstruction via TRANSIENT_LOCAL |
| OR Scheduling Gateway | Inbound: drives partition assignment and procedure context from scheduled data |
| Hospital Alarm Management Gateway | Read-only subscriber to `ClinicalAlert` and `AlarmMessages`; routes to staff |
| Device Integration Gateway (bidirectional) | Infusion pump / anesthesia machine command/control; exclusive ownership primary/backup |

---

### V2.1.0 — Teleoperation / Remote Operator

**Theme:** Extend operator control to hospital and cloud levels with automatic failover, demonstrating DDS-enforced control authority arbitration via exclusive ownership and Routing Service QoS transformation.

| Module / Capability | Connext Features Demonstrated |
|---------------------|-------------------------------|
| Remote operator control path | Exclusive ownership, ownership strength, AUTOMATIC liveliness + DEADLINE failover, Routing Service QoS transformation |
| Routing Service control-tag bridge | Reverse data path (Hospital/Cloud → Procedure), separate domain_route per risk class |
| Failover automation | DDS ownership + liveliness for automatic primary/backup switching |
| Safe-hold mode | Application-level supervisory state machine layered on DDS ownership arbitration |

---

### V3.0.0 — Advanced Scenarios & Multi-Facility

**Theme:** Extend the system to larger-scale and more complex hospital scenarios. Demonstrates WAN bridging, inter-facility deployment, and scope expansion without architectural changes.

| Module / Capability | Connext Features Demonstrated |
|---------------------|-------------------------------|
| Surgical Instrument Tracking | Tool events, tray composition, TRANSIENT_LOCAL for count boards |
| PACS / Imaging Gateway (DICOM bridge sim) | Pre-op image metadata, intraoperative image capture, best-effort large-sample streaming |
| Inter-OR Communication | Specialist consultation events, shared resource availability (blood bank, staff) |
| Routing Service WAN bridging | Cross-facility domain bridging, WAN transport configuration |
| ClinicalAlerts High Availability | Primary/backup ClinicalAlerts engine pair, automatic failover |
| Multi-Segment Deployment | Per-segment ClinicalAlerts engine deployment; Cloud Discovery Service multi-initial-peer HA |
| Cross-Platform Support | Windows, macOS, QNX build/runtime; platform-specific setup scripts; parameterized Connext architecture |
| Cloud Command Center | Cloud/Enterprise domain (3rd databus layer); WAN Routing Service (Real-Time WAN Transport — `UDPv4_WAN`); Cloud Discovery Service for cross-site discovery; Connext Security Plugins on all WAN connections; Command Center dashboard; facility-level partitions; enterprise-wide aggregation; central Collector Service aggregating per-hospital Collectors → Prometheus → Grafana Loki → Grafana |
| Connext Runtime MCP Server | Cloud-deployed MCP server querying per-hospital Collector Service instances; AI-agent-powered frontend for natural-language DDS system health queries, participant topology, QoS compliance, and cross-hospital diagnostics |

---

## Version Boundary Rules

- A Major version boundary requires all spec scenarios from the new milestone to be authored and reviewed **before** implementation begins (per the Approval Rule in `/docs/agent/README.md`).
- A Minor version boundary requires new scenario(s) to be added to the appropriate spec file and the Summary of Concrete Requirements to be updated before implementation begins.
- Integration gateway modules follow the same doc cascade as core modules: vision → spec → implementation phase file.
- Security (V2.0.0) has pre-existing placeholder documents in `vision/security.md`, `spec/security.md`, and `implementation/phase-7-security.md`. These must be fully populated and operator-approved before V2 implementation begins.
