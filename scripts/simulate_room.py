#!/usr/bin/env python3
"""Spawn a complete simulated operating room with N robotic arms.

Usage:
    python scripts/simulate_room.py                    # 1 arm in OR-1
    python scripts/simulate_room.py --arms 3           # 3 arms in OR-1
    python scripts/simulate_room.py --arms 4 --room OR-2 --procedure proc-042
    python scripts/simulate_room.py --arms 2 --no-clinical --no-operational

All subprocesses are reaped on Ctrl-C or SIGTERM.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time

# Table positions assigned round-robin to arms (matches TablePosition enum
# from surgery.idl, excluding UNKNOWN).
_TABLE_POSITIONS = [
    "RIGHT",
    "LEFT",
    "RIGHT_HEAD",
    "LEFT_HEAD",
    "RIGHT_FOOT",
    "LEFT_FOOT",
    "HEAD",
    "FOOT",
]

_PYTHON_SERVICE_HOSTS = {
    "clinical": "surgical_procedure.clinical_service_host",
    "operational": "surgical_procedure.operational_service_host",
}


def _find_routing_service() -> str | None:
    """Locate the rtiroutingservice binary, return None if not found."""
    nddshome = os.environ.get("NDDSHOME", "")
    if nddshome:
        candidate = os.path.join(nddshome, "bin", "rtiroutingservice")
        if os.path.isfile(candidate):
            return candidate
    return None


def _base_env(room_id: str, procedure_id: str) -> dict[str, str]:
    env = os.environ.copy()
    env["ROOM_ID"] = room_id
    env["PROCEDURE_ID"] = procedure_id
    return env


def _find_robot_binary() -> str:
    """Locate the robot-service-host binary."""
    install = os.environ.get("MEDTECH_INSTALL", "install")
    candidate = os.path.join(install, "bin", "robot-service-host")
    if os.path.isfile(candidate):
        return candidate
    build_candidate = os.path.join(
        "build",
        "modules",
        "surgical-procedure",
        "robot_service_host",
        "robot-service-host",
    )
    if os.path.isfile(build_candidate):
        return build_candidate
    raise FileNotFoundError(
        "robot-service-host not found. Run: cmake --build build && cmake --install build"
    )


def _spawn(
    cmd: list[str],
    env: dict[str, str],
    label: str,
) -> subprocess.Popen:
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(f"  [{proc.pid:>6}] {label}")
    return proc


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Spawn a simulated OR with N arms.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--arms",
        type=int,
        default=1,
        metavar="N",
        help="Number of robotic arms (default: 1, max: 8)",
    )
    parser.add_argument(
        "--room",
        type=str,
        default="OR-1",
        help="Room identifier (default: OR-1)",
    )
    parser.add_argument(
        "--procedure",
        type=str,
        default="proc-001",
        help="Procedure identifier (default: proc-001)",
    )
    parser.add_argument(
        "--no-operator",
        action="store_true",
        help="Skip launching the operator service host",
    )
    parser.add_argument(
        "--no-clinical",
        action="store_true",
        help="Skip launching the clinical service host",
    )
    parser.add_argument(
        "--no-operational",
        action="store_true",
        help="Skip launching the operational service host",
    )
    parser.add_argument(
        "--no-bridge",
        action="store_true",
        help="Skip launching Routing Service (bridge Domain 10 → 11 for Dashboard)",
    )
    args = parser.parse_args()

    n_arms = max(1, min(args.arms, 8))
    room = args.room
    procedure = args.procedure
    room_tag = room.lower().replace("-", "")

    robot_bin = _find_robot_binary()
    procs: list[tuple[str, subprocess.Popen]] = []

    print(f"\n{'='*60}")
    print(f"  Simulated OR: {room}  |  Procedure: {procedure}  |  Arms: {n_arms}")
    print(f"{'='*60}\n")

    # ── Robot arms ──────────────────────────────────────────────────
    arm_robot_ids: list[str] = []
    for i in range(1, n_arms + 1):
        pos = _TABLE_POSITIONS[(i - 1) % len(_TABLE_POSITIONS)]
        host_id = f"robot-host-{room_tag}-{i:02d}"
        robot_id = f"arm-{room_tag}-{i:02d}"
        arm_robot_ids.append(robot_id)
        env = _base_env(room, procedure)
        env["HOST_ID"] = host_id
        env["ROBOT_ID"] = robot_id
        label = f"Robot arm {i}/{n_arms}  host={host_id}  robot={robot_id}  pos={pos}"
        proc = _spawn([robot_bin], env, label)
        procs.append((host_id, proc))

    # ── Per-arm operator consoles ───────────────────────────────────
    if not args.no_operator:
        for i, robot_id in enumerate(arm_robot_ids, 1):
            host_id = f"operator-host-{room_tag}-{i:02d}"
            env = _base_env(room, procedure)
            env["HOST_ID"] = host_id
            env["ROBOT_ID"] = robot_id
            label = f"Operator console {i}/{n_arms}  robot={robot_id}"
            proc = _spawn(
                [sys.executable, "-m", "surgical_procedure.operator_service_host"],
                env,
                label,
            )
            procs.append((host_id, proc))

    # ── Python service hosts ────────────────────────────────────────
    skip = set()
    if args.no_clinical:
        skip.add("clinical")
    if args.no_operational:
        skip.add("operational")

    for name, module in _PYTHON_SERVICE_HOSTS.items():
        if name in skip:
            continue
        host_id = f"{name}-host-{room_tag}"
        env = _base_env(room, procedure)
        env["HOST_ID"] = host_id
        label = f"{name.capitalize()} service host  host={host_id}"
        proc = _spawn(
            [sys.executable, "-m", module],
            env,
            label,
        )
        procs.append((host_id, proc))

    # ── Routing Service (Domain 10 → 11 bridge for Dashboard) ──────
    if not args.no_bridge:
        rs_bin = _find_routing_service()
        if rs_bin:
            rs_cfg = os.path.join("services", "routing", "RoutingService.xml")
            if os.path.isfile(rs_cfg):
                env = _base_env(room, procedure)
                label = "Routing Service  (Domain 10 → 11 bridge)"
                proc = _spawn(
                    [rs_bin, "-cfgFile", rs_cfg, "-cfgName", "MedtechBridge"],
                    env,
                    label,
                )
                procs.append(("routing-service", proc))
            else:
                print(f"  ⚠  Routing Service config not found: {rs_cfg}")
                print("     Dashboard will not receive data (no bridge).")
        else:
            print("  ⚠  rtiroutingservice not found in $NDDSHOME/bin/")
            print("     Dashboard will not receive data (no bridge).")
            print("     Use --no-bridge to suppress this warning.")

    print(f"\n  {len(procs)} processes running. Press Ctrl-C to stop all.\n")
    print("  Launch the GUI in another terminal:")
    print("    python -m medtech.gui.app\n")
    print("  Then click 'Start All' in the Controller view.\n")

    # ── Wait / signal handling ──────────────────────────────────────
    shutdown = False

    def _handle_signal(sig: int, _frame: object) -> None:
        nonlocal shutdown
        if not shutdown:
            shutdown = True
            print(f"\n  Caught signal {sig}, shutting down...")

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Wait for any process to exit or for shutdown signal
    try:
        while not shutdown:
            for name, proc in procs:
                ret = proc.poll()
                if ret is not None:
                    print(f"  [{proc.pid}] {name} exited with code {ret}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutdown = True

    # ── Graceful teardown ─────────────────────────────────────────
    print("  Terminating all processes...")
    for name, proc in procs:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)

    deadline = time.monotonic() + 5.0
    for name, proc in procs:
        remaining = max(0.1, deadline - time.monotonic())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        print(f"  [{proc.pid:>6}] {name} — stopped")

    print("\n  All processes stopped.\n")


if __name__ == "__main__":
    main()
