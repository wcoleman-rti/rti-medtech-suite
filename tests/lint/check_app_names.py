"""Verify every participant/writer/reader in XML has a const in app_names.idl.

Parses SurgicalParticipants.xml and app_names.idl to cross-check that no
entity name is missing from the IDL constants file.

Tags: @consistency @lint
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

pytestmark = [pytest.mark.consistency, pytest.mark.lint]

ROOT = Path(__file__).resolve().parents[2]
XML_PATH = ROOT / "interfaces" / "participants" / "SurgicalParticipants.xml"
IDL_PATH = ROOT / "interfaces" / "idl" / "app_names.idl"


def _extract_xml_names():
    """Extract all participant, writer, and reader names from XML."""
    tree = ET.parse(XML_PATH)
    root = tree.getroot()
    ns = ""

    lib_name = None
    participants = []
    writers = []
    readers = []

    for lib in root.iter("domain_participant_library"):
        lib_name = lib.get("name")
        for dp in lib.iter("domain_participant"):
            dp_name = dp.get("name")
            participants.append(f"{lib_name}::{dp_name}")
            for pub in dp.iter("publisher"):
                pub_name = pub.get("name")
                for dw in pub.iter("data_writer"):
                    writers.append(f"{pub_name}::{dw.get('name')}")
            for sub in dp.iter("subscriber"):
                sub_name = sub.get("name")
                for dr in sub.iter("data_reader"):
                    readers.append(f"{sub_name}::{dr.get('name')}")

    return set(participants), set(writers), set(readers)


def _extract_idl_values():
    """Extract all const string values from app_names.idl."""
    content = IDL_PATH.read_text()
    return set(re.findall(r'=\s*"([^"]+)"', content))


class TestXmlIdlCrossCheck:
    """Every XML entity name must have a corresponding IDL constant."""

    def test_all_participants_in_idl(self):
        participants, _, _ = _extract_xml_names()
        idl_values = _extract_idl_values()
        missing = participants - idl_values
        assert not missing, f"Participants in XML but not in app_names.idl: {missing}"

    def test_all_writers_in_idl(self):
        _, writers, _ = _extract_xml_names()
        idl_values = _extract_idl_values()
        missing = writers - idl_values
        assert not missing, f"Writers in XML but not in app_names.idl: {missing}"

    def test_all_readers_in_idl(self):
        _, _, readers = _extract_xml_names()
        idl_values = _extract_idl_values()
        missing = readers - idl_values
        assert not missing, f"Readers in XML but not in app_names.idl: {missing}"
