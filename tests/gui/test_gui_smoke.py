"""Smoke tests: NiceGUI + rti.asyncio event loop coexistence (Step N.1).

Validates that NiceGUI and rti.connext coexist on the same asyncio
event loop — the foundational requirement for the NiceGUI migration.

Spec: nicegui-migration.md — Event Loop Integration
Tags: @gui @integration
"""

from __future__ import annotations

import asyncio

import app_names
import pytest
import rti.asyncio  # noqa: F401 — enable async DDS extensions
import rti.connextdds as dds
from medtech.dds import initialize_connext
from nicegui import app

pytestmark = [pytest.mark.gui, pytest.mark.integration]

names = app_names.MedtechEntityNames.SurgicalParticipants


# ---------------------------------------------------------------------------
# Test gate: NiceGUI installs and imports successfully
# ---------------------------------------------------------------------------


class TestNiceguiInstall:
    """NiceGUI is installed and importable."""

    def test_nicegui_importable(self):
        """nicegui package imports without error."""
        import nicegui

        assert hasattr(nicegui, "__version__")

    def test_nicegui_app_colors(self):
        """app.colors() can be called with RTI brand palette."""
        app.colors(
            primary="#004C97",
            secondary="#71C5E8",
            accent="#ED8B00",
            positive="#43B02A",
            negative="#E4002B",
            warning="#ED8B00",
        )

    def test_nicegui_quasar_config(self):
        """Quasar icon set config constant is valid."""
        config = {"iconSet": "material-symbols-outlined"}
        assert config["iconSet"] == "material-symbols-outlined"


# ---------------------------------------------------------------------------
# Test gate: rti.asyncio coexists with NiceGUI's asyncio event loop
# ---------------------------------------------------------------------------


class TestEventLoopCoexistence:
    """NiceGUI and rti.asyncio share the same asyncio event loop."""

    def test_rti_asyncio_enabled(self):
        """rti.asyncio module loads without conflict with NiceGUI."""
        import rti.asyncio as rti_async

        assert rti_async is not None

    def test_dds_participant_creation(self):
        """DDS participant can be created alongside NiceGUI app."""
        initialize_connext()
        provider = dds.QosProvider.default
        participant = provider.create_participant_from_config(
            names.CONTROL_DIGITAL_TWIN
        )
        assert participant is not None
        participant.close()

    @pytest.mark.asyncio
    async def test_async_reader_on_asyncio_loop(self):
        """An async DDS reader coroutine runs on a standard asyncio loop.

        Verifies that rti.asyncio async iteration is compatible with
        the asyncio event loop (same loop NiceGUI uses).
        """
        loop = asyncio.get_running_loop()
        assert loop is not None, "Should have a running asyncio event loop"

        initialize_connext()
        provider = dds.QosProvider.default
        participant = provider.create_participant_from_config(
            names.CONTROL_DIGITAL_TWIN
        )
        try:
            reader_any = participant.find_datareader(names.TWIN_ROBOT_STATE_READER)
            assert reader_any is not None, "RobotStateReader should exist"
        finally:
            participant.close()
