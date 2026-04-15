"""Scenario definitions for ``medtech launch``."""

from __future__ import annotations

SCENARIOS: dict[str, dict] = {
    "distributed": {
        "description": "Split GUI, 2 ORs, full stack",
        "hospital_args": [],
        "rooms": ["OR-1", "OR-3"],
    },
    "multi-site": {
        "description": "Two named hospitals with NAT isolation, 2 ORs each",
        "hospitals": [
            {"name": "hospital-a", "rooms": ["OR-1", "OR-2"]},
            {"name": "hospital-b", "rooms": ["OR-1", "OR-2"]},
        ],
    },
    "minimal": {
        "description": "Single OR, split GUI, no observability",
        "hospital_args": [],
        "rooms": ["OR-1"],
    },
}
