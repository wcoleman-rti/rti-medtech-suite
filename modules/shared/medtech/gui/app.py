"""Unified NiceGUI application entry point for medtech-suite.

Serves all GUI modules — Hospital Dashboard, Procedure Controller, and
Digital Twin — from a single process with a persistent SPA shell.

Routes:
    /                  Landing page (redirects to /dashboard)
    /dashboard         Hospital Dashboard  (dashboard.dashboard_page)
    /controller        Procedure Controller (controller.controller_page)
    /twin/{room_id}    Digital Twin 3D      (digital_twin.twin_page)

Health / Readiness probes:
    GET /health        Liveness probe — always 200 while process is running
    GET /ready         Readiness probe — 200 when all GuiBackend instances are
                       active, 503 otherwise

Architecture notes:
    GuiBackend subclasses are instantiated at module level in each page
    module.  Their __init__ calls app.on_startup/on_shutdown automatically,
    so this main entry point never manually calls start() or close().

    The SPA shell (header + left drawer) is rendered inside ``shell_page``.
    ``ui.sub_pages()`` swaps the content area without a full page reload so
    the WebSocket connection and all DDS backends remain live.
"""

from __future__ import annotations

import os

from fastapi.responses import JSONResponse

# Import page builder functions — module-level GuiBackend instantiation
# happens inside these modules, self-registering lifecycle hooks.
from hospital_dashboard.dashboard.dashboard import dashboard_content  # noqa: F401
from hospital_dashboard.procedure_controller.controller import (  # noqa: F401
    controller_content,
)
from medtech.gui._backend import GuiBackend
from medtech.gui._icons import ICONS
from medtech.gui._theme import (
    NICEGUI_STORAGE_SECRET_ENV,
    NICEGUI_THEME_MODE_KEY,
    _theme_mode_value,
    init_theme,
)
from nicegui import app, ui
from surgical_procedure.digital_twin.digital_twin import twin_content  # noqa: F401

# ---------------------------------------------------------------------------
# Health / Readiness probes (FastAPI routes)
# ---------------------------------------------------------------------------

_LIVENESS_RESPONSE = {"status": "ok"}
_READY_RESPONSE = {"status": "ready"}
_NOT_READY_RESPONSE = {"status": "not ready"}


def _backends_ready() -> bool:
    """Return True if every registered GuiBackend has completed start()."""
    # GuiBackend tracks readiness via the ``_ready`` flag set in start().
    for backend in GuiBackend.registry():
        if not backend.is_ready():
            return False
    return True


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness probe — always 200 while the process is running."""
    return JSONResponse(content=_LIVENESS_RESPONSE, status_code=200)


@app.get("/ready")
async def ready() -> JSONResponse:
    """Readiness probe — 200 when all GuiBackend instances are active."""
    if _backends_ready():
        return JSONResponse(content=_READY_RESPONSE, status_code=200)
    return JSONResponse(content=_NOT_READY_RESPONSE, status_code=503)


# ---------------------------------------------------------------------------
# SPA shell
# ---------------------------------------------------------------------------

_NAV_ITEMS = [
    ("/dashboard", ICONS["dashboard"], "Dashboard"),
    ("/controller", ICONS["service"], "Controller"),
    ("/twin/OR-1", ICONS["robot"], "Digital Twin"),
]


@ui.page("/")
def shell_page() -> None:
    """Root SPA shell: persistent header + left drawer + sub-pages content."""
    init_theme(title="Medtech Suite")

    stored_mode = app.storage.user.get(NICEGUI_THEME_MODE_KEY, "system")
    dark_mode = ui.dark_mode(_theme_mode_value(stored_mode))  # noqa: F841

    with ui.left_drawer(fixed=True).classes(
        "bg-primary text-white flex flex-col gap-2 pt-4"
    ):
        ui.label("Navigation").classes("px-4 font-bold text-sm uppercase text-white/60")
        for path, icon, label in _NAV_ITEMS:
            with ui.button(on_click=lambda p=path: ui.navigate.to(p)).props(
                "flat align=left"
            ).classes("w-full text-white justify-start px-4 gap-3"):
                ui.icon(icon).classes("text-xl")
                ui.label(label).classes("text-sm")

    # Content area — ui.sub_pages() swaps this without a full page reload
    with ui.column().classes("w-full h-full p-0 m-0"):
        ui.sub_pages(
            {
                "/dashboard": dashboard_content,
                "/controller": controller_content,
                "/twin/{room_id}": twin_content,
                "/": lambda: ui.navigate.to("/dashboard"),
            }
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Launch the unified medtech-suite web application."""
    storage_secret = os.environ.get(NICEGUI_STORAGE_SECRET_ENV)
    if not storage_secret:
        raise RuntimeError(
            f"{NICEGUI_STORAGE_SECRET_ENV} must be set before starting the application"
        )

    # Eagerly instantiate stable backends (dashboard, controller) before
    # ui.run() so they register app.on_startup / on_shutdown hooks while the
    # app is still in the pre-start state.  The digital twin backend is
    # room-scoped and created lazily on first page visit; GuiBackend.__init__
    # handles that case by scheduling the start coroutine as a background task.
    from hospital_dashboard.dashboard.dashboard import _current_backend as _dash_init
    from hospital_dashboard.procedure_controller.controller import (
        _current_backend as _ctrl_init,
    )

    _dash_init()
    _ctrl_init()

    app.add_static_files("/static", "resources/")

    try:
        ui.run(
            storage_secret=storage_secret,
            reload=False,
            title="Medtech Suite",
        )
    except KeyboardInterrupt:
        pass


if __name__ in {"__main__", "__mp_main__"}:
    main()


__all__ = [
    "health",
    "main",
    "ready",
    "shell_page",
    "_backends_ready",
]
