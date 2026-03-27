// robot_service_host.hpp — Factory for the Robot Service Host.
//
// The RobotServiceHost class is defined in robot_service_host.cpp.
// This header exposes only the factory to keep DDS types out of
// headers per AP-10.

#ifndef ROBOT_SERVICE_HOST_HPP
#define ROBOT_SERVICE_HOST_HPP

#include <memory>
#include <string>

#include "medtech/logging.hpp"
#include "medtech/service.hpp"

namespace medtech::surgical {

/// Create a RobotServiceHost.  Returns a medtech::Service pointer.
/// The host manages the RobotControllerService on the Procedure domain
/// and exposes a ServiceHostControl RPC endpoint on the Orchestration
/// domain.
std::unique_ptr<medtech::Service> make_robot_service_host(
    const std::string& host_id,
    const std::string& room_id,
    const std::string& procedure_id,
    medtech::ModuleLogger& log);

}  // namespace medtech::surgical

#endif  // ROBOT_SERVICE_HOST_HPP
