# Phase 21: Teleoperation / Remote Operator (V2.1)

**Goal:** Extend operator control to hospital and cloud levels with
automatic failover, enabling remote surgical assistance and supervision
with DDS-enforced control authority arbitration via exclusive ownership,
Routing Service strength tiering, safe-hold mode, and the
ControlAuthority supervisory state machine.

**Depends on:** Phases 1–5 (V1.0 complete), Phase 7 (Security — V2.0)
**Blocks:** Nothing directly — V2.1 is a self-contained enhancement

**Prerequisite:** V2.0 Security (Phase 7) must be complete. All
teleoperation data paths require Connext Security Plugins for
authentication and topic-level access control.

**Spec file:** [spec/teleoperation.md](../spec/teleoperation.md)
**Vision references:**
- [vision/capabilities.md — V2.1.0](../vision/capabilities.md)
- [vision/data-model.md — V2.1 Forward Design Notes](../vision/data-model.md)
- [vision/system-architecture.md — Teleoperation Routing Service](../vision/system-architecture.md)
- [vision/system-architecture.md — Safe-Hold Mode](../vision/system-architecture.md)
- [vision/dds-consistency.md — New Module Checklist](../vision/dds-consistency.md)

---

## Step 21.1 — Hospital Domain Tag Re-Evaluation

### Work

- Resolve the escalation trigger documented in
  [system-architecture.md — Hospital Domain Tag Re-Evaluation](../vision/system-architecture.md):
  the reverse data path (Hospital → Procedure) makes Hospital-domain
  participants **actors** rather than observers
- Evaluate whether the Hospital domain needs a `control` tag for the
  remote operator's outbound `OperatorInput` data path:
  - Option A: Add a `control` domain tag to the Hospital domain — remote
    operator console publishes on Hospital `control`, RS bridges to
    Procedure `control`
  - Option B: No tag on Hospital domain — remote operator console
    publishes on the flat Hospital domain, RS bridges to Procedure
    `control` using a separate `domain_route` with a `control`-tagged
    Procedure-side participant
- Document the decision in `vision/system-architecture.md` (requires
  operator approval)
- Update domain definitions in `Domains.xml` if a new tag is added
- Consult `rti-chatbot-mcp` for domain tag + Routing Service interaction
  patterns

### Test Gate

- [ ] Decision documented and approved in `system-architecture.md`
- [ ] `Domains.xml` updated if Hospital domain tag added
- [ ] `bash scripts/ci.sh --lint` passes

---

## Step 21.2 — Exclusive Ownership QoS for OperatorInput

### Work

- Add `ExclusiveOwnership` snippet composition to
  `TopicProfiles::OperatorInput` in `interfaces/qos/Topics.xml`:
  - Composes existing `Snippets::ExclusiveOwnership` into the
    `OperatorInput` profile
  - Writer QoS includes ownership strength (200 for local console)
- Evaluate `OperatorInput` key structure:
  - V1.x keys: `operator_id`, `robot_id`
  - V2.1 requirement: ownership resolved per `robot_id` instance
    (procedure-wide, not per-operator)
  - If `operator_id` must be removed from key fields, this is an IDL
    breaking change — add migration steps and coordinate with
    V2.0 security permissions (which may reference key fields)
- Add ownership strength configuration to `Snippets.xml`:
  - `OwnershipStrength200` — local console default
  - Strength values for RS output writers are configured in the RS XML,
    not in application QoS
- Verify DDS ownership arbitration works with the modified key structure
- Consult `rti-chatbot-mcp` for exclusive ownership + key field
  interaction behavior

### Test Gate

- [ ] `TopicProfiles::OperatorInput` includes `ExclusiveOwnership`
- [ ] Local console DataWriter has ownership strength 200
- [ ] Two writers with different strengths: higher-strength writer's
      samples are delivered, lower-strength suppressed
- [ ] Key structure evaluation documented (breaking change if applicable)
- [ ] QoS compatibility checker passes
- [ ] `bash scripts/ci.sh` passes

---

## Step 21.3 — ControlAuthority State Machine

### Work

- Add `ControlAuthority` IDL type to `interfaces/idl/surgery/surgery.idl`:
  - `ControlAuthorityState` enum: `LOCAL_ACTIVE`, `REMOTE_ACTIVE`,
    `FAILOVER_PENDING`, `RECLAIM_PENDING`, `NO_OPERATOR`
  - `@appendable` for forward compatibility
- Implement the `ControlAuthorityManager` in the robot controller
  service (C++):
  - Tracks the current authority state
  - Observes DDS ownership changes on the `OperatorInput` DataReader
    (via `on_liveliness_changed` and ownership status)
  - Transitions between states per the state machine in
    [data-model.md — ControlAuthority State Machine](../vision/data-model.md):
    - `LOCAL_ACTIVE` → `FAILOVER_PENDING` (local liveliness lost)
    - `FAILOVER_PENDING` → `REMOTE_ACTIVE` (backup acknowledged)
    - `FAILOVER_PENDING` → `NO_OPERATOR` (all sources lost)
    - `REMOTE_ACTIVE` → `RECLAIM_PENDING` (local returns)
    - `RECLAIM_PENDING` → `LOCAL_ACTIVE` (local acknowledged)
  - Publishes authority state for monitoring (optional topic or via
    existing `RobotState` operational_mode)
- Write unit tests for all state transitions

### Test Gate

- [ ] `ControlAuthorityState` enum generated in C++ and Python
- [ ] State machine transitions through all 5 states correctly
- [ ] `LOCAL_ACTIVE` → `FAILOVER_PENDING` on liveliness loss
- [ ] `FAILOVER_PENDING` → `NO_OPERATOR` when all sources lost
- [ ] `RECLAIM_PENDING` → `LOCAL_ACTIVE` on acknowledgment
- [ ] State machine observes (does not override) DDS ownership decisions
- [ ] `bash scripts/ci.sh` passes

---

## Step 21.4 — Safe-Hold Mode Implementation

### Work

- Implement safe-hold behavior in the robot controller:
  - **Entry:** triggered by `ControlAuthorityManager` on `FAILOVER_PENDING`
    or `RECLAIM_PENDING`
  - **Deceleration:** in-progress motion commands complete to kinematic
    safe-stop (controlled deceleration to zero velocity, not snap-stop)
  - **Position hold:** active servo hold at current position
  - **No new commands:** incoming `OperatorInput` samples received but
    not acted upon until authority confirmed
  - **Safety interlocks remain active** and monitored during safe-hold
  - **`RobotState`:** continues publishing at 100 Hz with
    `operational_mode = PAUSED`
- Implement safe-hold exit:
  - Live operator source detected (DDS ownership resolved)
  - `OperatorInput` receiving within deadline (4 ms)
  - Explicit "resume" acknowledgment from operator
  - State synchronization check (operator demonstrates awareness of
    current robot state)
- Ensure safe-hold scope is **per-procedure**: all arms enter safe-hold
  simultaneously when authority is uncertain

### Test Gate

- [ ] Robot enters safe-hold on `FAILOVER_PENDING` transition
- [ ] Controlled deceleration to zero velocity (not snap-stop)
- [ ] Position hold with active servo (position maintained)
- [ ] `RobotState` publishes at 100 Hz with `PAUSED` mode
- [ ] `SafetyInterlock` NOT published during safe-hold (not emergency stop)
- [ ] Incoming `OperatorInput` received but not acted upon
- [ ] All arms enter safe-hold simultaneously (per-procedure scope)
- [ ] `bash scripts/ci.sh` passes

---

## Step 21.5 — Emergency Safe-Stop

### Work

- Implement emergency safe-stop for the `NO_OPERATOR` state:
  - Faster deceleration profile than safe-hold
  - All axes actively locked
  - Publish `SafetyInterlock(interlock_active = true,
    reason = "no active operator")`
  - Robot does not resume until operator re-authenticates and explicitly
    resumes (application-level gate, not automatic DDS resume)
- Implement re-authentication and resume flow:
  - Returning operator's liveliness detected
  - Operator must pass re-authentication (leverages V2.0 Security
    infrastructure)
  - Explicit system check and resume command required
  - Only then does robot exit emergency safe-stop

### Test Gate

- [ ] `NO_OPERATOR` → emergency safe-stop with faster deceleration
- [ ] All axes locked after deceleration
- [ ] `SafetyInterlock(interlock_active = true, reason = "no active operator")`
      published
- [ ] Robot does NOT auto-resume when operator liveliness returns
- [ ] Explicit re-authentication + resume required to exit
- [ ] `bash scripts/ci.sh` passes

---

## Step 21.6 — Routing Service Control-Tag Bridge

### Work

- Author Routing Service configuration for the reverse teleoperation
  data path (Hospital → Procedure `control`):
  - **Separate `domain_route`** from the existing observational bridge
  - Procedure-side DomainParticipant: `control` domain tag
  - Hospital-side DomainParticipant: Hospital domain (tag per Step 21.1
    decision)
  - Route only `OperatorInput` topic
  - Output DataWriter QoS: `ExclusiveOwnership` with strength **100**
    (hospital tier)
- Author WAN Routing Service configuration for the cloud tier
  (Cloud → Procedure `control`):
  - Same architecture as hospital route but via WAN transport
  - Output DataWriter QoS: `ExclusiveOwnership` with strength **50**
    (cloud tier)
- Verify route isolation: observational bridge fault does not affect
  control-tag bridge (and vice versa)
- Add Routing Service configuration to the Docker Compose deployment

### Test Gate

- [ ] Hospital → Procedure `control` route bridges `OperatorInput`
- [ ] RS output writer has ownership strength 100 (hospital tier)
- [ ] Cloud → Procedure `control` route bridges `OperatorInput`
      with strength 50 (cloud tier)
- [ ] Observational bridge continues independently
- [ ] Fault in observational bridge → control-tag bridge unaffected
- [ ] Fault in control-tag bridge → observational bridge unaffected
- [ ] Only `OperatorInput` is routed (no `RobotCommand`, `RobotState`,
      `SafetyInterlock`)
- [ ] `bash scripts/ci.sh` passes

---

## Step 21.7 — Failover Integration Testing

### Work

- Author integration tests covering the full failover scenarios:
  1. **Local → Hospital failover:** local console killed → liveliness
     expires (≤ 2 s) → arms enter safe-hold → DDS ownership transfers
     to hospital console (strength 100) → hospital operator acknowledges
     → arms resume
  2. **Hospital → Local reclaim:** local console restarts → DDS ownership
     switches to higher-strength writer → arms enter safe-hold → local
     operator acknowledges → arms resume as `LOCAL_ACTIVE`
  3. **Total loss (emergency safe-stop):** all consoles killed →
     `NO_OPERATOR` → emergency safe-stop → `SafetyInterlock` published
     → operator returns and re-authenticates → explicit resume
  4. **Deadline-triggered safe-hold:** operator process alive but
     control loop stalled → 4 ms deadline missed → safe-hold entry
     (even though liveliness remains asserted)
- Verify AUTOMATIC liveliness detects process crash within 2 s
- Verify DEADLINE detects control-loop stall independently of liveliness
- Verify write-on-change topics (`RobotCommand`, `SafetyInterlock`) do
  NOT use deadline — only liveliness

### Test Gate

- [ ] Local → Hospital failover completes end-to-end
- [ ] Hospital → Local reclaim completes with acknowledgment
- [ ] Emergency safe-stop on total operator loss
- [ ] DEADLINE miss triggers safe-hold independently of liveliness
- [ ] AUTOMATIC liveliness expires within 2 s on process crash
- [ ] Write-on-change topics use liveliness only (no deadline)
- [ ] All `@teleop` `@failover` spec scenarios pass
- [ ] `bash scripts/ci.sh` passes

---

## Step 21.8 — Acceptance Tests and Docker Integration

### Work

- Author `@acceptance` `@teleop` end-to-end tests:
  1. **Failover acceptance:** local console, hospital console, Routing
     Service (control-tag bridge), 2 robot arms, digital twin in Docker
     Compose → local killed → safe-hold → hospital takes over → resume
  2. **Reclaim acceptance:** hospital active → local restarts →
     safe-hold → local reclaims → resume
  3. **Emergency safe-stop acceptance:** both consoles killed →
     `NO_OPERATOR` → emergency safe-stop → operator returns →
     re-authentication → explicit resume
- Update `docker-compose.yml` with:
  - Hospital-level operator console service
  - Routing Service control-tag bridge service
  - (Optionally) cloud-level console + WAN RS for cloud tier testing
- Verify all 3 acceptance scenarios pass in Docker Compose

### Test Gate

- [ ] `@acceptance` failover test passes in Docker Compose
- [ ] `@acceptance` reclaim test passes in Docker Compose
- [ ] `@acceptance` emergency safe-stop test passes in Docker Compose
- [ ] All teleoperation components start and communicate correctly
- [ ] `bash scripts/ci.sh` passes

---

## Step 21.9 — Isolation and Regression Suite

### Work

- Author isolation tests:
  - Control-tag RS bridge creates `control`-tag participants (not
    `clinical`/`operational`)
  - RS control-tag route does not carry topics other than `OperatorInput`
  - Observational bridge and control-tag bridge are fault-isolated
- Author ownership arbitration tests:
  - Console uses identical config at all deployment locations
  - Ownership strength varies only at the RS output writer
  - Per-arm override does NOT occur (procedure-wide ownership)
- Run full V1.0 + V1.2 regression suite to confirm zero breakage:
  - All `@orchestration`, `@multi-arm`, `@partition`, `@isolation`,
    `@durability` scenarios pass
  - All standalone deployment scenarios pass
- Author `@teleop` scenario tests covering all GWT scenarios from
  [spec/teleoperation.md](../spec/teleoperation.md) that are not already
  covered by integration/acceptance tests in prior steps

### Test Gate

- [ ] Control-tag RS bridge uses correct domain tags
- [ ] Only `OperatorInput` routed on control-tag bridge
- [ ] Observational and control-tag bridges fault-isolated
- [ ] Console config identical at all deployment locations
- [ ] Procedure-wide ownership (no per-arm override)
- [ ] All V1.0 and V1.2 tests pass (zero regressions)
- [ ] All `@teleop` spec scenario tests pass
- [ ] `bash scripts/ci.sh` passes

---

## Step 21.10 — Documentation and Performance Baseline

### Work

- Update module READMEs for teleoperation capabilities:
  - Robot controller: safe-hold mode, ControlAuthority state machine,
    exclusive ownership behavior, emergency safe-stop
  - Operator console: static ownership strength, deployment-agnostic
    configuration
  - Routing Service: control-tag bridge architecture, ownership strength
    tiering table, fault isolation from observational bridge
  - DDS Entities tables updated with exclusive ownership, liveliness,
    and deadline annotations
- Update project root `README.md` for V2.1 capabilities
- Run the performance benchmark harness and record the Phase 21 baseline:
  - `tests/performance/baselines/phase-21.json`
  - Key metric: failover latency (time from liveliness expiration to
    backup operator's first sample delivered)
- Verify all quality gates pass

### Test Gate

- [ ] All module READMEs pass `markdownlint` and section-order lint
- [ ] `tests/performance/baselines/phase-21.json` committed
- [ ] No performance regression against Phase 20 / V2.0 baseline
- [ ] `bash scripts/ci.sh` passes — all quality gates green

---

## V2.1.0 Release Gate

After Phase 21 is complete, a **final regression gate** must pass before
the V2.1.0 version is cut:

- [ ] Full test suite passes (`bash scripts/ci.sh`) — zero failures,
      zero skips, zero expected-failures
- [ ] All `@teleop` spec scenarios pass
- [ ] All V1.0, V1.2, and V2.0 spec scenarios pass (zero regressions)
- [ ] All `@orchestration` and `@multi-arm` scenarios pass
- [ ] Full Docker Compose environment runs with teleoperation:
      local console + hospital console + RS control-tag bridge + 2 arms
- [ ] Failover: local killed → hospital takes over within 2 s
- [ ] Reclaim: local returns → acknowledgment → local resumes
- [ ] Emergency safe-stop: all consoles lost → interlock published →
      re-authentication required
- [ ] Safe-hold: per-procedure scope, controlled deceleration, position
      hold, `RobotState(PAUSED)` at 100 Hz
- [ ] Routing Service: control-tag bridge isolated from observational
      bridge, ownership strength 100 (hospital) / 50 (cloud)
- [ ] No open incidents in `docs/agent/incidents.md`
- [ ] All module READMEs pass lint
- [ ] Performance benchmark passes against Phase 21 baseline
- [ ] `tests/performance/baselines/v2.1.0.json` committed
