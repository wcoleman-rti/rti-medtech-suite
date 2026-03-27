"""Alarm evaluation logic for patient vitals.

Monitors vitals against configurable thresholds and produces AlarmMessage
instances on state transitions only (write-on-change publication model).
See vision/data-model.md — Publication Model.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence

import common
import monitoring

AlarmMessage = monitoring.Monitoring.AlarmMessage
AlarmSeverity = monitoring.Monitoring.AlarmSeverity
AlarmState = monitoring.Monitoring.AlarmState
PatientVitals = monitoring.Monitoring.PatientVitals
Time_t = common.Common.Time_t

_MAX_ID = common.Common.MAX_ID_LENGTH


def _make_alarm_id(patient_id: str, alarm_code: str) -> str:
    """Build a compact alarm_id that fits within EntityId (string<16>).

    Format: ``<patient_suffix>-<alarm_code>``, truncated from the left
    on the patient portion so the alarm_code is always preserved.
    """
    suffix_budget = _MAX_ID - len(alarm_code) - 1  # 1 for the separator
    if suffix_budget < 1:
        # alarm_code itself is too long — truncate the whole thing
        return f"{patient_id}-{alarm_code}"[:_MAX_ID]
    patient_suffix = (
        patient_id[-suffix_budget:] if len(patient_id) > suffix_budget else patient_id
    )
    return f"{patient_suffix}-{alarm_code}"


@dataclass
class ThresholdRule:
    """A single threshold-based alarm rule.

    Compares a named vital-sign field against a boundary value.
    A HIGH-bound rule fires when ``value >= threshold`` (upper alarm).
    A LOW-bound rule fires when ``value <= threshold`` (lower alarm).
    """

    alarm_code: str
    field_name: str  # attribute on PatientVitals (e.g., "heart_rate")
    threshold: float
    severity: AlarmSeverity
    upper: bool = True  # True = fire when value >= threshold


# Default clinical alarm thresholds (HR HIGH per spec = 120 bpm)
DEFAULT_RULES: list[ThresholdRule] = [
    ThresholdRule(
        alarm_code="HR_HIGH",
        field_name="heart_rate",
        threshold=120.0,
        severity=AlarmSeverity.HIGH,
        upper=True,
    ),
    ThresholdRule(
        alarm_code="HR_LOW",
        field_name="heart_rate",
        threshold=45.0,
        severity=AlarmSeverity.MEDIUM,
        upper=False,
    ),
    ThresholdRule(
        alarm_code="SPO2_LOW",
        field_name="spo2",
        threshold=90.0,
        severity=AlarmSeverity.HIGH,
        upper=False,
    ),
    ThresholdRule(
        alarm_code="SBP_LOW",
        field_name="systolic_bp",
        threshold=80.0,
        severity=AlarmSeverity.HIGH,
        upper=False,
    ),
    ThresholdRule(
        alarm_code="TEMP_HIGH",
        field_name="temperature",
        threshold=39.0,
        severity=AlarmSeverity.MEDIUM,
        upper=True,
    ),
    ThresholdRule(
        alarm_code="RR_LOW",
        field_name="respiratory_rate",
        threshold=8.0,
        severity=AlarmSeverity.MEDIUM,
        upper=False,
    ),
    ThresholdRule(
        alarm_code="RR_HIGH",
        field_name="respiratory_rate",
        threshold=30.0,
        severity=AlarmSeverity.MEDIUM,
        upper=True,
    ),
]


class AlarmEvaluator:
    """Evaluates vitals against thresholds and emits alarm state transitions.

    Only produces AlarmMessage instances when the alarm state changes
    (raised, cleared). This is the write-on-change publication model —
    stable alarm state produces no messages.
    """

    def __init__(
        self,
        patient_id: str,
        device_id: str = "bedside-monitor",
        rules: Sequence[ThresholdRule] | None = None,
    ) -> None:
        self._patient_id = patient_id
        self._device_id = device_id
        self._rules = list(rules) if rules is not None else list(DEFAULT_RULES)
        # Track active alarm state per alarm_code
        self._active: dict[str, AlarmMessage] = {}

    def evaluate(self, vitals: PatientVitals) -> list[AlarmMessage]:
        """Evaluate vitals and return alarm messages for state transitions only.

        Returns a list of AlarmMessage for alarms that were newly raised or
        newly cleared since the last evaluation. Returns an empty list if no
        state transitions occurred.
        """
        transitions: list[AlarmMessage] = []
        now = time.time()
        sec = int(now)
        nsec = int((now - sec) * 1_000_000_000)

        for rule in self._rules:
            value = getattr(vitals, rule.field_name, None)
            if value is None:
                continue

            violated = (
                (value >= rule.threshold) if rule.upper else (value <= rule.threshold)
            )
            was_active = rule.alarm_code in self._active

            if violated and not was_active:
                # New alarm — raise
                alarm = AlarmMessage(
                    alarm_id=_make_alarm_id(self._patient_id, rule.alarm_code),
                    patient_id=self._patient_id,
                    source_device_id=self._device_id,
                    severity=rule.severity,
                    state=AlarmState.ACTIVE,
                    alarm_code=rule.alarm_code,
                    message=f"{rule.field_name} {'above' if rule.upper else 'below'} threshold ({rule.threshold})",
                    onset_time=Time_t(sec=sec & 0xFFFFFFFF, nsec=nsec),
                )
                self._active[rule.alarm_code] = alarm
                transitions.append(alarm)

            elif not violated and was_active:
                # Alarm cleared
                prev = self._active.pop(rule.alarm_code)
                cleared = AlarmMessage(
                    alarm_id=prev.alarm_id,
                    patient_id=prev.patient_id,
                    source_device_id=prev.source_device_id,
                    severity=prev.severity,
                    state=AlarmState.CLEARED,
                    alarm_code=prev.alarm_code,
                    message=f"{rule.field_name} returned to normal",
                    onset_time=prev.onset_time,
                )
                transitions.append(cleared)

        return transitions

    @property
    def active_alarms(self) -> dict[str, AlarmMessage]:
        """Return a copy of currently active alarm states."""
        return dict(self._active)
