"""Entry point for the Operator Console simulator.

Usage:
    python -m surgical_procedure.operator_sim

Environment:
    ROOM_ID          Procedure room identifier (default: OR-1)
    PROCEDURE_ID     Procedure identifier (default: proc-001)
"""

from __future__ import annotations

import asyncio
import os
import signal

from .operator_console_service import OperatorConsoleService


def main() -> None:
    room_id = os.environ.get("ROOM_ID", "OR-1")
    procedure_id = os.environ.get("PROCEDURE_ID", "proc-001")

    console = OperatorConsoleService(room_id=room_id, procedure_id=procedure_id)

    loop = asyncio.new_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, console.stop)
    loop.run_until_complete(console.run())


if __name__ == "__main__":
    main()
