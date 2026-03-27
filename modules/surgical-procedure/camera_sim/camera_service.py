"""Camera simulator — CameraFrame publisher.

Publishes CameraFrame on the Procedure domain (operational tag) using
Stream pattern QoS at a configured frame rate (default 30 Hz).

Simulates frame metadata (camera ID, sequence number, timestamp,
resolution) and a synthetic image reference as a small JPEG stub.

Follows the canonical application architecture in vision/dds-consistency.md §3.
Uses generated entity name constants from app_names.idl.
Implements medtech.Service for orchestration lifecycle management.
"""

from __future__ import annotations

import asyncio
import struct
import time

import app_names
import common
import imaging
import rti.connextdds as dds
from medtech.service import Service, ServiceState
from medtech_dds_init.dds_init import initialize_connext
from medtech_logging import ModuleName, init_logging

names = app_names.MedtechEntityNames.SurgicalParticipants

CameraFrame = imaging.Imaging.CameraFrame
Time_t = common.Common.Time_t

log = init_logging(ModuleName.SURGICAL_PROCEDURE)


class CameraService(Service):
    """Surgical camera simulator publishing CameraFrame at a configured rate.

    Owns its DomainParticipant (created from XML configuration
    SurgicalParticipants::OperationalPub) and looks up the CameraFrame
    writer by entity name.
    Implements medtech.Service for orchestration lifecycle management.
    """

    DEFAULT_FRAME_RATE_HZ = 30
    DEFAULT_WIDTH = 1920
    DEFAULT_HEIGHT = 1080

    def __init__(
        self,
        room_id: str,
        procedure_id: str,
        camera_id: str = "camera-001",
        frame_rate_hz: int = DEFAULT_FRAME_RATE_HZ,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        *,
        participant: dds.DomainParticipant | None = None,
    ) -> None:
        self._camera_id = camera_id
        self._frame_rate_hz = frame_rate_hz
        self._width = width
        self._height = height
        self._sequence = 0
        self._state = ServiceState.STOPPED
        self._stop_event: asyncio.Event | None = None

        # --- DDS entities (dual-mode participant) ---
        if participant is None:
            initialize_connext()
            provider = dds.QosProvider.default
            self._participant = provider.create_participant_from_config(
                names.OPERATIONAL_PUB
            )
            partition = f"room/{room_id}/procedure/{procedure_id}"
            qos = self._participant.qos
            qos.partition.name = [partition]
            self._participant.qos = qos
        else:
            self._participant = participant

        frame_any = self._participant.find_datawriter(names.CAMERA_FRAME_WRITER)
        if frame_any is None:
            raise RuntimeError(f"Writer not found: {names.CAMERA_FRAME_WRITER}")

        self._frame_writer = dds.DataWriter(frame_any)

    def _start(self) -> None:
        """Enable participant and begin DDS discovery."""
        self._participant.enable()
        log.notice(
            f"CameraService enabled: camera={self._camera_id}, "
            f"rate={self._frame_rate_hz} Hz"
        )

    def tick(self) -> CameraFrame:
        """Generate and publish one CameraFrame sample.

        Returns the published CameraFrame for testing/inspection.
        """
        now = time.time()
        sec = int(now)
        nsec = int((now - sec) * 1_000_000_000)

        frame_id = f"{self._camera_id}-{self._sequence:08d}"

        # Synthetic JPEG stub: 16 bytes encoding sequence + timestamp
        data = struct.pack(">QQ", self._sequence, sec)

        frame = CameraFrame(
            camera_id=self._camera_id,
            timestamp=Time_t(sec=sec & 0xFFFFFFFF, nsec=nsec),
            frame_id=frame_id,
            data=list(data),
            format="jpeg",
        )
        self._frame_writer.write(frame)
        self._sequence += 1
        return frame

    @property
    def frame_rate_hz(self) -> int:
        """Configured frame rate in Hz."""
        return self._frame_rate_hz

    @property
    def participant(self) -> dds.DomainParticipant:
        """Access the underlying participant (for test setup only)."""
        return self._participant

    # --- medtech.Service interface ---

    async def run(self) -> None:
        self._state = ServiceState.STARTING
        self._stop_event = asyncio.Event()
        self._start()
        self._state = ServiceState.RUNNING

        interval = 1.0 / self._frame_rate_hz
        while not self._stop_event.is_set():
            self.tick()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

        self._state = ServiceState.STOPPING
        self._state = ServiceState.STOPPED

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    @property
    def name(self) -> str:
        return "CameraService"

    @property
    def state(self) -> ServiceState:
        return self._state
