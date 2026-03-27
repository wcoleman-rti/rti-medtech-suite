// medtech/service_host.hpp — Generic Service Host for orchestration.
//
// Provides the reusable ServiceHost<Capacity> template and supporting
// types that all concrete service hosts (robot, clinical, operational)
// share.  A concrete host only needs to register its service factories
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
// Accepts the service's Common::EntityId so the host can pass the
// managed identity to each service it creates.  All other context
// (room_id, procedure_id, device IDs, logger, …) is captured in the
// closure at registration time.
// ---------------------------------------------------------------------------
using ServiceFactory =
    std::function<std::unique_ptr<Service>(const Common::EntityId&)>;

// Factory map keyed by Common::EntityId (== std::string, bounded by
// MAX_ID_LENGTH in the IDL).  Each entry is a named service that this
// host can start/stop via RPC.
using ServiceFactoryMap = std::unordered_map<Common::EntityId, ServiceFactory>;

// Per-service snapshot returned by the RPC impl for status polling.
using ServiceStateMap = std::unordered_map<Common::EntityId,
                                           Orchestration::ServiceState>;

// ---------------------------------------------------------------------------
// make_service_host<Capacity> — compile-time factory-count enforcement.
//
// Capacity is the maximum number of services this host advertises in its
// HostCatalog.  The factory map size is validated at construction time
// via a static_assert-friendly template plus a runtime check.
//
// Usage:
//   ServiceFactoryMap factories;
//   factories["RobotControllerService"] = [=, &log](const auto& id) {
//       return make_robot_controller_service(id, room_id, proc_id, log);
//   };
//   auto host = medtech::make_service_host<1>(
//       host_id, "RobotServiceHost",
//       std::move(factories), log);
// ---------------------------------------------------------------------------

// Forward — defined in service_host.cpp.
std::unique_ptr<Service> make_service_host_impl(
    const std::string& host_id,
    const std::string& host_name,
    int32_t capacity,
    ServiceFactoryMap factories,
    ModuleLogger& log);

/// Create a typed service host.  `Capacity` is the compile-time upper
/// bound on registered factories (matches CapabilityReport.capacity).
template <int32_t Capacity>
std::unique_ptr<Service> make_service_host(
    const std::string& host_id,
    const std::string& host_name,
    ServiceFactoryMap factories,
    ModuleLogger& log)
{
    static_assert(Capacity > 0, "ServiceHost capacity must be positive");
    if (static_cast<int32_t>(factories.size()) > Capacity) {
        throw std::invalid_argument(
            "ServiceHost<" + std::to_string(Capacity) + ">: registered "
            + std::to_string(factories.size()) + " factories — exceeds capacity");
    }
    return make_service_host_impl(
        host_id, host_name,
        Capacity, std::move(factories), log);
}

}  // namespace medtech

#endif  // MEDTECH_SERVICE_HOST_HPP
