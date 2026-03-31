"""Entry point for the Digital Twin Display application.

Usage:
    python -m surgical_procedure.digital_twin

Environment:
    ROOM_ID          Procedure room identifier (default: OR-1)
    PROCEDURE_ID     Procedure identifier (default: proc-001)
"""

from __future__ import annotations

import os
import sys

import rti.asyncio  # noqa: F401 — enables async DataReader methods
from PySide6 import QtAsyncio
from PySide6.QtWidgets import QApplication

from .digital_twin_display import DigitalTwinDisplay


def main() -> None:
    room_id = os.environ.get("ROOM_ID", "OR-1")
    procedure_id = os.environ.get("PROCEDURE_ID", "proc-001")

    app = QApplication(sys.argv)  # noqa: F841 — QApplication must exist before widgets
    display = DigitalTwinDisplay(room_id=room_id, procedure_id=procedure_id)
    display.show()

    QtAsyncio.run(display.start(), handle_sigint=True)
    display.close_dds()


if __name__ == "__main__":
    main()
