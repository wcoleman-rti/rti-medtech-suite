# Digital Twin Display

## Overview

The digital twin display is a PySide6 GUI application that renders a
live 2D visualization of the surgical robot. It subscribes to the
Procedure DDS domain (`control` tag) and displays robot joint positions,
operational mode, active commands, and safety interlock status in
real time.

The display is a read-only DDS subscriber — it publishes no data.
Connectivity monitoring detects robot disconnection via liveliness
and grays out the visualization.

| Connext Feature        | How It Is Used                                                                                                                                                                              |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| DDS topics (subscribe) | `RobotState`, `OperatorInput`, `SafetyInterlock`, `RobotCommand`, `RobotArmAssignment`                                                                                                      |
| QoS profiles           | `TopicProfiles::GuiRobotState`, `TopicProfiles::GuiOperatorInput` (time-based filter), `TopicProfiles::SafetyInterlock`, `TopicProfiles::RobotCommand`, `TopicProfiles::RobotArmAssignment` |
| Domain tag             | `control`                                                                                                                                                                                   |
| Partition              | `room/<ROOM_ID>/procedure/<PROCEDURE_ID>`                                                                                                                                                   |
| Time-based filter      | 100 ms minimum separation on `RobotState` and `OperatorInput` readers for 60 Hz rendering                                                                                                   |
| TRANSIENT_LOCAL        | Late-joining display receives current robot state                                                                                                                                           |
| Liveliness             | Detects robot disconnection (grayed-out state)                                                                                                                                              |
| `rti.asyncio`          | Async data generators for non-blocking DDS reads                                                                                                                                            |

## Quick Start

### Prerequisites

- RTI Connext DDS 7.6.0 installed (`NDDSHOME` set)
- Project built and installed
- Python venv activated with `rti.connext` and `PySide6`
- Environment sourced: `source install/setup.bash`
- A robot controller instance running in the same partition

### Build

No separate build step — the digital twin is a pure Python module
installed with the project:

```bash
cmake --build build --parallel
cmake --install build
```

### Configure

```bash
source install/setup.bash
export ROOM_ID="OR-1"
export PROCEDURE_ID="proc-001"
```

### Run

```bash
python -m surgical_procedure.digital_twin
```

For headless operation (no display server required):

```bash
QT_QPA_PLATFORM=offscreen python -m surgical_procedure.digital_twin
```

Docker Compose:

```bash
docker compose up digital-twin-or1
```

## Architecture

### Component Structure

```text
digital_twin/
├── __init__.py                 Package exports
├── __main__.py                 Entry point (QtAsyncio event loop)
├── digital_twin_display.py     QMainWindow with DDS reader coroutines
└── _robot_widget.py            2D robot visualization widget
```

### DDS Entities

The display creates a single `DomainParticipant` from XML
configuration `SurgicalParticipants::ControlDigitalTwin` with domain
tag `control`. Entity names are generated constants from
`app_names.idl`, looked up via `find_datareader()`.

| Entity     | Topic                | QoS Profile                         | Notes                                                           |
| ---------- | -------------------- | ----------------------------------- | --------------------------------------------------------------- |
| DataReader | `RobotState`         | `TopicProfiles::GuiRobotState`      | Time-based filter ~100 ms for 60 Hz rendering                   |
| DataReader | `OperatorInput`      | `TopicProfiles::GuiOperatorInput`   | Time-based filter ~100 ms for 60 Hz rendering                   |
| DataReader | `SafetyInterlock`    | `TopicProfiles::SafetyInterlock`    | No time-based filter — every sample delivered (safety-critical) |
| DataReader | `RobotCommand`       | `TopicProfiles::RobotCommand`       | No time-based filter — each command must be processed           |
| DataReader | `RobotArmAssignment` | `TopicProfiles::RobotArmAssignment` | Multi-arm spatial tracking; visibility per-slot (V1.2)          |

### Threading Model

The display uses **QtAsyncio** with `rti.asyncio` async data
generators (`take_data_async()`). DDS reads are dispatched as async
coroutines on the Qt event loop — the main thread is never blocked
by DDS I/O.

Data flow:

1. `__main__.py` starts the `QtAsyncio` event loop
2. `DigitalTwinDisplay.__init__()` creates the participant and
   finds readers
3. `start_tasks()` launches one async coroutine per reader, plus a
   liveliness-check coroutine
4. Each reader coroutine calls `take_data_async()` and updates the
   `RobotWidget` on each sample
5. The liveliness coroutine polls
   `reader.liveliness_changed_status` every 500 ms and calls
   `set_connected(False)` when no alive writers remain

All QoS is loaded from XML (`NDDS_QOS_PROFILES`). The only
programmatic QoS is partition, set from runtime context after
participant creation.

### Visualization Features

- Schematic arm with joint angles from `RobotState`
- Tool-tip position indicator
- Active command annotation from `RobotCommand`
- Operational mode label (OPERATIONAL, PAUSED, EMERGENCY_STOP, IDLE)
- Safety interlock overlay (red, prominent) from `SafetyInterlock`
- Disconnected state (grayed out) on liveliness lost
- Multi-arm rendering with 4 pre-defined table slots (V1.2):
  - Color-coded arm status (green=OPERATIONAL, amber=POSITIONING,
    red=FAILED, gray=IDLE/ASSIGNED)
  - Per-arm status overlay panel with table position labels
  - Visibility driven by `RobotArmAssignment` instance lifecycle
  - `dispose()` hides the arm slot automatically

## Configuration Reference

### Environment Variables

| Variable               | Type   | Default               | Description                                   |
| ---------------------- | ------ | --------------------- | --------------------------------------------- |
| `ROOM_ID`              | string | `"OR-1"`              | Operating room identifier                     |
| `PROCEDURE_ID`         | string | `"proc-001"`          | Procedure identifier                          |
| `QT_QPA_PLATFORM`      | string | (system default)      | Qt platform plugin (`offscreen` for headless) |
| `NDDS_QOS_PROFILES`    | string | (set by `setup.bash`) | QoS XML file paths                            |
| `NDDS_DISCOVERY_PEERS` | string | (set by `setup.bash`) | DDS discovery peer list                       |

### XML Configuration Files

Participant configuration:
`SurgicalParticipants::ControlDigitalTwin` in
`interfaces/participants/SurgicalParticipants.xml`.

QoS profiles loaded via `NDDS_QOS_PROFILES`:

| File                                            | Content                                                                                                                            |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `share/qos/Topics.xml`                          | `TopicProfiles::GuiRobotState`, `TopicProfiles::GuiOperatorInput`, `TopicProfiles::SafetyInterlock`, `TopicProfiles::RobotCommand` |
| `share/qos/Patterns.xml`                        | Base State, Stream, Command patterns                                                                                               |
| `share/domains/Room,Hospital,CloudDatabuses.xml` | Domain library definitions                                                                                                         |

### Domain Partition

```text
room/<ROOM_ID>/procedure/<PROCEDURE_ID>
```

Set programmatically from `ROOM_ID` and `PROCEDURE_ID` environment
variables after participant creation.

## Testing

Run digital twin tests:

```bash
source install/setup.bash
python -m pytest tests/gui/test_digital_twin.py -v
```

Run all GUI tests:

```bash
python -m pytest tests/ -m gui -v
```

| Marker        | Tests                                      |
| ------------- | ------------------------------------------ |
| `gui`         | All PySide6 widget and display tests       |
| `integration` | DDS reader/writer interaction tests        |
| `durability`  | Late-joiner TRANSIENT_LOCAL verification   |
| `streaming`   | Time-based filter and rendering rate tests |

The tests use dependency injection — pre-created `DataReader` objects
are passed to `DigitalTwinDisplay` for isolated unit testing without
requiring the full XML participant configuration.

## Going Further

- [spec/surgical-procedure.md](../../../docs/agent/spec/surgical-procedure.md)
  — Digital Twin Display GWT scenarios
- [vision/data-model.md](../../../docs/agent/vision/data-model.md) —
  topic definitions and QoS profiles
- [vision/system-architecture.md](../../../docs/agent/vision/system-architecture.md)
  — layered databus architecture
- [vision/coding-standards.md](../../../docs/agent/vision/coding-standards.md)
  — threading model and `DataReaderListener` prohibition
- [implementation/phase-2-surgical.md](../../../docs/agent/implementation/phase-2-surgical.md)
  — Step 2.6 implementation details
- [modules/surgical-procedure/](../) — parent module with all
  simulators
