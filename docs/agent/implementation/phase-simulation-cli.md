# Phase SIM: Distributed Simulation & CLI

**Goal:** Provide a developer-facing quick-start workflow: a `medtech` CLI
tool for build/launch/scale, and a split-GUI Docker topology that
simulates production network separation. Per-OR containers are launched
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

## Step SIM.1 — `medtech` CLI Scaffold

### Work

- Add `click` to `requirements.txt`
- Create `modules/shared/medtech/cli/__init__.py` (exports `main`)
- Create `modules/shared/medtech/cli/_main.py` with a `click.group()`
  entry point and a helper function that prints and runs shell commands
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
    convention (infrastructure, GUI, and dynamic OR containers)
  - Print each command before execution

### Test Gate

- [ ] `pip install -e .` makes `medtech` available on PATH
- [ ] `medtech --help` prints available commands
- [ ] `medtech build --help` prints build usage
- [ ] `medtech status --help` prints status usage
- [ ] `medtech stop --help` prints stop usage
- [ ] All existing tests pass
- [ ] Lint passes

---

## Step SIM.2 — `medtech run hospital`

### Work

- Implement `medtech run` as a `click.group()` subcommand group
- Implement `medtech run hospital`:
  - Run sequential `docker run --rm -d` commands:
    1. Cloud Discovery Service (`cloud-discovery-service` image,
       attached to `surgical-net`, `hospital-net`, `orchestration-net`)
    2. Routing Service (`routing-service` image, attached to
       `surgical-net`, `hospital-net`)
    3. Central GUI (`medtech-gui` image, attached to `hospital-net`,
       `orchestration-net`, port 8080)
  - Create Docker networks (`medtech_surgical-net`,
    `medtech_hospital-net`, `medtech_orchestration-net`) if they
    do not exist
  - Print each `docker run` command, then print a URL summary
    (dashboard at `http://localhost:8080`)
  - Accept `--observability` flag to include the observability
    containers (Collector Service, Prometheus, Grafana)

### Test Gate

- [ ] `medtech run hospital` starts CDS, Routing Service, and GUI containers
- [ ] `medtech run hospital --help` documents options
- [ ] Each underlying `docker run` command is printed to stdout
- [ ] Docker networks are created if absent
- [ ] All existing tests pass
- [ ] Lint passes

---

## Step SIM.3 — `medtech run or`

### Work

- Implement `medtech run or --room-id ROOM_ID [--twin-port PORT]`:
  - Derive container names from room ID (lowercase, hyphenated):
    e.g., `OR-5` → `clinical-service-host-or5`,
    `robot-service-host-or5`, `operational-service-host-or5`,
    `operator-service-host-or5`, `medtech-twin-or5`
  - If `--twin-port` is not specified, scan host ports starting from
    8081 and assign the first available
  - For each container, run `docker run --rm -d`:
    - `--name <container-name>`
    - `--network medtech_surgical-net` (service hosts also join
      `medtech_orchestration-net` if they require orchestration access)
    - `--label medtech.dynamic=true` (for `medtech stop` cleanup)
    - `-e ROOM_ID=<room_id>` `-e PROCEDURE_ID=<room_id>-001`
    - `-e HOST_ID=<host-type>-<room_id_lower>`
    - `-e MEDTECH_GUI_EXTERNAL_URL=http://localhost:<twin_port>`
      (twin container only)
    - All standard `medtech-env` variables (read from `.env` or
      project defaults)
    - Volume mounts matching `*config-volumes` from compose
    - Image: `medtech/app-python` or `medtech/app-cpp` as appropriate
    - Command: the module entry point for each service type
  - Print each `docker run` command before execution
  - Print summary: room ID, container names, twin URL
- Update `medtech stop` to stop containers with
  `--label medtech.dynamic=true` before running `docker compose down`

### Test Gate

- [ ] `medtech run or --room-id OR-5` starts 5 containers
      (4 service hosts + 1 twin)
- [ ] Each `docker run` command is printed to stdout
- [ ] Twin is accessible at the assigned host port
- [ ] Containers have the `medtech.dynamic=true` label
- [ ] `medtech stop` removes dynamically added containers
- [ ] All existing tests pass
- [ ] Lint passes

---

## Step SIM.4 — Scenarios & `medtech launch`

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
    `medtech run or` for each room in the scenario
  - Print a final URL summary table
- Implement `medtech launch --list`:
  - Print scenario names and descriptions in a table

### Test Gate

- [ ] `medtech launch --list` prints all three scenarios
- [ ] `medtech launch --help` documents the scenario argument
- [ ] `medtech launch` starts the distributed scenario by default
- [ ] `medtech launch unified` starts the monolithic GUI
- [ ] `medtech launch minimal` starts a single-OR scenario
- [ ] All existing tests pass
- [ ] Lint passes

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
- [ ] `medtech run or --room-id OR-1` starts twin accessible at
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
- Run `medtech launch` → `medtech run or --room-id OR-5` →
  `medtech status` → `medtech stop` workflow end-to-end

### Test Gate

- [ ] All `@simulation` and `@cli` spec tests pass
- [ ] All existing tests pass
- [ ] Lint passes (including markdownlint)
- [ ] `medtech launch` → `medtech run or --room-id OR-5` →
      `medtech status` → `medtech stop` workflow completes without
      errors
- [ ] `medtech launch unified` runs monolithic GUI end-to-end

---

## Step SIM.7 — Topology Visualization

### Work

- Implement `medtech status --topology`:
  - Run `docker network inspect` on each medtech network
    (`medtech_surgical-net`, `medtech_hospital-net`,
    `medtech_orchestration-net`)
  - Parse the JSON response to extract container names, IPs, and
    mapped host ports per network
  - Render an ASCII tree grouping containers by network:
    ```
    surgical-net (172.20.0.0/16)
    ├── or-1-twin        172.20.0.2   (ports: 8081)
    ├── cloud-discovery   172.20.0.10
    └── routing-service   172.20.0.11

    hospital-net (172.21.0.0/16)
    ├── medtech-gui       172.21.0.2   (ports: 8080)
    └── cloud-discovery   172.21.0.10
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

### Test Gate

- [ ] `medtech status --topology` renders a non-empty ASCII tree
- [ ] Each network group lists its attached containers with IPs
- [ ] `medtech launch --dockgraph` starts DockGraph on port 7800
- [ ] DockGraph container has `medtech.dynamic=true` label
- [ ] `medtech stop` removes the DockGraph container
- [ ] All existing tests pass
- [ ] Lint passes
