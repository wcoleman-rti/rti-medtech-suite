"""vitals_sim — Patient vitals simulation model and bedside monitor."""

from ._alarm import AlarmEvaluator
from ._profiles import PROFILES, ScenarioProfile
from ._signal import SignalModel
from .bedside_monitor import BedsideMonitor

__all__ = [
    "AlarmEvaluator",
    "BedsideMonitor",
    "PROFILES",
    "ScenarioProfile",
    "SignalModel",
]
