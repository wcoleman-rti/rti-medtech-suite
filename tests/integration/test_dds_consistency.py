"""Integration tests for @consistency scenarios from spec/common-behaviors.md.

Verifies runtime DDS consistency: initialization, XML participant creation,
class encapsulation, and destructor shutdown sequence.

Tags: @integration @consistency
"""

from __future__ import annotations

from pathlib import Path

import pytest
import rti.connextdds as dds

pytestmark = [pytest.mark.integration, pytest.mark.consistency]

ROOT = Path(__file__).resolve().parents[2]


class TestSharedInitialization:
    """Scenario: All applications call shared initialization before
    participant creation."""

    def test_initialize_connext_sets_xtypes_mask(self):
        """After initialize_connext(), XTypes mask includes
        accept_unknown_enum_value."""
        from medtech_dds_init.dds_init import initialize_connext

        initialize_connext()

        mask = dds.compliance.get_xtypes_mask()
        accept_bit = dds.compliance.XTypesMask.ACCEPT_UNKNOWN_ENUM_VALUE_BIT
        assert (mask & accept_bit) == accept_bit, (
            "XTypes mask does not include accept_unknown_enum_value after "
            "initialize_connext()"
        )

    def test_initialize_connext_registers_types(self):
        """After initialize_connext(), XML participant creation succeeds,
        which requires all referenced types to be registered."""
        import app_names
        from medtech_dds_init.dds_init import initialize_connext

        initialize_connext()

        # create_participant_from_config will fail if register_idl_type
        # was not called for every <register_type> entry in the XML.
        # Success here validates that type registration is complete.
        names = app_names.MedtechEntityNames.SurgicalParticipants
        provider = dds.QosProvider.default

        # Test with ControlRobot (has writers AND readers — exercises all
        # control-tag types: RobotState, RobotCommand, SafetyInterlock,
        # OperatorInput)
        participant = provider.create_participant_from_config(names.CONTROL_ROBOT)
        assert participant is not None

        # Verify writer lookup succeeds (type binding is correct)
        writer_any = participant.find_datawriter(names.ROBOT_STATE_WRITER)
        assert writer_any is not None, (
            f"Writer {names.ROBOT_STATE_WRITER} not found — type "
            f"registration may be incomplete"
        )

        participant.close()


class TestXmlParticipantCreation:
    """Scenario: All participants are created from XML configuration."""

    def test_participant_created_from_config(self):
        """Verify that create_participant_from_config() works with the
        generated entity name constants."""
        import app_names
        from medtech_dds_init.dds_init import initialize_connext

        initialize_connext()

        names = app_names.MedtechEntityNames.SurgicalParticipants
        provider = dds.QosProvider.default

        # Create participant from XML config — this verifies the constant
        # matches a valid participant configuration
        participant = provider.create_participant_from_config(names.OPERATIONAL_PUB)
        assert participant is not None

        # Set partition and enable
        qos = participant.qos
        qos.partition.name = ["room/OR-test/procedure/proc-test"]
        participant.qos = qos
        participant.enable()

        # Verify a writer can be looked up by generated constant name
        writer_any = participant.find_datawriter(names.PROCEDURE_CONTEXT_WRITER)
        assert writer_any is not None, (
            f"Writer {names.PROCEDURE_CONTEXT_WRITER} not found in "
            f"participant {names.OPERATIONAL_PUB}"
        )

        participant.close()


class TestClassEncapsulation:
    """Scenario: Application classes encapsulate DDS entities as private
    members."""

    def test_procedure_context_publisher_no_dds_in_public_api(self):
        """ProcedureContextPublisher exposes no DDS entity types in its
        public interface. Public methods: __init__, start, publish_context,
        publish_status, procedure_id."""
        from surgical_procedure.procedure_context import ProcedureContextPublisher

        # Verify that the class has no 'context_writer' or 'status_writer'
        # public properties (D-7 fix)
        assert not hasattr(
            ProcedureContextPublisher, "context_writer"
        ), "ProcedureContextPublisher should not expose context_writer"
        assert not hasattr(
            ProcedureContextPublisher, "status_writer"
        ), "ProcedureContextPublisher should not expose status_writer"

    def test_procedure_context_publisher_has_start(self):
        """ProcedureContextPublisher.start() replaces run() (D-8 fix)."""
        from surgical_procedure.procedure_context import ProcedureContextPublisher

        assert hasattr(
            ProcedureContextPublisher, "start"
        ), "ProcedureContextPublisher should have a start() method"
        # run() should no longer exist
        assert not hasattr(ProcedureContextPublisher, "run"), (
            "ProcedureContextPublisher should not have a run() method "
            "(renamed to start())"
        )


class TestDestructorShutdownSequence:
    """Scenario: Destructor shutdown sequence is correct (C++)."""

    def test_cpp_member_declaration_order(self):
        """Verify AsyncWaitSet is declared after DDS entities in the C++
        source for correct reverse destruction order."""
        cpp_path = (
            ROOT
            / "modules"
            / "surgical-procedure"
            / "robot_controller"
            / "robot_controller_app.cpp"
        )
        content = cpp_path.read_text()

        # Find the private section member declarations
        # AsyncWaitSet must appear after all DDS entity declarations
        participant_pos = content.find("DomainParticipant participant_")
        aws_pos = content.find("AsyncWaitSet sub_aws_")
        thread_pos = content.find("std::thread timer_thread_")

        assert participant_pos < aws_pos, (
            "AsyncWaitSet must be declared after DomainParticipant "
            "(reverse destruction order)"
        )
        assert aws_pos < thread_pos, "timer_thread_ must be declared after AsyncWaitSet"

    def test_cpp_destructor_calls_stop_before_destruction(self):
        """Verify the destructor calls aws_.stop() explicitly."""
        cpp_path = (
            ROOT
            / "modules"
            / "surgical-procedure"
            / "robot_controller"
            / "robot_controller_app.cpp"
        )
        content = cpp_path.read_text()

        # Extract destructor body by counting braces
        dtor_start = content.find("~RobotControllerApp()")
        assert dtor_start != -1, "Destructor not found"
        brace_start = content.find("{", dtor_start)
        depth = 0
        dtor_body = ""
        for i in range(brace_start, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    dtor_body = content[brace_start + 1 : i]
                    break

        assert dtor_body, "Could not extract destructor body"

        # Verify running_.store(false) comes before join, which comes
        # before aws_.stop()
        assert (
            "running_.store(false" in dtor_body
        ), "Destructor must signal running_ = false"
        assert "timer_thread_.join()" in dtor_body, "Destructor must join timer thread"
        assert "sub_aws_.stop()" in dtor_body, "Destructor must call sub_aws_.stop()"

        # Verify order: running_.store before join before stop
        running_pos = dtor_body.find("running_.store(false")
        join_pos = dtor_body.find("timer_thread_.join()")
        stop_pos = dtor_body.find("sub_aws_.stop()")
        assert running_pos < join_pos < stop_pos, (
            "Destructor shutdown sequence must be: "
            "signal threads → join → aws_.stop()"
        )
