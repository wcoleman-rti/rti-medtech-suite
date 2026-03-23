# Performance Baseline Framework

The medtech suite evolves across multiple implementation phases, milestones, and agent
sessions. Each change — new modules, rearchitectures, dependency upgrades, QoS tuning,
or infrastructure modifications — can affect system performance in ways that are invisible
to functional tests. This framework establishes a **repeatable, quantitative performance
measurement and regression detection system** that tracks the performance impact of every
change across the project's lifecycle.

The framework is built entirely on infrastructure already present in the project: the RTI
Observability Framework (Monitoring Library 2.0 → Collector Service → Prometheus) for
metrics collection, and Docker Compose for reproducible execution environments.

---

## Principles

1. **Measure, don't guess.** Every performance claim is backed by a metric collected from
   a standardized benchmark run. Agents never estimate or assume performance — they run
   the benchmark and read the numbers.
2. **Baselines are committed artifacts.** After each implementation phase is complete,
   a baseline JSON file is recorded and committed. This file is the quantitative record
   of the system's performance at that point in time.
3. **Thresholds are defined up front.** Acceptable deviation from the baseline is a
   concrete percentage defined in this document — not left to agent interpretation.
4. **Regressions block the phase.** A performance regression that exceeds the defined
   threshold is treated the same as a failing functional test: it blocks the phase until
   resolved or the baseline is updated with explicit operator approval.
5. **The benchmark is deterministic.** The same workload, the same Docker Compose
   environment, the same QoS profiles. Variance comes only from the system under test,
   not from the test harness.

---

## Architecture

### Data Flow

```
DDS Applications (surgical, dashboard, ClinicalAlerts engine)
    │
    │  Monitoring Library 2.0 (per-participant, enabled via XML)
    ▼
RTI Collector Service  ──  exposes :19090/metrics (Prometheus exposition format)
    │
    │  Prometheus scrapes /metrics at configured interval
    ▼
Prometheus (time-series storage)
    │
    │  PromQL queries (rate, quantiles, aggregations over time windows)
    ▼
Performance Benchmark Harness (`tests/performance/benchmark.py`)
    │
    │  Writes / compares
    ▼
Baseline JSON (`tests/performance/baselines/<phase>.json`)
```

> **Why Prometheus instead of scraping the Collector Service directly?** The Collector
> Service's `/metrics` endpoint serves instantaneous counter and gauge values in
> Prometheus exposition format. The benchmark harness requires time-windowed
> computations — `rate()` over the 60 s measurement window, percentile aggregations,
> `sum()` across all readers — that only PromQL against Prometheus's time-series store
> can provide. The raw `/metrics` page is the *data source* that Prometheus scrapes; it
> is not a substitute for Prometheus's query engine.

### Components

| Component | Role | Already exists? |
|-----------|------|-----------------|
| Monitoring Library 2.0 | Collects per-participant metrics | Yes (Observability Standard) |
| Collector Service | Aggregates metrics; exposes `:19090/metrics` endpoint in Prometheus exposition format | Yes (Docker `--profile observability`) |
| Prometheus | Scrapes Collector Service `/metrics`; provides time-series storage and PromQL query engine | Yes (Docker `--profile observability`) |
| Benchmark harness | Orchestrates workload, queries metrics, compares baselines | **New** |
| Baseline files | Committed JSON snapshots of metric values per phase | **New** |

---

## Metrics Collected

Metrics are organized into three tiers aligned with the system's data architecture.

### Tier 1 — Latency & Timing (Safety-Critical Path)

These metrics track the `control`-tag data path where timing directly affects the
safety argument. All values are collected via Monitoring Library 2.0 and Prometheus.

| Metric ID | Description | Source | Unit |
|-----------|-------------|--------|------|
| `L1` | `OperatorInput` writer-to-reader latency (p50) | Prometheus: `dds_datareader_sample_received_latency_p50{topic="OperatorInput"}` | µs |
| `L2` | `OperatorInput` writer-to-reader latency (p99) | Prometheus: `dds_datareader_sample_received_latency_p99{topic="OperatorInput"}` | µs |
| `L3` | `RobotState` writer-to-reader latency (p50) | Prometheus: `dds_datareader_sample_received_latency_p50{topic="RobotState"}` | µs |
| `L4` | `RobotCommand` writer-to-reader latency (p50) | Prometheus: `dds_datareader_sample_received_latency_p50{topic="RobotCommand"}` | µs |
| `L5` | Routing Service input-to-output latency (p50) | Prometheus: `rti_routing_service_route_latency_p50` | µs |
| `L6` | Discovery time — last participant matched | Prometheus: computed from participant creation timestamp to last endpoint match event | ms |

### Tier 2 — Throughput & Delivery (Data Bus Health)

These metrics track whether the data bus sustains its configured publication rates and
delivers data without loss under the benchmark workload.

| Metric ID | Description | Source | Unit |
|-----------|-------------|--------|------|
| `T1` | `OperatorInput` received sample rate | Prometheus: `rate(dds_datareader_samples_received_total{topic="OperatorInput"}[30s])` | samples/s |
| `T2` | `WaveformData` received sample rate | Prometheus: `rate(dds_datareader_samples_received_total{topic="WaveformData"}[30s])` | samples/s |
| `T3` | `CameraFrame` received sample rate | Prometheus: `rate(dds_datareader_samples_received_total{topic="CameraFrame"}[30s])` | samples/s |
| `T4` | `PatientVitals` received sample rate | Prometheus: `rate(dds_datareader_samples_received_total{topic="PatientVitals"}[30s])` | samples/s |
| `T5` | Total samples lost (all topics, all readers) | Prometheus: `sum(dds_datareader_samples_lost_total)` | samples |
| `T6` | Deadline missed events (all readers) | Prometheus: `sum(dds_datareader_deadline_missed_total)` | count |

### Tier 3 — Resource & Overhead (System Impact)

These metrics track resource consumption of the DDS infrastructure itself, ensuring
that new modules or configuration changes do not degrade the system.

| Metric ID | Description | Source | Unit |
|-----------|-------------|--------|------|
| `R1` | Total DDS participant count | Prometheus: `count(dds_domainparticipant_up)` | count |
| `R2` | Total matched endpoint pairs | Prometheus: `sum(dds_datawriter_matched_subscriptions_total)` | count |
| `R3` | Peak heap memory per container (surgical) | Docker stats / cAdvisor via Prometheus | MB |
| `R4` | Peak heap memory per container (dashboard) | Docker stats / cAdvisor via Prometheus | MB |
| `R5` | Collector Service telemetry ingestion rate | Prometheus: `rate(collector_samples_received_total[30s])` | samples/s |

---

## Benchmark Workload

The benchmark runs a **standardized, repeatable workload** in the full Docker Compose
environment. The workload is defined here — not invented by the agent at runtime.

### Workload Profile

| Parameter | Value |
|-----------|-------|
| Surgical instances | 2 (OR-1, OR-3) |
| Benchmark duration | 60 seconds of steady-state operation |
| Warm-up period (excluded from metrics) | 15 seconds |
| Cool-down period (excluded from metrics) | 5 seconds |
| Total run time | 80 seconds |
| Docker Compose profile | `--profile observability` (required) |
| Prometheus scrape interval | 5 s (configured in Prometheus scrape config) |
| Environment variable | `MEDTECH_ENV=docker` |

### Workload Sequence

1. `docker compose --profile observability up -d` — start full environment
2. Wait for all health checks to pass (Cloud Discovery Service, Routing Service,
   surgical instances, dashboard, ClinicalAlerts engine, Collector Service, Prometheus)
3. Begin 15 s warm-up timer (system stabilizes, discovery completes)
4. Begin 60 s measurement window
5. At measurement end, query Prometheus for all metrics (PromQL over the 60 s window)
6. 5 s cool-down
7. `docker compose down`
8. Produce benchmark result JSON

### Result File Format

```json
{
  "version": "1.0",
  "phase": "phase-2",
  "timestamp": "2026-03-21T14:30:00Z",
  "git_commit": "abc1234",
  "environment": {
    "connext_version": "7.6.0",
    "docker_compose_profile": "observability",
    "surgical_instances": 2,
    "measurement_duration_s": 60,
    "warmup_s": 15
  },
  "metrics": {
    "L1": { "value": 850, "unit": "µs" },
    "L2": { "value": 2100, "unit": "µs" },
    "T1": { "value": 498.5, "unit": "samples/s" },
    "T5": { "value": 0, "unit": "samples" },
    "T6": { "value": 0, "unit": "count" },
    "R1": { "value": 12, "unit": "count" }
  }
}
```

---

## Regression Thresholds

These thresholds define the **maximum acceptable deviation** from the recorded baseline
for each metric tier. Deviations beyond these thresholds block the phase.

### Tier 1 — Latency Thresholds

| Metric | Allowed Regression | Rationale |
|--------|--------------------|-----------|
| `L1`–`L4` (p50 latencies) | ≤ **+20%** from baseline | p50 captures typical-case latency; 20% accounts for Docker scheduling variance while catching meaningful regressions |
| `L2` (p99 `OperatorInput`) | ≤ **+30%** from baseline | p99 tail latency is inherently more variable in Docker; wider band prevents false positives while still catching large regressions |
| `L5` (Routing Service latency) | ≤ **+25%** from baseline | Routing Service adds a hop; slightly wider tolerance for the bridge path |
| `L6` (Discovery time) | ≤ **+50%** from baseline, **hard cap 30 s** | Discovery is inherently variable in Docker networking; cap ensures it never exceeds the maximum initialization budget |

### Tier 2 — Throughput Thresholds

| Metric | Allowed Regression | Rationale |
|--------|--------------------|-----------|
| `T1`–`T4` (sample rates) | ≤ **−10%** from baseline | Throughput drops beyond 10% indicate a real delivery problem, not variance. Reliability topics should lose zero. |
| `T5` (samples lost) | ≤ baseline **+ 0.1%** of total published samples | Best-effort topics may lose samples; 0.1% is the noise floor in Docker |
| `T6` (deadline missed) | **= 0** (absolute, no deviation) | Deadline misses in steady state are never acceptable — they indicate a broken QoS contract |

### Tier 3 — Resource Thresholds

| Metric | Allowed Regression | Rationale |
|--------|--------------------|-----------|
| `R1` (participant count) | **= baseline** (exact match) | Participant count is a structural property; any change is intentional and must be reflected in an updated baseline |
| `R2` (matched endpoints) | **= baseline** (exact match) | Same reasoning as participant count |
| `R3`–`R4` (heap memory) | ≤ **+25%** from baseline | Memory can vary with allocator behavior; 25% catches leaks and unbounded growth |
| `R5` (Collector ingestion rate) | ≤ **+50%** from baseline | More participants/endpoints = more telemetry; large increases signal unexpected entity creation |

### Threshold Override Policy

These thresholds are the defaults. If an implementation phase intentionally changes
performance characteristics (e.g., adding a new module increases participant count and
memory), the implementing agent must:

1. Record a new baseline after the phase is complete and all functional tests pass
2. Document in the commit message which metrics changed and why
3. The new baseline becomes the reference for subsequent phases

Threshold overrides (changing the percentage values in this document) require **operator
approval** per the Approval Rule in [docs/agent/README.md](../README.md).

---

## Baseline Recording Policy

### When to Record

A performance baseline is recorded at the completion of each implementation phase,
**after all functional tests and quality gates pass**. The baseline captures the
system's performance at that known-good state.

| Event | Action |
|-------|--------|
| Phase completion (all test gates green) | Run benchmark → record baseline → commit `tests/performance/baselines/<phase>.json` |
| V1.0.0 Release Gate | Run benchmark → record final V1.0.0 baseline → commit as `tests/performance/baselines/v1.0.0.json` |
| Milestone version cut (V1.1, V2.0, V3.0) | Run benchmark → record milestone baseline |
| Intentional performance-affecting change mid-phase | Run benchmark → record updated baseline with justification in commit message |

### Baseline Comparison

Every benchmark run compares its results against the **most recent committed baseline**.
The comparison produces a pass/fail verdict per metric:

- **PASS** — metric is within the allowed deviation of its baseline value
- **FAIL** — metric exceeds the allowed deviation
- **NEW** — metric has no baseline value (first measurement or new metric added)
- **REMOVED** — baseline contains a metric not present in the current run (structural change)

The benchmark exits with a non-zero status if any metric is **FAIL**. **NEW** and
**REMOVED** produce warnings but do not fail the run — they indicate structural
changes that should be reviewed and baselined.

### Baseline File Management

- Baseline files are committed to `tests/performance/baselines/` and tracked in version
  control. They are never deleted (same policy as tests).
- The file naming convention is `<phase-or-version>.json` (e.g., `phase-1.json`,
  `phase-2.json`, `v1.0.0.json`).
- The benchmark harness always compares against the **lexicographically latest** baseline
  file unless a specific baseline is passed via command-line argument.
- Historical baselines enable trend analysis across the project lifecycle.

---

## Integration with Existing Infrastructure

### Observability Stack Dependency

The benchmark requires the observability Docker Compose profile (`--profile observability`).
This is the only context in which Prometheus is running. The benchmark harness is not a
substitute for the observability stack — it is a consumer of it.

If the observability stack is not available (e.g., Prometheus is not running), the benchmark
exits with an error and a clear message. It does not attempt to collect metrics through
alternative means.

### Prometheus Query Interface

The benchmark harness queries Prometheus via its HTTP API (`/api/v1/query` and
`/api/v1/query_range`). The Prometheus endpoint URL is configured via environment
variable:

```bash
export PROMETHEUS_URL="http://localhost:9090"
```

Docker Compose sets this for the benchmark container. Local development points to the
forwarded Prometheus port.

### No Application Code Changes

The benchmark collects all metrics from Monitoring Library 2.0 telemetry that is already
published by every participant. **No application code is modified to support benchmarking.**
The benchmark is a pure observer — it reads from Prometheus, not from DDS.

---

## Benchmark Harness

### Location

```
tests/performance/
├── benchmark.py              # Main harness: orchestrate, measure, compare, report
├── metrics.py                # Metric definitions and PromQL query templates
├── baselines/                # Committed baseline JSON files
│   └── .gitkeep
└── conftest.py               # pytest fixtures for performance tests
```

### Interface

```bash
# Run benchmark and compare against latest baseline
python tests/performance/benchmark.py

# Run benchmark and record a new baseline
python tests/performance/benchmark.py --record --phase phase-2

# Run benchmark against a specific baseline
python tests/performance/benchmark.py --baseline tests/performance/baselines/phase-1.json

# Run as part of pytest (tagged @benchmark)
pytest tests/performance/ -m benchmark
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All metrics within thresholds |
| 1 | One or more metrics exceed regression thresholds |
| 2 | Infrastructure error (Prometheus unreachable, Docker not running, etc.) |

---

## Change Management Integration

### Phase Completion Workflow

The existing phase completion workflow (run tests → commit → record baseline) is
extended with a performance baseline step:

1. All functional test gates pass
2. All quality gates pass (workflow.md Section 7)
3. Run performance benchmark: `python tests/performance/benchmark.py --record --phase <phase>`
4. Review benchmark results — all metrics within thresholds of prior baseline (or no prior baseline if this is Phase 1)
5. Commit the baseline file alongside the phase completion commit
6. The committed baseline becomes the reference for the next phase

### Mid-Phase Performance Check

Agents are encouraged (but not required) to run the benchmark mid-phase to catch
regressions early. Mid-phase runs compare against the latest committed baseline
but do not produce a new baseline file. A mid-phase regression should be investigated
before proceeding — it may indicate an implementation approach that will fail at
the phase gate.

### Rearchitecture and Migration

When a change intentionally affects performance (e.g., adding a new domain, changing
transport configuration, upgrading Connext version):

1. Run benchmark **before** the change against the current baseline → record as
   `pre-<change-description>.json`
2. Implement the change
3. Run benchmark **after** the change
4. If metrics regress beyond thresholds, evaluate whether the regression is acceptable
   for the architectural benefit gained
5. If acceptable, record a new baseline with justification in the commit message
6. If not acceptable, iterate on the implementation until metrics are within bounds
   or escalate to the operator per workflow.md Section 5

---

## Stress Testing (V1.1+)

The performance baseline framework above measures regression under a **standard
workload** (2 ORs, 60 s steady state). It answers: "did this change make the system
slower?" It does not answer: "how far can this system be pushed?"

Stress testing extends the same infrastructure (Prometheus + benchmark harness +
Docker Compose) with **non-standard workloads** designed to find limits, expose
failure modes, and validate fault tolerance. Stress testing is planned for V1.1
or V2.0 — after the baseline framework is proven in V1.0.

### Planned Stress Test Categories

| Category | Workload | What It Validates |
|----------|----------|-------------------|
| **Scale-up** | 8–16 concurrent surgical instances (`docker compose up --scale surgical=N`) | Discovery time scaling, participant count limits, Routing Service throughput under fan-in, memory growth per instance |
| **Publication burst** | 10× normal rate on select topics (OperatorInput at 5000 Hz, WaveformData at 500 Hz) | Transport saturation behavior, sample loss under overload, QoS differentiation (do State/Command topics survive while Stream topics degrade gracefully?) |
| **Network degradation** | Introduce packet loss (1%, 5%, 10%) and latency (50 ms, 100 ms) on Docker networks via `tc netem` | RELIABLE QoS recovery under loss, BEST_EFFORT graceful degradation, TRANSIENT_LOCAL durability under impairment, deadline miss behavior |
| **Component failure cascade** | Sequentially kill surgical instance → Routing Service → Cloud Discovery Service, then restart in reverse | Dashboard resilience (no crash, cached data served), ClinicalAlerts engine recovery, discovery re-convergence timing, TRANSIENT_LOCAL re-delivery |
| **Long-duration soak** | Standard workload (2 ORs) running for 4–8 hours | Memory leaks, handle/resource exhaustion, user log forwarding volume growth, Prometheus storage scaling, Collector Service stability |

### Implementation Approach

Stress tests will reuse the existing benchmark harness (`tests/performance/benchmark.py`)
with extended workload profiles. New components:

- `tests/stress/` directory for stress-specific test scripts and workload definitions
- Docker Compose override files (`docker-compose.stress.yml`) for scaled and degraded
  configurations
- `tc netem` wrapper scripts for reproducible network impairment
- Extended Prometheus query templates for stress-specific metrics (e.g., peak sample
  loss rate, maximum discovery time across N instances)
- Wider regression thresholds — stress tests measure limits, not steady-state precision

### Prerequisites

Stress testing requires the V1.0 system to be complete and the standard benchmark
baseline to be recorded. Scale-up tests require the Docker Compose configuration to
support service scaling. Network degradation tests require `tc` (iproute2) to be
available in the Docker containers or on the Docker host.

### Value

- **Credibility:** Quantitative evidence of the system's operational envelope —
  "this system handles 16 concurrent ORs with < 5% latency increase"
- **Limit discovery:** Identifies the breaking point before a customer or evaluator
  finds it
- **Fault tolerance validation:** Proves that the DDS QoS contracts (reliability,
  durability, liveliness, ownership failover) work under adverse conditions, not
  just in ideal Docker networking
- **Regression safety net:** Catches performance cliffs that incremental 2-OR
  benchmarks would miss
