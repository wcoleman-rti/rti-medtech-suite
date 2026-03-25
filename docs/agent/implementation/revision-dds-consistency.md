# Revision: DDS Consistency Alignment

**Goal:** Bring the current implementation into compliance with
[vision/dds-consistency.md](../vision/dds-consistency.md). This revision
addresses gaps identified between the vision contract and the artifacts
produced by Phase 1 (complete) and Phase 2 Steps 2.1–2.2 (complete).

**Trigger:** Addition of `vision/dds-consistency.md` to the planning
framework, introducing contracts for initialization sequence, entity name
constants (`app_names.idl`), application architecture pattern, expanded
anti-pattern catalog, and Routing Service usage guidelines.

**Scope:** Retroactive alignment of completed work + forward integration
into not-yet-started steps. No new module features are added.

**Version impact:** Minor (V1.0.x patch) — no domain layout, topic, or
QoS architecture changes. All existing tests must continue to pass.

---

## Prerequisites

- All existing tests pass before starting any revision step
- `vision/dds-consistency.md` is the authoritative reference for every
  change in this revision

---

## Step R.1 — Author `app_names.idl` Entity Name Constants

### Work

- Create `interfaces/idl/app_names.idl` per
  [dds-consistency.md §1 Step 2](../vision/dds-consistency.md)
- Define `module MedtechEntityNames` with nested modules per participant
  library XML (e.g., `SurgicalParticipants`)
- Add `const string` entries for every participant config name, DataWriter
  name, and DataReader name currently defined in
  `interfaces/participants/*.xml`
- Add `connextdds_rtiddsgen_run()` calls in `interfaces/CMakeLists.txt`
  for C++ (`-language C++11 -standard IDL4_CPP`) and Python
  (`-language Python`) generation
- Verify generated C++ constants are `std::string_view` (C++17)
- Verify generated Python constants are importable module-level values
- Cross-check: every name in `app_names.idl` must exactly match the
  corresponding XML `<domain_participant name="...">`, `<data_writer
  name="...">`, and `<data_reader name="...">` attributes

### Test Gate

- [ ] `cmake --build build` generates `app_names` type support without
      errors (C++ and Python)
- [ ] C++ test: `#include` generated header, static_assert that each
      constant matches expected string value
- [ ] Python test: `from app_names.MedtechEntityNames import
      SurgicalParticipants as names; assert names.CONTROL_ROBOT ==
      "SurgicalParticipants::ControlRobot"`
- [ ] Every participant, writer, and reader name in participant XML has a
      corresponding `const string` in `app_names.idl` (automated check)
- [ ] All existing tests pass (no regression)

---

## Step R.2 — Relocate Python `dds_init.py` to Shared Location

### Work

- Move `modules/surgical-procedure/dds_init.py` to
  `modules/shared/medtech_dds_init/dds_init.py` (or equivalent package
  structure aligned with the C++ header location)
- Update all Python imports that reference `dds_init` to use the new
  shared package path
- Add CMake install rule to place the shared Python init module in
  `install/lib/python/site-packages/medtech_dds_init/`
- Verify the shared module is importable after `source install/setup.bash`
- Ensure the module remains idempotent per dds-consistency.md §1 Step 1

### Test Gate

- [ ] `from medtech_dds_init.dds_init import initialize_connext` succeeds
      after install
- [ ] `modules/surgical-procedure/` no longer contains `dds_init.py`
- [ ] All Python modules (`procedure_context.py`,
      `robot_controller_app.cpp` equivalent launchers) import from the
      shared location
- [ ] All existing tests pass (no regression)

---

## Step R.3 — Retrofit Entity Name Constants into Completed Steps

### Work

- **Phase 2 Step 2.1 (`procedure_context.py`):** Replace raw string
  literals in `create_participant_from_config()` and
  `find_datawriter()`/`find_datareader()` calls with generated constants
  from `app_names.idl`
- **Phase 2 Step 2.2 (`robot_controller_app.cpp`):** Replace raw string
  literals in `create_participant_from_config()`,
  `find_datawriter_by_name()`, and `find_datareader_by_name()` calls
  with generated constants from the `app_names` C++ header
- Verify no raw string literals remain for entity names in application
  code under `modules/`
- Add an automated lint check (see Step R.5) to prevent future regressions

### Test Gate

- [ ] `grep` for raw string literals matching participant/writer/reader
      names in `modules/` returns zero hits
- [ ] `procedure_context.py` uses `SurgicalParticipants.OPERATIONAL_PUB`
      (or equivalent) instead of a string literal
- [ ] `robot_controller_app.cpp` uses `names::CONTROL_ROBOT` (or
      equivalent) instead of a string literal
- [ ] All existing tests pass (no regression)

---

## Step R.4 — Reimplement Service Classes to Canonical Architecture

### Rationale

The existing `RobotControllerApp` (C++) and `ProcedureContextPublisher`
(Python) were written before `vision/dds-consistency.md` codified the
application architecture pattern (§3). Rather than patching deviations
incrementally, this step performs a clean reimplementation of both
service classes to establish a canonical reference that all future
modules (Steps 2.3–2.6, Phases 3–4) will follow. There is no
backwards-compatibility constraint — the public API can change freely.

### Current Deviations (audit findings)

**`robot_controller_app.cpp`:**

| # | Deviation | §3 Rule |
|---|-----------|---------|
| D-1 | Shutdown logic (detach conditions, `stop()`, join timer thread) lives in `run()`, not the destructor | Rule 6 |
| D-2 | Timer thread is a local variable in `run()`, not a class member — lifetime not scoped to the class | Rule 5, Rule 6 |
| D-3 | Uses a global `g_shutdown_requested` atomic instead of a private `running_` member | Rule 5 |
| D-4 | `sub_aws_` is declared before `ReadCondition` members — should be declared **after** all DDS entities and conditions for reverse destruction order | Rule 6 (member declaration order) |
| D-5 | Reader entities (`interlock_reader`, `command_reader`, `input_reader`) are local variables, not members — their lifetimes are not explicitly scoped to the class | Rule 1 |
| D-6 | No explicit `start()` method — `run()` both enables and blocks | Rule 5 |

**`procedure_context.py`:**

| # | Deviation | §3 Rule |
|---|-----------|---------|
| D-7 | `context_writer` and `status_writer` properties expose `dds.DataWriter` in the public API | Rule 1 (AP-10) |
| D-8 | `run()` only enables the participant — does not start an event loop (acceptable for a pure publisher, but should be named `enable()` or `start()` for consistency) | Rule 5 (naming) |

### Work — C++ (`RobotControllerApp`)

Rewrite `robot_controller_app.cpp` to match the canonical C++ service
class pattern in dds-consistency.md §3:

1. **Private `running_` member:** Replace the global
   `g_shutdown_requested` with a private `std::atomic<bool> running_`
   member. The signal handler sets it via a file-level pointer or the
   `main()` function signals the app object directly.

2. **Member declaration order (§3 Rule 6):**
   ```
   // Members declared in construction order:
   RobotController controller_;          // pure logic, no DDS
   ModuleLogger& log_;
   std::atomic<bool> running_{true};

   // DDS entities (destroyed after AsyncWaitSet):
   DomainParticipant participant_{nullptr};
   DataWriter<RobotState> state_writer_{nullptr};
   DataReader<SafetyInterlock> interlock_reader_{nullptr};
   DataReader<RobotCommand> command_reader_{nullptr};
   DataReader<OperatorInput> input_reader_{nullptr};

   // Conditions (destroyed before readers):
   ReadCondition interlock_rc_{nullptr};
   ReadCondition command_rc_{nullptr};
   ReadCondition input_rc_{nullptr};

   // AsyncWaitSet (destroyed first — declared last):
   AsyncWaitSet sub_aws_;

   // Worker thread (joined in destructor before aws_.stop()):
   std::thread timer_thread_;
   ```

3. **Store readers as members (D-5):** Look up all three readers in the
   constructor and store as private members alongside the writer. This
   makes their lifetimes explicitly scoped to the class.

4. **`start()` method (D-6, §3 Rule 5):**
   - Calls `participant_.enable()`
   - Starts the subscriber `AsyncWaitSet`
   - Spawns the 100 Hz timer thread and stores it in `timer_thread_`
   - Returns immediately (non-blocking)

5. **Blocking `wait_for_shutdown()`:** A simple method that blocks until
   `running_` is false (replacing the `sleep_for` loop that was in
   `run()`). The `main()` function calls `app.start()` then
   `app.wait_for_shutdown()`.

6. **Destructor (D-1, D-2, D-4, §3 Rule 6):**
   ```cpp
   ~RobotControllerApp()
   {
       // 1. Signal threads to stop
       running_.store(false);
       // 2. Join timer thread
       if (timer_thread_.joinable()) timer_thread_.join();
       // 3. Stop AsyncWaitSet
       sub_aws_.stop();
       // 4. Members destruct in reverse order:
       //    sub_aws_ → conditions → readers → writer → participant_
   }
   ```
   No manual detach of conditions — they are cleaned up by the
   `AsyncWaitSet` destructor after `stop()` returns.

7. **Entity name constants (from R.1/R.3):** All entity names use
   generated constants from `app_names.idl`.

8. **`main()` simplification:**
   ```cpp
   int main() {
       std::signal(SIGINT, ...);
       std::signal(SIGTERM, ...);

       auto log = medtech::init_logging(...);
       RobotControllerApp app(robot_id, room_id, procedure_id, log);
       app.start();
       app.wait_for_shutdown();
       return 0;
   }
   ```

### Work — Python (`ProcedureContextPublisher`)

Rewrite `procedure_context.py` to match the canonical Python service
class pattern in dds-consistency.md §3:

1. **Remove public writer properties (D-7):** Delete the
   `context_writer` and `status_writer` properties. Callers interact
   via `publish_context()` and `publish_status()` only. If tests need
   to verify writer state, add test-specific accessors behind a
   `_testing` flag or use DDS subscriber-side verification.

2. **Rename `run()` to `start()` (D-8):** Align with the canonical
   naming. `start()` calls `participant.enable()` and, if the class
   gains async tasks in the future, starts them.

3. **Entity name constants (from R.1/R.3):** All entity names use
   generated constants from `app_names.idl`:
   ```python
   from app_names.MedtechEntityNames import SurgicalParticipants as names

   self._participant = provider.create_participant_from_config(
       names.OPERATIONAL_PUB)
   ctx_any = self._participant.find_datawriter(
       names.PROCEDURE_CONTEXT_WRITER)
   ```

4. **Import from shared location (from R.2):**
   ```python
   from medtech_dds_init.dds_init import initialize_connext
   ```

### Existing Tests — Update Strategy

Tests that currently use the `context_writer` / `status_writer`
properties must be updated to either:
- Use subscriber-side verification (preferred — create a test reader
  and verify received samples)
- Use the public `publish_context()` / `publish_status()` methods and
  verify behavior through DDS delivery

This may require refactoring test fixtures. No test may be deleted.

### Test Gate

- [ ] `robot_controller_app.cpp` compiles and runs successfully with
      the new structure
- [ ] C++ destructor follows the canonical shutdown sequence: signal
      threads → join → `aws_.stop()` → member destruction
- [ ] C++ member declaration order: DDS entities before conditions
      before `AsyncWaitSet` before worker thread
- [ ] `RobotControllerApp` has no DDS entity types in its public API
      (only `start()`, `wait_for_shutdown()`, and signal-handler
      integration)
- [ ] `ProcedureContextPublisher` has no `context_writer` or
      `status_writer` properties (no DDS entity leakage)
- [ ] `ProcedureContextPublisher.start()` replaces `run()`
- [ ] All entity names use generated constants from `app_names.idl`
- [ ] All existing tests pass (no regression) — tests updated to use
      subscriber-side verification where needed
- [ ] Both service classes pass the AP-10 grep check (no DDS entity
      types in public interface)

---

## Step R.5 — Expand CI Anti-Pattern Checks

### Work

- Update `scripts/ci.sh` Step 5 (grep checks) to add the following
  prohibited pattern checks per dds-consistency.md §6 anti-pattern
  catalog:
  - **AP-8:** `grep` for `QosProvider(` constructor calls (custom
    QosProvider) in `modules/` — should find only `QosProvider::Default()`
    or `QosProvider.default`
  - **AP-9:** `grep` for publisher-level or subscriber-level partition
    QoS in `modules/` and `interfaces/qos/` — should find zero hits
  - **AP-10:** `grep` for DDS entity types (`DataWriter`, `DataReader`,
    `DomainParticipant`) in public class declarations in `modules/` —
    scoped to public sections of header files and class-level type hints
    in Python
  - **AP-11:** `grep` for raw string literals matching known entity names
    (from `app_names.idl` values) in `modules/` — should find zero hits
    outside of the generated code and the IDL file itself
- Each new grep check must:
  - Print a clear error message identifying the anti-pattern number
  - Exit non-zero on first violation
  - Exclude `build/`, `.venv/`, `interfaces/idl/app_names.idl`,
    and generated code directories

### Test Gate

- [ ] A deliberately introduced `QosProvider("file.xml")` in a module
      causes CI to fail with AP-8 message
- [ ] A deliberately introduced raw string literal for a known entity
      name causes CI to fail with AP-11 message
- [ ] Clean codebase passes all new and existing CI checks
- [ ] All existing tests pass (no regression)

---

## Step R.6 — Add `@consistency` Spec Tests

### Work

- Implement automated tests for the new `@consistency` scenarios added
  to [spec/common-behaviors.md](../spec/common-behaviors.md):
  - `tests/integration/test_dds_consistency.py` — integration tests:
    - Verify `initialize_connext()` sets XTypes mask and registers types
    - Verify participants are created from XML config (not constructed
      with domain ID)
    - Verify destructor shutdown sequence (C++ — may require a dedicated
      C++ test)
  - `tests/lint/check_dds_consistency.py` — lint/static checks:
    - Verify all entity name arguments use generated constants (AP-11)
    - Verify only default QosProvider is used (AP-8)
    - Verify no DDS entity types in public APIs (AP-10)
    - Verify no pub/sub partition QoS (AP-9)
- Tag all new tests with `@consistency`
- Run full test suite to confirm no regressions

### Test Gate

- [ ] `pytest tests/integration/test_dds_consistency.py` — all
      `@consistency` integration scenarios pass
- [ ] `pytest tests/lint/check_dds_consistency.py` — all `@consistency`
      lint scenarios pass
- [ ] Full test suite passes: `pytest tests/`

---

## Execution Order

```text
R.1 (app_names.idl)
  │
  ├──► R.2 (relocate dds_init.py)    — independent of R.1
  │
  └──► R.3 (retrofit constants)       — depends on R.1
         │
         └──► R.4 (architecture audit) — depends on R.2, R.3
                │
                ├──► R.5 (CI checks)   — depends on R.3
                │
                └──► R.6 (spec tests)  — depends on R.3, R.4
```

Steps R.1 and R.2 can proceed in parallel. Steps R.3–R.6 must follow
in sequence.

---

## Completion Criteria

- [ ] All six revision steps completed with test gates green
- [ ] Full test suite passes: `pytest tests/` — zero failures, zero skips
- [ ] All new `@consistency` spec scenarios have corresponding tests
- [ ] CI pipeline (`scripts/ci.sh`) includes expanded anti-pattern checks
- [ ] No raw string literals for entity names in `modules/`
- [ ] Python `dds_init.py` is in the shared location
- [ ] `app_names.idl` is authored, generated, and integrated
- [ ] No open regressions from the revision
