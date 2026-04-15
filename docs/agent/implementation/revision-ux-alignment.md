# Revision: UX Alignment

**Goal:** Align the user experience across setup, launch, and interaction
workflows with the design decisions documented in the UX audit. This
revision touches the hospital dashboard (room-centric primary view),
the Procedure Controller (room-deployed, procedure lifecycle workflow),
room-level GUI navigation (`medtech.gui.room_nav`), and the simulation
CLI (`medtech build --docker`, controller container deployment).

**Depends on:** Phase SIM (V1.4 — Distributed Simulation & CLI complete)
**Blocks:** Nothing — UX improvement within existing architecture
**Version impact:** Minor bump (V1.5.0)

**Spec coverage:**
- [hospital-dashboard.md](../spec/hospital-dashboard.md)
  (`Room Overview`, `Active Procedures` scenarios)
- [procedure-orchestration.md](../spec/procedure-orchestration.md)
  (`Procedure Lifecycle Workflow`, `Room-Level GUI Navigation` scenarios)
- [simulation-cli.md](../spec/simulation-cli.md)
  (`medtech build --docker`, `medtech build --all`, updated `medtech run or`)

**Vision references:**
- [capabilities.md](../vision/capabilities.md) — Module 2 (Room Overview
  primary view, Navigation Model), V1.0.0 Procedure Controller (room-deployed,
  procedure lifecycle)
- [system-architecture.md](../vision/system-architecture.md) — Split-GUI
  Deployment (controller room-deployed, nav model, Docker topology)

---

## Step UX.1 — `medtech build --docker` and `--all`

### Work

- Add `--docker` flag to `medtech build` in
  `modules/shared/medtech/cli/_main.py`:
  - Runs `docker compose build` (or individual `docker build` commands
    for all project images)
  - Prints each command before execution
- Add `--all` flag:
  - Runs CMake build + install followed by Docker image build
- Update `medtech build` help text to document both flags
- Update project root `README.md` quick-start to reference
  `medtech build --all`

### Test Gate

- [ ] `medtech build --docker --help` prints usage
- [ ] `medtech build --all` runs CMake then Docker builds
- [ ] `medtech build` (no flags) continues to run CMake only (backward compat)
- [ ] **@smoke Tier 1:** `medtech build --help` exits 0 and lists `--docker` and `--all` flags
- [ ] All existing tests pass
- [ ] Lint passes

---

## Step UX.2 — Room-Deployed Procedure Controller

### Work

- **Move controller from hospital container to per-room container:**
  - Update `modules/shared/medtech/cli/_or.py` to launch a
    `medtech-controller-<or_key>` container alongside the twin container:
    - Image: `medtech/app-python`
    - Command: `python -m hospital_dashboard.procedure_controller`
    - Networks: `surgical-net` + `orchestration-net` (dual-homed)
    - Host port: auto-assigned from controller port range (base: 8091
      for unnamed hospital, offset by hospital ordinal for named)
    - Env: `ROOM_ID`, `PROCEDURE_ID`, `HOST_ID`, `NDDS_DISCOVERY_PEERS`,
      `MEDTECH_GUI_EXTERNAL_URL=http://localhost:<controller_port>`
  - Update `modules/shared/medtech/cli/_hospital.py` to **not** launch
    a controller container — `medtech-gui` serves dashboard only
  - Update `medtech-gui` SPA shell (`modules/shared/medtech/gui/app.py`)
    to remove controller imports and routes; serve only `/dashboard` and
    `/` (redirect to `/dashboard`)
  - The controller continues to register its `gui_url` in `ServiceCatalog`
    (already implemented), so the hospital dashboard discovers it via
    RS-bridged `ServiceCatalog`

- **Controller container serves its own SPA shell:**
  - Create a lightweight entry point for the per-room controller GUI
    that uses NiceGUI's standard `ui.run()` with the controller page as
    the root
  - Include the room_nav pill (Step UX.4) for horizontal navigation

- **Update `medtech launch` output:**
  - Prominently display dashboard URL as the primary entry point
  - Include per-OR controller and twin URLs in summary table

### Test Gate

- [ ] `medtech run or --name OR-1` starts controller container alongside twin
- [ ] Controller container joins both `surgical-net` and `orchestration-net`
- [ ] Controller is accessible at assigned host port
- [ ] `medtech-gui` serves only the hospital dashboard (no controller routes)
- [ ] `medtech launch` output shows dashboard URL prominently, includes per-OR controller URLs
- [ ] `medtech stop` removes controller containers
- [ ] **@smoke Tier 1:** `import medtech.gui.app` succeeds; registered sub_pages contain `/dashboard` only (no `/controller`, no `/twin`)
- [ ] **@smoke Tier 1:** `from hospital_dashboard.procedure_controller import controller` succeeds
- [ ] **@smoke Tier 2:** Hospital dashboard container starts; `GET /health` returns 200 within 30 s
- [ ] **@smoke Tier 2:** Controller container starts with `ROOM_ID=OR-1`; `GET /health` returns 200 within 30 s
- [ ] All existing tests pass
- [ ] Lint passes

---

## Step UX.3 — Room-Centric Hospital Dashboard

### Work

- **Rewrite hospital dashboard primary view as room cards:**
  - Subscribe to RS-bridged `ServiceCatalog` on the Hospital Integration databus (already
    delivered by per-room MedtechBridge) to discover rooms and their
    GUI URLs
  - Render room cards as the primary view: room name, active procedure
    indicator (from `procedure_id` property in `ServiceCatalog`),
    service counts (from `ServiceStatus` aggregated per room), and
    alert/warning counts (from `ClinicalAlert` filtered by room)
  - Room cards include action links to room-level GUIs: "Controller"
    and "Twin" buttons with `open_in_new` icon (Material Icons) that
    open the `gui_url` in a new browser tab
  - Room cards without `gui_url` entries show no action links

- **Add "Active Procedures" secondary view:**
  - Filtered view showing only rooms with a non-empty `procedure_id`
  - Shows procedure type, surgeon, phase, patient, elapsed time
    (from bridged `ProcedureStatus` and `ProcedureContext`)

- **Preserve existing dashboard views:**
  - Vitals Overview, Alert Feed, Robot Status, Resource Panel remain
    as they are — these become detail/drill-down panels accessible
    from the room card or from tab navigation within the dashboard

### Test Gate

- [ ] Hospital dashboard primary view shows room cards
- [ ] Room cards display room name and active procedure indicator
- [ ] Room cards show aggregate service counts (running/total)
- [ ] Room cards show alert/warning counts per room
- [ ] New rooms auto-appear when `ServiceCatalog` arrives
- [ ] Room card action links include `open_in_new` icon
- [ ] Clicking a room GUI link opens a new browser tab
- [ ] Active Procedures secondary view filters to rooms with procedures
- [ ] Existing vitals, alert, robot, resource panels still render
- [ ] All existing dashboard spec tests pass (may need adaptation for
      new primary view structure)
- [ ] **@smoke Tier 1:** Hospital dashboard entry point imports without error; `/dashboard` route is registered
- [ ] **@smoke Tier 2:** Hospital dashboard container starts; `GET /health` returns 200; dashboard URL is reachable
- [ ] All existing tests pass
- [ ] Lint passes

---

## Step UX.4 — Room-Level GUI Navigation Module (`medtech.gui.room_nav`)

### Work

- **Author `modules/shared/medtech/gui/room_nav.py`:**
  - Creates a single read-only Orchestration databus participant
    (the Orchestration databus, `procedure` tier partition)
  - Subscribes to `ServiceCatalog` topic
  - Filters by `room_id` matching the current room (passed as
    constructor parameter)
  - Maintains a live dict of `{display_name: gui_url}` for sibling
    GUIs in the same room
  - Provides a `render_nav_pill()` function that:
    - Renders a floating nav pill (shared CSS with existing pill style)
    - Shows a button for each discovered sibling GUI (dynamic — updates
      as services start/stop via `@ui.refreshable` / `ui.timer()`)
    - Highlights the currently active page
    - **No upward link to hospital dashboard** — room GUIs have
      visibility at and below their level only. A room can be deployed
      standalone without a hospital instance above it.
    - Uses the design token system and glassmorphism styling from
      the existing UI modernization phase
  - DDS reads run as asyncio coroutines (never block the event loop)

- **Integrate room_nav into existing room GUIs:**
  - Procedure Controller: replace existing nav pill with `room_nav`
  - Digital Twin: add `room_nav` pill (currently has no nav pill)
  - Each GUI passes its `room_id` to the module (no dashboard URL needed)

- **Dashboard URL discovery:**
  - Not applicable — room GUIs do **not** link to the hospital
    dashboard. Room-level services have visibility at and below their
    level only, matching the layered databus principle that lower
    levels never depend on upper levels. To return to the hospital
    view, the user closes the room tab.

### Test Gate

- [ ] `room_nav` module creates Orchestration participant and discovers
      sibling GUIs via `ServiceCatalog`
- [ ] Nav pill renders buttons for each discovered sibling GUI
- [ ] Nav pill updates dynamically when a sibling GUI starts or stops
- [ ] Clicking a sibling button navigates the current tab to that URL
- [ ] Nav pill does **not** include any link to the hospital dashboard
- [ ] Room GUI operates correctly without a hospital instance deployed
- [ ] Procedure Controller uses `room_nav` for navigation
- [ ] Digital Twin uses `room_nav` for navigation
- [ ] DDS reads do not block the NiceGUI event loop
- [ ] All existing tests pass
- [ ] Lint passes

---

## Step UX.5 — Procedure Lifecycle Workflow

### Work

- **Add "Start Procedure" workflow to Procedure Controller UI:**
  - When no `ServiceCatalog` entries for the current room have a
    non-empty `procedure_id`, show a "Start Procedure" button
  - Clicking "Start Procedure" opens a selection view of idle services
    (those with empty `procedure_id`)
  - User selects services and clicks "Deploy"
  - Controller generates a unique `procedure_id` (e.g.,
    `<room_id>-<timestamp>` or `<room_id>-<sequence>`)
  - Controller sends `start_service` RPCs to each selected service's
    host, including `procedure_id` as a property

- **Add procedure management actions:**
  - When a procedure is active: show "Add Services" and
    "Stop Procedure" actions
  - "Add Services" re-opens the selection view showing only remaining
    idle services; deploys with the same `procedure_id`
  - "Stop Procedure" sends `stop_service` RPCs to all services with
    the active `procedure_id`

- **One active procedure per room constraint:**
  - Disable "Start Procedure" when any `ServiceCatalog` entry for
    the room has a non-empty `procedure_id`
  - Display the active procedure indicator (type, phase, elapsed)

- **Procedure state reconstruction:**
  - On controller restart, TRANSIENT_LOCAL `ServiceCatalog` samples
    with non-empty `procedure_id` reconstruct the active procedure
    view — no manual re-deployment needed

### Test Gate

- [ ] "Start Procedure" button visible when room has no active procedure
- [ ] Start Procedure workflow shows idle services for selection
- [ ] Deploying selected services sends RPCs with generated `procedure_id`
- [ ] Active procedure indicator shown after deployment
- [ ] "Start Procedure" disabled when a procedure is already active
- [ ] "Add Services" deploys additional services with same `procedure_id`
- [ ] "Stop Procedure" stops all services with the active `procedure_id`
- [ ] Stopped services clear `procedure_id` from `ServiceCatalog`
- [ ] Procedure state reconstructed on controller restart
- [ ] All existing orchestration tests pass
- [ ] All existing tests pass
- [ ] Lint passes

---

## Step UX.6 — Regression & Acceptance

### Work

- Run the full quality gate pipeline (`bash scripts/ci.sh`)
- Run the end-to-end user workflow:
  1. `medtech build --all`
  2. `medtech launch`
  3. Open dashboard (`http://localhost:8080`) — verify room cards
  4. Click room GUI link → new tab opens room controller
  5. In controller: Start Procedure → select services → Deploy
  6. Nav pill → click Twin → navigates to twin in same tab
  7. Close room tab → return to hospital dashboard
  8. Hospital dashboard → room card shows active procedure indicator
  9. `medtech stop` — clean teardown
- Write `@acceptance` test that programmatically validates the above

### Test Gate

- [ ] All `@gui` spec tests pass for Room Overview scenarios
- [ ] All `@orchestration` spec tests pass for Procedure Lifecycle scenarios
- [ ] All `@cli` spec tests pass for updated build/run/launch
- [ ] **@smoke Tier 1:** All entry point import tests pass (hospital app, controller, twin, CLI)
- [ ] **@smoke Tier 2:** All container startup tests pass (hospital, controller, twin, C++ runtime)
- [ ] `@acceptance` test validates the composed end-to-end UX workflow
- [ ] All existing tests pass
- [ ] Lint passes (including markdownlint)
- [ ] Performance benchmark passes against the Phase SIM baseline

---

## Tests to Rewrite or Remove

The following existing tests verify behavior that is superseded by V1.5.0.
They should be **removed or replaced** during the implementation steps above.
Do not preserve these tests as-is — they validate the old unified-app /
sidebar navigation model that no longer applies.

### `tests/gui/test_unified_app.py`

| Test | Reason | Action | Step |
|------|--------|--------|------|
| `TestShellPage::test_shell_page_registers_sub_pages` | Asserts `/controller/{room_id}` and `/twin/{room_id}` in hospital app sub_pages — those routes move to room containers | **Rewrite**: hospital app sub_pages should only contain `/dashboard` (and `/alerts` when added) | UX.2 |
| `TestShellPage::test_shell_page_sub_pages_use_content_functions` | Imports `controller_content_for_room` and `twin_content` and asserts they're in hospital app routes | **Rewrite**: only `dashboard_content` should remain in hospital app routes | UX.2 |
| `TestShellPage::test_shell_page_nav_pill_has_static_buttons` | Asserts ≥2 static nav buttons (Dashboard + Controller) | **Rewrite**: only 1 static button (Dashboard) in hospital app; Controller moves to room nav | UX.3 |
| `TestDiscoveredRooms` (entire class: 3 tests) | Tests `_discovered_rooms()` via `ControllerBackend` — discovery moves to `DashboardBackend` reading bridged `ServiceCatalog` on the Hospital Integration databus | **Rewrite**: new discovery tests should use `DashboardBackend` directly | UX.3 |
| `TestPageTitleForPath::test_controller_path` | `/controller/OR-1` path won't exist in hospital app | **Move**: to room-level app test suite | UX.2 |
| `TestPageTitleForPath::test_twin_with_room_id` | `/twin/OR-1` path won't exist in hospital app | **Move**: to room-level app test suite | UX.2 |
| `TestPageTitleForPath::test_twin_with_different_room_id` | Same as above | **Move**: to room-level app test suite | UX.2 |
| `TestMainUsesRoot::test_main_calls_ui_run_with_root` | Mocks controller backend factory that will no longer exist in hospital app | **Adjust**: remove controller/twin mock patching | UX.2 |

### `tests/integration/test_cli_launch.py`

| Test | Reason | Action | Step |
|------|--------|--------|------|
| `TestLaunchUnified::test_starts_unified` | Tests `medtech launch unified` — command removed | **Remove** | UX.1 |

### `tests/integration/test_cli_split_gui.py`

| Test | Reason | Action | Step |
|------|--------|--------|------|
| `TestGuiModeEnvVar::test_default_gui_mode_is_unified` | `MEDTECH_GUI_MODE` env var removed — no unified fallback | **Remove** | UX.2 |
| `TestGuiModeEnvVar::test_controller_dashboard_mode` | Same — env var removed | **Remove** | UX.2 |
| `TestDockerComposeGuiMode::test_compose_has_gui_mode` | Asserts `MEDTECH_GUI_MODE` in docker-compose.yml — env var removed | **Remove** | UX.2 |

### `tests/integration/test_cli_acceptance_sim.py`

| Test | Reason | Action | Step |
|------|--------|--------|------|
| `test_launch_unified` | Tests `medtech launch unified` — command removed | **Remove** | UX.1 |

### Tests to Keep (no changes needed)

| Test | Why |
|------|-----|
| `TestStaticNavItems::test_controller_is_per_room_not_static` | Already asserts controller is excluded from static nav — still valid |
| `TestStaticNavItems::test_static_nav_count` | Asserts 1 static nav item — still valid |
| `TestDigitalTwinGuiUrl` (2 tests) | Tests `gui_url` construction from env vars — still valid for room containers |
| `TestDigitalTwinMain` (2 tests) | Tests `MEDTECH_GUI_EXTERNAL_URL` handling — still valid |
| All `TestGuiBackend*` tests | Backend lifecycle contract unchanged |
| All `test_hospital_dashboard.py` tests | Dashboard data display tests unaffected by nav model |
| All `test_digital_twin.py` tests | Twin rendering tests unaffected |
| All `test_procedure_controller.py` tests | Controller backend logic unaffected |
