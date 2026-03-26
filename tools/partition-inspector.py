#!/usr/bin/env python3
"""Partition Inspector — Active Partition Scanner.

Joins the Procedure domain with a room/* wildcard partition, discovers
all active partitions from endpoint builtin topics, and reports which
entities are publishing on each.

KNOWN LIMITATION (INC-003):
    This project sets partitions at the DomainParticipant level, but
    ParticipantBuiltinTopicData in the RTI Connext Python 7.6.0 binding
    does not expose a ``partition`` field.  Publisher/Subscriber-level
    partitions (available via PublicationBuiltinTopicData and
    SubscriptionBuiltinTopicData) are independent from DomainParticipant
    partitions and are not set by application code.  Therefore, this tool
    will report no active partitions until either:
      - A future Connext Python API update exposes DomainParticipant
        partitions in builtin discovery data.
      - Application code propagates partition names via user_data or
        property on each DomainParticipant.

Usage:
    python tools/partition-inspector.py               # scan once
    python tools/partition-inspector.py --watch        # continuous mode
    python tools/partition-inspector.py --filter "room/OR-3/*"

Exit codes:
    0 — success
    2 — infrastructure error
"""

from __future__ import annotations

import argparse
import sys
import time

import rti.connextdds as dds

# Reset factory QoS — prevent monitoring participants and log noise
# when running inside application containers.
_factory_qos = dds.DomainParticipant.participant_factory_qos
_factory_qos.entity_factory.autoenable_created_entities = False
_factory_qos.monitoring.enable = False
dds.DomainParticipant.participant_factory_qos = _factory_qos
dds.Logger.instance.verbosity = dds.Verbosity.SILENT

PROCEDURE_DOMAIN_ID = 10
DISCOVERY_WAIT_S = 3.0


def _create_inspector(
    partition_filter: str | None = None,
    peers: list[str] | None = None,
) -> dds.DomainParticipant:
    """Create a read-only participant for partition inspection."""
    qos = dds.DomainParticipantQos()
    qos.participant_name.name = "partition-inspector"
    qos.transport_builtin.mask = dds.TransportBuiltinMask.UDPv4
    qos.discovery.multicast_receive_addresses = dds.StringSeq()

    if partition_filter:
        qos.partition.name = dds.StringSeq([partition_filter])
    else:
        qos.partition.name = dds.StringSeq(["room/*"])

    if peers:
        qos.discovery.initial_peers = dds.StringSeq(peers)

    participant = dds.DomainParticipant(PROCEDURE_DOMAIN_ID, qos)
    # Access builtin readers before enabling (factory QoS may disable
    # autoenable_created_entities).
    _ = participant.publication_reader
    _ = participant.subscription_reader
    participant.enable()
    return participant


def _scan(participant: dds.DomainParticipant) -> dict[str, list[str]]:
    """Discover endpoints and group by partition.

    Uses typed builtin readers (RTI Connext Python 7.6.0 API):
    ``participant.publication_reader`` and ``participant.subscription_reader``.

    Returns a dict mapping partition name -> list of entity descriptions.
    """
    partitions: dict[str, list[str]] = {}

    for reader, kind in [
        (participant.publication_reader, "writer"),
        (participant.subscription_reader, "reader"),
    ]:
        for sample in reader.read():
            if not sample.info.valid:
                continue
            data = sample.data
            topic = data.topic_name
            try:
                names = data.partition.name
            except AttributeError:
                names = []
            for pname in names:
                if not pname:
                    pname = "(default)"
                partitions.setdefault(pname, [])
                partitions[pname].append(f"{kind}: {topic}")

    return partitions


def _print_partitions(partitions: dict[str, list[str]]) -> None:
    """Print partition scan results."""
    if not partitions:
        print("No active partitions discovered.")
        return

    print(f"\nActive partitions: {len(partitions)}")
    print("-" * 50)
    for pname in sorted(partitions.keys()):
        entities = partitions[pname]
        print(f"\n  {pname} ({len(entities)} endpoints)")
        for e in sorted(set(entities)):
            count = entities.count(e)
            suffix = f" ×{count}" if count > 1 else ""
            print(f"    {e}{suffix}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan active DDS partitions on the Procedure domain.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuous mode — rescan every 5 seconds.",
    )
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help='Partition filter (default: "room/*").',
    )
    parser.add_argument(
        "--peers",
        nargs="+",
        default=None,
        help="DDS discovery peers (e.g. rtps@udpv4://cloud-discovery-service:7400).",
    )
    args = parser.parse_args(argv)

    try:
        participant = _create_inspector(
            partition_filter=args.filter,
            peers=args.peers,
        )
    except Exception as e:
        sys.stderr.write(f"Error creating participant: {e}\n")
        return 2

    try:
        time.sleep(DISCOVERY_WAIT_S)

        if args.watch:
            print("Watching partitions (Ctrl+C to stop)...")
            while True:
                partitions = _scan(participant)
                # Clear-ish output
                print(f"\n--- Scan at {time.strftime('%H:%M:%S')} ---")
                _print_partitions(partitions)
                time.sleep(5.0)
        else:
            partitions = _scan(participant)
            _print_partitions(partitions)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        participant.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
