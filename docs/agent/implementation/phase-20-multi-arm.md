# Phase 20: Dynamic Multi-Arm Orchestration (V1.2)

**Goal:** Extend the procedure orchestration model to support dynamic
spawning, spatial assignment, and positioning of multiple robot arm
services around a surgical table, with full lifecycle visibility from
the Procedure Controller and digital twin display.

**Depends on:** Phases 1–5 (V1.0 complete)
**Blocks:** Nothing directly — V1.2 is a self-contained enhancement

**Spec file:** [spec/multi-arm-orchestration.md](../spec/multi-arm-orchestration.md)
**Vision references:**
- [vision/capabilities.md — V1.2.0](../vision/capabilities.md)
- [vision/data-model.md — `Surgery::RobotArmAssignment`](../vision/data-model.md)
- [vision/data-model.md — `ArmAssignmentState`, `TablePosition`, `MAX_ARM_COUNT`](../vision/data-model.md)
- [vision/system-architecture.md — Procedure Controller participant model](../vision/system-architecture.md)
- [vision/dds-consistency.md — New Module Checklist](../vision/dds-consistency.md)

---

## Step 20.1 — Multi-Arm IDL Types

### Work

- Add `ArmAssignmentState` enum to `interfaces/idl/surgery/surgery.idl`:
  - `UNKNOWN`, `IDLE`, `ASSIGNED`, `POSITIONING`, `OPERATIONAL`, `FAILED`
  - `@appendable` for forward compatibility
- Add `TablePosition` enum to `interfaces/idl/surgery/surgery.idl`:
  - `UNKNOWN`, `HEAD`, `FOOT`, `LEFT`, `RIGHT`, `LEFT_HEAD`, `RIGHT_HEAD`,
    `LEFT_FOOT`, `RIGHT_FOOT`
  - `@appendable` for forward compatibility
- Add `MAX_ARM_COUNT` constant (`long`, value 8) to the Surgery module
- Add `RobotArmAssignment` struct to `interfaces/idl/surgery/surgery.idl`:
  - `@appendable`
  - `robot_id` (`Common::EntityId`, `@key`)
  - `procedure_id` (`Common::EntityId`)
  - `table_position` (`TablePosition`)
  - `status` (`ArmAssignmentState`)
  - `capabilities` (`string<Common::MAX_DESCRIPTION_LENGTH>`)
- Register `Surgery::RobotArmAssignment` type in the type registration
  sections (both C++ and Python) per `data-model.md`
- Verify generated code compiles (C++) and imports (Python)

### Test Gate

- [ ] `cmake --build build` succeeds with new IDL types generated
- [ ] C++ can reference `Surgery::ArmAssignmentState`, `Surgery::TablePosition`,
      `Surgery::RobotArmAssignment`, and `Surgery::MAX_ARM_COUNT`
- [ ] Python can import and reference all new enum values and the struct
- [ ] `bash scripts/ci.sh --lint` passes

---

## Step 20.2 — QoS Profile and Topic Binding

### Work

- Add `TopicProfiles::RobotArmAssignment` to `interfaces/qos/Topics.xml`:
  - Inherits from `Patterns::State` (RELIABLE, TRANSIENT_LOCAL, KEEP_LAST 1,
    `Liveliness2s`)
  - No additional topic-specific tuning needed (write-on-change, standard
    liveliness)
- Add topic-filter binding in the `Topics` library of `Topics.xml`:
  - `<datawriter_qos topic_filter="RobotArmAssignment" base_name="TopicProfiles::RobotArmAssignment"/>`
  - `<datareader_qos topic_filter="RobotArmAssignment" base_name="TopicProfiles::RobotArmAssignment"/>`
- Run QoS compatibility checker (`tools/qos-checker.py`) to verify the
  new profile is compatible with existing `control`-tag patterns

### Test Gate

- [ ] `TopicProfiles::RobotArmAssignment` is present in installed QoS XML
- [ ] Topic-filter binding resolves correctly for readers and writers
- [ ] QoS compatibility checker passes with the new profile
- [ ] `bash scripts/ci.sh --lint` passes

---

## Step 20.3 — Participant Configuration for Procedure Controller

### Work

- Add a new participant profile `Participant::ProcedureController_ProcedureControl`
  to `interfaces/participants/Participants.xml`:
  - Domain: Procedure domain (Domain 10)
  - Domain tag: `control`
  - Contained entities: `RobotArmAssignment` DataReader
  - Same transport profile as other `control`-tag participants
- Add entity name constants for the new participant to
  `interfaces/idl/app_names/app_names.idl` per the naming convention in
  [dds-consistency.md §1 Step 2](../vision/dds-consistency.md)
- Update the Procedure Controller's startup sequence to create 3
  DomainParticipants:
  1. Orchestration domain (existing)
  2. Procedure domain `control` tag (new)
  3. Hospital domain (existing)
- Verify the new participant discovers `control`-tag publishers but not
  `clinical`/`operational`-tag publishers

### Test Gate

- [ ] Participant profile `ProcedureController_ProcedureControl` is present
      in installed `Participants.xml`
- [ ] Entity name constants are generated and accessible in both C++ and Python
- [ ] Procedure Controller creates 3 DomainParticipants (+1 Observability)
- [ ] `control`-tag subscriber discovers `control`-tag publishers only
- [ ] `bash scripts/ci.sh --lint` passes

---

## Step 20.4 — Robot Arm Service: Assignment Publishing

### Work

- Extend the robot arm service (C++ `RobotControllerService`) to publish
  `RobotArmAssignment` on the Procedure domain `control` tag:
  - Accept `table_position` as a configuration parameter (passed from
    Service Host via `start_service` RPC config)
  - On startup: publish `RobotArmAssignment(status = ASSIGNED, table_position = <configured>)`
  - On positioning start: publish `status = POSITIONING`
  - On positioning complete: publish `status = OPERATIONAL`
  - On error: publish `status = FAILED`
  - On shutdown: call `dispose()` on the `RobotArmAssignment` instance
- Implement a simple positioning simulation:
  - Configurable delay (e.g., 2–5 s) representing physical arm movement
  - Transitions: `ASSIGNED → POSITIONING → OPERATIONAL` with the delay
    applied during `POSITIONING`
- The arm service DataWriter uses `TopicProfiles::RobotArmAssignment`
  via topic-aware QoS resolution

### Test Gate

- [ ] Arm publishes `ASSIGNED` within 5 s of `ServiceStatus(RUNNING)`
- [ ] Arm transitions through `ASSIGNED → POSITIONING → OPERATIONAL`
- [ ] `dispose()` is called on shutdown; subscriber sees `NOT_ALIVE_DISPOSED`
- [ ] `FAILED` is published on simulated positioning error
- [ ] No samples published when arm is in steady state (write-on-change)
- [ ] `bash scripts/ci.sh` passes

---

## Step 20.5 — Procedure Controller: Assignment Subscription

### Work

- Add `RobotArmAssignment` subscription to the Procedure Controller
  using the new `control`-tag participant:
  - DataReader with `TopicProfiles::RobotArmAssignment`
  - Track instances by `robot_id` key
  - Maintain an internal table mapping `robot_id → (table_position, status)`
  - Update on each received sample
  - Detect `NOT_ALIVE_DISPOSED` and `NOT_ALIVE_NO_WRITERS` to remove arms
  - Detect liveliness lost (2 s) for unclean arm departures
- Implement the procedure start gate:
  - Track the set of requested arms (from `start_service` RPCs)
  - Procedure control enabled only when ALL requested arms are `OPERATIONAL`
  - Any arm in `FAILED` or disposed blocks the gate and generates a warning
- Implement `MAX_ARM_COUNT` enforcement:
  - Reject `start_service` requests that would exceed 8 active arms

### Test Gate

- [ ] Controller receives `RobotArmAssignment` samples from arm services
- [ ] Controller tracks arm lifecycle state per `robot_id`
- [ ] Procedure start gate: not enabled until all arms `OPERATIONAL`
- [ ] `NOT_ALIVE_DISPOSED` removes arm from table layout
- [ ] Liveliness lost within 2 s on unclean arm departure
- [ ] `MAX_ARM_COUNT` exceeded → request rejected, no RPC sent
- [ ] TRANSIENT_LOCAL: restarted controller receives current arm states
- [ ] `bash scripts/ci.sh` passes

---

## Step 20.6 — Digital Twin: Multi-Arm Rendering

### Work

- Extend the digital twin PySide6 display to subscribe to
  `RobotArmAssignment` (it already subscribes to `RobotState` on the
  `control` tag — same participant):
  - Render a schematic surgical table with arm positions
  - Color-code arms by `ArmAssignmentState`:
    - `OPERATIONAL` → green
    - `POSITIONING` → amber
    - `FAILED` → red
    - `IDLE` / `ASSIGNED` → grey
  - Clickable per-arm overlay showing `capabilities`, `table_position`,
    and current `ArmAssignmentState`
- Update rendering to show multiple arms simultaneously, each at its
  assigned `TablePosition` around the table
- Handle dynamic arm arrivals and departures (new instances,
  `NOT_ALIVE_DISPOSED`)
- Use existing `GuiState` pattern with `GuiSubsample` for downsampled
  delivery to the UI thread

### Test Gate

- [ ] Digital twin renders arms at their assigned table positions
- [ ] Color-coded lifecycle indicators match spec (green/amber/red/grey)
- [ ] Clickable overlay shows capabilities and state per arm
- [ ] New arm arrival automatically appears in the layout
- [ ] Arm departure (`dispose()`) removes the arm from the layout
- [ ] GUI remains responsive during concurrent multi-arm data arrival
- [ ] `bash scripts/ci.sh` passes

---

## Step 20.7 — Multi-Arm Orchestration Flow Integration

### Work

- Extend the `start_service` RPC flow to pass `table_position` as a
  `ServiceProperty` in the `ServiceRequest`:
  - Procedure Controller includes a `ServiceProperty` with
    `name="table_position"` in the `ServiceRequest.properties` sequence
    when issuing `start_service` to a Robot Service Host
  - Service Host factory receives the full `ServiceRequest` and extracts
    the `table_position` property to pass to the arm service constructor
- Author integration test for the full orchestration flow:
  1. Procedure Controller issues `start_service` RPCs for N arms at
     distinct table positions
  2. Service Hosts spawn arms → `ServiceStatus(RUNNING)` on Orchestration
  3. Arms publish `ASSIGNED → POSITIONING → OPERATIONAL` on Procedure `control`
  4. Procedure Controller's start gate activates when all arms reach
     `OPERATIONAL`
  5. One arm is stopped → `dispose()` → remaining arms unaffected
  6. Controller detects removed arm and updates table layout

### Test Gate

- [ ] `start_service` RPC includes `table_position` in config
- [ ] Orchestration-to-assignment latency ≤ 5 s
- [ ] Procedure start gate activates only when all arms `OPERATIONAL`
- [ ] Arm removal via `stop_service` → `dispose()` → remaining arms unaffected
- [ ] Multiple arms at distinct positions coexist correctly
- [ ] `bash scripts/ci.sh` passes

---

## Step 20.8 — Isolation and Regression Tests

### Work

- Author `@isolation` tests:
  - `RobotArmAssignment` on `control` tag is NOT discoverable by
    `clinical` or `operational` tag subscribers
  - Orchestration domain failure does not disrupt `RobotArmAssignment`
    data flow on the Procedure domain
- Author correlation tests:
  - `robot_id` correlates `RobotArmAssignment` with `RobotState` and
    `RobotCommand`
  - `procedure_id` in `RobotArmAssignment` correlates with
    `ProcedureContext.procedure_id`
- Run full V1.0 regression suite to confirm zero breakage:
  - All existing `@orchestration` scenarios pass
  - All standalone deployment scenarios pass
  - All `@partition`, `@isolation`, `@durability` scenarios pass
- Author `@multi-arm` scenario tests covering all GWT scenarios from
  [spec/multi-arm-orchestration.md](../spec/multi-arm-orchestration.md)

### Test Gate

- [ ] `control`-tag isolation: `clinical`/`operational` subscribers cannot
      discover `RobotArmAssignment`
- [ ] Orchestration crash → `RobotArmAssignment` flow unaffected
- [ ] `robot_id` correlation verified across topics
- [ ] All existing V1.0 tests pass (zero regressions)
- [ ] All `@multi-arm` spec scenario tests pass
- [ ] `bash scripts/ci.sh` passes

---

## Step 20.9 — Acceptance Test and Docker Integration

### Work

- Author the `@acceptance` `@multi-arm` end-to-end test:
  1. Docker Compose starts: Procedure Controller, 2 Robot Service Hosts,
     digital twin display
  2. Procedure Controller issues `start_service` RPCs for 2 arms at
     positions `LEFT` and `RIGHT`
  3. Both arms transition through `ASSIGNED → POSITIONING → OPERATIONAL`
  4. Procedure Controller shows both arms with green status
  5. `stop_service` for one arm → `dispose()` → remaining arm unaffected
  6. Test fails if any component is absent or non-functional
- Update `docker-compose.yml` if needed for multi-arm deployment targets
- Verify the full orchestrated + multi-arm scenario runs end-to-end

### Test Gate

- [ ] `@acceptance` `@multi-arm` test passes in Docker Compose
- [ ] All multi-arm components start and communicate correctly
- [ ] Remaining-arm resilience: one arm removed, other continues
- [ ] `bash scripts/ci.sh` passes

---

## Step 20.10 — Documentation and Performance Baseline

### Work

- Update module READMEs to document multi-arm capabilities:
  - Robot arm service: new `table_position` configuration parameter,
    `RobotArmAssignment` lifecycle, `dispose()` on shutdown
  - Procedure Controller: 3-participant model, assignment subscription,
    procedure start gate, `MAX_ARM_COUNT` enforcement
  - Digital twin: multi-arm rendering, color-coded status indicators
  - DDS Entities tables updated with `RobotArmAssignment` writer/reader
- Update project root `README.md` if needed for V1.2 capabilities
- Run the performance benchmark harness and record the Phase 20 baseline:
  - `tests/performance/baselines/phase-20.json`
- Verify all quality gates pass

### Test Gate

- [ ] All module READMEs pass `markdownlint` and section-order lint
- [ ] `tests/performance/baselines/phase-20.json` committed
- [ ] No performance regression against Phase 5 baseline
- [ ] `bash scripts/ci.sh` passes — all quality gates green

---

## V1.2.0 Release Gate

After Phase 20 is complete, a **final regression gate** must pass before
the V1.2.0 version is cut:

- [ ] Full test suite passes (`bash scripts/ci.sh`) — zero failures,
      zero skips, zero expected-failures
- [ ] All `@multi-arm` spec scenarios pass
- [ ] All V1.0 spec scenarios pass simultaneously (zero regressions)
- [ ] All `@orchestration` spec scenarios pass (including multi-arm
      extensions)
- [ ] Full Docker Compose environment runs with multi-arm deployment:
      2+ arms at distinct table positions, Procedure Controller on 3
      domains, digital twin rendering multiple arms
- [ ] `MAX_ARM_COUNT` enforcement tested
- [ ] `dispose()` and liveliness-based arm health detection verified
- [ ] Procedure start gate blocks until all arms `OPERATIONAL`
- [ ] No open incidents in `docs/agent/incidents.md`
- [ ] All module READMEs pass lint
- [ ] Performance benchmark passes against Phase 20 baseline
- [ ] `tests/performance/baselines/v1.2.0.json` committed
