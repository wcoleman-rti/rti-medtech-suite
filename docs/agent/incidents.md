# Incident Log

> **Terminology note:** Entries in this log use the terminology current at
> the time they were written. Pre-V1.4.x entries may refer to "Procedure
> domain" (now "Procedure control/clinical/operational databus"),
> "Hospital domain" (now "Hospital Integration databus"),
> "Orchestration domain" (now "Orchestration databus"), and
> `MedtechDomains` (now `Room`/`Hospital`/`Cloud` libraries).

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
  `Domains.xml`, `vision/data-model.md`
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
  affected files (IDL, CMakeLists.txt, Domains.xml), but neither
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

---

## INC-027: CameraFrame XTypes — @key field breaks Foxglove wire compatibility

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Extension — CameraFrame inline data redesign
- **Documents involved:** `vision/data-model.md`, `interfaces/idl/imaging/imaging.idl`
- **Description:** During the CameraFrame redesign to carry inline
  compressed image data (Foxglove `CompressedImage`-aligned), the
  question arose whether the medtech `CameraFrame` type could be
  wire-compatible with Foxglove's type while also having `@key
  camera_id` for per-camera DDS instance handling.
  Consulted `rti-chatbot-mcp` for XTypes assignability rules.
  Findings:
  - **`@appendable`:** Adding a `@key` field at any position
    (beginning or end) breaks assignability. Appendable only
    allows non-key fields appended at the end.
  - **`@mutable`:** Using member IDs solves position reordering,
    but adding or removing key members still breaks assignability.
  - **Conclusion:** A type with `@key camera_id` is fundamentally
    a different DDS topic type, not a compatible evolution of
    Foxglove's `CompressedImage`. Foxglove interop, if needed
    (V3.0+ PACS gateway), requires a Routing Service
    transformation bridge — not wire compatibility.
- **Resolution:** Designed `CameraFrame` as a standalone medtech
  type with `@key camera_id` first (project convention), kept
  `@appendable`, and documented the non-wire-compatibility with
  Foxglove. Field semantics are aligned (timestamp, frame_id,
  data, format) for conceptual compatibility and future bridging.
  Introduced separate `CameraConfig` state topic for stream
  metadata (resolution, encoding, exposure) — write-on-change,
  TRANSIENT_LOCAL, correlated via `camera_id`.
- **Guideline:** When designing DDS types inspired by external
  schemas (Foxglove, ROS 2, OMG), adding `@key` fields always
  creates a distinct DDS type. Wire compatibility with the
  external schema is only achievable if the key structure matches
  exactly. Plan for Routing Service bridging when interop with
  external types is needed.
- **Date closed:** 2026-03-24

---

## INC-028: Common::Time_t replaced with Common::Timestamp_t (typedef int64) — Y2038 eliminated

- **Status:** Closed (superseded)
- **Category:** Design Decision
- **Date opened:** 2026-03-24
- **Date reopened:** 2026-03-27
- **Phase/Step:** Extension — Foxglove translatability revision
- **Documents involved:** `interfaces/idl/common/common.idl`,
  `interfaces/idl/imaging/imaging.idl`, `vision/data-model.md`
- **Description:** `Common::Time_t` (`@final` struct, `uint32 sec` +
  `uint32 nsec`) was originally introduced for field-semantic alignment
  with Foxglove's `foxglove::Time`. This carried a Y2038 overflow
  limitation.

  **Resolution (2026-03-27):** The Foxglove alignment strategy was
  revised from "field-semantic alignment" to "translatable, not
  aligned." Since Foxglove timestamps are now assembled from
  `SampleInfo.source_timestamp` by the Transformation plugin, there
  is no need for a Foxglove-shaped struct in medtech IDL.

  `Common::Time_t` has been **replaced** with `Common::Timestamp_t`
  (`typedef int64 Timestamp_t`) — epoch nanoseconds. This eliminates
  the Y2038 limitation (±292 year range), reduces the type from a
  2-member struct to a single scalar, and maintains a consistent
  timestamp representation across modules.

  **Consumer migration:**
  - `Imaging::CameraFrame.timestamp` — **removed entirely**. Frame
    capture time ≈ write time; use `SampleInfo.source_timestamp`.
  - `Surgery::ProcedureContext.start_time` — type changed to
    `Common::Timestamp_t` (epoch nanoseconds).
  - `Monitoring::AlarmMessage.onset_time` — type changed to
    `Common::Timestamp_t` (epoch nanoseconds).

  The Foxglove `foxglove::Time` struct is no longer referenced by
  medtech IDL. The vendored `foxglove/Time.idl` file remains available
  for the V2 Transformation plugin build.
- **Resolution:** Superseded by translatability revision. `Time_t`
  removed; `Timestamp_t` alias introduced. See `vision/data-model.md`
  (`Common::Timestamp_t` section).
- **Date closed:** 2026-03-27

---

## INC-029: source_timestamp convention — DDS metadata replaces IDL timestamp fields

- **Status:** Closed (updated)
- **Category:** Design Decision
- **Date opened:** 2026-03-24
- **Date updated:** 2026-03-27
- **Phase/Step:** Extension — timestamp field removal / source_timestamp adoption
- **Documents involved:** `vision/data-model.md`, all IDL files under
  `interfaces/idl/`
- **Description:** Removed `Common::Time_t timestamp` as the trailing
  member from all top-level IDL types. Sample publication time is now
  conveyed via DDS `SampleInfo.source_timestamp`, which is
  automatically set by the DataWriter at `write()` time and available
  to subscribers without any payload overhead.

  **Update (2026-03-27):** As part of the Foxglove translatability
  revision, `Imaging::CameraFrame.timestamp` has also been removed.
  Frame capture time ≈ write time for this project's use case.
  The Foxglove Transformation plugin populates
  `foxglove::CompressedImage.timestamp` from
  `SampleInfo.source_timestamp`.

  **Retained `Common::Timestamp_t` fields** (domain-meaningful times
  distinct from write time):
  - `Surgery::ProcedureContext.start_time` — wall-clock procedure start
  - `Monitoring::AlarmMessage.onset_time` — wall-clock alarm onset

  **Caveats confirmed via `rti-chatbot-mcp`:**
  1. `source_timestamp` participates in `DESTINATION_ORDER
     BY_SOURCE_TIMESTAMP` — if used, explicit timestamps must be
     monotonically increasing or writes may fail.
  2. Batching: `Batch::source_timestamp_resolution` controls whether
     batched samples share a timestamp. High-rate topics
     (`OperatorInput`, `WaveformData`) should verify per-sample
     uniqueness if batching is enabled.
  3. Routing Service: must preserve `source_timestamp` across bridges
     (default behavior with `propagate_source_timestamp`). Verify for
     Hospital domain bridged topics.
  4. Subscribers must access `SampleInfo` alongside data — code paths
     that pass only deserialized data objects will lose timestamp access.
- **Resolution:** Applied. All IDL files updated, `data-model.md` type
  tables updated. `Common::Time_t` replaced with `Common::Timestamp_t`
  (`typedef int64`, epoch nanoseconds) — see INC-028.
- **Date closed:** 2026-03-27

---

## INC-030: PARTITION env var must be defined for SurgicalParticipants.xml loading

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-24
- **Phase/Step:** Phase 2 / Step 2.1
- **Documents involved:** `interfaces/participants/SurgicalParticipants.xml`, `setup.bash.in`
- **Description:** SurgicalParticipants.xml uses `$(PARTITION)` in publisher/subscriber
  QoS partition elements. When this XML is loaded via `NDDS_QOS_PROFILES`, the RTI XML
  parser fails with `Undefined environment variable PARTITION` if PARTITION is not set in
  the environment. This breaks all DDS operations, including existing Phase 1 tests that
  don't use partitions. The fix is to ensure PARTITION is always defined (defaulting to
  empty string for the default partition) in `setup.bash.in`.
- **Resolution:** Added `export PARTITION="${PARTITION:-}"` to `setup.bash.in` before the
  runtime configuration block. Applications set PARTITION to their specific value before
  launching. All 126 tests pass.
- **Guideline:** Any XML file loaded globally via NDDS_QOS_PROFILES that references
  environment variables via `$(VAR)` must have a default defined in the setup script, or
  the entire QoS provider will fail to load.
- **Date closed:** 2026-03-24

---

## INC-031: AsyncWaitSet conditions must be detached before entity destruction

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-25
- **Phase/Step:** Phase 2 / Step 2.2
- **Documents involved:** `modules/surgical-procedure/robot_controller/main.cpp`
- **Description:** When shutting down the robot-controller, calling `participant.close()`
  with conditions still attached to AsyncWaitSet instances causes a fatal error:
  "Precondition not met error: waitset attached". The ReadConditions and GuardCondition
  must be explicitly detached from their respective AsyncWaitSets before `stop()` and
  before any DDS entity they reference is destroyed.
- **Resolution:** Added `pub_aws.detach_condition(publish_tick)` and
  `sub_aws.detach_condition(...)` for all three ReadConditions before stopping the
  AsyncWaitSets and closing the participant. Shutdown is now clean.
- **Guideline:** Always detach all conditions from AsyncWaitSet instances before calling
  `stop()` and before closing/destroying the DDS entities the conditions reference.
- **Date closed:** 2026-03-25

---

## INC-032: OperatorInput lifespan interacts with test polling interval

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-25
- **Phase/Step:** Phase 2 / Step 2.2
- **Documents involved:** `tests/integration/test_robot_controller.py`, `tests/conftest.py`
- **Description:** The `wait_for_data()` helper polls with 50 ms sleep intervals using
  `reader.read()`. OperatorInput has a 20 ms lifespan (LifespanOperatorInput snippet). By the time
  the helper reads the sample, it has already expired and been purged from the reader
  queue. Tests for short-lifespan topics must use a tighter polling loop (2 ms) with
  `reader.take()` to read samples before they expire.
- **Resolution:** Replaced `wait_for_data()` call in `test_operator_input_delivery` with
  an inline loop polling at 2 ms intervals using `reader.take()`.
- **Guideline:** When testing topics with short lifespan QoS, poll at intervals shorter
  than the lifespan. The generic `wait_for_data()` helper (50 ms interval) is only
  suitable for topics without lifespan or with lifespan > 100 ms.
- **Date closed:** 2026-03-25

---

## INC-033: DDS Python API returns integers for IDL boolean fields

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-25
- **Phase/Step:** Phase 2 / Step 2.2
- **Documents involved:** `tests/integration/test_robot_controller.py`
- **Description:** IDL boolean fields (e.g., `SafetyInterlock.interlock_active`) are
  returned as Python integers (`0` or `1`) by the RTI Connext Python API, not as Python
  `bool` (`True`/`False`). This means `assert data.interlock_active is True` fails because
  `1 is True` is `False` in Python. Use `== True` or truthiness checks instead of
  identity checks for DDS boolean fields.
- **Resolution:** Changed assertion from `is True` to `== True` with a `noqa: E712`
  comment explaining the DDS integer return type.
- **Guideline:** Always use equality (`==`) or truthiness checks for IDL boolean fields
  in Python tests, never identity (`is`).
- **Date closed:** 2026-03-25

---

## INC-034: app_names.idl generates flat Python module — no package import

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-25
- **Phase/Step:** Revision / Step R.1
- **Documents involved:** `interfaces/idl/app_names.idl`, `interfaces/CMakeLists.txt`
- **Description:** `rtiddsgen -language Python` generates `app_names.py` as a flat file, not
  a package with submodules. The nested IDL module `MedtechEntityNames::SurgicalParticipants`
  becomes a nested class attribute, not a subpackage. This means
  `from app_names.MedtechEntityNames import SurgicalParticipants` raises `ModuleNotFoundError`.
  The correct import is `import app_names; names = app_names.MedtechEntityNames.SurgicalParticipants`.
- **Resolution:** Adopted the attribute-access pattern in all Python consumers.
- **Guideline:** For rtiddsgen Python output with nested IDL modules, use attribute access
  (`import app_names; ns = app_names.Module.Submodule`) rather than `from ... import`.
- **Date closed:** 2026-03-25

---

## INC-035: C++ string_view constants require std::string() wrapper for DDS API calls

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-25
- **Phase/Step:** Revision / Step R.3
- **Documents involved:** `interfaces/idl/app_names.idl`,
  `modules/surgical-procedure/robot_controller/robot_controller_app.cpp`
- **Description:** `rtiddsgen -language C++11` generates `@module` constants as
  `::omg::types::string_view` (via `RTI_CONSTEXPR_OR_CONST_STRING`). DDS API functions like
  `create_participant_from_config()` and `find_datawriter_by_name()` accept `const std::string&`,
  not `string_view`. An explicit `std::string(names::CONSTANT)` wrapper is required at each
  call site.
- **Resolution:** All call sites wrap constants in `std::string()`.
- **Guideline:** When using IDL-generated `string_view` constants in C++ DDS API calls,
  always wrap with `std::string()`.
- **Date closed:** 2026-03-25

---

## INC-036: is_type_registered() is instance method, not class method

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-25
- **Phase/Step:** Revision / Step R.6
- **Documents involved:** `tests/integration/test_dds_consistency.py`
- **Description:** `dds.DomainParticipant.is_type_registered()` is an instance method in the
  RTI Connext Python API. A `@consistency` test attempted to call it as a class method to verify
  type registration without creating a participant. The correct approach is to create a
  participant from XML config (which triggers `initialize_connext()` and type registration)
  and then verify types are registered on the live participant instance.
- **Resolution:** Rewrote test to create a participant from config and verify type registration
  via the instance method.
- **Guideline:** Use a live `DomainParticipant` instance to verify type registration in tests.
  Creating the participant from XML config exercises the full initialization path.
- **Date closed:** 2026-03-25

---

## INC-037: Test readers require explicit enable() due to factory-level autoenable

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-25
- **Phase/Step:** Phase 2 / Step 2.3
- **Documents involved:** `tests/integration/test_vitals_sim.py`,
  `interfaces/qos/Participants.xml`
- **Description:** Integration test readers created via
  `dds.DomainParticipant(domain_id, qos)` + `dds.DataReader(sub, topic, qos)`
  failed with `NotEnabledError` on `take()`. The `participant_factory_qos`
  in `Participants.xml` sets `entity_factory.autoenable_created_entities = FALSE`
  (process-global), which affects all participants in the process — not just
  those created from XML config. The existing `conftest.py` fixtures
  (`_make_participant()`) already call `p.enable()` to handle this, but
  test fixtures created inline in individual test files must do the same.
- **Resolution:** Added explicit `dp.enable()` calls in all test fixtures
  after creating the participant and its contained entities, matching the
  pattern in `conftest.py`.
- **Guideline:** When creating DDS participants in test code, always call
  `enable()` explicitly after entity setup is complete. The factory-level
  `autoenable_created_entities = FALSE` is global and affects all
  participants in the process, regardless of how they were created.
- **Date closed:** 2026-03-25

---

## INC-038: Relative imports required for installed Python subpackages

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-25
- **Phase/Step:** Phase 2 / Step 2.3
- **Documents involved:** `modules/surgical-procedure/vitals_sim/__init__.py`,
  `modules/surgical-procedure/vitals_sim/bedside_monitor.py`
- **Description:** The `vitals_sim` subpackage within `surgical_procedure`
  initially used absolute imports (`from vitals_sim._alarm import ...`).
  After CMake install, the package lives at
  `lib/python/site-packages/surgical_procedure/vitals_sim/`, so the
  top-level `vitals_sim` name is not resolvable. Relative imports
  (`from ._alarm import ...`) resolve correctly within the installed
  package hierarchy.
- **Resolution:** Changed all within-package imports to relative form.
  External consumers use `from surgical_procedure.vitals_sim import ...`.
- **Guideline:** For Python subpackages installed under a parent package
  (e.g., `surgical_procedure.vitals_sim`), always use relative imports
  for within-package references and absolute imports for cross-package
  references.
- **Date closed:** 2026-03-25

---

## INC-039: DDS ownership kind is immutable after entity creation

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-25
- **Phase/Step:** Phase 2 / Step 2.5
- **Documents involved:** `vision/data-model.md`, `vision/dds-consistency.md`
- **Description:** Attempted to set `OwnershipKind.EXCLUSIVE` on a
  DataWriter created from XML configuration (`create_participant_from_config()`)
  which defaults to `SHARED` ownership via the `Patterns::State` QoS profile.
  The Connext Python API raises `rti.connextdds.ImmutablePolicyError` when
  calling `writer.qos = modified_qos` with a changed ownership kind. This is
  correct per the DDS specification — ownership kind is an immutable QoS policy
  that must be set before entity creation.
- **Possible resolutions:**
  1. Create a separate XML QoS profile (`ExclusiveState`) with
     `EXCLUSIVE_OWNERSHIP_QOS` and an `ownership_strength` parameter for
     the primary/backup pattern. The DeviceGateway would reference this
     profile when exclusive ownership is required.
  2. Create the DataWriter manually (not from XML) when exclusive ownership
     is needed, setting ownership QoS at construction time.
  3. Keep the DeviceGateway using the standard State pattern (SHARED) and
     test exclusive ownership failover independently using DDS fixtures
     (which already passes in `test_exclusive_ownership.py`).
- **Resolution:** Resolution 3 adopted for V1.0. The DeviceGateway uses
  the standard State pattern from XML. Exclusive ownership failover for
  DeviceTelemetry is validated at the DDS level using manually-created
  writers in `test_exclusive_ownership.py`. For V2 device gateways that
  require exclusive ownership in production, Resolution 1 (XML profile)
  is the recommended approach.
- **Guideline:** Never attempt to change ownership kind, reliability kind,
  durability kind, or other immutable QoS policies after entity creation.
  If different QoS is needed for deployment variants (e.g., exclusive
  ownership failover), define separate XML profiles in Topics.xml.
- **Date closed:** 2026-03-25


---

## INC-040: GuiSubsample TBF exceeded RobotState deadline — inconsistent QoS

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-26
- **Phase/Step:** Phase 2 / Step 2.6
- **Documents involved:** `interfaces/qos/Snippets.xml`, `interfaces/qos/Topics.xml`, `spec/surgical-procedure.md`
- **Description:** The `Snippets::GuiSubsample` QoS snippet was set to
  `time_based_filter.minimum_separation = 100 ms`. The `TopicProfiles::RobotState`
  profile uses `Snippets::DeadlineRobotState` (deadline = 20 ms). The DDS QoS
  consistency rule requires `time_based_filter.minimum_separation <= deadline.period`.
  With TBF = 100 ms > deadline = 20 ms, creating a DataReader from the
  `ControlDigitalTwin` participant (which uses `TopicProfiles::GuiRobotState`)
  failed with `rti.connextdds.Error: Failed to create DataReader` and the message
  `inconsistent QoS policies: deadline.period and time_based_filter.minimum_separation`.
  A second inconsistency: `TopicProfiles::OperatorInput` has a 4 ms deadline,
  so `GuiOperatorInput` (which adds GuiSubsample) was also inconsistent.
- **Resolution:**
  1. Changed `GuiSubsample` TBF from 100 ms to 16 ms (matching the spec's
     stated ~16 ms (~60 Hz) rendering interval), which is <= the 20 ms
     RobotState deadline.
  2. Added an explicit `deadline.period = 100 ms` override to `GuiOperatorInput`
     to satisfy the constraint for the OperatorInput reader (whose base profile
     has a 4 ms deadline that is stricter than needed for a display reader).
- **Guideline:** When composing a GUI QoS profile that adds a time-based filter
  on top of a topic profile with a strict deadline, always verify that
  `time_based_filter.minimum_separation <= deadline.period`. Display readers
  that observe data opportunistically should override the deadline to a relaxed
  value appropriate for their rendering rate.
- **Date closed:** 2026-03-26

---

## INC-041: DomainParticipant partitions not discoverable via Python 7.6.0 builtin topics

- **Status:** Open
- **Category:** Discovery
- **Date opened:** 2026-03-27
- **Phase/Step:** Phase 2 / Step 2.11
- **Documents involved:** `tools/medtech-diag/diag.py`,
  `tools/partition-inspector.py`, `spec/surgical-procedure.md`
- **Description:** This project sets partitions at the DomainParticipant
  level (`DomainParticipantQos.partition.name`), but
  `ParticipantBuiltinTopicData` in the RTI Connext Python 7.6.0 binding
  does not expose a `partition` field.  `PublicationBuiltinTopicData` and
  `SubscriptionBuiltinTopicData` do have a `partition` field, but it
  reflects Publisher/Subscriber-level partitions, which are completely
  independent from DomainParticipant-level partitions.  Since application
  code does not set Publisher/Subscriber partitions, endpoint discovery
  always returns empty partition lists.  The `property` field of
  `ParticipantBuiltinTopicData` contains only `dds.sys_info.*` metadata
  keys (8 total); there is no partition-related key.
- **Impact:** The `medtech-diag` partition check and the
  `partition-inspector.py` tool cannot introspect active partitions.
  The partition check in `medtech-diag` has been made informational-only
  (always passes) and `partition-inspector.py` includes a prominent
  limitation notice.
- **Possible resolutions:**
  1. Wait for a future Connext Python API update that exposes
     DomainParticipant partitions in `ParticipantBuiltinTopicData`.
  2. Propagate partition names via `DomainParticipantQos.user_data` or
     `DomainParticipantQos.property` at the application level and read
     them back from builtin discovery data.
  3. Use RTI Admin Console or `rtiddsspy` (C-based tools) which may
     have access to the full discovery data including participant
     partitions.
- **Resolution:** Deferred — partition introspection skipped for now.
  Tools document the limitation and reference this incident.

---

## INC-042: Cross-container CDS discovery fails on domain 10 (Procedure)

- **Status:** Open
- **Category:** Discovery
- **Date opened:** 2026-03-27
- **Phase/Step:** Phase 2 / Step 2.11
- **Documents involved:** `docker-compose.yml`,
  `services/cloud-discovery-service/CloudDiscoveryService.xml`,
  `interfaces/qos/Participants.xml`, `tools/medtech-diag/diag.py`
- **Description:** Cloud Discovery Service (CDS) on Docker correctly
  relays SPDP announcements for domain 20 (Observability) — a test
  participant discovers 11 monitoring participants.  However, CDS does not
  relay discovery for domain 10 (Procedure) or domain 11 (Hospital). A test
  participant on domain 10 returns 0 discovered participants regardless of
  domain_tag setting (tested with "operational", "control", "clinical",
  and no tag).  Same-process discovery on domain 10 works fine (two
  participants in one process discover each other), confirming the issue is
  cross-container CDS relay, not domain_tag handling.
  The CDS config explicitly allows domains 10, 11, and 20.
  All participants use `NDDS_DISCOVERY_PEERS=rtps@udpv4://cloud-discovery-service:7400`
  and the SimulationTransport QoS profile (UDPv4 only, multicast disabled,
  `AvoidIPFragmentation` message_size_max=1400).  The monitoring
  participants on domain 20 are created by the ML2.0 middleware and may use
  different transport settings (message_size_max=65507).  The
  message_size_max mismatch is suspected but not confirmed as the root cause.
- **Impact:** The `medtech-diag` tool cannot discover Procedure or Hospital
  domain participants when run from a separate container.  It can only
  verify infrastructure checks (CDS reachability, Prometheus) and
  Observability domain discovery from outside the app containers.
- **Possible resolutions:**
  1. Set `message_size_max` in CDS transport config to match the
     application's 1400 (AvoidIPFragmentation).
  2. Remove `AvoidIPFragmentation` from application QoS (use default
     65507) — acceptable in Docker bridge networks.
  3. Investigate CDS verbosity logs at LOCAL level to trace domain 10
     announcement handling.
  4. Test with multicast enabled on the Docker bridge network instead
     of CDS-only discovery.
- **Resolution:** Deferred to Phase 3 — does not block Phase 2 completion.
  Diagnostic tools function correctly for Observability domain and
  infrastructure checks.

---

## INC-043: Transport profile revision — dual profiles, SHMEM enabled, is_default_qos removed

- **Status:** Closed
- **Category:** Discovery (operator-directed revision)
- **Date opened:** 2026-03-26
- **Phase/Step:** Post-V1.0 revision (operator review)
- **Documents involved:** `interfaces/qos/Participants.xml`,
  `interfaces/qos/transport/Default.xml` (new),
  `interfaces/qos/transport/Docker.xml` (new),
  `interfaces/participants/SurgicalParticipants.xml`,
  `vision/data-model.md`, `vision/system-architecture.md`,
  `vision/dds-consistency.md`, `implementation/phase-1-foundation.md`
- **Description:** Operator review identified three issues with the
  `Participants::SimulationTransport` profile:
  1. **`is_default_qos="true"`** — all participants already reference
     the profile explicitly. The default flag is redundant and can
     silently apply simulation transport to participants that forget
     to specify a profile, masking configuration errors.
  2. **SHMEM disabled** — the profile set `<mask>UDPv4</mask>`,
     excluding SHMEM. SHMEM is beneficial for intra-container
     communication (multiple participants or processes within the
     same container) and should be enabled in both Docker and
     bare-metal deployments.
  3. **Single profile for all environments** — no path to enable
     multicast for bare-metal / production without editing XML.
  Additionally, the inline `<datareader_qos>` deadline override in
  `GuiOperatorInput` was moved to a `GuiReaderDeadline` snippet for
  consistency with the snippet composition model.
- **Resolution:**
  1. Removed `is_default_qos="true"` from the transport profile.
  2. Created two transport files under `interfaces/qos/transport/`:
     - `Default.xml` — SHMEM + UDPv4, multicast enabled, Connext
       default discovery.
     - `Docker.xml` — SHMEM + UDPv4, multicast disabled, explicit
       initial peers (`builtin.shmem://`, `builtin.udpv4://localhost`,
       CDS locator). Clears `multicast_receive_addresses`.
     Both define `Participants::Transport`. Deployment selects via
     `NDDS_QOS_PROFILES` (setup.bash loads Default, docker-compose
     loads Docker).
  3. Removed the `Participants` QoS library from `Participants.xml`
     (now contains only the `Factory` library).
  4. Renamed all 6 participant references from
     `Participants::SimulationTransport` → `Participants::Transport`.
  5. Added `Snippets::GuiReaderDeadline` (reader-only, 100 ms deadline)
     and replaced the inline override in `GuiOperatorInput`.
  6. Updated `setup.bash.in`, `build/setup.bash`, `docker-compose.yml`,
     `CMakeLists.txt`, and CTest environment.
  7. Updated vision docs: `data-model.md`, `system-architecture.md`,
     `dds-consistency.md`, `phase-1-foundation.md`.
- **Guideline:** Transport profiles should be deployment-selected
  via `NDDS_QOS_PROFILES` path, not environment-switched within a
  single file. SHMEM should remain enabled in all profiles — it is
  always beneficial for co-located participants.
- **Date closed:** 2026-03-26

---

## INC-044: Unified transport profile — env-var-selected snippets in Participants.xml

- **Status:** Closed
- **Category:** Discovery (operator-directed revision)
- **Date opened:** 2026-03-26
- **Phase/Step:** Post-V1.0 revision (operator review, follows INC-043)
- **Documents involved:** `interfaces/qos/Participants.xml`,
  `interfaces/qos/transport/Default.xml` (deleted),
  `interfaces/qos/transport/Docker.xml` (deleted),
  `setup.bash.in`, `docker-compose.yml`, `CMakeLists.txt`,
  `tests/qos/CMakeLists.txt`,
  `vision/data-model.md`, `vision/system-architecture.md`,
  `vision/dds-consistency.md`, `implementation/phase-1-foundation.md`
- **Description:** Operator review of INC-043's dual-file transport design
  identified two concerns:
  1. **DRY violation** — `BuiltinQosSnippetLib::Transport.UDP.AvoidIPFragmentation`
     was duplicated in both `transport/Default.xml` and `transport/Docker.xml`.
     As common participant QoS grows, duplication would increase.
  2. **File-selection fragility** — deployment-specific `NDDS_QOS_PROFILES`
     paths are error-prone and require coordinating two different profile
     load orders (setup.bash vs docker-compose.yml).
  Operator proposed consolidating all transport configuration into a single
  `Participants.xml` using `<configuration_variables>` with
  `$(MEDTECH_TRANSPORT_PROFILE)` variable substitution in `<base_name>`.
  MCP confirmed that `$(VAR)` substitution works in `<base_name><element>`
  text at parse time (RTI Connext 7.6.0).
- **Resolution:**
  1. Moved all transport snippets into `Participants.xml` as a `Transport`
     QoS library with profiles `Default` (empty — Connext defaults) and
     `Docker` (multicast disabled, explicit CDS peers).
  2. Added `<configuration_variables>` with `MEDTECH_TRANSPORT_PROFILE`
     defaulting to `Default`. Environment variable overrides the XML default.
  3. `Participants::Transport` profile composes `AvoidIPFragmentation`
     (common) and `Transport::$(MEDTECH_TRANSPORT_PROFILE)` (selected).
  4. Deleted `interfaces/qos/transport/` directory and both files.
  5. Simplified `NDDS_QOS_PROFILES` — same path everywhere (no transport
     file variation). `docker-compose.yml` sets `MEDTECH_TRANSPORT_PROFILE=Docker`.
  6. `setup.bash.in` drops `transport/Default.xml` from path (default
     handled by `<configuration_variables>`).
  7. Removed CMake install rules for `transport/` files.
  8. Updated all vision/implementation docs.
- **Guideline:** Use `<configuration_variables>` with `$(VAR)` substitution
  in `<base_name><element>` to select deployment-specific QoS snippets from
  a single file. This eliminates file-path coordination and keeps common
  participant QoS in one place. Library names follow short PascalCase
  convention (`Transport`, not `TransportSnippetLib`).
- **Date closed:** 2026-03-26

---

## INC-045: alarm_id exceeds EntityId string bound (16 chars)

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-27
- **Phase/Step:** Phase 2 / Step 2.3
- **Documents involved:** `interfaces/idl/common/common.idl`,
  `interfaces/idl/monitoring/monitoring.idl`,
  `modules/surgical-procedure/vitals_sim/_alarm.py`
- **Description:** The `AlarmMessage.alarm_id` field uses
  `Common::EntityId` (bounded `string<16>`). The alarm evaluator
  generated IDs as `f"{patient_id}-{alarm_code}"` — e.g.,
  `"patient-001-RR_LOW"` (18 chars), causing a `ValueError` at
  serialisation time. The default `patient_id` of `"patient-001"`
  (11 chars) plus separator plus any alarm code longer than 4 chars
  overflows the bound.
- **Resolution:** Introduced `_make_alarm_id()` helper that truncates
  the patient_id prefix from the right to guarantee the composite key
  fits within `MAX_ID_LENGTH`. Added regression test
  `test_alarm_id_fits_entity_id_bound` that triggers every default
  alarm rule with the production patient_id.
- **Guideline:** Any code that constructs composite entity IDs must
  validate the total length against the IDL string bound. Consider
  increasing `MAX_ID_LENGTH` in a future revision if composite IDs
  become common.
- **Date closed:** 2026-03-27

---

## INC-046: Digital twin DomainParticipant never enabled

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-27
- **Phase/Step:** Phase 2 / Step 2.6
- **Documents involved:**
  `modules/surgical-procedure/digital_twin/digital_twin_display.py`,
  `vision/dds-consistency.md` §3
- **Description:** The digital twin display's `_init_dds()` method
  created the `ControlDigitalTwin` participant and set its partition,
  but never called `participant.enable()`. Since
  `create_participant_from_config()` returns a disabled participant
  (to allow partition assignment first), the readers never discovered
  any writers and the GUI showed "UNKNOWN" with no data.
  Every other Python simulator in the module (camera_sim,
  vitals_sim, device_telemetry_sim, procedure_context) correctly
  calls `enable()` after setting the partition. The C++ robot
  controller also calls `enable()`. This was a unique omission in
  the digital twin.
- **Resolution:** Added `self._participant.enable()` after partition
  assignment in `_init_dds()`.
- **Guideline:** The canonical participant lifecycle documented in
  `vision/dds-consistency.md` §3 should explicitly list
  `participant.enable()` as a mandatory step after partition
  assignment. Consider adding an anti-pattern check to CI that
  greps for `create_participant_from_config` without a corresponding
  `.enable()` call.
- **Date closed:** 2026-03-27

---

## INC-047: QtAsyncio.run() event loop mismatch — DDS tasks never started

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-27
- **Phase/Step:** Phase 2 / Step 2.6
- **Documents involved:**
  `modules/surgical-procedure/digital_twin/__main__.py`
- **Description:** The digital twin entry point used
  `asyncio.get_event_loop().call_soon(...)` to schedule
  `display.start()`, then called `QtAsyncio.run()`.
  `QtAsyncio.run()` creates a **new** Qt-integrated event loop,
  orphaning the `call_soon` callback on the original default loop.
  The DDS reader tasks were never started.
- **Resolution:** Replaced with `QtAsyncio.run(display.start(), ...)`,
  which passes the coroutine directly to the Qt event loop. Removed
  unused `import asyncio`.
- **Guideline:** When using `QtAsyncio.run()`, always pass coroutines
  directly as the first argument — never pre-schedule on a separate
  asyncio loop. The Qt async integration creates its own loop.
- **Date closed:** 2026-03-27

---

## INC-048: Operator console simulator missing from Step 2.2 deliverables

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-27
- **Phase/Step:** Phase 2 / Step 2.2
- **Documents involved:** `docs/agent/implementation/phase-2-surgical.md`,
  `interfaces/participants/SurgicalParticipants.xml`,
  `interfaces/idl/app_names.idl`
- **Description:** Phase 2 Step 2.2 specifies "Implement operator input
  publisher", "Implement robot command publisher", and "Implement safety
  interlock publisher" as deliverables. The `ControlOperator` participant
  XML and all entity name constants were created, but no standalone
  operator console application was implemented. The integration tests
  created ad-hoc publishers inline, masking the gap. In a manual test,
  the robot controller had no operator input and stayed in IDLE.
- **Resolution:** Implemented `modules/surgical-procedure/operator_sim/`
  as a proper module package following canonical patterns: `__init__.py`,
  `__main__.py`, and `operator_console.py` (`OperatorConsole` class).
  Added Docker Compose containers for OR-1 and OR-3. Updated module
  README.
- **Guideline:** Each publisher/subscriber role in the implementation
  plan should map to a concrete launchable application, not just XML
  configuration and test fixtures. Future steps should verify that all
  `create_participant_from_config` participants in XML have a
  corresponding application entry point.
- **Date closed:** 2026-03-27

---

## INC-049: rtiddsgen 4.6.0 C++ RPC codegen variable shadowing

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-27
- **Phase/Step:** Phase 5 / Step 5.1
- **Documents involved:** `interfaces/idl/orchestration/orchestration.idl`,
  `interfaces/CMakeLists.txt`
- **Description:** When an `@service("DDS")` interface operation uses
  `request` as a parameter name (e.g., `start_service(in ServiceRequest request)`),
  rtiddsgen 4.6.0 generates C++ client `send_*` methods that shadow the
  function parameter with `auto& request = scratchpad_request()`. This
  causes two compile errors per method: (1) `-Werror=shadow` / hard error
  on redeclaration, and (2) the `_In` wrapper constructor receives the
  scratchpad `ServiceHostControl_Call&` instead of the original parameter
  type. Python codegen is unaffected.
- **Possible resolutions:**
  1. Rename the IDL parameter to avoid `request` (e.g., `req`).
  2. Post-generation `sed` patch to rename the local variable.
  3. Report upstream to RTI as a codegen defect.
- **Resolution:** Resolution 1 adopted — renamed IDL parameters from
  `request` to `req`. Clean fix, no post-gen patching required.
- **Guideline:** Avoid using `request` as an `@service("DDS")` interface
  parameter name in IDL. The rtiddsgen C++ template uses `request`
  internally for the scratchpad variable.
- **Date closed:** 2026-03-27

---

## INC-050: C++ RPC handler AWSet thread deadlock on factory/stop

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-28
- **Phase/Step:** Phase 5 / Step 5.4–5.5
- **Documents involved:** `modules/shared/medtech_dds_init/service_host.cpp`
- **Description:** The `dds::rpc::Server` dispatches RPC handler methods
  on an `AsyncWaitSet` (AWSet) thread at nesting level 1. When
  `start_service()` calls a factory that constructs an `AsyncWaitSet`
  (e.g., `RobotControllerService`), the nested AWSet creation triggers:
  `"dead lock risk: cannot enter WSCT of level 1 from WSCT of level 1"`.
  Similarly, `stop_service()` joining the service thread and destroying
  the service (which calls `sub_aws_.stop()`) deadlocks on the same
  nesting constraint. The error manifests as a `remoteEx` (discriminator=0)
  reply with code `UNKNOWN_EXCEPTION` (value=5).
- **Possible resolutions:**
  1. Delegate factory creation and stop/join to a worker `std::thread`
     so the AWSet thread is never nested.
  2. Defer service construction to `run()` rather than the constructor.
  3. Use `std::async` with `std::launch::async` for the factory call.
- **Resolution:** Resolution 1 adopted — both `start_service` and
  `stop_service` delegate blocking work to a temporary `std::thread`
  and join it before returning the result. This keeps the RPC handler
  non-blocking with respect to AWSet nesting.
- **Guideline:** Never create/destroy `AsyncWaitSet` instances from
  within an RPC handler. All DDS entity lifecycle work in RPC handlers
  must be delegated to a non-AWSet thread.
- **Date closed:** 2026-03-28

---

## INC-051: Test participant transport QoS must match AvoidIPFragmentation

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-28
- **Phase/Step:** Phase 5 / Step 5.5
- **Documents involved:** `tests/integration/test_*_service_host.py`,
  `interfaces/qos/Participants.xml`
- **Description:** Test participants created via bare
  `dds.DomainParticipant(domain_id)` use the default UDPv4
  `message_size_max=65507`. All XML-configured participants inherit
  `BuiltinQosSnippetLib::Transport.UDP.AvoidIPFragmentation`, which
  sets `message_size_max=1400`. This mismatch causes DDS to log
  `INVALID CONFIGURATION | the message_size_max, 1400 ... does not
  match the message_size_max, 65507` and silently drop RTPS packets
  larger than the smaller value. The result is intermittent discovery
  or data loss — tests pass sometimes but fail when the RPC reply or
  HostCatalog exceeds 1400 bytes.
  Additionally, the RTI Connext Python API does NOT expose
  `transport_builtin.udpv4.message_size_max` as a direct attribute
  (raises `AttributeError`). The correct API is the Property QoS:
  `qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"`.
- **Resolution:** All test `orch_participant` fixtures now set
  `message_size_max=1400` via the Property QoS API.
- **Guideline:** Any test participant on a domain shared with
  XML-configured participants must match the transport QoS. For the
  Orchestration domain (15), set
  `qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"`.
- **Date closed:** 2026-03-28

---

## INC-052: RPC reply union discriminator=0 is remoteEx, not method result

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-28
- **Phase/Step:** Phase 5 / Step 5.4
- **Documents involved:** `tests/integration/test_robot_service_host.py`,
  generated `orchestration.hpp` / Python `orchestration.py`
- **Description:** The RTI RPC `ServiceHostControl_Return` union uses
  `discriminator=0` for the `remoteEx` (remote exception) branch, not
  for any method result. When the server throws an unhandled exception,
  the reply has `discriminator=0, value=5` (UNKNOWN_EXCEPTION). If the
  test accesses `.start_service` on this reply, it raises
  `ValueError: Union field not selected by current discriminator (0)`.
  This is easy to confuse with "the RPC succeeded with OperationResultCode::OK"
  since `OK=0` in the IDL enum.
- **Resolution:** Robot test adds
  `assert reply.discriminator != 0, f"RPC returned remote exception"`.
  The root cause (INC-050) was also fixed so remoteEx no longer occurs.
- **Guideline:** Always check `reply.discriminator != 0` (or equivalently,
  check that the expected method branch is selected) before accessing
  RPC reply fields. Discriminator 0 = `remoteEx` in RTI RPC unions.
- **Date closed:** 2026-03-28

---

## INC-053: TRANSIENT_LOCAL HostCatalog stale cross-host reads

> **Note:** The `HostCatalog` topic was renamed to `ServiceCatalog` (INC-062).
> Historical references in this incident reflect the original name.

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-28
- **Phase/Step:** Phase 5 / Step 5.5
- **Documents involved:** `tests/integration/test_*_service_host.py`
- **Description:** When multiple service hosts share Domain 15
  (Orchestration), a test reader subscribing to `HostCatalog`
  (TRANSIENT_LOCAL, KEEP_LAST depth=1, keyed by `host_id`) may
  receive samples from a different host — particularly samples left
  over from a previous test module's subprocess that hasn't fully
  shut down. The test assumed `samples[0].data.host_id == HOST_ID`
  but received a stale sample from `clinical-host-test` while
  running the operational test suite. The same issue applies to
  `ServiceStatus` reads.
- **Resolution:** All test assertions now filter samples by `host_id`
  before checking values. HostCatalog tests use
  `matching = [s for s in samples if s.data.host_id == HOST_ID]`.
  ServiceStatus tests poll with a `host_id` filter rather than
  assuming `min_count` valid samples are all from the target host.
- **Guideline:** Never assume `samples[0]` belongs to the test's
  own host on a shared domain. Always filter by the key field
  (`host_id`, `service_id`) before asserting.
- **Date closed:** 2026-03-28

---

## INC-054: RTI Connext Logging API is not printf-style

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-30
- **Phase/Step:** Phase 5 / Step 5.6
- **Documents involved:** `modules/hospital-dashboard/procedure_controller/procedure_controller.py`
- **Description:** The `ModuleLogger` returned by `medtech_logging.init_logging()`
  wraps the RTI Connext Logging API. Its methods (`notice()`, `informational()`,
  `error()`, etc.) take a single string argument — not printf-style `(fmt, *args)`.
  Using `log.informational("msg: %s", value)` raises
  `TypeError: ModuleLogger.informational() takes 2 positional arguments but 3 were given`.
  The correct usage is `log.informational(f"msg: {value}")`.
- **Resolution:** All logging calls in the Procedure Controller use f-strings.
- **Guideline:** Always use f-strings with the medtech logging API:
  `log.informational(f"message: {val}")`, never `log.informational("message: %s", val)`.
- **Date closed:** 2026-03-30

---

## INC-055: rti.rpc.Service lifecycle: close_on_cancel and thread cleanup

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-30
- **Phase/Step:** Phase 5 / Step 5.6
- **Documents involved:** `tests/integration/test_procedure_controller.py`
- **Description:** When running `rti.rpc.Service.run()` on a background
  thread (via `asyncio.new_event_loop().run_until_complete()`), the
  service's `run()` blocks indefinitely and cannot be interrupted by
  `svc.close()` — calling `close()` while the service is running raises
  `PreconditionNotMetError: Cannot close a running service. Cancel the
  run() task first.` The correct pattern is: (1) hold a reference to the
  `asyncio.current_task()` inside the runner coroutine, (2) cancel that
  task using `loop.call_soon_threadsafe(task.cancel)`, (3) catch
  `CancelledError` in the runner, (4) then call `svc.close()` (which may
  raise `AlreadyClosedError` if `close_on_cancel=True` was used — wrap
  in try/except). This pattern makes in-process mock RPC services for
  tests feasible, though test hangs can still occur if the cleanup
  sequence is wrong. For Step 5.6, the RPC tests were simplified to
  unit-level call construction tests; full end-to-end RPC delivery is
  deferred to Step 5.7.
- **Resolution:** RPC tests in Step 5.6 verify call construction and
  requester creation without starting a mock RPC service. End-to-end
  RPC tests will use real Service Host subprocesses (Step 5.7) where
  process-level signal handling provides clean shutdown.
- **Guideline:** Do not attempt to run `rti.rpc.Service` on a background
  thread in unit/integration tests. Instead, test RPC call construction
  and requester creation separately. For full RPC validation, use
  subprocess-based tests with real Service Host binaries.
- **Date closed:** 2026-03-30

---

## INC-056: dispatch_async handler runs on DDS thread — segfault on Qt widget access

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-30
- **Phase/Step:** GUI Evolution — Procedure Controller
- **Documents involved:** `procedure_controller.py`,
  `docs/agent/vision/dds-consistency.md`,
  `docs/agent/vision/ui-design-system.md`
- **Description:** `WaitSet.dispatch_async()` with `set_handler()`
  invokes the handler callback on a DDS internal notification thread,
  not the asyncio/Qt event loop thread. When the handler performed Qt
  widget operations (rebuilding tile views, updating status bar,
  deleting widgets via `_remove_host()`), Qt emitted
  `"Cannot set parent, new parent is in a different thread"` errors
  followed by a segmentation fault. The root cause is that Qt widgets
  have thread affinity — they can only be modified from their owning
  thread (the main/UI thread).
- **Possible resolutions:**
  1. Use `wait_async()` instead of `dispatch_async()`. After
     `await wait_async()` returns, execution resumes on the asyncio
     event loop thread, making inline Qt widget operations safe.
  2. Use `dispatch_async()` + handler but bridge to the Qt thread via
     `QMetaObject.invokeMethod` or an `asyncio.Queue`.
- **Resolution:** Resolution 1 adopted. Replaced `dispatch_async()` +
  `set_handler()` with `await waitset.wait_async(timeout)` followed by
  inline status processing. The `dds.TimeoutError` exception on timeout
  is caught and the loop continues.
- **Guideline:** In Python GUI applications using QtAsyncio, **always
  use `wait_async()`** for status condition monitoring, not
  `dispatch_async()`. The `wait_async` pattern keeps all processing on
  the event-loop/Qt thread. Document this in the UI design system.
- **Date closed:** 2026-03-30

---

## INC-057: rti.rpc.Requester has native async API — ThreadPoolExecutor unnecessary

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-30
- **Phase/Step:** GUI Evolution — Procedure Controller
- **Documents involved:** `procedure_controller.py`,
  `docs/agent/vision/dds-consistency.md`
- **Description:** The Procedure Controller originally wrapped
  `rti.rpc.Requester` calls in a `ThreadPoolExecutor` because
  `receive_replies()` is blocking. However, RTI Connext 7.6.0 Python
  API provides native async methods:
  - `await requester.wait_for_service_async(timeout)` — async service
    discovery
  - `requester.send_request(call)` — non-blocking write (safe on
    event loop thread)
  - `await requester.wait_for_replies_async(timeout, related_request_id)`
    — async reply wait
  - `requester.take_replies(related_request_id)` — non-blocking drain
  Using these eliminates the need for `ThreadPoolExecutor` and
  `run_in_executor()` entirely. Source: `rti-chatbot-mcp` confirmed
  `send_request()` is a DDS write operation (not a blocking wait),
  and `receive_replies()` is documented as a convenience combining
  `wait_for_replies()` + `take_replies()`.
- **Resolution:** Removed `ThreadPoolExecutor`. Both `_do_rpc()` and
  `_do_rpc_display()` now use the native async Requester flow directly
  on the asyncio event loop.
- **Guideline:** For Python asyncio/QtAsyncio applications, prefer the
  native async `Requester` API over wrapping blocking calls in an
  executor. The pattern is:
  `await wait_for_service_async()` → `send_request()` →
  `await wait_for_replies_async()` → `take_replies()`.
- **Date closed:** 2026-03-30

---

## INC-058: Integration tests used time.sleep() for DDS discovery waits

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-31
- **Phase/Step:** Test Suite Optimization
- **Documents involved:** `tests/conftest.py`,
  `tests/integration/test_vitals_sim.py`,
  `tests/integration/test_camera_sim.py`,
  `docs/agent/vision/coding-standards.md`
- **Description:** Integration tests used `time.sleep(2.0)` after
  creating DDS entities to wait for discovery. This added ~20 seconds
  of fixed delay across the suite. DDS discovery on localhost typically
  completes in <100 ms, making these sleeps 20× longer than necessary.
  The proper approach is to use `StatusCondition` with
  `StatusMask.PUBLICATION_MATCHED` / `StatusMask.SUBSCRIPTION_MATCHED`
  and a `WaitSet` to block until discovery actually completes, with a
  generous timeout as a safety net.
- **Resolution:** Added `wait_for_discovery(writer, reader)` and
  `wait_for_reader_match(reader)` helpers to `conftest.py`. Both use
  `StatusCondition` + `WaitSet` and return as soon as matched status
  counts are > 0. All discovery sleeps in integration tests replaced
  with these helpers.
- **Guideline:** Never use `time.sleep()` to wait for DDS discovery.
  Use `StatusCondition(SUBSCRIPTION_MATCHED / PUBLICATION_MATCHED)` +
  `WaitSet.wait()` with a timeout. See `conftest.py` helpers.
- **Date closed:** 2026-03-31

---

## INC-059: Integration tests used polling loops and sleep for data delivery

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-31
- **Phase/Step:** Test Suite Optimization
- **Documents involved:** `tests/conftest.py`,
  `tests/integration/test_vitals_sim.py`,
  `tests/integration/test_camera_sim.py`,
  `tests/integration/test_robot_service_host.py`
- **Description:** Tests waiting for data samples used either
  `time.sleep(0.5)` or polling loops with `time.sleep(0.05)`. The DDS
  API provides `StatusCondition(StatusMask.DATA_AVAILABLE)` + `WaitSet`
  for event-driven notification. For TRANSIENT_LOCAL late-joiner
  scenarios, `DataReader.wait_for_historical_data(Duration)` blocks
  until cached samples are delivered. For reliable write-then-read
  patterns, `DataWriter.wait_for_acknowledgments(Duration)` ensures
  the reader has received the sample before proceeding.
- **Resolution:** Rewrote `wait_for_data()` in `conftest.py` to use
  `DATA_AVAILABLE` StatusCondition + WaitSet. Applied
  `wait_for_historical_data()` in durability and QoS enforcement tests.
  Applied `wait_for_acknowledgments()` in procedure context tests where
  writes precede takes.
- **Guideline:** Use the appropriate DDS blocking primitive:
  - **Discovery:** `StatusCondition(SUBSCRIPTION/PUBLICATION_MATCHED)` +
    `WaitSet`
  - **Data arrival:** `StatusCondition(DATA_AVAILABLE)` + `WaitSet`
  - **Late-joiner (TRANSIENT_LOCAL):** `reader.wait_for_historical_data()`
  - **Write confirmation (RELIABLE):** `writer.wait_for_acknowledgments()`
  See the Integration Test Timing Patterns section of
  `docs/agent/vision/coding-standards.md`.
- **Date closed:** 2026-03-31

---

## INC-060: Negative-proof sleeps in tests were overly conservative

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-31
- **Phase/Step:** Test Suite Optimization
- **Documents involved:** `tests/integration/test_domain_isolation.py`,
  `tests/integration/test_partition_isolation.py`,
  `tests/integration/test_multi_instance.py`,
  `tests/integration/test_procedure_controller.py`
- **Description:** "Negative proof" assertions (verifying that data does
  NOT arrive on an isolated reader) used `time.sleep(2)` or
  `time.sleep(3)`. On localhost, if data were going to leak across
  domains or partitions, it would arrive within milliseconds. A 0.5 s
  sleep provides a generous margin while saving ~1.5–2.5 s per
  occurrence (accumulated ~15 s across the suite).
- **Resolution:** Reduced all negative-proof sleeps to `time.sleep(0.5)`.
- **Guideline:** For negative-proof tests (asserting non-delivery),
  `time.sleep(0.5)` is sufficient on localhost. Do not exceed 1 second
  unless testing a time-dependent QoS (e.g., lifespan expiry).
- **Date closed:** 2026-03-31

---

## INC-061: Parallel test execution requires domain-aware grouping

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-31
- **Phase/Step:** Test Suite Optimization
- **Documents involved:** `pyproject.toml`, `requirements.txt`,
  `tests/integration/test_robot_service_host.py`,
  `tests/integration/test_operational_service_host.py`,
  `tests/integration/test_clinical_service_host.py`,
  `tests/integration/test_procedure_controller.py`
- **Description:** Adding `pytest-xdist` with `--dist loadfile` caused
  4 test failures. Service host tests on domain 15 (orchestration)
  launch subprocesses that publish/subscribe on shared topics. When
  multiple test files ran in parallel on domain 15, the service hosts
  interfered with each other (unexpected samples, premature matches).
  Tests on domain 10 were safe because they use distinct domain tags
  (clinical / operational / control) which provide partition-level
  isolation.
- **Resolution:** Switched to `--dist loadgroup`. All test files using
  domain 15 are marked with `@pytest.mark.xdist_group("orch")`, which
  forces them to run sequentially on a single xdist worker. All other
  tests run in parallel across workers.
- **Guideline:** When adding new integration tests:
  - Tests on domain 15 (orchestration): add
    `@pytest.mark.xdist_group("orch")` to `pytestmark`.
  - Tests on domain 10 with domain tags: safe for parallel execution
    (existing tag isolation is sufficient).
  - Tests on domain 0 or unique domains: safe for parallel execution.
  - If a new domain is shared across files, create a new xdist group.
- **Date closed:** 2026-03-31

---

## INC-062: HostCatalog → ServiceCatalog rename and ServiceRegistration introduction

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-31
- **Phase/Step:** Phase 5 / Evolution (post-completion)
- **Documents involved:**
  `interfaces/idl/orchestration/orchestration.idl`,
  `interfaces/idl/app_names.idl`,
  `interfaces/domains/Domains.xml`,
  `interfaces/qos/Topics.xml`,
  `interfaces/participants/OrchestrationParticipants.xml`,
  `modules/shared/medtech_dds_init/include/medtech/service_host.hpp`,
  `modules/shared/medtech_dds_init/service_host.cpp`,
  `modules/shared/medtech_dds_init/include/medtech/dds_init.hpp`,
  `modules/shared/medtech/service_host.py`,
  `modules/shared/medtech_dds_init/dds_init.py`,
  `modules/surgical-procedure/robot_service_host/robot_service_host.hpp`,
  `modules/surgical-procedure/clinical_service_host/clinical_service_host.py`,
  `modules/surgical-procedure/operational_service_host/operational_service_host.py`,
  `modules/surgical-procedure/operator_service_host/operator_service_host.py`,
  `modules/hospital-dashboard/procedure_controller/procedure_controller.py`,
  `tests/integration/test_robot_service_host.py`,
  `tests/integration/test_clinical_service_host.py`,
  `tests/integration/test_operational_service_host.py`,
  `tests/integration/test_procedure_controller.py`,
  all `docs/agent/` planning docs,
  both module READMEs
- **Description:** The single-per-host `HostCatalog` topic was replaced
  by a dual-keyed `ServiceCatalog` topic (`host_id` + `service_id`).
  Each Service Host now writes N DDS instances — one per registered
  service — instead of a single monolithic catalog.  This enables:
  (1) per-service `PropertyDescriptor` advertisement (name, current
  value, default, description, required) so the Procedure Controller
  can render configuration forms at discovery time without an RPC
  round-trip; (2) finer-grained liveliness — the controller can detect
  which services are offered without parsing a list.

  Structural changes:
  - **IDL:** `HostCatalog` removed; `ServiceCatalog` added with dual
    key.  `PropertyDescriptor` (`@appendable @nested`) added.
    `CapabilityReport.supported_services` removed (now redundant —
    discovered via `ServiceCatalog`).  `CapabilityReport` slimmed to
    just `capacity`.
  - **C++/Python framework:** `ServiceFactoryMap` replaced by
    `ServiceRegistryMap`, keyed by `EntityId` to `ServiceRegistration`.
    `ServiceRegistration` bundles factory + `display_name` +
    `vector<PropertyDescriptor>`.  `publish_host_catalog()` replaced by
    `publish_service_catalog()` (writes N instances).
    `get_capabilities()` returns only `capacity`.
  - **Concrete hosts:** All four hosts (robot, clinical, operational,
    operator) provide `ServiceRegistration` with `display_name` and
    empty `properties` (V1.0).
  - **Procedure Controller:** Internal state changed from
    `_hosts: dict[str, HostCatalog]` to
    `_catalogs: dict[tuple[str, str], ServiceCatalog]`.  Added
    `_known_host_ids()` and `_services_by_host()` helpers.  Host tile
    builder aggregates health from individual entries.
  - **Tests:** All four integration test suites updated to create
    `ServiceCatalog` topics, assert per-service instances, and remove
    `supported_services` assertions.
  - **XML configs:** Type registrations, topic names, writer/reader
    names, QoS profiles, and entity name constants all renamed.
  - **Planning docs:** All 8 `docs/agent/` files updated.
  - **Module READMEs:** Both updated.

  All 306 Python tests + 5 C++ tests + 12 CI gates pass.
- **Resolution:** Complete rename applied across ~30 files.
  RTI Connext `rti-chatbot-mcp` was consulted and validated the
  design: `PropertyDescriptor` should be `@appendable` (not `@final`)
  for future extensibility; `current_value` and `default_value` should
  be separate fields.  User explicitly declined `schema_version` /
  `config_version` fields.
- **Guideline:** When renaming a DDS topic/type, the full propagation
  chain is: IDL → codegen (automatic) → XML configs (Domains, QoS,
  Participants) → entity name constants (`app_names.idl`) →
  type registrations (`dds_init.hpp`/`dds_init.py`) → framework code →
  concrete hosts → subscribers (Procedure Controller) → tests →
  planning docs → module READMEs.  Missing any layer causes a build
  or runtime failure.  Start from the IDL and work outward.
- **Date closed:** 2026-03-31

---

## INC-063: Shared package consolidation — isort requires re-run after mass renames

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-31
- **Phase/Step:** Revision: Shared Package Consolidation / Steps RC.1–RC.2
- **Documents involved:** `modules/shared/medtech/service_host.py`,
  `modules/surgical-procedure/` (multiple service files)
- **Description:** After renaming imports from `medtech_dds_init`,
  `medtech_logging`, and `medtech_gui` to `medtech.dds`, `medtech.log`,
  and `medtech.gui`, the new import paths sort differently under isort's
  known-first-party classification. Automated `multi_replace_string_in_file`
  preserves the old line positions but does not re-sort the import block.
  Gate 1 (isort `--check`) caught 8 source files with incorrect ordering.
- **Resolution:** Ran `isort modules/ tests/` to auto-fix all affected files.
  Reinstalled to propagate fixes to the install tree. All 12 CI gates pass.
- **Guideline:** After any mass import rename, always run
  `isort modules/ tests/` before CI to fix sort order. Prefer running
  `bash scripts/ci.sh --lint` as an early smoke test after bulk edits.
- **Date closed:** 2026-03-31

---

## INC-064: markdownlint 0.48.0 MD060 table column alignment

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-31
- **Phase/Step:** Phase 5 / Step 5.8
- **Documents involved:** `modules/hospital-dashboard/README.md`,
  `modules/surgical-procedure/README.md`, `README.md`
- **Description:** markdownlint-cli 0.48.0 introduced rule MD060
  (table-column-count) which requires pipe characters to be
  consistently aligned across all rows in a Markdown table. All three
  project READMEs had tables with inconsistent column widths that
  passed under older markdownlint versions but fail under 0.48.0.
  Additionally, markdownlint 0.48.0 requires Node 20+ (uses regex `/v`
  flag unavailable in Node 18).
- **Resolution:** Wrote a Python auto-alignment script to reformat all
  tables with consistent pipe positions. Also fixed one MD040
  (fenced-code-block-language) violation in hospital-dashboard README.
  CI Gate 2 invokes markdownlint via `nvm use 20` to ensure Node 20
  compatibility.
- **Guideline:** When authoring Markdown tables, align pipe characters
  so every row has the same column widths. Use Node 20+ for
  markdownlint 0.48.0. Run `bash scripts/ci.sh --lint` after any
  README edits.
- **Date closed:** 2026-03-31

---

## INC-065: Docker BuildKit cache mount speeds up pip installs

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-31
- **Phase/Step:** Phase 5 / Step 5.8
- **Documents involved:** `docker/runtime-python.Dockerfile`,
  `scripts/ci.sh`
- **Description:** The Python runtime Dockerfile ran `pip install`
  without caching, re-downloading all packages on every build even
  when `requirements.txt` was unchanged. Docker Gate 7 was also
  building images sequentially.
- **Resolution:** Added `# syntax=docker/dockerfile:1` header and
  `RUN --mount=type=cache,target=/root/.cache/pip` to
  `runtime-python.Dockerfile`. Added `--parallel` flag to
  `docker compose build` in ci.sh. Extended `--skip-build` flag to
  also skip Gate 7.
- **Guideline:** Always use BuildKit cache mounts for package manager
  installs in Dockerfiles. Use `--parallel` for multi-image builds.
- **Date closed:** 2026-03-31

---

## INC-066: Test timeout defaults reduced 60–80% without failures

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-31
- **Phase/Step:** Phase 5 / Step 5.8
- **Documents involved:** `tests/conftest.py`, multiple test files
- **Description:** Default timeouts in conftest helpers were set
  conservatively during initial development: `wait_for_discovery` 5 s,
  `wait_for_data` 5 s, `wait_for_replier` 10 s, `wait_for_status`
  and `wait_for_all_states` 15 s. These defaults dominated test wall
  time in failure scenarios and were far above actual DDS latency
  (~50–200 ms for intra-host discovery, ~10 ms for data delivery).
  Reduced to: discovery 2 s, data 1 s, replier 3 s, status 5 s,
  all_states 5 s. Also reduced `_terminate_proc` defaults from 10 s
  to 3 s and `proc.wait()` timeouts to 3 s across service host tests.
  Full suite (321 tests) passes at the lower defaults. Test wall time
  dropped from ~33 s to ~29 s.
- **Resolution:** Lowered all defaults in `conftest.py`. Removed
  explicit `timeout_sec=10` overrides from `wait_for_discovery` in
  pure DDS tests (9 files). Subprocess-hosted tests retain explicit
  overrides where process startup requires more time.
- **Guideline:** Set test timeouts to 2–5× the expected latency, not
  10–50×. Pure DDS entity operations (discovery, data delivery) on
  localhost complete in under 500 ms; 1–2 s defaults are sufficient.
  Subprocess startup may need 3–5 s. Reserve 10+ s only for
  multi-process orchestration scenarios.
- **Date closed:** 2026-03-31

---

## INC-067: QueryCondition negative assertions replace sleep-based proofs

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-31
- **Phase/Step:** Phase 5 / Step 5.8
- **Documents involved:** `tests/integration/test_orchestration_e2e.py`
- **Description:** The partition isolation negative test in
  `test_best_effort_wildcard_coexistence` used `time.sleep(3)` followed
  by `read_data()` to prove no data arrived. This wasted 3 s of wall
  time per run and was not deterministic — it proved "no data arrived
  within 3 s" rather than "no data was deliverable."
- **Resolution:** Replaced with `dds.QueryCondition` filtering on the
  expected key field (`host_id = 'partition-test-host'`) combined with
  `assert not wait_for_data(reader, timeout_sec=1, conditions=...)`.
  This is faster (1 s worst-case) and semantically clearer: if the
  condition triggers, partition isolation is broken.
- **Guideline:** For negative data assertions ("this reader should NOT
  receive data"), use a `QueryCondition` with `wait_for_data()` and
  assert it returns `False`. Avoid `time.sleep()` + `read_data()`.
- **Date closed:** 2026-03-31

---

## INC-068: sed bulk edits require black auto-format pass

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-31
- **Phase/Step:** Phase 5 / Step 5.8
- **Documents involved:** Multiple test files under `tests/integration/`
- **Description:** Using `sed -i` to bulk-remove `timeout_sec=10` from
  `wait_for_discovery()` calls across 9 test files left trailing
  formatting artifacts (extra line breaks, misaligned arguments) that
  violated black's formatting rules. Gate 1 caught 5 files with
  violations.
- **Resolution:** Ran `black .` after the sed pass to auto-fix all
  formatting. All 5 files reformatted cleanly.
- **Guideline:** After any `sed`-based bulk edit, always run

---

## INC-069: QueryCondition prevents cross-test DDS sample pollution

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-04-01
- **Phase/Step:** Phase N / Step N.1
- **Documents involved:** `tests/integration/test_robot_service_host.py`, `tests/integration/test_orchestration_e2e.py`
- **Description:** Several orchestration-domain tests initially used `wait_for_data()` on an unfiltered reader and then filtered the returned samples afterward. In a parallel pytest run, unrelated samples published by other tests on the same DDS topic could satisfy the wait and leave the subsequent filter step empty, producing intermittent failures even though the target host had published correctly.
- **Possible resolutions:**
  1. Use a `dds.QueryCondition` inside `wait_for_data(..., conditions=[...])` so the wait itself is satisfied only by the intended content.
  2. Keep generic waits and add extra post-wait filtering / retries.
- **Resolution:** Resolution 1 adopted. Robot-service-host tests now wait on content-filtered `QueryCondition` objects keyed to the expected host/service fields, and the `ServiceCatalog` check includes the expected display name. This eliminates the need for a post-wait `take_data()` in the exact-match case and avoids cross-test DDS noise.
- **Guideline:** When a test needs a specific DDS sample from a shared topic, make the wait content-aware instead of waiting first and filtering later. `QueryCondition` + `wait_for_data()` is the preferred pattern for exact-match assertions in parallel test runs.
- **Date closed:** 2026-04-01
  `black .` (and `isort .` if imports were affected) before
  committing. Prefer `bash scripts/ci.sh --lint` as a quick check.
- **Date closed:** 2026-03-31

---

## INC-069: Root README.md excluded from markdownlint CI gate

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-31
- **Phase/Step:** Phase 5 / Step 5.8
- **Documents involved:** `scripts/ci.sh`, `README.md`
- **Description:** CI Gate 2 (markdownlint) only linted READMEs under
  `modules/` and `services/`. The root `README.md` was excluded,
  allowing MD060 table alignment violations to accumulate undetected.
- **Resolution:** Updated Gate 2 in `ci.sh` to include `README.md` in
  the glob pattern alongside `modules/*/README.md` and
  `services/*/README.md`. Fixed MD060 violations in the root README.
  Updated gate label to "Markdown lint (project + module READMEs)".
- **Guideline:** Any README that is part of the project documentation
  surface should be included in the markdownlint CI gate.
- **Date closed:** 2026-03-31

---

## INC-070: Routing Service cannot propagate participant-level partitions

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-31
- **Phase/Step:** Phase 3 / Step 3.1
- **Documents involved:** `vision/system-architecture.md`,
  `services/routing/RoutingService.xml`
- **Description:** The system architecture document states "Routing
  Service preserves the source partition" and "Data bridged from
  `room/OR-3/procedure/proc-001` is published on the Hospital domain
  with the same partition string." However, RTI Routing Service 7.6.0
  does **not** automatically propagate participant-level partition QoS
  from the input side to the output side. Verified via
  `rti-chatbot-mcp`: "Routing Service does not automatically propagate
  participant-level partitions." The RS output participant uses whatever
  partition is configured in its own `<domain_participant_qos>`, not
  the source participant's partition. The `<propagation_qos>` element
  does not exist for participant-level partitions in RS 7.6.0.
- **Possible resolutions:**
  1. Use wildcard partition `room/*/procedure/*` on both input and
     output RS participants. Hospital domain consumers match using
     compatible wildcards (e.g., `room/*` or `room/*/procedure/*`).
     Room/patient identity is carried in the data model fields.
  2. Create multiple RS output participants per room (static config).
  3. Implement a custom RS processor plugin for dynamic propagation.
- **Resolution:** Resolution 1 adopted. All RS participants (input and
  output) use `room/*/procedure/*` at the DomainParticipant QoS
  partition level. Hospital dashboard uses a compatible wildcard.
  Procedure Controller Hospital participant updated from `room/{room_id}`
  to `room/{room_id}/procedure/*` for RS compatibility. Data model fields
  (`room_id`, `patient.id`) provide the room/patient identity for
  UI filtering and content-filtered topics. This approach is consistent
  with the aggregation use case — the Hospital domain is a facility-wide
  view, not a per-room view.
- **Guideline:** When using participant-level partitions with Routing
  Service, configure matching wildcard partitions on both input and
  output RS participants. Do not rely on automatic partition propagation.
  Carry context identity (room, patient, procedure) in the data model
  for filtering, not solely in partition strings.
- **Date closed:** 2026-03-31

---

## INC-071: Hospital domain types not registered in initialize_connext()

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-31
- **Phase/Step:** Phase 3 / Step 3.2
- **Documents involved:** `modules/shared/medtech/dds.py`,
  `interfaces/domains/Domains.xml`
- **Description:** `initialize_connext()` registered types for the
  Procedure, Monitoring, Imaging, Devices, and Orchestration domains but
  not for Hospital domain types (`ClinicalAlerts::ClinicalAlert`,
  `ClinicalAlerts::RiskScore`, `Hospital::ResourceAvailability`).
  Creating the HospitalDashboard participant via
  `create_participant_from_config()` failed with
  "failed to get type definition for XML register_type
  name='ClinicalAlerts::ClinicalAlert'".
- **Resolution:** Added `clinical_alerts` and `hospital` imports and
  registered all three types in `initialize_connext()`. Any new domain
  or type added to `Domains.xml` requires a corresponding
  `register_idl_type()` call in `dds.py`.
- **Guideline:** When adding new XML-defined domains or topics that
  reference new IDL types, always update `initialize_connext()` with
  the corresponding `register_idl_type()` calls. The
  `create_participant_from_config()` API cannot resolve type references
  in domain library XML without prior IDL type registration.
- **Date closed:** 2026-03-31

---

## INC-072: test_camera_sim transport QoS mismatch in xdist parallel runs

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-31
- **Phase/Step:** Phase 3 / Step 3.2
- **Documents involved:** `tests/integration/test_camera_sim.py`,
  INC-051
- **Description:** `test_camera_sim.py::TestCameraServiceIntegration`
  created a test participant on domain 10 using
  `DomainParticipant.default_participant_qos` without setting
  `message_size_max=1400`. When running in parallel via pytest-xdist,
  this participant (message_size_max=65507) discovered other test
  participants with AvoidIPFragmentation (message_size_max=1400),
  causing transport mismatch errors and intermittent test failures.
  INC-051 previously fixed this in conftest participants but missed
  the camera test's inline participant creation.
- **Resolution:** Added
  `p.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"`
  to the camera test's `frame_reader` fixture. All test participants
  on Procedure domain 10 now use consistent transport QoS.
- **Guideline:** Every test participant that creates a
  `DomainParticipant` on a production domain (10, 11, 15, 20) must set
  `message_size_max=1400` via the UDPv4 property to match the project's
  AvoidIPFragmentation transport profile. Use the `participant_factory`
  conftest fixture when possible; when creating participants inline,
  always set the property explicitly.
- **Date closed:** 2026-03-31

---

## INC-073: NiceGUI `ui.image()` unreliable for static-served images

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-04-08
- **Phase/Step:** NiceGUI Migration / UI Polish
- **Documents involved:** `modules/shared/medtech/gui/_theme.py`,
  `tests/gui/test_init_theme.py`
- **Description:** `ui.image("/images/rti-logo-color.png")` with a
  static files route registered via `app.add_static_files("/images", ...)`
  did not render the logo in the header bar. The element was present in
  the DOM but the image did not display. Replacing `ui.image(...)` with
  `ui.html('<img src="/images/rti-logo-color.png" ...>')` rendered
  correctly and consistently. Root cause appears to be NiceGUI's
  `ui.image()` applying additional wrapper styling or sizing constraints
  that interfere with inline header layout.
- **Resolution:** Use `ui.html()` with a raw `<img>` tag for images
  that must render inline at a fixed size (e.g., logos in headers).
  Reserve `ui.image()` for standalone content images where NiceGUI's
  responsive sizing behavior is desirable.
- **Guideline:** When embedding images inline in constrained containers
  (headers, toolbars, badges), prefer `ui.html('<img src="..." style="...">')`.
  Use `ui.image()` only for content images in cards or full-width sections
  where default responsive behavior is acceptable. Always register the
  static files route via `app.add_static_files()` in `init_theme()`.
- **Date closed:** 2026-04-08

---

## INC-074: NiceGUI `asyncio.create_task()` loses slot context

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-04-08
- **Phase/Step:** NiceGUI Migration / UI Polish
- **Documents involved:**
  `modules/hospital-dashboard/procedure_controller/nicegui_controller.py`
- **Description:** Event handlers defined as
  `lambda: asyncio.create_task(some_async_func())` caused
  `RuntimeError: slot stack for this task is empty` when the async
  function attempted to create or modify NiceGUI UI elements. The root
  cause is that `asyncio.create_task()` spawns a new asyncio Task that
  inherits no NiceGUI slot context. NiceGUI internally tracks which UI
  container (slot) the current code is executing within; tasks spawned
  via `asyncio.create_task()` escape this tracking.
- **Resolution:** Replace all `lambda: asyncio.create_task(coro())`
  patterns with proper `async def` handlers passed directly to
  `.on("event", handler)` or `on_click=handler`. NiceGUI automatically
  awaits async handlers within the correct slot context. For
  button-specific handlers needing `click.stop` propagation, define the
  `async def` at the correct scope and pass it to `.on("click.stop", fn)`.
- **Guideline:** **Never use `asyncio.create_task()` for NiceGUI event
  handlers.** Always define `async def` handler functions and pass them
  directly to NiceGUI's `.on()` or `on_click` parameter. NiceGUI manages
  the slot context automatically for directly-passed async callables.
  The only safe use of `asyncio.create_task()` in NiceGUI code is in
  `app.on_startup` or `background_tasks.create()` where no UI slot
  context is needed.
- **Date closed:** 2026-04-08

---

## INC-075: Multiple `add_head_html` calls break position-dependent test assertions

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-04-08
- **Phase/Step:** NiceGUI Migration / UI Polish
- **Documents involved:** `modules/shared/medtech/gui/_theme.py`,
  `tests/gui/test_init_theme.py`
- **Description:** `init_theme()` originally had a single
  `ui.add_head_html()` call (for `@font-face` CSS). A test used
  `next(call for call in recorder.calls if call[0] == "add_head_html")`
  to find this call by position (first match). When a favicon
  `<link>` was added as a second `add_head_html()` call *before* the
  font CSS call, the test assertion failed because `next()` returned
  the favicon call instead of the font CSS call.
- **Resolution:** Changed the test to collect all `add_head_html`
  calls and filter by content (`"@font-face" in call[1][0]`) instead
  of relying on insertion order. Similarly, the header branding test
  expected `call[0] == "image"` which was updated to
  `call[0] == "html"` matching the new `ui.html('<img ...>')` pattern
  (see INC-073).
- **Guideline:** Test assertions for NiceGUI mock recorders must
  filter by **content**, not by **call position**. Use list
  comprehensions with content predicates
  (`[c for c in calls if "keyword" in c[1][0]]`) rather than
  `next(...)` which assumes a specific call order. This applies to
  any mock recorder pattern where multiple calls to the same NiceGUI
  function are recorded.
- **Date closed:** 2026-04-08

---

## INC-076: Python duplicate dict keys silently shadow — enforce ruff F601

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-04-08
- **Phase/Step:** NiceGUI Migration / UI Polish
- **Documents involved:** `modules/shared/medtech/gui/_icons.py`
- **Description:** The `ICONS` dictionary in `_icons.py` contained two
  entries with the key `"settings"`: one mapping to `"tune"` (line 21)
  and a later one mapping to `"settings"` (line 27, the Material Icon
  name). Python silently keeps the last duplicate, meaning
  `ICONS["settings"]` returned `"settings"` while the intended value
  `"tune"` was silently lost. This was caught by ruff rule `F601`
  ("Dictionary key literal repeated").
- **Resolution:** Removed the duplicate `"settings": "settings"` entry.
  Code referencing the gear/cog icon now uses `ICONS["update"]` (which
  maps to the `"settings"` Material Icon). The original
  `ICONS["settings"]` mapping (`"tune"`) is preserved for its intended
  "tune/adjust" semantics.
- **Guideline:** The `ICONS` dictionary is the **single source of truth**
  for icon name mappings. When adding new icons, always check for
  existing keys first. Ruff rule `F601` must remain enabled (it is
  auto-fixable) to catch duplicate keys at lint time. If two logical
  concepts need the same Material Icon glyph, give them distinct
  semantic keys (e.g., `"update"` and `"settings"` can both map to
  the `"settings"` glyph, but they must have different dict keys).
- **Date closed:** 2026-04-08

---

## INC-077: conftest `participant_factory` missing message_size_max — root cause of persistent flaky test

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-04-08
- **Phase/Step:** NiceGUI Migration / Pre-commit cleanup
- **Documents involved:** `tests/conftest.py`,
  `tests/integration/test_partition_isolation.py`, INC-051, INC-072
- **Description:** `test_partition_isolation.py::TestWildcardPartition::
  test_wildcard_receives_from_multiple` failed intermittently under
  pytest-xdist with `message_size_max` mismatch errors. INC-051 and
  INC-072 previously fixed individual inline participant creations but
  never fixed the root cause: the shared `_make_participant()` helper in
  `tests/conftest.py` (used by `participant_factory`) created
  participants with `DomainParticipant.default_participant_qos`
  (message_size_max=65507). Any test using `participant_factory`
  discovered xdist-parallel participants with
  AvoidIPFragmentation (1400), printing transport mismatch errors
  and occasionally failing due to dropped discovery messages.
- **Resolution:** Added
  `qos.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"`
  to `_make_participant()` in `conftest.py`, unconditionally. This
  fixes the problem at the source — all future tests using
  `participant_factory` automatically get consistent transport QoS.
  Verified: 362/362 tests pass twice in a row under xdist.
- **Guideline:** (Updated from INC-072) The `participant_factory`
  conftest fixture now sets `message_size_max=1400` automatically.
  Tests should always use `participant_factory` rather than creating
  `DomainParticipant` instances directly. If a test must create a
  participant inline, it must set the UDPv4 `message_size_max`
  property to `"1400"` explicitly.
- **Date closed:** 2026-04-08

---

## INC-078: Digital twin `__init__.py` PySide6 unconditional import blocks NiceGUI test collection

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-04-08
- **Phase/Step:** NiceGUI Migration / Step N.5
- **Documents involved:** `implementation/phase-nicegui-migration.md`,
  `modules/surgical-procedure/digital_twin/__init__.py`
- **Description:** After creating `nicegui_digital_twin.py`, the new
  test file `test_nicegui_digital_twin.py` imported from
  `surgical_procedure.digital_twin`, which triggered the package
  `__init__.py`. The original `__init__.py` unconditionally imported
  `RobotWidget` and `DigitalTwinDisplay` from PySide6-dependent modules,
  causing `ModuleNotFoundError: No module named 'PySide6'` even when
  only the NiceGUI backend was needed.
- **Possible resolutions:**
  1. Wrap the PySide6 imports in a try/except ImportError block so the
     NiceGUI backend remains importable when PySide6 is absent.
  2. Remove the legacy PySide6 exports from `__init__.py` entirely
     (too early — PySide6 removal is deferred to Step N.9).
- **Resolution:** Resolution 1 adopted. The `__init__.py` now exports
  `DigitalTwinBackend` unconditionally, and wraps the legacy
  `RobotWidget`/`DigitalTwinDisplay` imports in `try/except ImportError`.
  All 22 new tests pass with PySide6 absent.
- **Guideline:** When a NiceGUI implementation module is added alongside
  a legacy PySide6 module in the same package, the `__init__.py` must
  guard PySide6 imports so the NiceGUI exports remain importable in
  environments (CI, runtime containers) where PySide6 is not installed.
- **Date closed:** 2026-04-08

---

## INC-079: NiceGUI `ui.scene` background color not reactive at runtime (v3.9.x)

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-04-09
- **Phase/Step:** NiceGUI Migration / Step N.5 (post-commit visual iteration)
- **Documents involved:** `implementation/phase-nicegui-migration.md`,
  `modules/surgical-procedure/digital_twin/nicegui_digital_twin.py`
- **Description:** `ui.scene` sets the Three.js renderer background color
  once in the Vue component's `mounted()` hook (`renderer.setClearColor(this.backgroundColor)`).
  The `backgroundColor` prop has no Vue `watch:` block, so updating
  `scene._props["background-color"]` + `scene.update()` pushes the Vue
  prop but the renderer's clear color is never changed at runtime.
  Three approaches were attempted and all failed reliably:
  1. `scene._props["background_color"] + scene.update()` — wrong prop key
     (internal key is hyphenated `"background-color"`); even with the
     correct key, no watcher means the renderer is never notified.
  2. `getElement(id).renderer.setClearColor()` — `getElement()` returns
     Vue 3's public instance proxy which only exposes declared reactive
     members; `renderer` is assigned in `mounted()` without a `data()`
     declaration so the proxy returns `undefined`.
  3. `document.getElementById('c{id}').__vueParentComponent.ctx.renderer`
     — `ctx` is the internal component instance and does hold `renderer`,
     but the expression failed silently in some browser builds, suggesting
     the internal Vue 3 component tree layout is not stable API.
- **Resolution:** Fixed dark background (`THEME_PALETTE["dark"]["bg_bottom"]`
  = `#1B2838`) for the 3D scene, independent of the app UI theme toggle.
  This matches industry convention — every major surgical simulation
  platform (da Vinci, Stryker, Moog) uses a fixed dark neutral viewport
  to reduce eye strain and maximise contrast of colored arm segments.
  The `THEME_PALETTE["dark"]["arm"]` token is already in place; if
  NiceGUI adds a `watch: { backgroundColor }` in a future version the
  runtime-reactive path requires only restoring the removed callback.
- **Guideline:** Do not attempt to update `ui.scene` background color
  at runtime via prop manipulation or JavaScript in NiceGUI ≤ 3.9.x.
  Use a fixed scene background. File a NiceGUI upstream issue if
  per-theme scene background is a hard requirement.
- **Date closed:** 2026-04-09

---

## INC-080: `ui.scene` cylinder aesthetics — segment count and taper (NiceGUI v3.9.x)

- **Status:** Closed
- **Category:** Design decision
- **Date opened:** 2026-04-09
- **Phase/Step:** NiceGUI Migration / Step N.5 (post-commit visual iteration)
- **Documents involved:** `implementation/phase-nicegui-migration.md`,
  `modules/surgical-procedure/digital_twin/nicegui_digital_twin.py`,
  `vision/ui-design-system.md`
- **Description:** The NiceGUI `scene.cylinder(r_top, r_bottom, height, segments)`
  signature is not documented with segment count guidance. Through visual
  iteration, 16 segments produced visibly faceted silhouettes at the
  scene's ~1 m object scale; 32 segments produces a smooth round profile.
  Additionally, the design system's "flat fills" principle and the
  real-world cobot arm reference (Stryker, da Vinci) both suggest link
  segments should taper toward the distal joint. A taper ratio of
  `r_tip = r_base × 0.82` (18% narrowing) was found to match the
  visual proportion of commercially available 7-DOF surgical arms.
- **Resolution:** All arm link cylinders use 32 segments and the 0.82
  taper ratio. The `THEME_PALETTE["dark"]["arm"]` token (`#C8D2DC`) is
  added to `medtech/gui/_colors.py` as the canonical joint/shoulder
  sphere color per `ui-design-system.md §Theme Palettes`. The heatmap
  zero color was updated from `#263238` (near-black) to `#78909C`
  (the `heatmap-zero-light` token) so mid-range joints render as
  visible polished-steel grey rather than near-invisible charcoal.
- **Guideline:** Use 32 segments for all arm cylinders in the 3D scene.
  Apply `r_tip = r_base × 0.82` taper on link segments. Joint spheres
  and shoulder housing use `THEME_PALETTE["dark"]["arm"]`. Heatmap zero
  anchor is `#78909C`.
- **Date closed:** 2026-04-09

---

## INC-081: `orch` / `orch_e2e` xdist groups run concurrently on domain 15 — CPU contention causes subprocess timeout

- **Status:** Closed (mitigated; structural fix deferred)
- **Category:** Test infrastructure / CI flakiness
- **Date opened:** 2026-04-09
- **Phase/Step:** Phase 20, Step 20.1 CI
- **Documents involved:** `tests/integration/test_robot_service_host.py`,
  `tests/integration/test_orchestration_e2e.py`
- **Description:** `test_robot_service_host.py` uses `xdist_group("orch")` and
  `test_orchestration_e2e.py` uses `xdist_group("orch_e2e")`. Because they are
  *different* groups, pytest-xdist assigns them to different workers and runs
  them simultaneously — both on domain 15 with the `procedure` partition. The
  `orch_e2e` group launches the `all_service_hosts` module fixture (3–4 C++
  processes), creating peak CPU/network load precisely when `test_robot_service_host.py`
  (last alphabetically in the `orch` group) starts a `robot-service-host`
  subprocess. The subprocess could not complete DDS participant initialization
  and write its first ServiceCatalog sample within the 10 s fixture timeout.
- **Root cause:** The `orch`/`orch_e2e` split was introduced in Step 20.0 to
  prevent double-instantiation of the `all_service_hosts` module fixture
  (putting both files in `orch` caused two fixture instances in different workers).
  The side effect — concurrent domain-15 load — was not anticipated.
- **Resolution (immediate):** Increased `robot_service_host` fixture timeout
  from 10 s to 30 s (commit `83cfcaf`). This tolerates the contention without
  eliminating it.
- **Structural fix (deferred):** Merge `orch` and `orch_e2e` into a single
  group and prevent double-fixture instantiation via a session-scoped sentinel
  or `pytest-xdist` `--dist worksteal` with explicit fixture scoping. Requires
  spec-level planning; file as future implementation step.
- **Guideline:** Never create two xdist groups that share a DDS domain and
  where one group's module fixture launches external processes. Either use the
  same group (serialized) or use different domain IDs.
- **Date closed:** 2026-04-09

---

## INC-082: Partition isolation tests using BEST_EFFORT QoS — wrong abstraction, load-induced flakiness

- **Status:** Closed
- **Category:** Test design / CI flakiness
- **Date opened:** 2026-04-09
- **Phase/Step:** Phase 20, Step 20.1 CI
- **Documents involved:** `tests/integration/test_partition_isolation.py`
- **Description:** `TestWildcardPartition::test_wildcard_receives_from_multiple`
  and `TestSamePartition::test_same_partition_exchanges_data` used default
  `DataWriterQos()` / `DataReaderQos()`, which is BEST_EFFORT VOLATILE. Under
  full CI load (8 parallel workers), single BEST_EFFORT UDP samples written
  immediately after `wait_for_discovery()` were dropped by the OS socket
  buffer before the reader thread was scheduled. The test then failed with
  "Priming samples should arrive" or "Should receive from both OR-3 and OR-5".
  Multiple workaround attempts (burst write, extended timeouts, priming step)
  were applied before identifying the root cause.
- **Root cause:** These tests validate DDS *partition matching* semantics
  (does wildcard `room/*` match `room/OR-3/...`?), not delivery probability.
  BEST_EFFORT is the wrong QoS for any test with a delivery assertion —
  it introduces non-determinism that has nothing to do with the behavior
  under test.
- **Resolution:** Both tests now use `ReliabilityKind.RELIABLE` on writer and
  reader. RELIABLE on loopback guarantees delivery once matching is confirmed,
  making the test deterministic regardless of CPU load (commit `13ff4a4`).
  A single write per source is sufficient; burst size reduced back to 1.
- **Guideline:** Any test that makes a `wait_for_data` assertion MUST use
  RELIABLE QoS (or document explicitly why BEST_EFFORT is acceptable for the
  specific behavior under test). BEST_EFFORT is appropriate only for tests
  that explicitly test best-effort drop/loss behavior.
- **Date closed:** 2026-04-09

---

## INC-083: CFT XML requires expression_parameters default — SQL compiler error

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-04-10
- **Phase/Step:** Phase 20 / Post-step bug fix (multi-arm per-arm isolation)
- **Documents involved:** `interfaces/participants/SurgicalParticipants.xml`,
  `modules/surgical-procedure/robot_controller/robot_controller_service.cpp`
- **Description:** Adding `<content_filter kind="builtin.sql">` to XML
  Application Creation DataReaders with `<expression>robot_id = %0</expression>`
  but without `<expression_parameters>` causes the DDS SQL filter compiler
  to fail at participant creation time with "Unknown param used". The filter
  expression references parameter `%0` but no default value is provided in
  the XML, so the compiler cannot validate the expression.
- **Root cause:** RTI Connext XML Application Creation requires that
  parameterized CFT expressions include `<expression_parameters>` with a
  default value for every referenced `%N` parameter. The parameters are
  updated at runtime via `filter_parameters()` but must have initial
  values in the XML.
- **Resolution:** Added `<expression_parameters><element>'__unset__'</element></expression_parameters>`
  to all 3 CFT definitions in ControlRobot participant. At runtime, the C++
  service updates the parameter to the actual `robot_id` via
  `dds::core::polymorphic_cast<ContentFilteredTopic<T>>()` and
  `cft.filter_parameters()`. String parameters must include SQL single
  quotes in the parameter value (e.g., `"'arm-or1-01'"`), NOT in the
  expression — `'%0'` is parsed as literal string "%0" per RTI docs.
- **Guideline:** All parameterized CFT expressions in XML MUST include
  `<expression_parameters>` with placeholder defaults. String parameters
  require SQL quotes in the value, not the expression.
- **Date closed:** 2026-04-10

---

## INC-084: key_value() crash on NOT_ALIVE instance handles during shutdown

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-04-10
- **Phase/Step:** Phase 20 / Post-step bug fix (multi-arm shutdown)
- **Documents involved:** `modules/surgical-procedure/digital_twin/digital_twin.py`,
  `modules/hospital-dashboard/procedure_controller/controller.py`
- **Description:** When DDS services shut down, subscribers may receive
  `NOT_ALIVE_DISPOSED` followed by `NOT_ALIVE_NO_WRITERS` for the same
  instance. After the first disposal, the middleware may purge the instance
  handle. Calling `key_value()` on the purged handle raises
  `rti.connextdds.InvalidArgumentError: Invalid argument error: get key value`.
  This manifested as runtime errors during service shutdown in both the
  digital twin and procedure controller.
- **Root cause:** Race between two not-alive notifications —
  `NOT_ALIVE_DISPOSED` and `NOT_ALIVE_NO_WRITERS` — where the instance
  handle is purged by the middleware between the two events.
- **Resolution:** Wrapped `key_value()` calls in `try/except dds.InvalidArgumentError`
  with `continue` to skip samples with purged instance handles. This is a
  safe guard — the instance is already being removed from the tracking table.
- **Guideline:** Always guard `key_value()` calls with
  `try/except InvalidArgumentError` when processing not-alive samples,
  as the instance handle may have been purged between notifications.
- **Date closed:** 2026-04-10

---

## INC-085: Dead code — robot_controller_app.cpp not in any CMakeLists.txt

- **Status:** Closed
- **Category:** Housekeeping
- **Date opened:** 2026-04-10
- **Phase/Step:** Phase 20 / Post-step cleanup
- **Documents involved:** `modules/surgical-procedure/robot_controller/robot_controller_app.cpp`
- **Description:** `robot_controller_app.cpp` (306 lines) contained a
  standalone DDS application with duplicated entity wiring logic that
  paralleled `robot_controller_service.cpp`. The file was not referenced
  in any `CMakeLists.txt` and was never compiled or linked. It originated
  from an earlier iteration before the Service/ServiceHost architecture
  was established.
- **Resolution:** File deleted. The canonical pattern is:
  Service (reusable logic) → standalone `main.cpp` → ServiceHost `main.cpp`
  (with orchestration RPC). All DDS entity wiring lives in the service class.
- **Date closed:** 2026-04-10

---

## INC-086: Empty Observability domain breaks Routing Service XML validation

- **Status:** Closed
- **Category:** Bug
- **Date opened:** 2026-04-13
- **Phase/Step:** Phase UI-M / Routing Service integration
- **Documents involved:** `interfaces/domains/Domains.xml`,
  `services/routing/RoutingService.xml`
- **Description:** The `MedtechDomains::Observability` domain (domain 20)
  was declared as an empty `<domain>` element with no `<register_type>` or
  `<topic>` children. While the application-level QoS provider accepted
  this, Routing Service's stricter XML parser rejected it with:
  `Element 'domain': Missing child element(s). Expected is one of
  ( register_type, topic ).` This caused RS to exit with code 255.
- **Root cause:** The Observability domain was a placeholder for Monitoring
  Library 2.0 internal topics, which are created automatically at runtime
  and don't need XML declarations. The empty element violated the XSD
  `xs:sequence` constraint requiring at least one child.
- **Resolution:** Removed the empty `Observability` domain from
  `Domains.xml`. Domain 20 is not referenced by any participant config
  or routing service route. Monitoring Library creates its topics
  independently of domain library declarations.
- **Guideline:** Do not declare empty `<domain>` elements in domain
  library XML. If a domain has no application-defined topics, omit it.
- **Date closed:** 2026-04-13

---

## INC-087: content_filter / datareader_qos element ordering in SurgicalParticipants.xml

- **Status:** Closed
- **Category:** Bug
- **Date opened:** 2026-04-13
- **Phase/Step:** Phase UI-M / Routing Service integration
- **Documents involved:** `interfaces/participants/SurgicalParticipants.xml`
- **Description:** Three `<data_reader>` elements in the `ControlRobot`
  participant's `RobotSubscriber` had `<datareader_qos>` preceding
  `<content_filter>`. The RTI DDS profiles XSD requires `<content_filter>`
  to appear before `<datareader_qos>` within a `<data_reader>` element.
  While the application-level QoS provider tolerated the misordering,
  Routing Service's XML parser (which validates the full
  `NDDS_QOS_PROFILES` file set) rejected it with: `Element
  'content_filter': This element is not expected.` This caused RS to exit
  with code 255.
- **Root cause:** The original XML was authored with `<datareader_qos>`
  first, then `<content_filter>`. The XSD `xs:sequence` defines
  `content_filter` before `datareader_qos` in the element order.
- **Resolution:** Reordered all three `<data_reader>` elements to place
  `<content_filter>` before `<datareader_qos>`, matching the XSD schema.
  Affected readers: `OperatorInputReader`, `RobotCommandReader`,
  `SafetyInterlockReader`.
- **Guideline:** When authoring participant XML with both
  `<content_filter>` and `<datareader_qos>` inside a `<data_reader>`,
  always place `<content_filter>` first. Use the XSD schema
  (`rti_dds_profiles.xsd`) as the authoritative element order reference.
- **Date closed:** 2026-04-13

---

## INC-088: Routing Service admin/monitoring incompatible with autoenable=false

- **Status:** Open
- **Category:** Limitation
- **Date opened:** 2026-04-13
- **Phase/Step:** Phase UI-M / Routing Service integration
- **Documents involved:** `services/routing/RoutingService.xml`,
  `interfaces/qos/Participants.xml`
- **Description:** The Routing Service `<administration>` and
  `<monitoring>` sections create internal DDS participants on Domain 20.
  These participants inherit QoS from `Participants::Transport`, which
  sets `entity_factory.autoenable_created_entities` to `false`. RS's
  internal admin publisher is never explicitly enabled, causing:
  `DDS_DataWriter_enableI: ERROR: parent publisher is not enabled`.
  This prevents RS from starting when admin/monitoring is configured.
- **Root cause:** `Participants::Transport` disables auto-enable so that
  application participants can set partition QoS before enabling. RS's
  internal admin participant inherits this but has no mechanism to
  explicitly enable after creation.
- **Possible resolutions:**
  1. Create a dedicated `Participants::AdminTransport` QoS profile that
     inherits from `Transport` but re-enables auto-enable.
  2. Override `entity_factory` inline in the RS `<administration>` section.
  3. Leave admin/monitoring commented out (current state).
- **Resolution:** Pending. Admin and monitoring sections are commented out
  in `RoutingService.xml` with an explanatory note. Functional bridging
  is unaffected.

---

## INC-089: Dashboard empty — requires Routing Service bridge (Domain 10 → 11)

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-04-13
- **Phase/Step:** Phase UI-M / Dashboard integration
- **Documents involved:** `modules/hospital-dashboard/dashboard/dashboard.py`,
  `services/routing/RoutingService.xml`, `scripts/simulate_room.py`
- **Description:** The Hospital Dashboard subscribes on Domain 11
  (Hospital) but simulation services publish on Domain 10 (Procedure).
  Data only reaches Domain 11 via Routing Service bridging. Running
  `simulate_room.py` without Routing Service left the Dashboard empty
  with no procedures, vitals, or alerts displayed.
- **Root cause:** Routing Service was not launched as part of the room
  simulation. The domain separation (Procedure 10 → Hospital 11) is
  architecturally correct but requires the bridge to be running.
- **Resolution:** `simulate_room.py` now automatically launches Routing
  Service alongside the other room services. The `--no-bridge` flag
  skips RS if not needed. RS uses the standard `NDDS_QOS_PROFILES`
  from `setup.bash` (after INC-086 and INC-087 fixes).
- **Date closed:** 2026-04-13

---

## INC-091: Domain ID migration required broader scope than revision plan

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-04-14
- **Phase/Step:** Revision: Domain ID Migration / Steps DM.1–DM.10
- **Documents involved:** `implementation/revision-domain-id-migration.md`
- **Description:** The revision plan covered the primary XML configuration
  files, IDL, controller code, and the explicitly listed test files.
  During implementation, additional files required updates that were not
  enumerated in the plan:
  1. `interfaces/qos/Topics.xml` — domain number comments (Hospital 11→20,
     Orchestration 15→11)
  2. `interfaces/idl/orchestration/orchestration.idl` — domain comment (15→11)
  3. `docker-compose.yml` — `OBSERVABILITY_DOMAIN: "20"` → `"19"`
  4. `scripts/simulate_room.py` — Routing Service bridge comment (11→20)
  5. `tests/integration/test_observability.py` — observability domain assertions
     (20→19)
  6. Five additional test files with `ORCHESTRATION_DOMAIN_ID = 15` beyond
     the three explicitly listed in the plan (`test_clinical_service_host.py`,
     `test_controller_arm_tracking.py`, `test_acceptance_orchestration.py`,
     `test_acceptance_multi_arm.py`, `test_operational_service_host.py`,
     `test_multi_arm_orchestration.py`, `test_multi_arm_isolation.py`)
  7. `Domains.xml` — `ServiceCatalog` type+topic registration needed in
     Hospital domain for the new `HospitalDashboard::ServiceCatalogReader`
  All were straightforward mechanical updates consistent with the migration.
- **Guideline:** Future domain ID / architectural constant revisions should
  use `grep` to discover all references rather than enumerating files by
  memory. A comprehensive search pattern like `domain.?15|ORCHESTRATION_DOMAIN`
  catches references that the plan author may not recall.
- **Resolution:** All additional files updated and verified via full CI (647
  tests passing, 12/12 gates).
- **Date closed:** 2026-04-14

## INC-092: Bulk sed rename produced text artifacts in docs

- **Status:** Closed
- **Severity:** Low
- **Category:** Discovery
- **Date opened:** 2026-04-15
- **Phase/Step:** Revision: Databus Terminology Alignment / Steps T.3a–T.3b
- **Documents involved:** `implementation/revision-databus-terminology.md`
- **Description:** The bulk `sed` rename in steps T.3a (38 markdown files) and
  T.3b (32 code/XML files) produced three classes of text artifacts:
  1. **"databuss" typo** (12 occurrences) — `sed 's/domains/databuses/g'`
     pattern also transformed partial-word matches like "domains" at end of
     compound replacements, yielding "databuss" instead of "databuses".
  2. **Doubled-name patterns** (9 occurrences) — e.g.,
     `Hospital Integration databus (Hospital Integration databus)`. The
     original text was `Hospital domain (Domain 20)` and two sed passes
     (one replacing the name, one replacing the parenthetical) each produced
     the new name, creating a redundant double.
  3. **Stale mixed terminology** (4 occurrences) — e.g.,
     `Hospital integration domain (Hospital Integration databus)` where the
     parenthetical was updated but the preceding text was not.
  All were cosmetic defects in documentation — no code, XML, or test impact.
- **Guideline:** Bulk `sed` renames across natural-language prose are
  error-prone. For future terminology revisions: (a) use targeted
  `replace_string_in_file` / `multi_replace_string_in_file` instead of
  piped `sed` where feasible, (b) run post-rename grep sweeps for
  common artifact patterns (doubled names, typos), (c) on WSL `/mnt/c/`
  prefer VS Code edit APIs over `sed` to avoid the "overwrite unsaved
  changes" dialog caused by slow cross-filesystem file watcher
  notifications.
- **Resolution:** All 25 occurrences fixed in commit `350d430`.
- **Date closed:** 2026-04-15
