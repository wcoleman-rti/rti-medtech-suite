# Surgical Procedure Module

## Overview

The surgical procedure module is a multi-instance application set that
simulates a complete surgical operating room. Each instance represents
one OR and runs in an isolated DDS partition. The module publishes
robot control, patient vitals, camera feeds, device telemetry, and
procedure context onto the Procedure domain.

All participants operate on the **Procedure domain** across three
domain tags:

- **control** — Robot teleop loop (100 Hz state, operator input,
  commands, safety interlocks)
- **clinical** — Patient vitals, waveforms, alarms, device telemetry
- **operational** — Procedure context, procedure status, camera frames

| Connext Feature | How It Is Used |
|-----------------|----------------|
| DDS topics | `RobotState`, `OperatorInput`, `RobotCommand`, `SafetyInterlock`, `PatientVitals`, `WaveformData`, `AlarmMessages`, `DeviceTelemetry`, `ProcedureContext`, `ProcedureStatus`, `CameraFrame`, `CameraConfig` |
| QoS profiles | `TopicProfiles::*` per topic — State, Stream, Command patterns loaded from `NDDS_QOS_PROFILES` XML |
| Domain tags | `control`, `clinical`, `operational` — each tag uses a separate `DomainParticipant` |
| Partitions | `room/<ROOM_ID>/procedure/<PROCEDURE_ID>` — set programmatically at participant startup |
| TRANSIENT_LOCAL durability | State-pattern topics (`RobotState`, `PatientVitals`, `ProcedureContext`, `ProcedureStatus`, `DeviceTelemetry`, `SafetyInterlock`) for late-joiner support |
| Exclusive ownership | `DeviceTelemetry` supports primary/backup failover via ownership strength |
| Time-based filter | Digital twin applies 100 ms minimum separation on high-rate readers (`RobotState`, `OperatorInput`) for 60 Hz rendering |
| Cloud Discovery Service | All participants discover peers through CDS (`NDDS_DISCOVERY_PEERS`) |
| Monitoring Library 2.0 | Telemetry forwarded to Collector Service for Prometheus/Grafana |

## Quick Start

### Prerequisites

- RTI Connext DDS 7.6.0 installed (`NDDSHOME` set)
- Project built and installed (`cmake --build build && cmake --install build`)
- Python venv activated with `rti.connext`, `PySide6`, and project
  packages installed
- Environment sourced: `source install/setup.bash`

### Build

```bash
cmake --preset default
cmake --build build --parallel
cmake --install build
```

### Configure

Source the install environment. All QoS, domain, and participant XML
files are loaded via `NDDS_QOS_PROFILES`:

```bash
source install/setup.bash
```

Set room and procedure context via environment variables:

```bash
export ROOM_ID="OR-1"
export PROCEDURE_ID="proc-001"
```

### Run

Individual simulators (local, outside Docker):

```bash
# Procedure context publisher
python -m surgical_procedure.procedure_context

# Robot controller (C++)
robot-controller

# Operator console simulator (joystick/haptic input)
python -m surgical_procedure.operator_sim

# Bedside monitor (vitals + waveforms + alarms)
python -m surgical_procedure.vitals_sim

# Camera simulator
python -m surgical_procedure.camera_sim

# Device telemetry (pump + anesthesia machine)
python -m surgical_procedure.device_telemetry_sim

# Digital twin display (PySide6 GUI)
python -m surgical_procedure.digital_twin
```

Docker Compose (two OR instances):

```bash
docker compose up -d
```

## Architecture

### Component Structure

```text
modules/surgical-procedure/
├── procedure_context_service.py        Procedure context & status publisher
├── robot_controller/            C++ robot controller (100 Hz state loop)
│   ├── robot_controller.hpp    Pure logic state machine
│   ├── robot_controller.cpp    State machine implementation
│   └── robot_controller_service.cpp + main.cpp  DDS application entry point
├── operator_sim/               Operator console simulator
│   └── operator_console_service.py     OperatorInput + RobotCommand + SafetyInterlock
├── vitals_sim/                 Bedside monitor simulator
│   ├── bedside_monitor_service.py      PatientVitals + WaveformData + AlarmMessages
│   ├── _signal.py              Signal model (convergence, noise, correlation)
│   ├── _profiles.py            Scenario profiles (stable, hemorrhage_onset)
│   └── _alarm.py               Alarm evaluation (threshold + hysteresis)
├── camera_sim/                 Camera frame simulator
│   └── camera_service.py          CameraFrame publisher (30 Hz default)
├── device_telemetry_sim/       Device gateway simulator
│   ├── device_telemetry_service.py       DeviceTelemetry write-on-change publisher
│   └── _device_model.py        Device profiles + state model
└── digital_twin/               PySide6 digital twin display
    ├── digital_twin_display.py Main window with async DDS readers
    └── _robot_widget.py        2D robot visualization widget
```

### DDS Entities

Each application creates its `DomainParticipant` from XML configuration
via `create_participant_from_config()`. Entity names are generated
constants from `app_names.idl`. Writers and readers are found by name
after participant creation.

**OperationalPub** (`SurgicalParticipants::OperationalPub`) —
domain tag: `operational`

| Entity | Topic | QoS Profile | Publication Model |
|--------|-------|-------------|-------------------|
| DataWriter | `ProcedureContext` | `TopicProfiles::ProcedureContext` | Write-on-change (State, TRANSIENT_LOCAL) |
| DataWriter | `ProcedureStatus` | `TopicProfiles::ProcedureStatus` | Write-on-change (State, TRANSIENT_LOCAL) |
| DataWriter | `CameraFrame` | `TopicProfiles::CameraFrame` | Continuous-stream (30 Hz, BEST_EFFORT) |
| DataWriter | `CameraConfig` | `TopicProfiles::CameraConfig` | Write-on-change (State) |

**ControlRobot** (`SurgicalParticipants::ControlRobot`) —
domain tag: `control`

| Entity | Topic | QoS Profile | Publication Model |
|--------|-------|-------------|-------------------|
| DataWriter | `RobotState` | `TopicProfiles::RobotState` | Periodic-snapshot (100 Hz, RELIABLE, TRANSIENT_LOCAL) |
| DataReader | `OperatorInput` | `TopicProfiles::OperatorInput` | Continuous-stream |
| DataReader | `RobotCommand` | `TopicProfiles::RobotCommand` | Command pattern (RELIABLE) |
| DataReader | `SafetyInterlock` | `TopicProfiles::SafetyInterlock` | State (RELIABLE, TRANSIENT_LOCAL) |

**ClinicalMonitor** (`SurgicalParticipants::ClinicalMonitor`) —
domain tag: `clinical`

| Entity | Topic | QoS Profile | Publication Model |
|--------|-------|-------------|-------------------|
| DataWriter | `PatientVitals` | `TopicProfiles::PatientVitals` | Periodic-snapshot (1 Hz, RELIABLE, TRANSIENT_LOCAL) |
| DataWriter | `WaveformData` | `TopicProfiles::WaveformData` | Continuous-stream (50 Hz, BEST_EFFORT) |
| DataWriter | `AlarmMessages` | `TopicProfiles::AlarmMessages` | Write-on-change (alarm state transitions only) |

**ClinicalDeviceGateway**
(`SurgicalParticipants::ClinicalDeviceGateway`) —
domain tag: `clinical`

| Entity | Topic | QoS Profile | Publication Model |
|--------|-------|-------------|-------------------|
| DataWriter | `DeviceTelemetry` | `TopicProfiles::DeviceTelemetry` | Write-on-change (State, exclusive ownership) |

**ControlDigitalTwin** (`SurgicalParticipants::ControlDigitalTwin`) —
domain tag: `control`

| Entity | Topic | QoS Profile | Notes |
|--------|-------|-------------|-------|
| DataReader | `RobotState` | `TopicProfiles::GuiRobotState` | Time-based filter ~100 ms |
| DataReader | `OperatorInput` | `TopicProfiles::GuiOperatorInput` | Time-based filter ~100 ms |
| DataReader | `SafetyInterlock` | `TopicProfiles::SafetyInterlock` | No TBF (safety-critical) |
| DataReader | `RobotCommand` | `TopicProfiles::RobotCommand` | No TBF (command delivery) |

### Threading Model

**Robot controller (C++):** Dual `AsyncWaitSet` architecture with
thread pool size 1 each:

- **Publisher AsyncWaitSet** — dedicated to the 100 Hz `RobotState`
  output. A timer thread triggers a `GuardCondition` every 10 ms.
  The handler acquires a read-lock on shared controller state,
  snapshots it, and writes `RobotState`. No `ReadCondition`s are
  attached — this thread only publishes.
- **Subscriber AsyncWaitSet** — dispatches `ReadCondition`s for
  `SafetyInterlock`, `RobotCommand`, and `OperatorInput`. Single-
  threaded dispatch prevents reader races on shared state.
- A `std::shared_mutex` protects the shared controller state between
  publisher (read-lock) and subscriber (write-lock) threads.

**Python simulators:** Single-threaded — each simulator runs a
blocking `time.sleep()` loop on a background thread or in a main
loop. DDS I/O occurs on the loop thread, not the main/UI thread.

**Digital twin (PySide6):** Uses `QtAsyncio` with `rti.asyncio` async
data generators (`take_data_async()`). DDS reads are dispatched as
async coroutines on the Qt event loop — the main thread is never
blocked by DDS I/O. A periodic liveliness-check coroutine polls
reader status to detect robot disconnection.

## Configuration Reference

### Environment Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ROOM_ID` | string | `"OR-1"` | Operating room identifier |
| `PROCEDURE_ID` | string | `"proc-001"` | Procedure identifier |
| `ROBOT_ID` | string | `"001"` | Robot numeric ID (prefixed to `robot-001`) |
| `MEDTECH_SIM_SEED` | integer | (system entropy) | RNG seed for deterministic simulation |
| `MEDTECH_SIM_PROFILE` | string | `"stable"` | Vitals scenario profile (`stable`, `hemorrhage_onset`) |
| `MEDTECH_APP_NAME` | string | (module default) | Monitoring Library 2.0 application name |
| `QT_QPA_PLATFORM` | string | (system default) | Qt platform plugin (`offscreen` for headless) |
| `NDDS_QOS_PROFILES` | string | (set by `setup.bash`) | Semicolon-separated QoS XML file paths |
| `NDDS_DISCOVERY_PEERS` | string | (set by `setup.bash`) | DDS discovery peer list |

### XML Configuration Files

All QoS and entity configuration is loaded from XML via
`NDDS_QOS_PROFILES` (set by `source install/setup.bash`):

| File | Content |
|------|---------|
| `share/qos/Snippets.xml` | Reusable QoS snippets (reliability, durability) |
| `share/qos/Patterns.xml` | QoS patterns (State, Stream, Command) |
| `share/qos/Topics.xml` | Per-topic QoS profiles (`TopicProfiles::*`) |
| `share/qos/Participants.xml` | Transport and participant base QoS |
| `share/domains/Domains.xml` | Domain library (Procedure, Hospital domain IDs and tags) |

Participant configurations are in
`interfaces/participants/SurgicalParticipants.xml`, which is included
by the QoS provider chain.

### Domain Partition

Partition is derived from `ROOM_ID` and `PROCEDURE_ID` and set
programmatically on the `DomainParticipantQos` after
`create_participant_from_config()`. The format is:

```text
room/<ROOM_ID>/procedure/<PROCEDURE_ID>
```

For example: `room/OR-1/procedure/proc-001`. Each OR instance uses a
unique partition for data isolation. There is no separate `PARTITION`
environment variable — applications construct the string from their
room and procedure context.

## Testing

Run the full project test suite (includes all surgical tests):

```bash
source install/setup.bash
python -m pytest tests/ -x --tb=short
```

Run only surgical-procedure-related tests:

```bash
python -m pytest tests/integration/test_robot_controller.py \
                 tests/integration/test_vitals_sim.py \
                 tests/integration/test_camera_sim.py \
                 tests/integration/test_device_telemetry.py \
                 tests/integration/test_procedure_context_service.py \
                 tests/integration/test_exclusive_ownership.py \
                 tests/integration/test_partition_isolation.py \
                 tests/gui/test_digital_twin.py \
                 -v
```

Run by marker:

```bash
# Integration tests only
python -m pytest tests/ -m integration

# GUI tests only
python -m pytest tests/ -m gui

# Partition isolation tests
python -m pytest tests/ -m partition

# Exclusive ownership failover
python -m pytest tests/ -m failover
```

| Marker | Description |
|--------|-------------|
| `integration` | Tests requiring two or more DDS participants |
| `gui` | PySide6 GUI verification tests |
| `partition` | Partition-based isolation tests |
| `failover` | Exclusive ownership failover tests |
| `streaming` | High-rate best-effort streaming tests |
| `durability` | TRANSIENT_LOCAL and VOLATILE behavior tests |
| `consistency` | DDS consistency contract tests |

## Going Further

- [spec/surgical-procedure.md](../../docs/agent/spec/surgical-procedure.md)
  — behavioral specification (GWT scenarios)
- [vision/data-model.md](../../docs/agent/vision/data-model.md) — topic
  definitions, QoS profiles, domain layout
- [vision/system-architecture.md](../../docs/agent/vision/system-architecture.md)
  — layered databus architecture
- [vision/simulation-model.md](../../docs/agent/vision/simulation-model.md)
  — vitals signal model, scenario profiles, cross-signal correlation
- [implementation/phase-2-surgical.md](../../docs/agent/implementation/phase-2-surgical.md)
  — implementation plan and test gates
- [modules/hospital-dashboard/](../hospital-dashboard/) — downstream
  consumer of surgical data via Routing Service
- [modules/clinical-alerts/](../clinical-alerts/) — risk scoring engine
  consuming vitals and device telemetry
