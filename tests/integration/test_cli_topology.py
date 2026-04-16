"""Tests for topology visualization (Phase SIM, Step SIM.7).

Tags: @simulation, @cli
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from medtech.cli._main import main


def _make_network_inspect(name: str, subnet: str, containers: dict) -> str:
    """Build a JSON string mimicking ``docker network inspect`` output."""
    return json.dumps(
        [
            {
                "Name": name,
                "IPAM": {"Config": [{"Subnet": subnet}]},
                "Containers": containers,
            }
        ]
    )


def _container_entry(name: str, ip: str) -> dict:
    """Build a container entry for network inspect data."""
    return {"Name": name, "IPv4Address": f"{ip}/24"}


class TestTopologyBasic:
    """Verify ``medtech status --topology`` renders ASCII tree."""

    @patch("medtech.cli._main.subprocess.run")
    def test_topology_renders_tree(self, mock_subprocess) -> None:
        """--topology renders a non-empty ASCII tree."""
        # Mock docker network ls
        network_names = "medtech_hospitalA_or1-net\nmedtech_hospitalA-net\n"

        room_inspect = _make_network_inspect(
            "medtech_hospitalA_or1-net",
            "172.18.0.0/16",
            {
                "c1": _container_entry("hospitalA-or1-gateway", "172.18.0.2"),
                "c2": _container_entry(
                    "hospitalA-clinical-service-host-or1", "172.18.0.3"
                ),
            },
        )
        hospital_inspect = _make_network_inspect(
            "medtech_hospitalA-net",
            "172.19.0.0/16",
            {
                "c3": _container_entry("hospitalA-gui", "172.19.0.2"),
            },
        )

        def subprocess_side_effect(args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            if "network" in args and "ls" in args:
                result.stdout = network_names
            elif "network" in args and "inspect" in args:
                net_name = args[-1]
                if net_name == "medtech_hospitalA_or1-net":
                    result.stdout = room_inspect
                elif net_name == "medtech_hospitalA-net":
                    result.stdout = hospital_inspect
                else:
                    result.stdout = "[]"
            else:
                result.stdout = ""
            return result

        mock_subprocess.side_effect = subprocess_side_effect

        runner = CliRunner()
        result = runner.invoke(main, ["status", "--topology"])
        assert result.exit_code == 0, result.output
        # Should contain network names
        assert "medtech_hospitalA_or1-net" in result.output
        assert "medtech_hospitalA-net" in result.output
        # Should contain container names
        assert "hospitalA-or1-gateway" in result.output
        assert "hospitalA-clinical-service-host-or1" in result.output
        assert "hospitalA-gui" in result.output
        # Should contain IPs
        assert "172.18.0.2" in result.output

    @patch("medtech.cli._main.subprocess.run")
    def test_topology_no_networks(self, mock_subprocess) -> None:
        """--topology with no networks prints a message."""
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="")
        runner = CliRunner()
        result = runner.invoke(main, ["status", "--topology"])
        assert result.exit_code == 0
        assert "No medtech networks found" in result.output


class TestTopologyMultiHospital:
    """Verify multi-hospital topology groups by hospital name."""

    @patch("medtech.cli._main.subprocess.run")
    def test_groups_by_hospital(self, mock_subprocess) -> None:
        """Multi-hospital topology groups containers by hospital name."""
        network_names = (
            "medtech_hospital-a_or1-net\n"
            "medtech_hospital-b_or1-net\n"
            "medtech_wan-net\n"
        )

        a_inspect = _make_network_inspect(
            "medtech_hospital-a_or1-net",
            "10.10.1.0/24",
            {"c1": _container_entry("hospital-a-clinical-or1", "10.10.1.2")},
        )
        b_inspect = _make_network_inspect(
            "medtech_hospital-b_or1-net",
            "10.20.1.0/24",
            {"c2": _container_entry("hospital-b-clinical-or1", "10.20.1.2")},
        )
        wan_inspect = _make_network_inspect(
            "medtech_wan-net",
            "172.30.0.0/24",
            {
                "c3": _container_entry("hospital-a-nat", "172.30.0.2"),
                "c4": _container_entry("hospital-b-nat", "172.30.0.3"),
            },
        )

        def subprocess_side_effect(args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            if "network" in args and "ls" in args:
                result.stdout = network_names
            elif "network" in args and "inspect" in args:
                net_name = args[-1]
                data = {
                    "medtech_hospital-a_or1-net": a_inspect,
                    "medtech_hospital-b_or1-net": b_inspect,
                    "medtech_wan-net": wan_inspect,
                }.get(net_name, "[]")
                result.stdout = data
            else:
                result.stdout = ""
            return result

        mock_subprocess.side_effect = subprocess_side_effect

        runner = CliRunner()
        result = runner.invoke(main, ["status", "--topology"])
        assert result.exit_code == 0, result.output
        # Hospital names should appear as group headers
        assert "hospital-a" in result.output
        assert "hospital-b" in result.output
        # WAN should show NAT routers from both hospitals
        assert "wan-net" in result.output
        assert "hospital-a-nat" in result.output
        assert "hospital-b-nat" in result.output


class TestDockgraphLabel:
    """Verify DockGraph container has medtech.dynamic=true label."""

    @patch("medtech.cli._or._next_controller_port", return_value=8091)
    @patch("medtech.cli._or._next_twin_port", return_value=8081)
    @patch("medtech.cli._or._running_networks", return_value=[])
    @patch("medtech.cli._or._detect_hospitals")
    @patch("medtech.cli._or._ensure_network")
    @patch("medtech.cli._hospital._running_networks", return_value=[])
    @patch("medtech.cli._hospital.run_cmd")
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    @patch("medtech.cli._main.run_cmd")
    @patch("medtech.cli._main.subprocess.run")
    def test_dockgraph_has_dynamic_label(
        self,
        mock_subprocess_run,
        mock_main_run_cmd,
        mock_env,
        mock_vols,
        mock_or_run,
        mock_h_run,
        mock_nets,
        mock_ensure_net,
        mock_hosp,
        mock_or_nets,
        mock_port,
        mock_ctrl_port,
    ) -> None:
        """medtech launch --dockgraph starts DockGraph with dynamic label."""
        mock_hosp.return_value = [
            {
                "name": "hospitalA",
                "net": "medtech_hospitalA-net",
            }
        ]

        runner = CliRunner()
        result = runner.invoke(main, ["launch", "--dockgraph"])
        assert result.exit_code == 0, result.output

        # Find the DockGraph docker run call
        dockgraph_calls = [
            c
            for c in mock_main_run_cmd.call_args_list
            if len(c[0]) > 0 and "dockgraph" in str(c[0][0])
        ]
        assert len(dockgraph_calls) >= 1
        args = dockgraph_calls[0][0][0]
        assert "medtech.dynamic=true" in str(args)

    @patch("medtech.cli._main.run_cmd")
    @patch("medtech.cli._main.subprocess.run")
    def test_status_dockgraph_starts_sidecar(
        self,
        mock_subprocess_run,
        mock_main_run_cmd,
    ) -> None:
        """medtech status --dockgraph starts DockGraph independently."""
        runner = CliRunner()
        result = runner.invoke(main, ["status", "--dockgraph"])
        assert result.exit_code == 0, result.output

        # Verify docker rm -f was called for cleanup
        rm_calls = [c for c in mock_subprocess_run.call_args_list if "rm" in str(c)]
        assert len(rm_calls) >= 1

        # Verify docker run was called with dockgraph image
        dockgraph_calls = [
            c
            for c in mock_main_run_cmd.call_args_list
            if len(c[0]) > 0 and "dockgraph" in str(c[0][0])
        ]
        assert len(dockgraph_calls) >= 1


class TestDockgraphInThirdParty:
    """Verify DockGraph is documented in THIRD_PARTY_NOTICES.md."""

    def test_dockgraph_in_notices(self) -> None:
        """DockGraph appears in THIRD_PARTY_NOTICES.md."""
        import os

        notices_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "THIRD_PARTY_NOTICES.md"
        )
        with open(notices_path) as f:
            content = f.read()
        assert "dockgraph/dockgraph" in content
        assert "BSL-1.1" in content


class TestTopologyHelp:
    """Verify --topology appears in status help."""

    def test_topology_in_help(self) -> None:
        """medtech status --help mentions --topology."""
        runner = CliRunner()
        result = runner.invoke(main, ["status", "--help"])
        assert result.exit_code == 0
        assert "--topology" in result.output
