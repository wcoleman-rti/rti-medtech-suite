"""Entry point for the Hospital Dashboard GUI.

Usage::

    python -m hospital_dashboard.dashboard
"""

from __future__ import annotations

import sys

import rti.asyncio  # noqa: F401 — enables async DataReader methods
from PySide6 import QtAsyncio
from PySide6.QtWidgets import QApplication

from .hospital_dashboard import HospitalDashboard


def main() -> None:
    app = QApplication(sys.argv)  # noqa: F841 — QApplication must exist before widgets
    dashboard = HospitalDashboard()
    dashboard.show()

    QtAsyncio.run(dashboard.start(), handle_sigint=True)
    dashboard.close_dds()


if __name__ == "__main__":
    main()
