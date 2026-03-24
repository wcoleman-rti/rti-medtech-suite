"""Tests for medtech_gui.init_theme — Step 1.6 test gate.

Tags: @gui @integration
"""

import pytest
from medtech_gui import init_theme
from PySide6.QtGui import QFontDatabase

pytestmark = [pytest.mark.gui, pytest.mark.integration]

REQUIRED_FAMILIES = {"Roboto Condensed", "Montserrat", "Roboto Mono"}


@pytest.fixture(scope="module")
def header(qapp):
    """Call init_theme once for the module and return the header widget."""
    return init_theme(qapp)


class TestStylesheet:
    """init_theme loads the .qss stylesheet."""

    def test_stylesheet_applied(self, qapp, header):
        ss = qapp.styleSheet()
        assert len(ss) > 0, "Stylesheet should be non-empty"
        assert "#004C97" in ss, "Stylesheet should contain RTI Blue"


class TestFonts:
    """init_theme registers bundled fonts via QFontDatabase."""

    def test_roboto_condensed_registered(self, header):
        families = QFontDatabase.families()
        assert "Roboto Condensed" in families

    def test_montserrat_registered(self, header):
        families = QFontDatabase.families()
        assert "Montserrat" in families

    def test_roboto_mono_registered(self, header):
        families = QFontDatabase.families()
        assert any(f.startswith("Roboto Mono") for f in families)


class TestHeaderWidget:
    """init_theme returns a header bar with correct branding."""

    def test_header_object_name(self, header):
        assert header.objectName() == "headerBar"

    def test_header_has_children(self, header):
        # Should have at least a logo label and a title label
        from PySide6.QtWidgets import QLabel

        labels = header.findChildren(QLabel)
        assert len(labels) >= 1, "Header should contain at least one QLabel"

    def test_header_background_color(self, qapp, header):
        # The stylesheet sets headerBar background to #004C97
        ss = qapp.styleSheet()
        assert "QFrame#headerBar" in ss
        assert "#004C97" in ss

    def test_header_has_logo(self, header):
        from PySide6.QtWidgets import QLabel

        labels = header.findChildren(QLabel)
        logo_found = any(
            label.pixmap() is not None and not label.pixmap().isNull()
            for label in labels
        )
        assert logo_found, "Header should contain a label with the RTI logo pixmap"
