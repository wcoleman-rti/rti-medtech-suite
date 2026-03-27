# Data Model

The data model is the shared contract for the entire medtech suite. It consists of three parts:

1. **Domain definitions** — the domains, registered types, and topics that define the system's DDS architecture
2. **IDL type definitions** — the structure of every message on the bus
3. **QoS profiles** — the behavioral contract for how messages are delivered

All three are maintained in the `interfaces/` component and are dependencies for all modules. Modules define their own DomainParticipants (each app has its own participant XML) but the domains, topics, and QoS they reference are defined here.

---

## Design Principles

### Domain Definitions in XML

Domains are defined using the DDS-XML [Domain Library](https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/connext_dds_professional/xml_application_creation/xml_based_app_creation_guide/UnderstandingXMLBased/DomainLibrary.htm) format. Each domain declares:
- A **domain ID** (starting from 10, incrementing upward — domain 0 is reserved for prototyping/testing)
- **Registered types** referencing IDL-defined types
- **Topics** referencing registered types

Module participant XML files reference domains via `domain_ref` and topics via `topic_ref`. This ensures that the system architecture (which domains and topics exist) is centrally defined, while participant topology (which apps join which domains) is module-owned.

### Topic Design

Each topic represents a **data pattern** — a semantic class of data defined by its purpose. Topics are not created per-instance or per-entity.

When multiple variations or iterations of a data stream exist, they share a single topic and are distinguished by:
- **Key fields** — serve a role analogous to indexes in a SQL database; they enable semantic pivoting on the data within a topic (e.g., `patient.id`, `device_id`, `robot_id`)
- **Content-filtered topics** — subscriber-side narrowing when only a subset of instances is needed
- **Domain partitions** — room/procedure/context isolation

**Bad:** `PatientVitals_OR3`, `PatientVitals_OR4` (per-instance topics)
**Good:** `PatientVitals` with `@key patient.id`, partitioned by room, filtered by subscriber

### Content Filtering

Subscribers should create content-filtered topics wherever they consume a subset of a topic's instance space. This reduces network and processing overhead:

- Dashboard showing one patient → filter on `patient.id`
- Clinical Decision Support (ClinicalAlerts module) engine for one procedure → filter on partition + patient key
- Device gateway for one pump → filter on `device_id`

### QoS as Interface — Strict XML-Only

All QoS is defined in shared XML profiles under `interfaces/qos/`. **No QoS is constructed or modified programmatically**, with two exceptions:

1. **XTypes compliance mask** — the factory-level `accept_unknown_enum_value` bit (`0x00000020`) has no XML equivalent and must be set before any DomainParticipant is created.
2. **Participant partition** — partition strings (e.g., `room/OR-3/procedure/proc-001`) are context-dependent startup configuration determined by the application's runtime environment (which room, which procedure). They are set programmatically on the `DomainParticipantQos` immediately after `create_participant_from_config()`. This is preferred over XML environment-variable substitution (`$(PARTITION)`) because the application already knows its context and can set it directly — no indirection through the shell environment is needed. Participant partition controls discovery-level visibility (Connext 7.x extension) and is independent of Publisher/Subscriber partition QoS, which is not used.

Modules use the **default QosProvider** to access profiles — they never call QoS setter APIs or construct custom `QosProvider` instances with explicit file paths.

- **C++:** `dds::core::QosProvider::Default()`
- **Python:** `dds.QosProvider.default`

This ensures:
- Writer/reader QoS compatibility is enforced by using the same named profile
- Tuning behavior (deadlines, durability depth, lifespan) is a configuration change, not a code change
- Future modules automatically get compatible QoS by referencing the same profiles

### QoS XML Loading via `NDDS_QOS_PROFILES`

QoS and domain library XML files are loaded at runtime via the `NDDS_QOS_PROFILES` environment variable. This variable lists all XML files in dependency order (Snippets before Patterns, Patterns before Topics, etc.). Applications do not hardcode XML file paths.

```bash
export NDDS_QOS_PROFILES="interfaces/qos/Snippets.xml;interfaces/qos/Patterns.xml;interfaces/qos/Topics.xml;interfaces/qos/Participants.xml;interfaces/domains/Domains.xml"
```

Docker Compose sets this variable for all service containers. Local development sets it in the shell or via a wrapper script.

### QoS XML Schema Validation

Every DDS XML file (QoS profiles, domain library, participant configuration) must declare the RTI schema in its root element:

```xml
<dds xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xsi:noNamespaceSchemaLocation="https://community.rti.com/schema/7.6.0/rti_dds_profiles.xsd">
```

All XML files are validated against this schema as part of the build/CI process. `rtiddsgen` is not used for XML validation.

### QoS Assigned to Topics via Topic Filters

QoS profiles use [topic filters](https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/connext_dds_professional/users_manual/users_manual/Topic_Filters.htm) to bind DataWriter/DataReader QoS to topics by name pattern. Applications use the topic-aware QoS APIs so that the correct QoS is automatically resolved based on the topic being written/read. This decouples applications from knowing which QoS profile applies to which topic.

The concrete topic-aware QoS resolution methods are:

- **Python:** `dds.QosProvider.default.get_topic_datawriter_qos(topic_name)` /
  `dds.QosProvider.default.get_topic_datareader_qos(topic_name)`
- **C++:** `provider.datawriter_qos(profile, topic_name)` /
  `provider.datareader_qos(profile, topic_name)`

Alternatively, when creating endpoints directly with `create_datawriter_with_profile` /
`create_datareader_with_profile`, the topic name is passed implicitly and
Connext resolves the matching topic-filter QoS automatically.

### Durability and Lifespan

- **TRANSIENT_LOCAL** durability on any topic where late-joining subscribers need current state (vitals, procedure context, device status, robot state)
- **Lifespan QoS** only where stale data is genuinely harmful or meaningless — not as a default. Primary candidates are command topics (executing a stale command could be dangerous) and high-rate control streams where applying stale input to an actuator is unsafe (e.g., `OperatorInput` — 20 ms lifespan ensures the robot control loop never acts on input older than 10× the publication interval).
- **VOLATILE** for command topics — stale commands must not be delivered to late joiners

### Exclusive Ownership for Redundancy

Use `EXCLUSIVE_OWNERSHIP_QOS` where a primary/backup writer pattern provides redundancy and automatic failover:
- **Service gateways** (device gateways and Routing Service instances) — primary gateway (strength 100) and backup (strength 50); if primary fails liveliness, backup takes over seamlessly with no application logic required
- **Robot state publishers** — if redundant controllers exist, only the active one's state is delivered

The subscriber always receives from the highest-strength live writer. Failover is automatic via DDS ownership and liveliness detection.

### Time-Based Filter for GUI Applications

GUI applications that refresh at a fixed rate (e.g., 30 Hz, 10 Hz) should use `TIME_BASED_FILTER` QoS on their DataReaders to avoid processing data faster than the display can render. This is configured via QoS snippets, not application code. The `minimum_separation` is set to match the GUI refresh interval.

### Publication Model — When to Write

DDS is a data-centric middleware — each `write()` call is semantically equivalent
to an INSERT or UPDATE on a distributed data store. The system uses three distinct
publication models, and every topic must be assigned to exactly one. The choice
determines when `write()` is called and affects QoS selection, bus utilization,
and the semantic meaning of each sample.

#### Continuous Stream

**When to use:** Safety-critical control loops and real-time data feeds where freshness
is the primary concern. Data is always changing or must always be fresh.

**Behavior:** The publisher calls `write()` at a **fixed rate** regardless of whether
the value has changed. The rate is configured per topic and enforced by a timer
(e.g., `GuardCondition` trigger, `asyncio` periodic task). DDS Deadline QoS on both
writer and reader detects stream interruption.

| Topic | Rate | Rationale |
|-------|------|-----------|
| `OperatorInput` | 500 Hz | Haptic/joystick control — continuous actuation |
| `RobotState` | 100 Hz | Closed-loop feedback — must be continuously fresh |
| `RobotFrameTransform` | 100 Hz | Kinematic frame hierarchy — published at same rate as `RobotState` for synchronized 3D visualization *(V1.2)* |
| `WaveformData` | 50 Hz (10-sample blocks) | Physiological signal reconstruction requires gapless stream |
| `CameraFrame` | 30 Hz | Video feed — continuous frame delivery |

#### Periodic Snapshot

**When to use:** Signals that change continuously but are sampled at a human-readable
or clinically meaningful rate. Even if the underlying physiological signal is
continuous, the publication rate is chosen to match the consumption cadence.

**Behavior:** The publisher calls `write()` at a **fixed rate**. Each sample is a
snapshot of the current state at the time of publication. Unlike continuous stream,
the rate is chosen for readability and clinical practice, not for control-loop
freshness. TRANSIENT_LOCAL durability provides the latest snapshot to late joiners.

| Topic | Rate | Rationale |
|-------|------|-----------|
| `PatientVitals` | 1 Hz | Vital signs dashboard update cadence |

#### Write-on-Change (Event-Driven)

**When to use:** State data, commands, and status indicators that are stable until
something happens. Publishing identical data on a fixed period wastes bus bandwidth
and obscures the semantic meaning of each sample — if every sample is "the same,"
consumers cannot distinguish "nothing happened" from "the system confirmed its state."

**Behavior:** The publisher calls `write()` **only when the logical state changes**.
A state change is defined as any field in the published type having a different value
from the last published sample (excluding timestamps, which always change). DDS
TRANSIENT_LOCAL durability ensures the current state is available to late joiners
without periodic re-publication.

For write-on-change topics, the absence of new samples is **normal and expected** —
it means the state is stable. Consumers detect writer failure via **liveliness QoS**
(automatic, 2 s lease), not via the absence of data samples. This is the key
difference from continuous-stream topics where sample absence indicates a fault.

| Topic | Trigger | Rationale |
|-------|---------|-----------|
| `ProcedureContext` | Metadata update (surgeon change, patient reassignment) | Context is static for the duration of most procedures |
| `ProcedureStatus` | Status transition (in-progress → completing → alert) | Status changes are discrete events, not continuous signals |
| `AlarmMessages` | Alarm raised, severity changed, or alarm cleared | Alarm state transitions are the semantically important events |
| `DeviceTelemetry` | Device parameter change, fault onset, or mode transition | A pump running at a steady rate of 100 mL/hr does not need a sample every 500 ms saying "still 100 mL/hr" |
| `SafetyInterlock` | Interlock state change (activated/deactivated) | Safety events are discrete; redundant samples add no safety value |
| `RobotCommand` | New command issued | Commands are inherently event-driven |
| `CameraConfig` | Camera setting change (resolution, encoding, exposure) | Stream configuration is stable between adjustments |
| `ClinicalAlert` | Risk threshold crossed or alert resolved | Alert events are discrete |
| `RiskScore` | Score changes beyond a noise threshold (±0.05) | Avoids bus chatter from floating-point noise in repeated computations |
| `ResourceAvailability` | Resource state change (bed freed, OR available) | Resource status is stable between transitions |

#### Minimum Heartbeat for Write-on-Change Topics

Write-on-change topics that use TRANSIENT_LOCAL durability and liveliness QoS do
**not** require a periodic heartbeat publication for correctness — DDS liveliness
detection handles writer health, and durability handles late joiners.

However, for **observability and debugging**, a configurable minimum heartbeat
interval may be implemented (default: disabled). When enabled, the publisher
re-publishes the current state if no change has occurred within the heartbeat
interval. This is an optional diagnostic aid, not a functional requirement:

| Environment Variable | Type | Default | Description |
|---------------------|------|---------|-------------|
| `MEDTECH_HEARTBEAT_INTERVAL` | Seconds (float) or `0` | `0` (disabled) | If > 0, write-on-change publishers re-publish current state at this interval even when unchanged |

---

## Domain Definitions

Domain IDs start at 10 (domain 0 is reserved for prototyping/testing).

**Domain Naming Rule:** Numeric domain IDs are defined **exactly once** — in the
headings below (e.g., "Domain 10 — Procedure") and in the corresponding
`<domain>` element in `Domains.xml`. Every other document, code comment,
spec scenario, implementation step, and log message must reference a domain
by **name only** (e.g., "Procedure domain", "Hospital domain", "Observability domain").
If a domain ID changes, only this section and `Domains.xml` require an update.

### Domain 10 — Procedure

The surgical procedure layer. All data related to an active surgical procedure lives here, subdivided by domain tags for criticality isolation per medical device risk classification.

#### Domain Tags (Risk-Class Aligned)

| Domain Tag | Risk Class | Traffic | Examples |
|------------|-----------|---------|----------|
| `control` | Class C / Class III (safety-critical) | Real-time closed-loop control, safety interlocks | Robot command, robot state, safety interlock, operator input |
| `clinical` | Class B / Class II (clinical significance) | Patient vitals, alarms, device telemetry | Patient vitals, waveforms, alarm messages, device telemetry |
| `operational` | Class A / Class I (non-critical) | Visualization, recording, procedure metadata, camera | Camera frames, procedure context, logging |

Data streams that cross a risk class boundary must not operate within the same domain tag.

#### Topics

| Topic | Registered Type | Domain Tag | Key Fields | Notes |
|-------|----------------|------------|------------|-------|
| `RobotCommand` | `Surgery::RobotCommand` | `control` | `robot_id`, `command_id` | Operator → robot. Volatile, reliable. |
| `RobotState` | `Surgery::RobotState` | `control` | `robot_id` | Robot → operator/dashboard. TRANSIENT_LOCAL. Deadline-enforced (20 ms). |
| `SafetyInterlock` | `Surgery::SafetyInterlock` | `control` | `robot_id` | Safety system state. Write-on-change; writer health detected via `Liveliness500ms` (500 ms lease). |
| `OperatorInput` | `Surgery::OperatorInput` | `control` | `operator_id`, `robot_id` | High-rate control input (joystick/haptic). Best-effort streaming. |
| `PatientVitals` | `Monitoring::PatientVitals` | `clinical` | `patient.id` | Periodic snapshot of current vital signs. Deadline-enforced (2 s). |
| `WaveformData` | `Monitoring::WaveformData` | `clinical` | `patient.id`, `source_device_id`, `waveform_kind` | High-rate physiological waveforms. Deadline-enforced (40 ms). |
| `AlarmMessages` | `Monitoring::AlarmMessage` | `clinical` | `alarm_id` | Per-alarm instance (keyed by alarm ID). Write-on-change. |
| `DeviceTelemetry` | `Devices::DeviceTelemetry` | `clinical` | `device_id` | Generic device status (pump, ventilator, anesthesia). |
| `CameraFrame` | `Imaging::CameraFrame` | `operational` | `camera_id` | Endoscope/surgical camera compressed frame data (inline bytes). Deadline-enforced (66 ms). Foxglove `CompressedImage` field-semantically aligned (not wire-compatible due to `@key camera_id`). |
| `CameraConfig` | `Imaging::CameraConfig` | `operational` | `camera_id` | Camera stream configuration state (resolution, encoding, exposure). Write-on-change, TRANSIENT_LOCAL. Late joiners correlate with `CameraFrame` via `camera_id`. |
| `ProcedureContext` | `Surgery::ProcedureContext` | `operational` | `procedure_id` | Hospital, room, bed, patient, surgeon, procedure type. TRANSIENT_LOCAL. |
| `RobotFrameTransform` | `Surgery::RobotFrameTransform` | `control` | `robot_id` | *(V1.2)* Kinematic frame hierarchy for 3D visualization. Continuous stream at 100 Hz, synchronized with `RobotState`. Foxglove `FrameTransforms` aligned. |
| `ProcedureStatus` | `Surgery::ProcedureStatus` | `operational` | `procedure_id` | Running status (in-progress, completing, alert). Published by each instance. TRANSIENT_LOCAL. Bridged to Hospital domain. |

### Domain 11 — Hospital

The facility-wide layer. Aggregated data for dashboards, clinical decision support, and resource coordination.

The Hospital domain has **no domain tags**. All participants on the Hospital domain discover
each other directly — there is no tag-based discovery scoping. All bridged data from the Procedure domain's three
risk-class tags lands in a single flat domain. This is intentional: Hospital-domain
participants are read-only observers — they do not publish commands or interlocks
back into the Procedure domain. Domain-tag isolation protects the surgical process
from cross-class interference between actors; since there are no actors on the Hospital
domain, tags would add participant complexity with no safety benefit. The trust boundary
is Routing Service (one-way, selective bridge). See
[system-architecture.md — Hospital Domain](system-architecture.md) for the full
rationale and escalation trigger.

#### Topics

| Topic | Registered Type | Key Fields | Notes |
|-------|----------------|------------|-------|
| `ProcedureStatus` | `Surgery::ProcedureStatus` | `procedure_id` | Procedure state for dashboard. Bridged from Procedure domain — not published directly on this domain. |
| `ProcedureContext` | `Surgery::ProcedureContext` | `procedure_id` | Hospital, room, bed, patient, surgeon, procedure type. Bridged from Procedure domain (`operational` tag) — not published directly on this domain. TRANSIENT_LOCAL — late-joining dashboards receive current context immediately. |
| `PatientVitals` | `Monitoring::PatientVitals` | `patient.id` | Real-time vital signs snapshot per patient. Bridged from Procedure domain (`clinical` tag) — not published directly on this domain. Consumed by the Dashboard vitals overview and the ClinicalAlerts engine. |
| `AlarmMessages` | `Monitoring::AlarmMessage` | `alarm_id` | Device-level alarms (Pathway 1). Bridged from Procedure domain (`clinical` tag) — not published directly on this domain. Consumed by the Dashboard alert feed. |
| `DeviceTelemetry` | `Devices::DeviceTelemetry` | `device_id` | Device status. Bridged from Procedure domain (`clinical` tag) — not published directly on this domain. Available on this domain in V1.0; not displayed by the V1.0 dashboard — reserved for V1.2+. |
| `RobotState` | `Surgery::RobotState` | `robot_id` | Read-only robot state for the Dashboard robot status panel. Bridged from Procedure domain (`control` tag) — not published directly on this domain. |
| `ClinicalAlert` | `ClinicalAlerts::ClinicalAlert` | `alert_id` | Risk-based alerts from ClinicalAlerts engine. |
| `RiskScore` | `ClinicalAlerts::RiskScore` | `patient.id`, `score_kind` | Computed risk scores (sepsis, hemorrhage, etc.). |
| `ResourceAvailability` | `Hospital::ResourceAvailability` | `resource_id` | *(V1.2)* OR, bed, equipment, and staff availability. Deferred to V1.2 — no simulator or dashboard panel in V1.0. |

### Domain 12 — Cloud / Enterprise (V3.0)

The multi-facility command center layer. Aggregated operational data bridged from individual hospital sites via WAN Routing Service (Real-Time WAN Transport — `UDPv4_WAN`). See [system-architecture.md](system-architecture.md) for WAN topology and transport configuration.

#### Topics

| Topic | Registered Type | Key Fields | Notes |
|-------|----------------|------------|-------|
| `FacilityStatus` | `Cloud::FacilityStatus` | `facility_id` | Per-hospital operational summary (OR utilization, staffing). TRANSIENT_LOCAL. |
| `AggregatedAlerts` | `Cloud::AggregatedAlerts` | `facility_id`, `alert_id` | Facility-level alert roll-up from hospital ClinicalAlerts engines. |
| `ResourceUtilization` | `Cloud::ResourceUtilization` | `facility_id` | Equipment, staffing, and capacity metrics per facility. |
| `OperationalKPIs` | `Cloud::OperationalKPIs` | `facility_id` | Procedure throughput, turnaround time, quality indicators. |

Partition format: `facility/<hospital_id>` (e.g., `facility/HOSP-NYC-01`).

### Domain 15 — Orchestration (V1.1)

Infrastructure lifecycle management layer for procedure service orchestration. The Procedure Controller and Service Hosts communicate on this domain using a hybrid of DDS RPC (directed commands) and pub/sub (asynchronous state distribution).

**Why domain 15:** Positioned between the application domains (10–12) and the infrastructure domain (20) in the ID numbering scheme. Like the Observability domain, the Orchestration domain is infrastructure — not clinical data.

**No domain tags.** All participants discover each other directly. See [system-architecture.md — Orchestration Domain](system-architecture.md) for the full rationale.

**Why a separate domain (not a Procedure domain tag):** The Procedure domain's domain tags isolate risk classes of surgical data per IEC 62304. Orchestration is an infrastructure control-plane with a fundamentally different lifecycle — Service Hosts persist across procedures, shift changes, and OR reassignments. Domain-level isolation guarantees that orchestration failures (controller crash, RPC timeout) cannot disrupt an in-progress surgical procedure. See [system-architecture.md — Why a Separate Domain](system-architecture.md) for the full analysis.

#### Pub/Sub Topics

| Topic | Registered Type | Key Fields | Publication Model | Notes |
|-------|----------------|------------|-------------------|-------|
| `HostCatalog` | `Orchestration::HostCatalog` | `host_id` | State (write-on-change, TRANSIENT_LOCAL, RELIABLE, KEEP_LAST 1) | Service Host capability advertisement. Published by each Service Host. Liveliness-monitored for host failure detection. |
| `ServiceStatus` | `Orchestration::ServiceStatus` | `host_id`, `service_id` | State (write-on-change, TRANSIENT_LOCAL, RELIABLE, KEEP_LAST 1) | Per-service lifecycle state. Published by Service Hosts (polled from each hosted service's `state` property). Late-joining controllers reconstruct full state. |

#### RPC Service Interface

| RPC Service | IDL Interface | Publisher (Service) | Subscriber (Client) | QoS Pattern |
|-------------|--------------|---------------------|---------------------|-------------|
| `ServiceHostControl` | `Orchestration::ServiceHostControl` | Each Service Host (unique service name per host: `ServiceHostControl/<host_id>`) | Procedure Controller | `Pattern.RPC` (RELIABLE, KEEP_ALL) |

**Operations:**

| Operation | Request | Reply | Semantics |
|-----------|---------|-------|-----------|
| `start_service` | `ServiceRequest` (service_id, config) | `OperationResult` (code, message) | Start a service on the target host |
| `stop_service` | `ServiceRequest` (service_id) | `OperationResult` | Gracefully stop a running service |
| `configure_service` | `ConfigureRequest` (service_id, config) | `OperationResult` | Update service configuration |
| `get_capabilities` | (no params) | `CapabilityReport` (supported services, capacity) | Query host capabilities |
| `get_health` | (no params) | `HealthReport` (alive, summary, diagnostics) | Query host health |

#### IDL Module

New IDL directory: `interfaces/idl/orchestration/`

Types defined in `module Orchestration`:

- **Pub/sub state types:** `HostCatalog`, `ServiceStatus`
- **RPC interface:** `ServiceHostControl` — `@service("DDS")` interface
- **RPC parameter types:** `ServiceRequest`, `ConfigureRequest`, `OperationResult`, `CapabilityReport`, `HealthReport`
- **Enums:**
  - `ServiceState` — `STOPPED`, `STARTING`, `RUNNING`, `STOPPING`, `FAILED`, `UNKNOWN`
  - `OperationResultCode` — `OK`, `INVALID_SERVICE`, `INVALID_CONFIG`, `BUSY`, `ALREADY_RUNNING`, `NOT_RUNNING`, `INTERNAL_ERROR`

> **IDL-generated `ServiceState`:** This enum is the **single source of
> truth** for service lifecycle state across both languages. The
> `medtech::Service` abstract interface (see
> [dds-consistency.md §3](dds-consistency.md)) returns it from its
> `state()` property. Because it is IDL-defined, it can also appear
> directly in DDS topic types (e.g., `ServiceStatus.state`) and RPC
> return types without manual mapping — enabling on-wire service health
> monitoring, inter-service status queries, and future health-check RPC
> extensions.

Partition format: `room/<room_id>` (e.g., `room/OR-1`). Service Hosts not yet assigned to an OR use the `unassigned` partition.

### Domain 20 — Observability

Dedicated domain for **RTI Observability Framework** telemetry. Monitoring Library 2.0 creates a dedicated DomainParticipant on this domain in every process to publish metrics, logs, and security events. RTI Collector Service subscribes on this domain to aggregate telemetry and export it to Prometheus (metrics), Grafana Loki (logs), or an OpenTelemetry Collector.

**Why a separate domain:**

- **Performance** — high-volume telemetry (metrics emitted at configurable intervals, forwarded logs) cannot compete for transport resources with safety-critical control or clinical data on the Procedure domain.
- **Safety** — temporarily increasing telemetry verbosity for debugging must not affect discovery, deadline enforcement, or sample delivery on Domains 10 or 11.
- **Isolation** — Collector Service only needs to join the Observability domain. It does not participate in application domains, reducing its attack surface and resource footprint.

The Observability domain has **no domain tags** and **no application-defined topics**. Monitoring Library 2.0 creates its internal telemetry topics, publishers, and subscribers automatically — no XML topic or endpoint definitions are needed in `Domains.xml`.

#### Configuration

The domain ID is set in the MONITORING QoS policy on the `DomainParticipantFactory`:

```xml
<participant_factory_qos>
    <monitoring>
        <enable>true</enable>
        <distribution_settings>
            <dedicated_participant>
                <domain_id>20</domain_id>
            </dedicated_participant>
        </distribution_settings>
    </monitoring>
</participant_factory_qos>
```

This overrides the Monitoring Library 2.0 default (domain 2) to place observability traffic on the project’s designated Observability domain. The configuration is defined once in the shared QoS profile and applies to all applications. See [technology.md — Observability Standard](technology.md) for the full QoS configuration.

### Cross-Domain Bridging (Routing Service)

Routing Service bridges selected topics from the Procedure domain to the Hospital domain (and within the Procedure domain across domain tags where explicitly needed). WAN Routing Service bridges the Hospital domain to the Cloud domain across facility boundaries. Only a configured subset of data crosses boundaries. Topics bridged Procedure → Hospital: `ProcedureStatus`, `ProcedureContext`, `PatientVitals`, `AlarmMessages`, `DeviceTelemetry`, `RobotState`. See [system-architecture.md](system-architecture.md) for topology.

---

## QoS Architecture

### File Organization

QoS configuration is split by concern:

```
interfaces/qos/
├── Snippets.xml              # Isolated, reusable QoS policy chunks (no inheritance)
├── Patterns.xml              # Generic data-pattern base profiles (State, Command, Stream, + GUI variants)
├── Topics.xml                # Topic-filter-based profiles binding QoS to topics
└── Participants.xml          # Transport, Factory, and Participants libraries
```

- **Snippets** define isolated QoS policy chunks. Where a builtin equivalent exists in `BuiltinQosSnippetLib` (e.g., `QosPolicy.Reliability.Reliable`, `QosPolicy.Durability.TransientLocal`, `QosPolicy.History.KeepLast_1`, `QosPolicy.History.KeepAll`, `QosPolicy.Reliability.BestEffort`), the builtin is used directly — custom snippets are only defined for policies that have no builtin equivalent. Snippets do not inherit from other snippets or profiles.
- **Patterns** are generic base profiles that inherit from semantically appropriate `BuiltinQosLib` profiles (e.g., `Generic.KeepLastReliable.TransientLocal` for state data, `Generic.BestEffort` for streaming) and compose additional custom snippets as needed. They represent reusable data-flow archetypes. GUI downsampling variants (composing the `GuiSubsample` snippet) are defined here alongside their base patterns.
- **TopicProfiles** (within `Topics.xml`) define per-topic profiles that inherit from a pattern and add topic-specific tuning (deadline, lifespan, liveliness) in exactly one place. Each topic that requires tuning beyond its base pattern has a single `TopicProfiles::` profile that is the **single source of truth** for that topic's QoS. GUI variants inherit from the standard topic profile and add `GuiSubsample`.
- **Topics** profiles (within `Topics.xml`) use `topic_filter` to bind QoS to specific topic names by referencing `TopicProfiles::` profiles. Topic-filter entries contain no nested `<base_name>` tags or explicit policy configuration — they are pure references. Applications use topic-aware QoS APIs so the correct QoS resolves automatically.
- **Participants** profiles contain discovery, transport, and resource configuration. These are separate from data/topic profiles because they apply to DomainParticipants, not DataWriters/DataReaders. `Participants.xml` contains three QoS libraries: `Transport` (deployment-specific transport overrides, selected via `$(MEDTECH_TRANSPORT_PROFILE)` variable substitution), `Factory` (process-level `participant_factory_qos`), and `Participants` (the `Transport` profile composing common transport QoS and the selected transport snippet).

### QoS Snippets (`Snippets.xml`)

Isolated, composable, no inheritance. Each enables/disables a single concern.

**Builtin snippets** (from `BuiltinQosSnippetLib`, not redefined in `Snippets.xml`):

| Builtin Snippet | Applies To | What It Does |
|-----------------|-----------|--------------|
| `BuiltinQosSnippetLib::QosPolicy.Reliability.Reliable` | DW + DR | Sets RELIABLE reliability |
| `BuiltinQosSnippetLib::QosPolicy.Reliability.BestEffort` | DW + DR | Sets BEST_EFFORT reliability |
| `BuiltinQosSnippetLib::QosPolicy.Durability.TransientLocal` | DW + DR | Sets TRANSIENT_LOCAL durability |
| `BuiltinQosSnippetLib::QosPolicy.History.KeepLast_1` | DW + DR | KEEP_LAST history, depth 1 |
| `BuiltinQosSnippetLib::QosPolicy.History.KeepAll` | DW + DR | KEEP_ALL history |

**Custom snippets** (defined in `Snippets.xml` — no builtin equivalent):

| Snippet | Applies To | What It Does |
|---------|-----------|--------------|
| `Volatile` | DW + DR | Sets VOLATILE durability |
| `ExclusiveOwnership` | DW + DR | Sets EXCLUSIVE_OWNERSHIP |
| `Liveliness2s` | DW + DR | Automatic liveliness, 2-second lease |
| `Deadline4ms` | DW + DR | Deadline period = 4 ms. Writer: detects publish stall. Reader: detects stream interruption. See *Deadline QoS* below. |
| `Deadline20ms` | DW + DR | Deadline period = 20 ms. Stream interruption detection for 100 Hz topics (2× nominal). |
| `Deadline40ms` | DW + DR | Deadline period = 40 ms. Stream interruption detection for 50 Hz topics (2× nominal). |
| `Deadline66ms` | DW + DR | Deadline period = 66 ms. Stream interruption detection for 30 Hz topics (2× nominal). |
| `Deadline2s` | DW + DR | Deadline period = 2 s. Periodic-snapshot interruption detection for 1 Hz topics (2× nominal). |
| `Lifespan20ms` | DW only | Lifespan duration = 20 ms. Samples older than 20 ms are discarded before delivery. |
| `Liveliness500ms` | DW + DR | Automatic liveliness, 500 ms lease. Tight writer-health detection for safety-critical write-on-change topics. |
| `GuiSubsample` | DR only | TIME_BASED_FILTER minimum_separation for GUI refresh rate |
| `GuiDeadline100ms` | DR only | Deadline period = 100 ms (reader only). Relaxes strict writer-side deadlines for GUI display readers where the TBF-controlled rendering rate doesn't need sub-millisecond stream-interruption detection. Satisfies DDS constraint: TBF (16 ms) ≤ deadline (100 ms). |
| `NonBlockingWrite` | DW only | Guarantees `write()` never blocks the calling thread. Enables writes on the Qt UI event loop. Sets: `publish_mode.kind = ASYNCHRONOUS`, `reliability.max_blocking_time = 0`, `protocol.rtps_reliable_writer.max_send_window_size = LENGTH_UNLIMITED`, `protocol.rtps_reliable_writer.min_send_window_size = LENGTH_UNLIMITED`. Requires the writer to also use `KEEP_LAST` history (enforced by the Pattern that composes it). Batching must be disabled. See [dds-consistency.md §5 — GUI Host Applications](dds-consistency.md) for the threading policy this snippet enables. |

### Data Pattern Base Profiles (`Patterns.xml`)

Generic profiles that inherit from semantically appropriate `BuiltinQosLib` profiles. Each builtin base provides reliable/best-effort semantics, history, and reliability protocol optimization out of the box. Custom snippets are composed on top only where the builtin base does not cover a needed policy. These patterns are not used directly by applications — they are inherited by topic-specific profiles in `TopicProfiles`.

| Pattern Profile | Base | Additional Composition | Use Case |
|----------------|------|------------------------|----------|
| `State` | `BuiltinQosLib::Generic.KeepLastReliable.TransientLocal` | `Snippets::Liveliness2s` | Latest-state data: vitals, device status, robot state, procedure context, alarms. Base provides Reliable + KeepLast1 + TransientLocal + ReliabilityProtocol.KeepLast optimization. |
| `Command` | `BuiltinQosLib::Generic.KeepLastReliable` | *(none)* | Commands where only the most recent matters, stale commands must not reach late joiners. Base provides Reliable + KeepLast1 + ReliabilityProtocol.KeepLast optimization. Volatile durability is the Connext default — no explicit override needed. |
| `Stream` | `BuiltinQosLib::Generic.BestEffort` | Override writer history depth to 1 (no repair cache needed for best-effort), reader history depth to 4. | High-rate streaming: waveforms, camera frames, operator input. Base provides BestEffort + KeepLast (depth 100 by default, overridden here). |
| `GuiState` | `Patterns::State` | `Snippets::GuiSubsample` | Downsampled state for GUI readers (~100–200 ms minimum separation) |
| `GuiStream` | `Patterns::Stream` | `Snippets::GuiSubsample` | Downsampled streaming for GUI readers (~33 ms / 30 Hz minimum separation) |

### Deadline QoS

DDS Deadline QoS is independent of reliability — it works with both RELIABLE and BEST_EFFORT endpoints. Deadline is an RxO (Requested/Offered) policy: the writer's offered deadline period must be ≤ the reader's requested deadline period for the endpoints to match. If incompatible, Connext reports `OFFERED_INCOMPATIBLE_QOS` / `REQUESTED_INCOMPATIBLE_QOS` and the endpoints do **not** match.

For keyed topics, Deadline is enforced **per instance**:

- **Writer side:** if the application does not call `write()` at least once per deadline period for a registered instance, Connext triggers `OFFERED_DEADLINE_MISSED` and calls `on_offered_deadline_missed()`. This detects publisher task stalls regardless of reliability.
- **Reader side:** if no sample is received for an instance within the deadline period, Connext triggers `REQUESTED_DEADLINE_MISSED` and calls `on_requested_deadline_missed()`. With BEST_EFFORT, a miss can indicate the writer stopped, the network dropped samples, or jitter exceeded the budget — the reader cannot distinguish.

Deadline is applied to every topic that publishes at a **fixed rate** — continuous-stream and periodic-snapshot topics. The deadline period is set to **2× the nominal publication interval**, providing jitter tolerance while detecting any interruption longer than two consecutive missed cycles. Write-on-change topics do **not** use Deadline because sample absence is normal; writer health is detected via liveliness QoS instead.

| Topic | Publication Model | Nominal Rate | Deadline Period | Snippet |
|-------|-------------------|-------------|----------------|--------|
| `OperatorInput` | Continuous Stream | 500 Hz (2 ms) | 4 ms | `Deadline4ms` |
| `RobotState` | Continuous Stream | 100 Hz (10 ms) | 20 ms | `Deadline20ms` |
| `RobotFrameTransform` | Continuous Stream | 100 Hz (10 ms) | 20 ms | `Deadline20ms` |
| `WaveformData` | Continuous Stream | 50 Hz (20 ms) | 40 ms | `Deadline40ms` |
| `CameraFrame` | Continuous Stream | 30 Hz (~33 ms) | 66 ms | `Deadline66ms` |
| `PatientVitals` | Periodic Snapshot | 1 Hz (1000 ms) | 2 s | `Deadline2s` |

Setting Deadline on **both** writer and reader enables diagnosability: writer-missed + reader-missed → publisher-side fault; writer-OK + reader-missed → transport/network issue.

**`OperatorInput` additional rationale:** Combined with a 20 ms Lifespan, the control loop never acts on stale input even if delivery is delayed but not missed.

### Liveliness QoS for Write-on-Change Topics

Write-on-change topics rely on DDS liveliness QoS — not Deadline — to detect writer health, because sample absence is the normal steady state. The general `Liveliness2s` snippet (2-second automatic lease, composed into the `State` pattern) covers most write-on-change topics.

**`SafetyInterlock` exception:** The safety interlock is a write-on-change topic on the `control` tag (Class C / Class III). Although its data pattern is event-driven, the consequence of an undetected writer failure is a robot operating without safety oversight. A tighter liveliness lease (500 ms via `Liveliness500ms`) provides faster detection of safety-system failure than the general 2-second lease — the robot controller can transition to a safe-stopped state within 500 ms of losing the safety writer, rather than waiting 2 seconds.

### Topic Profiles and Topic-Bound Profiles (`Topics.xml`)

`Topics.xml` contains two QoS libraries:

1. **`TopicProfiles`** — per-topic profiles that inherit from a pattern and add topic-specific tuning. Each topic that needs tuning beyond its base pattern has exactly one profile here. This is the **single source of truth** for that topic's QoS — changing a topic's deadline, lifespan, or liveliness requires editing only this one profile. Topic-specific snippets are composed at the profile level using `<base_name>` (which applies to both writer and reader QoS when the snippet defines both). GUI variants inherit from the standard topic profile and add `Snippets::GuiSubsample`.

2. **`Topics`** — domain-scoped profiles that use `topic_filter` to bind QoS to specific topic names by referencing `TopicProfiles::` profiles. Topic-filter entries contain **no nested `<base_name>` tags or explicit policy configuration** — they are pure references to topic profiles.

Applications use `create_datawriter_with_profile` / `create_datareader_with_profile` with the topic name, and Connext resolves the matching QoS automatically.

Example structure:

```xml
<!-- Library 1: Single source of truth for each topic's QoS -->
<qos_library name="TopicProfiles">

    <!-- Topics that just alias a pattern (no extra tuning) -->
    <qos_profile name="RobotCommand" base_name="Patterns::Command"/>
    <qos_profile name="AlarmMessages" base_name="Patterns::State"/>
    <qos_profile name="DeviceTelemetry" base_name="Patterns::State"/>
    <qos_profile name="ProcedureContext" base_name="Patterns::State"/>
    <qos_profile name="ProcedureStatus" base_name="Patterns::State"/>

    <!-- Topics with additional tuning (deadline, lifespan, liveliness) -->
    <qos_profile name="OperatorInput" base_name="Patterns::Stream">
        <base_name>
            <element>Snippets::Deadline4ms</element>
            <element>Snippets::Lifespan20ms</element>
        </base_name>
    </qos_profile>

    <qos_profile name="RobotState" base_name="Patterns::State">
        <base_name>
            <element>Snippets::Deadline20ms</element>
        </base_name>
    </qos_profile>

    <qos_profile name="SafetyInterlock" base_name="Patterns::State">
        <base_name>
            <element>Snippets::Liveliness500ms</element>
        </base_name>
    </qos_profile>

    <qos_profile name="PatientVitals" base_name="Patterns::State">
        <base_name>
            <element>Snippets::Deadline2s</element>
        </base_name>
    </qos_profile>

    <qos_profile name="WaveformData" base_name="Patterns::Stream">
        <base_name>
            <element>Snippets::Deadline40ms</element>
        </base_name>
    </qos_profile>

    <qos_profile name="CameraFrame" base_name="Patterns::Stream">
        <base_name>
            <element>Snippets::Deadline66ms</element>
        </base_name>
    </qos_profile>

    <!-- V1.2: RobotFrameTransform — same deadline as RobotState -->
    <qos_profile name="RobotFrameTransform" base_name="Patterns::Stream">
        <base_name>
            <element>Snippets::Deadline20ms</element>
        </base_name>
    </qos_profile>

    <qos_profile name="ClinicalAlert" base_name="Patterns::State"/>
    <qos_profile name="RiskScore" base_name="Patterns::State"/>
    <qos_profile name="ResourceAvailability" base_name="Patterns::State"/>

    <!-- GUI variants: inherit from topic profile, add GuiSubsample -->
    <qos_profile name="GuiRobotState" base_name="TopicProfiles::RobotState">
        <base_name>
            <element>Snippets::GuiSubsample</element>
        </base_name>
    </qos_profile>
    <!-- ... GuiSafetyInterlock, GuiPatientVitals, etc. follow same pattern ... -->

</qos_library>

<!-- Library 2: Domain-scoped topic-filter bindings (pure references) -->
<qos_library name="Topics">

    <qos_profile name="ProcedureTopics">
        <datawriter_qos topic_filter="OperatorInput" base_name="TopicProfiles::OperatorInput"/>
        <datareader_qos topic_filter="OperatorInput" base_name="TopicProfiles::OperatorInput"/>
        <datawriter_qos topic_filter="RobotCommand" base_name="TopicProfiles::RobotCommand"/>
        <datareader_qos topic_filter="RobotCommand" base_name="TopicProfiles::RobotCommand"/>
        <datawriter_qos topic_filter="RobotState" base_name="TopicProfiles::RobotState"/>
        <datareader_qos topic_filter="RobotState" base_name="TopicProfiles::RobotState"/>
        <!-- ...etc for all Procedure domain topics... -->
    </qos_profile>

    <qos_profile name="HospitalTopics">
        <datareader_qos topic_filter="RobotState" base_name="TopicProfiles::RobotState"/>
        <datareader_qos topic_filter="PatientVitals" base_name="TopicProfiles::PatientVitals"/>
        <!-- ...etc for all Hospital domain topics... -->
    </qos_profile>

    <qos_profile name="GuiProcedureTopics">
        <datareader_qos topic_filter="RobotState" base_name="TopicProfiles::GuiRobotState"/>
        <!-- ...etc using Gui* topic profiles... -->
    </qos_profile>

    <qos_profile name="GuiHospitalTopics">
        <datareader_qos topic_filter="RobotState" base_name="TopicProfiles::GuiRobotState"/>
        <!-- ...etc using Gui* topic profiles... -->
    </qos_profile>

</qos_library>
```

### Participant Configuration (`Participants.xml`)

Discovery, transport, and resource settings for DomainParticipants. Separated from data/topic QoS because these apply to the participant entity, not to writers/readers.

`Participants.xml` contains three QoS libraries and a `<configuration_variables>` block:

1. **`<configuration_variables>`** — defines `MEDTECH_TRANSPORT_PROFILE` with a default value of `Default`. The environment variable `MEDTECH_TRANSPORT_PROFILE` overrides this at runtime. This variable is substituted into the `Participants::Transport` profile's `<base_name>` to select the active transport snippet.

2. **`Transport`** — deployment-specific transport overrides as self-contained QoS profile snippets. Each snippet is named for its deployment context:

| Snippet | SHMEM | UDPv4 | Multicast | Discovery Peers | Use Case |
|---------|-------|-------|-----------|-----------------|----------|
| `Transport::Default` | Enabled | Enabled | Enabled | Connext defaults (multicast + unicast) | Bare-metal, native development, production |
| `Transport::Docker` | Enabled | Enabled | Disabled | `builtin.shmem://`, `builtin.udpv4://localhost`, CDS locator | Docker simulation |

3. **`Factory`** — process-level `participant_factory_qos` profile for logging, Monitoring Library 2.0, and other factory-scoped settings. This profile has `is_default_participant_factory_profile="true"` and applies to the global `DomainParticipantFactory` — above any individual participant. Separated into its own library to make the scope boundary explicit.

4. **`Participants`** — the `Transport` profile composes common participant QoS (currently `BuiltinQosSnippetLib::Transport.UDP.AvoidIPFragmentation`) and the deployment-selected snippet (`Transport::$(MEDTECH_TRANSPORT_PROFILE)`). All participant XML references this single profile name.

SHMEM is enabled in both transport snippets — it benefits intra-container communication (multiple participants or processes within the same container). Both snippets inherit `AvoidIPFragmentation` via the shared `Participants::Transport` base.

The Docker snippet explicitly sets initial peers to:
1. `builtin.shmem://` — intra-container SHMEM discovery
2. `builtin.udpv4://localhost` — intra-container UDPv4 discovery
3. `rtps@udpv4://cloud-discovery-service:7400` — CDS for cross-container discovery

This excludes the default multicast discovery address, preventing warnings about multicast on Docker bridge networks.

Deployment selection is a single environment variable: `MEDTECH_TRANSPORT_PROFILE=Docker` in `docker-compose.yml`. Bare-metal uses the XML default (`Default`) with no env var needed.

- **Discovery peers** — Docker peers are configured in the `Transport::Docker` snippet. For the Default snippet, peers use Connext defaults (including multicast). `NDDS_DISCOVERY_PEERS` can still be set to override/add peers in either environment.
- **Resource limits** — participant-level resource bounds

---

## IDL Module Structure

Types are organized into subdirectories by functional domain. Each subdirectory contains IDL files whose types are wrapped in a module matching the directory name. This mirrors C++ conventions where the directory path corresponds to the header include path and the module translates to a C++ namespace.

```
interfaces/idl/
├── common/
│   └── common.idl          # module Common { Time_t, EntityIdentity, constants, aliases }
├── surgery/
│   └── surgery.idl         # module Surgery { RobotCommand, RobotState, SafetyInterlock, OperatorInput, ProcedureContext, ProcedureStatus }
├── monitoring/
│   └── monitoring.idl      # module Monitoring { PatientVitals, WaveformData, AlarmMessage }
├── imaging/
│   └── imaging.idl         # module Imaging { CameraFrame, CameraConfig }
├── devices/
│   └── devices.idl         # module Devices { DeviceTelemetry, PumpStatus, VentilatorCommands }
├── clinical_alerts/
│   └── clinical_alerts.idl             # module ClinicalAlerts { ClinicalAlert, RiskScore }
├── hospital/
│   └── hospital.idl        # module Hospital { ResourceAvailability }
└── foxglove/                       # (V1.2) Vendored Foxglove OMG IDL schemas (plugin build dependency only)
    ├── Time.idl
    ├── Quaternion.idl
    ├── Vector3.idl
    ├── Pose.idl
    ├── PoseInFrame.idl
    ├── JointState.idl
    ├── JointStates.idl
    ├── FrameTransform.idl
    ├── FrameTransforms.idl
    └── CompressedImage.idl
```

### Module / Namespace Convention

Every IDL file wraps all its types in a `module` block named after the functional domain. This module maps to:
- A **C++ namespace** (e.g., `Surgery::RobotCommand` → `Surgery::RobotCommand` in C++)
- A **Python module** (e.g., `Surgery.RobotCommand`)
- The **registered type name** in domain library XML (e.g., `type_ref="Surgery::RobotCommand"`)

Common types (`common/common.idl`) define the `Common` module. Other modules that depend on common types use `#include "common/common.idl"`.

If a functional domain grows large enough to warrant further subdivision, additional IDL files can be added within the same subdirectory (e.g., `surgery/teleop.idl`, `surgery/context.idl`) — all still under `module Surgery`.

### IDL Conventions

- **Extensibility:** All types default to `@appendable` (fields may only be added at the end). Use `@mutable` only for types that are expected to undergo non-additive evolution (field reordering or removal) — the additional serialization overhead must be justified. The choice for each type is recorded in the IDL file with a comment if `@mutable` is selected.
- **Bounded strings and sequences:** All `string` and `sequence` members must have explicit bounds defined. Code generation uses `rtiddsgen -unboundedSupport` for true unbounded support where needed, but explicit bounds on type members minimize dynamic allocation at endpoints.
- **Constants (`const`):** Shared bounds and magic numbers are defined as `const` values in IDL. These constants propagate into generated code and can be referenced by multiple types. Example: `const long MAX_MEASUREMENTS = 32;` then `sequence<VitalMeasurement, MAX_MEASUREMENTS>`.
- **Aliases (`typedef`):** Use `typedef` for commonly reused types (e.g., `typedef string<64> EntityId;`). Aliases propagate into generated code and improve readability and consistency across modules.
- **Sentinel-first enums:** Every `@appendable` enum must declare a sentinel value as its **first** enumerator (e.g., `UNKNOWN`, `UNSPECIFIED`). This value is the deserialization target when XTypes compliance bit `0x00000020` (`accept_unknown_enum_value`) is set and a subscriber encounters an enumerator not present in its local type definition. The middleware maps unknown values to the **first declared enumerator** — not to `@default_literal`. Therefore the sentinel must always be listed first. Application code must handle the sentinel in `switch`/`if` branches (log a warning, display "unknown state", degrade gracefully). `@final` enums that will never evolve do not require a sentinel. See [Pre-Participant Initialization](#pre-participant-initialization) below for the mandatory initialization that enables this behavior.

### Pre-Participant Initialization

Two global operations must be performed before any `DomainParticipant` is created.
Both are factory-level/application-global and have no XML equivalent. They must
be executed in the order shown below.

#### Operation 1 — XTypes compliance mask (bit `0x00000020`)

The sentinel-first enum convention has a hard dependency on RTI Connext DDS XTypes
compliance mask bit `0x00000020` (`accept_unknown_enum_value`). Any application
that subscribes to or publishes on topics defined by this data model **must** set
this bit on the `DomainParticipantFactory` before creating any `DomainParticipant`.

Failure to do so means a subscriber receiving an `@appendable` enum sample containing
a value unknown to its local type definition will **silently drop the sample** rather
than mapping the unknown value to the sentinel. The `UNKNOWN` sentinel enumerators
defined throughout this data model are meaningless at an endpoint that has not set
this bit.

#### Operation 2 — Type registration

When using XML-based application creation (`create_participant_from_config()`),
each compiled/generated type must be **individually registered** with the factory
before any participant is created. Registration binds the XML
`<register_type name="..."/>` attribute to the generated type-support plugin for
that type. Failure to register a type causes participant creation to fail for
configurations that reference it.

The name string passed to `register_type` must **exactly match** the `name`
attribute of the corresponding `<register_type>` element in the XML domain library.
Each type must be registered separately — there is no batch registration call.

#### Required initialization order

```
1. set XTypes compliance mask (bit 0x00000020)
2. register all compiled types
3. create_participant_from_config()
```

#### C++ (Modern C++ API)

```cpp
#include <rti/rti.hpp>
// Headers generated by rtiddsgen from each IDL file:
#include "common/Common.hpp"
#include "surgery/Surgery.hpp"
#include "monitoring/Monitoring.hpp"
#include "imaging/Imaging.hpp"
#include "devices/Devices.hpp"
#include "clinical_alerts/ClinicalAlerts.hpp"
#include "hospital/Hospital.hpp"

void initialize_connext()
{
    // Step 1 — XTypes compliance: must precede type registration and participant creation.
    rti::config::compliance::set_xtypes_mask(
        rti::config::compliance::get_xtypes_mask()
        | rti::config::compliance::XTypesMask::accept_unknown_enum_value());

    // Step 2 — Register every compiled type referenced by XML <register_type name="..."/>.
    //           Name strings must match the <register_type name="..."/> in the domain XML.
    //           Only top-level topic types require registration — @nested types
    //           (Time_t, EntityIdentity, CartesianPosition)
    //           are embedded by the parent type and do not need separate registration.
    rti::domain::register_type<Surgery::RobotCommand>("Surgery::RobotCommand");
    rti::domain::register_type<Surgery::RobotState>("Surgery::RobotState");
    rti::domain::register_type<Surgery::SafetyInterlock>("Surgery::SafetyInterlock");
    rti::domain::register_type<Surgery::OperatorInput>("Surgery::OperatorInput");
    rti::domain::register_type<Surgery::ProcedureContext>("Surgery::ProcedureContext");
    rti::domain::register_type<Surgery::ProcedureStatus>("Surgery::ProcedureStatus");
    rti::domain::register_type<Monitoring::PatientVitals>("Monitoring::PatientVitals");
    rti::domain::register_type<Monitoring::WaveformData>("Monitoring::WaveformData");
    rti::domain::register_type<Monitoring::AlarmMessage>("Monitoring::AlarmMessage");
    rti::domain::register_type<Imaging::CameraFrame>("Imaging::CameraFrame");
    rti::domain::register_type<Imaging::CameraConfig>("Imaging::CameraConfig");
    rti::domain::register_type<Devices::DeviceTelemetry>("Devices::DeviceTelemetry");
    rti::domain::register_type<ClinicalAlerts::ClinicalAlert>("ClinicalAlerts::ClinicalAlert");
    rti::domain::register_type<ClinicalAlerts::RiskScore>("ClinicalAlerts::RiskScore");
    rti::domain::register_type<Hospital::ResourceAvailability>("Hospital::ResourceAvailability");
}

// Usage:
//   initialize_connext();   // must be first
//   auto provider = dds::core::QosProvider("USER_QOS_PROFILES.xml");
//   auto participant = provider.create_participant_from_config(
//       "MedtechParticipantLibrary::SurgicalProcessor");
```

#### Python

```python
import rti.connextdds as dds
# Classes generated by rtiddsgen (rtiddsgen -language Python) from each IDL file:
from surgery.Surgery import (RobotCommand, RobotState, SafetyInterlock,
                              OperatorInput, ProcedureContext, ProcedureStatus)
from monitoring.Monitoring import PatientVitals, WaveformData, AlarmMessage
from imaging.Imaging import CameraFrame, CameraConfig
from devices.Devices import DeviceTelemetry
from clinical_alerts.ClinicalAlerts import ClinicalAlert, RiskScore
from hospital.Hospital import ResourceAvailability

def initialize_connext():
    # Step 1 — XTypes compliance: must precede type registration and participant creation.
    dds.compliance.set_xtypes_mask(
        dds.compliance.get_xtypes_mask()
        | dds.compliance.XTypesMask.ACCEPT_UNKNOWN_ENUM_VALUE_BIT
    )

    # Step 2 — Register every compiled type referenced by XML <register_type name="..."/>.
    #           Only top-level topic types require registration — @nested types
    #           (Time_t, EntityIdentity, CartesianPosition)
    #           are embedded by the parent type and do not need separate registration.
    dds.DomainParticipant.register_idl_type(RobotCommand,           "Surgery::RobotCommand")
    dds.DomainParticipant.register_idl_type(RobotState,             "Surgery::RobotState")
    dds.DomainParticipant.register_idl_type(SafetyInterlock,        "Surgery::SafetyInterlock")
    dds.DomainParticipant.register_idl_type(OperatorInput,          "Surgery::OperatorInput")
    dds.DomainParticipant.register_idl_type(ProcedureContext,       "Surgery::ProcedureContext")
    dds.DomainParticipant.register_idl_type(ProcedureStatus,        "Surgery::ProcedureStatus")
    dds.DomainParticipant.register_idl_type(PatientVitals,          "Monitoring::PatientVitals")
    dds.DomainParticipant.register_idl_type(WaveformData,           "Monitoring::WaveformData")
    dds.DomainParticipant.register_idl_type(AlarmMessage,           "Monitoring::AlarmMessage")
    dds.DomainParticipant.register_idl_type(CameraFrame,            "Imaging::CameraFrame")
    dds.DomainParticipant.register_idl_type(CameraConfig,           "Imaging::CameraConfig")
    dds.DomainParticipant.register_idl_type(DeviceTelemetry,        "Devices::DeviceTelemetry")
    dds.DomainParticipant.register_idl_type(ClinicalAlert,          "ClinicalAlerts::ClinicalAlert")
    dds.DomainParticipant.register_idl_type(RiskScore,              "ClinicalAlerts::RiskScore")
    dds.DomainParticipant.register_idl_type(ResourceAvailability,   "Hospital::ResourceAvailability")

# Usage:
#   initialize_connext()   # must be first
#   provider = dds.QosProvider("USER_QOS_PROFILES.xml")
#   participant = provider.create_participant_from_config(
#       "MedtechParticipantLibrary::MonitoringDashboard")
```

#### Rules

1. **Every application must call `initialize_connext()` before any participant
   creation.** It is part of the mandatory startup sequence alongside Distributed
   Logger setup.
2. **Compliance mask before type registration.** The mask must be set first; type
   registration may depend on the runtime serialization configuration being in
   place.
3. **Only `accept_unknown_enum_value` is added to the default mask.** The
   `default_mask()` baseline is preserved so that any bits Connext enables by
   default remain active. No compliance bits beyond the default plus
   `accept_unknown_enum_value` (bit `0x00000020`) may be added without operator
   approval.
4. **Registered names must match XML exactly.** The name string in each
   `register_type` call must match the `name` attribute of the corresponding
   `<register_type>` element in the domain XML library. A mismatch causes
   participant creation to fail.
5. **One call per type.** There is no batch registration — each type requires its
   own call.
6. **Application code must handle the sentinel value.** All `switch` or `if` chains
   on enum fields must include a branch for the `UNKNOWN` sentinel — log a warning
   and degrade gracefully.

The field inventory tables below define the canonical fields for every
IDL type. IDL files are authored during implementation Phase 1
(Foundation) using these definitions. Agents must not add fields
beyond those listed without operator approval.

Field names used in spec scenarios (e.g., `interlock_active`,
`heart_rate`, `systolic_bp`) are derived from these tables. Key field
paths in the Domain Definitions tables above (e.g., `patient.id`)
correspond to nested key resolution through the types below.

---

## IDL Type Definitions (Field Inventory)

### Module: Common (`common/common.idl`)

#### Constants

| Constant | Type | Value | Purpose |
|----------|------|-------|---------|
| `MAX_ID_LENGTH` | `long` | 16 | Bound for all entity identifier strings |
| `MAX_NAME_LENGTH` | `long` | 128 | Bound for human-readable names |
| `MAX_DESCRIPTION_LENGTH` | `long` | 512 | Bound for free-text description and rationale fields |
| `MAX_WAVEFORM_SAMPLES` | `long` | 64 | Maximum samples per waveform block |
| `MAX_ALARM_COUNT` | `long` | 16 | Maximum active alarms per alarm message |
| `MAX_JOINT_COUNT` | `long` | 7 | Maximum robot arm joint count |
| `MAX_FRAME_SIZE` | `long` | 2097152 | Maximum compressed camera frame payload (2 MB) |

#### Aliases

| Alias | Underlying Type | Usage |
|-------|-----------------|-------|
| `EntityId` | `string<MAX_ID_LENGTH>` | Reusable bounded identifier type for patients, devices, robots, procedures, operators, cameras, alerts |

#### `Common::Time_t`

Standard timestamp. `@final`. Aligned with
[`foxglove::Time`](https://github.com/foxglove/foxglove-sdk/blob/main/schemas/omgidl/foxglove/Time.idl)
(`uint32 sec` + `uint32 nsec`) for field-semantic compatibility with
Foxglove's `CompressedImage` type (used by `Imaging::CameraFrame`).

> **Y2038 limitation:** `uint32 sec` overflows on 2038-01-19 03:14:07 UTC.
> The previous representation used `int64 seconds` (no practical overflow).
> This trade-off is accepted because Foxglove alignment is a higher priority
> than Y2038 safety for this project's simulation-focused deployment. The
> affected fields are `CameraFrame.timestamp` (Foxglove-aligned, primary
> motivation), `ProcedureContext.start_time` (wall-clock procedure start),
> and `AlarmMessage.onset_time` (wall-clock alarm onset). **Migration plan:**
> when Foxglove migrates `foxglove::Time` to a wider seconds field (e.g.,
> `int64 sec`), update `Common::Time_t` to match. Because the struct is
> `@final`, any field-type change is a breaking type evolution requiring
> coordinated redeployment of all publishers and subscribers — acceptable
> given the project's containerized deployment model. Monitor the upstream
> schema at the Foxglove SDK repository.

> **`source_timestamp` convention:** Most top-level types no longer
> carry an explicit `timestamp` member. Sample publication time is
> conveyed via `SampleInfo.source_timestamp`, set automatically by
> the DataWriter. `Common::Time_t` is retained only where a
> domain-meaningful time distinct from write time is needed
> (`CameraFrame.timestamp`, `ProcedureContext.start_time`,
> `AlarmMessage.onset_time`).

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `sec` | `uint32` | — | Seconds since epoch (Y2038 — see limitation note above) |
| `nsec` | `uint32` | — | Sub-second nanoseconds |

#### `Common::EntityIdentity`

`@nested` `@appendable` — embedded identity struct for nested key
resolution. When used as a `@key` member in a top-level type
(e.g., `@key EntityIdentity patient`), the effective topic key
path becomes `patient.id`.

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `id` | `EntityId` | @key | Stable application-level identifier |
| `name` | `string<MAX_NAME_LENGTH>` | — | Display name (informational, not part of key) |

---

### Module: Surgery (`surgery/surgery.idl`)

Dependencies: `#include "common/common.idl"`

#### Enums

**`Surgery::RobotMode`** — `@appendable`

| Value | Meaning |
|-------|---------|
| `UNKNOWN` | Sentinel — unknown or unrecognized mode (deserialization default for evolved types) |
| `IDLE` | Robot powered but not in active control loop |
| `OPERATIONAL` | Normal operating mode — accepting commands |
| `PAUSED` | Temporarily suspended — commands queued but not executed |
| `EMERGENCY_STOP` | Safety-triggered halt — no motion permitted |

**`Surgery::ProcedurePhase`** — `@appendable`

| Value | Meaning |
|-------|---------|
| `UNKNOWN` | Sentinel — unknown or unrecognized phase |
| `PRE_OP` | Pre-operative setup in progress |
| `IN_PROGRESS` | Active surgical procedure |
| `COMPLETING` | Procedure winding down |
| `COMPLETED` | Procedure finished |
| `ALERT` | Procedure requires immediate attention |

#### Helper Structs

**`Surgery::CartesianPosition`** — `@nested` `@final`

 Retained for `RobotCommand.target_position` where only position (no
 orientation) is commanded. For combined position + orientation, see
 `Common::Pose`.

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `x` | `double` | — | X position (mm) |
| `y` | `double` | — | Y position (mm) |
| `z` | `double` | — | Z position (mm) |

**`Surgery::JointState`** — `@nested` `@appendable` *(V1.2)*

Per-joint state. Field-semantically aligned with
[`foxglove::JointState`](https://github.com/foxglove/foxglove-sdk/blob/main/schemas/omgidl/foxglove/JointState.idl).
See [Foxglove Schema Alignment](#foxglove-schema-alignment).

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `name` | `string<Common::MAX_NAME_LENGTH>` | — | Joint name (e.g., `"shoulder_pan"`, `"elbow_flex"`) — Foxglove requires named joints for URDF binding |
| `position` | `double` | — | Joint position: radians for revolute, meters for prismatic |
| `velocity` | `double` | — | Joint velocity: rad/s or m/s (0.0 if unavailable) |
| `effort` | `double` | — | Joint torque (Nm) or force (N) (0.0 if unavailable) |

> **Foxglove `@optional` note:** Foxglove's `JointState` uses `@optional`
> for numeric fields. The medtech type uses non-optional `double` fields
> defaulting to 0.0 because `@optional` is not idiomatic in the existing
> data model and adds serialization overhead. The Routing Service
> Transformation plugin maps 0.0 values appropriately.

**`Surgery::FrameTransformEntry`** — `@nested` `@appendable` *(V1.2)*

Single parent → child coordinate frame transform. Field-semantically
aligned with
[`foxglove::FrameTransform`](https://github.com/foxglove/foxglove-sdk/blob/main/schemas/omgidl/foxglove/FrameTransform.idl)
(minus `timestamp`, conveyed via `SampleInfo.source_timestamp`).

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `parent_frame_id` | `string<Common::MAX_NAME_LENGTH>` | — | Parent coordinate frame (e.g., `"base_link"`, `"shoulder"`) |
| `child_frame_id` | `string<Common::MAX_NAME_LENGTH>` | — | Child coordinate frame (e.g., `"shoulder"`, `"elbow"`) |
| `translation` | `Common::Vector3` | — | Position of child origin in parent frame |
| `rotation` | `Common::Quaternion` | — | Orientation of child frame relative to parent |

#### `Surgery::RobotCommand`

Topic: `RobotCommand` | Domain Tag: `control` | Pattern: `Command`
| `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `robot_id` | `Common::EntityId` | @key | Target robot |
| `command_id` | `int32` | @key | Unique command sequence number |
| `target_position` | `CartesianPosition` | — | Commanded tool-tip target |

#### `Surgery::RobotState`

Topic: `RobotState` | Domain Tag: `control` | Pattern: `State`
| `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `robot_id` | `Common::EntityId` | @key | Robot instance identifier |
| `joints` | `sequence<JointState, Common::MAX_JOINT_COUNT>` | — | *(V1.2 — replaces `joint_positions`)* Per-joint state: name, position, velocity, effort. Foxglove `JointStates` aligned. |
| `tool_tip_pose` | `Common::Pose` | — | *(V1.2 — replaces `tool_tip_position`)* Tool-tip position + orientation. Foxglove `PoseInFrame` aligned. |
| `operational_mode` | `RobotMode` | — | Current robot mode |
| `error_state` | `int32` | — | Error code (0 = no error) |

#### `Surgery::SafetyInterlock`

Topic: `SafetyInterlock` | Domain Tag: `control` | Pattern: `State`
| `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `robot_id` | `Common::EntityId` | @key | Robot being interlocked |
| `interlock_active` | `boolean` | — | `true` = interlock engaged, robot must stop |
| `reason` | `string<Common::MAX_DESCRIPTION_LENGTH>` | — | Human-readable interlock reason |

#### `Surgery::OperatorInput`

Topic: `OperatorInput` | Domain Tag: `control` | Pattern: `Stream`
| `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `operator_id` | `Common::EntityId` | @key | Operator (surgeon) identifier |
| `robot_id` | `Common::EntityId` | @key | Target robot |
| `x_axis` | `double` | — | Joystick/haptic X translation |
| `y_axis` | `double` | — | Joystick/haptic Y translation |
| `z_axis` | `double` | — | Joystick/haptic Z translation |
| `roll` | `double` | — | Rotation about X axis |
| `pitch` | `double` | — | Rotation about Y axis |
| `yaw` | `double` | — | Rotation about Z axis |
| `primary_button` | `boolean` | — | Primary action button state |
| `secondary_button` | `boolean` | — | Secondary action button state |

#### `Surgery::ProcedureContext`

Topic: `ProcedureContext` | Domain Tag: `operational` | Pattern:
`State` | `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `procedure_id` | `Common::EntityId` | @key | Unique procedure instance |
| `hospital` | `string<Common::MAX_NAME_LENGTH>` | — | Hospital name |
| `room` | `string<Common::MAX_NAME_LENGTH>` | — | Operating room (e.g., "OR-3") |
| `bed` | `string<Common::MAX_NAME_LENGTH>` | — | Bed/station identifier |
| `patient` | `Common::EntityIdentity` | — | Assigned patient (not a key — context is keyed by `procedure_id`) |
| `procedure_type` | `string<Common::MAX_NAME_LENGTH>` | — | Procedure category |
| `surgeon` | `string<Common::MAX_NAME_LENGTH>` | — | Lead surgeon name |
| `anesthesiologist` | `string<Common::MAX_NAME_LENGTH>` | — | Anesthesiologist name |
| `start_time` | `Common::Time_t` | — | Procedure start time |

#### `Surgery::ProcedureStatus`

Topic: `ProcedureStatus` | Domain Tag: `operational` | Pattern:
`State` | `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `procedure_id` | `Common::EntityId` | @key | Procedure instance identifier |
| `phase` | `ProcedurePhase` | — | Current procedure lifecycle phase |
| `status_message` | `string<Common::MAX_DESCRIPTION_LENGTH>` | — | Optional human-readable status detail |

---

### Module: Monitoring (`monitoring/monitoring.idl`)

Dependencies: `#include "common/common.idl"`

#### Enums

**`Monitoring::AlarmSeverity`** — `@appendable`

| Value | Meaning |
|-------|---------|
| `UNKNOWN` | Sentinel — unknown or unrecognized severity |
| `INFO` | Informational — no action required |
| `LOW` | Low priority — review at convenience |
| `MEDIUM` | Medium priority — timely review needed |
| `HIGH` | High priority — prompt attention required |
| `CRITICAL` | Critical — immediate intervention required |

**`Monitoring::AlarmState`** — `@appendable`

| Value | Meaning |
|-------|---------|
| `UNKNOWN` | Sentinel — unknown or unrecognized alarm state |
| `ACTIVE` | Alarm condition is present |
| `CLEARED` | Alarm condition has resolved |
| `ACKNOWLEDGED` | Alarm seen by clinician but not yet resolved |

**`Monitoring::WaveformKind`** — `@appendable`

| Value | Meaning |
|-------|---------|
| `UNKNOWN` | Sentinel — unknown or unrecognized waveform type |
| `ECG` | Electrocardiogram |
| `PLETH` | Plethysmograph (pulse oximetry waveform) |
| `CAPNOGRAPHY` | End-tidal CO₂ waveform |
| `ABP` | Arterial blood pressure waveform |

#### `Monitoring::PatientVitals`

Topic: `PatientVitals` | Domain Tag: `clinical` | Pattern: `State`
| `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `patient` | `Common::EntityIdentity` | @key | Patient identity (effective key: `patient.id`) |
| `heart_rate` | `double` | — | Heart rate in bpm — referenced as HR in specs |
| `spo2` | `double` | — | Oxygen saturation (%) — SpO2 |
| `systolic_bp` | `double` | — | Systolic blood pressure (mmHg) |
| `diastolic_bp` | `double` | — | Diastolic blood pressure (mmHg) |
| `temperature` | `double` | — | Body temperature (°C) |
| `respiratory_rate` | `double` | — | Breaths per minute |

#### `Monitoring::WaveformData`

Topic: `WaveformData` | Domain Tag: `clinical` | Pattern: `Stream`
| `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `patient` | `Common::EntityIdentity` | @key | Patient identity (effective key: `patient.id`) |
| `source_device_id` | `Common::EntityId` | @key | Device producing the waveform |
| `waveform_kind` | `WaveformKind` | @key | Type of waveform signal |
| `samples` | `sequence<double, Common::MAX_WAVEFORM_SAMPLES>` | — | Waveform sample block (e.g., 10 samples per block for ECG at 500 Sa/s published at 50 Hz) |
| `sample_rate_hz` | `double` | — | Nominal sample rate of the source signal |

#### `Monitoring::AlarmMessage`

Topic: `AlarmMessages` | Domain Tag: `clinical` | Pattern: `State`
| `@appendable`

Per-alarm keying: each alarm is its own DDS instance (keyed by `alarm_id`).
Writers may enable DDS batching for efficient transport.

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `alarm_id` | `Common::EntityId` | @key | Unique alarm instance identifier |
| `patient_id` | `Common::EntityId` | — | Patient associated with this alarm |
| `source_device_id` | `Common::EntityId` | — | Device generating the alarm |
| `severity` | `AlarmSeverity` | — | Alarm severity level |
| `state` | `AlarmState` | — | Current alarm state (ACTIVE, CLEARED, ACKNOWLEDGED) |
| `alarm_code` | `string<64>` | — | Machine-readable alarm code |
| `message` | `string<Common::MAX_DESCRIPTION_LENGTH>` | — | Human-readable alarm description |
| `onset_time` | `Common::Time_t` | — | When the alarm condition first occurred |

---

### Module: Imaging (`imaging/imaging.idl`)

Dependencies: `#include "common/common.idl"`

#### `Imaging::CameraFrame`

Topic: `CameraFrame` | Domain Tag: `operational` | Pattern: `Stream`
| `@appendable`

Compressed image frame with inline data payload. Field-semantically aligned
with Foxglove `CompressedImage` (`timestamp`, `frame_id`, `data`, `format`)
but not wire-compatible due to `@key camera_id` (see XTypes analysis in
INC-027). If Foxglove interop is needed, a Routing Service transformation
would bridge between the two types.

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `camera_id` | `Common::EntityId` | @key | Camera source identifier |
| `timestamp` | `Common::Time_t` | — | Frame capture time |
| `frame_id` | `string<Common::MAX_NAME_LENGTH>` | — | Coordinate frame reference (e.g., `"endoscope_left"`, `"overhead_rgb"`). Foxglove-compatible field. |
| `data` | `sequence<uint8, Common::MAX_FRAME_SIZE>` | — | Inline compressed image bytes |
| `format` | `string<16>` | — | Compression format: `"jpeg"`, `"png"`, `"h264"`, `"h265"` |

#### `Imaging::CameraConfig`

Topic: `CameraConfig` | Domain Tag: `operational` | Pattern: `State`
| `@appendable`

Camera stream configuration state — published once at startup, re-published
only when camera settings change. Late joiners receive current config
immediately via TRANSIENT_LOCAL durability. Subscribers correlate with
`CameraFrame` samples via the shared `camera_id` key.

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `camera_id` | `Common::EntityId` | @key | Camera source identifier (same key as `CameraFrame`) |
| `width` | `uint32` | — | Frame width (pixels) |
| `height` | `uint32` | — | Frame height (pixels) |
| `encoding` | `string<32>` | — | Decoded pixel format (e.g., `"RGB8"`, `"YUV422"`, `"MONO8"`) |
| `exposure_us` | `uint32` | — | Exposure time in microseconds — clinically relevant for motion blur detection |
| `compression_ratio` | `float` | — | Typical compressed-size / raw-size ratio (0.0–1.0) for current settings |

---

### Module: Devices (`devices/devices.idl`)

Dependencies: `#include "common/common.idl"`

#### Enums

**`Devices::DeviceKind`** — `@appendable`

| Value | Meaning |
|-------|---------|
| `UNKNOWN` | Sentinel — unknown or unrecognized device kind |
| `INFUSION_PUMP` | IV infusion pump |
| `ANESTHESIA_MACHINE` | Anesthesia delivery system |
| `VENTILATOR` | Mechanical ventilator |
| `PATIENT_MONITOR` | Bedside patient monitor |

**`Devices::DeviceOperatingState`** — `@appendable`

| Value | Meaning |
|-------|---------|
| `UNKNOWN` | Sentinel — unknown or unrecognized operating state |
| `RUNNING` | Device operating normally |
| `STANDBY` | Device powered on but idle |
| `ALARM` | Device in alarm state |
| `OFF` | Device powered off or disconnected |

#### `Devices::DeviceTelemetry`

Topic: `DeviceTelemetry` | Domain Tag: `clinical` | Pattern: `State`
| `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `device_id` | `Common::EntityId` | @key | Unique device identifier |
| `device_kind` | `DeviceKind` | — | Type of device |
| `operating_state` | `DeviceOperatingState` | — | Current operating state |
| `battery_percent` | `double` | — | Battery level (0–100; −1 if N/A) |
| `error_code` | `int32` | — | Device error code (0 = no error) |
| `status_message` | `string<Common::MAX_DESCRIPTION_LENGTH>` | — | Free-text device status |

**`Devices::PumpMode`** — `@appendable` *(V2)*

| Value | Meaning |
|-------|---------|
| `UNKNOWN` | Sentinel — unknown or unrecognized pump mode |
| `CONTINUOUS` | Steady-state infusion at configured rate |
| `INTERMITTENT` | Periodic bolus at scheduled intervals |
| `LOADING_DOSE` | Initial high-rate bolus before transitioning to maintenance |
| `PCA` | Patient-controlled analgesia — demand-based delivery |
| `KVO` | Keep-vein-open — minimal flow to maintain IV patency |

**`Devices::VentilationMode`** — `@appendable` *(V2)*

| Value | Meaning |
|-------|---------|
| `UNKNOWN` | Sentinel — unknown or unrecognized ventilation mode |
| `CMV` | Continuous mandatory ventilation — fully controlled breaths |
| `SIMV` | Synchronized intermittent mandatory ventilation — mixed mandatory + spontaneous |
| `CPAP` | Continuous positive airway pressure — spontaneous breathing with pressure support |
| `PCV` | Pressure-controlled ventilation — clinician sets pressure, vent delivers volume |
| `PSV` | Pressure support ventilation — augments spontaneous breaths with set pressure |

#### `Devices::PumpStatus` *(V2 — Device Integration Gateway)*

Not registered as a V1 topic. Defined here to stabilize the type
contract for V2 bidirectional device gateway integration. The V2
Device Integration Gateway will subscribe to physical pump telemetry
via the facility's device integration engine (e.g., HL7 or
proprietary serial gateway) and republish it as DDS samples. This
type models the pump's real-time infusion state, fluid levels, and
safety alarms — enabling the dashboard and ClinicalAlerts engine to incorporate
drug delivery context into clinical decision support.
`@appendable`.

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `device_id` | `Common::EntityId` | @key | Pump instance identifier — matches the physical asset tag in the facility's device registry |
| `drug_label` | `string<Common::MAX_DESCRIPTION_LENGTH>` | — | Human-readable drug name (e.g., "Propofol 10 mg/mL") — as configured by the clinician at pump setup |
| `pump_mode` | `PumpMode` | — | Current delivery mode — determines how `infusion_rate_ml_hr` is interpreted |
| `infusion_rate_ml_hr` | `double` | — | Current infusion rate (mL/h); 0.0 when paused or in KVO (KVO rate is device-internal) |
| `volume_infused_ml` | `double` | — | Cumulative volume delivered since infusion start (mL); monotonically increasing within a session |
| `volume_remaining_ml` | `double` | — | Estimated volume remaining in the IV bag (mL); −1.0 if the pump does not support bag volume sensing |
| `occlusion_detected` | `boolean` | — | True when the pump detects downstream line occlusion — safety alarm, triggers audible alert at bedside |
| `air_in_line_detected` | `boolean` | — | True when the pump detects air bubbles in the infusion line — safety alarm, pump auto-pauses |
| `operating_state` | `DeviceOperatingState` | — | General device state (RUNNING, STANDBY, ALARM, OFF) — distinct from `pump_mode` which describes the delivery pattern |

#### `Devices::VentilatorCommands` *(V2 — Device Integration Gateway)*

Not registered as a V1 topic. Defined here to stabilize the type
contract for V2 bidirectional device gateway integration. The V2
gateway will accept ventilator parameter commands from the DDS
databus and translate them to the physical ventilator's control
interface. This type models a clinician-approved parameter change
request — not autonomous closed-loop control. Each command carries a
unique sequence number for reliable tracking and audit.
`@appendable`.

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `device_id` | `Common::EntityId` | @key | Ventilator instance identifier — matches the physical asset tag |
| `command_id` | `int32` | @key | Monotonically increasing command sequence number — enables deduplication and audit trail |
| `ventilation_mode` | `VentilationMode` | — | Requested ventilation mode — gateway translates to device-native protocol |
| `tidal_volume_ml` | `double` | — | Target tidal volume per breath (mL); applicable in volume-controlled modes (CMV, SIMV); ignored in pressure-controlled modes |
| `respiratory_rate_target` | `double` | — | Target mandatory breath rate (breaths/min); 0.0 in fully spontaneous modes (CPAP, PSV) |
| `peep_cmh2o` | `double` | — | Positive end-expiratory pressure (cmH₂O) — maintains alveolar recruitment between breaths |
| `fio2_percent` | `double` | — | Fraction of inspired oxygen (21–100%); 21% = room air |
| `inspiratory_pressure_cmh2o` | `double` | — | Target inspiratory pressure (cmH₂O); applicable in PCV and PSV modes; ignored in volume-controlled modes |
| `inspiratory_time_s` | `double` | — | Inspiratory time (seconds); controls I:E ratio; 0.0 = use device default |

---

### Module: ClinicalAlerts (`clinical_alerts/clinical_alerts.idl`)

Dependencies: `#include "common/common.idl"`

#### Enums

**`ClinicalAlerts::AlertSeverity`** — `@appendable`

| Value | Meaning |
|-------|---------|
| `UNKNOWN` | Sentinel — unknown or unrecognized alert severity |
| `INFO` | Informational — no action required |
| `WARNING` | Elevated risk — clinician awareness |
| `CRITICAL` | Immediate clinical intervention recommended |

**`ClinicalAlerts::AlertCategory`** — `@appendable`

| Value | Meaning |
|-------|---------|
| `UNKNOWN` | Sentinel — unknown or unrecognized alert category |
| `CLINICAL` | Computed from patient data (risk models) |
| `DEVICE` | Originating from device alarm escalation |
| `SYSTEM` | System-level alert (connectivity, service health) |

#### `ClinicalAlerts::RiskScore`

Topic: `RiskScore` | Domain: Hospital (11) | Pattern: `State`
| `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `patient` | `Common::EntityIdentity` | @key | Patient identity (effective key: `patient.id`) |
| `score_kind` | `string<64>` | @key | Risk model name (e.g., "hemorrhage", "sepsis") |
| `score_value` | `double` | — | Computed risk score (0.0–1.0) |
| `confidence` | `double` | — | Model confidence (0.0–1.0) |
| `rationale` | `string<Common::MAX_DESCRIPTION_LENGTH>` | — | Human-readable explanation of contributing factors |

#### `ClinicalAlerts::ClinicalAlert`

Topic: `ClinicalAlert` | Domain: Hospital (11) | Pattern: `State`
| `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `alert_id` | `Common::EntityId` | @key | Unique alert instance |
| `patient` | `Common::EntityIdentity` | — | Affected patient (not a key — alerts are keyed by `alert_id`) |
| `severity` | `AlertSeverity` | — | Alert severity |
| `category` | `AlertCategory` | — | Alert category |
| `message` | `string<Common::MAX_DESCRIPTION_LENGTH>` | — | Human-readable alert description |
| `rationale` | `string<Common::MAX_DESCRIPTION_LENGTH>` | — | Contributing factors / risk model output |
| `source_topic` | `string<64>` | — | Originating topic (e.g., "PatientVitals") |
| `room` | `string<Common::MAX_NAME_LENGTH>` | — | Operating room context |
| `is_resolved` | `boolean` | — | `true` when the alert condition has cleared |

---

### Module: Hospital (`hospital/hospital.idl`)

Dependencies: `#include "common/common.idl"`

#### `Hospital::ResourceAvailability`

Topic: `ResourceAvailability` | Domain: Hospital (11) | Pattern:
`State` | `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `resource_id` | `Common::EntityId` | @key | Unique resource identifier |
| `resource_kind` | `string<64>` | — | Category (e.g., "OR", "bed", "ventilator", "nurse", "surgeon") |
| `name` | `string<Common::MAX_NAME_LENGTH>` | — | Display name |
| `is_available` | `boolean` | — | Current availability status |
| `location` | `string<Common::MAX_NAME_LENGTH>` | — | Current location or assigned room |
| `notes` | `string<Common::MAX_DESCRIPTION_LENGTH>` | — | Free-text notes (e.g., "in sterilization") |

---

## Security: Domain Governance (Deferred)

Domain governance documents are part of the data model — they define how domains, partitions, and topics are secured at the architectural level. Governance is not per-module; it is a system-wide contract maintained in `interfaces/` alongside type definitions, domain definitions, and QoS profiles.

When security implementation begins, this section will define:

- **Per-domain governance documents** — one governance XML per domain ID, specifying:
  - Whether unauthenticated participants are allowed
  - Join access control requirements
  - Discovery protection (encrypt/sign discovery traffic)
  - RTPS protection level (encrypt, sign, or none)
  - Topic-level security rules: which topics require encryption, signing, or both
- **Partition-aware rules** — how domain partitions (room/procedure contexts) interact with access control; whether partition membership is constrained by permissions
- **Topic security classification** — mapping topics to protection levels aligned with the risk-class domain tags:
  - `control` tag topics (Class C/III) → encrypt + sign
  - `clinical` tag topics (Class B/II) → encrypt
  - `operational` tag topics (Class A/I) → sign or unprotected (per policy decision)
- **Cross-domain bridging security** — Routing Service identity and permissions for topics it is authorized to bridge

Governance files will be maintained at:

```
interfaces/security/
├── governance/
│   ├── Governance_Procedure.xml    # Procedure domain governance
│   └── Governance_Hospital.xml     # Hospital domain governance
└── permissions/                    # Per-participant permissions (module-owned, not defined here)
```

The security posture and policies must be scoped and documented here before implementation begins.

---

## Foxglove Schema Alignment

The medtech suite adopts **field-semantic alignment** with selected
[Foxglove message schemas](https://docs.foxglove.dev/docs/sdk/schemas)
(OMG IDL variants from the
[foxglove-sdk](https://github.com/foxglove/foxglove-sdk/tree/main/schemas/omgidl/foxglove))
to enable visualization of DDS data in
[Foxglove Studio](https://foxglove.dev/) with minimal adapter code.

### Alignment Strategy

**Field-semantic alignment** means medtech IDL types use field names,
nesting, and value conventions that match their Foxglove equivalents
wherever doing so does not compromise the DDS data model's functional
requirements. Specifically:

- **`@key` fields are never removed or changed** to satisfy Foxglove
  compatibility. DDS instance lifecycle, content filtering, and
  ownership semantics depend on keys.
- **Domain-specific fields** (e.g., `operational_mode`, `error_state`,
  `alarm_code`) that have no Foxglove analog are retained. Foxglove
  ignores fields it does not recognize.
- **Nested helper structs** (`Quaternion`, `Pose`, `Vector3`) are
  added to the `Common` module with field names matching their
  `foxglove::` counterparts. Medtech types embed these helpers where
  the data semantically matches.
- **Types are NOT wire-compatible** with `foxglove::` types. Foxglove
  types lack `@key` fields, use unbounded `string` and `sequence`,
  carry no DDS extensibility annotations, and live in the `foxglove`
  IDL module. The medtech types remain in their own modules with
  bounded members and full DDS annotations.

The gap between field-aligned medtech types and Foxglove-native types
is bridged by the **Foxglove Bridge plugin pipeline** (V2) — see
[Foxglove Bridge Plugins](#foxglove-bridge-plugins) below.

### Alignment Tiers and Milestones

The alignment is split into **data model** work (updating medtech IDL
types) and **plugin integration** work (transformation, adapter, and
storage plugins). Data model alignment for Tier 1 is delivered in
V1.2; all plugin infrastructure and Foxglove Studio connectivity is
delivered in V2.

| Tier | Foxglove Schema(s) | Medtech Type(s) | Foxglove Panel | Data Model | Plugin Integration |
|------|---------------------|-----------------|----------------|------------|--------------------|
| 1 | `JointStates` / `JointState` | `Surgery::RobotState` (`joints` field) | 3D (URDF model) | V1.2 | V2 |
| 1 | `FrameTransform` / `FrameTransforms` | New: `Surgery::RobotFrameTransform` | 3D (TF tree) | V1.2 | V2 |
| 1 | `PoseInFrame` | `Surgery::RobotState` (`tool_tip_pose` field) | 3D (pose marker) | V1.2 | V2 |
| 1 | `CompressedImage` | `Imaging::CameraFrame` (strengthen existing) | Image | V1.2 | V2 |
| 2 | `SceneUpdate` / `SceneEntity` | New: `Visualization::SceneUpdate` | 3D (primitives) | V2 | V2 |
| 2 | `CameraCalibration` | New: `Imaging::CameraCalibration` | 3D + Image | V2 | V2 |
| 2 | `ImageAnnotations` | New: `Imaging::ImageAnnotations` | Image (overlays) | V2 | V2 |
| 2 | `CompressedVideo` | New: `Imaging::CompressedVideo` | Image (video) | V2 | V2 |
| 2 | `Log` | New: `Diagnostics::LogMessage` | Log | V2 | V2 |
| 3 | `PointCloud` | New (TBD) | 3D (point cloud) | V3 | V3 |
| 3 | `Grid` | New (TBD) | 3D (heatmap) | V3 | V3 |
| 3 | `LocationFix` | New (TBD) | Map | V3 | V3 |
| 3 | `RawAudio` | New (TBD) | Plot | V3 | V3 |

Tier 3 types are placeholders — their IDL definitions will be authored
when V3 scope is finalized.

### Common Helper Structs (V1.2)

Three new helper structs are added to `Common` (`common/common.idl`)
for reuse across modules. Field names match their `foxglove::`
counterparts.

**`Common::Quaternion`** — `@nested` `@final`

Aligned with
[`foxglove::Quaternion`](https://github.com/foxglove/foxglove-sdk/blob/main/schemas/omgidl/foxglove/Quaternion.idl).

| Member | Type | Notes |
|--------|------|-------|
| `x` | `double` | Quaternion x component |
| `y` | `double` | Quaternion y component |
| `z` | `double` | Quaternion z component |
| `w` | `double` | Quaternion w component (default: 1.0 = identity rotation) |

**`Common::Vector3`** — `@nested` `@final`

Aligned with
[`foxglove::Vector3`](https://github.com/foxglove/foxglove-sdk/blob/main/schemas/omgidl/foxglove/Vector3.idl).
Used for translation components in transforms and directional vectors.

| Member | Type | Notes |
|--------|------|-------|
| `x` | `double` | X component |
| `y` | `double` | Y component |
| `z` | `double` | Z component |

**`Common::Pose`** — `@nested` `@final`

Aligned with
[`foxglove::Pose`](https://github.com/foxglove/foxglove-sdk/blob/main/schemas/omgidl/foxglove/Pose.idl).
Combines position and orientation for 3D spatial representation.

| Member | Type | Notes |
|--------|------|-------|
| `position` | `Vector3` | Position in 3D space |
| `orientation` | `Quaternion` | Orientation as quaternion |

> **Relationship to `CartesianPosition`:** The existing
> `Surgery::CartesianPosition` struct (x, y, z only) is retained for
> `RobotCommand.target_position` where orientation is not commanded.
> `Common::Pose` is used where both position and orientation are
> semantically meaningful (e.g., robot tool tip state in `RobotState`).

### V1.2 Field Alignments

The following types are updated or added in V1.2 to enable Tier 1
Foxglove visualization.

#### `Surgery::RobotState` (Updated)

Two field changes for Foxglove alignment:

1. `joint_positions` (`sequence<double>`) → `joints`
   (`sequence<JointState, MAX_JOINT_COUNT>`) — provides named joints
   with velocity and effort, aligned with `foxglove::JointStates`.
2. `tool_tip_position` (`CartesianPosition`) → `tool_tip_pose`
   (`Common::Pose`) — adds orientation, aligned with
   `foxglove::PoseInFrame`.

See the updated field inventory in the
[Surgery::RobotState](#surgeryrobotstate) section above. All existing
consumers (`RobotState` subscribers in Digital Twin Display, Hospital
Dashboard robot status panel) must be updated to use the new field
names and types.

#### `Surgery::RobotFrameTransform` (New Topic Type)

Topic: `RobotFrameTransform` | Domain Tag: `control` | Pattern:
`Stream` | `@appendable`

Publishes the robot's kinematic frame hierarchy as individual
parent → child transform pairs. The robot controller publishes one
sample containing all transforms for the kinematic chain at the
`RobotState` publication rate (100 Hz). Aligned with
[`foxglove::FrameTransforms`](https://github.com/foxglove/foxglove-sdk/blob/main/schemas/omgidl/foxglove/FrameTransforms.idl).

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `robot_id` | `Common::EntityId` | @key | Robot instance identifier — correlates with `RobotState` |
| `transforms` | `sequence<FrameTransformEntry, Common::MAX_JOINT_COUNT>` | — | Ordered kinematic chain: base → link1 → … → tool_tip |

QoS: inherits the `Stream` pattern base with `Deadline20ms` (same as
`RobotState`) via a new `TopicProfiles::RobotFrameTransform` profile.

#### `Imaging::CameraFrame` (Alignment Strengthened)

No field changes. The existing field-semantic alignment with
`foxglove::CompressedImage` is already complete:

| Medtech Field | Foxglove Field | Status |
|---------------|----------------|--------|
| `timestamp` (`Common::Time_t`) | `timestamp` (`foxglove::Time`) | Aligned |
| `frame_id` (`string<128>`) | `frame_id` (`string`) | Aligned |
| `data` (`sequence<uint8, MAX_FRAME_SIZE>`) | `data` (`sequence<uint8>`) | Aligned (bounded vs unbounded) |
| `format` (`string<16>`) | `format` (`string`) | Aligned |
| `camera_id` (`@key EntityId`) | *(no equivalent)* | Medtech-only — stripped by Transformation |

The Routing Service Transformation plugin maps `CameraFrame` →
`foxglove::CompressedImage` by copying the four aligned fields and
dropping `camera_id`.

### V2 Alignment Types (Deferred)

The following types will be fully defined when V2 scope is finalized.
Placeholder descriptions are provided for design continuity.

| Type | Foxglove Schema | Purpose |
|------|-----------------|--------|
| `Imaging::CameraCalibration` | `foxglove::CameraCalibration` | Intrinsic matrix (K), distortion model, projection matrix (P). Extends camera config for 3D image projection and lens correction. |
| `Imaging::ImageAnnotations` | `foxglove::ImageAnnotations` | 2D circle, point, and text annotations overlaid on `CameraFrame`. Tool tracking markers, safety zone indicators. |
| `Imaging::CompressedVideo` | `foxglove::CompressedVideo` | H.264/H.265 compressed video stream. Bandwidth reduction (10–50×) over per-frame JPEG. Coexists with `CameraFrame` for backward compatibility. |
| `Visualization::SceneUpdate` | `foxglove::SceneUpdate` | 3D scene description with entity primitives (cubes, cylinders, arrows, text). OR environment, robot arm schematic, safety zone boundaries. |
| `Diagnostics::LogMessage` | `foxglove::Log` | Structured log messages (timestamp, level, message, module name, file, line). Bridge from RTI Logging API / Monitoring Library 2.0 output for Foxglove Log panel visualization. |

V2 types will be defined in new IDL modules (`visualization/`,
`diagnostics/`) under `interfaces/idl/`. Their domain assignment,
QoS profiles, and topic registrations will be authored as part of
the V2 extension cycle.

### V3 Alignment Types (Placeholder)

| Foxglove Schema | Potential Medtech Use |
|-----------------|-----------------------|
| `foxglove::PointCloud` | Depth camera / 3D scanner data for surgical navigation |
| `foxglove::Grid` | 2D occupancy or heatmap overlay (e.g., radiation exposure map, thermal map) |
| `foxglove::LocationFix` | Facility-level indoor positioning / asset tracking |
| `foxglove::RawAudio` | OR ambient audio monitoring / communication recording |

These are not scoped. IDL definitions will be authored when V3
capability scope is finalized.

### Foxglove Bridge Plugins

The Foxglove Bridge is a set of three C++ shared-library plugins that
form a pipeline between the medtech DDS data model and Foxglove Studio.
All plugin infrastructure is delivered in **V2**; V1.2 delivers only
the data model field-semantic alignment described above.

The three plugins are:

1. **Routing Service Transformation plugin** —
   `libmedtech_foxglove_transf.so` implementing
   [`rti::routing::transf::DynamicDataTransformation`](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/api/routing_service/api_cpp/group__RTI__RoutingServiceTransformationModule.html).
   Reshapes medtech DDS types into Foxglove-native types.

2. **Routing Service Adapter plugin** —
   `libfoxglove_ws_adapter.so` implementing
   [`rti::routing::adapter::AdapterPlugin`](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/api/routing_service/api_cpp/group__RTI__RoutingServiceAdapterModule.html)
   → `Connection` → `DynamicDataStreamWriter`.
   Output-only adapter that serializes transformed Foxglove
   DynamicData to a Foxglove Studio live WebSocket connection.

3. **Recording Service Storage plugin** —
   `libmedtech_mcap_storage.so` implementing
   [`rti::recording::storage::StorageWriter`](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/api/recording_service/api_cpp/group__RTI__RecordingServiceStorageModule.html)
   → `DynamicDataStorageStreamWriter`.
   Custom storage backend that writes transformed Foxglove-native
   samples to MCAP files.

#### Architecture (V2)

```
  Routing Service Pipeline (live):

  Procedure Domain (10)         Transformation Plugin     Adapter Plugin (WS)
  ┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
  │ RobotState           │──▶│ DDS → foxglove::*    │──▶│ DynamicData → WS   │──▶ Foxglove
  │ RobotFrameTransform  │   │ (strip @key, map    │   │ StreamWriter       │    Studio
  │ CameraFrame          │   │  fields, set ts)    │   │ write()            │    (live)
  │ ...                  │   └─────────────────────┘   └─────────────────────┘
  └─────────────────────┘
         │
         │
  Recording Service Pipeline (offline):
         │
         │                   Transformation Plugin     Storage Plugin (MCAP)
         │                   ┌─────────────────────┐   ┌─────────────────────┐
         └─────────────────▶│ DDS → foxglove::*    │──▶│ DynamicData → MCAP │──▶ .mcap
                            │ (same plugin lib)    │   │ StorageStreamWriter│    file
                            │                      │   │ store()            │
                            └─────────────────────┘   └─────────────────────┘
                                                              │
                                                    Foxglove Studio (offline)
```

1. **RTI Routing Service (live)** — reads medtech DDS data via the
   built-in DDS input adapter, applies the Transformation plugin to
   reshape it into Foxglove-native types, then delivers the
   transformed samples to the Adapter plugin's
   `DynamicDataStreamWriter::write()`, which serializes and forwards
   them over a Foxglove Studio live WebSocket connection.
2. **RTI Recording Service (offline)** — subscribes to medtech DDS
   data, applies the same Transformation plugin to produce
   Foxglove-native types, then delivers the transformed samples to
   the Storage plugin's `DynamicDataStorageStreamWriter::store()`,
   which writes them to MCAP files. Foxglove Studio opens the MCAP
   files directly for offline visualization and replay.

Both pipelines can run concurrently — Routing Service feeds live
visualization while Recording Service simultaneously captures the
same data to MCAP.

#### Plugin Design

**Transformation plugin** (`libmedtech_foxglove_transf.so`):
- One transformation class per target Foxglove type (e.g.,
  `ToCompressedImage`, `ToJointStates`, `ToFrameTransforms`,
  `ToPoseInFrame`) — selected via XML `<property>` on each route
- Uses generated C++ types on both sides for type-safe field
  mapping via `rti::core::xtypes::convert<T>()`
- Foxglove IDL types compiled from the
  [foxglove-sdk OMG IDL schemas](https://github.com/foxglove/foxglove-sdk/tree/main/schemas/omgidl/foxglove)
  and linked into the shared library
- Unit conversions applied during transformation where needed
  (e.g., millimeters → meters for position fields)

**Adapter plugin** (`libfoxglove_ws_adapter.so`):
- `FoxgloveWebSocketAdapter` (`AdapterPlugin`) →
  `FoxgloveWebSocketConnection` (`Connection`) →
  `FoxgloveWebSocketStreamWriter` (`DynamicDataStreamWriter`)
- Output-only — no input-side implementation needed
- `StreamWriter::write()` receives post-transformation Foxglove
  DynamicData and serializes it to the WebSocket connection
- `StreamInfo` metadata maps DDS stream identity to Foxglove channel
  advertisement
- Connection-level properties (`ws_uri`) configure the WebSocket
  endpoint; per-output properties (`channel`) map to Foxglove channels

**Storage plugin** (`libmedtech_mcap_storage.so`):
- `McapStorageWriter` (`StorageWriter`) →
  `McapDynamicDataWriter` (`DynamicDataStorageStreamWriter`)
- `StorageStreamWriter::store()` receives post-transformation
  Foxglove DynamicData + `SampleInfo` and writes MCAP records
- Each DDS stream maps to an MCAP channel/schema pair via
  `StreamInfo`
- Stores reception timestamp and valid-data flag for Replay
  compatibility

#### Routing Service XML Pattern (V2)

```xml
<!-- Plugin registration -->
<plugin_library name="MedtechPlugins">
    <transformation_plugin name="MedtechToFoxglove">
        <dll>medtech_foxglove_transf</dll>
        <create_function>
            MedtechToFoxglovePlugin_create_transformation_plugin
        </create_function>
    </transformation_plugin>
</plugin_library>

<adapter_library name="FoxgloveAdapterLib">
    <adapter_plugin name="FoxgloveWsAdapter">
        <dll>foxglove_ws_adapter</dll>
        <create_function>
            FoxgloveWebSocketAdapter_create_adapter_plugin
        </create_function>
    </adapter_plugin>
</adapter_library>
```

Each topic route reads from DDS, transforms, and writes to the
WebSocket adapter:

```xml
<domain_route name="ProcedureToFoxglove">
    <connection name="FoxgloveConnection"
                plugin_name="FoxgloveAdapterLib::FoxgloveWsAdapter">
        <property>
            <value>
                <element>
                    <name>ws_uri</name>
                    <value>ws://127.0.0.1:8765</value>
                </element>
            </value>
        </property>
    </connection>

    <session name="FoxgloveBridge">
        <route name="RobotStateToJointStates">
            <input connection="ProcedureParticipant">
                <topic_name>RobotState</topic_name>
                <registered_type_name>Surgery::RobotState</registered_type_name>
            </input>
            <output connection="FoxgloveConnection">
                <transformation plugin_name="MedtechPlugins::MedtechToFoxglove">
                    <property>
                        <value>
                            <element>
                                <name>mapping</name>
                                <value>joint_states</value>
                            </element>
                        </value>
                    </property>
                </transformation>
            </output>
        </route>
    </session>
</domain_route>
```

#### Recording Service XML Pattern (V2)

```xml
<plugin_library name="McapStorageLib">
    <storage_plugin name="McapStoragePlugin">
        <dll>medtech_mcap_storage</dll>
        <create_function>McapStorageWriter_get_storage_writer</create_function>
    </storage_plugin>
</plugin_library>

<recording_service name="McapRecorder">
    <storage>
        <plugin plugin_name="McapStorageLib::McapStoragePlugin">
            <property>
                <value>
                    <element>
                        <name>mcap.filename</name>
                        <value>recording.mcap</value>
                    </element>
                </value>
            </property>
        </plugin>
    </storage>
    <!-- domain/session/topic selection configured here -->
</recording_service>
```

The Transformation plugin is referenced in the Recording Service
configuration alongside the Storage plugin — the transformation
runs before data reaches the storage writer's `store()` method.

#### Deployment Modes

The plugin pipeline supports two independent deployment modes
that can be used separately or simultaneously:

- **Live visualization** — Routing Service pipeline: DDS input
  adapter → Transformation plugin → Adapter plugin (WebSocket
  `StreamWriter`) → Foxglove Studio live WebSocket connection.
  Real-time monitoring during a procedure.
- **Offline recording** — Recording Service pipeline: DDS
  subscriber → Transformation plugin → Storage plugin (MCAP
  `StorageStreamWriter`) → `.mcap` file. Foxglove Studio opens
  the MCAP for post-procedure review, training, incident
  investigation, and regression testing.

Both modes can run concurrently — Routing Service feeds live
visualization while Recording Service simultaneously captures the
same data to MCAP.

#### V2 Mappings (Tier 1)

| Route | Input Type | Output Type | Key Handling |
|-------|-----------|-------------|-------------|
| `RobotStateToJointStates` | `Surgery::RobotState` | `foxglove::JointStates` | Drop `robot_id`; map `joints[]` → `foxglove::JointState[]`; populate `timestamp` from `SampleInfo.source_timestamp` |
| `RobotStateToToolPose` | `Surgery::RobotState` | `foxglove::PoseInFrame` | Drop `robot_id`; extract `tool_tip_pose` → `foxglove::Pose`; set `frame_id` to `"tool_tip"` |
| `RobotFrameTransformToFoxglove` | `Surgery::RobotFrameTransform` | `foxglove::FrameTransforms` | Drop `robot_id`; map `transforms[]` → `foxglove::FrameTransform[]` adding `timestamp` from `SampleInfo.source_timestamp` per entry |
| `CameraFrameToCompressedImage` | `Imaging::CameraFrame` | `foxglove::CompressedImage` | Drop `camera_id`; copy `timestamp`, `frame_id`, `data`, `format` directly |

#### V2 Mappings (Tier 2)

Additional routes defined alongside Tier 2 IDL types:

| Route | Input Type | Output Type |
|-------|-----------|-------------|
| `CameraConfigToCalibration` | `Imaging::CameraCalibration` | `foxglove::CameraCalibration` |
| `ImageAnnotationsToFoxglove` | `Imaging::ImageAnnotations` | `foxglove::ImageAnnotations` |
| `CompressedVideoToFoxglove` | `Imaging::CompressedVideo` | `foxglove::CompressedVideo` |
| `SceneUpdateToFoxglove` | `Visualization::SceneUpdate` | `foxglove::SceneUpdate` |
| `LogMessageToFoxglove` | `Diagnostics::LogMessage` | `foxglove::Log` |
