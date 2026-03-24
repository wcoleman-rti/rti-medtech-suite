"""Step 1.3 Test Gate — Validate QoS XML loading via Python default QosProvider.

Verifies that all QoS XML files load correctly via NDDS_QOS_PROFILES,
snippet/pattern/topic profiles resolve, and topic-filter QoS resolution
returns the expected policy values.

Python API methods (confirmed via rti-chatbot-mcp, INC-003):
    Named profile:      datawriter_qos_from_profile(profile)
    Topic + profile:    set_topic_datawriter_qos(profile, topic_name)
    Topic + default:    get_topic_datawriter_qos(topic_name)
    Participant:        participant_qos_from_profile(profile)
"""

import os

import pytest
import rti.connextdds as dds


@pytest.fixture(autouse=True)
def _check_env():
    """Ensure NDDS_QOS_PROFILES is set before any test runs."""
    assert os.environ.get(
        "NDDS_QOS_PROFILES"
    ), "NDDS_QOS_PROFILES not set — source install/setup.bash first"


@pytest.fixture
def provider():
    """Return the default QosProvider (loads from NDDS_QOS_PROFILES)."""
    return dds.QosProvider.default


# --- Snippets ---


class TestSnippets:
    def test_reliable(self, provider):
        qos = provider.datawriter_qos_from_profile("Snippets::Reliable")
        assert qos.reliability.kind == dds.ReliabilityKind.RELIABLE

    def test_best_effort(self, provider):
        qos = provider.datawriter_qos_from_profile("Snippets::BestEffort")
        assert qos.reliability.kind == dds.ReliabilityKind.BEST_EFFORT

    def test_transient_local(self, provider):
        qos = provider.datawriter_qos_from_profile("Snippets::TransientLocal")
        assert qos.durability.kind == dds.DurabilityKind.TRANSIENT_LOCAL

    def test_volatile(self, provider):
        qos = provider.datawriter_qos_from_profile("Snippets::Volatile")
        assert qos.durability.kind == dds.DurabilityKind.VOLATILE

    def test_keep_last_1(self, provider):
        qos = provider.datawriter_qos_from_profile("Snippets::KeepLast1")
        assert qos.history.kind == dds.HistoryKind.KEEP_LAST
        assert qos.history.depth == 1

    def test_keep_last_4(self, provider):
        qos = provider.datawriter_qos_from_profile("Snippets::KeepLast4")
        assert qos.history.depth == 4

    def test_keep_all(self, provider):
        qos = provider.datawriter_qos_from_profile("Snippets::KeepAll")
        assert qos.history.kind == dds.HistoryKind.KEEP_ALL


# --- Patterns ---


class TestPatterns:
    def test_state_writer(self, provider):
        qos = provider.datawriter_qos_from_profile("Patterns::State")
        assert qos.reliability.kind == dds.ReliabilityKind.RELIABLE
        assert qos.durability.kind == dds.DurabilityKind.TRANSIENT_LOCAL
        assert qos.history.depth == 1

    def test_command_writer(self, provider):
        qos = provider.datawriter_qos_from_profile("Patterns::Command")
        assert qos.reliability.kind == dds.ReliabilityKind.RELIABLE
        assert qos.durability.kind == dds.DurabilityKind.VOLATILE

    def test_stream_writer(self, provider):
        qos = provider.datawriter_qos_from_profile("Patterns::Stream")
        assert qos.reliability.kind == dds.ReliabilityKind.BEST_EFFORT
        assert qos.history.depth == 4


# --- Topic-filter QoS resolution (named profile) ---


class TestTopicFilters:
    def test_patient_vitals_writer(self, provider):
        """PatientVitals: State base + Deadline2s override."""
        qos = provider.set_topic_datawriter_qos(
            "Topics::ProcedureTopics", "PatientVitals"
        )
        assert qos.reliability.kind == dds.ReliabilityKind.RELIABLE
        assert qos.durability.kind == dds.DurabilityKind.TRANSIENT_LOCAL
        assert qos.deadline.period.sec == 2

    def test_patient_vitals_reader(self, provider):
        qos = provider.set_topic_datareader_qos(
            "Topics::ProcedureTopics", "PatientVitals"
        )
        assert qos.reliability.kind == dds.ReliabilityKind.RELIABLE
        assert qos.deadline.period.sec == 2

    def test_operator_input_writer(self, provider):
        """OperatorInput: BestEffort + KeepLast4 + Deadline4ms + Lifespan20ms."""
        qos = provider.set_topic_datawriter_qos(
            "Topics::ProcedureTopics", "OperatorInput"
        )
        assert qos.reliability.kind == dds.ReliabilityKind.BEST_EFFORT
        assert qos.history.depth == 4
        assert qos.deadline.period.nanosec == 4000000

    def test_robot_command_writer(self, provider):
        """RobotCommand: Command pattern → Reliable + Volatile."""
        qos = provider.set_topic_datawriter_qos(
            "Topics::ProcedureTopics", "RobotCommand"
        )
        assert qos.durability.kind == dds.DurabilityKind.VOLATILE

    def test_robot_state_writer(self, provider):
        """RobotState: State base + Deadline20ms."""
        qos = provider.set_topic_datawriter_qos("Topics::ProcedureTopics", "RobotState")
        assert qos.reliability.kind == dds.ReliabilityKind.RELIABLE
        assert qos.deadline.period.nanosec == 20000000

    def test_camera_frame_writer(self, provider):
        """CameraFrame: Stream + Deadline66ms."""
        qos = provider.set_topic_datawriter_qos(
            "Topics::ProcedureTopics", "CameraFrame"
        )
        assert qos.reliability.kind == dds.ReliabilityKind.BEST_EFFORT
        assert qos.deadline.period.nanosec == 66000000

    def test_waveform_data_writer(self, provider):
        """WaveformData: Stream + Deadline40ms."""
        qos = provider.set_topic_datawriter_qos(
            "Topics::ProcedureTopics", "WaveformData"
        )
        assert qos.reliability.kind == dds.ReliabilityKind.BEST_EFFORT
        assert qos.deadline.period.nanosec == 40000000


# --- Participant profiles ---


class TestParticipants:
    def test_simulation_transport_loads(self, provider):
        qos = provider.participant_qos_from_profile("Participants::SimulationTransport")
        assert qos is not None

    def test_factory_defaults_loads(self, provider):
        qos = provider.participant_qos_from_profile("Participants::FactoryDefaults")
        assert qos is not None
        assert qos is not None
