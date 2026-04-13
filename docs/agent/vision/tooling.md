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
- "Are partitions working?" — run spy without a partition filter (see note below) and verify isolation

> **Note — rtiddsspy and DomainParticipant partitions:** rtiddsspy's `-partition` flag
> sets the spy's **Publisher/Subscriber** partition QoS, which is **not** the same as the
> **DomainParticipant**-level partition this project uses. Since application DataWriters
> in this project do not set Pub/Sub partitions, the spy's `-partition` flag will not
> filter data by room — the spy either sees all data (if its DomainParticipant partition
> matches) or none. Room-level partition filtering via rtiddsspy is not supported for this
> project's partition scheme. Use `partition-inspector.py` and `medtech-diag` for
> partition diagnostics (noting their known limitations in `incidents.md` INC-041).

**How to run in this project:**

```bash
# Spy on the Procedure domain (all topics, all DomainParticipant partitions visible)
rtiddsspy -domainId 10 -printSample

# Spy on the Hospital domain
rtiddsspy -domainId 11 -printSample

# NOTE: The -partition flag sets Pub/Sub partition QoS on the spy, NOT DomainParticipant
# partition. Since this project uses DomainParticipant partitions only, -partition
# does NOT filter by room and may prevent the spy from receiving data at all.
# Omit -partition and use content filtering or medtech-diag for targeted inspection.
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
wildcard DomainParticipant partition, discovers all active partitions from endpoint
builtin topics, and reports which instances are publishing on each.

> **Known limitation (INC-041):** RTI Connext Python 7.6.0 does not expose
> `DomainParticipant` partition in `ParticipantBuiltinTopicData`. The `partition`
> field on `PublicationBuiltinTopicData` / `SubscriptionBuiltinTopicData` reflects
> **Publisher/Subscriber** partition QoS, which application code does not set.
> As a result, `partition-inspector.py` currently reports no active partitions.
> This tool is retained for future use when the API limitation is resolved or a
> `user_data`-based propagation alternative is implemented.

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

### `medtech` CLI — Build, Launch & Scale

**What:** A locally-installed Python console script (`medtech`) that
provides a single entry point for the developer quick-start workflow:
build the project, launch simulation scenarios in Docker, dynamically
add operating rooms, and check system status.

**Design philosophy:** The CLI is a thin wrapper over native tools
(`cmake`, `docker run`). Every command prints the exact underlying
invocation before running it, so developers can run or adapt the native
commands directly.

**When to use:**

- "I just cloned the repo — how do I build and run it?" → `medtech build && medtech launch`
- "I want to add another OR to the running simulation" → `medtech run or --room-id OR-5`
- "What's running and where do I open it?" → `medtech status`
- "I want to tear everything down" → `medtech stop`

**Interface:**

```bash
# Build and install
medtech build

# Launch the default distributed simulation (2 ORs, split GUI)
medtech launch
# equivalent to:
#   medtech run hospital
#   medtech run or --room-id OR-1
#   medtech run or --room-id OR-3

# Launch a specific scenario
medtech launch minimal

# List available scenarios
medtech launch --list

# Start infrastructure + central GUI only
medtech run hospital
# Running: docker run --rm -d --name cloud-discovery-service ...
# Running: docker run --rm -d --name routing-service ...
# Running: docker run --rm -d --name medtech-gui -p 8080:8080 ...

# Add an OR (service hosts + digital twin)
medtech run or --room-id OR-5
# Running: docker run --rm -d --name clinical-service-host-or5 \
#   --network medtech_surgical-net -e ROOM_ID=OR-5 ...
# Running: docker run --rm -d --name robot-service-host-or5 ...
# Running: docker run --rm -d --name medtech-twin-or5 -p 8083:8080 ...
# ✓ OR-5 started — twin at http://localhost:8083/twin/OR-5

# Show running containers and URLs
medtech status

# Show topology: containers grouped by Docker network
medtech status --topology

# Tear down everything
medtech stop
```

**Scenarios** (used with `medtech launch`):

| Scenario | Description |
|----------|-------------|
| `distributed` (default) | Split GUI: dashboard + controller on `hospital-net`, per-OR twins on `surgical-net`, 2 ORs |
| `unified` | Monolithic GUI (pre-V1.4 behavior), 2 ORs — no separate twin containers |
| `minimal` | Single OR, split GUI, no observability stack |

**Implementation phase:** Phase SIM (Distributed Simulation & CLI).

### DockGraph — Docker Topology Visualizer (Optional)

**What:** [DockGraph](https://github.com/dockgraph/dockgraph) is a
self-hosted, real-time Docker infrastructure visualizer. It renders
containers, networks, volumes, and their relationships as an interactive,
zoomable graph in the browser.

**Why it fits:** Unlike container management tools (Portainer, lazydocker,
dozzle), DockGraph focuses on **topology** — showing which containers
are on which networks, `depends_on` edges, volume mounts, and
cross-network connections. This is exactly the view needed to understand
the medtech suite’s multi-network Docker simulation.

**Key features:**

- Live topology graph with network grouping (containers visually
  clustered by `surgical-net`, `hospital-net`, `orchestration-net`)
- Compose-aware — mount the compose file and it shows services that
  haven’t started yet
- Real-time — watches Docker event stream; new `medtech run or`
  containers appear within seconds
- Detail panels — click any container to see stats, ports, mounts,
  env, labels, logs, health, network config
- Read-only API — cannot start, stop, or modify containers
- Self-excluding — hides its own container from the graph
- Single container, single port (7800), read-only Docker socket mount

**Quick start:**

```bash
# Standalone
docker run -d -p 7800:7800 \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  --label dockgraph.self=true \
  dockgraph/dockgraph

# Or via the medtech CLI
medtech launch --dockgraph
```

Open `http://localhost:7800` to see the full Docker topology.

**Maturity note:** DockGraph is a young project (first release early
2026, BSL 1.1 license converting to Apache 2.0 after 4 years). It is
recommended as an **optional** developer convenience, not a hard
dependency. The built-in `medtech status --topology` provides a
zero-dependency ASCII fallback for terminal-based inspection.

**Integration:** DockGraph is not part of the medtech build or test
pipeline. It is documented here as a recommended optional sidecar
for topology exploration during development.

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

## WAN Test Infrastructure

**Authoritative reference:** [`wan-testing-strategy.md`](wan-testing-strategy.md)

WAN-spanning behaviors introduced in V3.0.0 — `UDPv4_WAN`, Cloud Discovery Service
NAT traversal, and Routing Service WAN bridge — are validated with a Docker-native
topology that uses **privileged router containers** rather than a network emulation
framework. The topology provides both WAN impairment injection and real NAT, which
together exercise the full CDS locator-resolution and peer-to-peer discovery path.

### Inject with Linux, observe with RTI

The governing principle for WAN tests is to separate the roles of the two tool
categories:

- **Linux `tc` / `iptables`** — inject impairments (delay, loss, jitter, bandwidth
  cap, blackhole) and model NAT boundaries. This is infrastructure work; it does
  not make assertions about DDS behavior.
- **RTI tooling** — observe and assert DDS behavior: route state, locator resolution,
  throughput, delivery latency, reconnection timing. These are the pass/fail signals
  for WAN test cases.

| WAN Observation Need | Tool |
|---------------------|------|
| Routing Service route state and sample counts | Admin Console → Routing Service view |
| Throughput / latency per topic under impairment | Grafana Data Flow and Sample Latency dashboards |
| CDS locator resolution behavior | CDS `-verbosity 5` log output |
| NAT translation confirmation | `tcpdump` on router container WAN interfaces |
| Routing Service reconnection events | RTI distributed logging + `medtech-diag` |
| Discovery timeline under NAT | Admin Console → participant discovery view |

See [`wan-testing-strategy.md`](wan-testing-strategy.md) for the full topology
diagram, impairment profiles, RTI configuration requirements, and the NAT traversal
validation checklist.

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
