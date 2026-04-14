"""Tests for ``medtech run hospital`` (Phase SIM, Step SIM.2).

Tags: @simulation, @cli
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from medtech.cli._main import main


def _make_run_result(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> MagicMock:
    """Create a mock subprocess.run result."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


class TestRunHospitalUnnamed:
    """Verify ``medtech run hospital`` (unnamed, flat networks)."""

    @patch("medtech.cli._hospital._running_networks", return_value=[])
    @patch("medtech.cli._hospital.run_cmd")
    def test_creates_flat_networks(self, mock_run, mock_nets) -> None:
        """Flat Docker networks are created."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "hospital"])
        assert result.exit_code == 0
        # Should create 3 flat networks + gateway + RS + collector + GUI
        network_creates = [
            c
            for c in mock_run.call_args_list
            if len(c.args) > 0
            and isinstance(c.args[0], list)
            and "network" in c.args[0]
            and "create" in c.args[0]
        ]
        assert len(network_creates) == 3

    @patch("medtech.cli._hospital._running_networks", return_value=[])
    @patch("medtech.cli._hospital.run_cmd")
    def test_starts_gateway_rs_collector_gui(self, mock_run, mock_nets) -> None:
        """Hospital-gateway (CDS + RS + Collector) and GUI containers are launched."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "hospital"])
        assert result.exit_code == 0
        docker_runs = [
            c.args[0]
            for c in mock_run.call_args_list
            if isinstance(c.args[0], list)
            and c.args[0][:3] == ["docker", "run", "--rm"]
        ]
        names = []
        for cmd in docker_runs:
            if "--name" in cmd:
                idx = cmd.index("--name")
                names.append(cmd[idx + 1])
        assert "hospital-gateway" in names
        assert "hospital-gateway-rs" in names
        assert "hospital-gateway-collector" in names
        assert "medtech-gui" in names

    @patch("medtech.cli._hospital._running_networks", return_value=[])
    @patch("medtech.cli._hospital.run_cmd")
    def test_no_nat_router(self, mock_run, mock_nets) -> None:
        """No NAT router is created for unnamed hospital."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "hospital"])
        assert result.exit_code == 0
        all_names = []
        for c in mock_run.call_args_list:
            if isinstance(c.args[0], list) and "--name" in c.args[0]:
                idx = c.args[0].index("--name")
                all_names.append(c.args[0][idx + 1])
        assert not any("nat" in n for n in all_names)

    @patch("medtech.cli._hospital._running_networks", return_value=[])
    @patch("medtech.cli._hospital.run_cmd")
    def test_prints_dashboard_url(self, mock_run, mock_nets) -> None:
        """Output includes the dashboard URL."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "hospital"])
        assert result.exit_code == 0
        assert "http://localhost:8080" in result.output

    @patch(
        "medtech.cli._hospital._running_networks",
        return_value=[
            "medtech_surgical-net",
            "medtech_hospital-net",
            "medtech_orchestration-net",
        ],
    )
    def test_second_unnamed_errors(self, mock_nets) -> None:
        """Second unnamed hospital errors."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "hospital"])
        assert result.exit_code != 0
        assert (
            "already running" in result.output.lower()
            or "already running" in (result.output + str(result.exception)).lower()
        )


class TestRunHospitalNamed:
    """Verify ``medtech run hospital --name hospital-a``."""

    @patch("medtech.cli._hospital._running_networks", return_value=[])
    @patch("medtech.cli._hospital.run_cmd")
    def test_creates_per_hospital_networks(self, mock_run, mock_nets) -> None:
        """Per-hospital networks with explicit subnets are created."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "hospital", "--name", "hospital-a"])
        assert result.exit_code == 0
        network_creates = [
            c.args[0]
            for c in mock_run.call_args_list
            if isinstance(c.args[0], list)
            and "network" in c.args[0]
            and "create" in c.args[0]
        ]
        net_names = [cmd[-1] for cmd in network_creates]
        assert "medtech_hospital-a_surgical-net" in net_names
        assert "medtech_hospital-a_hospital-net" in net_names
        assert "medtech_hospital-a_orchestration-net" in net_names

    @patch("medtech.cli._hospital._running_networks", return_value=[])
    @patch("medtech.cli._hospital.run_cmd")
    def test_creates_wan_net(self, mock_run, mock_nets) -> None:
        """Shared wan-net is created."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "hospital", "--name", "hospital-a"])
        assert result.exit_code == 0
        network_creates = [
            c.args[0]
            for c in mock_run.call_args_list
            if isinstance(c.args[0], list)
            and "network" in c.args[0]
            and "create" in c.args[0]
        ]
        net_names = [cmd[-1] for cmd in network_creates]
        assert "medtech_wan-net" in net_names

    @patch("medtech.cli._hospital._running_networks", return_value=[])
    @patch("medtech.cli._hospital.run_cmd")
    def test_nat_router_created(self, mock_run, mock_nets) -> None:
        """NAT router with --privileged is created for named hospitals."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "hospital", "--name", "hospital-a"])
        assert result.exit_code == 0
        docker_runs = [
            c.args[0]
            for c in mock_run.call_args_list
            if isinstance(c.args[0], list)
            and c.args[0][:3] == ["docker", "run", "--rm"]
        ]
        nat_cmds = [cmd for cmd in docker_runs if "hospital-a-nat" in cmd]
        assert len(nat_cmds) == 1
        assert "--privileged" in nat_cmds[0]

    @patch("medtech.cli._hospital._running_networks", return_value=[])
    @patch("medtech.cli._hospital.run_cmd")
    def test_gui_port_allocation(self, mock_run, mock_nets) -> None:
        """GUI port follows ordinal scheme (1st=8080)."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "hospital", "--name", "hospital-a"])
        assert result.exit_code == 0
        assert "http://localhost:8080" in result.output

    @patch(
        "medtech.cli._hospital._running_networks",
        return_value=[
            "medtech_hospital-a_surgical-net",
            "medtech_hospital-a_hospital-net",
            "medtech_hospital-a_orchestration-net",
            "medtech_wan-net",
        ],
    )
    @patch("medtech.cli._hospital.run_cmd")
    def test_second_hospital_different_subnets(self, mock_run, mock_nets) -> None:
        """Second named hospital gets different subnet range."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "hospital", "--name", "hospital-b"])
        assert result.exit_code == 0
        network_creates = [
            c.args[0]
            for c in mock_run.call_args_list
            if isinstance(c.args[0], list)
            and "network" in c.args[0]
            and "create" in c.args[0]
        ]
        # hospital-b should get ordinal 2 → 10.20.x.0/24 subnets
        subnet_args = [
            cmd[cmd.index("--subnet") + 1]
            for cmd in network_creates
            if "--subnet" in cmd
        ]
        assert any("10.20." in s for s in subnet_args)
        # Should also get port 9080
        assert "http://localhost:9080" in result.output

    @patch(
        "medtech.cli._hospital._running_networks",
        return_value=[
            "medtech_hospital-a_surgical-net",
            "medtech_hospital-a_hospital-net",
            "medtech_hospital-a_orchestration-net",
            "medtech_wan-net",
        ],
    )
    @patch("medtech.cli._hospital.run_cmd")
    def test_wan_net_not_created_twice(self, mock_run, mock_nets) -> None:
        """wan-net is NOT re-created when it already exists."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "hospital", "--name", "hospital-b"])
        assert result.exit_code == 0
        network_creates = [
            c.args[0]
            for c in mock_run.call_args_list
            if isinstance(c.args[0], list)
            and "network" in c.args[0]
            and "create" in c.args[0]
        ]
        net_names = [cmd[-1] for cmd in network_creates]
        assert net_names.count("medtech_wan-net") == 0


class TestRunHospitalObservability:
    """Verify ``medtech run hospital --observability``."""

    @patch("medtech.cli._hospital._running_networks", return_value=[])
    @patch("medtech.cli._hospital.run_cmd")
    def test_observability_starts_prometheus_grafana(self, mock_run, mock_nets) -> None:
        """--observability includes Prometheus and Grafana."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "hospital", "--observability"])
        assert result.exit_code == 0
        all_names = []
        for c in mock_run.call_args_list:
            args = c.args[0] if c.args else []
            if isinstance(args, list) and "--name" in args:
                idx = args.index("--name")
                all_names.append(args[idx + 1])
        assert "prometheus" in all_names
        assert "grafana" in all_names
