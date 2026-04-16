// robot_service_host.hpp — Robot Service Host factory (header-only).
//
// Registers the RobotControllerService and delegates to the generic
// medtech::ServiceHost via make_service_host<1>().
// All orchestration infrastructure lives in the shared service_host
// library — this file is the only robot-specific code.

#ifndef ROBOT_SERVICE_HOST_HPP
#define ROBOT_SERVICE_HOST_HPP

#include <memory>
#include <string>

#include "medtech/logging.hpp"
#include "medtech/service.hpp"
#include "medtech/service_host.hpp"
#include "robot_controller_service.hpp"

namespace medtech::surgical {

/// Create a RobotServiceHost.  Returns a medtech::Service pointer.
/// The host manages the RobotControllerService on the Procedure domain
/// and exposes a ServiceHostControl RPC endpoint on the Orchestration
/// domain.
inline std::unique_ptr<medtech::Service> make_robot_service_host(
    const std::string& host_id,
    const std::string& room_id,
    const std::string& robot_id,
    medtech::ModuleLogger& log)
{
    medtech::ServiceRegistryMap registry;
    registry["RobotControllerService"] = medtech::ServiceRegistration{
        .factory = [robot_id, room_id, &log](
            const Orchestration::ServiceRequest& req) {
            // Extract orchestrated context from request properties.
            // room_id falls back to the host's launch-time value;
            // procedure_id must come from the orchestrator.
            std::string eff_room = room_id;
            std::string eff_proc;
            std::string table_pos;
            for (const auto& prop : req.properties) {
                const std::string pname(prop.name);
                if (pname == "room_id") {
                    eff_room = std::string(prop.value);
                } else if (pname == "procedure_id") {
                    eff_proc = std::string(prop.value);
                } else if (pname == "table_position") {
                    table_pos = std::string(prop.value);
                }
            }
            return make_robot_controller_service(
                robot_id, eff_room, eff_proc, table_pos, log);
        },
        .display_name = "Robot Controller",
        .properties = {},
    };

    return medtech::make_service_host<1>(
        host_id, "RobotServiceHost", std::move(registry), log);
}

}  // namespace medtech::surgical

#endif  // ROBOT_SERVICE_HOST_HPP
