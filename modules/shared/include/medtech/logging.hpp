// medtech/logging.hpp — Shared logging initialization for RTI Connext modules.
//
// Verbosity is configured entirely via QoS XML (participant_factory_qos
// LOGGING policy). This header never sets verbosity programmatically.
//
// All log messages are routed through ModuleLogger, a thin wrapper
// around rti::config::Logger that auto-prefixes messages with the
// module name. If the logging backend is swapped in the future, only
// this header needs to change — call sites remain untouched.

#ifndef MEDTECH_LOGGING_HPP
#define MEDTECH_LOGGING_HPP

#include <stdexcept>
#include <string>
#include <string_view>
#include <rti/config/Logger.hpp>

namespace medtech {

// Recognised module names — values match module directory names.
enum class ModuleName {
    SurgicalProcedure,
    HospitalDashboard,
    ClinicalAlerts,
};

inline constexpr std::string_view to_string(ModuleName m) noexcept
{
    switch (m) {
    case ModuleName::SurgicalProcedure: return "surgical-procedure";
    case ModuleName::HospitalDashboard: return "hospital-dashboard";
    case ModuleName::ClinicalAlerts:    return "clinical-alerts";
    }
    return "unknown";  // unreachable — silences compiler warning
}

// Thin wrapper around rti::config::Logger that auto-prefixes messages.
// Swapping the backend means changing only this class.
class ModuleLogger {
public:
    explicit ModuleLogger(ModuleName name)
        : prefix_(std::string("[") + std::string(to_string(name)) + "] ")
        , logger_(rti::config::Logger::instance())
    {
    }

    void emergency(const std::string& msg)     { logger_.emergency((prefix_ + msg).c_str()); }
    void alert(const std::string& msg)         { logger_.alert((prefix_ + msg).c_str()); }
    void critical(const std::string& msg)      { logger_.critical((prefix_ + msg).c_str()); }
    void error(const std::string& msg)         { logger_.error((prefix_ + msg).c_str()); }
    void warning(const std::string& msg)       { logger_.warning((prefix_ + msg).c_str()); }
    void notice(const std::string& msg)        { logger_.notice((prefix_ + msg).c_str()); }
    void informational(const std::string& msg) { logger_.informational((prefix_ + msg).c_str()); }
    void debug(const std::string& msg)         { logger_.debug((prefix_ + msg).c_str()); }

private:
    std::string prefix_;
    rti::config::Logger& logger_;
};

inline ModuleLogger init_logging(ModuleName name)
{
    return ModuleLogger(name);
}

}  // namespace medtech

#endif  // MEDTECH_LOGGING_HPP
