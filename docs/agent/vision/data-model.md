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

All QoS is defined in shared XML profiles under `interfaces/qos/`. **No QoS is constructed or modified programmatically.** Modules use the **default QosProvider** to access profiles — they never call QoS setter APIs or construct custom `QosProvider` instances with explicit file paths.

- **C++:** `dds::core::QosProvider::Default()`
- **Python:** `dds.QosProvider.default`

This ensures:
- Writer/reader QoS compatibility is enforced by using the same named profile
- Tuning behavior (deadlines, durability depth, lifespan) is a configuration change, not a code change
- Future modules automatically get compatible QoS by referencing the same profiles

### QoS XML Loading via `NDDS_QOS_PROFILES`

QoS and domain library XML files are loaded at runtime via the `NDDS_QOS_PROFILES` environment variable. This variable lists all XML files in dependency order (Snippets before Patterns, Patterns before Topics, etc.). Applications do not hardcode XML file paths.

```bash
export NDDS_QOS_PROFILES="interfaces/qos/Snippets.xml;interfaces/qos/Patterns.xml;interfaces/qos/Topics.xml;interfaces/qos/Participants.xml;interfaces/domains/domains.xml"
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

QoS profiles use [topic filters](https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/connext_dds_professional/users_manual/users_manual/Topic_Filters.htm) to bind DataWriter/DataReader QoS to topics by name pattern. Applications use the topic-aware QoS APIs (`create_datawriter_with_profile`, `create_datareader_with_profile`, or `QosProvider` with topic name) so that the correct QoS is automatically resolved based on the topic being written/read. This decouples applications from knowing which QoS profile applies to which topic.

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
`<domain>` element in `domains.xml`. Every other document, code comment,
spec scenario, implementation step, and log message must reference a domain
by **name only** (e.g., "Procedure domain", "Hospital domain", "Observability domain").
If a domain ID changes, only this section and `domains.xml` require an update.

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
| `AlarmMessages` | `Monitoring::AlarmMessages` | `clinical` | `patient.id`, `source_device_id` | Active alarm set for a patient/device. |
| `DeviceTelemetry` | `Devices::DeviceTelemetry` | `clinical` | `device_id` | Generic device status (pump, ventilator, anesthesia). |
| `CameraFrame` | `Imaging::CameraFrame` | `operational` | `camera_id` | Endoscope/surgical camera feed (metadata + frame ref). Deadline-enforced (66 ms). |
| `ProcedureContext` | `Surgery::ProcedureContext` | `operational` | `procedure_id` | Hospital, room, bed, patient, surgeon, procedure type. TRANSIENT_LOCAL. |
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
| `AlarmMessages` | `Monitoring::AlarmMessages` | `patient.id`, `source_device_id` | Device-level alarms (Pathway 1). Bridged from Procedure domain (`clinical` tag) — not published directly on this domain. Consumed by the Dashboard alert feed. |
| `DeviceTelemetry` | `Devices::DeviceTelemetry` | `device_id` | Device status. Bridged from Procedure domain (`clinical` tag) — not published directly on this domain. Available on this domain in V1.0; not displayed by the V1.0 dashboard — reserved for V1.1+. |
| `RobotState` | `Surgery::RobotState` | `robot_id` | Read-only robot state for the Dashboard robot status panel. Bridged from Procedure domain (`control` tag) — not published directly on this domain. |
| `ClinicalAlert` | `ClinicalAlerts::ClinicalAlert` | `alert_id` | Risk-based alerts from ClinicalAlerts engine. |
| `RiskScore` | `ClinicalAlerts::RiskScore` | `patient.id`, `score_kind` | Computed risk scores (sepsis, hemorrhage, etc.). |
| `ResourceAvailability` | `Hospital::ResourceAvailability` | `resource_id` | *(V1.1)* OR, bed, equipment, and staff availability. Deferred to V1.1 — no simulator or dashboard panel in V1.0. |

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

### Domain 20 — Observability

Dedicated domain for **RTI Observability Framework** telemetry. Monitoring Library 2.0 creates a dedicated DomainParticipant on this domain in every process to publish metrics, logs, and security events. RTI Collector Service subscribes on this domain to aggregate telemetry and export it to Prometheus (metrics), Grafana Loki (logs), or an OpenTelemetry Collector.

**Why a separate domain:**

- **Performance** — high-volume telemetry (metrics emitted at configurable intervals, forwarded logs) cannot compete for transport resources with safety-critical control or clinical data on the Procedure domain.
- **Safety** — temporarily increasing telemetry verbosity for debugging must not affect discovery, deadline enforcement, or sample delivery on Domains 10 or 11.
- **Isolation** — Collector Service only needs to join the Observability domain. It does not participate in application domains, reducing its attack surface and resource footprint.

The Observability domain has **no domain tags** and **no application-defined topics**. Monitoring Library 2.0 creates its internal telemetry topics, publishers, and subscribers automatically — no XML topic or endpoint definitions are needed in `domains.xml`.

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
└── Participants.xml          # Discovery, transport, resource config for DomainParticipants
```

- **Snippets** define isolated QoS policy chunks. They do not inherit from other snippets or profiles.
- **Patterns** are generic base profiles that inherit from `BuiltinQosLib::Generic.Common` and compose snippets. They represent reusable data-flow archetypes. GUI downsampling variants (composing the `GuiSubsample` snippet) are defined here alongside their base patterns.
- **Topics** profiles inherit from a pattern and use `topic_filter` to bind QoS to specific topic names. Applications use topic-aware QoS APIs so the correct QoS resolves automatically. GUI-specific topic bindings (e.g., dashboard readers using a downsampled pattern) are defined here via topic filter.
- **Participants** profiles contain discovery, transport, and resource configuration. These are separate from data/topic profiles because they apply to DomainParticipants, not DataWriters/DataReaders.

### QoS Snippets (`Snippets.xml`)

Isolated, composable, no inheritance. Each enables/disables a single concern:

| Snippet | Applies To | What It Does |
|---------|-----------|--------------|
| `Reliable` | DW + DR | Sets RELIABLE reliability |
| `BestEffort` | DW + DR | Sets BEST_EFFORT reliability |
| `TransientLocal` | DW + DR | Sets TRANSIENT_LOCAL durability |
| `Volatile` | DW + DR | Sets VOLATILE durability |
| `KeepLast1` | DW + DR | KEEP_LAST history, depth 1 |
| `KeepLast4` | DW + DR | KEEP_LAST history, depth 4 |
| `KeepAll` | DW + DR | KEEP_ALL history |
| `ExclusiveOwnership` | DW + DR | Sets EXCLUSIVE_OWNERSHIP |
| `Liveliness2s` | DW + DR | Automatic liveliness, 2-second lease |
| `Deadline4ms` | DW + DR | Deadline period = 4 ms. Writer: detects publish stall. Reader: detects stream interruption. See *Deadline QoS* below. |
| `Deadline20ms` | DW + DR | Deadline period = 20 ms. Stream interruption detection for 100 Hz topics (2× nominal). |
| `Deadline40ms` | DW + DR | Deadline period = 40 ms. Stream interruption detection for 50 Hz topics (2× nominal). |
| `Deadline66ms` | DW + DR | Deadline period = 66 ms. Stream interruption detection for 30 Hz topics (2× nominal). |
| `Deadline2s` | DW + DR | Deadline period = 2 s. Periodic-snapshot interruption detection for 1 Hz topics (2× nominal). |
| `Lifespan20ms` | DW + DR | Lifespan duration = 20 ms. Samples older than 20 ms are discarded before delivery. |
| `Liveliness500ms` | DW + DR | Automatic liveliness, 500 ms lease. Tight writer-health detection for safety-critical write-on-change topics. |
| `GuiSubsample` | DR only | TIME_BASED_FILTER minimum_separation for GUI refresh rate |

### Data Pattern Base Profiles (`Patterns.xml`)

Generic profiles rooted on `BuiltinQosLib::Generic.Common`, composed from snippets. These are not used directly — they are inherited by topic-specific profiles.

| Pattern Profile | Base | Composed Snippets | Use Case |
|----------------|------|-------------------|----------|
| `State` | `BuiltinQosLib::Generic.Common` | `Reliable` + `TransientLocal` + `KeepLast1` + `Liveliness2s` | Latest-state data: vitals, device status, robot state, procedure context, alarms |
| `Command` | `BuiltinQosLib::Generic.Common` | `Reliable` + `Volatile` + `KeepLast1` | Commands where only the most recent matters, stale commands must not reach late joiners |
| `Stream` | `BuiltinQosLib::Generic.Common` | `BestEffort` + `KeepLast4` | High-rate streaming: waveforms, camera frames, operator input (operator input adds `Deadline4ms` + `Lifespan20ms` at the topic level) |
| `GuiState` | `State` | `GuiSubsample` | Downsampled state for GUI readers (~100–200 ms minimum separation) |
| `GuiStream` | `Stream` | `GuiSubsample` | Downsampled streaming for GUI readers (~33 ms / 30 Hz minimum separation) |

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
| `WaveformData` | Continuous Stream | 50 Hz (20 ms) | 40 ms | `Deadline40ms` |
| `CameraFrame` | Continuous Stream | 30 Hz (~33 ms) | 66 ms | `Deadline66ms` |
| `PatientVitals` | Periodic Snapshot | 1 Hz (1000 ms) | 2 s | `Deadline2s` |

Setting Deadline on **both** writer and reader enables diagnosability: writer-missed + reader-missed → publisher-side fault; writer-OK + reader-missed → transport/network issue.

**`OperatorInput` additional rationale:** Combined with a 20 ms Lifespan, the control loop never acts on stale input even if delivery is delayed but not missed.

### Liveliness QoS for Write-on-Change Topics

Write-on-change topics rely on DDS liveliness QoS — not Deadline — to detect writer health, because sample absence is the normal steady state. The general `Liveliness2s` snippet (2-second automatic lease, composed into the `State` pattern) covers most write-on-change topics.

**`SafetyInterlock` exception:** The safety interlock is a write-on-change topic on the `control` tag (Class C / Class III). Although its data pattern is event-driven, the consequence of an undetected writer failure is a robot operating without safety oversight. A tighter liveliness lease (500 ms via `Liveliness500ms`) provides faster detection of safety-system failure than the general 2-second lease — the robot controller can transition to a safe-stopped state within 500 ms of losing the safety writer, rather than waiting 2 seconds.

### Topic-Bound Profiles (`Topics.xml`)

These profiles use `topic_filter` to assign QoS by topic name. Applications use `create_datawriter_with_profile` / `create_datareader_with_profile` with the topic name, and Connext resolves the matching QoS automatically.

Example structure:

```xml
<qos_profile name="ProcedureTopics" base_name="Patterns::State">
    <!-- Default: State pattern QoS for unmatched topics in this profile -->

    <!-- Control topics (inherit State, but override for streaming where needed) -->
    <datawriter_qos topic_filter="OperatorInput">
        <base_name>
            <element>Snippets::BestEffort</element>
            <element>Snippets::KeepLast4</element>
            <element>Snippets::Deadline4ms</element>
            <element>Snippets::Lifespan20ms</element>
        </base_name>
    </datawriter_qos>
    <datareader_qos topic_filter="OperatorInput">
        <base_name>
            <element>Snippets::BestEffort</element>
            <element>Snippets::KeepLast4</element>
            <element>Snippets::Deadline4ms</element>
            <element>Snippets::Lifespan20ms</element>
        </base_name>
    </datareader_qos>

    <datawriter_qos topic_filter="RobotCommand">
        <base_name>
            <element>Snippets::Volatile</element>
        </base_name>
    </datawriter_qos>
    <datareader_qos topic_filter="RobotCommand">
        <base_name>
            <element>Snippets::Volatile</element>
        </base_name>
    </datareader_qos>

    <!-- RobotState: State pattern + Deadline20ms (100 Hz continuous stream) -->
    <datawriter_qos topic_filter="RobotState">
        <base_name>
            <element>Snippets::Deadline20ms</element>
        </base_name>
    </datawriter_qos>
    <datareader_qos topic_filter="RobotState">
        <base_name>
            <element>Snippets::Deadline20ms</element>
        </base_name>
    </datareader_qos>

    <!-- SafetyInterlock: State pattern + Liveliness500ms (write-on-change, tighter lease) -->
    <datawriter_qos topic_filter="SafetyInterlock">
        <base_name>
            <element>Snippets::Liveliness500ms</element>
        </base_name>
    </datawriter_qos>
    <datareader_qos topic_filter="SafetyInterlock">
        <base_name>
            <element>Snippets::Liveliness500ms</element>
        </base_name>
    </datareader_qos>

    <!-- PatientVitals: State pattern + Deadline2s (1 Hz periodic snapshot) -->
    <datawriter_qos topic_filter="PatientVitals">
        <base_name>
            <element>Snippets::Deadline2s</element>
        </base_name>
    </datawriter_qos>
    <datareader_qos topic_filter="PatientVitals">
        <base_name>
            <element>Snippets::Deadline2s</element>
        </base_name>
    </datareader_qos>

    <!-- Streaming topics -->
    <datawriter_qos topic_filter="WaveformData">
        <base_name>
            <element>Snippets::BestEffort</element>
            <element>Snippets::KeepLast4</element>
            <element>Snippets::Deadline40ms</element>
        </base_name>
    </datawriter_qos>
    <datareader_qos topic_filter="WaveformData">
        <base_name>
            <element>Snippets::BestEffort</element>
            <element>Snippets::KeepLast4</element>
            <element>Snippets::Deadline40ms</element>
        </base_name>
    </datareader_qos>

    <datawriter_qos topic_filter="CameraFrame">
        <base_name>
            <element>Snippets::BestEffort</element>
            <element>Snippets::KeepLast4</element>
            <element>Snippets::Deadline66ms</element>
        </base_name>
    </datawriter_qos>
    <datareader_qos topic_filter="CameraFrame">
        <base_name>
            <element>Snippets::BestEffort</element>
            <element>Snippets::KeepLast4</element>
            <element>Snippets::Deadline66ms</element>
        </base_name>
    </datareader_qos>
</qos_profile>
```

### Participant Configuration (`Participants.xml`)

Discovery, transport, and resource settings for DomainParticipants. Separated from data/topic QoS because these apply to the participant entity, not to writers/readers.

Defines profiles for:
- **Simulation transport** — shared memory disabled, UDPv4 only, explicit peers, no multicast
- **Discovery tuning** — peer lists per domain/network
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
│   └── monitoring.idl      # module Monitoring { PatientVitals, WaveformData, AlarmMessages }
├── imaging/
│   └── imaging.idl         # module Imaging { CameraFrame, ImageMetadata }
├── devices/
│   └── devices.idl         # module Devices { DeviceTelemetry, PumpStatus, VentilatorCommands }
├── clinical_alerts/
│   └── clinical_alerts.idl             # module ClinicalAlerts { ClinicalAlert, RiskScore }
└── hospital/
    └── hospital.idl        # module Hospital { ResourceAvailability }
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
    //           (Time_t, EntityIdentity, CartesianPosition, AlarmEntry, ImageMetadata)
    //           are embedded by the parent type and do not need separate registration.
    rti::domain::register_type<Surgery::RobotCommand>("Surgery::RobotCommand");
    rti::domain::register_type<Surgery::RobotState>("Surgery::RobotState");
    rti::domain::register_type<Surgery::SafetyInterlock>("Surgery::SafetyInterlock");
    rti::domain::register_type<Surgery::OperatorInput>("Surgery::OperatorInput");
    rti::domain::register_type<Surgery::ProcedureContext>("Surgery::ProcedureContext");
    rti::domain::register_type<Surgery::ProcedureStatus>("Surgery::ProcedureStatus");
    rti::domain::register_type<Monitoring::PatientVitals>("Monitoring::PatientVitals");
    rti::domain::register_type<Monitoring::WaveformData>("Monitoring::WaveformData");
    rti::domain::register_type<Monitoring::AlarmMessages>("Monitoring::AlarmMessages");
    rti::domain::register_type<Imaging::CameraFrame>("Imaging::CameraFrame");
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
from monitoring.Monitoring import PatientVitals, WaveformData, AlarmMessages
from imaging.Imaging import CameraFrame
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
    #           (Time_t, EntityIdentity, CartesianPosition, AlarmEntry, ImageMetadata)
    #           are embedded by the parent type and do not need separate registration.
    dds.DomainParticipant.register_idl_type(RobotCommand,           "Surgery::RobotCommand")
    dds.DomainParticipant.register_idl_type(RobotState,             "Surgery::RobotState")
    dds.DomainParticipant.register_idl_type(SafetyInterlock,        "Surgery::SafetyInterlock")
    dds.DomainParticipant.register_idl_type(OperatorInput,          "Surgery::OperatorInput")
    dds.DomainParticipant.register_idl_type(ProcedureContext,       "Surgery::ProcedureContext")
    dds.DomainParticipant.register_idl_type(ProcedureStatus,        "Surgery::ProcedureStatus")
    dds.DomainParticipant.register_idl_type(PatientVitals,          "Monitoring::PatientVitals")
    dds.DomainParticipant.register_idl_type(WaveformData,           "Monitoring::WaveformData")
    dds.DomainParticipant.register_idl_type(AlarmMessages,          "Monitoring::AlarmMessages")
    dds.DomainParticipant.register_idl_type(CameraFrame,            "Imaging::CameraFrame")
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
| `MAX_ID_LENGTH` | `long` | 64 | Bound for all entity identifier strings |
| `MAX_NAME_LENGTH` | `long` | 128 | Bound for human-readable names |
| `MAX_DESCRIPTION_LENGTH` | `long` | 512 | Bound for free-text description and rationale fields |
| `MAX_WAVEFORM_SAMPLES` | `long` | 64 | Maximum samples per waveform block |
| `MAX_ALARM_COUNT` | `long` | 16 | Maximum active alarms per alarm message |
| `MAX_JOINT_COUNT` | `long` | 7 | Maximum robot arm joint count |

#### Aliases

| Alias | Underlying Type | Usage |
|-------|-----------------|-------|
| `EntityId` | `string<MAX_ID_LENGTH>` | Reusable bounded identifier type for patients, devices, robots, procedures, operators, cameras, alerts |

#### `Common::Time_t`

Standard timestamp for all sample time-stamping. `@appendable`.

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `seconds` | `int32` | — | Seconds since epoch |
| `nanoseconds` | `uint32` | — | Sub-second nanoseconds |

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

**`Surgery::CartesianPosition`** — `@nested` `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `x` | `double` | — | X position (mm) |
| `y` | `double` | — | Y position (mm) |
| `z` | `double` | — | Z position (mm) |

#### `Surgery::RobotCommand`

Topic: `RobotCommand` | Domain Tag: `control` | Pattern: `Command`
| `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `robot_id` | `Common::EntityId` | @key | Target robot |
| `command_id` | `int32` | @key | Unique command sequence number |
| `target_position` | `CartesianPosition` | — | Commanded tool-tip target |
| `timestamp` | `Common::Time_t` | — | Command issue time |

#### `Surgery::RobotState`

Topic: `RobotState` | Domain Tag: `control` | Pattern: `State`
| `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `robot_id` | `Common::EntityId` | @key | Robot instance identifier |
| `joint_positions` | `sequence<double, Common::MAX_JOINT_COUNT>` | — | Current joint angles (radians) |
| `tool_tip_position` | `CartesianPosition` | — | Computed tool-tip position |
| `operational_mode` | `RobotMode` | — | Current robot mode |
| `error_state` | `int32` | — | Error code (0 = no error) |
| `timestamp` | `Common::Time_t` | — | State sample time |

#### `Surgery::SafetyInterlock`

Topic: `SafetyInterlock` | Domain Tag: `control` | Pattern: `State`
| `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `robot_id` | `Common::EntityId` | @key | Robot being interlocked |
| `interlock_active` | `boolean` | — | `true` = interlock engaged, robot must stop |
| `reason` | `string<Common::MAX_DESCRIPTION_LENGTH>` | — | Human-readable interlock reason |
| `timestamp` | `Common::Time_t` | — | Interlock event time |

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
| `timestamp` | `Common::Time_t` | — | Input sample time |

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
| `timestamp` | `Common::Time_t` | — | Status update time |

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

#### Helper Structs

**`Monitoring::AlarmEntry`** — `@nested` `@appendable`. A single
alarm within an `AlarmMessages` sample.

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `alarm_id` | `Common::EntityId` | — | Unique alarm instance identifier |
| `severity` | `AlarmSeverity` | — | Alarm severity level |
| `state` | `AlarmState` | — | Current alarm state |
| `alarm_code` | `string<64>` | — | Machine-readable alarm code |
| `message` | `string<Common::MAX_DESCRIPTION_LENGTH>` | — | Human-readable alarm description |
| `onset_time` | `Common::Time_t` | — | When the alarm condition first occurred |

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
| `timestamp` | `Common::Time_t` | — | Measurement time |

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
| `timestamp` | `Common::Time_t` | — | Timestamp of the first sample in this block |

#### `Monitoring::AlarmMessages`

Topic: `AlarmMessages` | Domain Tag: `clinical` | Pattern: `State`
| `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `patient` | `Common::EntityIdentity` | @key | Patient identity (effective key: `patient.id`) |
| `source_device_id` | `Common::EntityId` | @key | Device generating alarms |
| `alarms` | `sequence<AlarmEntry, Common::MAX_ALARM_COUNT>` | — | Current active alarm set for this patient/device |
| `timestamp` | `Common::Time_t` | — | Alarm evaluation time |

---

### Module: Imaging (`imaging/imaging.idl`)

Dependencies: `#include "common/common.idl"`

#### Helper Structs

**`Imaging::ImageMetadata`** — `@nested` `@appendable`. Describes
properties of a captured frame.

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `width` | `uint32` | — | Frame width (pixels) |
| `height` | `uint32` | — | Frame height (pixels) |
| `encoding` | `string<32>` | — | Pixel format (e.g., "RGB8", "YUV422") |
| `frame_size_bytes` | `uint32` | — | Size of the raw image data |

#### `Imaging::CameraFrame`

Topic: `CameraFrame` | Domain Tag: `operational` | Pattern: `Stream`
| `@appendable`

| Member | Type | Key | Notes |
|--------|------|-----|-------|
| `camera_id` | `Common::EntityId` | @key | Camera source identifier |
| `frame_sequence_number` | `uint32` | — | Monotonically increasing frame counter |
| `metadata` | `ImageMetadata` | — | Frame resolution and encoding |
| `image_reference` | `string<Common::MAX_DESCRIPTION_LENGTH>` | — | URI or shared-memory handle to raw image data |
| `timestamp` | `Common::Time_t` | — | Frame capture time |

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
| `timestamp` | `Common::Time_t` | — | Telemetry sample time |

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
| `timestamp` | `Common::Time_t` | — | Source timestamp from the device gateway — not DDS middleware time |

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
| `timestamp` | `Common::Time_t` | — | Command issue time — used for command staleness detection at the gateway |

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
| `timestamp` | `Common::Time_t` | — | Computation time |

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
| `timestamp` | `Common::Time_t` | — | Alert generation time |

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
| `timestamp` | `Common::Time_t` | — | Last status update time |

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
