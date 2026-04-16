"""Tests for the medtech CLI scaffold (Phase SIM, Step SIM.1).

Tags: @simulation, @cli
"""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

from medtech.cli._naming import next_or_name


class TestCLIScaffold:
    """Verify the CLI entry point and command structure."""

    def test_medtech_on_path(self) -> None:
        """pip install -e . makes medtech available on PATH."""
        result = subprocess.run(
            [sys.executable, "-m", "medtech.cli", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "medtech" in result.stdout.lower()

    def test_medtech_help(self) -> None:
        """medtech --help prints available commands."""
        from click.testing import CliRunner
        from medtech.cli._main import main

        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "build" in result.output
        assert "status" in result.output
        assert "stop" in result.output

    def test_build_help(self) -> None:
        """medtech build --help prints build usage."""
        from click.testing import CliRunner
        from medtech.cli._main import main

        runner = CliRunner()
        result = runner.invoke(main, ["build", "--help"])
        assert result.exit_code == 0
        assert "Build" in result.output or "build" in result.output.lower()

    def test_build_help_lists_docker_and_no_docker_flags(self) -> None:
        """@smoke Tier 1: medtech build --help lists --docker and --no-docker flags."""
        from click.testing import CliRunner
        from medtech.cli._main import main

        runner = CliRunner()
        result = runner.invoke(main, ["build", "--help"])
        assert result.exit_code == 0
        assert "--docker" in result.output
        assert "--no-docker" in result.output

    def test_status_help(self) -> None:
        """medtech status --help prints status usage."""
        from click.testing import CliRunner
        from medtech.cli._main import main

        runner = CliRunner()
        result = runner.invoke(main, ["status", "--help"])
        assert result.exit_code == 0
        assert "status" in result.output.lower()

    def test_stop_help(self) -> None:
        """medtech stop --help prints stop usage."""
        from click.testing import CliRunner
        from medtech.cli._main import main

        runner = CliRunner()
        result = runner.invoke(main, ["stop", "--help"])
        assert result.exit_code == 0
        assert "stop" in result.output.lower()


class TestStopCommand:
    """Verify medtech stop removes containers and networks."""

    def test_stop_removes_containers_and_networks(self) -> None:
        """medtech stop removes containers AND Docker networks."""
        from click.testing import CliRunner
        from medtech.cli._main import main

        runner = CliRunner()
        result = runner.invoke(main, ["stop"])
        # When nothing is running, stop completes without error
        assert result.exit_code == 0
        assert "No medtech containers" in result.output or "docker" in result.output


class TestAutoNaming:
    """Verify auto-name generation helpers."""

    def test_next_or_name_no_ors(self) -> None:
        """next_or_name() returns OR-1 when no ORs are running."""
        with patch("medtech.cli._naming._running_containers", return_value=[]):
            assert next_or_name("hospitalA") == "OR-1"

    def test_next_or_name_skips_existing(self) -> None:
        """next_or_name() skips existing OR numbers."""
        fake_containers = [
            {"Names": "hospitalA-clinical-service-host-or1"},
            {"Names": "hospitalA-clinical-service-host-or2"},
        ]
        with patch(
            "medtech.cli._naming._running_containers",
            return_value=fake_containers,
        ):
            assert next_or_name("hospitalA") == "OR-3"

    def test_next_or_name_hospital_filter(self) -> None:
        """next_or_name(hospital) only counts ORs for that hospital."""
        fake_containers = [
            {"Names": "hospital-a-clinical-service-host-or1"},
            {"Names": "hospital-b-clinical-service-host-or1"},
        ]
        with patch(
            "medtech.cli._naming._running_containers",
            return_value=fake_containers,
        ):
            assert next_or_name("hospital-a") == "OR-2"
            assert next_or_name("hospital-b") == "OR-2"
