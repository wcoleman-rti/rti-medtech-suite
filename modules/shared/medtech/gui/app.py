"""Unified NiceGUI application entry point for medtech-suite.

Serves all GUI modules — Hospital Dashboard, Procedure Controller, and
Digital Twin — from a single process with a persistent SPA shell.

Routes:
    /                  Landing page (redirects to /dashboard)
    /dashboard         Hospital Dashboard  (dashboard.dashboard_content)
    /controller        Procedure Controller (controller.controller_content)
    /twin/{room_id}    Digital Twin 3D      (digital_twin.twin_content)

Health / Readiness probes:
    GET /health        Liveness probe — always 200 while process is running
    GET /ready         Readiness probe — 200 when all GuiBackend instances are
                       active, 503 otherwise

Architecture notes:
    GuiBackend subclasses are instantiated at module level in each page
    module.  Their __init__ calls app.on_startup/on_shutdown automatically,
    so this main entry point never manually calls start() or close().

    ``shell_page`` is passed as the ``root`` argument to ``ui.run()``, making
    it the handler for **all** URL paths. ``ui.sub_pages()`` inside it does
    client-side routing so the shell (header, drawer, connection dot) persists
    across all navigations and browser refreshes.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from fastapi.responses import JSONResponse

# Import page builder functions — module-level GuiBackend instantiation
# happens inside these modules, self-registering lifecycle hooks.
from hospital_dashboard.dashboard.dashboard import dashboard_content  # noqa: F401
from hospital_dashboard.procedure_controller.controller import (  # noqa: F401
    ControllerBackend,
    controller_content,
)
from medtech.gui._backend import GuiBackend
from medtech.gui._icons import ICONS
from medtech.gui._theme import (
    NICEGUI_STORAGE_SECRET_DEFAULT,
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

# Tier 1 — Static local pages (always present)
_STATIC_NAV_ITEMS = [
    ("/dashboard", ICONS["dashboard"], "Dashboard"),
    ("/controller", ICONS["service"], "Controller"),
]

# Page display names keyed by route prefix (for breadcrumb)
_PAGE_TITLES: dict[str, str] = {
    "/dashboard": "Dashboard",
    "/controller": "Controller",
    "/twin/": "Digital Twin",
}


def _page_title_for_path(path: str) -> str:
    """Return a human-readable page title for a given URL path."""
    for prefix, title in _PAGE_TITLES.items():
        if path == prefix or path.startswith(prefix):
            # For twin pages, extract room_id
            if prefix == "/twin/" and len(path) > len(prefix):
                room_id = path[len(prefix) :]
                return f"Digital Twin — {room_id}"
            return title
    return "Home"


def _get_controller_backend() -> ControllerBackend | None:
    """Return the ControllerBackend from the registry, if any."""
    for b in GuiBackend.registry():
        if isinstance(b, ControllerBackend):
            return b
    return None


def _discovered_gui_services() -> list[tuple[str, str, str, str]]:
    """Return discovered GUI services from ServiceCatalog.

    Returns list of (display_name, room_id, gui_url, icon) tuples for
    services that have a non-empty gui_url property.
    """
    ctrl = _get_controller_backend()
    if ctrl is None:
        return []
    results: list[tuple[str, str, str, str]] = []
    for (_host_id, _service_id), catalog in ctrl.catalogs.items():
        gui_url = ""
        display_name = ""
        room_id = ""
        for prop in getattr(catalog, "properties", None) or []:
            name = getattr(prop, "name", "")
            val = getattr(prop, "current_value", "") or ""
            if name == "gui_url" and val:
                gui_url = val
            elif name == "display_name" and val:
                display_name = val
            elif name == "room_id" and val:
                room_id = val
        if gui_url:
            label = display_name or _service_id
            if room_id:
                label = f"{label} ({room_id})"
            icon = ICONS.get("robot", "smart_toy")
            results.append((label, room_id, gui_url, icon))
    return results


def shell_page() -> None:
    """Root SPA shell: persistent header + left drawer + sub-pages content."""
    init_theme(title="Medtech Suite")

    stored_mode = app.storage.user.get(NICEGUI_THEME_MODE_KEY, "system")
    dark_mode = ui.dark_mode(_theme_mode_value(stored_mode))  # noqa: F841

    # Track current path for active-nav highlighting and breadcrumb
    current_path: dict[str, str] = {"value": ""}
    breadcrumb_label: ui.label | None = None

    # --- Dynamic breadcrumb in header ---
    # We inject a breadcrumb label into the header's content area
    with ui.header().classes(
        "items-center gap-4 px-4 py-3 bg-primary text-white"
    ).style("box-shadow: 0 4px 12px rgba(0,0,0,0.15);"):
        from medtech.gui._theme import _logo_path

        logo = _logo_path()
        ui.html(
            f'<img src="/images/{logo.name}" style="height: 2rem; width: auto;" alt="RTI">'
        )
        ui.label("Medtech Suite").classes("text-2xl font-bold brand-heading")
        breadcrumb_label = ui.label("").classes("text-sm text-white/70 font-normal")
        ui.space()
        # Theme toggle
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

        with ui.button(on_click=lambda: _cycle_to(None)).props("flat round").classes(
            "text-white"
        ).bind_visibility_from(dm, "value", value=True):
            ui.icon(ICONS["dark_mode"]).classes("text-xl")
        with ui.button(on_click=lambda: _cycle_to(True)).props("flat round").classes(
            "text-white"
        ).bind_visibility_from(dm, "value", value=False):
            ui.icon(ICONS["light_mode"]).classes("text-xl")
        with ui.button(on_click=lambda: _cycle_to(False)).props("flat round").classes(
            "text-white"
        ).bind_visibility_from(dm, "value", backward=lambda v: v is None):
            ui.icon(ICONS["auto_mode"]).classes("text-xl")
        from medtech.gui._widgets import ConnectionDot

        ConnectionDot(connected=True)

    # --- Navigation drawer ---
    nav_buttons: dict[str, ui.button] = {}

    def _update_active_nav(path: str) -> None:
        """Highlight the nav button matching the current path."""
        for btn_path, btn in nav_buttons.items():
            if path == btn_path or (btn_path != "/" and path.startswith(btn_path)):
                btn.classes(add="bg-white/20 font-bold", remove="")
            else:
                btn.classes(remove="bg-white/20 font-bold")
        # Update breadcrumb
        if breadcrumb_label is not None:
            title = _page_title_for_path(path)
            breadcrumb_label.set_text(f"› {title}" if title != "Home" else "")

    with ui.left_drawer(fixed=True).classes(
        "bg-primary text-white flex flex-col gap-2 pt-4"
    ):
        ui.label("Navigation").classes("px-4 font-bold text-sm uppercase text-white/60")
        for path, icon, label in _STATIC_NAV_ITEMS:
            btn = (
                ui.button(on_click=lambda p=path: ui.navigate.to(p))
                .props("flat align=left")
                .classes("w-full text-white justify-start px-4 gap-3")
            )
            with btn:
                ui.icon(icon).classes("text-xl")
                ui.label(label).classes("text-sm")
            nav_buttons[path] = btn

        # Tier 2 — Discovered GUI services (dynamic)
        ui.separator().classes("my-2 bg-white/20")
        ui.label("Services").classes("px-4 font-bold text-sm uppercase text-white/60")
        discovered_container = ui.column().classes("w-full gap-1")

        # Obtain browser origin once for same-origin / cross-origin detection
        browser_origin: dict[str, str] = {"value": ""}

        async def _detect_origin() -> None:
            try:
                origin = await ui.run_javascript("window.location.origin")
                browser_origin["value"] = origin
            except Exception:
                pass

        ui.timer(0.5, _detect_origin, once=True)

        @ui.refreshable
        def render_discovered_services() -> None:
            discovered_container.clear()
            services = _discovered_gui_services()
            if not services:
                with discovered_container:
                    ui.label("No services discovered").classes(
                        "px-4 text-xs text-white/40 italic"
                    )
                return
            with discovered_container:
                for svc_label, _room_id, gui_url, svc_icon in services:
                    parsed = urlparse(gui_url)
                    svc_origin = f"{parsed.scheme}://{parsed.netloc}"
                    is_local = (
                        browser_origin["value"]
                        and svc_origin == browser_origin["value"]
                    )
                    if is_local:
                        svc_path = parsed.path or "/"

                        def _nav_local(p: str = svc_path) -> None:
                            ui.navigate.to(p)

                        click_fn = _nav_local
                        hint_icon = "home"
                    else:

                        def _nav_remote(u: str = gui_url) -> None:
                            ui.navigate.to(u, new_tab=True)

                        click_fn = _nav_remote
                        hint_icon = "open_in_new"

                    with ui.button(on_click=click_fn).props("flat align=left").classes(
                        "w-full text-white justify-start px-4 gap-3 text-xs"
                    ):
                        ui.icon(svc_icon).classes("text-lg")
                        ui.label(svc_label).classes("text-xs")
                        ui.icon(hint_icon).classes("text-xs text-white/50")

        render_discovered_services()
        ui.timer(2.0, render_discovered_services.refresh)

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

    # Track path changes for active highlighting
    if hasattr(ui.context, "client") and hasattr(ui.context.client, "sub_pages_router"):
        ui.context.client.sub_pages_router.on_path_changed(
            lambda path: (
                current_path.__setitem__("value", path),
                _update_active_nav(path),
            )
        )
    # Set initial active state
    _update_active_nav("/dashboard")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Launch the unified medtech-suite web application."""
    storage_secret = os.environ.get(
        NICEGUI_STORAGE_SECRET_ENV, NICEGUI_STORAGE_SECRET_DEFAULT
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

    from medtech.gui._theme import _resource_dir

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
