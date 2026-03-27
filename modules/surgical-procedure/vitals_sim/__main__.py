"""Entry point for the Bedside Monitor simulator.

Usage:
    python -m surgical_procedure.vitals_sim

Environment:
    ROOM_ID            Procedure room identifier (default: OR-1)
    PROCEDURE_ID       Procedure identifier (default: proc-001)
    MEDTECH_SIM_SEED   RNG seed for reproducible simulation (optional)
    MEDTECH_SIM_PROFILE  Simulation profile name (default: stable)
"""

from __future__ import annotations

import asyncio
import os
import signal

from .bedside_monitor_service import BedsideMonitorService


def main() -> None:
    room_id = os.environ.get("ROOM_ID", "OR-1")
    procedure_id = os.environ.get("PROCEDURE_ID", "proc-001")
    seed_str = os.environ.get("MEDTECH_SIM_SEED", "")
    sim_seed = int(seed_str) if seed_str else None
    sim_profile = os.environ.get("MEDTECH_SIM_PROFILE", "stable")

    monitor = BedsideMonitorService(
        room_id=room_id,
        procedure_id=procedure_id,
        sim_seed=sim_seed,
        sim_profile=sim_profile,
    )

    loop = asyncio.new_event_loop()

    def _shutdown(signum: int, frame: object) -> None:
        monitor.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    loop.run_until_complete(monitor.run())


if __name__ == "__main__":
    main()
