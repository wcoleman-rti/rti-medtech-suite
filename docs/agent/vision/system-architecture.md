# System Architecture

## Overview

The medtech suite is a multi-domain DDS system built on RTI Connext Professional 7.6.0. It simulates a hospital environment where multiple surgical procedures run concurrently, monitored by a centralized dashboard, with Clinical Decision Support (ClinicalAlerts module) providing real-time alerts.

The architecture follows a **layered databus** model: each data layer gets its own domain, criticality within a layer is separated by domain tag, and operational context (room, procedure, facility) is isolated by domain partition. This ensures that a single application binary can operate in any room or facility — the operational context is injected at startup, not baked into code.

Domain names are used throughout this document. Domain IDs are defined only in the domain library XML (`interfaces/`). See [data-model.md](data-model.md) for the domain name → ID mapping.

---

## Layered Databus

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  Cloud / Enterprise Domain (V3.0)                                            ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  Facility status │ Aggregated alerts │ Resource utilization │ KPIs          ║
╚═══════════════════════════╩══════════════════════════════════════════════════╝
                            ▲
               RTI Routing Service (WAN bridge — Real-Time WAN Transport)
               UDPv4_WAN + Cloud Discovery Service + Security Plugins
                            │
╔══════════════════════════════════════════════════════════════════════════════╗
║  Hospital Domain                                                             ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  Procedure status │ Clinical alerts │ Risk scores │ Resource availability   ║
╚═══════════════════════════╩══════════════════════════════════════════════════╝
                            ▲
               RTI Routing Service (selective bridge)
               Only configured topics cross this boundary
                            │
╔══════════════════════════════════════════════════════════════════════════════╗
║  Procedure Domain                                                            ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  Domain Tag: control     │ Domain Tag: clinical  │ Domain Tag: operational  ║
║  (Class C / Class III)   │ (Class B / Class II)  │ (Class A / Class I)     ║
║  ─────────────────────── │ ───────────────────── │ ───────────────────────  ║
║  Robot command           │ Patient vitals        │ Camera frames            ║
║  Robot state             │ Waveforms             │ Procedure context        ║
║  Safety interlock        │ Alarm messages        │ Logging                  ║
║  Operator input          │ Device telemetry      │                          ║
╚══════════════════════════════════════════════════════════════════════════════╝
          │                        │                        │
          └────────────────────────┴────────────────────────┘
                  Domain Partitions (context isolation)
          room/OR-1/procedure/...   room/OR-3/procedure/...
```

### Procedure Domain

All data produced or consumed by an active surgical procedure. Subdivided by domain tag according to risk class (see [data-model.md](data-model.md) for the full domain tag breakdown and topic assignments).

- **`control` tag** — safety-critical closed-loop teleop. Deterministic, lowest-latency, strictest deadlines. Participants that do not need control data must not join this tag.
- **`clinical` tag** — patient-significant data: vitals, waveforms, alarms, device telemetry. Reliable, durable where needed.
- **`operational` tag** — non-critical procedure data: camera, context, logging. Mixed streaming and state.

Data streams that cross a risk class boundary must not share a domain tag.

### Domain Tag Participant Model

A DomainParticipant can have at most **one domain tag**. Because the Procedure domain uses
three domain tags (`control`, `clinical`, `operational`), a surgical procedure instance that
needs to interact with all three risk classes must create **three separate DomainParticipants**
— one per tag — all on the same domain ID.

In practice, not every process needs all three tags:

| Process | DomainParticipants | Domain Tags |
|---------|--------------------|-------------|
| Robot controller | 1 (+1 Observability) | `control` |
| Bedside monitor / vitals sim | 1 (+1 Observability) | `clinical` |
| Camera simulator | 1 (+1 Observability) | `operational` |
| Procedure context + status publisher | 1 (+1 Observability) | `operational` |
| Device telemetry gateway | 1 (+1 Observability) | `clinical` |
| Digital twin display | 1 (+1 Observability) | `control` |
| **Routing Service** (Procedure → Hospital bridge) | **4** (+1 Observability) | `control` + `clinical` + `operational` (3 on Procedure domain) + 1 on Hospital domain (no tag) |

Application logging uses the **RTI Connext Logging API** (`rti::config::Logger` / `rti.connextdds.Logger`), with log messages forwarded to Collector Service via Monitoring Library 2.0. See [technology.md — Logging Standard](technology.md) for details.

Monitoring Library 2.0 creates an additional **+1 dedicated participant** per process on the **Observability domain** (Domain 20) to distribute telemetry (metrics, logs, security events) to Collector Service. This participant is created automatically by the MONITORING QoS policy — no application code is needed. See [data-model.md — Domain 20](data-model.md) for the domain definition.

Each process creates a single participant on the tag it needs. If a future process genuinely
requires data from multiple tags (e.g., a combined surgical console), it creates multiple
participants within the same process — one per tag. The QoS participant profile
(`Participants.xml`) parameterizes the domain tag via a property or via separate named
profiles (e.g., `Participant::ProcedureControl`D, `Participant::ProcedureClinical`,
`Participant::ProcedureOperational`).

Domain tags are configured in the DomainParticipant QoS XML using the
`domain_tag` element within `<domain_participant_qos>`:

```xml
<domain_participant_qos>
    <discovery>
        <domain_tag>control</domain_tag>
    </discovery>
</domain_participant_qos>
```

This keeps domain tag assignment in XML configuration — never in application code — consistent
with system contract #8 (Configuration over code).

### Hospital Domain

Facility-wide layer for dashboards, clinical decision support, and resource coordination. Data arrives here only via Routing Service from the Procedure domain — no application directly publishes to both domains.

#### Why the Hospital Domain Has No Domain Tags

The Procedure domain uses domain tags (`control`, `clinical`, `operational`) to isolate
risk classes **at the point of surgical action** — preventing a fault in a lower-risk
participant from interfering with higher-risk data paths (e.g., a camera publisher
cannot disrupt robot commands). That isolation model is necessary because Procedure-domain
participants are **actors**: they publish commands, state, and interlocks that directly
affect the surgical process.

Hospital-domain participants are **observers only**. They consume bridged data for
monitoring, alerting, and resource coordination. No Hospital-domain application
publishes commands back into the Procedure domain. Because there is no surgical
process at risk on the Hospital domain, domain-tag isolation provides no safety
benefit — it would add participant complexity (dashboards would need 3 participants
instead of 1) with no corresponding risk reduction.

The trust and isolation boundary is **Routing Service itself**. It is a one-way,
configuration-controlled gateway. Only explicitly configured topics cross from
Procedure → Hospital. The Hospital domain receives a denormalized, read-only view
of surgical data.

> **Escalation trigger:** If any future requirement introduces a Hospital → Procedure
> data path (e.g., remote emergency stop, remote parameter adjustment), the Hospital
> domain must be re-evaluated for domain-tag isolation. A reverse data path would make
> Hospital-domain participants actors rather than observers, re-introducing the risk-class
> interference concern that tags are designed to prevent. This change requires operator
> approval and a revision of this section.

### Cloud / Enterprise Domain (V3.0)

Regional or enterprise-wide layer for multi-facility command center operations. Data arrives here only via a WAN-capable Routing Service from individual Hospital domains — no hospital application publishes directly to the Cloud domain.

The Cloud domain aggregates across facilities the same way the Hospital domain aggregates across ORs:

- **Facility-level partitions** isolate data by hospital: `facility/hospital-a`, `facility/hospital-b`
- **Wildcard partition matching** (`facility/*`) enables enterprise-wide aggregation
- Topics on the Cloud domain are facility-level summaries: `FacilityStatus`, `AggregatedAlerts`, `ResourceUtilization`, `OperationalKPIs`
- A Command Center dashboard (PySide6 GUI, same design standard as Hospital Dashboard) subscribes to the Cloud domain

The WAN Routing Service bridge uses the **RTI Real-Time WAN Transport** (`UDPv4_WAN`) for NAT/firewall-traversal cross-site communication, with **Cloud Discovery Service** providing multicast-free discovery across WAN-connected sites. **Connext Security Plugins** are required on all WAN connections — mutual authentication, encrypted data, and governance enforcement. Each hospital runs its own WAN Routing Service instance that selectively forwards Hospital domain data to the Cloud domain.

This layer is deferred to V3.0. The Procedure and Hospital layers are designed so that adding the Cloud layer above them requires **zero changes** to existing modules — only new Routing Service configurations and the Command Center application are added.

### Alert Data Flow — Two Independent Pathways

Two semantically distinct alert pathways coexist on the Hospital domain. They are
**not redundant** — they originate from different sources, serve different purposes,
and the dashboard consumes both.

```
Procedure Domain (clinical tag)              Hospital Domain
┌──────────────────────────┐                ┌─────────────────────────────┐
│  Bedside Monitor Sim     │                │                             │
│  ┌────────────────────┐  │  Routing Svc   │  ┌───────────────────────┐  │
│  │ PatientVitals      │──┼───────────────►│  │ PatientVitals (bridged)│  │
│  │ AlarmMessages      │──┼───────────────►│  │ AlarmMessages (bridged)│  │
│  └────────────────────┘  │                │  └───────┬───────────────┘  │
└──────────────────────────┘                │          │                  │
                                            │          ▼                  │
                                            │  ┌───────────────────────┐  │
                                            │  │ ClinicalAlerts Engine            │  │
                                            │  │ (subscribes to bridged │  │
                                            │  │  PatientVitals)       │  │
                                            │  │                       │  │
                                            │  │ → computes RiskScore  │  │
                                            │  │ → publishes           │  │
                                            │  │   ClinicalAlert       │──┼─┐
                                            │  └───────────────────────┘  │ │
                                            │                             │ │
                                            │  ┌───────────────────────┐  │ │
                                            │  │ Hospital Dashboard    │◄─┼─┘
                                            │  │ (subscribes to BOTH   │  │
                                            │  │  AlarmMessages AND    │  │
                                            │  │  ClinicalAlert)       │  │
                                            │  └───────────────────────┘  │
                                            └─────────────────────────────┘
```

#### Pathway 1 — Device-Level Alarms (`AlarmMessages`)

| Attribute | Detail |
|-----------|--------|
| **Origin** | Bedside monitor simulator (Procedure domain, `clinical` tag) |
| **Trigger** | Immediate threshold violation on a single vital sign (e.g., HR ≥ 120 bpm) |
| **Latency** | Sub-second — alarm is raised in the same publication cycle as the triggering vital |
| **Semantics** | Raw device alarm: "this sensor reading exceeded a configured limit right now" |
| **Lifecycle** | Alarm is ACTIVE when the condition holds, transitions to CLEARED when the vital returns to normal range |
| **Transport** | Published on Procedure domain (`clinical` tag), bridged to Hospital domain via Routing Service |
| **Consumer** | Dashboard alert feed (direct display), ClinicalAlerts engine (optional — could incorporate device alarms into risk models in future versions) |

#### Pathway 2 — Analytics-Level Alerts (`ClinicalAlert`)

| Attribute | Detail |
|-----------|--------|
| **Origin** | ClinicalAlerts engine (publishes natively on the Hospital domain — not bridged) |
| **Trigger** | Computed risk score exceeds a configured threshold (e.g., hemorrhage risk ≥ 0.7), or a direct vital-sign rule fires (e.g., HR > 150 bpm) |
| **Latency** | ≤ 500 ms after receiving the triggering vitals sample |
| **Semantics** | Analytical assessment: "based on a weighted model of multiple vital signs, this patient's clinical risk is elevated" |
| **Lifecycle** | Alert is published once per threshold crossing; duplicates are suppressed for sustained conditions at the same severity; alert resolves when the score drops below threshold |
| **Transport** | Published directly on Hospital domain — no Routing Service involvement |
| **Consumer** | Dashboard alert feed (displayed alongside device alarms, distinguished by category) |

#### Why Both Exist

- **`AlarmMessages` provides immediacy.** A single-parameter spike (HR = 180) triggers
  an alarm instantly, before any analytics model runs. This is the device-level safety net.
- **`ClinicalAlert` provides clinical intelligence.** A patient's HR may be 110 (below
  the device alarm threshold) while their SBP is 75 — neither triggers a device alarm
  alone, but the hemorrhage risk model scores this at 0.72 (CRITICAL). Only the ClinicalAlerts
  engine detects this pattern.
- The dashboard displays both in the same alert feed, distinguished by `category`
  (`DEVICE` vs. `CLINICAL`). Clinicians see the full picture: raw device alarms for
  immediate response, analytics alerts for pattern-based risk awareness.

#### What Must Not Happen

- **Do not merge the pathways.** `AlarmMessages` and `ClinicalAlert` are independent
  data flows. The ClinicalAlerts engine does not re-publish device alarms as `ClinicalAlert`.
  The bedside monitor does not publish `ClinicalAlert`.
- **Do not bridge `ClinicalAlert` back to the Procedure domain.** It originates on
  and stays on the Hospital domain. (This is consistent with the Hospital-domain
  observer-only design — see [Hospital Domain](#hospital-domain).)

---

## Partition Strategy

### Domain Partitions

Domain partitions provide **context-based isolation**. They isolate at the participant level
when the isolation factor lives outside of the data being delivered — i.e., the operational context (which room, which procedure) rather than the data content itself.

Each surgical procedure instance is launched with a partition derived from its context:

```
Format:  room/<room_id>/procedure/<procedure_id>
Example: room/OR-3/procedure/proc-2026-0042
```

Wildcard matching enables aggregation without special application logic:

| Partition Pattern | Who Uses It | Meaning |
|-------------------|-------------|---------|
| `room/OR-3/procedure/proc-001` | Per-instance surgical apps | Exactly one procedure in one room |
| `room/OR-3/*` | OR-3 monitoring | All procedures in OR-3 |
| `room/*/procedure/*` | Dashboard, Routing Service | All procedures across all rooms |
| `room/OR-*` | Subset monitoring | All rooms matching a name pattern |

- Adding a new OR requires zero code or configuration changes beyond a different partition value at startup
- Partition is always assigned from context (environment variable or startup config) — never hardcoded

### Publisher/Subscriber Partitions

Publisher/Subscriber Partition QoS is **not used** in this system. All context-based isolation is handled by domain partitions. All data-content-based isolation is handled by content-filtered topics.

If an application must operate across multiple contexts simultaneously, it should either:
- Create multiple DomainParticipant entities (each with its own partition), or
- Associate a single participant with multiple partitions explicitly

### Content vs. Partition — Choosing the Right Tool

| Isolation need | Tool |
|----------------|------|
| Which room/procedure a participant belongs to | Domain partition |
| Filtering data by a field value (patient ID, device ID) | Content-filtered topic |
| Separating criticality/risk class | Domain tag |
| Separating data layers | Domain ID |

---

## Network Topology & Simulation

### Production Model

```
┌──────────────────────────────────┐
│  Surgical LAN (per OR)           │  Dedicated, low-latency network
│  • Robot controller              │  Procedure domain (all tags)
│  • Surgeon console               │  Domain partition: room/OR-n/procedure/...
│  • Digital twin display          │
│  • Bedside monitors              │
│  • Anesthesia machine            │
└────────────────┬─────────────────┘
                 │
        RTI Routing Service
        (controlled, selective gateway)
                 │
┌────────────────▼─────────────────┐
│  Hospital Backbone Network       │  Standard LAN/VLAN
│  • Dashboard servers             │  Hospital domain
│  • ClinicalAlerts engine                    │
│  • Nurse station                 │
│                                  │  Note: multicast is commonly restricted
│  RTI Cloud Discovery Service     │  on hospital networks. It enables
│  (per segment or centralized)    │  multicast-free participant discovery.
│                                  │
│  RTI Collector Service           │  Telemetry aggregation (Observability
│  Prometheus · Loki · Grafana     │  Framework — optional profile)
└────────────────┬─────────────────┘
                 │
        RTI Routing Service (WAN — UDPv4_WAN)     ← V3.0
        Real-Time WAN Transport + Security Plugins
                 │
┌────────────────▼─────────────────┐
│  Cloud / Enterprise Network      │  Enterprise WAN / VPN
│  • Command Center dashboard     │  Cloud domain
│  • Enterprise alerting          │  Domain partition: facility/hospital-a
│  • Cloud Discovery Service      │
└──────────────────────────────────┘
```

### Single-Machine Simulation (Docker)

Each logical host is a Docker container. Custom Docker networks simulate the network boundaries.

> **Docker Hub Image Policy:** For RTI infrastructure services available on Docker Hub
> ([hub.docker.com/u/rticom](https://hub.docker.com/u/rticom)), use the official RTI
> images rather than building custom images. This applies to Cloud Discovery Service
> (`rticom/cloud-discovery-service`), Routing Service, and any other RTI service
> images published to Docker Hub.

> **Performance note:** Docker simulation disables shared memory and routes traffic through
> the Docker virtual network stack, introducing significantly higher latency than a dedicated
> surgical LAN. Timing requirements specified in `spec/` (e.g., 4 ms delivery deadline,
> 40 ms interlock response) describe the **production target**. `@performance`-tagged tests
> apply a 10\u00d7 tolerance multiplier when running in Docker. See
> [spec/common-behaviors.md](../spec/common-behaviors.md) — Performance Test Environment
> Tolerance.

| Docker Network | Simulates | Containers |
|----------------|-----------|------------|
| `surgical-net` | Per-OR surgical LAN | Robot sim, surgeon console, digital twin display, bedside monitors, procedure context sim, Routing Service |
| `hospital-net` | Hospital backbone | Dashboard, ClinicalAlerts engine, Cloud Discovery Service, Routing Service, Collector Service, Prometheus, Grafana Loki, Grafana |
| `cloud-net` **(V3.0)** | Enterprise WAN | WAN Routing Service (dual-homed: hospital-net + cloud-net), Command Center dashboard, Cloud Discovery Service — **not created until V3.0 implementation** |

### Docker Compose Service Startup Ordering

Docker Compose `depends_on` with health checks must enforce the following startup order
to prevent intermittent initialization failures:

1. **Cloud Discovery Service** starts first and reports healthy (listening on its configured
   port) before any application container starts. All participants use Cloud Discovery
   Service as their initial peer; if it is unavailable at startup, discovery is delayed
   and initialization time budgets may be exceeded.
2. **Routing Service** starts after Cloud Discovery Service is healthy and before any
   Hospital domain consumer (dashboard, ClinicalAlerts engine). Routing Service must be dual-homed
   and matched on both networks before bridged data can flow.
3. **Surgical procedure instances** start after Cloud Discovery Service is healthy.
   They operate entirely on `surgical-net` and do not depend on Routing Service or
   Hospital domain services.
4. **Hospital domain applications** (dashboard, ClinicalAlerts engine) start after both Cloud
   Discovery Service and Routing Service are healthy.
5. **Observability stack** (Collector Service, Prometheus, Grafana Loki, Grafana) has no
   startup ordering dependency with application services — it is profile-gated and can
   start in any order.

Health checks use the simplest reliable method per service:
- Cloud Discovery Service: TCP port check on its configured listening port
- Routing Service: TCP port check on its administration port or a custom "ready" script
- Application containers: a process-alive check (`CMD ["pgrep", "-f", "<process>"]`)

### Transport Configuration

Transport behavior is configured via XML QoS profiles, never in application code. The appropriate profile is selected per deployment context (simulation vs. production).

#### Simulation (Docker containers — inter-host traffic)

Containers simulating separate hosts use:
- **Shared memory disabled** — forces traffic through the Docker network stack, simulating real network behavior
- **UDPv4 only** — no SHMEM, no UDPv6 unless explicitly needed
- **Explicit discovery peers** — `hospital-net` may not support multicast; all participants configured with explicit peer addresses or Cloud Discovery Service
- **Interface restrictions** — each participant binds only to its container's relevant network interface

```xml
<domain_participant_qos>
    <transport_builtin>
        <mask>UDPv4</mask>
    </transport_builtin>
    <discovery>
        <initial_peers>
            <element>rtps@udpv4://cloud-discovery-service:7400</element>
        </initial_peers>
        <multicast_receive_addresses/>  <!-- empty = no multicast -->
    </discovery>
</domain_participant_qos>
```

#### Intra-Machine / Intra-Process Communication

Shared memory (SHMEM) transport is appropriate and efficient for communication between participants on the same physical host or within the same process. When all communicating participants are co-located:
- Enable SHMEM transport for those participants
- UDPv4 may still be enabled as a fallback for participants that cross host boundaries
- Security policy implications for SHMEM-only paths are deferred to [vision/security.md](security.md)

### Cloud Discovery Service

Hospital networks commonly restrict UDP multicast for security reasons, making standard DDS unicast/multicast discovery unreliable. RTI Cloud Discovery Service provides multicast-free participant discovery:

- Participants configure Cloud Discovery Service as their initial peer instead of multicast addresses
- Cloud Discovery Service acts as a rendezvous server, brokering discovery between participants without requiring multicast routing
- Deployed on `hospital-net` (and optionally on `surgical-net` for consistency)
- Primary + backup Cloud Discovery Service instances recommended for high availability

**Design decision (resolved):** Cloud Discovery Service runs as a dedicated container
(`rticom/cloud-discovery-service` from Docker Hub) attached to both `hospital-net` and
`surgical-net`. This gives all participants on both networks a direct discovery path.
Configuration and deployment details are in
[Phase 1 Step 1.4](../implementation/phase-1-foundation.md).

### Routing Service Deployment

Routing Service runs as its own container, attached to both `surgical-net` and `hospital-net` (dual-homed). It is the **single controlled gateway** between the Procedure and Hospital domains.

It bridges:
- Procedure → Hospital: `ProcedureStatus`, `ProcedureContext`, patient vitals, alarm messages, device telemetry
- Procedure (`control` tag) → Hospital: robot state (read-only, for dashboard display)

For the `control`-tag bridge, Routing Service creates a DomainParticipant on the Procedure
domain with the `control` domain tag (configured in its participant XML) in order to subscribe
to `RobotState`. It publishes the bridged data on the Hospital domain participant, which has
no domain tag restriction. This cross-tag route is explicitly configured in the Routing Service
XML — it does not imply that `control`-tag data is generally accessible outside its tag.

Only explicitly configured topics cross this boundary. Routing Service uses separate sessions for different traffic classes:
- **StateSession** — low-rate status/state topics
- **StreamingSession** — higher-rate telemetry if needed
- **ImagingSession** — imaging metadata (future)

### Routing Service Partition Mapping

On the **Procedure domain input side**, Routing Service joins with the wildcard partition
`room/*/procedure/*` so it receives data from all rooms and procedures. This is the same
mechanism used by any aggregating subscriber.

On the **Hospital domain output side**, Routing Service **preserves the source partition**.
Data bridged from `room/OR-3/procedure/proc-001` is published on the Hospital domain with
the same partition string. This enables:

- Hospital dashboard to use wildcard `room/*/procedure/*` for facility-wide aggregation
- Content-filtered drill-down by room (filtering on the `ProcedureContext` room field) or
  per-room partition narrowing if the dashboard creates multiple participants
- Consistent partition semantics across both domains — the partition format
  `room/<room_id>/procedure/<procedure_id>` is universal

The Routing Service configuration specifies partition propagation via the
`<propagation_qos>` element or by configuring the output DataWriter with
the same partition expression as the matched input DataReader. No partition
transformation or stripping is performed.

Hospital-only topics (e.g., `ClinicalAlert`, `RiskScore`) that originate on the Hospital
domain and are published directly by hospital-domain applications (ClinicalAlerts engine) do **not**
use room partitions. They use the default (empty) partition unless the publishing application
explicitly sets one for multi-context purposes.

### WAN Routing Service Deployment (V3.0)

A second Routing Service tier bridges Hospital → Cloud domain traffic across facility boundaries. Each hospital runs a WAN Routing Service instance on `cloud-net` (dual-homed to `hospital-net` + `cloud-net`).

It bridges:
- Hospital → Cloud: facility status, aggregated clinical alerts, resource utilization, operational KPIs

WAN transport uses the RTI Real-Time WAN Transport (`UDPv4_WAN`) for NAT/firewall traversal, Cloud Discovery Service for cross-site discovery, and Connext Security Plugins for authentication and encryption. The WAN Routing Service follows the same architectural principles as the intra-hospital bridge — only explicitly configured topics cross the boundary, and no hospital application publishes directly to the Cloud domain.

---

## Security (Deferred)

Security implementation is deferred to a later phase. Architecture and posture are defined in [vision/security.md](security.md). All modules are designed to be security-compatible when the security layer is enabled.
