"""Entry point for the Operator Service Host.

Usage::

    HOST_ID=operator-host-or1 ROOM_ID=OR-1 \
        python -m surgical_procedure.operator_service_host
"""

from __future__ import annotations

import asyncio
import os

import rti.asyncio  # noqa: F401 — RTI asyncio integration
from medtech.gui_runtime import NiceGuiRuntime
from nicegui import app, background_tasks, ui

from .operator_service_host import make_operator_service_host


def main() -> None:
    host_id = os.environ.get("HOST_ID", "operator-host-001")
    room_id = os.environ.get("ROOM_ID", "OR-1")
    robot_id = os.environ.get("ROBOT_ID", "robot-001")
    gui_runtime = NiceGuiRuntime.from_env()

    host = make_operator_service_host(host_id, room_id, robot_id, gui_runtime)
    host_task: asyncio.Task | None = None

    @app.on_startup
    async def _start_host() -> None:
        nonlocal host_task
        host_task = background_tasks.create(host.run())

    @app.on_shutdown
    async def _stop_host() -> None:
        host.stop()
        if host_task is not None:
            await asyncio.gather(host_task, return_exceptions=True)

    ui.page("/")(lambda: ui.navigate.to(f"/twin/{room_id}"))

    gui_runtime.run(title="Operator Service Host — Medtech Suite")


if __name__ == "__main__":
    main()
