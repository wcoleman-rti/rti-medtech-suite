// robot_controller_service.hpp — Factory for the robot controller service.
//
// The RobotControllerService class is defined in robot_controller_service.cpp.
// This header exposes only the factory to keep DDS types out of headers
// per AP-10.

#ifndef ROBOT_CONTROLLER_SERVICE_HPP
#define ROBOT_CONTROLLER_SERVICE_HPP

#include <memory>
#include <string>

#include "medtech/logging.hpp"
#include "medtech/service.hpp"

namespace medtech::surgical {

/// Create a RobotControllerService.  Returns a medtech::Service pointer.
std::unique_ptr<medtech::Service> make_robot_controller_service(
    const std::string& robot_id,
    const std::string& room_id,
    const std::string& procedure_id,
    medtech::ModuleLogger& log);

}  // namespace medtech::surgical

#endif  // ROBOT_CONTROLLER_SERVICE_HPP
