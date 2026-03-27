// main.cpp — Robot Service Host executable entry point.
//
// Reads environment variables, wires signal handling, and runs
// the RobotServiceHost via the medtech::Service interface.

#include <csignal>
#include <cstdlib>
#include <memory>
#include <string>

#include "medtech/logging.hpp"
#include "robot_service_host.hpp"

namespace {

medtech::Service* g_svc_ptr = nullptr;

void signal_handler(int /*sig*/)
{
    if (g_svc_ptr != nullptr) {
        g_svc_ptr->stop();
    }
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
        const std::string host_id = env_or("HOST_ID", "robot-host-or1");
        const std::string room_id = env_or("ROOM_ID", "OR-1");
        const std::string procedure_id = env_or("PROCEDURE_ID", "proc-001");

        auto svc = medtech::surgical::make_robot_service_host(
            host_id, room_id, procedure_id, log);
        g_svc_ptr = svc.get();
        svc->run();
        g_svc_ptr = nullptr;
        return 0;
    } catch (const std::exception& ex) {
        log.error(std::string("Fatal: ") + ex.what());
        return 1;
    }
}
