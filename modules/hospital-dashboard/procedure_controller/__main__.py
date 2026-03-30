"""Entry point for the Procedure Controller GUI.

Usage::

    ROOM_ID=OR-1 python -m hospital_dashboard.procedure_controller
"""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from .procedure_controller import ProcedureController


def main() -> None:
    room_id = os.environ.get("ROOM_ID", "OR-1")

    app = QApplication(sys.argv)
    controller = ProcedureController(room_id=room_id)
    controller.show()

    exit_code = app.exec()
    controller.close_dds()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
