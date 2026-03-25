"""Tests for app_names.idl generated Python constants.

Verifies that all entity name constants are importable and match their
expected string values from SurgicalParticipants.xml.

Tags: @consistency
"""

import app_names
import pytest

pytestmark = [pytest.mark.consistency]

names = app_names.MedtechEntityNames.SurgicalParticipants


class TestParticipantNames:
    """Verify participant configuration name constants."""

    def test_operational_pub(self):
        assert names.OPERATIONAL_PUB == "SurgicalParticipants::OperationalPub"

    def test_control_robot(self):
        assert names.CONTROL_ROBOT == "SurgicalParticipants::ControlRobot"

    def test_control_operator(self):
        assert names.CONTROL_OPERATOR == "SurgicalParticipants::ControlOperator"

    def test_clinical_monitor(self):
        assert names.CLINICAL_MONITOR == "SurgicalParticipants::ClinicalMonitor"

    def test_clinical_device_gw(self):
        assert names.CLINICAL_DEVICE_GW == "SurgicalParticipants::ClinicalDeviceGateway"

    def test_control_digital_twin(self):
        assert names.CONTROL_DIGITAL_TWIN == "SurgicalParticipants::ControlDigitalTwin"


class TestWriterNames:
    """Verify writer entity name constants."""

    def test_procedure_context_writer(self):
        assert names.PROCEDURE_CONTEXT_WRITER == "OperationalPublisher::ProcedureContextWriter"

    def test_procedure_status_writer(self):
        assert names.PROCEDURE_STATUS_WRITER == "OperationalPublisher::ProcedureStatusWriter"

    def test_camera_frame_writer(self):
        assert names.CAMERA_FRAME_WRITER == "OperationalPublisher::CameraFrameWriter"

    def test_camera_config_writer(self):
        assert names.CAMERA_CONFIG_WRITER == "OperationalPublisher::CameraConfigWriter"

    def test_robot_state_writer(self):
        assert names.ROBOT_STATE_WRITER == "RobotPublisher::RobotStateWriter"

    def test_operator_input_writer(self):
        assert names.OPERATOR_INPUT_WRITER == "OperatorPublisher::OperatorInputWriter"

    def test_robot_command_writer(self):
        assert names.ROBOT_COMMAND_WRITER == "OperatorPublisher::RobotCommandWriter"

    def test_safety_interlock_writer(self):
        assert names.SAFETY_INTERLOCK_WRITER == "OperatorPublisher::SafetyInterlockWriter"

    def test_patient_vitals_writer(self):
        assert names.PATIENT_VITALS_WRITER == "MonitorPublisher::PatientVitalsWriter"

    def test_waveform_data_writer(self):
        assert names.WAVEFORM_DATA_WRITER == "MonitorPublisher::WaveformDataWriter"

    def test_alarm_messages_writer(self):
        assert names.ALARM_MESSAGES_WRITER == "MonitorPublisher::AlarmMessagesWriter"

    def test_device_telemetry_writer(self):
        assert names.DEVICE_TELEMETRY_WRITER == "DevicePublisher::DeviceTelemetryWriter"


class TestReaderNames:
    """Verify reader entity name constants."""

    def test_robot_command_reader(self):
        assert names.ROBOT_COMMAND_READER == "RobotSubscriber::RobotCommandReader"

    def test_operator_input_reader(self):
        assert names.OPERATOR_INPUT_READER == "RobotSubscriber::OperatorInputReader"

    def test_safety_interlock_reader(self):
        assert names.SAFETY_INTERLOCK_READER == "RobotSubscriber::SafetyInterlockReader"

    def test_robot_state_reader(self):
        assert names.ROBOT_STATE_READER == "OperatorSubscriber::RobotStateReader"

    def test_procedure_context_reader(self):
        assert names.PROCEDURE_CONTEXT_READER == "OperationalSubscriber::ProcedureContextReader"

    def test_procedure_status_reader(self):
        assert names.PROCEDURE_STATUS_READER == "OperationalSubscriber::ProcedureStatusReader"

    def test_patient_vitals_reader(self):
        assert names.PATIENT_VITALS_READER == "MonitorSubscriber::PatientVitalsReader"

    def test_twin_robot_state_reader(self):
        assert names.TWIN_ROBOT_STATE_READER == "TwinSubscriber::RobotStateReader"

    def test_twin_operator_input_reader(self):
        assert names.TWIN_OPERATOR_INPUT_READER == "TwinSubscriber::OperatorInputReader"

    def test_twin_safety_interlock_reader(self):
        assert names.TWIN_SAFETY_INTERLOCK_READER == "TwinSubscriber::SafetyInterlockReader"

    def test_twin_robot_command_reader(self):
        assert names.TWIN_ROBOT_COMMAND_READER == "TwinSubscriber::RobotCommandReader"
