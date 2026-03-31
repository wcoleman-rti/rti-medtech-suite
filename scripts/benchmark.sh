#!/usr/bin/env bash
# scripts/benchmark.sh — One-command performance benchmark runner.
#
# Manages the full Docker stack lifecycle: start → health-check →
# warmup → measure → collect → record/compare → teardown.
#
# Usage:
#   bash scripts/benchmark.sh                              # compare vs latest baseline
#   bash scripts/benchmark.sh --record --phase phase-5     # record a new baseline
#   bash scripts/benchmark.sh --baseline baselines/phase-2.json  # compare vs specific baseline
#   bash scripts/benchmark.sh --no-teardown                # leave stack running after
#   bash scripts/benchmark.sh --skip-startup               # assume stack is already running
#
# Exit codes:
#   0  All metrics within thresholds (or baseline recorded)
#   1  One or more metrics exceed regression thresholds
#   2  Infrastructure error (Docker, Prometheus, etc.)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# ── Configuration ─────────────────────────────────────────────────

PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
WARMUP_S="${BENCHMARK_WARMUP_S:-15}"
MEASUREMENT_S="${BENCHMARK_MEASUREMENT_S:-60}"
HEALTH_TIMEOUT=120          # max seconds to wait for healthy stack
PROMETHEUS_TIMEOUT=90       # max seconds to wait for Prometheus targets
TEARDOWN=true
SKIP_STARTUP=false
BENCHMARK_ARGS=()

# ── Argument parsing ──────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-teardown)    TEARDOWN=false; shift ;;
        --skip-startup)   SKIP_STARTUP=true; shift ;;
        --warmup)         WARMUP_S="$2"; shift 2 ;;
        --measurement)    MEASUREMENT_S="$2"; shift 2 ;;
        *)                BENCHMARK_ARGS+=("$1"); shift ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────────

info()  { echo "▸ $*"; }
ok()    { echo "  ✓ $*"; }
warn()  { echo "  ⚠ $*" >&2; }
die()   { echo "  ✗ $*" >&2; exit 2; }

elapsed_since() {
    local start=$1
    echo $(( $(date +%s) - start ))
}

# ── Pre-flight checks ────────────────────────────────────────────

command -v docker >/dev/null 2>&1 || die "docker not found in PATH"
docker info >/dev/null 2>&1     || die "Docker daemon not reachable"
command -v python >/dev/null 2>&1 || die "python not found in PATH"
[[ -f tests/performance/benchmark.py ]] || die "benchmark.py not found"

# ── Phase 1: Start Docker stack ──────────────────────────────────

cleanup() {
    if [[ "$TEARDOWN" == true ]]; then
        info "Tearing down Docker stack..."
        docker compose --profile observability down --timeout 10 2>/dev/null || true
        ok "Stack torn down"
    else
        info "Leaving stack running (--no-teardown)"
    fi
}

if [[ "$SKIP_STARTUP" == true ]]; then
    info "Skipping stack startup (--skip-startup)"
else
    info "Starting Docker stack (CDS + services + observability)..."
    docker compose --profile observability up -d 2>&1 | tail -3
    ok "Docker compose started"
fi

# Register cleanup trap
trap cleanup EXIT

# ── Phase 2: Wait for Prometheus health ──────────────────────────

info "Waiting for Prometheus at $PROMETHEUS_URL (timeout: ${PROMETHEUS_TIMEOUT}s)..."
prom_start=$(date +%s)
until curl -sf "$PROMETHEUS_URL/api/v1/status/buildinfo" >/dev/null 2>&1; do
    if (( $(elapsed_since "$prom_start") > PROMETHEUS_TIMEOUT )); then
        die "Prometheus not reachable after ${PROMETHEUS_TIMEOUT}s"
    fi
    sleep 2
done
ok "Prometheus reachable ($(elapsed_since "$prom_start")s)"

# ── Phase 3: Wait for DDS metrics to appear ──────────────────────

info "Waiting for DDS metrics from Collector Service..."
metrics_start=$(date +%s)
until curl -sf "$PROMETHEUS_URL/api/v1/query?query=dds_domain_participant_presence" 2>/dev/null \
    | python -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('data',{}).get('result') else 1)" 2>/dev/null; do
    if (( $(elapsed_since "$metrics_start") > HEALTH_TIMEOUT )); then
        die "DDS metrics not appearing after ${HEALTH_TIMEOUT}s"
    fi
    sleep 3
done

# Report participant count
participant_count=$(curl -sf "$PROMETHEUS_URL/api/v1/query?query=count(dds_domain_participant_presence)" 2>/dev/null \
    | python -c "import sys,json; r=json.load(sys.stdin)['data']['result']; print(r[0]['value'][1] if r else '0')" 2>/dev/null || echo "?")
ok "DDS metrics visible — $participant_count participants ($(elapsed_since "$metrics_start")s)"

# ── Phase 4: Warmup ──────────────────────────────────────────────

info "Warmup period: ${WARMUP_S}s..."
sleep "$WARMUP_S"
ok "Warmup complete"

# ── Phase 5: Measurement window ──────────────────────────────────

info "Measurement window: ${MEASUREMENT_S}s..."
sleep "$MEASUREMENT_S"
ok "Measurement complete"

# ── Phase 6: Run benchmark harness ───────────────────────────────

info "Running benchmark harness..."
echo ""

# Activate venv if available
# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || true

benchmark_rc=0
python tests/performance/benchmark.py "${BENCHMARK_ARGS[@]}" || benchmark_rc=$?

echo ""

case $benchmark_rc in
    0)  ok "Benchmark PASSED" ;;
    1)  warn "Benchmark FAILED — regression detected" ;;
    2)  die "Benchmark harness error" ;;
    *)  die "Benchmark exited with unexpected code $benchmark_rc" ;;
esac

# ── Summary ───────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Benchmark run complete"
echo "  Warmup: ${WARMUP_S}s  Measurement: ${MEASUREMENT_S}s"
echo "  Participants: $participant_count"
if [[ $benchmark_rc -eq 0 ]]; then
    echo "  Result: PASS"
else
    echo "  Result: FAIL"
fi
echo "═══════════════════════════════════════════════════════════"

exit $benchmark_rc
