"""``medtech run`` command group."""

from __future__ import annotations

from medtech.cli._main import main


@main.group()
def run() -> None:
    """Run simulation components (hospital, OR)."""
