# Vision

This directory defines **what** the medtech suite is, **why** it exists, and the architectural decisions that govern all modules.

Any agent working in this project should consult these documents before making design decisions that affect cross-module concerns (domains, topics, QoS, partitions, type definitions).

---

## System Contracts

These rules are non-negotiable across all modules and phases:

1. **Tests enforce specs.** Every behavior defined in `spec/` must have a corresponding test. Tests are never deleted or disabled. A failing test means the code is wrong, not the test.
2. **QoS and IDL are shared interfaces.** All type definitions and QoS profiles live in a common interface component. Modules depend on this component — they do not define their own types or QoS inline.
3. **Domain IDs separate data layers.** Each logical data layer (procedure, hospital, cloud, etc.) gets its own domain ID. This is the coarsest isolation boundary — participants in different domains do not communicate.
4. **Domain tags separate criticality within a layer, aligned to medical device risk classes.** Within a single domain ID, criticality classes are isolated using domain tags. Domain tag boundaries must align with industry medtech regulatory risk classifications (e.g., IEC 62304 software safety classes, FDA device risk classes). Data streams/topics that fall under different risk classes must not operate within the same domain tag. For example, safety-critical teleop control (Class C / Class III) and non-critical telemetry/visualization (Class A / Class I) require separate domain tags even though they share a domain ID. Participants must share the same domain ID *and* domain tag to discover each other. See [Creating DomainParticipant Partitions](https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/connext_dds_professional/users_manual/users_manual/Creating_ParticipantPartitions.htm).
5. **Domain partitions drive dynamic instance isolation.** Context-based isolation (room, procedure, hospital, etc.) is achieved via DomainParticipant partitions — not via separate domain IDs, domain tags, or topic names. The same application binary runs in any room; the domain partition is assigned at startup from context (environment variable or configuration).
6. **Topics represent data patterns, not instances.** Each topic carries a class of data defined by its semantic purpose. When multiple variations or iterations of a data stream exist, they share a single topic and are distinguished by key fields and content-filtered topics. Key fields serve a role analogous to indexes in a SQL database — they enable semantic pivoting on the data within a topic.
7. **All QoS is set in XML configuration, never in code.** This is a strict requirement. All DDS QoS, transport settings, discovery peers, and partition assignments come from XML profiles and environment/startup parameters. No QoS is constructed or modified programmatically. Modules reference named QoS profiles via `QosProvider` — they never call QoS setter APIs. **Sole exception:** the factory-level XTypes compliance mask (bit `0x00000020`, `accept_unknown_enum_value`) must be set programmatically before any DomainParticipant is created, as it has no XML equivalent. This is a data model prerequisite — see [data-model.md — Pre-Participant Initialization](data-model.md). That section also documents the type registration requirement that must be performed in the same initialization pass.
8. **Configuration over code.** Beyond QoS, all runtime-variable DDS settings (domain IDs, domain tags, partitions, transport, discovery peers) come from XML configuration and environment parameters — not hardcoded in application logic.

---

## Documents

| File | Purpose |
|------|---------|
| [system-architecture.md](system-architecture.md) | Domain layout, partition strategy, network topology, Docker simulation, Routing Service |
| [data-model.md](data-model.md) | IDL type definitions, QoS profiles, topic design, content filtering strategy |
| [technology.md](technology.md) | Tech stack, build system, dependencies, toolchain, integrated CMake build |
| [capabilities.md](capabilities.md) | V1 feature scope, module descriptions, versioned milestone roadmap (V1.1, V2, V3) |
| [versioning.md](versioning.md) | Release version policy: Major.Minor.Patch scheme, release criteria, milestone-to-version mapping, version boundary rules |
| [documentation.md](documentation.md) | README standard: required section structure, markdownlint compliance rules, CI enforcement |
| [security.md](security.md) | Security architecture: governance posture, participant identity model, permissions design, CRL, PSK, origin authentication |
| [coding-standards.md](coding-standards.md) | Coding standards: C++/Python naming conventions, class vs struct, namespace rules, file organization, test patterns, CMake conventions |
| [dds-consistency.md](dds-consistency.md) | DDS consistency contract: initialization sequence, canonical data access patterns, QoS provider usage, threading rules, anti-pattern catalog, Routing Service usage, new module checklist |
| [performance-baseline.md](performance-baseline.md) | Performance baseline framework: benchmark harness, Connext metrics collection, phase-gate baselines, regression thresholds, stress testing roadmap |
| [simulation-model.md](simulation-model.md) | Simulation fidelity: non-deterministic realistic data, seeded reproducibility, scenario profiles, cross-signal correlation, publication model integration |
| [tooling.md](tooling.md) | Debugging & diagnostics: RTI Admin Console, DDS Spy, Grafana dashboards, project-specific diagnostic tools (medtech-diag, partition-inspector, QoS checker) |
