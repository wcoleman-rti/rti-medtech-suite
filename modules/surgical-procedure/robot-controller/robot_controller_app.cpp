// robot_controller_app.cpp — Robot controller DDS application entry point.
//
// Creates a ControlRobot participant from XML config, wraps all DDS
// entities in a RobotControllerApp class for RAII lifecycle, and runs
// a 100 Hz publish loop on a dedicated timer thread alongside an
// AsyncWaitSet for subscriber input processing.
//
// Environment variables:
//   ROBOT_ID         — Robot numeric ID (default: "001"), prefixed to "robot-001"
//   ROOM_ID          — Room identifier (e.g., "OR-3")
//   PROCEDURE_ID     — Procedure identifier (e.g., "proc-001")
//   MEDTECH_APP_NAME — Monitoring Library 2.0 application name
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

#include "medtech/dds_init.hpp"
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

// ---------------------------------------------------------------------------
// RobotControllerApp — owns all DDS entities and the controller state machine.
// Destruction follows reverse-construction order and the DomainParticipant
// destructor handles entity cleanup.
// ---------------------------------------------------------------------------
class RobotControllerApp {
public:
    RobotControllerApp(const std::string& robot_id,
                       const std::string& room_id,
                       const std::string& procedure_id,
                       medtech::ModuleLogger& log)
        : controller_("robot-" + robot_id), log_(log)
    {
        const std::string partition =
            "room/" + room_id + "/procedure/" + procedure_id;

        // Centralized pre-participant initialization
        medtech::initialize_connext();

        // Create participant from XML config
        auto provider = dds::core::QosProvider::Default();
        participant_ = provider.extensions().create_participant_from_config(
            "SurgicalParticipants::ControlRobot");

        // Set participant-level partition from runtime context.
        auto dp_qos = participant_.qos();
        dp_qos << dds::core::policy::Partition(partition);
        participant_.qos(dp_qos);

        log_.notice("Participant created: SurgicalParticipants::ControlRobot");

        // Look up typed writers and readers
        state_writer_ =
            rti::pub::find_datawriter_by_name<
                dds::pub::DataWriter<Surgery::RobotState>>(
                participant_, "RobotPublisher::RobotStateWriter");

        auto interlock_reader =
            rti::sub::find_datareader_by_name<
                dds::sub::DataReader<Surgery::SafetyInterlock>>(
                participant_, "RobotSubscriber::SafetyInterlockReader");

        auto command_reader =
            rti::sub::find_datareader_by_name<
                dds::sub::DataReader<Surgery::RobotCommand>>(
                participant_, "RobotSubscriber::RobotCommandReader");

        auto input_reader =
            rti::sub::find_datareader_by_name<
                dds::sub::DataReader<Surgery::OperatorInput>>(
                participant_, "RobotSubscriber::OperatorInputReader");

        if (state_writer_ == dds::core::null
            || interlock_reader == dds::core::null
            || command_reader == dds::core::null
            || input_reader == dds::core::null) {
            throw std::runtime_error(
                "Failed to find one or more named DDS entities");
        }

        log_.notice("All DDS entities found");

        // Set up subscriber AsyncWaitSet with ReadConditions
        interlock_rc_ = dds::sub::cond::ReadCondition(
            interlock_reader,
            dds::sub::status::DataState::any(),
            [&, interlock_reader]() mutable {
                auto samples = interlock_reader.take();
                std::unique_lock<std::shared_mutex> lock(controller_.mutex());
                for (const auto& sample : samples) {
                    if (sample.info().valid()) {
                        controller_.apply_safety_interlock(sample.data());
                    }
                }
            });

        command_rc_ = dds::sub::cond::ReadCondition(
            command_reader,
            dds::sub::status::DataState::any(),
            [&, command_reader]() mutable {
                auto samples = command_reader.take();
                std::unique_lock<std::shared_mutex> lock(controller_.mutex());
                for (const auto& sample : samples) {
                    if (sample.info().valid()) {
                        controller_.apply_robot_command(sample.data());
                    }
                }
            });

        input_rc_ = dds::sub::cond::ReadCondition(
            input_reader,
            dds::sub::status::DataState::any(),
            [&, input_reader]() mutable {
                auto samples = input_reader.take();
                std::unique_lock<std::shared_mutex> lock(controller_.mutex());
                for (const auto& sample : samples) {
                    if (sample.info().valid()) {
                        controller_.apply_operator_input(sample.data());
                    }
                }
            });

        sub_aws_.attach_condition(interlock_rc_);
        sub_aws_.attach_condition(command_rc_);
        sub_aws_.attach_condition(input_rc_);
    }

    // Run the application: starts subscriber AsyncWaitSet, spawns the
    // 100 Hz publisher timer thread, and blocks until shutdown is requested.
    void run()
    {
        // Enable participant now that all entities are created and
        // conditions attached. Recursively enables all child entities
        // and initiates DDS discovery.
        participant_.enable();

        sub_aws_.start();
        log_.notice("Robot controller running (100 Hz publish, robot_id="
                    + controller_.snapshot().state.robot_id + ")");

        // Timer thread: write RobotState directly at 100 Hz.
        // DataWriter::write() is thread-safe — no GuardCondition needed.
        std::thread timer_thread([this]() {
            using clock = std::chrono::steady_clock;
            const auto period = std::chrono::microseconds(10000);  // 10 ms
            auto next_tick = clock::now() + period;

            while (!g_shutdown_requested.load(std::memory_order_relaxed)) {
                std::this_thread::sleep_until(next_tick);
                medtech::surgical::ControllerSnapshot snap;
                {
                    std::shared_lock<std::shared_mutex> lock(
                        controller_.mutex());
                    snap = controller_.snapshot();
                }
                state_writer_.write(snap.state);
                next_tick += period;
            }
        });

        // Block until shutdown signal
        while (!g_shutdown_requested.load(std::memory_order_relaxed)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }

        log_.notice("Shutting down robot controller");
        timer_thread.join();

        // Detach conditions before stopping to avoid
        // "Precondition not met: waitset attached" errors.
        sub_aws_.detach_condition(interlock_rc_);
        sub_aws_.detach_condition(command_rc_);
        sub_aws_.detach_condition(input_rc_);
        sub_aws_.stop();
    }

private:
    medtech::surgical::RobotController controller_;
    medtech::ModuleLogger& log_;

    dds::domain::DomainParticipant participant_{nullptr};
    dds::pub::DataWriter<Surgery::RobotState> state_writer_{nullptr};

    rti::core::cond::AsyncWaitSet sub_aws_;
    dds::sub::cond::ReadCondition interlock_rc_{nullptr};
    dds::sub::cond::ReadCondition command_rc_{nullptr};
    dds::sub::cond::ReadCondition input_rc_{nullptr};
};

}  // anonymous namespace

int main()
{
    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    auto log = medtech::init_logging(medtech::ModuleName::SurgicalProcedure);

    try {
        const std::string robot_id = env_or("ROBOT_ID", "001");
        const std::string room_id = env_or("ROOM_ID", "OR-1");
        const std::string procedure_id = env_or("PROCEDURE_ID", "proc-001");

        RobotControllerApp app(robot_id, room_id, procedure_id, log);
        app.run();
        return 0;

    } catch (const std::exception& ex) {
        log.error(std::string("Fatal: ") + ex.what());
        return 1;
    }
}
