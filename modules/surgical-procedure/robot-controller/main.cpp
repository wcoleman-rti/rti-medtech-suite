// main.cpp — Robot controller DDS application.
//
// Creates a ControlRobot participant from XML config, sets up dual
// AsyncWaitSet instances (publisher + subscriber), and runs the 100 Hz
// robot state publisher alongside input readers.
//
// Environment variables:
//   PARTITION        — DDS participant partition (e.g., "room/OR-3/procedure/proc-001")
//   MEDTECH_APP_NAME — Monitoring Library 2.0 application name
//   ROBOT_ID         — Robot entity ID (default: "robot-001")
//   NDDS_QOS_PROFILES — QoS XML files (set by setup.bash)

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <shared_mutex>
#include <string>
#include <thread>

#include <dds/dds.hpp>
#include <rti/core/cond/AsyncWaitSet.hpp>
#include <rti/domain/find.hpp>
#include <rti/pub/findImpl.hpp>
#include <rti/sub/findImpl.hpp>
#include <rti/domain/PluginSupport.hpp>

#include "surgery/surgery.hpp"
#include "medtech/logging.hpp"
#include "robot_controller.hpp"

namespace {

std::atomic<bool> g_shutdown_requested{false};

void signal_handler(int /*sig*/)
{
    g_shutdown_requested.store(true);
}

std::string env_or(const char* name, const char* fallback)
{
    const char* val = std::getenv(name);
    return (val != nullptr) ? std::string(val) : std::string(fallback);
}

}  // anonymous namespace

int main()
{
    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    auto log = medtech::init_logging(medtech::ModuleName::SurgicalProcedure);

    try {
        const std::string robot_id = env_or("ROBOT_ID", "robot-001");
        const std::string partition = env_or("PARTITION", "");

        // --- Register compiled types for XML Application Creation ---
        rti::domain::register_type<Surgery::RobotState>("Surgery::RobotState");
        rti::domain::register_type<Surgery::RobotCommand>("Surgery::RobotCommand");
        rti::domain::register_type<Surgery::SafetyInterlock>(
            "Surgery::SafetyInterlock");
        rti::domain::register_type<Surgery::OperatorInput>(
            "Surgery::OperatorInput");

        // --- Create participant from XML config ---
        auto provider = dds::core::QosProvider::Default();
        auto participant = provider.extensions().create_participant_from_config(
            "SurgicalParticipants::ControlRobot");

        // Set participant-level partition from runtime context.
        // Partition is context-dependent startup configuration (room/procedure),
        // so it is set in code rather than in XML.
        if (!partition.empty()) {
            auto dp_qos = participant.qos();
            dp_qos << dds::core::policy::Partition(partition);
            participant.qos(dp_qos);
        }

        log.notice("Participant created: SurgicalParticipants::ControlRobot");

        // --- Look up typed writers and readers ---
        auto state_writer =
            rti::pub::find_datawriter_by_name<
                dds::pub::DataWriter<Surgery::RobotState>>(
                participant, "RobotPublisher::RobotStateWriter");

        auto interlock_reader =
            rti::sub::find_datareader_by_name<
                dds::sub::DataReader<Surgery::SafetyInterlock>>(
                participant, "RobotSubscriber::SafetyInterlockReader");

        auto command_reader =
            rti::sub::find_datareader_by_name<
                dds::sub::DataReader<Surgery::RobotCommand>>(
                participant, "RobotSubscriber::RobotCommandReader");

        auto input_reader =
            rti::sub::find_datareader_by_name<
                dds::sub::DataReader<Surgery::OperatorInput>>(
                participant, "RobotSubscriber::OperatorInputReader");

        if (state_writer == dds::core::null
            || interlock_reader == dds::core::null
            || command_reader == dds::core::null
            || input_reader == dds::core::null) {
            log.error("Failed to find one or more named DDS entities");
            return 1;
        }

        log.notice("All DDS entities found");

        // --- Robot controller state machine ---
        medtech::surgical::RobotController controller(robot_id);

        // --- Publisher AsyncWaitSet (100 Hz RobotState output) ---
        rti::core::cond::AsyncWaitSet pub_aws;

        dds::core::cond::GuardCondition publish_tick;
        publish_tick.handler([&]() {
            // Read shared state under read-lock
            medtech::surgical::ControllerSnapshot snap;
            {
                std::shared_lock<std::shared_mutex> lock(controller.mutex());
                snap = controller.snapshot();
            }
            state_writer.write(snap.state);
            publish_tick.trigger_value(false);
        });

        pub_aws.attach_condition(publish_tick);

        // --- Subscriber AsyncWaitSet (all input readers) ---
        rti::core::cond::AsyncWaitSet sub_aws;

        // SafetyInterlock reader — highest priority
        dds::sub::cond::ReadCondition interlock_rc(
            interlock_reader,
            dds::sub::status::DataState::any(),
            [&]() {
                auto samples = interlock_reader.take();
                std::unique_lock<std::shared_mutex> lock(controller.mutex());
                for (const auto& sample : samples) {
                    if (sample.info().valid()) {
                        controller.apply_safety_interlock(sample.data());
                    }
                }
            });

        // RobotCommand reader
        dds::sub::cond::ReadCondition command_rc(
            command_reader,
            dds::sub::status::DataState::any(),
            [&]() {
                auto samples = command_reader.take();
                std::unique_lock<std::shared_mutex> lock(controller.mutex());
                for (const auto& sample : samples) {
                    if (sample.info().valid()) {
                        controller.apply_robot_command(sample.data());
                    }
                }
            });

        // OperatorInput reader
        dds::sub::cond::ReadCondition input_rc(
            input_reader,
            dds::sub::status::DataState::any(),
            [&]() {
                auto samples = input_reader.take();
                std::unique_lock<std::shared_mutex> lock(controller.mutex());
                for (const auto& sample : samples) {
                    if (sample.info().valid()) {
                        controller.apply_operator_input(sample.data());
                    }
                }
            });

        sub_aws.attach_condition(interlock_rc);
        sub_aws.attach_condition(command_rc);
        sub_aws.attach_condition(input_rc);

        // --- Start both AsyncWaitSets ---
        pub_aws.start();
        sub_aws.start();

        log.notice("Robot controller running (100 Hz publish, robot_id="
                   + robot_id + ")");

        // --- Timer thread: trigger publish_tick at 100 Hz ---
        std::thread timer_thread([&]() {
            using clock = std::chrono::steady_clock;
            const auto period = std::chrono::microseconds(10000);  // 10 ms
            auto next_tick = clock::now() + period;

            while (!g_shutdown_requested.load(std::memory_order_relaxed)) {
                std::this_thread::sleep_until(next_tick);
                publish_tick.trigger_value(true);
                next_tick += period;
            }
        });

        // --- Wait for shutdown signal ---
        while (!g_shutdown_requested.load(std::memory_order_relaxed)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }

        log.notice("Shutting down robot controller");

        // --- Cleanup ---
        g_shutdown_requested.store(true);
        timer_thread.join();

        // Detach all conditions before stopping to avoid
        // "Precondition not met: waitset attached" errors.
        pub_aws.detach_condition(publish_tick);
        sub_aws.detach_condition(interlock_rc);
        sub_aws.detach_condition(command_rc);
        sub_aws.detach_condition(input_rc);

        pub_aws.stop();
        sub_aws.stop();
        participant.close();

        return 0;

    } catch (const std::exception& ex) {
        log.error(std::string("Fatal: ") + ex.what());
        return 1;
    }
}
