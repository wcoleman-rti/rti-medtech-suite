# Revision: Docker Network Topology — Per-Instance Isolation

**Status:** R.1–R.12 complete. All 12 CI gates pass (655 Python + 5 C++
tests). Committed in two increments: `810a704` (R.1–R.7) and the
extension commit (R.8–R.12).

**Goal:** Replace the shared-network Docker simulation topology with a
per-instance network model where each deployable instance (room, hospital,
cloud) gets its own isolated LAN. This aligns the Docker simulation with
the production model where each OR has a dedicated surgical LAN and each
hospital has a dedicated backbone network.

**Trigger:** The current topology uses shared flat networks
(`surgical-net`, `hospital-net`, `orchestration-net`) across all rooms
within a hospital. OR-1 and OR-3 containers share the same L2 broadcast
domain, meaning network-level isolation between rooms does not exist —
only DDS partitions provide logical separation. In production, each OR
has its own physical LAN. The Docker simulation should mirror this.

**Scope:** Planning documents (`vision/`, `spec/`), `docker-compose.yml`,
`medtech` CLI (`_hospital.py`, `_or.py`, `_naming.py`), and CLI tests.
No DDS architecture, topic, QoS, domain ID, or application logic changes.
No new modules or features.

**Version impact:** Minor (V1.x) — infrastructure change. All existing
tests must continue to pass. DDS behavior is unchanged (domain IDs,
domain tags, partitions, QoS remain identical).

---

## Design Decisions

### D.1 — One network per deployable instance

Each room, hospital, and cloud instance gets exactly one Docker network.
The `orchestration-net` network is eliminated. Orchestration services
(Procedure Controller, Service Hosts receiving orchestration commands)
join the room's single network — the separation between surgical data
and orchestration commands is logical (separate domain IDs / domain
tags), not physical.

### D.2 — Room-level CDS is always deployed

Every room deploys its own CDS as the base process of the room gateway
container. All intra-room participants use the room CDS hostname as
their initial peer. The "Room-level CDS exception" in
`system-architecture.md` is removed. This is the correct production
model: each OR's CDS handles intra-room discovery without depending on
network reachability to the hospital CDS.

### D.3 — Gateway joins exactly two networks

A room gateway joins `{room}-net` + `{hospital}-net`.
A hospital gateway joins `{hospital}-net` only (single hospital) or
`{hospital}-net` + `wan-net` (multi-hospital with NAT).
A cloud gateway joins `cloud-net` + `wan-net` (V3.0).

### D.4 — Unified hospital/room naming (no unnamed/named fork)

The CLI always follows a single code path. When `--name` is omitted,
a default name is used:
- Default hospital name: `hospitalA`
- Default room names: auto-generated (`OR-1`, `OR-2`, …)

Network naming is always `medtech_{hospital}-net` for the hospital
and `medtech_{hospital}_{or}-net` for rooms:
- `medtech run hospital` → `medtech_hospitalA-net`
- `medtech run hospital --name hospital-b` → `medtech_hospital-b-net`
- `medtech run or` (on hospitalA) → `medtech_hospitalA_or1-net`
- `medtech run or --name OR-3 --hospital hospital-b` →
  `medtech_hospital-b_or3-net`

Container names follow the same pattern:
- `hospitalA-gateway`, `hospitalA-or1-gateway`
- `hospital-b-gateway`, `hospital-b-or3-gateway`

NAT routers are only created when multiple hospitals are deployed.

### D.5 — Discovery peer topology

| Participant level | Initial peer |
|-------------------|-------------|
| Intra-room service/app | Room CDS: `rtps@udpv4://{room}-gateway:7400` |
| Room RS upward output | Hospital CDS: `rtps@udpv4://{hospital}-gateway:7400` |
| Room Collector forwarding | Hospital CDS: `rtps@udpv4://{hospital}-gateway:7400` |
| Hospital-level app | Hospital CDS: `rtps@udpv4://{hospital}-gateway:7400` |
| Hospital RS upward output (V3.0) | Cloud CDS: `rtps@udpv4://cloud-gateway:7400` |

---

## Prerequisites

- All existing tests pass before starting any revision step
- No concurrent modifications to Docker, CLI, or vision files

---

## Step R.1 — Update vision/system-architecture.md

### Work

Update the following sections:

1. **Docker Network table** (§ Single-Machine Simulation): replace the
   4-row table (`surgical-net`, `hospital-net`, `orchestration-net`,
   `cloud-net`) with the per-instance model. New table rows:
   `{room}-net`, `{hospital}-net`, `cloud-net`.

2. **Rule 1 — CDS Per Instance**: remove the "Room-level CDS exception"
   blockquote. Update the Room row to state CDS is always deployed.
   Update the Networks column to show `{room}-net` only.

3. **Infrastructure Gateway Containers**: update gateway network
   attachments. Room gateway joins `{room}-net` + `{hospital}-net`.
   Hospital gateway joins `{hospital}-net` only (+ `wan-net` in named
   mode).

4. **Named-hospital topology diagrams**: replace the 3-net-per-hospital
   ASCII diagrams with 1-per-room + 1-per-hospital topology. Remove
   all `orchestration-net` references.

5. **Subnet Allocation table**: remove `orchestration-net` column, add
   per-room subnet column with allocation scheme.

6. **Split-GUI Deployment tables**: update network columns. Room GUI
   containers join `{room}-net` only (not dual-homed). Hospital GUI
   joins `{hospital}-net` only.

7. **Transport Configuration / Docker snippet**: update the initial peer
   from `gateway:7400` to `{room}-gateway:7400` for room-level
   participants.

8. **Docker Compose Service Startup Ordering**: update network references.

### Test gate

Manual review: no internal contradictions, no stale `orchestration-net`
references, all tables/diagrams consistent.

## Step R.2 — Cascade vision document updates

### Work

Update all other vision documents that reference Docker network names:

- `vision/capabilities.md` — V1.4 split-GUI section
- `vision/versioning.md` — V1.4 milestone table
- `vision/nicegui-migration.md` — Docker deployment references
- `vision/tooling.md` — DockGraph topology example

### Test gate

`grep -r "orchestration-net\|surgical-net" docs/agent/vision/` returns
zero matches (except historical context in `wan-testing-strategy.md` if
applicable).

## Step R.3 — Update spec/simulation-cli.md

### Work

Update GWT scenarios for:

- `medtech run hospital` — creates `medtech_hospital-net` only (no
  `surgical-net` or `orchestration-net`)
- `medtech run hospital --name` — creates `medtech_{name}-net` (no
  3-network set)
- `medtech run or --name` — creates `medtech_{or}-net` per room;
  room gateway joins `{or}-net` + `{hospital}-net`; service hosts and
  GUI containers join `{or}-net` only (not dual-homed)
- `medtech run or --hospital` — room network prefixed with hospital name

### Test gate

Manual review: scenarios are internally consistent and match updated
vision.

## Step R.4 — Update docker-compose.yml

### Work

Replace the `networks:` section:
- Remove `surgical-net` and `hospital-net`
- Add `or1-net`, `or3-net`, `hospital-net`

Update every service's `networks:` key:
- OR-1 containers: `or1-net` only
- OR-3 containers: `or3-net` only
- Room gateway (per-OR): `{or}-net` + `hospital-net`
- Hospital-level services (GUI, placeholder): `hospital-net` only
- CDS: `or1-net`, `or3-net`, `hospital-net` (unchanged role as
  combined gateway — or split into per-room gateways for compose)
- Routing Service: `or1-net` + `hospital-net` (or per-room RS)
- Observability: `hospital-net`

### Test gate

`docker compose config` succeeds. `docker compose up` starts all
services (manual verification).

## Step R.5 — Update medtech CLI (`_hospital.py`, `_or.py`)

### Work

**`_hospital.py`:**
- Remove `_FLAT_NETWORKS` and `_start_unnamed_hospital` entirely
- Single code path: `--name` defaults to `hospitalA` when omitted
- `_start_hospital`: create `medtech_{name}-net` (1 network per
  hospital); gateway joins only `{name}-net`
- **Duplicate validation:** before creating infrastructure, check if
  `medtech_{name}-net` already exists in `_running_networks()`. If so,
  error: `"Hospital '{name}' is already running."`
- NAT router only created when multiple hospitals are deployed
- `_start_gui`: attach to `{name}-net` only

**`_or.py`:**
- `_detect_hospitals`: detect hospitals by `medtech_*-net` pattern
- **Duplicate validation:** before creating room infrastructure, check
  if `medtech_{hospital}_{or}-net` already exists. If so, error:
  `"Room '{or_name}' already exists on hospital '{hospital}'."`
- `or_cmd`: create per-room network (`medtech_{hospital}_{or}-net`);
  room gateway dual-homed on `{or}-net` + `{hospital}-net`
- Service hosts: join `{or}-net` only (no dual-homing)
- Twin/Controller containers: join `{or}-net` only
- All containers: `NDDS_DISCOVERY_PEERS` points to room CDS
  (`{hospital}-{or}-gateway:7400`)

### Test gate

`bash scripts/ci.sh` passes. CLI acceptance tests updated and passing.

## Step R.6 — Update CLI tests and integration tests

### Work

- `test_cli_acceptance_sim.py`: update network name expectations,
  remove `orchestration-net` references, update `_detect_hospitals`
  mock data
- Any other test referencing Docker network names

### Test gate

`bash scripts/ci.sh` passes (full suite).

## Step R.7 — Update remaining implementation/spec docs

### Work

- `implementation/revision-ux-alignment.md` — remove `orchestration-net`
  references
- Any other `spec/` or `implementation/` docs with stale network names

### Test gate

`grep -r "orchestration-net\|surgical-net" docs/agent/` returns zero
unexpected matches.

---

# Extension: CLI-Owned Container Orchestration

**Goal:** Remove all simulation instance definitions from
`docker-compose.yml`. The `medtech` CLI becomes the sole orchestrator
for simulation containers via pure `docker run` / `docker network
create` commands. Docker Compose is retained **only** for image builds
(`docker compose --profile build build`).

**Trigger:** The compose file and CLI are redundant orchestrators.
Compose hardcodes instance names (OR-1, OR-3), duplicates service
definitions per room, and must keep default names in sync with the CLI.
The CLI already launches all containers via `docker run` — compose
instances are unused when running `medtech launch` or `medtech run`.
Keeping both creates a maintenance burden with no benefit.

**Scope:** `docker-compose.yml`, `medtech` CLI (`_or.py`,
`_hospital.py`, `_scenarios.py`), CLI tests, vision/spec docs that
reference `docker compose up`. No DDS, QoS, domain, or application
logic changes.

**Version impact:** None — same V1.x. The CLI behavior is unchanged.
Only the compose file shrinks and docs update.

---

## Extension Design Decisions

### D.6 — Compose retains only image build definitions

`docker-compose.yml` keeps:
- YAML anchors (`x-medtech-env`, `x-config-volumes`, `x-build-args`)
- Build-only services under `profiles: ["build"]`: `build-base`,
  `runtime-cpp`, `runtime-python`, `app-cpp`, `app-python`

Everything else is removed: `networks:` section, `cloud-discovery-
service`, all OR-1/OR-3 instance services, `routing-service`,
`medtech-gui`, `hospital-placeholder`, and all observability services
(`collector-service`, `prometheus`, `loki`, `grafana`).

The `medtech build --docker` command continues to delegate to
`docker compose --profile build build`.

### D.7 — CLI owns the full per-room container roster

The CLI's `_SERVICE_HOSTS` list (and the equivalent launched by
`or_cmd`) defines what runs in each room. The current compose file
has a broader set of per-room services than the CLI — the CLI must
be expanded to match:

| Container role | Image | Currently in CLI | Currently in compose |
|---|---|---|---|
| clinical-service-host | app-python | Yes | Yes |
| operational-service-host | app-python | Yes | Yes |
| operator-service-host | app-python | Yes | Yes |
| robot-service-host | app-cpp | Yes | Yes (×2 for OR-1) |
| procedure-controller | app-python | Yes | No |
| digital-twin | app-python | Yes | No |
| procedure-context | app-python | No | Yes |
| robot-controller | app-cpp | No | Yes |
| operator-sim | app-python | No | Yes |
| vitals-sim | app-python | No | Yes |
| camera-sim | app-python | No | Yes |
| device-telemetry | app-python | No | Yes |

The six compose-only services (`procedure-context`, `robot-controller`,
`operator-sim`, `vitals-sim`, `camera-sim`, `device-telemetry`) must be
added to the CLI's `_SERVICE_HOSTS` list (or a separate `_SIMULATORS`
list) so that `medtech run or` spawns the full room stack.

### D.8 — Scenario definitions control what is spawned

`_scenarios.py` already defines scenario shape (hospital count, room
names). This is extended to also control which optional container
categories are included. Container roles are grouped into categories:

| Category | Roles | Default |
|---|---|---|
| `core` | service hosts, procedure-context | Always |
| `sim` | operator-sim, vitals-sim, camera-sim, device-telemetry | Always in `distributed`/`minimal` |
| `gui` | digital-twin, procedure-controller | Always |
| `robot` | robot-controller | Always when robot-service-host present |

Scenarios can override: e.g. a future `headless` scenario could exclude
`gui`. The default (`distributed`) includes all categories.

### D.9 — Observability is a CLI flag, not a compose profile

The CLI's `--observability` flag on `medtech run hospital` already
launches Prometheus and Grafana via `docker run`. This is the only
path. The compose `profiles: ["observability"]` section is removed.

Loki is added to the CLI's observability launcher (currently missing).
In the V3.0 cloud tier vision, observability migrates to the cloud
instance — but for now it attaches to the hospital network.

### D.10 — No `docker compose up` for simulation

All documentation referencing `docker compose up` for running the
simulation is updated to reference `medtech launch` or `medtech run`.
`docker compose` is only referenced for `docker compose --profile
build build` (image building).

---

## Extension Prerequisites

- Steps R.1–R.7 are complete (per-instance network topology)
- All existing tests pass

---

## Step R.8 — Expand CLI per-room container roster

### Work

**`_or.py`:**
- Add the six missing container roles to a new `_SIMULATORS` list (or
  merge into `_SERVICE_HOSTS`):
  - `procedure-context` — `app-python`,
    `python -m surgical_procedure.procedure_context_service`
  - `robot-controller` — `app-cpp`, `/opt/medtech/bin/robot-controller`
  - `operator-sim` — `app-python`,
    `python -m surgical_procedure.operator_sim`
  - `vitals-sim` — `app-python`,
    `python -m surgical_procedure.vitals_sim`
  - `camera-sim` — `app-python`,
    `python -m surgical_procedure.camera_sim`
  - `device-telemetry` — `app-python`,
    `python -m surgical_procedure.device_telemetry_sim`
- All new containers join `{room}-net` only, with
  `NDDS_DISCOVERY_PEERS` pointing to the room CDS
- Environment: `ROOM_ID`, `PROCEDURE_ID`, `MEDTECH_APP_NAME`,
  `NDDS_DISCOVERY_PEERS` (same pattern as existing service hosts)
- `robot-controller` also needs `ROBOT_ID` (same as robot-service-host)

### Test gate

`medtech run or --name OR-1` launches 15 containers:
room-gateway (CDS + RS + Collector = 3) + 4 service hosts +
procedure-context + robot-controller + 4 simulators + digital-twin +
procedure-controller = 15. Test `test_starts_gateway_and_5_containers`
updated to verify new count.

## Step R.9 — Strip compose to build-only

### Work

**`docker-compose.yml`:**
- Remove `networks:` section entirely
- Remove all runtime services: `cloud-discovery-service`,
  `procedure-context-or1`, `robot-service-host-or1`, `robot-service-
  host-or1-b`, `clinical-service-host-or1`,
  `operational-service-host-or1`, `operator-service-host-or1`,
  `robot-controller-or1`, `operator-sim-or1`, `vitals-sim-or1`,
  `camera-sim-or1`, `device-telemetry-or1`, `medtech-gui`,
  all OR-3 equivalents, `routing-service`, `hospital-placeholder`
- Remove observability services: `collector-service`, `prometheus`,
  `loki`, `grafana`
- Keep only: YAML anchors (`x-medtech-env`, `x-config-volumes`,
  `x-build-args`) and the 5 build-profile services (`build-base`,
  `runtime-cpp`, `runtime-python`, `app-cpp`, `app-python`)
- Remove `x-qos-volumes` anchor (only used by removed services)

**Estimated result:** ~80 lines (down from ~615).

### Test gate

`docker compose --profile build config` succeeds.
`docker compose --profile build build` builds all 5 images.
Tests that validate compose structure (`test_observability.py`,
`test_service.py`) are updated or removed as appropriate.

## Step R.10 — Add Loki to CLI observability launcher

### Work

**`_hospital.py`:**
- Add Loki container to `_start_observability()`:
  `grafana/loki:2.9.0`, port 3100, on the hospital network.
- Collector's `OBSERVABILITY_LOKI_HOSTNAME` should resolve to the
  Loki container name.

### Test gate

`test_observability_starts_prometheus_grafana` updated to also verify
Loki is spawned. Renamed to `test_observability_starts_full_stack`.

## Step R.11 — Update docs and specs

### Work

- `vision/system-architecture.md` — remove any remaining references
  to `docker compose up` for simulation. Keep `docker compose build`
  references.
- `vision/tooling.md` — update CLI examples, remove compose-up
  workflows.
- `spec/simulation-cli.md` — verify no scenarios reference compose
  runtime behavior.
- `implementation/phase-simulation-cli.md` — historical, no changes
  needed.

### Test gate

`grep -r "compose up\|compose .*up" docs/agent/` returns zero matches
outside of build contexts and historical phase docs.

## Step R.12 — Update tests referencing compose runtime

### Work

- `tests/test_service.py` — tests that inspect compose service
  definitions (network attachments, environment, etc.) are updated
  to reflect the build-only compose. Tests that validated runtime
  service structure now validate CLI behavior instead.
- `tests/integration/test_observability.py` — tests that read
  compose for collector/prometheus/grafana network attachments are
  updated to test CLI observability launcher output.
- Any other tests that parse `docker-compose.yml` for runtime service
  expectations.

### Test gate

`bash scripts/ci.sh` passes (full suite).
