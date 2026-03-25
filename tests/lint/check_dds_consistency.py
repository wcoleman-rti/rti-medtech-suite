"""Lint checks for @consistency scenarios from spec/common-behaviors.md.

Static analysis of the codebase to verify DDS consistency patterns:
entity name usage, QosProvider usage, DDS entity type encapsulation,
and partition QoS rules.

Tags: @lint @consistency
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.lint, pytest.mark.consistency]

ROOT = Path(__file__).resolve().parents[2]
MODULES_DIR = ROOT / "modules"
INTERFACES_DIR = ROOT / "interfaces"
IDL_PATH = INTERFACES_DIR / "idl" / "app_names.idl"


def _get_module_source_files():
    """Collect all .py, .cpp, .hpp files under modules/."""
    files = []
    for ext in ("*.py", "*.cpp", "*.hpp"):
        files.extend(MODULES_DIR.rglob(ext))
    return [f for f in files if "__pycache__" not in str(f)]


def _get_entity_name_values():
    """Extract all const string values from app_names.idl."""
    content = IDL_PATH.read_text()
    return set(re.findall(r'=\s*"([^"]+)"', content))


class TestEntityNameConstants:
    """Scenario: All entity lookups use generated name constants (AP-11)."""

    def test_no_raw_entity_name_strings_in_modules(self):
        """No raw string literals matching known entity names in modules/."""
        entity_names = _get_entity_name_values()
        violations = []
        for src in _get_module_source_files():
            content = src.read_text()
            for name in entity_names:
                # Look for the name as a quoted string literal
                pattern = f'"{re.escape(name)}"'
                for match in re.finditer(pattern, content):
                    line_num = content[: match.start()].count("\n") + 1
                    violations.append(
                        f"  {src.relative_to(ROOT)}:{line_num}: "
                        f'raw literal "{name}"'
                    )
        assert (
            not violations
        ), "AP-11: Raw entity name string literals found in modules/:\n" + "\n".join(
            violations
        )


class TestDefaultQosProvider:
    """Scenario: Only default QosProvider is used (AP-8)."""

    def test_no_custom_qos_provider_python(self):
        """No custom QosProvider() constructor in Python module code."""
        violations = []
        for src in MODULES_DIR.rglob("*.py"):
            if "__pycache__" in str(src):
                continue
            content = src.read_text()
            for i, line in enumerate(content.splitlines(), 1):
                if "QosProvider(" in line and "QosProvider.default" not in line:
                    violations.append(f"  {src.relative_to(ROOT)}:{i}: {line.strip()}")
        assert (
            not violations
        ), "AP-8: Custom QosProvider constructor found:\n" + "\n".join(violations)

    def test_no_custom_qos_provider_cpp(self):
        """No custom QosProvider() constructor in C++ module code."""
        violations = []
        for ext in ("*.cpp", "*.hpp"):
            for src in MODULES_DIR.rglob(ext):
                content = src.read_text()
                for i, line in enumerate(content.splitlines(), 1):
                    if "QosProvider(" in line and "QosProvider::Default()" not in line:
                        violations.append(
                            f"  {src.relative_to(ROOT)}:{i}: {line.strip()}"
                        )
        assert (
            not violations
        ), "AP-8: Custom QosProvider constructor found:\n" + "\n".join(violations)


class TestDdsEntityEncapsulation:
    """Scenario: DDS entity types are not exposed in public class APIs
    (AP-10)."""

    def test_no_dds_types_in_python_public_api(self):
        """No DDS entity types in Python public methods/properties."""
        dds_types = {
            "DataWriter",
            "DataReader",
            "DomainParticipant",
            "Publisher",
            "Subscriber",
        }
        violations = []
        for src in MODULES_DIR.rglob("*.py"):
            if "__pycache__" in str(src):
                continue
            content = src.read_text()
            for i, line in enumerate(content.splitlines(), 1):
                stripped = line.strip()
                # Check return type annotations on public methods
                if stripped.startswith("def ") and not stripped.startswith("def _"):
                    for dt in dds_types:
                        if f"-> {dt}" in stripped or f"-> dds.{dt}" in stripped:
                            violations.append(
                                f"  {src.relative_to(ROOT)}:{i}: {stripped}"
                            )
                # Check @property methods that return DDS types
                if stripped.startswith("@property"):
                    # Next non-blank line is the def — check return annotation
                    lines = content.splitlines()
                    for j in range(i, min(i + 3, len(lines))):
                        for dt in dds_types:
                            if f"-> {dt}" in lines[j] or f"-> dds.{dt}" in lines[j]:
                                if not lines[j].strip().startswith("def _"):
                                    violations.append(
                                        f"  {src.relative_to(ROOT)}:{j + 1}: "
                                        f"{lines[j].strip()}"
                                    )
        assert (
            not violations
        ), "AP-10: DDS entity types found in public API:\n" + "\n".join(violations)


class TestPartitionQos:
    """Scenario: No publisher/subscriber partition QoS is used (AP-9)."""

    def test_no_pub_sub_partition_in_code(self):
        """No publisher-level or subscriber-level partition QoS in modules/."""
        violations = []
        for src in _get_module_source_files():
            content = src.read_text()
            for i, line in enumerate(content.splitlines(), 1):
                lower = line.lower()
                # Look for publisher/subscriber + partition patterns
                if ("publisher" in lower and "partition" in lower) or (
                    "subscriber" in lower and "partition" in lower
                ):
                    # Exclude comments and participant-level partition
                    if "participant" not in lower and not line.strip().startswith(
                        ("#", "//")
                    ):
                        violations.append(
                            f"  {src.relative_to(ROOT)}:{i}: {line.strip()}"
                        )
        assert (
            not violations
        ), "AP-9: Publisher/subscriber partition QoS found:\n" + "\n".join(violations)

    def test_no_pub_sub_partition_in_qos_xml(self):
        """No publisher/subscriber partition in QoS XML files."""
        qos_dir = INTERFACES_DIR / "qos"
        violations = []
        for xml_file in qos_dir.glob("*.xml"):
            content = xml_file.read_text()
            # Check for <partition> inside <publisher_qos> or <subscriber_qos>
            # (participant_qos partition is allowed)
            if "<publisher_qos>" in content or "<subscriber_qos>" in content:
                in_pub_sub = False
                for i, line in enumerate(content.splitlines(), 1):
                    if "<publisher_qos>" in line or "<subscriber_qos>" in line:
                        in_pub_sub = True
                    if "</publisher_qos>" in line or "</subscriber_qos>" in line:
                        in_pub_sub = False
                    if in_pub_sub and "<partition>" in line:
                        violations.append(
                            f"  {xml_file.relative_to(ROOT)}:{i}: {line.strip()}"
                        )
        assert (
            not violations
        ), "AP-9: Publisher/subscriber partition in QoS XML:\n" + "\n".join(violations)
