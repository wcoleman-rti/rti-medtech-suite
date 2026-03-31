"""Device telemetry gateway — DeviceTelemetry publisher.

Publishes DeviceTelemetry on the Procedure domain (clinical tag) using
the write-on-change publication model: samples are published only when
device parameters change, faults occur, or mode transitions happen.

Supports exclusive ownership for primary/backup pattern. Ownership
strength is configurable at construction time.

Follows the canonical application architecture in vision/dds-consistency.md §3.
Uses generated entity name constants from app_names.idl.
Implements medtech.Service for orchestration lifecycle management.
"""

from __future__ import annotations

import asyncio
import random
import time

import app_names
import devices
import rti.connextdds as dds
from medtech.service import Service, ServiceState
from medtech.dds import initialize_connext
from medtech.log import ModuleName, init_logging

from ._device_model import DEVICE_PROFILES, DeviceProfile, DeviceStateModel

names = app_names.MedtechEntityNames.SurgicalParticipants

DeviceTelemetry = devices.Devices.DeviceTelemetry
DeviceOperatingState = devices.Devices.DeviceOperatingState

log = init_logging(ModuleName.SURGICAL_PROCEDURE)


def _samples_equal(a: DeviceTelemetry, b: DeviceTelemetry) -> bool:
    """Compare two DeviceTelemetry samples for logical equality.

    All fields are compared except timestamp-like fields (which always
    change). This implements the write-on-change comparison defined in
    vision/data-model.md — a state change is any field difference
    excluding timestamps.

    Battery percentage uses a noise-threshold tolerance (±0.5%) to prevent
    sub-perceptual noise from triggering publishes. This mirrors the
    RiskScore noise threshold (±0.05) defined in data-model.md.
    """
    return (
        a.device_id == b.device_id
        and a.device_kind == b.device_kind
        and a.operating_state == b.operating_state
        and abs(a.battery_percent - b.battery_percent) < 0.5
        and a.error_code == b.error_code
        and a.status_message == b.status_message
    )


class DeviceTelemetryService(Service):
    """Device telemetry gateway simulator.

    Simulates infusion pump and anesthesia machine telemetry. Publishes
    DeviceTelemetry using write-on-change — samples are published only
    when the logical state differs from the last-published sample.

    The class owns its DomainParticipant and DeviceTelemetry writer.
    Public interface is domain-meaningful — no DDS types exposed via
    the tick/run interface.
    Implements medtech.Service for orchestration lifecycle management.
    """

    def __init__(
        self,
        room_id: str,
        procedure_id: str,
        *,
        participant: dds.DomainParticipant | None = None,
        sim_seed: int | None = None,
        sim_profile: str = "stable",
        heartbeat_interval: float = 0.0,
    ) -> None:
        self._room_id = room_id
        self._procedure_id = procedure_id
        self._svc_state = ServiceState.STOPPED
        self._stop_event: asyncio.Event | None = None

        # --- RNG ---
        if sim_seed is not None:
            self._rng = random.Random(sim_seed)
        else:
            self._rng = random.Random()

        # --- Profile ---
        self._profile: DeviceProfile = DEVICE_PROFILES.get(
            sim_profile, DEVICE_PROFILES["stable"]
        )

        # --- Device state models ---
        self._devices: dict[str, DeviceStateModel] = {}
        for spec in self._profile.device_specs:
            self._devices[spec.device_id] = DeviceStateModel(spec, self._rng)

        # --- Pending fault events (sorted by time offset) ---
        self._pending_faults = sorted(
            list(self._profile.fault_events), key=lambda e: e.time_offset
        )

        # --- DDS entities (dual-mode participant) ---
        if participant is None:
            initialize_connext()
            provider = dds.QosProvider.default
            self._participant = provider.create_participant_from_config(
                names.CLINICAL_DEVICE_GW
            )
            partition = f"room/{room_id}/procedure/{procedure_id}"
            qos = self._participant.qos
            qos.partition.name = [partition]
            self._participant.qos = qos
        else:
            self._participant = participant

        writer_any = self._participant.find_datawriter(names.DEVICE_TELEMETRY_WRITER)
        if writer_any is None:
            raise RuntimeError(f"Writer not found: {names.DEVICE_TELEMETRY_WRITER}")

        self._writer = dds.DataWriter(writer_any)

        # --- Write-on-change tracking ---
        self._last_published: dict[str, DeviceTelemetry] = {}

        # --- Heartbeat (optional observability aid) ---
        self._heartbeat_interval = heartbeat_interval
        self._last_heartbeat: dict[str, float] = {}

        # --- Timing ---
        self._sim_start: float | None = None
        self._last_fault_idx = -1
        self._publish_count = 0

    def _start(self) -> None:
        """Enable participant and begin DDS discovery.

        Publishes the initial state for all devices so late joiners
        receive current state via TRANSIENT_LOCAL.
        """
        self._participant.enable()
        self._sim_start = time.monotonic()
        log.notice(
            f"DeviceTelemetryService enabled: room={self._room_id}, "
            f"devices={list(self._devices.keys())}, "
            f"profile={self._profile.name}"
        )

        # Publish initial state for all devices (TRANSIENT_LOCAL seeding)
        for device_id, model in self._devices.items():
            sample = model.tick()
            self._writer.write(sample)
            self._last_published[device_id] = sample
            self._last_heartbeat[device_id] = time.monotonic()
            self._publish_count += 1

    def tick(self) -> list[DeviceTelemetry]:
        """Advance all device models by one simulation tick.

        Applies any pending fault events whose time has arrived.
        Publishes only devices whose state has changed (write-on-change).

        Returns the list of samples that were actually published.
        """
        self._apply_scheduled_faults()

        published = []
        now = time.monotonic()

        for device_id, model in self._devices.items():
            sample = model.tick()
            last = self._last_published.get(device_id)

            should_publish = last is None or not _samples_equal(sample, last)

            # Optional heartbeat re-publication for observability
            if (
                not should_publish
                and self._heartbeat_interval > 0
                and device_id in self._last_heartbeat
            ):
                elapsed = now - self._last_heartbeat[device_id]
                if elapsed >= self._heartbeat_interval:
                    should_publish = True

            if should_publish:
                self._writer.write(sample)
                self._last_published[device_id] = sample
                self._last_heartbeat[device_id] = now
                self._publish_count += 1
                published.append(sample)

        return published

    @property
    def publish_count(self) -> int:
        """Total number of samples published since start()."""
        return self._publish_count

    @property
    def devices(self) -> dict[str, DeviceStateModel]:
        """Access device state models (for testing/inspection)."""
        return self._devices

    @property
    def participant(self) -> dds.DomainParticipant:
        """Access the underlying participant (for test setup only)."""
        return self._participant

    @property
    def writer(self) -> dds.DataWriter:
        """Access the underlying writer (for test setup only)."""
        return self._writer

    def close(self) -> None:
        """Close the participant and release DDS resources."""
        self._participant.close()

    # --- medtech.Service interface ---

    async def run(self) -> None:
        self._svc_state = ServiceState.STARTING
        self._stop_event = asyncio.Event()
        self._start()
        self._svc_state = ServiceState.RUNNING

        interval = 1.0  # 1 Hz
        while not self._stop_event.is_set():
            self.tick()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

        self._svc_state = ServiceState.STOPPING
        self._svc_state = ServiceState.STOPPED

    @property
    def name(self) -> str:
        return "DeviceTelemetryService"

    @property
    def state(self) -> ServiceState:
        return self._svc_state

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    def _apply_scheduled_faults(self) -> None:
        """Apply any pending fault events whose time offset has arrived."""
        if self._sim_start is None:
            return

        elapsed = time.monotonic() - self._sim_start
        while self._pending_faults:
            event = self._pending_faults[0]
            if elapsed >= event.time_offset:
                self._pending_faults.pop(0)
                model = self._devices.get(event.device_id)
                if model is not None:
                    model.apply_fault(event)
                    log.notice(
                        f"Device fault applied: {event.device_id} → "
                        f"{event.target_state}, error={event.error_code}"
                    )
            else:
                break
