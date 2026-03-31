"""Bedside monitor simulator — PatientVitals, WaveformData, AlarmMessages.

Publishes on the Procedure domain (clinical tag) using:
- PatientVitals: periodic-snapshot at 1 Hz
- WaveformData: continuous-stream at 50 Hz (10-sample ECG blocks at 500 Sa/s)
- AlarmMessages: write-on-change (alarm state transitions only)

Follows the canonical application architecture in vision/dds-consistency.md §3.
Uses generated entity name constants from app_names.idl.
Implements medtech.Service for orchestration lifecycle management.
"""

from __future__ import annotations

import asyncio
import math
import random
import time

import app_names
import common
import monitoring
import rti.connextdds as dds
from medtech.dds import initialize_connext
from medtech.log import ModuleName, init_logging
from medtech.service import Service, ServiceState

from ._alarm import AlarmEvaluator
from ._profiles import PROFILES, ScenarioProfile
from ._signal import SignalModel

names = app_names.MedtechEntityNames.SurgicalParticipants

PatientVitals = monitoring.Monitoring.PatientVitals
WaveformData = monitoring.Monitoring.WaveformData
WaveformKind = monitoring.Monitoring.WaveformKind
AlarmMessage = monitoring.Monitoring.AlarmMessage
Time_t = common.Common.Time_t

log = init_logging(ModuleName.SURGICAL_PROCEDURE)


class BedsideMonitorService(Service):
    """Bedside monitor simulator with vitals, waveforms, and alarm generation.

    The class owns its DomainParticipant and all contained writers.
    Public interface is domain-meaningful — no DDS types exposed.
    Implements medtech.Service for orchestration lifecycle management.
    """

    def __init__(
        self,
        room_id: str,
        procedure_id: str,
        patient_id: str = "patient-001",
        device_id: str = "vital-mon-001",
        *,
        participant: dds.DomainParticipant | None = None,
        sim_seed: int | None = None,
        sim_profile: str = "stable",
    ) -> None:
        self._patient_id = patient_id
        self._device_id = device_id
        self._room_id = room_id
        self._procedure_id = procedure_id
        self._state = ServiceState.STOPPED
        self._stop_event: asyncio.Event | None = None

        # --- RNG ---
        if sim_seed is not None:
            self._rng = random.Random(sim_seed)
        else:
            self._rng = random.Random()

        # --- Profile ---
        self._profile: ScenarioProfile = PROFILES.get(sim_profile, PROFILES["stable"])
        self._signals: dict[str, SignalModel] = self._profile.create_signals(self._rng)

        # --- DDS entities (dual-mode participant) ---
        if participant is None:
            initialize_connext()
            provider = dds.QosProvider.default
            self._participant = provider.create_participant_from_config(
                names.CLINICAL_MONITOR
            )
            partition = f"room/{room_id}/procedure/{procedure_id}"
            qos = self._participant.qos
            qos.partition.name = [partition]
            self._participant.qos = qos
        else:
            self._participant = participant

        vitals_any = self._participant.find_datawriter(names.PATIENT_VITALS_WRITER)
        waveform_any = self._participant.find_datawriter(names.WAVEFORM_DATA_WRITER)
        alarm_any = self._participant.find_datawriter(names.ALARM_MESSAGES_WRITER)

        if vitals_any is None:
            raise RuntimeError(f"Writer not found: {names.PATIENT_VITALS_WRITER}")
        if waveform_any is None:
            raise RuntimeError(f"Writer not found: {names.WAVEFORM_DATA_WRITER}")
        if alarm_any is None:
            raise RuntimeError(f"Writer not found: {names.ALARM_MESSAGES_WRITER}")

        self._vitals_writer = dds.DataWriter(vitals_any)
        self._waveform_writer = dds.DataWriter(waveform_any)
        self._alarm_writer = dds.DataWriter(alarm_any)

        # --- Alarm evaluator ---
        self._alarm_eval = AlarmEvaluator(patient_id=patient_id, device_id=device_id)

        # --- Waveform state ---
        self._ecg_phase = 0.0  # continuous ECG oscillator phase

        # --- Timing ---
        self._sim_start: float | None = None
        self._last_event_idx = -1

    def start(self) -> None:
        """Enable participant and begin DDS discovery."""
        self._participant.enable()
        self._sim_start = time.monotonic()
        log.notice(
            f"BedsideMonitor enabled: patient={self._patient_id}, "
            f"profile={self._profile.name}"
        )

    def tick_vitals(self) -> PatientVitals:
        """Advance the simulation by one vitals tick (1 Hz) and publish.

        Returns the published PatientVitals sample.
        """
        self._apply_scheduled_events()
        self._apply_correlations()

        # Tick all signals
        for sig in self._signals.values():
            sig.tick()

        vitals = PatientVitals(
            patient_id=self._patient_id,
            heart_rate=self._signals["heart_rate"].value,
            spo2=self._signals["spo2"].value,
            systolic_bp=self._signals["systolic_bp"].value,
            diastolic_bp=self._signals["diastolic_bp"].value,
            temperature=self._signals["temperature"].value,
            respiratory_rate=self._signals["respiratory_rate"].value,
        )
        self._vitals_writer.write(vitals)

        # Evaluate alarms (write-on-change)
        transitions = self._alarm_eval.evaluate(vitals)
        for alarm in transitions:
            self._alarm_writer.write(alarm)
            log.notice(f"Alarm transition: {alarm.alarm_code} → {alarm.state}")

        return vitals

    def tick_waveform(self) -> WaveformData:
        """Generate and publish one waveform block (50 Hz, 10 samples per block).

        ECG waveform at 500 Sa/s, published in 10-sample blocks at 50 Hz.
        Returns the published WaveformData sample.
        """
        hr = self._signals["heart_rate"].value
        # ECG frequency derived from heart rate (beats per second)
        ecg_freq = hr / 60.0
        samples_per_block = 10
        sample_rate = 500.0  # Sa/s
        dt = 1.0 / sample_rate

        samples = []
        for _ in range(samples_per_block):
            # Simplified ECG model: sine + sharp R-peak approximation
            t = self._ecg_phase
            # QRS complex approximation using a narrow Gaussian pulse
            qrs = math.exp(-((t % (1.0 / ecg_freq) - 0.1) ** 2) / 0.0005) * 1.5
            baseline = 0.2 * math.sin(2 * math.pi * ecg_freq * t)
            noise = self._rng.gauss(0, 0.02)
            samples.append(baseline + qrs + noise)
            self._ecg_phase += dt

        waveform = WaveformData(
            patient_id=self._patient_id,
            source_device_id=self._device_id,
            waveform_kind=WaveformKind.ECG,
            samples=samples,
            sample_rate_hz=sample_rate,
        )
        self._waveform_writer.write(waveform)
        return waveform

    @property
    def signals(self) -> dict[str, SignalModel]:
        """Access signal models (for testing/inspection)."""
        return self._signals

    @property
    def alarm_evaluator(self) -> AlarmEvaluator:
        """Access the alarm evaluator (for testing/inspection)."""
        return self._alarm_eval

    @property
    def participant(self) -> dds.DomainParticipant:
        """Access the underlying participant (for test setup only)."""
        return self._participant

    def _apply_scheduled_events(self) -> None:
        """Apply any scheduled profile events whose time has arrived."""
        if self._sim_start is None:
            return
        elapsed = time.monotonic() - self._sim_start
        for i, event in enumerate(self._profile.events):
            if i > self._last_event_idx and elapsed >= event.time_offset:
                for sig_name, target_val in event.signal_targets.items():
                    if sig_name in self._signals:
                        self._signals[sig_name].target = target_val
                self._last_event_idx = i

    def _apply_correlations(self) -> None:
        """Apply cross-signal correlation rules from the active profile."""
        for fn in self._profile.correlations:
            fn(self._signals)

    # --- medtech.Service interface ---

    async def run(self) -> None:
        self._state = ServiceState.STARTING
        self._stop_event = asyncio.Event()
        self.start()
        self._state = ServiceState.RUNNING

        vitals_interval = 1.0
        waveform_interval = 0.02
        next_vitals = asyncio.get_event_loop().time()
        next_waveform = asyncio.get_event_loop().time()

        while not self._stop_event.is_set():
            now = asyncio.get_event_loop().time()
            if now >= next_waveform:
                self.tick_waveform()
                next_waveform += waveform_interval
            if now >= next_vitals:
                self.tick_vitals()
                next_vitals += vitals_interval
            next_event = min(next_vitals, next_waveform)
            delay = max(0.0, next_event - asyncio.get_event_loop().time())
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

        self._state = ServiceState.STOPPING
        self._state = ServiceState.STOPPED

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    @property
    def name(self) -> str:
        return "BedsideMonitor"

    @property
    def state(self) -> ServiceState:
        return self._state
