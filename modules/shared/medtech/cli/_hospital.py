"""``medtech run hospital`` implementation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from medtech.cli._main import run_cmd
from medtech.cli._naming import _running_networks
from medtech.cli._run import run

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def _find_project_root() -> Path:
    """Walk up from this file to find the project root (contains pyproject.toml)."""
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    # Fallback: source tree layout (modules/shared/medtech/cli -> root)
    return Path(__file__).resolve().parents[4]


_PROJECT_ROOT = _find_project_root()

# Common medtech-env variables matching docker-compose.yml x-medtech-env
_MEDTECH_ENV: dict[str, str] = {
    "NDDS_QOS_PROFILES": (
        "/opt/medtech/share/qos/Snippets.xml;"
        "/opt/medtech/share/qos/Patterns.xml;"
        "/opt/medtech/share/qos/Topics.xml;"
        "/opt/medtech/share/qos/Participants.xml;"
        "/opt/medtech/share/domains/RoomDatabuses.xml;"
        "/opt/medtech/share/domains/HospitalDatabuses.xml;"
        "/opt/medtech/share/domains/CloudDatabuses.xml;"
        "/opt/medtech/share/participants/SurgicalParticipants.xml;"
        "/opt/medtech/share/participants/OrchestrationParticipants.xml;"
        "/opt/medtech/share/participants/HospitalParticipants.xml"
    ),
    "MEDTECH_TRANSPORT_PROFILE": "Docker",
    "PYTHONPATH": "/opt/medtech/lib/python/site-packages",
    # Docker QoS timing overrides (non-real-time scheduling)
    "DEADLINE_OPERATOR_INPUT_SEC": "0",
    "DEADLINE_OPERATOR_INPUT_NS": "100000000",
    "DEADLINE_ROBOT_STATE_SEC": "0",
    "DEADLINE_ROBOT_STATE_NS": "100000000",
    "DEADLINE_WAVEFORM_SEC": "0",
    "DEADLINE_WAVEFORM_NS": "200000000",
    "DEADLINE_CAMERA_FRAME_SEC": "0",
    "DEADLINE_CAMERA_FRAME_NS": "200000000",
    "LIFESPAN_OPERATOR_INPUT_SEC": "0",
    "LIFESPAN_OPERATOR_INPUT_NS": "100000000",
}

_WAN_NET = "medtech_wan-net"
_WAN_SUBNET = "172.30.0.0/24"

# Default hospital name when --name is omitted
_DEFAULT_HOSPITAL = "hospitalA"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    """Return the project root, preferring MEDTECH_PROJECT_ROOT env var."""
    env = os.environ.get("MEDTECH_PROJECT_ROOT")
    if env:
        return Path(env)
    return _PROJECT_ROOT


def _config_volumes() -> list[str]:
    """Return -v flags matching the x-config-volumes pattern."""
    root = _project_root()
    license_file = os.environ.get("RTI_LICENSE_FILE", str(root / "rti_license.dat"))
    return [
        "-v",
        f"{root}/interfaces/qos:/opt/medtech/share/qos:ro",
        "-v",
        f"{root}/interfaces/domains:/opt/medtech/share/domains:ro",
        "-v",
        f"{root}/install/share/participants:/opt/medtech/share/participants:ro",
        "-v",
        f"{root}/install/share/resources:/opt/medtech/share/resources:ro",
        "-v",
        f"{license_file}:/opt/rti.com/rti_connext_dds-7.6.0/rti_license.dat:ro",
    ]


def _env_flags(extra: dict[str, str] | None = None) -> list[str]:
    """Return -e flags for the medtech-env variables."""
    env = dict(_MEDTECH_ENV)
    if extra:
        env.update(extra)
    flags: list[str] = []
    for k, v in env.items():
        flags.extend(["-e", f"{k}={v}"])
    return flags


def _ensure_network(name: str, subnet: str | None = None) -> None:
    """Create a Docker network if it doesn't exist."""
    existing = _running_networks()
    if name in existing:
        return
    cmd = ["docker", "network", "create"]
    if subnet:
        cmd.extend(["--subnet", subnet])
    cmd.append(name)
    run_cmd(cmd)


def _detect_hospital_names() -> list[str]:
    """Return sorted list of hospital names detected from running networks.

    Hospital networks match ``medtech_{name}-net`` (no underscore in the
    name portion).  Room networks (``medtech_{hospital}_{room}-net``) and
    the ``medtech_wan-net`` infrastructure network are excluded.
    """
    networks = _running_networks()
    names: list[str] = []
    for net in sorted(networks):
        stripped = net.removeprefix("medtech_")
        if not stripped.endswith("-net"):
            continue
        # Room nets contain an underscore (medtech_{hospital}_{room}-net)
        if "_" in stripped:
            continue
        hname = stripped.removesuffix("-net")
        # Exclude infrastructure networks
        if hname == "wan":
            continue
        if hname not in names:
            names.append(hname)
    return names


def _hospital_ordinal(name: str) -> int:
    """Derive a 1-based ordinal from a hospital name for subnet/port allocation."""
    names = _detect_hospital_names()
    if name in names:
        return names.index(name) + 1
    return len(names) + 1


def _gui_port(ordinal: int) -> int:
    """Dashboard host port for a hospital ordinal (1→8080, 2→9080, …)."""
    return 8080 + (ordinal - 1) * 1000


def _collector_control_port(ordinal: int) -> int:
    """Collector Service control host port for a hospital ordinal (1→19098, 2→20098, …)."""
    return 19098 + (ordinal - 1) * 1000


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


@run.command("hospital")
@click.option(
    "--name",
    "hospital_name",
    default=None,
    help="Hospital name (enables NAT isolation). Defaults to hospitalA.",
)
@click.option(
    "--observability", is_flag=True, help="Include Prometheus and Grafana containers"
)
def hospital(hospital_name: str | None, observability: bool) -> None:
    """Start hospital infrastructure (CDS gateway, Routing Service, Collector, GUI)."""
    named_explicitly = hospital_name is not None
    name = hospital_name or _DEFAULT_HOSPITAL

    # Duplicate validation
    net_name = f"medtech_{name}-net"
    if net_name in _running_networks():
        click.secho(
            f"Error: Hospital '{name}' is already running.",
            fg="red",
            err=True,
        )
        sys.exit(1)

    ordinal = _hospital_ordinal(name)

    if named_explicitly:
        # Named hospital: explicit subnet + WAN + NAT
        subnet = f"10.{ordinal * 10}.1.0/24"
        _ensure_network(net_name, subnet)
        _ensure_network(_WAN_NET, _WAN_SUBNET)
        _start_nat_router(name, net_name, subnet)
    else:
        _ensure_network(net_name)

    gateway_name = f"{name}-gateway"
    _start_gateway(gateway_name, net_name, ordinal)

    port = _gui_port(ordinal)
    gui_name = f"{name}-gui"
    _start_gui(gui_name, net_name, port, gateway_name)

    if observability:
        _start_observability(net_name, name, ordinal)

    click.echo()
    click.secho(f"Dashboard ({name}): http://localhost:{port}", fg="green", bold=True)


# ---------------------------------------------------------------------------
# Container launchers
# ---------------------------------------------------------------------------


def _start_gateway(
    gateway_name: str,
    network: str,
    ordinal: int = 1,
) -> None:
    """Launch the gateway base container (CDS) plus co-located RS and Collector."""
    root = _project_root()
    cds_peers = f"rtps@udpv4://{gateway_name}:7400"

    # 1. CDS base container
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
        network,
        # Collector shares this network namespace; map its control port here.
        "-p",
        f"{_collector_control_port(ordinal)}:19098",
        "-v",
        f"{root}/services/cloud-discovery-service/CloudDiscoveryService.xml:"
        "/opt/medtech/config/CloudDiscoveryService.xml:ro",
        "-v",
        f"{os.environ.get('RTI_LICENSE_FILE', str(root / 'rti_license.dat'))}:"
        "/opt/rti.com/rti_connext_dds-7.6.0/rti_license.dat:ro",
        "rticom/cloud-discovery-service:7.6.0",
        "-cfgFile",
        "/opt/medtech/config/CloudDiscoveryService.xml",
        "-cfgName",
        "DockerCDS",
        "-verbosity",
        "WARN",
    ]
    run_cmd(cmd)

    # 2. Routing Service — Hospital → Cloud bridge (V3.0)
    # The Procedure → Hospital bridge runs in the per-OR gateway (see _or.py).
    # The hospital-level RS will bridge Domain 20 → 30 once the Cloud
    # Routing Service config is implemented.  Suppressed until then.

    # 3. Collector Service (shares gateway network namespace)
    # Loki runs in the observability node (Prometheus's namespace),
    # reachable via the Prometheus container's DNS name.
    hospital_name = gateway_name.removesuffix("-gateway")
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
        # "CFG_NAME=NonSecureForwarderLANtoLAN",
        "CFG_NAME=NonSecureRemoteDebuggingLAN",
        "-e",
        "OBSERVABILITY_DOMAIN=29",
        "-e",
        "OBSERVABILITY_OUTPUT_DOMAIN=39",
        "-e",
        "OBSERVABILITY_OUTPUT_COLLECTOR_PEER=rtps@udpv4://cloud-gateway:7400",
        "-e",
        "OBSERVABILITY_PROMETHEUS_EXPORTER_PORT=19090",
        "-e",
        f"OBSERVABILITY_LOKI_HOSTNAME={loki_host}",
        "-e",
        "OBSERVABILITY_LOKI_EXPORTER_PORT=3100",
        "-e",
        f"NDDS_DISCOVERY_PEERS={cds_peers}",
        "-v",
        f"{os.environ.get('RTI_LICENSE_FILE', str(root / 'rti_license.dat'))}:"
        "/opt/rti.com/rti_connext_dds-7.6.0/rti_license.dat:ro",
        "rticom/collector-service:7.6.0",
    ]
    run_cmd(collector_cmd)


def _start_nat_router(
    hospital_name: str,
    network: str,
    subnet: str,
) -> None:
    """Launch a privileged NAT router container for a named hospital."""
    router_name = f"{hospital_name}-nat"
    cmd = [
        "docker",
        "run",
        "--rm",
        "-d",
        "--name",
        router_name,
        "--privileged",
        "--label",
        "medtech.dynamic=true",
        "--network",
        network,
        "-e",
        f"NAT_PRIVATE_SUBNETS={subnet}",
        "alpine:3.19",
        "sh",
        "-c",
        "apk add --no-cache iptables > /dev/null 2>&1 && "
        "sysctl -w net.ipv4.ip_forward=1 > /dev/null && "
        "for subnet in $(echo $NAT_PRIVATE_SUBNETS | tr ',' ' '); do "
        "iptables -t nat -A POSTROUTING -s $subnet ! -d $subnet -j MASQUERADE; "
        "done && "
        "echo 'NAT router ready' && "
        "sleep infinity",
    ]
    run_cmd(cmd)

    # Connect to WAN
    run_cmd(["docker", "network", "connect", _WAN_NET, router_name], check=False)


def _start_gui(
    name: str,
    network: str,
    host_port: int,
    gateway_name: str,
) -> None:
    """Launch a GUI container."""
    cds_peers = f"rtps@udpv4://{gateway_name}:7400"
    cmd = [
        "docker",
        "run",
        "--rm",
        "-d",
        "--name",
        name,
        "--label",
        "medtech.dynamic=true",
        "-p",
        f"{host_port}:8080",
        "--network",
        network,
    ]
    cmd.extend(_config_volumes())
    cmd.extend(
        _env_flags(
            {
                "NDDS_DISCOVERY_PEERS": cds_peers,
                "MEDTECH_NICEGUI_STORAGE_SECRET": os.environ.get(
                    "MEDTECH_NICEGUI_STORAGE_SECRET", "changeme-set-in-env"
                ),
                "MEDTECH_APP_NAME": name,
            }
        )
    )
    cmd.append("medtech/app-python")
    run_cmd(cmd)


def _start_observability(
    network: str, hospital_name: str | None = None, ordinal: int = 1
) -> None:
    """Launch Prometheus, Loki, and Grafana as a co-located observability node.

    Prometheus is the base container (owns the network identity and port
    mappings).  Loki and Grafana join its network namespace via
    ``--network container:prometheus-{suffix}``, so all three share a
    single IP and can reach each other on ``localhost``.

    Host ports are offset by hospital ordinal (1000 stride) to avoid
    collisions in multi-hospital scenarios::

        Hospital 1: Prometheus 9090, Loki 3100, Grafana 3000
        Hospital 2: Prometheus 10090, Loki 4100, Grafana 4000

    Maximum 8 concurrent hospitals before port ranges overlap with
    other well-known services — see ``Port Allocation`` in README.

    Collectors (in the gateway namespace) reach Loki via the Prometheus
    container's DNS hostname on the hospital network.
    """
    root = _project_root()
    suffix = f"-{hospital_name}" if hospital_name else ""
    base_name = f"prometheus{suffix}"
    offset = (ordinal - 1) * 1000
    prom_port = 9090 + offset
    loki_port = 3100 + offset
    grafana_port = 3000 + offset

    # Prometheus — base container (owns all host-mapped ports)
    prom_cmd = [
        "docker",
        "run",
        "--rm",
        "-d",
        "--name",
        base_name,
        "--label",
        "medtech.dynamic=true",
        "--network",
        network,
        "-p",
        f"{prom_port}:9090",
        "-p",
        f"{loki_port}:3100",
        "-p",
        f"{grafana_port}:3000",
        "-v",
        f"{root}/services/observability/prometheus.yml:/etc/prometheus/prometheus.yml:ro",
        "prom/prometheus:v2.51.0",
    ]
    run_cmd(prom_cmd)

    # Loki — shares Prometheus network namespace
    loki_cmd = [
        "docker",
        "run",
        "--rm",
        "-d",
        "--name",
        f"loki{suffix}",
        "--label",
        "medtech.dynamic=true",
        "--network",
        f"container:{base_name}",
        "grafana/loki:2.9.0",
    ]
    run_cmd(loki_cmd)

    # Grafana — shares Prometheus network namespace
    nddshome = os.environ.get("NDDSHOME", "/opt/rti.com/rti_connext_dds-7.6.0")
    grafana_cmd = [
        "docker",
        "run",
        "--rm",
        "-d",
        "--name",
        f"grafana{suffix}",
        "--label",
        "medtech.dynamic=true",
        "--network",
        f"container:{base_name}",
        "-e",
        "GF_SECURITY_ADMIN_PASSWORD=admin",
        "-e",
        "GF_AUTH_ANONYMOUS_ENABLED=true",
        "-e",
        "GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer",
        "-v",
        f"{root}/services/observability/grafana/provisioning:/etc/grafana/provisioning:ro",
        "-v",
        f"{nddshome}/resource/app/app_support/observability/templates/grafana/dashboards/General:/var/lib/grafana/dashboards:ro",
        "grafana/grafana:10.4.0",
    ]
    run_cmd(grafana_cmd)
