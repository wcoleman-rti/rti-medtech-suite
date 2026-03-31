"""Entry point for the Procedure Controller GUI.

Usage::

    ROOM_ID=OR-1 python -m hospital_dashboard.procedure_controller
"""

from __future__ import annotations

import os
import sys

import rti.asyncio  # noqa: F401 — enables async DataReader methods
from PySide6 import QtAsyncio
from PySide6.QtWidgets import QApplication

from .procedure_controller import ProcedureController


def main() -> None:
    room_id = os.environ.get("ROOM_ID", "OR-1")

    app = QApplication(sys.argv)  # noqa: F841 — QApplication must exist before widgets
    controller = ProcedureController(room_id=room_id)
    controller.show()

    QtAsyncio.run(controller.start(), handle_sigint=True)
    controller.close_dds()


if __name__ == "__main__":
    main()
