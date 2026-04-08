"""Digital twin display sub-package for the surgical procedure module.

Public API:
    DigitalTwinBackend — NiceGUI GuiBackend subclass powering the 3D
                         digital twin web page.
    DigitalTwinDisplay — PySide6 main window (legacy; guarded by
                         PySide6 availability in test collection).
    RobotWidget        — QWidget rendering the robot arm, interlock
                         overlays, and mode labels (legacy PySide6).
"""

from .nicegui_digital_twin import DigitalTwinBackend

try:
    from ._robot_widget import RobotWidget
    from .digital_twin_display import DigitalTwinDisplay

    __all__ = ["DigitalTwinBackend", "DigitalTwinDisplay", "RobotWidget"]
except ImportError:
    __all__ = ["DigitalTwinBackend"]
