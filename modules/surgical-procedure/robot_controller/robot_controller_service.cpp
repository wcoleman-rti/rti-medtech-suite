// robot_controller_service.cpp — RobotControllerService implementation.

#include "robot_controller_service.hpp"

#include <atomic>
#include <chrono>
#include <shared_mutex>
#include <string>
#include <thread>

#include <dds/dds.hpp>
#include <dds/topic/ContentFilteredTopic.hpp>
#include <rti/core/cond/AsyncWaitSet.hpp>
#include <rti/domain/find.hpp>
#include <rti/pub/findImpl.hpp>
#include <rti/sub/findImpl.hpp>

#include "medtech/dds_init.hpp"
#include "robot_controller.hpp"

#include <app_names/app_names.hpp>

namespace names = MedtechEntityNames::SurgicalParticipants;

namespace medtech::surgical {

namespace {

// Set the %0 parameter on a reader's ContentFilteredTopic to a SQL string
// literal.  No-op if the reader does not use a CFT.
template <typename T>
void set_cft_robot_id(
    dds::sub::DataReader<T>& reader,
    const std::string& robot_id,
    medtech::ModuleLogger& log)
{
    try {
        auto cft = dds::core::polymorphic_cast<
            dds::topic::ContentFilteredTopic<T>>(reader.topic_description());
        std::vector<std::string> params = { "'" + robot_id + "'" };
        cft.filter_parameters(params.begin(), params.end());
        log.informational("CFT parameter set: robot_id='" + robot_id + "'");
    } catch (const dds::core::InvalidDowncastError&) {
        // Reader was not created with a CFT (e.g. injected test reader)
    }
}

// Parse a string to Surgery::TablePosition (case-insensitive).
Surgery::TablePosition parse_table_position(const std::string& s) {
    if (s == "HEAD")       return Surgery::TablePosition::HEAD;
    if (s == "FOOT")       return Surgery::TablePosition::FOOT;
    if (s == "LEFT")       return Surgery::TablePosition::LEFT;
    if (s == "RIGHT")      return Surgery::TablePosition::RIGHT;
    if (s == "LEFT_HEAD")  return Surgery::TablePosition::LEFT_HEAD;
    if (s == "RIGHT_HEAD") return Surgery::TablePosition::RIGHT_HEAD;
    if (s == "LEFT_FOOT")  return Surgery::TablePosition::LEFT_FOOT;
    if (s == "RIGHT_FOOT") return Surgery::TablePosition::RIGHT_FOOT;
    return Surgery::TablePosition::UNKNOWN;
}

// ---------------------------------------------------------------------------
// RobotControllerService — canonical C++ service per dds-consistency.md §3.
//
// Owns all DDS entities privately. Member declaration order ensures
// reverse destruction: timer_thread_ → sub_aws_ → conditions → readers →
// writer → participant_ → running_ → log_ → controller_.
// ---------------------------------------------------------------------------
class RobotControllerService : public medtech::Service {
public:
    RobotControllerService(const std::string& robot_id,
                           const std::string& room_id,
                           const std::string& procedure_id,
                           const std::string& table_position_str,
                           medtech::ModuleLogger& log)
        : controller_(robot_id), log_(log),
          svc_state_(Orchestration::ServiceState::STOPPED),
          robot_id_(robot_id), procedure_id_(procedure_id),
          table_position_(parse_table_position(table_position_str))
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

        assignment_writer_ =
            rti::pub::find_datawriter_by_name<
                dds::pub::DataWriter<Surgery::RobotArmAssignment>>(
                participant_, std::string(names::ROBOT_ARM_ASSIGNMENT_WRITER));

        if (state_writer_ == dds::core::null
            || interlock_reader_ == dds::core::null
            || command_reader_ == dds::core::null
            || input_reader_ == dds::core::null
            || assignment_writer_ == dds::core::null) {
            throw std::runtime_error(
                "Failed to find one or more named DDS entities");
        }

        log_.notice("All DDS entities found");

        // Set CFT filter parameters so each reader delivers only
        // samples addressed to this controller's robot_id.
        set_cft_robot_id(input_reader_, controller_.robot_id(), log_);
        set_cft_robot_id(command_reader_, controller_.robot_id(), log_);
        set_cft_robot_id(interlock_reader_, controller_.robot_id(), log_);

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

    ~RobotControllerService() override
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

    void run() override
    {
        svc_state_.store(Orchestration::ServiceState::STARTING,
                         std::memory_order_release);
        start();
        svc_state_.store(Orchestration::ServiceState::RUNNING,
                         std::memory_order_release);

        // Publish arm assignment lifecycle: ASSIGNED → POSITIONING → OPERATIONAL
        // Each phase checks running_ so stop() is handled promptly.
        publish_assignment(Surgery::ArmAssignmentState::ASSIGNED);

        // Brief pause for ASSIGNED to propagate before transitioning
        std::this_thread::sleep_for(std::chrono::milliseconds(500));

        if (running_.load(std::memory_order_relaxed)) {
            publish_assignment(Surgery::ArmAssignmentState::POSITIONING);

            // Simulate positioning delay (2 seconds)
            for (int i = 0; i < 20 && running_.load(std::memory_order_relaxed); ++i) {
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
            }
        }

        if (running_.load(std::memory_order_relaxed)) {
            publish_assignment(Surgery::ArmAssignmentState::OPERATIONAL);
        }

        wait_for_shutdown();

        svc_state_.store(Orchestration::ServiceState::STOPPING,
                         std::memory_order_release);

        // Dispose the assignment instance on shutdown
        dispose_assignment();

        svc_state_.store(Orchestration::ServiceState::STOPPED,
                         std::memory_order_release);
    }

    void stop() override
    {
        running_.store(false, std::memory_order_release);
    }

    std::string_view name() const override
    {
        return "RobotControllerService";
    }

    Orchestration::ServiceState state() const override
    {
        return svc_state_.load(std::memory_order_acquire);
    }

private:
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

    void publish_assignment(Surgery::ArmAssignmentState new_status)
    {
        assignment_status_ = new_status;
        Surgery::RobotArmAssignment sample(
            robot_id_, procedure_id_, table_position_,
            assignment_status_, "robot-controller");
        assignment_writer_.write(sample);
        log_.notice("Arm assignment: " + robot_id_ + " -> "
                    + std::to_string(static_cast<int>(new_status)));
    }

    void dispose_assignment()
    {
        Surgery::RobotArmAssignment key;
        key.robot_id = robot_id_;
        auto handle = assignment_writer_.register_instance(key);
        assignment_writer_.dispose_instance(handle);
        log_.notice("Arm assignment disposed: " + robot_id_);
    }

    // Members declared in construction order; destroyed in reverse.
    RobotController controller_;
    medtech::ModuleLogger& log_;
    std::atomic<bool> running_{true};
    std::atomic<Orchestration::ServiceState> svc_state_{
        Orchestration::ServiceState::STOPPED};

    dds::domain::DomainParticipant participant_{nullptr};
    dds::pub::DataWriter<Surgery::RobotState> state_writer_{nullptr};
    dds::pub::DataWriter<Surgery::RobotArmAssignment> assignment_writer_{nullptr};
    dds::sub::DataReader<Surgery::SafetyInterlock> interlock_reader_{nullptr};
    dds::sub::DataReader<Surgery::RobotCommand> command_reader_{nullptr};
    dds::sub::DataReader<Surgery::OperatorInput> input_reader_{nullptr};

    dds::sub::cond::ReadCondition interlock_rc_{nullptr};
    dds::sub::cond::ReadCondition command_rc_{nullptr};
    dds::sub::cond::ReadCondition input_rc_{nullptr};

    rti::core::cond::AsyncWaitSet sub_aws_;
    std::thread timer_thread_;

    // Arm assignment state
    std::string robot_id_;
    std::string procedure_id_;
    Surgery::TablePosition table_position_;
    Surgery::ArmAssignmentState assignment_status_{
        Surgery::ArmAssignmentState::UNKNOWN};
};

}  // anonymous namespace

std::unique_ptr<medtech::Service> make_robot_controller_service(
    const std::string& robot_id,
    const std::string& room_id,
    const std::string& procedure_id,
    const std::string& table_position,
    medtech::ModuleLogger& log)
{
    return std::make_unique<RobotControllerService>(
        robot_id, room_id, procedure_id, table_position, log);
}

}  // namespace medtech::surgical
