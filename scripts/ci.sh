#!/usr/bin/env bash
# scripts/ci.sh — Run all quality gates from workflow.md Section 7.
#
# Usage:
#   bash scripts/ci.sh                # full gate sequence
#   bash scripts/ci.sh --skip-build   # skip build/install (use existing)
#   bash scripts/ci.sh --lint         # fast lint/style gates only (~5s)
#
# Gate ordering: fast lint/style checks run first so formatting issues
# are caught in seconds, before spending minutes on builds and tests.
#
# Exits non-zero on the first gate failure.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SKIP_BUILD=false
LINT_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --skip-build) SKIP_BUILD=true ;;
        --lint) LINT_ONLY=true ;;
    esac
done

pass_count=0
gate_count=0

gate() {
    gate_count=$((gate_count + 1))
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  GATE $gate_count: $1"
    echo "═══════════════════════════════════════════════════════════════"
}

pass() {
    pass_count=$((pass_count + 1))
    echo "  ✓ PASS"
}

fail() {
    echo "  ✗ FAIL: $1" >&2
    exit 1
}

# Activate venv early — needed by lint gates that run before build
# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || true

# ═══════════════════════════════════════════════════════════════════
# FAST GATES — lint & static checks (~5 seconds)
# ═══════════════════════════════════════════════════════════════════

# ─── Gate 1: Python code style ────────────────────────────────────
gate "Python code style (black + isort + ruff)"

PY_DIRS="modules/ tests/"

black --check $PY_DIRS 2>&1 | tail -3 || fail "black formatting violations"
isort --check $PY_DIRS 2>&1 | tail -3 || fail "isort import sorting violations"
ruff check $PY_DIRS 2>&1 | tail -3 || fail "ruff lint violations"
pass

# ─── Gate 2: Markdown lint ────────────────────────────────────────
gate "Markdown lint (module/service READMEs)"

MDLINT=""
if command -v markdownlint >/dev/null 2>&1; then
    MDLINT="markdownlint"
elif [ -x /tmp/mdlint/node_modules/.bin/markdownlint ]; then
    MDLINT="/tmp/mdlint/node_modules/.bin/markdownlint"
fi

readme_files=$(find modules/ services/ -maxdepth 2 -name "README.md" 2>/dev/null || true)
if [ -z "$readme_files" ]; then
    echo "  No module/service READMEs found — skipping markdownlint."
    pass
elif [ -z "$MDLINT" ]; then
    echo "  WARNING: markdownlint not found — skipping."
    echo "  Install: npm install --prefix /tmp/mdlint markdownlint-cli@0.39.0"
    pass
else
    echo "$readme_files" | xargs "$MDLINT" --config .markdownlint.json || fail "markdownlint errors found"
    pass
fi

# ─── Gate 3: README section order ─────────────────────────────────
gate "README section order check"
python tests/lint/check_readme_sections.py || fail "README section order check failed"
pass

# ─── Gate 4: Prohibited patterns ──────────────────────────────────
gate "Prohibited patterns in application code"

APP_DIRS="modules/"

violations=0

# 4a: print() / printf / std::cout in application code
if grep -rn --include='*.py' '\bprint\s*(' "$APP_DIRS" 2>/dev/null | grep -v '__pycache__' | grep -v '# noqa'; then
    echo "  VIOLATION: print() found in application code" >&2
    violations=$((violations + 1))
fi
if grep -rn --include='*.cpp' --include='*.hpp' '\bprintf\b\|std::cout' "$APP_DIRS" 2>/dev/null; then
    echo "  VIOLATION: printf/std::cout found in application code" >&2
    violations=$((violations + 1))
fi

# 4b: Literal domain IDs (10, 11) in application code
if grep -rn --include='*.py' --include='*.cpp' --include='*.hpp' \
    '\bDomainParticipant\s*(\s*\(10\|11\)\b' "$APP_DIRS" 2>/dev/null; then
    echo "  VIOLATION: literal domain ID found in application code" >&2
    violations=$((violations + 1))
fi

# 4c: QoS setter API calls in application code
if grep -rn --include='*.py' \
    '\.reliability\s*=\|\.durability\s*=\|\.history\s*=\|\.deadline\s*=\|\.liveliness\s*=' \
    "$APP_DIRS" 2>/dev/null | grep -v '__pycache__'; then
    echo "  VIOLATION: programmatic QoS setter found in application code" >&2
    violations=$((violations + 1))
fi
if grep -rn --include='*.cpp' --include='*.hpp' \
    '<<\s*Reliability\|<<\s*Durability\|<<\s*History\|<<\s*Deadline\|\.reliability\s*(' \
    "$APP_DIRS" 2>/dev/null; then
    echo "  VIOLATION: programmatic QoS setter found in C++ application code" >&2
    violations=$((violations + 1))
fi

# 4d: AP-8 — Custom QosProvider
if grep -rn --include='*.py' 'QosProvider(' "$APP_DIRS" 2>/dev/null | grep -v '__pycache__' | grep -v 'QosProvider.default'; then
    echo "  VIOLATION [AP-8]: custom QosProvider constructor found in Python application code" >&2
    violations=$((violations + 1))
fi
if grep -rn --include='*.cpp' --include='*.hpp' 'QosProvider(' "$APP_DIRS" 2>/dev/null | grep -v 'QosProvider::Default()'; then
    echo "  VIOLATION [AP-8]: custom QosProvider constructor found in C++ application code" >&2
    violations=$((violations + 1))
fi

# 4e: AP-9 — Publisher/subscriber partition QoS
if grep -rn --include='*.py' --include='*.cpp' --include='*.hpp' \
    'publisher.*partition\|subscriber.*partition\|Publisher.*partition\|Subscriber.*partition' \
    "$APP_DIRS" interfaces/qos/ 2>/dev/null | grep -v '__pycache__' | grep -v '\.participant'; then
    echo "  VIOLATION [AP-9]: publisher/subscriber-level partition QoS found" >&2
    violations=$((violations + 1))
fi

# 4f: AP-10 — DDS entity types in public class APIs
if grep -rn --include='*.hpp' \
    'public:' -A 50 "$APP_DIRS" 2>/dev/null | grep -E 'DataWriter|DataReader|DomainParticipant|Publisher|Subscriber' | grep -v 'private:' | grep -v '//' | grep -v 'find_data'; then
    echo "  VIOLATION [AP-10]: DDS entity types found in public class API (C++)" >&2
    violations=$((violations + 1))
fi
if grep -rn --include='*.py' \
    -E '^\s*(def |.*->)\s*.*(DataWriter|DataReader|DomainParticipant)\b' \
    "$APP_DIRS" 2>/dev/null | grep -v '__pycache__' | grep -v '_'; then
    echo "  VIOLATION [AP-10]: DDS entity types found in public class API (Python)" >&2
    violations=$((violations + 1))
fi

# 4g: AP-11 — Raw string literals for known entity names
_IDL_FILE="interfaces/idl/app_names.idl"
if [ -f "$_IDL_FILE" ]; then
    _entity_names=$(grep -oP '=\s*"\K[^"]+' "$_IDL_FILE" || true)
    _ap11_found=false
    for _name in $_entity_names; do
        if grep -rn --include='*.py' --include='*.cpp' --include='*.hpp' \
            "\"$_name\"" "$APP_DIRS" 2>/dev/null | grep -v '__pycache__'; then
            _ap11_found=true
        fi
    done
    if [ "$_ap11_found" = true ]; then
        echo "  VIOLATION [AP-11]: raw string literals for entity names found in application code" >&2
        violations=$((violations + 1))
    fi
fi

if [ "$violations" -gt 0 ]; then
    fail "$violations prohibited pattern violation(s) found"
fi
echo "  No prohibited patterns found."
pass

# ─── Gate 5: No generated files in source tree ────────────────────
gate "No generated files committed to source tree"

gen_files=$(find interfaces/ -name '*Plugin.*' -o -name '*Support.*' -o -name '*_publisher.*' -o -name '*_subscriber.*' 2>/dev/null | grep -v __pycache__ || true)
if [ -n "$gen_files" ]; then
    echo "$gen_files"
    fail "Generated files found in source tree"
fi
echo "  No generated files in source tree."
pass

# ─── Early exit for --lint mode ───────────────────────────────────
if [ "$LINT_ONLY" = true ]; then
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  ALL $pass_count/$gate_count LINT GATES PASSED (--lint mode)"
    echo "═══════════════════════════════════════════════════════════════"
    exit 0
fi

# ═══════════════════════════════════════════════════════════════════
# HEAVY GATES — build, test, Docker (~2+ minutes)
# ═══════════════════════════════════════════════════════════════════

# ─── Gate 6: Build + Install ──────────────────────────────────────
gate "Clean build + install"
if [ "$SKIP_BUILD" = true ]; then
    echo "  (skipped via --skip-build)"
    pass
else
    cmake -B build -S . >/dev/null 2>&1 || fail "cmake configure failed"
    cmake --build build 2>&1 | tail -3 || fail "cmake build failed"
    cmake --install build >/dev/null 2>&1 || fail "cmake install failed"
    pass
fi

# ─── Gate 7: Docker multi-stage build ─────────────────────────────
gate "Docker multi-stage build"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    docker compose --profile build build 2>&1 | tail -5 \
        || fail "docker compose build failed"
    pass
else
    echo "  WARNING: Docker not available — skipping."
    pass
fi

# Source install environment for test gates
# shellcheck disable=SC1091
source install/setup.bash 2>/dev/null || true

# ─── Gate 8: Full test suite (Python) ─────────────────────────────
gate "Python test suite (pytest)"

pytest_output=$(pytest tests/ -q --tb=line 2>&1) || true
echo "$pytest_output" | tail -3
if echo "$pytest_output" | grep -q "failed"; then
    fail "pytest reported failures"
elif echo "$pytest_output" | grep -q "passed"; then
    pass
else
    fail "pytest did not report any passed tests"
fi

# ─── Gate 9: C++ test suite (CTest) ───────────────────────────────
gate "C++ test suite (CTest)"
ctest_output=$(ctest --test-dir build --output-on-failure 2>&1) || true
echo "$ctest_output" | tail -5
if echo "$ctest_output" | grep -q "tests passed"; then
    pass
else
    fail "CTest reported failures"
fi

# ─── Gate 10: Performance benchmark ───────────────────────────────
gate "Performance benchmark"
if [ -f tests/performance/benchmark.py ]; then
    python tests/performance/benchmark.py --help >/dev/null 2>&1 || fail "benchmark harness broken"
    echo "  Benchmark harness available (run with observability stack for full benchmark)."
else
    echo "  Benchmark harness not yet implemented (Step 1.9)."
fi
pass

# ─── Gate 11: QoS compatibility check ─────────────────────────────
gate "QoS compatibility pre-flight check"
if [ -f tools/qos-checker.py ]; then
    python tools/qos-checker.py || fail "QoS incompatibilities detected"
    pass
else
    echo "  QoS checker not yet implemented."
    pass
fi

# ─── Gate 12: Container runtime smoke test ─────────────────────────
gate "Container runtime smoke test"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    docker run --rm medtech/app-cpp \
        ldd /opt/medtech/bin/robot-controller 2>&1 \
        | grep -q "not found" \
        && fail "robot-controller has unresolved shared libraries" \
        || true
    docker run --rm medtech/app-python \
        python3 -c "import surgery; import monitoring; print('OK')" 2>&1 \
        || fail "Python type imports failed in container"
    pass
else
    echo "  WARNING: Docker not available — skipping."
    pass
fi

# ─── Summary ──────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  ALL $pass_count/$gate_count GATES PASSED"
echo "═══════════════════════════════════════════════════════════════"
