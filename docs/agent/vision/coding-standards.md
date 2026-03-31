# Coding Standards

This document defines the naming conventions, code organization rules, and
stylistic standards that all implementing agents must follow when writing C++,
Python, CMake, and test code in this project. These conventions ensure that
code written across multiple agent sessions, models, and providers is
internally consistent and reads as if authored by a single developer.

Rules here apply to **application code only** — not to generated code
produced by `rtiddsgen`. Generated files live in the build directory and are
never modified by hand.

Where this document is silent, the language-community default applies:
the [C++ Core Guidelines](https://isocpp.github.io/CppCoreGuidelines/) for
C++ and [PEP 8](https://peps.python.org/pep-0008/) for Python.

---

## C++ Conventions

### Naming

| Element | Style | Example |
|---------|-------|---------|
| Namespace | `snake_case` | `medtech`, `medtech::surgical` |
| Class | `PascalCase` | `ProcedureManager`, `SafetyMonitor` |
| Struct (plain data) | `PascalCase` | `LaunchConfig`, `MetricSnapshot` |
| Function / method | `snake_case` | `start_procedure()`, `compute_risk()` |
| Variable (local, member) | `snake_case` | `sample_count`, `patient_id` |
| Private data member | `snake_case_` (trailing underscore) | `participant_`, `reader_` |
| Constant (`constexpr` / `const`) | `k_snake_case` | `k_max_retries`, `k_default_timeout` |
| Enum type | `PascalCase` | `ProcedurePhase` |
| Enum value (scoped `enum class`) | `PascalCase` | `ProcedurePhase::InProgress` |
| Macro (avoid if possible) | `ALL_CAPS` | `MEDTECH_ASSERT` |
| Template parameter | `PascalCase` | `template <typename DataType>` |
| File name (`.cpp`, `.hpp`) | `snake_case` | `procedure_manager.hpp` |

### Namespace Structure

All project code lives under the `medtech` root namespace. Modules add a
nested namespace matching the module directory name:

```cpp
namespace medtech::surgical {
    class ProcedureManager { ... };
}

namespace medtech::dashboard {
    class RoomPanel { ... };
}

namespace medtech::clinical_alerts {
    double compute_hemorrhage_risk(...);
}
```

- **Never `using namespace` in headers.** A header must not import any
  namespace into the global scope or its parent scope.
- **`using namespace` in `.cpp` files is permitted** only for the module's
  own namespace (e.g., `using namespace medtech::surgical;` inside
  `procedure_manager.cpp`). Never import `rti::` or `dds::` namespaces
  unqualified — use them explicitly or with targeted `using` declarations
  (`using rti::core::cond::AsyncWaitSet;`).
- **Anonymous namespaces** for file-local helpers (preferred over `static`
  functions).

### Class vs Struct

Use the keyword that communicates intent:

| Use `struct` when | Use `class` when |
|-------------------|------------------|
| All members are public | There are private members or invariants to maintain |
| No non-trivial constructors, destructors, or virtual methods | Constructors enforce invariants |
| The type is plain data or a configuration bundle | The type has behavior (methods beyond getters) |
| The type is a local aggregate returned from a function | The type manages a resource (RAII) |

Both may have methods, but `struct` signals "transparent data" while `class`
signals "enforced encapsulation." When in doubt, use `class`.

### Headers

- Use **`#pragma once`** as the include guard. Do not use `#ifndef`/`#define`
  guards.
- Header files use the `.hpp` extension. Implementation files use `.cpp`.
- Include order (separated by blank lines):
  1. Corresponding header (`#include "procedure_manager.hpp"`)
  2. Project headers (`#include "medtech/surgical/safety_monitor.hpp"`)
  3. RTI Connext headers (`#include <rti/rti.hpp>`)
  4. Third-party headers (`#include <nlohmann/json.hpp>`)
  5. Standard library headers (`#include <vector>`)
- Each group is sorted alphabetically.

### Const Correctness

- Mark every variable, parameter, and member function `const` unless
  mutation is required.
- Prefer `const auto&` for loop variables over undecorated copies.
- Member functions that do not modify state are `const`.
- Pass non-trivial types by `const&`. Pass cheap-to-copy types
  (`int`, `double`, `bool`, `string_view`) by value.

### Modern C++17 Idioms

- Prefer `std::optional` over sentinel values or output parameters.
- Prefer `std::string_view` for non-owning string parameters.
- Prefer structured bindings (`auto [key, value] = ...`) where they
  improve clarity.
- Prefer `if constexpr` over SFINAE for compile-time branching.
- Use `[[nodiscard]]` on functions whose return value must not be
  silently ignored (especially factory functions and error-returning
  functions).
- Do not use `std::any` or `std::variant` unless the design requires
  type erasure.
- No raw `new`/`delete`. Use `std::unique_ptr` or `std::shared_ptr`
  for heap allocations. Prefer stack allocation.

### Error Handling

- No exceptions across module boundaries. Connext APIs may throw;
  catch at the call site and convert to a return value or log entry.
- Within a module, exceptions are permitted for truly exceptional
  conditions (resource exhaustion, programmer errors). Normal control
  flow must not use exceptions.
- Use the RTI Connext Logging API (`rti::config::Logger`) for all error reporting — never
  `std::cerr` or `std::cout`.

### Connext Modern C++ API Conventions

The Modern C++ API has its own conventions that application code must
respect. These are defined by RTI and are **not project choices** — they
are inherent to the API. Reference: [Connext Modern C++ API Conventions](https://community.rti.com/static/documentation/connext-dds/current/doc/api/connext_dds/api_cpp2/group__DDSCpp2Conventions.html).

#### No Listeners for Data Processing

**Never use `DataReaderListener::on_data_available()` (or any listener
callback) for sample processing.** Listener callbacks execute on the
middleware's internal receive thread, which is shared across all
DataReaders in the participant. Blocking or slow processing in a
listener starves other DataReaders of receive-thread time, causing
latency spikes, sample loss, or deadline misses.

Use one of these patterns instead:

| Pattern | Language | When to use |
|---------|----------|-------------|
| `AsyncWaitSet` + `ReadCondition` | C++ | **Preferred.** When multiple conditions (data available, status changes, guards) must be dispatched together, or when custom read logic (filtering, batching) is needed. Supports `GuardCondition` for application-driven events (e.g., periodic publish ticks). |
| `rti::sub::SampleProcessor` | C++ only | Convenience wrapper for per-sample callbacks on an internal `AsyncWaitSet`. Suitable only for simple, independent-per-reader processing where samples do not share mutable state. **Experimental in Connext 7.6.0** — do not use for safety-critical or latency-sensitive paths. |
| `async`/`await` with `rti.connext` async APIs | Python | All Python data processing — integrates with asyncio and QtAsyncio. |
| Polling `read()`/`take()` | Both | When data should be processed at a fixed frequency or on specific application events rather than on arrival. |

#### `AsyncWaitSet` Isolation Principle

Each critical-path I/O context with an independent jitter budget must
get its own `AsyncWaitSet` instance (thread pool size = 1). Do not
combine high-rate publishers and subscribers on the same `AsyncWaitSet`
when either side has a strict timing requirement — a burst of
data-available events on the subscriber side can delay the publisher
(and vice versa).

**Rule of thumb:** if two I/O activities have independent timing
constraints (e.g., a 100 Hz fixed-rate publisher vs. a 500 Hz
data-driven subscriber), separate them into distinct `AsyncWaitSet`
instances. Protect any shared mutable state between the two threads
with a lightweight read-write lock.

I/O contexts that share a timing model — such as multiple readers whose
samples update the same state and are processed cooperatively — may
share a single `AsyncWaitSet` (single-threaded for lock-free access).

**Do not use listeners at all** — including for non-data entity status
callbacks (`on_subscription_matched`, `on_liveliness_changed`, etc.).
All status change handling must use a `StatusCondition` for the
corresponding entity, attached to an `AsyncWaitSet`. This keeps all
event dispatch on async threads and completely avoids the middleware
receive thread.

#### Type System: Value Types vs Reference Types

The API has two fundamental type categories:

- **Value types** — deep-copy semantics. IDL-generated types (`struct`,
  `enum class`) are value types. They support copy, move, equality,
  and `swap()`. Treat them like regular C++ data objects.
- **Reference types** — shared-pointer semantics. DDS entities
  (`DomainParticipant`, `Publisher`, `Subscriber`, `DataWriter`,
  `DataReader`, `Topic`) are reference types. Copying a reference does
  not copy the entity — it creates another handle to the same object.

```cpp
// Value type: copies are independent
Surgery::RobotCommand cmd1;
cmd1.sequence_number = 1;
auto cmd2 = cmd1;            // deep copy — cmd2 is independent
cmd2.sequence_number = 2;    // cmd1 is still 1

// Reference type: copies share the same entity
dds::domain::DomainParticipant p1(domain_id);
auto p2 = p1;                // p2 references the SAME participant
// When the last reference goes out of scope, the entity is destroyed
```

#### No DynamicData in Applications

**Never use `DynamicData` or `DynamicType` in application code.** All
applications — publishers, subscribers, GUIs, services — must use the
IDL-generated types produced by `rtiddsgen`. Generated types provide
compile-time safety (C++) and IDE-discoverable field access (Python),
and they match the type definitions under `interfaces/idl/` exactly.

DynamicData is permitted **only** in developer tools (e.g.,
`tools/qos-checker.py`) and standalone test utilities where
type-agnostic introspection is the explicit goal. Integration tests
that exercise DDS behaviors (partition isolation, QoS enforcement,
etc.) must use the project's generated types.

#### Entity Lifecycle

Reference-type entities are destroyed when the last reference to them
goes out of scope — unless explicitly `retain()`ed or `close()`d:

- **`close()`** — immediately destroys the underlying entity regardless
  of other references. Subsequent calls on any reference throw
  `dds::core::AlreadyClosedError`.
- **`nullptr` assignment** — releases one reference. If it was the last,
  the entity is destroyed.
- **`retain()`** — prevents automatic destruction when all references go
  out of scope. The entity must later be `close()`d explicitly.

In this project, prefer **scope-based lifecycle** (let references go out
of scope naturally) over explicit `close()` or `retain()`. Use `close()`
only when deterministic shutdown ordering is required.

#### Standard vs Extension APIs

The API is split across two namespace families:

| Namespace | Contains | Call pattern |
|-----------|----------|-------------|
| `dds::` | OMG DDS standard API | `entity.method()` |
| `rti::` | RTI Connext extensions | `entity->method()` or `entity.extensions().method()` |

```cpp
// Standard API — dot operator
participant.assert_liveliness();

// Extension API — arrow operator (preferred) or .extensions()
participant->register_durable_subscription(...);
```

Extension types (e.g., `rti::pub::FlowController`,
`rti::core::cond::AsyncWaitSet`) live entirely in the `rti::`
namespace and use the normal dot operator — the arrow pattern is only
for calling RTI extensions on standard `dds::` types.

#### Exceptions and `noexcept` Variants

The Modern C++ API throws exceptions by default (any of the
[standard DDS exceptions](https://community.rti.com/static/documentation/connext-dds/current/doc/api/connext_dds/api_cpp2/group__DDSException.html)).
For performance-critical read paths, the API provides `_noexcept`
variants that return `rti::core::Result` instead:

```cpp
// Exception-throwing (default — use in most application code):
auto samples = reader.take();

// noexcept variant (use only in hot paths where exception
// overhead is measurable):
auto result = reader->take_noexcept();
if (result.is_ok()) {
    auto& samples = result.get();
}
```

In this project, use the **exception-throwing variants by default**.
The `_noexcept` variants are permitted only in the `control`-tag data
path where latency is safety-critical, and only if profiling
demonstrates measurable exception overhead.

---

## Python Conventions

### Naming

| Element | Style | Example |
|---------|-------|---------|
| Module / file | `snake_case` | `procedure_publisher.py` |
| Package / directory | `snake_case` | `surgical_procedure/` |
| Class | `PascalCase` | `ProcedurePublisher`, `VitalsReader` |
| Function / method | `snake_case` | `start_procedure()`, `on_data_available()` |
| Variable (local, instance) | `snake_case` | `sample_count`, `room_id` |
| Private member | `_snake_case` (leading underscore) | `_participant`, `_writer` |
| Constant (module-level) | `ALL_CAPS` | `MAX_RETRIES`, `DEFAULT_DOMAIN_ID` |
| Type variable | `PascalCase` | `T`, `DataType` |

### PEP 8 Compliance

PEP 8 is mandatory with these project-specific clarifications:

- **Line length:** 88 characters (Black default). This aligns with the
  project's use of modern monitor widths while staying narrower than the
  100-character markdown limit.
- **Formatter:** Code must be formatted with **Black** (version pinned in
  `requirements.txt`). No manual formatting overrides.
- **Import sorter:** **isort** with Black-compatible profile
  (`profile = "black"` in `pyproject.toml`).
- **Linter:** **Ruff** for fast lint checks (pinned in `requirements.txt`).

### Type Hints

All function signatures must include type annotations. This includes:

- Parameter types
- Return types (use `-> None` explicitly for procedures)
- Class attributes defined in `__init__`

```python
def compute_hemorrhage_risk(
    heart_rate: float,
    systolic_bp: float,
) -> float:
    ...

class ProcedurePublisher:
    def __init__(self, participant: dds.DomainParticipant) -> None:
        self._writer: dds.DataWriter = ...
```

Use `from __future__ import annotations` at the top of every module to
enable PEP 604 union syntax (`X | None`) and forward references without
runtime cost.

### Import Order

Separated by blank lines, sorted alphabetically within each group:

1. `from __future__ import annotations`
2. Standard library (`import asyncio`, `from pathlib import Path`)
3. Third-party (`import rti.connext as dds`, `from PySide6.QtWidgets import ...`)
4. Project (`from medtech_gui import init_theme`)

### Docstrings

- All public classes and functions must have a docstring.
- Use **Google style** docstrings:

```python
def start_procedure(room_id: str, procedure_id: str) -> bool:
    """Start a surgical procedure in the given room.

    Args:
        room_id: Operating room identifier (e.g., "OR-3").
        procedure_id: Unique procedure identifier.

    Returns:
        True if the procedure was started successfully.

    Raises:
        ValueError: If room_id is empty.
    """
```

- Private functions (`_helper()`) do not require docstrings unless the
  logic is non-obvious.

### Class Design

- Use `dataclasses.dataclass` for plain-data types with no behavior beyond
  initialization and equality.
- Use regular classes when the type manages resources, maintains invariants,
  or has non-trivial lifecycle.
- Use `typing.NamedTuple` for immutable value types returned from functions.
- Avoid inheritance unless the framework requires it (e.g., `QWidget`
  subclasses). Prefer composition.
- **DDS service classes** must implement `medtech.Service` (the project's
  abstract base class) — see [dds-consistency.md — Service Interface](dds-consistency.md)
  for the interface definition, `ServiceState` enum, and lifecycle rules.

---

## Shared Conventions (Both Languages)

### Naming Alignment with Generated Code

Both C++ and Python types are **generated from IDL by `rtiddsgen`** — the
code generator is run as part of the CMake build (see
[technology.md](technology.md)). Agents never hand-write or manually
implement IDL-to-language translations. The examples below exist solely so
agents understand the naming patterns and access styles they will encounter
when *consuming* generated types in application code.

#### IDL → Modern C++ (generated by `rtiddsgen -language C++11 -standard IDL4_CPP`)

IDL `module` → C++ `namespace`. IDL `struct` → C++ `struct` with
**public data members** accessed directly (not through getters/setters).
IDL `enum` → `enum class`. The `-standard IDL4_CPP` flag produces the
newer IDL4 convention — this is distinct from the legacy PSM convention
which generated `class` types with getter/setter accessors. Reference:
[Foo.hpp example (IDL4 convention)](https://community.rti.com/static/documentation/connext-dds/current/doc/api/connext_dds/api_cpp2/Foo_8hpp-example.html).

```cpp
// IDL: module Surgery { struct RobotCommand { int32 sequence_number; string<64> target_id; }; };
//
// What rtiddsgen produces (do NOT write this yourself):
namespace Surgery {
    struct RobotCommand {
        int32_t sequence_number {};
        std::string target_id {};

        RobotCommand();
        RobotCommand(int32_t sequence_number_, const ::omg::types::string_view& target_id_);
    };
}

// What application code looks like when USING the generated type:
Surgery::RobotCommand cmd;
cmd.sequence_number = 42;
cmd.target_id = "arm-1";
writer.write(cmd);

// Or using the constructor:
auto cmd2 = Surgery::RobotCommand(42, "arm-1");
```

> **IDL `union` is the exception.** Unions still generate a `class` with
> getter/setter accessors because the discriminator must be validated on
> each member access. Application code uses `my_union.my_member()` and
> `my_union.my_member(value)` for union branches.

#### IDL → Python (generated by `rtiddsgen -language Python`)

IDL `module` → Python namespace class inside the generated module file.
IDL `struct` → `@idl.struct`-decorated dataclass nested under the module class.
IDL `enum` → `@idl.enum` class extending `IntEnum`.
Access pattern: `<generated_file>.<IDL_module>.<Type>` (e.g., `surgery.Surgery.RobotCommand`).
Reference: [RTI IDL Type Translations — Python](https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/connext_dds_professional/users_manual/users_manual/Translations_for_IDL_Types.htm#DataTypes_Python).

```python
# IDL: module Surgery { struct RobotCommand { int32 sequence_number; string<64> target_id; }; };
#
# What rtiddsgen produces in surgery.py (do NOT write this yourself):
class Surgery:
    @idl.struct(
        member_annotations={
            "target_id": [idl.bound(64)],
        }
    )
    class RobotCommand:
        sequence_number: idl.int32 = 0
        target_id: str = ""

# What application code looks like when USING the generated type:
import surgery

cmd = surgery.Surgery.RobotCommand(sequence_number=42, target_id="arm-1")
writer.write(cmd)

# Optional: create a local alias for a frequently used type
RobotCommand = surgery.Surgery.RobotCommand
cmd2 = RobotCommand(sequence_number=43, target_id="arm-2")
```

#### Application Wrapper Naming

Application-level wrappers use each language's native naming conventions
but must clearly indicate which generated DDS type they operate on:

| Layer | C++ | Python |
|-------|-----|--------|
| Generated type | `Surgery::RobotCommand` (struct, public members) | `surgery.Surgery.RobotCommand` (`@idl.struct` dataclass) |
| Generated enum | `Surgery::ProcedurePhase` (`enum class`) | `surgery.Surgery.ProcedurePhase` (`@idl.enum`, `IntEnum`) |
| Application wrapper | `medtech::surgical::CommandPublisher` | `surgical_procedure.command_publisher.CommandPublisher` |

Application wrappers use each language's native naming style. The generated
types are used as-is — never aliased, re-wrapped, or renamed in
application code.

### DDS Code Separation

RTI Connext API usage should be **visibly separated** from other
operational code (GUI logic, application state machines, business rules)
within each module. This separation serves two purposes: it improves
readability for developers unfamiliar with DDS, and it makes the Connext
integration clearly demonstrable. Apply this when the module is complex
enough to benefit — trivial glue code does not need forced separation.

In practice:

- **Dedicated DDS classes or files.** Encapsulate DDS entity creation,
  reading, and writing in purpose-built classes (e.g.,
  `CommandPublisher`, `VitalsReader`, `ProcedureStatusWriter`) rather
  than scattering `DataWriter` and `DataReader` calls throughout GUI
  handlers or state machine transitions.
- **Thin DDS boundary.** The DDS layer exposes a domain-meaningful
  interface to the rest of the module (e.g., `publish_command(cmd)`,
  `on_vitals_received(callback)`) — not raw Connext types or entities.
  Application code interacts with this interface, not directly with
  `DataWriter` or `DataReader`.
- **Clear import/include separation.** Files that contain DDS logic
  import Connext headers/modules (`#include <rti/rti.hpp>`,
  `import rti.connext`). Files that contain GUI or business logic
  should not — they interact with the DDS layer through the module's
  own interface.

This does **not** mean a rigid multi-layer architecture is required for
every module. A small module may have a single file where the DDS setup
is in one section and the application logic in another. The goal is that
someone reading the code can quickly identify "this is the DDS part"
versus "this is the application logic."

### File Organization Within a Module

```
modules/<module-name>/
├── CMakeLists.txt
├── README.md                          # Required (vision/documentation.md)
├── include/medtech/<module>/          # C++ public headers (.hpp)
│   ├── <class_name>.hpp
│   └── ...
├── src/                               # C++ implementation (.cpp)
│   ├── <class_name>.cpp
│   ├── main.cpp                       # Host entry point (standalone mode)
│   └── ...
├── python/                            # Python source
│   └── <package_name>/
│       ├── __init__.py
│       ├── <module_file>.py
│       └── ...
└── tests/                             # Module-level tests
    ├── test_<feature>.py              # Python tests (pytest)
    └── test_<feature>.cpp             # C++ tests (Google Test)
```

- **One class per file** for primary classes. Small helper types may share
  a file with their primary class.
- **File names match the primary type** they define:
  `ProcedureManager` → `procedure_manager.hpp` / `procedure_manager.cpp`.
- **Test files mirror source files:** `procedure_manager.cpp` →
  `test_procedure_manager.cpp`.

### Comments

- Prefer self-documenting code (clear names, small functions) over comments
  that restate the code.
- Use comments to explain **why**, not **what**. If a design choice is
  non-obvious (e.g., a particular QoS interaction, a threading constraint,
  a workaround for a Connext behavior), document the reason.
- Do not add `TODO` comments unless they reference a specific phase/step
  (e.g., `// TODO(phase-3/step-3.2): add content filter`). Free-floating
  TODOs become permanent noise.
- Do not add commented-out code. Dead code is deleted, not commented.

### Magic Numbers

No magic numbers in application code. All constants are:
- **C++:** `constexpr` or `const` at namespace scope, or IDL `const` values
  from generated code.
- **Python:** Module-level `ALL_CAPS` constants, or IDL constants imported
  from generated modules.

Domain IDs, partition strings, topic names, and QoS profile names are
**never** literals in application code — they come from XML configuration
per [vision/data-model.md](data-model.md) System Contract #7.

---

## CMake Conventions

| Element | Style | Example |
|---------|-------|---------|
| Variable (project) | `ALL_CAPS` | `CONNEXT_VERSION`, `CONNEXTDDS_ARCH`, `BUILD_SHARED_LIBS` |
| Function / macro (project) | `snake_case` | `add_medtech_executable()` |
| Target name | `snake_case` with module prefix | `surgical_procedure`, `hospital_dashboard` |
| Option | `ALL_CAPS` with project prefix | `MEDTECH_BUILD_TESTS` |

- Prefer **functions** over macros (functions have their own scope).
- Use `target_*` commands — never set global `CMAKE_*` variables in
  subdirectory `CMakeLists.txt` files. Global settings belong only in
  the top-level `CMakeLists.txt`.
- Use generator expressions for conditional logic (`$<CONFIG:Release>`)
  rather than `if()` blocks where possible.

---

## Test Code Conventions

### Python (pytest)

| Element | Convention |
|---------|-----------|
| Test file | `test_<feature>.py` |
| Test function | `test_<what_it_verifies>` |
| Fixture | `snake_case`, defined in `conftest.py` |
| Parametrize IDs | Descriptive (`@pytest.mark.parametrize("vitals", [...], ids=["normal", "critical"])`) |
| Assertion style | Plain `assert` (pytest introspection handles the rest) |
| Spec tag mapping | `@pytest.mark.<tag>` matches spec tags (e.g., `@pytest.mark.integration`) |

### C++ (Google Test)

| Element | Convention |
|---------|-----------|
| Test file | `test_<feature>.cpp` |
| Test suite | `PascalCase` matching the class under test | `ProcedureManagerTest` |
| Test case | `PascalCase` describing the behavior | `TEST_F(ProcedureManagerTest, RejectsInvalidRoomId)` |
| Fixture class | `<ClassUnderTest>Test` | `class ProcedureManagerTest : public ::testing::Test` |
| Assertion | `EXPECT_*` for non-fatal, `ASSERT_*` only when subsequent assertions depend on the result |

### Shared Test Principles

- Tests are **deterministic**. No random data, no time-dependent assertions
  (use fakes/mocks for timing), no network calls to external services.
- Tests are **independent**. Test order must not matter. Each test sets up
  its own state via fixtures.
- Tests do not test generated code or Connext internals — only project
  application logic and its integration with DDS.
- Test helpers and factories live in `conftest.py` (Python) or a `testing/`
  support directory (C++), not inline in test files.

### Integration Test Timing Patterns (Python)

DDS integration tests must **never** use `time.sleep()` to wait for
discovery or data delivery. Use the appropriate DDS blocking primitive
instead. `time.sleep()` is permitted only for negative-proof assertions
(see below).

#### Discovery Waits

Use `StatusCondition` with `SUBSCRIPTION_MATCHED` or
`PUBLICATION_MATCHED` and a `WaitSet`:

```python
from conftest import wait_for_discovery, wait_for_reader_match

# When you have both writer and reader:
wait_for_discovery(writer, reader, timeout_sec=5.0)

# When writing against a service (writer is encapsulated):
wait_for_reader_match(reader, timeout_sec=5.0)
```

Do not use `time.sleep()` for discovery — it adds 20× more delay than
necessary on localhost.

#### Data Delivery Waits

Use `StatusCondition(DATA_AVAILABLE)` + `WaitSet`:

```python
from conftest import wait_for_data

samples = wait_for_data(reader, timeout_sec=5.0, count=1)
```

#### TRANSIENT_LOCAL Late-Joiner Reads

Use `DataReader.wait_for_historical_data()`:

```python
reader.wait_for_historical_data(dds.Duration(5))
samples = reader.take()
```

This blocks until cached historical samples have been delivered by the
matched writer.

#### Reliable Write-Then-Read

Use `DataWriter.wait_for_acknowledgments()` after writing, before the
reader takes:

```python
writer.write(sample)
writer.wait_for_acknowledgments(dds.Duration(5))
received = reader.take()
```

#### Subprocess / Service Host Readiness

When a fixture launches a subprocess that creates DDS entities, do not
use `time.sleep()`. Instead, create a probe reader on the subprocess's
topic and wait for discovery + historical data:

```python
probe = dds.DynamicData.DataReader(participant, topic, reader_qos)
wait_for_reader_match(probe, timeout_sec=10.0)
probe.wait_for_historical_data(dds.Duration(5))
probe.close()
```

#### Negative-Proof Assertions (Non-Delivery)

The only acceptable use of `time.sleep()` in integration tests is for
negative proofs — verifying that data does **not** arrive on an
isolated reader (e.g., cross-domain or cross-partition isolation).
Use `time.sleep(0.5)`. Do not exceed 1 second unless testing a
time-dependent QoS such as lifespan expiry.

```python
time.sleep(0.5)
assert len(isolated_reader.take()) == 0, "Data leaked across domains"
```

#### Parallel Execution (pytest-xdist)

The test suite runs in parallel via `pytest-xdist` with
`--dist loadgroup`. Tests that share DDS domain 15 (orchestration)
must be grouped:

```python
pytestmark = [
    pytest.mark.integration,
    pytest.mark.xdist_group("orch"),
]
```

Domain 10 tests are safe for parallel execution because domain tags
(`clinical`, `operational`, `control`) provide partition-level
isolation. Tests on domain 0 or unique domains are also safe.

---

## Enforcement

These conventions are enforced through the quality gates in
[workflow.md](../workflow.md) Section 7 and the CI pipeline defined in
[phase-1-foundation.md](../implementation/phase-1-foundation.md) Step 1.8:

| Convention | Enforcement mechanism |
|------------|----------------------|
| Python formatting (Black) | CI step: `black --check .` |
| Python imports (isort) | CI step: `isort --check .` |
| Python linting (Ruff) | CI step: `ruff check .` |
| Python type hints | CI step: `mypy` or inline review (see note below) |
| C++ naming / style | Code review by operator; enforced by convention |
| Markdown | CI step: `markdownlint` (existing gate) |
| No magic numbers / no raw QoS | CI step: `grep` checks (existing gate) |

> **Note on mypy:** Full `mypy --strict` is a stretch goal. The minimum
> requirement is that all function signatures have type annotations. Agents
> must not introduce `# type: ignore` comments unless the suppression is
> justified by a comment explaining the cause (e.g., a Connext API type
> stub gap).
