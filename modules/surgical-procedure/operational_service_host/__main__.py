"""Entry point for the Operational Service Host.

Usage::

    HOST_ID=operational-host-or1 ROOM_ID=OR-1 PROCEDURE_ID=OR1-001 \
        python -m surgical_procedure.operational_service_host
"""

from __future__ import annotations

import asyncio
import os
import signal

from .operational_service_host import make_operational_service_host


def main() -> None:
    host_id = os.environ.get("HOST_ID", "operational-host-001")
    room_id = os.environ.get("ROOM_ID", "OR-1")
    procedure_id = os.environ.get("PROCEDURE_ID", "proc-001")

    host = make_operational_service_host(host_id, room_id, procedure_id)

    loop = asyncio.new_event_loop()
    _shutdown_count = 0

    def _on_signal() -> None:
        nonlocal _shutdown_count
        _shutdown_count += 1
        if _shutdown_count == 1:
            host.stop()
        else:
            os._exit(1)

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _on_signal)
    loop.run_until_complete(host.run())


if __name__ == "__main__":
    main()
