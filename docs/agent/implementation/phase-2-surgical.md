# Phase 2: Surgical Procedure Module

**Goal:** Implement the surgical procedure module — a multi-instance application set that simulates a robot controller, patient monitor, surgical camera, procedure context publisher, and device telemetry. Verify partition-based room isolation and all surgical spec scenarios.

**Depends on:** Phase 1 (Foundation)
**Blocks:** Phase 3 (Dashboard), Phase 4 (Clinical Decision Support)
**Spec coverage:** [surgical-procedure.md](../spec/surgical-procedure.md) (Robot Teleop, Patient Vitals, Camera Feed, Device Telemetry, Procedure Context, Digital Twin Display, Multi-Instance Isolation), [common-behaviors.md](../spec/common-behaviors.md) (Partition Isolation)

---

## Step 2.1 — Procedure Context & Status Publisher ✅ `84c7b22`

### Work

- Implement `ProcedureContext` publisher (Python or C++)
- Reads room, patient, procedure, surgeon info from configuration (file or environment)
- Publishes on the Procedure domain (`operational` tag) with `State` pattern QoS and TRANSIENT_LOCAL durability
- Partition assigned from `PARTITION` environment variable at startup
- Implement `ProcedureStatus` publisher alongside `ProcedureContext`
- Publishes running status (in-progress, completing, alert) on the Procedure domain (`operational` tag) with `State` pattern QoS and TRANSIENT_LOCAL durability
- Status is updated as the procedure progresses through its lifecycle

### Test Gate (spec: surgical-procedure.md — Procedure Context)

- [x] Procedure context is published at startup with all required fields
- [x] Late-joining subscriber receives procedure context immediately
- [x] Procedure context update reflects changes
- [x] ProcedureStatus is published with running status and is durable for late joiners

---

## Step 2.2 — Robot Simulator (Procedure Domain, `control` Tag) ✅ `3627039`

### Work

- Implement robot state publisher (C++) on the Procedure domain (`control` tag)
  - Publishes `RobotState` at configured rate with `State` pattern QoS
  - Supports modes: OPERATIONAL, PAUSED, EMERGENCY_STOP, IDLE
- Implement operator input publisher (C++ or Python) on the Procedure domain (`control` tag)
  - Publishes `OperatorInput` at high rate with `Stream` pattern QoS
  - Simulates joystick/haptic input
- Implement robot command publisher on the Procedure domain (`control` tag)
  - Publishes `RobotCommand` with `Command` pattern QoS
- Implement safety interlock publisher on the Procedure domain (`control` tag)
  - Publishes `SafetyInterlock` with `State` pattern QoS
- Robot controller subscriber receives `OperatorInput` and `RobotCommand`, responds to `SafetyInterlock`
- **Robot controller threading pattern: dual `AsyncWaitSet` (pub/sub separation)**
  - Critical-path I/O contexts with tight jitter budgets must not share a dispatch thread with lower-priority processing. The 100 Hz `RobotState` publisher and the subscription readers are therefore separated into two independent `AsyncWaitSet` instances, each with **thread pool size = 1**.
  - **Publisher `AsyncWaitSet`** (dedicated to 100 Hz output):
    - Attach a single `GuardCondition` (`publish_tick`) — a dedicated timer thread sleeps until the next 10 ms boundary and calls `publish_tick.trigger_value(true)`
    - In the `publish_tick` handler: reset the guard condition, acquire read-lock on shared controller state, snapshot, write `RobotState`
    - No `ReadCondition`s — this thread does nothing except publish on schedule, ensuring reader data-available processing cannot introduce jitter into the 100 Hz output
  - **Subscriber `AsyncWaitSet`** (all input readers):
    - Attach a `ReadCondition` for each of the three DataReaders: `SafetyInterlock`, `RobotCommand`, `OperatorInput`
    - Single-threaded dispatch means readers do not race each other on shared controller state
    - In the `SafetyInterlock` handler: `take()` all samples, update controller mode (→ `EMERGENCY_STOP` on violation)
    - In the `OperatorInput` handler: `take()` samples, discard if interlock is active, otherwise update commanded state
    - In the `RobotCommand` handler: `take()` samples, apply mode/command changes
  - **Shared state synchronization:** A lightweight mutex (or read-write lock) protects the shared controller state between the publisher and subscriber threads. The subscriber holds a write-lock only during short state updates; the publisher holds a read-lock only during snapshot. Contention is minimal because both sides are single-threaded with short critical sections.
  - Do **not** use `rti::sub::SampleProcessor` — it dispatches per-sample callbacks independently per reader, which does not support the coordinated shared-state model this controller requires (it is also experimental in Connext 7.6.0)
  - Do **not** use `DataReaderListener` — see `vision/coding-standards.md` for rationale

### Test Gate (spec: surgical-procedure.md — Robot Teleop & Control)

- [x] Operator input reaches robot controller within deadline
- [x] Robot state is published at configured rate with correct fields
- [x] Safety interlock halts robot on violation (state → EMERGENCY_STOP)
- [x] Stale operator input (expired lifespan) is not applied
- [x] Robot command delivery is strictly reliable and ordered
- [x] RobotState publishes at 100 Hz ± tolerance regardless of input arrival rate

---

## Step 2.3 — Patient Vitals & Alarm Simulator

### Work

- Implement bedside monitor simulator (Python) on the Procedure domain (`clinical` tag)
  - Publishes `PatientVitals` at configured rate with `State` pattern QoS (periodic-snapshot publication model — see `vision/data-model.md`)
  - Implements the simulation model per `vision/simulation-model.md`:
    - Signal model with current value, target value, convergence rate, and noise parameters
    - Cross-signal correlation (SBP drop → HR compensation within 1–3 s; temperature rise → HR increase)
    - Scenario profile engine supporting `MEDTECH_SIM_PROFILE` environment variable
    - Seeded PRNG via `MEDTECH_SIM_SEED` (default: system entropy for non-deterministic runs)
    - Temporal realism: values trend toward targets over multiple cycles, no discontinuities without cause
  - Publishes `WaveformData` (ECG, pleth, etc.) at configured frequency with `Stream` pattern QoS (continuous-stream publication model)
- Implement alarm evaluation logic
  - Monitors vitals against configurable thresholds
  - Publishes `AlarmMessages` using write-on-change publication model — samples published only on alarm state transitions (raised, severity changed, cleared), not periodically

### Test Gate (spec: surgical-procedure.md — Patient Vitals)

- [ ] Vitals snapshot published periodically with all required measurements
- [ ] Waveform data streams at configured frequency with correct block size
- [ ] Alarm raised when vital exceeds threshold
- [ ] Alarm clears when vital returns to normal
- [ ] Late-joining subscriber receives current vitals (TRANSIENT_LOCAL)
- [ ] Simulator produces non-deterministic output by default (two runs differ)
- [ ] Simulator produces deterministic output with fixed seed (`MEDTECH_SIM_SEED=42`)
- [ ] Vitals trend smoothly — no discontinuities exceeding 3× noise amplitude
- [ ] Cross-signal correlation: SBP drop triggers HR compensation within 1–3 s
- [ ] Scenario profile `hemorrhage_onset` produces coordinated multi-signal deterioration
- [ ] `AlarmMessages` publishes only on state transitions (write-on-change model)

---

## Step 2.4 — Camera Simulator

### Work

- Implement camera simulator (Python) on the Procedure domain (`operational` tag)
  - Publishes `CameraFrame` at configured frame rate with `Stream` pattern QoS
  - Simulates frame metadata (ID, sequence, timestamp, resolution) and synthetic image reference

### Test Gate (spec: surgical-procedure.md — Camera Feed)

- [ ] Camera frame metadata published at configured rate
- [ ] Best-effort delivery: subscriber continues on frame loss without stalling

---

## Step 2.5 — Device Telemetry Simulator

### Work

- Implement device telemetry simulators (Python) on the Procedure domain (`clinical` tag)
  - Infusion pump status, anesthesia machine status
  - Publishes `DeviceTelemetry` with `State` pattern QoS using **write-on-change publication model** — samples published only when device parameters change, faults occur, or mode transitions happen (see `vision/data-model.md` Publication Model)
  - Supports exclusive ownership for primary/backup pattern
  - Implements simulation model per `vision/simulation-model.md` for device state variation

### Test Gate (spec: surgical-procedure.md — Device Telemetry)

- [ ] Device telemetry published for each simulated device
- [ ] Device telemetry uses write-on-change model — stable state produces no samples
- [ ] Exclusive ownership failover: backup takes over when primary liveliness expires

---

## Step 2.6 — Digital Twin Display

### Work

- Create PySide6 application in `modules/surgical-procedure/digital-twin/`
- Load shared GUI theme: apply `resources/styles/medtech.qss`, register bundled fonts, display RTI logo in header bar (see `vision/technology.md` GUI Design Standard)
- Create DomainParticipant on the Procedure domain (`control` tag) with partition from `PARTITION` environment variable
- Subscribe to `RobotState`, `RobotCommand`, `SafetyInterlock`, and `OperatorInput`
  - QoS loaded automatically via the default QosProvider (`NDDS_QOS_PROFILES`)
  - Apply time-based filter (~16 ms minimum separation for 60 Hz rendering) on **high-rate streaming readers only**: `RobotState` and `OperatorInput`
  - Do **not** apply time-based filter to `SafetyInterlock` (safety-critical state — every sample matters) or `RobotCommand` (Command pattern, RELIABLE KEEP_LAST 1 — each command must be processed)
- Implement 2D robot visualization widget:
  - Schematic arm with joint angles from `RobotState`
  - Tool-tip position indicator
  - Active command annotation from `RobotCommand`
  - Operational mode label (OPERATIONAL, PAUSED, EMERGENCY_STOP, IDLE)
  - Safety interlock overlay (red, prominent) from `SafetyInterlock`
  - Disconnected state (grayed out) on liveliness lost
- Use QtAsyncio for DDS data reception — never block the main/UI thread
- Add Docker container to `docker-compose.yml` on `surgical-net`

### Test Gate (spec: surgical-procedure.md — Digital Twin Display)

- [ ] Digital twin renders current robot state (joint positions, mode)
- [ ] Active command displayed as visual annotation
- [ ] Safety interlock prominently rendered when active
- [ ] Time-based filter limits updates to rendering frame rate on `RobotState` and `OperatorInput` readers
- [ ] `SafetyInterlock` and `RobotCommand` readers have no time-based filter (every sample delivered)
- [ ] Late-joining display receives current state via TRANSIENT_LOCAL
- [ ] Robot disconnect detected via liveliness (grayed out)
- [ ] DDS reads do not block the Qt main thread

---

## Step 2.7 — Module README & Documentation Compliance

### Work

- Author `modules/surgical-procedure/README.md` following all seven required sections per [vision/documentation.md](../vision/documentation.md): Title, Overview, Quick Start, Architecture, Configuration Reference, Testing, Going Further
- Author `modules/surgical-procedure/digital-twin/README.md` (same structure) for the digital twin sub-module
- Verify both READMEs pass `markdownlint` with zero errors/warnings using the project `.markdownlint.json`
- Verify both pass the section-order lint script (`tests/lint/check_readme_sections.py`)

### Test Gate (spec: documentation.md)

- [ ] `markdownlint modules/surgical-procedure/README.md` — zero errors, zero warnings
- [ ] `python tests/lint/check_readme_sections.py` — all required sections present and in order
- [ ] Architecture section documents all DDS entities (participants, writers, readers, topics, QoS profiles, domain tags)
- [ ] Architecture section documents the threading model
- [ ] Architecture section documents the publication model (continuous-stream, periodic-snapshot, write-on-change) for each topic
- [ ] Documentation handoff verification: module README is self-sufficient without consulting `docs/agent/`

---

## Step 2.8 — Multi-Instance Integration Test

### Work

- Launch two complete surgical procedure instances with different partitions (OR-1, OR-3)
- Verify partition isolation end-to-end: data from OR-1 does not appear in OR-3 and vice versa
- Verify all topics are publishing correctly in both instances
- Run in Docker Compose with `surgical-net`

### Test Gate

- [ ] Two concurrent instances run without interference
- [ ] Cross-partition isolation: subscriber in OR-1 receives zero samples from OR-3
- [ ] All surgical spec scenarios pass under multi-instance conditions
- [ ] Docker Compose launches and runs both instances successfully

---

## Step 2.9 — Observability Verification

### Work

- Run Docker Compose with `--profile observability` alongside 2+ surgical instances
- Verify Monitoring Library 2.0 telemetry flows from surgical participants to Collector Service
- Verify Collector Service forwards metrics to Prometheus and logs to Grafana Loki
- Run the `@observability` scenarios from [common-behaviors.md](../spec/common-behaviors.md)
- Verify the observability stack can be removed (`docker compose up` without `--profile observability`) and all functional tests still pass

### Test Gate (spec: common-behaviors.md — Observability)

- [ ] Collector Service receives telemetry from surgical participants
- [ ] Prometheus shows per-participant metrics within 30 s
- [ ] Deadline-missed event is visible in Prometheus after induced deadline violation
- [ ] Grafana dashboard displays system health overview with participant metrics and logs
- [ ] All functional spec scenarios pass with observability profile disabled

---

## Step 2.10 — Performance Baseline Recording

### Work

- Run the performance benchmark harness with the full Phase 2 Docker Compose environment (2 surgical instances + observability stack): `python tests/performance/benchmark.py --record --phase phase-2`
- This is the **first meaningful baseline** — Phase 1 has no real publishers, so Phase 2 establishes the initial performance reference point
- Review the benchmark output: all metrics should report status NEW (no prior baseline)
- Commit `tests/performance/baselines/phase-2.json` alongside the Phase 2 completion commit
- Note: only Tier 1 latency (Procedure domain internal) and Tier 2 throughput metrics are meaningful at this phase. Routing Service metrics (L5) and Hospital domain metrics will be populated in Phase 3.

### Test Gate (spec: performance-baseline.md — Baseline Recording, Phase Gate Integration)

- [ ] Benchmark harness runs successfully against the Phase 2 Docker Compose environment
- [ ] All collected metrics have valid numeric values (no NaN, no query errors)
- [ ] Baseline file `tests/performance/baselines/phase-2.json` is produced and well-formed
- [ ] Baseline is committed to version control

---

## Step 2.11 — Diagnostic Tools Implementation

### Work

- Implement `tools/medtech-diag/diag.py` per [vision/tooling.md](../vision/tooling.md):
  - Joins each domain (Procedure, Hospital, Observability) as a temporary read-only participant
  - Inspects discovered entities via built-in discovery topics (`DCPSParticipant`, `DCPSPublication`, `DCPSSubscription`)
  - Performs all checks: participant discovery, endpoint matching, partition topology, liveliness status, application logging health, Cloud Discovery Service reachability
  - Supports `--domain`, `--check`, and `--format json` options
  - Exits cleanly and destroys temporary participants on completion
- Implement `tools/partition-inspector.py`:
  - Joins Procedure domain with `room/*` wildcard partition
  - Enumerates all active partitions and lists entities per partition
  - Supports `--watch` (continuous) and `--filter` options
- Update `tools/README.md` to document all implemented tools
- Update `tools/admin-console.md` with concrete connection instructions now that Docker networking is fully configured
- Update `tools/dds-spy.md` with concrete examples using the real topics and domains

### Test Gate

- [ ] `python tools/medtech-diag/diag.py` runs against the Phase 2 Docker Compose environment and reports all checks PASS
- [ ] `python tools/medtech-diag/diag.py --format json` produces valid JSON output
- [ ] `python tools/partition-inspector.py` correctly lists OR-1 and OR-3 partitions when 2 surgical instances are running
- [ ] `tools/README.md` indexes all tools with scenario-to-tool mapping
