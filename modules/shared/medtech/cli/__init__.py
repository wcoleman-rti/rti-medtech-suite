"""medtech CLI — build/launch/scale orchestrator for the medtech suite."""

import medtech.cli._hospital  # noqa: F401  -- registers ``run hospital``
import medtech.cli._launch  # noqa: F401  -- registers ``launch``
import medtech.cli._or  # noqa: F401  -- registers ``run or``

# Register sub-command groups and commands (side-effect imports)
import medtech.cli._run  # noqa: F401  -- registers ``run`` group
from medtech.cli._main import main

__all__ = ["main"]
