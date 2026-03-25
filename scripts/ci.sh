#!/usr/bin/env bash
# scripts/ci.sh — Run all quality gates from workflow.md Section 7.
#
# Usage:
#   bash scripts/ci.sh          # full gate sequence
#   bash scripts/ci.sh --skip-build   # skip build/install (use existing)
#
# Exits non-zero on the first gate failure.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SKIP_BUILD=false
for arg in "$@"; do
    case "$arg" in
        --skip-build) SKIP_BUILD=true ;;
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

# ─── Gate 1: Build + Install ──────────────────────────────────────
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

# ─── Gate 2: Full test suite (Python) ─────────────────────────────
gate "Python test suite (pytest)"

# Source the install environment for tests
# shellcheck disable=SC1091
source install/setup.bash 2>/dev/null || true
# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || true

pytest_output=$(pytest tests/ -q --tb=line 2>&1) || true
echo "$pytest_output" | tail -3
if echo "$pytest_output" | grep -q "failed"; then
    fail "pytest reported failures"
elif echo "$pytest_output" | grep -q "passed"; then
    pass
else
    fail "pytest did not report any passed tests"
fi

# ─── Gate 3: C++ test suite (CTest) ───────────────────────────────
gate "C++ test suite (CTest)"
ctest_output=$(ctest --test-dir build --output-on-failure 2>&1) || true
echo "$ctest_output" | tail -5
if echo "$ctest_output" | grep -q "tests passed"; then
    pass
else
    fail "CTest reported failures"
fi

# ─── Gate 4: Markdown lint ────────────────────────────────────────
gate "Markdown lint (module/service READMEs)"

# Find markdownlint — check PATH, then common local install locations
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

# ─── Gate 5: README section order ─────────────────────────────────
gate "README section order check"
python tests/lint/check_readme_sections.py || fail "README section order check failed"
pass

# ─── Gate 6: Prohibited patterns ──────────────────────────────────
gate "Prohibited patterns in application code"

# Directories containing application code (not tests, not tools)
APP_DIRS="modules/"

violations=0

# 6a: print() / printf / std::cout in application code
if grep -rn --include='*.py' '\bprint\s*(' "$APP_DIRS" 2>/dev/null | grep -v '__pycache__' | grep -v '# noqa'; then
    echo "  VIOLATION: print() found in application code" >&2
    violations=$((violations + 1))
fi
if grep -rn --include='*.cpp' --include='*.hpp' '\bprintf\b\|std::cout' "$APP_DIRS" 2>/dev/null; then
    echo "  VIOLATION: printf/std::cout found in application code" >&2
    violations=$((violations + 1))
fi

# 6b: Literal domain IDs (10, 11) in application code
# Match standalone integers 10 or 11 that look like domain ID usage
if grep -rn --include='*.py' --include='*.cpp' --include='*.hpp' \
    '\bDomainParticipant\s*(\s*\(10\|11\)\b' "$APP_DIRS" 2>/dev/null; then
    echo "  VIOLATION: literal domain ID found in application code" >&2
    violations=$((violations + 1))
fi

# 6c: QoS setter API calls in application code
# Look for programmatic QoS setting patterns
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

# 6d: AP-8 — Custom QosProvider (only QosProvider::Default / QosProvider.default allowed)
if grep -rn --include='*.py' 'QosProvider(' "$APP_DIRS" 2>/dev/null | grep -v '__pycache__' | grep -v 'QosProvider.default'; then
    echo "  VIOLATION [AP-8]: custom QosProvider constructor found in Python application code" >&2
    violations=$((violations + 1))
fi
if grep -rn --include='*.cpp' --include='*.hpp' 'QosProvider(' "$APP_DIRS" 2>/dev/null | grep -v 'QosProvider::Default()'; then
    echo "  VIOLATION [AP-8]: custom QosProvider constructor found in C++ application code" >&2
    violations=$((violations + 1))
fi

# 6e: AP-9 — Publisher/subscriber partition QoS (only participant-level allowed)
if grep -rn --include='*.py' --include='*.cpp' --include='*.hpp' \
    'publisher.*partition\|subscriber.*partition\|Publisher.*partition\|Subscriber.*partition' \
    "$APP_DIRS" interfaces/qos/ 2>/dev/null | grep -v '__pycache__' | grep -v '\.participant'; then
    echo "  VIOLATION [AP-9]: publisher/subscriber-level partition QoS found" >&2
    violations=$((violations + 1))
fi

# 6f: AP-10 — DDS entity types in public class APIs (headers / class-level hints)
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

# 6g: AP-11 — Raw string literals for known entity names in application code
# Extract all entity name values from app_names.idl and check for raw usage
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

# ─── Gate 7: No generated files in source tree ────────────────────
gate "No generated files committed to source tree"

gen_files=$(find interfaces/ -name '*Plugin.*' -o -name '*Support.*' -o -name '*_publisher.*' -o -name '*_subscriber.*' 2>/dev/null | grep -v __pycache__ || true)
if [ -n "$gen_files" ]; then
    echo "$gen_files"
    fail "Generated files found in source tree"
fi
echo "  No generated files in source tree."
pass

# ─── Gate 8: Python code style ────────────────────────────────────
gate "Python code style (black + isort + ruff)"

# Find Python dirs containing .py files (exclude build, install, .venv)
PY_DIRS="modules/ tests/"

black --check $PY_DIRS 2>&1 | tail -3 || fail "black formatting violations"
isort --check $PY_DIRS 2>&1 | tail -3 || fail "isort import sorting violations"
ruff check $PY_DIRS 2>&1 | tail -3 || fail "ruff lint violations"
pass

# ─── Gate 9: Performance benchmark (placeholder) ──────────────────
gate "Performance benchmark"
if [ -f tests/performance/benchmark.py ]; then
    python tests/performance/benchmark.py --help >/dev/null 2>&1 || fail "benchmark harness broken"
    echo "  Benchmark harness available (run with observability stack for full benchmark)."
else
    echo "  Benchmark harness not yet implemented (Step 1.9)."
fi
pass

# ─── Gate 10: QoS compatibility check ─────────────────────────────
gate "QoS compatibility pre-flight check"
if [ -f tools/qos-checker.py ]; then
    python tools/qos-checker.py || fail "QoS incompatibilities detected"
    pass
else
    echo "  QoS checker not yet implemented."
    pass
fi

# ─── Summary ──────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  ALL $pass_count/$gate_count GATES PASSED"
echo "═══════════════════════════════════════════════════════════════"
