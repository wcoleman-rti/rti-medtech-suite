"""Hospital dashboard NiceGUI application entry point.

Serves only the hospital-level dashboard. Room-level GUIs (Procedure
Controller, Digital Twin) run in per-room containers launched by
``medtech run or``.

Routes:
    /                  Landing page (redirects to /dashboard)
    /dashboard         Hospital Dashboard  (dashboard.dashboard_content)

Health / Readiness probes:
    GET /health        Liveness probe — always 200 while process is running
    GET /ready         Readiness probe — 200 when all GuiBackend instances are
                       active, 503 otherwise
"""

from __future__ import annotations

import os

from fastapi.responses import JSONResponse

# Import page builder functions — module-level GuiBackend instantiation
# happens inside these modules, self-registering lifecycle hooks.
from hospital_dashboard.dashboard.dashboard import dashboard_content  # noqa: F401
from medtech.gui._backend import GuiBackend
from medtech.gui._icons import ICONS
from medtech.gui._theme import (
    NICEGUI_STORAGE_SECRET_DEFAULT,
    NICEGUI_STORAGE_SECRET_ENV,
    NICEGUI_THEME_MODE_KEY,
    _resource_dir,
    _theme_mode_value,
    init_theme,
)
from medtech.gui._widgets import ConnectionDot
from nicegui import app, ui

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

# Tier 1 — Static local pages (always present)
_STATIC_NAV_ITEMS = [
    ("/dashboard", ICONS["dashboard"], "Dashboard"),
]

# Page display names keyed by route prefix (for breadcrumb)
_PAGE_TITLES: dict[str, str] = {
    "/dashboard": "Dashboard",
}


def _page_title_for_path(path: str) -> str:
    """Return a human-readable page title for a given URL path."""
    for prefix, title in _PAGE_TITLES.items():
        if path == prefix or path.startswith(prefix):
            return title
    return "Home"


def shell_page() -> None:
    """Root SPA shell: full-screen content with floating navigation pill."""
    init_theme(title="Medtech Suite", header=False)

    stored_mode = app.storage.user.get(NICEGUI_THEME_MODE_KEY, "system")
    dark_mode = ui.dark_mode(_theme_mode_value(stored_mode))  # noqa: F841

    # ---- Floating navigation pill (top-center overlay) --------------------
    # Positioned absolutely over the full-screen content.  No header or
    # sidebar — the entire viewport belongs to the active page.
    _NAV_PILL_CSS = (
        "position: fixed; top: 18px; left: 50%; transform: translateX(-50%);"
        " z-index: 100; pointer-events: auto;"
        " max-width: 95vw; white-space: nowrap;"
    )
    with (
        ui.row()
        .classes("items-center gap-2 px-4 py-2 rounded-full glass-panel flex-nowrap")
        .style(_NAV_PILL_CSS)
    ):
        # Theme-aware logo: white logo for dark mode, color logo for light mode.
        ui.html(
            '<img src="/images/rti-logo-white.png" '
            'class="rti-logo-dark" '
            'style="height: 1.8rem; width: auto; opacity: 0.85;" alt="RTI">'
            '<img src="/images/rti-logo-color.png" '
            'class="rti-logo-light" '
            'style="height: 1.8rem; width: auto; opacity: 0.85;" alt="RTI">'
        )

        # --- Static page tabs ---
        nav_buttons: dict[str, ui.button] = {}
        for path, icon, label in _STATIC_NAV_ITEMS:
            btn = (
                ui.button(label, icon=icon, on_click=lambda p=path: ui.navigate.to(p))
                .props("flat no-caps size=md")
                .classes("rounded-full px-4 transition-fast")
            )
            nav_buttons[path] = btn

        # --- Separator + theme toggle + connection dot ---
        ui.separator().props("vertical").classes("mx-2 h-6")
        stored = app.storage.user.get(NICEGUI_THEME_MODE_KEY, "system")
        dm = ui.dark_mode(_theme_mode_value(stored))

        def _cycle_to(new_value: bool | None) -> None:
            dm.set_value(new_value)
            if new_value is True:
                mode = "dark"
            elif new_value is False:
                mode = "light"
            else:
                mode = "system"
            app.storage.user[NICEGUI_THEME_MODE_KEY] = mode

        with (
            ui.button(on_click=lambda: _cycle_to(None))
            .props("flat round size=sm")
            .bind_visibility_from(dm, "value", value=True)
        ):
            ui.icon(ICONS["dark_mode"]).classes("text-base")
        with (
            ui.button(on_click=lambda: _cycle_to(True))
            .props("flat round size=sm")
            .bind_visibility_from(dm, "value", value=False)
        ):
            ui.icon(ICONS["light_mode"]).classes("text-base")
        with (
            ui.button(on_click=lambda: _cycle_to(False))
            .props("flat round size=sm")
            .bind_visibility_from(dm, "value", backward=lambda v: v is None)
        ):
            ui.icon(ICONS["auto_mode"]).classes("text-base")

        ConnectionDot(connected=True)

    # ---- Active-tab highlighting ------------------------------------------
    def _update_active_nav(path: str) -> None:
        for btn_path, btn in nav_buttons.items():
            if path == btn_path or (btn_path != "/" and path.startswith(btn_path)):
                btn.classes(add="bg-primary text-white", remove="")
            else:
                btn.classes(remove="bg-primary text-white")

    # ---- Full-screen content area -----------------------------------------
    # Top padding reserves space so page content doesn't hide behind the pill.
    with ui.column().classes("w-full h-full p-0 m-0").style("padding-top: 64px;"):
        routes: dict = {
            "/dashboard": dashboard_content,
            "/": lambda: ui.navigate.to("/dashboard"),
        }
        ui.sub_pages(routes)

    # Track path changes for active highlighting
    initial_path = "/dashboard"
    if hasattr(ui.context, "client") and hasattr(ui.context.client, "sub_pages_router"):
        router = ui.context.client.sub_pages_router
        initial_path = router.current_path.split("?")[0] or "/dashboard"
        router.on_path_changed(lambda path: _update_active_nav(path))
    _update_active_nav(initial_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Launch the hospital dashboard web application."""
    storage_secret = os.environ.get(
        NICEGUI_STORAGE_SECRET_ENV, NICEGUI_STORAGE_SECRET_DEFAULT
    )

    # Eagerly instantiate the dashboard backend before ui.run() so it
    # registers app.on_startup/on_shutdown hooks while the app is still
    # in the pre-start state.
    from hospital_dashboard.dashboard.dashboard import _current_backend as _dash_init

    _dash_init()

    # Remove standalone @ui.page routes registered by module imports so that
    # the root=shell_page catch-all handles all paths through the SPA shell.
    _standalone_paths = {
        "/dashboard",
    }
    app.routes[:] = [
        r for r in app.routes if getattr(r, "path", None) not in _standalone_paths
    ]

    app.add_static_files("/static", str(_resource_dir()))

    favicon_path = _resource_dir() / "images" / "favicon.ico"

    try:
        ui.run(
            root=shell_page,
            storage_secret=storage_secret,
            reload=False,
            title="Medtech Suite",
            favicon=str(favicon_path) if favicon_path.is_file() else None,
        )
    except KeyboardInterrupt:
        pass


if __name__ in {"__main__", "__mp_main__"}:
    main()


__all__ = [
    "_STATIC_NAV_ITEMS",
    "_PAGE_TITLES",
    "_page_title_for_path",
    "health",
    "main",
    "ready",
    "shell_page",
    "_backends_ready",
]
