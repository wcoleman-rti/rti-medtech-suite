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
        from medtech.dds import initialize_connext

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
        from medtech.dds import initialize_connext

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
        from medtech.dds import initialize_connext

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

    def test_procedure_context_service_no_dds_in_public_api(self):
        """ProcedureContextService exposes no DDS entity types in its
        public interface."""
        from surgical_procedure.procedure_context_service import ProcedureContextService

        # Verify that the class has no 'context_writer' or 'status_writer'
        # public properties (D-7 fix)
        assert not hasattr(
            ProcedureContextService, "context_writer"
        ), "ProcedureContextService should not expose context_writer"
        assert not hasattr(
            ProcedureContextService, "status_writer"
        ), "ProcedureContextService should not expose status_writer"

    def test_procedure_context_service_implements_service(self):
        """ProcedureContextService implements medtech.Service (Phase 5)."""
        from surgical_procedure.procedure_context_service import ProcedureContextService

        assert hasattr(
            ProcedureContextService, "_start"
        ), "ProcedureContextService should have a _start() method"
        assert hasattr(
            ProcedureContextService, "run"
        ), "ProcedureContextService should have a run() method (Service interface)"
        assert hasattr(
            ProcedureContextService, "stop"
        ), "ProcedureContextService should have a stop() method (Service interface)"


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
            / "robot_controller_service.cpp"
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
            / "robot_controller_service.cpp"
        )
        content = cpp_path.read_text()

        # Extract destructor body by counting braces
        dtor_start = content.find("~RobotControllerService()")
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


class TestProcedureControllerProcedureControlParticipant:
    """Step 20.3 test gate: ProcedureController_ProcedureControl participant.

    Verifies that the new control-tag participant profile was added and that
    the Procedure Controller uses all three domain participants.
    """

    def test_entity_name_constants_accessible(self):
        """Entity name constants for ProcedureController_ProcedureControl
        are generated and accessible in Python."""
        import app_names

        surg = app_names.MedtechEntityNames.SurgicalParticipants
        assert surg.PROCEDURE_CONTROLLER_PROCEDURE_CONTROL == (
            "SurgicalParticipants::ProcedureController_ProcedureControl"
        )
        assert surg.CTRL_ROBOT_ARM_ASSIGNMENT_READER == (
            "ProcedureControlSubscriber::RobotArmAssignmentReader"
        )

    def test_participant_created_from_config(self):
        """ProcedureController_ProcedureControl can be created from XML config
        and its RobotArmAssignmentReader is accessible."""
        import app_names
        from medtech.dds import initialize_connext

        initialize_connext()
        surg = app_names.MedtechEntityNames.SurgicalParticipants
        provider = dds.QosProvider.default

        participant = provider.create_participant_from_config(
            surg.PROCEDURE_CONTROLLER_PROCEDURE_CONTROL
        )
        assert (
            participant is not None
        ), f"Failed to create participant {surg.PROCEDURE_CONTROLLER_PROCEDURE_CONTROL}"

        qos = participant.qos
        qos.partition.name = ["procedure"]
        participant.qos = qos
        participant.enable()

        reader = participant.find_datareader(surg.CTRL_ROBOT_ARM_ASSIGNMENT_READER)
        assert (
            reader is not None
        ), f"Reader {surg.CTRL_ROBOT_ARM_ASSIGNMENT_READER} not found"
        participant.close()

    def test_control_tag_not_visible_to_clinical_tag(self):
        """A control-tag participant does not discover clinical-tag publishers.

        Domain tag isolation: participants with different domain tags on the
        same domain ID are invisible to each other.
        """
        import app_names
        from medtech.dds import initialize_connext

        initialize_connext()
        names = app_names.MedtechEntityNames.SurgicalParticipants
        provider = dds.QosProvider.default

        # Create a control-tag participant (subscribes RobotArmAssignment)
        ctrl = provider.create_participant_from_config(
            names.PROCEDURE_CONTROLLER_PROCEDURE_CONTROL
        )
        ctrl_qos = ctrl.qos
        ctrl_qos.partition.name = ["procedure"]
        ctrl.qos = ctrl_qos
        ctrl.enable()

        ctrl_reader = ctrl.find_datareader(names.CTRL_ROBOT_ARM_ASSIGNMENT_READER)
        assert ctrl_reader is not None
        ctrl_reader = dds.DataReader(ctrl_reader)

        # Create a clinical-tag participant (publishes PatientVitals)
        clinical = provider.create_participant_from_config(names.CLINICAL_MONITOR)
        clin_qos = clinical.qos
        clin_qos.partition.name = ["procedure"]
        clinical.qos = clin_qos
        clinical.enable()

        # Brief discovery wait — the two participants should NOT discover each
        # other because they have different domain tags.
        import time

        time.sleep(1.0)

        matched = ctrl_reader.matched_publications
        assert len(matched) == 0, (
            "control-tag subscriber must NOT discover clinical-tag publishers; "
            f"unexpectedly matched {len(matched)} publication(s)"
        )

        clinical.close()
        ctrl.close()
