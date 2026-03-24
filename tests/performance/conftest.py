"""Pytest fixtures for performance benchmark tests."""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config, items):
    """Auto-mark tests in this directory with the 'benchmark' marker."""
    for item in items:
        if "performance" in str(item.fspath):
            item.add_marker(pytest.mark.benchmark)
