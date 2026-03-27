# DDS Consistency Contract

This document is the **single operational guide** for correctly using RTI
Connext DDS Professional 7.6.0 in the medtech suite. It consolidates the
DDS usage rules, initialization sequences, canonical code patterns, and
anti-patterns that are distributed across the vision, spec, and workflow
documents into one place.

**Role of this document:** This is the "how to use Connext correctly"
reference. It does not replace the authoritative design documents — it
cross-references them. The authoritative sources remain:

| Concern | Authoritative Document |
|---------|----------------------|
| QoS architecture (Snippet/Pattern/Topic/Participant hierarchy) | [data-model.md](data-model.md) |
| Domain layout, domain tags, partitions, Routing Service topology | [system-architecture.md](system-architecture.md) |
| Domain definitions, topic assignments, publication models | [data-model.md](data-model.md) |
| Technology stack, build integration, Connext version | [technology.md](technology.md) |
| API naming conventions, generated code patterns | [coding-standards.md](coding-standards.md) |
| Prohibited actions, quality gates | [../workflow.md](../workflow.md) §4, §7 |
| GWT behavioral scenarios | [../spec/common-behaviors.md](../spec/common-behaviors.md) |

**Domain knowledge authority:** When this document or any planning document
leaves an implementation detail to the agent's discretion, consult
**`rti-chatbot-mcp`** — the RTI Connext domain expert MCP tool. It provides
API usage guidance, QoS semantics, transport configuration, and
troubleshooting expertise backed by RTI documentation.

> Every code pattern in this document was validated against `rti-chatbot-mcp`
> guidance for RTI Connext Professional 7.6.0.

---

## 1. Initialization Sequence

Every application — C++ or Python — must execute these steps in this exact
order before performing any DDS I/O. The underlying operations are defined
in [data-model.md — Pre-Participant Initialization](data-model.md).

```
1. Call the shared medtech::initialize_connext() function
2. Create DomainParticipant from XML configuration
3. Set participant-level partition (before enabling entities)
4. Enable the participant (mandatory — discovery does not begin until enable)
```

### Step 1 — Shared Initialization (`initialize_connext()`)

All applications must call the shared initialization function **before any
DomainParticipant is created**. This function performs two operations
internally:

1. Sets the XTypes compliance mask (`accept_unknown_enum_value` bit) — the
   sole approved programmatic QoS exception (no XML equivalent).
2. Registers every IDL-generated topic type with the factory so that
   `create_participant_from_config()` can resolve `<register_type>` entries.

The function is **idempotent** — safe to call multiple times per process.
C++ uses `std::call_once`; Python uses a module-level guard flag.

**C++ — implementation (`modules/shared/medtech_dds_init/include/medtech/dds_init.hpp`):**

```cpp
#include <rti/config/Compliance.hpp>
#include <rti/domain/PluginSupport.hpp>
// ... generated type includes ...

namespace medtech {

inline void initialize_connext()
{
    static std::once_flag flag;
    std::call_once(flag, []() {
        // 1. XTypes compliance: accept unknown enum values
        rti::config::compliance::set_xtypes_mask(
            rti::config::compliance::get_xtypes_mask()
            | rti::config::compliance::XTypesMask::accept_unknown_enum_value());

        // 2. Register every compiled type referenced by XML <register_type>
        rti::domain::register_type<Surgery::RobotCommand>("Surgery::RobotCommand");
        rti::domain::register_type<Surgery::RobotState>("Surgery::RobotState");
        // ... all topic types — see dds_init.hpp for full list ...
    });
}

}  // namespace medtech
```

**Python — implementation (`modules/surgical-procedure/dds_init.py`):**

```python
import rti.connextdds as dds
import surgery, monitoring, imaging, devices  # generated modules

_initialized = False

def initialize_connext() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True

    # 1. XTypes compliance: accept unknown enum values
    dds.compliance.set_xtypes_mask(
        dds.compliance.get_xtypes_mask()
        | dds.compliance.XTypesMask.ACCEPT_UNKNOWN_ENUM_VALUE_BIT
    )

    # 2. Register every compiled type referenced by XML <register_type>
    dds.DomainParticipant.register_idl_type(
        surgery.Surgery.RobotCommand, "Surgery::RobotCommand")
    dds.DomainParticipant.register_idl_type(
        surgery.Surgery.RobotState, "Surgery::RobotState")
    # ... all topic types — see dds_init.py for full list ...
```

**Call site (both languages):**

```cpp
// C++
#include <medtech/dds_init.hpp>

int main() {
    medtech::initialize_connext();
    // ... create participants
}
```

```python
# Python
from dds_init import initialize_connext

initialize_connext()
# ... create participants
```

> **Structural note:** The Python `dds_init.py` currently resides in
> `modules/surgical-procedure/`. It should be relocated to a shared
> location aligned with the C++ structure (e.g.,
> `modules/shared/medtech_dds_init/`) so that all Python modules import
> from one common package. This relocation is an implementation task.

See [data-model.md — Pre-Participant Initialization](data-model.md) for
the full type registration list, the authoritative XTypes bit value,
and the sentinel-first enum convention this enables.

### Step 2 — Create Participant from XML Configuration

All participants are created from XML configuration using
`create_participant_from_config()`. XML files are loaded via the
`NDDS_QOS_PROFILES` environment variable (see §2) — applications do not
hardcode XML file paths.

#### Entity Name Constants (`app_names.idl`)

Participant configuration names (passed to `create_participant_from_config()`)
and entity lookup names (passed to `find_datawriter_by_name()` /
`find_datareader_by_name()`) must be defined as `const string` declarations
in a dedicated IDL file — `interfaces/idl/app_names.idl`. `rtiddsgen`
generates language-specific constants from these declarations:

- **C++ (IDL4_CPP):** `std::string_view` constants
- **Python:** module-level constants

Application code references the generated constants — never raw string
literals. This eliminates typo-induced runtime lookup failures and keeps
name definitions synchronized with the XML configuration.

**Rule:** Every participant, DataWriter, and DataReader name defined in an
XML participant configuration file **must** have a corresponding `const
string` entry in `app_names.idl`.

**IDL structure** (`interfaces/idl/app_names.idl`):

```idl
// Entity name constants for XML Application Creation.
// Each participant library XML gets its own nested module.

module MedtechEntityNames {

    // --- SurgicalParticipants library ---
    module SurgicalParticipants {

        // Participant config names — create_participant_from_config()
        const string OPERATIONAL_PUB      = "SurgicalParticipants::OperationalPub";
        const string CONTROL_ROBOT        = "SurgicalParticipants::ControlRobot";
        const string CONTROL_OPERATOR     = "SurgicalParticipants::ControlOperator";
        const string CLINICAL_MONITOR     = "SurgicalParticipants::ClinicalMonitor";
        const string CLINICAL_DEVICE_GW   = "SurgicalParticipants::ClinicalDeviceGateway";
        const string CONTROL_DIGITAL_TWIN = "SurgicalParticipants::ControlDigitalTwin";

        // Writer names — find_datawriter_by_name()
        const string ROBOT_STATE_WRITER        = "RobotPublisher::RobotStateWriter";
        const string PROCEDURE_CONTEXT_WRITER  = "OperationalPublisher::ProcedureContextWriter";
        const string PROCEDURE_STATUS_WRITER   = "OperationalPublisher::ProcedureStatusWriter";
        const string CAMERA_FRAME_WRITER       = "OperationalPublisher::CameraFrameWriter";
        const string CAMERA_CONFIG_WRITER      = "OperationalPublisher::CameraConfigWriter";
        const string PATIENT_VITALS_WRITER     = "MonitorPublisher::PatientVitalsWriter";
        const string WAVEFORM_DATA_WRITER      = "MonitorPublisher::WaveformDataWriter";
        const string ALARM_MESSAGES_WRITER     = "MonitorPublisher::AlarmMessagesWriter";
        const string DEVICE_TELEMETRY_WRITER   = "DevicePublisher::DeviceTelemetryWriter";
        const string OPERATOR_INPUT_WRITER     = "OperatorPublisher::OperatorInputWriter";
        const string ROBOT_COMMAND_WRITER      = "OperatorPublisher::RobotCommandWriter";
        const string SAFETY_INTERLOCK_WRITER   = "OperatorPublisher::SafetyInterlockWriter";

        // Reader names — find_datareader_by_name()
        const string ROBOT_COMMAND_READER      = "RobotSubscriber::RobotCommandReader";
        const string OPERATOR_INPUT_READER     = "RobotSubscriber::OperatorInputReader";
        const string SAFETY_INTERLOCK_READER   = "RobotSubscriber::SafetyInterlockReader";
        const string ROBOT_STATE_READER        = "OperatorSubscriber::RobotStateReader";
        const string PROCEDURE_CONTEXT_READER  = "OperationalSubscriber::ProcedureContextReader";
        const string PROCEDURE_STATUS_READER   = "OperationalSubscriber::ProcedureStatusReader";
        const string PATIENT_VITALS_READER     = "MonitorSubscriber::PatientVitalsReader";
        // ... one constant per configured reader
    };

    // --- Future participant libraries get their own module ---
    // module HospitalParticipants { ... };
};
```

> **`rti-chatbot-mcp` note:** IDL `const string` is a supported construct
> in RTI Connext 7.6.0. With `-standard IDL4_CPP`, string constants
> generate as `std::string_view` on C++17-capable platforms. Python
> generates module-level constants. Using IDL for these names is a
> project-level best practice — not a documented RTI pattern — adopted
> to single-source entity names across C++ and Python.

**C++ (Modern C++ API):**

```cpp
#include <app_names/MedtechEntityNames/SurgicalParticipants.hpp>  // generated
namespace names = MedtechEntityNames::SurgicalParticipants;

auto participant = dds::core::QosProvider::Default()
    .create_participant_from_config(names::CONTROL_ROBOT);
```

**Python:**

```python
from app_names.MedtechEntityNames import SurgicalParticipants as names

participant = dds.QosProvider.default.create_participant_from_config(
    names.CONTROL_ROBOT
)
```

### Step 3 — Set Participant Partition

Partition strings are context-dependent (which room, which procedure) and
are set programmatically. This is the second approved programmatic QoS
exception.

**Partition must be set before entities are enabled** to avoid triggering
re-discovery. If the participant is created with `autoenable_created_entities`
disabled in XML, set the partition before calling `enable()`. If entities are
auto-enabled, set the partition immediately after
`create_participant_from_config()` — the brief discovery window before the
partition is applied is acceptable for startup but should be minimized.

Partition can also be **updated at runtime** if the application's context
changes (e.g., moving to a different procedure). Updating the partition on a
live participant triggers re-discovery with the new partition value.

**C++ (Modern C++ API):**

```cpp
auto qos = participant.qos();
qos << dds::core::policy::Partition(
    dds::core::StringSeq({"room/OR-3/procedure/proc-001"}));
participant.qos(qos);
participant.enable();
```

**Python:**

```python
qos = participant.qos
qos.partition.name = ["room/OR-3/procedure/proc-001"]
participant.qos = qos
participant.enable()
```

The partition format is `room/<room_id>/procedure/<procedure_id>`. See
[system-architecture.md — Partition Strategy](system-architecture.md)
for wildcard matching rules.

---

## 2. QoS Provider Usage

All QoS is defined in shared XML profiles under `interfaces/qos/`. The
QoS architecture (Snippets → Patterns → TopicProfiles → Topics) is defined
in [data-model.md — QoS Architecture](data-model.md).

### `NDDS_QOS_PROFILES` Environment Variable

The default QosProvider loads QoS and domain library XML at runtime from
the `NDDS_QOS_PROFILES` environment variable. This variable lists all XML
files in dependency order. It must be set before any Connext API call:

```bash
export NDDS_QOS_PROFILES="interfaces/qos/Snippets.xml;interfaces/qos/Patterns.xml;interfaces/qos/Topics.xml;interfaces/qos/Participants.xml;interfaces/domains/Domains.xml"
```

`setup.bash` and Docker Compose set this automatically. If
`NDDS_QOS_PROFILES` is missing or incomplete, the default QosProvider
will not find the project's profiles and participant creation will fail.

### Rules

1. **Always use the default QosProvider.** Never construct a custom
   `QosProvider` with explicit file paths.
2. **Never call QoS setter APIs.** No `qos << policy` except for the
   two approved exceptions (compliance mask, partition).
3. **Prefer XML-defined entities.** Applications should define their
   DDS entities (participants, publishers, subscribers, writers, readers)
   in XML participant configuration and create them via
   `create_participant_from_config()`. Entities created this way already
   have the correct QoS applied from the XML — no code-side QoS lookup
   is needed.

### Topic-Aware QoS Resolution (Tests and Tools Only)

When creating DataWriters or DataReaders **in code** — which should only
be necessary in tests and developer tools, not in application modules —
use topic-aware QoS resolution so that Connext resolves the correct QoS
via topic filters automatically.

**C++ (Modern C++ API):**

```cpp
auto provider = dds::core::QosProvider::Default();

// Resolve QoS for a specific topic via topic filters in Topics.xml
auto writer_qos = provider.datawriter_qos_w_topic_name("PatientVitals");
auto reader_qos = provider.datareader_qos_w_topic_name("PatientVitals");
```

**Python:**

```python
provider = dds.QosProvider.default

writer_qos = provider.get_topic_datawriter_qos("PatientVitals")
reader_qos = provider.get_topic_datareader_qos("PatientVitals")
```

> **`rti-chatbot-mcp` note:** The Modern C++ API does not have a direct
> `create_datawriter_with_profile()` method. Instead, retrieve QoS from
> the provider and pass it to the DataWriter/DataReader constructor. This
> is the idiomatic pattern for Connext 7.6.0 Modern C++.

> **Application modules** should not need these APIs. If an application
> creates writers/readers via `create_participant_from_config()`, they
> are configured entirely from XML — including QoS, topic binding, and
> entity names. Writers and readers are then looked up by name using
> `find_datawriter()` / `find_datareader()`, passing the generated
> constants from `app_names.idl` (see §1 Step 2).

---

## 3. Application Architecture Pattern

Application and service classes must encapsulate DDS entities behind a
**domain-meaningful interface**. Writers, readers, participants, and DDS
types should not appear in the class's public API. Callers interact with
domain concepts (commands, state, telemetry) — never with DDS primitives.

This is the concrete realization of the "DDS Code Separation" principle in
[coding-standards.md](coding-standards.md). The patterns in §4.1–§4.4
show the **internal** implementation details within this architecture.

### Structural Rules

1. **The class owns its DDS entities privately.** Participant, writers, and
   readers are private members, created/looked up in the constructor from
   the XML configuration name. Callers never see or pass DDS entity
   references.

2. **The constructor accepts domain configuration, not DDS entities.**
   Parameters are domain-level: room ID, procedure ID, participant config
   name. The constructor calls `initialize_connext()`, creates the
   participant from XML config, sets the partition, and looks up
   writers/readers by their XML entity names.

3. **State mutations drive writes internally.** Public setters (e.g.,
   `set_telemetry()`, `update_status()`) mutate internal state and write
   the applicable sample(s) through private writer(s). The caller does not
   manage writer references or track published state.

4. **Incoming data is surfaced via domain callbacks or signals.** Readers
   are wired to internal handlers (via `AsyncWaitSet` / `asyncio`) that
   update internal state and invoke domain-level callbacks or Qt signals.
   The callback signature uses domain types, not `dds::sub::LoanedSamples`.

5. **Lifecycle is scoped to the class.** `start()` / `run()` first calls
   `participant.enable()` to activate the participant and all its contained
   entities, then starts the `AsyncWaitSet` or async event loop.
   If the participant is already enabled the call is a safe no-op.
   No explicit teardown method is needed — DDS entities are
   reference types (similar to `std::shared_ptr`) that automatically
   destroy the underlying middleware object when the last reference is
   released. When the owning class is destroyed, its member entities go
   out of scope and clean up automatically. When the service class itself
   is heap-allocated, manage it with `std::unique_ptr` (or `std::shared_ptr`
   if shared ownership is required) so that destruction — and therefore DDS
   cleanup — is deterministic. See
   [coding-standards.md — Modern C++17 Idioms](coding-standards.md).

6. **Shutdown sequencing belongs in the destructor.** The class destructor
   must tear down resources in this order:
   1. Signal worker threads / async tasks to stop (e.g., set
      `std::atomic<bool> running_` to `false`; cancel async tasks).
   2. Join worker threads / await task completion.
   3. Call `aws_.stop()` on every owned `AsyncWaitSet`. `stop()` blocks
      until async dispatch completes and no handlers are in flight.
      This step is **mandatory** — the `AsyncWaitSet` destructor is not
      documented as performing a synchronous stop/join.
   4. Let remaining member entities (conditions, writers, readers,
      participant) destruct via normal member destruction order.
   Do not provide a separate public teardown method — a
   single destruction path avoids double-cleanup bugs and ensures cleanup
   is deterministic regardless of how the object’s lifetime ends.

   **Member declaration order matters.** Declare DDS entities (participant,
   readers, writers, conditions) **before** the `AsyncWaitSet` so that
   reverse destruction order destroys the `AsyncWaitSet` first as a
   defensive layer. The explicit `stop()` in the destructor is the
   primary shutdown mechanism; declaration order is the backup.

### C++ Example — Service Class

```cpp
#include <app_names/MedtechEntityNames/SurgicalParticipants.hpp>  // generated
namespace names = MedtechEntityNames::SurgicalParticipants;

class RobotController {
public:
    RobotController(const std::string& room_id, const std::string& procedure_id)
    {
        medtech::initialize_connext();

        participant_ = dds::core::QosProvider::Default()
            .create_participant_from_config(names::CONTROL_ROBOT);

        auto qos = participant_.qos();
        qos << dds::core::policy::Partition(dds::core::StringSeq(
            {"room/" + room_id + "/procedure/" + procedure_id}));
        participant_.qos(qos);

        // Look up writers/readers by generated name constant — no typo risk
        command_reader_ = rti::sub::find_datareader_by_name<
            dds::sub::DataReader<Surgery::RobotCommand>>(
                participant_, names::ROBOT_COMMAND_READER);
        state_writer_ = rti::pub::find_datawriter_by_name<
            dds::pub::DataWriter<Surgery::RobotState>>(
                participant_, names::ROBOT_STATE_WRITER);

        // Wire reader to internal handler via AsyncWaitSet
        read_condition_ = dds::sub::cond::ReadCondition(
            command_reader_, dds::sub::status::DataState::any(),
            [this]() { on_command_received_(); });
        aws_ += read_condition_;
    }

    ~RobotController()
    {
        aws_.stop();  // block until no handlers are in flight
        // members destruct in reverse declaration order:
        // aws_ → read_condition_ → state_writer_ → command_reader_ → participant_
    }

    // Domain interface — no DDS types exposed
    void start() {
        participant_.enable();  // no-op if already enabled
        aws_.start();
    }

    void set_on_command(std::function<void(const Surgery::RobotCommand&)> cb) {
        on_command_ = std::move(cb);
    }

private:
    void on_command_received_() {
        for (const auto& sample : command_reader_.take()) {
            if (sample.info().valid() && on_command_) {
                on_command_(sample.data());
            }
        }
    }

    void publish_state_(const Surgery::RobotState& state) {
        state_writer_.write(state);
    }

    // Declaration order: DDS entities first, AsyncWaitSet last.
    // Reverse destruction order ensures aws_ is destroyed before entities.
    dds::domain::DomainParticipant participant_{nullptr};
    dds::sub::DataReader<Surgery::RobotCommand> command_reader_{nullptr};
    dds::pub::DataWriter<Surgery::RobotState> state_writer_{nullptr};
    dds::sub::cond::ReadCondition read_condition_{nullptr};
    rti::core::cond::AsyncWaitSet aws_;  // destroyed first (declared last)
    std::function<void(const Surgery::RobotCommand&)> on_command_;
};
```

### Python Example — Service Class

```python
from app_names.MedtechEntityNames import SurgicalParticipants as names

class BedsideMonitor:
    def __init__(self, room_id: str, procedure_id: str) -> None:
        initialize_connext()

        self._participant = dds.QosProvider.default.create_participant_from_config(
            names.CLINICAL_MONITOR
        )
        qos = self._participant.qos
        qos.partition.name = [f"room/{room_id}/procedure/{procedure_id}"]
        self._participant.qos = qos

        # Look up writers by generated name constant — no typo risk
        self._vitals_writer = dds.DataWriter(
            self._participant.find_datawriter(names.PATIENT_VITALS_WRITER))
        self._alarm_writer = dds.DataWriter(
            self._participant.find_datawriter(names.ALARM_MESSAGES_WRITER))

        self._last_vitals: monitoring.Monitoring.PatientVitals | None = None

    # Domain interface — no DDS types exposed to callers
    def update_vitals(self, vitals: monitoring.Monitoring.PatientVitals) -> None:
        self._vitals_writer.write(vitals)
        self._last_vitals = vitals

    def raise_alarm(self, alarm: monitoring.Monitoring.AlarmMessage) -> None:
        self._alarm_writer.write(alarm)

    async def run(self) -> None:
        self._participant.enable()  # no-op if already enabled
        await asyncio.gather(
            self._publish_vitals_loop(),
            # ... other async tasks
        )

    async def _publish_vitals_loop(self) -> None:
        while True:
            vitals = self._sample_sensors()  # application-specific
            self.update_vitals(vitals)
            await asyncio.sleep(1.0)  # 1 Hz periodic snapshot
```

> **Key takeaway:** If a caller needs to `import rti.connextdds` or
> `#include <dds/dds.hpp>` to use your class's public API, the DDS
> boundary is leaking. The generated IDL types (e.g.,
> `Surgery::RobotCommand`) are domain types and are acceptable in the
> public interface — DDS entity types (`DataWriter`, `DataReader`,
> `DomainParticipant`) are not.

---

## 4. Data Access Patterns (Internal Implementation)

This section defines the canonical read/write patterns used **inside**
application classes (§3). The publication model for every topic is defined
in [data-model.md — Publication Model](data-model.md).

### 4.1 Continuous-Stream / Periodic-Snapshot (Fixed-Rate Write)

Topics: `OperatorInput`, `RobotState`, `WaveformData`, `CameraFrame`,
`PatientVitals`, `RobotFrameTransform`.

The publisher calls `write()` at a fixed rate regardless of whether the
value changed. DDS Deadline QoS detects stream interruption.

**C++ — dedicated publisher thread (primary pattern):**

When the periodic publish loop runs on its own dedicated thread, call
`write()` directly from that thread. No `AsyncWaitSet` or
`GuardCondition` indirection is needed — the dedicated thread is already
off the main thread, and writing directly avoids unnecessary context
switching.

```cpp
void publish_loop(
    dds::pub::DataWriter<Surgery::RobotState>& writer,
    std::atomic<bool>& running)
{
    Surgery::RobotState sample{};
    while (running) {
        sample = read_sensor();      // application-specific
        writer.write(sample);
        std::this_thread::sleep_for(std::chrono::milliseconds(10)); // 100 Hz
    }
}

// Launch from main after entities are enabled:
std::thread pub_thread(publish_loop, std::ref(writer), std::ref(running));
```

**C++ — GuardCondition + AsyncWaitSet (event delegation only):**

Use this pattern only when a **non-periodic event** originates on a
thread that should not perform DDS I/O directly (e.g., the main thread
or a UI thread) and the write must be delegated to an `AsyncWaitSet`
thread. **Do not use `GuardCondition` as a periodic timer mechanism** —
use standard language threading primitives (dedicated thread +
`sleep_for`, `asyncio.sleep`, etc.) for periodic writes.

`GuardCondition` is a **wake-up signal**, not a counted event queue.
Multiple `trigger_value(true)` calls before the handler runs may
coalesce into a single dispatch. If the delegated work must not be
lost, back the condition with a thread-safe queue:

```cpp
rti::core::cond::AsyncWaitSet aws;
dds::core::cond::GuardCondition event_signal;
std::mutex queue_mtx;
std::queue<Surgery::RobotCommand> pending;

event_signal.handler([&]() {
    std::lock_guard lock(queue_mtx);
    while (!pending.empty()) {
        writer.write(pending.front());
        pending.pop();
    }
});

aws += event_signal;
aws.start();

// Producer on a non-DDS thread:
{
    std::lock_guard lock(queue_mtx);
    pending.push(command);
}
event_signal.trigger_value(true);
event_signal.trigger_value(false);
```

**Python — asyncio:**

```python
async def publish_fixed_rate(writer: dds.DataWriter) -> None:
    while True:
        sample = read_sensor()   # application-specific
        writer.write(sample)
        await asyncio.sleep(0.01)  # 100 Hz
```

### 4.2 Write-on-Change (Event-Driven Write)

Topics: `ProcedureContext`, `ProcedureStatus`, `AlarmMessages`,
`DeviceTelemetry`, `SafetyInterlock`, `RobotCommand`, `CameraConfig`,
`ClinicalAlert`, `RiskScore`, `ResourceAvailability`.

The publisher calls `write()` only when the logical state changes. Sample
absence is normal — writer health is detected via liveliness QoS, not
Deadline.

**Design principle:** Write-on-change publishing should be managed by the
application's state machine, not by external diffing logic. The class that
owns the DDS writer also owns the internal state. When a state setter is
called and the value changes, the class writes the applicable sample(s)
through its owned writer(s). Callers should not need to manage writer
references or track last-published state externally.

**C++ — state-machine-driven write:**

```cpp
class DeviceGateway {
public:
    void set_telemetry(const Devices::DeviceTelemetry& state) {
        if (!have_last_ || state != last_written_) {
            writer_.write(state);
            last_written_ = state;
            have_last_ = true;
        }
    }

private:
    dds::pub::DataWriter<Devices::DeviceTelemetry> writer_;  // looked up from participant
    Devices::DeviceTelemetry last_written_{};
    bool have_last_{false};
};
```

**Python — state-machine-driven write:**

```python
class DeviceGateway:
    def __init__(self, writer: dds.DataWriter) -> None:
        self._writer = writer
        self._last: devices.Devices.DeviceTelemetry | None = None

    def set_telemetry(self, state: devices.Devices.DeviceTelemetry) -> None:
        if self._last is None or state != self._last:
            self._writer.write(state)
            self._last = state
```

### 4.3 Reading Data

**C++ — AsyncWaitSet + ReadCondition (preferred):**

Attach `ReadCondition`s to an `AsyncWaitSet` during setup. Call
`aws.start()` at the beginning of the application's `run()` method,
after all entities are enabled.

```cpp
rti::core::cond::AsyncWaitSet aws;

dds::sub::cond::ReadCondition rc(
    reader,
    dds::sub::status::DataState::any(),
    [&reader]() {
        for (const auto& sample : reader.take()) {
            if (sample.info().valid()) {
                process(sample.data());  // application-specific
            }
        }
    });

aws += rc;
// ... attach other conditions as needed ...

// In the application's run() method, after entities are enabled:
aws.start();
```

**Python — asyncio (preferred):**

Use the standard `asyncio` module for the event loop. Use
`asyncio.gather()` when multiple async tasks (readers, periodic
publishers) need to run concurrently.

```python
import asyncio
import rti.connextdds as dds

async def read_vitals(reader: dds.DataReader) -> None:
    async for data in reader.take_data_async():
        process(data)  # application-specific

async def main() -> None:
    # ... create participant, look up entities ...
    await asyncio.gather(
        read_vitals(vitals_reader),
        read_alarms(alarm_reader),
        publish_fixed_rate(vitals_writer),
    )

asyncio.run(main())
```

### 4.4 Status Change Handling

All application-visible status change handling (subscription matched,
liveliness changed, deadline missed, etc.) must use `StatusCondition`
attached to an `AsyncWaitSet` — not a listener callback. Listeners are
acceptable only for narrowly scoped infrastructure concerns (e.g.,
minimal flag-setting) that are documented and justified.

The implementation pattern below shows **how** to observe status events.
Which statuses are mandatory for each topic class is a data-model
concern — see [data-model.md — Publication Model](data-model.md) for
the per-topic QoS expectations (Deadline, Liveliness, Reliability) that
determine which statuses the application must handle.

**C++ — typical status monitoring setup:**

Attach one `StatusCondition` per entity with the statuses relevant to
that entity. In the handler, read the corresponding status struct and
act (log, update internal state, raise an application-level alert).

```cpp
dds::core::cond::StatusCondition sc(reader);
sc.enabled_statuses(
    dds::core::status::StatusMask::liveliness_changed()
    | dds::core::status::StatusMask::requested_deadline_missed()
    | dds::core::status::StatusMask::sample_lost());
sc.handler([&reader]() {
    // Check each status — multiple may fire in one dispatch
    if (reader.status_changes().test(
            dds::core::status::StatusMask::liveliness_changed())) {
        auto s = reader.liveliness_changed_status();
        // e.g., log or raise alarm if alive_count dropped to 0
    }
    if (reader.status_changes().test(
            dds::core::status::StatusMask::requested_deadline_missed())) {
        auto s = reader.requested_deadline_missed_status();
        // e.g., log missed deadline, total count
    }
    if (reader.status_changes().test(
            dds::core::status::StatusMask::sample_lost())) {
        auto s = reader.sample_lost_status();
        // e.g., log lost samples
    }
});

aws += sc;
```

**Python:**

```python
status_cond = dds.StatusCondition(reader)
status_cond.enabled_statuses = (
    dds.StatusMask.LIVELINESS_CHANGED
    | dds.StatusMask.REQUESTED_DEADLINE_MISSED
    | dds.StatusMask.SAMPLE_LOST
)
# Attach to WaitSet or handle via asyncio status monitoring
```

> **Common statuses to monitor:** `liveliness_changed` (writer
> liveness), `requested_deadline_missed` / `offered_deadline_missed`
> (stream interruption), `sample_lost` / `sample_rejected` (delivery
> failures), `subscription_matched` / `publication_matched` (discovery
> events), `inconsistent_topic` / `offered_incompatible_qos` /
> `requested_incompatible_qos` (configuration mismatches).

---

## 5. Threading Contract

DDS I/O must never occur on the main thread or UI event loop. The threading
model is defined in [technology.md — DDS I/O Threading](technology.md).

### Rules

| Language | Publisher Pattern | Subscriber Pattern |
|----------|------------------|--------------------|
| C++ | Dedicated publisher thread for periodic writes; `AsyncWaitSet` + `GuardCondition` when delegating from a non-DDS thread | `AsyncWaitSet` + `ReadCondition` (thread pool size = 1) |
| Python | `asyncio` periodic task or event-driven coroutine | `async for data in reader.take_data_async()` via `asyncio` |
| Python GUI | QtAsyncio event loop integration | Same async pattern, integrated with Qt via `QtAsyncio` |

### AsyncWaitSet Isolation Principle (C++)

Each critical-path I/O context with an independent jitter budget gets its
own `AsyncWaitSet` instance. Do not combine fixed-rate publishers and
data-driven subscribers on the same `AsyncWaitSet` when either side has
a strict timing requirement. See
[coding-standards.md — AsyncWaitSet Isolation Principle](coding-standards.md)
for the full rule.

### AsyncWaitSet Lifecycle Rules (C++)

The `AsyncWaitSet` manages its own internal thread pool. These rules
govern its lifecycle within the service class pattern (§3):

1. **Ownership:** Each `AsyncWaitSet` is owned by exactly one service
   class as a private member. It is not shared across classes or
   returned to callers.
2. **Setup before start:** Attach all conditions (`ReadCondition`,
   `StatusCondition`, `GuardCondition`) to the `AsyncWaitSet` before
   calling `start()`. Attaching/detaching conditions after `start()`
   is thread-safe but should be avoided unless the design requires
   dynamic condition management.
3. **Handlers must not block.** Condition handlers execute on the
   `AsyncWaitSet`'s internal thread(s). Long-running or blocking
   operations (file I/O, network calls, waiting on mutexes held by
   other DDS handlers) stall the dispatch loop and delay other
   conditions.
4. **Handlers must not destroy entities.** A handler must not destroy
   or reset any entity that may still be referenced by the same or
   another handler on the same `AsyncWaitSet`. Entity destruction
   happens only when the owning class is destroyed, after the
   `AsyncWaitSet` has been stopped (see rule 6).
5. **Shared state synchronization.** If a handler reads or writes
   state shared with another thread (including another `AsyncWaitSet`),
   protect it with `std::atomic` variables or a lightweight lock
   (`std::mutex`). Prefer `std::atomic` for simple flags and counters
   to avoid lock contention on the dispatch path.
6. **Explicit `stop()` before entity destruction.** The `AsyncWaitSet`
   destructor is **not documented** as performing a synchronous
   stop/join of its worker threads. The class destructor must call
   `aws_.stop()` explicitly before DDS entities begin destruction.
   `stop()` blocks until async dispatch completes and no handlers are
   in flight. As a defensive layer, declare the `AsyncWaitSet` **after**
   all DDS entities so that reverse member destruction order destroys
   it first — but the explicit `stop()` call is the primary mechanism.

> **`rti-chatbot-mcp` note:** RTI documents `AsyncWaitSet::stop()` as
> blocking until async wait and dispatch have stopped. However, the
> class reference does not explicitly state that the destructor calls
> `stop()` automatically. Always call `stop()` explicitly in the owning
> class’s destructor to avoid use-after-destruction races between
> in-flight handlers and DDS entity teardown.

### GUI Applications

```
┌─────────────────────┐     signals/slots     ┌─────────────────────┐
│  DDS Thread(s)      │ ──────────────────────►│  UI Thread          │
│  AsyncWaitSet / rti │                        │  Qt Event Loop      │
│  .asyncio           │◄────────────────────── │  Widget rendering   │
│  Reads & writes     │     commands/events    │  User input         │
└─────────────────────┘                        └─────────────────────┘
```

DDS threads own DDS entities. The UI thread owns widgets. Communication
between them uses thread-safe signals/slots or queues — never direct
DDS API calls from the UI thread.

> **`rti-chatbot-mcp` guidance:** RTI explicitly warns that `write()` can
> block under certain QoS/resource-limit conditions. Performing writes on
> the UI thread risks frozen UIs and deadlocks. Polling at the GUI refresh
> rate is a valid alternative for subscriber-side display updates.

---

## 6. Anti-Pattern Catalog

These are **default prohibitions for production application code** unless
a specific, justified exception is documented and approved. Each
anti-pattern is sourced from [../workflow.md](../workflow.md) §4 and
validated against `rti-chatbot-mcp` RTI best-practice guidance.

| # | Anti-Pattern | Risk | Approved Alternative |
|---|-------------|------|---------------------|
| AP-1 | **`DataReaderListener` for data processing** | Stalls middleware receive thread → data loss, latency spikes, deadlocks, cross-reader interference. RTI: "never block in a listener callback." | `AsyncWaitSet` + `ReadCondition` (C++); `take_data_async()` (Python); polling at fixed rate for GUIs. Listeners acceptable only for minimal flag-setting. |
| AP-2 | **Programmatic QoS (setter APIs)** | Configuration drift across modules/languages; rebuild required for tuning; inconsistent cross-language behavior; hidden defaults. | XML QoS profiles via default `QosProvider`. **Exceptions:** XTypes compliance mask, participant partition (see §1). |
| AP-10 | **DDS entities in public class APIs** | Leaks middleware abstractions into domain interfaces; couples callers to DDS imports; makes testing harder. | Encapsulate all DDS entities as private members. Public interface uses domain types only (see §3). |
| AP-3 | **`DynamicData` / `DynamicType` in application code** | Runtime field-name errors (stringly-typed); no compile-time safety; weaker IDE support; higher runtime overhead; fragile refactoring. | IDL-generated types (`rtiddsgen`). DynamicData permitted only in developer tools (`tools/`) and test utilities. |
| AP-4 | **Hardcoded domain IDs in source code** | Deployment collisions; recompilation for environment changes; test contamination; hidden assumptions. | Domain IDs live exclusively in `Domains.xml` and [data-model.md](data-model.md). Code references domains by name (e.g., "Procedure domain"). |
| AP-5 | **DDS I/O on main/UI thread** | Frozen UI; jittery UX; deadlocks; priority inversion; unbounded latency from reliable writes or resource-limit pressure. | Dedicated DDS worker threads (see §5). UI thread only renders state received via signals/queues. |
| AP-6 | **`print()` / `printf` / `std::cout` for logging** | No integration with Connext verbosity categories; blocking console I/O; interleaved unstructured output; dangerous in listener/internal-thread contexts. | RTI Connext Logging API for middleware-level logging. Application-level logging uses the project’s approved logging interface — see [technology.md — Logging Standard](technology.md) for the authoritative logging guidance. No `print()` / `printf` / `std::cout` in production code. |
| AP-7 | **Hardcoded XML file paths in application code** | Breaks install-tree portability; couples code to file layout; prevents `NDDS_QOS_PROFILES`-based loading. | Use default `QosProvider` which loads from `NDDS_QOS_PROFILES`. See [data-model.md — QoS XML Loading](data-model.md). |
| AP-8 | **Custom `QosProvider` instances** | Bypasses the shared QoS hierarchy; risks loading partial or inconsistent XML; fragments configuration. | Always use `dds::core::QosProvider::Default()` (C++) or `dds.QosProvider.default` (Python). |
| AP-9 | **Publisher/Subscriber Partition QoS** | Conflates data-content isolation with context isolation; complicates QoS compatibility. | Domain partitions for context isolation; content-filtered topics for data-content filtering. Pub/Sub partition is **not used** in this system. See [system-architecture.md — Partition Strategy](system-architecture.md). |
| AP-11 | **Raw string literals for XML entity names** | Runtime lookup failures from typos; no compile-time/import-time safety; name drift between XML config and code; inconsistent across C++/Python. | Use generated constants from `app_names.idl` — every participant, writer, and reader name defined in XML must have a corresponding IDL constant (see §1 Step 2). |

---

## 7. Entity Lifecycle

Reference-type entities (`DomainParticipant`, `Publisher`, `Subscriber`,
`DataWriter`, `DataReader`, `Topic`) use shared-pointer semantics. Copying
a reference does not copy the entity — it creates another handle.

### Rules

- Prefer **scope-based lifecycle** — let references go out of scope
  naturally when the owning class is destroyed.
- Do not call `close()` on entities manually — rely on the destructor
  shutdown sequence (§3 rule 6) and RAII member destruction.
- Do not use `retain()` unless explicitly justified.
- See [coding-standards.md — Entity Lifecycle](coding-standards.md) for
  the full entity reference-type semantics.

---

## 8. Routing Service Usage

Routing Service is the controlled gateway between domains. The topology and
bridged topic list are defined in
[system-architecture.md — Routing Service Deployment](system-architecture.md).

### Architectural Principles

These principles were validated against `rti-chatbot-mcp` guidance for
RTI Routing Service 7.6.0:

1. **One `domain_route` per bridge boundary.** The medtech suite has one
   bridge boundary: Procedure domain → Hospital domain.
2. **Named participants with semantic roles.** Input-side participants are
   named by their domain and tag (e.g., `procedure_control`,
   `procedure_clinical`, `procedure_operational`). The output-side
   participant is named `hospital`.
3. **Separate sessions by traffic class.** Different traffic classes get
   different sessions for QoS isolation and independent threading:
   - `StateSession` — low-rate status/state topics
   - `StreamingSession` — higher-rate telemetry
   - `ImagingSession` — imaging metadata (future)
4. **Explicit topic filters.** Only explicitly configured topics cross the
   bridge. Always exclude `rti/*` internal topics.
5. **Domain tags on input participants.** Routing Service participants on
   the Procedure domain must be created with the correct domain tag.
   Hospital domain participants have no tag. See
   [system-architecture.md — Domain Tag Participant Model](system-architecture.md).

### Partition Propagation

Routing Service preserves the source partition on the output side. Data
bridged from `room/OR-3/procedure/proc-001` is published on the Hospital
domain with the same partition string. See
[system-architecture.md — Routing Service Partition Mapping](system-architecture.md)
for the `<propagation_qos>` configuration.

> **`rti-chatbot-mcp` note:** Routing Service does not automatically
> propagate partitions. Partition behavior must be configured explicitly
> in the session's `<subscriber_qos>` and `<publisher_qos>`, or via
> `<propagation_qos>`. This project uses explicit propagation to preserve
> source partitions — it is not a default Routing Service behavior.

### Health Monitoring

- Enable `<administration>` and `<monitoring>` in the Routing Service XML.
- Use the Observability domain (Domain 20) for monitoring traffic,
  consistent with the application observability strategy.
- Set practical publication periods (status: 5 s, statistics: 1 s).
- Monitor at service/session/route granularity.
- Use TCP port health checks in Docker Compose for startup ordering.

---

## 9. New Module Checklist

When adding a new module that uses DDS, follow this checklist to ensure
consistency with the existing system:

### Participant Configuration

- [ ] Create a participant XML entry in `interfaces/participants/` referencing
      the correct domain and domain tag
- [ ] Add corresponding `const string` entries in `interfaces/idl/app_names.idl`
      for the participant config name and every writer/reader entity name
- [ ] Ensure the participant references only domains/topics defined in
      `interfaces/domains/Domains.xml`
- [ ] Set the domain tag in the participant QoS XML (`<discovery><domain_tag>`)
      — never in application code
- [ ] Verify transport configuration: participant references `Participants::Transport`
      (composed from `Transport::$(MEDTECH_TRANSPORT_PROFILE)` in `Participants.xml`)

### Initialization

- [ ] Call `initialize_connext()` (the shared init function) before any
      participant creation
- [ ] Set partition from runtime context after `create_participant_from_config()`
- [ ] Use generated constants from `app_names.idl` for all participant and
      entity names — no raw string literals
- [ ] Do not hardcode domain IDs, partition strings, or XML file paths

### QoS

- [ ] Use `QosProvider::Default()` / `QosProvider.default` — no custom providers
- [ ] Use topic-aware QoS resolution — no explicit profile names in application
      code unless required
- [ ] Do not call any QoS setter API beyond the two approved exceptions
- [ ] Verify new topics have a corresponding entry in `Topics.xml`

### Data Access

- [ ] Use `AsyncWaitSet` + `ReadCondition` (C++) or `take_data_async()` (Python)
      for reading — no `DataReaderListener`
- [ ] Use the correct publication model for each topic (continuous-stream,
      periodic-snapshot, or write-on-change) per [data-model.md](data-model.md)
- [ ] Keep all DDS I/O off the main/UI thread
- [ ] Separate DDS code from business logic (thin DDS boundary pattern) per
      [coding-standards.md — DDS Code Separation](coding-standards.md)

### Logging & Observability

- [ ] Use RTI Connext Logging API — no `print()`, `printf`, `std::cout`
- [ ] Set module name prefix matching the module directory name
- [ ] Monitoring Library 2.0 is enabled via XML — no code-level opt-in needed

### Testing

- [ ] Integration tests use the project's generated IDL types — no DynamicData
- [ ] Partition isolation, QoS enforcement, and domain tag isolation scenarios
      from [../spec/common-behaviors.md](../spec/common-behaviors.md) apply

---

## 10. Cross-Reference Index

Quick lookup for where each DDS concern is authoritatively defined:

| Concern | Document | Section |
|---------|----------|---------|
| Domain IDs, domain tags, topic assignments | [data-model.md](data-model.md) | Domain Definitions |
| QoS XML hierarchy (Snippets/Patterns/Topics/Participants) | [data-model.md](data-model.md) | QoS Architecture |
| Publication models (when to write) | [data-model.md](data-model.md) | Publication Model |
| Pre-participant initialization (XTypes, type registration) | [data-model.md](data-model.md) | Pre-Participant Initialization |
| QoS XML loading (`NDDS_QOS_PROFILES`) | [data-model.md](data-model.md) | QoS XML Loading |
| Topic-aware QoS APIs | [data-model.md](data-model.md) | QoS Assigned to Topics via Topic Filters |
| Layered databus, domain tag participant model | [system-architecture.md](system-architecture.md) | Layered Databus |
| Partition strategy, wildcard matching | [system-architecture.md](system-architecture.md) | Partition Strategy |
| Routing Service topology, partition mapping | [system-architecture.md](system-architecture.md) | Routing Service Deployment |
| Transport configuration (SHMEM, UDPv4) | [system-architecture.md](system-architecture.md) | Transport Configuration |
| Cloud Discovery Service | [system-architecture.md](system-architecture.md) | Cloud Discovery Service |
| Threading model (AsyncWaitSet, asyncio, QtAsyncio) | [technology.md](technology.md) | DDS I/O Threading |
| Connext version management | [technology.md](technology.md) | Connext Version Management |
| Build integration (rtiddsgen, CMake) | [technology.md](technology.md) | Build System |
| Install tree, `setup.bash`, `NDDS_QOS_PROFILES` | [technology.md](technology.md) | Install Tree |
| AsyncWaitSet isolation, no-listener rule | [coding-standards.md](coding-standards.md) | Connext Modern C++ API Conventions |
| No DynamicData rule | [coding-standards.md](coding-standards.md) | No DynamicData in Applications |
| DDS code separation pattern | [coding-standards.md](coding-standards.md) | DDS Code Separation |
| Application architecture (encapsulated DDS) | This document | §3 Application Architecture Pattern |
| Entity name constants (`app_names.idl`) | This document | §1 Step 2 — Entity Name Constants |
| Generated code naming (IDL → C++/Python) | [coding-standards.md](coding-standards.md) | Naming Alignment with Generated Code |
| Prohibited actions table | [../workflow.md](../workflow.md) | §4 Strict Boundaries |
| Quality gates (QoS grep, domain ID grep, etc.) | [../workflow.md](../workflow.md) | §7 Quality Gates |
| DDS Design Review Gate | [../workflow.md](../workflow.md) | §8 DDS Design Review Gate |
| Behavioral scenarios (partition, QoS, isolation) | [../spec/common-behaviors.md](../spec/common-behaviors.md) | All sections |
| Security architecture | [security.md](security.md) | Deferred |

---

## 11. Consulting `rti-chatbot-mcp`

For implementation decisions that this document or the planning documents
leave to the agent's discretion, consult `rti-chatbot-mcp`. Use it for:

- **API usage patterns** — Modern C++ and Python idioms for Connext 7.6.0
- **QoS policy semantics** — understanding interactions between policies
  (e.g., Deadline + Liveliness, Reliability + History + Resource Limits)
- **Transport configuration** — UDPv4, SHMEM, Real-Time WAN Transport
- **Service administration** — Routing Service, Cloud Discovery Service,
  Collector Service XML configuration
- **IDL and type system** — extensibility annotations, bounds, key design
- **Troubleshooting** — DDS discovery, matching, delivery, and performance
  issues
- **Validating design choices** — before implementing new DDS patterns,
  verify alignment with RTI best practices

**When `rti-chatbot-mcp` is insufficient**, consult these additional
resources in priority order:

1. [RTI Connext Modern C++ API Reference — How-To](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/api/connext_dds/api_cpp2/group__DDSHowToModule.html)
   — task-oriented API guidance for the Modern C++ (C++11) API
2. [RTI Connext Python API Reference — Overview](https://community.rti.com/static/documentation/connext-dds/7.6.0/doc/api/connext_dds/api_python/overview.html)
   — API overview and usage guide for the Python API
3. [RTI Connext DDS Examples](https://github.com/rticommunity/rticonnextdds-examples/tree/master/examples/connext_dds)
   — feature-specific examples (`c++11/` for Modern C++, `py/` for Python)
4. [RTI Connext DDS Tutorials](https://github.com/rticommunity/rticonnextdds-examples/tree/master/tutorials)
   — end-to-end walkthroughs
