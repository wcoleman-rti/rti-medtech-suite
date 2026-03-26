#!/usr/bin/env python3
"""Performance benchmark harness.

Orchestrates workload timing, queries Prometheus for DDS metrics,
compares results against baselines, and produces JSON output.

See vision/performance-baseline.md for the full specification.

Usage:
    python tests/performance/benchmark.py                 # compare vs latest baseline
    python tests/performance/benchmark.py --record --phase phase-2
    python tests/performance/benchmark.py --baseline path/to/baseline.json
    python tests/performance/benchmark.py --help
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from metrics import ALL_METRICS, METRICS_BY_ID, MetricDef

BASELINES_DIR = Path(__file__).parent / "baselines"
RESULT_VERSION = "1.0"

# Workload parameters from vision/performance-baseline.md
WARMUP_S = 15
MEASUREMENT_S = 60
COOLDOWN_S = 5


# ── Prometheus Query Interface ───────────────────────────────────────


def get_prometheus_url() -> str:
    return os.environ.get("PROMETHEUS_URL", "http://localhost:9090")


def _prometheus_get(path: str, params: dict) -> dict:
    """Make a GET request to the Prometheus HTTP API."""
    from urllib.parse import urlencode

    query_string = urlencode(params)
    url = f"{get_prometheus_url()}{path}?{query_string}"
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=10) as resp:  # noqa: S310 — URL from env config
        return json.loads(resp.read())


def query_instant(promql: str) -> float | None:
    """Execute an instant query and return the scalar value."""
    result = _prometheus_get("/api/v1/query", {"query": promql})
    if result.get("status") != "success":
        return None
    data = result.get("data", {})
    results = data.get("result", [])
    if not results:
        return None
    # For aggregations, return the single value; for vectors, sum all
    if data.get("resultType") == "scalar":
        return float(results[1])
    total = 0.0
    for r in results:
        val = r.get("value", [None, None])
        if val[1] is not None:
            total += float(val[1])
    return total


def query_range(
    promql: str, start: float, end: float, step: str = "5s"
) -> float | None:
    """Execute a range query and return the average value over the window."""
    result = _prometheus_get(
        "/api/v1/query_range",
        {
            "query": promql,
            "start": str(start),
            "end": str(end),
            "step": step,
        },
    )
    if result.get("status") != "success":
        return None
    results = result.get("data", {}).get("result", [])
    if not results:
        return None
    # Average all values across all series
    all_values = []
    for series in results:
        for _ts, val in series.get("values", []):
            all_values.append(float(val))
    if not all_values:
        return None
    return sum(all_values) / len(all_values)


def query_metric(metric: MetricDef, start: float, end: float) -> float | None:
    """Query Prometheus for a single metric."""
    if metric.query_type == "instant":
        return query_instant(metric.promql)
    return query_range(metric.promql, start, end)


def check_prometheus_reachable() -> bool:
    """Return True if Prometheus is reachable."""
    try:
        result = _prometheus_get("/api/v1/status/buildinfo", {})
        return result.get("status") == "success"
    except (URLError, OSError, TimeoutError):
        return False


# ── Baseline Management ──────────────────────────────────────────────


def find_latest_baseline() -> Path | None:
    """Find the lexicographically latest baseline JSON in baselines/."""
    if not BASELINES_DIR.exists():
        return None
    baselines = sorted(BASELINES_DIR.glob("*.json"))
    return baselines[-1] if baselines else None


def load_baseline(path: Path) -> dict:
    """Load a baseline JSON file."""
    with open(path) as f:
        return json.load(f)


def save_baseline(data: dict, phase: str) -> Path:
    """Save a baseline JSON file."""
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    path = BASELINES_DIR / f"{phase}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    return path


# ── Comparison Logic ─────────────────────────────────────────────────


def compare_metric(
    metric_id: str,
    current_value: float,
    baseline_value: float | None,
    total_published: float | None = None,
) -> str:
    """Compare a single metric against its baseline.

    Returns: "PASS", "FAIL", "NEW", or "REMOVED".
    """
    metric_def = METRICS_BY_ID.get(metric_id)
    if metric_def is None:
        return "FAIL"

    if baseline_value is None:
        return "NEW"

    return (
        "PASS"
        if metric_def.threshold.check(current_value, baseline_value, total_published)
        else "FAIL"
    )


def compare_results(
    current: dict[str, float],
    baseline_metrics: dict[str, dict],
    total_published: float | None = None,
) -> list[dict]:
    """Compare all current metrics against a baseline.

    Returns a list of per-metric result dicts.
    """
    results = []
    all_ids = set(current.keys()) | set(baseline_metrics.keys())

    for mid in sorted(all_ids):
        if mid not in current:
            results.append(
                {
                    "metric_id": mid,
                    "verdict": "REMOVED",
                    "baseline": baseline_metrics[mid].get("value"),
                    "current": None,
                }
            )
            continue

        current_val = current[mid]
        baseline_val = (
            baseline_metrics[mid].get("value") if mid in baseline_metrics else None
        )

        verdict = compare_metric(mid, current_val, baseline_val, total_published)
        results.append(
            {
                "metric_id": mid,
                "verdict": verdict,
                "baseline": baseline_val,
                "current": current_val,
            }
        )

    return results


# ── Result Construction ──────────────────────────────────────────────


def get_git_commit() -> str:
    """Get the current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def build_result(
    metrics: dict[str, float],
    phase: str | None = None,
) -> dict:
    """Build a benchmark result dict."""
    result = {
        "version": RESULT_VERSION,
        "phase": phase or "unknown",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
        "environment": {
            "connext_version": "7.6.0",
            "docker_compose_profile": "observability",
            "surgical_instances": 2,
            "measurement_duration_s": MEASUREMENT_S,
            "warmup_s": WARMUP_S,
        },
        "metrics": {},
    }
    for mid, value in sorted(metrics.items()):
        metric_def = METRICS_BY_ID.get(mid)
        result["metrics"][mid] = {
            "value": value,
            "unit": metric_def.unit if metric_def else "unknown",
        }
    return result


# ── CLI & Main ───────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Performance benchmark harness for the medtech suite.",
        epilog="See vision/performance-baseline.md for details.",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="Record a new baseline (requires --phase).",
    )
    parser.add_argument(
        "--phase",
        type=str,
        default=None,
        help="Phase name for baseline recording (e.g. phase-1).",
    )
    parser.add_argument(
        "--baseline",
        type=str,
        default=None,
        help="Path to a specific baseline JSON to compare against.",
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    """Main entry point. Returns exit code (0, 1, or 2)."""
    args = parse_args(argv)

    if args.record and not args.phase:
        sys.stderr.write("Error: --record requires --phase\n")
        return 2

    # Check Prometheus connectivity
    if not check_prometheus_reachable():
        sys.stderr.write(
            f"Error: Prometheus not reachable at {get_prometheus_url()}\n"
            "Ensure the observability stack is running "
            "(docker compose --profile observability up -d)\n"
        )
        return 2

    # Collect metrics from Prometheus
    measurement_end = time.time()
    measurement_start = measurement_end - MEASUREMENT_S

    collected: dict[str, float] = {}
    for metric in ALL_METRICS:
        value = query_metric(metric, measurement_start, measurement_end)
        if value is not None:
            collected[metric.metric_id] = value

    # Build result
    result = build_result(collected, phase=args.phase)

    # Record mode
    if args.record:
        path = save_baseline(result, args.phase)
        sys.stdout.write(f"Baseline recorded: {path}\n")
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
        return 0

    # Compare mode — find baseline
    if args.baseline:
        baseline_path = Path(args.baseline)
    else:
        baseline_path = find_latest_baseline()

    if baseline_path is None:
        # No baseline exists — all metrics are NEW
        sys.stdout.write("No baseline found. All metrics reported as NEW.\n")
        for mid in sorted(collected.keys()):
            sys.stdout.write(
                f"  {mid}: {collected[mid]} [{METRICS_BY_ID[mid].unit}] — NEW\n"
            )
        return 0

    baseline_data = load_baseline(baseline_path)
    baseline_metrics = baseline_data.get("metrics", {})

    # Get total published for T5 threshold
    total_published = None
    for tid in ("T1", "T2", "T3", "T4"):
        if tid in collected:
            rate = collected[tid]
            total_published = (total_published or 0) + rate * MEASUREMENT_S

    comparison = compare_results(collected, baseline_metrics, total_published)

    # Report
    sys.stdout.write(f"Comparing against baseline: {baseline_path.name}\n\n")
    has_fail = False
    for entry in comparison:
        mid = entry["metric_id"]
        verdict = entry["verdict"]
        current = entry["current"]
        baseline = entry["baseline"]
        metric_def = METRICS_BY_ID.get(mid)
        unit = metric_def.unit if metric_def else ""

        if verdict == "FAIL":
            has_fail = True

        marker = {"PASS": "✓", "FAIL": "✗", "NEW": "?", "REMOVED": "−"}.get(
            verdict, " "
        )
        sys.stdout.write(f"  {marker} {mid}: {current} {unit}")
        if baseline is not None:
            sys.stdout.write(f" (baseline: {baseline})")
        sys.stdout.write(f" — {verdict}\n")

    sys.stdout.write("\n")
    if has_fail:
        sys.stdout.write(
            "RESULT: FAIL — one or more metrics exceed regression thresholds\n"
        )
        return 1

    sys.stdout.write("RESULT: PASS — all metrics within thresholds\n")
    return 0


if __name__ == "__main__":
    sys.exit(run())
