// service_host.cpp — Generic Service Host implementation.
//
// Contains ServiceHostControlImpl (the RPC handler) and ServiceHost
// (the medtech::Service wrapper).  These are fully generic — each
// concrete host (robot, clinical, operational) only provides a
// ServiceRegistryMap with factories and catalog metadata.
//
// Mirrors modules/shared/medtech/service_host.py for the Python side.

#include "medtech/service_host.hpp"

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <future>
#include <memory>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <unordered_map>

#include <dds/dds.hpp>
#include <dds/rpc/Server.hpp>
#include <dds/rpc/ServerParams.hpp>
#include <dds/rpc/ServiceEndpoint.hpp>
#include <dds/rpc/ServiceParams.hpp>
#include <rti/domain/find.hpp>
#include <rti/pub/findImpl.hpp>
#include <rti/sub/findImpl.hpp>

#include "medtech/dds_init.hpp"

#include <app_names/app_names.hpp>
#include <orchestration/orchestration.hpp>

namespace orch_names = MedtechEntityNames::OrchestrationParticipants;

namespace medtech {

namespace {

// ---------------------------------------------------------------------------
// ServiceSlot — a running service instance and its dedicated thread.
// ---------------------------------------------------------------------------
struct ServiceSlot {
    std::unique_ptr<Service> service;
    std::thread thread;
};

using ServiceSlotMap = std::unordered_map<Common::EntityId, ServiceSlot>;

// ---------------------------------------------------------------------------
// ServiceHostControlImpl — generic RPC service implementation.
//
// Implements the IDL-generated Orchestration::ServiceHostControl interface.
// Manages zero or more services keyed by Common::EntityId via a registry.
// Dispatched by the RPC framework on the server thread pool.
// ---------------------------------------------------------------------------
class ServiceHostControlImpl : public Orchestration::ServiceHostControl {
public:
    ServiceHostControlImpl(
        const std::string& host_id,
        int32_t capacity,
        ServiceRegistryMap registry,
        ModuleLogger& log)
        : host_id_(host_id),
          capacity_(capacity),
          registry_(std::move(registry)),
          log_(log)
    {
    }

    Orchestration::OperationResult start_service(
        const Orchestration::ServiceRequest& req) override
    {
        std::lock_guard<std::mutex> lock(mu_);
        Orchestration::OperationResult result;
        const Common::EntityId svc_id(req.service_id);

        auto reg_it = registry_.find(svc_id);
        if (reg_it == registry_.end()) {
            result.code = Orchestration::OperationResultCode::INVALID_SERVICE;
            result.message = "Unknown service: " + svc_id;
            log_.notice("start_service rejected: INVALID_SERVICE ("
                + svc_id + ")");
            return result;
        }

        auto slot_it = slots_.find(svc_id);
        if (slot_it != slots_.end()) {
            auto st = slot_it->second.service->state();
            if (st != Orchestration::ServiceState::STOPPED
                && st != Orchestration::ServiceState::FAILED) {
                result.code = Orchestration::OperationResultCode::ALREADY_RUNNING;
                result.message = "Service is already running";
                log_.notice("start_service rejected: ALREADY_RUNNING ("
                    + svc_id + ")");
                return result;
            }
            // Clear stale slot (STOPPED or FAILED).
            // Destroy on a worker thread: the service destructor may
            // call AsyncWaitSet::stop(), which deadlocks if called
            // from the RPC server's AsyncWaitSet thread (same level).
            {
                ServiceSlot stale = std::move(slot_it->second);
                slots_.erase(slot_it);
                std::thread cleanup([s = std::move(stale)]() mutable {
                    if (s.thread.joinable()) {
                        s.thread.join();
                    }
                    // ~ServiceSlot destroys the service here,
                    // off the RPC AsyncWaitSet thread.
                });
                cleanup.join();
            }
        }

        try {
            // Phase 1: Create the service on a temporary worker thread.
            // The RPC handler runs on an AsyncWaitSet thread; service
            // constructors may create their own AsyncWaitSet, which
            // deadlocks if nested at the same AWSet level.
            auto& factory_fn = reg_it->second.factory;
            std::unique_ptr<Service> new_service;
            std::string create_error;
            {
                std::thread creator([&]() {
                    try {
                        new_service = factory_fn(req);
                    } catch (const std::exception& ex) {
                        create_error = ex.what();
                    }
                });
                creator.join();
            }

            if (!create_error.empty()) {
                throw std::runtime_error(create_error);
            }

            // Phase 2: Start run() on a dedicated thread.
            ServiceSlot slot;
            slot.service = std::move(new_service);
            auto* svc_ptr = slot.service.get();
            slot.thread = std::thread([svc_ptr, this]() {
                try {
                    svc_ptr->run();
                } catch (const std::exception& ex) {
                    log_.error(
                        std::string("Service run() threw: ") + ex.what());
                }
            });

            slots_.emplace(svc_id, std::move(slot));

            // Extract procedure_id from request properties and mark dirty
            std::string procedure_id;
            for (const auto& prop : req.properties) {
                if (std::string(prop.name) == "procedure_id") {
                    procedure_id = std::string(prop.value);
                    break;
                }
            }
            if (!procedure_id.empty()) {
                procedure_ids_[svc_id] = procedure_id;
            } else {
                procedure_ids_.erase(svc_id);
            }
            catalog_dirty_.insert(svc_id);

            result.code = Orchestration::OperationResultCode::OK;
            result.message = "Service started";
            log_.notice("start_service: OK (service_id=" + svc_id + ")");
        } catch (const std::exception& ex) {
            result.code = Orchestration::OperationResultCode::INTERNAL_ERROR;
            std::string msg = std::string("Failed to start service: ") + ex.what();
            if (msg.size() > 500) msg.resize(500);
            result.message = msg;
            log_.error("start_service: INTERNAL_ERROR — "
                + std::string(ex.what()));
        }
        return result;
    }

    Orchestration::OperationResult stop_service(
        const Common::EntityId& service_id) override
    {
        std::lock_guard<std::mutex> lock(mu_);
        Orchestration::OperationResult result;
        const Common::EntityId svc_id(service_id);

        auto slot_it = slots_.find(svc_id);
        if (slot_it == slots_.end()
            || slot_it->second.service->state()
                   == Orchestration::ServiceState::STOPPED) {
            result.code = Orchestration::OperationResultCode::NOT_RUNNING;
            result.message = "Service is not running";
            log_.notice("stop_service rejected: NOT_RUNNING ("
                + svc_id + ")");
            return result;
        }

        {
            slot_it->second.service->stop();

            // Join the service's run thread and destroy the service off the
            // RPC handler's AsyncWaitSet thread (avoids level-nesting deadlock).
            // Keep the slot so the status polling loop can detect the STOPPED
            // transition and publish ServiceStatus. start_service clears
            // stale STOPPED/FAILED slots before creating a new service.
            {
                auto& slot_ref = slot_it->second;
                std::thread joiner([&slot_ref]() {
                    if (slot_ref.thread.joinable()) {
                        slot_ref.thread.join();
                    }
                });
                joiner.join();
            }
        }

        result.code = Orchestration::OperationResultCode::OK;
        result.message = "Service stopped";
        log_.notice("stop_service: OK (service_id=" + svc_id + ")");

        procedure_ids_.erase(svc_id);
        catalog_dirty_.insert(svc_id);

        return result;
    }

    Orchestration::OperationResult update_service(
        const Orchestration::ServiceRequest& req) override
    {
        Orchestration::OperationResult result;
        result.code = Orchestration::OperationResultCode::OK;
        result.message = "Configuration accepted (no-op in V1.0)";
        log_.notice("update_service: OK (service_id="
            + std::string(req.service_id) + ")");
        return result;
    }

    Orchestration::CapabilityReport get_capabilities() override
    {
        Orchestration::CapabilityReport report;
        report.capacity = capacity_;
        log_.notice("get_capabilities: capacity="
            + std::to_string(capacity_));
        return report;
    }

    Orchestration::HealthReport get_health() override
    {
        Orchestration::HealthReport report;
        report.alive = true;

        std::lock_guard<std::mutex> lock(mu_);
        if (slots_.empty()) {
            report.summary = "No services running";
        } else {
            std::string summary;
            for (const auto& [id, slot] : slots_) {
                if (!summary.empty()) summary += "; ";
                summary += id + ": "
                    + std::to_string(
                          static_cast<int>(slot.service->state()));
            }
            report.summary = summary;
        }
        report.diagnostics = "";
        return report;
    }

    /// Return current state for every running service (for status polling).
    ServiceStateMap service_states() const
    {
        std::lock_guard<std::mutex> lock(mu_);
        ServiceStateMap states;
        for (const auto& [id, slot] : slots_) {
            states[id] = slot.service->state();
        }
        return states;
    }

    /// Return registry-registered service IDs (for initial status publish).
    std::vector<Common::EntityId> registered_service_ids() const
    {
        std::vector<Common::EntityId> ids;
        ids.reserve(registry_.size());
        for (const auto& [name, _] : registry_) {
            ids.push_back(name);
        }
        return ids;
    }

    /// Read-only access to the registry for catalog publishing.
    const ServiceRegistryMap& registry() const
    {
        return registry_;
    }

    /// Stop all running services (called during host shutdown).
    void stop_all()
    {
        std::lock_guard<std::mutex> lock(mu_);
        for (auto& [id, slot] : slots_) {
            slot.service->stop();
        }
        for (auto& [id, slot] : slots_) {
            if (slot.thread.joinable()) {
                slot.thread.join();
            }
        }
        slots_.clear();
    }

    /// Atomically return and clear the set of services needing catalog re-publish.
    std::set<Common::EntityId> pop_catalog_dirty()
    {
        std::lock_guard<std::mutex> lock(mu_);
        std::set<Common::EntityId> result;
        result.swap(catalog_dirty_);
        return result;
    }

    /// Return the current procedure_id for a service (empty if none).
    std::string procedure_id(const Common::EntityId& svc_id) const
    {
        std::lock_guard<std::mutex> lock(mu_);
        auto it = procedure_ids_.find(svc_id);
        return (it != procedure_ids_.end()) ? it->second : "";
    }

    /// Return gui_urls for a running service (empty vector if not found/stopped).
    std::vector<std::string> gui_urls_for(const Common::EntityId& svc_id) const
    {
        std::lock_guard<std::mutex> lock(mu_);
        auto it = slots_.find(svc_id);
        if (it == slots_.end() || it->second.service == nullptr) {
            return {};
        }
        return it->second.service->gui_urls();
    }

private:
    std::string host_id_;
    int32_t capacity_;
    ServiceRegistryMap registry_;
    ModuleLogger& log_;

    mutable std::mutex mu_;
    ServiceSlotMap slots_;
    std::unordered_map<Common::EntityId, std::string> procedure_ids_;
    std::set<Common::EntityId> catalog_dirty_;
};


// ---------------------------------------------------------------------------
// ServiceHost — generic medtech::Service that wraps the orchestration layer.
//
// Creates an Orchestration domain participant, registers the RPC service,
// publishes ServiceCatalog and ServiceStatus, and blocks in run().
// Configured via ServiceRegistryMap — the only variation point between
// robot, clinical, and operational service hosts.
// ---------------------------------------------------------------------------
class ServiceHost : public Service {
public:
    ServiceHost(
        const std::string& host_id,
        const std::string& host_name,
        int32_t capacity,
        ServiceRegistryMap registry,
        ModuleLogger& log)
        : host_id_(host_id),
          host_name_(host_name),
          capacity_(capacity),
          log_(log),
          svc_state_(Orchestration::ServiceState::STOPPED)
    {
        // -- Create Orchestration domain participant from XML --
        initialize_connext();
        auto provider = dds::core::QosProvider::Default();
        orch_participant_ = provider.extensions()
            .create_participant_from_config(
                std::string(orch_names::ORCHESTRATION));

        // Set tier partition BEFORE enable() — static deployment-time property
        {
            auto dp_qos = orch_participant_.qos();
            dp_qos << dds::core::policy::Partition(std::string("procedure"));
            orch_participant_.qos(dp_qos);
        }

        // Read room context from environment
        const char* room_env = std::getenv("ROOM_ID");
        room_id_ = (room_env != nullptr) ? room_env : "";

        log_.notice("Orchestration participant created");

        // -- Look up pub/sub entities --
        catalog_writer_ =
            rti::pub::find_datawriter_by_name<
                dds::pub::DataWriter<Orchestration::ServiceCatalog>>(
                orch_participant_,
                std::string(orch_names::SERVICE_CATALOG_WRITER));

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
            host_id,
            capacity, std::move(registry), log);
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

        // -- Publish initial ServiceCatalog (one instance per service) --
        publish_service_catalog();

        // -- Publish initial ServiceStatus (STOPPED) for each service --
        for (const auto& svc_id : rpc_impl_->registered_service_ids()) {
            publish_service_status(svc_id,
                Orchestration::ServiceState::STOPPED);
        }

        svc_state_.store(Orchestration::ServiceState::RUNNING,
                         std::memory_order_release);
        log_.notice(host_name_ + " running (host_id=" + host_id_ + ")");

        // -- Status polling loop --
        ServiceStateMap last_published_states;
        while (running_.load(std::memory_order_relaxed)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));

            auto states = rpc_impl_->service_states();
            for (const auto& [svc_id, state] : states) {
                auto it = last_published_states.find(svc_id);
                if (it == last_published_states.end()
                    || it->second != state) {
                    publish_service_status(svc_id, state);
                    last_published_states[svc_id] = state;

                    // On RUNNING: capture gui_url and mark catalog dirty
                    if (state == Orchestration::ServiceState::RUNNING) {
                        auto urls = rpc_impl_->gui_urls_for(svc_id);
                        gui_urls_[svc_id] = urls.empty() ? "" : urls[0];
                        rpc_impl_->pop_catalog_dirty();  // discard stale dirty entry
                        publish_service_catalog_for(svc_id);
                    } else if (state == Orchestration::ServiceState::STOPPED
                               || state == Orchestration::ServiceState::FAILED) {
                        gui_urls_.erase(svc_id);
                    }
                }
            }

            // Re-publish catalog for start/stop property changes
            auto dirty = rpc_impl_->pop_catalog_dirty();
            for (const auto& svc_id : dirty) {
                publish_service_catalog_for(svc_id);
            }
        }

        // -- Shutdown --
        svc_state_.store(Orchestration::ServiceState::STOPPING,
                         std::memory_order_release);
        log_.notice(host_name_ + " shutting down");

        // Stop all hosted services before tearing down RPC
        rpc_impl_->stop_all();

        // Release RPC references — RAII cleanup via reference counting.
        rpc_service_.reset();
        rpc_server_ = dds::core::null;

        svc_state_.store(Orchestration::ServiceState::STOPPED,
                         std::memory_order_release);
    }

    void stop() override
    {
        running_.store(false, std::memory_order_release);
    }

    std::string_view name() const override
    {
        return host_name_;
    }

    Orchestration::ServiceState state() const override
    {
        return svc_state_.load(std::memory_order_acquire);
    }

private:
    void publish_service_catalog()
    {
        for (const auto& [svc_id, reg] : rpc_impl_->registry()) {
            publish_service_catalog_for(svc_id);
        }
    }

    void publish_service_catalog_for(const Common::EntityId& svc_id)
    {
        const auto& registry = rpc_impl_->registry();
        auto reg_it = registry.find(svc_id);
        if (reg_it == registry.end()) return;
        const auto& reg = reg_it->second;

        Orchestration::ServiceCatalog catalog;
        catalog.host_id = host_id_;
        catalog.service_id = svc_id;
        catalog.display_name = reg.display_name;

        // Start with registered static properties
        for (const auto& pd : reg.properties) {
            catalog.properties.push_back(pd);
        }

        // room_id — static host context
        if (!room_id_.empty()) {
            Orchestration::PropertyDescriptor room_prop;
            room_prop.name = "room_id";
            room_prop.current_value = room_id_;
            room_prop.description = "Operating room identifier";
            room_prop.required = false;
            catalog.properties.push_back(room_prop);
        }

        // procedure_id — set when service is deployed in a procedure
        std::string procedure_id = rpc_impl_->procedure_id(svc_id);
        if (!procedure_id.empty()) {
            Orchestration::PropertyDescriptor proc_prop;
            proc_prop.name = "procedure_id";
            proc_prop.current_value = procedure_id;
            proc_prop.description = "Procedure this service is deployed in";
            proc_prop.required = false;
            catalog.properties.push_back(proc_prop);
        }

        // gui_url — non-empty only for RUNNING GUI services
        auto gui_it = gui_urls_.find(svc_id);
        if (gui_it != gui_urls_.end() && !gui_it->second.empty()) {
            Orchestration::PropertyDescriptor gui_prop;
            gui_prop.name = "gui_url";
            gui_prop.current_value = gui_it->second;
            gui_prop.description = "GUI endpoint URL";
            gui_prop.required = false;
            catalog.properties.push_back(gui_prop);
        }

        catalog.health_summary = "OK";
        catalog_writer_.write(catalog);
        log_.notice("Published ServiceCatalog for "
            + host_id_ + "/" + svc_id);
    }

    void publish_service_status(
        const Common::EntityId& service_id,
        Orchestration::ServiceState svc_state)
    {
        Orchestration::ServiceStatus status;
        status.host_id = host_id_;
        status.service_id = service_id;
        status.state = svc_state;

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
            + " for " + service_id);
    }

    // Configuration
    std::string host_id_;
    std::string host_name_;
    std::string room_id_;
    int32_t capacity_;
    ModuleLogger& log_;

    // Runtime service URL cache (svc_id -> first gui_url, empty if none)
    std::unordered_map<Common::EntityId, std::string> gui_urls_;

    // Lifecycle
    std::atomic<bool> running_{true};
    std::atomic<Orchestration::ServiceState> svc_state_{
        Orchestration::ServiceState::STOPPED};

    // Orchestration domain
    dds::domain::DomainParticipant orch_participant_{nullptr};
    dds::pub::DataWriter<Orchestration::ServiceCatalog> catalog_writer_{nullptr};
    dds::pub::DataWriter<Orchestration::ServiceStatus> status_writer_{nullptr};

    // RPC
    std::shared_ptr<ServiceHostControlImpl> rpc_impl_;
    dds::rpc::Server rpc_server_{nullptr};
    std::unique_ptr<Orchestration::ServiceHostControlService> rpc_service_;
};

}  // anonymous namespace

// ---------------------------------------------------------------------------
// Factory implementation — called by the make_service_host<N> template.
// ---------------------------------------------------------------------------
std::unique_ptr<Service> make_service_host_impl(
    const std::string& host_id,
    const std::string& host_name,
    int32_t capacity,
    ServiceRegistryMap registry,
    ModuleLogger& log)
{
    return std::make_unique<ServiceHost>(
        host_id, host_name,
        capacity, std::move(registry), log);
}

}  // namespace medtech
