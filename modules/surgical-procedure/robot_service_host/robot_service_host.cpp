// robot_service_host.cpp — Robot Service Host implementation.
//
// Manages a single RobotControllerService on the Procedure domain and
// exposes a ServiceHostControl RPC endpoint on the Orchestration domain.
// Publishes HostCatalog and ServiceStatus per the orchestration spec.

#include "robot_service_host.hpp"

#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include <dds/dds.hpp>
#include <dds/rpc/Server.hpp>
#include <dds/rpc/ServerParams.hpp>
#include <dds/rpc/ServiceEndpoint.hpp>
#include <dds/rpc/ServiceParams.hpp>
#include <rti/domain/find.hpp>
#include <rti/pub/findImpl.hpp>
#include <rti/sub/findImpl.hpp>

#include "medtech/dds_init.hpp"
#include "../robot_controller/robot_controller_service.hpp"

#include <app_names/app_names.hpp>
#include <orchestration/orchestration.hpp>

namespace orch_names = MedtechEntityNames::OrchestrationParticipants;
namespace proc_names = MedtechEntityNames::SurgicalParticipants;

namespace medtech::surgical {

namespace {

// ---------------------------------------------------------------------------
// ServiceHostControlImpl — concrete RPC service implementation.
//
// Implements the IDL-generated Orchestration::ServiceHostControl interface.
// Dispatched by the RPC framework on the server thread pool.
// ---------------------------------------------------------------------------
class ServiceHostControlImpl : public Orchestration::ServiceHostControl {
public:
    ServiceHostControlImpl(
        const std::string& host_id,
        const std::string& room_id,
        const std::string& procedure_id,
        medtech::ModuleLogger& log)
        : host_id_(host_id),
          room_id_(room_id),
          procedure_id_(procedure_id),
          log_(log)
    {
    }

    Orchestration::OperationResult start_service(
        const Orchestration::ServiceRequest& req) override
    {
        std::lock_guard<std::mutex> lock(mu_);
        Orchestration::OperationResult result;

        if (service_ && service_->state() != Orchestration::ServiceState::STOPPED
            && service_->state() != Orchestration::ServiceState::FAILED) {
            result.code = Orchestration::OperationResultCode::ALREADY_RUNNING;
            result.message = "Service is already running";
            log_.notice("start_service rejected: ALREADY_RUNNING");
            return result;
        }

        try {
            // Create a Procedure domain participant for the hosted service
            auto provider = dds::core::QosProvider::Default();
            hosted_participant_ = provider.extensions()
                .create_participant_from_config(
                    std::string(proc_names::CONTROL_ROBOT));

            const std::string partition =
                "room/" + room_id_ + "/procedure/" + procedure_id_;
            auto dp_qos = hosted_participant_.qos();
            dp_qos << dds::core::policy::Partition(partition);
            hosted_participant_.qos(dp_qos);

            // Construct the service in hosted mode — it does NOT create
            // its own participant since we pass a valid one.
            // Note: The current RobotControllerService always creates its
            // own participant (standalone only for now). We construct via
            // the factory which creates in standalone mode.
            service_ = make_robot_controller_service(
                "001", room_id_, procedure_id_, log_);

            // Spawn run() on a dedicated thread
            service_thread_ = std::thread([this]() {
                try {
                    service_->run();
                } catch (const std::exception& ex) {
                    log_.error(
                        std::string("Service run() threw: ") + ex.what());
                }
            });

            result.code = Orchestration::OperationResultCode::OK;
            result.message = "Service started";
            log_.notice("start_service: OK (service_id="
                + req.service_id + ")");
        } catch (const std::exception& ex) {
            result.code = Orchestration::OperationResultCode::INTERNAL_ERROR;
            result.message = std::string("Failed to start service: ") + ex.what();
            log_.error("start_service: INTERNAL_ERROR — "
                + std::string(ex.what()));
        }
        return result;
    }

    Orchestration::OperationResult stop_service(
        const Orchestration::ServiceRequest& req) override
    {
        std::lock_guard<std::mutex> lock(mu_);
        Orchestration::OperationResult result;

        if (!service_ || service_->state() == Orchestration::ServiceState::STOPPED) {
            result.code = Orchestration::OperationResultCode::NOT_RUNNING;
            result.message = "Service is not running";
            log_.notice("stop_service rejected: NOT_RUNNING");
            return result;
        }

        service_->stop();
        if (service_thread_.joinable()) {
            service_thread_.join();
        }

        // Release the service and hosted participant
        service_.reset();
        if (hosted_participant_ != dds::core::null) {
            hosted_participant_.close();
            hosted_participant_ = dds::core::null;
        }

        result.code = Orchestration::OperationResultCode::OK;
        result.message = "Service stopped";
        log_.notice("stop_service: OK (service_id="
            + req.service_id + ")");
        return result;
    }

    Orchestration::OperationResult configure_service(
        const Orchestration::ConfigureRequest& req) override
    {
        Orchestration::OperationResult result;
        result.code = Orchestration::OperationResultCode::OK;
        result.message = "Configuration accepted (no-op in V1.0)";
        log_.notice("configure_service: OK (service_id="
            + req.service_id + ")");
        return result;
    }

    Orchestration::CapabilityReport get_capabilities() override
    {
        Orchestration::CapabilityReport report;
        report.supported_services.push_back("RobotControllerService");
        report.capacity = 1;
        log_.notice("get_capabilities: reported 1 service");
        return report;
    }

    Orchestration::HealthReport get_health() override
    {
        Orchestration::HealthReport report;
        report.alive = true;

        std::lock_guard<std::mutex> lock(mu_);
        if (service_) {
            auto st = service_->state();
            report.summary =
                std::string("RobotControllerService: ")
                + std::to_string(static_cast<int>(st));
        } else {
            report.summary = "No service running";
        }
        report.diagnostics = "";
        return report;
    }

    /// Poll the current service state (called from the host's status thread).
    Orchestration::ServiceState service_state() const
    {
        std::lock_guard<std::mutex> lock(mu_);
        if (service_) {
            return service_->state();
        }
        return Orchestration::ServiceState::STOPPED;
    }

    std::string service_name() const
    {
        std::lock_guard<std::mutex> lock(mu_);
        if (service_) {
            return std::string(service_->name());
        }
        return "";
    }

private:
    std::string host_id_;
    std::string room_id_;
    std::string procedure_id_;
    medtech::ModuleLogger& log_;

    mutable std::mutex mu_;
    std::unique_ptr<medtech::Service> service_;
    std::thread service_thread_;
    dds::domain::DomainParticipant hosted_participant_{nullptr};
};


// ---------------------------------------------------------------------------
// RobotServiceHost — medtech::Service that wraps the orchestration layer.
//
// Creates an Orchestration domain participant, registers the RPC service,
// publishes HostCatalog and ServiceStatus, and blocks in run().
// ---------------------------------------------------------------------------
class RobotServiceHost : public medtech::Service {
public:
    RobotServiceHost(
        const std::string& host_id,
        const std::string& room_id,
        const std::string& procedure_id,
        medtech::ModuleLogger& log)
        : host_id_(host_id),
          room_id_(room_id),
          procedure_id_(procedure_id),
          log_(log),
          svc_state_(Orchestration::ServiceState::STOPPED)
    {
        // -- Create Orchestration domain participant from XML --
        medtech::initialize_connext();
        auto provider = dds::core::QosProvider::Default();
        orch_participant_ = provider.extensions()
            .create_participant_from_config(
                std::string(orch_names::ORCHESTRATION));

        const std::string partition = "room/" + room_id;
        auto dp_qos = orch_participant_.qos();
        dp_qos << dds::core::policy::Partition(partition);
        orch_participant_.qos(dp_qos);

        log_.notice("Orchestration participant created, partition=" + partition);

        // -- Look up pub/sub entities --
        catalog_writer_ =
            rti::pub::find_datawriter_by_name<
                dds::pub::DataWriter<Orchestration::HostCatalog>>(
                orch_participant_,
                std::string(orch_names::HOST_CATALOG_WRITER));

        status_writer_ =
            rti::pub::find_datawriter_by_name<
                dds::pub::DataWriter<Orchestration::ServiceStatus>>(
                orch_participant_,
                std::string(orch_names::SERVICE_STATUS_WRITER));

        if (catalog_writer_ == dds::core::null
            || status_writer_ == dds::core::null) {
            throw std::runtime_error(
                "Failed to find orchestration DataWriter entities");
        }

        log_.notice("Orchestration DataWriters found");

        // -- Create the RPC implementation --
        rpc_impl_ = std::make_shared<ServiceHostControlImpl>(
            host_id, room_id, procedure_id, log);
    }

    void run() override
    {
        svc_state_.store(Orchestration::ServiceState::STARTING,
                         std::memory_order_release);

        // Enable the orchestration participant
        orch_participant_.enable();

        // -- Set up the RPC server + service endpoint --
        dds::rpc::ServerParams server_params;
        server_params.extensions().thread_pool_size(1);
        rpc_server_ = dds::rpc::Server(server_params);

        dds::rpc::ServiceParams service_params(orch_participant_);
        service_params.service_name(
            "ServiceHostControl/" + host_id_);

        rpc_service_ = std::make_unique<
            Orchestration::ServiceHostControlService>(
            rpc_impl_, rpc_server_, service_params);

        log_.notice("RPC service registered: ServiceHostControl/" + host_id_);

        // -- Publish initial HostCatalog --
        publish_host_catalog();

        // -- Publish initial ServiceStatus (STOPPED) --
        publish_service_status(Orchestration::ServiceState::STOPPED);

        svc_state_.store(Orchestration::ServiceState::RUNNING,
                         std::memory_order_release);
        log_.notice("Robot Service Host running (host_id=" + host_id_ + ")");

        // -- Status polling loop --
        auto last_published_state = Orchestration::ServiceState::STOPPED;
        while (running_.load(std::memory_order_relaxed)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));

            auto current = rpc_impl_->service_state();
            if (current != last_published_state) {
                publish_service_status(current);
                last_published_state = current;
            }
        }

        // -- Shutdown --
        svc_state_.store(Orchestration::ServiceState::STOPPING,
                         std::memory_order_release);
        log_.notice("Robot Service Host shutting down");

        // Close the RPC service before shutting down other entities
        if (rpc_service_) {
            rpc_service_->close();
            rpc_service_.reset();
        }
        if (rpc_server_ != dds::core::null) {
            rpc_server_.close();
            rpc_server_ = dds::core::null;
        }

        svc_state_.store(Orchestration::ServiceState::STOPPED,
                         std::memory_order_release);
    }

    void stop() override
    {
        running_.store(false, std::memory_order_release);
    }

    std::string_view name() const override
    {
        return "RobotServiceHost";
    }

    Orchestration::ServiceState state() const override
    {
        return svc_state_.load(std::memory_order_acquire);
    }

private:
    void publish_host_catalog()
    {
        Orchestration::HostCatalog catalog;
        catalog.host_id = host_id_;
        catalog.supported_services.push_back("RobotControllerService");
        catalog.capacity = 1;
        catalog.health_summary = "OK";
        catalog_writer_.write(catalog);
        log_.notice("Published HostCatalog for host " + host_id_);
    }

    void publish_service_status(Orchestration::ServiceState svc_state)
    {
        Orchestration::ServiceStatus status;
        status.host_id = host_id_;

        auto svc_name = rpc_impl_->service_name();
        status.service_id =
            svc_name.empty() ? "RobotControllerService" : svc_name;

        status.state = svc_state;

        // Use system_clock for wall-clock timestamp
        auto now = std::chrono::system_clock::now();
        auto epoch = now.time_since_epoch();
        auto secs = std::chrono::duration_cast<std::chrono::seconds>(epoch);
        auto nsecs = std::chrono::duration_cast<std::chrono::nanoseconds>(
            epoch - secs);

        status.timestamp.sec =
            static_cast<uint32_t>(secs.count());
        status.timestamp.nsec =
            static_cast<uint32_t>(nsecs.count());

        status_writer_.write(status);
        log_.notice("Published ServiceStatus: "
            + std::to_string(static_cast<int>(svc_state))
            + " for " + status.service_id);
    }

    // Configuration
    std::string host_id_;
    std::string room_id_;
    std::string procedure_id_;
    medtech::ModuleLogger& log_;

    // Lifecycle
    std::atomic<bool> running_{true};
    std::atomic<Orchestration::ServiceState> svc_state_{
        Orchestration::ServiceState::STOPPED};

    // Orchestration domain
    dds::domain::DomainParticipant orch_participant_{nullptr};
    dds::pub::DataWriter<Orchestration::HostCatalog> catalog_writer_{nullptr};
    dds::pub::DataWriter<Orchestration::ServiceStatus> status_writer_{nullptr};

    // RPC
    std::shared_ptr<ServiceHostControlImpl> rpc_impl_;
    dds::rpc::Server rpc_server_{nullptr};
    std::unique_ptr<Orchestration::ServiceHostControlService> rpc_service_;
};

}  // anonymous namespace

std::unique_ptr<medtech::Service> make_robot_service_host(
    const std::string& host_id,
    const std::string& room_id,
    const std::string& procedure_id,
    medtech::ModuleLogger& log)
{
    return std::make_unique<RobotServiceHost>(
        host_id, room_id, procedure_id, log);
}

}  // namespace medtech::surgical
