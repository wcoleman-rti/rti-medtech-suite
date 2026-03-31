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
    const std::string& procedure_id,
    medtech::ModuleLogger& log)
{
    medtech::ServiceRegistryMap registry;
    registry["RobotControllerService"] = medtech::ServiceRegistration{
        .factory = [room_id, procedure_id, &log](
            const Orchestration::ServiceRequest& req) {
            return make_robot_controller_service(
                req.service_id, room_id, procedure_id, log);
        },
        .display_name = "Robot Controller",
        .properties = {},
    };

    return medtech::make_service_host<1>(
        host_id, "RobotServiceHost", std::move(registry), log);
}

}  // namespace medtech::surgical

#endif  // ROBOT_SERVICE_HOST_HPP
