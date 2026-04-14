"""``medtech run or`` implementation."""

from __future__ import annotations

import os
import sys

import click
from medtech.cli._hospital import (
    _MEDTECH_ENV,
    _config_volumes,
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

    Each entry has ``name`` (str or None for unnamed) and ``nets``
    (dict mapping role → network name).
    """
    networks = _running_networks()
    hospitals: list[dict] = []

    # Check for unnamed (flat) hospital
    if "medtech_surgical-net" in networks:
        hospitals.append(
            {
                "name": None,
                "nets": {
                    "surgical": "medtech_surgical-net",
                    "hospital": "medtech_hospital-net",
                    "orchestration": "medtech_orchestration-net",
                },
            }
        )

    # Check for named hospitals
    seen: set[str] = set()
    for net in sorted(networks):
        parts = net.removeprefix("medtech_").split("_")
        if len(parts) >= 2 and parts[0].startswith("hospital-"):
            hname = parts[0]
            if hname not in seen:
                seen.add(hname)
                prefix = f"medtech_{hname}"
                hospitals.append(
                    {
                        "name": hname,
                        "nets": {
                            "surgical": f"{prefix}_surgical-net",
                            "hospital": f"{prefix}_hospital-net",
                            "orchestration": f"{prefix}_orchestration-net",
                        },
                    }
                )

    return hospitals


def _twin_port_base(hospital_name: str | None) -> int:
    """Base port for twin containers.  Unnamed=8081, hospital-a=8081, hospital-b=9081, …"""
    if hospital_name is None:
        return 8081
    # Derive ordinal from existing networks
    networks = _running_networks()
    names: list[str] = []
    for net in sorted(networks):
        parts = net.removeprefix("medtech_").split("_")
        if len(parts) >= 2 and parts[0].startswith("hospital-"):
            if parts[0] not in names:
                names.append(parts[0])
    if hospital_name in names:
        ordinal = names.index(hospital_name) + 1
    else:
        ordinal = 1
    return 8081 + (ordinal - 1) * 1000


def _next_twin_port(hospital_name: str | None) -> int:
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
        "needs_orch": True,
    },
    {
        "role": "operational-service-host",
        "image": "medtech/app-python",
        "command": ["python", "-m", "surgical_procedure.operational_service_host"],
        "needs_orch": True,
    },
    {
        "role": "operator-service-host",
        "image": "medtech/app-python",
        "command": ["python", "-m", "surgical_procedure.operator_service_host"],
        "needs_orch": True,
    },
    {
        "role": "robot-service-host",
        "image": "medtech/app-cpp",
        "command": ["/opt/medtech/bin/robot-service-host"],
        "needs_orch": True,
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
    h_prefix = f"{target['name']}-" if target["name"] else ""

    # Auto-assign twin port
    if twin_port is None:
        twin_port = _next_twin_port(target["name"])

    root = _project_root()
    gateway_name_for_hospital = (
        f"{target['name']}-gateway" if target["name"] else "hospital-gateway"
    )
    cds_peers = f"rtps@udpv4://{gateway_name_for_hospital}:7400"

    # 1. Room-gateway (CDS + RS + Collector in shared namespace)
    room_gw = f"{h_prefix}{or_name.lower()}-gateway"
    _start_room_gateway(room_gw, target["nets"], root, cds_peers)

    # 2. Service host containers
    procedure_id = f"{or_name}-001"
    for svc in _SERVICE_HOSTS:
        container_name = f"{h_prefix}{svc['role']}-{or_key}"
        networks_to_join = [target["nets"]["surgical"]]
        if svc["needs_orch"]:
            networks_to_join.append(target["nets"]["orchestration"])
        host_id = f"{svc['role'].replace('-service-host', '-host')}-{or_key}"
        extra_env = {
            "ROOM_ID": or_name,
            "PROCEDURE_ID": procedure_id,
            "HOST_ID": host_id,
            "MEDTECH_APP_NAME": container_name,
            "NDDS_DISCOVERY_PEERS": cds_peers,
        }
        # Robot needs ROBOT_ID
        if "robot" in svc["role"]:
            extra_env["ROBOT_ID"] = f"arm-{or_key}-a"

        _start_service_container(
            name=container_name,
            image=svc["image"],
            command=svc["command"],
            networks=networks_to_join,
            extra_env=extra_env,
        )

    # 3. Digital twin container
    twin_name = f"{h_prefix}medtech-twin-{or_key}"
    twin_url = f"http://localhost:{twin_port}"
    _start_service_container(
        name=twin_name,
        image="medtech/app-python",
        command=["python", "-m", "surgical_procedure.digital_twin"],
        networks=[target["nets"]["surgical"], target["nets"]["hospital"]],
        extra_env={
            "ROOM_ID": or_name,
            "PROCEDURE_ID": procedure_id,
            "MEDTECH_APP_NAME": twin_name,
            "MEDTECH_GUI_EXTERNAL_URL": twin_url,
            "NDDS_DISCOVERY_PEERS": cds_peers,
        },
        port_mapping=f"{twin_port}:8080",
    )

    # Summary
    click.echo()
    click.secho(f"OR: {or_name}", bold=True)
    if target["name"]:
        click.echo(f"Hospital: {target['name']}")
    click.secho(f"Twin: {twin_url}/twin/{or_name}", fg="green")


# ---------------------------------------------------------------------------
# Container launchers
# ---------------------------------------------------------------------------


def _start_room_gateway(
    gateway_name: str,
    nets: dict[str, str],
    root: "os.PathLike[str]",
    cds_peers: str,
) -> None:
    """Launch room-level CDS + RS + Collector in shared namespace."""
    license_file = os.environ.get("RTI_LICENSE_FILE", str(root / "rti_license.dat"))

    # CDS base
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
        nets["surgical"],
    ]
    cmd.extend(
        [
            "-v",
            f"{root}/services/cloud-discovery-service/CloudDiscoveryService.xml:"
            "/opt/medtech/config/CloudDiscoveryService.xml:ro",
            "-v",
            f"{license_file}:/opt/rti.com/rti_connext_dds-7.6.0/rti_license.dat:ro",
            "medtech/cloud-discovery-service",
            "-cfgFile",
            "/opt/medtech/config/CloudDiscoveryService.xml",
            "-cfgName",
            "DockerCDS",
            "-verbosity",
            "WARN",
        ]
    )
    run_cmd(cmd)

    # Connect to additional networks
    for role in ("hospital", "orchestration"):
        if role in nets:
            run_cmd(
                ["docker", "network", "connect", nets[role], gateway_name],
                check=False,
            )

    # RS (shared namespace)
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
            "NDDS_DISCOVERY_PEERS=rtps@udpv4://localhost:7400",
            "-e",
            f"NDDS_QOS_PROFILES={_MEDTECH_ENV['NDDS_QOS_PROFILES']}",
            "-e",
            "MEDTECH_TRANSPORT_PROFILE=Docker",
            "medtech/routing-service",
        ]
    )
    run_cmd(rs_cmd)

    # Collector (shared namespace)
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
        "NDDS_DISCOVERY_PEERS=rtps@udpv4://localhost:7400",
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
