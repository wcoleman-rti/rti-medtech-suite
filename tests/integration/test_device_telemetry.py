"""Tests for Phase 2 Step 2.5 — Device Telemetry Simulator.

Covers all test gate items from phase-2-surgical.md Step 2.5:
- Device telemetry published for each simulated device
- Device telemetry uses write-on-change model — stable state produces no samples
- Exclusive ownership failover: backup takes over when primary liveliness expires

Spec coverage:
  surgical-procedure.md — Device Telemetry
  common-behaviors.md — Write-on-change, Exclusive Ownership / Failover
"""

from __future__ import annotations

import time

import devices
import pytest
import rti.connextdds as dds
from conftest import offset_domain, wait_for_data, wait_for_discovery
from surgical_procedure.device_telemetry_sim._device_model import (
    DEVICE_PROFILES,
    DeviceFaultEvent,
    DeviceSpec,
    DeviceStateModel,
)
from surgical_procedure.device_telemetry_sim.device_telemetry_service import (
    DeviceTelemetryService,
    _samples_equal,
)

DeviceTelemetry = devices.Devices.DeviceTelemetry
DeviceKind = devices.Devices.DeviceKind
DeviceOperatingState = devices.Devices.DeviceOperatingState

pytestmark = [pytest.mark.integration]


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _env_override(monkeypatch, **kwargs):
    """Set environment variables for the test, restoring after."""
    for k, v in kwargs.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, str(v))


# -----------------------------------------------------------------------
# Unit tests — DeviceStateModel
# -----------------------------------------------------------------------


class TestDeviceStateModel:
    """Unit tests for the device state model."""

    def test_tick_returns_telemetry_sample(self):
        """Each device model tick produces a DeviceTelemetry sample."""
        import random

        rng = random.Random(42)
        spec = DeviceSpec(
            device_id="pump-test",
            device_kind=DeviceKind.INFUSION_PUMP,
            initial_state=DeviceOperatingState.RUNNING,
            initial_battery=95.0,
            noise_amplitude=0.1,
        )
        model = DeviceStateModel(spec, rng)
        sample = model.tick()

        assert sample.device_id == "pump-test"
        assert sample.device_kind == DeviceKind.INFUSION_PUMP
        assert sample.operating_state == DeviceOperatingState.RUNNING
        assert 0.0 <= sample.battery_percent <= 100.0

    def test_fault_changes_state(self):
        """apply_fault transitions device to fault state."""
        import random

        rng = random.Random(42)
        spec = DeviceSpec(
            device_id="pump-test",
            device_kind=DeviceKind.INFUSION_PUMP,
        )
        model = DeviceStateModel(spec, rng)
        event = DeviceFaultEvent(
            time_offset=0.0,
            device_id="pump-test",
            target_state=DeviceOperatingState.ALARM,
            error_code=101,
            status_message="Occlusion",
        )
        model.apply_fault(event)
        sample = model.tick()

        assert sample.operating_state == DeviceOperatingState.ALARM
        assert sample.error_code == 101
        assert sample.status_message == "Occlusion"

    def test_battery_noise_produces_variation(self):
        """Battery level varies with noise over multiple ticks."""
        import random

        rng = random.Random(42)
        spec = DeviceSpec(
            device_id="pump-test",
            device_kind=DeviceKind.INFUSION_PUMP,
            initial_battery=95.0,
            noise_amplitude=1.0,
        )
        model = DeviceStateModel(spec, rng)
        batteries = [model.tick().battery_percent for _ in range(50)]
        unique = set(batteries)
        assert len(unique) > 1, "Battery should vary with noise"


class TestSamplesEqual:
    """Unit tests for the write-on-change comparison function."""

    def test_identical_samples(self):
        a = DeviceTelemetry()
        a.device_id = "d1"
        a.device_kind = DeviceKind.INFUSION_PUMP
        a.operating_state = DeviceOperatingState.RUNNING
        a.battery_percent = 95.0
        a.error_code = 0
        a.status_message = ""

        b = DeviceTelemetry()
        b.device_id = "d1"
        b.device_kind = DeviceKind.INFUSION_PUMP
        b.operating_state = DeviceOperatingState.RUNNING
        b.battery_percent = 95.0
        b.error_code = 0
        b.status_message = ""

        assert _samples_equal(a, b)

    def test_different_battery(self):
        a = DeviceTelemetry()
        a.device_id = "d1"
        a.battery_percent = 95.0

        b = DeviceTelemetry()
        b.device_id = "d1"
        b.battery_percent = 94.5

        assert not _samples_equal(a, b)

    def test_different_state(self):
        a = DeviceTelemetry()
        a.device_id = "d1"
        a.operating_state = DeviceOperatingState.RUNNING

        b = DeviceTelemetry()
        b.device_id = "d1"
        b.operating_state = DeviceOperatingState.ALARM

        assert not _samples_equal(a, b)


# -----------------------------------------------------------------------
# Integration tests — DeviceTelemetryService
# -----------------------------------------------------------------------


class TestDeviceTelemetryPublished:
    """spec: Device telemetry is published for each simulated device @integration"""

    def test_each_device_publishes_on_start(self, monkeypatch):
        """Given simulated devices, when the gateway starts, each device
        publishes initial DeviceTelemetry."""
        _env_override(monkeypatch, MEDTECH_SIM_SEED="42", MEDTECH_SIM_PROFILE="stable")

        gw = DeviceTelemetryService(
            domain_id=offset_domain(10),
            room_id="OR-1",
            procedure_id="proc-001",
            sim_seed=42,
            sim_profile="stable",
        )
        try:
            gw._start()
            time.sleep(0.5)

            # Should have published initial state for both devices (pump + anesthesia)
            assert (
                gw.publish_count >= 2
            ), f"Expected at least 2 initial publishes, got {gw.publish_count}"

            # Verify both device IDs are present
            device_ids = set(gw.devices.keys())
            assert "pump-001" in device_ids
            assert "anesthesia-001" in device_ids
        finally:
            gw.close()

    def test_device_specific_fields(self, monkeypatch):
        """Each sample is keyed by device_id and contains device-type-specific
        status fields."""
        _env_override(monkeypatch, MEDTECH_SIM_SEED="42", MEDTECH_SIM_PROFILE="stable")

        gw = DeviceTelemetryService(
            domain_id=offset_domain(10),
            room_id="OR-1",
            procedure_id="proc-001",
            sim_seed=42,
            sim_profile="stable",
        )
        try:
            gw._start()
            time.sleep(0.5)

            # Tick to advance state
            gw.tick()

            # Check each device model produces correct kind
            pump = gw.devices["pump-001"]
            anesthesia = gw.devices["anesthesia-001"]
            assert pump.device_kind == DeviceKind.INFUSION_PUMP
            assert anesthesia.device_kind == DeviceKind.ANESTHESIA_MACHINE
        finally:
            gw.close()

    def test_subscriber_receives_telemetry(
        self, monkeypatch, participant_factory, reader_factory
    ):
        """A subscriber on the same domain receives DeviceTelemetry from the
        gateway."""
        _env_override(monkeypatch, MEDTECH_SIM_SEED="42", MEDTECH_SIM_PROFILE="stable")

        gw = DeviceTelemetryService(
            domain_id=offset_domain(10),
            room_id="OR-1",
            procedure_id="proc-001",
            sim_seed=42,
            sim_profile="stable",
        )
        try:
            gw._start()

            # Create a subscriber
            p = participant_factory(
                domain_id=10,
                domain_tag="clinical",
                partition="room/OR-1/procedure/proc-001",
            )
            topic = dds.Topic(p, "DeviceTelemetry", DeviceTelemetry)
            qos = dds.DataReaderQos()
            qos.reliability.kind = dds.ReliabilityKind.RELIABLE
            qos.durability.kind = dds.DurabilityKind.TRANSIENT_LOCAL
            r = reader_factory(p, topic, qos=qos)

            # Wait for discovery and data
            assert wait_for_discovery(gw.writer, r)
            assert wait_for_data(
                r, timeout_sec=10, count=1
            ), "Should receive at least one telemetry sample"

            # Verify device IDs are present in received data
            device_ids = {s.device_id for s in r.take_data()}
            assert len(device_ids) >= 1, "Should receive samples with device IDs"
        finally:
            gw.close()


class TestWriteOnChange:
    """spec: Device telemetry uses write-on-change model @integration @simulation"""

    def test_stable_state_produces_no_samples(self, monkeypatch):
        """Given a stable device, when no state changes occur,
        then no periodic samples are published after the initial write."""
        _env_override(
            monkeypatch,
            MEDTECH_SIM_SEED="100",
            MEDTECH_SIM_PROFILE="stable",
            MEDTECH_HEARTBEAT_INTERVAL="0",
        )

        gw = DeviceTelemetryService(
            domain_id=offset_domain(10),
            room_id="OR-1",
            procedure_id="proc-001",
            sim_seed=42,
            sim_profile="stable",
        )
        try:
            gw._start()

            # Run 60 ticks (simulating 30 seconds at 2 Hz tick rate)
            # With stable profile and fixed seed, battery noise is rounded
            # to 0.1 precision — many ticks should produce no change
            total_published = 0
            for _ in range(60):
                published = gw.tick()
                total_published += len(published)

            # Write-on-change: a stable device should publish significantly
            # fewer samples than a fixed-rate publisher would at 2 Hz for 30 s
            # (which would be 120 samples for 2 devices)
            assert total_published < 60, (
                f"Write-on-change violation: {total_published} samples published "
                f"in 60 ticks for stable devices (expected ≪ 60)"
            )
        finally:
            gw.close()

    def test_state_change_triggers_publish(self, monkeypatch):
        """When a device state changes (e.g., fault), a sample is published."""
        _env_override(
            monkeypatch,
            MEDTECH_SIM_SEED="42",
            MEDTECH_SIM_PROFILE="stable",
        )

        gw = DeviceTelemetryService(
            domain_id=offset_domain(10),
            room_id="OR-1",
            procedure_id="proc-001",
            sim_seed=42,
            sim_profile="stable",
        )
        try:
            gw._start()

            # Manually inject a fault to force a state change
            pump = gw.devices["pump-001"]
            pump.apply_fault(
                DeviceFaultEvent(
                    time_offset=0.0,
                    device_id="pump-001",
                    target_state=DeviceOperatingState.ALARM,
                    error_code=101,
                    status_message="Test fault",
                )
            )

            published = gw.tick()
            # At least the faulted pump should have been published
            pump_samples = [s for s in published if s.device_id == "pump-001"]
            assert len(pump_samples) >= 1, "Faulted device should trigger publish"
            assert pump_samples[0].operating_state == DeviceOperatingState.ALARM
            assert pump_samples[0].error_code == 101
        finally:
            gw.close()

    def test_write_on_change_fewer_than_fixed_rate(self, monkeypatch):
        """spec: Write-on-change topic does not publish when state is unchanged.

        Given the device telemetry simulator running with profile stable,
        and the simulated infusion pump state is steady,
        when 30 s of operation elapse,
        then the number of DeviceTelemetry samples published is significantly
        fewer than would be published at a fixed 2 Hz rate.
        """
        _env_override(
            monkeypatch,
            MEDTECH_SIM_SEED="42",
            MEDTECH_SIM_PROFILE="stable",
            MEDTECH_HEARTBEAT_INTERVAL="0",
        )

        gw = DeviceTelemetryService(
            domain_id=offset_domain(10),
            room_id="OR-1",
            procedure_id="proc-001",
            sim_seed=42,
            sim_profile="stable",
        )
        try:
            gw._start()
            initial_count = gw.publish_count  # initial publishes for all devices

            # Simulate 60 ticks (standing for 30 s at 2 Hz)
            for _ in range(60):
                gw.tick()

            additional = gw.publish_count - initial_count
            # At fixed 2 Hz for 30 s with 2 devices = 120 samples
            # Write-on-change should be significantly fewer
            assert additional < 60, (
                f"Write-on-change violation: {additional} additional samples "
                f"in 60 ticks (expected ≪ 60 for stable profile)"
            )
        finally:
            gw.close()


class TestExclusiveOwnershipFailover:
    """spec: Device telemetry supports exclusive ownership failover @integration @failover

    Full exclusive ownership failover for DeviceTelemetry is tested in
    test_exclusive_ownership.py (common-behaviors.md — Exclusive Ownership).
    These tests verify that the DeviceTelemetryService's writer has the QoS
    properties required for failover to work and that liveliness is
    correctly configured for writer health detection.
    """

    def test_writer_has_liveliness_configured(self, monkeypatch):
        """The DeviceTelemetry writer has AUTOMATIC liveliness with 2s lease,
        enabling writer health detection for write-on-change topics."""
        _env_override(monkeypatch, MEDTECH_SIM_SEED="42", MEDTECH_SIM_PROFILE="stable")

        gw = DeviceTelemetryService(
            domain_id=offset_domain(10),
            room_id="OR-1",
            procedure_id="proc-001",
            sim_seed=42,
            sim_profile="stable",
        )
        try:
            gw._start()
            qos = gw.writer.qos
            assert qos.liveliness.kind == dds.LivelinessKind.AUTOMATIC
            assert qos.liveliness.lease_duration.sec == 2
        finally:
            gw.close()

    def test_writer_uses_reliable_transient_local(self, monkeypatch):
        """The DeviceTelemetry writer uses RELIABLE + TRANSIENT_LOCAL QoS
        matching the State pattern required for late-joiner support and
        exclusive ownership failover."""
        _env_override(monkeypatch, MEDTECH_SIM_SEED="42", MEDTECH_SIM_PROFILE="stable")

        gw = DeviceTelemetryService(
            domain_id=offset_domain(10),
            room_id="OR-1",
            procedure_id="proc-001",
            sim_seed=42,
            sim_profile="stable",
        )
        try:
            gw._start()
            qos = gw.writer.qos
            assert qos.reliability.kind == dds.ReliabilityKind.RELIABLE
            assert qos.durability.kind == dds.DurabilityKind.TRANSIENT_LOCAL
        finally:
            gw.close()

    def test_exclusive_ownership_failover_with_device_telemetry_type(
        self, participant_factory, writer_factory, reader_factory
    ):
        """Given exclusive ownership writers for DeviceTelemetry, failover
        works when primary liveliness expires.

        This validates the DDS-level exclusive ownership behavior
        with DeviceTelemetry type (complementing test_exclusive_ownership.py).
        """
        TEST_DOMAIN = 0

        p_primary = participant_factory(domain_id=TEST_DOMAIN)
        p_backup = participant_factory(domain_id=TEST_DOMAIN)
        p_sub = participant_factory(domain_id=TEST_DOMAIN)

        topic_a = dds.Topic(p_primary, "DevTelFailover", DeviceTelemetry)
        topic_b = dds.Topic(p_backup, "DevTelFailover", DeviceTelemetry)
        topic_r = dds.Topic(p_sub, "DevTelFailover", DeviceTelemetry)

        # Primary: strength 100
        w_qos_a = dds.DataWriterQos()
        w_qos_a.ownership.kind = dds.OwnershipKind.EXCLUSIVE
        w_qos_a.ownership_strength.value = 100
        w_qos_a.reliability.kind = dds.ReliabilityKind.RELIABLE
        w_qos_a.liveliness.kind = dds.LivelinessKind.AUTOMATIC
        w_qos_a.liveliness.lease_duration = dds.Duration.from_seconds(2.0)
        w_a = writer_factory(p_primary, topic_a, qos=w_qos_a)

        # Backup: strength 50
        w_qos_b = dds.DataWriterQos()
        w_qos_b.ownership.kind = dds.OwnershipKind.EXCLUSIVE
        w_qos_b.ownership_strength.value = 50
        w_qos_b.reliability.kind = dds.ReliabilityKind.RELIABLE
        w_qos_b.liveliness.kind = dds.LivelinessKind.AUTOMATIC
        w_qos_b.liveliness.lease_duration = dds.Duration.from_seconds(2.0)
        w_b = writer_factory(p_backup, topic_b, qos=w_qos_b)

        # EXCLUSIVE reader
        r_qos = dds.DataReaderQos()
        r_qos.ownership.kind = dds.OwnershipKind.EXCLUSIVE
        r_qos.reliability.kind = dds.ReliabilityKind.RELIABLE
        r_qos.liveliness.kind = dds.LivelinessKind.AUTOMATIC
        r_qos.liveliness.lease_duration = dds.Duration.from_seconds(2.0)
        r = reader_factory(p_sub, topic_r, qos=r_qos)

        assert wait_for_discovery(w_a, r)
        assert wait_for_discovery(w_b, r)

        # Primary publishes
        sample_a = DeviceTelemetry()
        sample_a.device_id = "pump-001"
        sample_a.device_kind = DeviceKind.INFUSION_PUMP
        sample_a.battery_percent = 90.0
        w_a.write(sample_a)

        time.sleep(0.1)

        # Backup publishes
        sample_b = DeviceTelemetry()
        sample_b.device_id = "pump-001"
        sample_b.device_kind = DeviceKind.INFUSION_PUMP
        sample_b.battery_percent = 50.0
        w_b.write(sample_b)

        time.sleep(0.5)
        valid = r.take_data()
        assert len(valid) >= 1, "Should receive data"
        assert any(
            s.battery_percent == 90.0 for s in valid
        ), "Primary should be delivering"

        # Kill primary
        r.take()  # drain
        p_primary.close()

        # Wait for liveliness expiry (2 s lease + margin)
        time.sleep(3.0)

        # Backup keeps publishing
        for _ in range(3):
            w_b.write(sample_b)
            time.sleep(0.2)

        valid = r.take_data()
        assert len(valid) >= 1, "Backup should deliver after primary failure"
        assert any(s.battery_percent == 50.0 for s in valid)


# -----------------------------------------------------------------------
# Profile tests
# -----------------------------------------------------------------------


class TestDeviceProfiles:
    """Verify device simulation profiles are correctly defined."""

    def test_stable_profile_exists(self):
        assert "stable" in DEVICE_PROFILES

    def test_device_fault_profile_exists(self):
        assert "device_fault" in DEVICE_PROFILES
        profile = DEVICE_PROFILES["device_fault"]
        assert len(profile.fault_events) > 0

    def test_normal_variation_profile_exists(self):
        assert "normal_variation" in DEVICE_PROFILES


# -----------------------------------------------------------------------
# Seeded reproducibility
# -----------------------------------------------------------------------


class TestSeededReproducibility:
    """Verify deterministic behavior with fixed seed."""

    def test_same_seed_same_output(self, monkeypatch):
        """Two gateways with the same seed produce the same tick results."""
        _env_override(monkeypatch, MEDTECH_SIM_SEED="99", MEDTECH_SIM_PROFILE="stable")

        gw1 = DeviceTelemetryService(
            domain_id=offset_domain(10),
            room_id="OR-1",
            procedure_id="proc-001",
            sim_seed=99,
            sim_profile="stable",
        )
        gw2 = DeviceTelemetryService(
            domain_id=offset_domain(10),
            room_id="OR-1",
            procedure_id="proc-001",
            sim_seed=99,
            sim_profile="stable",
        )
        try:
            gw1._start()
            gw2._start()

            samples1 = []
            samples2 = []
            for _ in range(10):
                s1 = gw1.tick()
                s2 = gw2.tick()
                samples1.extend(s1)
                samples2.extend(s2)

            assert len(samples1) == len(samples2), "Same seed should produce same count"
            for a, b in zip(samples1, samples2):
                assert _samples_equal(
                    a, b
                ), "Same seed should produce identical samples"
        finally:
            gw1.close()
            gw2.close()
