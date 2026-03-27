"""Entry point for the Camera simulator.

Usage:
    python -m surgical_procedure.camera_sim

Environment:
    ROOM_ID          Procedure room identifier (default: OR-1)
    PROCEDURE_ID     Procedure identifier (default: proc-001)
"""

from __future__ import annotations

import asyncio
import os
import signal

from .camera_service import CameraService


def main() -> None:
    room_id = os.environ.get("ROOM_ID", "OR-1")
    procedure_id = os.environ.get("PROCEDURE_ID", "proc-001")

    sim = CameraService(room_id=room_id, procedure_id=procedure_id)

    loop = asyncio.new_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, sim.stop)
    loop.run_until_complete(sim.run())


if __name__ == "__main__":
    main()
