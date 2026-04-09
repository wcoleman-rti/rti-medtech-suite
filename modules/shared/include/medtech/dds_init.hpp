#ifndef MEDTECH_DDS_INIT_HPP
#define MEDTECH_DDS_INIT_HPP

// dds_init.hpp — Centralized pre-participant DDS initialization.
//
// Mirrors dds_init.py: XTypes compliance mask + type registration for
// all IDL-generated types. Must be called once per process before any
// DomainParticipant is created. Thread-safe (idempotent via std::once).

#include <mutex>

#include <rti/config/Compliance.hpp>
#include <rti/domain/PluginSupport.hpp>

#include "clinical_alerts/clinical_alerts.hpp"
#include "devices/devices.hpp"
#include "hospital/hospital.hpp"
#include "imaging/imaging.hpp"
#include "monitoring/monitoring.hpp"
#include "orchestration/orchestration.hpp"
#include "surgery/surgery.hpp"

namespace medtech {

inline void initialize_connext()
{
    static std::once_flag flag;
    std::call_once(flag, []() {
        // Step 1 — XTypes compliance: accept unknown enum values
        rti::config::compliance::set_xtypes_mask(
            rti::config::compliance::get_xtypes_mask()
            | rti::config::compliance::XTypesMask::accept_unknown_enum_value());

        // Step 2 — Register every compiled type referenced by XML <register_type>
        // Surgery module
        rti::domain::register_type<Surgery::RobotCommand>("Surgery::RobotCommand");
        rti::domain::register_type<Surgery::RobotState>("Surgery::RobotState");
        rti::domain::register_type<Surgery::SafetyInterlock>("Surgery::SafetyInterlock");
        rti::domain::register_type<Surgery::OperatorInput>("Surgery::OperatorInput");
        rti::domain::register_type<Surgery::ProcedureContext>("Surgery::ProcedureContext");
        rti::domain::register_type<Surgery::ProcedureStatus>("Surgery::ProcedureStatus");
        rti::domain::register_type<Surgery::RobotArmAssignment>("Surgery::RobotArmAssignment");

        // Monitoring module
        rti::domain::register_type<Monitoring::PatientVitals>("Monitoring::PatientVitals");
        rti::domain::register_type<Monitoring::WaveformData>("Monitoring::WaveformData");
        rti::domain::register_type<Monitoring::AlarmMessage>("Monitoring::AlarmMessage");

        // Imaging module
        rti::domain::register_type<Imaging::CameraFrame>("Imaging::CameraFrame");
        rti::domain::register_type<Imaging::CameraConfig>("Imaging::CameraConfig");

        // Devices module
        rti::domain::register_type<Devices::DeviceTelemetry>("Devices::DeviceTelemetry");

        // ClinicalAlerts module
        rti::domain::register_type<ClinicalAlerts::ClinicalAlert>("ClinicalAlerts::ClinicalAlert");
        rti::domain::register_type<ClinicalAlerts::RiskScore>("ClinicalAlerts::RiskScore");

        // Hospital module
        rti::domain::register_type<Hospital::ResourceAvailability>("Hospital::ResourceAvailability");

        // Orchestration module
        rti::domain::register_type<Orchestration::ServiceCatalog>("Orchestration::ServiceCatalog");
        rti::domain::register_type<Orchestration::ServiceStatus>("Orchestration::ServiceStatus");
    });
}

}  // namespace medtech

#endif  // MEDTECH_DDS_INIT_HPP
