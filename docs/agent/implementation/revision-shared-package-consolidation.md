# Revision: Shared Package Consolidation

**Goal:** Consolidate the four separate top-level Python packages
(`medtech`, `medtech_dds_init`, `medtech_logging`, `medtech_gui`) under
`modules/shared/` into a single `medtech` namespace package. Unify the
C++ include and source directories under `modules/shared/include/` and
`modules/shared/src/`. No behavioral change — purely structural.

**Depends on:** Phase 5 Steps 5.1–5.6 (all shared code exists)

**Must complete before:** Phase 5 Step 5.7 (E2E Orchestration Integration)

**Vision references:**

- [vision/coding-standards.md — Shared Package Structure](../vision/coding-standards.md)
- [vision/technology.md — Shared GUI Bootstrap](../vision/technology.md)
- [vision/dds-consistency.md — §1 Step 1](../vision/dds-consistency.md)
- [vision/ui-design-system.md — Applicability](../vision/ui-design-system.md)

---

## Step RC.1 — Restructure Python Packages

### Work

Consolidate the Python package layout under `modules/shared/medtech/`:

1. **Move `medtech_dds_init/dds_init.py`** →
   `medtech/dds.py`. Rename the function's module but keep the public
   API (`initialize_connext()`) unchanged.
2. **Move `medtech_logging/_logging.py`** →
   `medtech/log.py`. Keep the public API (`init_logging()`,
   `ModuleLogger`, `ModuleName`) unchanged. The name `log` avoids
   shadowing the standard library `logging` module.
3. **Move `medtech_gui/`** → `medtech/gui/`. Preserve internal
   structure (`__init__.py`, `_theme.py`, `_widgets.py`).
4. **Update `medtech/__init__.py`** to re-export `Service` and
   `ServiceState` (unchanged public API).
5. **Remove the old directories** (`medtech_dds_init/`,
   `medtech_logging/`, `medtech_gui/`). The `.gitkeep` sentinels in
   `medtech_gui/` and `medtech_logging/` are no longer needed.
6. **Update CMake install rules** in the top-level `CMakeLists.txt`:
   - Replace the four separate `install(DIRECTORY ...)` rules with a
     single rule that installs `modules/shared/medtech/` to
     `lib/python/site-packages/medtech/`.
   - Preserve `FILES_MATCHING PATTERN "*.py"`.
   - Exclude `include/` and `src/` from the Python install.

### Test Gate

- [ ] `python -c "from medtech.service import Service"` succeeds after
      install
- [ ] `python -c "from medtech.dds import initialize_connext"` succeeds
      after install
- [ ] `python -c "from medtech.log import init_logging, ModuleName"`
      succeeds after install
- [ ] `python -c "from medtech.gui import init_theme"` succeeds after
      install
- [ ] No `medtech_dds_init/`, `medtech_logging/`, or `medtech_gui/`
      directories exist under `modules/shared/` or
      `install/lib/python/site-packages/`
- [ ] `bash scripts/ci.sh --lint` passes (no import errors, no stale
      references)

---

## Step RC.2 — Update All Python Imports

### Work

Update every Python file that imports from the old package names:

| Old import | New import |
|------------|-----------|
| `from medtech_dds_init.dds_init import initialize_connext` | `from medtech.dds import initialize_connext` |
| `from medtech_logging import init_logging, ModuleName, ModuleLogger` | `from medtech.log import init_logging, ModuleName, ModuleLogger` |
| `from medtech_gui import init_theme` | `from medtech.gui import init_theme` |
| `from medtech_gui import ConnectionDot, ...` | `from medtech.gui import ConnectionDot, ...` |
| `from medtech_gui._theme import ThemeManager` | `from medtech.gui._theme import ThemeManager` |

**Scope** — files under:

- `modules/surgical-procedure/` (all service files, digital twin,
  service hosts)
- `modules/hospital-dashboard/` (procedure controller)
- `modules/clinical-alerts/` (if any exist)
- `tests/` (all test files referencing shared packages)
- `tools/` (any tool scripts)

### Test Gate

- [ ] `grep -rn "medtech_dds_init\|medtech_logging\|medtech_gui"
      modules/ tests/ tools/ --include="*.py"` returns zero hits
- [ ] `bash scripts/ci.sh` passes (full pipeline — build, lint, Python
      tests, C++ tests, Docker gates)

---

## Step RC.3 — Consolidate C++ Include and Source Directories

### Work

Relocate C++ headers and source from the scattered per-package
directories to a unified layout:

1. **Move headers:**
   - `medtech_dds_init/include/medtech/*.hpp` →
     `modules/shared/include/medtech/`
   - `medtech_logging/include/medtech/logging.hpp` →
     `modules/shared/include/medtech/` (already in the same namespace)
2. **Move source:**
   - `medtech_dds_init/service_host.cpp` →
     `modules/shared/src/service_host.cpp`
   - `medtech_dds_init/CMakeLists.txt` →
     `modules/shared/src/CMakeLists.txt` (update paths)
3. **Update CMake:**
   - Top-level `CMakeLists.txt`: change `add_subdirectory(modules/shared/medtech_dds_init)`
     to `add_subdirectory(modules/shared/src)`
   - `modules/shared/src/CMakeLists.txt`: update
     `target_include_directories` to point to `${CMAKE_SOURCE_DIR}/modules/shared/include`
   - All consumers that use
     `${CMAKE_SOURCE_DIR}/modules/shared/medtech_dds_init/include` or
     `${CMAKE_SOURCE_DIR}/modules/shared/medtech_logging/include`
     change to `${CMAKE_SOURCE_DIR}/modules/shared/include`
   - Update the `install(DIRECTORY ... include/ ...)` rule to install
     from `modules/shared/include/`
4. **Remove the old directories** (`medtech_dds_init/include/`,
   `medtech_dds_init/service_host.cpp`,
   `medtech_logging/include/`).

### Test Gate

- [ ] `cmake --build build && cmake --install build` succeeds
- [ ] `ctest --test-dir build --output-on-failure` passes
- [ ] No `medtech_dds_init/` or `medtech_logging/include/` directories
      exist under `modules/shared/`
- [ ] `#include "medtech/service_host.hpp"` resolves from
      `modules/shared/include/medtech/` (verified by successful build)
- [ ] `bash scripts/ci.sh` passes (full pipeline)

---

## Step RC.4 — Update Documentation References

### Work

Update all remaining references to old paths in non-vision documentation:

1. **`docs/agent/implementation/` files** — update path references in
   `revision-dds-consistency.md`, `phase-1-foundation.md`,
   `phase-2-surgical.md`, and `phase-5-orchestration.md` to reflect
   the new `medtech.dds`, `medtech.log`, `medtech.gui` import paths
   and the new directory layout.
2. **`docs/agent/incidents.md`** — no changes needed (incidents are
   historical records; paths were accurate at time of writing).
3. **Module READMEs** — update any import examples in `modules/shared/README.md`
   or other module READMEs that reference old package names.
4. **Docker files** — verify `docker/medtech-app.Dockerfile` and
   `docker-compose.yml` do not hardcode old package paths (they should
   not — they use the install tree, not source paths).

### Test Gate

- [ ] `grep -rn "medtech_dds_init\|medtech_logging\|medtech_gui"
      docs/agent/implementation/ docs/agent/vision/ modules/
      --include="*.md"` returns zero hits (excluding `incidents.md`
      historical entries)
- [ ] `bash scripts/ci.sh --lint` passes (markdownlint, README checks)
- [ ] `bash scripts/ci.sh` passes
