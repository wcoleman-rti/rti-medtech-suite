"""Tests for room-level GUI navigation module (Step UX.4).

Tags: @gui @unit @room-nav
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from surgical_procedure.room_nav import RoomNav

pytestmark = [pytest.mark.gui, pytest.mark.unit]


def _make_catalog_sample(
    host_id: str,
    service_id: str,
    display_name: str,
    room_id: str = "",
    gui_url: str = "",
    procedure_id: str = "",
) -> SimpleNamespace:
    """Build a fake ServiceCatalog sample with property list."""
    props: list[Any] = []
    if room_id:
        props.append(SimpleNamespace(name="room_id", current_value=room_id))
    if gui_url:
        props.append(SimpleNamespace(name="gui_url", current_value=gui_url))
    if procedure_id:
        props.append(SimpleNamespace(name="procedure_id", current_value=procedure_id))
    return SimpleNamespace(
        host_id=host_id,
        service_id=service_id,
        display_name=display_name,
        properties=props,
    )


class _FakeReader:
    """Stub reader that yields nothing — used to avoid DDS init."""

    async def take_data_async(self):
        # Yield nothing — never produces samples
        return
        yield  # noqa: F401 — makes this an async generator


class TestRoomNavDiscovery:
    """RoomNav discovers sibling GUIs via ServiceCatalog."""

    def test_creates_with_injected_reader(self) -> None:
        """RoomNav can be created with an injected reader (no DDS)."""
        nav = RoomNav("OR-1", catalog_reader=_FakeReader())
        assert nav.room_id == "OR-1"
        assert nav.siblings == {}

    def test_discovers_sibling_gui(self) -> None:
        """A ServiceCatalog with matching room_id and gui_url is discovered."""
        nav = RoomNav("OR-1", catalog_reader=_FakeReader())
        nav._update_catalog(
            _make_catalog_sample(
                "h1", "s1", "Digital Twin", room_id="OR-1", gui_url="http://twin:8081"
            )
        )
        assert "Digital Twin" in nav.siblings
        assert nav.siblings["Digital Twin"] == "http://twin:8081"

    def test_ignores_different_room(self) -> None:
        """ServiceCatalog with different room_id is ignored."""
        nav = RoomNav("OR-1", catalog_reader=_FakeReader())
        nav._update_catalog(
            _make_catalog_sample(
                "h1", "s1", "Twin", room_id="OR-2", gui_url="http://twin:8082"
            )
        )
        assert nav.siblings == {}

    def test_ignores_no_gui_url(self) -> None:
        """ServiceCatalog without gui_url is not added to siblings."""
        nav = RoomNav("OR-1", catalog_reader=_FakeReader())
        nav._update_catalog(
            _make_catalog_sample("h1", "s1", "Robot Arm", room_id="OR-1")
        )
        assert nav.siblings == {}

    def test_removes_sibling_when_gui_url_cleared(self) -> None:
        """When a previously discovered service loses gui_url, it's removed."""
        nav = RoomNav("OR-1", catalog_reader=_FakeReader())
        nav._update_catalog(
            _make_catalog_sample(
                "h1", "s1", "Twin", room_id="OR-1", gui_url="http://twin:8081"
            )
        )
        assert "Twin" in nav.siblings
        # Service re-publishes without gui_url
        nav._update_catalog(_make_catalog_sample("h1", "s1", "Twin", room_id="OR-1"))
        assert "Twin" not in nav.siblings

    def test_multiple_siblings(self) -> None:
        """Multiple services with gui_url in the same room are all discovered."""
        nav = RoomNav("OR-1", catalog_reader=_FakeReader())
        nav._update_catalog(
            _make_catalog_sample(
                "h1", "s1", "Twin", room_id="OR-1", gui_url="http://twin:8081"
            )
        )
        nav._update_catalog(
            _make_catalog_sample(
                "h2", "s2", "Controller", room_id="OR-1", gui_url="http://ctrl:8091"
            )
        )
        assert len(nav.siblings) == 2
        assert "Twin" in nav.siblings
        assert "Controller" in nav.siblings

    def test_no_hospital_dashboard_link(self) -> None:
        """Room nav never includes a link to the hospital dashboard."""
        nav = RoomNav("OR-1", catalog_reader=_FakeReader())
        # Even if a "dashboard" ServiceCatalog arrives with a different room
        nav._update_catalog(
            _make_catalog_sample(
                "h1",
                "dash",
                "Hospital Dashboard",
                room_id="HOSPITAL",
                gui_url="http://dashboard:8080",
            )
        )
        assert "Hospital Dashboard" not in nav.siblings

    def test_operates_without_hospital(self) -> None:
        """RoomNav works correctly without any hospital-scoped services."""
        nav = RoomNav("OR-1", catalog_reader=_FakeReader())
        nav._update_catalog(
            _make_catalog_sample(
                "h1", "s1", "Twin", room_id="OR-1", gui_url="http://twin:8081"
            )
        )
        assert nav.siblings == {"Twin": "http://twin:8081"}

    def test_siblings_is_copy(self) -> None:
        """siblings property returns a copy, not a mutable reference."""
        nav = RoomNav("OR-1", catalog_reader=_FakeReader())
        nav._update_catalog(
            _make_catalog_sample(
                "h1", "s1", "Twin", room_id="OR-1", gui_url="http://twin:8081"
            )
        )
        s = nav.siblings
        s["HACKED"] = "http://evil"
        assert "HACKED" not in nav.siblings
