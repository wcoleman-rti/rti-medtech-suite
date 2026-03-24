#include <gtest/gtest.h>
#include <medtech/logging.hpp>

TEST(InitLogging, SurgicalProcedure)
{
    auto log = medtech::init_logging(medtech::ModuleName::SurgicalProcedure);
    // Verify the logger can write without error.
    log.notice("C++ test — surgical-procedure notice");
}

TEST(InitLogging, HospitalDashboard)
{
    auto log = medtech::init_logging(medtech::ModuleName::HospitalDashboard);
    log.notice("C++ test — hospital-dashboard notice");
}

TEST(InitLogging, ClinicalAlerts)
{
    auto log = medtech::init_logging(medtech::ModuleName::ClinicalAlerts);
    log.notice("C++ test — clinical-alerts notice");
}

TEST(ModuleName, ToString)
{
    EXPECT_EQ(medtech::to_string(medtech::ModuleName::SurgicalProcedure),
              "surgical-procedure");
    EXPECT_EQ(medtech::to_string(medtech::ModuleName::HospitalDashboard),
              "hospital-dashboard");
    EXPECT_EQ(medtech::to_string(medtech::ModuleName::ClinicalAlerts),
              "clinical-alerts");
}

TEST(ModuleLogger, AllLevels)
{
    auto log = medtech::init_logging(medtech::ModuleName::SurgicalProcedure);
    // All severity methods must compile and execute without error.
    log.emergency("test emergency");
    log.alert("test alert");
    log.critical("test critical");
    log.error("test error");
    log.warning("test warning");
    log.notice("test notice");
    log.informational("test informational");
    log.debug("test debug");
}
