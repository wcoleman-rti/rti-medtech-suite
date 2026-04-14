"""Auto-name generation helpers for hospitals and ORs."""

from __future__ import annotations

import json
import subprocess


def _running_networks() -> list[str]:
    """Return names of Docker networks matching the medtech naming convention."""
    result = subprocess.run(
        [
            "docker",
            "network",
            "ls",
            "--filter",
            "name=medtech_",
            "--format",
            "{{.Name}}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [n.strip() for n in result.stdout.strip().splitlines() if n.strip()]


def _running_containers(prefix: str = "medtech") -> list[dict]:
    """Return parsed JSON for running containers matching *prefix*."""
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name={prefix}", "--format", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    containers = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if line:
            try:
                containers.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return containers


def next_hospital_name() -> str | None:
    """Return the next available hospital name, or None if unnamed is OK."""
    networks = _running_networks()
    hospital_names: set[str] = set()
    for net in networks:
        # Named hospitals create networks like medtech_hospital-a_surgical-net
        parts = net.removeprefix("medtech_").split("_")
        if len(parts) >= 2 and parts[0].startswith("hospital-"):
            hospital_names.add(parts[0])
    return None  # Caller decides; this helper is for enumeration


def next_or_name(hospital: str | None = None) -> str:
    """Return the next sequential OR name (OR-1, OR-2, …) for the hospital."""
    # Look for containers with service-host or twin naming
    containers = _running_containers()
    or_numbers: set[int] = set()
    for c in containers:
        name = c.get("Names", "")
        # Patterns: clinical-service-host-or1, medtech-twin-or2,
        # hospital-a-clinical-service-host-or3
        lower = name.lower()
        if hospital:
            prefix = hospital.lower() + "-"
            if not lower.startswith(prefix):
                continue
        # Extract OR number from container names like *-or<N>
        for part in lower.split("-"):
            if part.startswith("or") and part[2:].isdigit():
                or_numbers.add(int(part[2:]))
    n = 1
    while n in or_numbers:
        n += 1
    return f"OR-{n}"
