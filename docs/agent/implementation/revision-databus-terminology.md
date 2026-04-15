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
4. Implemented XML files (`Domains.xml`, `RoutingService.xml`, etc.)

Everywhere else — vision prose, spec narrative, implementation
descriptions, code comments, commit messages — use the **semantic
databus name** (e.g., "Procedure control databus", "Hospital
Integration databus").

---

## Prerequisites

- Revision: Domain ID Migration is complete (all domain IDs are at
  their final values).
- All existing tests pass before starting any step.

---

## Step T.1 — Glossary & Conventions in Vision Documents

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

## Step T.2 — Domain Library Restructure (XML)

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

**e) Update `RoutingService.xml`** domain-related comments (the RS uses
inline `<domain_id>` elements, not `domain_ref`, so the library split
does not affect its runtime behavior — only comments need updating).

### Test Gate

- [ ] `cmake --build build` succeeds (XML parsed at configure time)
- [ ] `tests/tools/test_xml_validator.py` passes (schema validation for
      all three new files)
- [ ] `tests/lint/` passes
- [ ] All existing tests pass (`bash scripts/ci.sh`)
- [ ] Grep gate: no `MedtechDomains` string remains in any file under
      `interfaces/` or `services/`
- [ ] Grep gate: no `domain_ref` references the old library name

---

## Step T.3 — Documentation Rename

### Work

Bulk rename across all Markdown files under `docs/agent/`:

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

**Exclusions — do NOT rename:**

- DDS API terms: `DomainParticipant`, `domain_id`, `domain_ref`,
  `<domain>`, `domain_tag`, `<domain_library>`, `domain_participant_qos`
- `Domains.xml` filename references (these become historical after T.2;
  update to new filenames instead)
- Headings in `data-model.md` § Domain Definitions (these are the
  canonical ID locations)
- The `MedtechDomains` string in `revision-domain-id-migration.md`
  (historical record of completed revision)

**Scope:** All files under `docs/agent/` (~34 files, ~446 occurrences
of architectural "X domain" patterns, ~150 occurrences of numeric
"Domain NN" references).

### Test Gate

- [ ] `tests/lint/` passes (markdownlint)
- [ ] Grep gate: `grep -rn "Procedure domain\b" docs/agent/` returns
      zero hits (excluding data-model.md headings and DDS API contexts)
- [ ] Grep gate: `grep -rn "Hospital domain\b" docs/agent/` returns
      zero hits (same exclusions)
- [ ] Grep gate: `grep -rn "Domain 10\|Domain 11\|Domain 19\|Domain 20\|Domain 29" docs/agent/`
      returns hits only in the 4 canonical locations

---

## Step T.4 — Verification & Cleanup

### Work

- Run the full test suite (`bash scripts/ci.sh`) end-to-end.
- Run the grep gates from Steps T.2 and T.3 as a final check.
- Update `docs/agent/implementation/README.md` if any phase files
  reference old `MedtechDomains::` names (only
  `revision-domain-id-migration.md` should, as historical record).
- Verify that `incidents.md` references to `MedtechDomains` are updated
  (there is at least one at line ~2685).

### Test Gate

- [ ] Full CI pass: `bash scripts/ci.sh`
- [ ] All grep gates from T.2 and T.3 pass
- [ ] No file under `interfaces/` contains the string `MedtechDomains`
- [ ] No file under `docs/agent/` contains "X domain" (for any databus
      name X) outside explicitly excluded contexts
