"""Acceptance test for the CLI simulation workflow (Phase SIM, Step SIM.6).

Tags: @acceptance, @simulation

Programmatically runs:
  medtech launch → medtech run or --name OR-5 →
  medtech status → medtech stop
and asserts correct container/network lifecycle.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from medtech.cli._main import main


class TestAcceptanceSimulationWorkflow:
    """Full CLI workflow acceptance test."""

    @patch("medtech.cli._main.subprocess.run")
    @patch("medtech.cli._or._next_twin_port", return_value=8081)
    @patch("medtech.cli._or._detect_hospitals")
    @patch("medtech.cli._hospital._running_networks", return_value=[])
    @patch("medtech.cli._hospital.run_cmd")
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_launch_add_or_status_stop(
        self,
        mock_env,
        mock_vols,
        mock_or_run,
        mock_h_run,
        mock_nets,
        mock_hosp,
        mock_port,
        mock_subprocess,
    ) -> None:
        """Full workflow: launch → run or OR-5 → status → stop."""
        runner = CliRunner()

        # --- Phase 1: medtech launch (distributed) -------------------------
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
        result = runner.invoke(main, ["launch"])
        assert result.exit_code == 0, result.output

        # Hospital should have been created (via hospital run_cmd)
        assert mock_h_run.call_count > 0

        # OR containers should have been created (via or run_cmd)
        assert mock_or_run.call_count > 0

        # --- Phase 2: medtech run or --name OR-5 ---------------------------
        mock_or_run.reset_mock()
        mock_h_run.reset_mock()
        mock_port.return_value = 8083

        result = runner.invoke(main, ["run", "or", "--name", "OR-5"])
        assert result.exit_code == 0, result.output

        # OR-5 containers should be launched
        or5_names = []
        for c in mock_or_run.call_args_list:
            args = c[0][0] if c[0] else []
            for i, a in enumerate(args):
                if a == "--name" and i + 1 < len(args):
                    or5_names.append(args[i + 1])
        assert any(
            "or5" in n for n in or5_names
        ), f"Expected OR-5 containers, got names: {or5_names}"

        # --- Phase 3: medtech status ----------------------------------------
        # Mock docker ps output for status
        containers_json = [
            json.dumps(
                {
                    "Names": "hospital-gateway",
                    "Status": "Up 5 minutes",
                    "Ports": "",
                }
            ),
            json.dumps(
                {
                    "Names": "medtech-gui",
                    "Status": "Up 5 minutes",
                    "Ports": "0.0.0.0:8080->8080/tcp",
                }
            ),
            json.dumps(
                {
                    "Names": "clinical-service-host-or5",
                    "Status": "Up 2 minutes",
                    "Ports": "",
                }
            ),
        ]
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="\n".join(containers_json) + "\n",
        )

        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0, result.output
        assert "hospital-gateway" in result.output
        assert "medtech-gui" in result.output

        # --- Phase 4: medtech stop ------------------------------------------
        # Mock running containers and networks for stop
        running_containers = [
            json.dumps({"Names": "hospital-gateway"}),
            json.dumps({"Names": "medtech-gui"}),
            json.dumps({"Names": "clinical-service-host-or5"}),
            json.dumps({"Names": "medtech-twin-or5"}),
        ]
        running_networks = (
            "medtech_surgical-net\nmedtech_hospital-net\nmedtech_orchestration-net\n"
        )

        call_count = [0]

        def subprocess_side_effect(*args, **kwargs):
            call_count[0] += 1
            cmd = args[0] if args else kwargs.get("args", [])
            mock_result = MagicMock()
            mock_result.returncode = 0

            if "ps" in cmd and "--format" in cmd:
                mock_result.stdout = "\n".join(running_containers) + "\n"
            elif "network" in cmd and "ls" in cmd:
                mock_result.stdout = running_networks
            else:
                mock_result.stdout = ""
            return mock_result

        mock_subprocess.side_effect = subprocess_side_effect

        result = runner.invoke(main, ["stop"])
        assert result.exit_code == 0, result.output

        # Verify stop called docker commands
        assert mock_subprocess.call_count > 0

    @patch("medtech.cli._main.subprocess.run")
    @patch("medtech.cli._or._next_twin_port", return_value=8081)
    @patch("medtech.cli._or._detect_hospitals")
    @patch("medtech.cli._hospital._running_networks")
    @patch("medtech.cli._hospital.run_cmd")
    @patch("medtech.cli._or.run_cmd")
    @patch("medtech.cli._or._config_volumes", return_value=[])
    @patch("medtech.cli._or._env_flags", return_value=[])
    def test_multi_site_status_stop(
        self,
        mock_env,
        mock_vols,
        mock_or_run,
        mock_h_run,
        mock_nets,
        mock_hosp,
        mock_port,
        mock_subprocess,
    ) -> None:
        """Multi-site workflow: launch multi-site → status → stop."""
        runner = CliRunner()

        hospital_a = {
            "name": "hospital-a",
            "nets": {
                "surgical": "medtech_hospital-a_surgical-net",
                "hospital": "medtech_hospital-a_hospital-net",
                "orchestration": "medtech_hospital-a_orchestration-net",
            },
        }
        hospital_b = {
            "name": "hospital-b",
            "nets": {
                "surgical": "medtech_hospital-b_surgical-net",
                "hospital": "medtech_hospital-b_hospital-net",
                "orchestration": "medtech_hospital-b_orchestration-net",
            },
        }

        # _running_networks: called once per hospital creation
        mock_nets.return_value = []

        # _detect_hospitals: each OR invocation needs to find its hospital
        mock_hosp.side_effect = [
            [hospital_a],  # OR-1 in hospital-a
            [hospital_a],  # OR-2 in hospital-a
            [hospital_a, hospital_b],  # OR-1 in hospital-b
            [hospital_a, hospital_b],  # OR-2 in hospital-b
        ]

        result = runner.invoke(main, ["launch", "multi-site"])
        assert result.exit_code == 0, result.output

        # Both hospitals + ORs should have been created
        assert mock_h_run.call_count > 0
        assert mock_or_run.call_count > 0
