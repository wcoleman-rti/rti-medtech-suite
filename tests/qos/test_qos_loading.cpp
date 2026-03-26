/**
 * @file test_qos_loading.cpp
 * @brief Step 1.3 Test Gate — Validate QoS XML loading via default QosProvider.
 *
 * Verifies that all QoS XML files load correctly via NDDS_QOS_PROFILES,
 * snippet/pattern/topic profiles resolve, and topic-filter QoS resolution
 * returns the expected policy values.
 *
 * RTI Extension API (INC-003):
 *   provider->datawriter_qos_w_topic_name(profile, topic_name)
 *   provider->datareader_qos_w_topic_name(profile, topic_name)
 */

#include <gtest/gtest.h>
#include <dds/core/QosProvider.hpp>
#include <dds/pub/qos/DataWriterQos.hpp>
#include <dds/sub/qos/DataReaderQos.hpp>

class QosLoadingTest : public ::testing::Test {
protected:
    dds::core::QosProvider provider_{dds::core::QosProvider::Default()};
};

// --- Snippets: isolated policy chunks ---

TEST_F(QosLoadingTest, SnippetReliable) {
    auto qos = provider_.datawriter_qos("BuiltinQosSnippetLib::QosPolicy.Reliability.Reliable");
    auto kind = qos.policy<dds::core::policy::Reliability>().kind();
    EXPECT_EQ(kind, dds::core::policy::ReliabilityKind::RELIABLE);
}

TEST_F(QosLoadingTest, SnippetBestEffort) {
    auto qos = provider_.datawriter_qos("BuiltinQosSnippetLib::QosPolicy.Reliability.BestEffort");
    auto kind = qos.policy<dds::core::policy::Reliability>().kind();
    EXPECT_EQ(kind, dds::core::policy::ReliabilityKind::BEST_EFFORT);
}

TEST_F(QosLoadingTest, SnippetTransientLocal) {
    auto qos = provider_.datawriter_qos("BuiltinQosSnippetLib::QosPolicy.Durability.TransientLocal");
    auto kind = qos.policy<dds::core::policy::Durability>().kind();
    EXPECT_EQ(kind, dds::core::policy::DurabilityKind::TRANSIENT_LOCAL);
}

TEST_F(QosLoadingTest, SnippetVolatile) {
    auto qos = provider_.datawriter_qos("Snippets::Volatile");
    auto kind = qos.policy<dds::core::policy::Durability>().kind();
    EXPECT_EQ(kind, dds::core::policy::DurabilityKind::VOLATILE);
}

TEST_F(QosLoadingTest, SnippetKeepLast1) {
    auto qos = provider_.datawriter_qos("BuiltinQosSnippetLib::QosPolicy.History.KeepLast_1");
    auto hist = qos.policy<dds::core::policy::History>();
    EXPECT_EQ(hist.kind(), dds::core::policy::HistoryKind::KEEP_LAST);
    EXPECT_EQ(hist.depth(), 1);
}

TEST_F(QosLoadingTest, SnippetKeepAll) {
    auto qos = provider_.datawriter_qos("BuiltinQosSnippetLib::QosPolicy.History.KeepAll");
    auto kind = qos.policy<dds::core::policy::History>().kind();
    EXPECT_EQ(kind, dds::core::policy::HistoryKind::KEEP_ALL);
}

// --- Patterns: composite base profiles ---

TEST_F(QosLoadingTest, PatternStateWriter) {
    auto qos = provider_.datawriter_qos("Patterns::State");
    auto rel = qos.policy<dds::core::policy::Reliability>().kind();
    auto dur = qos.policy<dds::core::policy::Durability>().kind();
    auto depth = qos.policy<dds::core::policy::History>().depth();
    EXPECT_EQ(rel, dds::core::policy::ReliabilityKind::RELIABLE);
    EXPECT_EQ(dur, dds::core::policy::DurabilityKind::TRANSIENT_LOCAL);
    EXPECT_EQ(depth, 1);
}

TEST_F(QosLoadingTest, PatternCommandWriter) {
    auto qos = provider_.datawriter_qos("Patterns::Command");
    auto rel = qos.policy<dds::core::policy::Reliability>().kind();
    auto dur = qos.policy<dds::core::policy::Durability>().kind();
    EXPECT_EQ(rel, dds::core::policy::ReliabilityKind::RELIABLE);
    EXPECT_EQ(dur, dds::core::policy::DurabilityKind::VOLATILE);
}

TEST_F(QosLoadingTest, PatternStreamWriter) {
    auto qos = provider_.datawriter_qos("Patterns::Stream");
    auto rel = qos.policy<dds::core::policy::Reliability>().kind();
    auto depth = qos.policy<dds::core::policy::History>().depth();
    EXPECT_EQ(rel, dds::core::policy::ReliabilityKind::BEST_EFFORT);
    EXPECT_EQ(depth, 1);
}

// --- Topics: topic-filter-bound QoS resolution (RTI extension API) ---

TEST_F(QosLoadingTest, TopicFilterPatientVitals) {
    auto qos = provider_->datawriter_qos_w_topic_name(
        "Topics::ProcedureTopics", "PatientVitals");
    auto rel = qos.policy<dds::core::policy::Reliability>().kind();
    auto dur = qos.policy<dds::core::policy::Durability>().kind();
    auto deadline_sec = qos.policy<dds::core::policy::Deadline>().period().sec();
    EXPECT_EQ(rel, dds::core::policy::ReliabilityKind::RELIABLE);
    EXPECT_EQ(dur, dds::core::policy::DurabilityKind::TRANSIENT_LOCAL);
    EXPECT_EQ(deadline_sec, 2);
}

TEST_F(QosLoadingTest, TopicFilterOperatorInput) {
    auto qos = provider_->datawriter_qos_w_topic_name(
        "Topics::ProcedureTopics", "OperatorInput");
    auto rel = qos.policy<dds::core::policy::Reliability>().kind();
    auto depth = qos.policy<dds::core::policy::History>().depth();
    auto deadline_ns = qos.policy<dds::core::policy::Deadline>().period().nanosec();
    EXPECT_EQ(rel, dds::core::policy::ReliabilityKind::BEST_EFFORT);
    EXPECT_EQ(depth, 1);
    EXPECT_EQ(deadline_ns, 4000000u);
}

TEST_F(QosLoadingTest, TopicFilterRobotCommand) {
    auto qos = provider_->datawriter_qos_w_topic_name(
        "Topics::ProcedureTopics", "RobotCommand");
    auto dur = qos.policy<dds::core::policy::Durability>().kind();
    EXPECT_EQ(dur, dds::core::policy::DurabilityKind::VOLATILE);
}

// --- Participant profiles ---

TEST_F(QosLoadingTest, ParticipantTransport) {
    auto qos = provider_.participant_qos("Participants::Transport");
    (void)qos; // Loading without error is the test
}

TEST_F(QosLoadingTest, ParticipantFactoryDefaults) {
    auto qos = provider_.participant_qos("Factory::FactoryDefaults");
    (void)qos;
}
