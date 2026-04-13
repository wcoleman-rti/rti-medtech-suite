# Simulation CLI & Split-GUI Deployment

Spec scenarios for the `medtech` CLI tool and the split-GUI Docker
deployment model introduced in V1.4.0.

**Tags:** `@simulation`, `@cli`

---

## CLI Build Command

### @simulation @cli — `medtech build` runs CMake build and install

**Given** the Connext environment is sourced and CMake prerequisites are met
**When** the developer runs `medtech build`
**Then** the CLI runs `cmake -B build -S .` (if not already configured) followed by `cmake --build build --target install`
**And** the underlying commands are printed to stdout before execution
**And** the exit code reflects the build result

---

## CLI Run Commands

### @simulation @cli — `medtech run hospital` starts infrastructure and central GUI

**Given** Docker images are built
**When** the developer runs `medtech run hospital`
**Then** the CLI runs sequential `docker run --rm -d` commands for Cloud Discovery Service, Routing Service, and the central GUI container
**And** each underlying `docker run` command is printed to stdout
**And** the output includes the dashboard URL (`http://localhost:8080`)

### @simulation @cli — `medtech run or` spawns per-OR containers via docker run

**Given** infrastructure is running (`medtech run hospital` completed)
**When** the developer runs `medtech run or --room-id OR-1`
**Then** the CLI runs `docker run --rm -d` for each required Service Host container (clinical, operational, operator, robot) and a digital twin container
**And** each `docker run` command is printed to stdout before execution
**And** containers are attached to the existing Docker networks (`surgical-net` for procedure services, both `surgical-net` and `orchestration-net` for service hosts that require orchestration)
**And** the twin container is assigned a host port (default: auto-assigned, or `--twin-port` if specified)
**And** the CLI prints a summary including the twin URL

### @simulation @cli — `medtech run or` auto-assigns twin port

**Given** infrastructure is running
**When** the developer runs `medtech run or --room-id OR-1` without specifying `--twin-port`
**Then** the CLI scans host ports starting from 8081 and assigns the first available port
**And** the assigned port is printed in the summary output

### @simulation @cli — `medtech run or --twin-port` uses explicit port

**Given** infrastructure is running
**When** the developer runs `medtech run or --room-id OR-1 --twin-port 8085`
**Then** the twin container is mapped to host port 8085
**And** the summary output shows `http://localhost:8085/twin/OR-1`

---

## CLI Launch Command (Scenario Shorthand)

### @simulation @cli — `medtech launch` starts the default distributed scenario

**Given** Docker images are built
**When** the developer runs `medtech launch`
**Then** the CLI executes `medtech run hospital` followed by `medtech run or --room-id OR-1` and `medtech run or --room-id OR-3`
**And** the output includes a summary of all GUI URLs (dashboard, controller, per-OR twins)

### @simulation @cli — `medtech launch minimal` starts a single-OR scenario

**Given** Docker images are built
**When** the developer runs `medtech launch minimal`
**Then** infrastructure is started via `medtech run hospital`
**And** only a single OR instance is started (`medtech run or --room-id OR-1`)
**And** the observability stack is not started

### @simulation @cli — `medtech launch unified` starts monolithic GUI

**Given** Docker images are built
**When** the developer runs `medtech launch unified`
**Then** the CLI runs `docker compose --profile unified-gui up -d`
**And** a single `medtech-gui` container serves all GUI modules in one process
**And** per-OR twin containers are not started separately

---

## CLI Topology Visualization

### @simulation @cli — `medtech status --topology` renders ASCII network tree

**Given** a simulation is running
**When** the developer runs `medtech status --topology`
**Then** the output groups running containers by their Docker network attachment
**And** each group shows the container name, IP, and mapped host ports
**And** the underlying `docker network inspect` command is printed to stdout

### @simulation @cli — `medtech launch --dockgraph` starts DockGraph sidecar

**Given** Docker images are built
**When** the developer runs `medtech launch --dockgraph`
**Then** the simulation starts as usual (infrastructure + ORs)
**And** a DockGraph container is launched on port 7800 with a read-only Docker socket mount
**And** DockGraph is accessible at `http://localhost:7800`
**And** the DockGraph container hides itself from its own graph via the `dockgraph.self=true` label

### @simulation @cli — `medtech launch --list` shows available scenarios

**Given** the CLI is installed
**When** the developer runs `medtech launch --list`
**Then** a table of scenario names and descriptions is printed

---

## CLI Status & Stop Commands

### @simulation @cli — `medtech status` shows running containers and URLs

**Given** a simulation is running
**When** the developer runs `medtech status`
**Then** a table of running containers is printed (name, status, ports)
**And** GUI URLs are highlighted (dashboard, controller, per-OR twins)

### @simulation @cli — `medtech stop` tears down everything

**Given** a simulation is running (with or without dynamically added rooms)
**When** the developer runs `medtech stop`
**Then** the CLI stops all containers with a `medtech.*` name prefix (infrastructure, GUI, and dynamic OR containers) via `docker stop`
**And** no orphan medtech containers remain
**And** the underlying commands are printed to stdout

---

## Split-GUI Deployment

### @simulation — dynamically launched OR is discovered by Procedure Controller

**Given** infrastructure is running and the Procedure Controller is loaded
**And** the developer runs `medtech run or --room-id OR-5`
**When** the new Service Hosts publish `ServiceCatalog` on the Orchestration domain
**Then** the Procedure Controller sidebar discovers and displays the new hosts/services
**And** the digital twin's `gui_url` appears in the sidebar as a cross-origin link

### @simulation — twin gui_url is browser-reachable

**Given** `medtech-twin-or1` has `MEDTECH_GUI_EXTERNAL_URL=http://localhost:8081`
**When** the Procedure Controller sidebar reads the twin's `gui_url` from `ServiceCatalog`
**Then** the URL is `http://localhost:8081/twin/OR-1`
**And** the developer's browser can reach this URL via Docker port mapping

### @simulation — cross-origin twins open in new tabs

**Given** the dashboard SPA is open at `http://localhost:8080`
**And** the sidebar shows a discovered twin with `gui_url` `http://localhost:8081/twin/OR-1`
**When** the developer clicks the twin sidebar entry
**Then** the twin opens in a new browser tab (not within the SPA shell)
**And** the standalone twin page includes a "Return to Controller" link

### @simulation — unified-gui profile deploys monolithic GUI

**Given** the developer runs `docker compose --profile unified-gui up -d`
**Then** a single `medtech-gui` container serves all GUI modules (dashboard, controller, twin) in one process
**And** no separate twin containers are started

---

## CLI Transparency

### @simulation @cli — all commands print underlying invocations

**Given** the developer runs any `medtech` CLI command
**Then** the exact `docker` or `cmake` command is printed to stdout before execution
**And** the developer could copy-paste the printed command to achieve the same result manually
