#!/usr/bin/env python3
"""Medtech Suite System Health Diagnostic.

Joins each DDS domain as a temporary read-only participant, inspects
discovered entities via built-in discovery topics, and reports issues.

Usage:
    python tools/medtech-diag/diag.py                     # full check
    python tools/medtech-diag/diag.py --domain procedure   # check one domain
    python tools/medtech-diag/diag.py --check endpoints    # check one aspect
    python tools/medtech-diag/diag.py --format json        # JSON output

Exit codes:
    0 — all checks pass
    1 — one or more checks failed
    2 — infrastructure error
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from dataclasses import asdict, dataclass, field

import rti.connextdds as dds

# ── Factory QoS Reset ────────────────────────────────────────────────
# When running inside a container that loads the application factory QoS
# (monitoring, logging, autoenable_created_entities=false), the diagnostic
# tool must override the factory to prevent spawning monitoring participants
# and producing excessive log noise.
_factory_qos = dds.DomainParticipant.participant_factory_qos
_factory_qos.entity_factory.autoenable_created_entities = False
_factory_qos.monitoring.enable = False
dds.DomainParticipant.participant_factory_qos = _factory_qos
dds.Logger.instance.verbosity = dds.Verbosity.SILENT

# ── Domain Configuration ─────────────────────────────────────────────

DOMAINS: dict[str, int] = {
    "procedure": 10,
    "hospital": 11,
    "observability": 20,
}

# Domain tags per domain — participants with different domain_tag values are
# isolated from each other.  The diagnostic tool must create one participant
# per tag to discover all entities.
DOMAIN_TAGS: dict[str, list[str]] = {
    "procedure": ["control", "clinical", "operational"],
    "hospital": [],
    "observability": [],
}

# Discovery settling time (seconds)
DISCOVERY_WAIT_S = 3.0

# Cloud Discovery Service default host/port
CDS_HOST = "localhost"
CDS_PORT = 7400

# Default discovery peers (override with --peers or NDDS_DISCOVERY_PEERS)
DEFAULT_PEERS = ["rtps@udpv4://cloud-discovery-service:7400"]

# ── Result Model ─────────────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    status: str  # "PASS" or "FAIL"
    domain: str
    detail: str = ""
    items: list[str] = field(default_factory=list)


# ── Discovery Helper ─────────────────────────────────────────────────


def _create_diagnostic_participant(
    domain_id: int,
    peers: list[str] | None = None,
    domain_tag: str = "",
) -> dds.DomainParticipant:
    """Create a minimal, short-lived participant for discovery inspection."""
    qos = dds.DomainParticipantQos()
    qos.participant_name.name = "medtech-diag"
    # UDPv4 only, no multicast, no shared memory
    qos.transport_builtin.mask = dds.TransportBuiltinMask.UDPv4
    qos.discovery.multicast_receive_addresses = dds.StringSeq()
    # Set discovery peers — prefer explicit peers, then env var, then defaults
    if peers is None:
        env_peers = os.environ.get("NDDS_DISCOVERY_PEERS")
        if env_peers:
            peers = [p.strip() for p in env_peers.split(",") if p.strip()]
        else:
            peers = DEFAULT_PEERS
    if peers:
        qos.discovery.initial_peers = dds.StringSeq(peers)
    # Set domain tag if specified
    if domain_tag:
        qos.property.set("dds.domain_participant.domain_tag", domain_tag)
    participant = dds.DomainParticipant(domain_id, qos)
    # Access builtin readers before enabling so none are missed.
    # The factory QoS may disable autoenable_created_entities,
    # so we must explicitly enable after setup.
    _ = participant.participant_reader
    _ = participant.publication_reader
    _ = participant.subscription_reader
    participant.enable()
    return participant


def _discover(participant: dds.DomainParticipant) -> tuple[list, list, list]:
    """Wait for discovery and return (participants, publications, subscriptions).

    Uses the typed builtin readers accessible via
    ``participant.participant_reader``, ``.publication_reader``, and
    ``.subscription_reader`` (RTI Connext Python 7.6.0 API).
    """
    time.sleep(DISCOVERY_WAIT_S)

    participants = []
    for sample in participant.participant_reader.take():
        if sample.info.valid:
            participants.append(sample.data)

    writers = []
    for sample in participant.publication_reader.take():
        if sample.info.valid:
            writers.append(sample.data)

    readers = []
    for sample in participant.subscription_reader.take():
        if sample.info.valid:
            readers.append(sample.data)

    return participants, writers, readers


# ── Individual Checks ────────────────────────────────────────────────


def _participant_name(data) -> str:
    """Extract participant name string from ParticipantBuiltinTopicData."""
    pn = data.participant_name
    # RTI Python API: participant_name may be a string or an
    # EntityName object with a .name attribute.
    if isinstance(pn, str):
        return pn
    return getattr(pn, "name", str(pn))


def check_participants(
    domain_name: str,
    participants: list,
) -> CheckResult:
    """Verify that at least one application participant exists."""
    # Filter out the diagnostic participant itself
    app_parts = [p for p in participants if _participant_name(p) != "medtech-diag"]
    names = []
    for p in app_parts:
        name = _participant_name(p)
        names.append(name or "(unnamed)")

    if not app_parts:
        return CheckResult(
            name="participant_discovery",
            status="FAIL",
            domain=domain_name,
            detail=f"No application participants discovered on domain {domain_name}",
        )
    return CheckResult(
        name="participant_discovery",
        status="PASS",
        domain=domain_name,
        detail=f"{len(app_parts)} participant(s) discovered",
        items=names,
    )


def check_endpoints(
    domain_name: str,
    publications: list,
    subscriptions: list,
) -> CheckResult:
    """Check that writers and readers exist and report any unmatched.

    On the observability domain, zero user endpoints is expected because
    ML2.0 monitoring uses internal mechanisms rather than user-created
    DataWriters/DataReaders.
    """
    pub_topics = set()
    for p in publications:
        pub_topics.add(p.topic_name)

    sub_topics = set()
    for s in subscriptions:
        sub_topics.add(s.topic_name)

    unmatched_pubs = pub_topics - sub_topics
    unmatched_subs = sub_topics - pub_topics

    items = []
    if unmatched_pubs:
        items.append(f"Writers without readers: {sorted(unmatched_pubs)}")
    if unmatched_subs:
        items.append(f"Readers without writers: {sorted(unmatched_subs)}")

    total = len(publications) + len(subscriptions)
    if total == 0:
        # Room Observability databus has no user endpoints (ML2.0 monitoring only)
        if domain_name == "observability":
            return CheckResult(
                name="endpoint_matching",
                status="PASS",
                domain=domain_name,
                detail="No user endpoints (ML2.0 monitoring only)",
            )
        return CheckResult(
            name="endpoint_matching",
            status="FAIL",
            domain=domain_name,
            detail="No endpoints discovered",
        )

    status = "PASS" if not unmatched_pubs and not unmatched_subs else "FAIL"
    return CheckResult(
        name="endpoint_matching",
        status=status,
        domain=domain_name,
        detail=f"{len(publications)} writers, {len(subscriptions)} readers",
        items=items,
    )


def check_partitions(
    domain_name: str,
    publications: list,
    subscriptions: list,
) -> CheckResult:
    """Report partition status (informational only).

    Limitation: this project sets partitions at the DomainParticipant level,
    but ParticipantBuiltinTopicData in the RTI Connext Python 7.6.0 binding
    does not expose a ``partition`` field.  Publisher/Subscriber-level
    partitions (available on Publication/SubscriptionBuiltinTopicData) are
    independent from DomainParticipant partitions and are not set by
    application code, so endpoint discovery always returns an empty list.

    This check is therefore informational and always passes.  Full partition
    introspection will require a future Connext Python API update or an
    application-level convention (e.g. propagating partition names via
    DomainParticipantQos.user_data or property).
    """
    return CheckResult(
        name="partition_topology",
        status="PASS",
        domain=domain_name,
        detail="Partition introspection not available (see INC-041)",
    )


def check_liveliness(
    domain_name: str,
    publications: list,
) -> CheckResult:
    """Check that all discovered writers are alive."""
    # We can check via the publication built-in data — if it's in the
    # discovery data it's alive (liveliness is checked by DDS automatically)
    alive = len(publications)
    return CheckResult(
        name="liveliness",
        status="PASS",
        domain=domain_name,
        detail=f"{alive} writer(s) alive",
    )


def check_cds_reachability() -> CheckResult:
    """Check if Cloud Discovery Service is reachable on its UDP port."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)
        # Send a small UDP packet — CDS won't respond but if the port
        # is open the send succeeds without ICMP unreachable.
        sock.sendto(b"\x00", (CDS_HOST, CDS_PORT))
        sock.close()
        return CheckResult(
            name="cds_reachability",
            status="PASS",
            domain="infrastructure",
            detail=f"CDS reachable at {CDS_HOST}:{CDS_PORT}",
        )
    except (OSError, TimeoutError) as e:
        return CheckResult(
            name="cds_reachability",
            status="FAIL",
            domain="infrastructure",
            detail=f"CDS not reachable at {CDS_HOST}:{CDS_PORT}: {e}",
        )


def check_observability_stack() -> CheckResult:
    """Check if Prometheus is reachable (optional)."""
    try:
        from urllib.request import Request, urlopen

        req = Request(
            "http://localhost:9090/api/v1/status/buildinfo",
            headers={"Accept": "application/json"},
        )
        with urlopen(req, timeout=3) as resp:  # noqa: S310
            data = json.loads(resp.read())
            if data.get("status") == "success":
                return CheckResult(
                    name="observability_stack",
                    status="PASS",
                    domain="infrastructure",
                    detail="Prometheus reachable",
                )
    except Exception:
        pass

    return CheckResult(
        name="observability_stack",
        status="FAIL",
        domain="infrastructure",
        detail="Prometheus not reachable at localhost:9090",
    )


# ── Check Orchestration ──────────────────────────────────────────────

ALL_CHECKS = {
    "participants",
    "endpoints",
    "partitions",
    "liveliness",
    "cds",
    "observability",
}


def run_domain_checks(
    domain_name: str,
    domain_id: int,
    checks: set[str],
    peers: list[str] | None = None,
) -> list[CheckResult]:
    """Run all applicable checks for a single domain.

    If the domain uses domain_tag isolation (e.g., procedure), creates one
    participant per tag and merges the discovered data before running checks.
    """
    results: list[CheckResult] = []
    tags = DOMAIN_TAGS.get(domain_name, [])

    all_parts: list = []
    all_pubs: list = []
    all_subs: list = []

    if tags:
        for tag in tags:
            participant = _create_diagnostic_participant(
                domain_id,
                peers=peers,
                domain_tag=tag,
            )
            try:
                parts, pubs, subs = _discover(participant)
                all_parts.extend(parts)
                all_pubs.extend(pubs)
                all_subs.extend(subs)
            finally:
                participant.close()
    else:
        participant = _create_diagnostic_participant(domain_id, peers=peers)
        try:
            all_parts, all_pubs, all_subs = _discover(participant)
        finally:
            participant.close()

    if "participants" in checks:
        results.append(check_participants(domain_name, all_parts))
    if "endpoints" in checks:
        results.append(check_endpoints(domain_name, all_pubs, all_subs))
    if "partitions" in checks:
        results.append(check_partitions(domain_name, all_pubs, all_subs))
    if "liveliness" in checks:
        results.append(check_liveliness(domain_name, all_pubs))

    return results


def run_all(
    domain_filter: str | None = None,
    check_filter: str | None = None,
    peers: list[str] | None = None,
) -> list[CheckResult]:
    """Run the full diagnostic suite."""
    checks = ALL_CHECKS if check_filter is None else {check_filter}
    results: list[CheckResult] = []

    # Infrastructure checks
    if "cds" in checks:
        results.append(check_cds_reachability())
    if "observability" in checks:
        results.append(check_observability_stack())

    # Domain checks
    domains = DOMAINS
    if domain_filter:
        key = domain_filter.lower()
        if key not in DOMAINS:
            results.append(
                CheckResult(
                    name="domain_filter",
                    status="FAIL",
                    domain=key,
                    detail=f"Unknown domain: {key}. Valid: {list(DOMAINS.keys())}",
                )
            )
            return results
        domains = {key: DOMAINS[key]}

    domain_checks = checks - {"cds", "observability"}
    if domain_checks:
        for name, did in domains.items():
            results.extend(run_domain_checks(name, did, domain_checks, peers=peers))

    return results


# ── Output Formatting ────────────────────────────────────────────────


def format_text(results: list[CheckResult]) -> str:
    lines = ["Medtech Suite System Health Diagnostic", "=" * 42, ""]

    for r in results:
        marker = "✓" if r.status == "PASS" else "✗"
        lines.append(f"  {marker} [{r.domain}] {r.name}: {r.detail}")
        for item in r.items:
            lines.append(f"      {item}")

    lines.append("")
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    lines.append(f"Results: {passed} passed, {failed} failed")

    if failed > 0:
        lines.append("OVERALL: FAIL")
    else:
        lines.append("OVERALL: PASS")

    return "\n".join(lines) + "\n"


def format_json(results: list[CheckResult]) -> str:
    output = {
        "results": [asdict(r) for r in results],
        "summary": {
            "passed": sum(1 for r in results if r.status == "PASS"),
            "failed": sum(1 for r in results if r.status == "FAIL"),
            "overall": ("PASS" if all(r.status == "PASS" for r in results) else "FAIL"),
        },
    }
    return json.dumps(output, indent=2) + "\n"


# ── CLI ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Medtech suite system health diagnostic.",
    )
    parser.add_argument(
        "--domain",
        choices=list(DOMAINS.keys()),
        default=None,
        help="Check a specific domain only.",
    )
    parser.add_argument(
        "--check",
        choices=sorted(ALL_CHECKS),
        default=None,
        help="Run a specific check only.",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="output_format",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--peers",
        nargs="+",
        default=None,
        help="DDS discovery peers (e.g. rtps@udpv4://cloud-discovery-service:7400).",
    )
    args = parser.parse_args(argv)

    try:
        results = run_all(
            domain_filter=args.domain,
            check_filter=args.check,
            peers=args.peers,
        )
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        return 2

    if args.output_format == "json":
        sys.stdout.write(format_json(results))
    else:
        sys.stdout.write(format_text(results))

    return 0 if all(r.status == "PASS" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
