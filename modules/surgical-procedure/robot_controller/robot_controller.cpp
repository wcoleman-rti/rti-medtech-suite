// robot_controller.cpp — Robot controller state machine implementation.

#include "robot_controller.hpp"

#include <cmath>

namespace medtech::surgical {

RobotController::RobotController(const std::string& robot_id)
{
    state_.robot_id = robot_id;
    state_.operational_mode = Surgery::RobotMode::IDLE;
    state_.error_state = 0;

    // Initialize joint positions to zero (7-DOF arm)
    state_.joint_positions.resize(7, 0.0);

    state_.tool_tip_position.x = 0.0;
    state_.tool_tip_position.y = 0.0;
    state_.tool_tip_position.z = 0.0;
}

void RobotController::apply_operator_input(
    const Surgery::OperatorInput& input)
{
    // If interlock is active, discard input entirely
    if (interlock_active_) {
        return;
    }

    last_input_ = input;
    update_state_from_input();
}

void RobotController::apply_robot_command(const Surgery::RobotCommand& cmd)
{
    // If interlock is active, ignore commands
    if (interlock_active_) {
        return;
    }

    // Apply command target as tool-tip position
    state_.tool_tip_position = cmd.target_position;

    // Transition to OPERATIONAL if currently IDLE
    if (state_.operational_mode == Surgery::RobotMode::IDLE) {
        state_.operational_mode = Surgery::RobotMode::OPERATIONAL;
    }
}

void RobotController::apply_safety_interlock(
    const Surgery::SafetyInterlock& interlock)
{
    interlock_active_ = interlock.interlock_active;

    if (interlock_active_) {
        // Immediately transition to EMERGENCY_STOP
        state_.operational_mode = Surgery::RobotMode::EMERGENCY_STOP;
        state_.error_state = 1;
    } else {
        // Clear interlock — transition back to IDLE (operator must
        // explicitly resume to OPERATIONAL via RobotCommand)
        if (state_.operational_mode == Surgery::RobotMode::EMERGENCY_STOP) {
            state_.operational_mode = Surgery::RobotMode::IDLE;
            state_.error_state = 0;
        }
    }
}

ControllerSnapshot RobotController::snapshot() const
{
    ControllerSnapshot snap;
    snap.state = state_;
    snap.interlock_active = interlock_active_;
    return snap;
}

void RobotController::update_state_from_input()
{
    // Simple simulation: map operator input axes to joint increments
    const double k_scale = 0.01;  // radians per unit input

    if (state_.joint_positions.size() >= 3) {
        state_.joint_positions[0] += last_input_.x_axis * k_scale;
        state_.joint_positions[1] += last_input_.y_axis * k_scale;
        state_.joint_positions[2] += last_input_.z_axis * k_scale;
    }
    if (state_.joint_positions.size() >= 6) {
        state_.joint_positions[3] += last_input_.roll * k_scale;
        state_.joint_positions[4] += last_input_.pitch * k_scale;
        state_.joint_positions[5] += last_input_.yaw * k_scale;
    }

    // Update tool tip from axes (simplified forward kinematics)
    state_.tool_tip_position.x += last_input_.x_axis * k_scale;
    state_.tool_tip_position.y += last_input_.y_axis * k_scale;
    state_.tool_tip_position.z += last_input_.z_axis * k_scale;

    // Ensure operational mode is OPERATIONAL when receiving input
    if (state_.operational_mode == Surgery::RobotMode::IDLE) {
        state_.operational_mode = Surgery::RobotMode::OPERATIONAL;
    }
}

}  // namespace medtech::surgical
