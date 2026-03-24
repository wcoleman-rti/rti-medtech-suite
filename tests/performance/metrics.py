"""Performance metric definitions with PromQL templates and thresholds.

Each metric has an ID (L1-L6, T1-T6, R1-R5), a PromQL query template,
a unit, and regression threshold configuration per
vision/performance-baseline.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ThresholdKind(str, Enum):
    """How a metric's regression threshold is evaluated."""

    PERCENTAGE = "percentage"
    ABSOLUTE_ZERO = "absolute_zero"
    EXACT_MATCH = "exact_match"
    PERCENTAGE_WITH_CAP = "percentage_with_cap"
    ABSOLUTE_DELTA_FRACTION = "absolute_delta_fraction"


@dataclass(frozen=True)
class Threshold:
    """Regression threshold configuration for a single metric."""

    kind: ThresholdKind
    # For PERCENTAGE / PERCENTAGE_WITH_CAP: max allowed increase ratio
    # e.g. 0.20 means +20%
    max_ratio: float | None = None
    # For PERCENTAGE_WITH_CAP: absolute hard cap value
    hard_cap: float | None = None
    # For ABSOLUTE_DELTA_FRACTION: fraction of total published samples
    fraction: float | None = None

    def check(
        self,
        current: float,
        baseline: float,
        total_published: float | None = None,
    ) -> bool:
        """Return True if current value is within threshold of baseline."""
        if self.kind == ThresholdKind.ABSOLUTE_ZERO:
            return current == 0

        if self.kind == ThresholdKind.EXACT_MATCH:
            return current == baseline

        if self.kind == ThresholdKind.PERCENTAGE:
            if baseline == 0:
                return current == 0
            limit = baseline * (1 + self.max_ratio)
            if self.max_ratio < 0:
                # Throughput: must not drop below floor
                return current >= limit
            # Latency/resource: must not exceed ceiling
            return current <= limit

        if self.kind == ThresholdKind.PERCENTAGE_WITH_CAP:
            if baseline == 0:
                within_pct = current == 0
            else:
                within_pct = current <= baseline * (1 + self.max_ratio)
            within_cap = current <= self.hard_cap if self.hard_cap is not None else True
            return within_pct and within_cap

        if self.kind == ThresholdKind.ABSOLUTE_DELTA_FRACTION:
            if total_published is None or total_published == 0:
                return current <= baseline
            allowed = baseline + self.fraction * total_published
            return current <= allowed

        return False


# Query type: "range" uses /api/v1/query_range, "instant" uses /api/v1/query
@dataclass(frozen=True)
class MetricDef:
    """Definition of a single performance metric."""

    metric_id: str
    description: str
    promql: str
    unit: str
    query_type: str  # "instant" or "range"
    threshold: Threshold


# ── Tier 1: Latency & Timing ────────────────────────────────────────

L1 = MetricDef(
    metric_id="L1",
    description="OperatorInput writer-to-reader latency (p50)",
    promql='dds_datareader_sample_received_latency_p50{topic="OperatorInput"}',
    unit="µs",
    query_type="instant",
    threshold=Threshold(kind=ThresholdKind.PERCENTAGE, max_ratio=0.20),
)

L2 = MetricDef(
    metric_id="L2",
    description="OperatorInput writer-to-reader latency (p99)",
    promql='dds_datareader_sample_received_latency_p99{topic="OperatorInput"}',
    unit="µs",
    query_type="instant",
    threshold=Threshold(kind=ThresholdKind.PERCENTAGE, max_ratio=0.30),
)

L3 = MetricDef(
    metric_id="L3",
    description="RobotState writer-to-reader latency (p50)",
    promql='dds_datareader_sample_received_latency_p50{topic="RobotState"}',
    unit="µs",
    query_type="instant",
    threshold=Threshold(kind=ThresholdKind.PERCENTAGE, max_ratio=0.20),
)

L4 = MetricDef(
    metric_id="L4",
    description="RobotCommand writer-to-reader latency (p50)",
    promql='dds_datareader_sample_received_latency_p50{topic="RobotCommand"}',
    unit="µs",
    query_type="instant",
    threshold=Threshold(kind=ThresholdKind.PERCENTAGE, max_ratio=0.20),
)

L5 = MetricDef(
    metric_id="L5",
    description="Routing Service input-to-output latency (p50)",
    promql="rti_routing_service_route_latency_p50",
    unit="µs",
    query_type="instant",
    threshold=Threshold(kind=ThresholdKind.PERCENTAGE, max_ratio=0.25),
)

L6 = MetricDef(
    metric_id="L6",
    description="Discovery time — last participant matched",
    promql="dds_domainparticipant_discovery_time_ms",
    unit="ms",
    query_type="instant",
    threshold=Threshold(
        kind=ThresholdKind.PERCENTAGE_WITH_CAP, max_ratio=0.50, hard_cap=30000.0
    ),
)

# ── Tier 2: Throughput & Delivery ────────────────────────────────────

T1 = MetricDef(
    metric_id="T1",
    description="OperatorInput received sample rate",
    promql='rate(dds_datareader_samples_received_total{topic="OperatorInput"}[30s])',
    unit="samples/s",
    query_type="range",
    threshold=Threshold(kind=ThresholdKind.PERCENTAGE, max_ratio=-0.10),
)

T2 = MetricDef(
    metric_id="T2",
    description="WaveformData received sample rate",
    promql='rate(dds_datareader_samples_received_total{topic="WaveformData"}[30s])',
    unit="samples/s",
    query_type="range",
    threshold=Threshold(kind=ThresholdKind.PERCENTAGE, max_ratio=-0.10),
)

T3 = MetricDef(
    metric_id="T3",
    description="CameraFrame received sample rate",
    promql='rate(dds_datareader_samples_received_total{topic="CameraFrame"}[30s])',
    unit="samples/s",
    query_type="range",
    threshold=Threshold(kind=ThresholdKind.PERCENTAGE, max_ratio=-0.10),
)

T4 = MetricDef(
    metric_id="T4",
    description="PatientVitals received sample rate",
    promql='rate(dds_datareader_samples_received_total{topic="PatientVitals"}[30s])',
    unit="samples/s",
    query_type="range",
    threshold=Threshold(kind=ThresholdKind.PERCENTAGE, max_ratio=-0.10),
)

T5 = MetricDef(
    metric_id="T5",
    description="Total samples lost (all topics, all readers)",
    promql="sum(dds_datareader_samples_lost_total)",
    unit="samples",
    query_type="instant",
    threshold=Threshold(kind=ThresholdKind.ABSOLUTE_DELTA_FRACTION, fraction=0.001),
)

T6 = MetricDef(
    metric_id="T6",
    description="Deadline missed events (all readers)",
    promql="sum(dds_datareader_deadline_missed_total)",
    unit="count",
    query_type="instant",
    threshold=Threshold(kind=ThresholdKind.ABSOLUTE_ZERO),
)

# ── Tier 3: Resource & Overhead ──────────────────────────────────────

R1 = MetricDef(
    metric_id="R1",
    description="Total DDS participant count",
    promql="count(dds_domainparticipant_up)",
    unit="count",
    query_type="instant",
    threshold=Threshold(kind=ThresholdKind.EXACT_MATCH),
)

R2 = MetricDef(
    metric_id="R2",
    description="Total matched endpoint pairs",
    promql="sum(dds_datawriter_matched_subscriptions_total)",
    unit="count",
    query_type="instant",
    threshold=Threshold(kind=ThresholdKind.EXACT_MATCH),
)

R3 = MetricDef(
    metric_id="R3",
    description="Peak heap memory — surgical container",
    promql='container_memory_usage_bytes{name=~"surgical.*"}',
    unit="MB",
    query_type="instant",
    threshold=Threshold(kind=ThresholdKind.PERCENTAGE, max_ratio=0.25),
)

R4 = MetricDef(
    metric_id="R4",
    description="Peak heap memory — dashboard container",
    promql='container_memory_usage_bytes{name=~"dashboard.*"}',
    unit="MB",
    query_type="instant",
    threshold=Threshold(kind=ThresholdKind.PERCENTAGE, max_ratio=0.25),
)

R5 = MetricDef(
    metric_id="R5",
    description="Collector Service telemetry ingestion rate",
    promql="rate(collector_samples_received_total[30s])",
    unit="samples/s",
    query_type="range",
    threshold=Threshold(kind=ThresholdKind.PERCENTAGE, max_ratio=0.50),
)

# All metrics in definition order
ALL_METRICS: list[MetricDef] = [
    L1,
    L2,
    L3,
    L4,
    L5,
    L6,
    T1,
    T2,
    T3,
    T4,
    T5,
    T6,
    R1,
    R2,
    R3,
    R4,
    R5,
]

METRICS_BY_ID: dict[str, MetricDef] = {m.metric_id: m for m in ALL_METRICS}
