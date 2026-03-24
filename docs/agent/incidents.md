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
