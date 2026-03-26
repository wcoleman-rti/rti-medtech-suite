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
        proc = subprocess.Popen(
            [
                "docker",
                "run",
                "--rm",
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
