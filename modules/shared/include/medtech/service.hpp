// medtech/service.hpp — Abstract service interface for orchestration.
//
// All DDS service classes implement this interface. The Service Host
// framework uses it to manage services uniformly regardless of domain
// or internal complexity.
//
// ServiceState comes from the IDL-generated Orchestration module —
// no hand-written enum duplicate exists.

#ifndef MEDTECH_SERVICE_HPP
#define MEDTECH_SERVICE_HPP

#include <string>
#include <string_view>
#include <vector>

#include "orchestration/orchestration.hpp"

namespace medtech {

class Service {
public:
    virtual ~Service() = default;

    /// Run the service. Blocks the calling thread until stop() is called
    /// or an unrecoverable error occurs. The service manages its own
    /// internal concurrency — it must not assume any properties of the
    /// thread that calls run().
    virtual void run() = 0;

    /// Signal the service to stop. Thread-safe, non-blocking.
    /// run() must return promptly after stop() is called.
    virtual void stop() = 0;

    /// Service identifier for orchestration and logging.
    virtual std::string_view name() const = 0;

    /// Current lifecycle state. Polled by the Service Host for status
    /// reporting. Returns the IDL-generated Orchestration::ServiceState.
    virtual Orchestration::ServiceState state() const = 0;

    /// Return active GUI endpoint URLs for this service.
    ///
    /// GUI services override this to return the URL(s) served after the
    /// service transitions to RUNNING.  The Service Host publishes these
    /// in the ``gui_url`` ServiceCatalog property so the Procedure
    /// Controller can render an "Open" action button.
    ///
    /// Returns an empty vector for non-GUI services (default behavior).
    virtual std::vector<std::string> gui_urls() const
    {
        return {};
    }
};

}  // namespace medtech

#endif  // MEDTECH_SERVICE_HPP
