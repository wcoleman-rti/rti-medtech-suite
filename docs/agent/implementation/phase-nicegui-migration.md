# Phase N: NiceGUI Migration

**Goal:** Replace PySide6 with NiceGUI across all GUI applications, unifying the
event loop, enabling multi-client browser access, and upgrading the digital twin
to 3D visualization.

**Depends on:** Phase 3 Steps 3.1–3.5 (complete), Phase 5 (Procedure Orchestration)
**Blocks:** Phase 3 Steps 3.6–3.8 (to be reimplemented on NiceGUI)
**Spec coverage:** [nicegui-migration.md](../spec/nicegui-migration.md),
[hospital-dashboard.md](../spec/hospital-dashboard.md),
[clinical-alerts.md](../spec/clinical-alerts.md)

> **Migration principle:** Each step produces a working application. PySide6 code
> is not deleted until its NiceGUI replacement passes all corresponding tests.
> Both frameworks may coexist in the repo during migration.

---

## Step N.1 — Dependency & Infrastructure Update ✅ `1ddc0f6`

### Work

- Add `nicegui` to `requirements.txt`, remove `PySide6` and `pytest-qt`
- Update `pyproject.toml`: change `@gui` marker description from "PySide6 GUI verification" to "GUI verification"
- Update `THIRD_PARTY_NOTICES.md`: remove PySide6 (LGPL-3.0) and pytest-qt (MIT); add NiceGUI (MIT)
- Update `docker/runtime-python.Dockerfile`:
  - Remove Qt platform dependencies (`libgl1`, `libglib2.0-0`, `libfontconfig1`, `libxkbcommon0`, `libdbus-1-3`, `libegl1`)
  - Remove `QT_QPA_PLATFORM=offscreen`
  - Add `EXPOSE 8080` and `ENV NICEGUI_STORAGE_PATH=/data/nicegui`
- Establish `ui.run()` configuration constants for all NiceGUI apps:
  - `storage_secret` — required for `app.storage.user` and `app.storage.tab` persistence (generate and store securely)
  - `quasar_config={'iconSet': 'material-symbols-outlined'}` — enforced icon set (see vision doc § Iconography)
- Update `setup.bash.in` comment: replace PySide6 reference with NiceGUI
- Validate that `pip install -r requirements.txt` succeeds in the venv
- Validate that NiceGUI + rti.connext coexist on the same asyncio event loop (smoke test)

### Test Gate

- [x] `pip install -r requirements.txt` installs NiceGUI successfully
- [x] A minimal NiceGUI app with `rti.asyncio` DDS reader runs without event loop conflicts
- [x] Docker image builds without Qt dependencies
- [x] `ui.run(storage_secret=..., quasar_config={'iconSet': 'material-symbols-outlined'})` starts without errors

---

## Step N.2 — Shared GUI Module Rewrite ✅ `0ca1bb2`

### Work

- Create `_backend.py` — `GuiBackend` ABC (see [vision/nicegui-migration.md](../vision/nicegui-migration.md)):
  - Abstract: `start()` (launch background reader tasks), `close()` (release DDS resources), `name` (logging identifier)
  - Concrete: `__init__` registers `app.on_startup(self.start)` and `app.on_shutdown(self.close)` — minimal NiceGUI lifecycle wiring (follows `global_worker` example pattern)
  - DDS setup (participants, entity lookup) remains fully in each concrete subclass
  - Subclasses call `super().__init__()` as the last line of their `__init__`, after DDS setup is complete
  - Unit test: verify ABC cannot be instantiated without implementing all abstract members; verify hooks are registered on construction
- Rewrite `modules/shared/medtech/gui/__init__.py` to export `GuiBackend` and NiceGUI-based utilities
- Replace `_theme.py`:
  - `init_theme()` → function that calls `app.colors(primary='#004C97', accent='#ED8B00', ...)` and adds font CSS
  - `ThemeMode` enum → removed (NiceGUI's `ui.dark_mode()` handles this)
  - `ThemeManager` class → removed
  - Header bar → reusable function returning `ui.header()` with RTI logo, title, dark mode toggle, connection dot
- Replace `_widgets.py`:
  - `ConnectionDot` → function returning `ui.icon('circle')` with timer-driven color/pulse classes
  - `create_status_chip(state)` → function returning `ui.chip()` with color lookup dict
  - `create_stat_card(value, label, icon, color)` → function returning `ui.card()` with bound value label
  - `create_section_header(text, icon)` → function returning labeled `ui.row()`
  - `create_empty_state(text)` → function returning centered `ui.column()` with icon + label
- Serve fonts locally: `app.add_static_files('/fonts', 'resources/fonts/')` with `@font-face` CSS
- Add brand color constants module (`_colors.py`) for programmatic access
- Add icon constants module (`_icons.py`) — standard icon names for shared concepts (vitals, alerts, procedures, robot, etc.) using `sym_o_` prefix (Material Symbols outlined)

### Test Gate (spec: nicegui-migration.md — Theming & Branding, GuiBackend ABC Contract)

- [x] `GuiBackend` ABC enforces `start()`, `close()`, and `name` (all abstract)
- [x] `GuiBackend` cannot be instantiated directly (pure skeleton, like `Service`)
- [x] `app.colors()` applies RTI brand palette
- [x] Dark/light toggle works without page reload
- [x] Local fonts load correctly (no CDN requests)
- [x] All widget helper functions produce correctly styled elements
- [x] Icon set enforced as `material-symbols-outlined` via `quasar_config`
- [x] `test_init_theme.py` rewritten and passing with NiceGUI fixtures

---

## Step N.3 — Hospital Dashboard Migration

### Work

- Create `@ui.page('/dashboard')` function replacing `HospitalDashboard(QMainWindow)`
- DDS integration (subclass `GuiBackend` — see [vision/nicegui-migration.md](../vision/nicegui-migration.md)):
  - Implement `DashboardBackend(GuiBackend)`: DDS init + participant creation + entity lookup in `__init__`, call `super().__init__()` last, implement `start()` with `background_tasks.create()` per reader, implement `name` property
  - Reader topics: `ProcedureStatus`, `ProcedureContext`, `PatientVitals`, `AlarmMessages`, `RobotState`, `ClinicalAlert`, `ResourceAvailability`
  - Store received data in backend state dicts; UI reads from these
  - Module-level instantiation: `backend = DashboardBackend()` — DDS init runs synchronously; `super().__init__()` (called last) self-registers `start()` and `close()` with NiceGUI lifecycle hooks
- Layout:
  - `ui.header()` with shared header bar (RTI logo, title, dark toggle, connection dot)
  - `ui.splitter()` with procedure list (left) and detail panel (right)
  - Procedure list: `@ui.refreshable` function rendering `ui.card()` per procedure
  - Detail panel: `ui.tab_panels()` for vitals / alerts / robot per selected procedure
  - Alert feed: `ui.scroll_area()` at bottom with `ui.card()` per alert
  - Severity filter: `ui.select()` bound to filter state
  - Room filter: `ui.select()` bound to filter state
- `VitalsRow` → `ui.row()` with `ui.badge()` for HR/SpO2/BP, color bound to severity
- `ui.timer(0.5, ...)` for periodic UI rebuild (replaces 2 Hz QTimer)
- New: `ui.echart()` sparkline for vitals trend (rolling 60 s window)
- New: `ui.notification()` for CRITICAL alert browser push

### Test Gate (spec: hospital-dashboard.md — all scenarios + nicegui-migration.md)

- [ ] Dashboard renders at `/dashboard` with all panels
- [ ] Procedure list auto-updates on new `ProcedureStatus`
- [ ] Vitals color-coded by severity thresholds
- [ ] Alert feed filterable by severity and room
- [ ] New CRITICAL alert within 2 s display latency
- [ ] Multiple browser clients see consistent data
- [ ] `test_hospital_dashboard.py` rewritten and passing

---

## Step N.4 — Procedure Controller Migration

### Work

- Create `@ui.page('/controller')` function replacing `ProcedureController(QMainWindow)`
- DDS integration (subclass `GuiBackend`):
  - Implement `ControllerBackend(GuiBackend)`: DDS init + participant creation + entity lookup in `__init__`, call `super().__init__()` last, implement `start()` and `name`
  - Async reader loops via `background_tasks.create()` for `ServiceStatus`, `HostStatus` topics
  - RPC requester: `await run.io_bound(requester.send_request, ...)` for non-blocking RPC (NiceGUI `run.io_bound` wraps sync calls in a thread)
- Layout:
  - `ui.header()` with shared header bar
  - `ui.tabs()` for Host View / Service View toggle
  - `ui.tab_panels()` containing respective grids
  - Host/Service cards: `ui.card()` in `ui.grid(columns=4)` or flex row, `on_click` for selection
  - Stat cards: `ui.row()` of `create_stat_card()` with bound values
  - Floating action: `ui.page_sticky(position='bottom-center')` with context-aware buttons
  - Result card: `ui.dialog()` for RPC result display
- Liveliness-based host removal: `StatusCondition` + async wait for `LIVELINESS_CHANGED`

### Test Gate (spec: hospital-dashboard.md — Procedure Controller scenarios)

- [ ] Controller renders at `/controller` with host/service views
- [ ] Service discovery populates cards in real-time
- [ ] RPC calls execute without blocking UI
- [ ] Host removal on liveliness loss
- [ ] `test_procedure_controller.py` (integration) rewritten and passing

---

## Step N.5 — Digital Twin 3D Migration

### Work

- Create `@ui.page('/twin/{room_id}')` function replacing `DigitalTwinDisplay(QMainWindow)`
- DDS integration (subclass `GuiBackend`):
  - Implement `DigitalTwinBackend(GuiBackend)`: DDS init + participant creation + entity lookup in `__init__`, call `super().__init__()` last, implement `start()` and `name`
  - Async readers for `RobotState`, `RobotCommand`, `SafetyInterlock`, `OperatorInput` via `background_tasks.create()`
  - Time-based filter: 100 ms minimum separation (unchanged)
  - Note: unlike the dashboard, the digital twin creates a per-client participant scoped to one room. Use `app.on_disconnect` or `close()` (required by `GuiBackend`) for cleanup when client navigates away.
  - Partition derived from `room_id` path parameter — set before `participant.enable()`; `super().__init__()` is called last (after enable), same as all other backends
- 3D scene (`ui.scene()`):
  - Robot base: `scene.sphere()` with RTI Blue material
  - Arm segments: `scene.cylinder()` per joint, positioned/rotated from joint angles
  - Joint knuckles: `scene.sphere()` at articulation points
  - Tool tip: `scene.sphere()` with RTI Green material
  - Heatmap coloring: `.material(heatmap_color(joint_value))` — same diverging ramp
  - Orbit controls enabled by default (drag to rotate, scroll to zoom)
  - `scene.text('mode')` for operational mode overlay
- Safety interlock: `ui.notification('SAFETY INTERLOCK ACTIVE', type='negative', timeout=None)`
- Mode badge: `ui.badge()` with color per mode (OPERATIONAL/PAUSED/E-STOP/IDLE)
- `ui.timer(0.1, update_scene)` for 10 Hz scene refresh
- New: `ui.joystick()` element for operator input demo (optional)

### Test Gate (spec: nicegui-migration.md — Digital Twin 3D scenarios)

- [ ] 3D scene renders robot arm with joint angles from DDS
- [ ] Heatmap coloring updates per joint
- [ ] Orbit/zoom controls work during live data
- [ ] Safety interlock overlay appears on interlock sample
- [ ] `test_digital_twin.py` rewritten and passing

---

## Step N.6 — Unified App & SPA Navigation

### Work

- Create root app entry point (`modules/shared/medtech/gui/app.py` or `__main__.py`)
  - `@ui.page('/')` root page with persistent app shell: `ui.header()` (logo, title, dark toggle, connection dot), `ui.left_drawer()` (navigation links)
  - `ui.sub_pages()` for SPA client-side routing — swaps content area without full page reload; header, drawer, and WebSocket persist across navigation
  - Imports page builder functions from dashboard, controller, digital twin modules
  - `GuiBackend` subclasses are instantiated at module level in each page module — `super().__init__()` self-registers `start()` / `close()` with NiceGUI hooks automatically. The unified app does **not** manually call `start()` or `close()`.
  - Static file serving: `app.add_static_files('/static', 'resources/')`
- FastAPI health/readiness endpoints (NiceGUI is built on FastAPI):
  - `GET /health` — liveness probe, returns `{"status": "ok"}`
  - `GET /ready` — readiness probe, returns 200 if all `GuiBackend` participants are active, 503 otherwise
  - Update `docker/medtech-app.Dockerfile` `HEALTHCHECK` to use `curl http://localhost:8080/health`
- `ui.run()` with `storage_secret` and `quasar_config` (from Step N.1 constants)
- Update `docker/medtech-app.Dockerfile` entry point to launch unified app

### Test Gate (spec: nicegui-migration.md — Page Routing, SPA Navigation, Health & Readiness Probes)

- [ ] Landing page at `/` with working navigation drawer
- [ ] SPA navigation swaps content without full page reload
- [ ] Header, drawer, and WebSocket persist during navigation
- [ ] All `GuiBackend` hooks fire via self-registration (no manual orchestration)
- [ ] `GET /health` returns 200
- [ ] `GET /ready` returns 200 when backends are active, 503 otherwise
- [ ] All pages accessible from single container

---

## Step N.7 — Complete Remaining Dashboard Steps on NiceGUI

### Work

Resume Phase 3 steps that were not yet complete, now implemented on NiceGUI:

- **Step 3.6 (Robot Status Display)** — robot status cards with mode indicator, E-STOP flash, liveliness disconnect detection. Use `ui.chip()` with color binding, `ui.timer()` for flash animation.
- **Step 3.6b (Resource Panel)** — resource availability grid using `ui.aggrid()` or `ui.table()` with live row updates. Create resource simulator service.
- **Step 3.7 (Content Filtering & Detail View)** — per-room drill-down via content-filtered topic. Create filtered DDS subscription when user selects a procedure.
- **Step 3.8 (Module README & Documentation Compliance)** — update all README files to reflect NiceGUI architecture.

### Test Gate (spec: hospital-dashboard.md — Robot Status, Resource Panel, GUI Threading)

- [ ] Robot state per OR with mode indicator
- [ ] E-STOP prominently displayed
- [ ] Robot disconnect detected via liveliness
- [ ] Resource panel displays and updates in real-time
- [ ] Content-filtered topic delivers only matching patient data
- [ ] DDS data processing does not block UI (burst test)

---

## Step N.8 — Agent Documentation Update

### Work

- Update `docs/agent/vision/technology.md` — GUI Framework section: NiceGUI replaces PySide6; remove QtAsyncio references; add NiceGUI deployment model
- Update `docs/agent/vision/ui-design-system.md` — Applicability section: replace PySide6 file references with NiceGUI equivalents; add NiceGUI component mapping table; update DDS Threading Patterns section for native asyncio
- Update `docs/agent/vision/coding-standards.md` — Python GUI section: NiceGUI conventions (declarative with-blocks, `@ui.page`, `@ui.refreshable`, Tailwind classes)
- Update `docs/agent/spec/hospital-dashboard.md` — remove PySide6 references in preamble; update UI thread protection requirement for asyncio model
- Update `docs/agent/implementation/phase-3-dashboard.md` — mark completed steps; reference NiceGUI migration phase for remaining steps
- Remove `resources/styles/medtech.qss` and `resources/styles/medtech-dark.qss`
- Archive PySide6 code (or delete after all tests pass on NiceGUI)

### Test Gate

- [ ] All `@gui` tests pass
- [ ] Full test suite passes (`pytest --tb=short`)
- [ ] No PySide6 imports remain in application code
- [ ] No Qt platform dependencies in Docker images
- [ ] `markdownlint` passes on all updated docs

---

## Step N.9 — Cleanup & Dependency Removal

### Work

- Delete PySide6-specific files:
  - `resources/styles/medtech.qss`
  - `resources/styles/medtech-dark.qss`
  - Old `_theme.py` and `_widgets.py` (replaced in Step N.2)
  - Old `__main__.py` entry points with `QApplication` (replaced in Steps N.3–N.5)
- Remove `PySide6` and `pytest-qt` from `requirements.txt` (if not done in N.1)
- Remove `QT_QPA_PLATFORM` from any remaining scripts/configs
- Final `grep -r "PySide6\|QtWidgets\|QApplication\|pytest-qt"` to confirm zero references
- Tag release

### Test Gate

- [ ] Zero PySide6/Qt references in codebase (verified by grep)
- [ ] Full test suite passes
- [ ] Docker image builds and runs successfully
- [ ] All GUI applications accessible via browser

---

## Step N.10 — Project-Wide PySide6/Qt Reference Purge in Agent Docs

### Rationale

After implementation is complete, all remaining references to PySide6, Qt,
QtAsyncio, QSS, `QApplication`, `QMainWindow`, `QPainter`, `pytest-qt`, and
related Qt terminology must be removed or replaced throughout the entire
`docs/agent/` tree (and project-wide). This ensures there is no confusion
about the implementation direction going forward — NiceGUI is the sole GUI
framework.

### Work

- **Automated scan:** `grep -rn "PySide6\|QtWidgets\|QApplication\|QtAsyncio\|QMainWindow\|QPainter\|QTimer\|pytest-qt\|QSS\|\.qss\|QT_QPA_PLATFORM\|Qt event loop\|Qt signals" docs/agent/ modules/ scripts/ docker/ *.txt *.toml *.md`
- **Vision docs** (`docs/agent/vision/`):
  - `technology.md` — GUI Framework section: replace PySide6 description with NiceGUI; remove QtAsyncio references; update DDS I/O threading paragraph
  - `ui-design-system.md` — DDS Threading Patterns section: replace QtAsyncio/Qt signal references with NiceGUI asyncio model; update Applicability file list; update Prohibited Patterns if any reference Qt
  - `coding-standards.md` — update any Python GUI conventions that reference Qt widgets, QSS, or Qt-specific patterns; add NiceGUI conventions (`@ui.page`, `@ui.refreshable`, Tailwind classes, lifecycle hooks)
  - `dds-consistency.md` — update §3 Python examples if they reference QtAsyncio; ensure `async`/`await` guidance mentions NiceGUI event loop (not Qt)
  - `capabilities.md` — replace "PySide6 GUI" references with "NiceGUI web application" for Digital Twin, Dashboard, Controller
  - `system-architecture.md` — update any GUI-related architectural notes
- **Spec docs** (`docs/agent/spec/`):
  - `hospital-dashboard.md` — preamble: "NiceGUI dashboard" (not "PySide6 dashboard"); UI thread protection requirement: update for asyncio model
  - `common-behaviors.md` — update threading model references if Qt-specific
  - Any other spec referencing "PySide6", "Qt", or "QMainWindow"
- **Implementation docs** (`docs/agent/implementation/`):
  - `phase-3-dashboard.md` — update goal line and completed steps to reflect NiceGUI; add note that remaining steps moved to phase-nicegui-migration.md
  - `phase-2-surgical.md` — if Digital Twin steps reference PySide6, update
  - Any other phase doc referencing Qt
- **Root / config files:**
  - `README.md` — update technology references
  - `setup.bash.in` — update venv comment
  - `THIRD_PARTY_NOTICES.md` — should already be updated in N.1, verify
  - `docker-compose.yml` — verify no Qt env vars remain
- **Verification:** After all edits, re-run the grep scan and confirm zero hits for Qt/PySide6 terminology in the entire repo (excluding `build/`, `.venv/`, `_deps/`)

### Test Gate

- [ ] `grep -rn "PySide6\|QtWidgets\|QApplication\|pytest-qt" --include="*.md" --include="*.py" --include="*.txt" --include="*.toml" --include="*.yml" docs/ modules/ scripts/ docker/ resources/` returns zero results
- [ ] All doc references use NiceGUI terminology consistently
- [ ] `markdownlint` passes on all updated docs
- [ ] No broken cross-references between agent docs
