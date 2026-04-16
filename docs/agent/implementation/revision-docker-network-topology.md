# Revision: Docker Network Topology — Per-Instance Isolation

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
A hospital gateway joins `{hospital}-net` + `wan-net` (named mode) or
`{hospital}-net` only (unnamed mode, no WAN).
A cloud gateway joins `cloud-net` + `wan-net` (V3.0).

### D.4 — Dynamic hospital network naming

Hospital networks are always named after the hospital instance:
- Unnamed mode: `medtech_hospital-net` (single hospital; unambiguous)
- Named mode: `medtech_{name}-net` (e.g., `medtech_hospital-a-net`)

Room networks are always per-room:
- Unnamed mode: `medtech_{or}-net` (e.g., `medtech_or1-net`)
- Named mode: `medtech_{hospital}_{or}-net` (e.g.,
  `medtech_hospital-a_or1-net`)

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
- `_FLAT_NETWORKS`: change from 3 networks to 1 (`medtech_hospital-net`)
- `_start_unnamed_hospital`: create only `hospital-net`; gateway joins
  only `hospital-net`
- `_start_named_hospital`: create only `medtech_{name}-net` (1 network
  per hospital, not 3)
- `_start_gateway`: attach to hospital network only (+ `wan-net` for
  named)
- `_start_gui`: attach to hospital network only

**`_or.py`:**
- `_detect_hospitals`: detect hospitals by `medtech_*-net` or
  `medtech_hospital-net` pattern (no longer keyed on `surgical-net`)
- `or_cmd`: create per-room network (`medtech_{or}-net` or
  `medtech_{hospital}_{or}-net`); pass room network to room gateway and
  all service containers
- `_start_room_gateway`: attach to `{or}-net` + `{hospital}-net`
  (exactly two networks)
- Service hosts: join `{or}-net` only (no dual-homing)
- Twin/Controller containers: join `{or}-net` only
- All containers: `NDDS_DISCOVERY_PEERS` points to room CDS
  (`{or}-gateway:7400`)

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
