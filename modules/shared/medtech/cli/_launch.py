"""``medtech launch`` command implementation."""

from __future__ import annotations

import sys

import click
from medtech.cli._main import main, run_cmd
from medtech.cli._scenarios import SCENARIOS


@main.command("launch")
@click.argument("scenario", default="distributed", required=False)
@click.option(
    "--list", "list_scenarios", is_flag=True, help="List available scenarios."
)
@click.option("--dockgraph", is_flag=True, help="Start DockGraph topology visualizer.")
def launch(scenario: str, list_scenarios: bool, dockgraph: bool) -> None:
    """Launch a simulation scenario (default: distributed)."""
    if list_scenarios:
        _print_scenario_list()
        return

    if scenario not in SCENARIOS:
        click.secho(
            f"Error: Unknown scenario '{scenario}'. "
            f"Available: {', '.join(SCENARIOS.keys())}",
            fg="red",
            err=True,
        )
        sys.exit(1)

    spec = SCENARIOS[scenario]

    if "hospitals" in spec:
        # Multi-site mode
        _launch_multi_site(spec)
    else:
        # Single-hospital mode (distributed / minimal)
        _launch_single_hospital(spec)

    if dockgraph:
        _start_dockgraph()

    click.echo()
    click.secho("Simulation ready.", fg="green", bold=True)


def _print_scenario_list() -> None:
    """Print scenarios in a table."""
    name_w = max(len(k) for k in SCENARIOS)
    name_w = max(name_w, 8)
    click.echo(f"{'SCENARIO':<{name_w}}  DESCRIPTION")
    click.echo(f"{'-' * name_w}  {'-' * 50}")
    for name, spec in SCENARIOS.items():
        click.echo(f"{name:<{name_w}}  {spec['description']}")


def _launch_single_hospital(spec: dict) -> None:
    """Launch a single unnamed hospital with ORs."""
    from medtech.cli._hospital import hospital as hospital_cmd
    from medtech.cli._or import or_cmd

    ctx = click.Context(hospital_cmd)
    ctx.invoke(hospital_cmd, hospital_name=None, observability=False)

    for room in spec.get("rooms", []):
        ctx = click.Context(or_cmd)
        ctx.invoke(or_cmd, or_name=room, hospital_name=None, twin_port=None)


def _launch_multi_site(spec: dict) -> None:
    """Launch multiple named hospitals with ORs."""
    from medtech.cli._hospital import hospital as hospital_cmd
    from medtech.cli._or import or_cmd

    for h in spec["hospitals"]:
        ctx = click.Context(hospital_cmd)
        ctx.invoke(hospital_cmd, hospital_name=h["name"], observability=False)

        for room in h.get("rooms", []):
            ctx = click.Context(or_cmd)
            ctx.invoke(or_cmd, or_name=room, hospital_name=h["name"], twin_port=None)


def _start_dockgraph() -> None:
    """Launch the DockGraph topology sidecar."""
    run_cmd(
        [
            "docker",
            "run",
            "-d",
            "--name",
            "medtech-dockgraph",
            "-p",
            "7800:7800",
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock:ro",
            "--label",
            "dockgraph.self=true",
            "--label",
            "medtech.dynamic=true",
            "dockgraph/dockgraph",
        ]
    )
    click.secho("DockGraph: http://localhost:7800", fg="green")
