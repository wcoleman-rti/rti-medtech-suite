"""medtech.gui_service — GUI-specific service abstractions."""

from __future__ import annotations

from abc import ABC

from medtech.gui_runtime import NiceGuiRuntime
from medtech.service import Service


class GuiService(Service, ABC):
    """Base class for services hosted on a host-owned NiceGUI runtime."""

    def __init__(
        self,
        gui_runtime: NiceGuiRuntime,
        *,
        canonical_path: str,
        claimed_paths: tuple[str, ...] = (),
    ) -> None:
        self._gui_runtime = gui_runtime
        canonical = (
            canonical_path if canonical_path.startswith("/") else f"/{canonical_path}"
        )
        claims = claimed_paths or (canonical,)
        normalized_claims = tuple(p if p.startswith("/") else f"/{p}" for p in claims)
        self._canonical_path = canonical
        self._claimed_paths = normalized_claims

    @property
    def gui_runtime(self) -> NiceGuiRuntime:
        return self._gui_runtime

    @property
    def canonical_path(self) -> str:
        """Canonical route used for generating external GUI URL."""
        return self._canonical_path

    @property
    def claimed_paths(self) -> tuple[str, ...]:
        """Route templates claimed by this service for collision checks."""
        return self._claimed_paths

    def gui_urls(self) -> list[str]:
        """Compose GUI URL from host-owned runtime and canonical path."""
        url = self.gui_runtime.url_for(self._canonical_path)
        return [url] if url else []
