"""Entry point for the Procedure Controller GUI.

Usage::

    ROOM_ID=OR-1 python -m surgical_procedure.procedure_controller
"""

from __future__ import annotations

from .controller import main

if __name__ == "__main__":
    main()
