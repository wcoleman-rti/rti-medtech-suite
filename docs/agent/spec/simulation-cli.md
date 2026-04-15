# Simulation CLI & Split-GUI Deployment

Spec scenarios for the `medtech` CLI tool, split-GUI Docker deployment,
and multi-hospital NAT simulation introduced in V1.4.0.

**Tags:** `@simulation`, `@cli`

---

## CLI Build Command

### @simulation @cli — `medtech build` runs CMake build and install

**Given** the Connext environment is sourced and CMake prerequisites are met
**When** the developer runs `medtech build`
**Then** the CLI runs `cmake -B build -S .` (if not already configured) followed by `cmake --build build --target install`
**And** the underlying commands are printed to stdout before execution
**And** the exit code reflects the build result

### @simulation @cli — `medtech build --docker` builds Docker images

**Given** the CMake build and install have completed (or `medtech build` runs them first)
**When** the developer runs `medtech build --docker`
**Then** the CLI runs `docker compose build` (or equivalent `docker build` commands for all project images)
**And** each underlying command is printed to stdout before execution
**And** the exit code reflects the Docker build result

### @simulation @cli — `medtech build --all` runs CMake build, install, and Docker image build

**Given** the Connext environment is sourced and CMake prerequisites are met
**When** the developer runs `medtech build --all`
**Then** the CLI runs the CMake build and install followed by the Docker image build
**And** each underlying command is printed to stdout
**And** the exit code reflects the combined result

---

## CLI Run Commands — Hospital

### @simulation @cli — `medtech run hospital` starts unnamed hospital

**Given** Docker images are built
**When** the developer runs `medtech run hospital`
**Then** the CLI creates flat Docker networks (`medtech_surgical-net`, `medtech_hospital-net`, `medtech_orchestration-net`) if they do not exist
**And** the CLI launches a hospital-gateway container (CDS base) followed by co-located Routing Service and Collector containers sharing its network namespace via `--network container:hospital-gateway`
**And** the CLI launches the central GUI container
**And** no NAT router container is created
**And** each underlying command is printed to stdout
**And** the output includes the dashboard URL (`http://localhost:8080`)

### @simulation @cli — `medtech run hospital --name` starts named hospital with NAT

**Given** Docker images are built
**When** the developer runs `medtech run hospital --name hospital-a`
**Then** the CLI creates per-hospital private networks (`medtech_hospital-a_surgical-net`, `medtech_hospital-a_hospital-net`, `medtech_hospital-a_orchestration-net`) with explicit subnets
**And** the CLI creates the shared `medtech_wan-net` (172.30.0.0/24) if it does not exist
**And** a privileged NAT router container (`hospital-a-nat`) is launched, dual-homed on the private networks and `wan-net`, with IP forwarding and `iptables MASQUERADE`
**And** a per-hospital gateway container (CDS base with co-located RS and Collector via `--network container:<name>-gateway`) and GUI container are launched on the private networks
**And** the GUI is mapped to a host port allocated by hospital ordinal (1st = 8080, 2nd = 9080, etc.)
**And** each command is printed to stdout

### @simulation @cli — `medtech run hospital --observability` includes the observability stack

**Given** Docker images are built
**When** the developer runs `medtech run hospital --observability`
**Then** the usual infrastructure containers are started (hospital-gateway with co-located RS and Collector, GUI)
**And** Prometheus and Grafana containers are also started for local telemetry visualization
**And** each container's `docker run` command is printed to stdout

---

### @simulation @cli — second named hospital gets separate networks and NAT

**Given** `hospital-a` is running
**When** the developer runs `medtech run hospital --name hospital-b`
**Then** a new set of private networks is created with a different subnet range
**And** a new NAT router (`hospital-b-nat`) is launched on `wan-net`
**And** `hospital-b` containers cannot directly reach `hospital-a` private networks
**And** both NAT routers can reach each other on `wan-net`

---

## CLI Run Commands — OR

### @simulation @cli — `medtech run or --name` spawns per-OR containers

**Given** a hospital is running
**When** the developer runs `medtech run or --name OR-1`
**Then** the CLI launches a room-gateway container (CDS base with co-located RS and Collector via `--network container:<OR-name>-gateway`) on the hospital's Docker networks
**And** the CLI runs `docker run --rm -d` for each required Service Host container (clinical, operational, operator, robot), a Procedure Controller container, and a Digital Twin container
**And** the Controller and Twin containers are attached to both `surgical-net` and `orchestration-net` (for Procedure domain data and `medtech.gui.room_nav` sibling discovery)
**And** each `docker run` command is printed to stdout before execution
**And** the controller container is assigned a host port (auto-assigned from the hospital's controller port range)
**And** the twin container is assigned a host port (auto-assigned from the hospital's twin port range)
**And** the CLI prints a summary including the controller URL and twin URL

### @simulation @cli — `medtech run or` auto-generates name when omitted

**Given** a hospital is running with no ORs
**When** the developer runs `medtech run or`
**Then** the CLI auto-generates a unique name (`OR-1`)
**And** a second `medtech run or` generates `OR-2`

### @simulation @cli — `medtech run or --hospital` targets a specific hospital

**Given** `hospital-a` and `hospital-b` are both running
**When** the developer runs `medtech run or --name OR-1 --hospital hospital-a`
**Then** the OR containers are attached to `hospital-a`'s private networks
**And** the twin port is allocated from `hospital-a`'s port range

### @simulation @cli — `medtech run or` infers hospital when only one is running

**Given** exactly one hospital is running (named or unnamed)
**When** the developer runs `medtech run or --name OR-1` without `--hospital`
**Then** the OR is attached to the running hospital

### @simulation @cli — `medtech run or` errors when multiple hospitals exist and --hospital omitted

**Given** `hospital-a` and `hospital-b` are both running
**When** the developer runs `medtech run or --name OR-1` without `--hospital`
**Then** the CLI prints an error: "Multiple hospitals running. Specify --hospital NAME."
**And** no containers are started

### @simulation @cli — `medtech run or --twin-port` uses explicit port

**Given** a hospital is running
**When** the developer runs `medtech run or --name OR-1 --twin-port 8085`
**Then** the twin container is mapped to host port 8085
**And** the summary output shows `http://localhost:8085/twin/OR-1`

---

## CLI Launch Command (Scenario Shorthand)

### @simulation @cli — `medtech launch` starts the default distributed scenario

**Given** Docker images are built
**When** the developer runs `medtech launch`
**Then** the CLI executes `medtech run hospital` followed by `medtech run or --name OR-1` and `medtech run or --name OR-3`
**And** the output prominently displays the hospital dashboard URL (`http://localhost:8080`) as the primary entry point
**And** the output includes a summary table of all GUI URLs (dashboard, per-OR controllers, per-OR twins)

### @simulation @cli — `medtech launch multi-site` starts two hospitals with NAT

**Given** Docker images are built
**When** the developer runs `medtech launch multi-site`
**Then** the CLI runs `medtech run hospital --name hospital-a` and `medtech run hospital --name hospital-b`
**And** two ORs are added to each hospital
**And** each hospital has its own NAT router on `wan-net`
**And** the output lists all GUI URLs for both hospitals

### @simulation @cli — `medtech launch minimal` starts a single-OR scenario

**Given** Docker images are built
### @simulation @cli — `medtech launch minimal` starts single-OR simulation

**Given** Docker images are built
**When** the developer runs `medtech launch minimal`
**Then** infrastructure is started via `medtech run hospital`
**And** only a single OR instance is started (`medtech run or --name OR-1`)
**And** the observability stack is not started

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

**Given** a simulation is running (with or without multiple hospitals)
**When** the developer runs `medtech stop`
**Then** the CLI stops all medtech containers via `docker stop`
**And** the CLI removes all medtech Docker networks via `docker network rm`
**And** no orphan medtech containers or networks remain
**And** the underlying commands are printed to stdout

---

## Split-GUI Deployment

### @simulation — dynamically launched OR appears in hospital dashboard room cards

**Given** infrastructure is running and the hospital dashboard is loaded
**And** the developer runs `medtech run or --name OR-5`
**When** the new per-room Routing Service bridges `ServiceCatalog` from Domain 11 to Domain 20
**Then** a new room card for OR-5 appears in the dashboard Room Overview
**And** the card shows the room's `gui_url` with an `open_in_new` button

### @simulation — room gui_url is browser-reachable

**Given** a room container has `MEDTECH_GUI_EXTERNAL_URL=http://localhost:8091`
**When** the hospital dashboard reads the room's `gui_url` from bridged `ServiceCatalog`
**Then** the URL is `http://localhost:8091/controller/OR-1`
**And** the developer's browser can reach this URL via Docker port mapping

### @simulation — room card opens room GUI in new tab

**Given** the hospital dashboard is open at `http://localhost:8080`
**And** the Room Overview shows a room card for OR-1 with `gui_url` `http://localhost:8091/controller/OR-1`
**When** the developer clicks the room card's `open_in_new` button
**Then** the room GUI opens in a new browser tab
**And** the hospital dashboard tab remains unchanged

### @simulation — room nav pill discovers sibling GUIs

**Given** a room GUI (Procedure Controller for OR-1) is open at `http://localhost:8091/controller/OR-1`
**When** the `room_nav` module's read-only Orchestration participant discovers a twin `gui_url` for OR-1
**Then** a "Digital Twin" button appears in the floating nav pill
**And** clicking it navigates to the twin's `gui_url` in the same tab

---

## Multi-Hospital NAT Isolation

### @simulation — named hospital's private networks are unreachable from other hospitals

**Given** `hospital-a` and `hospital-b` are running
**When** a container on `hospital-a_surgical-net` attempts to reach an IP on `hospital-b_surgical-net`
**Then** the connection fails (no route)

### @simulation — NAT routers can reach each other on wan-net

**Given** `hospital-a` and `hospital-b` are running
**When** `hospital-a-nat` pings `hospital-b-nat` on `wan-net`
**Then** the ping succeeds

### @simulation — NAT MASQUERADE translates source addresses

**Given** `hospital-a` is running with its NAT router
**When** a packet egresses from `hospital-a-nat` onto `wan-net`
**Then** the source IP is the NAT router's `wan-net` address (172.30.0.x), not the private network address (10.10.x.x)

---

## CLI Auto-Name Generation

### @simulation @cli — `medtech run hospital` without --name auto-generates

**Given** no hospitals are running
**When** the developer runs `medtech run hospital` twice
**Then** the first hospital is unnamed (flat networks, no NAT prefix)
**And** the second invocation errors because only one unnamed hospital is allowed

### @simulation @cli — `medtech run or` without --name auto-assigns sequential names

**Given** a hospital is running with no ORs
**When** the developer runs `medtech run or` three times
**Then** the ORs are named `OR-1`, `OR-2`, `OR-3`

---

## CLI Transparency

### @simulation @cli — all commands print underlying invocations

**Given** the developer runs any `medtech` CLI command
**Then** the exact `docker` or `cmake` command is printed to stdout before execution
**And** the developer could copy-paste the printed command to achieve the same result manually
