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
5. **Connext architecture string** — if the target architecture name changes (e.g., `x64Linux4gcc8.5.0` → `x64Linux4gcc12.3.0`), update it in `CONNEXTDDS_ARCH` in CMakeLists.txt and in the Dockerfile `ARG` declarations
6. **Validate** — run the full test suite, QoS XML XSD validation, and Docker build
7. **Review RTI migration guide** — check the [RTI Connext Migration Guide](https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/migration_guide/index.html) for any behavioral changes, deprecated APIs, or QoS default changes

#### Design Constraints for Migration Safety

- **No hardcoded version strings in application code.** The version `7.6.0` must never appear in `.cpp`, `.py`, or `.hpp` files. It exists only in build/config files listed above.
- **`find_package` uses the CMake variable.** `find_package(RTIConnextDDS "${CONNEXT_VERSION}" ...)` — never a literal string.
- **Python pin uses `==`, not `>=`.** Exact pinning prevents silent upgrades and makes the bump explicit.
- **Docker images use `ARG` for the version.** All `COPY` paths and `ENV` values that reference the Connext install path derive from the `ARG`, not hardcoded paths.
- **QoS XML schema URL is the only version reference in XML.** No other element in QoS or domain XML is version-specific.
- **The architecture string is parameterized in CMake.** A `CONNEXTDDS_ARCH` cache variable (defaulting from the `$CONNEXTDDS_ARCH` environment variable set by `rtisetenv`, falling back to `x64Linux4gcc8.5.0`) is used wherever the architecture name appears in build logic, so a toolchain change is a single variable update.

This design ensures that a non-breaking Connext version bump touches at most **5 files** and **~6 lines of configuration** — no application code, no QoS tuning, no IDL changes.

## Languages

| Language | Standard | Use |
|----------|----------|-----|
| C++ | C++17 | Terminal/background/service applications, Routing Service plugins (including Foxglove Bridge — V2), performance-critical data paths |
| Python | 3.10+ | GUI applications, simulators, test harnesses |

## Foxglove IDL Schemas (V1.1)

Selected [Foxglove OMG IDL schemas](https://github.com/foxglove/foxglove-sdk/tree/main/schemas/omgidl/foxglove) are compiled with `rtiddsgen` and linked into the Foxglove Transformation plugin. These schemas are **build-time dependencies of the plugin only** — they are not part of the medtech application data model and are not registered on application-domain participants.

| Schema File | Foxglove Type | Used By |
|-------------|---------------|--------|
| `Time.idl` | `foxglove::Time` | All transformed types |
| `Quaternion.idl` | `foxglove::Quaternion` | `FrameTransform`, `Pose` |
| `Vector3.idl` | `foxglove::Vector3` | `FrameTransform`, `Pose` |
| `Pose.idl` | `foxglove::Pose` | `PoseInFrame` |
| `PoseInFrame.idl` | `foxglove::PoseInFrame` | Tool tip pose route |
| `JointState.idl` | `foxglove::JointState` | `JointStates` |
| `JointStates.idl` | `foxglove::JointStates` | Robot joint state route |
| `FrameTransform.idl` | `foxglove::FrameTransform` | `FrameTransforms` |
| `FrameTransforms.idl` | `foxglove::FrameTransforms` | Kinematic chain route |
| `CompressedImage.idl` | `foxglove::CompressedImage` | Camera frame route |

Foxglove IDL files are vendored into the project under `interfaces/idl/foxglove/` (copied from the foxglove-sdk repository at a pinned commit). They are compiled by `rtiddsgen` during the CMake build and generate C++ types linked into `libmedtech_foxglove_transf.so`. The vendored copy and pinned commit hash are tracked in `THIRD_PARTY_NOTICES.md`.

Additional Foxglove schemas (`CameraCalibration`, `ImageAnnotations`, `CompressedVideo`, `SceneUpdate`, `SceneEntity`, `Log`, etc.) will be vendored when V2 and V3 scopes are implemented.

## GUI Framework

- **NiceGUI** — Python web-based UI framework, built on FastAPI and Quasar/Vue3
- GUI applications run in the browser; the NiceGUI server uses a single asyncio event loop shared with `rti.asyncio` for DDS I/O — no separate Qt event loop or thread bridge required
- **Hospital container** serves the hospital dashboard at `http://localhost:8080`; **per-room containers** serve the Procedure Controller and Digital Twin at dynamically assigned ports (e.g., `8091`, `8092`). Each container runs its own NiceGUI process with only its own page modules.
- `GuiBackend` ABC (see `modules/shared/medtech/gui/_backend.py`) is the standardized lifecycle pattern: subclasses register `app.on_startup` / `app.on_shutdown` hooks automatically, ensuring clean DDS participant lifecycle management

### GUI Design Standard

All GUI applications (Hospital Dashboard, Digital Twin Display, and any future GUIs) must share a consistent visual identity. The authoritative design reference is [ui-design-system.md](ui-design-system.md). This section provides a summary.

#### Color Palette

**Primary colors** — used for the majority of UI surfaces:

| Name | Hex | RGB | Usage |
|------|-----|-----|-------|
| RTI Blue | `#004A8A` | 0 / 74 / 138 | Window title bars, primary action buttons, sidebar backgrounds, selected-row highlight |
| RTI Orange | `#E68A00` | 230 / 138 / 0 | Warning indicators, accent buttons, call-to-action elements |
| RTI Gray | `#63666A` | 99 / 102 / 106 | Secondary text, borders, disabled controls, neutral status |

**Secondary colors** — used in conjunction with primary colors, never as standalone dominant colors:

| Name | Hex | RGB | Usage |
|------|-----|-----|-------|
| RTI Light Blue | `#00B5E2` | 0 / 181 / 226 | Info badges, link text, hover highlights, streaming-data sparklines |
| RTI Light Orange | `#FFA300` | 255 / 163 / 0 | Elevated-warning indicators, pending-state badges |
| RTI Green | `#059669` | 5 / 150 / 105 | Normal/healthy status, operational mode indicators, successful actions |
| RTI Light Gray | `#BBBCBC` | 187 / 188 / 188 | Panel backgrounds, dividers, placeholder text, disabled backgrounds |

**Semantic mapping for clinical severity:**

| Severity | Color | Hex |
|----------|-------|-----|
| Normal / Operational | Success | `#059669` |
| Warning / Caution | Warning | `#D97706` |
| Critical / E-STOP / Alarm | Critical | `#DC2626` |
| Info / Nominal | Info | `#0284C7` |
| Disconnected / Unknown | Neutral-500 | `#6B7280` |

See [ui-design-system.md](ui-design-system.md) § Design Token Architecture for the full token system.

#### Typography

All GUI applications use the following web typography stack:

| Role | Font Family | Fallback |
|------|-------------|----------|
| Headlines, panel titles, navigation, body text | **Inter** | sans-serif |
| Monospace (data values, log output, raw DDS data) | **Roboto Mono** | monospace |

Fonts are bundled as application resources (`.ttf`/`.woff2` files under `resources/fonts/`) and loaded at startup via `@font-face` CSS. No system font or CDN dependency. See [ui-design-system.md](ui-design-system.md) § Typography for the semantic type scale.

#### Branding

- The **RTI logo** is displayed in the application title bar or header region of every GUI window
- Logo asset is stored at `resources/images/rti-logo.png` (and `rti-logo.svg` for scalable contexts)
- The logo appears left-aligned in the header, sized proportionally to the header height
- A "Powered by RTI Connext" tagline may appear in the status bar or about dialog

#### Layout Conventions

- **Dark header bar** — RTI Blue (`#004A8A`) background with white text and RTI logo (glassmorphism optional)
- **Light content area** — white or near-white background (`neutral-50`) for data panels
- **Sidebar navigation** (where applicable) — RTI Blue background, white text, RTI Light Blue hover
- **Status bar** — bottom of window, RTI Gray background, shows connection state and DDS participant health
- All panels use consistent padding (12 px per design tokens), border radius (8 px cards, 16 px floating panels), and neutral-300 dividers
- Color-coded status indicators use the semantic severity mapping above, with icons alongside color for accessibility

#### Stylesheets

All GUI applications use Tailwind CSS utility classes (provided by Quasar/NiceGUI) for layout and spacing. The brand palette is applied via `ui.colors(primary='#004A8A', accent='#E68A00', ...)` in `init_theme()`. Glassmorphism effects use `backdrop-filter: blur()`. No `.qss` stylesheet files are used.

#### Shared GUI Bootstrap

All NiceGUI applications share a common initialization sequence via the `medtech.gui` shared subpackage:

```python
from medtech.gui import init_theme
from medtech.gui._backend import GuiBackend

# Apply brand palette + load local fonts (called once per app)
init_theme()  # calls ui.colors(), app.add_static_files('/fonts', ...)

# Per-module backend: subclass GuiBackend, call super().__init__() last
class MyBackend(GuiBackend):
    # DDS setup in __init__; super().__init__() registers on_startup/on_shutdown
    ...

backend = MyBackend()  # registers hooks automatically at module import time
```

Each NiceGUI process imports only its own page modules at startup. The hospital app imports the dashboard module; each room app imports the controller and digital twin modules for its room. Each page module instantiates its `GuiBackend` subclass at module level — no manual lifecycle orchestration is needed in the entry point.

## CLI Tool

The `medtech` CLI is a locally-installed Python console script that
provides a streamlined quick-start workflow for building, launching, and
scaling the medtech suite simulation. It is a thin convenience wrapper
over native tools (`cmake`, `docker run`) — every command prints the
underlying invocation so developers can run native commands directly if
they prefer.

| Component | Version | Purpose |
|-----------|---------|---------|
| `click` | latest stable | CLI framework — composable subcommands, auto-generated `--help` |

The entry point is declared in `pyproject.toml`:

```toml
[project.scripts]
medtech = "medtech.cli:main"
```

After `pip install -e .` (or sourcing `setup.bash` in the install tree),
the `medtech` command is available on PATH. No platform-specific wrapper
script is needed — pip generates the appropriate shim for the active
platform.

### Command Summary

| Command | Wraps | Purpose |\n|---------|-------|---------|\n| `medtech build` | `cmake --build build --target install` | Configure (if needed), build, and install |\n| `medtech run hospital [--name NAME]` | Sequential `docker run --rm -d` (CDS, Routing, GUI; + NAT router if named) | Start a hospital instance — unnamed = flat networks, named = isolated + NAT |\n| `medtech run or [--name NAME] [--hospital NAME]` | `docker run --rm -d ...` (multiple) | Spawn Service Host + twin containers for one OR |\n| `medtech run cloud --name NAME` | `docker run --rm -d` (CDS, WAN RS) | *V3.0:* Start a cloud instance on `wan-net` |\n| `medtech launch [SCENARIO]` | Sequence of `run` calls | Start a named simulation scenario end-to-end |\n| `medtech launch --list` | — | List available scenarios with descriptions |\n| `medtech launch --dockgraph` | Adds a DockGraph sidecar container | Include topology visualizer at `http://localhost:7800` |\n| `medtech stop` | `docker stop` + `docker network rm` | Tear down all containers and networks |\n| `medtech status` | `docker ps --filter` | Show running containers and GUI URLs |\n| `medtech status --topology` | `docker network inspect` | ASCII tree of containers grouped by network |

All multi-instance `run` commands accept `--name`. When omitted, the
CLI auto-generates a unique name by scanning running containers (e.g.,
`hospital-1`, `OR-1`). This ensures every resource has an explicit
identity in `docker ps`, `medtech status`, and DockGraph.

`medtech launch` is a convenience that calls the appropriate `run`
commands for a named scenario. Developers who prefer manual control
can compose their own topology with individual `run` calls.

### Design Constraints

- **Transparency:** Every Docker or CMake invocation is printed to
  stdout before execution. The developer can copy-paste any command.
- **No abstraction:** The CLI does not invent its own configuration
  format, state files, or daemon processes. It delegates entirely to
  `cmake` and `docker run`.
- **No DDS dependency:** The CLI does not import `rti.connext` or
  create DDS participants. It is a pure build/launch orchestrator.
- **Fail-through:** If a command fails, the underlying tool's error
  message is shown directly. The CLI does not swallow or reformat
  errors.

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
| Docker base images | Ubuntu 24.04 |
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
  (requires `include(ConnextDdsCodegen)` before first use — the module
  is on `CMAKE_MODULE_PATH` after the `FetchContent` above but is not
  auto-included by `find_package`)
- Standard CMake targets for linking Connext libraries

### Default Build Configuration

The top-level `CMakeLists.txt` must set these defaults:

```cmake
# --- Connext version and architecture (single source of truth) ---
set(CONNEXT_VERSION "7.6.0" CACHE STRING "RTI Connext DDS version")
set(CONNEXTDDS_ARCH "$ENV{CONNEXTDDS_ARCH}" CACHE STRING "RTI Connext target architecture")
if(NOT CONNEXTDDS_ARCH)
    set(CONNEXTDDS_ARCH "x64Linux4gcc8.5.0" CACHE STRING "" FORCE)
endif()

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
- **`CONNEXTDDS_ARCH`** — single CMake variable for the Connext target architecture, named to match RTI's `FindRTIConnextDDS` convention. Defaults from the `$CONNEXTDDS_ARCH` environment variable (set by `rtisetenv`), falling back to `x64Linux4gcc8.5.0`. Used in Docker build args and any architecture-dependent logic.
- **C++17** — required minimum. Do not use C++20 features.
- **Release** — default build type. Debug builds are used only for targeted troubleshooting.
- **Shared libraries** — default linkage. Connext ships shared libraries for the target architecture; static linking is not used unless explicitly required by a deployment constraint.
- **Install prefix** — defaults to `<source>/install/` when the user has not explicitly set `CMAKE_INSTALL_PREFIX`. Users who want to install elsewhere pass `-DCMAKE_INSTALL_PREFIX=<path>` explicitly.

C++ targets must link against the `RTIConnextDDS::cpp2_api` imported target (the Modern C++ API). Do not link against lower-level C targets directly.

`connextdds_rtiddsgen_run` is invoked for both `C++11` (with `-standard IDL4_CPP`) and `Python` language targets. Generated output files must mirror the IDL source directory structure so that `#include` and `import` paths are consistent with the IDL file paths:

```
interfaces/idl/surgery/surgery.idl
  → <build>/generated/cpp/surgery/surgery.hpp     (C++11)
  → <build>/generated/python/surgery.py            (Python — flat)
```

Generated output is written into the CMake build directory, not the source tree. The source tree is kept clean; `generated/` is never committed to version control.

#### Python Generated Type Packaging

The CMake build generates Python type-support modules via `rtiddsgen -language Python`. These must be installed as importable Python packages without placing generated code in the source tree.

**Build time:** `rtiddsgen` outputs one `.py` file per IDL file into a **flat** directory `<build>/generated/python/`. The `-noSysPathGeneration` flag (see INC-002) suppresses the default `sys.path.append` stanzas, allowing clean imports via `PYTHONPATH`. No `__init__.py` markers or subdirectories are needed — each generated module is a standalone `.py` file importable directly.

```cmake
foreach(mod ${IDL_MODULES})
    connextdds_rtiddsgen_run(
        IDL_FILE "${IDL_DIR}/${mod}/${mod}.idl"
        LANG "Python"
        OUTPUT_DIRECTORY "${PY_GEN_DIR}"    # flat output
        INCLUDE_DIRS "${IDL_DIR}"
        VAR "${mod}_py"
        EXTRA_ARGS -noSysPathGeneration
    )
endforeach()
```

**Install time:** `cmake --install` copies the flat generated `.py` files into `lib/python/site-packages/`:

```cmake
install(DIRECTORY "${PY_GEN_DIR}/"
    DESTINATION lib/python/site-packages
    FILES_MATCHING PATTERN "*.py"
    PATTERN "*_timestamp.cmake" EXCLUDE)
```

The installed layout:

```
install/lib/python/site-packages/
├── common.py               # Common::Timestamp_t, Common::EntityIdentity, etc.
├── surgery.py              # Surgery::RobotCommand, Surgery::RobotState, etc.
├── monitoring.py           # Monitoring::PatientVitals, etc.
├── imaging.py              # Imaging::CameraFrame
├── devices.py              # Devices::DeviceTelemetry
├── clinical_alerts.py      # ClinicalAlerts::ClinicalAlert, ClinicalAlerts::RiskScore
└── hospital.py             # Hospital::ResourceAvailability
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

The `requirements.txt` pins exact versions for all runtime and development dependencies (e.g., `rti.connext==7.6.0`, `nicegui==...`, `pytest==...`, `black==...`, `isort==...`, `ruff==...`). See [vision/coding-standards.md](coding-standards.md) for the formatting and linting tools that these packages provide.

## DDS I/O Threading

Connext 7.6.0 DDS API calls (`write()`, `take()`, etc.) are safe from
**any application thread**. There is no restriction tied to the process
main thread.

For **GUI host applications** (NiceGUI — asyncio-based):

- DDS `async for sample in reader.take_async()` and `reader.take_data_async()` run as asyncio coroutines on the NiceGUI event loop — they are the **only approved** data-reception patterns for GUI modules.
- **Writes** are **allowed** from any asyncio coroutine. For DataWriters on the asyncio event loop, configure the `Snippets::NonBlockingWrite` QoS snippet (asynchronous publish mode, zero `max_blocking_time`) to eliminate any blocking path.
- **Blocking waits** (`WaitSet.wait()`, synchronous `take()` in a tight loop) are **prohibited** in asyncio coroutines — they stall the event loop and freeze all connected browser clients.
- Use `background_tasks.create(coroutine)` (NiceGUI API) to launch long-running reader loops so they run concurrently without blocking page rendering.

See [dds-consistency.md §5 — GUI Host Applications](dds-consistency.md)
for the complete policy, architecture diagram, and per-operation
allowed/prohibited table.

Services must not assume any properties of the thread that calls `run()`.
If a service needs periodic publishing or subscriber dispatch, it creates
its own concurrency primitives internally. See
[dds-consistency.md §5](dds-consistency.md) for the full threading
contract.

### Python
- Use `async`/`await` with `rti.connext` async APIs
- GUI host applications use the **NiceGUI asyncio event loop** directly — `rti.asyncio` DDS coroutines and `background_tasks.create()` are the approved patterns; no QtAsyncio or separate thread bridge is needed
- Non-GUI services use an asyncio event loop (the `run()` coroutine is
  gathered by the Service Host or driven by `asyncio.run()` in standalone mode)

### C++
- Use **`rti::core::cond::AsyncWaitSet`** (thread pool size = 1) for non-blocking, callback-driven data reception
- **`rti::sub::SampleProcessor`** is a convenience wrapper over `AsyncWaitSet` for simple per-sample dispatch. It is **experimental in Connext 7.6.0** and must not be used for safety-critical or latency-sensitive paths. Prefer explicit `AsyncWaitSet` + `ReadCondition` for production control flows.
- Services create their own `AsyncWaitSet` and worker threads inside `run()` — they do not assume the calling thread provides any concurrency
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

- **GUI testability:** NiceGUI page functions and `GuiBackend` subclasses are designed with a clear separation between DDS data handling (`GuiBackend` state dicts) and page rendering (`@ui.page` functions). UI logic is tested by instantiating the backend in test mode with injected DDS participants and verifying state dict updates; rendering logic is tested via `nicegui.testing.User`. DDS behavior is tested by injecting data through live test participants.
- **DDS testability:** Applications accept injected DomainParticipants or readers/writers via dependency injection or configuration, enabling tests to substitute real DDS with controlled test participants.
- **C++ testability:** Business logic is separated from DDS entity creation so that unit tests can exercise logic without requiring a Connext license or runtime.

---

## Install Tree & Runtime Environment

The project uses a CMake install step to produce a self-contained install tree. This tree is the contract between the build system and runtime — both local development and Docker containers consume the same structure.

### Install Tree Structure

```
install/
├── bin/                              # C++ executables
├── lib/                              # Project shared libraries
│   ├── libmedtech_foxglove_transf.so  #   (V2) Foxglove Transformation plugin for Routing Service
│   ├── libfoxglove_ws_adapter.so      #   (V2) Foxglove WebSocket Adapter plugin for Routing Service
│   └── libmedtech_mcap_storage.so     #   (V2) MCAP Storage plugin for Recording Service
├── lib/python/site-packages/         # rtiddsgen Python output (flat layout — see §Python Generated Type Packaging)
│   ├── common.py                     #   Common module types
│   ├── surgery.py                    #   Surgery module types
│   ├── monitoring.py                 #   Monitoring module types
│   ├── imaging.py                    #   Imaging module types
│   ├── devices.py                    #   Devices module types
│   ├── clinical_alerts.py            #   ClinicalAlerts module types
│   └── hospital.py                   #   Hospital module types
├── share/
│   ├── qos/                          # Snippets.xml, Patterns.xml, Topics.xml, Participants.xml
│   ├── domains/                      # RoomDatabuses.xml, HospitalDatabuses.xml, CloudDatabuses.xml
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

# Activate Python venv (pip-installed: rti.connext, nicegui, pytest)
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
$_DIR/share/domains/RoomDatabuses.xml;\
$_DIR/share/domains/HospitalDatabuses.xml;\
$_DIR/share/domains/CloudDatabuses.xml"

# Runtime configuration root
export MEDTECH_CONFIG_DIR="$_DIR/etc"
```

> **Observability note:** Monitoring Library 2.0 is enabled entirely via XML properties in the participant QoS profile. No additional environment variables are required in `setup.bash`. Collector Service connection details (host, port) are configured in `Participants.xml`, not environment variables. Docker Compose sets container-specific overrides (e.g., Collector Service hostname) via service environment, not `setup.bash`.

### Local Development Workflow

```bash
# One-time: venv setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Build + install (install prefix defaults to <source>/install/)
# Source rtisetenv first so CMake can find Connext and read CONNEXTDDS_ARCH
source $NDDSHOME/resource/scripts/rtisetenv_x64Linux4gcc8.5.0.bash
cmake -B build -S .
cmake --build build
cmake --install build

# Activate runtime environment (sources rtisetenv + venv + sets all paths)
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
ENV NDDS_QOS_PROFILES="/opt/medtech/share/qos/Snippets.xml;/opt/medtech/share/qos/Patterns.xml;/opt/medtech/share/qos/Topics.xml;/opt/medtech/share/qos/Participants.xml;/opt/medtech/share/domains/RoomDatabuses.xml;/opt/medtech/share/domains/HospitalDatabuses.xml;/opt/medtech/share/domains/CloudDatabuses.xml"
ENV MEDTECH_CONFIG_DIR="/opt/medtech/etc"
```

Docker containers do not use `setup.bash` — they set env vars directly in the Dockerfile or `docker-compose.yml`.

#### Container Build Integrity Rule

C++ binaries and project shared libraries must be compiled inside the Docker build stage using the container's toolchain. Mounting host-compiled binaries into containers (`-v ./install/bin:/opt/medtech/bin`) is prohibited for CI, integration tests, and deployment.

The host-mount pattern is permitted **only** for:

- XML configuration files (QoS, domain, participant XML)
- Python source files during local development iteration
- The RTI license file

Rationale: the host toolchain's GCC/libstdc++ version may differ from the container's runtime libraries, causing ABI mismatches (GLIBCXX_x.y.z not found, segmentation faults from vtable incompatibility). Building inside the container eliminates this class of error entirely.

#### Development Inner Loop

For development iteration without rebuilding the full Docker image, compile inside the build-base container:

```bash
docker run --rm \
  -v "$(pwd)":/workspace \
  -w /workspace \
  medtech/build-base \
  bash -c "cmake -B /tmp/build -S . \
    -DCMAKE_INSTALL_PREFIX=/workspace/install && \
    cmake --build /tmp/build -j && \
    cmake --install /tmp/build"
```

This uses the container's toolchain while writing output to the host filesystem. The resulting `install/` tree is ABI-compatible with the runtime containers.

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

All Dockerfiles use pinned Ubuntu 24.04 LTS as the base (`FROM ubuntu:24.04`). No `latest` tags. All Dockerfiles must use the same Ubuntu LTS release to guarantee ABI consistency across base images. Mixing Ubuntu versions (e.g., 22.04 build-base with 24.04 runtime) risks glibc/libstdc++ mismatches.

| Image | Purpose | Contents |
|-------|---------|----------|
| `build-base` | Compile C++ targets | Ubuntu 24.04, GCC toolchain, CMake, Connext 7.6.0 host libraries (`x64Linux4gcc8.5.0`) |
| `runtime-cpp` | Run compiled C++ apps | Ubuntu 24.04 minimal, Connext 7.6.0 shared libraries only — no compiler |
| `runtime-python` | Run Python apps | Ubuntu 24.04, Python 3.12, project venv, `rti.connext==7.6.0`, NiceGUI |
| `nat-router` | NAT gateway for multi-hospital simulation (V1.4) | Alpine (pinned), iptables pre-installed; env-driven entrypoint configures IP forwarding and MASQUERADE rules via `NAT_WAN_IFACE` and `NAT_PRIVATE_SUBNETS`. No Connext dependency. |

## Testing

| Layer | Framework | Notes |
|-------|-----------|-------|
| C++ unit/integration | Google Test | Linked via CMake `FetchContent` |
| Python unit/integration | pytest | Run from venv |
| DDS integration | pytest + rti.connext | Verifies pub/sub, QoS, partition, filtering behaviors |
| GUI | pytest + nicegui.testing | NiceGUI page and GuiBackend unit tests |
| System/E2E | Docker Compose + pytest | Full multi-container scenario tests |

## Logging Standard

All modules use a consistent, structured logging approach built on the **RTI Connext Logging API** (`rti::config::Logger` in Modern C++, `rti.connextdds.Logger` in Python). Application log messages are written using the logger's **USER** category methods (e.g., `logger.warning(...)`, `logger.notice(...)`). These messages are captured locally and — when Monitoring Library 2.0 is enabled — automatically forwarded through the RTI Observability Framework pipeline to RTI Collector Service, which exports them to Grafana Loki (or an OpenTelemetry Collector) for centralized search and dashboarding.

The native Connext logging API emits user-category messages that Monitoring Library 2.0 collects and forwards to Collector Service alongside middleware telemetry. Application code does not create a participant or topic for logging — Monitoring Library 2.0's dedicated participant on the Room Observability databus handles all telemetry transport.

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
[surgical-procedure] Participant matched on Hospital Integration databus (room/OR-3/procedure/proc-2026-0042)
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
logger.notice("[surgical-procedure] Participant matched on Procedure DDS domain");
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

Monitoring Library 2.0 creates a **dedicated DomainParticipant** on the Room Observability databus to distribute telemetry. This keeps observability traffic isolated from application data on the Procedure and Hospital Integration databuses. The domain ID and optional participant QoS profile are configured in the MONITORING QoS policy:

```xml
<participant_factory_qos>
    <monitoring>
        <enable>true</enable>
        <distribution_settings>
            <dedicated_participant>
                <domain_id>19</domain_id>
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

This configuration is defined once in the shared participant factory QoS profile (via `BuiltinQosSnippetLib::Feature.Monitoring2.Enable` as a base) and applies to all applications. The default Monitoring Library 2.0 domain ID is 2; the medtech suite overrides it to 19 to align with the project's decade-offset domain numbering scheme (see [data-model.md — the Room Observability databus](data-model.md)).

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
2. **Observability stack is CLI-gated.** `medtech run hospital --observability` starts the telemetry backends (Prometheus, Loki, Grafana); the core simulation runs independently.
3. **Collector Service REST API is the runtime control plane.** Log verbosity and metric collection rates are adjusted via REST, not by restarting applications.
4. **Dashboard configurations are version-controlled.** Grafana dashboard JSON and Prometheus scrape configs are stored under `services/observability/`.
5. **No application code depends on observability.** Removing the observability profile must not affect functional behavior.

---

## Project Layout (Target)

```
rti-medtech-suite/
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
│   │   ├── hospital/
│   │   └── foxglove/               # Vendored Foxglove OMG IDL schemas (V2 — plugin build dependency)
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
│   │   ├── digital_twin/           # NiceGUI 3D robot visualization (browser-based)
│   │   └── README.md               # Module purpose, usage, Connext features used
│   ├── hospital-dashboard/         # NiceGUI web application
│   │   └── README.md
│   └── clinical-alerts/            # Clinical Decision Support (ClinicalAlerts module) engine
│       └── README.md
├── services/
│   ├── routing/                    # Routing Service configurations
│   │   └── README.md
│   ├── foxglove-bridge/            # Foxglove Bridge plugins (Transformation + Adapter + Storage) (V2)
│   │   └── README.md
│   ├── recording/                  # RTI Recording Service + RTI Replay Service configurations
│   │   └── README.md
│   ├── discovery/                  # RTI Cloud Discovery Service configurations
│   │   └── README.md
│   └── observability/              # Collector Service config, Prometheus scrape config, Grafana dashboards
│       └── README.md
├── resources/                      # Shared GUI assets (served via NiceGUI static file routes)
│   ├── fonts/                      # Roboto Condensed, Montserrat, Roboto Mono (.ttf)
│   └── images/                     # RTI logo (rti-logo.png, rti-logo.svg)
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
