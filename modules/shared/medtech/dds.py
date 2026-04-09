"""DDS initialization for the surgical procedure module.

Performs the mandatory pre-participant initialization sequence defined in
vision/data-model.md: XTypes compliance mask, type registration, and
participant creation from XML via the default QosProvider.

Participants are created using create_participant_from_config() which reads
named participant definitions from SurgicalParticipants.xml. DataWriters
and DataReaders are then looked up by entity name using find_datawriter()
and find_datareader().
"""

from __future__ import annotations

import clinical_alerts
import common  # noqa: F401  — generated; registers Common types
import devices
import hospital
import imaging
import monitoring
import orchestration
import rti.connextdds as dds
import surgery

_initialized = False


def initialize_connext() -> None:
    """Run the mandatory pre-participant initialization sequence.

    Must be called once per process before any DomainParticipant is created.
    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    # Step 1 — XTypes compliance: accept unknown enum values
    dds.compliance.set_xtypes_mask(
        dds.compliance.get_xtypes_mask()
        | dds.compliance.XTypesMask.ACCEPT_UNKNOWN_ENUM_VALUE_BIT
    )

    # Step 2 — Register every compiled type referenced by XML <register_type>
    dds.DomainParticipant.register_idl_type(
        surgery.Surgery.RobotCommand, "Surgery::RobotCommand"
    )
    dds.DomainParticipant.register_idl_type(
        surgery.Surgery.RobotState, "Surgery::RobotState"
    )
    dds.DomainParticipant.register_idl_type(
        surgery.Surgery.SafetyInterlock, "Surgery::SafetyInterlock"
    )
    dds.DomainParticipant.register_idl_type(
        surgery.Surgery.OperatorInput, "Surgery::OperatorInput"
    )
    dds.DomainParticipant.register_idl_type(
        surgery.Surgery.ProcedureContext, "Surgery::ProcedureContext"
    )
    dds.DomainParticipant.register_idl_type(
        surgery.Surgery.ProcedureStatus, "Surgery::ProcedureStatus"
    )
    dds.DomainParticipant.register_idl_type(
        surgery.Surgery.RobotArmAssignment, "Surgery::RobotArmAssignment"
    )
    dds.DomainParticipant.register_idl_type(
        monitoring.Monitoring.PatientVitals, "Monitoring::PatientVitals"
    )
    dds.DomainParticipant.register_idl_type(
        monitoring.Monitoring.WaveformData, "Monitoring::WaveformData"
    )
    dds.DomainParticipant.register_idl_type(
        monitoring.Monitoring.AlarmMessage, "Monitoring::AlarmMessage"
    )
    dds.DomainParticipant.register_idl_type(
        imaging.Imaging.CameraFrame, "Imaging::CameraFrame"
    )
    dds.DomainParticipant.register_idl_type(
        imaging.Imaging.CameraConfig, "Imaging::CameraConfig"
    )
    dds.DomainParticipant.register_idl_type(
        devices.Devices.DeviceTelemetry, "Devices::DeviceTelemetry"
    )

    # Orchestration module
    dds.DomainParticipant.register_idl_type(
        orchestration.Orchestration.ServiceCatalog, "Orchestration::ServiceCatalog"
    )
    dds.DomainParticipant.register_idl_type(
        orchestration.Orchestration.ServiceStatus, "Orchestration::ServiceStatus"
    )

    # Hospital module
    dds.DomainParticipant.register_idl_type(
        clinical_alerts.ClinicalAlerts.ClinicalAlert, "ClinicalAlerts::ClinicalAlert"
    )
    dds.DomainParticipant.register_idl_type(
        clinical_alerts.ClinicalAlerts.RiskScore, "ClinicalAlerts::RiskScore"
    )
    dds.DomainParticipant.register_idl_type(
        hospital.Hospital.ResourceAvailability, "Hospital::ResourceAvailability"
    )
