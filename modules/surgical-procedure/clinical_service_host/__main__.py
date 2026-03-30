"""Entry point for the Clinical Service Host.

Usage::

    HOST_ID=clinical-host-or1 ROOM_ID=OR-1 PROCEDURE_ID=OR1-001 \
        python -m surgical_procedure.clinical_service_host
"""

from __future__ import annotations

import asyncio
import os
import signal

from .clinical_service_host import make_clinical_service_host


def main() -> None:
    host_id = os.environ.get("HOST_ID", "clinical-host-001")
    room_id = os.environ.get("ROOM_ID", "OR-1")
    procedure_id = os.environ.get("PROCEDURE_ID", "proc-001")

    host = make_clinical_service_host(host_id, room_id, procedure_id)

    loop = asyncio.new_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, host.stop)
    loop.run_until_complete(host.run())


if __name__ == "__main__":
    main()
