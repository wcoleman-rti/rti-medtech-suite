# Simulation Model

The medtech suite is a demonstration system — no physical devices or real patients
exist. All data originates from software simulators. Because the system exists to
demonstrate RTI Connext in a medtech context, the quality of the simulation directly
affects the credibility and usefulness of the demonstration.

This document defines the simulation fidelity requirements that all data-generating
modules must satisfy.

---

## Principles

### 1. Non-Deterministic but Realistic

Simulators must produce data that is **non-deterministic** (different on every run by
default) but **physiologically and mechanically plausible**. A purely random number
generator with bounds is insufficient — it produces data that no clinician or engineer
would recognize as realistic.

- **Non-deterministic:** Each run produces a different data trajectory. Two runs of the
  same scenario profile should show the same *character* (e.g., "hemorrhage onset") but
  different specific values.
- **Realistic:** Signal values respect physiological and mechanical constraints. Values
  are temporally correlated (signals trend, they don't jump). Cross-signal relationships
  hold (when blood pressure drops, heart rate compensates upward). Noise is present but
  bounded and realistic in character.

### 2. Seeded Reproducibility

All simulators accept a configurable random seed via the `MEDTECH_SIM_SEED` environment
variable:

| Value | Behavior |
|-------|----------|
| Unset or empty | System entropy (non-deterministic — default for demos and normal operation) |
| Integer value (e.g., `42`) | Deterministic run — identical output for the same seed and scenario profile |

Seeded mode exists for **debugging and test reproducibility**. Tests tagged `@unit` may
use fixed seeds for deterministic assertions. Integration and end-to-end tests should
use the default non-deterministic mode unless a specific scenario requires
reproducibility.

### 3. Scenario Profiles

Simulators support named **scenario profiles** that drive coordinated, clinically
meaningful data trajectories. The active profile is selected via the
`MEDTECH_SIM_PROFILE` environment variable.

Each profile defines:

- **Signal trajectories** — the target behavior of each vital sign, device parameter,
  or robot state over time
- **Cross-signal correlations** — how changes in one signal affect related signals
- **Event timing** — when state transitions occur (approximate, with jitter)
- **Noise model** — the character and amplitude of per-signal noise

#### Required Profiles (V1.0)

| Profile | Description | Primary Signals Affected |
|---------|-------------|--------------------------|
| `stable` | Normal operation. All vitals in healthy ranges with natural variation. Robot operates nominally. No alarms triggered. | All — baseline healthy values |
| `normal_variation` | Mild, realistic fluctuations around normal ranges. Occasional boundary approaches but no threshold crossings. Useful for verifying GUI rendering and data flow without alarm noise. | PatientVitals, DeviceTelemetry |
| `hemorrhage_onset` | Gradual blood loss scenario. SBP trends downward over 2–5 minutes. HR compensates upward. SpO2 declines with delay. Hemorrhage risk score crosses CRITICAL threshold. | PatientVitals (SBP, HR, SpO2), RiskScore |
| `sepsis_progression` | Slow-onset sepsis early warning. Temperature rises gradually. HR elevates. Respiratory rate increases. WBC (if modeled) elevates. Multiple vitals contribute to risk without any single alarm triggering first. | PatientVitals (temp, HR, RR) |
| `cardiac_event` | Acute cardiac event. HR spikes rapidly above alarm threshold (>120 bpm). ST segment changes in ECG waveform. Immediate alarm triggering. | PatientVitals (HR), WaveformData (ECG), AlarmMessages |
| `device_fault` | Device malfunction. One device telemetry stream degrades (noisy readings, then flatline). Liveliness eventually lost. Tests failover via exclusive ownership. | DeviceTelemetry |
| `robot_estop` | Safety interlock activation. Robot receives e-stop during operation. Tests safety response path and state transitions. | SafetyInterlock, RobotState, RobotCommand |

Additional profiles may be added for V1.1+ scenarios (e.g., `recording_replay_demo`,
`multi_patient_stress`). Custom profiles can be defined via configuration file.

### 4. Temporal Realism — Signals Trend, Not Jump

Physiological signals in the real world change continuously and smoothly (at the
timescale of publication). Simulators must model this:

- **Moving-state model:** Each signal has a current value, a target value (set by the
  scenario profile), and a convergence rate. The current value moves toward the target
  over multiple publication cycles, not in a single step.
- **Noise overlay:** Per-cycle noise is added after the trend computation. Noise
  amplitude is signal-specific and clinically appropriate (e.g., HR noise ±2 bpm,
  SBP noise ±3 mmHg).
- **No discontinuities without cause:** A signal may only jump (change by more than
  3× its normal noise amplitude in a single cycle) if the scenario profile explicitly
  models an acute event (e.g., cardiac arrest, device failure). The jump must be
  documented in the profile definition.

### 5. Cross-Signal Correlation

Vital signs are physiologically coupled. Simulators must enforce these relationships:

| Primary Change | Correlated Response | Delay |
|---------------|---------------------|-------|
| SBP decreases (hemorrhage) | HR increases (baroreceptor reflex) | 1–3 s |
| SBP decreases significantly (< 80 mmHg) | SpO2 begins declining | 10–30 s |
| Temperature rises (infection) | HR increases (~10 bpm per °C) | Concurrent |
| Respiratory rate decreases (sedation) | SpO2 decreases | 5–15 s |
| HR spike (arrhythmia) | SBP may become erratic | Concurrent |

These correlations are modeled as soft constraints — the simulator enforces the
direction and approximate magnitude of the response, with noise and individual
variation. They are not rigid formulas.

---

## Publication Model Integration

Simulators must follow the publication model defined in
[data-model.md — Publication Model](data-model.md). In particular:

- **Write-on-change topics** (`ProcedureContext`, `ProcedureStatus`, `AlarmMessages`,
  `DeviceTelemetry`, `SafetyInterlock`) should only publish when the simulated state
  actually changes. The scenario profile's convergence rate and noise model may cause
  state to "settle" — during settlement, no new samples are published.
- **Continuous-stream topics** (`OperatorInput`, `RobotState`, `WaveformData`,
  `CameraFrame`) publish at their configured fixed rate regardless of whether the
  value has changed — these represent real-time data feeds.
- **Periodic-snapshot topics** (`PatientVitals`) publish at their configured rate.
  Every sample reflects the current simulated state (which trends continuously per
  Section 4 above).

---

## Implementation Guidance

### Simulator Architecture

Each simulator module should implement these components:

1. **Signal model** — maintains current state, target state, convergence rate, and
   noise parameters for each simulated signal
2. **Profile engine** — reads the active scenario profile and schedules target-state
   transitions (including cross-signal correlations)
3. **Publication driver** — decides when to call `write()` based on the topic's
   publication model (fixed-rate, on-change, or periodic-snapshot)
4. **PRNG** — a seeded pseudorandom number generator (Python: `random.Random(seed)`;
   C++: `std::mt19937` with seed) used for all stochastic aspects (noise, jitter,
   variation)

### Configuration

| Environment Variable | Type | Default | Description |
|---------------------|------|---------|-------------|
| `MEDTECH_SIM_SEED` | Integer or empty | (empty — system entropy) | Random seed for reproducibility |
| `MEDTECH_SIM_PROFILE` | String | `stable` | Active scenario profile name |

Profile definitions beyond the built-in set may be loaded from a JSON configuration
file at `config/sim-profiles/<profile-name>.json`. The file format will be defined
during Phase 2 implementation.

---

## Relationship to Other Documents

- **[data-model.md](data-model.md)** — defines topics, types, and QoS that simulators
  publish on. The Publication Model section defines when to write.
- **[spec/surgical-procedure.md](../spec/surgical-procedure.md)** — spec scenarios
  reference simulated data (vitals rates, alarm thresholds). Scenario profiles must
  produce data that exercises these spec scenarios.
- **[spec/clinical-alerts.md](../spec/clinical-alerts.md)** — the ClinicalAlerts engine
  consumes simulated vitals. Scenario profiles like `hemorrhage_onset` must produce vitals
  that exercise the risk scoring and alert pathways.
- **[performance-baseline.md](performance-baseline.md)** — benchmark workloads use the
  `stable` profile to provide consistent, low-event-rate background data.
