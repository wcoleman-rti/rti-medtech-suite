"""``medtech run or`` implementation."""

from __future__ import annotations

import os
import sys

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


def _twin_port_base(hospital_name: str) -> int:
    """Base port for twin containers.  hospitalA=8081, 2nd hospital=9081, …"""
    names = _detect_hospital_names()
    if hospital_name in names:
        ordinal = names.index(hospital_name) + 1
    else:
        ordinal = 1
    return 8081 + (ordinal - 1) * 1000


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
    containers = _running_containers()
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


def _next_twin_port(hospital_name: str) -> int:
    """Auto-assign the next available twin port for the hospital."""
    base = _twin_port_base(hospital_name)
    containers = _running_containers()
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

# Service host containers to start per OR
_SERVICE_HOSTS = [
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

# Additional per-room containers: core services and simulators
_ROOM_SERVICES = [
    {
        "role": "procedure-context",
        "image": "medtech/app-python",
        "command": ["python", "-m", "surgical_procedure.procedure_context_service"],
    },
    {
        "role": "robot-controller",
        "image": "medtech/app-cpp",
        "command": ["/opt/medtech/bin/robot-controller"],
    },
    {
        "role": "operator-sim",
        "image": "medtech/app-python",
        "command": ["python", "-m", "surgical_procedure.operator_sim"],
    },
    {
        "role": "vitals-sim",
        "image": "medtech/app-python",
        "command": ["python", "-m", "surgical_procedure.vitals_sim"],
    },
    {
        "role": "camera-sim",
        "image": "medtech/app-python",
        "command": ["python", "-m", "surgical_procedure.camera_sim"],
    },
    {
        "role": "device-telemetry",
        "image": "medtech/app-python",
        "command": ["python", "-m", "surgical_procedure.device_telemetry_sim"],
    },
]


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
    "--twin-port", type=int, default=None, help="Host port for the digital twin GUI."
)
def or_cmd(
    or_name: str | None, hospital_name: str | None, twin_port: int | None
) -> None:
    """Spawn per-OR containers (room-gateway, service hosts, digital twin)."""
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

    # Auto-assign twin port
    if twin_port is None:
        twin_port = _next_twin_port(target["name"])

    # Auto-assign controller port
    controller_port = _next_controller_port(target["name"])

    root = _project_root()

    # Room gateway: dual-homed on room-net + hospital-net
    room_gw = f"{target['name']}-{or_key}-gateway"
    room_cds_peers = f"rtps@udpv4://{room_gw}:7400"
    hospital_cds_peers = f"rtps@udpv4://{target['name']}-gateway:7400"
    _start_room_gateway(room_gw, room_net, target["net"], root, hospital_cds_peers)

    # Service host containers — all on room-net only
    procedure_id = f"{or_name}-001"
    for svc in _SERVICE_HOSTS:
        container_name = f"{target['name']}-{svc['role']}-{or_key}"
        host_id = f"{svc['role'].replace('-service-host', '-host')}-{or_key}"
        extra_env = {
            "ROOM_ID": or_name,
            "PROCEDURE_ID": procedure_id,
            "HOST_ID": host_id,
            "MEDTECH_APP_NAME": container_name,
            "NDDS_DISCOVERY_PEERS": room_cds_peers,
        }
        # Robot needs ROBOT_ID
        if "robot" in svc["role"]:
            extra_env["ROBOT_ID"] = f"arm-{or_key}-a"

        _start_service_container(
            name=container_name,
            image=svc["image"],
            command=svc["command"],
            networks=[room_net],
            extra_env=extra_env,
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
        # Robot controller needs ROBOT_ID
        if "robot" in svc["role"]:
            extra_env["ROBOT_ID"] = f"arm-{or_key}-a"

        _start_service_container(
            name=container_name,
            image=svc["image"],
            command=svc["command"],
            networks=[room_net],
            extra_env=extra_env,
        )

    # Digital twin container — room-net only
    twin_name = f"{target['name']}-medtech-twin-{or_key}"
    twin_url = f"http://localhost:{twin_port}"

    # Procedure Controller container — room-net only
    ctrl_name = f"{target['name']}-medtech-controller-{or_key}"
    ctrl_url = f"http://localhost:{controller_port}"

    # Start twin with cross-reference to controller
    _start_service_container(
        name=twin_name,
        image="medtech/app-python",
        command=["python", "-m", "surgical_procedure.digital_twin"],
        networks=[room_net],
        extra_env={
            "ROOM_ID": or_name,
            "PROCEDURE_ID": procedure_id,
            "MEDTECH_APP_NAME": twin_name,
            "MEDTECH_GUI_EXTERNAL_URL": twin_url,
            "MEDTECH_CONTROLLER_URL": f"{ctrl_url}/controller/{or_name}",
            "NDDS_DISCOVERY_PEERS": room_cds_peers,
        },
        port_mapping=f"{twin_port}:8080",
    )

    # Start controller with cross-reference to twin
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
            "MEDTECH_TWIN_URL": f"{twin_url}/twin/{or_name}",
            "NDDS_DISCOVERY_PEERS": room_cds_peers,
        },
        port_mapping=f"{controller_port}:8080",
    )

    # Summary
    click.echo()
    click.secho(f"OR: {or_name}", bold=True)
    click.echo(f"Hospital: {target['name']}")
    click.secho(f"Controller: {ctrl_url}/controller/{or_name}", fg="green")
    click.secho(f"Twin: {twin_url}/twin/{or_name}", fg="green")


# ---------------------------------------------------------------------------
# Container launchers
# ---------------------------------------------------------------------------


def _start_room_gateway(
    gateway_name: str,
    room_net: str,
    hospital_net: str,
    root: "os.PathLike[str]",
    hospital_cds_peers: str,
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
        "CFG_NAME=NonSecureLAN",
        "-e",
        "OBSERVABILITY_DOMAIN=20",
        "-e",
        "OBSERVABILITY_PROMETHEUS_EXPORTER_PORT=19090",
        "-e",
        "OBSERVABILITY_LOKI_HOSTNAME=loki",
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
