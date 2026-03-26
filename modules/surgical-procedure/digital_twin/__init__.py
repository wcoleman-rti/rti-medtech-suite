"""Digital twin display sub-package for the surgical procedure module.

Public API:
    DigitalTwinDisplay — PySide6 main window subscribing to Procedure
                         domain (control tag) and rendering a 2D robot
                         visualization.
    RobotWidget        — QWidget rendering the robot arm, interlock
                         overlays, and mode labels.
"""

from ._robot_widget import RobotWidget
from .digital_twin_display import DigitalTwinDisplay

__all__ = ["DigitalTwinDisplay", "RobotWidget"]
