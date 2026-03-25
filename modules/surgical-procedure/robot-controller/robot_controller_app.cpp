// robot_controller_app.cpp — Robot controller DDS application entry point.
//
// Creates a ControlRobot participant from XML config, wraps all DDS
// entities in a RobotControllerApp class for RAII lifecycle, and runs
// a 100 Hz publish loop on a dedicated timer thread alongside an
// AsyncWaitSet for subscriber input processing.
//
// Canonical architecture pattern per vision/dds-consistency.md §3:
//   - All DDS entities are private members
//   - start() enables participant, starts AWS, spawns timer
//   - wait_for_shutdown() blocks until running_ is false
//   - Destructor follows canonical shutdown sequence
//   - Member declaration order ensures correct destruction
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

#include <app_names/app_names.hpp>

namespace names = MedtechEntityNames::SurgicalParticipants;

namespace {

std::string env_or(const char* name, const char* fallback)
{
    const char* val = std::getenv(name);
    return (val != nullptr) ? std::string(val) : std::string(fallback);
}

// ---------------------------------------------------------------------------
// RobotControllerApp — canonical C++ service class per dds-consistency.md §3.
//
// Owns all DDS entities privately. Member declaration order ensures
// reverse destruction: timer_thread_ → sub_aws_ → conditions → readers →
// writer → participant_ → running_ → log_ → controller_.
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

        medtech::initialize_connext();

        auto provider = dds::core::QosProvider::Default();
        participant_ = provider.extensions().create_participant_from_config(
            std::string(names::CONTROL_ROBOT));

        auto dp_qos = participant_.qos();
        dp_qos << dds::core::policy::Partition(partition);
        participant_.qos(dp_qos);

        log_.notice("Participant created: " + std::string(names::CONTROL_ROBOT));

        state_writer_ =
            rti::pub::find_datawriter_by_name<
                dds::pub::DataWriter<Surgery::RobotState>>(
                participant_, std::string(names::ROBOT_STATE_WRITER));

        interlock_reader_ =
            rti::sub::find_datareader_by_name<
                dds::sub::DataReader<Surgery::SafetyInterlock>>(
                participant_, std::string(names::SAFETY_INTERLOCK_READER));

        command_reader_ =
            rti::sub::find_datareader_by_name<
                dds::sub::DataReader<Surgery::RobotCommand>>(
                participant_, std::string(names::ROBOT_COMMAND_READER));

        input_reader_ =
            rti::sub::find_datareader_by_name<
                dds::sub::DataReader<Surgery::OperatorInput>>(
                participant_, std::string(names::OPERATOR_INPUT_READER));

        if (state_writer_ == dds::core::null
            || interlock_reader_ == dds::core::null
            || command_reader_ == dds::core::null
            || input_reader_ == dds::core::null) {
            throw std::runtime_error(
                "Failed to find one or more named DDS entities");
        }

        log_.notice("All DDS entities found");

        interlock_rc_ = dds::sub::cond::ReadCondition(
            interlock_reader_,
            dds::sub::status::DataState::any(),
            [this]() {
                auto samples = interlock_reader_.take();
                std::unique_lock<std::shared_mutex> lock(controller_.mutex());
                for (const auto& sample : samples) {
                    if (sample.info().valid()) {
                        controller_.apply_safety_interlock(sample.data());
                    }
                }
            });

        command_rc_ = dds::sub::cond::ReadCondition(
            command_reader_,
            dds::sub::status::DataState::any(),
            [this]() {
                auto samples = command_reader_.take();
                std::unique_lock<std::shared_mutex> lock(controller_.mutex());
                for (const auto& sample : samples) {
                    if (sample.info().valid()) {
                        controller_.apply_robot_command(sample.data());
                    }
                }
            });

        input_rc_ = dds::sub::cond::ReadCondition(
            input_reader_,
            dds::sub::status::DataState::any(),
            [this]() {
                auto samples = input_reader_.take();
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

    ~RobotControllerApp()
    {
        // 1. Signal threads to stop
        running_.store(false, std::memory_order_release);
        // 2. Join timer thread
        if (timer_thread_.joinable()) {
            timer_thread_.join();
        }
        // 3. Stop AsyncWaitSet — blocks until no handlers are in flight
        sub_aws_.stop();
        // 4. Members destruct in reverse declaration order:
        //    sub_aws_ → conditions → readers → writer → participant_
    }

    void start()
    {
        participant_.enable();
        sub_aws_.start();

        log_.notice("Robot controller running (100 Hz publish, robot_id="
                    + controller_.snapshot().state.robot_id + ")");

        timer_thread_ = std::thread([this]() {
            using clock = std::chrono::steady_clock;
            const auto period = std::chrono::microseconds(10000);  // 10 ms
            auto next_tick = clock::now() + period;

            while (running_.load(std::memory_order_relaxed)) {
                std::this_thread::sleep_until(next_tick);
                medtech::surgical::ControllerSnapshot snap;
                {
                    std::shared_lock<std::shared_mutex> lock(
                        controller_.mutex());
                    snap = controller_.snapshot();
                }
                if (running_.load(std::memory_order_relaxed)) {
                    state_writer_.write(snap.state);
                }
                next_tick += period;
            }
        });
    }

    void wait_for_shutdown()
    {
        while (running_.load(std::memory_order_relaxed)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
        log_.notice("Shutting down robot controller");
    }

    void request_shutdown()
    {
        running_.store(false, std::memory_order_release);
    }

private:
    // Members declared in construction order; destroyed in reverse.
    // Pure logic — no DDS
    medtech::surgical::RobotController controller_;
    medtech::ModuleLogger& log_;
    std::atomic<bool> running_{true};

    // DDS entities (destroyed after AsyncWaitSet)
    dds::domain::DomainParticipant participant_{nullptr};
    dds::pub::DataWriter<Surgery::RobotState> state_writer_{nullptr};
    dds::sub::DataReader<Surgery::SafetyInterlock> interlock_reader_{nullptr};
    dds::sub::DataReader<Surgery::RobotCommand> command_reader_{nullptr};
    dds::sub::DataReader<Surgery::OperatorInput> input_reader_{nullptr};

    // Conditions (destroyed before readers)
    dds::sub::cond::ReadCondition interlock_rc_{nullptr};
    dds::sub::cond::ReadCondition command_rc_{nullptr};
    dds::sub::cond::ReadCondition input_rc_{nullptr};

    // AsyncWaitSet (destroyed first — declared last among DDS members)
    rti::core::cond::AsyncWaitSet sub_aws_;

    // Worker thread (joined in destructor before aws_.stop())
    std::thread timer_thread_;
};

// File-level pointer for signal handler → app shutdown integration
RobotControllerApp* g_app_ptr = nullptr;

void signal_handler(int /*sig*/)
{
    if (g_app_ptr != nullptr) {
        g_app_ptr->request_shutdown();
    }
}

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
        g_app_ptr = &app;
        app.start();
        app.wait_for_shutdown();
        g_app_ptr = nullptr;
        return 0;

    } catch (const std::exception& ex) {
        log.error(std::string("Fatal: ") + ex.what());
        return 1;
    }
}
