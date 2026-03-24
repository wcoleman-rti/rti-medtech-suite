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
    assert os.environ.get("NDDS_QOS_PROFILES"), (
        "NDDS_QOS_PROFILES not set — source install/setup.bash first"
    )


@pytest.fixture
def provider():
    """Return the default QosProvider."""
    return dds.QosProvider.default


def _make_participant(domain_id, domain_tag=None, qos=None):
    """Create a DomainParticipant with optional domain tag.

    Partition is a Publisher/Subscriber QoS — set it via writer_factory
    and reader_factory instead.
    """
    if qos is None:
        qos = dds.DomainParticipant.default_participant_qos

    if domain_tag is not None:
        qos.property[
            "dds.domain_participant.domain_tag"
        ] = domain_tag

    return dds.DomainParticipant(domain_id, qos)


@pytest.fixture
def participant_factory():
    """Factory fixture that creates participants and tracks them for cleanup.

    Usage:
        p = participant_factory(domain_id=0, domain_tag="control")
    """
    participants = []

    def _create(domain_id=0, domain_tag=None, qos=None):
        p = _make_participant(domain_id, domain_tag, qos)
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
    """Factory fixture that creates DataWriters with optional partition.

    Usage:
        w = writer_factory(participant, topic, qos=writer_qos,
                           partition="room/OR-1")
    """
    writers = []

    def _create(participant, topic, qos=None, partition=None):
        pub_qos = dds.PublisherQos()
        if partition is not None:
            if isinstance(partition, str):
                partition = [partition]
            pub_qos.partition.name = partition
        pub = dds.Publisher(participant, pub_qos)
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
    """Factory fixture that creates DataReaders with optional partition.

    Usage:
        r = reader_factory(participant, topic, qos=reader_qos,
                           partition="room/OR-1")
    """
    readers = []

    def _create(participant, topic, qos=None, partition=None):
        sub_qos = dds.SubscriberQos()
        if partition is not None:
            if isinstance(partition, str):
                partition = [partition]
            sub_qos.partition.name = partition
        sub = dds.Subscriber(participant, sub_qos)
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


def wait_for_discovery(writer, reader, timeout_sec=5.0):
    """Wait until a writer and reader have discovered each other."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if (
            writer.matched_subscriptions
            and reader.matched_publications
        ):
            return True
        time.sleep(0.05)
    return False


def wait_for_data(reader, timeout_sec=5.0, count=1):
    """Wait until reader has at least `count` samples available."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        samples = reader.read()
        valid = [s for s in samples if s.info.valid]
        if len(valid) >= count:
            return valid
        time.sleep(0.05)
    return []
