"""Tests for ``medtech launch`` (Phase SIM, Step SIM.4).

Tags: @simulation, @cli
"""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner
from medtech.cli._main import main


class TestLaunchList:
    """Verify ``medtech launch --list``."""

    def test_lists_all_scenarios(self) -> None:
        """medtech launch --list prints all four scenarios."""
        runner = CliRunner()
        result = runner.invoke(main, ["launch", "--list"])
        assert result.exit_code == 0
        assert "distributed" in result.output
        assert "multi-site" in result.output
        assert "unified" in result.output
        assert "minimal" in result.output


class TestLaunchHelp:
    """Verify ``medtech launch --help``."""

    def test_help_documents_scenario(self) -> None:
        """medtech launch --help documents the scenario argument."""
        runner = CliRunner()
        result = runner.invoke(main, ["launch", "--help"])
        assert result.exit_code == 0
        assert "SCENARIO" in result.output or "scenario" in result.output.lower()


class TestLaunchDistributed:
    """Verify ``medtech launch`` (default distributed scenario)."""

    @patch("medtech.cli._or._next_twin_port", return_value=8081)
    @patch("medtech.cli._or._detect_hospitals")
    @patch("medtech.cli._hospital._running_networks", return_value=[])
    @patch("medtech.cli._hospital.run_cmd")
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_starts_distributed(
        self,
        mock_env,
        mock_vols,
        mock_or_run,
        mock_h_run,
        mock_nets,
        mock_hosp,
        mock_port,
    ) -> None:
        """medtech launch starts the distributed scenario."""
        # After hospital starts, detect_hospitals returns one hospital
        mock_hosp.return_value = [
            {
                "name": None,
                "nets": {
                    "surgical": "medtech_surgical-net",
                    "hospital": "medtech_hospital-net",
                    "orchestration": "medtech_orchestration-net",
                },
            }
        ]
        runner = CliRunner()
        result = runner.invoke(main, ["launch"])
        assert result.exit_code == 0
        assert "Simulation ready" in result.output


class TestLaunchMultiSite:
    """Verify ``medtech launch multi-site``."""

    @patch("medtech.cli._or._next_twin_port", return_value=8081)
    @patch("medtech.cli._or._detect_hospitals")
    @patch("medtech.cli._hospital._running_networks", return_value=[])
    @patch("medtech.cli._hospital.run_cmd")
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_starts_multi_site(
        self,
        mock_env,
        mock_vols,
        mock_or_run,
        mock_h_run,
        mock_nets,
        mock_hosp,
        mock_port,
    ) -> None:
        """medtech launch multi-site starts two hospitals with 4 ORs total."""

        def detect_side_effect():
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

        mock_hosp.side_effect = lambda: detect_side_effect()
        # Also need to handle _running_networks returning progressively more
        mock_nets.return_value = []
        runner = CliRunner()
        result = runner.invoke(main, ["launch", "multi-site"])
        assert result.exit_code == 0
        assert "Simulation ready" in result.output


class TestLaunchUnified:
    """Verify ``medtech launch unified``."""

    @patch("medtech.cli._launch.run_cmd")
    def test_starts_unified(self, mock_run) -> None:
        """medtech launch unified runs docker compose with unified-gui profile."""
        runner = CliRunner()
        result = runner.invoke(main, ["launch", "unified"])
        assert result.exit_code == 0
        # Should invoke docker compose with --profile unified-gui
        compose_calls = [
            c.args[0]
            for c in mock_run.call_args_list
            if isinstance(c.args[0], list) and "compose" in c.args[0]
        ]
        assert len(compose_calls) >= 1
        assert "unified-gui" in compose_calls[0]


class TestLaunchMinimal:
    """Verify ``medtech launch minimal``."""

    @patch("medtech.cli._or._next_twin_port", return_value=8081)
    @patch("medtech.cli._or._detect_hospitals")
    @patch("medtech.cli._hospital._running_networks", return_value=[])
    @patch("medtech.cli._hospital.run_cmd")
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_starts_minimal(
        self,
        mock_env,
        mock_vols,
        mock_or_run,
        mock_h_run,
        mock_nets,
        mock_hosp,
        mock_port,
    ) -> None:
        """medtech launch minimal starts a single-OR scenario."""
        mock_hosp.return_value = [
            {
                "name": None,
                "nets": {
                    "surgical": "medtech_surgical-net",
                    "hospital": "medtech_hospital-net",
                    "orchestration": "medtech_orchestration-net",
                },
            }
        ]
        runner = CliRunner()
        result = runner.invoke(main, ["launch", "minimal"])
        assert result.exit_code == 0
        assert "Simulation ready" in result.output
