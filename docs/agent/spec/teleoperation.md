# Spec: Teleoperation / Remote Operator (V2.1)

Behavioral specifications for the V2.1 Teleoperation milestone:
procedure-wide exclusive ownership on `OperatorInput`, ownership
strength tiering via Routing Service, safe-hold mode during control
authority transitions, the ControlAuthority supervisory state machine,
AUTOMATIC liveliness + DEADLINE failover detection, and the reverse
control-tag Routing Service bridge.

**Prerequisite:** V2.0 (Security) must be complete before V2.1
implementation begins. All teleoperation data paths require Connext
Security Plugins for authentication and topic-level access control.

All scenarios assume the Procedure control databus and partition
`room/<room_id>/procedure/<procedure_id>` unless stated otherwise.

---

## Summary of Concrete Requirements

| Requirement | Value |
|-------------|-------|
| `OperatorInput` ownership | `EXCLUSIVE_OWNERSHIP_QOS` — exactly one operator source controls all arms in a procedure |
| Ownership scope | Procedure-wide (not per-arm); per-arm override is prohibited |
| Local console ownership strength | 200 (static, configured in console application QoS) |
| Hospital→Procedure RS output strength | 100 (set on Routing Service output DataWriter QoS) |
| Cloud→Procedure RS output strength | 50 (set on Routing Service output DataWriter QoS) |
| Console strength configuration | Static — console uses the same strength regardless of deployment location |
| Liveliness kind (control-tag participant) | `AUTOMATIC` — on the dedicated `control`-tag DomainParticipant |
| Liveliness lease duration (control-tag participant) | 2 s (existing `LivelinessStandard` snippet) |
| `OperatorInput` DEADLINE period | 4 ms (existing `DeadlineOperatorInput` snippet) |
| Safe-hold deceleration profile | Controlled deceleration to zero velocity (kinematic safe-stop, not snap-stop) |
| Safe-hold `RobotState.operational_mode` | `PAUSED` |
| Safe-hold `RobotState` publication rate | 100 Hz (unchanged from normal operation) |
| Emergency safe-stop trigger | ALL operator sources lose liveliness |
| Emergency safe-stop interlock | `SafetyInterlock(interlock_active = true, reason = "no active operator")` |
| Reclaim acknowledgment | Returning operator must explicitly acknowledge current robot state before commands are executed |
| ControlAuthority states | `LOCAL_ACTIVE`, `REMOTE_ACTIVE`, `FAILOVER_PENDING`, `RECLAIM_PENDING`, `NO_OPERATOR` |
| Safe-hold scope | Per-procedure (not per-arm) — all arms enter safe-hold simultaneously |
| Routing Service control-tag bridge | Separate `domain_route` with dedicated `control`-tag participants, isolated from observational bridge |
| Hospital Integration databus tag re-evaluation | Required before V2.1 implementation — determine if Hospital Integration databus needs a `control` tag |

*This table must be updated whenever a concrete value in the scenarios below is added or changed.*

---

## Exclusive Ownership on OperatorInput

### Scenario: Only one operator source controls the procedure `@integration` `@teleop`

**Given** `OperatorInput` is configured with `EXCLUSIVE_OWNERSHIP_QOS`
**And** local console A publishes `OperatorInput` with ownership strength 200
**And** remote hospital console B publishes `OperatorInput` (via Routing Service) with effective ownership strength 100
**When** both consoles are alive and publishing
**Then** the robot controller's DataReader receives samples only from console A (highest strength)
**And** console B's samples are suppressed by DDS ownership arbitration

### Scenario: Ownership is procedure-wide, not per-arm `@integration` `@teleop`

**Given** a procedure has 3 arms with `robot_id` keys `arm-001`, `arm-002`, `arm-003`
**And** local console publishes `OperatorInput` for all 3 arms with ownership strength 200
**When** a remote console publishes `OperatorInput` for `arm-002` with effective strength 100
**Then** the local console retains ownership for all 3 arms
**And** per-arm ownership override does not occur — the highest-strength source controls all arms

### Scenario: Lower-strength writer takes over when higher-strength writer loses liveliness `@integration` `@teleop` `@failover`

**Given** local console A (strength 200) is the active owner of `OperatorInput`
**And** hospital console B (effective strength 100 via RS) is a standby writer
**When** console A's process crashes (liveliness expires on the `control`-tag participant)
**Then** the robot controller's DataReader automatically switches to console B's samples
**And** console B becomes the active owner for all arms in the procedure

### Scenario: Exclusive ownership resolves via DDS, not application logic `@integration` `@teleop`

**Given** multiple `OperatorInput` writers with different ownership strengths
**When** the writers' liveliness states change
**Then** DDS exclusive ownership arbitration determines the active writer
**And** no application-level election, token passing, or coordination protocol is required for data-path switching

---

## Ownership Strength via Routing Service

### Scenario: Routing Service lowers ownership strength for hospital route `@integration` `@teleop` `@routing`

**Given** a hospital console publishes `OperatorInput` on the Hospital Integration databus with the console's native strength (200)
**When** Routing Service bridges the `OperatorInput` samples to the Procedure control databus
**Then** the Routing Service output DataWriter publishes with ownership strength 100
**And** the console application itself is unmodified — strength lowering is a Routing Service QoS transformation

### Scenario: Routing Service lowers ownership strength for cloud route `@integration` `@teleop` `@routing`

**Given** a cloud console publishes `OperatorInput` on the Cloud domain with the console's native strength (200)
**When** WAN Routing Service bridges the `OperatorInput` samples to the Procedure control databus
**Then** the Routing Service output DataWriter publishes with ownership strength 50
**And** the console application itself is unmodified

### Scenario: Console uses identical configuration at all deployment locations `@unit` `@teleop`

**Given** the surgeon console application
**When** it is deployed bedside (local), at the hospital level, or at the cloud level
**Then** the console uses the same ownership strength (200) in all cases
**And** the only difference is which domain the console publishes on (Procedure direct, Hospital, or Cloud)
**And** Routing Service is responsible for strength adjustment — not the console

### Scenario: Routing Service control-tag route is isolated from observational bridge `@integration` `@teleop` `@routing` `@isolation`

**Given** Routing Service has two domain routes:
  1. Observational bridge (Procedure `clinical`/`operational` → Hospital, existing V1.0 route)
  2. Control-tag bridge (Hospital → Procedure `control`, new V2.1 route)
**When** the observational bridge experiences a fault (e.g., session error, restart)
**Then** the control-tag bridge continues operating without interruption
**And** `OperatorInput` samples continue flowing from the remote console to the Procedure DDS domain

### Scenario: Control-tag route uses dedicated participants `@integration` `@teleop` `@routing`

**Given** the Routing Service control-tag domain route
**When** the route creates its DomainParticipants
**Then** the Procedure-side participant carries the `control` domain tag
**And** this participant is separate from the observational bridge's participants
**And** the participants discover only `control`-tag endpoints on the Procedure DDS domain

---

## Safe-Hold Mode

### Scenario: Robot enters safe-hold on active operator liveliness loss `@integration` `@teleop` `@failover`

**Given** the local console is the active operator (ownership strength 200)
**And** all arms are in `OPERATIONAL` mode
**When** the local console's AUTOMATIC liveliness expires on the `control`-tag participant
**Then** all arms in the procedure simultaneously enter safe-hold mode
**And** in-progress motion commands complete to a kinematic safe-stop (controlled deceleration to zero velocity)
**And** no new motion commands are executed until authority is confirmed

### Scenario: Robot enters safe-hold on OperatorInput deadline miss `@integration` `@teleop` `@failover`

**Given** the active operator is publishing `OperatorInput` at 500 Hz (2 ms interval)
**And** `OperatorInput` has DEADLINE QoS of 4 ms
**When** the active operator's control loop stalls (process alive but application hung)
**And** the 4 ms deadline is missed on the DataReader
**Then** all arms in the procedure enter safe-hold mode
**And** `REQUESTED_DEADLINE_MISSED` status is available on the reader

### Scenario: Robot enters safe-hold on explicit handoff command `@integration` `@teleop`

**Given** the local console is the active operator
**When** the operator issues an explicit handoff command (planned authority transfer)
**Then** all arms enter safe-hold mode during the transition
**And** the state machine transitions to `FAILOVER_PENDING` (or `RECLAIM_PENDING` for a reverse handoff)

### Scenario: Safe-hold maintains position with active servo `@integration` `@teleop`

**Given** all arms have entered safe-hold mode
**When** the robot is in safe-hold
**Then** each arm holds its current position with active servo (position-hold, not powered-off drift)
**And** safety interlocks remain active and monitored
**And** `RobotState` continues publishing at 100 Hz with `operational_mode = PAUSED`

### Scenario: Safe-hold does not publish SafetyInterlock `@integration` `@teleop`

**Given** arms are in safe-hold mode (not emergency safe-stop)
**When** the safe-hold is a recoverable transitional state (at least one operator source exists)
**Then** `SafetyInterlock` is NOT published with `interlock_active = true`
**And** safe-hold is distinct from emergency safe-stop

### Scenario: Safe-hold scope is per-procedure `@integration` `@teleop`

**Given** a procedure has 3 active arms
**When** the active operator loses liveliness
**Then** all 3 arms enter safe-hold simultaneously
**And** no arm continues accepting commands while others are in safe-hold
**And** split authority (some arms holding, others accepting commands) does not occur

### Scenario: Incoming OperatorInput is buffered during safe-hold `@integration` `@teleop`

**Given** arms are in safe-hold mode
**And** DDS ownership has resolved a new active writer (backup operator)
**When** the new active operator publishes `OperatorInput`
**Then** the new operator's samples are received by the DataReader (DDS delivers them)
**But** they are not acted upon by the robot control loop
**And** commands are held until authority is confirmed through the state machine

---

## Emergency Safe-Stop

### Scenario: Emergency safe-stop when all operators lose liveliness `@integration` `@teleop` `@failover`

**Given** the local console (strength 200) and the hospital console (effective strength 100) are both active writers
**When** both operators' liveliness expires (both processes crash or lose connectivity)
**Then** the state machine transitions to `NO_OPERATOR`
**And** all arms enter emergency safe-stop (faster deceleration profile than safe-hold)
**And** all axes are actively locked
**And** `SafetyInterlock` is published with `interlock_active = true` and `reason = "no active operator"`

### Scenario: Emergency safe-stop requires re-authentication to resume `@integration` `@teleop`

**Given** all arms are in emergency safe-stop (`NO_OPERATOR`)
**When** an operator's liveliness is restored (process restart, connectivity recovery)
**Then** the operator must explicitly re-authenticate and perform a system check
**And** the robot does not resume operation automatically
**And** only after re-authentication and explicit resume command do arms exit emergency safe-stop

---

## ControlAuthority State Machine

### Scenario: Initial state is LOCAL_ACTIVE with local console `@integration` `@teleop`

**Given** the teleoperation system starts with a local console as the only operator
**When** the local console's `OperatorInput` is the active owner via DDS exclusive ownership
**Then** the ControlAuthority state is `LOCAL_ACTIVE`

### Scenario: Transition to FAILOVER_PENDING on local operator loss `@integration` `@teleop` `@failover`

**Given** the ControlAuthority state is `LOCAL_ACTIVE`
**When** the local console's AUTOMATIC liveliness expires
**Then** the state transitions to `FAILOVER_PENDING`
**And** all arms enter safe-hold mode
**And** DDS ownership begins resolving the next active writer

### Scenario: Transition to REMOTE_ACTIVE after failover completes `@integration` `@teleop` `@failover`

**Given** the ControlAuthority state is `FAILOVER_PENDING`
**And** DDS ownership has resolved the hospital console (strength 100) as the active writer
**When** the hospital operator's `OperatorInput` is receiving within deadline
**And** the hospital operator issues an explicit "resume" acknowledgment
**And** the operator demonstrates awareness of current robot state (state synchronization check)
**Then** the state transitions to `REMOTE_ACTIVE`
**And** arms exit safe-hold and resume accepting commands from the hospital operator

### Scenario: Transition to NO_OPERATOR when all sources lost `@integration` `@teleop` `@failover`

**Given** the ControlAuthority state is `FAILOVER_PENDING`
**When** no live operator source exists (all writers' liveliness has expired)
**Then** the state transitions to `NO_OPERATOR`
**And** emergency safe-stop is engaged

### Scenario: Transition to RECLAIM_PENDING when higher-strength writer returns `@integration` `@teleop` `@failover`

**Given** the ControlAuthority state is `REMOTE_ACTIVE` (hospital console owns control)
**When** the local console's liveliness is restored (higher ownership strength writer returns)
**Then** DDS automatically switches the DataReader to the higher-strength writer
**And** the state transitions to `RECLAIM_PENDING`
**And** arms enter safe-hold during the synchronization period

### Scenario: Reclaim requires explicit acknowledgment `@integration` `@teleop`

**Given** the ControlAuthority state is `RECLAIM_PENDING`
**When** the returning local operator acknowledges the current robot state
**And** the operator's `OperatorInput` is receiving within deadline
**Then** the state transitions to `LOCAL_ACTIVE`
**And** arms exit safe-hold and resume accepting commands from the local operator

### Scenario: State machine does not override DDS ownership `@integration` `@teleop`

**Given** the ControlAuthority state machine tracks authority transitions
**When** DDS ownership resolves the active writer
**Then** the state machine observes (not overrides) the DDS ownership decision
**And** the state machine's role is to enforce safety rules (safe-hold, acknowledgment) that DDS does not cover
**And** the data-path arbitration is always DDS exclusive ownership

---

## Liveliness and Deadline Failover Detection

### Scenario: AUTOMATIC liveliness detects process crash `@integration` `@teleop` `@failover`

**Given** the local console has a dedicated `control`-tag DomainParticipant with AUTOMATIC liveliness (2 s lease)
**When** the local console process crashes
**Then** the `control`-tag participant disappears
**And** AUTOMATIC liveliness expires for all writers on that participant simultaneously
**And** the robot controller detects liveliness lost within 2 s

### Scenario: AUTOMATIC liveliness detects connectivity loss `@integration` `@teleop` `@failover`

**Given** the local console is publishing `OperatorInput` on the `control`-tag participant
**When** network connectivity between the console and the robot controller is lost
**Then** AUTOMATIC liveliness expires within 2 s (no heartbeat renewal reaches the reader)
**And** DDS ownership transfers to the next highest-strength writer (if available)

### Scenario: DEADLINE detects control-loop stall `@integration` `@teleop` `@failover`

**Given** the active operator's `OperatorInput` has DEADLINE QoS of 4 ms
**And** the operator's process is alive and middleware threads are running
**When** the application logic producing `OperatorInput` hangs (stall, deadlock)
**Then** the 4 ms DEADLINE is missed on the DataReader
**And** `REQUESTED_DEADLINE_MISSED` status triggers safe-hold entry
**And** this is detected even though AUTOMATIC liveliness remains asserted (middleware is alive)

### Scenario: DEADLINE on OperatorInput serves as canary for control-path health `@integration` `@teleop` `@failover`

**Given** the control path: operator publishes `OperatorInput` → robot processes it → robot publishes `RobotCommand`, `RobotState`
**When** `OperatorInput` DEADLINE is missed
**Then** the system knows the control path is broken at the source
**And** downstream write-on-change topics (`RobotCommand`, `SafetyInterlock`) may also be stalled
**And** the `OperatorInput` deadline miss is sufficient to trigger safe-hold without waiting for write-on-change topic health detection

### Scenario: Write-on-change topics rely on participant liveliness, not deadline `@unit` `@teleop`

**Given** `RobotCommand` and `SafetyInterlock` are write-on-change topics on the `control` tag
**When** there are long periods with no state transitions
**Then** no samples are published (this is normal, not a failure)
**And** writer health is detected via AUTOMATIC liveliness on the `control`-tag participant (2 s lease)
**And** DEADLINE QoS is NOT applied to these topics

---

## Routing Service Configuration

### Scenario: Control-tag domain route creates control-tag participants `@integration` `@teleop` `@routing`

**Given** the Routing Service configuration for the teleoperation control-tag bridge
**When** the domain route is created
**Then** the Procedure-side DomainParticipant is configured with the `control` domain tag
**And** the Hospital-side DomainParticipant is configured for the Hospital Integration databus
**And** both participants are in the correct partition for the procedure

### Scenario: Control-tag route bridges only OperatorInput `@integration` `@teleop` `@routing`

**Given** the Routing Service control-tag domain route
**When** topics are configured for bridging
**Then** only `OperatorInput` is routed from Hospital to Procedure `control` tag
**And** no other control-tag topics (`RobotCommand`, `RobotState`, `SafetyInterlock`) are bridged in this direction
**And** the reverse direction (Procedure `control` → Hospital) is not configured on this route

### Scenario: Observational bridge continues independently `@integration` `@teleop` `@routing`

**Given** the existing V1.0 observational bridge (Procedure → Hospital) is running
**And** the V2.1 control-tag bridge (Hospital → Procedure `control`) is running
**When** both routes are active
**Then** each route operates independently with its own participants, sessions, and topics
**And** a failure in one route does not affect the other

---

## Acceptance

### Scenario: Teleoperation failover end-to-end `@e2e` `@teleop` `@acceptance`

**Given** a local console, a hospital console, Routing Service (with control-tag bridge), 2 robot arms, and a digital twin are running in Docker Compose
**And** the local console (strength 200) is the active operator
**When** the local console process is killed
**Then** AUTOMATIC liveliness expires within 2 s
**And** all arms enter safe-hold (`RobotState.operational_mode = PAUSED`)
**And** DDS ownership transfers to the hospital console (effective strength 100)
**And** the ControlAuthority state transitions through `FAILOVER_PENDING`
**When** the hospital operator acknowledges the current robot state and issues a resume command
**Then** the state transitions to `REMOTE_ACTIVE`
**And** arms exit safe-hold and resume accepting the hospital operator's commands
**And** the digital twin reflects the authority change

### Scenario: Teleoperation reclaim end-to-end `@e2e` `@teleop` `@acceptance`

**Given** the hospital console is the active operator (`REMOTE_ACTIVE`)
**When** the local console process is restarted (higher strength writer returns)
**Then** DDS ownership automatically switches to the local console
**And** all arms enter safe-hold (`RECLAIM_PENDING`)
**When** the local operator acknowledges current robot state and issues a resume command
**Then** the state transitions to `LOCAL_ACTIVE`
**And** arms exit safe-hold and resume accepting the local operator's commands

### Scenario: Emergency safe-stop end-to-end `@e2e` `@teleop` `@acceptance`

**Given** a local console and a hospital console are the only operator sources
**When** both consoles are killed simultaneously
**Then** all operator liveliness expires within 2 s
**And** the ControlAuthority state transitions to `NO_OPERATOR`
**And** all arms enter emergency safe-stop (faster deceleration, axes locked)
**And** `SafetyInterlock(interlock_active = true, reason = "no active operator")` is published
**And** arms do not resume until an operator re-authenticates and explicitly resumes
