"""Unit tests for the performance benchmark harness.

Tests comparison logic, threshold enforcement, baseline recording,
and CLI behavior — all without requiring Prometheus.

Spec: performance-baseline.md — Benchmark Execution, Baseline Recording,
      Regression Detection
Tags: @benchmark
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add the performance directory to sys.path so we can import directly
sys.path.insert(0, str(Path(__file__).parent))

from benchmark import build_result, compare_metric, compare_results, run
from metrics import ALL_METRICS, Threshold, ThresholdKind

pytestmark = [pytest.mark.benchmark]

# ── Comparison logic: PASS ───────────────────────────────────────────


class TestComparisonPass:
    """Comparison logic correctly reports PASS for metrics within threshold."""

    def test_percentage_within(self):
        """L1 at +15% (within +20% threshold) → PASS."""
        assert compare_metric("L1", 115.0, 100.0) == "PASS"

    def test_percentage_exact_baseline(self):
        """L1 at exact baseline → PASS."""
        assert compare_metric("L1", 100.0, 100.0) == "PASS"

    def test_percentage_at_boundary(self):
        """L1 at exactly +20% → PASS."""
        assert compare_metric("L1", 120.0, 100.0) == "PASS"

    def test_exact_match_pass(self):
        """R1 with same value → PASS."""
        assert compare_metric("R1", 12.0, 12.0) == "PASS"

    def test_absolute_zero_pass(self):
        """T6 at 0 → PASS."""
        assert compare_metric("T6", 0.0, 0.0) == "PASS"

    def test_percentage_with_cap_within(self):
        """L6 at +40% and under 30s cap → PASS."""
        assert compare_metric("L6", 14000.0, 10000.0) == "PASS"


# ── Comparison logic: FAIL ───────────────────────────────────────────


class TestComparisonFail:
    """Comparison logic correctly reports FAIL for metrics exceeding threshold."""

    def test_percentage_exceeded(self):
        """L1 at +25% (beyond +20% threshold) → FAIL."""
        assert compare_metric("L1", 125.0, 100.0) == "FAIL"

    def test_exact_match_fail(self):
        """R1 changed from 12 to 13 → FAIL."""
        assert compare_metric("R1", 13.0, 12.0) == "FAIL"

    def test_absolute_zero_fail(self):
        """T6 at 1 (non-zero) → FAIL."""
        assert compare_metric("T6", 1.0, 0.0) == "FAIL"

    def test_percentage_with_cap_exceeds_cap(self):
        """L6 within percentage but exceeds 30s hard cap → FAIL."""
        assert compare_metric("L6", 31000.0, 25000.0) == "FAIL"

    def test_percentage_with_cap_exceeds_percentage(self):
        """L6 exceeds +50% threshold → FAIL."""
        assert compare_metric("L6", 16000.0, 10000.0) == "FAIL"


# ── Comparison logic: NEW ────────────────────────────────────────────


class TestComparisonNew:
    """Comparison logic correctly reports NEW for metrics not in baseline."""

    def test_new_metric(self):
        """Metric with no baseline value → NEW."""
        assert compare_metric("L1", 100.0, None) == "NEW"

    def test_new_in_compare_results(self):
        """compare_results marks metric not in baseline as NEW."""
        current = {"L1": 100.0}
        baseline_metrics = {}
        results = compare_results(current, baseline_metrics)
        assert results[0]["verdict"] == "NEW"


# ── Comparison logic: REMOVED ────────────────────────────────────────


class TestComparisonRemoved:
    """Comparison logic correctly reports REMOVED for baseline metrics missing from current."""

    def test_removed_metric(self):
        """Baseline metric not in current run → REMOVED."""
        current = {}
        baseline_metrics = {"L1": {"value": 100.0, "unit": "µs"}}
        results = compare_results(current, baseline_metrics)
        assert results[0]["verdict"] == "REMOVED"


# ── T6: absolute zero threshold ──────────────────────────────────────


class TestT6AbsoluteZero:
    """T6 (deadline missed) comparison enforces absolute zero threshold."""

    def test_zero_passes(self):
        assert compare_metric("T6", 0.0, 0.0) == "PASS"

    def test_zero_current_no_baseline(self):
        assert compare_metric("T6", 0.0, None) == "NEW"

    def test_nonzero_fails_even_if_baseline_was_zero(self):
        assert compare_metric("T6", 1.0, 0.0) == "FAIL"

    def test_nonzero_fails_even_if_baseline_was_nonzero(self):
        """T6 threshold is absolute zero regardless of baseline."""
        assert compare_metric("T6", 5.0, 5.0) == "FAIL"


# ── R1/R2: exact match ──────────────────────────────────────────────


class TestExactMatch:
    """R1/R2 comparison enforces exact match."""

    def test_r1_same(self):
        assert compare_metric("R1", 10.0, 10.0) == "PASS"

    def test_r1_increased(self):
        assert compare_metric("R1", 11.0, 10.0) == "FAIL"

    def test_r1_decreased(self):
        assert compare_metric("R1", 9.0, 10.0) == "FAIL"

    def test_r2_same(self):
        assert compare_metric("R2", 24.0, 24.0) == "PASS"

    def test_r2_changed(self):
        assert compare_metric("R2", 25.0, 24.0) == "FAIL"


# ── L6: percentage + hard cap ────────────────────────────────────────


class TestL6DualThreshold:
    """L6 (discovery time) comparison enforces both percentage and hard cap."""

    def test_within_both(self):
        """Within +50% and under 30s → PASS."""
        assert compare_metric("L6", 12000.0, 10000.0) == "PASS"

    def test_exceeds_percentage(self):
        """Over +50% but under 30s → FAIL."""
        assert compare_metric("L6", 16000.0, 10000.0) == "FAIL"

    def test_exceeds_cap(self):
        """Within +50% but over 30s → FAIL."""
        assert compare_metric("L6", 31000.0, 25000.0) == "FAIL"

    def test_exceeds_both(self):
        """Over +50% and over 30s → FAIL."""
        assert compare_metric("L6", 50000.0, 10000.0) == "FAIL"


# ── Prometheus unreachable: exit code 2 ──────────────────────────────


class TestPrometheusUnreachable:
    """Harness exits with code 2 when Prometheus is unreachable."""

    def test_exit_code_2(self):
        with patch.dict(os.environ, {"PROMETHEUS_URL": "http://localhost:99999"}):
            with patch("benchmark.check_prometheus_reachable", return_value=False):
                code = run([])
        assert code == 2


# ── --record --phase writes baseline ─────────────────────────────────


class TestRecordBaseline:
    """--record --phase writes a valid JSON file to baselines/."""

    def test_record_writes_json(self, tmp_path):
        """Recording writes valid JSON with expected structure."""
        baselines_dir = tmp_path / "baselines"
        baselines_dir.mkdir()

        fake_metrics = {"L1": 850.0, "T6": 0.0, "R1": 12.0}
        result = build_result(fake_metrics, phase="test")
        result_path = baselines_dir / "test.json"
        with open(result_path, "w") as f:
            json.dump(result, f, indent=2)
            f.write("\n")

        # Validate structure
        with open(result_path) as f:
            loaded = json.load(f)

        assert loaded["version"] == "1.0"
        assert loaded["phase"] == "test"
        assert "timestamp" in loaded
        assert "git_commit" in loaded
        assert "metrics" in loaded
        assert "L1" in loaded["metrics"]
        assert loaded["metrics"]["L1"]["value"] == 850.0

    def test_record_via_cli(self, tmp_path, monkeypatch):
        """--record --phase test writes a baseline JSON file."""
        monkeypatch.setattr("benchmark.BASELINES_DIR", tmp_path)
        monkeypatch.setattr("benchmark.check_prometheus_reachable", lambda: True)
        monkeypatch.setattr("benchmark.query_metric", lambda *a: 42.0)

        code = run(["--record", "--phase", "test"])
        assert code == 0

        output_file = tmp_path / "test.json"
        assert output_file.exists()
        with open(output_file) as f:
            data = json.load(f)
        assert data["phase"] == "test"
        assert len(data["metrics"]) == len(ALL_METRICS)


# ── First run with no baseline: all NEW, exit 0 ─────────────────────


class TestFirstRunNoBaseline:
    """First run with no baseline reports all metrics as NEW and exits 0."""

    def test_no_baseline_exits_0(self, tmp_path, monkeypatch):
        """When no baseline exists, all metrics are NEW → exit 0."""
        empty_baselines = tmp_path / "baselines"
        empty_baselines.mkdir()
        monkeypatch.setattr("benchmark.BASELINES_DIR", empty_baselines)
        monkeypatch.setattr("benchmark.check_prometheus_reachable", lambda: True)
        monkeypatch.setattr("benchmark.query_metric", lambda *a: 100.0)

        code = run([])
        assert code == 0


# ── Threshold unit mechanics ─────────────────────────────────────────


class TestThresholdCheck:
    """Direct unit tests of Threshold.check() for edge cases."""

    def test_percentage_zero_baseline(self):
        """Percentage threshold with zero baseline — only 0 passes."""
        t = Threshold(kind=ThresholdKind.PERCENTAGE, max_ratio=0.20)
        assert t.check(0.0, 0.0) is True
        assert t.check(1.0, 0.0) is False

    def test_absolute_delta_fraction(self):
        """T5 threshold: baseline + 0.1% of total published."""
        t = Threshold(kind=ThresholdKind.ABSOLUTE_DELTA_FRACTION, fraction=0.001)
        # baseline=0, total_published=100000 → allowed = 0 + 100 = 100
        assert t.check(50.0, 0.0, total_published=100000.0) is True
        assert t.check(150.0, 0.0, total_published=100000.0) is False

    def test_throughput_drop_detected(self):
        """T1-T4 threshold: -10% means current must be >= baseline * 0.9."""
        t = Threshold(kind=ThresholdKind.PERCENTAGE, max_ratio=-0.10)
        # For throughput, "regression" means current < baseline * (1 + ratio)
        # ratio is -0.10, so allowed: current <= baseline * 0.90
        # Wait — this is the formula: current <= baseline * (1 + max_ratio)
        # For throughput drops, max_ratio is negative: current <= baseline * 0.90
        # So a drop from 500 to 450 (=0.9) should PASS
        assert t.check(450.0, 500.0) is True
        # A drop from 500 to 440 (=0.88) should FAIL
        assert t.check(440.0, 500.0) is False
