# Phase 5: Procedure Orchestration

**Goal:** Introduce the service-oriented orchestration layer: the
`medtech::Service` interface, dual-mode participant pattern, Service Host
framework, Procedure Controller GUI, and the Orchestration domain
(Domain 11) with DDS RPC and pub/sub state distribution.

**Depends on:** Phases 1–2 (Foundation + Surgical Procedure complete)
**Blocks:** Phase 3 (Hospital Dashboard), Phase 4 (Clinical Alerts)

**Spec file:** [spec/procedure-orchestration.md](../spec/procedure-orchestration.md)
**Vision references:**
- [vision/capabilities.md — V1.0.0](../vision/capabilities.md)
- [vision/system-architecture.md — Orchestration Domain](../vision/system-architecture.md)
- [vision/data-model.md — Domain 11](../vision/data-model.md)
- [vision/dds-consistency.md — §3 Service Interface, Dual-Mode Participant](../vision/dds-consistency.md)
- [vision/coding-standards.md](../vision/coding-standards.md)

---

## Step 5.1 — Orchestration IDL & QoS Profiles ✅

**Status:** Complete — committed `9c0ea97`

### Work

- Author `interfaces/idl/orchestration/Orchestration.idl` in `module Orchestration`:
  - `ServiceState` enum: `STOPPED`, `STARTING`, `RUNNING`, `STOPPING`, `FAILED`, `UNKNOWN`
  - `OperationResultCode` enum: `OK`, `INVALID_SERVICE`, `INVALID_CONFIG`, `BUSY`, `ALREADY_RUNNING`, `NOT_RUNNING`, `INTERNAL_ERROR`
  - `ServiceCatalog` struct (keyed on `host_id` + `service_id`): host ID, service ID, display name, property descriptors, health summary
  - `ServiceStatus` struct (keyed on `host_id` + `service_id`): host ID, service ID, `ServiceState`, timestamp
  - `ServiceProperty` `@final @nested` struct: name, value (bounded strings)
  - `ServiceRequest` struct: service_id, sequence of `ServiceProperty` name-value pairs
  - `OperationResult` struct: `OperationResultCode`, message string
  - `CapabilityReport` struct: supported services, capacity
  - `HealthReport` struct: alive flag, summary, diagnostics
  - `@service("DDS") interface ServiceHostControl`: `start_service`, `stop_service`, `update_service`, `get_capabilities`, `get_health`
- Add `connextdds_rtiddsgen_run()` calls for C++11 and Python code generation of the orchestration IDL
- Add Domain 11 definition to `interfaces/domains/Domains.xml` with no domain tag
- Author `Pattern.RPC` QoS profile in `interfaces/qos/Patterns.xml`: RELIABLE, KEEP_ALL, appropriate history depth
- Author `Pattern.Status` QoS profile (if not already covered by existing `Patterns::State`): TRANSIENT_LOCAL, RELIABLE, KEEP_LAST 1, liveliness 2 s
- Author topic-specific profiles for `ServiceCatalog` and `ServiceStatus` in `interfaces/qos/TopicProfiles.xml` inheriting from the appropriate pattern
- Add orchestration participant profiles to `interfaces/participants/Participants.xml`:
  - `Participant::Orchestration` — Domain 11, no domain tag, with contained entities for `ServiceCatalog` writer/reader, `ServiceStatus` writer/reader, and `ServiceHostControl` RPC endpoints
  - `Participant::ProcedureController_Orchestration` — controller's Orchestration domain participant (RPC client + status subscriber)
  - `Participant::ProcedureController_Hospital` — controller's Hospital domain participant (read-only subscriber)
- Add orchestration entity name constants to `interfaces/idl/app_names/app_names.idl` per the naming convention in [dds-consistency.md §1 Step 2](../vision/dds-consistency.md)
- Verify generated code compiles (C++) and imports (Python)

### Test Gate

- [x] `cmake --build build` succeeds with orchestration IDL generated
- [x] C++ can `#include <orchestration/Orchestration.hpp>` and reference `Orchestration::ServiceState`
- [x] Python can `from orchestration import Orchestration` and reference all enum values
- [x] Domain 11 is present in the installed `Domains.xml`
- [x] `Pattern.RPC` and orchestration topic profiles are present in installed QoS XML
- [x] QoS compatibility checker (`tools/qos-checker.py`) passes with the new profiles
- [x] `bash scripts/ci.sh --lint` passes

**Notes:**
- Python import is `from orchestration import Orchestration` (flat module), not `from orchestration.Orchestration`
- IDL parameter `request` renamed to `req` to avoid rtiddsgen 4.6.0 C++ codegen variable shadowing (INC-049)
- `BuiltinQosLib::Pattern.RPC` used as base_name for the RPC profile
- `RTIConnextDDS::messaging_cpp2_api` linked for RPC client/service stubs

---

## Step 5.2 — `medtech::Service` Abstract Interface ✅

**Status:** Complete — committed `5c40dd8`

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

- [x] C++ unit test: mock service state transitions `STOPPED` → `STARTING` → `RUNNING` → (stop) → `STOPPING` → `STOPPED`
- [x] C++ unit test: `stop()` is non-blocking (returns within bounded time while `run()` is in progress)
- [x] C++ unit test: `FAILED` state on simulated error
- [x] Python unit test: same state transition sequence
- [x] Python unit test: `stop()` non-blocking
- [x] Python unit test: `FAILED` state
- [x] `bash scripts/ci.sh --lint` passes

---

## Step 5.3 — Refactor V1.0 Services to Dual-Mode ✅

**Status:** Complete — committed `60c585e`

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
  - `RobotControllerService` (`robot_controller_service.cpp`) — split from monolithic `robot_controller_app.cpp` into library + executable
- Affected services (Python):
  - `BedsideMonitorService` (`bedside_monitor_service.py`)
  - `CameraService` (`camera_service.py`)
  - `ProcedureContextService` (`procedure_context_service.py`)
  - `DeviceTelemetryService` (`device_telemetry_service.py`)
  - `OperatorConsoleService` (`operator_console_service.py`)
- Update each service's standalone `main()` / entry point to:
  1. Read environment variables (`ROOM_ID`, `PROCEDURE_ID`, etc.)
  2. Pass them as constructor parameters to the service
  3. Call `service.run()` (or `asyncio.run(service.run())` for Python)
  4. Only interact with the public Service interface (`run()`, `stop()`, `state`)
- Verify backward compatibility: all existing V1.0 tests updated for new class/file names

**User-feedback-driven refinements (applied during implementation):**
- All service classes renamed to `*Service` convention; files renamed to match
- `start()` made private (`_start()` in Python, `private:` in C++) — only `run()`/`stop()` are public
- C++ split into static library (`robot_controller_service`) + executable (`robot-controller`) with factory function `make_robot_controller_service()` — keeps DDS types out of headers (AP-10)
- `ProcedureContextService.run()` is self-contained: publishes initial context/status internally
- All `__main__.py` entry points use only the public Service interface
- `request_shutdown()` removed from C++ in favor of `stop()`
- `OperatorConsoleService` entity lookup validation added (was missing null-check on `find_datawriter` results — fixed to match other services' pattern)

### Test Gate

- [x] All existing V1.0 test suite passes (`bash scripts/ci.sh`) — zero regressions (12/12 gates)
- [x] Each refactored service constructs in standalone mode with `None`/`null` participant
- [x] Each refactored service constructs in hosted mode with a provided participant
- [x] Entity lookup validation: test that an invalid participant config raises/throws with the entity name
- [x] State transitions verified for each service class
- [x] No service class reads environment variables directly (CI lint check passes)
- [x] Docker Compose deployment still starts all services in standalone mode (Gate 12 smoke test)

---

## Step 5.4 — Service Host Framework (C++)

**Status:** Complete — committed `df7bb1f`

### Work

- Author the Robot Service Host (`modules/surgical-procedure/src/robot_service_host.cpp`):
  - Creates an Orchestration domain participant from `Participant::Orchestration` XML config
  - Creates a Procedure domain `control`-tag participant for the hosted `RobotController`
  - Registers `ServiceHostControl/<host_id>` RPC service on the Orchestration domain
  - Publishes `ServiceCatalog` (TRANSIENT_LOCAL, liveliness 2 s)
  - Polls `RobotController::state()` and publishes `ServiceStatus` (write-on-change)
  - Implements `start_service`: constructs `RobotController` in hosted mode, spawns `run()` on a dedicated thread
  - Implements `stop_service`: calls `stop()`, joins thread
  - Implements `update_service`: accepts updated configuration (no-op in V1.0)
  - Implements `get_capabilities` and `get_health`
  - Reconciliation on startup: publishes current (empty) state; controller detects mismatch via TRANSIENT_LOCAL
- Author entry point (`main.cpp`) that reads `HOST_ID`, `ROOM_ID` from environment and passes to the Service Host constructor
- Author a Dockerfile / Docker Compose service for the Robot Service Host

### Test Gate

- [x] Robot Service Host starts and publishes `ServiceCatalog` on the Orchestration domain
- [x] `ServiceHostControl` RPC is addressable at `ServiceHostControl/<host_id>`
- [x] `start_service` RPC creates and starts `RobotController` in hosted mode
- [x] `ServiceStatus` transitions (`STOPPED` → `STARTING` → `RUNNING`) are published
- [x] `stop_service` RPC stops the service; `ServiceStatus` transitions to `STOPPED`
- [x] `ALREADY_RUNNING` returned on duplicate start
- [x] `NOT_RUNNING` returned on stopping a non-running service
- [x] Liveliness lost detected when Service Host process is killed (within 2 s)
- [x] Orchestration domain is isolated from Procedure domain (no cross-domain discovery)
- [x] `bash scripts/ci.sh` passes

---

## Step 5.5 — Service Host Framework (Python)

**Status:** Complete — committed `1be1dc1`

### Work

- Author the Clinical Service Host (`modules/surgical-procedure/clinical_service_host.py`):
  - Manages Python services: `BedsideMonitor`, `DeviceTelemetryGateway`
  - Same orchestration pattern as C++ host: RPC, ServiceCatalog, ServiceStatus
  - Uses `asyncio.gather()` for hosted service coroutines
- Author the Operational Service Host (`modules/surgical-procedure/operational_service_host.py`):
  - Manages: `CameraSimulator`, `ProcedureContextPublisher`
  - Same pattern
- Author the Operator Service Host (`modules/surgical-procedure/operator_service_host/`):
  - Manages: `OperatorConsoleService`
  - Same pattern: thin factory wrapper, delegates to `make_service_host()`
- Author entry points and Docker Compose services for all three

### Test Gate

- [x] Clinical Service Host publishes `ServiceCatalog` and responds to RPC
- [x] `start_service` creates and gathers Python service coroutines
- [x] `ServiceStatus` reflects hosted service state transitions
- [x] `stop_service` cancels service coroutines; state transitions to `STOPPED`
- [x] Operational Service Host same test coverage
- [x] Tier partition isolation: `procedure`-tier Service Host not discoverable by a participant using only the `facility` DomainParticipant partition (and vice versa)
- [x] `bash scripts/ci.sh` passes

---

## Step 5.6 — Procedure Controller GUI ✅ `4d811d5`

### Work

- Author the Procedure Controller NiceGUI application (`modules/hospital-dashboard/procedure_controller/controller.py`):
  - Creates one participant on the Orchestration domain (`Participant::ProcedureController_Orchestration`)
  - Creates one participant on the Hospital domain (`Participant::ProcedureController_Hospital`, read-only)
  - Subscribes to `ServiceCatalog` and `ServiceStatus` on the Orchestration domain
  - Displays available Service Hosts and their service states
  - Provides UI controls to: select a host, start a service, stop a service, view capabilities/health
  - Issues RPC commands via `ServiceHostControl` client stubs
  - Reads scheduling context from the Hospital domain (read-only)
  - Uses `background_tasks.create()` / asyncio for DDS data reception per [dds-consistency.md §5](../vision/dds-consistency.md)
  - Writes on the asyncio event loop use `NonBlockingWrite` QoS snippet per vision policy
- Apply shared GUI design standard: RTI Blue header, Roboto fonts, NiceGUI theme
- Author entry point and Docker Compose service

### Test Gate

- [x] Procedure Controller discovers available Service Hosts (ServiceCatalog received)
- [x] Procedure Controller displays service states (ServiceStatus rendered)
- [x] `start_service` RPC issued from GUI results in service starting on target host
- [x] `stop_service` RPC issued from GUI results in service stopping
- [x] Controller is read-only on Hospital domain (no DataWriters created)
- [x] Controller restart reconstructs state from TRANSIENT_LOCAL (within 15 s)
- [x] Controller does not join Procedure domain
- [x] GUI remains responsive during concurrent data arrival
- [x] `bash scripts/ci.sh` passes

---

## Step 5.7 — End-to-End Orchestration Integration ✅ `00da821`

### Work

- Author Docker Compose target for the full orchestration scenario:
  - Robot Service Host (C++) + Operator Service Host (Python) + Clinical Service Host (Python) + Operational Service Host (Python) + Procedure Controller
  - All on `hospital-net`
  - Routing Service still bridges Procedure → Hospital (unchanged)
- Author integration tests covering the full lifecycle:
  1. Controller discovers all four Service Hosts
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

- [x] Full Docker Compose orchestration scenario runs end-to-end
- [x] All `@orchestration` spec scenarios pass
- [x] All V1.0 spec scenarios pass (zero regressions)
- [x] Orchestration domain isolation verified (no cross-domain data leakage)
- [x] Service Host crash → liveliness lost detected within 2 s
- [x] Procedure Controller crash → surgical data unaffected
- [x] `@acceptance` orchestration workflow test passes
- [x] `@acceptance` standalone surgical-procedure workflow test passes (Phase 2 retroactive)
- [x] All quality gates pass: `bash scripts/ci.sh`

---

## Step 5.8 — Documentation & Performance Baseline ✅ `75ae84b`

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

- [x] All module READMEs pass `markdownlint` and section-order lint
- [x] `tests/performance/baselines/phase-5.json` committed
- [x] No performance regression against Phase 2 baseline (within defined thresholds)
- [x] `bash scripts/ci.sh` passes — all 12 quality gates green

---

## V1.0.0 Release Gate (Phase 5 contribution)

Phase 5 is part of the V1.0.0 release. The full V1.0.0 release gate
(covering Phases 1–5 and 3–4) is defined in
[implementation/README.md](README.md#v100-release-gate). Phase 5’s
contribution to that gate:

- [x] Full test suite passes (`bash scripts/ci.sh`) — zero failures, zero skips
- [x] All `@orchestration` spec scenarios pass
- [x] All V1.0 spec scenarios from Phases 1–2 still pass (no regressions)
- [x] Full Docker Compose environment runs end-to-end: standalone deployment + orchestrated deployment
- [x] Procedure Controller discovers, starts, stops, and monitors services across all three Service Host types
- [x] Orchestration domain is fully isolated from Procedure and Hospital domains
- [x] All module READMEs pass lint
- [x] Performance benchmark passes against Phase 5 baseline
- [ ] No open incidents in `docs/agent/incidents.md` *(INC-041, INC-042 remain open — Phase 2 discovery issues, not Phase 5 blockers)*
- [x] `tests/performance/baselines/phase-5.json` committed
