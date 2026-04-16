# Spec: Surgical Procedure Module

Behavioral specifications for a single surgical procedure instance covering robot teleop, patient vitals, camera feed, procedure context, and device telemetry.

All scenarios assume the participant operates within a DomainParticipant partition (e.g., `room/OR-3/procedure/proc-001`) unless stated otherwise.

---

## Summary of Concrete Requirements

| Requirement | Value |
|-------------|-------|
| `OperatorInput` publication rate | 500 Hz (one sample every 2 ms) |
| Digital twin display rendering frame rate | 60 Hz |
| Digital twin time-based filter minimum separation | ~16 ms |
| `OperatorInput` end-to-end delivery deadline | ≤ 4 ms |
| `OperatorInput` lifespan (stale discard threshold) | 20 ms |
| `RobotState` publication rate | 100 Hz (one sample every 10 ms) |
| `RobotState` deadline (DDS Deadline QoS) | 20 ms — enforced on both writer and reader |
| `RobotFrameTransform` publication rate | 100 Hz (one sample every 10 ms) — V1.1 |
| `RobotFrameTransform` deadline (DDS Deadline QoS) | 20 ms — enforced on both writer and reader (V1.1) |
| `SafetyInterlock` response — robot reaches safe-stopped state | ≤ 40 ms after receiving interlock sample |
| `SafetyInterlock` liveliness lease | 500 ms — writer health detection via `LivelinessSafety` snippet |
| `PatientVitals` publication rate | 1 Hz |
| `PatientVitals` deadline | 2 s |
| `WaveformData` sample rate (ECG) | 500 Sa/s; published in 10-sample blocks at 50 Hz |
| `WaveformData` deadline (DDS Deadline QoS) | 40 ms — enforced on both writer and reader |
| `AlarmMessages` — HR HIGH alarm threshold | HR ≥ 120 bpm |
| `CameraFrame` publication rate | 30 Hz |
| `CameraFrame` deadline (DDS Deadline QoS) | 66 ms — enforced on both writer and reader |
| `DeviceTelemetry` publication model | Write-on-change (publish on state transition, fault, or mode change — not periodic) |
| Device gateway liveliness lease | 2 s |
| Procedure system initialization — all participants matched | ≤ 5 s from last component start on the room network (`{room}-net`) |
| Procedure system initialization — initial TRANSIENT_LOCAL state received | ≤ 5 s from last component start (included in initialization budget) |
| Restarted component re-integration | ≤ 5 s to re-match all endpoints and receive TRANSIENT_LOCAL state |
| `ProcedureStatus` durability | TRANSIENT_LOCAL — late joiners receive current status immediately |
| Simulator default seed | System entropy (non-deterministic) — configurable via `MEDTECH_SIM_SEED` |
| Simulator default profile | `stable` — configurable via `MEDTECH_SIM_PROFILE` |
| Vitals cross-signal: SBP drop → HR compensation | HR increases within 1–3 s of SBP decrease |
| Vitals temporal model | Values trend toward targets over multiple publication cycles — no discontinuities without modeled cause |

*This table must be updated whenever a concrete value in the scenarios below is added or changed.*

---

## Robot Teleop & Control (Procedure DDS domain — `control` tag)

### Scenario: Operator input reaches robot controller within deadline `@integration` `@streaming`

**Given** an operator console publishing `OperatorInput` on the Procedure control databus with the `TopicProfiles::OperatorInput` QoS profile (Stream pattern + DeadlineOperatorInput + LifespanOperatorInput)
**And** a robot controller subscribing to `OperatorInput` on the Procedure control databus in the same partition with the same `TopicProfiles::OperatorInput` QoS profile
**When** the operator publishes a control input sample
**Then** the robot controller receives the sample within 4 ms of publication
**And** the 4 ms threshold is enforced by DDS Deadline QoS (not only measured by the test harness) — a `REQUESTED_DEADLINE_MISSED` status on the reader indicates a stream interruption

### Scenario: Robot state is published at configured rate `@integration`

**Given** a robot controller publishing `RobotState` on the Procedure control databus with `State` QoS
**When** the robot is operational
**Then** `RobotState` samples are published at 100 Hz (one sample every 10 ms)
**And** each sample contains the current joint positions, operational mode, and error state

### Scenario: Safety interlock halts robot on violation `@integration`

**Given** a robot controller subscribed to `SafetyInterlock` on the Procedure control databus
**And** the robot is in operational mode
**When** a `SafetyInterlock` sample with `interlock_active = true` is received
**Then** the robot transitions to a safe-stopped state within 40 ms of receiving the interlock sample
**And** a `RobotState` sample with mode `EMERGENCY_STOP` is published

### Scenario: Stale operator input is not applied `@integration` `@command`

**Given** an operator console publishing `OperatorInput` with `LifespanOperatorInput` snippet (lifespan = 20 ms)
**When** the robot controller reads a sample older than 20 ms
**Then** the sample is discarded by DDS before delivery and is not applied to the robot control loop

### Scenario: Robot command delivery is strictly reliable `@integration` `@command`

**Given** an operator console publishing `RobotCommand` with `Command` QoS (RELIABLE, VOLATILE, KEEP_LAST 1)
**When** a command sample is published
**Then** the robot controller receives the command exactly once
**And** commands are delivered in publication order

---

## Patient Vitals (Procedure DDS domain — `clinical` tag)

### Scenario: Vitals snapshot is published periodically `@integration`

**Given** a bedside monitor simulator publishing `PatientVitals` on the Procedure clinical databus with `State` QoS
**When** the simulation is running
**Then** `PatientVitals` samples are published at 1 Hz (one sample per second)
**And** each sample contains measurements for HR, SpO2, BP, temperature, and respiratory rate

### Scenario: Waveform data streams at configured frequency `@integration` `@streaming`

**Given** a bedside monitor simulator publishing `WaveformData` on the Procedure clinical databus with `Stream` QoS
**When** ECG waveform generation is active
**Then** waveform sample blocks are published at 50 Hz
**And** each block contains 10 samples (ECG sampled at 500 Sa/s)

### Scenario: Alarm is raised when vital exceeds threshold `@unit`

**Given** the alarm evaluation logic has HR HIGH threshold set to ≥ 120 bpm
**When** a `PatientVitals` sample contains HR = 135 bpm
**Then** an `AlarmMessages` sample is published containing an alarm with severity HIGH and an appropriate alarm code

### Scenario: Alarm clears when vital returns to normal `@unit`

**Given** an active HIGH alarm (triggered at HR ≥ 120 bpm)
**When** a subsequent `PatientVitals` sample contains HR = 85 bpm
**Then** the alarm transitions to CLEARED state in the next `AlarmMessages` publication

### Scenario: Late-joining subscriber receives current vitals `@integration` `@durability`

**Given** a bedside monitor has been publishing `PatientVitals` with TRANSIENT_LOCAL durability
**When** a new subscriber joins the Procedure DDS domain in the same partition
**Then** the subscriber immediately receives the most recent `PatientVitals` sample without waiting for the next publication cycle

---

## Camera Feed (Procedure DDS domain — `operational` tag)

### Scenario: Camera frame metadata is published at configured rate `@integration` `@streaming`

**Given** a camera simulator publishing `CameraFrame` on the Procedure operational databus with `Stream` QoS
**When** the camera is active
**Then** `CameraFrame` samples are published at 30 Hz
**And** each sample contains camera ID, frame sequence number, timestamp, resolution, and image reference

### Scenario: Camera feed uses best-effort delivery for live display `@integration` `@streaming`

**Given** a camera subscriber using `Stream` QoS (BEST_EFFORT)
**When** transient network congestion causes frame loss
**Then** the subscriber continues displaying the most recent received frame without stalling
**And** no retransmission backlog accumulates

---

## Procedure Context (Procedure DDS domain — `operational` tag)

### Scenario: Procedure context is published at startup `@integration`

**Given** a surgical procedure instance starting in room OR-3
**When** the procedure application initializes
**Then** a `ProcedureContext` sample is published containing hospital, room (OR-3), bed, patient ID, procedure type, surgeon, and start time

### Scenario: Procedure context is durable for late joiners `@integration` `@durability`

**Given** a `ProcedureContext` sample has been published with TRANSIENT_LOCAL durability
**When** a new subscriber joins the Procedure DDS domain in the same partition after the initial publication
**Then** the subscriber receives the `ProcedureContext` sample immediately

### Scenario: Procedure context update reflects changes `@integration`

**Given** a published `ProcedureContext` for an active procedure
**When** the procedure metadata is updated (e.g., additional surgeon joins)
**Then** a new `ProcedureContext` sample is published with the updated information
**And** subscribers see the updated context as the current state (KEEP_LAST 1)

### Scenario: Procedure status is published and durable `@integration` `@durability`

**Given** a surgical procedure instance publishing `ProcedureStatus` on the Procedure operational databus with `State` QoS
**When** the procedure is active
**Then** `ProcedureStatus` samples are published with the current running status (in-progress, completing, alert)
**And** a late-joining subscriber receives the most recent `ProcedureStatus` immediately via TRANSIENT_LOCAL durability

### Scenario: Procedure status transitions through lifecycle `@integration`

**Given** a surgical procedure instance publishing `ProcedureStatus`
**When** the procedure progresses from in-progress to completing
**Then** a new `ProcedureStatus` sample is published with status "completing"
**And** subscribers see the updated status as the current state (KEEP_LAST 1)

---

## Device Telemetry (Procedure DDS domain — `clinical` tag)

### Scenario: Device telemetry is published for each simulated device `@integration`

**Given** simulated devices (infusion pump, anesthesia machine) in the surgical procedure
**When** the simulation is running
**Then** each device publishes `DeviceTelemetry` on state change (write-on-change publication model per `vision/data-model.md`)
**And** each sample is keyed by `device_id` and contains device-type-specific status fields
**And** a stable device (no parameter changes, no faults) does not produce periodic samples
**And** writer health is detectable via liveliness QoS (2 s lease), not via sample arrival rate

### Scenario: Device telemetry supports exclusive ownership failover `@integration` `@failover`

**Given** a primary device gateway publishing `DeviceTelemetry` with ownership strength 100
**And** a backup device gateway publishing the same instance with ownership strength 50
**When** the primary gateway becomes unresponsive (liveliness lost)
**Then** subscribers begin receiving from the backup gateway automatically
**And** no application-level failover logic is required

---

## Digital Twin Display (Procedure DDS domain — `control` tag)

### Scenario: Digital twin renders current robot state `@integration` `@gui`

**Given** a digital twin display subscribed to `RobotState` on the Procedure control databus in the same partition as the robot controller
**When** the robot controller publishes a `RobotState` sample
**Then** the display updates the 2D robot visualization to reflect the current joint positions, tool-tip location, and operational mode

### Scenario: Digital twin displays active command `@integration` `@gui`

**Given** a digital twin display subscribed to `RobotCommand` on the Procedure control databus
**When** a `RobotCommand` sample is received
**Then** the display renders the active command as a visual annotation (target position, motion trajectory indicator)

### Scenario: Digital twin shows safety interlock status `@integration` `@gui`

**Given** a digital twin display subscribed to `SafetyInterlock` on the Procedure control databus
**When** a `SafetyInterlock` sample with `interlock_active = true` is received
**Then** the display renders a prominent interlock indicator (red overlay, status text)
**And** the robot visualization shows the arm in its safe-stopped pose

### Scenario: Digital twin downsamples to rendering frame rate `@integration` `@gui`

**Given** a digital twin display with a rendering frame rate of 60 Hz
**And** the robot controller publishes `RobotState` at 100 Hz
**When** the display is running
**Then** the DataReader uses a time-based filter with minimum separation matching the frame interval (~16 ms)
**And** the display processes no more than 60 updates per second

### Scenario: Digital twin receives state on late join `@integration` `@durability` `@gui`

**Given** a robot controller has been publishing `RobotState` with TRANSIENT_LOCAL durability
**When** the digital twin display starts and joins the Procedure DDS domain in the same partition
**Then** the display immediately receives the most recent `RobotState` sample
**And** the robot visualization renders in the correct pose without waiting for the next publication cycle

### Scenario: Digital twin detects robot disconnect `@integration` `@gui`

**Given** a digital twin display subscribed to `RobotState` with a liveliness lease of 2 s
**When** the robot controller becomes unresponsive and liveliness expires
**Then** the display renders the robot in a disconnected state (grayed out, "DISCONNECTED" label)

### Scenario: Digital twin does not block on DDS reads `@integration` `@gui`

**Given** a digital twin display receiving data from multiple `control`-tag topics at high rates
**When** the display is running
**Then** DDS reads use polling (`take()`/`read()`) on the UI thread or worker-thread dispatch — the mechanism is not prescribed, but the UI thread must never block on DDS operations
**And** frame rendering remains smooth at the target frame rate

---

## Digital Twin Visual Modernization

### Scenario: Digital twin uses glassmorphism for HUD overlays `@gui` `@ui-modernization`

**Given** the digital twin display is running with the 3D robot scene visible
**When** any HUD overlay panel is displayed (joint values, mode badge, telemetry readout)
**Then** the overlay uses a translucent background with backdrop blur (glassmorphism)
**And** the overlay has a 16 px border radius and a 1 px translucent border
**And** the 3D scene content behind the overlay is visibly blurred

### Scenario: Selected joint shows glow effect `@gui` `@ui-modernization`

**Given** the digital twin displays a multi-joint robot arm in the 3D scene
**When** the user selects a joint (tap/click on the arm segment)
**Then** the selected joint segment displays a soft glow effect using the `rti-light-blue` color at `selection_glow` opacity
**And** the glow follows the segment geometry and updates with joint movement

### Scenario: Robot mode badge uses modern status chip style `@gui` `@ui-modernization`

**Given** the digital twin displays a mode badge for the robot's operational state
**When** the mode is OPERATIONAL, PAUSED, E-STOP, or IDLE
**Then** the badge uses the semantic status chip style (12 px radius, icon + label, tinted background)
**And** E-STOP mode triggers a pulsing red border ring animation
**And** the animation respects `prefers-reduced-motion` browser settings

### Scenario: Digital twin applies Inter font for all UI text `@gui` `@ui-modernization`

**Given** the digital twin page renders text overlays (joint labels, mode badge, telemetry values)
**When** the page is displayed
**Then** non-monospace text uses the Inter font family at appropriate semantic scale weights
**And** numeric data values use Roboto Mono
**And** fonts load from local static files with no CDN requests

### Scenario: Digital twin uses design tokens for all visual values `@gui` `@ui-modernization`

**Given** the digital twin renders UI elements (badges, overlays, data labels)
**When** colors, spacing, radii, or transitions are applied
**Then** all values derive from the centralized design token system
**And** no hardcoded hex colors or pixel sizes appear in component-level rendering code

### Scenario: Digital twin shows skeleton state during discovery `@gui` `@ui-modernization`

**Given** the digital twin page loads before DDS endpoints have matched
**When** the 3D scene area is rendered but no `RobotState` samples have arrived
**Then** the scene area displays a skeleton placeholder animation (shimmer overlay) or an animated loading state
**And** the skeleton is replaced by the live 3D scene once the first `RobotState` sample arrives

---

## System Initialization

### Scenario: Procedure system reaches operational state within time budget `@integration` `@performance`

**Given** all procedure system components (robot controller, bedside monitor, procedure context publisher, device gateway) are started within a 2 s window on the room network (`{room}-net`)
**When** the last component starts
**Then** all DomainParticipant DataWriter/DataReader pairs have matched within 5 s
**And** all TRANSIENT_LOCAL topics (`ProcedureContext`, `RobotState`) have delivered their most recent samples to late-joining subscribers within the same 5 s window
**And** no component reports a missed deadline or liveliness loss during initialization

### Scenario: Restarted component re-integrates within time budget `@integration` `@performance`

**Given** a procedure system is fully operational
**When** a single component (e.g., the bedside monitor) is stopped and restarted
**Then** the restarted component's participants have re-matched all expected endpoints within 5 s of restart
**And** TRANSIENT_LOCAL state is re-delivered to the restarted component within the same 5 s window

---

## Simulation Fidelity (see also `vision/simulation-model.md`)

### Scenario: Simulators produce non-deterministic output by default `@integration` `@simulation`

**Given** the vitals simulator is started without `MEDTECH_SIM_SEED` set
**When** two separate runs execute the `stable` profile for 30 s
**Then** the recorded `PatientVitals` sample sequences differ between runs
**And** both sequences contain values within clinically normal ranges

### Scenario: Simulators produce deterministic output with fixed seed `@unit` `@simulation`

**Given** the vitals simulator is configured with `MEDTECH_SIM_SEED=42` and `MEDTECH_SIM_PROFILE=stable`
**When** two separate runs execute for 10 s
**Then** the recorded `PatientVitals` sample sequences are identical between runs

### Scenario: Vitals trend smoothly — no discontinuities `@unit` `@simulation`

**Given** the vitals simulator is running with any profile
**When** `PatientVitals` is published at 1 Hz over 60 s
**Then** no consecutive pair of HR samples differs by more than 3× the noise amplitude (±2 bpm × 3 = 6 bpm) unless a profile-defined acute event is active
**And** no consecutive pair of SBP samples differs by more than 3× the noise amplitude (±3 mmHg × 3 = 9 mmHg) unless a profile-defined acute event is active

### Scenario: Cross-signal correlation — SBP drop triggers HR compensation `@unit` `@simulation`

**Given** the vitals simulator is running with profile `hemorrhage_onset`
**When** the simulated SBP trends below 90 mmHg
**Then** the simulated HR trends upward within 1–3 s of the SBP decrease
**And** the HR increase is proportional to the SBP decrease (baroreceptor reflex model)

### Scenario: Scenario profile drives coordinated trajectory `@integration` `@simulation`

**Given** the vitals simulator is running with profile `hemorrhage_onset`
**When** 5 minutes of simulated time have elapsed
**Then** the `PatientVitals` samples show a coordinated multi-signal deterioration pattern:
SBP has decreased, HR has increased, and SpO2 has declined (with delay)
**And** the hemorrhage risk score computed from these vitals exceeds the CRITICAL threshold (≥ 0.7)

### Scenario: Write-on-change topic does not publish when state is unchanged `@integration` `@simulation`

**Given** the device telemetry simulator is running with profile `stable`
**And** the simulated infusion pump state is steady (no parameter changes, no faults)
**When** 30 s of operation elapse
**Then** the number of `DeviceTelemetry` samples published is significantly fewer than would be published at a fixed 2 Hz rate (i.e., ≪ 60 samples)
**And** the published samples correspond to actual state transitions or noise-threshold crossings

### Scenario: Continuous-stream topic publishes at fixed rate regardless of value change `@integration` `@simulation`

**Given** the robot state publisher is running
**When** the robot is in IDLE mode with no state changes for 10 s
**Then** `RobotState` samples continue to be published at 100 Hz (≈ 1000 samples in 10 s)
**And** each sample reflects the current (unchanged) robot state
