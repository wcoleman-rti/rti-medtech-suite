"""Tests for ``medtech run or`` (Phase SIM, Step SIM.3).

Tags: @simulation, @cli
"""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner
from medtech.cli._main import main


def _mock_hospitals_one_default():
    """Return mock for one default hospital."""
    return [
        {
            "name": "hospitalA",
            "net": "medtech_hospitalA-net",
        }
    ]


def _mock_hospitals_two_named():
    """Return mock for two named hospitals."""
    return [
        {
            "name": "hospital-a",
            "net": "medtech_hospital-a-net",
        },
        {
            "name": "hospital-b",
            "net": "medtech_hospital-b-net",
        },
    ]


class TestRunOR:
    """Verify ``medtech run or``."""

    @patch("medtech.cli._or._next_controller_port", return_value=8091)
    @patch("medtech.cli._or._next_operator_gui_port", return_value=8081)
    @patch("medtech.cli._or._running_networks", return_value=[])
    @patch(
        "medtech.cli._or._detect_hospitals", return_value=_mock_hospitals_one_default()
    )
    @patch("medtech.cli._or._ensure_network")
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_starts_gateway_and_5_containers(
        self,
        mock_env,
        mock_vols,
        mock_run,
        mock_ensure_net,
        mock_hosp,
        mock_or_nets,
        mock_operator_gui_port,
        mock_ctrl_port,
    ) -> None:
        """medtech run or --name OR-5 starts room-gateway + 5 containers."""
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
        # Gateway (CDS) + RS + Collector + 4 service hosts
        # + 1 controller = 8
        assert len(docker_runs) == 8
        assert any("gateway" in n for n in names)
        assert any("clinical" in n for n in names)
        assert any("operational" in n for n in names)
        assert any("operator-service-host" in n for n in names)
        assert any("robot-service-host" in n for n in names)
        assert any("controller" in n and "robot" not in n for n in names)
        # Room network should be created
        mock_ensure_net.assert_called()

    @patch("medtech.cli._or._next_controller_port", return_value=8091)
    @patch("medtech.cli._or._next_operator_gui_port", return_value=8081)
    @patch("medtech.cli._or._running_networks", return_value=[])
    @patch(
        "medtech.cli._or._detect_hospitals", return_value=_mock_hospitals_one_default()
    )
    @patch("medtech.cli._or._ensure_network")
    @patch("medtech.cli._or.next_or_name", return_value="OR-1")
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_auto_generates_name(
        self,
        mock_env,
        mock_vols,
        mock_run,
        mock_next_or,
        mock_ensure_net,
        mock_hosp,
        mock_or_nets,
        mock_operator_gui_port,
        mock_ctrl_port,
    ) -> None:
        """medtech run or (no --name) auto-generates OR-1."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "or"])
        assert result.exit_code == 0
        assert "OR-1" in result.output
        mock_next_or.assert_called_once()

    @patch("medtech.cli._or._next_controller_port", return_value=8091)
    @patch("medtech.cli._or._next_operator_gui_port", return_value=8081)
    @patch("medtech.cli._or._running_networks", return_value=[])
    @patch(
        "medtech.cli._or._detect_hospitals", return_value=_mock_hospitals_two_named()
    )
    @patch("medtech.cli._or._ensure_network")
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_targets_named_hospital(
        self,
        mock_env,
        mock_vols,
        mock_run,
        mock_ensure_net,
        mock_hosp,
        mock_or_nets,
        mock_operator_gui_port,
        mock_ctrl_port,
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

    @patch("medtech.cli._or._next_controller_port", return_value=8091)
    @patch("medtech.cli._or._next_operator_gui_port", return_value=8081)
    @patch("medtech.cli._or._running_networks", return_value=[])
    @patch(
        "medtech.cli._or._detect_hospitals", return_value=_mock_hospitals_one_default()
    )
    @patch("medtech.cli._or._ensure_network")
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_infers_single_hospital(
        self,
        mock_env,
        mock_vols,
        mock_run,
        mock_ensure_net,
        mock_hosp,
        mock_or_nets,
        mock_operator_gui_port,
        mock_ctrl_port,
    ) -> None:
        """Infers hospital when only one is running."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "or", "--name", "OR-1"])
        assert result.exit_code == 0

    @patch("medtech.cli._or._next_controller_port", return_value=8091)
    @patch("medtech.cli._or._next_operator_gui_port", return_value=8081)
    @patch("medtech.cli._or._running_networks", return_value=[])
    @patch(
        "medtech.cli._or._detect_hospitals", return_value=_mock_hospitals_one_default()
    )
    @patch("medtech.cli._or._ensure_network")
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_containers_have_dynamic_label(
        self,
        mock_env,
        mock_vols,
        mock_run,
        mock_ensure_net,
        mock_hosp,
        mock_or_nets,
        mock_operator_gui_port,
        mock_ctrl_port,
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

    @patch("medtech.cli._or._next_controller_port", return_value=8091)
    @patch("medtech.cli._or._next_operator_gui_port", return_value=8081)
    @patch("medtech.cli._or._running_networks", return_value=[])
    @patch(
        "medtech.cli._or._detect_hospitals", return_value=_mock_hospitals_one_default()
    )
    @patch("medtech.cli._or._ensure_network")
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_prints_docker_commands(
        self,
        mock_env,
        mock_vols,
        mock_run,
        mock_ensure_net,
        mock_hosp,
        mock_or_nets,
        mock_operator_gui_port,
        mock_ctrl_port,
    ) -> None:
        """Each docker run command is printed to stdout (via run_cmd)."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "or", "--name", "OR-1"])
        assert result.exit_code == 0
        # run_cmd prints "  $ <cmd>" for each docker run
        # gateway CDS + network connect + RS + collector + 4 hosts
        # + controller
        assert mock_run.call_count >= 9

    @patch("medtech.cli._or._detect_hospitals", return_value=[])
    def test_errors_no_hospital(self, mock_hosp) -> None:
        """Errors when no hospital is running."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "or", "--name", "OR-1"])
        assert result.exit_code != 0

    @patch("medtech.cli._or._next_controller_port", return_value=8091)
    @patch("medtech.cli._or._next_operator_gui_port", return_value=8081)
    @patch("medtech.cli._or._running_networks", return_value=[])
    @patch(
        "medtech.cli._or._detect_hospitals", return_value=_mock_hospitals_one_default()
    )
    @patch("medtech.cli._or._ensure_network")
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch(
        "medtech.cli._or._env_flags",
        side_effect=lambda extra=None: [
            flag for k, v in (extra or {}).items() for flag in ("-e", f"{k}={v}")
        ],
    )
    def test_multi_arm_spawns_pairs(
        self,
        mock_env,
        mock_vols,
        mock_run,
        mock_ensure_net,
        mock_hosp,
        mock_or_nets,
        mock_operator_gui_port,
        mock_ctrl_port,
    ) -> None:
        """--arms 3 spawns three operator + robot pairs with unique ROBOT_IDs."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "or", "--name", "OR-1", "--arms", "3"])
        assert result.exit_code == 0

        docker_runs = [
            c.args[0]
            for c in mock_run.call_args_list
            if isinstance(c.args[0], list)
            and len(c.args[0]) > 2
            and c.args[0][:3] == ["docker", "run", "--rm"]
        ]
        # Gateway(CDS) + RS + Collector + 2 room hosts + 3*(operator+robot)
        # + controller = 3 + 2 + 6 + 1 = 12
        assert len(docker_runs) == 12

        # Collect ROBOT_ID values from -e flags
        robot_ids: list[str] = []
        for cmd in docker_runs:
            for i, arg in enumerate(cmd):
                if arg == "-e" and i + 1 < len(cmd):
                    val = cmd[i + 1]
                    if val.startswith("ROBOT_ID="):
                        robot_ids.append(val.split("=", 1)[1])
        # 3 arms × 2 containers each = 6 ROBOT_ID env vars
        assert len(robot_ids) == 6
        # Three unique IDs: arm-or1-a, arm-or1-b, arm-or1-c
        assert set(robot_ids) == {"arm-or1-a", "arm-or1-b", "arm-or1-c"}

    @patch("medtech.cli._or._next_controller_port", return_value=8091)
    @patch("medtech.cli._or._next_operator_gui_port", return_value=8081)
    @patch("medtech.cli._or._running_networks", return_value=[])
    @patch(
        "medtech.cli._or._detect_hospitals", return_value=_mock_hospitals_one_default()
    )
    @patch("medtech.cli._or._ensure_network")
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch(
        "medtech.cli._or._env_flags",
        side_effect=lambda extra=None: [
            flag for k, v in (extra or {}).items() for flag in ("-e", f"{k}={v}")
        ],
    )
    def test_operator_host_gets_robot_id(
        self,
        mock_env,
        mock_vols,
        mock_run,
        mock_ensure_net,
        mock_hosp,
        mock_or_nets,
        mock_operator_gui_port,
        mock_ctrl_port,
    ) -> None:
        """Operator-service-host receives the same ROBOT_ID as robot-service-host."""
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
        # Find containers with ROBOT_ID and collect (name, robot_id) pairs
        pairs: list[tuple[str, str]] = []
        for cmd in docker_runs:
            name = ""
            rid = ""
            for i, arg in enumerate(cmd):
                if arg == "--name" and i + 1 < len(cmd):
                    name = cmd[i + 1]
                if arg == "-e" and i + 1 < len(cmd):
                    val = cmd[i + 1]
                    if val.startswith("ROBOT_ID="):
                        rid = val.split("=", 1)[1]
            if rid:
                pairs.append((name, rid))

        # Both operator and robot hosts should have ROBOT_ID
        names = [n for n, _ in pairs]
        assert any("operator-service-host" in n for n in names)
        assert any("robot-service-host" in n for n in names)
        # They should share the same ROBOT_ID
        ids = {r for _, r in pairs}
        assert len(ids) == 1
        assert ids == {"arm-or1-a"}
