"""medtech.gui_runtime — lightweight NiceGUI runtime wrapper.

Provides a host-owned runtime object that GUI services can receive via
constructor injection instead of accessing NiceGUI globals directly.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from nicegui import app, ui


class NiceGuiRuntime:
    """Host-owned wrapper around the process-local NiceGUI app singleton."""

    def __init__(
        self,
        *,
        external_base_url: str = "",
        bind_host: str = "0.0.0.0",
        bind_port: int = 8080,
    ) -> None:
        self._external_base_url = external_base_url.rstrip("/")
        self._bind_host = bind_host
        self._bind_port = bind_port

    @property
    def external_base_url(self) -> str:
        """Externally reachable base URL (for catalog links), if configured."""
        return self._external_base_url

    @property
    def bind_host(self) -> str:
        return self._bind_host

    @property
    def bind_port(self) -> int:
        return self._bind_port

    @classmethod
    def from_env(cls) -> "NiceGuiRuntime":
        """Build runtime from conventional MEDTECH GUI environment variables."""
        external = os.environ.get("MEDTECH_GUI_EXTERNAL_URL", "")
        port = int(os.environ.get("MEDTECH_GUI_PORT", "8080"))
        host = os.environ.get("MEDTECH_GUI_BIND_HOST", "0.0.0.0")
        return cls(external_base_url=external, bind_host=host, bind_port=port)

    def url_for(self, path: str) -> str:
        """Return external URL for *path* if external_base_url is configured."""
        if not self._external_base_url:
            return ""
        normalized = path if path.startswith("/") else f"/{path}"
        return f"{self._external_base_url}{normalized}"

    def on_startup(self, callback: Callable[..., Any]) -> None:
        app.on_startup(callback)

    def on_shutdown(self, callback: Callable[..., Any]) -> None:
        app.on_shutdown(callback)

    def add_root_redirect(self, target_path: str) -> None:
        """Add a root route that redirects to *target_path*."""

        @ui.page("/")
        def _root() -> None:
            ui.navigate.to(target_path)

    def run(self, *, title: str, favicon: str | None = None) -> None:
        """Run the NiceGUI app with host-owned bind settings."""
        # Strip pytest env vars so NiceGUI doesn't activate its test harness
        # when the GUI runtime is launched as a subprocess during pytest.
        os.environ.pop("PYTEST_CURRENT_TEST", None)
        os.environ.pop("NICEGUI_SCREEN_TEST_PORT", None)
        ui.run(
            host=self._bind_host,
            port=self._bind_port,
            storage_secret=os.environ.get(
                "NICEGUI_STORAGE_SECRET", "medtech-local-dev-secret"
            ),
            reload=False,
            title=title,
            favicon=favicon,
        )
