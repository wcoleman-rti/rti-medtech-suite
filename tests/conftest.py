"""Project-level pytest conftest.py — DDS fixtures for integration tests.

Provides reusable fixtures for creating DDS participants, writers, and readers
with automatic cleanup. Uses domain 0 for test isolation (reserved for testing
per vision/data-model.md). QoS profiles are loaded from NDDS_QOS_PROFILES.
"""

import os
import time

import pytest
import rti.connextdds as dds


@pytest.fixture(autouse=True, scope="session")
def _check_qos_env():
    """Ensure NDDS_QOS_PROFILES is set before any test session."""
    assert os.environ.get(
        "NDDS_QOS_PROFILES"
    ), "NDDS_QOS_PROFILES not set — source install/setup.bash first"


@pytest.fixture
def provider():
    """Return the default QosProvider."""
    return dds.QosProvider.default


def _make_participant(domain_id, domain_tag=None, partition=None, qos=None):
    """Create a DomainParticipant with optional domain tag and partition.

    Partition is set at the DomainParticipant level (Connext 7.x extension)
    to control participant-level visibility.

    The participant is created disabled (participant_factory_qos has
    autoenable_created_entities=false) and explicitly enabled after QoS
    configuration is complete.
    """
    if qos is None:
        qos = dds.DomainParticipant.default_participant_qos

    if domain_tag is not None:
        qos.property["dds.domain_participant.domain_tag"] = domain_tag

    if partition is not None:
        if isinstance(partition, str):
            partition = [partition]
        qos.partition.name = partition

    p = dds.DomainParticipant(domain_id, qos)
    p.enable()
    return p


@pytest.fixture
def participant_factory():
    """Factory fixture that creates participants and tracks them for cleanup.

    Usage:
        p = participant_factory(domain_id=0, domain_tag="control",
                                partition="room/OR-1")
    """
    participants = []

    def _create(domain_id=0, domain_tag=None, partition=None, qos=None):
        p = _make_participant(domain_id, domain_tag, partition, qos)
        participants.append(p)
        return p

    yield _create

    # Cleanup: close all participants in reverse order
    for p in reversed(participants):
        try:
            p.close()
        except dds.AlreadyClosedError:
            pass  # Participant was closed explicitly during the test


@pytest.fixture
def writer_factory():
    """Factory fixture that creates DataWriters.

    Usage:
        w = writer_factory(participant, topic, qos=writer_qos)
    """
    writers = []

    def _create(participant, topic, qos=None):
        pub = dds.Publisher(participant)
        if qos is None:
            qos = dds.DataWriterQos()
        w = dds.DataWriter(pub, topic, qos)
        writers.append(w)
        return w

    yield _create

    for w in reversed(writers):
        try:
            w.close()
        except dds.AlreadyClosedError:
            pass


@pytest.fixture
def reader_factory():
    """Factory fixture that creates DataReaders.

    Usage:
        r = reader_factory(participant, topic, qos=reader_qos)
    """
    readers = []

    def _create(participant, topic, qos=None):
        sub = dds.Subscriber(participant)
        if qos is None:
            qos = dds.DataReaderQos()
        r = dds.DataReader(sub, topic, qos)
        readers.append(r)
        return r

    yield _create

    for r in reversed(readers):
        try:
            r.close()
        except dds.AlreadyClosedError:
            pass


def _to_duration(timeout_sec):
    """Convert a float timeout to a dds.Duration."""
    sec = int(timeout_sec)
    nanosec = int((timeout_sec - sec) * 1_000_000_000)
    return dds.Duration(sec, nanosec)


def wait_for_discovery(writer, reader, timeout_sec=5.0):
    """Wait until a writer and reader have discovered each other.

    Uses StatusCondition + WaitSet for event-driven wakeup instead of
    polling, so discovery is detected within milliseconds of occurring.
    """

    def discovered():
        return (
            writer.publication_matched_status.current_count > 0
            and reader.subscription_matched_status.current_count > 0
        )

    if discovered():
        return True

    writer_cond = dds.StatusCondition(writer)
    writer_cond.enabled_statuses = dds.StatusMask.PUBLICATION_MATCHED
    reader_cond = dds.StatusCondition(reader)
    reader_cond.enabled_statuses = dds.StatusMask.SUBSCRIPTION_MATCHED

    waitset = dds.WaitSet()
    waitset += writer_cond
    waitset += reader_cond

    deadline = time.monotonic() + timeout_sec
    while True:
        if discovered():
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            waitset.wait(_to_duration(remaining))
        except dds.TimeoutError:
            return discovered()


def wait_for_reader_match(reader, timeout_sec=5.0):
    """Wait until a reader has at least one matched publication.

    Uses StatusCondition + WaitSet for event-driven wakeup.
    Use this when the writer is encapsulated inside a service object
    and not directly accessible.
    """
    if reader.subscription_matched_status.current_count > 0:
        return True

    cond = dds.StatusCondition(reader)
    cond.enabled_statuses = dds.StatusMask.SUBSCRIPTION_MATCHED

    waitset = dds.WaitSet()
    waitset += cond

    deadline = time.monotonic() + timeout_sec
    while True:
        if reader.subscription_matched_status.current_count > 0:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            waitset.wait(_to_duration(remaining))
        except dds.TimeoutError:
            return reader.subscription_matched_status.current_count > 0


def wait_for_data(reader, timeout_sec=5.0, count=1):
    """Wait until reader has at least `count` valid samples.

    Uses StatusCondition(DATA_AVAILABLE) + WaitSet for event-driven
    wakeup instead of polling, so data is detected within milliseconds
    of arrival.
    """
    # Fast path: data already available
    samples = reader.read()
    valid = [s for s in samples if s.info.valid]
    if len(valid) >= count:
        return valid

    cond = dds.StatusCondition(reader)
    cond.enabled_statuses = dds.StatusMask.DATA_AVAILABLE
    waitset = dds.WaitSet()
    waitset += cond

    deadline = time.monotonic() + timeout_sec
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return []
        try:
            waitset.wait(_to_duration(remaining))
        except dds.TimeoutError:
            pass
        samples = reader.read()
        valid = [s for s in samples if s.info.valid]
        if len(valid) >= count:
            return valid
