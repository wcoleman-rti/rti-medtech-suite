"""Entry point for the Operator Console simulator.

Usage:
    python -m surgical_procedure.operator_sim

Environment:
    ROOM_ID          Procedure room identifier (default: OR-1)
    PROCEDURE_ID     Procedure identifier (default: proc-001)
"""

from __future__ import annotations

import os
import signal
import time

from .operator_console import OperatorConsole

_running = True


def _shutdown(signum: int, frame: object) -> None:
    global _running
    _running = False


def main() -> None:
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    room_id = os.environ.get("ROOM_ID", "OR-1")
    procedure_id = os.environ.get("PROCEDURE_ID", "proc-001")

    console = OperatorConsole(room_id=room_id, procedure_id=procedure_id)
    console.start()

    # Allow discovery before sending the initial command
    time.sleep(2)

    # Publish initial SafetyInterlock (inactive) so robot knows it's safe
    console.set_interlock(active=False)

    # Send RobotCommand to transition robot IDLE → OPERATIONAL
    console.send_command()

    interval = 1.0 / console.input_rate_hz

    while _running:
        console.tick()
        time.sleep(interval)

    console.close()


if __name__ == "__main__":
    main()
