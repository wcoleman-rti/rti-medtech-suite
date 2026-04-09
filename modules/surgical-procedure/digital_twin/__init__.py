"""Digital twin display sub-package for the surgical procedure module.

Public API:
    DigitalTwinBackend — NiceGUI GuiBackend subclass powering the 3D
                         digital twin web page.
"""

from .nicegui_digital_twin import DigitalTwinBackend

__all__ = ["DigitalTwinBackend"]
