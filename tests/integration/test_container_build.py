"""E2E tests for Container Build Integrity scenarios from
spec/common-behaviors.md.

Verifies that C++ binaries and Python modules built inside Docker
multi-stage builds run without ABI/library errors.

Tags: @e2e

These tests require Docker and pre-built images (medtech/app-cpp,
medtech/app-python). They are skipped when Docker is not available.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

pytestmark = [pytest.mark.e2e]

docker_available = shutil.which("docker") is not None


@pytest.mark.skipif(not docker_available, reason="Docker not available")
class TestContainerBuildIntegrity:
    """Scenario: C++ binary built inside Docker runs without ABI errors."""

    def test_cpp_binary_no_unresolved_libs(self):
        """ldd on robot-controller inside cpp-runtime shows all libs resolved."""
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "medtech/app-cpp",
                "ldd",
                "/opt/medtech/bin/robot-controller",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"ldd failed: {result.stderr}"
        assert (
            "not found" not in result.stdout
        ), f"Unresolved libraries:\n{result.stdout}"

    def test_cpp_binary_no_glibcxx_errors(self):
        """robot-controller starts without GLIBCXX/GLIBC errors."""
        # robot-controller is a long-lived process; start it, let it
        # initialize briefly, then check output for ABI errors.
        # Use a named container so we can reliably stop + remove it.
        container_name = "medtech-test-glibcxx-check"
        # Remove any leftover container from a previous failed run.
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            timeout=10,
        )
        proc = subprocess.Popen(
            [
                "docker",
                "run",
                "--name",
                container_name,
                "-e",
                "MEDTECH_APP_NAME=test-robot",
                "medtech/app-cpp",
                "/opt/medtech/bin/robot-controller",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            # Stop the container (sends SIGTERM to PID 1 inside), then
            # remove it.  This prevents orphaned containers accumulating
            # after each test run.
            subprocess.run(
                ["docker", "stop", "-t", "3", container_name],
                capture_output=True,
                timeout=10,
            )
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                timeout=10,
            )
            proc.kill()
            stdout, stderr = proc.communicate()
        combined = stdout + stderr
        assert "GLIBCXX" not in combined, f"GLIBCXX error:\n{combined}"
        # Allow normal GLIBC references (e.g., ldd output); only flag
        # version-mismatch errors
        for line in combined.splitlines():
            assert not (
                "GLIBC" in line and "not found" in line
            ), f"GLIBC version error:\n{line}"


@pytest.mark.skipif(not docker_available, reason="Docker not available")
class TestPythonContainerImports:
    """Scenario: Python modules import successfully in Docker."""

    def test_python_type_imports(self):
        """surgery and monitoring modules import without errors."""
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "medtech/app-python",
                "python3",
                "-c",
                "import surgery; import monitoring; print('OK')",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Python import failed:\n{result.stderr}"
        assert "OK" in result.stdout
