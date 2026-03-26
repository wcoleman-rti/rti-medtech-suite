"""Entry point for the Bedside Monitor simulator.

Usage:
    python -m surgical_procedure.vitals_sim

Environment:
    ROOM_ID          Procedure room identifier (default: OR-1)
    PROCEDURE_ID     Procedure identifier (default: proc-001)
"""

from __future__ import annotations

import os
import signal
import time

from .bedside_monitor import BedsideMonitor

_running = True


def _shutdown(signum: int, frame: object) -> None:
    global _running
    _running = False


def main() -> None:
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    room_id = os.environ.get("ROOM_ID", "OR-1")
    procedure_id = os.environ.get("PROCEDURE_ID", "proc-001")

    monitor = BedsideMonitor(room_id=room_id, procedure_id=procedure_id)
    monitor.start()

    vitals_interval = 1.0       # 1 Hz
    waveform_interval = 0.02    # 50 Hz

    next_vitals = time.monotonic()
    next_waveform = time.monotonic()

    while _running:
        now = time.monotonic()

        if now >= next_waveform:
            monitor.tick_waveform()
            next_waveform += waveform_interval

        if now >= next_vitals:
            monitor.tick_vitals()
            next_vitals += vitals_interval

        # Sleep until the next event
        next_event = min(next_vitals, next_waveform)
        sleep_time = next_event - time.monotonic()
        if sleep_time > 0:
            time.sleep(sleep_time)


if __name__ == "__main__":
    main()
