# Technology Stack

## Middleware

| Component | Version | Location |
|-----------|---------|----------|
| RTI Connext DDS Professional | 7.6.0 | `/opt/rti.com/rti_connext_dds-7.6.0` |
| RTI Connext Python (`rti.connext`) | 7.6.0 | Installed via pip in project venv |

### Connext Version Management

The Connext version (`7.6.0`) is a project-wide constant that must be defined in **exactly one place per integration layer**, making a version bump a minimal, auditable change:

| Integration Layer | Single Source of Truth | Consumers |
|-------------------|----------------------|------------|
| CMake | `CONNEXT_VERSION` variable in top-level `CMakeLists.txt` | `find_package(RTIConnextDDS "${CONNEXT_VERSION}" ...)`, rtiddsgen calls |
| Python | `rti.connext==${version}` line in `requirements.txt` | `pip install -r requirements.txt` |
| Docker | `ARG CONNEXT_VERSION=7.6.0` in each base Dockerfile | `COPY` paths, `ENV NDDSHOME`, `pip install` |
| QoS XML | `xsi:noNamespaceSchemaLocation` URL in each XML root element | XSD validation |
| Connext env script | `$NDDSHOME/resource/scripts/rtisetenv_<arch>.bash` | `$NDDSHOME` is set by the install, not the version string |

#### Migration Checklist (non-breaking version bump)

When upgrading Connext (e.g., 7.6.0 → 7.7.0) with no breaking API changes:

1. **CMakeLists.txt** — update `set(CONNEXT_VERSION "7.7.0")` (one line)
2. **requirements.txt** — update `rti.connext==7.7.0` (one line)
3. **Dockerfiles** — update `ARG CONNEXT_VERSION=7.7.0` in each base image (three files, one line each)
4. **QoS/domain XML** — update the XSD URL version in `xsi:noNamespaceSchemaLocation` (one `sed` across all XML files)
5. **Connext architecture string** — if the target architecture name changes (e.g., `x64Linux4gcc8.5.0` → `x64Linux4gcc12.3.0`), update it in `CONNEXT_ARCH` in CMakeLists.txt and in the Dockerfile `rtisetenv` invocation
6. **Validate** — run the full test suite, QoS XML XSD validation, and Docker build
7. **Review RTI migration guide** — check the [RTI Connext Migration Guide](https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/migration_guide/index.html) for any behavioral changes, deprecated APIs, or QoS default changes

#### Design Constraints for Migration Safety

- **No hardcoded version strings in application code.** The version `7.6.0` must never appear in `.cpp`, `.py`, or `.hpp` files. It exists only in build/config files listed above.
- **`find_package` uses the CMake variable.** `find_package(RTIConnextDDS "${CONNEXT_VERSION}" ...)` — never a literal string.
- **Python pin uses `==`, not `>=`.** Exact pinning prevents silent upgrades and makes the bump explicit.
- **Docker images use `ARG` for the version.** All `COPY` paths and `ENV` values that reference the Connext install path derive from the `ARG`, not hardcoded paths.
- **QoS XML schema URL is the only version reference in XML.** No other element in QoS or domain XML is version-specific.
- **The architecture string is parameterized in CMake.** A `CONNEXT_ARCH` cache variable (defaulting to `x64Linux4gcc8.5.0`) is used wherever the architecture name appears in build logic, so a toolchain change is a single variable update.

This design ensures that a non-breaking Connext version bump touches at most **5 files** and **~6 lines of configuration** — no application code, no QoS tuning, no IDL changes.

## Languages

| Language | Standard | Use |
|----------|----------|-----|
| C++ | C++17 | Terminal/background/service applications, Routing Service plugins, performance-critical data paths |
| Python | 3.10+ | GUI applications, simulators, test harnesses |

## GUI Framework

- **PySide6** — Qt 6 bindings for Python
- **QtAsyncio** — used for integrating async DDS reads with the Qt event loop
- DDS I/O must never occur on the main/UI thread (see DDS I/O Threading below)

### GUI Design Standard

All GUI applications (Hospital Dashboard, Digital Twin Display, and any future GUIs) must share a consistent visual identity built on the RTI brand guidelines.

#### Color Palette

**Primary colors** — used for the majority of UI surfaces:

| Name | Hex | RGB | Usage |
|------|-----|-----|-------|
| RTI Blue | `#004C97` | 0 / 76 / 151 | Window title bars, primary action buttons, sidebar backgrounds, selected-row highlight |
| RTI Orange | `#ED8B00` | 237 / 139 / 0 | Warning indicators, accent buttons, call-to-action elements |
| RTI Gray | `#63666A` | 99 / 102 / 106 | Secondary text, borders, disabled controls, neutral status |

**Secondary colors** — used in conjunction with primary colors, never as standalone dominant colors:

| Name | Hex | RGB | Usage |
|------|-----|-----|-------|
| RTI Light Blue | `#00B5E2` | 0 / 181 / 226 | Info badges, link text, hover highlights, streaming-data sparklines |
| RTI Light Orange | `#FFA300` | 255 / 163 / 0 | Elevated-warning indicators, pending-state badges |
| RTI Green | `#A4D65E` | 164 / 214 / 94 | Normal/healthy status, operational mode indicators, successful actions |
| RTI Light Gray | `#BBBCBC` | 187 / 188 / 188 | Panel backgrounds, dividers, placeholder text, disabled backgrounds |

**Semantic mapping for clinical severity:**

| Severity | Color | Hex |
|----------|-------|-----|
| Normal / Operational | RTI Green | `#A4D65E` |
| Warning / Caution | RTI Orange | `#ED8B00` |
| Critical / E-STOP / Alarm | Red (standard) | `#D32F2F` |
| Info / Nominal | RTI Light Blue | `#00B5E2` |
| Disconnected / Unknown | RTI Light Gray | `#BBBCBC` |

A dedicated red (`#D32F2F`) is used for critical/alarm states — not part of the RTI palette, but required for immediate clinical visual distinction.

#### Typography

All GUI applications use the RTI web typography stack:

| Role | Font Family | Fallback |
|------|-------------|----------|
| Headlines, panel titles, status labels | **Roboto Condensed** | sans-serif |
| Body text, data values, table content | **Montserrat** | sans-serif |
| Monospace (log output, raw DDS data) | **Roboto Mono** | monospace |

Fonts are bundled as application resources (`.ttf` files under `resources/fonts/`) and loaded at startup via `QFontDatabase`. No system font dependency.

#### Branding

- The **RTI logo** is displayed in the application title bar or header region of every GUI window
- Logo asset is stored at `resources/images/rti-logo.png` (and `rti-logo.svg` for scalable contexts)
- The logo appears left-aligned in the header, sized proportionally to the header height
- A "Powered by RTI Connext" tagline may appear in the status bar or about dialog

#### Layout Conventions

- **Dark header bar** — RTI Blue (`#004C97`) background with white text and RTI logo
- **Light content area** — white or near-white background for data panels
- **Sidebar navigation** (where applicable) — RTI Blue background, white text, RTI Light Blue hover
- **Status bar** — bottom of window, RTI Gray background, shows connection state and DDS participant health
- All panels use consistent padding (8 px), border radius (4 px), and RTI Light Gray dividers
- Color-coded status indicators use the semantic severity mapping above

#### Stylesheets

A shared Qt stylesheet (`resources/styles/medtech.qss`) defines the common theme. All GUI applications load this stylesheet at startup. Module-specific overrides are permitted but must not conflict with the base theme colors or typography.

#### Shared GUI Bootstrap

All PySide6 applications share a common initialization sequence: load the `.qss` stylesheet, register bundled fonts via `QFontDatabase`, and place the RTI logo in the header bar. To avoid duplicating this boilerplate, a shared Python utility module (`medtech_gui`) is installed to `lib/python/site-packages/`. It exposes a single entry point:

```python
from medtech_gui import init_theme

app = QApplication(sys.argv)
init_theme(app)  # loads medtech.qss, registers fonts, returns header widget
```

Each GUI module calls `init_theme(app)` once at startup. Module-specific styling is applied afterward.

## Build System

### Connext Environment

Before configuring CMake, the Connext environment must be sourced:

```bash
source $NDDSHOME/resource/scripts/rtisetenv_x64Linux4gcc8.5.0.bash
```

This sets `NDDSHOME`, `PATH`, `LD_LIBRARY_PATH`, and other variables required by `find_package(RTIConnextDDS ...)`. All build and run instructions assume this has been done.

### Platform Support

All current development, CI, Docker images, and runtime scripts target **Linux x86-64** (`x64Linux4gcc8.5.0`). Platform-specific artifacts include:

| Artifact | Linux-specific aspect |
|----------|----------------------|
| `setup.bash` | Bash syntax, `LD_LIBRARY_PATH`, `source` activation |
| `rtisetenv_x64Linux4gcc8.5.0.bash` | Architecture-specific Connext env script |
| Docker base images | Ubuntu 22.04 |
| `NDDS_QOS_PROFILES` separator | `;` (same on all platforms, no issue) |
| Shared library extension | `.so` |

The core CMake build system, IDL definitions, QoS XML, and application source code are **platform-neutral by design**. Cross-platform support is planned for a future milestone and will require:

- `setup.bash` → equivalent `setup.ps1` (Windows) and `setup.zsh` (macOS)
- Connext architecture selection parameterized (not hardcoded to `x64Linux4gcc8.5.0`)
- Docker alternatives or native build instructions for non-Linux hosts
- Platform-specific transport configuration profiles in `Participants.xml` (e.g., shared memory path differences, loopback interface names)
- QNX cross-compilation toolchain file for CMake
- CI matrix expanded to cover target platforms

For platforms that require cross-compilation (e.g., QNX), a CMake toolchain file must be provided under `cmake/toolchains/`. The toolchain file sets `CMAKE_SYSTEM_NAME`, `CMAKE_C_COMPILER`, `CMAKE_CXX_COMPILER`, and any platform-specific flags. Cross-compilation is invoked by passing the toolchain file at configure time:

```bash
cmake -B build-qnx -S . -DCMAKE_TOOLCHAIN_FILE=cmake/toolchains/qnx-aarch64.cmake
```

The project's `CMakeLists.txt` must not assume the host and target are the same platform. All platform-detection logic must use `CMAKE_SYSTEM_NAME` (not `CMAKE_HOST_SYSTEM_NAME`), and Python-only targets must be excluded from cross-compilation builds where the target cannot run Python.

Until that milestone, agents must not introduce platform-specific assumptions beyond those already documented here. All application code, IDL, and QoS XML must remain portable.

### CMake (unified build)

All C++ and Python components are built through a single CMake project. Python sources are not "compiled" but are installed/staged by CMake targets so that a single `cmake --build` produces the complete suite.

### RTI CMake Utilities

[rticonnextdds-cmake-utils](https://github.com/rticommunity/rticonnextdds-cmake-utils) is included via `FetchContent` (main branch):

```cmake
include(FetchContent)
FetchContent_Declare(
    rticonnextdds-cmake-utils
    GIT_REPOSITORY https://github.com/rticommunity/rticonnextdds-cmake-utils.git
    GIT_TAG        main
)
FetchContent_MakeAvailable(rticonnextdds-cmake-utils)

list(APPEND CMAKE_MODULE_PATH
    "${rticonnextdds-cmake-utils_SOURCE_DIR}/cmake/Modules")

find_package(RTIConnextDDS "${CONNEXT_VERSION}" REQUIRED)
```

This provides:
- `find_package(RTIConnextDDS ...)` — locates Connext installation; version comes from the `CONNEXT_VERSION` cache variable
- `connextdds_rtiddsgen_run(...)` — code generation from IDL files
- Standard CMake targets for linking Connext libraries

### Default Build Configuration

The top-level `CMakeLists.txt` must set these defaults:

```cmake
# --- Connext version and architecture (single source of truth) ---
set(CONNEXT_VERSION "7.6.0" CACHE STRING "RTI Connext DDS version")
set(CONNEXT_ARCH "x64Linux4gcc8.5.0" CACHE STRING "RTI Connext target architecture")

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

if(CMAKE_INSTALL_PREFIX_INITIALIZED_TO_DEFAULT)
    set_property(CACHE CMAKE_INSTALL_PREFIX
        PROPERTY VALUE "${CMAKE_CURRENT_SOURCE_DIR}/install")
endif()

option(BUILD_SHARED_LIBS "Build shared libraries" ON)
```

The `find_package` call references the version variable:

```cmake
find_package(RTIConnextDDS "${CONNEXT_VERSION}" REQUIRED)
```

- **`CONNEXT_VERSION`** — single CMake variable controlling the required Connext version. All `find_package` calls and version-dependent logic reference this variable, never a literal.
- **`CONNEXT_ARCH`** — single CMake variable for the Connext target architecture. Used in `rtisetenv` script paths, Docker build args, and any architecture-dependent logic. Defaults to `x64Linux4gcc8.5.0` for the current Linux target.
- **C++17** — required minimum. Do not use C++20 features.
- **Release** — default build type. Debug builds are used only for targeted troubleshooting.
- **Shared libraries** — default linkage. Connext ships shared libraries for the target architecture; static linking is not used unless explicitly required by a deployment constraint.
- **Install prefix** — defaults to `<source>/install/` when the user has not explicitly set `CMAKE_INSTALL_PREFIX`. Users who want to install elsewhere pass `-DCMAKE_INSTALL_PREFIX=<path>` explicitly.

C++ targets must link against the `RTIConnextDDS::cpp2_api` imported target (the Modern C++ API). Do not link against lower-level C targets directly.

`connextdds_rtiddsgen_run` is invoked for both `C++11` (with `-standard IDL4_CPP`) and `Python` language targets. Generated output files must mirror the IDL source directory structure so that `#include` and `import` paths are consistent with the IDL file paths:

```
interfaces/idl/surgery/surgery.idl
  → <build>/generated/cpp/surgery/surgery.hpp     (C++11)
  → <build>/generated/python/surgery/surgery.py   (Python)
```

Generated output is written into the CMake build directory, not the source tree. The source tree is kept clean; `generated/` is never committed to version control.

#### Python Generated Type Packaging

The CMake build generates Python type-support modules via `rtiddsgen -language Python`. These must be installed as importable Python packages without placing generated code in the source tree.

**Build time:** `rtiddsgen` outputs one `.py` file per IDL file into `<build>/generated/python/<module>/`. CMake generates an `__init__.py` in each module directory to create valid Python packages:

```cmake
# For each IDL module directory, generate an __init__.py alongside the rtiddsgen output
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/generated/python/surgery/__init__.py" "")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/generated/python/monitoring/__init__.py" "")
# ... etc. for each IDL module
```

**Install time:** `cmake --install` copies the generated Python tree into `lib/python/site-packages/`, preserving the directory structure:

```cmake
install(DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/generated/python/
        DESTINATION lib/python/site-packages
        FILES_MATCHING PATTERN "*.py")
```

The installed layout:

```
install/lib/python/site-packages/
├── common/
│   ├── __init__.py
│   └── common.py           # Common::Time_t, Common::EntityIdentity, etc.
├── surgery/
│   ├── __init__.py
│   └── surgery.py          # Surgery::RobotCommand, Surgery::RobotState, etc.
├── monitoring/
│   ├── __init__.py
│   └── monitoring.py       # Monitoring::PatientVitals, etc.
├── imaging/
│   ├── __init__.py
│   └── imaging.py          # Imaging::CameraFrame
├── devices/
│   ├── __init__.py
│   └── devices.py          # Devices::DeviceTelemetry
├── clinical_alerts/
│   ├── __init__.py
│   └── clinical_alerts.py              # ClinicalAlerts::ClinicalAlert, ClinicalAlerts::RiskScore
└── hospital/
    ├── __init__.py
    └── hospital.py         # Hospital::ResourceAvailability
```

**Runtime:** `setup.bash` sets `PYTHONPATH` to include `install/lib/python/site-packages/` (already configured). The canonical import pattern:

```python
import rti.connextdds as dds

# Import the generated module — the IDL module becomes a Python namespace
import surgery
import monitoring
# ... import whichever generated modules the application needs

# Access types through the IDL module namespace
cmd = surgery.Surgery.RobotCommand(sequence_number=42, target_id="arm-1")
vitals = monitoring.Monitoring.PatientVitals()

# Optional: create local aliases for frequently used types
RobotCommand = surgery.Surgery.RobotCommand
PatientVitals = monitoring.Monitoring.PatientVitals
```

The `import <generated_module>` step is required — it executes the generated code that defines `@idl.struct` and `@idl.enum` types. IDL modules map to Python namespaces inside the generated module: `surgery.Surgery.RobotCommand` accesses the `RobotCommand` type inside IDL module `Surgery` from generated file `surgery.py`. See [coding-standards.md](coding-standards.md) — IDL → Python for the full type mapping.

C++ include paths are configured by CMake targets directly and follow the same source-directory-mirroring convention.

Reference: [rticonnextdds-examples CMakeLists.txt](https://github.com/rticommunity/rticonnextdds-examples/blob/master/examples/connext_dds/build_systems/cmake/CMakeLists.txt)

### Python Virtual Environment

A project-level venv is created and managed by CMake or a setup script:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

CMake Python targets reference this venv for consistent interpreter and package resolution.

Python package dependencies are tracked in a `requirements.txt` file at the project root. All setup guides must direct users to install from this file:

```bash
pip install -r requirements.txt
```

The `requirements.txt` pins exact versions for all runtime and development dependencies (e.g., `rti.connext==7.6.0`, `PySide6==...`, `pytest==...`, `pytest-qt==...`, `black==...`, `isort==...`, `ruff==...`). See [vision/coding-standards.md](coding-standards.md) for the formatting and linting tools that these packages provide.

## DDS I/O Threading

DDS I/O must never occur on the main thread or UI event loop in any application — Python or C++.

### Python
- Use `async`/`await` with `rti.connext` async APIs
- Integrate with the Qt event loop via **QtAsyncio** for GUI applications
- Non-GUI applications use an asyncio event loop on a dedicated thread or as the main coroutine runner

### C++
- Use **`rti::core::cond::AsyncWaitSet`** (thread pool size = 1) for non-blocking, callback-driven data reception on a background thread
- **`rti::sub::SampleProcessor`** is a convenience wrapper over `AsyncWaitSet` for simple per-sample dispatch. It is **experimental in Connext 7.6.0** and must not be used for safety-critical or latency-sensitive paths. Prefer explicit `AsyncWaitSet` + `ReadCondition` for production control flows.
- The main thread handles initialization, configuration, and lifecycle; all DDS callbacks and reads occur on `AsyncWaitSet` threads
- **I/O context isolation:** Each critical-path I/O context with an independent jitter budget gets its own `AsyncWaitSet` instance. Do not combine fixed-rate publishers and data-driven subscribers on the same `AsyncWaitSet` — see [vision/coding-standards.md](coding-standards.md) (`AsyncWaitSet` Isolation Principle) for the full rule.
- **Never use `DataReaderListener` callbacks for data/sample processing** — listener callbacks run on the middleware's shared receive thread and block all other DataReaders in the participant. See [vision/coding-standards.md](coding-standards.md) for approved patterns and rationale.

---

## XTypes Compliance — Enum Evolution

The mandatory `accept_unknown_enum_value` initialization (compliance mask bit
`0x00000020`) is documented in
[data-model.md — Pre-Participant Initialization](data-model.md), co-located with
the IDL conventions it enables. That section also documents the type registration
requirement (`rti::domain::register_type<T>()` / `register_idl_type()`) that must
be performed in the same initialization pass. The `UNKNOWN` sentinel enumerators
throughout the data model are a direct consequence of the compliance bit; an
application that does not set it cannot correctly interoperate with the type
evolution strategy defined by those IDL conventions.

This is the **sole approved exception** to the "no programmatic QoS" rule.
The compliance mask is not a QoS policy — it has no XML equivalent and must be
set programmatically on the factory before any participant is created. All QoS
policies, transport settings, discovery configuration, and partition assignments
remain XML-only.

---

## Testability

All applications — including GUI applications — must be unit-testable in isolation.

- **GUI testability:** PySide6 widgets must be designed with a clear separation between DDS data handling (view-model / signal layer) and widget rendering. UI logic is tested via **pytest-qt**; DDS behavior is tested by injecting data through the signal/model layer without requiring a live DDS participant.
- **DDS testability:** Applications accept injected DomainParticipants or readers/writers via dependency injection or configuration, enabling tests to substitute real DDS with controlled test participants.
- **C++ testability:** Business logic is separated from DDS entity creation so that unit tests can exercise logic without requiring a Connext license or runtime.

---

## Install Tree & Runtime Environment

The project uses a CMake install step to produce a self-contained install tree. This tree is the contract between the build system and runtime — both local development and Docker containers consume the same structure.

### Install Tree Structure

```
install/
├── bin/                              # C++ executables
├── lib/                              # Project shared libraries (if any)
├── lib/python/site-packages/         # rtiddsgen Python output (see Python Generated Type Packaging)
│   ├── common/                       #   Common module types
│   ├── surgery/                      #   Surgery module types
│   ├── monitoring/                   #   Monitoring module types
│   ├── imaging/                      #   Imaging module types
│   ├── devices/                      #   Devices module types
│   ├── clinical_alerts/                          #   ClinicalAlerts module types
│   └── hospital/                     #   Hospital module types
├── share/
│   ├── qos/                          # Snippets.xml, Patterns.xml, Topics.xml, Participants.xml
│   ├── domains/                      # domains.xml
│   └── routing/                      # Routing Service XML configs
├── etc/
│   ├── clinical-alerts/              # ClinicalAlerts engine runtime config (thresholds, rules)
│   └── surgical-procedure/           # Procedure sim runtime config
└── setup.bash                        # Single source script for local development
```

Every CMake target that produces a runtime artifact must have a corresponding `install()` rule placing it in the correct location within this tree. Generated Python types are installed into `lib/python/site-packages/`. QoS and domain XML files are installed into `share/`. Per-module runtime configuration is installed into `etc/<module>/`.

### `setup.bash`

CMake generates and installs `setup.bash` at the install tree root. Sourcing it configures the complete runtime environment — venv activation, paths, QoS profile loading, and module config:

```bash
#!/usr/bin/env bash
# Auto-generated by CMake install. Do not edit.
_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_ROOT="$(dirname "$_DIR")"

# Activate Python venv (pip-installed: rti.connext, PySide6, pytest)
if [[ -f "$_ROOT/.venv/bin/activate" ]]; then
    source "$_ROOT/.venv/bin/activate"
fi

# Project install paths
export PATH="$_DIR/bin:$PATH"
export LD_LIBRARY_PATH="$_DIR/lib:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="$_DIR/lib/python/site-packages:${PYTHONPATH:-}"

# QoS + domain XML in dependency order
export NDDS_QOS_PROFILES="$_DIR/share/qos/Snippets.xml;\
$_DIR/share/qos/Patterns.xml;\
$_DIR/share/qos/Topics.xml;\
$_DIR/share/qos/Participants.xml;\
$_DIR/share/domains/domains.xml"

# Runtime configuration root
export MEDTECH_CONFIG_DIR="$_DIR/etc"
```

> **Observability note:** Monitoring Library 2.0 is enabled entirely via XML properties in the participant QoS profile. No additional environment variables are required in `setup.bash`. Collector Service connection details (host, port) are configured in `Participants.xml`, not environment variables. Docker Compose sets container-specific overrides (e.g., Collector Service hostname) via service environment, not `setup.bash`.

### Local Development Workflow

```bash
# One-time: Connext environment + venv
source $NDDSHOME/resource/scripts/rtisetenv_x64Linux4gcc8.5.0.bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Build + install (install prefix defaults to <source>/install/)
cmake -B build -S .
cmake --build build
cmake --install build

# Activate runtime environment
source install/setup.bash

# Run tests, modules, or services
pytest tests/
surgical-procedure --room OR-3
```

After the initial setup, the iterative cycle is:

```bash
cmake --build build && cmake --install build
# Re-source only if setup.bash itself changed
```

### Docker Integration

Docker multi-stage builds use the install tree directly:

```dockerfile
# Build stage
FROM build-base AS builder
COPY . /src
RUN cmake -B /build -S /src -DCMAKE_INSTALL_PREFIX=/opt/medtech \
    && cmake --build /build \
    && cmake --install /build

# Runtime stage
FROM runtime-cpp
COPY --from=builder /opt/medtech /opt/medtech
ENV PATH="/opt/medtech/bin:$PATH"
ENV LD_LIBRARY_PATH="/opt/medtech/lib:$LD_LIBRARY_PATH"
ENV NDDS_QOS_PROFILES="/opt/medtech/share/qos/Snippets.xml;/opt/medtech/share/qos/Patterns.xml;/opt/medtech/share/qos/Topics.xml;/opt/medtech/share/qos/Participants.xml;/opt/medtech/share/domains/domains.xml"
ENV MEDTECH_CONFIG_DIR="/opt/medtech/etc"
```

Docker containers do not use `setup.bash` — they set env vars directly in the Dockerfile or `docker-compose.yml`.

### Install Rules

Every CMake target must define `install()` rules. Missing install rules are a build defect.

| Artifact type | Install destination | CMake mechanism |
|---------------|--------------------|-----------------|
| C++ executables | `bin/` | `install(TARGETS ... RUNTIME DESTINATION bin)` |
| Project shared libraries | `lib/` | `install(TARGETS ... LIBRARY DESTINATION lib)` |
| Generated Python types | `lib/python/site-packages/` | `install(DIRECTORY ... DESTINATION lib/python/site-packages)` |
| Application Python packages | `lib/python/site-packages/` | `install(DIRECTORY ... DESTINATION lib/python/site-packages)` |
| QoS XML files | `share/qos/` | `install(FILES ... DESTINATION share/qos)` |
| Domain library XML | `share/domains/` | `install(FILES ... DESTINATION share/domains)` |
| Routing Service configs | `share/routing/` | `install(FILES ... DESTINATION share/routing)` |
| Per-module runtime config | `etc/<module>/` | `install(FILES ... DESTINATION etc/<module>)` |
| `setup.bash` | root of install tree | `install(FILES ... DESTINATION .)` |

---

## Containerization

- **Docker** — each application / service runs in its own container for multi-host simulation
- **Docker Compose** — orchestrates the full suite, defines custom networks, environment variables for partition/domain configuration
- Containers use transport configuration appropriate to the simulation context (see [system-architecture.md](system-architecture.md))

### Docker Base Images

All Dockerfiles use pinned Ubuntu 22.04 LTS as the base (`FROM ubuntu:22.04`). No `latest` tags.

| Image | Purpose | Contents |
|-------|---------|----------|
| `build-base` | Compile C++ targets | Ubuntu 22.04, GCC toolchain, CMake, Connext 7.6.0 host libraries (`x64Linux4gcc8.5.0`) |
| `runtime-cpp` | Run compiled C++ apps | Ubuntu 22.04 minimal, Connext 7.6.0 shared libraries only — no compiler |
| `runtime-python` | Run Python apps | Ubuntu 22.04, Python 3.10, project venv, `rti.connext==7.6.0`, PySide6 |

## Testing

| Layer | Framework | Notes |
|-------|-----------|-------|
| C++ unit/integration | Google Test | Linked via CMake `FetchContent` |
| Python unit/integration | pytest | Run from venv |
| DDS integration | pytest + rti.connext | Verifies pub/sub, QoS, partition, filtering behaviors |
| GUI | pytest-qt | PySide6 widget and signal tests |
| System/E2E | Docker Compose + pytest | Full multi-container scenario tests |

## Logging Standard

All modules use a consistent, structured logging approach built on the **RTI Connext Logging API** (`rti::config::Logger` in Modern C++, `rti.connextdds.Logger` in Python). Application log messages are written using the logger's **USER** category methods (e.g., `logger.warning(...)`, `logger.notice(...)`). These messages are captured locally and — when Monitoring Library 2.0 is enabled — automatically forwarded through the RTI Observability Framework pipeline to RTI Collector Service, which exports them to Grafana Loki (or an OpenTelemetry Collector) for centralized search and dashboarding.

The native Connext logging API emits user-category messages that Monitoring Library 2.0 collects and forwards to Collector Service alongside middleware telemetry. Application code does not create a participant or topic for logging — Monitoring Library 2.0’s dedicated participant on the Observability domain (Domain 20) handles all telemetry transport.

### Log Levels

All modules use the Connext syslog-style severity levels exposed by `rti::config::Logger`. Each level has a defined semantic meaning that must be respected consistently across every module:

| Level | Meaning | Example |
|-------|---------|---------|
| `emergency` | Unrecoverable error; process must terminate | DDS participant creation failed, required config file missing |
| `alert` | Critical error requiring immediate attention | DDS endpoint match failure, QoS incompatibility detected |
| `critical` | Critical error; module is degraded but running | Safety interlock timeout, redundancy failover triggered |
| `error` | Recoverable error; a single operation failed | Failed to process a vitals sample, config value out of range |
| `warning` | Unexpected condition that may indicate a problem | Sample received with stale timestamp, approaching resource limit |
| `notice` | Significant normal event | Module initialized, participant matched, procedure started |
| `informational` | Routine operational event | Sample published, configuration loaded, endpoint discovered |
| `debug` | Developer-level diagnostic detail | QoS profile resolved, partition assigned, filter expression built |

Logger verbosity is configured externally via the `LOGGING` QoS policy in `<participant_factory_qos>` — never hardcoded in application code. The default participant-factory profile sets overall verbosity to `WARNING`; operators can raise it for targeted troubleshooting by editing the QoS XML without recompiling.

### Log Message Format

Every log message must include:

1. **Module identity** — include the module name (e.g., `"surgical-procedure"`, `"hospital-dashboard"`, `"clinical-alerts"`) as a prefix or structured field in the message text
2. **Operational context** — include the partition context (room/procedure) when available in the message text
3. **Concise description** — what happened, in plain English, with relevant identifiers

Examples of well-formed messages:

```
[surgical-procedure] Participant matched on Hospital domain (room/OR-3/procedure/proc-2026-0042)
[hospital-dashboard] PatientVitals sample for patient P-1042 has timestamp older than 2 s
[clinical-alerts] Failed to compute hemorrhage risk score for patient P-1042: model input incomplete
```

Examples of poorly-formed messages:

```
Done                              ← no context, no specifics
error occurred                   ← meaningless
x=42                             ← no semantic meaning
```

### Verbosity Configuration (XML)

Logger verbosity is configured in the default participant-factory QoS profile — application code must not set verbosity programmatically:

```xml
<qos_profile name="FactoryDefaults"
             is_default_participant_factory_profile="true">
    <participant_factory_qos>
        <logging>
            <verbosity>WARNING</verbosity>
            <category>ALL</category>
            <print_format>VERBOSE_TIMESTAMPED</print_format>
        </logging>
    </participant_factory_qos>
</qos_profile>
```

To raise verbosity for troubleshooting, change `<verbosity>` in the XML (e.g., to `LOCAL` for notice-and-above, or `ALL` for full debug output). No recompilation required.

### Initialization

The `rti::config::Logger` singleton is process-global — no separate participant is needed for logging. Each module obtains the logger and writes user-category messages. Verbosity is controlled entirely by the QoS XML loaded at startup; modules must not call any verbosity-setting API.

**Python:**

```python
import rti.connextdds as dds

# Obtain the native Connext logger singleton (verbosity configured via XML)
logger = dds.Logger.instance

# Application logging — user-category methods
logger.notice("[clinical-alerts] Module initialized, subscribing to PatientVitals")
logger.warning("[clinical-alerts] PatientVitals sample for patient P-1042 has stale timestamp")
```

**C++ (Modern C++):**

```cpp
#include <rti/config/Logger.hpp>

// Obtain the native Connext logger singleton (verbosity configured via XML)
auto& logger = rti::config::Logger::instance();

// Application logging — user-category methods
logger.notice("[surgical-procedure] Participant matched on Procedure domain");
logger.warning("[surgical-procedure] Approaching resource limit on OR-3 partition");
```

No additional CMake components are required — the logging API is part of the core Connext library.

### User Log Forwarding via Monitoring Library 2.0

User-category log messages are forwarded to Collector Service through Monitoring Library 2.0. The forwarding level is configured in the participant factory QoS XML:

```xml
<participant_factory_qos>
    <monitoring>
        <enable>true</enable>
        <telemetry_data>
            <logs>
                <user_forwarding_level>NOTICE</user_forwarding_level>
                <middleware_forwarding_level>WARNING</middleware_forwarding_level>
            </logs>
        </telemetry_data>
    </monitoring>
</participant_factory_qos>
```

The `user_forwarding_level` controls which user-category messages Monitoring Library 2.0 forwards to Collector Service. The default is `WARNING`; the medtech suite sets it to `NOTICE` to capture significant operational events. Setting it higher than `NOTICE` in production may affect performance if modules produce high log volume.

Collector Service receives forwarded logs over DDS and exports them to Grafana Loki via its built-in `loki_exporter` (or to an OpenTelemetry Collector via `otlp_exporter`). See [Observability Standard](#observability-standard) for the full pipeline.

### Rules

1. **Every module must configure the Connext Logger.** No module may use `printf`, `std::cout`, `print()`, or a custom logging framework for diagnostic output. All application messages use `rti::config::Logger` (C++) or `rti.connextdds.Logger` (Python) user-category methods.
2. **Log level semantics are global.** The level definitions above apply to every module without exception. A `warning` in one module must mean the same thing as a `warning` in another.
3. **Module identity must be included in every message.** Use a `[module-name]` prefix matching the module directory name (e.g., `[surgical-procedure]`). This enables log filtering and correlation in Grafana Loki.
4. **Logger verbosity must be configured via QoS XML, never in code.** The `LOGGING` QoS policy in `<participant_factory_qos>` controls local emission; the `user_forwarding_level` in `<monitoring>` QoS separately controls which messages are forwarded to Collector Service. No module may call `verbosity()` or `verbosity_by_category()` programmatically.
5. **No log-level-based branching in application logic.** Log level controls output verbosity only — never branch on the current level to change functional behavior.
6. **No dedicated DomainParticipant for logging.** The Connext Logging API is process-global. Application logging does not create any additional DomainParticipants.

---

## Observability Standard

All Connext applications are instrumented with the **RTI Observability Framework** to provide real-time debugging and operational monitoring. The framework consists of three components:

### Monitoring Library 2.0

Every DomainParticipant is instrumented with Monitoring Library 2.0 via QoS XML configuration. The library collects middleware telemetry — metrics (throughput, latency, matched endpoints), logs, entity status changes (liveliness, dropped samples), discovery events, and security events — and forwards it to Collector Service. No application code changes are required; instrumentation is enabled entirely through XML properties.

Monitoring Library 2.0 creates a **dedicated DomainParticipant** on the Observability domain (Domain 20) to distribute telemetry. This keeps observability traffic isolated from application data on the Procedure and Hospital domains. The domain ID and optional participant QoS profile are configured in the MONITORING QoS policy:

```xml
<participant_factory_qos>
    <monitoring>
        <enable>true</enable>
        <distribution_settings>
            <dedicated_participant>
                <domain_id>20</domain_id>
            </dedicated_participant>
        </distribution_settings>
        <telemetry_data>
            <logs>
                <user_forwarding_level>NOTICE</user_forwarding_level>
                <middleware_forwarding_level>WARNING</middleware_forwarding_level>
            </logs>
        </telemetry_data>
    </monitoring>
</participant_factory_qos>
```

This configuration is defined once in the shared participant factory QoS profile (via `BuiltinQosSnippetLib::Feature.Monitoring2.Enable` as a base) and applies to all applications. The default Monitoring Library 2.0 domain ID is 2; the medtech suite overrides it to 20 to align with the project’s domain numbering scheme (see [data-model.md — Domain 20](data-model.md)).

### Collector Service

RTI Collector Service aggregates telemetry from all instrumented participants and forwards it to:

- **Prometheus** — time-series metrics storage (throughput, latency, resource utilization)
- **Grafana Loki** — log and security event aggregation
- **RTI Admin Console** — real-time remote debugging via WebSocket API

Collector Service runs as its own container on `hospital-net`, alongside Cloud Discovery Service. Its telemetry collection is controlled at runtime via the Collector Service REST API — enabling targeted debugging without restarting applications.

### Observability Dashboards

RTI provides a set of hierarchical **Grafana dashboards** that visualize Connext telemetry:

- System-level overview with alerting on anomalies (missed deadlines, liveliness loss, QoS incompatibilities)
- Per-participant drill-down (matched endpoints, sample counts, latency)
- Log and security event timeline

The dashboards read metrics from Prometheus and logs from Grafana Loki.

### Deployment (Docker Compose)

The observability stack runs as additional services in `docker-compose.yml`:

| Service | Image | Network | Purpose |
|---------|-------|---------|----------|
| `collector-service` | RTI Collector Service | `hospital-net` | Telemetry aggregation and forwarding |
| `prometheus` | `prom/prometheus` | `hospital-net` | Metrics time-series database |
| `grafana-loki` | `grafana/loki` | `hospital-net` | Log aggregation |
| `grafana` | `grafana/grafana-oss` | `hospital-net` | Observability dashboards |

All four services are optional — they can be included in a Docker Compose profile (e.g., `--profile observability`) so the core simulation runs without them when observability is not needed.

### Integration with Application Logging

The Connext Logging API and Monitoring Library 2.0 are complementary:

- **Connext Logging API** (`rti::config::Logger` / `rti.connextdds.Logger`) provides the application-level logging interface. Modules write user-category messages via methods like `logger.warning(...)`, `logger.notice(...)`, etc.
- **Monitoring Library 2.0** captures user-category log messages (alongside middleware-level telemetry — metrics, entity status, discovery events) and forwards them to Collector Service over DDS.
- **Collector Service** aggregates all telemetry and exports logs to Grafana Loki (`loki_exporter`) or an OpenTelemetry Collector (`otlp_exporter`) for centralized log search.

The forwarding level for user logs is configured in QoS XML via `<user_forwarding_level>` under the MONITORING QoS policy (see [Logging Standard](#logging-standard)). Both application logging and middleware telemetry flow through Monitoring Library 2.0 → Collector Service → Grafana Loki, providing a unified log view.

### Rules

1. **Every DomainParticipant must have Monitoring Library 2.0 enabled.** This is configured via XML properties in the participant QoS profile — no per-module opt-in code.
2. **Observability stack is profile-gated.** `docker compose --profile observability up` starts the telemetry backends; the core simulation runs independently.
3. **Collector Service REST API is the runtime control plane.** Log verbosity and metric collection rates are adjusted via REST, not by restarting applications.
4. **Dashboard configurations are version-controlled.** Grafana dashboard JSON and Prometheus scrape configs are stored under `services/observability/`.
5. **No application code depends on observability.** Removing the observability profile must not affect functional behavior.

---

## Project Layout (Target)

```
medtech-suite/
├── CMakeLists.txt                  # Top-level unified build
├── docker-compose.yml              # Multi-container orchestration
├── requirements.txt                # Pinned Python package dependencies
├── docs/agent/                     # Planning documents (this framework)
├── interfaces/                     # Shared IDL types, QoS XML, domain definitions, security
│   ├── idl/
│   │   ├── common/
│   │   ├── surgery/
│   │   ├── monitoring/
│   │   ├── imaging/
│   │   ├── devices/
│   │   ├── clinical_alerts/
│   │   └── hospital/
│   ├── qos/
│   │   ├── Snippets.xml
│   │   ├── Patterns.xml
│   │   ├── Topics.xml
│   │   └── Participants.xml
│   ├── domains/                    # Domain library XML (domain definitions and topic registrations)
│   └── security/
│       └── governance/
├── modules/
│   ├── surgical-procedure/         # C++ and Python components
│   │   ├── digital-twin/           # PySide6 robot visualization GUI
│   │   └── README.md               # Module purpose, usage, Connext features used
│   ├── hospital-dashboard/         # PySide6 GUI
│   │   └── README.md
│   └── clinical-alerts/            # Clinical Decision Support (ClinicalAlerts module) engine
│       └── README.md
├── services/
│   ├── routing/                    # Routing Service configurations
│   │   └── README.md
│   ├── recording/                  # RTI Recording Service + RTI Replay Service configurations
│   │   └── README.md
│   ├── discovery/                  # RTI Cloud Discovery Service configurations
│   │   └── README.md
│   └── observability/              # Collector Service config, Prometheus scrape config, Grafana dashboards
│       └── README.md
├── resources/                      # Shared GUI assets (loaded by all PySide6 apps)
│   ├── fonts/                      # Roboto Condensed, Montserrat, Roboto Mono (.ttf)
│   ├── images/                     # RTI logo (rti-logo.png, rti-logo.svg)
│   └── styles/                     # Shared Qt stylesheet (medtech.qss)
├── simulation/
│   ├── docker/                     # Dockerfiles per component
│   └── scenarios/                  # Scenario launchers and configs
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── build/                          # CMake build directory (not committed)
└── install/                        # CMake install tree (not committed)
    ├── bin/
    ├── lib/
    │   └── python/site-packages/
    ├── share/
    │   ├── qos/
    │   ├── domains/
    │   └── routing/
    ├── etc/
    │   ├── clinical-alerts/
    │   └── surgical-procedure/
    └── setup.bash
```

## Module Documentation Standard

Every module and service directory must contain a `README.md` that follows the structure,
heading order, markdownlint compliance rules, and CI enforcement requirements defined in
[vision/documentation.md](documentation.md).

The standard mandates seven required sections in order: **Overview**, **Quick Start**,
**Architecture**, **Configuration Reference**, **Testing**, and **Going Further**, plus the
file title as the sole top-level heading. Markdownlint must pass with zero errors and zero
warnings; inline suppression comments are never permitted.
