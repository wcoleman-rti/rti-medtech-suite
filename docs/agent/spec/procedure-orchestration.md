# Spec: Procedure Orchestration

Behavioral specifications for the V1.1 Procedure Orchestration milestone:
the `medtech::Service` interface, dual-mode participant pattern, Service
Host framework, Procedure Controller GUI, Orchestration domain (Domain 15)
communication, and DDS RPC lifecycle management.

All scenarios assume the Orchestration domain uses partition `room/<room_id>`
(e.g., `room/OR-1`) unless stated otherwise. Service Hosts not yet assigned
to an OR use the `unassigned` partition.

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
| `HostCatalog` durability | TRANSIENT_LOCAL (late-joining controllers receive current state) |
| `ServiceStatus` durability | TRANSIENT_LOCAL (late-joining controllers receive current state) |
| `ServiceHostControl` RPC QoS | `Pattern.RPC` (RELIABLE, KEEP_ALL) |
| Orchestration domain ID | 15 |
| Orchestration partition format | `room/<room_id>` |
| Unassigned Service Host partition | `unassigned` |
| Service Host liveliness lease | 2 s (host failure detection via liveliness) |
| Procedure Controller domains | Orchestration + Hospital |
| Orchestration → Procedure domain isolation | Complete — orchestration failure must not disrupt surgical data |
| Service context injection | All context via constructor/setter — never environment variables |
| RPC operations | `start_service`, `stop_service`, `configure_service`, `get_capabilities`, `get_health` |

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
**When** V1.1 service classes are deployed in standalone mode (no Service Host, no Orchestration domain)
**Then** all V1.0 spec scenarios continue to pass without modification
**And** the service operates identically to its V1.0 predecessor

### Scenario: Service does not read environment variables `@unit` `@orchestration`

**Given** a DDS service class implementing `medtech::Service`
**When** the service is constructed and run
**Then** the service never reads environment variables, CLI arguments, or config files directly
**And** all operational context (room ID, procedure ID, participant) is received via constructor parameters

---

## Service Host Framework

### Scenario: Service Host publishes HostCatalog on startup `@integration` `@orchestration`

**Given** a Service Host is started and assigned to partition `room/OR-1`
**When** the Service Host's Orchestration domain participant becomes active
**Then** the Service Host publishes a `HostCatalog` sample with its `host_id`, supported service types, and capacity
**And** the sample is TRANSIENT_LOCAL and available to late-joining controllers

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
**And** the request specifies `service_id` and configuration parameters
**When** the Service Host receives the request
**Then** the Service Host constructs the requested service in hosted mode (passing a participant)
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

**Given** a Service Host is publishing `HostCatalog` with automatic liveliness (2 s lease)
**And** the Procedure Controller is subscribed to `HostCatalog`
**When** the Service Host process is killed
**Then** the Procedure Controller detects liveliness lost within the 2 s lease period
**And** all `ServiceStatus` entries from that host are considered stale

---

## Procedure Controller

### Scenario: Procedure Controller discovers available Service Hosts `@integration` `@orchestration`

**Given** the Procedure Controller is subscribed to `HostCatalog` on the Orchestration domain
**When** Service Hosts publish their catalog entries
**Then** the Procedure Controller displays the available hosts and their capabilities

### Scenario: Procedure Controller reconstructs state on restart `@integration` `@orchestration` `@durability`

**Given** Service Hosts have been publishing `HostCatalog` and `ServiceStatus` with TRANSIENT_LOCAL durability
**When** the Procedure Controller restarts and joins the Orchestration domain
**Then** the controller immediately receives the most recent `HostCatalog` sample for each host
**And** the most recent `ServiceStatus` sample for each (host, service) pair
**And** reconstructs the full orchestration state without re-querying each host via RPC

### Scenario: Procedure Controller issues start_service via DDS RPC `@integration` `@orchestration`

**Given** the Procedure Controller has selected a Service Host and a service to start
**When** the controller sends a `start_service` RPC request to the targeted host
**Then** the request is delivered via DDS RPC on the Orchestration domain
**And** the targeted Service Host receives and processes the request
**And** the controller receives the `OperationResult` reply

### Scenario: Procedure Controller issues stop_service via DDS RPC `@integration` `@orchestration`

**Given** a service is running on a Service Host
**When** the Procedure Controller sends a `stop_service` RPC request
**Then** the targeted service is stopped
**And** the controller receives the `OperationResult` reply
**And** the controller observes the `ServiceStatus` transition to `STOPPED`

### Scenario: Procedure Controller joins both Orchestration and Hospital domains `@integration` `@orchestration`

**Given** the Procedure Controller process starts
**When** the controller creates its DomainParticipants
**Then** one participant is on the Orchestration domain (for RPC and status)
**And** one participant is on the Hospital domain (for scheduling context, read-only)
**And** the controller does not join the Procedure domain directly

### Scenario: Procedure Controller is read-only on the Hospital domain `@integration` `@orchestration`

**Given** the Procedure Controller has a participant on the Hospital domain
**When** the controller accesses Hospital domain data
**Then** the controller only subscribes (reads) — it never publishes on the Hospital domain
**And** all Hospital domain data arrives via the existing Routing Service bridge from the Procedure domain

---

## Orchestration Domain Isolation

### Scenario: Orchestration domain is isolated from the Procedure domain `@integration` `@orchestration` `@isolation`

**Given** a participant on the Orchestration domain (Domain 15)
**And** a participant on the Procedure domain (Domain 10, any tag)
**When** both are running
**Then** they do not discover each other
**And** no data published on the Orchestration domain is received on the Procedure domain (or vice versa)

### Scenario: Orchestration failure does not disrupt surgical data `@integration` `@orchestration` `@isolation`

**Given** a surgical procedure is active with services publishing on the Procedure domain
**And** the Procedure Controller is managing services via the Orchestration domain
**When** the Procedure Controller process crashes
**Then** all surgical data continues flowing on the Procedure domain without interruption
**And** no deadline violations or liveliness losses occur on Procedure domain topics as a result of the Orchestration domain failure

### Scenario: Orchestration domain has no domain tags `@integration` `@orchestration`

**Given** a Procedure Controller participant on the Orchestration domain
**And** a Service Host participant on the Orchestration domain
**When** both are active in the same partition
**Then** they discover each other directly — no domain tag is required or set
**And** all orchestration participants share a single tag-free domain space

### Scenario: Orchestration partition scopes communication to an OR `@integration` `@orchestration` `@partition`

**Given** Service Host A is on the Orchestration domain with partition `room/OR-1`
**And** Service Host B is on the Orchestration domain with partition `room/OR-3`
**When** both publish `HostCatalog` and `ServiceStatus`
**Then** a Procedure Controller with partition `room/OR-1` receives data only from Service Host A
**And** a Procedure Controller with partition `room/OR-3` receives data only from Service Host B

### Scenario: Unassigned Service Host uses the unassigned partition `@integration` `@orchestration` `@partition`

**Given** a Service Host has not been assigned to an OR
**When** the Service Host starts on the Orchestration domain
**Then** the Service Host uses partition `unassigned`
**And** it is not discoverable by a Procedure Controller scoped to a specific room partition

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

### Scenario: Orchestration domain participants match within time budget `@integration` `@orchestration` `@performance`

**Given** a Procedure Controller and one or more Service Hosts are started on `hospital-net`
**When** all processes are running
**Then** all Orchestration domain DomainParticipant endpoints have matched within 15 s
**And** `HostCatalog` and `ServiceStatus` TRANSIENT_LOCAL state has been delivered to the Procedure Controller within the same 15 s window

### Scenario: Procedure Controller restart re-integrates within time budget `@integration` `@orchestration` `@performance`

**Given** the Orchestration domain is active with running Service Hosts
**When** the Procedure Controller process is stopped and restarted
**Then** the controller has re-matched all expected endpoints within 15 s
**And** TRANSIENT_LOCAL state is re-delivered within the same 15 s window
**And** the controller can resume issuing commands without manual intervention
