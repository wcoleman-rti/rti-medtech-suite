"""Tests for the medtech CLI scaffold (Phase SIM, Step SIM.1).

Tags: @simulation, @cli
"""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

import click
from medtech.cli._main import _compact_summary, set_verbose
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
        # Compact mode shows checkmarks or "No medtech containers/networks"
        output = result.output.lower()
        assert (
            "no medtech containers" in output
            or "stopped" in output
            or "no medtech" in output
        )


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


class TestVerboseFlag:
    """Verify ``--verbose`` / ``-v`` flag and compact output."""

    def test_help_lists_verbose_flag(self) -> None:
        """medtech --help shows --verbose / -v."""
        from click.testing import CliRunner
        from medtech.cli._main import main

        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "--verbose" in result.output

    def test_verbose_flag_accepted(self) -> None:
        """medtech -v --help is accepted without error."""
        from click.testing import CliRunner
        from medtech.cli._main import main

        runner = CliRunner()
        result = runner.invoke(main, ["-v", "--help"])
        assert result.exit_code == 0


class TestCompactSummary:
    """Unit tests for ``_compact_summary``."""

    def test_docker_run_extracts_name(self) -> None:
        args = ["docker", "run", "--rm", "-d", "--name", "hospitalA-gateway", "img"]
        label, action = _compact_summary(args)
        assert label == "Container hospitalA-gateway"
        assert action == "Started"

    def test_docker_network_create(self) -> None:
        args = ["docker", "network", "create", "medtech_hospitalA-net"]
        label, action = _compact_summary(args)
        assert label == "Network medtech_hospitalA-net"
        assert action == "Created"

    def test_docker_network_connect_skipped(self) -> None:
        args = ["docker", "network", "connect", "net", "ctr"]
        assert _compact_summary(args) is None

    def test_docker_network_rm_plural(self) -> None:
        args = ["docker", "network", "rm", "net1", "net2", "net3"]
        label, action = _compact_summary(args)
        assert "3" in label
        assert action == "Removed"

    def test_docker_stop_singular(self) -> None:
        args = ["docker", "stop", "abc123"]
        label, action = _compact_summary(args)
        assert "1" in label
        assert action == "Stopped"

    def test_docker_compose(self) -> None:
        args = ["docker", "compose", "--profile", "build", "build"]
        label, action = _compact_summary(args)
        assert "Docker" in label
        assert action == "Built"

    def test_docker_rm_skipped(self) -> None:
        args = ["docker", "rm", "-f", "ctr"]
        assert _compact_summary(args) is None

    def test_non_docker_returns_none(self) -> None:
        args = ["cmake", "--build", "build"]
        assert _compact_summary(args) is None


class TestRunCmdCompact:
    """Verify ``run_cmd`` compact output (default mode)."""

    def setup_method(self) -> None:
        set_verbose(False)

    def teardown_method(self) -> None:
        set_verbose(False)

    @patch("medtech.cli._main.subprocess.run")
    def test_compact_docker_run_shows_checkmark(self, mock_sub) -> None:
        """Compact mode shows ✔ Container <name> Started for docker run."""
        from medtech.cli._main import run_cmd

        mock_sub.return_value.returncode = 0
        mock_sub.return_value.stdout = "abc123\n"
        mock_sub.return_value.stderr = ""

        from click.testing import CliRunner

        runner = CliRunner()
        with runner.isolated_filesystem():
            # run_cmd uses click.echo, so capture via CliRunner
            @click.command()
            def _cli() -> None:
                run_cmd(["docker", "run", "--rm", "-d", "--name", "test-ctr", "img"])

            result = runner.invoke(_cli)
            assert result.exit_code == 0
            assert "test-ctr" in result.output
            assert "Started" in result.output
            assert "$ docker" not in result.output

    @patch("medtech.cli._main.subprocess.run")
    def test_verbose_docker_run_shows_command(self, mock_sub) -> None:
        """Verbose mode shows the full $ docker run command."""
        from medtech.cli._main import run_cmd

        mock_sub.return_value.returncode = 0
        set_verbose(True)

        from click.testing import CliRunner

        @click.command()
        def _cli() -> None:
            run_cmd(["docker", "run", "--rm", "-d", "--name", "test-ctr", "img"])

        runner = CliRunner()
        result = runner.invoke(_cli)
        assert result.exit_code == 0
        assert "$ docker run" in result.output

    @patch("medtech.cli._main.subprocess.run")
    def test_compact_network_connect_silent(self, mock_sub) -> None:
        """Compact mode suppresses docker network connect output."""
        from medtech.cli._main import run_cmd

        mock_sub.return_value.returncode = 0
        mock_sub.return_value.stdout = ""
        mock_sub.return_value.stderr = ""

        from click.testing import CliRunner

        @click.command()
        def _cli() -> None:
            run_cmd(["docker", "network", "connect", "net", "ctr"], check=False)

        runner = CliRunner()
        result = runner.invoke(_cli)
        assert result.exit_code == 0
        assert result.output.strip() == ""

    @patch("medtech.cli._main.subprocess.run")
    def test_compact_failure_shows_error(self, mock_sub) -> None:
        """Compact mode shows ✗ and stderr on failure."""
        from medtech.cli._main import run_cmd

        mock_sub.return_value.returncode = 1
        mock_sub.return_value.stdout = ""
        mock_sub.return_value.stderr = "something went wrong"

        from click.testing import CliRunner

        @click.command()
        def _cli() -> None:
            run_cmd(
                ["docker", "run", "--rm", "-d", "--name", "fail-ctr", "img"],
                check=False,
            )

        runner = CliRunner()
        result = runner.invoke(_cli)
        assert result.exit_code == 0
        assert "fail-ctr" in result.output
        assert "Error" in result.output
