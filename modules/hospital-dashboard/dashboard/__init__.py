"""hospital_dashboard.dashboard — Hospital Dashboard GUI package."""

from .dashboard import (  # noqa: F401
    _STATIC_NAV_ITEMS,
    DashboardBackend,
    HospitalDashboard,
    _backends_ready,
    _page_title_for_path,
    backend,
    dashboard_page,
    health,
    ready,
    shell_page,
)

__all__ = [
    "DashboardBackend",
    "HospitalDashboard",
    "_STATIC_NAV_ITEMS",
    "_backends_ready",
    "_page_title_for_path",
    "backend",
    "dashboard_page",
    "health",
    "ready",
    "shell_page",
]
