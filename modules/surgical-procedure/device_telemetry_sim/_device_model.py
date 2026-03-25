"""Device state simulation model for write-on-change telemetry.

Each simulated device (infusion pump, anesthesia machine) has a state model
driven by a scenario profile. State changes are detected by comparing the
current DeviceTelemetry sample against the last-published sample. Only actual
state transitions trigger a DDS write — this is the write-on-change
publication model defined in vision/data-model.md.

The simulation model uses the same SignalModel infrastructure as the vitals
simulator for smooth temporal transitions and seeded reproducibility.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import devices

DeviceKind = devices.Devices.DeviceKind
DeviceOperatingState = devices.Devices.DeviceOperatingState
DeviceTelemetry = devices.Devices.DeviceTelemetry


@dataclass
class DeviceSpec:
    """Specification for a single simulated device."""

    device_id: str
    device_kind: DeviceKind
    initial_state: DeviceOperatingState = DeviceOperatingState.RUNNING
    initial_battery: float = 100.0
    battery_drain_rate: float = 0.0  # percent per tick (0 = no drain)
    noise_amplitude: float = 0.3  # battery noise per tick


@dataclass
class DeviceFaultEvent:
    """A scheduled fault event for a device."""

    time_offset: float  # seconds from simulation start
    device_id: str
    target_state: DeviceOperatingState
    error_code: int = 0
    status_message: str = ""


@dataclass
class DeviceProfile:
    """A named scenario profile for device telemetry simulation."""

    name: str
    device_specs: list[DeviceSpec] = field(default_factory=list)
    fault_events: list[DeviceFaultEvent] = field(default_factory=list)


class DeviceStateModel:
    """Manages the simulated state of a single device.

    Tracks battery level with optional drain and noise. State transitions
    are determined by the scenario profile's scheduled fault events.
    """

    def __init__(self, spec: DeviceSpec, rng: random.Random) -> None:
        self._spec = spec
        self._rng = rng
        self._state = spec.initial_state
        self._battery = spec.initial_battery
        self._error_code = 0
        self._status_message = ""

    @property
    def device_id(self) -> str:
        return self._spec.device_id

    @property
    def device_kind(self) -> DeviceKind:
        return self._spec.device_kind

    def tick(self) -> DeviceTelemetry:
        """Advance one simulation tick.

        Battery drains and noise is applied. Returns the current
        DeviceTelemetry sample (caller decides whether to publish
        based on write-on-change comparison).
        """
        if self._state == DeviceOperatingState.RUNNING:
            self._battery -= self._spec.battery_drain_rate
            self._battery += self._rng.gauss(0, self._spec.noise_amplitude)
            self._battery = max(0.0, min(100.0, self._battery))

        sample = DeviceTelemetry()
        sample.device_id = self._spec.device_id
        sample.device_kind = self._spec.device_kind
        sample.operating_state = self._state
        sample.battery_percent = round(self._battery, 1)
        sample.error_code = self._error_code
        sample.status_message = self._status_message
        return sample

    def apply_fault(self, event: DeviceFaultEvent) -> None:
        """Apply a scheduled fault event to this device."""
        self._state = event.target_state
        self._error_code = event.error_code
        self._status_message = event.status_message


# ---------------------------------------------------------------------------
# Default device specs
# ---------------------------------------------------------------------------

DEFAULT_PUMP = DeviceSpec(
    device_id="pump-001",
    device_kind=DeviceKind.INFUSION_PUMP,
    initial_state=DeviceOperatingState.RUNNING,
    initial_battery=95.0,
    battery_drain_rate=0.0,  # stable profile: no drain
    noise_amplitude=0.3,
)

DEFAULT_ANESTHESIA = DeviceSpec(
    device_id="anesthesia-001",
    device_kind=DeviceKind.ANESTHESIA_MACHINE,
    initial_state=DeviceOperatingState.RUNNING,
    initial_battery=100.0,
    battery_drain_rate=0.0,
    noise_amplitude=0.2,
)


# ---------------------------------------------------------------------------
# Device profiles
# ---------------------------------------------------------------------------

DEVICE_PROFILES: dict[str, DeviceProfile] = {}


def _register(profile: DeviceProfile) -> None:
    DEVICE_PROFILES[profile.name] = profile


# stable — both devices run normally, no faults
_register(
    DeviceProfile(
        name="stable",
        device_specs=[DEFAULT_PUMP, DEFAULT_ANESTHESIA],
        fault_events=[],
    )
)

# normal_variation — slight battery fluctuation, no faults
_register(
    DeviceProfile(
        name="normal_variation",
        device_specs=[
            DeviceSpec(
                device_id="pump-001",
                device_kind=DeviceKind.INFUSION_PUMP,
                initial_state=DeviceOperatingState.RUNNING,
                initial_battery=92.0,
                battery_drain_rate=0.01,
                noise_amplitude=0.5,
            ),
            DeviceSpec(
                device_id="anesthesia-001",
                device_kind=DeviceKind.ANESTHESIA_MACHINE,
                initial_state=DeviceOperatingState.RUNNING,
                initial_battery=98.0,
                battery_drain_rate=0.005,
                noise_amplitude=0.3,
            ),
        ],
        fault_events=[],
    )
)

# device_fault — pump develops a fault after 15 seconds
_register(
    DeviceProfile(
        name="device_fault",
        device_specs=[
            DeviceSpec(
                device_id="pump-001",
                device_kind=DeviceKind.INFUSION_PUMP,
                initial_state=DeviceOperatingState.RUNNING,
                initial_battery=95.0,
                battery_drain_rate=0.02,
                noise_amplitude=0.5,
            ),
            DEFAULT_ANESTHESIA,
        ],
        fault_events=[
            DeviceFaultEvent(
                time_offset=15.0,
                device_id="pump-001",
                target_state=DeviceOperatingState.ALARM,
                error_code=101,
                status_message="Occlusion detected — infusion halted",
            ),
        ],
    )
)
