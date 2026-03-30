# Spec: Dynamic Multi-Arm Orchestration (V1.2)

Behavioral specifications for the V1.2 Dynamic Multi-Arm Orchestration
milestone: dynamic spawning, spatial assignment, and positioning of
multiple robot arm services around a surgical table, with full lifecycle
visibility from the Procedure Controller and digital twin display.

All scenarios assume the Procedure domain `control` tag and partition
`room/<room_id>/procedure/<procedure_id>` unless stated otherwise.
Orchestration domain scenarios use partition `room/<room_id>`.

---

## Summary of Concrete Requirements

| Requirement | Value |
|-------------|-------|
| `RobotArmAssignment` domain tag | `control` (Class C / Class III) |
| `RobotArmAssignment` publication model | Write-on-change (publish on state transition; `dispose()` on arm removal) |
| `RobotArmAssignment` durability | TRANSIENT_LOCAL — late-joining controllers and digital twins receive current assignment state |
| `RobotArmAssignment` QoS profile | `TopicProfiles::RobotArmAssignment` (inherits `Patterns::State`) |
| `RobotArmAssignment` key field | `robot_id` |
| `ArmAssignmentState` lifecycle | `IDLE → ASSIGNED → POSITIONING → OPERATIONAL` (forward only during normal operation; `FAILED` on error) |
| `ArmAssignmentState` enum values | `UNKNOWN`, `IDLE`, `ASSIGNED`, `POSITIONING`, `OPERATIONAL`, `FAILED` |
| `TablePosition` enum values | `UNKNOWN`, `HEAD`, `FOOT`, `LEFT`, `RIGHT`, `LEFT_HEAD`, `RIGHT_HEAD`, `LEFT_FOOT`, `RIGHT_FOOT` |
| `MAX_ARM_COUNT` | 8 — maximum robot arms per surgical table |
| Arm departure notification | `dispose()` on `RobotArmAssignment` instance → subscribers see `NOT_ALIVE_DISPOSED` |
| Procedure start gate | All requested arms must reach `OPERATIONAL` before procedure control is enabled |
| Procedure Controller multi-domain model | Orchestration + Procedure `control` + Hospital |
| Liveliness for `RobotArmAssignment` | 2 s (inherited from `Patterns::State` via `Liveliness2s` snippet) |
| Arm instance correlation | `robot_id` — shared key across `RobotArmAssignment`, `RobotState`, `RobotCommand`, `OperatorInput` |
| Digital twin rendering | Subscribes to `RobotArmAssignment` on `control` tag; renders arm positions and lifecycle status |
| Orchestration-to-assignment coordination latency | ≤ 5 s from `ServiceStatus(RUNNING)` on Orchestration domain to first `RobotArmAssignment` sample on Procedure domain |

*This table must be updated whenever a concrete value in the scenarios below is added or changed.*

---

## RobotArmAssignment Topic Lifecycle

### Scenario: Arm publishes ASSIGNED on startup `@integration` `@multi-arm`

**Given** a robot arm service has been started by a Service Host via `start_service` RPC
**And** the arm service's `ServiceStatus` is `RUNNING` on the Orchestration domain
**When** the arm service initializes its Procedure domain `control`-tag participant
**Then** the arm publishes a `RobotArmAssignment` sample with `status = ASSIGNED` and the requested `table_position`
**And** remote subscribers (Procedure Controller, digital twin) begin tracking this `robot_id` instance

### Scenario: Arm transitions to POSITIONING during movement `@integration` `@multi-arm`

**Given** an arm has published `RobotArmAssignment(status = ASSIGNED)`
**When** the arm begins moving to its assigned table position
**Then** the arm publishes an updated `RobotArmAssignment` sample with `status = POSITIONING`
**And** the `table_position` field remains the target position (not the current position)

### Scenario: Arm reaches position and becomes OPERATIONAL `@integration` `@multi-arm`

**Given** an arm has published `RobotArmAssignment(status = POSITIONING)`
**When** the arm reaches its assigned table position
**Then** the arm publishes `RobotArmAssignment(status = OPERATIONAL)`
**And** the Procedure Controller considers this arm procedure-ready

### Scenario: Arm departs via dispose `@integration` `@multi-arm`

**Given** an arm is in any assignment state (`ASSIGNED`, `POSITIONING`, `OPERATIONAL`)
**When** the arm service is stopped (via `stop_service` RPC or graceful shutdown)
**Then** the arm calls `dispose()` on its `RobotArmAssignment` instance before shutting down
**And** subscribers receive a `NOT_ALIVE_DISPOSED` instance state notification
**And** the Procedure Controller removes the arm from its table layout view

### Scenario: Arm publishes FAILED on positioning error `@integration` `@multi-arm`

**Given** an arm is in `ASSIGNED` or `POSITIONING` state
**When** an unrecoverable positioning error occurs (e.g., collision avoidance interlock, mechanical fault)
**Then** the arm publishes `RobotArmAssignment(status = FAILED)`
**And** the Procedure Controller displays the failure and does not count this arm as procedure-ready

### Scenario: RobotArmAssignment uses write-on-change publication model `@unit` `@multi-arm`

**Given** an arm is in `OPERATIONAL` state with no state change
**When** time passes without a lifecycle transition
**Then** no new `RobotArmAssignment` samples are published
**And** arm health is detected via liveliness QoS (2 s lease), not periodic publication

### Scenario: RobotArmAssignment is TRANSIENT_LOCAL for late joiners `@integration` `@multi-arm` `@durability`

**Given** two arms have published `RobotArmAssignment` samples and are in `OPERATIONAL` state
**When** the Procedure Controller restarts and joins the Procedure domain `control` tag
**Then** the controller immediately receives the most recent `RobotArmAssignment` sample for each arm
**And** reconstructs the full table layout without re-querying the arms

### Scenario: ArmAssignmentState enum is IDL-generated `@unit` `@multi-arm`

**Given** the `ArmAssignmentState` enum is defined in `interfaces/idl/surgery/`
**When** both C++ and Python code reference `ArmAssignmentState`
**Then** they use the IDL-generated type (`Surgery::ArmAssignmentState` in C++, the corresponding Python import)
**And** no hand-written enum duplicate exists

### Scenario: TablePosition enum is IDL-generated `@unit` `@multi-arm`

**Given** the `TablePosition` enum is defined in `interfaces/idl/surgery/`
**When** both C++ and Python code reference `TablePosition`
**Then** they use the IDL-generated type (`Surgery::TablePosition` in C++, the corresponding Python import)
**And** no hand-written enum duplicate exists

---

## Multi-Arm Orchestration Flow

### Scenario: Procedure Controller requests arm startup with table position `@integration` `@multi-arm` `@orchestration`

**Given** the Procedure Controller has discovered a Robot Service Host via `HostCatalog`
**When** the controller sends a `start_service` RPC request to the Robot Service Host
**Then** the request includes the desired `table_position` in the service configuration parameters
**And** the Service Host spawns the arm service with the requested position

### Scenario: ServiceStatus RUNNING precedes RobotArmAssignment ASSIGNED `@integration` `@multi-arm` `@orchestration`

**Given** the Procedure Controller sends `start_service` to a Robot Service Host
**When** the Service Host spawns the arm service
**Then** `ServiceStatus(state = RUNNING)` is published on the Orchestration domain first
**And** `RobotArmAssignment(status = ASSIGNED)` is published on the Procedure domain `control` tag within 5 s
**And** the Procedure Controller correlates the two via matching `robot_id` / `service_id`

### Scenario: Procedure Controller waits for all arms OPERATIONAL before enabling control `@integration` `@multi-arm`

**Given** the Procedure Controller has requested N arms for a procedure
**And** N − 1 arms have reached `RobotArmAssignment(status = OPERATIONAL)`
**When** the final arm reaches `OPERATIONAL`
**Then** the Procedure Controller enables procedure control (all arms ready)
**And** the procedure can transition from setup phase to active phase

### Scenario: Procedure Controller does not enable control with arms in non-OPERATIONAL states `@integration` `@multi-arm`

**Given** the Procedure Controller has requested 3 arms for a procedure
**And** 2 arms are `OPERATIONAL` and 1 arm is `POSITIONING`
**When** the controller evaluates procedure readiness
**Then** procedure control remains disabled
**And** the controller UI shows which arms are not yet ready and their current states

### Scenario: Multiple arms coexist at distinct table positions `@integration` `@multi-arm`

**Given** 3 arms are started with positions `HEAD`, `LEFT`, and `RIGHT`
**When** all 3 arms reach `OPERATIONAL`
**Then** each arm's `RobotArmAssignment` has a distinct `table_position` value
**And** each arm's `robot_id` key correlates with its `RobotState` and `RobotCommand` instances
**And** the Procedure Controller's table layout shows all 3 positions occupied

### Scenario: Arm removal during procedure is non-disruptive to remaining arms `@integration` `@multi-arm`

**Given** 3 arms are `OPERATIONAL` in a procedure
**When** 1 arm is stopped (via `stop_service` RPC)
**And** the stopped arm calls `dispose()` on its `RobotArmAssignment`
**Then** the remaining 2 arms continue operating without interruption
**And** their `RobotState` and `OperatorInput` streams are unaffected
**And** the Procedure Controller updates the table layout to show 2 active arms

### Scenario: MAX_ARM_COUNT is enforced `@unit` `@multi-arm`

**Given** the Procedure Controller tracks the number of active arms in a procedure
**When** a request would exceed `MAX_ARM_COUNT` (8) arms
**Then** the request is rejected by the Procedure Controller
**And** no `start_service` RPC is sent to the Service Host

---

## Arm Instance Correlation

### Scenario: RobotArmAssignment correlates with RobotState via robot_id `@integration` `@multi-arm`

**Given** an arm is publishing `RobotArmAssignment` with `robot_id = "arm-001"`
**And** the same arm is publishing `RobotState` with `robot_id = "arm-001"`
**When** a subscriber receives both topics
**Then** the subscriber correlates the assignment state and robot state using the shared `robot_id` key
**And** the digital twin can display both position assignment and real-time joint state for each arm

### Scenario: RobotArmAssignment correlates with RobotCommand via robot_id `@integration` `@multi-arm`

**Given** an arm is `OPERATIONAL` with `robot_id = "arm-002"`
**When** the operator publishes `RobotCommand` targeting `robot_id = "arm-002"`
**Then** the command reaches the correct arm's control loop
**And** the arm's `RobotArmAssignment` is unaffected (assignment is orthogonal to command execution)

### Scenario: Arm procedure_id correlates with ProcedureContext `@integration` `@multi-arm`

**Given** a procedure is active with `procedure_id = "proc-2026-0042"`
**And** an arm publishes `RobotArmAssignment` with `procedure_id = "proc-2026-0042"`
**When** a subscriber receives both `ProcedureContext` and `RobotArmAssignment`
**Then** the subscriber can associate the arm with the correct procedure
**And** the partition already scopes data per procedure — `procedure_id` is an additional application-level correlation

---

## Procedure Controller Enhancement

### Scenario: Procedure Controller joins Procedure domain control tag `@integration` `@multi-arm` `@orchestration`

**Given** the Procedure Controller process starts
**When** the controller creates its DomainParticipants
**Then** one participant is on the Orchestration domain (for RPC and status)
**And** one participant is on the Procedure domain with `control` domain tag (for `RobotArmAssignment` subscription)
**And** one participant is on the Hospital domain (for scheduling context, read-only)
**And** the controller has 3 DomainParticipants total (plus Observability)

### Scenario: Procedure Controller subscribes to RobotArmAssignment `@integration` `@multi-arm`

**Given** the Procedure Controller has a Procedure domain `control`-tag participant
**When** arm services publish `RobotArmAssignment` in the same partition
**Then** the controller receives all arm assignment updates
**And** can build and maintain a complete table layout view

### Scenario: Procedure Controller is read-only on the Procedure domain `@integration` `@multi-arm` `@isolation`

**Given** the Procedure Controller has a Procedure domain `control`-tag participant
**When** the controller processes `RobotArmAssignment` data
**Then** the controller only subscribes (reads) — it never publishes on the Procedure domain
**And** all procedure-level commands are issued via the Orchestration domain RPC interface

### Scenario: Procedure Controller table layout UI `@gui` `@multi-arm`

**Given** the Procedure Controller GUI is displaying the table layout panel
**When** `RobotArmAssignment` samples are received for multiple arms
**Then** the GUI renders arm positions around a schematic surgical table
**And** each arm shows its current `ArmAssignmentState` with color-coded status indicators
**And** `OPERATIONAL` arms are green, `POSITIONING` arms are amber, `FAILED` arms are red, `IDLE`/`ASSIGNED` are grey

---

## Digital Twin Enhancement

### Scenario: Digital twin subscribes to RobotArmAssignment `@integration` `@multi-arm` `@gui`

**Given** the digital twin display is running with a Procedure domain `control`-tag participant
**When** arm services publish `RobotArmAssignment` in the same partition
**Then** the digital twin receives arm assignment and positioning data
**And** renders all arms at their table positions

### Scenario: Digital twin renders multi-arm table layout `@gui` `@multi-arm`

**Given** 3 arms are in `OPERATIONAL` state at positions `HEAD`, `LEFT`, and `RIGHT`
**When** the digital twin display updates
**Then** it renders all 3 arms around the table schematic at their assigned positions
**And** each arm is color-coded by lifecycle status
**And** clicking an arm shows an overlay with capabilities, assignment state, and real-time joint data

### Scenario: Digital twin updates on arm lifecycle changes `@gui` `@multi-arm`

**Given** the digital twin display is showing 3 `OPERATIONAL` arms
**When** one arm transitions to `FAILED`
**Then** the digital twin updates that arm's status indicator to red
**And** when the failed arm's instance is disposed, it is removed from the table layout

---

## QoS Compliance

### Scenario: RobotArmAssignment uses State pattern QoS `@integration` `@multi-arm` `@qos`

**Given** a DataWriter for `RobotArmAssignment` is created with `TopicProfiles::RobotArmAssignment`
**And** a DataReader for `RobotArmAssignment` is created with `TopicProfiles::RobotArmAssignment`
**When** endpoints match
**Then** reliability is RELIABLE
**And** durability is TRANSIENT_LOCAL
**And** history is KEEP_LAST depth 1
**And** liveliness is AUTOMATIC with a 2 s lease duration

### Scenario: RobotArmAssignment liveliness detects arm health `@integration` `@multi-arm` `@failover`

**Given** an arm is publishing `RobotArmAssignment` with 2 s liveliness lease
**And** the Procedure Controller is subscribed to `RobotArmAssignment`
**When** the arm process is killed without calling `dispose()`
**Then** the Procedure Controller detects liveliness lost within 2 s
**And** marks the arm instance as `NOT_ALIVE_NO_WRITERS`
**And** the arm is no longer considered procedure-ready

---

## Isolation and Safety

### Scenario: RobotArmAssignment is on the control tag `@integration` `@multi-arm` `@isolation`

**Given** a publisher for `RobotArmAssignment` on the Procedure domain `control` tag
**And** a subscriber on the Procedure domain `clinical` tag attempting to subscribe to `RobotArmAssignment`
**When** both participants are active
**Then** they do not discover each other
**And** no `RobotArmAssignment` data crosses domain tag boundaries

### Scenario: Orchestration domain failure does not affect arm assignment data `@integration` `@multi-arm` `@isolation`

**Given** arms are `OPERATIONAL` and publishing `RobotArmAssignment` on the Procedure domain
**And** the Procedure Controller is managing services via the Orchestration domain
**When** the Procedure Controller process crashes
**Then** `RobotArmAssignment` samples continue flowing on the Procedure domain without interruption
**And** no deadline violations or liveliness losses occur on `RobotArmAssignment` due to the Orchestration domain failure

---

## Acceptance

### Scenario: Multi-arm procedure lifecycle end-to-end `@e2e` `@multi-arm` `@acceptance`

**Given** a Procedure Controller, 2 Robot Service Hosts, and a digital twin display are running in Docker Compose
**And** the Procedure Controller is on the Orchestration domain and the Procedure domain `control` tag
**When** the Procedure Controller issues `start_service` RPCs for 2 arms at positions `LEFT` and `RIGHT`
**Then** both Service Hosts spawn arm services
**And** both arms publish `RobotArmAssignment` transitioning through `ASSIGNED → POSITIONING → OPERATIONAL`
**And** the Procedure Controller shows both arms at their table positions with green (OPERATIONAL) status
**And** the digital twin renders both arms around the table
**When** the Procedure Controller issues `stop_service` for one arm
**Then** the stopped arm calls `dispose()` on its `RobotArmAssignment`
**And** the remaining arm continues `OPERATIONAL`
**And** the Procedure Controller and digital twin update to show one active arm
