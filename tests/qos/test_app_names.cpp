// test_app_names.cpp — Verify generated entity name constants match expected
// values from SurgicalParticipants.xml.

#include <gtest/gtest.h>
#include "app_names/app_names.hpp"

namespace names = MedtechEntityNames::SurgicalParticipants;

// --- Participant config names ---
TEST(AppNames, OperationalPub)
{
    EXPECT_EQ(names::OPERATIONAL_PUB, "SurgicalParticipants::OperationalPub");
}

TEST(AppNames, ControlRobot)
{
    EXPECT_EQ(names::CONTROL_ROBOT, "SurgicalParticipants::ControlRobot");
}

TEST(AppNames, ControlOperator)
{
    EXPECT_EQ(names::CONTROL_OPERATOR, "SurgicalParticipants::ControlOperator");
}

TEST(AppNames, ClinicalMonitor)
{
    EXPECT_EQ(names::CLINICAL_MONITOR, "SurgicalParticipants::ClinicalMonitor");
}

TEST(AppNames, ClinicalDeviceGw)
{
    EXPECT_EQ(names::CLINICAL_DEVICE_GW, "SurgicalParticipants::ClinicalDeviceGateway");
}

TEST(AppNames, ControlDigitalTwin)
{
    EXPECT_EQ(names::CONTROL_DIGITAL_TWIN, "SurgicalParticipants::ControlDigitalTwin");
}

// --- Writer names ---
TEST(AppNames, ProcedureContextWriter)
{
    EXPECT_EQ(names::PROCEDURE_CONTEXT_WRITER, "OperationalPublisher::ProcedureContextWriter");
}

TEST(AppNames, ProcedureStatusWriter)
{
    EXPECT_EQ(names::PROCEDURE_STATUS_WRITER, "OperationalPublisher::ProcedureStatusWriter");
}

TEST(AppNames, CameraFrameWriter)
{
    EXPECT_EQ(names::CAMERA_FRAME_WRITER, "OperationalPublisher::CameraFrameWriter");
}

TEST(AppNames, CameraConfigWriter)
{
    EXPECT_EQ(names::CAMERA_CONFIG_WRITER, "OperationalPublisher::CameraConfigWriter");
}

TEST(AppNames, RobotStateWriter)
{
    EXPECT_EQ(names::ROBOT_STATE_WRITER, "RobotPublisher::RobotStateWriter");
}

TEST(AppNames, OperatorInputWriter)
{
    EXPECT_EQ(names::OPERATOR_INPUT_WRITER, "OperatorPublisher::OperatorInputWriter");
}

TEST(AppNames, RobotCommandWriter)
{
    EXPECT_EQ(names::ROBOT_COMMAND_WRITER, "OperatorPublisher::RobotCommandWriter");
}

TEST(AppNames, SafetyInterlockWriter)
{
    EXPECT_EQ(names::SAFETY_INTERLOCK_WRITER, "OperatorPublisher::SafetyInterlockWriter");
}

TEST(AppNames, PatientVitalsWriter)
{
    EXPECT_EQ(names::PATIENT_VITALS_WRITER, "MonitorPublisher::PatientVitalsWriter");
}

TEST(AppNames, WaveformDataWriter)
{
    EXPECT_EQ(names::WAVEFORM_DATA_WRITER, "MonitorPublisher::WaveformDataWriter");
}

TEST(AppNames, AlarmMessagesWriter)
{
    EXPECT_EQ(names::ALARM_MESSAGES_WRITER, "MonitorPublisher::AlarmMessagesWriter");
}

TEST(AppNames, DeviceTelemetryWriter)
{
    EXPECT_EQ(names::DEVICE_TELEMETRY_WRITER, "DevicePublisher::DeviceTelemetryWriter");
}

// --- Reader names ---
TEST(AppNames, RobotCommandReader)
{
    EXPECT_EQ(names::ROBOT_COMMAND_READER, "RobotSubscriber::RobotCommandReader");
}

TEST(AppNames, OperatorInputReader)
{
    EXPECT_EQ(names::OPERATOR_INPUT_READER, "RobotSubscriber::OperatorInputReader");
}

TEST(AppNames, SafetyInterlockReader)
{
    EXPECT_EQ(names::SAFETY_INTERLOCK_READER, "RobotSubscriber::SafetyInterlockReader");
}

TEST(AppNames, RobotStateReader)
{
    EXPECT_EQ(names::ROBOT_STATE_READER, "OperatorSubscriber::RobotStateReader");
}

TEST(AppNames, ProcedureContextReader)
{
    EXPECT_EQ(names::PROCEDURE_CONTEXT_READER, "OperationalSubscriber::ProcedureContextReader");
}

TEST(AppNames, ProcedureStatusReader)
{
    EXPECT_EQ(names::PROCEDURE_STATUS_READER, "OperationalSubscriber::ProcedureStatusReader");
}

TEST(AppNames, PatientVitalsReader)
{
    EXPECT_EQ(names::PATIENT_VITALS_READER, "MonitorSubscriber::PatientVitalsReader");
}

TEST(AppNames, TwinRobotStateReader)
{
    EXPECT_EQ(names::TWIN_ROBOT_STATE_READER, "TwinSubscriber::RobotStateReader");
}

TEST(AppNames, TwinOperatorInputReader)
{
    EXPECT_EQ(names::TWIN_OPERATOR_INPUT_READER, "TwinSubscriber::OperatorInputReader");
}

TEST(AppNames, TwinSafetyInterlockReader)
{
    EXPECT_EQ(names::TWIN_SAFETY_INTERLOCK_READER, "TwinSubscriber::SafetyInterlockReader");
}

TEST(AppNames, TwinRobotCommandReader)
{
    EXPECT_EQ(names::TWIN_ROBOT_COMMAND_READER, "TwinSubscriber::RobotCommandReader");
}
