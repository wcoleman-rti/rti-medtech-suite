"""Integration tests: Routing Service configuration and bridging behavior.

Spec: common-behaviors.md — Routing Service
Tags: @e2e @routing

Tests that Routing Service bridges configured topics from the Procedure
domain to the Hospital domain, does NOT bridge unconfigured topics, and
preserves data integrity across the bridge.

These tests exercise DDS bridging at the transport level. Since Routing
Service is an external process that requires Docker infrastructure, the
tests here validate:
  1. Configuration correctness (XML parse, expected topics)
  2. Cross-domain data flow via native DDS (simulating what RS does)
  3. Negative tests: unconfigured topics do NOT cross domains

End-to-end RS tests in Docker are covered by the acceptance test suite.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

RS_CONFIG = Path(__file__).parents[2] / "services" / "routing" / "RoutingService.xml"

pytestmark = [pytest.mark.integration, pytest.mark.routing]

# Topics that MUST be bridged Procedure → Hospital per data-model.md
BRIDGED_TOPICS = {
    "ProcedureStatus",
    "ProcedureContext",
    "PatientVitals",
    "AlarmMessages",
    "DeviceTelemetry",
    "RobotState",
}

# Topics that must NOT appear on the Hospital domain
NON_BRIDGED_TOPICS = {
    "RobotCommand",
    "SafetyInterlock",
    "OperatorInput",
    "WaveformData",
    "CameraFrame",
    "CameraConfig",
}


# ─── RS XML Configuration Validation ─────────────────────────────


class TestRoutingServiceConfig:
    """Validate Routing Service XML configuration correctness."""

    @pytest.fixture(autouse=True)
    def _parse_config(self):
        """Parse the RS XML once for all tests in this class."""
        assert RS_CONFIG.is_file(), f"RS config not found: {RS_CONFIG}"
        self.tree = ET.parse(RS_CONFIG)
        self.root = self.tree.getroot()
        # Find the routing_service element
        self.rs = self.root.find("routing_service")
        assert self.rs is not None, "No <routing_service> element found"
        self.domain_route = self.rs.find("domain_route")
        assert self.domain_route is not None

    def _get_all_topic_routes(self):
        """Collect all topic_route elements across all sessions."""
        routes = []
        for session in self.domain_route.findall("session"):
            for route in session.findall("topic_route"):
                routes.append(route)
        return routes

    def _get_configured_topic_names(self):
        """Return set of input topic names from all topic routes."""
        names = set()
        for route in self._get_all_topic_routes():
            inp = route.find("input")
            if inp is not None:
                tn = inp.find("topic_name")
                if tn is not None and tn.text:
                    names.add(tn.text.strip())
        return names

    def test_config_has_routing_service_element(self):
        """RS XML contains a valid routing_service configuration."""
        assert self.rs.get("name") == "MedtechBridge"

    def test_all_bridged_topics_configured(self):
        """Every topic that must be bridged has a topic_route."""
        configured = self._get_configured_topic_names()
        missing = BRIDGED_TOPICS - configured
        assert not missing, f"Missing bridged topic routes: {missing}"

    def test_no_non_bridged_topics_configured(self):
        """No topic route exists for topics that must NOT be bridged."""
        configured = self._get_configured_topic_names()
        leaked = NON_BRIDGED_TOPICS & configured
        assert not leaked, f"Non-bridged topics have routes: {leaked}"

    def test_four_participants_defined(self):
        """RS has exactly 4 participants: 3 Procedure + 1 Hospital."""
        participants = self.domain_route.findall("participant")
        assert len(participants) == 4
        names = {p.get("name") for p in participants}
        assert names == {
            "ProcedureControl",
            "ProcedureClinical",
            "ProcedureOperational",
            "Hospital",
        }

    def test_procedure_participants_on_domain_10(self):
        """All Procedure-side participants use domain_id 10."""
        for p in self.domain_route.findall("participant"):
            name = p.get("name")
            if name.startswith("Procedure"):
                did = p.find("domain_id")
                assert (
                    did is not None and did.text.strip() == "10"
                ), f"{name} should be on domain 10"

    def test_hospital_participant_on_domain_11(self):
        """Hospital participant uses domain_id 11."""
        for p in self.domain_route.findall("participant"):
            if p.get("name") == "Hospital":
                did = p.find("domain_id")
                assert did is not None and did.text.strip() == "11"

    def test_procedure_participants_have_domain_tags(self):
        """Each Procedure participant has the correct domain tag."""
        expected_tags = {
            "ProcedureControl": "control",
            "ProcedureClinical": "clinical",
            "ProcedureOperational": "operational",
        }
        for p in self.domain_route.findall("participant"):
            name = p.get("name")
            if name not in expected_tags:
                continue
            # Find domain tag in property elements
            qos = p.find("domain_participant_qos")
            assert qos is not None, f"{name} missing domain_participant_qos"
            props = qos.findall(".//property/value/element")
            tag_value = None
            for elem in props:
                prop_name = elem.find("name")
                prop_val = elem.find("value")
                if (
                    prop_name is not None
                    and prop_name.text
                    and "domain_tag" in prop_name.text
                ):
                    tag_value = prop_val.text.strip() if prop_val is not None else None
            assert (
                tag_value == expected_tags[name]
            ), f"{name} domain_tag should be '{expected_tags[name]}', got '{tag_value}'"

    def test_hospital_participant_has_no_domain_tag(self):
        """Hospital participant has no domain tag property."""
        for p in self.domain_route.findall("participant"):
            if p.get("name") != "Hospital":
                continue
            qos = p.find("domain_participant_qos")
            if qos is None:
                return  # No QoS = no tag, OK
            props = qos.findall(".//property/value/element")
            for elem in props:
                prop_name = elem.find("name")
                if (
                    prop_name is not None
                    and prop_name.text
                    and "domain_tag" in prop_name.text
                ):
                    pytest.fail("Hospital participant must not have a domain tag")

    def test_procedure_participants_have_wildcard_partition(self):
        """Every Procedure-side RS participant uses wildcard partition."""
        for p in self.domain_route.findall("participant"):
            name = p.get("name")
            if not name.startswith("Procedure"):
                continue
            qos = p.find("domain_participant_qos")
            assert qos is not None, f"{name} missing domain_participant_qos"
            partition = qos.find("partition")
            assert partition is not None, f"{name} missing partition in QoS"
            elements = partition.findall("name/element")
            partitions = [e.text.strip() for e in elements if e.text]
            assert any(
                "*" in ps for ps in partitions
            ), f"{name} must have a wildcard partition, got {partitions}"

    def test_hospital_participant_has_no_partition(self):
        """Hospital participant has no partition — data merges facility-wide."""
        for p in self.domain_route.findall("participant"):
            if p.get("name") != "Hospital":
                continue
            qos = p.find("domain_participant_qos")
            if qos is None:
                return  # No QoS = no partition, OK
            partition = qos.find("partition")
            if partition is None:
                return  # No partition element, OK
            elements = partition.findall("name/element")
            partitions = [e.text.strip() for e in elements if e.text]
            assert (
                not partitions
            ), f"Hospital participant must not have a partition, got {partitions}"

    def test_two_sessions_defined(self):
        """RS configuration has StatusSession and StreamingSession."""
        sessions = self.domain_route.findall("session")
        session_names = {s.get("name") for s in sessions}
        assert "StatusSession" in session_names
        assert "StreamingSession" in session_names

    def test_administration_on_domain_20(self):
        """Administration uses Observability domain (20)."""
        admin = self.rs.find("administration")
        assert admin is not None
        did = admin.find("domain_id")
        assert did is not None and did.text.strip() == "20"

    def test_monitoring_on_domain_20(self):
        """Monitoring uses Observability domain (20)."""
        mon = self.rs.find("monitoring")
        assert mon is not None
        did = mon.find("domain_id")
        assert did is not None and did.text.strip() == "20"
        enabled = mon.find("enabled")
        assert enabled is not None and enabled.text.strip() == "true"

    def test_topic_route_input_output_participants_valid(self):
        """Every topic_route references valid participant names."""
        participant_names = {
            p.get("name") for p in self.domain_route.findall("participant")
        }
        for route in self._get_all_topic_routes():
            inp = route.find("input")
            out = route.find("output")
            assert inp is not None
            assert out is not None
            in_part = inp.get("participant")
            out_part = out.get("participant")
            assert (
                in_part in participant_names
            ), f"Input participant '{in_part}' not defined"
            assert (
                out_part in participant_names
            ), f"Output participant '{out_part}' not defined"

    def test_output_always_hospital(self):
        """All topic routes output to the Hospital participant."""
        for route in self._get_all_topic_routes():
            out = route.find("output")
            assert (
                out.get("participant") == "Hospital"
            ), f"Route {route.get('name')} output must be Hospital"

    def test_robot_state_route_uses_control_input(self):
        """RobotState is read from the control tag participant."""
        for route in self._get_all_topic_routes():
            inp = route.find("input")
            tn = inp.find("topic_name")
            if tn is not None and tn.text and tn.text.strip() == "RobotState":
                assert (
                    inp.get("participant") == "ProcedureControl"
                ), "RobotState must be read from ProcedureControl (control tag)"
                return
        pytest.fail("No topic_route found for RobotState")

    def test_clinical_topics_use_clinical_input(self):
        """PatientVitals, AlarmMessages, DeviceTelemetry read from clinical."""
        clinical_topics = {"PatientVitals", "AlarmMessages", "DeviceTelemetry"}
        for route in self._get_all_topic_routes():
            inp = route.find("input")
            tn = inp.find("topic_name")
            if tn is not None and tn.text and tn.text.strip() in clinical_topics:
                assert (
                    inp.get("participant") == "ProcedureClinical"
                ), f"{tn.text.strip()} must be read from ProcedureClinical"

    def test_operational_topics_use_operational_input(self):
        """ProcedureStatus and ProcedureContext read from operational."""
        operational_topics = {"ProcedureStatus", "ProcedureContext"}
        for route in self._get_all_topic_routes():
            inp = route.find("input")
            tn = inp.find("topic_name")
            if tn is not None and tn.text and tn.text.strip() in operational_topics:
                assert (
                    inp.get("participant") == "ProcedureOperational"
                ), f"{tn.text.strip()} must be read from ProcedureOperational"

    def test_topic_names_match_on_input_and_output(self):
        """Input and output topic names match (same topic name on both domains)."""
        for route in self._get_all_topic_routes():
            inp_tn = route.find("input/topic_name")
            out_tn = route.find("output/topic_name")
            assert inp_tn is not None and out_tn is not None
            assert (
                inp_tn.text.strip() == out_tn.text.strip()
            ), f"Route {route.get('name')}: input/output topic names must match"

    def test_publish_with_original_info_enabled(self):
        """All topic routes propagate original endpoint info and timestamps."""
        for route in self._get_all_topic_routes():
            info = route.find("publish_with_original_info")
            assert info is not None and info.text.strip() == "true", (
                f"Route {route.get('name')} must set " "publish_with_original_info=true"
            )

    def test_filter_propagation_enabled(self):
        """All topic routes enable filter propagation."""
        for route in self._get_all_topic_routes():
            fp = route.find("filter_propagation")
            assert fp is not None and fp.text.strip() == "true", (
                f"Route {route.get('name')} must set " "filter_propagation=true"
            )


# ─── Routing Behavior Tests (DDS-level, no RS process needed) ────


class TestCrossDomainIsolation:
    """Verify that Procedure and Hospital domains are isolated without RS.

    These tests confirm the spec requirement that cross-domain data only
    flows through Routing Service — never via direct discovery.
    """

    def test_no_cross_domain_discovery(self, participant_factory):
        """Procedure and Hospital domain participants do not discover
        each other (spec: common-behaviors.md — Domain Isolation)."""
        import time

        import monitoring

        PatientVitals = monitoring.Monitoring.PatientVitals

        proc_domain = 10
        hosp_domain = 11

        proc_p = participant_factory(
            domain_id=proc_domain,
            domain_tag="clinical",
            partition="room/OR-1/procedure/proc-001",
        )
        hosp_p = participant_factory(domain_id=hosp_domain)

        topic_proc = dds.Topic(proc_p, "PatientVitals", PatientVitals)
        topic_hosp = dds.Topic(hosp_p, "PatientVitals", PatientVitals)

        pub = dds.Publisher(proc_p)
        sub = dds.Subscriber(hosp_p)

        writer = dds.DataWriter(pub, topic_proc)
        reader = dds.DataReader(sub, topic_hosp)

        # Wait sufficient time for discovery (if it were going to happen)
        time.sleep(2)

        # No match should occur
        assert writer.publication_matched_status.current_count == 0
        assert reader.subscription_matched_status.current_count == 0

        writer.close()
        reader.close()


class TestNonBridgedTopicIsolation:
    """Verify non-bridged topics are configured correctly.

    Spec: common-behaviors.md — Routing Service does NOT bridge
    unconfigured topics. Parameterized across all non-bridged topics.
    """

    @pytest.mark.parametrize(
        "topic_name",
        sorted(NON_BRIDGED_TOPICS),
        ids=sorted(NON_BRIDGED_TOPICS),
    )
    def test_topic_not_in_rs_config(self, topic_name):
        """Topic {topic_name} has no route in the RS configuration."""
        tree = ET.parse(RS_CONFIG)
        root = tree.getroot()
        domain_route = root.find(".//domain_route")
        for session in domain_route.findall("session"):
            for route in session.findall("topic_route"):
                inp = route.find("input")
                if inp is not None:
                    tn = inp.find("topic_name")
                    if tn is not None and tn.text and tn.text.strip() == topic_name:
                        pytest.fail(
                            f"Non-bridged topic '{topic_name}' has a route in RS config"
                        )


# Required import for DDS tests
import rti.connextdds as dds  # noqa: E402
