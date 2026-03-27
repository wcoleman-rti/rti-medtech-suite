// test_service.cpp — Unit tests for medtech::Service abstract interface.
//
// A MockService implements the interface and verifies state transitions:
//   STOPPED → STARTING → RUNNING → (stop) → STOPPING → STOPPED
//   STOPPED → STARTING → FAILED (on simulated error)
// Also verifies stop() is non-blocking while run() is in progress.

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <stdexcept>
#include <thread>

#include <gtest/gtest.h>
#include <medtech/service.hpp>

class MockService : public medtech::Service {
public:
    explicit MockService(bool simulate_failure = false)
        : simulate_failure_(simulate_failure)
    {
    }

    void run() override
    {
        state_.store(Orchestration::ServiceState::STARTING);

        if (simulate_failure_) {
            state_.store(Orchestration::ServiceState::FAILED);
            return;
        }

        state_.store(Orchestration::ServiceState::RUNNING);

        // Block until stop() is called
        std::unique_lock lock(mtx_);
        cv_.wait(lock, [this] { return stop_requested_.load(); });

        state_.store(Orchestration::ServiceState::STOPPING);
        // simulate teardown
        state_.store(Orchestration::ServiceState::STOPPED);
    }

    void stop() override
    {
        stop_requested_.store(true);
        cv_.notify_all();
    }

    std::string_view name() const override { return "MockService"; }

    Orchestration::ServiceState state() const override
    {
        return state_.load();
    }

private:
    std::atomic<Orchestration::ServiceState> state_{
        Orchestration::ServiceState::STOPPED};
    std::atomic<bool> stop_requested_{false};
    bool simulate_failure_;
    std::mutex mtx_;
    std::condition_variable cv_;
};

TEST(ServiceInterface, InitialStateIsStopped)
{
    MockService svc;
    EXPECT_EQ(svc.state(), Orchestration::ServiceState::STOPPED);
}

TEST(ServiceInterface, NameIsStable)
{
    MockService svc;
    auto n1 = svc.name();
    auto n2 = svc.name();
    EXPECT_EQ(n1, n2);
    EXPECT_FALSE(n1.empty());
}

TEST(ServiceInterface, FullLifecycleTransitions)
{
    MockService svc;
    EXPECT_EQ(svc.state(), Orchestration::ServiceState::STOPPED);

    // Run in a separate thread
    std::thread runner([&svc] { svc.run(); });

    // Wait for RUNNING state (with timeout)
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (svc.state() != Orchestration::ServiceState::RUNNING) {
        ASSERT_LT(std::chrono::steady_clock::now(), deadline)
            << "Timed out waiting for RUNNING state";
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }

    EXPECT_EQ(svc.state(), Orchestration::ServiceState::RUNNING);

    // Stop the service
    svc.stop();
    runner.join();

    EXPECT_EQ(svc.state(), Orchestration::ServiceState::STOPPED);
}

TEST(ServiceInterface, StopIsNonBlocking)
{
    MockService svc;
    std::thread runner([&svc] { svc.run(); });

    // Wait for RUNNING
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (svc.state() != Orchestration::ServiceState::RUNNING) {
        ASSERT_LT(std::chrono::steady_clock::now(), deadline);
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }

    // Measure stop() duration — must return within 100ms
    auto start = std::chrono::steady_clock::now();
    svc.stop();
    auto elapsed = std::chrono::steady_clock::now() - start;

    EXPECT_LT(elapsed, std::chrono::milliseconds(100))
        << "stop() blocked for too long";

    runner.join();
}

TEST(ServiceInterface, FailedStateOnError)
{
    MockService svc(/*simulate_failure=*/true);
    EXPECT_EQ(svc.state(), Orchestration::ServiceState::STOPPED);

    svc.run();  // returns after setting FAILED

    EXPECT_EQ(svc.state(), Orchestration::ServiceState::FAILED);
}
