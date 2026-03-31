"""Project-level pytest conftest.py — DDS fixtures for integration tests.

Provides reusable fixtures for creating DDS participants, writers, and readers
with automatic cleanup. Uses domain 0 for test isolation (reserved for testing
per vision/data-model.md). QoS profiles are loaded from NDDS_QOS_PROFILES.
"""

import os
import signal
import subprocess
import time

import pytest
import rti.connextdds as dds

# -------------------------------------------------------------------
# Zombie process guard
# -------------------------------------------------------------------

_SERVICE_HOST_PATTERNS = [
    "surgical_procedure.clinical_service_host",
    "surgical_procedure.operational_service_host",
    "robot-service-host",
]


@pytest.fixture(autouse=True, scope="session")
def _kill_zombie_service_hosts():
    """Kill leftover service-host processes from prior test runs.

    DDS participants in zombie processes publish stale ServiceCatalog/
    ServiceStatus data that contaminates readers in the current run.
    """
    my_pid = os.getpid()
    for pattern in _SERVICE_HOST_PATTERNS:
        try:
            result = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            break  # pgrep not available
        for line in result.stdout.strip().splitlines():
            pid_str = line.strip()
            if not pid_str:
                continue
            pid = int(pid_str)
            if pid == my_pid:
                continue
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    time.sleep(0.5)
    yield


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


def wait_for_discovery(writer, reader, timeout_sec=2.0):
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


def wait_for_reader_match(reader, timeout_sec=2.0):
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


def wait_for_data(reader, timeout_sec=1.0, count=1, conditions=None):
    """Wait until data conditions are satisfied on the reader.

    When ``conditions`` is None (default), creates a single ReadCondition
    for NOT_READ + ALIVE data and waits for ``count`` matching samples.

    When ``conditions`` is provided, it must be a list of
    ``(condition, required_count)`` tuples.  Each condition is attached
    to a shared WaitSet and must accumulate ``required_count`` read hits
    before the deadline.  Satisfied conditions are detached from the
    WaitSet to reduce noise.

    In both modes the function only calls ``read()`` — never ``take()`` —
    so the caller can inspect or take data afterward.

    Returns True if all conditions were satisfied, False otherwise.
    """
    if conditions is None:
        conditions = [
            (
                dds.ReadCondition(
                    reader,
                    dds.DataState(
                        dds.SampleState.NOT_READ,
                        dds.ViewState.ANY,
                        dds.InstanceState.ALIVE,
                    ),
                ),
                count,
            )
        ]

    waitset = dds.WaitSet()
    remaining = []  # list of [cond, needed]
    for cond, needed in conditions:
        waitset += cond
        remaining.append([cond, needed])

    deadline = time.monotonic() + timeout_sec
    while remaining:
        still_pending = []
        for entry in remaining:
            cond, needed = entry
            hits = len(reader.select().condition(cond).read_data())
            needed -= hits
            if needed > 0:
                still_pending.append([cond, needed])
            else:
                waitset -= cond
        remaining = still_pending
        if not remaining:
            break
        left = deadline - time.monotonic()
        if left <= 0:
            break
        try:
            waitset.wait(_to_duration(left))
        except dds.TimeoutError:
            break
    return len(remaining) == 0


def wait_for_status(reader, host_id, service_id, target_state, timeout_sec=5.0):
    """Wait for a ServiceStatus sample matching host/service/state.

    Uses a ReadCondition(NOT_READ, ANY, ALIVE) + WaitSet to avoid
    wakeups from already-consumed transitions.  Samples are taken
    (consumed) so repeated calls see only new transitions.
    """
    condition = dds.ReadCondition(
        reader,
        dds.DataState(
            dds.SampleState.NOT_READ,
            dds.ViewState.ANY,
            dds.InstanceState.ALIVE,
        ),
    )
    waitset = dds.WaitSet()
    waitset += condition

    deadline = time.monotonic() + timeout_sec
    while True:
        for sample in reader.select().condition(condition).take_data():
            if (
                sample.host_id == host_id
                and sample.service_id == service_id
                and sample.state == target_state
            ):
                return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            waitset.wait(_to_duration(remaining))
        except dds.TimeoutError:
            return False


def wait_for_all_states(reader, expected, timeout_sec=5.0):
    """Wait for multiple (host_id, service_id) pairs to reach target states.

    ``expected`` is a dict mapping ``(host_id, service_id)`` tuples to the
    desired ``ServiceState``.  Returns a set of ``(host_id, service_id)``
    pairs that did **not** reach the target state before the deadline.
    An empty set means all succeeded.

    Unlike sequential ``wait_for_status`` calls, this function processes
    all targets in a single take loop so no samples are silently discarded.
    """
    remaining = dict(expected)
    condition = dds.ReadCondition(
        reader,
        dds.DataState(
            dds.SampleState.NOT_READ,
            dds.ViewState.ANY,
            dds.InstanceState.ALIVE,
        ),
    )
    waitset = dds.WaitSet()
    waitset += condition

    deadline = time.monotonic() + timeout_sec
    while remaining:
        for sample in reader.select().condition(condition).take_data():
            key = (sample.host_id, sample.service_id)
            if key in remaining and sample.state == remaining[key]:
                del remaining[key]
        if not remaining:
            break
        left = deadline - time.monotonic()
        if left <= 0:
            break
        try:
            waitset.wait(_to_duration(left))
        except dds.TimeoutError:
            break
    return set(remaining.keys())


def wait_for_replier(requester, timeout_sec=3.0):
    """Wait until the requester has matched at least one replier.

    Requester exposes no StatusCondition — poll at 50 ms.
    """
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if requester.matched_replier_count > 0:
            return True
        time.sleep(0.05)
    return False


def send_rpc(requester, call, timeout_sec=10):
    """Send an RPC call and return the first valid reply (or None)."""
    request_id = requester.send_request(call)
    replies = requester.receive_replies(
        max_wait=dds.Duration(seconds=timeout_sec),
        related_request_id=request_id,
    )
    for reply, info in replies:
        if info.valid:
            return reply
    return None


# -------------------------------------------------------------------
# Orchestration RPC call builders (lazy-import orchestration module)
# -------------------------------------------------------------------


def make_start_call(service_id: str):
    """Build an RPC call to start_service."""
    from orchestration import Orchestration

    ct = Orchestration.ServiceHostControl.call_type
    call = ct()
    _in = ct.in_structs[-522153841][1]()
    _in.req = Orchestration.ServiceRequest(service_id=service_id, properties=[])
    call.start_service = _in
    return call


def make_stop_call(service_id: str):
    """Build an RPC call to stop_service."""
    from orchestration import Orchestration

    ct = Orchestration.ServiceHostControl.call_type
    call = ct()
    _in = ct.in_structs[123337698][1]()
    _in.service_id = service_id
    call.stop_service = _in
    return call
