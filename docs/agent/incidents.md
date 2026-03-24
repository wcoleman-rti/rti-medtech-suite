# Incident Log

This file records incidents discovered during implementation.
See [workflow.md](workflow.md) Section 5 for the incident recording
process and format.

Incidents are numbered sequentially and are never deleted, even
after closure. They form the project's decision log.

---

## INC-001: rti.connext pip package vs rti.connextdds runtime import

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-23
- **Phase/Step:** Phase 1 / Step 1.1
- **Documents involved:** `vision/technology.md`, `implementation/phase-1-foundation.md`
- **Description:** The pip package is named `rti.connext` (installed via
  `pip install rti.connext==7.6.0`), but the runtime Python import is
  `rti.connextdds` (i.e., `import rti.connextdds as dds`). The import
  `import rti.connext` raises `ModuleNotFoundError`. This is the expected
  RTI packaging convention — the pip distribution name and the importable
  module name differ. Phase 1 test gate language
  (`.venv/bin/python -c "import rti.connext"`) uses the pip package name
  rather than the importable module name.
- **Possible resolutions:**
  1. Treat the test gate literally and consider `import rti.connextdds`
     as satisfying the intent (validate that the Connext Python package
     is installed and functional).
  2. Request a spec clarification to update the test gate wording.
- **Resolution:** Resolution 1 adopted. The test gate intent is to confirm
  the Connext Python package is installed and usable.
  `import rti.connextdds` succeeds and is the correct runtime import.
  All application code and future tests use `import rti.connextdds as dds`
  per the RTI API convention documented in `vision/technology.md`.
- **Date closed:** 2026-03-23

---

## INC-002: Python codegen sys.path.append breaks flat install layout

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-23
- **Phase/Step:** Phase 1 / Step 1.2
- **Documents involved:** `interfaces/CMakeLists.txt`,
  `vision/technology.md`
- **Description:** By default, `rtiddsgen -language Python` emits
  `sys.path.append(os.path.join(os.path.dirname(__file__), '<dep>/')))`
  and `from <dep> import *` at the top of each generated `.py` file.
  These stanzas assume that dependent IDL modules are in subdirectories
  relative to the importing file (e.g., `surgery/common/common.py`).
  When all generated files are installed flat into
  `lib/python/site-packages/` (as required by the install tree spec),
  the relative path does not resolve and imports fail with
  `NameError: name 'Common' is not defined`.
- **Possible resolutions:**
  1. Use the `-noSysPathGeneration` rtiddsgen flag to suppress the
     `sys.path.append` stanzas. Imports then resolve via `PYTHONPATH`
     which already includes the install `site-packages` directory.
  2. Restructure the install tree to mirror rtiddsgen's expected
     subdirectory layout (rejected — violates the flat
     `site-packages` convention in `vision/technology.md`).
- **Resolution:** Resolution 1 adopted. Added
  `EXTRA_ARGS -noSysPathGeneration` to the Python
  `connextdds_rtiddsgen_run()` calls in `interfaces/CMakeLists.txt`.
  See RTI documentation:
  <https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/connext_dds_professional/code_generator/users_manual/code_generator/users_manual/GeneratingCode.htm#4.1.4.2_Python_Import_Path>
- **Date closed:** 2026-03-23

---

## INC-003: QosProvider topic-aware QoS resolution — correct API names

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-23
- **Phase/Step:** Phase 1 / Step 1.3
- **Documents involved:** `vision/data-model.md`
- **Description:** The data model document (QoS Assigned to Topics via
  Topic Filters section) references "topic-aware QoS APIs" using the
  generic names `create_datawriter_with_profile` /
  `create_datareader_with_profile` and "QosProvider with topic name"
  without specifying the concrete method signatures. During Step 1.3
  testing, the implementing agent attempted non-existent methods like
  `datawriter_qos_from_profile()`. The correct Python API methods for
  topic-filter QoS resolution via the QosProvider are:
  - Named profile: `provider.datawriter_qos_from_profile(profile)`
  - Named profile + topic filter: `provider.set_topic_datawriter_qos(profile, topic_name)`
  - Default profile + topic filter: `provider.get_topic_datawriter_qos(topic_name)`
  - Participant: `provider.participant_qos_from_profile(profile)`
  - (Reader equivalents: `datareader_qos_from_profile`, `set_topic_datareader_qos`, `get_topic_datareader_qos`)
  The C++ equivalents (RTI extension) are:
  - `provider->datawriter_qos_w_topic_name(profile, topic_name)`
  - `provider->datareader_qos_w_topic_name(profile, topic_name)`
  Source: rti-chatbot-mcp (RTI Connext Python API 7.6.0 documentation).
- **Possible resolutions:**
  1. Update `vision/data-model.md` to include the concrete method names
     alongside the generic description.
  2. Leave the doc as-is and rely on incident documentation.
- **Resolution:** Resolution 1 adopted. Updated
  `vision/data-model.md` QoS Assigned to Topics via Topic Filters
  section with the concrete Python and C++ method names.
- **Date closed:** 2026-03-23

---

## INC-004: DDS Design Review findings (Step 1.3b via rti-chatbot-mcp)

- **Status:** Closed
- **Category:** Design Review
- **Date opened:** 2026-03-23
- **Phase/Step:** Phase 1 / Step 1.3b
- **Documents involved:** IDL files, `Topics.xml`, `Participants.xml`,
  `domains.xml`, `vision/data-model.md`
- **Description:** Submitted all IDL, QoS XML, and domain XML artifacts
  to `rti-chatbot-mcp` for design review. Six findings identified:
  - **F1 (Fixed):** `@key EntityIdentity patient` includes mutable `name`
    field in the DDS key. Changed to `@key EntityId patient_id` with
    non-key `EntityIdentity patient` where needed. Affected types:
    `PatientVitals`, `WaveformData`, `AlarmMessage`, `RiskScore`.
  - **F2 (Declined):** Chatbot recommended removing `@appendable` from
    enums. Per RTI XTypes spec Section 2.2, enums *can* be appendable.
    Kept `@appendable` on enums to allow adding constants in future
    versions.
  - **F3 (Fixed):** Stream/command topics inherited from State base
    profile, leaving unwanted TransientLocal/Liveliness. Added explicit
    `base_name` attribute on every `<datawriter_qos>`/`<datareader_qos>`
    tag to declare the correct pattern per topic. Removed profile-level
    `base_name` to eliminate implicit inheritance. Confirmed approach
    with `rti-chatbot-mcp`.
  - **F4 (Fixed):** Removed explicit `initial_peers` from
    `Participants.xml`. UDPv4 mask already nullifies SHMEM default peer.
    Default discovery peers are sufficient.
  - **F5 (Confirmed):** Monitoring Library 2.0 configuration on domain 20
    is correct.
  - **Additional (Fixed):** `CartesianPosition` changed to `@final`
    (stable 3-field struct). `AlarmMessages` refactored to per-alarm
    keying as `AlarmMessage` (singular type, `@key alarm_id`). Topic
    name kept as `AlarmMessages` for spec compatibility. All topics
    in Procedure and Hospital domains now have explicit topic-filter
    entries in Topics.xml (including previously implicit state topics:
    AlarmMessages, DeviceTelemetry, ProcedureContext, ProcedureStatus).
    GuiProcedureTopics and GuiHospitalTopics also made fully explicit.
- **Resolution:** All actionable findings addressed. Tests pass
  (C++ 15/15, Python 19/19). IDL codegen and type imports verified.
- **Date closed:** 2026-03-23

---

## INC-005: RTI license missing CDS and Collector Service features

- **Status:** Closed
- **Category:** Environment / Licensing
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.4
- **Documents involved:** `docker-compose.yml`,
  `services/cloud-discovery-service/CloudDiscoveryService.xml`,
  `docker/cloud-discovery-service.Dockerfile`
- **Description:** The RTI license file at `/opt/rti.com/rti_license.dat`
  contains `RTIPRO` and `RTISECURITY` features but does not include the
  Cloud Discovery Service or Collector Service feature licenses. The
  Docker Hub image `rticom/cloud-discovery-service` required a
  feature-specific license and refused to start.
- **Impact:** Docker infrastructure was otherwise complete and verified:
  base images build successfully, Docker networks provide correct
  isolation, QoS XML files are mounted and accessible.
- **CDS Resolution (Step 1.5):** Replaced the Docker Hub image
  `rticom/cloud-discovery-service:latest` with a custom Dockerfile
  (`docker/cloud-discovery-service.Dockerfile`) that wraps the local
  CDS binary from `$NDDSHOME/resource/app/bin/<arch>/rticlouddiscoveryserviceapp`
  and its 9 required shared libraries. The local binary ships with
  RTI Connext Professional and works with the `RTIPRO` license — no
  separate CDS feature license is needed. CDS container starts, passes
  UDP health check on port 7400, is reachable from both `surgical-net`
  and `hospital-net`, and placeholder containers successfully wait for
  CDS health before starting.
- **Collector Service Resolution:** The Docker Hub image
  `rticom/collector-service:7.6.0` works with the `RTIPRO` license
  ("Connext Professional" per the RTI container licensing table —
  no additional feature license needed for non-secure, non-WAN usage).
  Verified: container starts on Docker bridge network, Prometheus
  exporter listens on TCP 19090, control server on TCP 19098,
  Prometheus scrape target reports `up`. Full observability stack
  (`docker compose --profile observability up`) starts all services
  successfully.
- **Date closed:** 2026-03-24

---

## INC-006: Fetch resources at configure time — do not commit binaries

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.6
- **Documents involved:** `resources/fonts/CMakeLists.txt`,
  `CMakeLists.txt`
- **Description:** Google Fonts TTF files (Roboto Condensed, Montserrat,
  Roboto Mono) were initially committed directly to the source tree under
  `resources/fonts/`. This inflated the repository with ~0.5 MB of binary
  data and made provenance tracking harder. Since these fonts are freely
  available from a stable upstream (GitHub `google/fonts`), they can be
  fetched reproducibly at CMake configure time with SHA-256 verification.
- **Resolution:** Moved font acquisition to `resources/fonts/CMakeLists.txt`
  using `file(DOWNLOAD)` with pinned commit SHA and per-file SHA-256
  hashes. TTF files download to `${CMAKE_CURRENT_BINARY_DIR}/downloaded/`
  (not the source tree) and are installed from there. A `.gitignore` in
  `resources/fonts/` prevents accidental re-commit. This pattern should
  be used for any future fetchable binary assets.
- **Guideline:** Prefer `file(DOWNLOAD)` with hash verification for
  static assets and `FetchContent` for CMake/C++ dependencies. Always
  pin to a specific commit or tag — never `main` or `latest` for
  reproducibility-critical artifacts. Document every fetched component
  in `THIRD_PARTY_NOTICES.md`.
- **Date closed:** 2026-03-24

---

## INC-007: Guard test infrastructure behind BUILD\_TESTING

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.6
- **Documents involved:** `CMakeLists.txt`
- **Description:** GoogleTest was fetched unconditionally via
  `FetchContent` and test subdirectories were always added, even when
  the build was not intended to produce tests (e.g., a release or
  install-only build). This wasted configure/build time and pulled in
  unnecessary dependencies.
- **Resolution:** Wrapped GoogleTest `FetchContent_Declare` /
  `FetchContent_MakeAvailable` and all `add_subdirectory(tests/...)`
  calls inside `if(BUILD_TESTING)` using the standard CMake
  `include(CTest)` pattern. When configured with
  `-DBUILD_TESTING=OFF`, no test framework is fetched and no test
  targets are generated. Verified: `BUILD_TESTING=ON` builds and runs
  all tests; `BUILD_TESTING=OFF` produces only `medtech_types` and
  `medtech_types_python` targets.
- **Guideline:** All future test-only dependencies (test frameworks,
  mock libraries, test data generators) must be placed inside the
  `if(BUILD_TESTING)` guard. Test subdirectories added in later phases
  follow the same pattern.
- **Date closed:** 2026-03-24

---

## INC-008: PySide6 variable font family names include foundry tags

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.6
- **Documents involved:** `modules/shared/medtech_gui/_theme.py`,
  `tests/gui/test_init_theme.py`
- **Description:** When loading variable-weight TTF fonts via
  `QFontDatabase.addApplicationFont()`, Qt/PySide6 reports the font
  family name with a foundry tag suffix. For example, `RobotoMono.ttf`
  (variable weight) registers as `"Roboto Mono [pyrs]"` or
  `"Roboto Mono [GOOG]"` instead of the plain `"Roboto Mono"` that
  non-variable (static) fonts would produce. This affects font lookup
  and test assertions.
- **Resolution:** Tests use `startswith("Roboto Mono")` matching
  rather than exact string equality. Application code that sets font
  families should use `QFont("Roboto Mono")` which Qt resolves
  correctly regardless of the foundry tag. This quirk applies to all
  variable-weight fonts — static-weight fonts are unaffected.
- **Date closed:** 2026-03-24

---

## INC-009: CMake binary dir leak when installing downloaded resources

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.6
- **Documents involved:** `resources/fonts/CMakeLists.txt`
- **Description:** When using `CMAKE_CURRENT_BINARY_DIR` directly as
  the download destination and then installing from that directory with
  `install(DIRECTORY ...)`, CMake's own `CMakeFiles/` subdirectory was
  included in the install tree. This leaked build system internals into
  the install prefix.
- **Resolution:** Download files to a dedicated subdirectory
  (`${CMAKE_CURRENT_BINARY_DIR}/downloaded/`) and install from that
  subdirectory instead of the binary dir root. This cleanly separates
  downloaded artifacts from CMake's internal files. Apply this pattern
  whenever using `file(DOWNLOAD)` with a subsequent `install(DIRECTORY)`.
- **Date closed:** 2026-03-24

---

## INC-010: Python pip dependencies need license attribution alongside requirements.txt

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.6
- **Documents involved:** `requirements.txt`, `THIRD_PARTY_NOTICES.md`,
  `docs/agent/workflow.md`
- **Description:** Python packages listed in `requirements.txt` (PySide6,
  pytest, black, etc.) are third-party software with their own licenses,
  but the project had no attribution record for them. `requirements.txt`
  is the standard mechanism for declaring and pinning Python dependencies,
  and the README already references it in the Quick Start section — so
  version/install information is covered. However, license attribution
  was missing. Unlike CMake `FetchContent` or `file(DOWNLOAD)` components
  (which have no other manifest), pip packages have `requirements.txt` as
  their version-pinning home, so `THIRD_PARTY_NOTICES.md` only needs to
  record name, license, and usage (not version pins, to avoid duplication).
- **Resolution:** Added a "Python Packages" section to
  `THIRD_PARTY_NOTICES.md` with a row per package (name, SPDX license,
  usage) and a checklist for adding future packages. Updated the
  `Third-party notices` quality gate in `docs/agent/workflow.md` to
  explicitly include pip dependencies. The convention is:
  - `requirements.txt` owns version pins.
  - `THIRD_PARTY_NOTICES.md` owns license attribution.
  - Both must be updated in the same commit when adding a dependency.
- **Date closed:** 2026-03-24

---

## INC-011: Logging wrapper pattern over direct dds.Logger usage

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.7
- **Documents involved:** `modules/shared/medtech_logging/_logging.py`,
  `modules/shared/medtech_logging/include/medtech/logging.hpp`,
  `vision/technology.md` (Logging Standard)
- **Description:** The vision document's Logging Standard shows
  application code calling `dds.Logger.instance` directly with manual
  `[module-name]` prefixes in every message. This works but has two
  shortcomings: (a) every call site must remember to include the prefix
  (a common source of log hygiene failures), and (b) every call site is
  tightly coupled to `dds.Logger` — swapping the backend later requires
  touching every file. The `workflow.md` Section 4 prohibition on
  "custom logging frameworks" targets replacements like `print()`,
  `spdlog`, or Python `logging` that bypass Connext. A thin delegation
  wrapper that routes all output through `dds.Logger` enforces the
  standard rather than bypassing it.
- **Resolution:** Implemented `ModuleLogger` — a thin composition
  wrapper around `dds.Logger.instance` (Python) / `rti::config::Logger`
  (C++) that auto-prefixes every message with `[module-name]`. Call
  sites use `log.notice("msg")` with no manual prefix. The backend
  can be swapped by changing only `_logging.py` / `logging.hpp`
  internals. This is categorised as a convenience adapter, not a
  custom logging framework, and remains compliant with the
  vision/technology.md Logging Standard.
- **Guideline:** Shared utilities that wrap RTI APIs are acceptable
  when they (a) delegate all I/O to the underlying RTI API, (b) do
  not suppress or alter severity/routing behavior, and (c) create a
  single substitution point for future backend changes. The wrapper
  pattern should be used for any shared infrastructure that may need
  to be swapped.
- **Date closed:** 2026-03-24

---

## INC-012: Type-safe module name enum over raw strings

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.7
- **Documents involved:** `modules/shared/medtech_logging/_logging.py`,
  `modules/shared/medtech_logging/include/medtech/logging.hpp`
- **Description:** The initial `init_logging()` API accepted a raw
  `str` (Python) / `std::string` (C++) for the module name, validated
  at runtime against a `frozenset` / `std::array`. This allows typos
  to compile and only fail at runtime. Since module names are a closed
  set matching directory names, an enumeration provides compile-time
  (C++) / IDE-autocomplete (Python) safety.
- **Resolution:** Replaced raw strings with:
  - Python: `ModuleName(str, Enum)` — compatible with Python 3.10+
    (uses `str, Enum` base instead of `StrEnum` which requires 3.11).
    Members are strings, usable directly in f-strings and comparisons.
  - C++: `enum class ModuleName` with `constexpr to_string()` returning
    `std::string_view`.
  `init_logging()` now takes the enum type, making invalid module names
  a static error (C++) or IDE-flagged mistake (Python).
- **Guideline:** Prefer enumerations over raw strings for closed sets
  of identifiers (module names, domain names, partition templates).
  Use `str, Enum` in Python 3.10+ for string-compatible enums.
- **Date closed:** 2026-03-24

---

## INC-013: rti::config::Logger string\_view overloads not in linked libraries

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.7
- **Documents involved:**
  `modules/shared/medtech_logging/include/medtech/logging.hpp`
- **Description:** The RTI Connext 7.6.0 Modern C++ API documents two
  overloads for each `rti::config::Logger` user-category method:
  `const char*` and `std::string_view`. In practice, passing a
  `std::string` (which implicitly converts to `std::string_view`)
  results in an undefined-reference linker error — the
  `std::string_view` overloads are declared in the header but not
  present in the shipped shared libraries for the
  `x64Linux4gcc8.5.0` architecture.
- **Resolution:** Call the `const char*` overloads explicitly via
  `.c_str()` on the concatenated `std::string`. This avoids the
  `string_view` codepath entirely. Example:
  `logger_.notice((prefix_ + msg).c_str());`
- **Guideline:** When using `rti::config::Logger` user-category
  methods in C++, always pass `const char*` (via `.c_str()`) rather
  than relying on implicit `std::string` → `std::string_view`
  conversion, until RTI ships the `string_view` symbols.
- **Date closed:** 2026-03-24

---

## INC-014: Monitoring Library 2.0 lifecycle and Loki label schema

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.7
- **Documents involved:** `interfaces/qos/Participants.xml`,
  `docker-compose.yml`
- **Description:** Two findings during the Step 1.7 log-forwarding
  verification:

  **1. Monitoring Library 2.0 lifecycle:** The monitoring library is
  *configured* at the `participant_factory_qos` level (process-global),
  but deferring runtime activation — the dedicated monitoring
  participant on the Observability domain (Domain 20) does not appear
  to be created until the first application `DomainParticipant` is
  created. This means user-category log messages written before any
  application participant exists may not be forwarded. Once the first
  participant is created, the monitoring participant is created and
  log forwarding begins.

  **2. Loki label schema:** Collector Service exports logs to Grafana
  Loki with the job label `connext_logger` (not `collector-service`
  as one might assume). User-category logs have `category: "N/A"`,
  while middleware logs have `category: "Discovery"`, `"Database"`,
  etc. The `resource_guid` label identifies the source participant.
  To query user logs in Loki/Grafana, use:
  `{job="connext_logger", category="N/A"}`.
- **Resolution:** Documented for future agent sessions. Forwarding
  test verified: user log with `[surgical-procedure]` prefix
  appeared in Loki within seconds of being written, confirming the
  full pipeline (Logger → Monitoring Library 2.0 → Collector Service
  → Loki) works correctly.
- **Guideline:** When verifying log forwarding, always create at
  least one application `DomainParticipant` first. Query Loki with
  `job="connext_logger"` (not `collector-service`). Use
  `category="N/A"` to filter to user-category logs.
- **Date closed:** 2026-03-24

---

## INC-015: markdownlint-cli Node 18 compatibility

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.8
- **Documents involved:** `scripts/ci.sh`
- **Description:** The latest `markdownlint-cli` (0.42+) requires
  Node.js 20+. The development environment runs Node.js 18.19.1.
  Pinned to `markdownlint-cli@0.39.0` which is the last version
  compatible with Node 18.
- **Resolution:** CI script checks PATH first, then falls back to
  `/tmp/mdlint/node_modules/.bin/markdownlint`. Install command:
  `npm install --prefix /tmp/mdlint markdownlint-cli@0.39.0`.
- **Guideline:** When adding Node-based CLI tools, verify the
  minimum Node.js version. Pin to a compatible release rather than
  using `@latest`.
- **Date closed:** 2026-03-24

---

## INC-016: CTest quiet mode suppresses summary line

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.8
- **Documents involved:** `scripts/ci.sh`
- **Description:** `ctest -q` suppresses the "100% tests passed"
  summary line, so `grep -q "100%"` used for the CI gate check
  would always fail even when all tests passed. Gate 3 initially
  ran CTest twice (once for output, once for the check) which also
  doubled execution time.
- **Resolution:** Capture CTest output once with `|| true`, display
  the tail, and grep the captured output for "tests passed" to
  determine pass/fail.
- **Guideline:** For CI gate checks, capture command output into a
  variable and parse it — avoid running the same command twice or
  relying on quiet-mode output format.
- **Date closed:** 2026-03-24

---

## INC-017: Integration test sleep durations dominated suite runtime

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.8
- **Documents involved:** `tests/integration/test_domain_isolation.py`,
  `tests/integration/test_partition_isolation.py`
- **Description:** Non-discovery validation sleeps in integration
  tests were set to 5s (domain isolation) and 3s (partition
  isolation), making the full pytest suite take ~63s. On localhost,
  DDS discovery completes in well under 1 second, so 2s is ample
  to confirm that non-discovery holds.
- **Resolution:** Reduced non-discovery sleeps from 5s→2s and
  data-exchange waits from 2–3s→1–2s. Suite time reduced by ~15s.
- **Guideline:** For non-discovery validation tests, 2s is
  sufficient on localhost. Only increase if running across physical
  network boundaries.
- **Date closed:** 2026-03-24

---

## INC-018: Bash `set -euo pipefail` requires guards on grep absence checks

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.8
- **Documents involved:** `scripts/ci.sh`
- **Description:** Under `set -euo pipefail`, a `grep` that
  legitimately matches zero lines returns exit code 1, which
  triggers immediate script termination. This affects "absence
  checks" (e.g., verifying no `print()` calls exist) where zero
  matches is the success case.
- **Resolution:** Use `if grep ... ; then VIOLATION` pattern
  (grep inside an `if` does not trigger `set -e`) or append
  `|| true` when the command's exit code is checked manually.
- **Guideline:** In `set -e` bash scripts, always wrap grep-based
  absence checks in `if` conditionals rather than relying on exit
  code suppression.
- **Date closed:** 2026-03-24

---

## INC-019: Throughput threshold direction requires inverted comparison

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.9
- **Documents involved:** `tests/performance/metrics.py`,
  `vision/performance-baseline.md`
- **Description:** The PERCENTAGE threshold check (`current <=
  baseline * (1 + max_ratio)`) works for latency and resource
  metrics where higher-is-worse. For throughput metrics (T1–T4)
  where `max_ratio` is negative (−0.10 = allowed 10% drop),
  the formula produces a ceiling check (`current <= baseline * 0.90`)
  that passes values *below* the floor instead of failing them.
  Throughput regression means current is *lower* than acceptable,
  so the comparison must be `current >= baseline * (1 + max_ratio)`.
- **Resolution:** Added direction check in `Threshold.check()`:
  when `max_ratio < 0`, use `>=` comparison (floor); when
  `max_ratio >= 0`, use `<=` comparison (ceiling). Unit test
  confirms 12% throughput drop correctly fails the 10% threshold.
- **Guideline:** When implementing percentage-based thresholds,
  always consider whether the regression direction is "higher is
  worse" (latency) or "lower is worse" (throughput) and invert
  the comparison accordingly.
- **Date closed:** 2026-03-24

---

## INC-020: Code style must be applied before committing new files

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.9
- **Documents involved:** `scripts/ci.sh`, `pyproject.toml`
- **Description:** Newly created Python files (metrics.py,
  benchmark.py, test_benchmark.py) and files edited during step
  1.8 sleep reduction (test_partition_isolation.py) had black,
  isort, and ruff violations that were not caught until the CI
  pipeline ran. Each tool needed a separate pass to fix.
- **Resolution:** Applied `black`, `isort --profile black`, and
  `ruff check --fix` to all affected files before committing.
- **Guideline:** Before committing any step, run
  `black modules/ tests/ && isort --profile black modules/ tests/ && ruff check --fix modules/ tests/`
  on all new or modified Python files. Consider adding a pre-commit
  hook or running style fixes automatically as part of the commit
  workflow.
- **Date closed:** 2026-03-24

---

## INC-021: Connext Python enum two-layer type model — `.underlying` pattern

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.10
- **Documents involved:** `tools/qos-checker.py`
- **Description:** Connext Python wraps pybind11 enums in two layers.
  Class-level members (e.g., `dds.DurabilityKind.VOLATILE`) are the
  *inner* type (`DurabilityKind.DurabilityKind`) — hashable, with
  `.name` and `.value` attributes. QoS-returned values (e.g.,
  `w_qos.durability.kind`) are the *outer* type (`DurabilityKind`) —
  NOT hashable, no `.name`/`.value`, but expose `.underlying` to get
  the inner type. Equality (`==`) works across both layers. Dict keys
  and `hash()` require the inner type.
- **Resolution:** Created a `_to_inner(val)` helper using
  `getattr(val, "underlying", val)` that transparently handles both
  layers. Dict keys use class-level members (already inner type);
  QoS-returned values go through `_to_inner()` for lookups and
  `.name` access.
- **Guideline:** When using Connext Python enum values as dict keys,
  in `hash()`, or accessing `.name`/`.value`, always call
  `.underlying` on values obtained from QoS objects. Use a helper
  like `_to_inner(val)` to handle both layers transparently.
- **Date closed:** 2026-03-24

---

## INC-022: No built-in RxO compatibility checker in Connext Python API

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.10
- **Documents involved:** `tools/qos-checker.py`,
  `vision/tooling.md`
- **Description:** The Connext Python API has no pre-flight function
  to check DataWriterQos / DataReaderQos RxO compatibility. RxO
  enforcement happens at entity matching time via
  `OFFERED_INCOMPATIBLE_QOS_STATUS` /
  `REQUESTED_INCOMPATIBLE_QOS_STATUS` listener callbacks.
  For offline validation, manual comparison of the five DDS RxO
  policies (reliability, durability, deadline, ownership, liveliness)
  is required. Confirmed via `rti-chatbot-mcp`.
- **Resolution:** Implemented manual RxO checks in
  `tools/qos-checker.py`. The checker resolves writer and reader QoS
  per topic via the default QosProvider's topic-filter API, then
  compares each RxO policy.
- **Guideline:** Use `tools/qos-checker.py` for pre-flight RxO
  validation. Extend the checker if new RxO-relevant policies are
  used in future phases.
- **Date closed:** 2026-03-24

---

## INC-023: CI pipeline grew to 10 gates beyond original workflow.md list

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Step 1.10
- **Documents involved:** `scripts/ci.sh`, `workflow.md` Section 7
- **Description:** Step 1.8 added Gate 9 (performance benchmark) and
  Step 1.10 added Gate 10 (QoS compatibility check) to
  `scripts/ci.sh`. The original `workflow.md` Section 7 describes
  quality gates as a conceptual checklist but does not enumerate the
  CI script gates by number. As the implementation progresses, the
  CI gate count grows beyond the original list.
- **Resolution:** `scripts/ci.sh` is the authoritative runtime gate
  set. A doc clarification was applied to `workflow.md` Section 7
  noting that `scripts/ci.sh` may include additional automated gates
  added during implementation.
- **Guideline:** When adding a new CI gate, add it to
  `scripts/ci.sh` and note the addition in the step's commit
  message. The workflow.md quality gate table describes the
  conceptual categories; the CI script is the executable authority.
- **Date closed:** 2026-03-24

---

## INC-024: Monitoring Library 2.0 application name via XML env variable

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 / Post-Phase 1 (pre-Phase 2 preparation)
- **Documents involved:** `interfaces/qos/Participants.xml`,
  `setup.bash.in`, `vision/technology.md`
- **Description:** Monitoring Library 2.0 exposes an
  `application_name` field in the `<monitoring>` section of
  `<participant_factory_qos>`. This name labels process-level
  telemetry in Collector Service, Prometheus, and Grafana dashboards.
  Without it, all applications appear as the same unnamed resource.
  The field is distinct from `participant_name` in
  `domain_participant_qos` (which labels individual participant
  instances in Admin Console and discovery).
  Because `participant_factory_qos` is process-global (not
  per-participant), the application name cannot vary per participant
  within a process. Each application process needs a unique name.
- **Possible resolutions:**
  1. XML environment variable substitution:
     `<application_name>$(MEDTECH_APP_NAME)</application_name>` with
     each process setting `MEDTECH_APP_NAME` before launch. Confirmed
     supported by `rti-chatbot-mcp` and RTI User Manual (XML
     Configuration Variables).
  2. Programmatic: set `DomainParticipantFactoryQos.monitoring`
     before creating any participant. Works but couples the name to
     application code rather than deployment configuration.
  3. Separate XML profiles per application — poor scaling when only
     the name differs.
- **Resolution:** Resolution 1 adopted. Added
  `<application_name>$(MEDTECH_APP_NAME)</application_name>` to the
  `FactoryDefaults` profile in `Participants.xml`. Added
  `export MEDTECH_APP_NAME="${MEDTECH_APP_NAME:-unknown}"` to
  `setup.bash.in` as a fallback default. Docker Compose will set the
  variable per service container. Module launcher scripts set it
  before sourcing `setup.bash`.
- **Guideline:** Every application entry point must set
  `MEDTECH_APP_NAME` to its module name (e.g.,
  `surgical-procedure`, `hospital-dashboard`, `clinical-alerts`)
  before any DDS entity is created. Docker Compose services set it
  via `environment:`. Local development sets it in the shell or
  launcher script. The value must match the module directory name
  per `vision/technology.md` naming convention.
- **Date closed:** 2026-03-24

---

## INC-025: rtisetenv prerequisite for Monitoring Library 2.0 at runtime

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 Review
- **Documents involved:** `setup.bash.in`, `vision/technology.md`
- **Description:** The project's `setup.bash` adds
  `install/lib` to `LD_LIBRARY_PATH`, but `librtimonitoring2.so`
  resides under the Connext installation tree
  (`$NDDSHOME/lib/<arch>/` and `$NDDSHOME/resource/app/lib/<arch>/`).
  Without sourcing `rtisetenv` (or otherwise adding the Connext
  library directories to `LD_LIBRARY_PATH`) before running tests or
  applications, every DDS participant that enables the Monitoring
  Library fails to load the shared library. During the Phase 1
  compliance audit this manifested as 35 import errors and 3 test
  failures — all resolved by sourcing `rtisetenv` first.
- **Guideline:** For local development, always source `rtisetenv`
  before `setup.bash`. The Docker runtime images already have
  Connext libraries on the default library path, so containers are
  not affected. Future sessions must not diagnose monitoring-related
  `ImportError` or `OSError` without first confirming `rtisetenv`
  has been sourced.
- **Date closed:** 2026-03-24

---

## INC-026: Vision doc propagation gap after incident-driven design changes

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 1 Review
- **Documents involved:** `vision/data-model.md`, `vision/technology.md`
- **Description:** INC-004 refactored the `AlarmMessages` aggregate
  type to a per-alarm keyed `AlarmMessage` struct, and INC-002
  adopted the `-noSysPathGeneration` flat Python layout. Both
  incidents changed the implementation and updated the directly
  affected files (IDL, CMakeLists.txt, domains.xml), but neither
  propagated the changes to all referencing vision documents. The
  Phase 1 compliance audit found 8 stale `Monitoring::AlarmMessages`
  type references in `data-model.md` and an entire obsolete
  subdirectory-based Python packaging subsection in `technology.md`.
  These were corrected in commit `54de015`.
- **Root cause:** The incident closure process did not include a
  cross-reference audit of all vision/spec documents that mention
  the changed entity. When an incident changes a type name, install
  layout, or other structural element, every vision and spec
  document that references that element must be checked and updated.
- **Guideline:** When closing any incident that changes a type name,
  topic name, install path, QoS profile name, or other structural
  identifier, grep the full `docs/agent/` tree for all references
  and update them before marking the incident closed. A convenient
  check: `grep -r "<old_name>" docs/agent/`.
- **Date closed:** 2026-03-24
