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
@click.option("--docker", is_flag=True, help="Build Docker images only (skip CMake).")
@click.option(
    "--no-docker", is_flag=True, help="CMake build only (skip Docker images)."
)
def build(docker: bool, no_docker: bool) -> None:
    """Build the project (CMake + Docker images by default)."""
    import os

    if docker and no_docker:
        click.secho(
            "Error: --docker and --no-docker are mutually exclusive.",
            fg="red",
            err=True,
        )
        raise SystemExit(1)

    run_cmake = not docker  # CMake unless --docker-only
    run_docker = not no_docker  # Docker unless --no-docker

    if run_cmake:
        if not os.path.isdir("build"):
            run_cmd(["cmake", "-B", "build", "-S", "."])
        run_cmd(["cmake", "--build", "build", "--target", "install"])

    if run_docker:
        run_cmd(
            ["docker", "compose", "--profile", "build", "build"],
            check=False,
        )


@main.command()
@click.option(
    "--topology", is_flag=True, help="Show ASCII topology tree with network details."
)
@click.option("--dockgraph", is_flag=True, help="Start DockGraph topology visualizer.")
def status(topology: bool, dockgraph: bool) -> None:
    """Show running medtech containers and GUI URLs."""
    if dockgraph:
        _start_dockgraph()
        return
    if topology:
        _show_topology()
        return

    result = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            "label=medtech.dynamic=true",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    click.secho(
        "  $ docker ps --filter label=medtech.dynamic=true --format json",
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

    gui_urls: set[str] = set()
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
                    gui_urls.add(f"http://localhost:{host_port}")

    if gui_urls:
        click.echo()
        click.secho("GUI URLs:", bold=True)
        for url in sorted(gui_urls):
            click.secho(f"  {url}", fg="green")


@main.command()
def stop() -> None:
    """Stop all medtech containers and remove Docker networks."""
    # Find and stop containers by label (all dynamic containers are labelled)
    result = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "-q",
            "--filter",
            "label=medtech.dynamic=true",
        ],
        capture_output=True,
        text=True,
    )
    container_ids = [
        cid.strip() for cid in result.stdout.strip().splitlines() if cid.strip()
    ]

    if container_ids:
        # Containers are created with --rm, so stop auto-removes them.
        run_cmd(["docker", "stop"] + container_ids)
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


# ---------------------------------------------------------------------------
# Topology viewer (medtech status --topology)
# ---------------------------------------------------------------------------


def _show_topology() -> None:
    """Inspect Docker networks and render an ASCII topology tree."""
    # Find medtech networks
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
    click.secho(
        "  $ docker network ls --filter name=medtech_ --format {{.Name}}",
        fg="cyan",
    )

    network_names = sorted(
        n.strip() for n in net_result.stdout.strip().splitlines() if n.strip()
    )
    if not network_names:
        click.echo("No medtech networks found.")
        return

    # Inspect each network
    network_data: dict[str, dict] = {}
    for net_name in network_names:
        inspect_result = subprocess.run(
            ["docker", "network", "inspect", net_name],
            capture_output=True,
            text=True,
        )
        click.secho(f"  $ docker network inspect {net_name}", fg="cyan")
        if inspect_result.returncode == 0 and inspect_result.stdout.strip():
            try:
                data = json.loads(inspect_result.stdout)
                if data and isinstance(data, list):
                    network_data[net_name] = data[0]
            except json.JSONDecodeError:
                pass

    if not network_data:
        click.echo("No network details available.")
        return

    # Group networks by hospital prefix
    hospitals: dict[str, list[str]] = {}
    wan_nets: list[str] = []
    flat_nets: list[str] = []

    for net_name in network_names:
        bare = net_name.removeprefix("medtech_")
        if bare == "wan-net":
            wan_nets.append(net_name)
        elif "_" in bare and bare.split("_")[0].startswith("hospital-"):
            h_name = bare.split("_")[0]
            hospitals.setdefault(h_name, []).append(net_name)
        else:
            flat_nets.append(net_name)

    # Render flat networks (unnamed hospital)
    if flat_nets:
        click.echo()
        click.secho("(unnamed hospital)", bold=True)
        for i, net_name in enumerate(flat_nets):
            is_last = i == len(flat_nets) - 1
            _render_network(net_name, network_data.get(net_name, {}), is_last)

    # Render named hospitals
    for h_name in sorted(hospitals.keys()):
        click.echo()
        click.secho(h_name, bold=True)
        nets = sorted(hospitals[h_name])
        for i, net_name in enumerate(nets):
            is_last = i == len(nets) - 1
            _render_network(net_name, network_data.get(net_name, {}), is_last)

    # Render WAN
    for net_name in wan_nets:
        click.echo()
        _render_network(net_name, network_data.get(net_name, {}), is_last=True)


def _render_network(net_name: str, data: dict, is_last: bool) -> None:
    """Render a single network's containers as an ASCII sub-tree."""
    subnet = ""
    ipam = data.get("IPAM", {})
    configs = ipam.get("Config", [])
    if configs:
        subnet = configs[0].get("Subnet", "")

    prefix = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
    child_prefix = "    " if is_last else "\u2502   "

    label = f"{net_name} ({subnet})" if subnet else net_name
    click.echo(f"{prefix}{label}")

    containers = data.get("Containers", {})
    if not containers:
        click.echo(f"{child_prefix}(empty)")
        return

    sorted_containers = sorted(containers.values(), key=lambda c: c.get("Name", ""))
    for j, cinfo in enumerate(sorted_containers):
        c_name = cinfo.get("Name", "")
        c_ip = cinfo.get("IPv4Address", "").split("/")[0]
        c_last = j == len(sorted_containers) - 1
        c_prefix = "\u2514\u2500\u2500 " if c_last else "\u251c\u2500\u2500 "
        click.echo(f"{child_prefix}{c_prefix}{c_name:<35} {c_ip}")


# ---------------------------------------------------------------------------
# DockGraph sidecar (medtech status --dockgraph / medtech launch --dockgraph)
# ---------------------------------------------------------------------------

_DOCKGRAPH_NAME = "medtech-dockgraph"


def _start_dockgraph() -> None:
    """Launch the DockGraph topology sidecar, replacing any stale container."""
    # Remove any existing container with the same name (running or stopped).
    subprocess.run(
        ["docker", "rm", "-f", _DOCKGRAPH_NAME],
        capture_output=True,
    )
    run_cmd(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            _DOCKGRAPH_NAME,
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
