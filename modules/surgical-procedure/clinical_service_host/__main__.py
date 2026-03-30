"""Entry point for the Clinical Service Host.

Usage::

    HOST_ID=clinical-host-or1 ROOM_ID=OR-1 PROCEDURE_ID=OR1-001 \
        python -m surgical_procedure.clinical_service_host
"""

from __future__ import annotations

import asyncio
import os
import signal

import rti.asyncio  # noqa: F401 — RTI asyncio integration

from .clinical_service_host import make_clinical_service_host


async def _run() -> None:
    host_id = os.environ.get("HOST_ID", "clinical-host-001")
    room_id = os.environ.get("ROOM_ID", "OR-1")
    procedure_id = os.environ.get("PROCEDURE_ID", "proc-001")

    host = make_clinical_service_host(host_id, room_id, procedure_id)

    loop = asyncio.get_running_loop()
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

    await host.run()


def main() -> None:
    rti.asyncio.run(_run())


if __name__ == "__main__":
    main()
