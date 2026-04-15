# System Architecture

## Overview

The medtech suite is a multi-domain DDS system built on RTI Connext Professional 7.6.0. It simulates a hospital environment where multiple surgical procedures run concurrently, monitored by a centralized dashboard, with Clinical Decision Support (ClinicalAlerts module) providing real-time alerts.

The architecture follows a **layered databus** model: each deployment level (room, hospital, cloud) gets its own set of domains, criticality within a level is separated by domain tag, and operational context (room, procedure, facility) is isolated by domain partition. Upper-level domains receive data from lower levels exclusively through RTI Routing Service — no application directly spans levels. Lower levels never change to support upper levels; upper levels "extract" only the data they need. This ensures that a single application binary can operate in any room or facility — the operational context is injected at startup, not baked into code.

Domain names are used throughout this document. Domain IDs follow the **Domain Numbering Guide** (see below). Full domain definitions are in [data-model.md](data-model.md).

### Domain Numbering Guide

Domain IDs use a **decade-offset** scheme: the tens digit encodes the deployment level and the units digit encodes the function class. Domain 0 is reserved for prototyping/testing. The maximum practical domain ID with Connext 7.6.0's default RTPS port mapping is **232**.

| Level | Decade | Description |
|-------|--------|-------------|
| Room / Procedure | 10–19 | Per-OR surgical and orchestration data |
| Hospital | 20–29 | Facility-wide integration and hospital-native data |
| Cloud / Enterprise | 30–39 | Multi-facility aggregation (V3.0) |
| (Reserved) | 40–49 | Future enterprise or regulatory layer |

| Offset | Function | Description |
|--------|----------|-------------|
| +0 | Data / Integration | Primary application data domain for the level |
| +1 | Orchestration | Service lifecycle management (RPC, catalog, status) |
| +2 | Command | Reverse control / actuation paths (V2.1+) |
| +3–8 | (Reserved) | Future function classes |
| +9 | Observability | Monitoring Library 2.0 telemetry, Collector Service |

**Concrete domain assignments:**

| Domain ID | Name | Level | Function |
|-----------|------|-------|----------|
| 0 | (Reserved) | — | Prototyping / testing |
| 10 | Procedure | Room | Surgical data (domain tags: `control` / `clinical` / `operational`) |
| 11 | Orchestration | Room | Service Host lifecycle, RPC, catalog, status |
| 12 | Command | Room | (Reserved — V2.1 room-level reverse control) |
| 19 | Room Observability | Room | Monitoring Library 2.0 per-room telemetry; Collector forwards to Domain 29 |
| 20 | Hospital | Hospital | Integration domain: extracted room data + hospital-native topics |
| 22 | Hospital Command | Hospital | (Reserved — V2.1 remote teleoperation reverse path) |
| 29 | Hospital Observability | Hospital | Aggregated telemetry: room-forwarded (from Domain 19) + hospital-native; Collector forwards to Domain 39 |
| 30 | Cloud | Cloud | Integration domain: extracted hospital data + cloud-native topics (V3.0) |
| 32 | Cloud Command | Cloud | (Reserved — V3.0 reverse control) |
| 39 | Cloud Observability | Cloud | Terminal telemetry aggregation: exports to Prometheus / Loki / OTEL (V3.0) |

> **Migration note:** Previous domain ID assignments (10 = Procedure, 11 = Hospital,
> 15 = Orchestration, 20 = Observability) are superseded by this scheme. All XML
> configurations, participant definitions, and RS routes must be updated.

---

## Layered Databus

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  Cloud Level — Domain 30 (V3.0)                                              ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  Extracted hospital data + cloud-native: FacilityStatus, AggregatedAlerts  ║
╚═══════════════════════════╩══════════════════════════════════════════════════╝
                            ▲
               RTI Routing Service (WAN bridge — Real-Time WAN Transport)
               UDPv4_WAN + Cloud Discovery Service + Security Plugins
               Hospital → Cloud: selective topic extraction
                            │
╔══════════════════════════════════════════════════════════════════════════════╗
║  Hospital Level — Domain 20 (Integration)                                    ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  Extracted from rooms: ProcedureStatus, PatientVitals, RobotState, ...     ║
║  Extracted from orch:  ServiceCatalog (room/GUI discovery)                 ║
║  Hospital-native:      ClinicalAlert, RiskScore, ResourceAvailability      ║
╚═══════════════════════════╩══════════════════════════════════════════════════╝
                            ▲
               Per-room RTI Routing Service (MedtechBridge)
               Domain 10 → 20 (select topics) + Domain 11 → 20 (ServiceCatalog)
                            │
╔══════════════════════════════════════════════════════════════════════════════╗
║  Room Level — Domain 10 (Procedure) + Domain 11 (Orchestration)              ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  Domain 10 Tags: control │ clinical │ operational    Domain 11: no tags    ║
║  Robot command           │ Patient vitals        │ ServiceCatalog          ║
║  Robot state             │ Waveforms             │ ServiceStatus           ║
║  Safety interlock        │ Alarm messages        │ ServiceHostControl RPC  ║
║  Operator input          │ Device telemetry      │                         ║
╚══════════════════════════════════════════════════════════════════════════════╝
          │                        │                        │
          └────────────────────────┴────────────────────────┘
                  Domain Partitions (context isolation)
          room/OR-1/procedure/...   room/OR-3/procedure/...
```

#### Gateway Interconnection — Layered Databus with Deployable Instances

The medtech suite instantiates the RTI layered databus pattern with three
deployment tiers. Each tier is a **replicable deployment instance** containing
its own databuses and participants, with a **gateway** at its boundary that
selectively routes application data **northbound only** to the next tier.
This mirrors the RTI V2X reference architecture where a Vehicle is a bounded
instance containing internal databuses, connected upward through Routing
Service to fleet and municipal layers.

Unlike the traditional flat layered-databus diagram where gateways float
between layers, this diagram nests each instance inside its parent to show
**where the gateway lives** — it belongs to the instance it serves, sitting
at user boundary between its local databuses and the parent-level databus.
This makes network visibility explicit: a gateway can only discover and
route to nodes on the networks its instance is attached to.

> **Cloud-gateway omits RS** — hospital-level Routing Services already bridge
> Domain 20 → 30 and publish directly into the Cloud databus. Cloud-native
> applications discover those RS output participants via standard DDS
> discovery. A cloud-side RS would add an unnecessary hop. However, if cloud
> services are not directly WAN-accessible, a WAN RS at the cloud boundary
> may serve as a single ingress point (firewall-like) — this is a V3.0
> deployment decision, orthogonal to data-plane routing.

```text
╔═════════════════════════════════════════════════════════════════════════╗
║  CLOUD INSTANCE  ×1                                                     ║
║  (Cloud)                 ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓               ║
║                          ┃         cloud-gateway        ┃               ║
║                          ┃         -------------        ┃               ║
║                          ┃  CDS (discovery)             ┃               ║ 
║                          ┃  Collector (telemetry fwd)   ┃               ║ 
║                          ┗━━━━━━━━━━━━━━━━━━┯━━━━━━━━━━━┛               ║ 
║                                             │                           ║ 
║                                             ▼                           ║  
║  ◄═══════ ENTERPRISE / CLOUD DATABUS (Domain 30) ═════════►  V3.0       ║ 
║  Command Center · MCP Server · Central Collector                        ║
║                                             ▲                           ║
║                                   CLOUD-WAN │                           ║
║  ╔══════════════════════════════════════════╪══════════════════╗        ║
║  ║ HOSPITAL INSTANCE  ×N                    │                  ║        ║
║  ║ (Hospital A, Hospital B, ...)            │                  ║        ║
║  ║                                          │                  ║        ║
║  ║               ┏━━━━━━━━━━━━━━━━━━━━━━━━━━┷━━━┓              ║        ║
║  ║               ┃  *-gateway (per hospital)    ┃              ║        ║
║  ║               ┃  ------------------------    ┃              ║        ║
║  ║               ┃  CDS (discovery)             ┃ ▲ north-     ║        ║
║  ║               ┃  Collector (telemetry fwd)   ┃ │ bound      ║        ║
║  ║               ┃  RS (selective routing)      ┃ │ only       ║        ║
║  ║               ┗━━━━━━━━━━━━━━━━┯━━━━━━━━━━━━━┛              ║        ║
║  ║                                │                            ║        ║
║  ║                                ▼                            ║        ║
║  ║  ◄══════ HOSPITAL INTEGRATION DATABUS (Domain 20) ════►     ║        ║
║  ║  Dashboard · ClinicalAlerts Engine · Room Aggregation       ║        ║
║  ║                                ▲                            ║        ║
║  ║                   HOSPITAL-LAN │                            ║        ║
║  ║   ╔════════════════════════════╪══════════════════╗         ║        ║
║  ║   ║ ROOM INSTANCE  ×M          │                  ║         ║        ║
║  ║   ║ (OR-1, ICU-3, ...)         │                  ║         ║        ║
║  ║   ║                            │                  ║         ║        ║
║  ║   ║       ┏━━━━━━━━━━━━━━━━━━━━┷━━━━━━━┓          ║         ║        ║
║  ║   ║       ┃  *-or1-gateway (per room)  ┃          ║         ║        ║
║  ║   ║       ┃  ------------------------  ┃          ║         ║        ║
║  ║   ║       ┃  CDS (discovery)           ┃ ▲ north- ║         ║        ║
║  ║   ║       ┃  Collector (telemetry fwd) ┃ │ bound  ║         ║        ║
║  ║   ║       ┃  RS (selective routing)    ┃ │ only   ║         ║        ║
║  ║   ║       ┗━━━━━━━━━━━┯━━━━━━━━━━━━━━━━┛          ║         ║        ║
║  ║   ║            OR-LAN │                           ║         ║        ║
║  ║   ║                   ▼                           ║         ║        ║
║  ║   ║  ◄══ PROCEDURE DATABUS (Domain 10) ══════►    ║         ║        ║
║  ║   ║  Robot Arms · Digital Twin                    ║         ║        ║
║  ║   ║                                               ║         ║        ║
║  ║   ║  ◄═ ORCHESTRATION DATABUS (Domain 11) ═══►    ║         ║        ║
║  ║   ║  Controller · Service Hosts                   ║         ║        ║
║  ║   ╚═══════════════════════════════════════════════╝         ║        ║
║  ║                                                             ║        ║
║  ╚═════════════════════════════════════════════════════════════╝        ║
║                                                                         ║ 
╚═════════════════════════════════════════════════════════════════════════╝

Legend:  ╔═══╗ deployable instance   ◄═══► databus   ┏━━━┓ gateway
         ▲ northbound-only flow      ×N replication
```

**Observability plane** (Collector Service forwarding chain — parallel to
data plane):

```text
  ┌──────────┐            ┌──────────┐            ┌──────────┐
  │ Dom 19   │──  fwd  ──►│ Dom 29   │──  fwd  ──►│ Dom 39   │──► Prometheus
  │ (room)   │            │(hospital)│            │ (cloud)  │    Loki
  └──────────┘            └──────────┘            └──────────┘
  room-gateway             hospital-gateway        cloud-gateway
  Collector                Collector               Collector
```

Each gateway's Collector Service receives telemetry on the local observability
domain and forwards it northbound to the next tier's observability domain. The
chain terminates at the cloud Collector, which stores metrics in Prometheus and
logs in Grafana Loki.

Unified data model: all levels share the same IDL type definitions.

### Cross-Domain Topic Routing (A2 Hybrid Architecture)

The medtech suite uses a **cross-domain topic routing** architecture: Routing Service
selectively bridges topics from lower-level domains into a single upper-level integration
domain. This is the recommended RTI layered-databus pattern for upward
telemetry/integration layers where upper-level consumers are observers, not actors.

A topic/type pair is **not inherently bound to a single domain** in DDS. The same topic
name and type can exist on multiple domains — each domain is an independent logical data
space, and Routing Service populates upper domains from lower ones. This is architecturally
valid and explicitly supported by RTI Connext.

**Key principles:**

1. **Lower levels never change to support upper levels.** Adding hospital or cloud visibility
   is purely a Routing Service configuration change.
2. **RS is the sole cross-level gateway.** No application directly spans deployment levels.
3. **Domain tags carry through the bridge** where risk-class isolation is relevant. RS can
   create separate output participants per domain tag on the destination domain.
4. **Each level has one primary integration domain** (offset +0) that receives extracted
   data from below plus any level-native topics.
5. **Reverse control paths** (V2.1+ teleoperation) use dedicated Command domains (offset +2)
   to maintain explicit separation of command traffic from observational data.

> **Escalation trigger for domain-tag isolation at hospital level:** If any future
> requirement introduces a Hospital → Procedure **command** data path (e.g., remote
> emergency stop), the Hospital integration domain (20) must be re-evaluated. Command
> traffic should flow through the dedicated Hospital Command domain (22) with
> appropriate domain tags, not through the integration domain. This change requires
> operator approval and a revision of this section.

### Tiered Infrastructure Deployment

The layered databus requires three RTI infrastructure services — Cloud Discovery
Service, Routing Service, and Collector Service — deployed according to consistent
rules at every level. These rules ensure that discovery bootstrapping, cross-level
data routing, and observability forwarding work uniformly regardless of whether a
deployment instance is a room, a hospital, or a cloud facility.

#### Rule 1 — Cloud Discovery Service Per Instance

Every deployment instance deploys its own CDS instance. Multicast availability
is **never assumed** — CDS is the universal discovery bootstrapper for all
participants within the instance. This applies regardless of whether the instance
interacts with other levels.

| Level | CDS Container | Networks | Role |
|-------|---------------|----------|------|
| Room | `<hospital>-<room>-gateway` (base) | `surgical-net`, `orchestration-net` | Multicast-free discovery for room-local participants (robot service hosts, digital twin, procedure controller). Also the initial peer for upward-facing RS output participants on `hospital-net` |
| Hospital | `<hospital>-gateway` (base) | `hospital-net`, `surgical-net`, `orchestration-net` | Intra-hospital discovery for all participants + upward-facing initial peer for hospital RS and Collector on `wan-net` |
| Cloud (V3.0) | `cloud-gateway` (base) | `wan-net` | Cross-facility discovery for hospital WAN RS output participants, hospital-to-cloud Collector forwarding, and cloud-level applications |

The observing level's CDS also serves as the **initial peer for upward-facing
participants** from the level below. For example, the per-room Routing Service's
Hospital-domain output participant and the room-level Collector Service's
forwarding participant both use the hospital CDS as their initial peer.

> **Room-level CDS exception:** Rooms do not deploy their own CDS in V1.x because
> the hospital CDS is directly reachable from all room networks (it is attached to
> `surgical-net` and `orchestration-net`). If a future deployment model requires
> rooms to operate in network isolation from the hospital (e.g., disconnected OR
> carts), a per-room CDS can be added without architectural changes.

#### Rule 2 — Routing Service as Upward Gateway

If a deployment instance is observed from above, it deploys a Routing Service
whose **upward-facing output participant** uses the upper-level CDS as its
initial peer. This is the sole mechanism by which data flows upward through
the layered databus.

| Gateway | Direction | Input Domains | Output Domain | Upward Initial Peer |
|---------|-----------|---------------|---------------|---------------------|
| Per-room MedtechBridge | Room → Hospital | Domain 10, 11 | Domain 20 | `rtps@udpv4://<hospital>-cds:7400` |
| Per-hospital WAN RS (V3.0) | Hospital → Cloud | Domain 20 | Domain 30 | `rtps@udpv4://wan-cds:7400` |

The upward-facing initial peer is configured as a **hostname**, not an IP
address. Connext 7.6.0 supports hostname resolution in initial peers. For
environments where the upper-level CDS may not be reachable at RS startup
(e.g., hospital CDS starts after room RS), the `dns_tracker_polling_period`
QoS setting in `discovery_config` enables periodic DNS re-resolution so
that the RS output participant discovers the upper-level CDS when it becomes
available — without requiring restart.

```xml
<!-- Upward-facing participant discovery config -->
<discovery_config>
    <dns_tracker_polling_period>
        <sec>5</sec>
        <nanosec>0</nanosec>
    </dns_tracker_polling_period>
</discovery_config>
<discovery>
    <initial_peers>
        <element>rtps@udpv4://hospital-a-gateway:7400</element>
    </initial_peers>
</discovery>
```

#### Rule 3 — Collector Service Per Instance with Forwarding Chain

Every deployment instance deploys a Collector Service on its **level-respective
observability domain** (offset +9). Lower-level Collectors forward telemetry
upward to the next level's Collector using the Collector Service forwarding
capability introduced in Connext 7.6.0.

Forwarding is DDS-based: the Collector receives telemetry on one domain
(`OBSERVABILITY_DOMAIN`) and forwards it on a **separate output domain**
(`OBSERVABILITY_OUTPUT_DOMAIN`). The output domain is the observability
domain of the next level up. The Collector discovers the upstream Collector
via `OBSERVABILITY_OUTPUT_COLLECTOR_PEER`, which points to the upper-level
CDS (or a direct address).

**Observability Forwarding Chain:**

| Level | Collector Input Domain | Collector Output Domain | Forwards To | `OBSERVABILITY_OUTPUT_COLLECTOR_PEER` |
|-------|----------------------|------------------------|-------------|--------------------------------------|
| Room | Domain 19 | Domain 29 | Hospital Collector | `rtps@udpv4://<hospital>-cds:7400` |
| Hospital | Domain 29 | Domain 39 | Cloud Collector (V3.0) | `rtps@udpv4://wan-cds:7400` |
| Cloud (V3.0) | Domain 39 | — (terminal) | Prometheus / Loki / OTEL | — |

This forwarding chain aligns perfectly with the decade-offset domain
numbering: a room Collector forwards on Domain 29 (hospital observability),
where the hospital Collector is already listening. The hospital Collector
aggregates local hospital-level telemetry AND forwarded room telemetry on
Domain 29, then forwards both upward on Domain 39.

**Participant `<collector_initial_peers>` configuration:** All application
participants within a deployment instance configure their Monitoring Library
2.0 `<collector_initial_peers>` to point to the directly-reachable
instance-local Collector Service. This is set via environment variable or
QoS XML and ensures telemetry reaches the local Collector without requiring
multicast or manual peer configuration.

**Docker environment variable configuration:**

```bash
# Room-level Collector (receives from room participants, forwards to hospital)
docker run --rm \
  -e OBSERVABILITY_DOMAIN=19 \
  -e OBSERVABILITY_OUTPUT_DOMAIN=29 \
  -e OBSERVABILITY_OUTPUT_COLLECTOR_PEER="rtps@udpv4://hospital-a-gateway:7400" \
  -e CFG_NAME="NonSecureForwarderLANtoLAN" \
  rticom/collector-service:latest

# Hospital-level Collector (receives from rooms + local, forwards to cloud)
docker run --rm \
  -e OBSERVABILITY_DOMAIN=29 \
  -e OBSERVABILITY_OUTPUT_DOMAIN=39 \
  -e OBSERVABILITY_OUTPUT_COLLECTOR_PEER="rtps@udpv4://wan-cds:7400" \
  -e CFG_NAME="NonSecureForwarderLANtoLAN" \
  rticom/collector-service:latest

# Cloud-level Collector (terminal — exports to Prometheus/Loki, no forwarding)
docker run --rm \
  -e OBSERVABILITY_DOMAIN=39 \
  -e CFG_NAME="NonSecure" \
  rticom/collector-service:latest
```

> **Note:** The upper-level CDS is used as the Collector forwarding initial
> peer because the forwarding Collector uses standard DDS discovery to find
> the upstream Collector. If the upper-level CDS is not yet available at
> startup, `dns_tracker_polling_period` in the Collector's participant XML
> handles late DNS resolution — same as for Routing Service upward peers.

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

| Process | DomainParticipants | Domain Tags / Domains |
|---------|--------------------|-------------|
| Robot controller (standalone) | 1 (+1 Observability) | Procedure `control` |
| Robot Service Host | 1 Orchestration + 1 Procedure `control` (+1 Observability) | Orchestration domain + Procedure `control` |
| Operator console sim (standalone) | 1 (+1 Observability) | Procedure `control` |
| Operator Service Host | 1 Orchestration + 1 Procedure `control` (+1 Observability) | Orchestration domain + Procedure `control` |
| Bedside monitor / vitals sim (standalone) | 1 (+1 Observability) | Procedure `clinical` |
| Clinical Service Host | 1 Orchestration + 1 Procedure `clinical` (+1 Observability) | Orchestration domain + Procedure `clinical` |
| Camera simulator (standalone) | 1 (+1 Observability) | Procedure `operational` |
| Operational Service Host | 1 Orchestration + 1 Procedure `operational` (+1 Observability) | Orchestration domain + Procedure `operational` |
| Procedure context + status publisher (standalone) | 1 (+1 Observability) | Procedure `operational` |
| Device telemetry gateway (standalone) | 1 (+1 Observability) | Procedure `clinical` |
| Digital twin display | 1 (+1 Observability) | Procedure `control` |
| **Procedure Controller** | 1 Orchestration + 2 Procedure read-only (+1 Observability) | Orchestration domain (Domain 11, room-scoped) + Procedure `operational` (read-only: ProcedureStatus, ProcedureContext) + Procedure `control` (read-only: RobotArmAssignment) |
| **Routing Service** (per-room MedtechBridge) | **5** (+1 Observability) | `control` + `clinical` + `operational` (3 on Domain 10) + 1 on Domain 11 (ServiceCatalog extraction) + 1 on Domain 20 (Hospital output, no tag) |

Application logging uses the **RTI Connext Logging API** (`rti::config::Logger` / `rti.connextdds.Logger`), with log messages forwarded to Collector Service via Monitoring Library 2.0. See [technology.md — Logging Standard](technology.md) for details.

Monitoring Library 2.0 creates an additional **+1 dedicated participant** per process on the **Room Observability domain** (Domain 19) to distribute telemetry (metrics, logs, security events) to Collector Service. This participant is created automatically by the MONITORING QoS policy — no application code is needed. See [data-model.md — Domain 19](data-model.md) for the domain definition.

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

### Hospital Integration Domain (Domain 20)

Facility-wide layer for dashboards, clinical decision support, and resource coordination.
Domain 20 is an **integration domain**: it receives extracted data from room-level domains
(Domain 10 and Domain 11) via per-room Routing Service, and also hosts hospital-native
topics published by hospital-level applications that have no room-level counterpart.

**Extracted topics** (bridged from rooms via per-room MedtechBridge RS):
- From Domain 10 (`control` tag): `RobotState` (read-only, for dashboard display)
- From Domain 10 (`clinical` tag): `PatientVitals`, `AlarmMessages`, device telemetry
- From Domain 10 (`operational` tag): `ProcedureStatus`, `ProcedureContext`
- From Domain 11: `ServiceCatalog` (room/GUI discovery for the dashboard room cards)

**Hospital-native topics** (published directly on Domain 20):
- `ClinicalAlert` — computed by the ClinicalAlerts engine from bridged vitals
- `RiskScore` — hemorrhage/complication risk scores
- `ResourceAvailability` — future OR scheduling data

No room-level application publishes directly to Domain 20. The per-room Routing Service
is the sole gateway. This means adding or removing rooms requires zero changes to
hospital-level applications — they discover new data automatically via DDS discovery
as new RS instances bridge additional rooms.

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
> data path (e.g., remote emergency stop, remote parameter adjustment), the reverse
> command traffic must flow through the dedicated **Hospital Command domain (Domain 22)**
> — not through the integration domain (Domain 20). Domain 22 should be evaluated for
> domain-tag isolation at that time, since reverse control makes Hospital-domain
> participants **actors** rather than observers, re-introducing the risk-class
> interference concern that tags are designed to prevent. This change requires operator
> approval and a revision of this section. See also § Teleoperation Routing Service (V2.1).

### Cloud / Enterprise Domain — Domain 30 (V3.0)

Regional or enterprise-wide layer for multi-facility command center operations. Data arrives here only via a WAN-capable Routing Service from individual Hospital domains (Domain 20) — no hospital application publishes directly to the Cloud domain (Domain 30).

The Cloud domain aggregates across facilities the same way the Hospital domain aggregates across ORs:

- **Facility-level partitions** isolate data by hospital: `facility/hospital-a`, `facility/hospital-b`
- **Wildcard partition matching** (`facility/*`) enables enterprise-wide aggregation
- Topics on the Cloud domain are facility-level summaries: `FacilityStatus`, `AggregatedAlerts`, `ResourceUtilization`, `OperationalKPIs`
- A Command Center dashboard (NiceGUI web application, same design standard as Hospital Dashboard) subscribes to the Cloud domain
- A **central Collector Service** aggregates telemetry forwarded from per-hospital Collectors and stores it in Prometheus (metrics) and Grafana Loki (logs) for enterprise-wide observability
- A **Connext Runtime MCP Server** is deployed at the cloud level alongside the central Collector Service. It queries per-hospital Collector Service instances reachable from the cloud network, runs specialized diagnostic tooling to aggregate system health data, and serves as the backend for an AI-agent-powered frontend where users can ask natural-language questions about hospital DDS system health, participant topology, QoS compliance, and operational characteristics across the enterprise

The WAN Routing Service bridge uses the **RTI Real-Time WAN Transport** (`UDPv4_WAN`) for NAT/firewall-traversal cross-site communication, with **Cloud Discovery Service** providing multicast-free discovery across WAN-connected sites. **Connext Security Plugins** are required on all WAN connections — mutual authentication, encrypted data, and governance enforcement. Each hospital runs its own WAN Routing Service instance that selectively forwards Hospital domain data to the Cloud domain.

This layer is deferred to V3.0. The Procedure and Hospital layers are designed so that adding the Cloud layer above them requires **zero changes** to existing modules — only new Routing Service configurations and the Command Center application are added.

### Orchestration Domain (Domain 11 — Room-Scoped)

Infrastructure lifecycle layer for managing Service Hosts and procedure service deployment.
The Orchestration domain is architecturally distinct from the Procedure domain because
orchestration has a fundamentally different lifecycle — Service Hosts and the Procedure
Controller persist across multiple procedures, shift changes, and OR reassignments, whereas
Procedure domain data is scoped to a single active procedure.

Orchestration is **room-scoped** in V1.x: all orchestration participants (Procedure
Controller and Service Hosts) operate within a single room's deployment. The Procedure
Controller runs as a room-level application alongside Service Hosts and the Digital Twin.

```
╔═══════════════════════════════════════════════════════════════════════╗
║  Orchestration Domain (Domain 11) — Per-Room                          ║
║  ─────────────────────────────────────────────────────────────────── ║
║  Host catalog │ Service status │ ServiceHostControl RPC              ║
║  (no domain tags — infrastructure control-plane, not clinical data)  ║
╚═══════════════════════════════════════════════════════════════════════╝
       │                          │
       ▼                          ▼
  Procedure Controller      Service Hosts (distributed)
  (room-level, Orchestration  each also joins Procedure
   domain only)                domain on its service's
                               required domain tag
       │
       └── ServiceCatalog ──► per-room RS ──► Domain 20 (Hospital)
           (bridged for dashboard room/GUI discovery)
```

#### Why a Separate Domain (Not a Domain Tag)

The Procedure domain's domain tags isolate **risk classes** of surgical data. Orchestration is not a risk class — it is an infrastructure control-plane with a different lifecycle, different failure modes, and different security posture:

- **Lifecycle:** A Service Host on a robot cart persists across procedures, shift changes, and OR reassignments. Procedure domain data is ephemeral per-procedure.
- **Scope:** Orchestration may eventually span multiple ORs or the entire facility (V3 upgrade path). Procedure domain data is always OR-local.
- **Failure isolation:** An orchestration failure (controller crash, RPC timeout) must not disrupt an in-progress surgical procedure. Domain-level isolation guarantees this — orchestration discovery, transport, and resource contention are fully separated from surgical data paths.
- **Security:** In V2, orchestration commands (`start_service`, `stop_service`) require different governance than surgical data (e.g., only an authenticated Procedure Controller may issue lifecycle commands).

#### Routing Topology

The Orchestration domain (Domain 11) does **not** sit on the primary data path between the
Procedure and Hospital domains. However, the per-room Routing Service (MedtechBridge)
selectively bridges **`ServiceCatalog`** from Domain 11 → Domain 20 so that the hospital
dashboard can discover room GUIs and Service Hosts without joining Domain 11 directly.

```
Procedure Domain (10) ──► Per-Room RS ──► Hospital Domain (20)
                           (MedtechBridge)
Orchestration (11) ────►  (ServiceCatalog only)
```

The ServiceCatalog bridge is **read-only** — no hospital application writes back to
Domain 11. This is consistent with the A2 hybrid principle: upward extraction only,
no reverse path through the integration domain.

#### The Orchestration Domain Has No Domain Tags

All orchestration participants — the Procedure Controller and all Service Hosts — discover each other directly on the Orchestration domain. Domain tags are not needed because:

- There is no risk-class separation concern — all orchestration traffic is infrastructure
- The Procedure Controller needs to communicate with all Service Hosts regardless of their specialization
- Adding tags would require Service Hosts to create additional participants with no isolation benefit

#### Orchestration Partition Strategy

The Orchestration domain uses **static DomainParticipant-level partitions** for tier isolation.
Partitions are set once at startup and never changed during a participant's lifetime —
avoiding the re-discovery churn that runtime partition changes would cause.
Room and procedure context is carried as data in `ServiceCatalog` property fields, not as
partition strings (see [data-model.md — Domain 11](data-model.md)).

| DomainParticipant Partition | Who Uses It | Meaning |
|-----------------------------|-------------|-------|
| `procedure` | Procedure-tier Service Hosts (managing Domain 10 services), Procedure Controller | All procedure-level orchestration participants |
| `facility` | Facility-tier Service Hosts (managing Domain 20 services) — future | Hospital-level service orchestration |
| `*` | Cross-tier observer (e.g., hospital admin dashboard) — set at startup, never changed | All orchestration tiers |
| `unassigned` | Service Hosts not yet configured with an orchestration tier | Unconfigured host pool |

Publisher/Subscriber Partition QoS is **not used** on the Orchestration domain.

#### Communication Model

The Orchestration domain uses a **hybrid RPC + pub/sub** model:

- **DDS RPC** (`ServiceHostControl` interface, `Pattern.RPC` QoS) — directed, transactional commands from Procedure Controller to a specific Service Host. Each Service Host exposes a uniquely-named RPC service instance (`ServiceHostControl/<host_id>`).
- **Pub/sub** (`ServiceCatalog` and `ServiceStatus` topics, `Pattern.Status` QoS) — asynchronous state distribution. Service Hosts publish per-service capabilities and lifecycle state. TRANSIENT_LOCAL durability enables state reconstruction by late-joining or restarting controllers.

See [data-model.md — Domain 11](data-model.md) for topic definitions and RPC interface specification.

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

### DomainParticipant Partitions

DomainParticipant partitions provide **context-based isolation**. They isolate at the
participant level when the isolation factor lives outside of the data being delivered —
i.e., the operational context (which room, which procedure) rather than the data content itself.

Each surgical procedure instance is launched with a DomainParticipant partition derived
from its context:

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
- Partition is always assigned from startup configuration (constructor parameters or configuration objects) — never hardcoded and never read from environment variables

### Publisher/Subscriber Partitions

Publisher/Subscriber Partition QoS is **not used** in this system. All context-based isolation is handled by DomainParticipant partitions. All data-content-based isolation is handled by content-filtered topics.

If an application must operate across multiple contexts simultaneously, it should either:
- Create multiple DomainParticipant entities (each with its own DomainParticipant partition), or
- Associate a single participant with multiple partition values in its `DomainParticipantQos.partition.name` list

### Content vs. Partition — Choosing the Right Tool

| Isolation need | Tool |
|----------------|------|
| Which room/procedure a participant belongs to | DomainParticipant partition |
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
│  RTI Collector Service           │  Per-hospital telemetry aggregation
│                                  │  (always deployed; forwards to cloud)
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
│  • Central Collector Service    │  Aggregates from per-hospital Collectors
│  • Prometheus · Loki · Grafana  │  Central telemetry visualization
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
| `surgical-net` | Per-OR surgical LAN | Robot sim, surgeon console, digital twin display, bedside monitors, procedure context sim, Service Hosts, room-level GUI containers (twin, controller — dual-homed with `orchestration-net`), per-room gateway (`*-or<N>-gateway`: CDS + RS + Collector, shared namespace) |
| `hospital-net` | Hospital backbone | Hospital gateway (`*-gateway`: CDS + RS + Collector, shared namespace), Hospital Dashboard, ClinicalAlerts engine, Prometheus, Grafana Loki, Grafana |
| `orchestration-net` | Orchestration control-plane | Procedure Controller, room-level GUI containers (for `medtech.gui.room_nav` sibling discovery via ServiceCatalog), Service Hosts (dual-homed: surgical-net + orchestration-net), hospital gateway, per-room gateway — Service Hosts bridge both networks to host surgical services on `surgical-net` while receiving orchestration commands on `orchestration-net` |
| `cloud-net` **(V3.0)** | Enterprise WAN | Cloud gateway (`cloud-gateway`: CDS + Collector, shared namespace), Command Center dashboard — **not created until V3.0 implementation** |

#### Infrastructure Gateway Containers (Shared Network Namespace)

In production, RTI infrastructure services (CDS, Routing Service, Collector Service) for
a given deployment instance are co-located on a single infrastructure appliance. The Docker
simulation preserves this **"container == host"** metaphor using Docker's shared network
namespace (`--network container:<base>`): multiple containers share a single network
identity (IP address, hostname, port space) while running official RTI Docker Hub images
unmodified.

**How it works:** A base container is launched first with all required Docker network
attachments. Subsequent infrastructure containers join the base container's network
namespace via `--network container:<base>`. All containers in the group share the same
IP on every attached network, appear as a single node in topology visualization, and
can communicate via `localhost`. Port conflicts are not a concern because CDS (7400),
RS (admin port), and Collector Service (control/exporter ports) use distinct port ranges.

**Gateway naming convention:** The consolidated infrastructure node is named `gateway`
with a deployment-instance prefix. The name is deliberately service-neutral — it
represents the combined discovery, routing, and telemetry gateway at the boundary of
the deployment instance, not any single RTI service.

| Instance Level | Gateway Hostname | Base Image | Co-located Services |
|----------------|-----------------|------------|---------------------|
| Hospital | `<hospital>-gateway` | `rticom/cloud-discovery-service` | CDS (base) + RS + Collector |
| Room | `<hospital>-<room>-gateway` | `rticom/cloud-discovery-service` | CDS (base) + RS + Collector |
| Cloud (V3.0) | `cloud-gateway` | `rticom/cloud-discovery-service` | CDS (base) + Collector |
| Unnamed hospital | `gateway` | `rticom/cloud-discovery-service` | CDS (base) + RS + Collector |

The base image is `rticom/cloud-discovery-service` at all levels — CDS starts first
(other services need discovery). The `medtech` CLI launches the base container, waits
for its health check, then launches co-located services with `--network container:<gateway>`.

**Topology visualization benefit:** `medtech status --topology` and DockGraph show
consolidated gateway nodes rather than a proliferation of per-service infrastructure
containers, making the simulated topology visually match the production architecture
diagram.
| `cloud-net` **(V3.0)** | Enterprise WAN | WAN Routing Service (dual-homed: hospital-net + cloud-net), Command Center dashboard, Cloud Discovery Service — **not created until V3.0 implementation** |

#### Multi-Hospital Simulation (V1.4)

The `medtech` CLI supports launching multiple independent hospital
instances on a single machine. Each named hospital gets its own set of
isolated Docker networks, its own infrastructure containers, and a NAT
router container that simulates the hospital's uplink to a public WAN.

**Unnamed (default) mode:** `medtech run hospital` (no `--name`) creates
flat, shared Docker networks with no NAT — the simplest path for
single-hospital exploration. This is backward-compatible with all
existing scenarios.

**Named mode:** `medtech run hospital --name hospital-a` creates
per-hospital private networks with explicit subnets and a privileged
NAT router container that performs `iptables MASQUERADE` on a shared
`wan-net`. This simulates production-like network isolation where each
hospital is behind its own NAT boundary, reachable only via the WAN
segment.

##### Network Topology — Named Hospitals

```
medtech_wan-net (172.30.0.0/24) ─── simulated public internet
├── hospital-a-nat    172.30.0.2    (MASQUERADE)
├── hospital-b-nat    172.30.0.3    (MASQUERADE)
└── cloud-gateway     172.30.0.10   (CDS + Collector — V3.0)

medtech_hospital-a_surgical-net (10.10.1.0/24) ─── private
├── hospital-a-gateway              (CDS + RS + Collector — shared namespace)
├── hospital-a-or1-gateway          (per-room CDS + RS + Collector — shared namespace)
├── hospital-a-robot-service-host-or1
├── hospital-a-twin-or1           :8081
└── hospital-a-nat  (dual-homed → wan-net)

medtech_hospital-a_hospital-net (10.10.2.0/24) ─── private
├── hospital-a-gateway              (same node as above — multi-homed)
├── hospital-a-or1-gateway          (same node — multi-homed)
├── hospital-a-gui                :8080
└── hospital-a-nat  (dual-homed → wan-net)

medtech_hospital-a_orchestration-net (10.10.3.0/24) ─── private
├── hospital-a-gateway              (same node — multi-homed)
├── hospital-a-or1-gateway          (same node — multi-homed)
├── hospital-a-controller-or1
└── hospital-a-robot-service-host-or1  (dual-homed: surgical + orchestration)

medtech_hospital-b_surgical-net (10.20.1.0/24) ─── private
├── hospital-b-gateway
├── hospital-b-or4-gateway
├── hospital-b-robot-service-host-or4
├── hospital-b-twin-or4           :9081
└── hospital-b-nat  (dual-homed → wan-net)

medtech_hospital-b_hospital-net (10.20.2.0/24) ─── private
├── hospital-b-gateway
├── hospital-b-or4-gateway
├── hospital-b-gui                :9080
└── hospital-b-nat  (dual-homed → wan-net)
```

##### NAT Router Container

Each named hospital launches a lightweight privileged container
(`hospital-<name>-nat`) that bridges the hospital's private networks
to `wan-net`. The NAT router:

- Is built from `docker/nat-router.Dockerfile` (Alpine + iptables
  installed at build time; env-driven entrypoint for routing rules)
- Accepts `NAT_WAN_IFACE` and `NAT_PRIVATE_SUBNETS` environment
  variables — the CLI passes the appropriate values at `docker run`
- Enables IP forwarding (`net.ipv4.ip_forward=1`)
- Applies `iptables -t nat -A POSTROUTING -o $NAT_WAN_IFACE -j MASQUERADE`
  (cone NAT — destination-independent mapping, compatible with RTI CDS
  NAT traversal per [wan-testing-strategy.md](wan-testing-strategy.md))
- Is dual-homed on the hospital's private networks + `wan-net`
- Does **not** run any DDS participants — it is pure L3 infrastructure

The NAT router ensures that hospital-private containers cannot directly
reach containers on another hospital's networks. Cross-hospital
communication must traverse NAT, exactly as in a real multi-facility
deployment. This infrastructure is reused by V3.0 WAN testing (Tier A
and Tier B) without modification.

##### Per-Hospital Collector Service

Each hospital instance launches an RTI Collector Service container
(`rticom/collector-service`) on `hospital-net` as base infrastructure.
Monitoring Library 2.0, enabled on every DDS participant, automatically
forwards metrics, logs, and security events to the local Collector
Service via its dedicated participant on the Room Observability domain
(Domain 19).

The hospital-level Collector operates as a **forwarding Collector** per
[Rule 3 — Collector Service Per Instance](#rule-3--collector-service-per-instance-with-forwarding-chain).
It receives telemetry from two sources on Domain 29 (Hospital Observability):

1. **Room-level Collectors** — each room's Collector forwards telemetry
   from Domain 19 → Domain 29 via the Collector forwarding chain.
2. **Hospital-level participants** — hospital-native applications
   (dashboard, ClinicalAlerts engine) publish their Monitoring Library
   telemetry directly to Domain 29.

The hospital Collector then forwards the aggregated telemetry upward to
Domain 39 (Cloud Observability) via `OBSERVABILITY_OUTPUT_DOMAIN=39`, using
the WAN-level CDS as the forwarding initial peer (V3.0).

The per-hospital Collector Service serves a **dual role**:

1. **Telemetry pipeline** — aggregates Monitoring Library 2.0
   telemetry from all local participants (room-forwarded + hospital-native)
   and forwards it to a central Collector Service at the cloud level
   (V3.0). The central Collector stores data in Prometheus (metrics) and
   Grafana Loki (logs) for enterprise-wide dashboards and alerting.
2. **Agent-observer data source** — serves as the runtime data
   backend for a specialized **Connext Runtime MCP Server** deployed
   at the cloud level (V3.0). The MCP server queries per-hospital
   Collector Service instances visible to the cloud instance,
   aggregates system health and behavioral data, and presents results
   through a frontend/UI workflow where users ask an AI agent about
   the health, characteristics, or diagnostics of a given hospital
   or set of hospitals.

This dual role is the architectural reason Collector Service is
deployed as always-on base infrastructure in V1.4 rather than as an
optional observability add-on. Even before V3.0 cloud infrastructure
exists, the per-hospital Collector is collecting telemetry that can be
inspected locally via `--observability` (Prometheus + Grafana) or via
RTI Admin Console.

Docker's built-in IPAM handles IP assignment within each network. No
external DHCP is needed — Docker assigns IPs from the configured subnet
on `docker network create --subnet`.

##### Subnet Allocation

| Hospital | surgical-net | hospital-net | orchestration-net |
|----------|-------------|-------------|-------------------|
| unnamed (default) | Docker default | Docker default | Docker default |
| hospital-a | 10.10.1.0/24 | 10.10.2.0/24 | 10.10.3.0/24 |
| hospital-b | 10.20.1.0/24 | 10.20.2.0/24 | 10.20.3.0/24 |
| hospital-c | 10.30.1.0/24 | 10.30.2.0/24 | 10.30.3.0/24 |
| hospital-N | 10.(N×10).1.0/24 | 10.(N×10).2.0/24 | 10.(N×10).3.0/24 |

The CLI allocates subnets by hospital ordinal (based on creation order).
The `wan-net` subnet (`172.30.0.0/24`) is shared and created once.

##### Port Allocation — Named Hospitals

| Hospital | GUI base port | Twin port range |
|----------|--------------|-----------------|
| unnamed (default) | 8080 | 8081+ |
| 1st named (hospital-a) | 8080 | 8081+ |
| 2nd named (hospital-b) | 9080 | 9081+ |
| 3rd named (hospital-c) | 10080 | 10081+ |

##### V3.0 Extension: Cloud Layer

V3.0 adds `medtech run cloud --name <id>` which launches a
`cloud-gateway` container on `wan-net` (CDS + Collector, shared
network namespace), enabling cross-hospital data bridging through the
NAT infrastructure already deployed by V1.4. Hospital-level Routing
Services bridge Domain 20 → 30 directly; cloud-native applications
discover those RS output participants via standard DDS discovery on
Domain 30. The Docker topology, NAT routers, and subnet scheme require
no changes.

> **V3.0 WAN ingress consideration:** If cloud services are not directly
> accessible on the WAN (e.g., behind a firewall), a WAN Routing Service
> at the cloud boundary may serve as a single ingress point — analogous
> to RTI's edge-to-data-center pattern where both sides act as WAN
> gateway endpoints. This is a deployment/security decision, orthogonal
> to the data-plane routing architecture.

#### Split-GUI Deployment (V1.4)

The default simulation (via `medtech launch` or `medtech run` commands)
deploys GUI modules as separate containers to simulate production-like
network separation, where per-OR displays run on the surgical LAN and the
hospital command center runs on the backbone.

**Single hospital (unnamed):**

| Container | Launched By | Network | Serves | Host Port | Simulates |
|-----------|-------------|---------|--------|-----------|-----------|
| `gateway` (base) | `docker run --rm` | `hospital-net`, `surgical-net`, `orchestration-net` | CDS — discovery bootstrapper | — | Hospital infrastructure appliance |
| `gateway` + RS | `docker run --rm --network container:gateway` | (shares `gateway` namespace) | Per-room MedtechBridge: Domain 10+11 → 20 | — | (co-located on gateway) |
| `gateway` + Collector | `docker run --rm --network container:gateway` | (shares `gateway` namespace) | Telemetry aggregation (Domain 29) | — | (co-located on gateway) |
| `medtech-gui` | `docker run --rm` | `hospital-net` | Hospital Dashboard (dashboard only — room-level GUIs served by per-room containers) | 8080 | Hospital control room workstation |
| `medtech-controller-or1` | `docker run --rm` | `surgical-net`, `orchestration-net` | Procedure Controller (OR-1, room-deployed) | 8091 | In-OR orchestration controller |
| `medtech-twin-or1` | `docker run --rm` | `surgical-net`, `orchestration-net` | Digital Twin (OR-1) | 8081 | In-OR display at OR-1 |

> **Room-level GUI containers** (controller, twin, future camera display) are launched
> by `medtech run or`, not by `medtech run hospital`. Each room GUI joins both
> `surgical-net` (for Procedure domain data) and `orchestration-net` (for
> `medtech.gui.room_nav` sibling discovery via `ServiceCatalog`). Each is served
> on its own host port — separate origins from the hospital dashboard.

**Named hospital (`--name hospital-a`):**

| Container | Launched By | Network | Host Port |
|-----------|-------------|---------|-----------|
| `hospital-a-nat` | `docker run --privileged` | private nets + `wan-net` | — |
| `hospital-a-gateway` (base: CDS) | `docker run --rm` | `hospital-a_hospital-net`, `hospital-a_surgical-net`, `hospital-a_orchestration-net` | — |
| `hospital-a-gateway` + RS | `docker run --rm --network container:hospital-a-gateway` | (shared namespace) | — |
| `hospital-a-gateway` + Collector | `docker run --rm --network container:hospital-a-gateway` | (shared namespace) | — |
| `hospital-a-gui` | `docker run --rm` | `hospital-a_hospital-net` | 8080 |
| `hospital-a-controller-or1` | `docker run --rm` | `hospital-a_surgical-net`, `hospital-a_orchestration-net` | 8091 |
| `hospital-a-twin-or1` | `docker run --rm` | `hospital-a_surgical-net`, `hospital-a_orchestration-net` | 8081 |

Infrastructure services within a gateway group share a single network identity.
The `--network container:<base>` flag causes the RS and Collector containers to
join the base CDS container's network namespace — they share the same IP address,
hostname, and port space on all attached networks. This mirrors a production
deployment where CDS, RS, and Collector run as co-located processes on a single
infrastructure appliance.

> **Docker Compose equivalent:** `network_mode: "service:<base-service>"` provides
> the same shared-namespace behavior in Compose files.

Each twin container runs `python -m surgical_procedure.digital_twin` in
standalone mode (`__main__` guard). It creates its own `control`-tag
DomainParticipant on `surgical-net`, subscribes to `RobotState`,
`RobotCommand`, `SafetyInterlock`, `OperatorInput`, and
`RobotArmAssignment`, and serves a NiceGUI web page on its container
port 8080 (mapped to a unique host port).

The central `medtech-gui` container runs the hospital dashboard on `hospital-net`.
It subscribes to Domain 20 (Hospital integration) for all procedure, vitals, and alert
data. It discovers room-level GUIs (controller, twin) via RS-bridged `ServiceCatalog`
`gui_url` properties from Domain 11 → Domain 20. Room GUIs are served by per-room
containers on separate origins — navigation from the dashboard to a room opens a
**new browser tab** (with the `open_in_new` icon), exactly as a production deployment
would behave.

**Room-level GUI navigation:** Each room GUI container (controller, twin, etc.) embeds a
shared navigation module (`medtech.gui.room_nav`) that creates a read-only Orchestration
domain participant, subscribes to `ServiceCatalog` filtered by `room_id`, and renders a
floating nav pill with buttons for each discovered sibling GUI. This enables same-tab
horizontal navigation between room GUIs (e.g., controller → twin → future camera display)
without infrastructure coupling. Room GUIs have **no upward visibility** to the hospital
level — a room can be deployed standalone without a hospital instance above it. The module
is deployment-agnostic — it works identically on Docker, physical hardware, or mixed
environments.

**`gui_url` browser reachability:** Each GUI container sets
`MEDTECH_GUI_EXTERNAL_URL` in its environment (e.g.,
`http://localhost:8081`). The service builds its advertised `gui_url`
from this value, ensuring the URL is reachable by the developer's
browser via Docker port mapping. When `MEDTECH_GUI_EXTERNAL_URL` is
unset, the service falls back to its container-internal address.

**Dynamic room addition:** The developer adds ORs at any time via
`medtech run or --name OR-5` (or `medtech run or --name OR-5 --hospital hospital-a`
for named hospitals). New containers join the existing Docker networks,
discover CDS, and appear automatically in the hospital dashboard room cards via
bridged `ServiceCatalog`. When `--name` is omitted, the CLI auto-generates a
unique name (e.g., `OR-1`, `OR-2`). No compose override files or
template generation is required.

**Topology visualization:** `medtech status --topology` renders an ASCII
tree of running containers grouped by Docker network (see
[tooling.md](tooling.md) § DockGraph). For a richer interactive view,
[DockGraph](https://github.com/dockgraph/dockgraph) can be launched as
an optional sidecar (`medtech launch --dockgraph`) — it presents a
real-time, zoomable graph of containers, networks, and their
relationships in the browser at `http://localhost:7800`.

### Docker Compose Service Startup Ordering

Docker Compose `depends_on` with health checks must enforce the following startup order
to prevent intermittent initialization failures:

1. **Gateway container (CDS base)** starts first and reports healthy (CDS listening on
   port 7400) before any other container starts. All participants use the gateway
   hostname as their initial peer; if it is unavailable at startup, discovery is delayed
   and initialization time budgets may be exceeded.
2. **Gateway co-located services (RS, Collector)** start after the CDS base is healthy,
   within the same network namespace. Routing Service must be discoverable on both
   networks before bridged data can flow. Collector Service should be available before
   application participants start so that Monitoring Library 2.0 telemetry is captured
   from the beginning.
3. **Surgical procedure instances** start after the gateway is healthy.
   They operate entirely on `surgical-net` and do not depend on Routing Service or
   Hospital domain services.
4. **Hospital domain applications** (dashboard, ClinicalAlerts engine) start after the
   gateway (including RS) is healthy.
5. **Visualization stack** (Prometheus, Grafana Loki, Grafana) — when enabled via
   `--observability` for local development, or as cloud infrastructure in V3.0 —
   has no startup ordering dependency with application services.

Health checks use the simplest reliable method per service:
- Gateway (CDS base): TCP port check on CDS listening port (7400)
- Gateway (RS co-located): TCP port check on RS administration port
- Application containers: a process-alive check (`CMD ["pgrep", "-f", "<process>"]`)

### Transport Configuration

Transport behavior is configured via XML QoS profiles, never in application code. The deployment-specific transport snippet is selected at XML parse time via the `MEDTECH_TRANSPORT_PROFILE` environment variable (defaulting to `Default` via `<configuration_variables>` in `Participants.xml`).

All transport snippets and the shared `Participants::Transport` profile live in a single file (`Participants.xml`). The `Transport` QoS library contains one snippet per deployment context:

| Snippet | SHMEM | UDPv4 | Multicast | Discovery Peers |
|---------|-------|-------|-----------|----------------|
| `Transport::Default` | Enabled | Enabled | Enabled | Connext defaults |
| `Transport::Docker` | Enabled | Enabled | Disabled | `builtin.shmem://`, `builtin.udpv4://localhost`, CDS |

SHMEM is enabled in both — it benefits intra-container (Docker) and intra-host (production) communication.

The `Participants::Transport` profile composes `BuiltinQosSnippetLib::Transport.UDP.AvoidIPFragmentation` (common to all deployments) and `Transport::$(MEDTECH_TRANSPORT_PROFILE)` (selected at parse time).

#### Docker Containers

Containers set `MEDTECH_TRANSPORT_PROFILE=Docker` which selects the Docker transport snippet. This snippet:
- Disables multicast (`multicast_receive_addresses` cleared, `dds.transport.UDPv4.builtin.multicast_enabled=0`)
- Sets explicit discovery peers: SHMEM and localhost for intra-container, CDS for cross-container
- Composes `BuiltinQosSnippetLib::Transport.UDP.AvoidIPFragmentation`

```xml
<domain_participant_qos>
    <discovery>
        <initial_peers>
            <element>builtin.shmem://</element>
            <element>builtin.udpv4://localhost</element>
            <element>rtps@udpv4://gateway:7400</element>
        </initial_peers>
        <multicast_receive_addresses/>
    </discovery>
    <property>
        <value>
            <element>
                <name>dds.transport.UDPv4.builtin.multicast_enabled</name>
                <value>0</value>
            </element>
        </value>
    </property>
</domain_participant_qos>
```

#### Intra-Machine / Intra-Process Communication

Shared memory (SHMEM) transport is appropriate and efficient for communication between participants on the same physical host or within the same process. When all communicating participants are co-located:
- Enable SHMEM transport for those participants
- UDPv4 may still be enabled as a fallback for participants that cross host boundaries
- Security policy implications for SHMEM-only paths are deferred to [vision/security.md](security.md)

#### Hostname-Based Initial Peers and DNS Tracking

Upward-facing participants (RS output, Collector forwarding) use **hostname-based
initial peers** (e.g., `rtps@udpv4://hospital-a-gateway:7400`) rather than hardcoded
IP addresses. This decouples peer configuration from IP assignment and allows the
same configuration to work across different Docker network setups.

Connext 7.6.0 resolves hostnames at participant creation by default. In
deployments where the target host may not be reachable at startup (e.g., the
hospital CDS starts after the room RS), configure `dns_tracker_polling_period`
to enable periodic DNS re-resolution:

```xml
<discovery_config>
    <dns_tracker_polling_period>
        <sec>5</sec>
        <nanosec>0</nanosec>
    </dns_tracker_polling_period>
</discovery_config>
```

This setting is applied to upward-facing participant profiles in `Participants.xml`.
Intra-level participants (those using only the local CDS) do not need DNS tracking
because the local CDS is guaranteed to start before application participants via
Docker Compose health check ordering.

### Cloud Discovery Service

Hospital networks commonly restrict UDP multicast for security reasons, making standard DDS unicast/multicast discovery unreliable. RTI Cloud Discovery Service provides multicast-free participant discovery:

- Participants configure Cloud Discovery Service as their initial peer instead of multicast addresses
- Cloud Discovery Service acts as a rendezvous server, brokering discovery between participants without requiring multicast routing
- Each deployment instance deploys its own CDS (see [Rule 1 — CDS Per Instance](#rule-1--cloud-discovery-service-per-instance))
- The upper-level CDS also serves as the initial peer for upward-facing RS and Collector participants from the level below
- Primary + backup Cloud Discovery Service instances recommended for high availability

**Design decision (resolved):** At the hospital level, the CDS runs as the base
process of the consolidated `<hospital>-gateway` container
(`rticom/cloud-discovery-service` from Docker Hub), attached to `hospital-net`,
`surgical-net`, and `orchestration-net`. This gives all participants across all
hospital networks a direct discovery path — and RS + Collector co-locate in the
same network namespace. Configuration and deployment details are in
[Phase 1 Step 1.4](../implementation/phase-1-foundation.md).

### Routing Service Deployment (Per-Room MedtechBridge)

Each room deploys its own Routing Service instance (the **MedtechBridge**), attached to
`surgical-net`, `orchestration-net`, and `hospital-net` (tri-homed). It is the **sole
cross-level gateway** between room-level domains and the Hospital integration domain.

It bridges:
- Domain 10 → Domain 20: `ProcedureStatus`, `ProcedureContext`, patient vitals, alarm messages, device telemetry
- Domain 10 (`control` tag) → Domain 20: `RobotState` (read-only, for dashboard display)
- Domain 11 → Domain 20: `ServiceCatalog` (room/GUI discovery for the dashboard room cards)

For the `control`-tag bridge, Routing Service creates a DomainParticipant on Domain 10
with the `control` domain tag (configured in its participant XML) in order to subscribe
to `RobotState`. It publishes the bridged data on the Domain 20 output participant, which
has no domain tag restriction. This cross-tag route is explicitly configured in the Routing
Service XML — it does not imply that `control`-tag data is generally accessible outside
its tag.

Only explicitly configured topics cross this boundary. Routing Service uses separate sessions for different traffic classes:
- **StateSession** — low-rate status/state topics
- **StreamingSession** — higher-rate telemetry if needed
- **ImagingSession** — imaging metadata (future)

### Routing Service Partition Mapping

On the **Domain 10 (Procedure) input side**, the per-room Routing Service participant uses
the wildcard DomainParticipant partition `room/*/procedure/*` so it discovers all procedure
instances within its room and receives data from all active procedures.

On the **Domain 20 (Hospital) output side**, the Routing Service output participant also uses
DomainParticipant partition `room/*/procedure/*`. RTI Routing Service 7.6.0 does **not**
automatically propagate participant-level partitions from the input participant to the output
participant — see `incidents.md` INC-070. There is no `<propagation_qos>` element for
participant-level partitions in RS 7.6.0. Both RS participants must be configured
explicitly with matching wildcard partitions.

On the **Domain 11 (Orchestration) input side**, the Routing Service participant uses the
`procedure` DomainParticipant partition (matching the Orchestration partition strategy) to
discover Service Host `ServiceCatalog` publications.

Hospital domain consumers (e.g., the dashboard) subscribe with wildcard partition
`room/*/procedure/*` and use content-based filtering on data fields (e.g.,
`ProcedureContext.room_id`) to narrow to a specific room — room narrowing is an
application-layer filter, not a partition change.

Hospital-native topics (e.g., `ClinicalAlert`, `RiskScore`) that originate on Domain 20
and are published directly by hospital-level applications (ClinicalAlerts engine) do **not**
use room partitions. They use the default (empty) partition unless the publishing application
explicitly sets one for multi-context purposes.

### WAN Routing Service Deployment (V3.0)

A second Routing Service tier bridges Domain 20 (Hospital) → Domain 30 (Cloud) traffic
across facility boundaries. Each hospital runs a WAN Routing Service instance on `cloud-net`
(dual-homed to `hospital-net` + `cloud-net`).

It bridges:
- Domain 20 → Domain 30: facility status, aggregated clinical alerts, resource utilization, operational KPIs

WAN transport uses the RTI Real-Time WAN Transport (`UDPv4_WAN`) for NAT/firewall traversal, Cloud Discovery Service for cross-site discovery, and Connext Security Plugins for authentication and encryption. The WAN Routing Service follows the same architectural principles as the per-room MedtechBridge — only explicitly configured topics cross the boundary, and no hospital application publishes directly to the Cloud domain.

### Teleoperation Routing Service (V2.1)

V2.1 teleoperation introduces a **reverse data path** from the Hospital
and Cloud domains into the Procedure domain for remote operator control.
This is a fundamentally different data flow from the existing Procedure →
Hospital observational bridge and requires dedicated routing
infrastructure.

#### Ownership Strength Lowering

The surgeon console application publishes `OperatorInput` with a fixed
ownership strength (200) regardless of its deployment location. When the
console is deployed at the hospital or cloud level, its `OperatorInput`
samples reach the Procedure domain via Routing Service. The Routing
Service output DataWriter is configured with a **lower ownership
strength** than the console's native strength:

| Route | Input (source domain) | Output Ownership Strength | Notes |
|-------|----------------------|---------------------------|-------|
| Local console (no RS) | Domain 10 `control` (direct) | 200 (native) | No routing — direct write |
| Hospital → Procedure | Domain 22 (Hospital Command) | 100 | RS output writer QoS override |
| Cloud → Procedure | Domain 32 (Cloud Command) | 50 | WAN RS output writer QoS override |

This pattern ensures that when a local console is present and alive, its
higher-strength samples always win. If the local console loses
liveliness, the Routing Service-bridged samples from the hospital or
cloud console automatically become the active source on the robot-side
reader — standard DDS exclusive ownership behavior.

#### Separate Control-Tag Domain Route

The reverse teleoperation route uses a **separate `domain_route`** from
the existing observational bridge. It creates dedicated
DomainParticipants with the `control` domain tag on the Procedure domain
side. This enforces the same risk-class isolation in the routing
infrastructure that exists between direct Procedure domain participants.

The control-tag route is architecturally independent:
- Separate participants (different domain tags)
- Separate sessions (different QoS and topic sets)
- Separate failure domains (a fault in the observational bridge does not
  affect the control-tag route, and vice versa)

#### Hospital Domain Tag Re-Evaluation

The reverse data path makes Hospital-domain participants **actors** (they
originate control data) rather than observers. Per the escalation trigger
in § Hospital Integration Domain, this requires re-evaluating the Hospital
domain for domain-tag isolation. Under the A2 hybrid architecture, reverse
control traffic flows through the dedicated **Hospital Command domain
(Domain 22)** — not through the integration domain (Domain 20). The V2.1
design must determine whether a `control` tag is needed on Domain 22 for
the remote operator's outbound data path.

### Safe-Hold Mode (V2.1)

Safe-hold is the robot operating mode entered when control authority is
uncertain or in transition. It is the bridge between DDS-level ownership
arbitration and application-level safety requirements.

See [data-model.md — V2.1 Forward Design Notes](data-model.md) for the
full behavioral specification including entry triggers, robot behavior,
exit conditions, emergency safe-stop, and reclaim behavior.

**Key architectural implications:**

- Safe-hold is **per-procedure, not per-arm.** When the active operator
  loses authority, all arms in the procedure enter safe-hold
  simultaneously. This is consistent with procedure-wide exclusive
  ownership — split authority (some arms holding, others accepting new
  commands) is a safety hazard.
- `RobotState` continues publishing during safe-hold (`operational_mode
  = PAUSED`). The robot is not silent — it actively reports its held
  state. This is critical for the returning or backup operator to assess
  the situation.
- `SafetyInterlock` is published with `interlock_active = true` only in
  the emergency safe-stop case (no operator available). Safe-hold itself
  is not an interlock — it is a recoverable transitional state.

---

## Security (Deferred)

Security implementation is deferred to a later phase. Architecture and posture are defined in [vision/security.md](security.md). All modules are designed to be security-compatible when the security layer is enabled.
