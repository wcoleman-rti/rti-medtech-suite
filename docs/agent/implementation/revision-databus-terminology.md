# Revision: Databus Terminology Alignment

**Goal:** Adopt RTI's "databus" terminology throughout the project
documentation and restructure the XML domain library from a single
monolithic `MedtechDomains` library into per-level libraries (`Room`,
`Hospital`, `Cloud`) whose `domain_ref` names follow a
`Level::Function` convention. Eliminate scattered numeric domain ID
references from documentation, restricting them to 4 canonical
locations.

**Depends on:** Revision: Domain ID Migration (domain IDs must be
stable before renaming the libraries that contain them)
**Blocks:** Nothing — terminology and organizational improvement
**Version impact:** Patch (`V1.5.x`) — no new capabilities, no IDL
changes, no QoS changes, no behavioral changes. All spec scenarios
continue to pass with updated symbolic names.

**Guiding principle:** "Databus" is a *semantic / documentation* term
aligned with RTI's published guidance. DDS XML element names (`<domain>`,
`<domain_participant>`, `domain_ref`, `domain_id`) remain unchanged —
those are DDS API terms, not architectural labels.

**Spec coverage:** No spec scenarios reference domain libraries by name
or use numeric IDs (per the Domain Naming Rule in
[data-model.md](../vision/data-model.md)). This revision therefore has
no spec-level changes.

**Vision references:**
- [data-model.md](../vision/data-model.md) — Domain Definitions,
  Domain Naming Rule
- [system-architecture.md](../vision/system-architecture.md) — Domain
  Numbering Guide, Deployment Levels

---

## Terminology Definitions

These definitions are authoritative for the entire project and will be
added to the vision documents as part of Step T.1.

| Term | Definition | Example |
|------|-----------|---------|
| **Databus** | A logical data space identified by a `(domain_id, domain_tag)` pair. All DomainParticipants that share both values are on the same databus. Per RTI guidance: "A databus provides a virtual data space where applications can share data." | Procedure control databus = Domain 10 + tag `control` |
| **DDS domain** | The native Connext isolation boundary identified solely by `domain_id`. In this project every DDS domain contains one or more databuses distinguished by domain tags. | Domain 10 (Procedure) |
| **Visibility plane** | A partition within a databus. Partitions restrict which writers and readers can match within the same databus. They do **not** constitute separate databuses. | `procedure` partition within the Orchestration databus |
| **Domain library** | An XML `<domain_library>` element grouping related `<domain>` definitions by deployment level. | `Room` library containing Procedure, Orchestration, and Room Observability domains |

### Named Databuses

| Databus | Domain ID | Domain Tag | Library |
|---------|-----------|------------|---------|
| Procedure control | 10 | `control` | `Room` |
| Procedure clinical | 10 | `clinical` | `Room` |
| Procedure operational | 10 | `operational` | `Room` |
| Orchestration | 11 | *(none)* | `Room` |
| Room Observability | 19 | *(none)* | `Room` |
| Hospital Integration | 20 | *(none)* | `Hospital` |
| Hospital Observability | 29 | *(none)* | `Hospital` |
| Cloud / Enterprise (V3.0) | 30 | *(none)* | `Cloud` |

### No-Numeric-ID Rule

Numeric domain IDs (e.g., "Domain 10", "domain 20") may appear in
exactly **4 canonical locations**:

1. `vision/data-model.md` § Domain Definitions (headings + tables)
2. `spec/` scenario tables where a domain ID is the *subject under test*
3. `implementation/` phase files where the work item explicitly changes
   a `domain_id` attribute
4. Implemented XML files (`RoomDatabuses.xml`, `HospitalDatabuses.xml`,
   `CloudDatabuses.xml`, `RoutingService.xml`,
   `CloudDiscoveryService.xml`, etc.)
5. Test fixtures that programmatically create DomainParticipants
   (e.g., `PROCEDURE_DOMAIN_ID = 10` constants in integration tests)
6. Application / tool code that must pass a numeric `domain_id` to the
   DDS API (e.g., `partition-inspector.py`)

Everywhere else — vision prose, spec narrative, implementation
descriptions, code comments, commit messages — use the **semantic
databus name** (e.g., "Procedure control databus", "Hospital
Integration databus").

### Historical-Record Policy

`incidents.md` and completed revision phase files (e.g.,
`revision-domain-id-migration.md`) are **append-only historical
records**. Old terminology in these files is not updated. Instead,
add a one-line annotation at the top of affected sections:

> **Terminology note:** This entry uses pre-V1.4.x terminology.
> "Procedure domain" → "Procedure control/clinical/operational
> databus"; "Hospital domain" → "Hospital Integration databus";
> `MedtechDomains` → `Room`/`Hospital`/`Cloud` libraries.

---

## Prerequisites

- Revision: Domain ID Migration is complete (all domain IDs are at
  their final values).
- All existing tests pass before starting any step.

---

## Step T.1 — Glossary & Conventions in Vision Documents ✅ `ae87cd0`

### Work

**a) Add terminology section to `vision/system-architecture.md`:**

Insert a new subsection "Databus Terminology" (after the Domain
Numbering Guide) containing:

- The Terminology Definitions table above
- The Named Databuses table above
- The No-Numeric-ID Rule above
- A note: "DDS XML element names (`<domain>`, `domain_ref`,
  `domain_id`, `<domain_participant>`) remain as-is — these are DDS API
  terms. 'Databus' is used in documentation, comments, and
  architectural discussion."

**b) Update `vision/data-model.md` § Domain Definitions:**

- Add a preamble paragraph after the existing decade-offset reference:
  > In this project, a **databus** is a logical data space identified by
  > a `(domain_id, domain_tag)` pair. Each heading below defines one
  > DDS domain; where domain tags subdivide a DDS domain, each tag
  > creates a distinct databus.
- Update the Domain Naming Rule to reference "databus name" instead of
  "domain name" and add "databus" to the list of acceptable reference
  forms (e.g., "Procedure control databus" alongside "Procedure control
  domain").
- Update each domain heading's prose to use "databus" where it refers
  to the logical data space (not the DDS element).

**c) Update `workflow.md` forbidden-actions table:**

- Row "Embed domain IDs as literals…": revise the guidance column to
  reference the No-Numeric-ID Rule and the 4 canonical locations (replacing
  the current reference to "domain name" with "semantic databus name").

### Test Gate

- [ ] `tests/lint/` passes (markdownlint on all modified docs)
- [ ] No numeric domain ID appears in modified vision doc prose outside
      the Domain Definitions headings and tables (manual grep gate)

---

## Step T.2 — Domain Library Restructure (XML) ✅ `ae87cd0`

### Work

**a) Split `interfaces/domains/Domains.xml`:**

Replace the single `MedtechDomains` `<domain_library>` with three XML
files, each containing one `<domain_library>`:

| File | Library Name | `<domain>` Elements |
|------|-------------|---------------------|
| `interfaces/domains/RoomDatabuses.xml` | `Room` | `Procedure_control`, `Procedure_clinical`, `Procedure_operational`, `Orchestration`, `Observability` |
| `interfaces/domains/HospitalDatabuses.xml` | `Hospital` | `Integration`, `Observability` |
| `interfaces/domains/CloudDatabuses.xml` | `Cloud` | `Enterprise` (placeholder, V3.0) |

Domain renames within the elements:

| Old `<domain name>` | New `<domain name>` | Rationale |
|---------------------|---------------------|-----------|
| `Procedure_control` | `Procedure_control` | No change |
| `Procedure_clinical` | `Procedure_clinical` | No change |
| `Procedure_operational` | `Procedure_operational` | No change |
| `Orchestration` | `Orchestration` | No change |
| `Hospital` | `Integration` | Disambiguates from library name |
| `RoomObservability` | `Observability` | Disambiguated by library (`Room::Observability`) |
| `HospitalObservability` | `Observability` | Disambiguated by library (`Hospital::Observability`) |

**b) Delete `interfaces/domains/Domains.xml`** after the split is
verified.

**c) Update all `domain_ref` attributes in participant XML files:**

| File | Old `domain_ref` | New `domain_ref` |
|------|------------------|------------------|
| `SurgicalParticipants.xml` | `MedtechDomains::Procedure_control` | `Room::Procedure_control` |
| `SurgicalParticipants.xml` | `MedtechDomains::Procedure_clinical` | `Room::Procedure_clinical` |
| `SurgicalParticipants.xml` | `MedtechDomains::Procedure_operational` | `Room::Procedure_operational` |
| `SurgicalParticipants.xml` | `MedtechDomains::Orchestration` | `Room::Orchestration` |
| `OrchestrationParticipants.xml` | `MedtechDomains::Orchestration` | `Room::Orchestration` |
| `OrchestrationParticipants.xml` | `MedtechDomains::Hospital` | `Hospital::Integration` |

**d) Update `setup.bash` (and `setup.bash.in`):**

Ensure `NDDS_QOS_PROFILES` loads all three new XML files in place of
the old single `Domains.xml`. The load order does not matter for domain
libraries.

**e) Update XML comments across all interface and service files:**

Not just `RoutingService.xml` — every XML file that contains "X domain
(Domain NN)" comment patterns must be updated to use semantic databus
names. Affected files:

- `services/routing/RoutingService.xml` — header block, participant
  comments, session comments (RS uses inline `<domain_id>` elements,
  not `domain_ref`, so only comments change)
- `interfaces/qos/Topics.xml` — `ProcedureTopics`, `HospitalTopics`,
  `OrchestrationTopics`, `GuiProcedureTopics`, `GuiHospitalTopics`
  section comments (~8 occurrences)
- `interfaces/participants/SurgicalParticipants.xml` — participant
  block comments
- `interfaces/participants/OrchestrationParticipants.xml` — header,
  participant block comments, inline entity comments

**f) Update build system `Domains.xml` references:**

| File | Change |
|------|--------|
| `CMakeLists.txt` (line ~84) | Replace single `Domains.xml` install entry with the three new filenames |
| `tests/qos/CMakeLists.txt` (line ~19) | Update `NDDS_QOS_PROFILES` env to list all three files instead of `Domains.xml` |

**g) Update Docker & deployment `Domains.xml` references:**

| File | Change |
|------|--------|
| `docker-compose.yml` (line ~13) | Update `NDDS_QOS_PROFILES` env value |
| `docker/medtech-app.Dockerfile` (lines ~34, ~46) | Update `NDDS_QOS_PROFILES` ENV in both build stages |
| `setup.bash.in` (line ~33) | Replace single `Domains.xml` path with three new file paths |

**h) Update tools & CLI code that locate `Domains.xml` by filename:**

| File | Change |
|------|--------|
| `tools/qos-checker.py` | Update `_find_domains_xml()` to locate any of the three new files (or all domain library XMLs); update docstring and error message |
| `tests/tools/test_qos_checker.py` | Update assertion that checks for `Domains.xml` filename |
| `modules/shared/medtech/cli/_hospital.py` | Update hardcoded `Domains.xml` path in `NDDS_QOS_PROFILES` construction |

### Test Gate

- [ ] `cmake --build build` succeeds (XML parsed at configure time)
- [ ] `tests/tools/test_xml_validator.py` passes (schema validation for
      all three new files)
- [ ] `tests/lint/` passes
- [ ] All existing tests pass (`bash scripts/ci.sh`)
- [ ] Grep gate: no `MedtechDomains` string remains in any file under
      `interfaces/` or `services/`
- [ ] Grep gate: no `domain_ref` references the old library name
- [ ] Grep gate: no file outside `docs/agent/` and `.git/` contains the
      string `Domains.xml` (filename fully retired)

---

## Step T.3a — Documentation Rename ✅ `0359019`

### Work

Bulk rename across all Markdown files under `docs/agent/` **and**
project-root documentation (`README.md`,
`modules/surgical-procedure/README.md`, etc.):

| Old Pattern | New Pattern |
|-------------|-------------|
| "Procedure domain" (when referring to the whole DDS domain) | "Procedure DDS domain" or "Domain 10 databuses" (context-dependent; only in Domain Definitions) |
| "Procedure control domain" / "control tag" as data space | "Procedure control databus" |
| "Procedure clinical domain" / "clinical tag" as data space | "Procedure clinical databus" |
| "Procedure operational domain" / "operational tag" as data space | "Procedure operational databus" |
| "Orchestration domain" | "Orchestration databus" |
| "Hospital domain" | "Hospital Integration databus" |
| "Room Observability domain" | "Room Observability databus" |
| "Hospital Observability domain" | "Hospital Observability databus" |
| "Cloud domain" / "Enterprise domain" | "Cloud Enterprise databus" |
| "Domain 10" / "Domain 11" / "Domain 20" etc. in prose | Semantic databus name (per No-Numeric-ID Rule) |

In addition, update **`Domains.xml` filename references** in vision and
spec documents to reflect the new filenames:

| File | Change |
|------|--------|
| `vision/technology.md` (directory tree, `setup.bash` snippet, Dockerfile ENV) | `Domains.xml` → list of 3 new filenames |
| `vision/data-model.md` (NDDS_QOS_PROFILES example, Domain Naming Rule) | `Domains.xml` → new filenames; update rule to say "domain library XML files" |
| `vision/dds-consistency.md` (NDDS_QOS_PROFILES example, AP-4 antipattern) | `Domains.xml` → new filenames; AP-4 guidance: "Domain IDs live exclusively in the domain library XML files and data-model.md. Code references databuses by semantic name." |
| `modules/surgical-procedure/README.md` (install tree table) | `share/domains/Domains.xml` → list of 3 new files |

**Exclusions — do NOT rename:**

- DDS API terms: `DomainParticipant`, `domain_id`, `domain_ref`,
  `<domain>`, `domain_tag`, `<domain_library>`, `domain_participant_qos`
- Historical records: `incidents.md` entries and
  `revision-domain-id-migration.md` are frozen per the Historical-Record
  Policy. Add terminology annotations instead of rewriting.
- Headings in `data-model.md` § Domain Definitions (canonical ID
  locations)

**Scope:** All Markdown files under `docs/agent/` (~34 files, ~446
occurrences of architectural "X domain" patterns, ~150 occurrences of
numeric "Domain NN" references), plus project-root and module READMEs.

### Test Gate

- [ ] `tests/lint/` passes (markdownlint)
- [ ] Grep gate: `grep -rn "Procedure domain\b" docs/agent/` returns
      zero hits (excluding data-model.md headings and DDS API contexts)
- [ ] Grep gate: `grep -rn "Hospital domain\b" docs/agent/` returns
      zero hits (same exclusions)
- [ ] Grep gate: `grep -rn "Domain 10\|Domain 11\|Domain 19\|Domain 20\|Domain 29" docs/agent/`
      returns hits only in the canonical locations

---

## Step T.3b — Code & XML Comment Rename ✅ `45aa175`

### Work

Apply the same terminology rename patterns from T.3a to **non-Markdown
files** — specifically Python comments/docstrings and XML comments.

**Python files** (`modules/`, `tools/`, `scripts/`, `tests/`):

| File | Example hit | Change |
|------|------------|--------|
| `modules/surgical-procedure/digital_twin/digital_twin.py` | `"Subscribes to the Procedure domain (control tag)"` | → `"Subscribes to the Procedure control databus"` |
| `modules/surgical-procedure/camera_sim/camera_simulator.py` | `"Publishes CameraFrame on the Procedure domain (operational tag)"` | → `"…on the Procedure operational databus"` |
| `modules/surgical-procedure/vitals_sim/bedside_monitor.py` | `"Publishes on the Procedure domain (clinical tag)"` | → `"…on the Procedure clinical databus"` |
| `modules/surgical-procedure/procedure_context_service.py` | `"Publishes … on the Procedure domain"` | → `"…on the Procedure operational databus"` |
| `scripts/simulate_room.py` | `"Domain 10 → 20 bridge"` | → `"Procedure → Hospital Integration bridge"` |
| `tools/qos-checker.py` | `"Within Procedure domain"`, `"Within Hospital domain"` | → databus names |
| `tools/partition-inspector.py` | `"Scan active DDS partitions on the Procedure domain"` | → `"…on the Procedure DDS domain"` |
| `tools/medtech-diag/diag.py` | `"On the observability domain"` | → `"On the Room Observability databus"` |
| `tests/integration/test_routing_service.py` | `"Hospital domain"`, `"domain 10"` | → databus names |
| `tests/integration/test_observability.py` | `"Room Observability domain 19"`, `"domain 19"` | → `"Room Observability databus"` |
| `tests/integration/test_robot_service_host.py` | `"domain 11"`, `"domain 10"` | → databus names |
| `tests/tools/test_qos_checker.py` | `"Observability domain"` | → `"Observability databus"` |

**Exclusions — do NOT rename in code:**

- Domain ID constants used as DDS API arguments
  (e.g., `PROCEDURE_DOMAIN_ID = 10`) — these are canonical location 5
- DDS API identifiers (`domain_id`, `DomainParticipant`, etc.)
- String literals that are part of runtime behavior (error messages
  containing `"Domains.xml"` are updated in T.2h, not here)
- Test assertion strings that verify numeric domain IDs in XML output
  — these test DDS configuration correctness

### Test Gate

- [ ] All existing tests pass (`bash scripts/ci.sh`)
- [ ] Grep gate: `grep -rn "Procedure domain" --include='*.py'` returns
      zero hits outside DDS API contexts
- [ ] Grep gate: `grep -rn "Hospital domain" --include='*.py'` returns
      zero hits outside DDS API contexts
- [ ] Grep gate: `grep -rn '"Domain 10\|Domain 11\|Domain 19\|Domain 20' --include='*.py'`
      returns zero hits outside test fixture constants and DDS API calls
- [ ] Grep gate: `grep -rn "Procedure domain\|Hospital domain\|Orchestration domain" --include='*.xml'`
      returns zero hits in XML comments (excluding historical/disabled blocks)

---

## Step T.4 — Verification & Cleanup ✅ `dc6e38f`

### Work

- Run the full test suite (`bash scripts/ci.sh`) end-to-end.
- Run **all** grep gates from Steps T.2, T.3a, and T.3b as a final check.
- Add Historical-Record Policy annotations to:
  - `incidents.md` — add a terminology note before any section that
    references `MedtechDomains` or old "X domain" terminology
    (at minimum, the entry near line ~2685)
  - `revision-domain-id-migration.md` — add a single annotation at the
    top of the file noting that it uses pre-V1.4.x terminology
- Verify `docs/agent/implementation/README.md` — only
  `revision-domain-id-migration.md` should reference `MedtechDomains`
  (as historical record).
- Verify `dds-consistency.md` AP-4 row references updated filenames and
  "semantic databus name" (not "Procedure domain").

### Test Gate

- [ ] Full CI pass: `bash scripts/ci.sh`
- [ ] All grep gates from T.2, T.3a, and T.3b pass
- [ ] No file under `interfaces/` contains the string `MedtechDomains`
- [ ] No file under `docs/agent/` contains "X domain" (for any databus
      name X) outside explicitly excluded contexts and historical records
- [ ] `grep -rn 'Domains\.xml' --include='*.py' --include='*.xml' --include='*.yml' --include='*.cmake' --include='Dockerfile' --include='*.sh' --include='*.in'`
      returns zero hits outside `.git/`
- [ ] `grep -rn 'MedtechDomains' .` returns hits only in `.git/`,
      `incidents.md`, and `revision-domain-id-migration.md`
