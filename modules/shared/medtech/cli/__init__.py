"""medtech CLI — build/launch/scale orchestrator for the medtech suite."""

import medtech.cli._hospital  # noqa: F401  -- registers ``run hospital``

# Register sub-command groups and commands (side-effect imports)
import medtech.cli._run  # noqa: F401  -- registers ``run`` group
from medtech.cli._main import main

__all__ = ["main"]
