"""hospital_dashboard.dashboard — Hospital Dashboard GUI package."""

from .dashboard import (  # noqa: F401
    DashboardBackend,
    HospitalDashboard,
    backend,
    dashboard_page,
)

__all__ = ["DashboardBackend", "HospitalDashboard", "backend", "dashboard_page"]
