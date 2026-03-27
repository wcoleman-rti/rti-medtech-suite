# Capabilities

## V1 Scope

V1 delivers three core modules that together demonstrate the key value propositions of RTI Connext in a medtech environment: real-time deterministic communication, multi-domain isolation, cross-domain bridging, and facility-wide situational awareness.

---

### Module 1: Surgical Procedure

A multi-instance module — each running instance represents one operating room with an active surgical procedure.

#### Sub-capabilities

| Sub-capability | Description | Domain / Tag |
|----------------|-------------|---------------|
| **Robot Teleop/Control** | Operator input → robot command stream. Robot state feedback. Safety interlock monitoring. Closed-loop control path with strict latency and deadline requirements. | Procedure (`control`) |
| **Camera Feed** | Simulated endoscope/surgical camera publishing frames (metadata + image reference). Consumed by operator display and optional processing pipeline. | Procedure (`operational`) |
| **Patient Vitals** | Simulated bedside monitor publishing vital signs (HR, SpO2, BP, temp, etc.) and physiological waveforms (ECG, pleth, capnography). Alarm generation on threshold violations. | Procedure (`clinical`) |
| **Procedure Context** | Medical setting metadata: hospital, room, bed, assigned patient, procedure type, surgeon, anesthesiologist, start time. Published once at procedure start, updated on changes. Durable for late joiners. | Procedure (`operational`) |
| **Procedure Status** | Running status of the procedure (in-progress, completing, alert). Published periodically and on state transitions. Durable for late joiners. Bridged to Hospital domain via Routing Service for dashboard consumption. | Procedure (`operational`) |
| **Device Telemetry** | Simulated device status for ancillary devices (infusion pump, anesthesia machine). Read-only telemetry for dashboard consumption. | Procedure (`clinical`) |
| **Digital Twin Display** | Per-OR PySide6 GUI rendering a schematic 2D visualization of the surgical robot arm — joint positions, tool tip, active command, operational mode, and safety interlock status. Read-only subscriber to `control`-tag topics (`RobotState`, `RobotCommand`, `SafetyInterlock`, `OperatorInput`). Uses time-based filter to downsample to the rendering frame rate. | Procedure (`control`) |

#### Multi-Instance Behavior

- All instances use the **same domain IDs, domain tags, and topic names**
- Room/procedure isolation is achieved via **domain partitions** using an xpath-like naming convention:
  - Per-instance: `room/OR-3/procedure/proc-2026-0042`
  - Wildcard matching enables multi-context subscriptions:
    - `room/OR-3/*` — all data in OR-3 regardless of procedure
    - `room/*/procedure/*` — all procedures across all rooms (dashboards, aggregators)
    - `room/OR-*` — match a subset of rooms by name pattern
- Launching a new instance requires only a different partition configuration — no code or topic changes
- Simulated scenarios can run 2–4 concurrent ORs to demonstrate isolation and dashboard aggregation

### Module 2: Hospital Dashboard

A single facility-wide PySide6 GUI application displaying real-time status across all active surgical procedures.

#### Sub-capabilities

| Sub-capability | Description |
|----------------|-------------|
| **Procedure List** | Real-time list of all active procedures with status indicators (in-progress, completing, alert). Auto-discovers new procedures via DDS. |
| **Vitals Overview** | Summarized vitals for each procedure/patient. Color-coded by severity. Click-to-expand for detail. |
| **Alert Feed** | Aggregated clinical alerts and alarms across all ORs. Filterable by severity, room, patient. |
| **Robot Status** | Read-only view of robot state per OR (operational, paused, e-stop, disconnected). |

#### Architecture

- Subscribes to Hospital domain topics
- Data arrives via Routing Service bridge from Procedure domain
- Uses content-filtered topics to support per-room drill-down views
- DDS reads occur off the main Qt thread via QtAsyncio; data is delivered to widgets via Qt signals or async coroutines

### Module 3: Clinical Alerts & Decision Support

A Clinical Decision Support (ClinicalAlerts module) engine that subscribes to patient vitals and procedure context, computes risk scores, and publishes clinical alerts.

#### Sub-capabilities

| Sub-capability | Description |
|----------------|-------------|
| **Risk Scoring** | Consumes vitals streams, computes configurable risk scores (e.g., hemorrhage risk, sepsis early warning). Publishes scores on `RiskScore` topic. |
| **Alert Generation** | Threshold and trend-based alert generation. Publishes on `ClinicalAlert` topic. Alerts include severity, category, rationale. |
| **Cross-Domain Subscription** | Subscribes to surgical domain data via Routing Service. Demonstrates content filtering and QoS-differentiated consumers. |

---

## Connext Features Demonstrated by V1

| Feature | Where Exercised |
|---------|-----------------|
| Multi-domain isolation | Procedure domain vs Hospital domain |
| Domain tags (risk-class) | `control` vs `clinical` vs `operational` within Procedure domain |
| Domain partitions | Room/procedure isolation across surgical instances; wildcard matching for aggregation |
| Real-time deterministic streaming | Robot teleop, waveforms, camera frames |
| QoS differentiation | Stream vs State vs Command patterns, topic-filter-bound profiles |
| Content-filtered topics | Dashboard per-room views, ClinicalAlerts per-patient subscription |
| Time-based filter | GUI readers downsampled to display refresh rate |
| Routing Service (cross-domain bridge) | Procedure → Hospital, selective topic/data forwarding |
| TRANSIENT_LOCAL durability | Late-joining dashboards receive current state |
| Exclusive ownership (failover) | Service gateway redundancy (simulated) |
| XML-based QoS configuration | All QoS from shared profiles, zero programmatic QoS |
| Topic filters in QoS | QoS auto-resolved by topic name via `topic_filter` |
| Cloud Discovery Service | Multicast-free discovery across Docker networks and hospital segments |
| Connext Logging API + Observability Framework | Centralized log collection across distributed modules via Monitoring Library 2.0 → Collector Service → Grafana Loki |
| Observability Framework | Monitoring Library 2.0 on all participants; Collector Service → Prometheus + Grafana Loki; RTI Grafana dashboards for system health and debugging |
| Integrated build (CMake) | Single build produces C++ services, Python GUIs, generated types |

---

## Versioned Milestone Roadmap

The full release version policy — including version increment rules, release criteria, and version boundary governance — is defined in [versioning.md](versioning.md). The milestone descriptions here focus on capability scope.

---

### V1.1.0 — Procedure Orchestration

**Theme:** Introduce a service-oriented orchestration layer for managing the lifecycle of surgical procedure services across distributed Service Hosts, using DDS RPC for directed commands and pub/sub for asynchronous state distribution on a dedicated Orchestration domain.

#### Service Interface & Dual-Mode Services
- **`medtech::Service` abstract interface** (C++ abstract class, Python ABC) defining the contract for all DDS service classes: `run()`, `stop()`, `name`, `state` — enabling consistent lifecycle management across languages
- **`ServiceState` enum** — pollable state exposed by every service: `STOPPED`, `STARTING`, `RUNNING`, `STOPPING`, `FAILED`, `UNKNOWN` — the Service Host polls this and publishes `ServiceStatus` to the Orchestration domain
- **Dual-mode constructor** — all existing V1.0 service classes (robot controller, bedside monitor, camera simulator, operator console, device gateway, procedure context publisher) refactored to accept a nullable `DomainParticipant` parameter:
  - `None` / `dds::core::null` → standalone mode: service creates its own participant (backward-compatible with existing Docker Compose deployment)
  - Valid participant → hosted mode: service uses the provided participant, lifecycle managed by Service Host
- **Validation** — services validate participant creation succeeded and that all expected writers/readers are found, regardless of mode
- **Reference-type lifecycle** — no `owns_participant` flag needed; DDS entities are reference types that self-clean when the last reference goes out of scope

#### Procedure Controller
- Surgeon-facing PySide6 GUI application for driving the procedure lifecycle: select patient, procedure type, equipment configuration, start procedure, monitor, stop
- Subscribes to Hospital domain for scheduling context and patient information (read-only, via Routing Service bridge)
- Issues service lifecycle commands via DDS RPC (`ServiceHostControl` interface) to targeted Service Hosts on the Orchestration domain
- Subscribes to `HostCatalog` and `ServiceStatus` topics on the Orchestration domain for real-time visibility of host availability and service state
- Reconstructs full orchestration state on restart via TRANSIENT_LOCAL status topics

#### Service Host Framework
- Distributed process that hosts and manages DDS services locally on behalf of the Procedure Controller
- Exposes a `ServiceHostControl` RPC service (uniquely named per host instance) for receiving start/stop/configure commands
- Polls hosted services' `state` property and publishes `HostCatalog` (capabilities, health) and `ServiceStatus` (per-service lifecycle state) on the Orchestration domain
- Reconciliation loop: on startup or controller reconnection, compares desired state from RPC commands against actual local service state and converges
- Specialized subtypes: Robot Service Host (C++, manages robot controller), Clinical Service Host (Python, manages vitals/alarms/telemetry), Operational Service Host (Python, manages camera/context)

#### Orchestration Domain
- New dedicated DDS domain (no domain tags) for infrastructure lifecycle management
- Completely isolated from the Procedure domain's surgical data — different lifecycle (Service Hosts span multiple procedures)
- Procedure domain continues to route directly to Hospital domain via Routing Service — Orchestration domain is **not** on that data path
- Hybrid communication model: DDS RPC (`Pattern.RPC`) for directed commands, pub/sub (`Pattern.Status`) for asynchronous state

| Module / Capability | Connext Features Demonstrated |
|---------------------|-------------------------------|
| Procedure Controller (PySide6 GUI) | DDS RPC client (Modern C++ and Python), multi-domain participant (Hospital + Orchestration), QtAsyncio integration |
| Service Host framework | DDS RPC service, dual-mode service lifecycle, per-host unique service naming |
| Orchestration domain | Dedicated domain for infrastructure control-plane, `Pattern.Status` for state topics, `Pattern.RPC` for command channel |
| `HostCatalog` + `ServiceStatus` topics | TRANSIENT_LOCAL state reconstruction, write-on-change, liveliness-based host failure detection |
| `ServiceHostControl` RPC interface | IDL `@service` interface, typed request/reply, generated client/service stubs for C++ and Python |
| `medtech::Service` interface | Consistent service contract across C++ and Python, pollable `ServiceState` for lifecycle reporting |

---

### V1.2.0 — Recording & Replay

Additive within the V1 milestone. No structural changes to V1 modules.

- **RTI Recording Service** — passive multi-domain capture of all DDS traffic across Procedure, Hospital, and Orchestration domains. Recording Service operates as a multi-domain subscriber, joining the Procedure domain (all domain tags), the Hospital domain, and the Orchestration domain simultaneously. A single Recording Service instance captures the complete system state.
- **RTI Replay Service** — deterministic replay into subscriber applications for training, incident review, and regression testing
- `@recording` and `@replay` spec scenarios added to cover capture completeness and replay fidelity
- **Resource Status** — `ResourceAvailability` topic on the Hospital domain: OR, bed, equipment,
  and staff availability simulator; resource status panel added to the Hospital Dashboard.
  Deferred from V1.0 to keep the initial release scope focused. Spec scenarios and a new
  implementation step will be authored when this milestone is approved for implementation.

#### Foxglove Data Model Alignment
- **Foxglove schema translatability (Tier 1 — data model only)** — `Surgery::RobotState` updated with Foxglove-compatible fields (`joints` as `sequence<JointState>`, `tool_tip_pose` as `Common::Pose`); new helper structs (`Common::Quaternion`, `Common::Vector3`, `Common::Pose`); new `Surgery::RobotFrameTransform` topic publishing the kinematic frame hierarchy at 100 Hz; `Imaging::CameraFrame` streamlined (timestamp and frame_id removed, format changed to enum). See [data-model.md — Foxglove Schema Alignment](data-model.md#foxglove-schema-alignment).
- **Translatable, not aligned** — V1.2 ensures all DDS types destined for Foxglove visualization are *translatable*: every field required by the target Foxglove schema is assemblable from medtech DDS data, `SampleInfo` metadata, or configuration lookups. Types are DDS-native first (enums over strings, no redundant payload fields). No Foxglove IDL compilation, no transformation plugins, no adapter/storage plugins, and no Foxglove Studio connectivity are included in V1.2. The full integration infrastructure is delivered in V2.

---

### V2.0.0 — Security & Hospital Integration Gateways

**Theme:** Harden the data bus with Connext Security Plugins and introduce simulated external hospital system integrations, demonstrating the open pub/sub model for hospital IT interoperability.

#### Security (Phase 7)
- Connext Security Plugins with per-participant identity (leaf certificates issued from a central CA)
- Domain-level governance documents per functional domain (`Governance_Procedure.xml`, `Governance_Hospital.xml`)
- Topic-level protection: encryption for `clinical`-tag data, encrypt + sign for `control`-tag data, signing for `operational` data
- Origin authentication: verify the identity of the data source — critical for safety-class (`control` tag) data paths
- Least-privilege permissions: dashboards read-only, controllers write-only where appropriate
- Certificate Revocation Lists (CRL) for managing revoked participant identities without system restart
- Pre-shared key (PSK) authentication for constrained or embedded device contexts
- File polling for live certificate/CRL rotation without participant restart
- Security posture and policies fully defined in `vision/security.md` and `interfaces/security/governance/` before implementation begins

#### EHR Gateway (Epic/FHIR bridge simulation)
- *Inbound:* seeds `ProcedureContext` from scheduled patient and procedure data before procedure start
- *Outbound:* reports procedure status progression and intraoperative events back to the EHR record
- Demonstrates the full procedure lifecycle: pre-op data load → live DDS bus → post-op documentation

#### LIS Gateway (Lab Information System)
- *Inbound:* publishes `LabResult` on the `clinical` domain tag (blood gas, hemoglobin, coagulation panel)
- Feeds directly into ClinicalAlerts risk scoring and alert logic alongside device-generated vitals
- Demonstrates how external critical results integrate with the same alert pathway as device alarms

#### AIMS Gateway (Anesthesia Information Management System)
- Read-only multi-topic subscriber: `PatientVitals`, `WaveformData`, `DeviceTelemetry`, drug administration events
- Demonstrates TRANSIENT_LOCAL durability for intraoperative record reconstruction on late join
- Natural complement to Recording Service: AIMS receives live data; Recording Service produces the persistent archive

#### OR Scheduling Gateway
- *Inbound:* drives domain partition assignment and initial `ProcedureContext` from scheduled OR data
- Demonstrates configuration-over-code: partition values and procedure metadata flow in from an external system, not hardcoded

#### Hospital Alarm Management Gateway
- Read-only subscriber to `ClinicalAlert` and `AlarmMessages`
- Routes alerts to staff via pager, mobile, or nurse call systems (simulated sink)
- Demonstrates clean decoupling: the surgical system doesn't know or care who receives alarms

#### Device Integration Gateway (bidirectional)
- Bidirectional integration for infusion pump and anesthesia machine: command/control (start, stop, rate adjust) + telemetry
- Exclusive ownership primary/backup gateway failover
- Upgrades V1's read-only `DeviceTelemetry` to a full command/response data path

#### Foxglove Visualization Bridge
- **Foxglove integration infrastructure** — full Foxglove Studio connectivity delivered in V2, building on the V1.2 data model translatability work. Three C++ shared-library plugins form the bridge pipeline:
  1. **Routing Service Transformation plugin** (`libmedtech_foxglove_transf.so`) — implements `rti::routing::transf::DynamicDataTransformation`. One transformation class per target Foxglove type. Converts medtech DDS types to Foxglove-native types by stripping `@key` fields, restructuring nested members, and populating timestamps from `SampleInfo.source_timestamp`. Uses generated C++ types on both sides via `rti::core::xtypes::convert<T>()`.
  2. **Routing Service Adapter plugin** (`libfoxglove_ws_adapter.so`) — implements `rti::routing::adapter::AdapterPlugin` → `Connection` → `DynamicDataStreamWriter`. Output-only adapter: receives transformed Foxglove DynamicData from the Routing Service pipeline and serializes it to a Foxglove Studio live WebSocket connection. The transformation runs before the adapter's `write()` call.
  3. **Recording Service Storage plugin** (`libmedtech_mcap_storage.so`) — implements `rti::recording::storage::StorageWriter` → `DynamicDataStorageStreamWriter`. Custom storage backend that writes transformed Foxglove-native samples to MCAP files. The transformation runs before the storage writer's `store()` call.
- **Foxglove IDL compilation** — selected [foxglove-sdk OMG IDL schemas](https://github.com/foxglove/foxglove-sdk/tree/main/schemas/omgidl/foxglove) (`CompressedImage`, `JointState`, `JointStates`, `FrameTransform`, `FrameTransforms`, `PoseInFrame`, `Pose`, `Quaternion`, `Vector3`, `Time`) compiled with `rtiddsgen` and linked into the transformation plugin.
- **V2 topic routes (Tier 1 + Tier 2)** — Tier 1: `RobotStateToJointStates`, `RobotStateToToolPose`, `RobotFrameTransformToFoxglove`, `CameraFrameToCompressedImage`. Tier 2: `CameraConfigToCalibration`, `ImageAnnotationsToFoxglove`, `CompressedVideoToFoxglove`, `SceneUpdateToFoxglove`, `LogMessageToFoxglove`.
- **Foxglove schema alignment (Tier 2)** — new IDL types aligned with Foxglove schemas for advanced visualization: `Imaging::CameraCalibration` (3D image projection, lens correction), `Imaging::ImageAnnotations` (2D camera overlays: tool tracking, safety zones), `Imaging::CompressedVideo` (H.264/H.265 video streaming, 10–50× bandwidth reduction over per-frame JPEG), `Visualization::SceneUpdate` (3D scene primitives: OR environment, robot schematic, safety boundaries), `Diagnostics::LogMessage` (structured logs for Foxglove Log panel, bridged from RTI Logging API / Monitoring Library 2.0)
- **New IDL modules** — `interfaces/idl/visualization/` and `interfaces/idl/diagnostics/` created to host V2 Foxglove-aligned types; `interfaces/idl/foxglove/` added for vendored Foxglove OMG IDL schemas.
- **Deployment modes** — live visualization (Routing Service: DDS → Transformation → Adapter Plugin → Foxglove Studio WebSocket) and offline recording (Recording Service: DDS → Transformation → Storage Plugin → MCAP file → Foxglove Studio). Both modes can run concurrently.
- `@foxglove` spec scenarios added to cover transformation correctness, adapter plugin WebSocket delivery, storage plugin MCAP output, and concurrent operation.

---

### V3.0.0 — Advanced Scenarios & Multi-Facility

**Theme:** Extend to larger-scale and more complex hospital scenarios — cross-facility bridging, scope expansion, and advanced specialized workflows — without architectural changes to the core system.

#### Surgical Instrument Tracking
- Tool-in/tool-out events, usage counts, sterilization status
- Tray composition and count verification
- TRANSIENT_LOCAL durability for late-joining count boards and display stations

#### PACS / Imaging Gateway (DICOM bridge simulation)
- *Inbound:* pre-op imaging metadata (CT/MRI study references) available at the surgical console
- *Outbound:* intraoperative image captures (laparoscopic frames, fluoroscopy) archived to PACS
- Demonstrates QoS differentiation: image metadata as state (`State` pattern), frame streams as best-effort (`Stream` pattern)

#### Inter-OR Communication
- Specialist consultation requests between rooms
- Shared resource availability (blood bank, equipment, on-call staff)
- Routing Service WAN bridging between facilities

#### ClinicalAlerts High Availability
- Primary/backup ClinicalAlerts engine pair with automatic failover
- Primary/backup RTI Cloud Discovery Service pair (multiple initial peers)
- Per-segment ClinicalAlerts engine deployment as hospital network topology grows

#### Cross-Platform Support
- Windows (x64), macOS (Darwin), and QNX build and runtime support
- Platform-specific setup scripts (`setup.ps1`, `setup.zsh`) alongside `setup.bash`
- Connext architecture selection parameterized in build system
- Native (non-Docker) build/run instructions for each platform
- QNX cross-compilation for embedded surgical controller targets

#### Cloud Command Center
- **Cloud / Enterprise domain** — third layer of the layered databus, above the Hospital domain
- **WAN Routing Service** — Real-Time WAN Transport (`UDPv4_WAN`) bridge from Hospital → Cloud domain; per-facility selective forwarding; Connext Security Plugins required on all WAN connections
- **Command Center Dashboard** — PySide6 GUI (shared design standard) subscribing to the Cloud domain; displays facility status, aggregated alerts, resource utilization, and operational KPIs across multiple hospitals
- **Facility-level partitions** — `facility/hospital-a`, `facility/hospital-b`; wildcard matching (`facility/*`) for enterprise-wide aggregation
- **Cloud-domain topics** — `FacilityStatus`, `AggregatedAlerts`, `ResourceUtilization`, `OperationalKPIs`
- **Cloud Discovery Service** — enterprise-level multicast-free discovery across WAN-connected sites
- Demonstrates the layered databus model at full scale: Procedure → Hospital → Cloud, each boundary bridged by a Routing Service tier with zero changes to lower layers

#### Foxglove Visualization Bridge (Tier 3)
- **Foxglove schema alignment (Tier 3)** — new IDL types for advanced spatial and sensor visualization: `foxglove::PointCloud` alignment (depth camera / 3D scanner for surgical navigation), `foxglove::Grid` alignment (2D heatmap overlays — radiation, thermal), `foxglove::LocationFix` alignment (facility-level indoor positioning / asset tracking), `foxglove::RawAudio` alignment (OR ambient audio monitoring)
- **Transformation plugin expansion** — additional mapping classes for V3 Foxglove types
- Specific IDL definitions authored when V3 capability scope is finalized
