# Phase 5: Procedure Orchestration

**Goal:** Introduce the service-oriented orchestration layer: the
`medtech::Service` interface, dual-mode participant pattern, Service Host
framework, Procedure Controller GUI, and the Orchestration domain
(Domain 15) with DDS RPC and pub/sub state distribution.

**Depends on:** Phases 1–2 (Foundation + Surgical Procedure complete)
**Blocks:** Phase 3 (Hospital Dashboard), Phase 4 (Clinical Alerts)

**Spec file:** [spec/procedure-orchestration.md](../spec/procedure-orchestration.md)
**Vision references:**
- [vision/capabilities.md — V1.0.0](../vision/capabilities.md)
- [vision/system-architecture.md — Orchestration Domain](../vision/system-architecture.md)
- [vision/data-model.md — Domain 15](../vision/data-model.md)
- [vision/dds-consistency.md — §3 Service Interface, Dual-Mode Participant](../vision/dds-consistency.md)
- [vision/coding-standards.md](../vision/coding-standards.md)

---

## Step 5.1 — Orchestration IDL & QoS Profiles

### Work

- Author `interfaces/idl/orchestration/Orchestration.idl` in `module Orchestration`:
  - `ServiceState` enum: `STOPPED`, `STARTING`, `RUNNING`, `STOPPING`, `FAILED`, `UNKNOWN`
  - `OperationResultCode` enum: `OK`, `INVALID_SERVICE`, `INVALID_CONFIG`, `BUSY`, `ALREADY_RUNNING`, `NOT_RUNNING`, `INTERNAL_ERROR`
  - `HostCatalog` struct (keyed on `host_id`): host ID, supported service types, capacity, health summary
  - `ServiceStatus` struct (keyed on `host_id` + `service_id`): host ID, service ID, `ServiceState`, timestamp
  - `ServiceRequest` struct: service_id, configuration parameters
  - `ConfigureRequest` struct: service_id, configuration parameters
  - `OperationResult` struct: `OperationResultCode`, message string
  - `CapabilityReport` struct: supported services, capacity
  - `HealthReport` struct: alive flag, summary, diagnostics
  - `@service("DDS") interface ServiceHostControl`: `start_service`, `stop_service`, `configure_service`, `get_capabilities`, `get_health`
- Add `connextdds_rtiddsgen_run()` calls for C++11 and Python code generation of the orchestration IDL
- Add Domain 15 definition to `interfaces/domains/Domains.xml` with no domain tag
- Author `Pattern.RPC` QoS profile in `interfaces/qos/Patterns.xml`: RELIABLE, KEEP_ALL, appropriate history depth
- Author `Pattern.Status` QoS profile (if not already covered by existing `Patterns::State`): TRANSIENT_LOCAL, RELIABLE, KEEP_LAST 1, liveliness 2 s
- Author topic-specific profiles for `HostCatalog` and `ServiceStatus` in `interfaces/qos/TopicProfiles.xml` inheriting from the appropriate pattern
- Add orchestration participant profiles to `interfaces/participants/Participants.xml`:
  - `Participant::Orchestration` — Domain 15, no domain tag, with contained entities for `HostCatalog` writer/reader, `ServiceStatus` writer/reader, and `ServiceHostControl` RPC endpoints
  - `Participant::ProcedureController_Orchestration` — controller's Orchestration domain participant (RPC client + status subscriber)
  - `Participant::ProcedureController_Hospital` — controller's Hospital domain participant (read-only subscriber)
- Add orchestration entity name constants to `interfaces/idl/app_names/app_names.idl` per the naming convention in [dds-consistency.md §1 Step 2](../vision/dds-consistency.md)
- Verify generated code compiles (C++) and imports (Python)

### Test Gate

- [ ] `cmake --build build` succeeds with orchestration IDL generated
- [ ] C++ can `#include <orchestration/Orchestration.hpp>` and reference `Orchestration::ServiceState`
- [ ] Python can `from orchestration.Orchestration import ServiceState` and reference all enum values
- [ ] Domain 15 is present in the installed `Domains.xml`
- [ ] `Pattern.RPC` and orchestration topic profiles are present in installed QoS XML
- [ ] QoS compatibility checker (`tools/qos-checker.py`) passes with the new profiles
- [ ] `bash scripts/ci.sh --lint` passes

---

## Step 5.2 — `medtech::Service` Abstract Interface

### Work

- Author `modules/shared/include/medtech/service.hpp` (C++):
  - Pure abstract class `medtech::Service` with virtual `run()`, `stop()`, `name() const`, `state() const`
  - `run()` blocks the calling thread; `stop()` is non-blocking and thread-safe
  - `state()` returns `Orchestration::ServiceState`
  - Virtual destructor defaulted
- Author `modules/shared/medtech/service.py` (Python):
  - ABC `medtech.Service` with `async def run()`, `def stop()`, `name` property, `state` property
  - `state` returns the IDL-generated `ServiceState`
- Install the C++ header via CMake `install(FILES ...)` to `include/medtech/`
- Install the Python module to the Python site-packages path
- Write unit tests:
  - C++: A mock service (inherits `medtech::Service`) that transitions through all states on `run()` and responds to `stop()`
  - Python: A mock service (inherits `medtech.Service`) that transitions through all states

### Test Gate

- [ ] C++ unit test: mock service state transitions `STOPPED` → `STARTING` → `RUNNING` → (stop) → `STOPPING` → `STOPPED`
- [ ] C++ unit test: `stop()` is non-blocking (returns within bounded time while `run()` is in progress)
- [ ] C++ unit test: `FAILED` state on simulated error
- [ ] Python unit test: same state transition sequence
- [ ] Python unit test: `stop()` non-blocking
- [ ] Python unit test: `FAILED` state
- [ ] `bash scripts/ci.sh --lint` passes

---

## Step 5.3 — Refactor V1.0 Services to Dual-Mode

### Work

- Refactor each existing V1.0 service class to:
  1. Implement `medtech::Service` (C++) or `medtech.Service` (Python)
  2. Accept a nullable `DomainParticipant` as an optional constructor parameter
  3. In standalone mode (`None`/`null`): create own participant, set partition, call `initialize_connext()`
  4. In hosted mode (valid participant): use the provided participant, skip `initialize_connext()`
  5. Validate participant creation and all entity lookups in both modes
  6. Never read environment variables — all context via constructor parameters
  7. Expose `run()`, `stop()`, `name`, `state` per the interface contract
- Affected services (C++):
  - `RobotController`
- Affected services (Python):
  - `BedsideMonitor` (vitals + alarms)
  - `CameraSimulator`
  - `ProcedureContextPublisher`
  - `DeviceTelemetryGateway`
  - `OperatorConsole`
- Update each service's standalone `main()` / entry point to:
  1. Read environment variables (`ROOM_ID`, `PROCEDURE_ID`, etc.)
  2. Pass them as constructor parameters to the service
  3. Call `service.run()` (or `asyncio.run(service.run())` for Python)
- Verify backward compatibility: all existing V1.0 tests must pass without modification

### Test Gate

- [ ] All existing V1.0 test suite passes (`bash scripts/ci.sh`) — zero regressions
- [ ] Each refactored service constructs in standalone mode with `None`/`null` participant
- [ ] Each refactored service constructs in hosted mode with a provided participant
- [ ] Entity lookup validation: test that an invalid participant config raises/throws with the entity name
- [ ] State transitions verified for each service class
- [ ] No service class reads environment variables directly (CI lint check)
- [ ] Docker Compose deployment still starts all services in standalone mode

---

## Step 5.4 — Service Host Framework (C++)

### Work

- Author the Robot Service Host (`modules/surgical-procedure/src/robot_service_host.cpp`):
  - Creates an Orchestration domain participant from `Participant::Orchestration` XML config
  - Creates a Procedure domain `control`-tag participant for the hosted `RobotController`
  - Registers `ServiceHostControl/<host_id>` RPC service on the Orchestration domain
  - Publishes `HostCatalog` (TRANSIENT_LOCAL, liveliness 2 s)
  - Polls `RobotController::state()` and publishes `ServiceStatus` (write-on-change)
  - Implements `start_service`: constructs `RobotController` in hosted mode, spawns `run()` on a dedicated thread
  - Implements `stop_service`: calls `stop()`, joins thread
  - Implements `get_capabilities` and `get_health`
  - Reconciliation on startup: publishes current (empty) state; controller detects mismatch via TRANSIENT_LOCAL
- Author entry point (`main.cpp`) that reads `HOST_ID`, `ROOM_ID` from environment and passes to the Service Host constructor
- Author a Dockerfile / Docker Compose service for the Robot Service Host

### Test Gate

- [ ] Robot Service Host starts and publishes `HostCatalog` on the Orchestration domain
- [ ] `ServiceHostControl` RPC is addressable at `ServiceHostControl/<host_id>`
- [ ] `start_service` RPC creates and starts `RobotController` in hosted mode
- [ ] `ServiceStatus` transitions (`STOPPED` → `STARTING` → `RUNNING`) are published
- [ ] `stop_service` RPC stops the service; `ServiceStatus` transitions to `STOPPED`
- [ ] `ALREADY_RUNNING` returned on duplicate start
- [ ] `NOT_RUNNING` returned on stopping a non-running service
- [ ] Liveliness lost detected when Service Host process is killed (within 2 s)
- [ ] Orchestration domain is isolated from Procedure domain (no cross-domain discovery)
- [ ] `bash scripts/ci.sh` passes

---

## Step 5.5 — Service Host Framework (Python)

### Work

- Author the Clinical Service Host (`modules/surgical-procedure/clinical_service_host.py`):
  - Manages Python services: `BedsideMonitor`, `DeviceTelemetryGateway`
  - Same orchestration pattern as C++ host: RPC, HostCatalog, ServiceStatus
  - Uses `asyncio.gather()` for hosted service coroutines
- Author the Operational Service Host (`modules/surgical-procedure/operational_service_host.py`):
  - Manages: `CameraSimulator`, `ProcedureContextPublisher`
  - Same pattern
- Author entry points and Docker Compose services for both

### Test Gate

- [ ] Clinical Service Host publishes `HostCatalog` and responds to RPC
- [ ] `start_service` creates and gathers Python service coroutines
- [ ] `ServiceStatus` reflects hosted service state transitions
- [ ] `stop_service` cancels service coroutines; state transitions to `STOPPED`
- [ ] Operational Service Host same test coverage
- [ ] Partition isolation: `room/OR-1` host not discoverable by `room/OR-3` controller
- [ ] `bash scripts/ci.sh` passes

---

## Step 5.6 — Procedure Controller GUI

### Work

- Author the Procedure Controller PySide6 application (`modules/hospital-dashboard/procedure_controller.py` or a new module directory):
  - Creates one participant on the Orchestration domain (`Participant::ProcedureController_Orchestration`)
  - Creates one participant on the Hospital domain (`Participant::ProcedureController_Hospital`, read-only)
  - Subscribes to `HostCatalog` and `ServiceStatus` on the Orchestration domain
  - Displays available Service Hosts and their service states
  - Provides UI controls to: select a host, start a service, stop a service, view capabilities/health
  - Issues RPC commands via `ServiceHostControl` client stubs
  - Reads scheduling context from the Hospital domain (read-only)
  - Uses polling reads or QtAsyncio for DDS data reception on the UI thread per [dds-consistency.md §5](../vision/dds-consistency.md)
  - Writes (if any) on the UI thread use `NonBlockingWrite` QoS snippet per vision policy
- Apply shared GUI design standard: RTI Blue header, Roboto fonts, `medtech.qss`
- Author entry point and Docker Compose service

### Test Gate

- [ ] Procedure Controller discovers available Service Hosts (HostCatalog received)
- [ ] Procedure Controller displays service states (ServiceStatus rendered)
- [ ] `start_service` RPC issued from GUI results in service starting on target host
- [ ] `stop_service` RPC issued from GUI results in service stopping
- [ ] Controller is read-only on Hospital domain (no DataWriters created)
- [ ] Controller restart reconstructs state from TRANSIENT_LOCAL (within 15 s)
- [ ] Controller does not join Procedure domain
- [ ] GUI remains responsive during concurrent data arrival
- [ ] `bash scripts/ci.sh` passes

---

## Step 5.7 — End-to-End Orchestration Integration

### Work

- Author Docker Compose target for the full orchestration scenario:
  - Robot Service Host (C++) + Clinical Service Host (Python) + Operational Service Host (Python) + Procedure Controller
  - All on `hospital-net`
  - Routing Service still bridges Procedure → Hospital (unchanged)
- Author integration tests covering the full lifecycle:
  1. Controller discovers all three Service Hosts
  2. Controller starts services on each host via RPC
  3. Services reach `RUNNING` state, surgical data flows on Procedure domain
  4. Controller stops services; state returns to `STOPPED`
  5. Controller restarts and reconstructs state from TRANSIENT_LOCAL
  6. Service Host crash: controller detects liveliness loss
  7. Orchestration failure does not disrupt running Procedure domain data
- Verify all existing V1.0 scenarios still pass in standalone mode alongside the new orchestration deployment
- Verify all `@orchestration` spec scenarios pass
- **`@acceptance` test (Rule 8):** Author an acceptance test that exercises
  the orchestrated surgical workflow end-to-end:
  1. Procedure Controller starts all services on all hosts via RPC
  2. Operator Console sends a robot command → RobotController moves → RobotState updates
  3. BedsideMonitor publishes vitals → subscriber receives on Procedure domain
  4. Procedure Controller stops all services → all states return to STOPPED
  - The test must fail if any component is missing or non-functional.
- **`@acceptance` test (Phase 2 retroactive — Rule 8):** Author an acceptance
  test for the standalone surgical-procedure module (no orchestration):
  1. Docker Compose starts all surgical services in standalone mode
  2. Operator Console publishes a `RobotCommand` → RobotController publishes
     updated `RobotState` within 100 ms
  3. BedsideMonitor publishes `PatientVitals` → subscriber receives
  4. An alarm condition triggers an `AlarmMessage`
  - This covers the gap identified in Step 2.8.

### Test Gate

- [ ] Full Docker Compose orchestration scenario runs end-to-end
- [ ] All `@orchestration` spec scenarios pass
- [ ] All V1.0 spec scenarios pass (zero regressions)
- [ ] Orchestration domain isolation verified (no cross-domain data leakage)
- [ ] Service Host crash → liveliness lost detected within 2 s
- [ ] Procedure Controller crash → surgical data unaffected
- [ ] `@acceptance` orchestration workflow test passes
- [ ] `@acceptance` standalone surgical-procedure workflow test passes (Phase 2 retroactive)
- [ ] All quality gates pass: `bash scripts/ci.sh`

---

## Step 5.8 — Documentation & Performance Baseline

### Work

- Author `modules/surgical-procedure/README.md` updates (or new Service Host READMEs) per [vision/documentation.md](../vision/documentation.md):
  - Required seven sections (Overview, Quick Start, Architecture, Configuration Reference, Testing, Going Further)
  - DDS Entities table documenting all Orchestration domain participants, writers, readers, RPC endpoints
  - Threading model description for each Service Host type
  - Environment Variables table
- Update project root `README.md` if needed to reference V1.0 orchestration capabilities
- Run the performance benchmark harness and record the Phase 5 baseline:
  - `tests/performance/baselines/phase-5.json`
- Verify all documentation lint passes

### Test Gate

- [ ] All module READMEs pass `markdownlint` and section-order lint
- [ ] `tests/performance/baselines/phase-5.json` committed
- [ ] No performance regression against Phase 2 baseline (within defined thresholds)
- [ ] `bash scripts/ci.sh` passes — all 12 quality gates green

---

## V1.0.0 Release Gate (Phase 5 contribution)

Phase 5 is part of the V1.0.0 release. The full V1.0.0 release gate
(covering Phases 1–5 and 3–4) is defined in
[implementation/README.md](README.md#v100-release-gate). Phase 5’s
contribution to that gate:

- [ ] Full test suite passes (`bash scripts/ci.sh`) — zero failures, zero skips
- [ ] All `@orchestration` spec scenarios pass
- [ ] All V1.0 spec scenarios from Phases 1–2 still pass (no regressions)
- [ ] Full Docker Compose environment runs end-to-end: standalone deployment + orchestrated deployment
- [ ] Procedure Controller discovers, starts, stops, and monitors services across all three Service Host types
- [ ] Orchestration domain is fully isolated from Procedure and Hospital domains
- [ ] All module READMEs pass lint
- [ ] Performance benchmark passes against Phase 5 baseline
- [ ] No open incidents in `docs/agent/incidents.md`
- [ ] `tests/performance/baselines/phase-5.json` committed
