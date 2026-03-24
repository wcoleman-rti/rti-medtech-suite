"""Tests for tools/qos-checker.py — QoS compatibility pre-flight checker.

Test gate (phase-1-foundation.md Step 1.10):
- qos-checker.py runs against Step 1.3 QoS XML and reports all topic
  pairs as compatible
- A deliberately introduced QoS incompatibility causes the checker to
  report FAIL and exit 1
"""

import importlib.util
import os
import subprocess
import sys

import pytest
import rti.connextdds as dds

# Import the checker module (hyphenated filename requires importlib).
_tools_dir = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
_spec = importlib.util.spec_from_file_location(
    "qos_checker", os.path.join(_tools_dir, "qos-checker.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

check_rxo = _mod.check_rxo
check_reliability = _mod.check_reliability
check_durability = _mod.check_durability
check_deadline = _mod.check_deadline
check_ownership = _mod.check_ownership
check_liveliness = _mod.check_liveliness
check_all = _mod.check_all
find_domains_xml = _mod.find_domains_xml
parse_domain_topics = _mod.parse_domain_topics


@pytest.fixture
def provider():
    return dds.QosProvider.default


# --- RxO policy unit tests ---


class TestReliability:
    def test_both_reliable(self, provider):
        w = provider.datawriter_qos_from_profile("Patterns::State")
        r = provider.datareader_qos_from_profile("Patterns::State")
        assert check_reliability(w, r) is None

    def test_reliable_writer_besteffort_reader(self, provider):
        w = provider.datawriter_qos_from_profile("Patterns::State")
        r = provider.datareader_qos_from_profile("Patterns::Stream")
        assert check_reliability(w, r) is None

    def test_besteffort_writer_reliable_reader(self, provider):
        w = provider.datawriter_qos_from_profile("Patterns::Stream")
        r = provider.datareader_qos_from_profile("Patterns::State")
        msg = check_reliability(w, r)
        assert msg is not None
        assert "RELIABLE" in msg


class TestDurability:
    def test_same_durability(self, provider):
        w = provider.datawriter_qos_from_profile("Patterns::State")
        r = provider.datareader_qos_from_profile("Patterns::State")
        assert check_durability(w, r) is None

    def test_higher_writer(self, provider):
        w = provider.datawriter_qos_from_profile("Patterns::State")
        r = provider.datareader_qos_from_profile("Patterns::Command")
        assert check_durability(w, r) is None

    def test_lower_writer(self, provider):
        w = provider.datawriter_qos_from_profile("Patterns::Command")
        r = provider.datareader_qos_from_profile("Patterns::State")
        msg = check_durability(w, r)
        assert msg is not None
        assert "VOLATILE" in msg


class TestDeadline:
    def test_equal_deadline(self, provider):
        w = provider.set_topic_datawriter_qos(
            "Topics::ProcedureTopics", "PatientVitals"
        )
        r = provider.set_topic_datareader_qos(
            "Topics::ProcedureTopics", "PatientVitals"
        )
        assert check_deadline(w, r) is None

    def test_incompatible_deadline(self, provider):
        # Base State writer has INFINITE deadline (no deadline snippet).
        # PatientVitals reader has 2s deadline.
        w = provider.datawriter_qos_from_profile("Patterns::State")
        r = provider.set_topic_datareader_qos(
            "Topics::ProcedureTopics", "PatientVitals"
        )
        msg = check_deadline(w, r)
        assert msg is not None
        assert "exceeds" in msg


class TestOwnership:
    def test_both_shared(self, provider):
        w = provider.datawriter_qos_from_profile("Patterns::State")
        r = provider.datareader_qos_from_profile("Patterns::State")
        assert check_ownership(w, r) is None


class TestLiveliness:
    def test_same_liveliness(self, provider):
        w = provider.set_topic_datawriter_qos(
            "Topics::ProcedureTopics", "PatientVitals"
        )
        r = provider.set_topic_datareader_qos(
            "Topics::ProcedureTopics", "PatientVitals"
        )
        assert check_liveliness(w, r) is None


class TestCheckRxo:
    def test_compatible_pair(self, provider):
        w = provider.set_topic_datawriter_qos(
            "Topics::ProcedureTopics", "PatientVitals"
        )
        r = provider.set_topic_datareader_qos(
            "Topics::ProcedureTopics", "PatientVitals"
        )
        errors = check_rxo(w, r)
        assert errors == []

    def test_incompatible_pair_detects_multiple_failures(self, provider):
        """BEST_EFFORT+VOLATILE writer vs RELIABLE+TRANSIENT_LOCAL reader."""
        w = provider.datawriter_qos_from_profile("Patterns::Stream")
        r = provider.datareader_qos_from_profile("Patterns::State")
        errors = check_rxo(w, r)
        assert len(errors) >= 2
        policy_names = {e[0] for e in errors}
        assert "Reliability" in policy_names
        assert "Durability" in policy_names


# --- Domain XML parsing ---


class TestDomainParsing:
    def test_find_domains_xml(self):
        xml = find_domains_xml()
        assert xml is not None
        assert xml.endswith("domains.xml")
        assert os.path.isfile(xml)

    def test_parse_domain_topics(self):
        domains_xml = find_domains_xml()
        topics = parse_domain_topics(domains_xml)
        assert "Procedure_control" in topics
        assert "Procedure_clinical" in topics
        assert "Procedure_operational" in topics
        assert "Hospital" in topics
        assert "RobotCommand" in topics["Procedure_control"]
        assert "PatientVitals" in topics["Procedure_clinical"]
        assert "ClinicalAlert" in topics["Hospital"]

    def test_observability_domain_excluded(self):
        """Observability domain has no topics and should be absent."""
        domains_xml = find_domains_xml()
        topics = parse_domain_topics(domains_xml)
        assert "Observability" not in topics


# --- Full check integration ---


class TestFullCheck:
    def test_all_topics_compatible(self, provider):
        """All project QoS topic pairs should be RxO compatible."""
        domains_xml = find_domains_xml()
        results, pass_count, fail_count = check_all(provider, domains_xml)
        assert fail_count == 0
        assert pass_count > 0

    def test_covers_procedure_topics(self, provider):
        domains_xml = find_domains_xml()
        results, _, _ = check_all(provider, domains_xml)
        contexts = [r[0] for r in results]
        assert any("Procedure/RobotCommand" in c for c in contexts)
        assert any("Procedure/PatientVitals" in c for c in contexts)
        assert any("Procedure/CameraFrame" in c for c in contexts)
        assert any("Procedure/OperatorInput" in c for c in contexts)

    def test_covers_hospital_native_topics(self, provider):
        domains_xml = find_domains_xml()
        results, _, _ = check_all(provider, domains_xml)
        contexts = [r[0] for r in results]
        assert any("Hospital/ClinicalAlert" in c for c in contexts)
        assert any("Hospital/RiskScore" in c for c in contexts)

    def test_covers_bridged_topics(self, provider):
        domains_xml = find_domains_xml()
        results, _, _ = check_all(provider, domains_xml)
        contexts = [r[0] for r in results]
        assert any("Bridged(PatientVitals)" in c for c in contexts)
        assert any("Bridged(RobotState)" in c for c in contexts)
        assert any("Bridged(ProcedureStatus)" in c for c in contexts)


# --- CLI integration ---


class TestCLI:
    def test_exit_zero_on_compatible(self):
        result = subprocess.run(
            [sys.executable, "tools/qos-checker.py"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "compatible" in result.stdout.lower()

    def test_help(self):
        result = subprocess.run(
            [sys.executable, "tools/qos-checker.py", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_verbose_shows_qos_details(self):
        result = subprocess.run(
            [sys.executable, "tools/qos-checker.py", "--verbose"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "writer:" in result.stdout.lower()
        assert "reader:" in result.stdout.lower()
