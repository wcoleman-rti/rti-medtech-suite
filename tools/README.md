# Diagnostic Tools

Index of all diagnostic and development tools for the medtech suite.
See [vision/tooling.md](../docs/agent/vision/tooling.md) for full
documentation and usage rationale.

## Available Tools

| Tool | Description | Status |
|------|-------------|--------|
| [qos-checker.py](qos-checker.py) | QoS RxO compatibility pre-flight checker | Available (Phase 1) |
| [admin-console.md](admin-console.md) | RTI Admin Console connection guide | Guide |
| [dds-spy.md](dds-spy.md) | RTI DDS Spy usage examples | Guide |
| `medtech-diag/` | System health diagnostic CLI | Phase 2 |
| `partition-inspector.py` | Active partition scanner | Phase 2 |

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
