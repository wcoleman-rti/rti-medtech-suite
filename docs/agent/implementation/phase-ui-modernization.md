# Phase UI-M: UI Modernization

**Goal:** Fix SPA navigation UX and modernize the visual design of all GUI
applications to align with the updated design system (glassmorphism, design
tokens, Inter font, semantic type scale, modern status indicators, animations,
accessibility). The first step fixes a critical UX regression; remaining
steps are visual-only — no DDS, IDL, QoS, or architectural changes.

**Depends on:** Phase 3 (Hospital Dashboard), Phase 5 (Procedure Orchestration),
Phase N (NiceGUI Migration) Steps N.1–N.5 ✅, Phase 20 (Multi-Arm)
**Blocks:** Nothing — this is an additive polish phase
**Version impact:** Minor bump (V1.2.x or V1.3.0 depending on scope)
**Spec coverage:** [hospital-dashboard.md](../spec/hospital-dashboard.md)
(`@ui-modernization` scenarios), [surgical-procedure.md](../spec/surgical-procedure.md)
(`@ui-modernization` scenarios), [nicegui-migration.md](../spec/nicegui-migration.md)
(SPA navigation + font update scenarios)

> **Principle:** Each step produces a visually improved but functionally identical
> application. All existing `@gui`, `@e2e`, and `@integration` tests must
> continue to pass after each step. New `@ui-modernization` tests are added
> incrementally.

---

## Step M.0 — Fix SPA Navigation (Unified App Shell) ✅ `cca747b`

### Problem

The unified app (`app.py`) renders the SPA shell (header + left drawer +
`ui.sub_pages()`) at the `@ui.page("/")` route. But each GUI module also
registers a standalone `@ui.page()` at its own route:

- `dashboard.py` → `@ui.page("/dashboard")`
- `controller.py` → `@ui.page("/controller")`
- `digital_twin.py` → `@ui.page("/twin/{room_id}")`

When the sidebar navigation calls `ui.navigate.to("/dashboard")`, the URL
changes to `/dashboard`. On browser refresh, the **standalone** handler wins
— the page renders without the shell (no sidebar, no header, no way to
navigate back). The only escape is the browser back button.

### Root Cause

NiceGUI's `ui.sub_pages()` is designed to work with `ui.run(root_function)`,
where the root function handles **all** URL paths and `ui.sub_pages()` does
client-side routing internally. But the current code uses `@ui.page("/")`
(matches only exact `/`) for the shell, while also registering server-side
`@ui.page()` handlers at each sub-path.

### Fix

1. **Remove `@ui.page("/")` decorator** from `shell_page()` in `app.py`.
   Instead, pass `shell_page` directly to `ui.run()`:
   ```python
   ui.run(shell_page, storage_secret=..., reload=False, ...)
   ```
   This makes `shell_page` the handler for **all** paths. `ui.sub_pages()`
   inside it handles sub-path routing client-side, and the shell (header,
   drawer, connection dot) persists across all navigations and refreshes.

2. **Remove standalone `@ui.page()` decorators** from each GUI module:
   - `dashboard.py`: Remove `@ui.page("/dashboard", ...)` from `dashboard_page()`
   - `controller.py`: Remove `@ui.page("/controller", ...)` from `controller_page()`
   - `digital_twin.py`: Remove `@ui.page("/twin/{room_id}", ...)` from `twin_page()`

   These standalone page functions are retained but guarded for standalone
   mode only (when the module is run directly via `__main__`). The unified
   app exclusively uses the `*_content()` functions via `ui.sub_pages()`.

3. **Replace hardcoded `_NAV_ITEMS` with a two-tier dynamic sidebar**:

   **Tier 1 — Static local pages** (always present):
   - Dashboard (`/dashboard`)
   - Controller (`/controller`)

   These are pages whose `*_content()` functions are compiled into this
   process and registered in `ui.sub_pages()` at startup.

   **Tier 2 — Discovered GUI services** (dynamic, from DDS):
   - The sidebar subscribes to the controller backend's
     `ServiceCatalog` data (already received via the Orchestration
     domain reader).
   - Services with a non-empty `gui_url` property appear in a
     "Services" section below the static nav, using:
     - `display_name` from `ServiceCatalog` as the label
     - `room_id` property as a suffix (e.g., "Digital Twin (OR-1)")
     - An appropriate icon from `ICONS`
   - The list rebuilds on a `ui.timer(0.5, ...)` sweep or on
     `@ui.refreshable` triggered by catalog changes.
   - Services without `gui_url` (non-GUI services) do not appear.
   - When a host loses liveliness, its services disappear from the
     sidebar.

   **Origin-aware click behavior** for discovered services:
   - Parse the `gui_url` and compare its origin to the browser's
     `window.location.origin` (obtained once at page load via
     `ui.run_javascript("window.location.origin")`).
   - **Same origin**: Extract the path from `gui_url` and call
     `ui.navigate.to(path)` — the content renders inside the SPA
     shell. If the path is not yet in `ui.sub_pages()`, register it
     dynamically via `sub_pages.add(path, content_fn)`.
   - **Different origin**: Call `ui.navigate.to(gui_url, new_tab=True)`
     — opens a new browser tab to the remote host's standalone page.
   - Render a small icon hint next to each entry indicating local
     (in-app) vs. remote (new-tab) navigation.

4. **Standalone page self-sufficiency**:
   - Each GUI module's `*_page()` function (guarded behind `__main__`)
     must render a self-contained page: header bar, theme toggle, and
     a "← Return to Controller" link.
   - The return link targets the controller's URL. In the initial
     implementation, this can be configured via an environment variable
     (`MEDTECH_CONTROLLER_URL`). A future enhancement can discover it
     from `ServiceCatalog` via a dedicated `controller_url` well-known
     property, or via the controller's own `gui_url`.

5. **Add active-nav highlighting** to the sidebar drawer:
   - Use `ui.context.client.sub_pages_router.on_path_changed()` to track
     the current path.
   - Conditionally apply an active class (e.g., `bg-white/20 font-bold`)
     to the nav button matching the current route.
   - This gives users a clear visual indicator of which page they are on.

6. **Add breadcrumb / page title** in the content area:
   - Display the current page name in the header bar (dynamic, updates
     on navigation) alongside the "Medtech Suite" title — e.g.,
     "Medtech Suite › Dashboard".
   - Alternatively, render a compact breadcrumb row below the header.

7. **Handle the root `/` redirect properly**:
   - In the `ui.sub_pages()` route map, `/` → `lambda: ui.navigate.to("/dashboard")`
     (current behavior, but now it works correctly because `ui.sub_pages()`
     owns the routing, not a separate `@ui.page`).
   - Or render a landing page at `/` with navigation cards.

### UX Improvements Delivered

| Before | After |
|--------|-------|
| Refresh at `/dashboard` loses shell — standalone page, no nav | Refresh at `/dashboard` renders full shell + sidebar + dashboard content |
| No way to navigate back except browser back button | Sidebar always visible; any page is one click away |
| No visual indicator of current page | Active nav item highlighted in sidebar |
| Page title is static "Medtech Suite" | Dynamic breadcrumb: "Medtech Suite › Dashboard" |
| URL shows `/dashboard` but shell is gone | URL still shows `/dashboard`, shell is always present |
| Sharing a link to `/controller` renders a broken standalone page | Shared link renders the full app with controller content |
| Sidebar is hardcoded — only shows 3 pre-defined pages | Static pages + dynamic discovered GUI services in sidebar |
| Digital Twin entry hardcoded to OR-1 | Dynamic: one entry per running Digital Twin instance, labeled by room |
| All "Open" buttons open new tabs | Same-origin services navigate in-app; cross-origin open new tabs |
| Remote standalone pages have no way back | Standalone pages include "← Return to Controller" link |

### Test Gate (spec: nicegui-migration.md — SPA Navigation scenarios)

- [x] Navigating to `/dashboard` renders the full SPA shell with sidebar
- [x] Refreshing the browser at `/dashboard` preserves the shell
- [x] Refreshing at `/controller` preserves the shell
- [x] Refreshing at `/twin/OR-1` preserves the shell
- [x] Clicking sidebar nav switches content without full page reload
- [x] Active nav item is visually highlighted
- [x] WebSocket connection persists across navigation (no reconnection)
- [x] All `GuiBackend` instances remain active during navigation
- [x] All existing `@gui` tests pass
- [x] Direct URL entry (e.g., pasting `/controller` in address bar) renders full shell
- [x] Discovered GUI service with same-origin `gui_url` navigates within shell
- [x] Discovered GUI service with cross-origin `gui_url` opens in new tab
- [x] Sidebar dynamically adds/removes entries as GUI services start/stop
- [x] Sidebar shows `display_name (room_id)` for each discovered service
- [x] Standalone pages render a self-contained shell with "Return to Controller"

---

## Step M.1 — Design Token System ✅ `b2a2e81`

### Work

- Create `modules/shared/medtech/gui/_tokens.py` — centralized `DESIGN_TOKENS`
  dict as defined in `vision/ui-design-system.md` § Design Token Architecture:
  - `color.brand`, `color.semantic`, `color.neutral` sub-dicts
  - `spacing`, `radius`, `shadow`, `opacity`, `transition`, `blur` sub-dicts
- Update `_colors.py` to derive `BRAND_COLORS` from `DESIGN_TOKENS["color"]`:
  - `"blue"` → `DESIGN_TOKENS["color"]["brand"]["primary"]` (`#004A8A`)
  - `"orange"` → `DESIGN_TOKENS["color"]["brand"]["accent"]` (`#E68A00`)
  - `"green"` → `DESIGN_TOKENS["color"]["semantic"]["success"]` (`#059669`)
  - `"red"` → `DESIGN_TOKENS["color"]["semantic"]["critical"]` (`#DC2626`)
  - `"amber"` → `DESIGN_TOKENS["color"]["semantic"]["warning"]` (`#D97706`)
  - `"gray"` → `#63666A` (unchanged, still maps to neutral tone)
  - `"light_blue"` → `#00B5E2` (unchanged)
  - `"light_gray"` → `#BBBCBC` (unchanged)
  - `"dark_gray"` → `DESIGN_TOKENS["color"]["neutral"]["800"]` (`#1E293B`)
- Update `OPACITY` dict to align with token values (glass_bg: 0.65, shadow: 0.12)
- Update `THEME_PALETTE` to include new tokens (`surface`, `hud-border`, `glass-blur`)
  and adjust `hud-bg` opacity from 0.85 to 0.65
- Update `STATUS_COLORS` and `STATUS_COLORS_DARK` with new semantic hex values
- Export `DESIGN_TOKENS` from `medtech.gui.__init__`
- Verify all existing color references still resolve correctly (backward compat)

### Test Gate

- [x] `DESIGN_TOKENS` importable and contains all required keys
- [x] `BRAND_COLORS` values match updated token palette
- [x] All existing `@gui` tests pass (no visual regression in test assertions)
- [x] `app.colors()` in `init_theme()` uses updated brand primary/accent values
- [x] Lint passes (`ruff check`, `markdownlint`)

---

## Step M.2 — Inter Font Integration

### Work

- Download Inter variable font (`.woff2` and `.ttf`) from Google Fonts
  (SIL Open Font License 1.1) and add to `resources/fonts/`
- Update `resources/fonts/CMakeLists.txt` install rule to include Inter files
- Update `THIRD_PARTY_NOTICES.md` to add Inter font license attribution
- Update `_theme.py` `_font_css()`:
  - Add `@font-face` declarations for Inter (weight range 400–700 variable)
  - Change `body` CSS rule from `'Roboto Condensed'` to `'Inter'`
  - Change `.brand-heading` CSS rule from `'Roboto Condensed'` to `'Inter'`
  - Retain `Roboto Mono` for `.mono` class (data values)
- Add semantic type scale CSS classes via `ui.add_head_html()`:
  ```css
  .type-h1 { font-size: 32px; font-weight: 700; line-height: 1.2; }
  .type-h2 { font-size: 24px; font-weight: 700; line-height: 1.3; }
  .type-h3 { font-size: 18px; font-weight: 600; line-height: 1.4; }
  .type-body-lg { font-size: 16px; font-weight: 500; line-height: 1.5; }
  .type-body { font-size: 14px; font-weight: 400; line-height: 1.6; }
  .type-body-sm { font-size: 12px; font-weight: 400; line-height: 1.5; }
  .type-label { font-size: 12px; font-weight: 600; line-height: 1.4; }
  .type-mono { font-family: 'Roboto Mono', monospace; font-size: 13px; font-weight: 700; }
  .type-mono-sm { font-family: 'Roboto Mono', monospace; font-size: 11px; font-weight: 400; }
  ```
- Roboto Condensed `.ttf` files may be retained for backward compatibility
  but are no longer referenced in CSS

### Test Gate (spec: nicegui-migration.md — font scenario; hospital-dashboard.md — Inter font)

- [ ] Inter font loads from local static files (no CDN requests)
- [ ] Page headings render in Inter Bold (700)
- [ ] Data values render in Roboto Mono Bold
- [ ] All existing `@gui` tests pass
- [ ] Docker image builds and serves fonts correctly

---

## Step M.3 — Glassmorphism Overlays

### Work

- Add global glassmorphism CSS classes via `init_theme()`:
  ```css
  .glass-panel {
    background: var(--glass-bg);
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
    border: 1px solid var(--glass-border);
    border-radius: 16px;
    box-shadow: var(--shadow-lg);
  }
  ```
  with CSS custom properties set per theme mode (dark: `rgba(13,27,42,0.65)`,
  blur 12 px; light: `rgba(255,255,255,0.65)`, blur 10 px)
- Update `create_header()` in `_theme.py`:
  - Apply glassmorphism to header bar (translucent primary + blur)
  - or keep solid header and apply glass to floating elements only (design choice)
- Update floating overlay patterns in all GUI modules:
  - Dashboard: alert detail popover, filter dropdowns → `.glass-panel`
  - Procedure Controller: `ui.dialog()` content → `.glass-panel`
  - Digital Twin: HUD overlay panels → `.glass-panel`
- Update `_widgets.py` helper functions to accept optional `glass=True` kwarg
  for panels that should use glassmorphism styling

### Test Gate (spec: hospital-dashboard.md — glassmorphism scenario; surgical-procedure.md — twin HUD scenario)

- [ ] Floating overlays render with visible backdrop blur
- [ ] Glass panels have 16 px radius and translucent border
- [ ] Content behind overlays is visibly blurred
- [ ] All existing `@gui` tests pass
- [ ] Glass effect degrades gracefully in browsers without `backdrop-filter` support

---

## Step M.4 — Modern Status Indicators

### Work

- Update `create_status_chip()` in `_widgets.py`:
  - Add `ui.icon()` prefix per status (checkmark for OPERATIONAL, stop-circle
    for E-STOP, pause for PAUSED, remove for IDLE, wifi-off for DISCONNECTED)
  - Change chip border radius to 12 px (from default)
  - Use 10% opacity tinted background with full-opacity text (dark and light variants)
- Add `create_skeleton_card()` to `_widgets.py`:
  - Returns a `ui.card()` with shimmer animation CSS (neutral-300 → neutral-100,
    1.5 s cycle)
  - Accepts `height` parameter for sizing
- Add pulse-critical CSS animation to `init_theme()`:
  ```css
  @keyframes pulse-critical {
    0%, 100% { box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.6); }
    50% { box-shadow: 0 0 0 10px rgba(220, 38, 38, 0); }
  }
  .pulse-critical { animation: pulse-critical 1s infinite; }
  ```
- Update dashboard alert feed: CRITICAL alerts get `.pulse-critical` class
- Update digital twin mode badge: E-STOP gets `.pulse-critical` class
- Apply skeleton loaders in dashboard during initial DDS discovery window:
  - Show skeleton cards in place of procedure list, vitals, resources
  - Replace with real content when first DDS sample arrives per topic

### Test Gate (spec: hospital-dashboard.md — status chip icon, skeleton, pulse scenarios)

- [ ] Status chips include both icon and color-coded background
- [ ] Skeleton loaders appear before data arrives
- [ ] Skeletons replaced by real data on first DDS sample
- [ ] CRITICAL alerts pulse with red ring animation
- [ ] E-STOP badge pulses with red ring animation
- [ ] All existing `@gui` tests pass

---

## Step M.5 — Animation & Transitions

### Work

- Add global transition CSS to `init_theme()`:
  ```css
  .transition-fast { transition: all 150ms ease-out; }
  .transition-default { transition: all 200ms cubic-bezier(0.34, 1.56, 0.64, 1); }
  .transition-slow { transition: all 300ms ease-out; }
  ```
- Add `prefers-reduced-motion` global override (per vision doc)
- Add `focus-visible` ring CSS (per vision doc § Accessibility):
  ```css
  :focus-visible {
    outline: 2px solid #0284C7;
    outline-offset: 2px;
    border-radius: inherit;
  }
  ```
- Update card hover in dashboard and controller:
  - Add `.hover-elevate` class: `transform: scale(1.02)` + shadow-lg on hover
  - Apply to procedure cards, host tiles, service tiles
- Add slide-in animation for new alert cards:
  ```css
  @keyframes slide-in-top {
    from { opacity: 0; transform: translateY(-12px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .animate-slide-in { animation: slide-in-top 300ms ease-out; }
  ```
- Apply `.animate-slide-in` to newly appended alert cards in dashboard feed
- Update `ConnectionDot` in `_widgets.py` to use CSS animation instead of
  timer-driven inline styles (smoother, respects reduced-motion)

### Test Gate (spec: hospital-dashboard.md — hover, animation, focus, reduced-motion scenarios)

- [ ] Cards scale on hover with smooth transition
- [ ] New CRITICAL alerts slide in with fade animation
- [ ] Focus-visible rings appear on keyboard Tab navigation
- [ ] All animations suppressed when `prefers-reduced-motion: reduce` is set
- [ ] Connection dot animates smoothly via CSS
- [ ] All existing `@gui` tests pass

---

## Step M.6 — Apply Semantic Type Scale Across All Pages

### Work

- Audit all `ui.label().classes(...)` calls in dashboard, controller, and
  digital twin modules. Replace ad-hoc Tailwind size classes with semantic
  type scale classes:
  - Page titles → `.type-h1`
  - Section headers → `.type-h2`
  - Card titles → `.type-h3`
  - Body content → `.type-body` or `.type-body-lg`
  - Secondary labels / timestamps → `.type-body-sm`
  - Form labels / chip text → `.type-label`
  - Numeric data values → `.type-mono`
  - Small HUD values → `.type-mono-sm`
- Update `create_section_header()` to use `.type-h2`
- Update `create_stat_card()` value label to use `.type-h1` and description
  to use `.type-body-sm`
- Ensure consistency across all three GUI modules

### Test Gate (spec: hospital-dashboard.md — semantic type scale; surgical-procedure.md — Inter font)

- [ ] All text elements use semantic type scale classes
- [ ] No arbitrary Tailwind font-size classes remain in GUI modules
- [ ] Visual hierarchy is consistent across dashboard, controller, and twin
- [ ] All existing `@gui` tests pass

---

## Step M.7 — Documentation & Regression

### Work

- Update `vision/technology.md` § GUI Design Standard:
  - Replace color palette table with updated values
  - Replace typography table with Inter + Roboto Mono
  - Add design token system reference
- Run full quality gate: `bash scripts/ci.sh`
- Run all `@gui` + `@ui-modernization` tests
- Visual smoke test: launch unified app, verify all three pages render
  correctly with modernized design in both light and dark themes
- Verify Docker image builds and serves correctly with new fonts/assets
- Commit: `Phase UI-M — UI Design Modernization`

### Test Gate

- [ ] Full `bash scripts/ci.sh` passes
- [ ] All `@gui` tests pass (no regressions)
- [ ] All `@ui-modernization` tests pass
- [ ] Docker image builds with Inter font and updated assets
- [ ] markdownlint passes on all updated docs
- [ ] No open incidents related to UI modernization

---

## Summary

| Step | Deliverable | Key Changes |
|------|-------------|-------------|
| M.0 | Fix SPA Navigation | Remove standalone `@ui.page()`, use `ui.run(shell_page)`, dynamic sidebar from ServiceCatalog, origin-aware navigation, active-nav highlight, breadcrumb, standalone return link |
| M.1 | Design Token System | `_tokens.py`, updated `_colors.py`, aligned `BRAND_COLORS` |
| M.2 | Inter Font | Font assets, `_theme.py` CSS, semantic type scale classes |
| M.3 | Glassmorphism | `.glass-panel` CSS, updated overlays in all GUI modules |
| M.4 | Modern Status Indicators | Icon chips, skeleton loaders, pulse-critical animation |
| M.5 | Animation & Transitions | Hover elevate, slide-in, focus rings, reduced-motion |
| M.6 | Semantic Type Scale | Replace ad-hoc sizes with type scale classes everywhere |
| M.7 | Documentation & Regression | Tech doc updates, full gate pass, Docker validation |
