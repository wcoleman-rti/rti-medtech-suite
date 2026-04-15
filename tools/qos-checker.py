#!/usr/bin/env python3
"""QoS Compatibility Pre-Flight Checker.

Loads all QoS XML profiles via NDDS_QOS_PROFILES and checks RxO
(Requested/Offered) compatibility for every topic pair defined in the
domain library.

Usage:
    python tools/qos-checker.py           # check all topic pairs
    python tools/qos-checker.py --verbose  # show resolved QoS per topic

Exit codes:
    0 - all compatible
    1 - incompatibilities found
    2 - infrastructure error (missing env, bad XML)
"""

import argparse
import os
import sys
import xml.etree.ElementTree as ET

import rti.connextdds as dds

# Domain names that make up the Procedure domain (domain ID 10).
PROCEDURE_DOMAINS = frozenset(
    {"Procedure_control", "Procedure_clinical", "Procedure_operational"}
)

# Mapping from domain library domain names to their topic QoS profiles.
DOMAIN_PROFILE_MAP = {
    "Procedure_control": "Topics::ProcedureTopics",
    "Procedure_clinical": "Topics::ProcedureTopics",
    "Procedure_operational": "Topics::ProcedureTopics",
    "Hospital": "Topics::HospitalTopics",
}

# --- Enum helpers ---
# Connext Python wraps pybind11 enums in two layers:
#   - Class-level members (e.g. dds.DurabilityKind.VOLATILE) are the *inner*
#     type (DurabilityKind.DurabilityKind) — hashable, have .name/.value.
#   - QoS-returned values (e.g. w_qos.durability.kind) are the *outer* type
#     (DurabilityKind) — NOT hashable, but expose .underlying to get the
#     inner type.
# Dict keys use inner types directly; lookups call _to_inner() on outer values.


def _to_inner(enum_val):
    """Convert an outer Connext enum to its hashable inner type.

    If the value is already the inner type (no .underlying), return as-is.
    """
    return getattr(enum_val, "underlying", enum_val)


_DURABILITY_RANK = {
    dds.DurabilityKind.VOLATILE: 0,
    dds.DurabilityKind.TRANSIENT_LOCAL: 1,
    dds.DurabilityKind.TRANSIENT: 2,
    dds.DurabilityKind.PERSISTENT: 3,
}

_LIVELINESS_RANK = {
    dds.LivelinessKind.AUTOMATIC: 0,
    dds.LivelinessKind.MANUAL_BY_PARTICIPANT: 1,
    dds.LivelinessKind.MANUAL_BY_TOPIC: 2,
}


def _durability_rank(kind):
    return _DURABILITY_RANK.get(_to_inner(kind), -1)


def _liveliness_rank(kind):
    return _LIVELINESS_RANK.get(_to_inner(kind), -1)


def duration_tuple(d):
    """Convert a DDS Duration to a (sec, nanosec) tuple for comparison."""
    return (d.sec, d.nanosec)


def duration_le(a, b):
    """Return True if Duration a <= Duration b."""
    return duration_tuple(a) <= duration_tuple(b)


def format_duration(d):
    """Human-readable Duration string."""
    if d.sec >= 2147483647:
        return "INFINITE"
    if d.sec == 0:
        if d.nanosec == 0:
            return "0"
        return f"{d.nanosec / 1e6:.1f}ms"
    return f"{d.sec}.{d.nanosec:09d}s"


# --- RxO policy checks ---
# Each returns None on success, or an error message string on failure.


def check_reliability(w_qos, r_qos):
    """RxO: if reader requires RELIABLE, writer must offer RELIABLE."""
    if r_qos.reliability.kind == dds.ReliabilityKind.RELIABLE:
        if w_qos.reliability.kind != dds.ReliabilityKind.RELIABLE:
            return "Reader requires RELIABLE but writer offers BEST_EFFORT"
    return None


def check_durability(w_qos, r_qos):
    """RxO: writer durability kind >= reader durability kind."""
    w_rank = _durability_rank(w_qos.durability.kind)
    r_rank = _durability_rank(r_qos.durability.kind)
    if w_rank < r_rank:
        return (
            f"Writer offers {_enum_name(w_qos.durability.kind)}"
            f" but reader requires {_enum_name(r_qos.durability.kind)}"
        )
    return None


def check_deadline(w_qos, r_qos):
    """RxO: writer deadline period <= reader deadline period."""
    if not duration_le(w_qos.deadline.period, r_qos.deadline.period):
        return (
            f"Writer deadline ({format_duration(w_qos.deadline.period)})"
            f" exceeds reader deadline ({format_duration(r_qos.deadline.period)})"
        )
    return None


def check_ownership(w_qos, r_qos):
    """RxO: ownership kind must match."""
    if w_qos.ownership.kind != r_qos.ownership.kind:
        return (
            f"Writer uses {_enum_name(w_qos.ownership.kind)}"
            f" but reader uses {_enum_name(r_qos.ownership.kind)}"
        )
    return None


def check_liveliness(w_qos, r_qos):
    """RxO: writer liveliness kind >= reader kind, lease <= reader lease."""
    w_kind = _liveliness_rank(w_qos.liveliness.kind)
    r_kind = _liveliness_rank(r_qos.liveliness.kind)
    if w_kind < r_kind:
        return (
            f"Writer liveliness kind {_enum_name(w_qos.liveliness.kind)}"
            f" < reader kind {_enum_name(r_qos.liveliness.kind)}"
        )
    if not duration_le(
        w_qos.liveliness.lease_duration, r_qos.liveliness.lease_duration
    ):
        return (
            f"Writer liveliness lease"
            f" ({format_duration(w_qos.liveliness.lease_duration)})"
            f" exceeds reader lease"
            f" ({format_duration(r_qos.liveliness.lease_duration)})"
        )
    return None


RXO_CHECKS = [
    ("Reliability", check_reliability),
    ("Durability", check_durability),
    ("Deadline", check_deadline),
    ("Ownership", check_ownership),
    ("Liveliness", check_liveliness),
]


def check_rxo(w_qos, r_qos):
    """Check all RxO policies. Returns list of (policy_name, error_message)."""
    errors = []
    for name, check_fn in RXO_CHECKS:
        msg = check_fn(w_qos, r_qos)
        if msg:
            errors.append((name, msg))
    return errors


# --- QoS summary formatting ---


def _enum_name(val):
    """Extract short name from a Connext enum value.

    Works for both outer types (via .underlying.name) and inner types
    (via .name directly).
    """
    return _to_inner(val).name


def format_qos_summary(qos, kind="writer"):
    """Format a one-line QoS summary for verbose output."""
    parts = [
        f"reliability={_enum_name(qos.reliability.kind)}",
        f"durability={_enum_name(qos.durability.kind)}",
        f"deadline={format_duration(qos.deadline.period)}",
        f"ownership={_enum_name(qos.ownership.kind)}",
        f"liveliness={_enum_name(qos.liveliness.kind)}"
        f"/{format_duration(qos.liveliness.lease_duration)}",
        f"history={_enum_name(qos.history.kind)}({qos.history.depth})",
    ]
    return f"  {kind}: {', '.join(parts)}"


# --- Domain XML parsing ---


def parse_domain_topics(domains_xml_paths):
    """Parse domain library XMLs and return {domain_name: [topic_names]}.

    Skips domains with no topics (e.g. Observability).
    """
    result = {}
    for xml_path in domains_xml_paths:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        for domain_lib in root.iter("domain_library"):
            for domain in domain_lib.findall("domain"):
                name = domain.get("name")
                topics = [t.get("name") for t in domain.findall("topic")]
                if topics:
                    result[name] = topics
    return result


_DOMAIN_LIB_SUFFIXES = ("RoomDatabuses.xml", "HospitalDatabuses.xml", "CloudDatabuses.xml")


def find_domain_library_xmls():
    """Locate domain library XMLs from the NDDS_QOS_PROFILES environment variable."""
    profiles = os.environ.get("NDDS_QOS_PROFILES", "")
    found = []
    for path in profiles.split(";"):
        path = path.strip()
        if any(path.endswith(s) for s in _DOMAIN_LIB_SUFFIXES) and os.path.isfile(path):
            found.append(path)
    return found if found else None


# --- Main check logic ---


def check_all(provider, domains_xml_paths, verbose=False):
    """Check RxO compatibility for all topic pairs.

    Returns (results, pass_count, fail_count).
    Each result is (context_label, writer_qos, reader_qos, errors).
    """
    domain_topics = parse_domain_topics(domains_xml_paths)

    procedure_topics = set()
    for dname in PROCEDURE_DOMAINS:
        if dname in domain_topics:
            procedure_topics.update(domain_topics[dname])

    hospital_topics = set(domain_topics.get("Integration", []))
    bridged = procedure_topics & hospital_topics

    results = []
    pass_count = 0
    fail_count = 0

    # Within Procedure domain
    for topic in sorted(procedure_topics):
        profile = "Topics::ProcedureTopics"
        w_qos = provider.set_topic_datawriter_qos(profile, topic)
        r_qos = provider.set_topic_datareader_qos(profile, topic)
        errors = check_rxo(w_qos, r_qos)
        context = f"Procedure/{topic}"
        results.append((context, w_qos, r_qos, errors))
        if errors:
            fail_count += 1
        else:
            pass_count += 1

    # Within Hospital domain (native topics only)
    for topic in sorted(hospital_topics - bridged):
        profile = "Topics::HospitalTopics"
        w_qos = provider.set_topic_datawriter_qos(profile, topic)
        r_qos = provider.set_topic_datareader_qos(profile, topic)
        errors = check_rxo(w_qos, r_qos)
        context = f"Hospital/{topic}"
        results.append((context, w_qos, r_qos, errors))
        if errors:
            fail_count += 1
        else:
            pass_count += 1

    # Bridged: Procedure writer -> Hospital reader
    for topic in sorted(bridged):
        w_qos = provider.set_topic_datawriter_qos("Topics::ProcedureTopics", topic)
        r_qos = provider.set_topic_datareader_qos("Topics::HospitalTopics", topic)
        errors = check_rxo(w_qos, r_qos)
        context = f"Bridged({topic}) Procedure->Hospital"
        results.append((context, w_qos, r_qos, errors))
        if errors:
            fail_count += 1
        else:
            pass_count += 1

    return results, pass_count, fail_count


def main():
    parser = argparse.ArgumentParser(description="QoS Compatibility Pre-Flight Checker")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show resolved QoS details per topic",
    )
    args = parser.parse_args()

    domains_xmls = find_domain_library_xmls()
    if not domains_xmls:
        print(
            "ERROR: Cannot find domain library XMLs in NDDS_QOS_PROFILES",
            file=sys.stderr,
        )
        sys.exit(2)

    provider = dds.QosProvider.default
    results, pass_count, fail_count = check_all(provider, domains_xmls, args.verbose)

    for context, w_qos, r_qos, errors in results:
        if errors:
            print(f"FAIL  {context}")
            for policy, msg in errors:
                print(f"      [{policy}] {msg}")
        else:
            print(f"PASS  {context}")
        if args.verbose:
            print(format_qos_summary(w_qos, "writer"))
            print(format_qos_summary(r_qos, "reader"))

    total = pass_count + fail_count
    print(f"\n{pass_count}/{total} topic pairs compatible")
    if fail_count > 0:
        print(f"{fail_count} INCOMPATIBLE pair(s) found")
        sys.exit(1)
    print("All topic pairs are RxO compatible")


if __name__ == "__main__":
    main()
