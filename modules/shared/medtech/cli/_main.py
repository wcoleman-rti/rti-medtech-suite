"""CLI entry point and shared helpers."""

from __future__ import annotations

import json
import subprocess
import sys

import click


def run_cmd(
    args: list[str],
    *,
    check: bool = True,
    capture: bool = False,
    env_override: dict[str, str] | None = None,
) -> int:
    """Print and execute a shell command. Returns the exit code."""
    cmd_str = " ".join(args)
    click.secho(f"  $ {cmd_str}", fg="cyan")
    env = None
    if env_override:
        import os

        env = {**os.environ, **env_override}
    if capture:
        result = subprocess.run(args, capture_output=True, text=True, env=env)
        if result.stdout:
            click.echo(result.stdout.rstrip())
        if result.returncode != 0 and result.stderr:
            click.secho(result.stderr.rstrip(), fg="red", err=True)
        if check and result.returncode != 0:
            sys.exit(result.returncode)
        return result.returncode
    result = subprocess.run(args, env=env)
    if check and result.returncode != 0:
        sys.exit(result.returncode)
    return result.returncode


@click.group()
def main() -> None:
    """medtech — build, launch, and manage the medtech suite."""


@main.command()
def build() -> None:
    """Build the project using CMake."""
    import os

    if not os.path.isdir("build"):
        run_cmd(["cmake", "-B", "build", "-S", "."])
    run_cmd(["cmake", "--build", "build", "--target", "install"])


@main.command()
def status() -> None:
    """Show running medtech containers and GUI URLs."""
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            "name=medtech",
            "--filter",
            "name=cloud-discovery",
            "--filter",
            "name=routing-service",
            "--filter",
            "name=collector",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    click.secho(
        "  $ docker ps --filter name=medtech --filter name=cloud-discovery "
        "--filter name=routing-service --filter name=collector --format json",
        fg="cyan",
    )

    if result.returncode != 0:
        click.secho(f"docker ps failed: {result.stderr.strip()}", fg="red", err=True)
        sys.exit(result.returncode)

    lines = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip()]
    if not lines:
        click.echo("No medtech containers running.")
        return

    containers = []
    for line in lines:
        try:
            containers.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not containers:
        click.echo("No medtech containers running.")
        return

    # Table header
    name_w = max(len(c.get("Names", "")) for c in containers)
    name_w = max(name_w, 4)
    click.echo(f"{'NAME':<{name_w}}  {'STATUS':<20}  PORTS")
    click.echo(f"{'-' * name_w}  {'-' * 20}  {'-' * 30}")

    gui_urls: list[str] = []
    for c in containers:
        name = c.get("Names", "")
        state = c.get("Status", "")
        ports = c.get("Ports", "")
        click.echo(f"{name:<{name_w}}  {state:<20}  {ports}")

        # Detect GUI URLs from port mappings
        if ports:
            for mapping in ports.split(","):
                mapping = mapping.strip()
                if "->8080" in mapping or "->8081" in mapping:
                    # Extract host port
                    host_part = mapping.split("->")[0].strip()
                    if ":" in host_part:
                        host_port = host_part.rsplit(":", 1)[-1]
                    else:
                        host_port = host_part
                    gui_urls.append(f"http://localhost:{host_port}")

    if gui_urls:
        click.echo()
        click.secho("GUI URLs:", bold=True)
        for url in gui_urls:
            click.secho(f"  {url}", fg="green")


@main.command()
def stop() -> None:
    """Stop all medtech containers and remove Docker networks."""
    # Find and stop containers
    result = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "-q",
            "--filter",
            "name=medtech",
            "--filter",
            "name=cloud-discovery",
            "--filter",
            "name=routing-service",
            "--filter",
            "name=collector",
            "--filter",
            "name=hospital-",
            "--filter",
            "name=prometheus",
            "--filter",
            "name=grafana",
        ],
        capture_output=True,
        text=True,
    )
    container_ids = [
        cid.strip() for cid in result.stdout.strip().splitlines() if cid.strip()
    ]

    if container_ids:
        run_cmd(["docker", "stop"] + container_ids)
        run_cmd(["docker", "rm", "-f"] + container_ids, check=False)
    else:
        click.echo("No medtech containers to stop.")

    # Remove medtech networks
    net_result = subprocess.run(
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
    networks = [n.strip() for n in net_result.stdout.strip().splitlines() if n.strip()]
    if networks:
        run_cmd(["docker", "network", "rm"] + networks, check=False)
    else:
        click.echo("No medtech networks to remove.")
