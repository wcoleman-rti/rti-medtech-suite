"""Entry point for the Camera simulator.

Usage:
    python -m surgical_procedure.camera_sim

Environment:
    ROOM_ID          Procedure room identifier (default: OR-1)
    PROCEDURE_ID     Procedure identifier (default: proc-001)
"""

from __future__ import annotations

import os
import signal
import time

from .camera_simulator import CameraSimulator

_running = True


def _shutdown(signum: int, frame: object) -> None:
    global _running
    _running = False


def main() -> None:
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    room_id = os.environ.get("ROOM_ID", "OR-1")
    procedure_id = os.environ.get("PROCEDURE_ID", "proc-001")

    sim = CameraSimulator(room_id=room_id, procedure_id=procedure_id)
    sim.start()

    interval = 1.0 / sim.frame_rate_hz

    while _running:
        sim.tick()
        time.sleep(interval)


if __name__ == "__main__":
    main()
