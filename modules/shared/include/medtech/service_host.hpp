// medtech/service_host.hpp — Generic Service Host for orchestration.
//
// Provides the reusable ServiceHost<Capacity> template and supporting
// types that all concrete service hosts (robot, clinical, operational)
// share.  A concrete host only needs to register its service entries
// and call make_service_host<N>().
//
// C++ and Python service host implementations mirror this structure:
//   C++ — ServiceHost<N>   (this file + service_host.cpp)
//   Py  — ServiceHost(N)   (modules/shared/medtech/service_host.py)
//
// Key types are keyed by Common::EntityId for IDL consistency.

#ifndef MEDTECH_SERVICE_HOST_HPP
#define MEDTECH_SERVICE_HOST_HPP

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

#include <common/common.hpp>
#include <orchestration/orchestration.hpp>

#include "medtech/logging.hpp"
#include "medtech/service.hpp"

namespace medtech {

// ---------------------------------------------------------------------------
// ServiceFactory — creates a medtech::Service.
//
// Accepts the full Orchestration::ServiceRequest so the host can pass
// both the service_id and any configuration properties to each service
// it creates.  All other context (room_id, procedure_id, device IDs,
// logger, …) is captured in the closure at registration time.
// ---------------------------------------------------------------------------
using ServiceFactory =
    std::function<std::unique_ptr<Service>(const Orchestration::ServiceRequest&)>;

// ---------------------------------------------------------------------------
// ServiceRegistration — bundles a factory with its catalog metadata.
//
// Each registered service provides:
//   - factory:     creates the Service instance
//   - display_name: human-readable name for the Procedure Controller UI
//   - properties:  configurable property descriptors (name, default,
//                  description, required) advertised in ServiceCatalog
// ---------------------------------------------------------------------------
struct ServiceRegistration {
    ServiceFactory factory;
    std::string display_name;
    std::vector<Orchestration::PropertyDescriptor> properties;
};

// Registry map keyed by service_id (Common::EntityId).  Each entry is
// a named service that this host can start/stop via RPC, together with
// the metadata published in ServiceCatalog.
using ServiceRegistryMap = std::unordered_map<Common::EntityId, ServiceRegistration>;

// Per-service snapshot returned by the RPC impl for status polling.
using ServiceStateMap = std::unordered_map<Common::EntityId,
                                           Orchestration::ServiceState>;

// ---------------------------------------------------------------------------
// make_service_host<Capacity> — compile-time factory-count enforcement.
//
// Capacity is the maximum number of services this host advertises in its
// ServiceCatalog.  The registry size is validated at construction time
// via a static_assert-friendly template plus a runtime check.
//
// Usage:
//   ServiceRegistryMap registry;
//   registry["RobotControllerService"] = {
//       .factory = [=, &log](const auto& req) {
//           return make_robot_controller_service(req, room_id, proc_id, log);
//       },
//       .display_name = "Robot Controller",
//       .properties = {},
//   };
//   auto host = medtech::make_service_host<1>(
//       host_id, "RobotServiceHost",
//       std::move(registry), log);
// ---------------------------------------------------------------------------

// Forward — defined in service_host.cpp.
std::unique_ptr<Service> make_service_host_impl(
    const std::string& host_id,
    const std::string& host_name,
    int32_t capacity,
    ServiceRegistryMap registry,
    ModuleLogger& log);

/// Create a typed service host.  `Capacity` is the compile-time upper
/// bound on registered services (matches CapabilityReport.capacity).
template <int32_t Capacity>
std::unique_ptr<Service> make_service_host(
    const std::string& host_id,
    const std::string& host_name,
    ServiceRegistryMap registry,
    ModuleLogger& log)
{
    static_assert(Capacity > 0, "ServiceHost capacity must be positive");
    if (static_cast<int32_t>(registry.size()) > Capacity) {
        throw std::invalid_argument(
            "ServiceHost<" + std::to_string(Capacity) + ">: registered "
            + std::to_string(registry.size()) + " services — exceeds capacity");
    }
    return make_service_host_impl(
        host_id, host_name,
        Capacity, std::move(registry), log);
}

}  // namespace medtech

#endif  // MEDTECH_SERVICE_HOST_HPP
