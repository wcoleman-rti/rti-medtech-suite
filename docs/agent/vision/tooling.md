# Tooling & Diagnostics

This document defines the debugging, troubleshooting, and diagnostic tools available
to developers and agents working on the medtech suite. It covers both RTI-provided
tools and project-specific utilities.

All tools are located under `tools/` in the project root. Each tool has a README
or usage section below. The `tools/README.md` indexes all available tools and maps
common debugging scenarios to the appropriate tool.

---

## RTI-Provided Tools

These tools ship with RTI Connext Professional or are available as RTI services.
They require no project-specific code but benefit from documented usage patterns
for this project's topology.

### RTI Admin Console

**What:** GUI application for live inspection of a DDS system — participants, topics,
endpoints, QoS policies, data visualization, and subscription matching.

**When to use:**

- "Why aren't my endpoints matching?" — inspect discovered participants and endpoints,
  check QoS compatibility reports
- "What data is flowing on this topic?" — subscribe to any topic and view live samples
- "How many participants exist and what domains are they on?" — system-wide topology view

**How to connect in this project:**

Admin Console must discover participants in the Docker network. Two approaches:

1. **Via Cloud Discovery Service** — configure Admin Console's initial peers to point
   to the Cloud Discovery Service container's forwarded port. This discovers all
   participants across all domains that Cloud Discovery Service serves.
2. **Docker host networking** — run Admin Console on the Docker host with peer
   addresses pointing to container IPs on the Docker bridge networks.

Usage documentation: `tools/admin-console.md`

### RTI DDS Spy (`rtiddsspy`)

**What:** CLI tool that subscribes to all topics on a domain and prints received
samples to stdout. Lightweight alternative to Admin Console for quick checks.

**When to use:**

- "Is this topic publishing?" — quick verification without a GUI
- "What does the data look like?" — inspect sample contents
- "Are partitions working?" — run spy with a specific partition and verify isolation

**How to run in this project:**

```bash
# Source the project environment first
source install/setup.bash

# Spy on the Procedure domain (all topics, all partitions)
rtiddsspy -domainId 10 -printSample

# Spy on the Hospital domain
rtiddsspy -domainId 11 -printSample

# Spy with a specific partition
rtiddsspy -domainId 10 -partition "room/OR-3/*" -printSample
```

Usage documentation: `tools/dds-spy.md`

### RTI Observability Dashboards (Grafana)

**What:** Pre-built Grafana dashboards that visualize Monitoring Library 2.0 telemetry
collected via Collector Service and stored in Prometheus. Already part of the project's
observability stack (`--profile observability`).

**When to use:**

- Latency analysis — per-topic sample delivery latency histograms
- Throughput monitoring — publication and reception rates per topic
- Deadline miss tracking — which readers are missing deadlines and when
- Discovery timeline — participant creation and endpoint matching events
- Resource monitoring — participant counts, matched endpoints, memory

**Key dashboard panels for common debugging scenarios:**

| Scenario | Dashboard / Panel |
|----------|-------------------|
| "OperatorInput latency is too high" | Sample Latency dashboard → filter by topic `OperatorInput` → p50 and p99 panels |
| "Samples are being lost" | Data Flow dashboard → Samples Lost panel → filter by reader |
| "Deadline missed on PatientVitals" | QoS Events dashboard → Deadline Missed panel → filter by topic |
| "Too many / too few participants" | System Overview dashboard → Participant Count panel |
| "Routing Service isn't forwarding" | Routes dashboard → Input/Output sample rate per route |
| "Discovery is slow" | Discovery dashboard → Time to first match per participant |

Access: `http://localhost:3000` when the observability profile is running.

---

## Project-Specific Tools

These are diagnostic utilities built specifically for the medtech suite. They are
implemented during Phase 1 or Phase 2 and live under `tools/`.

### `medtech-diag` — System Health Diagnostic

**What:** A CLI tool that performs a comprehensive health check of the running medtech
suite. It connects to the DDS domains, inspects the system topology, and reports
issues.

**Checks performed:**

| Check | What It Verifies |
|-------|------------------|
| Participant discovery | All expected participants are discovered on each domain (Procedure, Hospital, Observability) |
| Endpoint matching | All expected DataWriter/DataReader pairs are matched |
| Partition topology | Active partitions match the expected room/procedure configuration |
| QoS profile resolution | Topics resolve to their intended QoS profiles |
| Unmatched endpoints | Reports any endpoints that exist but have no matching peer (possible QoS incompatibility) |
| Liveliness status | All writers are alive; reports any liveliness-lost conditions |
| Application logging health | User-category log messages are being forwarded by Monitoring Library 2.0 to Collector Service |
| Cloud Discovery Service reachability | CDS is responding on its configured port |
| Observability stack (optional) | Prometheus, Collector Service, and Grafana are reachable |

**Interface:**

```bash
# Full health check (all domains, all checks)
python tools/medtech-diag/diag.py

# Check specific domain
python tools/medtech-diag/diag.py --domain procedure

# Check specific aspect
python tools/medtech-diag/diag.py --check endpoints

# JSON output (for CI integration)
python tools/medtech-diag/diag.py --format json
```

**Implementation:** Python script using `rti.connext` to join each domain as a
temporary participant, inspect discovered entities via built-in discovery topics
(`DCPSParticipant`, `DCPSPublication`, `DCPSSubscription`), and report findings.
The diagnostic participant is short-lived and read-only — it does not publish
application data.

**Implementation phase:** Phase 2 (after all surgical entities exist to inspect).

### `partition-inspector` — Active Partition Scanner

**What:** A lightweight subscriber that joins the Procedure domain with a `room/*`
wildcard partition, discovers all active partitions, and reports which instances
are publishing on each.

**When to use:**

- "How many ORs are running?" — enumerate active room partitions
- "Which publishers are in OR-3?" — list entities in a specific partition
- "Is my new instance's partition correct?" — verify partition assignment

**Interface:**

```bash
# Scan all active partitions
python tools/partition-inspector.py

# Watch mode (continuous, updates on discovery changes)
python tools/partition-inspector.py --watch

# Filter by room
python tools/partition-inspector.py --filter "room/OR-3/*"
```

**Implementation phase:** Phase 2.

### QoS Compatibility Checker (Pre-Flight)

**What:** A pre-flight validation script that loads all QoS XML profiles and
simulates the topic-filter resolution for every defined writer/reader topic pair.
Reports any RxO (Requested/Offered) incompatibilities before the system runs.

**When to use:**

- After modifying any QoS XML file
- After adding a new topic or changing a topic filter
- As part of the CI pipeline (catches QoS mismatches at build time)

**Checks performed:**

- Load all XML via `NDDS_QOS_PROFILES` using the default QosProvider
- For each topic defined in the domain library:
  - Resolve the writer QoS via topic filter
  - Resolve the reader QoS via topic filter
  - Check RxO policy compatibility (reliability, durability, ownership, deadline,
    liveliness, etc.)
- Report any incompatible pairs with the specific policy mismatch

**Interface:**

```bash
# Run QoS compatibility check
python tools/qos-checker.py

# Verbose output (show resolved QoS per topic)
python tools/qos-checker.py --verbose
```

**Implementation phase:** Phase 1 (Step 1.10 — QoS Compatibility Checker
& Tool Scaffolding).

---

## Tool Directory Structure

```
tools/
├── README.md                  # Index of all tools + scenario-to-tool mapping
├── admin-console.md           # RTI Admin Console connection guide for this project
├── dds-spy.md                 # RTI DDS Spy usage examples for this project
├── medtech-diag/
│   ├── diag.py                # System health diagnostic CLI
│   └── README.md
├── partition-inspector.py     # Active partition scanner
└── qos-checker.py             # QoS compatibility pre-flight checker
```

---

## Scenario-to-Tool Quick Reference

| Debugging Scenario | First Tool to Try | Second Tool |
|-------------------|-------------------|-------------|
| Endpoints not matching | `qos-checker.py` (offline) → Admin Console (live) | `medtech-diag --check endpoints` |
| No data flowing on a topic | `rtiddsspy` on the target domain | Grafana Data Flow dashboard |
| Latency is too high | Grafana Sample Latency dashboard | `medtech-diag` (check for unexpected participants or endpoint bloat) |
| Samples being lost | Grafana Data Flow → Samples Lost panel | `rtiddsspy` on both publisher and subscriber sides |
| Deadline missed | Grafana QoS Events dashboard | `medtech-diag --check liveliness` |
| Partition isolation broken | `partition-inspector.py` | `rtiddsspy` with and without partition filter |
| Discovery is slow or failing | `medtech-diag --check discovery` | Admin Console → participant discovery view |
| Routing Service not forwarding | Grafana Routes dashboard | `rtiddsspy` on both source and destination domains |
| Unknown system state after crash | `medtech-diag` (full check) | Grafana System Overview |
| New module not connecting | `medtech-diag --check endpoints` | `qos-checker.py --verbose` |
