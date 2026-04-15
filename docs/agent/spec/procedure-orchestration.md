# Spec: Procedure Orchestration

Behavioral specifications for the V1.0 Procedure Orchestration milestone:
the `medtech::Service` interface, dual-mode participant pattern, Service
Host framework, Procedure Controller GUI, Orchestration databus (Orchestration databus)
communication, and DDS RPC lifecycle management.

The Orchestration databus uses **no Publisher/Subscriber partitions** and no
domain tags. Tier-level visibility isolation is achieved via static
**DomainParticipant-level partitions** set once at startup and never changed
during a host or controller's lifetime. Room and procedure context is
propagated as data — as well-known property keys in `ServiceCatalog` — not
as partition strings.

---

## Summary of Concrete Requirements

| Requirement | Value |
|-------------|-------|
| `ServiceState` enum values | `STOPPED`, `STARTING`, `RUNNING`, `STOPPING`, `FAILED`, `UNKNOWN` |
| `ServiceState` source of truth | IDL-generated `Orchestration::ServiceState` — not hand-written enums |
| `medtech::Service` interface methods | `run()`, `stop()`, `name`, `state` |
| Python `run()` signature | `async def run(self) -> None` (awaitable coroutine) |
| C++ `run()` signature | `void run()` (blocks calling thread until `stop()` is called) |
| `stop()` behavior | Non-blocking, thread-safe; `run()` returns promptly after `stop()` |
| Dual-mode standalone signal | `None` (Python) / `dds::core::null` (C++) |
| Dual-mode hosted signal | Valid `DomainParticipant` passed to constructor |
| `ServiceCatalog` durability | TRANSIENT_LOCAL (late-joining controllers receive current state) |
| `ServiceStatus` durability | TRANSIENT_LOCAL (late-joining controllers receive current state) |
| `ServiceHostControl` RPC QoS | `Pattern.RPC` (RELIABLE, KEEP_ALL) |
| Orchestration databus ID | 15 |
| Orchestration tier partition — procedure hosts | `procedure` |
| Orchestration tier partition — facility hosts (future) | `facility` |
| Orchestration cross-tier observer partition | `*` (wildcard, set at startup) |
| Unassigned / untiered host partition | `unassigned` |
| Well-known property key — room context | `room_id` |
| Well-known property key — procedure context | `procedure_id` |
| Well-known property key — GUI endpoint URL | `gui_url` |
| Service Host liveliness lease | 2 s (host failure detection via liveliness) |
| Procedure Controller domains | Orchestration + Procedure (`operational` read-only, `control` read-only) |
| Orchestration → Procedure DDS domain isolation | Complete — orchestration failure must not disrupt surgical data |
| Service context injection | All context via constructor/setter — never environment variables |
| RPC operations | `start_service`, `stop_service`, `update_service`, `get_capabilities`, `get_health` |

*This table must be updated whenever a concrete value in the scenarios below
is added or changed.*

---

## Service Interface (`medtech::Service`)

### Scenario: Service transitions through lifecycle states `@unit` `@orchestration`

**Given** a DDS service class implementing `medtech::Service`
**When** the service is constructed
**Then** `state` returns `STOPPED`
**When** `run()` is invoked
**Then** `state` transitions to `STARTING` and then to `RUNNING` once initialization completes
**When** `stop()` is called
**Then** `state` transitions to `STOPPING`
**And** `run()` returns promptly
**And** `state` transitions to `STOPPED`

### Scenario: Service reports FAILED on unrecoverable error `@unit` `@orchestration`

**Given** a DDS service class implementing `medtech::Service`
**When** an unrecoverable error occurs during `run()` (e.g., participant creation failure, entity lookup failure)
**Then** `state` transitions to `FAILED`
**And** `run()` returns (does not hang)

### Scenario: stop() is non-blocking and thread-safe `@unit` `@orchestration`

**Given** a service in `RUNNING` state
**When** `stop()` is called from a thread other than the one executing `run()`
**Then** `stop()` returns immediately without blocking
**And** `run()` returns within a bounded time (no deadlock)

### Scenario: Service name is stable and unique `@unit` `@orchestration`

**Given** a DDS service class implementing `medtech::Service`
**When** `name` is queried at any point in the lifecycle
**Then** the returned value is a non-empty string that does not change across calls
**And** no two service classes in the same Service Host return the same name

### Scenario: ServiceState is IDL-generated `@unit` `@orchestration`

**Given** the `ServiceState` enum is defined in `interfaces/idl/orchestration/`
**When** both C++ and Python code reference `ServiceState`
**Then** they use the IDL-generated type (`Orchestration::ServiceState` in C++, `orchestration.Orchestration.ServiceState` in Python)
**And** no hand-written enum duplicate exists

---

## Dual-Mode Participant Pattern

### Scenario: Service creates its own participant in standalone mode `@integration` `@orchestration`

**Given** a DDS service class with a nullable participant constructor parameter
**When** the service is constructed with `None` (Python) or `dds::core::null` (C++)
**Then** the service calls `initialize_connext()` and creates its own `DomainParticipant` from XML configuration
**And** the service sets its own domain partition from the provided room/procedure IDs
**And** the service validates that the participant was created successfully

### Scenario: Service uses provided participant in hosted mode `@integration` `@orchestration`

**Given** a Service Host has created a `DomainParticipant` with the correct domain tag and partition
**When** a DDS service class is constructed with the valid participant
**Then** the service uses the provided participant (does not create a new one)
**And** entity lookup (`find_datawriter`, `find_datareader`) succeeds against the provided participant
**And** no `initialize_connext()` call is made

### Scenario: Service validates entity lookup in both modes `@integration` `@orchestration`

**Given** a DDS service class in either standalone or hosted mode
**When** the constructor looks up writers and readers by XML entity name
**Then** every lookup result is validated (not null)
**And** the service raises/throws with the missing entity name if any lookup fails

### Scenario: Standalone service is backward-compatible with V1.0 deployment `@integration` `@orchestration`

**Given** an existing V1.0 Docker Compose deployment with standalone services
**When** V1.0 service classes are deployed in standalone mode (no Service Host, no Orchestration databus)
**Then** all V1.0 spec scenarios continue to pass without modification
**And** the service operates identically to its V1.0 predecessor

### Scenario: Service does not read environment variables `@unit` `@orchestration`

**Given** a DDS service class implementing `medtech::Service`
**When** the service is constructed and run
**Then** the service never reads environment variables, CLI arguments, or config files directly
**And** all operational context (room ID, procedure ID, participant) is received via constructor parameters

---

## Service Host Framework

### Scenario: Service Host publishes ServiceCatalog on startup `@integration` `@orchestration`

**Given** a Service Host is started and assigned to partition `room/OR-1`
**When** the Service Host’s Orchestration databus participant becomes active
**Then** the Service Host publishes a `ServiceCatalog` sample for each registered service, with `host_id`, `service_id`, `display_name`, and configurable property descriptors
**And** the samples are TRANSIENT_LOCAL and available to late-joining controllers

### Scenario: Service Host publishes ServiceStatus for each hosted service `@integration` `@orchestration`

**Given** a Service Host is managing a service in `RUNNING` state
**When** the Service Host polls the service's `state` property
**Then** the Service Host publishes a `ServiceStatus` sample with `host_id`, `service_id`, and the current `ServiceState`
**And** the sample is TRANSIENT_LOCAL and keyed by (`host_id`, `service_id`)

### Scenario: Service Host detects service state transitions `@integration` `@orchestration`

**Given** a Service Host is polling a hosted service's `state`
**When** the service transitions from `RUNNING` to `STOPPING` to `STOPPED`
**Then** the Service Host publishes updated `ServiceStatus` samples for each state transition (write-on-change)

### Scenario: Service Host exposes uniquely-named RPC service `@integration` `@orchestration`

**Given** a Service Host with `host_id = "robot-host-or1"`
**When** the Service Host registers its `ServiceHostControl` RPC service
**Then** the RPC service name is `ServiceHostControl/robot-host-or1`
**And** the Procedure Controller can address commands to this specific host

### Scenario: Service Host starts a service via RPC `@integration` `@orchestration`

**Given** the Procedure Controller sends a `start_service` RPC request to a Service Host
**And** the request specifies a `ServiceRequest` with `service_id` and configuration properties
**When** the Service Host receives the request
**Then** the Service Host constructs the requested service in hosted mode (passing the `ServiceRequest` to the factory)
**And** invokes the service's `run()` method (on a dedicated thread for C++, or as a gathered coroutine for Python)
**And** returns an `OperationResult` with code `OK`
**And** publishes an updated `ServiceStatus` reflecting the service's state transitions

### Scenario: Service Host stops a service via RPC `@integration` `@orchestration`

**Given** a Service Host is running a service in `RUNNING` state
**When** the Procedure Controller sends a `stop_service` RPC request for that service
**Then** the Service Host calls the service's `stop()` method
**And** waits for `run()` to return
**And** returns an `OperationResult` with code `OK`
**And** publishes `ServiceStatus` with state `STOPPED`

### Scenario: Service Host rejects start for already-running service `@integration` `@orchestration`

**Given** a Service Host is already running service `S1`
**When** the Procedure Controller sends a `start_service` request for `S1`
**Then** the Service Host returns `OperationResult` with code `ALREADY_RUNNING`
**And** the existing service continues unaffected

### Scenario: Service Host rejects stop for non-running service `@integration` `@orchestration`

**Given** a Service Host has no running service with `service_id = "nonexistent"`
**When** the Procedure Controller sends a `stop_service` request for `nonexistent`
**Then** the Service Host returns `OperationResult` with code `NOT_RUNNING`

### Scenario: Service Host reconciles state on startup `@integration` `@orchestration`

**Given** a Service Host has restarted after an unexpected termination
**When** the Service Host initializes
**Then** it publishes its current (empty) service state via `ServiceStatus`
**And** the Procedure Controller detects the state mismatch via the TRANSIENT_LOCAL status topics
**And** the Procedure Controller can re-issue `start_service` commands to restore the desired state

### Scenario: Service Host failure is detected via liveliness `@integration` `@orchestration`

**Given** a Service Host is publishing `ServiceCatalog` with automatic liveliness (2 s lease)
**And** the Procedure Controller is subscribed to `ServiceCatalog`
**When** the Service Host process is killed
**Then** the Procedure Controller detects liveliness lost within the 2 s lease period
**And** all `ServiceStatus` entries from that host are considered stale

---

## Procedure Controller

### Scenario: Procedure Controller discovers available Service Hosts `@integration` `@orchestration`

**Given** the Procedure Controller is subscribed to `ServiceCatalog` on the Orchestration databus
**When** Service Hosts publish their catalog entries
**Then** the Procedure Controller displays the available hosts and their capabilities

### Scenario: Procedure Controller reconstructs state on restart `@integration` `@orchestration` `@durability`

**Given** Service Hosts have been publishing `ServiceCatalog` and `ServiceStatus` with TRANSIENT_LOCAL durability
**When** the Procedure Controller restarts and joins the Orchestration databus
**Then** the controller immediately receives the most recent `ServiceCatalog` sample for each (host, service) pair
**And** the most recent `ServiceStatus` sample for each (host, service) pair
**And** reconstructs the full orchestration state without re-querying each host via RPC

### Scenario: Procedure Controller issues start_service via DDS RPC `@integration` `@orchestration`

**Given** the Procedure Controller has selected a Service Host and a service to start
**When** the controller sends a `start_service` RPC request to the targeted host
**Then** the request is delivered via DDS RPC on the Orchestration databus
**And** the targeted Service Host receives and processes the request
**And** the controller receives the `OperationResult` reply

### Scenario: Procedure Controller issues stop_service via DDS RPC `@integration` `@orchestration`

**Given** a service is running on a Service Host
**When** the Procedure Controller sends a `stop_service` RPC request
**Then** the targeted service is stopped
**And** the controller receives the `OperationResult` reply
**And** the controller observes the `ServiceStatus` transition to `STOPPED`

### Scenario: Procedure Controller joins the Orchestration databus and reads Procedure context directly `@integration` `@orchestration`

**Given** the Procedure Controller process starts
**When** the controller creates its DomainParticipants
**Then** one participant is on the Orchestration databus (for RPC and status)
**And** one participant is on the Procedure DDS domain (`operational` tag, read-only — for `ProcedureStatus` and `ProcedureContext`)
**And** one participant is on the Procedure DDS domain (`control` tag, read-only — for `RobotArmAssignment`)
**And** the controller does not join the Hospital Integration databus

### Scenario: Procedure Controller does not publish on any domain `@integration` `@orchestration`

**Given** the Procedure Controller has participants on the Orchestration and Procedure DDS domain
**When** the controller operates normally
**Then** the controller only subscribes (reads) on the Procedure DDS domain — it never publishes
**And** the controller only publishes via DDS RPC on the Orchestration databus (request/reply)

---

## Procedure Lifecycle Workflow

### Scenario: Procedure Controller shows "Start Procedure" when no procedure is active `@integration` `@orchestration` `@gui`

**Given** the Procedure Controller is displaying services for a room (e.g., OR-1)
**And** no `ServiceCatalog` entries for OR-1 have a non-empty `procedure_id` property
**When** the controller renders the room view
**Then** a "Start Procedure" action is visible and enabled

### Scenario: Start Procedure workflow presents idle services for selection `@integration` `@orchestration` `@gui`

**Given** the user clicks "Start Procedure" on the OR-1 controller page
**And** OR-1 has 6 services in `ServiceCatalog`, all with empty `procedure_id`
**When** the workflow UI is displayed
**Then** the user sees a selectable list of available idle services
**And** the user can select one or more services to deploy

### Scenario: Deploying selected services sends start_service RPCs with procedure_id `@integration` `@orchestration`

**Given** the user has selected 4 services from the idle list and clicks "Deploy"
**When** the controller initiates the deployment
**Then** the controller generates a unique `procedure_id` (e.g., `OR-1-001`)
**And** sends a `start_service` RPC to each selected service's Service Host, including `procedure_id` as a property
**And** each Service Host starts the requested service and re-publishes `ServiceCatalog` with the `procedure_id` property set

### Scenario: Procedure becomes active after services are deployed `@integration` `@orchestration` `@gui`

**Given** the controller has deployed services with `procedure_id = "OR-1-001"`
**And** at least one service has transitioned to `RUNNING` state
**When** the controller view refreshes
**Then** the room shows an active procedure indicator with the procedure ID
**And** the "Start Procedure" action is replaced by procedure management actions (add services, stop procedure)

### Scenario: One active procedure per room is enforced `@integration` `@orchestration` `@gui`

**Given** OR-1 already has an active procedure (`procedure_id = "OR-1-001"` on deployed services)
**When** the controller renders the room view
**Then** the "Start Procedure" action is disabled or hidden
**And** only "Add Services" and "Stop Procedure" actions are available

### Scenario: Adding services to a running procedure `@integration` `@orchestration` `@gui`

**Given** OR-1 has an active procedure with `procedure_id = "OR-1-001"` and 4 running services
**And** 2 additional idle services are available in the room
**When** the user clicks "Add Services" and selects the idle services
**Then** the controller sends `start_service` RPCs with the same `procedure_id = "OR-1-001"`
**And** the newly deployed services appear in the procedure's service list

### Scenario: Stopping a procedure stops all deployed services `@integration` `@orchestration` `@gui`

**Given** OR-1 has an active procedure with `procedure_id = "OR-1-001"` and 4 running services
**When** the user clicks "Stop Procedure"
**Then** the controller sends `stop_service` RPCs to all services whose `ServiceCatalog` entry has `procedure_id = "OR-1-001"`
**And** services transition through `STOPPING` → `STOPPED`
**And** `procedure_id` is cleared from the stopped services' `ServiceCatalog` entries
**And** the room returns to idle state with "Start Procedure" action re-enabled

### Scenario: Procedure state is reconstructed on controller restart `@integration` `@orchestration` `@durability`

**Given** a procedure is active in OR-1 with deployed services
**When** the Procedure Controller process restarts
**Then** the controller receives TRANSIENT_LOCAL `ServiceCatalog` and `ServiceStatus` samples
**And** services with a non-empty `procedure_id` matching OR-1 are displayed as part of the active procedure
**And** no manual re-deployment is required

---

## Room-Level GUI Navigation

### Scenario: Room GUI nav pill discovers sibling GUIs via ServiceCatalog `@integration` `@orchestration` `@gui`

**Given** a room-level GUI (e.g., Procedure Controller for OR-1) is running
**And** the shared `medtech.gui.room_nav` module has a read-only Orchestration databus participant
**When** sibling GUI services (e.g., Digital Twin for OR-1) publish `ServiceCatalog` entries with `gui_url` properties
**Then** the nav pill renders buttons for each discovered sibling GUI
**And** button labels reflect the service display name

### Scenario: Nav pill updates dynamically as sibling GUIs start and stop `@integration` `@orchestration` `@gui`

**Given** the nav pill is showing a button for Digital Twin
**When** the Digital Twin service is stopped and its `ServiceCatalog` `gui_url` is cleared
**Then** the nav pill removes the Digital Twin button without manual refresh
**When** a new GUI service (e.g., Camera Display) starts and publishes a `gui_url`
**Then** the nav pill adds a new button for Camera Display

### Scenario: Nav pill clicking a sibling navigates the current tab `@gui`

**Given** the nav pill shows buttons for Controller and Digital Twin
**And** the user is viewing the Controller page
**When** the user clicks the "Digital Twin" button
**Then** the browser navigates the current tab to the Digital Twin's URL

### Scenario: Room-level GUI has no upward link to hospital `@gui`

**Given** a room-level GUI is running with the nav pill
**When** the nav pill renders
**Then** there is no link or button to the hospital dashboard
**And** the room GUI can operate independently without a hospital instance deployed above it

---

## Orchestration Domain Isolation

### Scenario: Orchestration databus is isolated from the Procedure databuses `@integration` `@orchestration` `@isolation`

**Given** a participant on the Orchestration databus (Orchestration databus)
**And** a participant on the Procedure DDS domain (the Procedure DDS domain, any tag)
**When** both are running
**Then** they do not discover each other
**And** no data published on the Orchestration databus is received on the Procedure DDS domain (or vice versa)

### Scenario: Orchestration failure does not disrupt surgical data `@integration` `@orchestration` `@isolation`

**Given** a surgical procedure is active with services publishing on the Procedure DDS domain
**And** the Procedure Controller is managing services via the Orchestration databus
**When** the Procedure Controller process crashes
**Then** all surgical data continues flowing on the Procedure DDS domain without interruption
**And** no deadline violations or liveliness losses occur on Procedure DDS domain topics as a result of the Orchestration databus failure

### Scenario: Orchestration databus has no domain tags and no Publisher/Subscriber partitions `@integration` `@orchestration`

**Given** a Procedure Controller participant on the Orchestration databus
**And** a Service Host participant on the Orchestration databus
**When** both are active with matching DomainParticipant-level tier partitions
**Then** they discover each other directly — no domain tag is required or set
**And** no Publisher/Subscriber partition QoS is applied to any DataWriter or DataReader on this domain

### Scenario: Tier isolation via static DomainParticipant partition `@integration` `@orchestration` `@partition`

**Given** a procedure-tier Service Host starts with DomainParticipant partition `procedure`
**And** a facility-tier Service Host starts with DomainParticipant partition `facility`
**And** a Procedure Controller starts with DomainParticipant partition `procedure`
**When** all participants are active on the Orchestration databus
**Then** the Procedure Controller discovers procedure-tier hosts and receives their `ServiceCatalog` and `ServiceStatus`
**And** the Procedure Controller does not discover facility-tier hosts
**And** no partition change occurs at runtime — all tier partitions are set once at startup and never modified

### Scenario: Cross-tier observer uses wildcard partition `@integration` `@orchestration` `@partition`

**Given** a hospital admin controller starts with DomainParticipant partition `*`
**When** the controller is active on the Orchestration databus
**Then** it discovers both procedure-tier and facility-tier Service Hosts
**And** no partition-change churn occurs because the wildcard is set at startup and never changed

### Scenario: Untiered Service Host uses the unassigned partition `@integration` `@orchestration` `@partition`

**Given** a Service Host has not been configured with an orchestration tier
**When** the Service Host starts on the Orchestration databus
**Then** the Service Host uses DomainParticipant partition `unassigned`
**And** it is not discoverable by a Procedure Controller or facility controller unless they also use `unassigned` or a wildcard

### Scenario: Room context is carried as a ServiceCatalog property `@integration` `@orchestration`

**Given** a Service Host is configured for operating room `OR-1`
**When** the Service Host publishes `ServiceCatalog` instances on startup
**Then** each `ServiceCatalog` instance includes a property with key `room_id` and value `OR-1`
**And** the Procedure Controller reads `room_id` from the catalog to filter or label hosts by room in the UI
**And** no DDS partition change is required for the controller to switch its room filter view

### Scenario: Procedure context is reflected in ServiceCatalog after service start `@integration` `@orchestration`

**Given** the Procedure Controller sends a `start_service` RPC request carrying a property `procedure_id = "proc-001"`
**And** the Service Host starts the service successfully
**When** the service enters `RUNNING` state
**Then** the Service Host re-publishes the service's `ServiceCatalog` instance with a property `procedure_id = "proc-001"`
**And** the property is cleared (removed or set to empty string) when the service is stopped

### Scenario: GUI service URL is reflected in ServiceCatalog after service start `@integration` `@orchestration`

**Given** the Procedure Controller sends a `start_service` RPC request for a GUI-capable service
**And** the service binds to a network port after starting
**When** the service enters `RUNNING` state
**Then** the Service Host re-publishes the service's `ServiceCatalog` instance with a property `gui_url` containing the active endpoint URL (e.g., `http://host-or1:8081`)
**And** the Procedure Controller detects the non-empty `gui_url` property and renders an "Open" action button for that service
**And** the `gui_url` property is cleared when the service is stopped
**And** services without a GUI do not publish a `gui_url` property

---

## DDS RPC Communication

### Scenario: RPC request is delivered to the correct Service Host `@integration` `@orchestration`

**Given** two Service Hosts with unique `host_id` values (`robot-host-or1`, `clinical-host-or1`)
**When** the Procedure Controller sends a `start_service` RPC request to `ServiceHostControl/robot-host-or1`
**Then** only `robot-host-or1` receives and processes the request
**And** `clinical-host-or1` is not invoked

### Scenario: RPC uses RELIABLE KEEP_ALL QoS `@integration` `@orchestration`

**Given** a `ServiceHostControl` RPC interface configured with `Pattern.RPC` QoS
**When** the Procedure Controller sends a request
**Then** the request is delivered reliably (RELIABLE)
**And** no request is lost under normal conditions

### Scenario: RPC timeout is handled gracefully `@integration` `@orchestration`

**Given** the Procedure Controller sends an RPC request to a Service Host
**When** the Service Host does not respond within the RPC timeout
**Then** the Procedure Controller receives a timeout indication
**And** no crash, hang, or unhandled exception occurs
**And** the controller can retry or escalate

---

## System Initialization

### Scenario: Orchestration databus participants match within time budget `@integration` `@orchestration` `@performance`

**Given** a Procedure Controller and one or more Service Hosts are started on `hospital-net`
**When** all processes are running
**Then** all Orchestration databus DomainParticipant endpoints have matched within 15 s
**And** `ServiceCatalog` and `ServiceStatus` TRANSIENT_LOCAL state has been delivered to the Procedure Controller within the same 15 s window

### Scenario: Procedure Controller restart re-integrates within time budget `@integration` `@orchestration` `@performance`

**Given** the Orchestration databus is active with running Service Hosts
**When** the Procedure Controller process is stopped and restarted
**Then** the controller has re-matched all expected endpoints within 15 s
**And** TRANSIENT_LOCAL state is re-delivered within the same 15 s window
**And** the controller can resume issuing commands without manual intervention
