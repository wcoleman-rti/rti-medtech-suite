# Hospital Dashboard Module

## Overview

The hospital dashboard module provides the **Procedure Controller**, a
PySide6 GUI application that acts as the central control plane for the
medtech suite. It discovers Service Hosts, displays their capabilities
and service states, and issues start/stop commands via DDS RPC.

The Procedure Controller does **not** host any surgical services — it is
a pure consumer and orchestrator. It creates three DomainParticipants:

| Participant      | Domain              | Role                                                            |
| ---------------- | ------------------- | --------------------------------------------------------------- |
| Orchestration    | 15 (no domain tags) | Subscribe to ServiceCatalog + ServiceStatus; issue RPC commands |
| ProcedureControl | 10 (`control` tag)  | Subscribe to RobotArmAssignment for arm tracking (V1.2)         |
| Hospital         | Hospital domain     | Read-only subscriber for scheduling context                     |

### Connext Features Used

| Feature                 | Where                                                                         |
| ----------------------- | ----------------------------------------------------------------------------- |
| XML App Creation        | All participants created via `QosProvider.create_participant_from_config`     |
| DDS RPC                 | `rti.rpc.Requester` for `ServiceHostControl` — start/stop/capabilities/health |
| Content-Filtered Topics | —                                                                             |
| Multiple Domains        | Orchestration (15) + Procedure (10, control tag) + Hospital                   |
| Partition QoS           | Hospital participant: `room/<room_id>`; ProcedureControl: room/procedure      |
| `start_service` RPC     | Accepts `table_position` property for multi-arm placement (V1.2)              |

## Quick Start

### Prerequisites

```bash
source install/setup.bash
```

### Run

```bash
# Set the operating room to control
export ROOM_ID=OR-1

# Launch the Procedure Controller
python -m hospital_dashboard.procedure_controller
```

The GUI window shows two tables (Service Hosts, Service States) and four
action buttons (Start, Stop, Capabilities, Health). Service Hosts appear
automatically as they publish ServiceCatalog samples on the Orchestration
domain.

## Architecture

### Component Structure

```text
modules/hospital-dashboard/
├── __init__.py
└── procedure_controller/
    ├── __init__.py
    ├── __main__.py            # Entry point (QApplication)
    └── procedure_controller.py # ProcedureController QMainWindow
```

### DDS Entities

**Orchestration Participant** — `ProcedureController::Orchestration`

| Entity        | Topic / Service                | Type                            | QoS                        |
| ------------- | ------------------------------ | ------------------------------- | -------------------------- |
| DataReader    | `ServiceCatalog`               | `Orchestration::ServiceCatalog` | RELIABLE / TRANSIENT_LOCAL |
| DataReader    | `ServiceStatus`                | `Orchestration::ServiceStatus`  | RELIABLE / TRANSIENT_LOCAL |
| RPC Requester | `ServiceHostControl/<host_id>` | Request/Reply                   | Created on-demand per host |

**ProcedureControl Participant** — `ProcedureController::ProcedureControl`

| Entity     | Topic                | Type                          | QoS                                             |
| ---------- | -------------------- | ----------------------------- | ----------------------------------------------- |
| DataReader | `RobotArmAssignment` | `Surgery::RobotArmAssignment` | RELIABLE / TRANSIENT_LOCAL; arm tracking (V1.2) |

**Hospital Participant** — `ProcedureController::Hospital`

| Entity      | Topic              | Type | QoS |
| ----------- | ------------------ | ---- | --- |
| (read-only) | Scheduling context | —    | —   |

The Hospital participant is partitioned with `room/<room_id>` and
enabled in read-only mode (no DataWriters).

### Threading Model

| Thread             | Responsibility                                                                                |
| ------------------ | --------------------------------------------------------------------------------------------- |
| Qt UI thread       | `QTimer` polls DDS readers at 10 Hz (`_poll_dds`), updates tables                             |
| RPC worker threads | One `threading.Thread` per RPC call (`_send_rpc_async`), results delivered to UI via `Signal` |

The Procedure Controller performs **no DDS writes on the UI thread**.
All RPC operations run on short-lived daemon worker threads. RPC results
are marshalled back to the UI thread via a Qt `Signal` to ensure
thread-safe widget updates.

## Configuration Reference

### Environment Variables

| Variable           | Default | Description                                        |
| ------------------ | ------- | -------------------------------------------------- |
| `ROOM_ID`          | `OR-1`  | Operating room identifier; sets Hospital partition |
| `CONNEXTDDS_DIR`   | —       | RTI Connext installation directory                 |
| `QT_QPA_PLATFORM`  | —       | Set to `offscreen` for headless / CI environments  |
| `MEDTECH_APP_NAME` | —       | Application name for structured logging            |

### XML Configuration

Participants are defined in the XML App Creation configuration loaded
by `QosProvider.default`. Entity names are generated constants from
`app_names.idl` (accessed via `app_names.MedtechEntityNames`).

## Testing

Run Procedure Controller integration tests:

```bash
python -m pytest tests/integration/test_procedure_controller.py -v
```

Run by marker:

```bash
# All orchestration tests (includes Procedure Controller + Service Host tests)
python -m pytest tests/ -m orchestration

# GUI tests only
python -m pytest tests/ -m gui
```

Key test scenarios (from `test_procedure_controller.py`):

| Test                                    | Verifies                                          |
| --------------------------------------- | ------------------------------------------------- |
| `test_host_catalog_discovery`           | ServiceCatalog samples populate the hosts table   |
| `test_service_status_tracking`          | ServiceStatus samples populate the services table |
| `test_hospital_domain_read_only`        | Hospital participant has zero DataWriters         |
| `test_start_service_rpc_call`           | Start button produces correct RPC request         |
| `test_stop_service_rpc_call`            | Stop button produces correct RPC request          |
| `test_rpc_requester_creation`           | On-demand requester creation per host             |
| `test_rpc_timeout_handling`             | Timeout produces status bar message (no crash)    |
| `test_close_dds_cleanup`                | `close_dds()` closes participants and requesters  |
| `test_dds_entities_use_generated_names` | All entity names match `app_names` constants      |

## Going Further

- [spec/orchestration.md](../../docs/agent/spec/orchestration.md) — orchestration
  behavioral specification (Procedure Controller GWT scenarios)
- [vision/data-model.md](../../docs/agent/vision/data-model.md) — topic
  definitions, QoS profiles, domain layout
- [vision/system-architecture.md](../../docs/agent/vision/system-architecture.md)
  — layered databus architecture
- [implementation/phase-5-orchestration.md](../../docs/agent/implementation/phase-5-orchestration.md)
  — orchestration implementation plan
- [modules/surgical-procedure/](../surgical-procedure/) — Service Hosts and
  surgical services controlled by the Procedure Controller
- [modules/clinical-alerts/](../clinical-alerts/) — risk scoring engine
  consuming vitals and device telemetry
