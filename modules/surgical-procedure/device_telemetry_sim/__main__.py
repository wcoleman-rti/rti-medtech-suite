"""Entry point for the Device Telemetry Gateway simulator.

Usage:
    python -m surgical_procedure.device_telemetry_sim

Environment:
    ROOM_ID          Procedure room identifier (default: OR-1)
    PROCEDURE_ID     Procedure identifier (default: proc-001)
"""

from __future__ import annotations

import os
import signal
import time

from .device_gateway import DeviceGateway

_running = True


def _shutdown(signum: int, frame: object) -> None:
    global _running
    _running = False


def main() -> None:
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    room_id = os.environ.get("ROOM_ID", "OR-1")
    procedure_id = os.environ.get("PROCEDURE_ID", "proc-001")

    gateway = DeviceGateway(room_id=room_id, procedure_id=procedure_id)
    gateway.start()

    tick_rate_hz = 1.0  # 1 Hz state checks
    interval = 1.0 / tick_rate_hz

    while _running:
        gateway.tick()
        time.sleep(interval)


if __name__ == "__main__":
    main()
