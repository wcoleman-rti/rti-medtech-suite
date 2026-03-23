# Documentation Standard

Every module and service in the medtech suite must be documented with a `README.md` that
follows the structure and rules defined here. Consistency allows any developer or agent to
engage with any module using the same mental model without needing to infer local conventions.

---

## Scope

This standard applies to every `README.md` under:

- `modules/<module-name>/README.md`
- `services/<service-name>/README.md`

It does not apply to planning documents under `docs/agent/`, which follow their own
conventions.

---

## Markdownlint Compliance

All README files must pass `markdownlint` with zero errors and zero warnings.

Rules:

1. A `.markdownlint.json` configuration file must exist at the project root and define the
   active ruleset. All rules are enabled by default unless explicitly and collectively
   agreed and recorded in that file.
2. **Suppression is never permitted.** No file may contain `<!-- markdownlint-disable -->`,
   `<!-- markdownlint-disable-next-line -->`, or any equivalent inline suppression comment.
   If a markdownlint rule produces a false positive for a legitimate construct, the
   `.markdownlint.json` configuration must be updated project-wide (with operator approval)
   rather than suppressed locally.
3. README files must not contain trailing spaces, hard tabs, bare URLs, or inline HTML.
4. Line length must not exceed 100 characters. Wrap prose at 100 characters. Code blocks,
   tables, and headings are exempt from the line length rule
   (`MD013: line_length: code_blocks: false, tables: false, headings: false`).
5. Every fenced code block must declare a language identifier.
6. There must be exactly one top-level heading (`#`) per file, and it must be the first line.

---

## Required Section Structure

Every README must contain the following sections in this order. No sections may be omitted.
Additional sections may be added after **Going Further** if genuinely needed, but the six
required sections must always appear first and in order.

### 1. Title (`#`)

The file title. Must be the exact module or service name as it appears in `CMakeLists.txt`
and `docker-compose.yml`. First line of the file.

### 2. Overview (`## Overview`)

- One or two paragraphs describing what the module does and why it exists
- Which functional domain(s) it participates in (Procedure, Hospital) and under which
  domain tag(s)
- Which RTI Connext products and features it uses (list as a bullet table):

  | Connext Feature | How It Is Used |
  |-----------------|----------------|
  | DDS topics      | ...            |
  | QoS profiles    | ...            |

### 3. Quick Start (`## Quick Start`)

A developer must be able to build and run the module in a single sequential pass through
this section with no external knowledge required. Required subsections:

- **Prerequisites** — what must already be in place (built foundation, Docker running, venv
  activated, etc.)
- **Build** — the exact CMake commands
- **Configure** — required environment variables and XML configuration files, with example
  values
- **Run** — the exact command(s) to start the module, including any Docker Compose
  invocation

All commands must be in fenced code blocks with the appropriate language identifier
(`bash`, `cmake`, `xml`, etc.).

### 4. Architecture (`## Architecture`)

A deeper explanation of how the module works internally. Required content:

- An ASCII diagram or a clear prose description of the module's component structure and
  data flow
- A **DDS Entities** subsection listing every `DomainParticipant`, `DataWriter`, and
  `DataReader` the module creates, the topic and QoS profile each uses, and its domain tag
- An explanation of the threading model: which thread creates DDS entities, which thread
  performs DDS I/O (must not be the main thread per `vision/technology.md`)

### 5. Configuration Reference (`## Configuration Reference`)

A complete reference for every runtime parameter the module accepts. Organized as:

- **Environment Variables** — name, type, default, description (table format)
- **XML Configuration Files** — which QoS, participant, domain library, and transport
  files are loaded, and how they are located at runtime
- **Domain Partition** — how the partition value is provided and what format it must follow

### 6. Testing (`## Testing`)

- The exact command(s) to run this module's tests
- A summary table of test coverage by scenario tag (`@unit`, `@integration`, etc.)
- How to run a specific subset of tests (e.g., `pytest -m "integration and not e2e"`)
- Any required environment setup for tests (e.g., a running DDS participant, Docker network)

### 7. Going Further (`## Going Further`)

Links to related documents the reader should consult next. Must include at minimum:

- The relevant `spec/` file for this module
- `vision/data-model.md` (topics and QoS profiles this module uses)
- `vision/system-architecture.md` (how this module fits in the layered databus)
- The relevant `implementation/` phase file
- Any sibling modules this module interacts with directly

---

## Enforcement

README compliance is verified as part of the CI pipeline. The pipeline step must:

1. Run `markdownlint` against all `modules/*/README.md` and `services/*/README.md` files
2. Verify the required section headings are present in the correct order using a lint script
   under `tests/lint/`
3. Fail the build if any README does not comply

No README may be merged without passing these checks.

---

## Documentation Handoff — From Planning to Implementation

The `docs/agent/` directory is a planning framework authored before implementation
begins. As the project is implemented, the knowledge in `docs/agent/` must transfer
into the living codebase so that future development does not depend on the planning
documents.

### Progressive Transfer Model

The goal is that once all `docs/agent/` content has been implemented, a developer can
understand, build, run, and modify any module by reading only:

- The module's own `README.md`
- The code and inline comments
- The project-root `docs/architecture/` directory (for system-level cross-cutting concerns)

The `docs/agent/` directory becomes a historical artifact — available for reference
but not required for ongoing work.

### What Transfers Where

| Planning Content | Transfer Target | When |
|-----------------|-----------------|------|
| Module architecture, DDS entities, threading model | Module `README.md` — Architecture section | During the module's implementation phase |
| Configuration reference (env vars, XML files, partitions) | Module `README.md` — Configuration Reference section | During the module's implementation phase |
| Topic/type definitions, QoS profile usage | Module `README.md` — Architecture section + code-level comments on entity creation | During the module's implementation phase |
| Cross-cutting system contracts (domain layout, partition strategy, alert pathways) | `docs/architecture/` — promoted from `docs/agent/vision/` | Post-V1.0.0 documentation audit |
| Behavioral specifications (GWT scenarios) | `docs/architecture/specs/` or remain as `tests/` docstrings | Post-V1.0.0 documentation audit |
| Simulation model and scenario profiles | Module `README.md` + `config/sim-profiles/README.md` | During Phase 2 implementation |
| Security architecture and governance posture | `docs/architecture/security.md` + security module README | During Phase 5 implementation |
| Performance baseline framework | `tests/performance/README.md` | During Phase 1 (benchmark harness step) |

### Phase-Level Handoff Step

Each implementation phase must include a documentation handoff verification as part
of its final step (typically the README & Documentation Compliance step). The
verification confirms:

1. **Self-sufficiency:** A developer reading only the module README and code can
   build, configure, run, and test the module without consulting `docs/agent/`.
2. **Architecture completeness:** The README's Architecture section documents every
   DDS entity, QoS profile, domain tag, and threading decision — not just a summary,
   but the actual design rationale that lives in `docs/agent/vision/`.
3. **Configuration completeness:** Every environment variable, XML file, and
   runtime parameter is documented with its type, default, and description.
4. **Cross-references point to permanent locations:** The Going Further section
   links to `docs/architecture/` (once created) or to the project root docs — not
   to `docs/agent/` files that will eventually be archived.

### Post-V1.0.0 Documentation Audit

After the V1.0.0 release gate passes, a documentation audit must be performed:

1. **Promote enduring content.** Create `docs/architecture/` and move system-level
   content (domain layout, partition strategy, data model summary, security posture,
   alert pathway design) from `docs/agent/vision/` into permanent architecture docs.
2. **Verify module READMEs.** Confirm each module README is fully self-sufficient
   per the criteria above.
3. **Archive planning artifacts.** Tag `docs/agent/` with the V1.0.0 release tag.
   Add a notice to `docs/agent/README.md` indicating it is a historical planning
   framework and directing readers to `docs/architecture/` and module READMEs.
4. **Update root README.** The project root `README.md` should reference
   `docs/architecture/` as the primary documentation, not `docs/agent/`.

The audit is a one-time effort at milestone completion. Subsequent milestones
(V1.1, V2.0, V3.0) update `docs/architecture/` directly rather than going through
the `docs/agent/` planning cycle — unless new modules require the full
vision → spec → implementation planning workflow.
