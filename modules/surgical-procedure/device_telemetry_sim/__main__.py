"""Entry point for the Device Telemetry Gateway simulator.

Usage:
    python -m surgical_procedure.device_telemetry_sim

Environment:
    ROOM_ID          Procedure room identifier (default: OR-1)
    PROCEDURE_ID     Procedure identifier (default: proc-001)
"""

from __future__ import annotations

import asyncio
import os
import signal

from .device_telemetry_service import DeviceTelemetryService


def main() -> None:
    room_id = os.environ.get("ROOM_ID", "OR-1")
    procedure_id = os.environ.get("PROCEDURE_ID", "proc-001")

    seed_env = os.environ.get("MEDTECH_SIM_SEED", "")
    sim_seed = int(seed_env) if seed_env else None
    sim_profile = os.environ.get("MEDTECH_SIM_PROFILE", "stable")
    hb_env = os.environ.get("MEDTECH_HEARTBEAT_INTERVAL", "0")
    heartbeat_interval = float(hb_env) if hb_env else 0.0

    gateway = DeviceTelemetryService(
        room_id=room_id,
        procedure_id=procedure_id,
        sim_seed=sim_seed,
        sim_profile=sim_profile,
        heartbeat_interval=heartbeat_interval,
    )

    loop = asyncio.new_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, gateway.stop)
    loop.run_until_complete(gateway.run())


if __name__ == "__main__":
    main()
