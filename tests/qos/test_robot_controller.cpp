// test_robot_controller.cpp — Unit tests for the robot controller state
// machine. Verifies state transitions, safety interlock behavior, and input
// processing without any DDS dependency.

#include <gtest/gtest.h>
#include "robot_controller.hpp"

using namespace medtech::surgical;

class RobotControllerTest : public ::testing::Test {
protected:
    void SetUp() override
    {
        controller_ = std::make_unique<RobotController>("robot-test-001");
    }

    std::unique_ptr<RobotController> controller_;
};

TEST_F(RobotControllerTest, InitialState)
{
    auto snap = controller_->snapshot();
    EXPECT_EQ(snap.state.robot_id, "robot-test-001");
    EXPECT_EQ(snap.state.operational_mode, Surgery::RobotMode::IDLE);
    EXPECT_EQ(snap.state.error_state, 0);
    EXPECT_EQ(snap.state.joint_positions.size(), 7u);
    EXPECT_FALSE(snap.interlock_active);
}

TEST_F(RobotControllerTest, SafetyInterlockHaltsRobot)
{
    // First make it operational via a command
    Surgery::RobotCommand cmd;
    cmd.robot_id = "robot-test-001";
    cmd.command_id = 1;
    cmd.target_position.x = 1.0;
    cmd.target_position.y = 2.0;
    cmd.target_position.z = 3.0;
    controller_->apply_robot_command(cmd);

    auto snap = controller_->snapshot();
    EXPECT_EQ(snap.state.operational_mode, Surgery::RobotMode::OPERATIONAL);

    // Activate interlock
    Surgery::SafetyInterlock interlock;
    interlock.robot_id = "robot-test-001";
    interlock.interlock_active = true;
    interlock.reason = "Test interlock";
    controller_->apply_safety_interlock(interlock);

    snap = controller_->snapshot();
    EXPECT_EQ(snap.state.operational_mode, Surgery::RobotMode::EMERGENCY_STOP);
    EXPECT_TRUE(snap.interlock_active);
    EXPECT_EQ(snap.state.error_state, 1);
}

TEST_F(RobotControllerTest, InterlockClearResumesToIdle)
{
    // Activate interlock
    Surgery::SafetyInterlock interlock;
    interlock.robot_id = "robot-test-001";
    interlock.interlock_active = true;
    interlock.reason = "Test";
    controller_->apply_safety_interlock(interlock);

    EXPECT_EQ(controller_->snapshot().state.operational_mode,
              Surgery::RobotMode::EMERGENCY_STOP);

    // Clear interlock
    interlock.interlock_active = false;
    controller_->apply_safety_interlock(interlock);

    auto snap = controller_->snapshot();
    EXPECT_EQ(snap.state.operational_mode, Surgery::RobotMode::IDLE);
    EXPECT_FALSE(snap.interlock_active);
    EXPECT_EQ(snap.state.error_state, 0);
}

TEST_F(RobotControllerTest, OperatorInputDiscardedDuringInterlock)
{
    // Activate interlock
    Surgery::SafetyInterlock interlock;
    interlock.robot_id = "robot-test-001";
    interlock.interlock_active = true;
    interlock.reason = "Blocked";
    controller_->apply_safety_interlock(interlock);

    // Joint positions before input
    auto before = controller_->snapshot().state.joint_positions;

    // Send operator input — should be discarded
    Surgery::OperatorInput input;
    input.operator_id = "op-001";
    input.robot_id = "robot-test-001";
    input.x_axis = 100.0;
    input.y_axis = 100.0;
    input.z_axis = 100.0;
    controller_->apply_operator_input(input);

    // Verify joints did not change
    auto after = controller_->snapshot().state.joint_positions;
    EXPECT_EQ(before, after);
    EXPECT_EQ(controller_->snapshot().state.operational_mode,
              Surgery::RobotMode::EMERGENCY_STOP);
}

TEST_F(RobotControllerTest, RobotCommandAppliesTargetPosition)
{
    Surgery::RobotCommand cmd;
    cmd.robot_id = "robot-test-001";
    cmd.command_id = 42;
    cmd.target_position.x = 1.5;
    cmd.target_position.y = 2.5;
    cmd.target_position.z = 3.5;
    controller_->apply_robot_command(cmd);

    auto snap = controller_->snapshot();
    EXPECT_EQ(snap.state.operational_mode, Surgery::RobotMode::OPERATIONAL);
    EXPECT_DOUBLE_EQ(snap.state.tool_tip_position.x, 1.5);
    EXPECT_DOUBLE_EQ(snap.state.tool_tip_position.y, 2.5);
    EXPECT_DOUBLE_EQ(snap.state.tool_tip_position.z, 3.5);
}

TEST_F(RobotControllerTest, RobotCommandIgnoredDuringInterlock)
{
    // Activate interlock
    Surgery::SafetyInterlock interlock;
    interlock.robot_id = "robot-test-001";
    interlock.interlock_active = true;
    interlock.reason = "Blocked";
    controller_->apply_safety_interlock(interlock);

    auto before = controller_->snapshot().state.tool_tip_position;

    // Send command — should be ignored
    Surgery::RobotCommand cmd;
    cmd.robot_id = "robot-test-001";
    cmd.command_id = 1;
    cmd.target_position.x = 99.0;
    controller_->apply_robot_command(cmd);

    auto after = controller_->snapshot().state.tool_tip_position;
    EXPECT_DOUBLE_EQ(before.x, after.x);
}

TEST_F(RobotControllerTest, OperatorInputMovesJoints)
{
    Surgery::OperatorInput input;
    input.operator_id = "op-001";
    input.robot_id = "robot-test-001";
    input.x_axis = 1.0;
    input.y_axis = 2.0;
    input.z_axis = 3.0;
    input.roll = 0.0;
    input.pitch = 0.0;
    input.yaw = 0.0;
    controller_->apply_operator_input(input);

    auto snap = controller_->snapshot();
    // Input transitions to OPERATIONAL
    EXPECT_EQ(snap.state.operational_mode, Surgery::RobotMode::OPERATIONAL);
    // First 3 joints should have changed
    EXPECT_NE(snap.state.joint_positions[0], 0.0);
    EXPECT_NE(snap.state.joint_positions[1], 0.0);
    EXPECT_NE(snap.state.joint_positions[2], 0.0);
}

TEST_F(RobotControllerTest, ReliableCommandOrdering)
{
    // Send multiple commands — each should update the target position
    for (int i = 1; i <= 5; ++i) {
        Surgery::RobotCommand cmd;
        cmd.robot_id = "robot-test-001";
        cmd.command_id = i;
        cmd.target_position.x = static_cast<double>(i);
        cmd.target_position.y = static_cast<double>(i * 10);
        cmd.target_position.z = 0.0;
        controller_->apply_robot_command(cmd);
    }

    // Final state should reflect the last command
    auto snap = controller_->snapshot();
    EXPECT_DOUBLE_EQ(snap.state.tool_tip_position.x, 5.0);
    EXPECT_DOUBLE_EQ(snap.state.tool_tip_position.y, 50.0);
}
