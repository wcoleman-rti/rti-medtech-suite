// robot_controller.cpp — Robot controller state machine implementation.

#include "robot_controller.hpp"

#include <cmath>

namespace medtech::surgical {

RobotController::RobotController(const std::string& robot_id)
    : robot_id_(robot_id)
{
    state_.robot_id = robot_id;
    state_.operational_mode = Surgery::RobotMode::IDLE;
    state_.error_state = 0;

    // Initialize joint positions — J0 pre-angled toward the operating table
    // (negative shoulder pitch = toward +Y where the table sits relative to
    // the arm's slot-0 base position).
    state_.joint_positions.resize(7, 0.0);
    state_.joint_positions[0] = -0.35;  // ~20° toward table — working posture
    state_.joint_positions[1] =  1.10;  // elbow bent, tip over operative field

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

    // Per-joint limits [min, max] in radians — matches _JOINT_LIMITS in
    // nicegui_digital_twin.py so the visualiser never needs to clip.
    static const std::array<std::pair<double, double>, 6> kJointLimits = {{
        {-1.20,  0.40},  // J0 shoulder pitch: toward table (-) / backward (+)
        { 0.20,  2.20},  // J1 elbow pitch (keeps arm above table surface)
        {-1.50,  1.50},  // J2 wrist yaw
        {-1.00,  1.00},  // J3 tool pitch
        {-0.80,  0.80},  // J4
        {-0.50,  0.50},  // J5
    }};

    auto clamp = [](double v, double lo, double hi) {
        return v < lo ? lo : (v > hi ? hi : v);
    };

    if (state_.joint_positions.size() >= 3) {
        state_.joint_positions[0] = clamp(
            state_.joint_positions[0] + last_input_.x_axis * k_scale,
            kJointLimits[0].first, kJointLimits[0].second);
        state_.joint_positions[1] = clamp(
            state_.joint_positions[1] + last_input_.y_axis * k_scale,
            kJointLimits[1].first, kJointLimits[1].second);
        state_.joint_positions[2] = clamp(
            state_.joint_positions[2] + last_input_.z_axis * k_scale,
            kJointLimits[2].first, kJointLimits[2].second);
    }
    if (state_.joint_positions.size() >= 6) {
        state_.joint_positions[3] = clamp(
            state_.joint_positions[3] + last_input_.roll * k_scale,
            kJointLimits[3].first, kJointLimits[3].second);
        state_.joint_positions[4] = clamp(
            state_.joint_positions[4] + last_input_.pitch * k_scale,
            kJointLimits[4].first, kJointLimits[4].second);
        state_.joint_positions[5] = clamp(
            state_.joint_positions[5] + last_input_.yaw * k_scale,
            kJointLimits[5].first, kJointLimits[5].second);
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
