"""Tests for ``medtech run or`` (Phase SIM, Step SIM.3).

Tags: @simulation, @cli
"""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner
from medtech.cli._main import main


def _mock_hospitals_one_unnamed():
    """Return mock for one unnamed hospital."""
    return [
        {
            "name": None,
            "nets": {
                "surgical": "medtech_surgical-net",
                "hospital": "medtech_hospital-net",
                "orchestration": "medtech_orchestration-net",
            },
        }
    ]


def _mock_hospitals_two_named():
    """Return mock for two named hospitals."""
    return [
        {
            "name": "hospital-a",
            "nets": {
                "surgical": "medtech_hospital-a_surgical-net",
                "hospital": "medtech_hospital-a_hospital-net",
                "orchestration": "medtech_hospital-a_orchestration-net",
            },
        },
        {
            "name": "hospital-b",
            "nets": {
                "surgical": "medtech_hospital-b_surgical-net",
                "hospital": "medtech_hospital-b_hospital-net",
                "orchestration": "medtech_hospital-b_orchestration-net",
            },
        },
    ]


class TestRunOR:
    """Verify ``medtech run or``."""

    @patch("medtech.cli._or._next_twin_port", return_value=8081)
    @patch(
        "medtech.cli._or._detect_hospitals", return_value=_mock_hospitals_one_unnamed()
    )
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_starts_gateway_and_5_containers(
        self, mock_env, mock_vols, mock_run, mock_hosp, mock_port
    ) -> None:
        """medtech run or --name OR-5 starts room-gateway + 5 app containers."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "or", "--name", "OR-5"])
        assert result.exit_code == 0
        docker_runs = [
            c.args[0]
            for c in mock_run.call_args_list
            if isinstance(c.args[0], list)
            and len(c.args[0]) > 2
            and c.args[0][:3] == ["docker", "run", "--rm"]
        ]
        names = []
        for cmd in docker_runs:
            if "--name" in cmd:
                idx = cmd.index("--name")
                names.append(cmd[idx + 1])
        # Gateway (CDS) + RS + Collector + 4 service hosts + 1 twin = 8
        assert len(docker_runs) == 8
        assert any("gateway" in n for n in names)
        assert any("clinical" in n for n in names)
        assert any("operational" in n for n in names)
        assert any("operator" in n for n in names)
        assert any("robot" in n for n in names)
        assert any("twin" in n for n in names)

    @patch("medtech.cli._or._next_twin_port", return_value=8081)
    @patch(
        "medtech.cli._or._detect_hospitals", return_value=_mock_hospitals_one_unnamed()
    )
    @patch("medtech.cli._or.next_or_name", return_value="OR-1")
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_auto_generates_name(
        self, mock_env, mock_vols, mock_run, mock_next_or, mock_hosp, mock_port
    ) -> None:
        """medtech run or (no --name) auto-generates OR-1."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "or"])
        assert result.exit_code == 0
        assert "OR-1" in result.output
        mock_next_or.assert_called_once()

    @patch("medtech.cli._or._next_twin_port", return_value=8081)
    @patch(
        "medtech.cli._or._detect_hospitals", return_value=_mock_hospitals_two_named()
    )
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_targets_named_hospital(
        self, mock_env, mock_vols, mock_run, mock_hosp, mock_port
    ) -> None:
        """medtech run or --hospital hospital-a targets named hospital networks."""
        runner = CliRunner()
        result = runner.invoke(
            main, ["run", "or", "--name", "OR-1", "--hospital", "hospital-a"]
        )
        assert result.exit_code == 0
        # Verify containers reference hospital-a networks
        network_connects = [
            c.args[0]
            for c in mock_run.call_args_list
            if isinstance(c.args[0], list) and "network" in c.args[0]
        ]
        network_names = []
        for cmd in network_connects:
            for arg in cmd:
                if "hospital-a" in arg:
                    network_names.append(arg)
        assert len(network_names) > 0

    @patch(
        "medtech.cli._or._detect_hospitals", return_value=_mock_hospitals_two_named()
    )
    def test_errors_multiple_hospitals_no_flag(self, mock_hosp) -> None:
        """Errors when multiple hospitals running and --hospital omitted."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "or", "--name", "OR-1"])
        assert result.exit_code != 0

    @patch("medtech.cli._or._next_twin_port", return_value=8081)
    @patch(
        "medtech.cli._or._detect_hospitals", return_value=_mock_hospitals_one_unnamed()
    )
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_infers_single_hospital(
        self, mock_env, mock_vols, mock_run, mock_hosp, mock_port
    ) -> None:
        """Infers hospital when only one is running."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "or", "--name", "OR-1"])
        assert result.exit_code == 0

    @patch("medtech.cli._or._next_twin_port", return_value=8081)
    @patch(
        "medtech.cli._or._detect_hospitals", return_value=_mock_hospitals_one_unnamed()
    )
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_containers_have_dynamic_label(
        self, mock_env, mock_vols, mock_run, mock_hosp, mock_port
    ) -> None:
        """Containers have the medtech.dynamic=true label."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "or", "--name", "OR-1"])
        assert result.exit_code == 0
        docker_runs = [
            c.args[0]
            for c in mock_run.call_args_list
            if isinstance(c.args[0], list)
            and len(c.args[0]) > 2
            and c.args[0][:3] == ["docker", "run", "--rm"]
        ]
        for cmd in docker_runs:
            assert "medtech.dynamic=true" in cmd

    @patch("medtech.cli._or._next_twin_port", return_value=8081)
    @patch(
        "medtech.cli._or._detect_hospitals", return_value=_mock_hospitals_one_unnamed()
    )
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_prints_docker_commands(
        self, mock_env, mock_vols, mock_run, mock_hosp, mock_port
    ) -> None:
        """Each docker run command is printed to stdout (via run_cmd)."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "or", "--name", "OR-1"])
        assert result.exit_code == 0
        # run_cmd prints "  $ <cmd>" for each docker run
        assert mock_run.call_count >= 8  # gateway + rs + collector + 4 hosts + twin

    @patch("medtech.cli._or._detect_hospitals", return_value=[])
    def test_errors_no_hospital(self, mock_hosp) -> None:
        """Errors when no hospital is running."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "or", "--name", "OR-1"])
        assert result.exit_code != 0
