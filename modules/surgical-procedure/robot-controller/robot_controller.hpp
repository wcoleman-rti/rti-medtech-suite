#pragma once

// robot_controller.hpp — Robot controller state machine.
//
// Pure logic, no DDS dependencies. The DDS layer (main.cpp) feeds
// inputs and reads outputs via the public API.

#include <shared_mutex>
#include <vector>

#include "surgery/surgery.hpp"

namespace medtech::surgical {

// Snapshot of the controller state, read atomically by the publisher.
struct ControllerSnapshot {
    Surgery::RobotState state{};
    bool interlock_active = false;
};

class RobotController {
public:
    explicit RobotController(const std::string& robot_id);

    // --- Input methods (called from subscriber AsyncWaitSet) ---

    // Process an incoming OperatorInput sample.
    void apply_operator_input(const Surgery::OperatorInput& input);

    // Process an incoming RobotCommand sample.
    void apply_robot_command(const Surgery::RobotCommand& cmd);

    // Process an incoming SafetyInterlock sample.
    void apply_safety_interlock(const Surgery::SafetyInterlock& interlock);

    // --- Output (called from publisher AsyncWaitSet) ---

    // Take a snapshot of the current RobotState under a read-lock.
    ControllerSnapshot snapshot() const;

    // --- Thread safety ---

    // The subscriber side calls write-locked methods.
    std::shared_mutex& mutex() { return mutex_; }

private:
    void update_state_from_input();

    mutable std::shared_mutex mutex_;

    Surgery::RobotState state_{};
    bool interlock_active_ = false;
    Surgery::OperatorInput last_input_{};
};

}  // namespace medtech::surgical
