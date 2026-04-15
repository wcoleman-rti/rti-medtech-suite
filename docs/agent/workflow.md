# Workflow Policies

Rules governing how an implementing agent conducts itself during any
session that modifies source code, configuration, tests, or
infrastructure in this repository. These policies are non-negotiable
and apply to every agent session regardless of context, model, or
provider.

This document is the single authority for process-level behavior. The
root [README.md](README.md) governs document change governance. The
[implementation/README.md](implementation/README.md) governs test
policy. This document governs everything else about how work is done.

---

## 1. Planning Documents Are Law

The files under `vision/`, `spec/`, and `implementation/` are the
agent's requirements. They are not suggestions, starting points, or
rough guidelines.

- **Never deviate from a vision contract.** If a vision document says
  QoS is XML-only, the agent must not write programmatic QoS. If it
  says domain IDs live only in domain library XML, the agent must not
  embed domain IDs in application code. No exceptions.
- **Never skip or reinterpret a spec scenario.** Every Given/When/Then
  scenario describes exact expected behavior. The implementation must
  satisfy the scenario as written — not a loose interpretation of it.
- **Never reorder or skip implementation steps.** Phase files define a
  deliberate sequence. Each step's test gate must be green before the
  next step begins. Parallelism is only permitted where the phase file
  explicitly states it.
- **Never invent features, optimizations, or refactors not called for
  by the current phase.** If the phase file does not ask for it, do not
  build it. Scope creep across sessions is the primary risk in
  multi-agent implementation.

---

## 2. Doc-First, Always

No implementation work begins until the planning documents for that
scope are complete, reviewed, and approved.

| Milestone state | What the agent may do |
|-----------------|----------------------|
| Vision + spec + phase file exist and are approved | Implement the phase |
| Vision + spec exist but phase file is missing | Draft the phase file and request operator approval — do not implement |
| Vision exists but spec is missing | Draft the spec and request operator approval — do not implement |
| Nothing exists | Draft the vision document and request operator approval — do not implement or draft downstream docs |
| Extension proposed on a completed project | Run impact analysis, then follow the extension cascade (vision → spec → phase → implement) per Section 9 |

If the agent discovers during implementation that a planning document
is incomplete, ambiguous, or appears incorrect, it must stop
implementing that area and follow the escalation process in
Section 5.

---

## 3. Session Discipline

### Starting a Session

1. Read `docs/agent/README.md` (this framework's root governance).
2. Read this file (`workflow.md`).
3. Read the current phase file to identify where work stopped (if
   resuming).
4. Run the full quality gate pipeline (`bash scripts/ci.sh`). Passing
   gates = completed work. Failing gates = in-progress work now
   broken. Zero tests = fresh start. See the **Test Commands
   Reference** below for the exact commands and when to use each.
5. Check `git status` and `git log --oneline -10` for uncommitted
   changes or recent commits.
6. Check `docs/agent/incidents.md` for any open incidents from prior
   sessions (see Section 5).
7. Only after steps 1–6 are complete may the agent begin
   implementation work.

### DDS / Connext Domain Knowledge

This project's planning documents (`vision/`, `spec/`,
`implementation/`) are the **primary authority** for all architectural
and design decisions. When a planning document specifies how something
must be done (e.g., QoS patterns, transport choices, threading model),
the agent follows the planning document — not external guidance.

For implementation decisions that the planning documents leave to the
agent's discretion (API call patterns, idiomatic Connext usage,
troubleshooting unexpected behavior), the agent must consult the
**`rti-chatbot-mcp`** MCP server tool for RTI Connext domain
expertise. Use it for:

- API usage patterns (Modern C++ API, Python API)
- QoS policy semantics and interactions
- Transport configuration (UDPv4, SHMEM, Real-Time WAN Transport)
- Service administration (Routing Service, Recording Service,
  Cloud Discovery Service, Collector Service)
- IDL and type system questions
- Connext Security Plugins configuration
- Troubleshooting DDS discovery, matching, or delivery issues

In short: **project docs decide _what_ to build; `rti-chatbot-mcp`
advises _how_ to build it correctly with Connext.**

When `rti-chatbot-mcp` is insufficient or the agent needs concrete
code patterns, consult these additional resources (in priority order):

1. **RTI Connext DDS Examples** —
   [examples/connext_dds](https://github.com/rticommunity/rticonnextdds-examples/tree/master/examples/connext_dds)
   — feature-specific examples demonstrating individual APIs and
   capabilities. Use `c++11/` subdirectories for Modern C++ and `py/`
   for Python.
2. **RTI Connext DDS Tutorials** —
   [tutorials](https://github.com/rticommunity/rticonnextdds-examples/tree/master/tutorials)
   — end-to-end walkthroughs. Use `c++11/` and `py/` subdirectories
   for the applicable language bindings.

### During a Session

- **One step at a time.** Complete the current implementation step's
  test gate before starting the next step.
- **Smoke tests on every step.** Before marking a step's test gate
  green, verify all `@smoke` tests pass. Tier 1 (host-side) catches
  import errors, missing routes, and broken CLI commands. Tier 2
  (container-side) catches container startup crashes, missing
  packages, wrong entrypoints, and unreachable URLs. Together these
  cover the failures most likely to block the operator's manual
  validation after a phase completes. A step that passes its
  functional gate but fails smoke tests is incomplete.
- **Commit at each test gate.** When a step's test gate is green,
  commit the work with a message referencing the phase and step
  (e.g., `phase-1: step 1.3 — QoS profiles and topic bindings`).
  Do not accumulate uncommitted work across multiple steps.
- **Mark completed steps in the phase file.** After committing a
  step, annotate its `## Step` heading in the phase file with ✅
  and the short commit hash (e.g.,
  `## Step 1.3 — QoS Profile Library ✅ \`10f7c6b\``). Check all
  test gate items as `[x]`. This gives resuming agents an
  instant visual summary of progress without reading git log.
- **No speculative work.** Do not begin the next step "while waiting"
  or pre-build infrastructure for future phases. The current step is
  the only scope.
- **No cleanup detours.** Do not refactor surrounding code, add
  comments to code you did not write, or "improve" file organization
  unless the phase file explicitly calls for it.
- **Record discoveries after each step.** Before committing a
  completed step, review the work for discoveries worth preserving:
  API quirks, workarounds, design decisions that deviated from the
  literal planning-doc text, patterns that future steps should follow,
  or environmental findings. Record each as a closed "Discovery"
  incident in `docs/agent/incidents.md` (see Section 5). Include a
  **Guideline** field summarising the reusable lesson. This is not
  optional — the incident log is the project's institutional memory
  and the primary mechanism for cross-session knowledge transfer.
- **Suggest doc clarifications.** If a step's implementation revealed
  that a planning document (vision, spec, or phase file) was ambiguous,
  incomplete, or could mislead a future agent, note the specific
  document and section in the commit message or in an incident, and
  propose a concrete edit to the operator. Do not modify planning docs
  without approval (Section 1), but do surface improvements proactively.
  Common triggers:
  - A vision example that uses a deprecated API or incomplete pattern
  - A spec scenario whose Given/When/Then is ambiguous about edge cases
  - A phase step whose test gate wording doesn't match the actual API
  - A naming convention that was unclear until implementation exposed it

### Ending a Session

1. Run the full quality gate pipeline (`bash scripts/ci.sh`) and
   confirm all gates pass.
2. Commit any uncommitted work with an appropriate message.
3. If work is incomplete, record in the commit message or a code
   comment exactly what remains (e.g.,
   `# TODO(phase-2/step-2.3): content filter not yet implemented`).
4. If any incidents were opened during the session and are now
   resolved, update `docs/agent/incidents.md` to mark them closed
   (see Section 5).

### Test Commands Reference

There are exactly **three test commands**. No other invocations,
flags, pipes, or output-parsing patterns are permitted.

#### Command 1 — Full quality gate pipeline

```bash
bash scripts/ci.sh
```

**When to use:** Session start, pre-commit, session end — the three
mandatory checkpoints. Also use when C++, IDL, CMake, Docker, or
markdown files changed (gates 2–7, 9, 12 cover these).

**Behavior:** Self-contained. Sources its own environment internally.
No `source install/setup.bash` is needed. Runs all 12 gates in order
(lint → build → install → Python tests → C++ tests → Docker). Exits
non-zero on the first failure.

**Convenience flags (same script, narrower scope):**

- `bash scripts/ci.sh --lint` — lint/style gates only (~5 s).
- `bash scripts/ci.sh --skip-build` — all gates except CMake
  build/install.

#### Command 2 — Python tests only

```bash
source install/setup.bash
python -m pytest -x --tb=short -q
```

**When to use:** Mid-step iteration when only Python source or test
files changed. This is the fast-feedback loop — use it freely while
coding. It must NOT replace Command 1 at mandatory checkpoints.

**Flags are mandatory and fixed:**

| Flag | Purpose |
|------|---------|
| `-x` | Stop on first failure — fix before continuing |
| `--tb=short` | Show concise tracebacks — enough to diagnose, not excessive |
| `-q` | Quiet progress — summary line at the end |

Note: `pyproject.toml` defines `addopts = "-n auto --dist loadgroup"`
which enables parallel execution via pytest-xdist. These flags are
always active and must not be overridden unless explicitly debugging
an xdist-specific issue (in which case use `-o "addopts="` to disable
temporarily, then restore before committing).

To run a single test file or test class during focused iteration:

```bash
source install/setup.bash
python -m pytest tests/path/to/test_file.py -x --tb=short -q
```

To run a single test by name:

```bash
source install/setup.bash
python -m pytest tests/path/to/test_file.py::TestClass::test_name -x --tb=short -q
```

#### Command 3 — C++ tests only

```bash
source install/setup.bash
ctest --test-dir build --output-on-failure
```

**When to use:** Mid-step iteration when C++, IDL, or CMake files
changed. Always rebuild first:

```bash
source install/setup.bash
cmake --build build && ctest --test-dir build --output-on-failure
```

#### Interpreting results

**The exit code is the sole source of truth.** Exit code 0 means all
tests passed. Non-zero means something failed.

Do not pipe test output through `grep`, `tail`, `head`, `awk`, or
any other filter to determine pass/fail. Do not parse stdout for
strings like "passed" or "failed." Do not re-run a test command
because output was truncated by a pipe or timeout.

If a command produces too much output to read, use the flags above
(`--tb=short -q` for pytest, `--output-on-failure` for ctest) —
these are already calibrated for the right verbosity level.

#### Terminal execution rules

1. **No timeouts on test commands.** Use timeout 0 (unlimited) when
   executing test commands in a terminal tool. Tests have their own
   internal timeouts. Prematurely killing a test run wastes time and
   requires a re-run.
2. **No output pipes.** Run test commands bare — no `| tail`, no
   `| grep`, no `2>&1 | head`. The full output must be visible for
   diagnosis if a test fails.
3. **One run is authoritative.** If a test command exits 0, the gate
   is passed. Do not re-run "to be sure." If it exits non-zero, the
   gate is failed — diagnose and fix, do not re-run hoping for a
   different result (if flakiness is suspected, that is a separate
   issue to investigate and fix, not to retry past).
4. **Environment sourcing.** Commands 2 and 3 require
   `source install/setup.bash` once per terminal session. This sets
   `NDDS_QOS_PROFILES`, `LD_LIBRARY_PATH`, `PYTHONPATH`, and
   activates the Python venv. Command 1 (`ci.sh`) handles this
   internally and requires no pre-sourcing.

---

## 4. Strict Boundaries

### What the Agent Must Never Do

| Prohibited action | Rationale |
|-------------------|-----------|
| Modify a `vision/`, `spec/`, or `implementation/` doc without operator approval | These are contracts, not working notes (see [README.md — Approval Rule](README.md)) |
| Delete or disable a test | Behavioral contracts are permanent (see [implementation/README.md — Test Policy](implementation/README.md)) |
| Add a dependency not listed in `vision/technology.md` | Undeclared dependencies break reproducibility and may violate regulatory traceability |
| Commit binary artifacts (fonts, test data, generated code) that can be fetched reproducibly at configure/build time | Binary blobs inflate the repository and complicate provenance tracking — use `file(DOWNLOAD)` with pinned hashes or `FetchContent` instead |
| Change a domain ID, topic name, or QoS profile name | These are architectural constants defined in `vision/data-model.md` |
| Use programmatic QoS (except XTypes compliance mask bit `0x00000020`, type registration, and participant partition — see `vision/data-model.md`) | All QoS is XML-only per `vision/data-model.md` and `vision/technology.md`. Exceptions: (1) the factory-level `accept_unknown_enum_value` XTypes compliance mask, which has no XML equivalent; (2) participant-level partition (`DomainParticipantQos::partition`), which is context-dependent startup configuration set in code after `create_participant_from_config()`. |
| Write DDS I/O on the main/UI thread | Threading model is mandated by `vision/technology.md` |
| Use `DataReaderListener` for data/sample processing | Listener callbacks block the middleware's shared receive thread — use `SampleProcessor`, `AsyncWaitSet` + `ReadCondition`, or polling `read()`/`take()` instead (see `vision/coding-standards.md`) |
| Embed domain IDs as literals in source code or documentation | Domain IDs are defined exactly once in `vision/data-model.md` Domain Definitions and in the domain library XML files (`RoomDatabuses.xml`, `HospitalDatabuses.xml`, `CloudDatabuses.xml`). All other references use the **semantic databus name** (e.g., "Procedure control databus", "Hospital Integration databus"). See the No-Numeric-ID Rule in `vision/system-architecture.md`. |
| Suppress a markdownlint warning or error | Zero-suppression policy per `vision/documentation.md` |
| Use `--force`, `--no-verify`, or equivalent safety bypasses | Reversibility and safety are non-negotiable |
| Push code without running the full test suite | See Section 3 commit discipline |
| Use `print()`, `printf`, `std::cout`, or a custom logging framework | All logging must use the RTI Connext Logging API per `vision/technology.md` |
| Use DynamicData / DynamicType in application code | All applications must use IDL-generated types. DynamicData is permitted only in developer tools (e.g., `tools/qos-checker.py`) and test utilities. See `vision/coding-standards.md`. |
| Mount host-compiled C++ binaries or shared libraries into Docker containers | Host toolchain ABI may differ from container runtime libraries, causing GLIBCXX/GLIBC mismatches. Compile inside the container. |

> **Consolidated reference:** All DDS-specific prohibited patterns above are cataloged with detailed risk assessments and approved alternatives in [vision/dds-consistency.md — Anti-Pattern Catalog](vision/dds-consistency.md). The initialization sequence, canonical data access patterns, and new module checklist in that document operationalize these prohibitions into actionable guidance.

### What the Agent May Decide Autonomously

| Permitted decision | Scope |
|--------------------|-------|
| Internal implementation details (variable names, function signatures, class structure) | Within the current phase step, provided the external behavior matches the spec |
| Choice of standard library utilities | Python stdlib, C++ STL, Qt utilities already in the dependency list |
| Test helper structure | Fixtures, factories, parameterized tests — as long as no test is deleted and all scenarios are covered |
| File organization within a module directory | Subdirectory layout, file naming within `modules/<name>/` — provided it satisfies `vision/documentation.md` README requirements |

If a decision does not clearly fall into one of these categories,
escalate per Section 5.

---

## 5. Escalation and Incident Recording

### When to Escalate

The agent must stop implementation and escalate to the operator when
any of the following occur:

- A planning document (vision, spec, or phase file) appears to
  contain a contradiction, ambiguity, or gap that prevents
  implementation.
- A spec scenario cannot be satisfied without violating a vision
  contract.
- A third-party tool, library, or service behaves differently than
  the planning documents assume.
- The agent encounters a situation not addressed by any planning
  document and cannot proceed without making an architectural
  decision.
- A test that was previously passing now fails due to an external
  change (dependency update, environment change).
- The agent believes a planning document is incorrect and should be
  changed.

### How to Escalate

1. **Stop implementing the affected area.** Do not attempt a
   workaround, best guess, or temporary fix. Workarounds introduced
   in one session become permanent tech debt in the next.
2. **Record an incident** in `docs/agent/incidents.md` (create the
   file if it does not exist). Each incident is a dated entry with:
   - A short title
   - The phase and step where the issue arose
   - The specific document(s) involved
   - A factual description of the conflict or gap
   - The agent's assessment of possible resolutions (without
     implementing any of them)
3. **Notify the operator** with a summary of the incident and a
   request to resolve it before implementation continues in that area.
4. **Continue working on other steps or phases** that are not blocked
   by the incident — but only if those steps have no dependency on
   the blocked area.

### Incident File Format

```markdown
## INC-<NNN>: <Short title>

- **Status:** Open | Closed
- **Date opened:** YYYY-MM-DD
- **Phase/Step:** Phase N / Step N.M
- **Documents involved:** `vision/data-model.md`, `spec/surgical-procedure.md`
- **Description:** <Factual description of the conflict or gap.>
- **Possible resolutions:**
  1. <Option A>
  2. <Option B>
- **Resolution:** <What was decided, by whom, and when. Filled in
  when the incident is closed.>
- **Date closed:** YYYY-MM-DD
```

Incidents are numbered sequentially (`INC-001`, `INC-002`, ...) and
are never deleted, even after closure. They form the project's
decision log.

---

## 6. Cross-Session Continuity

Multiple agent sessions — possibly with different models, providers,
or context window sizes — will work on this project over time. These
rules exist to prevent drift between sessions.

- **Trust the docs, not memory.** A resuming agent must re-read the
  relevant planning documents rather than relying on conversation
  history or summaries from prior sessions. Documents are the single
  source of truth.
- **Trust the tests, not assumptions.** The test suite is the
  definitive record of what works. A resuming agent must run the full
  suite before making any changes.
- **Do not undo another session's work.** If a prior session's
  implementation approach looks unusual but all tests pass, leave it
  alone. If tests are failing, fix the code to match the spec — do
  not rewrite from scratch unless the approach is fundamentally
  incompatible with the spec.
- **Preserve commit history.** Do not squash, rebase, or rewrite
  published history. Each session's commits are a traceable record.
- **Check incidents first.** Before starting any new work, read
  `docs/agent/incidents.md` for open incidents that may block or
  constrain the planned work.
- **Record discoveries.** If a session discovers something useful
  about the environment, tooling, or RTI Connext behavior (e.g., a
  specific `rtiddsgen` flag behavior, a Docker networking quirk, a
  NiceGUI asyncio integration detail), record it as a closed incident
  with category "Discovery" so future sessions benefit.

### Context Window Management

Agent sessions have a finite context window. These rules prevent
wasted tokens and keep sessions productive:

- **Read only what you need.** Do not read entire files when a
  targeted line range or search will answer the question. Read the
  phase file, the spec scenarios for the current step, and the
  relevant vision section — not every planning document at once.
- **Batch parallel reads.** When multiple files are needed for one
  decision, read them in a single parallel batch rather than
  sequentially. This applies to audits, cross-reference checks, and
  multi-file edits.
- **Front-load planning docs; defer source files.** Read planning
  documents during the session start sequence (Section 3). Defer
  reading source files until the specific step that modifies them.
- **Prefer search over scan.** Use targeted text search or semantic
  search to locate specific definitions, rather than reading files
  end-to-end looking for a passage.
- **Summarize before discarding.** If a large file was read for one
  decision and will be needed again later, capture the key facts
  (line numbers, values, function names) in a working note rather
  than re-reading the file.
- **One step per commit, one commit per step.** This is already
  required by Section 3, but it also bounds context: once a step is
  committed, its implementation details can be dropped from working
  memory. The tests guarantee correctness going forward.

---

## 7. Quality Gates

Before any code is pushed or presented as complete, the agent must
verify the checks below. The **Reviewer** agent
(`.github/agents/reviewer.agent.md`) can run this full checklist on
demand — use it after completing a phase, after an extension cycle,
or at any point to catch compliance drift.

| Gate | Check |
|------|-------|
| **Tests** | Full test suite passes. Zero failures, zero skips, zero expected-failures. |
| **Smoke** | All `@smoke` tests pass — **Tier 1 (host):** every application entry point imports without error, expected routes are registered, CLI commands are reachable (no Docker needed). **Tier 2 (container):** each application container starts without crash, health probe responds within timeout, expected URL is reachable via port mapping (single `docker run` + probe, no composed system). Smoke tests must pass **at every step**, not just at phase completion. |
| **Build** | Clean build from scratch (`cmake --build` from empty build dir for C++; `pip install` + import check for Python). |
| **Install** | `cmake --install build` succeeds. Install tree contains all expected artifacts. `source install/setup.bash` sets all runtime env vars correctly. |
| **Lint** | `markdownlint` passes on all `README.md` files under `modules/` and `services/` with zero errors and zero warnings. |
| **Code style** | Python: `black --check .`, `isort --check .`, `ruff check .` all pass with zero findings. C++: naming and conventions per `vision/coding-standards.md` enforced by review. |
| **Generated code** | No generated files committed to source tree. `rtiddsgen` output goes to build directory only. |
| **QoS** | All QoS is in XML profiles. `grep` for QoS setter API calls in application code must return zero matches. All XML files validate against the RTI XSD for the current `CONNEXT_VERSION`. |
| **Domain IDs** | `grep` for literal domain ID integers (10, 11) in application code must return zero matches (they belong in domain library XML only). |
| **Thread safety** | No blocking DDS waits on the asyncio event loop. Python uses `async`/`await` + `background_tasks.create()` (NiceGUI); C++ uses `AsyncWaitSet` or `SampleProcessor`. |
| **Logging** | Every module configures the RTI Connext Logging API per `vision/technology.md`. No `print()`, `printf`, `std::cout`, or custom logging. Module name prefix matches module directory name. |
| **Dependencies** | No new dependencies beyond those listed in `vision/technology.md` and `requirements.txt`. |
| **Third-party notices** | Every third-party component — whether fetched during configure/build (FetchContent, `file(DOWNLOAD)`), installed via pip (`requirements.txt`), or pulled as a Docker image — is documented in `THIRD_PARTY_NOTICES.md` at the repository root. CMake/Docker components list: name, version/pin, SPDX license, source URL, fetching mechanism, and usage. Python pip packages list: name, SPDX license, and usage (version pins live in `requirements.txt`). When adding a new dependency of any kind, update `THIRD_PARTY_NOTICES.md` in the same commit. |
| **Performance baseline** | Run `python tests/performance/benchmark.py` against the latest committed baseline. All metrics within regression thresholds per `vision/performance-baseline.md`. At phase completion, record a new baseline with `--record --phase <phase>`. |
| **Publication model** | Every topic's publisher uses the correct publication model (continuous-stream, periodic-snapshot, or write-on-change) as defined in `vision/data-model.md` Publication Model section. Write-on-change topics must not publish on a fixed timer. |
| **Docker build** | `docker compose --profile build build` succeeds. Multi-stage application images build without errors. `robot-controller` runs inside `cpp-runtime` container without library version mismatches. |

These gates are not aspirational. A phase step is not complete until
every gate passes. If a gate cannot pass, escalate per Section 5.

> **CI script authority:** The executable quality gate sequence lives in
> `scripts/ci.sh`. The table above describes the conceptual gate
> categories. As implementation progresses, `scripts/ci.sh` may include
> additional automated gates (e.g., performance benchmark, QoS
> compatibility check) that map to the categories above. When in doubt,
> the CI script is the authoritative list of what must pass.

---

## 8. DDS Design Review Gate

Before implementation of DDS entities begins (Phase 1, Step 1.3 completion or
Phase 2 start — whichever creates the first DDS entity beyond test stubs), the
agent must submit the DDS data model artifacts to `rti-chatbot-mcp` for review.

### What to Submit

| Artifact | Location | Review Focus |
|----------|----------|--------------|
| IDL type definitions | `interfaces/idl/` | Type structure, key selection, bounds, extensibility annotations |
| QoS XML hierarchy | `interfaces/qos/` | Profile composition, Snippet/Pattern/Topic layering, RxO compatibility |
| Domain library XML | `interfaces/domains/` | Domain/topic/type registration, domain tag assignments |
| Participant configuration | `interfaces/qos/Participants.xml` | Discovery, transport, resource limits, domain tag XML |
| Publication model | `vision/data-model.md` Publication Model | Write-on-change vs continuous-stream vs periodic-snapshot assignments |

### Review Process

1. **Prepare a review prompt** that includes the artifact contents and asks
   `rti-chatbot-mcp` to evaluate: QoS compatibility across writer/reader pairs,
   correct use of domain tags and domain partitions, IDL type design (key fields,
   bounds, extensibility), transport and discovery configuration for the Docker
   multi-network topology, and any potential issues with the proposed publication
   model.
2. **Record findings.** If `rti-chatbot-mcp` identifies issues, record them
   as items to address before proceeding. If findings require architectural
   changes, escalate per Section 5.
3. **Re-review after changes.** If significant changes are made to address
   findings, re-submit the affected artifacts.

This review is a **quality gate** — not a blocking approval. The agent proceeds
after addressing findings. The purpose is to catch DDS-specific design issues
(QoS incompatibility, discovery misconfiguration, type system pitfalls) that
functional tests may not reveal until much later.

> **Implementation guidance:** After the design review clears, use
> [vision/dds-consistency.md](vision/dds-consistency.md) as the operational
> reference for implementing DDS entities — it provides the canonical
> initialization sequence, data access patterns, and new module checklist.

### Subsequent Reviews

After the initial review, the agent should consult `rti-chatbot-mcp` for
targeted review whenever:

- A new topic or type is added
- QoS profiles are modified
- Transport or discovery configuration changes
- An unexplained DDS behavior is observed during testing

---

## 9. Evolution Mode Policies

These policies apply when extending the medtech suite with new
capabilities after the original implementation plan is complete
(see [README.md — Evolution Mode](README.md)).

### Impact-Before-Action

Every extension begins with an **impact analysis** before any document
is modified or any code is written. The analysis must identify:

- Every planning document (vision, spec, implementation) affected by
  the proposed change.
- Every shared interface (IDL types, QoS profiles, domain library,
  Routing Service config) that the change touches.
- Every existing test that could be affected.
- The version impact (minor vs. major bump).

The impact analysis is presented to the operator for review before
proceeding.

### Extension Cascade Rule

The cascade rule from [README.md — Document Change Governance](README.md)
applies with additional rigor during evolution:

1. **Vision update** — modify or add entries in the relevant vision
   document(s). Get operator approval.
2. **Spec update** — author new GWT scenarios for new behavior; review
   existing scenarios for compatibility. Get operator approval.
3. **Phase file** — author a new phase file for the extension (or add
   steps to an existing phase, if the extension is small). Get operator
   approval.
4. **Only then implement.**

Each step requires explicit operator approval. The agent must not
combine steps or begin implementation before the full design cycle
is complete.

### Existing Test Preservation

During evolution work, the full existing test suite is run at every
step gate — not just the new tests. If an existing test fails:

| Situation | Required action |
|-----------|----------------|
| Break is an expected consequence of an intentional behavioral change | Stop. Update the spec (with approval), then update the test. Document the rationale in the commit message. |
| Break is a regression (unintended side effect) | Fix the implementation. Do not modify the existing test. |
| Ambiguous | Escalate per Section 5. Do not modify the test or continue implementation until resolved. |

### Phase Numbering for Extensions

New phases added during evolution continue the existing phase numbering
sequence. For example, if the original plan had Phases 1–6, the first
extension phase is Phase 7.

Update `implementation/README.md` to include the new phase in the phase
structure and dependency graph.

### Version Tagging

After the extension's phase is complete and all tests (new + existing)
pass, tag the release per `vision/versioning.md`:

- Minor extensions: `V<major>.<minor+1>` (e.g., V1.0 → V1.1)
- Architectural extensions: `V<major+1>.0` (e.g., V1.x → V2.0)

Update `vision/capabilities.md` milestones to reflect the new version.
