# Phase SIM: Distributed Simulation & CLI

**Goal:** Provide a developer-facing quick-start workflow: a `medtech` CLI
tool for build/launch/scale, a split-GUI Docker topology that simulates
production network separation, and multi-hospital NAT-isolated simulation
for realistic WAN deployment testing. Per-OR containers are launched
dynamically via `docker run --rm` — no duplicated compose service blocks.

**Depends on:** Phase UI-M (V1.3 — UI Modernization), Phase 20 (Multi-Arm)
**Blocks:** Nothing — additive infrastructure
**Version impact:** Minor bump (V1.4.0)
**Spec coverage:** [simulation-cli.md](../spec/simulation-cli.md)
(`@simulation` and `@cli` scenarios)

> **Principle:** Each step produces a working CLI command or Docker topology
> change. Existing tests must continue to pass. The CLI must not import
> `rti.connext` or create DDS participants — it is a pure build/launch
> orchestrator. Every CLI command prints the underlying native invocation
> so developers can run or adapt commands directly.

---

## Step SIM.1 — `medtech` CLI Scaffold ✅ `eeff608`

### Work

- Add `click` to `requirements.txt`
- Create `modules/shared/medtech/cli/__init__.py` (exports `main`)
- Create `modules/shared/medtech/cli/_main.py` with a `click.group()`
  entry point and a helper function that prints and runs shell commands
- Create `modules/shared/medtech/cli/_naming.py` with auto-name
  generation helpers:
  - `next_hospital_name()` — scans running `medtech_*` networks,
    returns next available name if needed
  - `next_or_name(hospital)` — scans running containers for the
    hospital, returns next sequential OR name (`OR-1`, `OR-2`, …)
- Add `[project.scripts] medtech = "medtech.cli:main"` to `pyproject.toml`
- Implement `medtech build`:
  - Check for `build/` directory; run `cmake -B build -S .` if absent
  - Run `cmake --build build --target install`
  - Print each command before execution via the shared helper
- Implement `medtech status`:
  - Run `docker ps --filter "name=medtech" --filter "name=cloud-discovery" --filter "name=routing-service" --format json`
  - Parse and display a table: container name, status, ports
  - Highlight GUI URLs from port mappings
  - Print the underlying `docker ps` command
- Implement `medtech stop`:
  - Run `docker stop` for all containers matching the medtech naming
    convention (infrastructure, GUI, NAT routers, and dynamic OR
    containers)
  - Run `docker network rm` for all `medtech_*` networks
  - Print each command before execution

### Test Gate

- [x] `pip install -e .` makes `medtech` available on PATH
- [x] `medtech --help` prints available commands
- [x] `medtech build --help` prints build usage
- [x] `medtech status --help` prints status usage
- [x] `medtech stop --help` prints stop usage
- [x] `medtech stop` removes containers **and** Docker networks
- [x] `next_or_name()` returns `OR-1` when no ORs are running
- [x] All existing tests pass
- [x] Lint passes

---

## Step SIM.2 — `medtech run hospital` ✅ `04b7aee`

### Work

- Implement `medtech run` as a `click.group()` subcommand group
- Implement `medtech run hospital [--name NAME]`:

  **Unnamed hospital** (no `--name`):
  - Create flat Docker networks (`medtech_surgical-net`,
    `medtech_hospital-net`, `medtech_orchestration-net`) if they
    do not exist
  - Run sequential `docker run --rm -d` commands using the gateway
    shared-namespace pattern:
    1. Hospital-gateway base container (`cloud-discovery-service`
       image, attached to `surgical-net`, `hospital-net`,
       `orchestration-net`) — provides CDS for hospital-level
       participant discovery
    2. Routing Service (`routing-service` image,
       `--network container:hospital-gateway`) — shares the
       gateway's network namespace; bridges room domains (10s)
       into hospital domains (20s)
    3. Collector Service (`rticom/collector-service` image,
       `--network container:hospital-gateway`) — shares the
       gateway's network namespace; forwards Dom 19 → 29
    4. Central GUI (`medtech-gui` image, attached to `hospital-net`,
       `orchestration-net`, port 8080)
  - No NAT router is created

  **Named hospital** (e.g., `--name hospital-a`):
  - Create per-hospital private Docker networks with explicit subnets
    allocated by hospital ordinal (N=1,2,…):
    - `medtech_hospital-a_surgical-net`   — `10.(N×10).1.0/24`
    - `medtech_hospital-a_hospital-net`   — `10.(N×10).2.0/24`
    - `medtech_hospital-a_orchestration-net` — `10.(N×10).3.0/24`
  - Create shared `medtech_wan-net` (`172.30.0.0/24`) if it does not
    exist (created exactly once, shared by all hospitals)
  - Launch a privileged NAT router container (`hospital-a-nat`):
    - Dual-homed on all three private networks **and** `wan-net`
    - `--privileged`, `sysctl net.ipv4.ip_forward=1`
    - Image: built from `docker/nat-router.Dockerfile` (Alpine +
      iptables, installed at build time). The entrypoint script
      reads environment variables to configure routing:
      - `NAT_WAN_IFACE` — the interface connected to `wan-net`
        (determined by the CLI from network attachment order)
      - `NAT_PRIVATE_SUBNETS` — comma-separated list of private
        subnets to MASQUERADE (e.g., `10.10.1.0/24,10.10.2.0/24,10.10.3.0/24`)
    - The entrypoint enables IP forwarding and applies
      `iptables -t nat -A POSTROUTING -o $NAT_WAN_IFACE -j MASQUERADE`
      for each private subnet
  - Run a per-hospital gateway (CDS base with co-located RS and
    Collector via `--network container:<name>-gateway`) and GUI
    on the private networks
  - GUI host port allocated by hospital ordinal:
    1st hospital = 8080, 2nd = 9080, 3rd = 10080, etc.

  **Common behavior:**
  - Print each `docker run` command before execution
  - Print a URL summary (dashboard URL)
  - Accept `--observability` flag to include the local visualization
    containers (Prometheus, Grafana) for developer convenience.
    Collector Service is always launched as base infrastructure
    regardless of this flag.
  - Error if an unnamed hospital already exists and `--name` is
    not provided

### Test Gate

- [x] `medtech run hospital` starts hospital-gateway (CDS + RS + Collector in shared namespace) and GUI containers (flat networks)
- [x] `medtech run hospital --name hospital-a` creates per-hospital networks with explicit subnets
- [x] NAT router container is created for named hospitals with `--privileged` and IP forwarding
- [x] `medtech_wan-net` is created exactly once across multiple named hospitals
- [x] GUI port allocation follows ordinal scheme (8080, 9080, …)
- [x] Each underlying `docker run` command is printed to stdout
- [x] Docker networks are created if absent
- [x] Second unnamed hospital errors
- [x] All existing tests pass
- [x] Lint passes

---

## Step SIM.3 — `medtech run or` ✅ `91ce7d0`

### Work

- Implement `medtech run or [--name NAME] [--hospital HOSPITAL] [--twin-port PORT]`:
  - If `--name` is omitted, auto-generate using `next_or_name(hospital)`
    (e.g., `OR-1`, `OR-2`)
  - If `--hospital` is omitted:
    - If exactly one hospital is running (named or unnamed), target it
    - If multiple hospitals are running, error:
      "Multiple hospitals running. Specify --hospital NAME."
    - If no hospital is running, error
  - **Room-gateway launch** — before starting application containers,
    launch a room-level gateway using the shared-namespace pattern:
    1. Room-gateway base container (`cloud-discovery-service` image,
       `--name <or-name>-gateway`, attached to the hospital's
       Docker networks) — provides CDS for OR-LAN participant
       discovery (required for multicast-free environments)
    2. Routing Service (`routing-service` image,
       `--network container:<or-name>-gateway`) — bridges room
       domains (10/11/19) into hospital domains (20s)
    3. Collector Service (`rticom/collector-service` image,
       `--network container:<or-name>-gateway`) — forwards
       Dom 19 → hospital Collector on Dom 29
  - Derive container names from OR name (lowercase, hyphenated):
    e.g., `OR-5` → `clinical-service-host-or5`,
    `robot-service-host-or5`, `operational-service-host-or5`,
    `operator-service-host-or5`, `medtech-twin-or5`
    (for named hospitals, prefix with hospital name:
    `hospital-a-clinical-service-host-or5`)
  - If `--twin-port` is not specified, auto-assign from the hospital's
    twin port range (unnamed base: 8081; hospital-a base: 8081;
    hospital-b base: 9081; etc.)
  - For each container, run `docker run --rm -d`:
    - `--name <container-name>`
    - `--network <hospital-prefix>_surgical-net` (service hosts also
      join `<hospital-prefix>_orchestration-net` if they require
      orchestration access)
    - `--label medtech.dynamic=true` (for `medtech stop` cleanup)
    - `-e ROOM_ID=<name>` `-e PROCEDURE_ID=<name>-001`
    - `-e HOST_ID=<host-type>-<name_lower>`
    - `-e MEDTECH_GUI_EXTERNAL_URL=http://localhost:<twin_port>`
      (twin container only)
    - All standard `medtech-env` variables (read from `.env` or
      project defaults)
    - Volume mounts matching `*config-volumes` from compose
    - Image: `medtech/app-python` or `medtech/app-cpp` as appropriate
    - Command: the module entry point for each service type
  - Print each `docker run` command before execution
  - Print summary: OR name, hospital, container names, twin URL

### Test Gate

- [x] `medtech run or --name OR-5` starts room-gateway (CDS + RS +
      Collector in shared namespace) plus 5 application containers
      (4 service hosts + 1 twin)
- [x] `medtech run or` (no `--name`) auto-generates `OR-1`
- [x] `medtech run or --hospital hospital-a` targets named hospital networks
- [x] `medtech run or` errors when multiple hospitals are running and
      `--hospital` is omitted
- [x] `medtech run or` infers hospital when only one is running
- [x] Each `docker run` command is printed to stdout
- [x] Twin is accessible at the assigned host port
- [x] Containers have the `medtech.dynamic=true` label
- [x] `medtech stop` removes dynamically added containers
- [x] All existing tests pass
- [x] Lint passes

---

## Step SIM.4 — Scenarios & `medtech launch` ✅ `93e7a6d`

### Work

- Create `modules/shared/medtech/cli/_scenarios.py` defining scenario
  metadata:
  ```python
  SCENARIOS = {
      "distributed": {
          "description": "Split GUI, 2 ORs, full stack",
          "hospital_args": [],
          "rooms": ["OR-1", "OR-3"],
      },
      "multi-site": {
          "description": "Two named hospitals with NAT isolation, 2 ORs each",
          "hospitals": [
              {"name": "hospital-a", "rooms": ["OR-1", "OR-2"]},
              {"name": "hospital-b", "rooms": ["OR-1", "OR-2"]},
          ],
      },
      "unified": {
          "description": "Monolithic GUI (pre-V1.4), 2 ORs",
          "compose_profiles": ["unified-gui"],
          "rooms": [],  # twins served in-process
      },
      "minimal": {
          "description": "Single OR, split GUI, no observability",
          "hospital_args": [],
          "rooms": ["OR-1"],
      },
  }
  ```
- Implement `medtech launch [SCENARIO]`:
  - Default scenario: `distributed`
  - For `unified`: run `docker compose --profile unified-gui up -d`
    plus the existing per-OR compose services (no `run or` calls)
  - For `distributed` / `minimal`: call `medtech run hospital`, then
    `medtech run or --name <NAME>` for each room in the scenario
  - For `multi-site`: call `medtech run hospital --name <NAME>` for
    each hospital, then `medtech run or --name <OR> --hospital <NAME>`
    for each room within each hospital
  - Print a final URL summary table (including per-hospital dashboard
    URLs for `multi-site`)
- Implement `medtech launch --list`:
  - Print scenario names and descriptions in a table

### Test Gate

- [x] `medtech launch --list` prints all four scenarios
- [x] `medtech launch --help` documents the scenario argument
- [x] `medtech launch` starts the distributed scenario by default
- [x] `medtech launch multi-site` starts two hospitals with NAT + 4 ORs
- [x] `medtech launch unified` starts the monolithic GUI
- [x] `medtech launch minimal` starts a single-OR scenario
- [x] All existing tests pass
- [x] Lint passes

---

## Step SIM.5 — Split-GUI Docker Topology

### Work

- Update `medtech-gui` service in `docker-compose.yml`:
  - Add environment variable `MEDTECH_GUI_MODE=controller-dashboard`
    (or equivalent) to signal that the unified app should not load the
    digital twin module in split-GUI mode
  - Keep existing port 8080 and network attachments
- Add `unified-gui` profile to `docker-compose.yml`:
  - Overrides `MEDTECH_GUI_MODE` to load all modules (dashboard,
    controller, twin) in one process
  - Excludes dynamic twin containers
- Update digital twin `__main__` entry point:
  - Read `MEDTECH_GUI_EXTERNAL_URL` from environment
  - If set, build `gui_url` from it (e.g.,
    `f"{external_url}/twin/{room_id}"`)
  - Pass `gui_url` to the service's `gui_urls()` override
- Verify: per-OR compose services (procedure-context, service hosts,
  sims) remain unchanged — they are still launched by `medtech run or`
  for all rooms; the compose file is retained only for image building
  and as a legacy reference path

### Test Gate

- [ ] `docker compose up -d` starts infrastructure + central GUI
      (no twin containers)
- [ ] `http://localhost:8080` serves dashboard + controller
- [ ] `medtech run or --name OR-1` starts twin accessible at
      assigned port
- [ ] Procedure Controller sidebar discovers twin `gui_url` entries
- [ ] Clicking twin sidebar entry opens new browser tab
- [ ] `docker compose --profile unified-gui up -d` starts monolithic
      GUI serving all modules
- [ ] All existing tests pass
- [ ] Lint passes

---

## Step SIM.6 — Documentation & Regression

### Work

- Update project root `README.md` quick-start section to reference
  the `medtech` CLI workflow:
  1. Clone → 2. Install dependencies → 3. Configure environment →
  4. `medtech build` → 5. `medtech launch` → 6. Open
  `http://localhost:8080`
- Update `tools/README.md` to mention the CLI and its relationship to
  diagnostic tools (`medtech` is for launch/scale; `medtech-diag` is
  for DDS inspection)
- Run the full quality gate pipeline (`bash scripts/ci.sh`)
- Run `medtech launch` → `medtech run or --name OR-5` →
  `medtech status` → `medtech stop` workflow end-to-end

### Test Gate

- [ ] All `@simulation` and `@cli` spec tests pass
- [ ] All existing tests pass
- [ ] Lint passes (including markdownlint)
- [ ] `medtech launch` → `medtech run or --name OR-5` →
      `medtech status` → `medtech stop` workflow completes without
      errors
- [ ] `medtech launch multi-site` → `medtech status` → `medtech stop`
      workflow completes without errors
- [ ] `medtech launch unified` runs monolithic GUI end-to-end
- [ ] `@acceptance @simulation` test passes: programmatically runs
      `medtech launch` → `medtech run or --name OR-5` →
      `medtech status` (asserts expected containers) → `medtech stop`
      (asserts no orphan containers or networks)

---

## Step SIM.7 — Topology Visualization

### Work

- Implement `medtech status --topology`:
  - Run `docker network inspect` on each `medtech_*` network
    (flat networks for unnamed hospitals, per-hospital prefixed
    networks for named hospitals, plus `medtech_wan-net`)
  - Parse the JSON response to extract container names, IPs, and
    mapped host ports per network
  - Render an ASCII tree grouping containers by network, organized
    by hospital when named hospitals exist:
    ```
    hospital-a
    ├── hospital-a_surgical-net (10.10.1.0/24)
    │   ├── hospital-a-clinical-or1   10.10.1.2  (ports: -)
    │   ├── cloud-discovery-a          10.10.1.10
    │   └── routing-service-a          10.10.1.11
    ├── hospital-a_hospital-net (10.10.2.0/24)
    │   ├── medtech-gui-a              10.10.2.2  (ports: 8080)
    │   └── cloud-discovery-a          10.10.2.10
    └── hospital-a-nat ⟷ wan-net (172.30.0.2)

    wan-net (172.30.0.0/24)
    ├── hospital-a-nat   172.30.0.2
    └── hospital-b-nat   172.30.0.3
    ```
  - Print the underlying `docker network inspect` commands
- Implement `medtech launch --dockgraph`:
  - After starting the simulation, run:
    ```
    docker run -d --name medtech-dockgraph \
      -p 7800:7800 \
      -v /var/run/docker.sock:/var/run/docker.sock:ro \
      --label dockgraph.self=true \
      --label medtech.dynamic=true \
      dockgraph/dockgraph
    ```
  - Print the command and the DockGraph URL
    (`http://localhost:7800`)
  - `medtech stop` removes the DockGraph container along with all
    other medtech containers
- Add DockGraph to `THIRD_PARTY_NOTICES.md`:
  - Image: `dockgraph/dockgraph`
  - License: BSL 1.1 (converts to Apache 2.0 after 4 years)
  - Source: <https://github.com/dockgraph/dockgraph>
  - Usage: Optional Docker topology visualization sidecar

### Test Gate

- [ ] `medtech status --topology` renders a non-empty ASCII tree
- [ ] Each network group lists its attached containers with IPs
- [ ] Multi-hospital topology groups containers by hospital name
- [ ] `wan-net` section shows NAT router containers from all hospitals
- [ ] `medtech launch --dockgraph` starts DockGraph on port 7800
- [ ] DockGraph container has `medtech.dynamic=true` label
- [ ] `medtech stop` removes the DockGraph container
- [ ] All existing tests pass
- [ ] Lint passes
