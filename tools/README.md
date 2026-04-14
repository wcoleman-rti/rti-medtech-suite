# Diagnostic Tools

Index of all diagnostic and development tools for the medtech suite.
See [vision/tooling.md](../docs/agent/vision/tooling.md) for full
documentation and usage rationale.

> **Note:** The `medtech` CLI (`medtech build`, `medtech launch`,
> `medtech run`, `medtech status`, `medtech stop`) is for building,
> launching, and scaling the simulation environment. The diagnostic
> tools below are for **inspecting DDS runtime behavior** once the
> system is running. Install the CLI with `pip install -e .` from
> the project root.

## Available Tools

| Tool | Description | Status |
|------|-------------|--------|
| [qos-checker.py](qos-checker.py) | QoS RxO compatibility pre-flight checker | Available (Phase 1) |
| [medtech-diag/](medtech-diag/) | System health diagnostic CLI | Available (Phase 2) |
| [partition-inspector.py](partition-inspector.py) | Active partition scanner | Available (Phase 2) |
| [admin-console.md](admin-console.md) | RTI Admin Console connection guide | Guide |
| [dds-spy.md](dds-spy.md) | RTI DDS Spy usage examples | Guide |

## Quick Reference

| Debugging Scenario | First Tool | Second Tool |
|--------------------|------------|-------------|
| Endpoints not matching | `qos-checker.py` (offline) | Admin Console (live) |
| No data flowing on a topic | `rtiddsspy` on target domain | Grafana Data Flow dashboard |
| Latency is too high | Grafana Sample Latency dashboard | `medtech-diag` |
| Samples being lost | Grafana Data Flow → Samples Lost | `rtiddsspy` on both sides |
| Deadline missed | Grafana QoS Events dashboard | `medtech-diag --check liveliness` |
| Partition isolation broken | `partition-inspector.py` | `rtiddsspy` with partition filter |
| Discovery failing | `medtech-diag --check discovery` | Admin Console |
| Routing Service not forwarding | Grafana Routes dashboard | `rtiddsspy` on both domains |
| Unknown system state | `medtech-diag` (full check) | Grafana System Overview |
| New module not connecting | `medtech-diag --check endpoints` | `qos-checker.py --verbose` |

## Usage

All tools require the project environment to be sourced first:

```bash
source install/setup.bash
```

### QoS Compatibility Checker

```bash
# Check all topic pairs
python tools/qos-checker.py

# Verbose output (show resolved QoS details per topic)
python tools/qos-checker.py --verbose
```

Exit codes: 0 (all compatible), 1 (incompatibilities found),
2 (infrastructure error).

### System Health Diagnostic

```bash
# Full health check (all domains, all checks)
python tools/medtech-diag/diag.py

# Check specific domain
python tools/medtech-diag/diag.py --domain procedure

# Check specific aspect
python tools/medtech-diag/diag.py --check endpoints

# JSON output (for CI integration)
python tools/medtech-diag/diag.py --format json
```

Exit codes: 0 (all pass), 1 (failures found), 2 (infrastructure error).

### Partition Inspector

```bash
# Scan all active partitions
python tools/partition-inspector.py

# Watch mode (continuous, updates every 5 s)
python tools/partition-inspector.py --watch

# Filter by room
python tools/partition-inspector.py --filter "room/OR-3/*"
```
