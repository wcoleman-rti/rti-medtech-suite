"""Scenario profiles for the vitals simulation engine.

Each profile defines signal trajectories, cross-signal correlations, and
event timing per vision/simulation-model.md Section 3.

Required V1.0 profiles: stable, normal_variation, hemorrhage_onset,
sepsis_progression, cardiac_event, device_fault, robot_estop.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable

from ._signal import SignalModel

# ---------------------------------------------------------------------------
# Signal defaults — clinically normal baseline values
# ---------------------------------------------------------------------------

NORMAL_HR = 75.0
NORMAL_SPO2 = 98.0
NORMAL_SBP = 120.0
NORMAL_DBP = 80.0
NORMAL_TEMP = 36.8
NORMAL_RR = 14.0


@dataclass
class SignalSpec:
    """Initial parameters for one signal in a profile."""

    initial: float
    target: float
    convergence_rate: float
    noise_amplitude: float
    min_val: float
    max_val: float


# ---------------------------------------------------------------------------
# Event — a timed target change scheduled by a profile
# ---------------------------------------------------------------------------


@dataclass
class ScheduledEvent:
    """A target-state change scheduled at a time offset (seconds)."""

    time_offset: float  # seconds from simulation start
    signal_targets: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Cross-signal correlation rules
# ---------------------------------------------------------------------------

CrossCorrelationFn = Callable[[dict[str, SignalModel]], None]


def baroreceptor_reflex(signals: dict[str, SignalModel]) -> None:
    """SBP drop → HR compensation (1–3 s delay modeled as convergence)."""
    sbp = signals["systolic_bp"].value
    base_hr = NORMAL_HR
    if sbp < 90:
        # Proportional reflex: ~0.5 bpm increase per mmHg below 90
        compensation = (90.0 - sbp) * 0.5
        signals["heart_rate"].target = base_hr + compensation
    elif sbp < 110:
        # Mild compensation zone
        compensation = (110.0 - sbp) * 0.2
        signals["heart_rate"].target = base_hr + compensation


def sbp_spo2_coupling(signals: dict[str, SignalModel]) -> None:
    """SBP < 80 → SpO2 begins declining (delayed via convergence rate)."""
    sbp = signals["systolic_bp"].value
    if sbp < 80:
        deficit = (80.0 - sbp) / 40.0  # normalized 0..1
        signals["spo2"].target = max(85.0, NORMAL_SPO2 - deficit * 10.0)


def temperature_hr_coupling(signals: dict[str, SignalModel]) -> None:
    """Temperature rise → HR increases ~10 bpm per °C above 37.5."""
    temp = signals["temperature"].value
    if temp > 37.5:
        delta = (temp - 37.5) * 10.0
        current_target = signals["heart_rate"].target
        signals["heart_rate"].target = max(current_target, NORMAL_HR + delta)


def rr_spo2_coupling(signals: dict[str, SignalModel]) -> None:
    """RR decrease (sedation) → SpO2 decreases."""
    rr = signals["respiratory_rate"].value
    if rr < 10:
        deficit = (10.0 - rr) / 10.0
        signals["spo2"].target = max(88.0, NORMAL_SPO2 - deficit * 8.0)


# ---------------------------------------------------------------------------
# ScenarioProfile
# ---------------------------------------------------------------------------


@dataclass
class ScenarioProfile:
    """A named scenario profile that drives coordinated signal trajectories."""

    name: str
    signal_specs: dict[str, SignalSpec]
    events: list[ScheduledEvent] = field(default_factory=list)
    correlations: list[CrossCorrelationFn] = field(default_factory=list)

    def create_signals(self, rng: random.Random) -> dict[str, SignalModel]:
        """Instantiate SignalModel instances from the spec."""
        signals = {}
        for name, spec in self.signal_specs.items():
            signals[name] = SignalModel(
                name=name,
                initial=spec.initial,
                convergence_rate=spec.convergence_rate,
                noise_amplitude=spec.noise_amplitude,
                min_val=spec.min_val,
                max_val=spec.max_val,
                rng=rng,
            )
            signals[name].target = spec.target
        return signals


# ---------------------------------------------------------------------------
# Default signal specs (reusable across profiles)
# ---------------------------------------------------------------------------

_HEALTHY_SPECS: dict[str, SignalSpec] = {
    "heart_rate": SignalSpec(
        initial=NORMAL_HR,
        target=NORMAL_HR,
        convergence_rate=0.05,
        noise_amplitude=2.0,
        min_val=30.0,
        max_val=220.0,
    ),
    "spo2": SignalSpec(
        initial=NORMAL_SPO2,
        target=NORMAL_SPO2,
        convergence_rate=0.03,
        noise_amplitude=0.5,
        min_val=50.0,
        max_val=100.0,
    ),
    "systolic_bp": SignalSpec(
        initial=NORMAL_SBP,
        target=NORMAL_SBP,
        convergence_rate=0.04,
        noise_amplitude=3.0,
        min_val=40.0,
        max_val=250.0,
    ),
    "diastolic_bp": SignalSpec(
        initial=NORMAL_DBP,
        target=NORMAL_DBP,
        convergence_rate=0.04,
        noise_amplitude=2.0,
        min_val=20.0,
        max_val=150.0,
    ),
    "temperature": SignalSpec(
        initial=NORMAL_TEMP,
        target=NORMAL_TEMP,
        convergence_rate=0.02,
        noise_amplitude=0.05,
        min_val=34.0,
        max_val=42.0,
    ),
    "respiratory_rate": SignalSpec(
        initial=NORMAL_RR,
        target=NORMAL_RR,
        convergence_rate=0.04,
        noise_amplitude=1.0,
        min_val=4.0,
        max_val=40.0,
    ),
}


def _copy_specs(overrides: dict[str, dict] | None = None) -> dict[str, SignalSpec]:
    """Deep-copy healthy specs and apply optional field overrides."""
    import copy

    specs = copy.deepcopy(_HEALTHY_SPECS)
    if overrides:
        for sig_name, fields in overrides.items():
            if sig_name in specs:
                for k, v in fields.items():
                    setattr(specs[sig_name], k, v)
    return specs


# ---------------------------------------------------------------------------
# Profile definitions (V1.0 required set)
# ---------------------------------------------------------------------------

PROFILES: dict[str, ScenarioProfile] = {}


def _register(profile: ScenarioProfile) -> None:
    PROFILES[profile.name] = profile


# ---- stable ----
_register(
    ScenarioProfile(
        name="stable",
        signal_specs=_copy_specs(),
        events=[],
        correlations=[],
    )
)

# ---- normal_variation ----
_register(
    ScenarioProfile(
        name="normal_variation",
        signal_specs=_copy_specs(
            {
                "heart_rate": {"noise_amplitude": 3.0},
                "systolic_bp": {"noise_amplitude": 4.0},
                "respiratory_rate": {"noise_amplitude": 1.5},
            }
        ),
        events=[
            ScheduledEvent(
                time_offset=30.0,
                signal_targets={"heart_rate": 85.0, "systolic_bp": 130.0},
            ),
            ScheduledEvent(
                time_offset=90.0,
                signal_targets={"heart_rate": 70.0, "systolic_bp": 115.0},
            ),
        ],
        correlations=[],
    )
)

# ---- hemorrhage_onset ----
_register(
    ScenarioProfile(
        name="hemorrhage_onset",
        signal_specs=_copy_specs(
            {
                "systolic_bp": {"convergence_rate": 0.03},
                "heart_rate": {"convergence_rate": 0.06},
                "spo2": {"convergence_rate": 0.02},
            }
        ),
        events=[
            # Phase 1: initial BP drop (onset at ~30 s)
            ScheduledEvent(
                time_offset=30.0,
                signal_targets={"systolic_bp": 95.0, "diastolic_bp": 60.0},
            ),
            # Phase 2: progressive hemorrhage (at ~90 s)
            ScheduledEvent(
                time_offset=90.0,
                signal_targets={"systolic_bp": 75.0, "diastolic_bp": 45.0},
            ),
            # Phase 3: severe hemorrhage (at ~180 s)
            ScheduledEvent(
                time_offset=180.0,
                signal_targets={
                    "systolic_bp": 60.0,
                    "diastolic_bp": 35.0,
                    "spo2": 88.0,
                },
            ),
        ],
        correlations=[baroreceptor_reflex, sbp_spo2_coupling],
    )
)

# ---- sepsis_progression ----
_register(
    ScenarioProfile(
        name="sepsis_progression",
        signal_specs=_copy_specs(
            {
                "temperature": {"convergence_rate": 0.01},
                "heart_rate": {"convergence_rate": 0.04},
                "respiratory_rate": {"convergence_rate": 0.03},
            }
        ),
        events=[
            ScheduledEvent(
                time_offset=60.0,
                signal_targets={
                    "temperature": 38.0,
                    "heart_rate": 90.0,
                    "respiratory_rate": 18.0,
                },
            ),
            ScheduledEvent(
                time_offset=180.0,
                signal_targets={
                    "temperature": 39.2,
                    "heart_rate": 110.0,
                    "respiratory_rate": 24.0,
                },
            ),
        ],
        correlations=[temperature_hr_coupling],
    )
)

# ---- cardiac_event ----
_register(
    ScenarioProfile(
        name="cardiac_event",
        signal_specs=_copy_specs(
            {
                "heart_rate": {"convergence_rate": 0.15, "noise_amplitude": 5.0},
            }
        ),
        events=[
            # Acute HR spike at ~10 s
            ScheduledEvent(
                time_offset=10.0,
                signal_targets={"heart_rate": 145.0},
            ),
        ],
        correlations=[],
    )
)

# ---- device_fault (for DeviceTelemetry — vitals stay stable) ----
_register(
    ScenarioProfile(
        name="device_fault",
        signal_specs=_copy_specs(),
        events=[],
        correlations=[],
    )
)

# ---- robot_estop (for SafetyInterlock — vitals stay stable) ----
_register(
    ScenarioProfile(
        name="robot_estop",
        signal_specs=_copy_specs(),
        events=[],
        correlations=[],
    )
)
