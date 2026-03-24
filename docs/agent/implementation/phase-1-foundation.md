# Phase 1: Foundation

**Goal:** Establish the build system, shared data model (IDL + QoS), Docker simulation infrastructure, Python environment, and test harness. Nothing module-specific is built here — this phase produces the platform that all modules depend on.

**Depends on:** Nothing
**Blocks:** Phase 2, Phase 3, Phase 4

---

## Step 1.1 — Project Skeleton & CMake Build ✅ `5afc0d7`

### Work

- Create top-level `CMakeLists.txt` with `CONNEXT_VERSION` and `CONNEXT_ARCH` cache variables (see `vision/technology.md` Connext Version Management), C++17 standard, Release build type, shared libraries, and install prefix defaulting to `<source>/install/` via `CMAKE_INSTALL_PREFIX_INITIALIZED_TO_DEFAULT` (see `vision/technology.md` Default Build Configuration)
- Source Connext environment: `source $NDDSHOME/resource/scripts/rtisetenv_${CONNEXT_ARCH}.bash`
- Integrate `rticonnextdds-cmake-utils` via `FetchContent` (main branch)
- Call `find_package(RTIConnextDDS "${CONNEXT_VERSION}" REQUIRED)` — version must reference the CMake variable, never a literal
- C++ targets must link against the `RTIConnextDDS::cpp2_api` imported target (Modern C++ API)
- Create `interfaces/` directory with stub `CMakeLists.txt`
- Create `modules/` directory structure with stub `CMakeLists.txt` per module
- Create `tests/` directory structure
- Create `resources/` directory with shared GUI assets (see `vision/technology.md` GUI Design Standard):
  - `resources/fonts/` — bundle Roboto Condensed, Montserrat, and Roboto Mono `.ttf` files
  - `resources/images/` — RTI logo (`rti-logo.png`, `rti-logo.svg`)
  - `resources/styles/medtech.qss` — shared Qt stylesheet implementing the RTI color palette, typography, and layout conventions
- Author `requirements.txt` at the project root with pinned versions for all Python dependencies:
  - `rti.connext` — pin to the version matching Connext 7.6.0 (e.g., `rti.connext==7.6.0`)
  - `PySide6` — pin major.minor (e.g., `PySide6==6.7.*`)
  - `pytest` — pin major.minor (e.g., `pytest==8.2.*`)
  - `pytest-qt` — pin major.minor (e.g., `pytest-qt==4.4.*`)
  - `black` — pin major (e.g., `black==24.*`)
  - `isort` — pin major.minor (e.g., `isort==5.13.*`)
  - `ruff` — pin minor (e.g., `ruff==0.5.*`)
  - Use `==` pins (not `>=`) so every agent session installs the same environment. Exact patch versions will be resolved at authoring time — the examples above are illustrative.
- Create Python venv setup: `python3 -m venv .venv && pip install -r requirements.txt`
- Generate `setup.bash` via `configure_file()` and add `install(FILES setup.bash DESTINATION .)` — the script sources the venv, adds `bin/` and `lib/` to `PATH`/`LD_LIBRARY_PATH`, sets `PYTHONPATH` to `lib/python/site-packages/`, assembles `NDDS_QOS_PROFILES` from the install tree, and exports `MEDTECH_CONFIG_DIR` (see `vision/technology.md` Install Tree & Runtime Environment)
- Create the project root `README.md` with:
  - Project description
  - **Platform Support Matrix** (Linux x86-64 supported; Windows, macOS, QNX planned V3.0) — updated as platform support progresses
  - System requirements table (RTI Connext 7.6.0, GCC 8.5+, CMake 3.16+, Python 3.10+, Docker, Docker Compose)
  - Compiler/toolchain support (C++17, `x64Linux4gcc8.5.0`)
  - Quick-start build/install workflow
  - Pointer to `docs/agent/` for detailed planning documentation
- Create `.markdownlint.json` at the project root with the active ruleset per [vision/documentation.md](../vision/documentation.md) (line length 100, code blocks/tables/headings exempt, all rules enabled by default)
- Create `tests/lint/check_readme_sections.py` — a lint script that verifies the seven required README sections are present and in order per [vision/documentation.md](../vision/documentation.md). The script exits non-zero if any README under `modules/` or `services/` is non-compliant.
- Verify CMake configure + build + install succeeds with no targets (skeleton only)
- Verify `source install/setup.bash` activates the complete runtime environment

### Test Gate

- [x] `cmake -B build -S .` configures without errors
- [x] `cmake --build build` succeeds (no-op build, no source yet)
- [x] `cmake --install build` populates `install/` with `setup.bash` and empty directory structure
- [x] `source install/setup.bash` completes without errors and sets `NDDS_QOS_PROFILES`, `MEDTECH_CONFIG_DIR`, `PATH`, `LD_LIBRARY_PATH`, `PYTHONPATH`
- [x] `.venv/bin/python -c "import rti.connext"` succeeds
- [x] `.venv/bin/python -c "import PySide6"` succeeds

---

## Step 1.2 — IDL Type Definitions ✅ `208cc6d`

### Work

- Author IDL files under `interfaces/idl/` per the module structure in [vision/data-model.md](../vision/data-model.md):
  - `common.idl` — `Time_t`, `EntityIdentity`, bounded string typedefs
  - `surgery.idl` — `RobotCommand`, `RobotState`, `SafetyInterlock`, `OperatorInput`, `ProcedureContext`, `ProcedureStatus`
  - `monitoring.idl` — `PatientVitals`, `WaveformData`, `AlarmMessages`
  - `imaging.idl` — `CameraFrame`
  - `devices.idl` — `DeviceTelemetry`
  - `clinical_alerts.idl` — `ClinicalAlert`, `RiskScore` (module ClinicalAlerts — Clinical Decision Support)
  - `hospital.idl` — `ResourceAvailability`
- Add `connextdds_rtiddsgen_run()` calls in `interfaces/CMakeLists.txt` to generate C++ and Python type support from IDL
  - Use `-language C++11` and `-standard IDL4_CPP` for all C++ code generation targets (explicit even if IDL4_CPP is the default)
  - Use `-language Python` for Python code generation targets
  - Output is placed in the CMake build directory; the source tree is not modified
- Verify generated code compiles (C++) and imports (Python)

### Test Gate

- [x] `cmake --build build` generates type-support code from all IDL files without errors
- [x] C++ generated headers compile: a minimal C++ test file includes each generated header
- [x] `cmake --install build` installs generated Python modules into `install/lib/python/site-packages/` with `__init__.py` markers
- [x] Python generated modules import after sourcing `setup.bash`: `python -c "import surgery; print(surgery.Surgery.RobotCommand)"` for each module
- [x] Type instantiation works: `python -c "import surgery; cmd = surgery.Surgery.RobotCommand(); print(cmd)"`

---

## Step 1.3 — QoS Profile Library ✅ `10f7c6b`

### Work

- Author the four QoS XML files under `interfaces/qos/` per the structure in [vision/data-model.md](../vision/data-model.md):
  - `Snippets.xml` — isolated, composable QoS policy chunks (Reliable, BestEffort, TransientLocal, Volatile, KeepLast1, KeepLast4, KeepAll, ExclusiveOwnership, Liveliness2s, GuiSubsample)
  - `Patterns.xml` — data-pattern base profiles (State, Command, Stream, GuiState, GuiStream) rooted on `BuiltinQosLib::Generic.Common`
  - `Topics.xml` — topic-filter-bound profiles that assign QoS by topic name pattern
  - `Participants.xml` — discovery, transport, and resource configuration (simulation profile: SHMEM disabled, UDPv4 only, explicit peers, no multicast)
- Each XML file must declare the RTI schema in its root element for validation:
  ```xml
  <dds xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:noNamespaceSchemaLocation="https://community.rti.com/schema/7.6.0/rti_dds_profiles.xsd">
  ```
- Validate all QoS XML files against the RTI online XSD schema (`rti_dds_profiles.xsd`). Do not use `rtiddsgen` for XML validation.
- Author the domain library XML under `interfaces/domains/` with the same schema declaration
- Configure `NDDS_QOS_PROFILES` environment variable to load all XML files in dependency order at runtime. This is the mechanism by which applications discover QoS profiles — no application code hardcodes XML file paths:
  ```bash
  export NDDS_QOS_PROFILES="interfaces/qos/Snippets.xml;interfaces/qos/Patterns.xml;interfaces/qos/Topics.xml;interfaces/qos/Participants.xml;interfaces/domains/domains.xml"
  ```
- All applications must use the default QosProvider:
  - C++: `dds::core::QosProvider::Default()`
  - Python: `dds.QosProvider.default`
- Enable **Monitoring Library 2.0** on all DomainParticipants via XML properties in `Participants.xml` (see `vision/technology.md` Observability Standard). This requires no application code changes — telemetry collection is activated by the QoS profile.
- Install/stage QoS XML files via CMake so they are locatable at runtime in both local and Docker contexts

### Test Gate

- [x] All QoS XML files validate against `https://community.rti.com/schema/7.6.0/rti_dds_profiles.xsd` with zero errors
- [x] Domain library XML validates against the same schema
- [x] A minimal C++ program using `dds::core::QosProvider::Default()` loads all profiles via `NDDS_QOS_PROFILES` without errors
- [x] A minimal Python program using `dds.QosProvider.default` loads all profiles via `NDDS_QOS_PROFILES` without errors
- [x] Topic-filter resolution works: creating a DataWriter on topic `PatientVitals` with `NDDS_QOS_PROFILES` set resolves to the State pattern QoS automatically

---

## Step 1.3b — DDS Design Review via rti-chatbot-mcp ✅ `98d1306`

### Work

- Submit the following artifacts to `rti-chatbot-mcp` for design review per [workflow.md](../workflow.md) Section 8:
  - All IDL type definitions under `interfaces/idl/`
  - QoS XML hierarchy (`Snippets.xml`, `Patterns.xml`, `Topics.xml`, `Participants.xml`)
  - Domain library XML (`interfaces/domains/domains.xml`)
  - Publication model assignments from `vision/data-model.md`
- Review focus areas:
  - QoS compatibility across all writer/reader profile pairs (RxO policy matching)
  - Domain tag and domain partition configuration correctness
  - IDL type design: key field selection, bounded types, extensibility annotations, sentinel-first enums
  - Transport and discovery configuration for the Docker multi-network topology (UDPv4, Cloud Discovery Service)
  - Topic-filter QoS resolution — verify that topic names resolve to the intended QoS profiles
- Address any findings identified by `rti-chatbot-mcp`:
  - Correct QoS incompatibilities, type design issues, or configuration problems
  - If findings require architectural changes (domain layout, topic restructuring), escalate to operator per workflow.md Section 5
  - Re-submit affected artifacts after corrections
- Record the review summary (findings + resolutions) as a commit message or in `docs/agent/incidents.md` if significant

### Test Gate

- [x] `rti-chatbot-mcp` review completed for all artifacts
- [x] All identified QoS compatibility issues resolved
- [x] All identified type design issues resolved
- [x] All identified transport/discovery configuration issues resolved
- [x] If re-review was needed after changes, re-review completed with no remaining issues

---

## Step 1.4 — Docker Infrastructure ✅ `d73faff` (INC-005 partially resolved in Step 1.5)

### Work

- Define Docker base images (each with `ARG CONNEXT_VERSION=7.6.0` — all version-dependent paths derive from this ARG):
  - **Build base** (`docker/build-base.Dockerfile`): Ubuntu 22.04 LTS, GCC toolchain, CMake, Connext host libraries for the target architecture. Used for compiling C++ targets.
  - **C++ runtime base** (`docker/runtime-cpp.Dockerfile`): Ubuntu 22.04 LTS minimal, Connext shared libraries only. No compiler toolchain. Used for running compiled C++ applications.
  - **Python runtime base** (`docker/runtime-python.Dockerfile`): Ubuntu 22.04 LTS + Python 3.10, project venv, `rti.connext` (version from ARG), PySide6. Used for running Python applications.
- All base images must pin their Ubuntu version (`FROM ubuntu:22.04`) — no `latest` tags
- Create `docker-compose.yml` with network definitions:
  - `surgical-net` — surgical LAN simulation
  - `hospital-net` — hospital backbone simulation
- Docker Compose must set `NDDS_QOS_PROFILES` as an environment variable for all service containers, pointing to the mounted/copied QoS and domain XML files
- Add **Observability Framework** services behind a Docker Compose profile (`--profile observability`):
  - **Collector Service** container on `hospital-net` — RTI Collector Service configured to receive telemetry from all instrumented participants and forward to Prometheus and Grafana Loki
  - **Prometheus** container on `hospital-net` — scrapes metrics from Collector Service
  - **Grafana Loki** container on `hospital-net` — receives logs and security events from Collector Service
  - **Grafana** container on `hospital-net` — loads RTI Observability Dashboards, connected to Prometheus and Loki data sources
  - Store Collector Service configuration, Prometheus scrape config, and Grafana dashboard JSON under `services/observability/`
- Add **Cloud Discovery Service** container using the official RTI Docker Hub image `rticom/cloud-discovery-service` (see [system-architecture.md](../vision/system-architecture.md) — Docker Hub Image Policy):
  - Attach to `hospital-net` (primary) and `surgical-net` (allows all participants direct discovery access)
  - Configure the listening port (default 7400) and the domains it serves (the Procedure domain and the Hospital domain)
  - Store Cloud Discovery Service configuration under `services/cloud-discovery-service/`
  - Define a health check: TCP port check on port 7400 (`test: ["CMD", "nc", "-z", "localhost", "7400"]`)
  - All other application and infrastructure containers must declare `depends_on: cloud-discovery-service: condition: service_healthy` so Cloud Discovery Service starts first (see [system-architecture.md](../vision/system-architecture.md) — Docker Compose Service Startup Ordering)
- Create placeholder service entries (no real apps yet, just verify networking)
- Verify containers can ping each other on the correct networks and are isolated across networks

### Test Gate

- [x] `docker compose build` succeeds for all base images
- [x] `docker compose up` starts placeholder containers — CDS resolved via custom Dockerfile (INC-005)
- [x] Container on `surgical-net` can reach other containers on `surgical-net`
- [x] Container on `surgical-net` cannot reach containers on `hospital-net` (unless dual-homed)
- [x] `NDDS_QOS_PROFILES` is set and QoS XML files are accessible inside each container
- [x] Cloud Discovery Service container starts and passes its UDP health check on port 7400 — resolved via custom Dockerfile wrapping local `$NDDSHOME` binary (INC-005)
- [x] Cloud Discovery Service is reachable from both `surgical-net` and `hospital-net` containers
- [x] Application placeholder containers do not start until Cloud Discovery Service is healthy (`depends_on` ordering verified)
- [x] `docker compose --profile observability up` starts Collector Service, Prometheus, Grafana Loki, and Grafana — all services start and run (INC-005 resolved)
- [x] Grafana is accessible at its configured port and loads the RTI Observability Dashboards (38 dashboards loaded)
- [x] Prometheus targets page shows Collector Service as a scrape target — status `up`

---

## Step 1.5 — Test Harness & Common Behaviors

### Work

- Set up pytest with project-level `conftest.py` providing DDS fixtures:
  - `participant(domain_id, partition)` — creates a participant with test QoS and partition
  - `writer(participant, topic, qos_profile)` — creates a DataWriter
  - `reader(participant, topic, qos_profile)` — creates a DataReader
  - Automatic cleanup of all DDS entities after each test
- Set up C++ test framework (Google Test) with CMake integration via `FetchContent`
- Implement tests for **common-behaviors.md** specs that can run with the foundation:
  - Partition isolation (same partition matches, different partition doesn't)
  - Wildcard partition aggregation
  - Domain isolation (Procedure domain vs Hospital domain — no cross-talk)
  - QoS enforcement: deadline missed, liveliness lost, lifespan expiry, KEEP_LAST behavior
  - Durability: TRANSIENT_LOCAL late joiner, VOLATILE no history
  - Exclusive ownership: higher strength preferred, failover on liveliness loss, primary reclaim

### Test Gate

- [x] `pytest tests/integration/test_partition_isolation.py` — all partition scenarios pass
- [x] `pytest tests/integration/test_domain_isolation.py` — domain isolation scenarios pass
- [x] `pytest tests/integration/test_qos_enforcement.py` — deadline, liveliness, lifespan, history scenarios pass
- [x] `pytest tests/integration/test_durability.py` — TRANSIENT_LOCAL and VOLATILE scenarios pass
- [x] `pytest tests/integration/test_exclusive_ownership.py` — ownership and failover scenarios pass
- [x] All tests run from project root with a single command: `pytest tests/`

---

## Step 1.6 — Shared GUI Bootstrap (`medtech_gui`)

### Work

- Create the `medtech_gui` Python package under `modules/shared/medtech_gui/`
- Implement `init_theme(app: QApplication)` per [vision/technology.md](../vision/technology.md) GUI Design Standard:
  - Loads `resources/styles/medtech.qss` and applies it to the QApplication
  - Registers bundled fonts (Roboto Condensed, Montserrat, Roboto Mono) via `QFontDatabase`
  - Creates and returns a header widget with RTI Blue (`#004C97`) background, white text, left-aligned RTI logo
- Add CMake install rule to place the package in `lib/python/site-packages/medtech_gui/`
- The package must be importable after `source install/setup.bash`

### Test Gate

- [x] `python -c "from medtech_gui import init_theme"` succeeds after install
- [x] `init_theme(app)` loads the stylesheet without errors (pytest-qt test)
- [x] Fonts are registered and available after `init_theme()` call
- [x] Header widget renders with correct background color and logo

---

## Step 1.7 — Logging Initialization Utility

### Work

- Create a shared logging utility module (Python: `medtech_logging`; C++: header-only or static library)
- **Python** — provide `init_logging(module_name)` that:
  - Returns the `rti.connextdds.Logger.instance` singleton for application use
  - Does **not** set any verbosity — verbosity is configured entirely via QoS XML (`<participant_factory_qos><logging>`) loaded at startup
- **C++** — provide `medtech::init_logging(module_name)` that:
  - Returns a reference to `rti::config::Logger::instance()` for application use
  - Does **not** set any verbosity — verbosity is configured entirely via QoS XML
- Define module name prefixes per module (must match directory names per [vision/technology.md](../vision/technology.md)):
  - `"surgical-procedure"`, `"hospital-dashboard"`, `"clinical-alerts"`
- Add QoS XML configuration for logger verbosity and user log forwarding in the default participant-factory QoS profile:
  - Set `<logging><verbosity>WARNING</verbosity></logging>` in `<participant_factory_qos>` (the `LOGGING` QoS policy)
  - Set `<user_forwarding_level>NOTICE</user_forwarding_level>` in the `<monitoring>` section of the same profile
- No additional CMake components required — the Connext Logging API is part of the core library

### Test Gate

- [x] Python: `init_logging("surgical-procedure")` returns the Logger singleton without errors
- [x] C++: `medtech::init_logging("surgical-procedure")` returns the Logger reference without errors
- [x] Logger verbosity is controlled by QoS XML — no programmatic `verbosity()` or `verbosity_by_category()` calls exist in module code
- [x] A user-category log message written via the Connext Logging API is forwarded by Monitoring Library 2.0 and received by Collector Service
- [x] Module name prefix appears correctly in the forwarded log message

---

## Step 1.8 — CI Pipeline & Quality Gate Automation

### Work

- Create `scripts/ci.sh` (bash — target environments are Linux-only: Docker containers and WSL dev machines) that runs all quality gates from [workflow.md](../workflow.md) Section 7 in sequence:
  1. `cmake -B build -S . && cmake --build build && cmake --install build` — clean build + install
  2. `pytest tests/` — full test suite (zero failures, zero skips)
  3. `markdownlint modules/*/README.md services/*/README.md` — README lint
  4. `python tests/lint/check_readme_sections.py` — section order lint
  5. `grep` checks for prohibited patterns: QoS setter API calls in application code, literal domain IDs (10, 11) in application code, `print()`/`printf`/`std::cout` in application code
  6. Verify no generated files in source tree
  7. `black --check modules/ tests/` + `isort --check modules/ tests/` + `ruff check modules/ tests/` — Python code style per `vision/coding-standards.md` (scoped to source dirs, excluding build artifacts and `.venv`)
  8. `python tests/performance/benchmark.py` — performance benchmark against latest baseline (from Phase 2 onward; Phase 1 produces the harness only)
- The script must exit non-zero on the first gate failure
- Document how to run the full gate check locally: `make ci` or `bash scripts/ci.sh`

### Test Gate

- [x] `make ci` (or equivalent) runs all quality gates end-to-end
- [x] A deliberately introduced violation (e.g., a `print()` call) causes the gate to fail
- [x] Gate passes on the clean foundation with no violations

---

## Step 1.9 — Performance Benchmark Harness

### Work

- Create the benchmark harness under `tests/performance/` per [vision/performance-baseline.md](../vision/performance-baseline.md):
  - `benchmark.py` — main harness: orchestrates workload timing (warm-up, measurement, cool-down), queries Prometheus via HTTP API, compares results against baseline, produces JSON output
  - `metrics.py` — metric definitions (IDs L1–L6, T1–T6, R1–R5) with PromQL query templates, units, and regression threshold configuration
  - `baselines/` directory with `.gitkeep`
  - `conftest.py` — pytest fixtures for `@benchmark`-tagged tests
- Implement the Prometheus query interface:
  - Configure via `PROMETHEUS_URL` environment variable (default `http://localhost:9090`)
  - Use `/api/v1/query_range` for rate/histogram queries over the measurement window
  - Use `/api/v1/query` for point-in-time metrics (participant count, endpoint count)
- Implement baseline comparison logic:
  - Load the lexicographically latest baseline from `tests/performance/baselines/`
  - Compare each metric against its threshold (per vision document tier tables)
  - Report PASS / FAIL / NEW / REMOVED per metric
  - Exit code 0 (all pass), 1 (regression), 2 (infrastructure error)
- Implement `--record --phase <name>` mode for baseline recording
- Implement `--baseline <path>` for explicit baseline comparison
- Add `@benchmark` tag to `spec/README.md` tag table
- Add `PROMETHEUS_URL` to Docker Compose environment and `setup.bash`
- Note: the harness cannot run a meaningful benchmark at Phase 1 (no real publishers yet), but the harness itself must be testable with a mock Prometheus or unit tests of the comparison logic

### Test Gate (spec: performance-baseline.md — Benchmark Execution, Baseline Recording, Regression Detection)

- [ ] `python tests/performance/benchmark.py --help` runs without errors
- [ ] Comparison logic correctly reports PASS for a metric within threshold (unit test)
- [ ] Comparison logic correctly reports FAIL for a metric exceeding threshold (unit test)
- [ ] Comparison logic correctly reports NEW for a metric not in baseline (unit test)
- [ ] Comparison logic correctly reports REMOVED for a baseline metric not in current run (unit test)
- [ ] `T6` (deadline missed) comparison enforces absolute zero threshold (unit test)
- [ ] `R1`/`R2` comparison enforces exact match (unit test)
- [ ] `L6` (discovery time) comparison enforces both percentage and hard cap (unit test)
- [ ] Harness exits with code 2 when Prometheus is unreachable
- [ ] `--record --phase test` writes a valid JSON file to `tests/performance/baselines/test.json`
- [ ] First run with no baseline reports all metrics as NEW and exits 0

---

## Step 1.10 — QoS Compatibility Checker & Tool Scaffolding

### Work

- Create `tools/` directory at the project root with `tools/README.md` indexing all available diagnostic tools per [vision/tooling.md](../vision/tooling.md)
- Implement `tools/qos-checker.py` — QoS compatibility pre-flight checker:
  - Loads all QoS XML via `NDDS_QOS_PROFILES` using the default QosProvider
  - For each topic defined in the domain library, resolves the writer and reader QoS via topic filter
  - Checks RxO (Requested/Offered) policy compatibility for each writer/reader pair
  - Reports any incompatible pairs with the specific policy mismatch
  - Supports `--verbose` mode showing resolved QoS details per topic
  - Exit code 0 (all compatible), 1 (incompatibilities found)
- Add `tools/qos-checker.py` as a quality gate step in the CI pipeline (`scripts/ci.sh` or `Makefile`)
- Create placeholder files for RTI tool usage guides:
  - `tools/admin-console.md` — connection guide for RTI Admin Console with this project's Docker topology
  - `tools/dds-spy.md` — `rtiddsspy` usage examples for each domain
- Note: `tools/medtech-diag/` and `tools/partition-inspector.py` are implemented in Phase 2 when DDS entities exist to inspect

### Test Gate

- [ ] `python tools/qos-checker.py` runs against the Step 1.3 QoS XML and reports all topic pairs as compatible
- [ ] A deliberately introduced QoS incompatibility (e.g., RELIABLE writer + BEST_EFFORT reader on a State pattern topic) causes the checker to report FAIL and exit 1
- [ ] `tools/README.md` exists and indexes all tools
- [ ] CI pipeline includes the QoS compatibility check
