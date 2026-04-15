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

_FLAT_NETWORKS = [
    "medtech_surgical-net",
    "medtech_hospital-net",
    "medtech_orchestration-net",
]

_WAN_NET = "medtech_wan-net"
_WAN_SUBNET = "172.30.0.0/24"


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


def _hospital_ordinal(name: str) -> int:
    """Derive a 1-based ordinal from a hospital name for subnet/port allocation.

    Allocates sequentially based on how many named hospitals exist.
    """
    networks = _running_networks()
    names: list[str] = []
    for net in sorted(networks):
        parts = net.removeprefix("medtech_").split("_")
        if len(parts) >= 2 and parts[0].startswith("hospital-"):
            if parts[0] not in names:
                names.append(parts[0])
    if name in names:
        return names.index(name) + 1
    return len(names) + 1


def _unnamed_hospital_exists() -> bool:
    """Check if an unnamed (flat-network) hospital is running."""
    networks = _running_networks()
    return "medtech_surgical-net" in networks


def _gui_port(ordinal: int) -> int:
    """Dashboard host port for a hospital ordinal (1→8080, 2→9080, …)."""
    return 8080 + (ordinal - 1) * 1000


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


@run.command("hospital")
@click.option(
    "--name",
    "hospital_name",
    default=None,
    help="Hospital name (enables NAT isolation)",
)
@click.option(
    "--observability", is_flag=True, help="Include Prometheus and Grafana containers"
)
def hospital(hospital_name: str | None, observability: bool) -> None:
    """Start hospital infrastructure (CDS gateway, Routing Service, Collector, GUI)."""
    if hospital_name is None:
        _start_unnamed_hospital(observability)
    else:
        _start_named_hospital(hospital_name, observability)


def _start_unnamed_hospital(observability: bool) -> None:
    """Start a flat-network unnamed hospital."""
    if _unnamed_hospital_exists():
        click.secho(
            "Error: An unnamed hospital is already running. "
            "Use --name to create a named hospital.",
            fg="red",
            err=True,
        )
        sys.exit(1)

    # Create flat networks
    for net in _FLAT_NETWORKS:
        _ensure_network(net)

    gateway_name = "hospital-gateway"
    _start_gateway(gateway_name, _FLAT_NETWORKS, None)
    _start_gui("medtech-gui", _FLAT_NETWORKS[1:], 8080, gateway_name)

    if observability:
        _start_observability(_FLAT_NETWORKS)

    click.echo()
    click.secho("Dashboard: http://localhost:8080", fg="green", bold=True)


def _start_named_hospital(name: str, observability: bool) -> None:
    """Start a named hospital with per-hospital networks and NAT router."""
    ordinal = _hospital_ordinal(name)

    # Per-hospital private networks with explicit subnets
    net_prefix = f"medtech_{name}"
    nets = {
        "surgical": f"{net_prefix}_surgical-net",
        "hospital": f"{net_prefix}_hospital-net",
        "orchestration": f"{net_prefix}_orchestration-net",
    }
    subnets = {
        "surgical": f"10.{ordinal * 10}.1.0/24",
        "hospital": f"10.{ordinal * 10}.2.0/24",
        "orchestration": f"10.{ordinal * 10}.3.0/24",
    }
    for key in nets:
        _ensure_network(nets[key], subnets[key])

    # Shared WAN network
    _ensure_network(_WAN_NET, _WAN_SUBNET)

    # NAT router
    _start_nat_router(name, list(nets.values()), list(subnets.values()))

    # Gateway (CDS + RS + Collector in shared namespace)
    all_nets = list(nets.values())
    gateway_name = f"{name}-gateway"
    _start_gateway(gateway_name, all_nets, name)

    # GUI
    port = _gui_port(ordinal)
    gui_name = f"medtech-gui-{name}"
    _start_gui(gui_name, [nets["hospital"], nets["orchestration"]], port, gateway_name)

    if observability:
        _start_observability(list(nets.values()), name)

    click.echo()
    click.secho(f"Dashboard ({name}): http://localhost:{port}", fg="green", bold=True)


# ---------------------------------------------------------------------------
# Container launchers
# ---------------------------------------------------------------------------


def _start_gateway(
    gateway_name: str,
    networks: list[str],
    hospital_name: str | None,
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
    ]
    for net in networks:
        cmd.extend(["--network", net])
    cmd.extend(
        [
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
    )
    run_cmd(cmd)

    # 2. Routing Service (shares gateway network namespace)
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
            f"NDDS_DISCOVERY_PEERS={cds_peers}",
            "-e",
            f"NDDS_QOS_PROFILES={_MEDTECH_ENV['NDDS_QOS_PROFILES']}",
            "-e",
            "MEDTECH_TRANSPORT_PROFILE=Docker",
            "medtech/routing-service",
        ]
    )
    run_cmd(rs_cmd)

    # 3. Collector Service (shares gateway network namespace)
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
        f"NDDS_DISCOVERY_PEERS={cds_peers}",
        "-v",
        f"{os.environ.get('RTI_LICENSE_FILE', str(root / 'rti_license.dat'))}:"
        "/opt/rti.com/rti_connext_dds-7.6.0/rti_license.dat:ro",
        "rticom/collector-service:7.6.0",
    ]
    run_cmd(collector_cmd)


def _start_nat_router(
    hospital_name: str,
    private_nets: list[str],
    private_subnets: list[str],
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
    ]
    for net in private_nets:
        cmd.extend(["--network", net])
    # Also attach to WAN
    # Note: docker run --network only supports one network.
    # We attach additional networks after creation.
    cmd.extend(
        [
            "-e",
            f"NAT_PRIVATE_SUBNETS={','.join(private_subnets)}",
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
    )
    run_cmd(cmd)

    # Connect to WAN and remaining private networks
    # docker run --network only attaches the first network; connect the rest
    for net in private_nets[1:]:
        run_cmd(
            ["docker", "network", "connect", net, router_name],
            check=False,
        )
    run_cmd(["docker", "network", "connect", _WAN_NET, router_name], check=False)


def _start_gui(
    name: str,
    networks: list[str],
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
    ]
    for net in networks:
        cmd.extend(["--network", net])
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


def _start_observability(networks: list[str], hospital_name: str | None = None) -> None:
    """Launch Prometheus and Grafana containers for local telemetry."""
    root = _project_root()
    suffix = f"-{hospital_name}" if hospital_name else ""
    net = networks[0]  # Attach to first available network

    # Prometheus
    prom_cmd = [
        "docker",
        "run",
        "--rm",
        "-d",
        "--name",
        f"prometheus{suffix}",
        "--label",
        "medtech.dynamic=true",
        "--network",
        net,
        "-p",
        "9090:9090",
        "-v",
        f"{root}/services/observability/prometheus.yml:/etc/prometheus/prometheus.yml:ro",
        "prom/prometheus:v2.51.0",
    ]
    run_cmd(prom_cmd)

    # Grafana
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
        net,
        "-p",
        "3000:3000",
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
