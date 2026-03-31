"""Tests for Phase 2 Step 2.3 — Patient Vitals & Alarm Simulator.

Covers all test gate items from phase-2-surgical.md Step 2.3:
- Vitals snapshot published periodically with all required measurements
- Waveform data streams at configured frequency with correct block size
- Alarm raised when vital exceeds threshold
- Alarm clears when vital returns to normal
- Late-joining subscriber receives current vitals (TRANSIENT_LOCAL)
- Simulator produces non-deterministic output by default
- Simulator produces deterministic output with fixed seed
- Vitals trend smoothly — no discontinuities
- Cross-signal correlation: SBP drop triggers HR compensation
- Scenario profile hemorrhage_onset produces coordinated multi-signal deterioration
- AlarmMessages publishes only on state transitions (write-on-change model)

Spec coverage: surgical-procedure.md — Patient Vitals, Simulation Fidelity
"""

from __future__ import annotations

import os
import random
import time

import common
import monitoring
import pytest
import rti.connextdds as dds
from conftest import wait_for_reader_match
from surgical_procedure.vitals_sim._alarm import AlarmEvaluator
from surgical_procedure.vitals_sim._profiles import PROFILES, baroreceptor_reflex
from surgical_procedure.vitals_sim._signal import SignalModel
from surgical_procedure.vitals_sim.bedside_monitor_service import BedsideMonitorService

PatientVitals = monitoring.Monitoring.PatientVitals
WaveformData = monitoring.Monitoring.WaveformData
WaveformKind = monitoring.Monitoring.WaveformKind
AlarmMessage = monitoring.Monitoring.AlarmMessage
AlarmSeverity = monitoring.Monitoring.AlarmSeverity
AlarmState = monitoring.Monitoring.AlarmState


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _wait_data_available(reader, timeout_sec=2.0):
    """Block until DATA_AVAILABLE fires on *reader*, or timeout."""
    cond = dds.StatusCondition(reader)
    cond.enabled_statuses = dds.StatusMask.DATA_AVAILABLE
    ws = dds.WaitSet()
    ws += cond
    try:
        sec = int(timeout_sec)
        nsec = int((timeout_sec - sec) * 1_000_000_000)
        ws.wait(dds.Duration(sec, nsec))
    except dds.TimeoutError:
        pass


def _env_override(monkeypatch, **kwargs):
    """Set environment variables for the test, restoring after."""
    for k, v in kwargs.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, str(v))


# -----------------------------------------------------------------------
# Unit tests — SignalModel
# -----------------------------------------------------------------------


class TestSignalModel:
    """Unit tests for the signal model core."""

    def test_converges_toward_target(self):
        rng = random.Random(42)
        sig = SignalModel(
            "hr",
            initial=75.0,
            convergence_rate=0.1,
            noise_amplitude=0.0,
            min_val=30.0,
            max_val=220.0,
            rng=rng,
        )
        sig.target = 100.0
        for _ in range(50):
            sig.tick()
        # Should have converged significantly toward 100
        assert sig.value > 95.0

    def test_noise_produces_variation(self):
        rng = random.Random(42)
        sig = SignalModel(
            "hr",
            initial=75.0,
            convergence_rate=0.0,
            noise_amplitude=2.0,
            min_val=30.0,
            max_val=220.0,
            rng=rng,
        )
        sig.target = 75.0
        values = [sig.tick() for _ in range(100)]
        # With noise, not all values should be identical
        assert len(set(round(v, 2) for v in values)) > 1

    def test_clamped_to_bounds(self):
        rng = random.Random(42)
        sig = SignalModel(
            "hr",
            initial=220.0,
            convergence_rate=0.0,
            noise_amplitude=5.0,
            min_val=30.0,
            max_val=220.0,
            rng=rng,
        )
        sig.target = 220.0
        for _ in range(100):
            v = sig.tick()
            assert 30.0 <= v <= 220.0


# -----------------------------------------------------------------------
# Unit tests — AlarmEvaluator
# -----------------------------------------------------------------------


class TestAlarmEvaluator:
    """Unit tests for alarm evaluation logic."""

    def test_alarm_raised_when_vital_exceeds_threshold(self):
        """spec: Alarm is raised when vital exceeds threshold @unit"""
        evaluator = AlarmEvaluator(patient_id="p1")
        vitals = PatientVitals(
            patient_id="p1",
            heart_rate=135.0,  # Above HR HIGH threshold (120 bpm)
            spo2=98.0,
            systolic_bp=120.0,
            diastolic_bp=80.0,
            temperature=36.8,
            respiratory_rate=14.0,
        )
        transitions = evaluator.evaluate(vitals)
        hr_alarms = [a for a in transitions if a.alarm_code == "HR_HIGH"]
        assert len(hr_alarms) == 1
        alarm = hr_alarms[0]
        assert alarm.state == AlarmState.ACTIVE
        assert alarm.severity == AlarmSeverity.HIGH

    def test_alarm_clears_when_vital_returns_to_normal(self):
        """spec: Alarm clears when vital returns to normal @unit"""
        evaluator = AlarmEvaluator(patient_id="p1")
        # First: trigger alarm
        high_vitals = PatientVitals(
            patient_id="p1",
            heart_rate=135.0,
            spo2=98.0,
            systolic_bp=120.0,
            diastolic_bp=80.0,
            temperature=36.8,
            respiratory_rate=14.0,
        )
        evaluator.evaluate(high_vitals)
        assert "HR_HIGH" in evaluator.active_alarms

        # Then: return to normal
        normal_vitals = PatientVitals(
            patient_id="p1",
            heart_rate=85.0,
            spo2=98.0,
            systolic_bp=120.0,
            diastolic_bp=80.0,
            temperature=36.8,
            respiratory_rate=14.0,
        )
        transitions = evaluator.evaluate(normal_vitals)
        hr_cleared = [
            a
            for a in transitions
            if a.alarm_code == "HR_HIGH" and a.state == AlarmState.CLEARED
        ]
        assert len(hr_cleared) == 1
        assert "HR_HIGH" not in evaluator.active_alarms

    def test_no_transitions_when_state_unchanged(self):
        """spec: AlarmMessages publishes only on state transitions @unit"""
        evaluator = AlarmEvaluator(patient_id="p1")
        normal = PatientVitals(
            patient_id="p1",
            heart_rate=75.0,
            spo2=98.0,
            systolic_bp=120.0,
            diastolic_bp=80.0,
            temperature=36.8,
            respiratory_rate=14.0,
        )
        # Multiple evaluations with normal vitals → no transitions
        for _ in range(10):
            transitions = evaluator.evaluate(normal)
            assert transitions == []

    def test_no_duplicate_alarm_while_active(self):
        """Repeated high readings don't produce repeated alarm raises."""
        evaluator = AlarmEvaluator(patient_id="p1")
        high = PatientVitals(
            patient_id="p1",
            heart_rate=135.0,
            spo2=98.0,
            systolic_bp=120.0,
            diastolic_bp=80.0,
            temperature=36.8,
            respiratory_rate=14.0,
        )
        t1 = evaluator.evaluate(high)
        assert len([a for a in t1 if a.alarm_code == "HR_HIGH"]) == 1
        # Second eval with same high reading — should not re-raise
        t2 = evaluator.evaluate(high)
        assert len([a for a in t2 if a.alarm_code == "HR_HIGH"]) == 0

    def test_alarm_id_fits_entity_id_bound(self):
        """All generated alarm_ids must fit within EntityId (string<MAX_ID_LENGTH>).

        Regression test: the default patient_id 'patient-001' combined with
        longer alarm codes like 'TEMP_HIGH' previously exceeded 16 characters,
        causing a serialization crash at runtime.
        """
        max_len = common.Common.MAX_ID_LENGTH
        # Use the production default patient_id
        evaluator = AlarmEvaluator(patient_id="patient-001")
        # Build vitals that trigger every single default alarm rule
        vitals = PatientVitals(
            patient_id="patient-001",
            heart_rate=200.0,  # HR_HIGH
            spo2=50.0,  # SPO2_LOW
            systolic_bp=40.0,  # SBP_LOW
            diastolic_bp=80.0,
            temperature=42.0,  # TEMP_HIGH
            respiratory_rate=3.0,  # RR_LOW (and not RR_HIGH)
        )
        transitions = evaluator.evaluate(vitals)
        assert len(transitions) > 0, "Expected at least one alarm"
        for alarm in transitions:
            assert len(alarm.alarm_id) <= max_len, (
                f"alarm_id '{alarm.alarm_id}' ({len(alarm.alarm_id)} chars) "
                f"exceeds EntityId bound ({max_len})"
            )


# -----------------------------------------------------------------------
# Unit tests — Simulation model (determinism, smoothness, correlation)
# -----------------------------------------------------------------------


class TestSimulationModel:
    """Unit tests for simulation fidelity requirements."""

    def test_deterministic_with_fixed_seed(self):
        """spec: Simulator produces deterministic output with fixed seed @unit"""
        profile = PROFILES["stable"]

        def run_signals(seed):
            rng = random.Random(seed)
            signals = profile.create_signals(rng)
            return [signals["heart_rate"].tick() for _ in range(10)]

        run1 = run_signals(42)
        run2 = run_signals(42)
        assert run1 == run2

    def test_non_deterministic_without_seed(self):
        """spec: Simulator produces non-deterministic output by default @unit"""
        profile = PROFILES["stable"]

        def run_signals():
            rng = random.Random()  # system entropy
            signals = profile.create_signals(rng)
            return [round(signals["heart_rate"].tick(), 6) for _ in range(30)]

        # Two runs with system entropy should differ
        run1 = run_signals()
        run2 = run_signals()
        assert run1 != run2

    def test_vitals_trend_smoothly_no_discontinuities(self):
        """spec: Vitals trend smoothly — no discontinuities @unit

        No consecutive pair of HR samples differs by more than 3× the
        noise amplitude (±2 bpm × 3 = 6 bpm) unless a profile-defined
        acute event is active.
        """
        rng = random.Random(42)
        profile = PROFILES["stable"]
        signals = profile.create_signals(rng)

        hr_values = []
        for _ in range(60):
            signals["heart_rate"].tick()
            hr_values.append(signals["heart_rate"].value)

        for i in range(1, len(hr_values)):
            delta = abs(hr_values[i] - hr_values[i - 1])
            # 3× noise amplitude for HR = 3 × 2 = 6
            assert delta <= 6.0, (
                f"HR jump of {delta:.2f} at tick {i}: "
                f"{hr_values[i-1]:.2f} → {hr_values[i]:.2f}"
            )

    def test_sbp_smoothness(self):
        """No consecutive SBP pair differs by more than 3× noise (±3 × 3 = 9 mmHg)."""
        rng = random.Random(42)
        profile = PROFILES["stable"]
        signals = profile.create_signals(rng)

        sbp_values = []
        for _ in range(60):
            signals["systolic_bp"].tick()
            sbp_values.append(signals["systolic_bp"].value)

        for i in range(1, len(sbp_values)):
            delta = abs(sbp_values[i] - sbp_values[i - 1])
            assert delta <= 9.0, (
                f"SBP jump of {delta:.2f} at tick {i}: "
                f"{sbp_values[i-1]:.2f} → {sbp_values[i]:.2f}"
            )

    def test_cross_signal_sbp_drop_triggers_hr_compensation(self):
        """spec: Cross-signal correlation — SBP drop triggers HR compensation @unit

        When SBP trends below 90 mmHg, HR trends upward within 1–3 s.
        """
        rng = random.Random(42)
        profile = PROFILES["hemorrhage_onset"]
        signals = profile.create_signals(rng)

        # Record initial HR
        initial_hr = signals["heart_rate"].value

        # Force SBP below 90 to trigger baroreceptor reflex
        signals["systolic_bp"].set_value(80.0)
        signals["systolic_bp"].target = 75.0

        # Apply correlation and tick for 3 seconds (3 ticks at 1 Hz)
        for _ in range(3):
            baroreceptor_reflex(signals)
            for sig in signals.values():
                sig.tick()

        # HR should have increased from baseline
        assert signals["heart_rate"].value > initial_hr + 2.0, (
            f"HR should have compensated upward from {initial_hr:.1f}: "
            f"got {signals['heart_rate'].value:.1f}"
        )

    def test_hemorrhage_onset_coordinated_deterioration(self):
        """spec: Scenario profile hemorrhage_onset produces coordinated
        multi-signal deterioration @integration @simulation

        After 5 minutes (300 ticks at 1 Hz), SBP decreased, HR increased,
        SpO2 declined.
        """
        rng = random.Random(42)
        profile = PROFILES["hemorrhage_onset"]
        signals = profile.create_signals(rng)

        initial_sbp = signals["systolic_bp"].value
        initial_hr = signals["heart_rate"].value
        initial_spo2 = signals["spo2"].value

        last_event_idx = -1

        for tick in range(300):
            elapsed = float(tick)
            # Apply scheduled events
            for i, event in enumerate(profile.events):
                if i > last_event_idx and elapsed >= event.time_offset:
                    for sig_name, target_val in event.signal_targets.items():
                        if sig_name in signals:
                            signals[sig_name].target = target_val
                    last_event_idx = i

            # Apply correlations
            for fn in profile.correlations:
                fn(signals)

            for sig in signals.values():
                sig.tick()

        final_sbp = signals["systolic_bp"].value
        final_hr = signals["heart_rate"].value
        final_spo2 = signals["spo2"].value

        assert (
            final_sbp < initial_sbp - 20
        ), f"SBP should have decreased: {initial_sbp:.1f} → {final_sbp:.1f}"
        assert (
            final_hr > initial_hr + 10
        ), f"HR should have increased: {initial_hr:.1f} → {final_hr:.1f}"
        assert (
            final_spo2 < initial_spo2 - 2
        ), f"SpO2 should have declined: {initial_spo2:.1f} → {final_spo2:.1f}"


# -----------------------------------------------------------------------
# Integration tests — DDS publishing
# -----------------------------------------------------------------------

DOCKER_TOLERANCE = 10 if os.environ.get("MEDTECH_DOCKER") else 1


class TestBedsideMonitorServiceIntegration:
    """Integration tests for the BedsideMonitorService DDS publishing."""

    @pytest.fixture
    def monitor(self, monkeypatch):
        """Create a BedsideMonitorService with a stable profile and fixed seed."""
        monkeypatch.setenv("MEDTECH_SIM_SEED", "42")
        monkeypatch.setenv("MEDTECH_SIM_PROFILE", "stable")
        mon = BedsideMonitorService(
            room_id="OR-1",
            procedure_id="proc-001",
            patient_id="p1",
            device_id="bedside-001",
        )
        mon._start()
        yield mon
        mon.participant.close()

    @pytest.fixture
    def vitals_reader(self, monitor):
        """Create a DataReader for PatientVitals in the same partition."""
        p = dds.DomainParticipant.default_participant_qos
        p.partition.name = ["room/OR-1/procedure/proc-001"]
        p.property["dds.domain_participant.domain_tag"] = "clinical"
        p.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
        dp = dds.DomainParticipant(10, p)

        provider = dds.QosProvider.default
        reader_qos = provider.datareader_qos_from_profile(
            "TopicProfiles::PatientVitals"
        )
        topic = dds.Topic(dp, "PatientVitals", PatientVitals)
        sub = dds.Subscriber(dp)
        reader = dds.DataReader(sub, topic, reader_qos)
        dp.enable()
        yield reader
        dp.close()

    @pytest.fixture
    def waveform_reader(self, monitor):
        """Create a DataReader for WaveformData in the same partition."""
        p = dds.DomainParticipant.default_participant_qos
        p.partition.name = ["room/OR-1/procedure/proc-001"]
        p.property["dds.domain_participant.domain_tag"] = "clinical"
        p.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
        dp = dds.DomainParticipant(10, p)

        provider = dds.QosProvider.default
        reader_qos = provider.datareader_qos_from_profile("TopicProfiles::WaveformData")
        topic = dds.Topic(dp, "WaveformData", WaveformData)
        sub = dds.Subscriber(dp)
        reader = dds.DataReader(sub, topic, reader_qos)
        dp.enable()
        yield reader
        dp.close()

    @pytest.fixture
    def alarm_reader(self, monitor):
        """Create a DataReader for AlarmMessages in the same partition."""
        p = dds.DomainParticipant.default_participant_qos
        p.partition.name = ["room/OR-1/procedure/proc-001"]
        p.property["dds.domain_participant.domain_tag"] = "clinical"
        p.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
        dp = dds.DomainParticipant(10, p)

        provider = dds.QosProvider.default
        reader_qos = provider.datareader_qos_from_profile(
            "TopicProfiles::AlarmMessages"
        )
        topic = dds.Topic(dp, "AlarmMessages", AlarmMessage)
        sub = dds.Subscriber(dp)
        reader = dds.DataReader(sub, topic, reader_qos)
        dp.enable()
        yield reader
        dp.close()

    def test_vitals_published_with_all_fields(self, monitor, vitals_reader):
        """spec: Vitals snapshot published periodically with all required
        measurements @integration"""
        assert wait_for_reader_match(vitals_reader, timeout_sec=5)

        monitor.tick_vitals()

        _wait_data_available(vitals_reader)
        samples = [s for s in vitals_reader.take() if s.info.valid]
        assert len(samples) >= 1, "No vitals samples received"

        sample = samples[-1].data
        assert sample.patient_id == "p1"
        assert 30 <= sample.heart_rate <= 220
        assert 50 <= sample.spo2 <= 100
        assert 40 <= sample.systolic_bp <= 250
        assert 20 <= sample.diastolic_bp <= 150
        assert 34 <= sample.temperature <= 42
        assert 4 <= sample.respiratory_rate <= 40

    def test_waveform_published_with_correct_block_size(self, monitor, waveform_reader):
        """spec: Waveform data streams at configured frequency with correct
        block size @integration @streaming"""
        assert wait_for_reader_match(waveform_reader, timeout_sec=5)

        # WaveformData uses Patterns::Stream (BEST_EFFORT).  The writer
        # may not have completed endpoint discovery even after the reader
        # sees it — writes to an unmatched reader are silently discarded.
        # Retry publish-then-check until data arrives or timeout.
        deadline = time.monotonic() + 5.0
        samples = []
        while time.monotonic() < deadline:
            monitor.tick_waveform()
            _wait_data_available(waveform_reader, timeout_sec=0.5)
            samples = [s for s in waveform_reader.take() if s.info.valid]
            if samples:
                break

        assert len(samples) >= 1, "No waveform samples received"

        sample = samples[-1].data
        assert sample.patient_id == "p1"
        assert sample.waveform_kind == WaveformKind.ECG
        assert len(sample.samples) == 10  # 10-sample blocks
        assert sample.sample_rate_hz == 500.0

    def test_late_joiner_receives_vitals(self, monitor):
        """spec: Late-joining subscriber receives current vitals @integration
        @durability"""
        # Publish vitals first
        monitor.tick_vitals()
        time.sleep(0.5)

        # Create late-joining reader
        p = dds.DomainParticipant.default_participant_qos
        p.partition.name = ["room/OR-1/procedure/proc-001"]
        p.property["dds.domain_participant.domain_tag"] = "clinical"
        p.property["dds.transport.UDPv4.builtin.parent.message_size_max"] = "1400"
        dp = dds.DomainParticipant(10, p)

        provider = dds.QosProvider.default
        reader_qos = provider.datareader_qos_from_profile(
            "TopicProfiles::PatientVitals"
        )
        topic = dds.Topic(dp, "PatientVitals", PatientVitals)
        sub = dds.Subscriber(dp)
        reader = dds.DataReader(sub, topic, reader_qos)
        dp.enable()

        # Wait for discovery then TRANSIENT_LOCAL historical data
        try:
            cond = dds.StatusCondition(reader)
            cond.enabled_statuses = dds.StatusMask.SUBSCRIPTION_MATCHED
            ws = dds.WaitSet()
            ws += cond
            ws.wait(dds.Duration(5))
            reader.wait_for_historical_data(dds.Duration(5))
        except dds.TimeoutError:
            pass

        received = [s.data for s in reader.take() if s.info.valid]

        dp.close()
        assert len(received) >= 1, "Late joiner did not receive TRANSIENT_LOCAL vitals"
        assert received[0].patient_id == "p1"

    def test_alarm_published_on_state_transition(self, monitor, alarm_reader):
        """spec: AlarmMessages publishes only on state transitions
        (write-on-change model) @integration"""
        assert wait_for_reader_match(alarm_reader, timeout_sec=5)

        # Force HR above alarm threshold
        monitor.signals["heart_rate"].set_value(135.0)
        monitor.signals["heart_rate"].target = 135.0

        monitor.tick_vitals()

        _wait_data_available(alarm_reader)
        samples = [s for s in alarm_reader.take() if s.info.valid]
        hr_active = [
            s.data
            for s in samples
            if s.data.alarm_code == "HR_HIGH" and s.data.state == AlarmState.ACTIVE
        ]
        assert len(hr_active) >= 1, "HR_HIGH alarm was not published"

        # Now send normal readings — no alarm transitions expected (stable)
        alarm_reader.take()  # drain
        monitor.tick_vitals()  # still high HR
        _wait_data_available(alarm_reader, timeout_sec=0.3)
        stable_samples = [s for s in alarm_reader.take() if s.info.valid]
        stable_hr_alarms = [
            s.data for s in stable_samples if s.data.alarm_code == "HR_HIGH"
        ]
        # No new transitions while alarm state is unchanged
        assert len(stable_hr_alarms) == 0, "Alarm re-published without state transition"

        # Clear alarm by returning HR to normal
        monitor.signals["heart_rate"].set_value(85.0)
        monitor.signals["heart_rate"].target = 75.0
        monitor.tick_vitals()

        _wait_data_available(alarm_reader)
        cleared_samples = [s for s in alarm_reader.take() if s.info.valid]
        hr_cleared = [
            s.data
            for s in cleared_samples
            if s.data.alarm_code == "HR_HIGH" and s.data.state == AlarmState.CLEARED
        ]
        assert len(hr_cleared) >= 1, "HR_HIGH alarm clear was not published"
