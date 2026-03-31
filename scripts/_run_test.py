#!/usr/bin/env python3
"""Quick runner to execute pytest and capture output."""
import os
import subprocess
import sys

os.chdir("/mnt/c/Users/wcoleman/Documents/repos/medtech-suite")
result = subprocess.run(
    [
        sys.executable,
        "-m",
        "pytest",
        "tests/integration/test_operational_service_host.py",
        "-x",
        "-v",
        "--tb=short",
    ],
    capture_output=True,
    text=True,
    timeout=180,
)
print(result.stdout)
if result.stderr:
    print(result.stderr[-2000:])
print(f"EXIT={result.returncode}")
