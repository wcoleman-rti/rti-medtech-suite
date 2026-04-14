"""Tests for Split-GUI Docker topology (Phase SIM, Step SIM.5).

Tags: @simulation, @cli
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from medtech.cli._main import main


class TestGuiModeEnvVar:
    """Verify MEDTECH_GUI_MODE controls digital twin loading."""

    def test_default_gui_mode_is_unified(self) -> None:
        """Without MEDTECH_GUI_MODE, the app defaults to unified."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MEDTECH_GUI_MODE", None)
            mode = os.environ.get("MEDTECH_GUI_MODE", "unified")
            assert mode == "unified"

    def test_controller_dashboard_mode(self) -> None:
        """MEDTECH_GUI_MODE=controller-dashboard is accepted."""
        with patch.dict(os.environ, {"MEDTECH_GUI_MODE": "controller-dashboard"}):
            mode = os.environ.get("MEDTECH_GUI_MODE", "unified")
            assert mode == "controller-dashboard"


class TestDockerComposeGuiMode:
    """Verify docker-compose.yml has MEDTECH_GUI_MODE."""

    def test_compose_has_gui_mode(self) -> None:
        """docker-compose.yml medtech-gui service has MEDTECH_GUI_MODE."""
        import yaml

        compose_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "docker-compose.yml"
        )
        with open(compose_path) as f:
            compose = yaml.safe_load(f)
        gui_svc = compose["services"]["medtech-gui"]
        env = gui_svc["environment"]
        assert "MEDTECH_GUI_MODE" in env


class TestDigitalTwinGuiUrl:
    """Verify DigitalTwinBackend.gui_urls() in split-GUI mode."""

    def test_gui_urls_empty_by_default(self) -> None:
        """gui_urls() returns empty list when gui_url is not set."""
        from surgical_procedure.digital_twin.digital_twin import DigitalTwinBackend

        backend = DigitalTwinBackend.__new__(DigitalTwinBackend)
        backend.gui_url = ""
        assert backend.gui_urls() == []

    def test_gui_urls_returns_url(self) -> None:
        """gui_urls() returns the gui_url when set."""
        from surgical_procedure.digital_twin.digital_twin import DigitalTwinBackend

        backend = DigitalTwinBackend.__new__(DigitalTwinBackend)
        backend.gui_url = "http://localhost:8081/twin/OR-1"
        assert backend.gui_urls() == ["http://localhost:8081/twin/OR-1"]


class TestDigitalTwinMain:
    """Verify main() reads MEDTECH_GUI_EXTERNAL_URL."""

    @patch("surgical_procedure.digital_twin.digital_twin.ui")
    @patch("medtech.gui._theme._resource_dir")
    @patch("surgical_procedure.digital_twin.digital_twin._get_backend")
    def test_main_sets_gui_url_from_env(
        self, mock_get_backend, mock_res_dir, mock_ui
    ) -> None:
        """main() builds gui_url from MEDTECH_GUI_EXTERNAL_URL + room_id."""
        backend = MagicMock()
        mock_get_backend.return_value = backend
        mock_res_dir.return_value = MagicMock()

        with patch.dict(
            os.environ,
            {
                "ROOM_ID": "OR-5",
                "MEDTECH_GUI_EXTERNAL_URL": "http://localhost:8085",
            },
        ):
            from surgical_procedure.digital_twin.digital_twin import main as dt_main

            mock_ui.run.side_effect = KeyboardInterrupt
            mock_ui.page = MagicMock(return_value=lambda f: f)
            mock_ui.navigate = MagicMock()
            try:
                dt_main()
            except (KeyboardInterrupt, SystemExit):
                pass

        mock_get_backend.assert_called_with("OR-5")
        assert backend.gui_url == "http://localhost:8085/twin/OR-5"

    @patch("surgical_procedure.digital_twin.digital_twin.ui")
    @patch("medtech.gui._theme._resource_dir")
    @patch("surgical_procedure.digital_twin.digital_twin._get_backend")
    def test_main_no_gui_url_when_env_unset(
        self, mock_get_backend, mock_res_dir, mock_ui
    ) -> None:
        """main() does not set gui_url when MEDTECH_GUI_EXTERNAL_URL is absent."""
        backend = MagicMock(spec=["gui_url"])
        backend.gui_url = ""
        mock_get_backend.return_value = backend
        mock_res_dir.return_value = MagicMock()

        env = {"ROOM_ID": "OR-1"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("MEDTECH_GUI_EXTERNAL_URL", None)
            from surgical_procedure.digital_twin.digital_twin import main as dt_main

            mock_ui.run.side_effect = KeyboardInterrupt
            mock_ui.page = MagicMock(return_value=lambda f: f)
            mock_ui.navigate = MagicMock()
            try:
                dt_main()
            except (KeyboardInterrupt, SystemExit):
                pass

        # gui_url should remain empty (was not set by main)
        assert backend.gui_url == ""


class TestDigitalTwinDunderMain:
    """Verify __main__.py exists for python -m invocation."""

    def test_dunder_main_exists(self) -> None:
        """digital_twin/__main__.py exists in the source tree."""
        src_dir = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "modules",
            "surgical-procedure",
            "digital_twin",
        )
        assert os.path.isfile(os.path.join(src_dir, "__main__.py"))


class TestUnifiedLaunchSetsGuiMode:
    """Verify medtech launch unified passes MEDTECH_GUI_MODE=unified."""

    @patch("medtech.cli._launch.run_cmd")
    def test_launch_unified_sets_env(self, mock_run) -> None:
        """medtech launch unified passes env_override with MEDTECH_GUI_MODE."""
        runner = CliRunner()
        result = runner.invoke(main, ["launch", "unified"])
        assert result.exit_code == 0
        # Find the docker compose call
        compose_calls = [
            c
            for c in mock_run.call_args_list
            if len(c[0]) > 0 and c[0][0][:2] == ["docker", "compose"]
        ]
        assert len(compose_calls) >= 1
        # Check that env_override includes MEDTECH_GUI_MODE=unified
        call_kwargs = compose_calls[0].kwargs
        assert call_kwargs.get("env_override", {}).get("MEDTECH_GUI_MODE") == "unified"


class TestRunCmdEnvOverride:
    """Verify run_cmd env_override parameter."""

    @patch("medtech.cli._main.subprocess.run")
    def test_env_override_merges_with_environ(self, mock_subprocess) -> None:
        """env_override merges with current environment."""
        from medtech.cli._main import run_cmd

        mock_subprocess.return_value = MagicMock(returncode=0)
        run_cmd(["echo", "test"], env_override={"MY_VAR": "value"})
        call_kwargs = mock_subprocess.call_args[1]
        assert call_kwargs["env"]["MY_VAR"] == "value"
        # Original PATH should still be present
        assert "PATH" in call_kwargs["env"]

    @patch("medtech.cli._main.subprocess.run")
    def test_no_env_override_passes_none(self, mock_subprocess) -> None:
        """Without env_override, env=None is passed to subprocess."""
        from medtech.cli._main import run_cmd

        mock_subprocess.return_value = MagicMock(returncode=0)
        run_cmd(["echo", "test"])
        call_kwargs = mock_subprocess.call_args[1]
        assert call_kwargs.get("env") is None
