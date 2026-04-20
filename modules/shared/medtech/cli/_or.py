"""``medtech run or`` implementation."""

from __future__ import annotations

import os
import sys
from typing import Any

import click
from medtech.cli._hospital import (
    _MEDTECH_ENV,
    _config_volumes,
    _detect_hospital_names,
    _ensure_network,
    _env_flags,
    _project_root,
)
from medtech.cli._main import run_cmd
from medtech.cli._naming import _running_containers, _running_networks, next_or_name
from medtech.cli._run import run

# ---------------------------------------------------------------------------
# Hospital detection helpers
# ---------------------------------------------------------------------------


def _detect_hospitals() -> list[dict]:
    """Return a list of running hospitals.

    Each entry has ``name`` (str) and ``net`` (network name str).
    """
    names = _detect_hospital_names()
    return [{"name": n, "net": f"medtech_{n}-net"} for n in names]


def _controller_port_base(hospital_name: str) -> int:
    """Base port for controller containers.  hospitalA=8091, 2nd hospital=9091, …"""
    names = _detect_hospital_names()
    if hospital_name in names:
        ordinal = names.index(hospital_name) + 1
    else:
        ordinal = 1
    return 8091 + (ordinal - 1) * 1000


def _next_controller_port(hospital_name: str) -> int:
    """Auto-assign the next available controller port for the hospital."""
    base = _controller_port_base(hospital_name)
    containers = _running_containers(hospital_name)
    used_ports: set[int] = set()
    for c in containers:
        ports = c.get("Ports", "")
        if ports:
            for mapping in ports.split(","):
                mapping = mapping.strip()
                if "->" in mapping:
                    host_part = mapping.split("->")[0].strip()
                    if ":" in host_part:
                        port_str = host_part.rsplit(":", 1)[-1]
                    else:
                        port_str = host_part
                    try:
                        used_ports.add(int(port_str))
                    except ValueError:
                        pass
    port = base
    while port in used_ports:
        port += 1
    return port


def _operator_gui_port_base(hospital_name: str) -> int:
    """Base host port for operator-host NiceGUI endpoint."""
    names = _detect_hospital_names()
    if hospital_name in names:
        ordinal = names.index(hospital_name) + 1
    else:
        ordinal = 1
    return 8081 + (ordinal - 1) * 1000


def _next_operator_gui_port(hospital_name: str) -> int:
    """Auto-assign the next available operator-host GUI port."""
    base = _operator_gui_port_base(hospital_name)
    containers = _running_containers(hospital_name)
    used_ports: set[int] = set()
    for c in containers:
        ports = c.get("Ports", "")
        if ports:
            for mapping in ports.split(","):
                mapping = mapping.strip()
                if "->" in mapping:
                    host_part = mapping.split("->")[0].strip()
                    if ":" in host_part:
                        port_str = host_part.rsplit(":", 1)[-1]
                    else:
                        port_str = host_part
                    try:
                        used_ports.add(int(port_str))
                    except ValueError:
                        pass
    port = base
    while port in used_ports:
        port += 1
    return port


def _or_lower(or_name: str) -> str:
    """Convert OR-5 → or5 for container naming."""
    return or_name.lower().replace("-", "")


# ---------------------------------------------------------------------------
# Container definitions
# ---------------------------------------------------------------------------

# Arm letter suffix for robot-id indexing: a, b, c, ...
_ARM_LETTERS = "abcdefghijklmnopqrstuvwxyz"

# Non-arm service hosts started once per OR
_ROOM_SERVICE_HOSTS = [
    {
        "role": "clinical-service-host",
        "image": "medtech/app-python",
        "command": ["python", "-m", "surgical_procedure.clinical_service_host"],
    },
    {
        "role": "operational-service-host",
        "image": "medtech/app-python",
        "command": ["python", "-m", "surgical_procedure.operational_service_host"],
    },
]

# Arm-pair service hosts — one of each per arm in the OR.
# Both receive the same ROBOT_ID so the operator console targets the
# correct robot controller's content-filtered readers.
_ARM_SERVICE_HOSTS = [
    {
        "role": "operator-service-host",
        "image": "medtech/app-python",
        "command": ["python", "-m", "surgical_procedure.operator_service_host"],
    },
    {
        "role": "robot-service-host",
        "image": "medtech/app-cpp",
        "command": ["/opt/medtech/bin/robot-service-host"],
    },
]

# Legacy alias used by existing tests — union of both lists.
_SERVICE_HOSTS = _ROOM_SERVICE_HOSTS + _ARM_SERVICE_HOSTS

# Additional per-room containers: standalone services not managed by a
# service host.  All core services (procedure-context, robot-controller,
# operator, vitals, camera, device-telemetry) are orchestrated through
# their respective service hosts above; listing them here as well would
# create duplicate DDS writers on the same topics with mismatched IDs.
_ROOM_SERVICES: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


@run.command("or")
@click.option(
    "--name",
    "or_name",
    default=None,
    help="OR name (e.g., OR-1). Auto-generated if omitted.",
)
@click.option(
    "--hospital",
    "hospital_name",
    default=None,
    help="Target hospital (required when multiple are running).",
)
@click.option(
    "--arms",
    "num_arms",
    default=1,
    type=click.IntRange(1, len(_ARM_LETTERS)),
    show_default=True,
    help="Number of robot arms to deploy in the OR.",
)
def or_cmd(or_name: str | None, hospital_name: str | None, num_arms: int = 1) -> None:
    """Spawn per-OR containers (room-gateway, service hosts, procedure controller).

    Note: Digital Twin is now a procedure-scoped service deployed by the Procedure
    Controller when a procedure starts. It is no longer a standalone room service.
    """
    hospitals = _detect_hospitals()

    if not hospitals:
        click.secho(
            "Error: No hospital is running. Start one with: medtech run hospital",
            fg="red",
            err=True,
        )
        sys.exit(1)

    # Resolve target hospital
    if hospital_name:
        target = next((h for h in hospitals if h["name"] == hospital_name), None)
        if target is None:
            click.secho(
                f"Error: Hospital '{hospital_name}' not found. "
                f"Running hospitals: {[h['name'] for h in hospitals]}",
                fg="red",
                err=True,
            )
            sys.exit(1)
    elif len(hospitals) == 1:
        target = hospitals[0]
    else:
        click.secho(
            "Error: Multiple hospitals running. Specify --hospital NAME.",
            fg="red",
            err=True,
        )
        sys.exit(1)

    # Auto-generate OR name if needed
    if or_name is None:
        or_name = next_or_name(target["name"])

    or_key = _or_lower(or_name)

    # Duplicate room validation
    room_net = f"medtech_{target['name']}_{or_key}-net"
    if room_net in _running_networks():
        click.secho(
            f"Error: Room '{or_name}' already exists on hospital '{target['name']}'.",
            fg="red",
            err=True,
        )
        sys.exit(1)

    # Create per-room network
    _ensure_network(room_net)

    # Auto-assign controller port
    controller_port = _next_controller_port(target["name"])

    root = _project_root()

    # Room gateway: dual-homed on room-net + hospital-net
    room_gw = f"{target['name']}-{or_key}-gateway"
    room_cds_peers = f"rtps@udpv4://{room_gw}:7400"
    hospital_cds_peers = f"rtps@udpv4://{target['name']}-gateway:7400"
    _start_room_gateway(
        room_gw, room_net, target["net"], root, hospital_cds_peers, target["name"]
    )

    # Service host containers — all on room-net only
    procedure_id = f"{or_name}-001"

    # --- Non-arm service hosts (one per OR) ---
    for svc in _ROOM_SERVICE_HOSTS:
        container_name = f"{target['name']}-{svc['role']}-{or_key}"
        host_id = f"{svc['role'].replace('-service-host', '-host')}-{or_key}"
        extra_env = {
            "ROOM_ID": or_name,
            "PROCEDURE_ID": procedure_id,
            "HOST_ID": host_id,
            "MEDTECH_APP_NAME": container_name,
            "NDDS_DISCOVERY_PEERS": room_cds_peers,
        }
        _start_service_container(
            name=container_name,
            image=svc["image"],
            command=svc["command"],
            networks=[room_net],
            extra_env=extra_env,
        )

    # --- Arm-pair service hosts (one operator + one robot per arm) ---
    for arm_idx in range(num_arms):
        arm_letter = _ARM_LETTERS[arm_idx]
        robot_id = f"arm-{or_key}-{arm_letter}"
        arm_suffix = f"-{arm_letter}" if num_arms > 1 else ""

        for svc in _ARM_SERVICE_HOSTS:
            container_name = f"{target['name']}-{svc['role']}{arm_suffix}-{or_key}"
            host_id = (
                f"{svc['role'].replace('-service-host', '-host')}"
                f"{arm_suffix}-{or_key}"
            )
            extra_env = {
                "ROOM_ID": or_name,
                "PROCEDURE_ID": procedure_id,
                "HOST_ID": host_id,
                "MEDTECH_APP_NAME": container_name,
                "NDDS_DISCOVERY_PEERS": room_cds_peers,
                "ROBOT_ID": robot_id,
            }
            port_mapping = None

            if svc["role"] == "operator-service-host":
                gui_port = _next_operator_gui_port(target["name"])
                extra_env["MEDTECH_GUI_PORT"] = "8080"
                extra_env["MEDTECH_GUI_EXTERNAL_URL"] = f"http://localhost:{gui_port}"
                port_mapping = f"{gui_port}:8080"

            _start_service_container(
                name=container_name,
                image=svc["image"],
                command=svc["command"],
                networks=[room_net],
                extra_env=extra_env,
                port_mapping=port_mapping,
            )

    # Core services and simulators — all on room-net only
    for svc in _ROOM_SERVICES:
        container_name = f"{target['name']}-{svc['role']}-{or_key}"
        extra_env = {
            "ROOM_ID": or_name,
            "PROCEDURE_ID": procedure_id,
            "MEDTECH_APP_NAME": container_name,
            "NDDS_DISCOVERY_PEERS": room_cds_peers,
        }

        _start_service_container(
            name=container_name,
            image=svc["image"],
            command=svc["command"],
            networks=[room_net],
            extra_env=extra_env,
        )

    # Procedure Controller container — room-net only
    ctrl_name = f"{target['name']}-medtech-controller-{or_key}"
    ctrl_url = f"http://localhost:{controller_port}"

    # Start controller (digital twin will be deployed when procedure starts)
    _start_service_container(
        name=ctrl_name,
        image="medtech/app-python",
        command=["python", "-m", "surgical_procedure.procedure_controller"],
        networks=[room_net],
        extra_env={
            "ROOM_ID": or_name,
            "PROCEDURE_ID": procedure_id,
            "HOST_ID": f"controller-{or_key}",
            "MEDTECH_APP_NAME": ctrl_name,
            "MEDTECH_GUI_EXTERNAL_URL": ctrl_url,
            "NDDS_DISCOVERY_PEERS": room_cds_peers,
        },
        port_mapping=f"{controller_port}:8080",
    )

    # Summary
    click.echo()
    click.secho(f"OR: {or_name}", bold=True)
    click.echo(f"Hospital: {target['name']}")
    click.secho(f"Controller: {ctrl_url}/controller/{or_name}", fg="green")
    click.echo("(Digital Twin will be deployed when a procedure starts)")


# ---------------------------------------------------------------------------
# Container launchers
# ---------------------------------------------------------------------------


def _start_room_gateway(
    gateway_name: str,
    room_net: str,
    hospital_net: str,
    root: "os.PathLike[str]",
    hospital_cds_peers: str,
    hospital_name: str = "hospitalA",
) -> None:
    """Launch room-level CDS + RS + Collector in shared namespace."""
    license_file = os.environ.get("RTI_LICENSE_FILE", str(root / "rti_license.dat"))

    # CDS base — on room-net
    cmd = [
        "docker",
        "run",
        "--rm",
        "-d",
        "--name",
        gateway_name,
        "--label",
        "medtech.dynamic=true",
        "--network",
        room_net,
        "-v",
        f"{root}/services/cloud-discovery-service/CloudDiscoveryService.xml:"
        "/opt/medtech/config/CloudDiscoveryService.xml:ro",
        "-v",
        f"{license_file}:/opt/rti.com/rti_connext_dds-7.6.0/rti_license.dat:ro",
        "rticom/cloud-discovery-service:7.6.0",
        "-cfgFile",
        "/opt/medtech/config/CloudDiscoveryService.xml",
        "-cfgName",
        "DockerCDS",
        "-verbosity",
        "WARN",
    ]
    run_cmd(cmd)

    # Connect to hospital network (dual-homed)
    run_cmd(
        ["docker", "network", "connect", hospital_net, gateway_name],
        check=False,
    )

    # RS (shared namespace) — peers: room CDS (localhost) + hospital CDS
    dual_peers = f"rtps@udpv4://localhost:7400,{hospital_cds_peers}"
    rs_cmd = [
        "docker",
        "run",
        "--rm",
        "-d",
        "--name",
        f"{gateway_name}-rs",
        "--network",
        f"container:{gateway_name}",
        "--label",
        "medtech.dynamic=true",
    ]
    rs_cmd.extend(_config_volumes())
    rs_cmd.extend(
        [
            "-v",
            f"{root}/services/routing/RoutingService.xml:"
            "/opt/medtech/config/RoutingService.xml:ro",
            "-e",
            f"NDDS_DISCOVERY_PEERS={dual_peers}",
            "-e",
            f"NDDS_QOS_PROFILES={_MEDTECH_ENV['NDDS_QOS_PROFILES']}",
            "-e",
            "MEDTECH_TRANSPORT_PROFILE=Docker",
            "medtech/routing-service",
            "-cfgFile",
            "/opt/medtech/config/RoutingService.xml",
            "-cfgName",
            "MedtechBridge",
        ]
    )
    run_cmd(rs_cmd)

    # Collector (shared namespace) — peers: room CDS (localhost) + hospital CDS
    # Loki runs in the observability node (Prometheus's namespace),
    # reachable via the Prometheus container's DNS name.
    loki_host = f"prometheus-{hospital_name}"
    collector_cmd = [
        "docker",
        "run",
        "--rm",
        "-d",
        "--name",
        f"{gateway_name}-collector",
        "--network",
        f"container:{gateway_name}",
        "--label",
        "medtech.dynamic=true",
        "-e",
        "CFG_NAME=NonSecureForwarderLANtoLAN",
        "-e",
        "OBSERVABILITY_DOMAIN=19",
        "-e",
        "OBSERVABILITY_OUTPUT_DOMAIN=29",
        "-e",
        f"OBSERVABILITY_OUTPUT_COLLECTOR_PEER={hospital_cds_peers}",
        "-e",
        "OBSERVABILITY_PROMETHEUS_EXPORTER_PORT=19090",
        "-e",
        f"OBSERVABILITY_LOKI_HOSTNAME={loki_host}",
        "-e",
        "OBSERVABILITY_LOKI_EXPORTER_PORT=3100",
        "-e",
        f"NDDS_DISCOVERY_PEERS={dual_peers}",
        "-v",
        f"{license_file}:/opt/rti.com/rti_connext_dds-7.6.0/rti_license.dat:ro",
        "rticom/collector-service:7.6.0",
    ]
    run_cmd(collector_cmd)


def _start_service_container(
    *,
    name: str,
    image: str,
    command: list[str],
    networks: list[str],
    extra_env: dict[str, str],
    port_mapping: str | None = None,
) -> None:
    """Launch a service host or twin container."""
    cmd = [
        "docker",
        "run",
        "--rm",
        "-d",
        "--no-healthcheck",
        "--name",
        name,
        "--label",
        "medtech.dynamic=true",
        "--network",
        networks[0],
    ]
    if port_mapping:
        cmd.extend(["-p", port_mapping])
    cmd.extend(_config_volumes())
    cmd.extend(_env_flags(extra_env))
    cmd.extend([image] + command)
    run_cmd(cmd)

    # Connect to additional networks
    for net in networks[1:]:
        run_cmd(["docker", "network", "connect", net, name], check=False)
