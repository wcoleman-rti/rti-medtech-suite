# Spec: Performance Baseline

Behavioral specifications for the performance baseline framework: benchmark harness
execution, Prometheus metric collection, baseline recording, regression detection,
and threshold enforcement.

The performance baseline framework is defined in
[vision/performance-baseline.md](../vision/performance-baseline.md). All metric IDs,
threshold percentages, workload parameters, and file formats referenced here are
authoritative values from that document.

---

## Summary of Concrete Requirements

| Requirement | Value |
|-------------|-------|
| Benchmark workload — surgical instances | 2 (OR-1, OR-3) |
| Benchmark measurement duration | 60 s steady-state |
| Benchmark warm-up period (excluded) | 15 s |
| Benchmark cool-down period (excluded) | 5 s |
| Benchmark total run time | 80 s |
| Docker Compose profile required | `--profile observability` |
| Prometheus scrape interval | 5 s |
| Tier 1 p50 latency regression threshold | ≤ +20% from baseline |
| Tier 1 p99 latency regression threshold (`L2`) | ≤ +30% from baseline |
| Tier 1 Routing Service latency threshold (`L5`) | ≤ +25% from baseline |
| Tier 1 discovery time threshold (`L6`) | ≤ +50% from baseline, hard cap 30 s |
| Tier 2 throughput regression threshold | ≤ −10% from baseline |
| Tier 2 samples lost tolerance (`T5`) | ≤ baseline + 0.1% of total published |
| Tier 2 deadline missed events (`T6`) | = 0 (absolute) |
| Tier 3 participant count (`R1`) | = baseline (exact) |
| Tier 3 matched endpoints (`R2`) | = baseline (exact) |
| Tier 3 heap memory regression threshold | ≤ +25% from baseline |
| Tier 3 Collector ingestion rate threshold (`R5`) | ≤ +50% from baseline |
| Baseline recording trigger | Phase completion (all test gates green) |
| Baseline file location | `tests/performance/baselines/<phase>.json` |
| Benchmark exit code — all pass | 0 |
| Benchmark exit code — regression detected | 1 |
| Benchmark exit code — infrastructure error | 2 |

*This table must be updated whenever a concrete value in the scenarios below is added
or changed.*

---

## Benchmark Execution

### Scenario: Benchmark harness runs standard workload `@e2e` `@benchmark`

**Given** the full Docker Compose environment is running with `--profile observability`
**And** 2 surgical instances (OR-1, OR-3), Routing Service, Dashboard, ClinicalAlerts engine,
Collector Service, and Prometheus are healthy
**When** the benchmark harness is executed
**Then** the harness waits 15 s for warm-up (excluded from measurement)
**And** collects metrics over a 60 s measurement window
**And** waits 5 s for cool-down
**And** produces a benchmark result containing all defined metrics (L1–L6, T1–T6, R1–R5)

### Scenario: Benchmark fails if observability stack is unavailable `@e2e` `@benchmark`

**Given** the Docker Compose environment is running without `--profile observability`
**When** the benchmark harness is executed
**Then** the harness exits with code 2
**And** logs an error message indicating Prometheus is unreachable

### Scenario: Benchmark harness queries Prometheus for all metrics `@e2e` `@benchmark`

**Given** the observability stack is running and receiving telemetry
**And** the measurement window has completed
**When** the harness queries Prometheus
**Then** PromQL queries are executed for all metrics (L1–L6, T1–T6, R1–R5)
**And** each query uses the measurement window time range (excluding warm-up and cool-down)
**And** the result for each metric is a single scalar value

### Scenario: Benchmark produces valid result JSON `@unit` `@benchmark`

**Given** all metric values have been collected from Prometheus
**When** the harness writes the result file
**Then** the JSON contains `version`, `phase`, `timestamp`, `git_commit`, `environment`,
and `metrics` fields
**And** every metric in `metrics` has a `value` (numeric) and `unit` (string)
**And** the `git_commit` matches the current HEAD commit hash
**And** the `timestamp` is in ISO 8601 format

---

## Baseline Recording

### Scenario: Baseline is recorded on demand `@e2e` `@benchmark`

**Given** the benchmark harness has completed a successful run
**When** the `--record --phase <phase>` flags are provided
**Then** the result JSON is written to `tests/performance/baselines/<phase>.json`
**And** the file is suitable for committing to version control

### Scenario: Baseline file is not overwritten without explicit flag `@unit` `@benchmark`

**Given** a baseline file `tests/performance/baselines/phase-2.json` already exists
**When** the benchmark harness is run without `--record`
**Then** the existing baseline file is not modified
**And** the harness compares the current run against the existing baseline

### Scenario: First benchmark run with no prior baseline `@e2e` `@benchmark`

**Given** no baseline files exist in `tests/performance/baselines/`
**When** the benchmark harness is run without `--record`
**Then** all metrics are reported with status NEW
**And** the harness exits with code 0 (no failure — there is nothing to regress against)
**And** a warning is logged indicating no baseline exists for comparison

---

## Regression Detection — Tier 1 (Latency)

### Scenario: p50 latency within threshold passes `@unit` `@benchmark`

**Given** the baseline records `L1` (OperatorInput p50 latency) as 850 µs
**When** the current run measures `L1` as 1000 µs (+17.6%)
**Then** `L1` is reported as PASS (within the +20% threshold)

### Scenario: p50 latency exceeding threshold fails `@unit` `@benchmark`

**Given** the baseline records `L1` as 850 µs
**When** the current run measures `L1` as 1050 µs (+23.5%)
**Then** `L1` is reported as FAIL
**And** the report includes the baseline value, current value, percentage change,
and the allowed threshold (+20%)
**And** the benchmark exits with code 1

### Scenario: p99 latency uses wider threshold `@unit` `@benchmark`

**Given** the baseline records `L2` (OperatorInput p99 latency) as 2100 µs
**When** the current run measures `L2` as 2700 µs (+28.6%)
**Then** `L2` is reported as PASS (within the +30% threshold)

### Scenario: Discovery time within threshold passes `@unit` `@benchmark`

**Given** the baseline records `L6` (discovery time) as 4000 ms
**When** the current run measures `L6` as 5800 ms (+45%)
**Then** `L6` is reported as PASS (within the +50% threshold)

### Scenario: Discovery time exceeding hard cap fails regardless of percentage `@unit` `@benchmark`

**Given** the baseline records `L6` as 4000 ms
**When** the current run measures `L6` as 31000 ms (+675%)
**Then** `L6` is reported as FAIL due to exceeding the 30 s hard cap
**And** the fail reason states "exceeds hard cap of 30000 ms"

---

## Regression Detection — Tier 2 (Throughput)

### Scenario: Throughput within threshold passes `@unit` `@benchmark`

**Given** the baseline records `T1` (OperatorInput rate) as 498.5 samples/s
**When** the current run measures `T1` as 460 samples/s (−7.7%)
**Then** `T1` is reported as PASS (within the −10% threshold)

### Scenario: Throughput drop exceeding threshold fails `@unit` `@benchmark`

**Given** the baseline records `T1` as 498.5 samples/s
**When** the current run measures `T1` as 440 samples/s (−11.7%)
**Then** `T1` is reported as FAIL
**And** the report includes baseline, current, percentage change, and threshold (−10%)
**And** the benchmark exits with code 1

### Scenario: Zero deadline misses in steady state `@unit` `@benchmark`

**Given** the baseline records `T6` (deadline missed) as 0
**When** the current run measures `T6` as 1
**Then** `T6` is reported as FAIL (absolute threshold: must be 0)

### Scenario: Sample loss within noise floor passes `@unit` `@benchmark`

**Given** the baseline records `T5` (samples lost) as 0
**And** the total samples published during the run is 100000
**When** the current run measures `T5` as 50 (0.05% of published)
**Then** `T5` is reported as PASS (within 0.1% tolerance)

---

## Regression Detection — Tier 3 (Resources)

### Scenario: Participant count must match baseline exactly `@unit` `@benchmark`

**Given** the baseline records `R1` (participant count) as 12
**When** the current run measures `R1` as 13
**Then** `R1` is reported as FAIL (exact match required)

### Scenario: Memory within threshold passes `@unit` `@benchmark`

**Given** the baseline records `R3` (surgical container heap) as 128 MB
**When** the current run measures `R3` as 155 MB (+21.1%)
**Then** `R3` is reported as PASS (within +25% threshold)

### Scenario: Memory exceeding threshold fails `@unit` `@benchmark`

**Given** the baseline records `R3` as 128 MB
**When** the current run measures `R3` as 170 MB (+32.8%)
**Then** `R3` is reported as FAIL
**And** the report includes baseline, current, percentage, and threshold (+25%)

---

## Structural Changes

### Scenario: New metric not in baseline is reported as NEW `@unit` `@benchmark`

**Given** the current run collects a metric `R6` that does not exist in the baseline
**When** the comparison is performed
**Then** `R6` is reported as NEW
**And** the benchmark does not fail due to a NEW metric

### Scenario: Baseline metric missing from current run is reported as REMOVED `@unit` `@benchmark`

**Given** the baseline contains a metric `R6` that is not collected in the current run
**When** the comparison is performed
**Then** `R6` is reported as REMOVED
**And** the benchmark does not fail due to a REMOVED metric
**And** a warning is logged that the metric was expected but not found

---

## Phase Gate Integration

### Scenario: Benchmark runs as part of phase completion `@e2e` `@benchmark`

**Given** all functional test gates for the current phase have passed
**And** all quality gates from workflow.md Section 7 have passed
**When** the implementing agent runs the benchmark with `--record --phase <current-phase>`
**Then** a baseline file is produced at `tests/performance/baselines/<current-phase>.json`
**And** the file is committed alongside the phase completion commit

### Scenario: Benchmark regression blocks phase completion `@e2e` `@benchmark`

**Given** a prior baseline exists
**When** the benchmark is run at phase completion and one or more metrics fail
**Then** the phase is not considered complete
**And** the implementing agent must resolve the regression (fix the code or obtain
operator approval for a new baseline) before proceeding
