# Medtech Suite — Agent Guidance Framework

This directory is the authoritative planning and specification framework for the medtech suite. It is organized for modular AI agent consumption: each subdirectory addresses a distinct concern and can be attached independently to an agent session without requiring the full context.

---

## Evolution Mode — Extending the Medtech Suite

### When to Use Evolution Mode

Use evolution mode when:

- The original implementation plan has been fully executed (all phases
  complete, all tests passing, a versioned release exists).
- The user wants to add a new module, new topics, new domain tags, new
  phases, or otherwise extend the project beyond its original scope.

A preconfigured **Extender** agent (`.github/agents/extender.agent.md`) is
provided for this mode. Select it from the Copilot agent picker or invoke
it with `@extender` in chat.

### Extension Cycle Overview

Every extension follows a three-phase cycle that mirrors the original
design → implementation pipeline but with the additional constraint of
preserving the integrity of the existing system:

1. **Impact Analysis** — classify the extension, identify all affected
   documents (vision → spec → implementation), and assess regression
   risk against existing tests and shared interfaces.
2. **Design the Extension** — author or update planning documents
   following the cascade rule (`vision/` → `spec/` → `implementation/`).
   Each document change requires explicit user approval.
3. **Implement the Extension** — build the new capability step by step,
   validating that both new tests AND the full existing test suite pass
   at every gate.

### Extension Categories

The Extender recognizes these extension types and adjusts its impact
analysis accordingly:

| Extension Type | Typical Scope | Version Impact |
|----------------|---------------|----------------|
| New module (e.g., new clinical subsystem) | New vision entries, new spec file, new phase file | Minor bump (V1.x) |
| New topics/types | `data-model.md` update, spec updates, phase updates | Minor bump |
| Module enhancement | `capabilities.md` update, spec additions, phase additions | Minor bump |
| New domain or domain tag (e.g., new IEC 62304 risk class) | Architecture change, multiple vision/spec updates | Major bump (V2.0) |
| Infrastructure change | `technology.md` update, build/Docker changes | Minor bump |
| Connext version upgrade | `technology.md`, validation across all modules | Minor or major bump |

### Guardrails

- **Doc-first applies.** No implementation code is written until the
  extension's vision, spec, and phase documents are authored and approved.
- **Cascade rule applies.** A vision change triggers spec review, which
  triggers implementation review.
- **Existing tests are sacred.** The full existing test suite must pass
  before the extension begins and after every step. If an existing test
  breaks, the agent stops and assesses whether it is an expected behavioral
  change (requiring spec update and approval) or a regression (requiring
  an implementation fix).
- **Approval required for every doc change.** Even in evolution mode, the
  agent must not autonomously modify planning documents.

---

## Review Mode — Compliance Auditing

### When to Use Review Mode

Use review mode at any point during or after implementation to verify the
project conforms to the framework's rules, specs, and quality gates. Common
trigger points:

- After completing an implementation phase (before tagging a milestone)
- After an extension cycle (before tagging a new version)
- Periodically during multi-session implementation to catch drift
- Before a demo or presentation
- When onboarding a new contributor who wants to assess project health

A preconfigured **Reviewer** agent (`.github/agents/reviewer.agent.md`) is
provided for this mode. Select it from the Copilot agent picker or invoke
it with `@reviewer` in chat.

### What the Reviewer Audits

The Reviewer runs a 10-category checklist covering all quality gates defined
in [workflow.md](workflow.md) Section 7:

1. **Spec ↔ test traceability** — every GWT scenario has a test, every test
   references a valid spec tag
2. **QoS compliance** — no programmatic QoS, no hardcoded domain IDs or
   partitions
3. **Threading model** — no DDS I/O on main thread, no `DataReaderListener`
4. **Logging compliance** — RTI Connext Logging API only, module prefix
5. **Coding standards** — naming, file organization, style tools
6. **Documentation coverage** — README in every directory, markdownlint
7. **Dependency compliance** — no undeclared dependencies
8. **Build & install** — clean build, correct install tree
9. **Publication model** — correct model per topic per `data-model.md`
10. **Test suite health** — zero failures, zero skips, correct naming

The Reviewer is **strictly read-only** — it reports findings but never
modifies files. The user decides which agent (Implementer or Extender)
should address any findings.

---

## Debug Mode — DDS Runtime Troubleshooting

### When to Use Debug Mode

Use debug mode when the system is running (or recently ran) and something
isn't working correctly. Common symptoms:

- Data not flowing between publishers and subscribers
- Discovery failures (participants don't see each other)
- QoS mismatch warnings in logs
- Partition isolation not working as expected
- Deadline violations or liveliness loss events
- Routing Service not bridging data between domains
- Performance degradation (latency spikes, throughput drops)
- Docker containers unhealthy or failing to start

A preconfigured **Debugger** agent (`.github/agents/debugger.agent.md`) is
provided for this mode. Select it from the Copilot agent picker or invoke
it with `@debugger` in chat.

### How the Debugger Works

The Debugger follows structured **diagnostic playbooks** for common DDS
runtime issues. Each playbook is a step-by-step investigation that:

1. Gathers evidence using RTI tools (`rtiddsspy`, `rtimonitor`, Docker
   commands, log analysis)
2. Cross-references findings against the project's planning documents
   (`vision/system-architecture.md`, `vision/data-model.md`,
   `spec/common-behaviors.md`)
3. Consults `rti-chatbot-mcp` for DDS-specific expertise
4. Proposes targeted fixes with references to the planning doc rule that
   supports the change

The Debugger requires **user approval** before modifying any file. It
will never weaken QoS settings, bypass security, or disable tests as a
troubleshooting shortcut.

---

## Project Goal

The medtech suite is a multi-domain RTI Connext Professional demonstration system that simulates a hospital environment with concurrent surgical procedures, a facility-wide dashboard, and a clinical decision support engine. It communicates entirely over DDS and is designed to demonstrate the value of RTI Connext in a medtech context:

- Real-time deterministic data exchange across safety-critical, clinical, and operational data classes
- Multi-domain isolation with domain tags aligned to medical device risk classifications (IEC 62304 / FDA)
- Cross-domain bridging via RTI Routing Service
- Facility-wide situational awareness without coupling modules to each other
- Multicast-free participant discovery via RTI Cloud Discovery Service
- A unified CMake build producing C++ services and Python/NiceGUI web applications from shared IDL and QoS

Every behavior is specified as a Given/When/Then scenario. Every scenario becomes an automated test. Tests are never deleted.

---

## Agent Kickoff

**You are the implementing agent for this project.** This document is your entry
point. The planning documents under this directory are your requirements — they
are not suggestions or rough guidelines.

### Session Start Sequence

Before writing or modifying any code, complete these steps in order:

1. Read this file (`docs/agent/README.md`) — you are here.
2. Read [workflow.md](workflow.md) — process policies, session discipline,
   escalation rules, quality gates, DDS domain knowledge sources.
3. Read [implementation/README.md](implementation/README.md) — test policy,
   phase dependency graph, resumption guide.
4. Identify the current phase — read the phase file listed as in-progress
   (start with [phase-1-foundation.md](implementation/phase-1-foundation.md)
   if no work has been committed).
5. Run the full test suite (`pytest tests/` if tests exist). Passing tests =
   completed work. Failing tests = in-progress work now broken. Zero tests =
   fresh start.
6. Check `git status` and `git log --oneline -10` for uncommitted changes or
   recent commits.
7. Check [incidents.md](incidents.md) for open incidents from prior sessions.
8. Only after steps 1–7 are complete may you begin implementation work.

### Execution Rules

These are non-negotiable. The full set is in [workflow.md](workflow.md); the
critical subset is here for immediate visibility:

- **Planning documents are law.** Never deviate from a vision contract, skip a
  spec scenario, or reorder implementation steps.
- **One step at a time.** Complete each step's test gate before starting the
  next. Commit at each test gate.
- **All QoS is XML-only.** Exceptions: XTypes compliance mask, type
  registration, and participant partition (context-dependent startup config) —
  see `vision/data-model.md`.
- **No DDS I/O on the main/UI thread.** No `DataReaderListener` for data
  processing. No `print()`/`printf`/`std::cout` — use the RTI Connext Logging
  API only.
- **Consult `rti-chatbot-mcp`** for RTI Connext domain expertise when making
  implementation decisions the planning docs leave to your discretion.
- **Escalate, don't guess.** If you encounter a contradiction, ambiguity, or
  gap in the planning documents, stop and escalate per
  [workflow.md](workflow.md) Section 5. Do not work around it.

### How to Begin

After completing the session start sequence, proceed to the first incomplete
step in the current phase file. Each step specifies its work items and test
gate. Work through steps sequentially until the phase is complete, then move
to the next phase per the dependency graph in
[implementation/README.md](implementation/README.md).

---

## Framework Structure

```
docs/agent/
  ├── vision/              ← What are we building and why?
  ├── spec/                ← How do we know it works?
  └── implementation/      ← How do we build it, in what order?
```

Each directory contains a `README.md` that indexes its files and states its own conventions.

### vision/

Defines the architecture, technology decisions, data model, and V1 capability scope. These are the **system contracts** — non-negotiable constraints that all modules and phases must respect. Read this before making any design decision that touches domain layout, topics, QoS, IDL, or cross-module structure.

### spec/

Contains Given/When/Then behavioral specifications organized by module and cross-cutting concern. Every spec scenario must have a corresponding automated test. Specs are immutable once a test is green — if behavior needs to change, the spec is updated first with explicit justification.

### implementation/

Contains the phased work plan. Each phase file describes the deliverables, step-by-step work, and the test gates that must pass before proceeding. Phases depend on each other in a defined order. Includes a resumption guide for interrupted sessions.

---

## When to Attach What

| Task | Attach |
|------|--------|
| Making architecture or design decisions | `vision/` (start with `vision/README.md` for contracts, then the relevant file) |
| Writing or reviewing tests | `spec/` file for the relevant module + `vision/data-model.md` for topic/type names |
| Implementing a specific phase | The phase file + relevant `spec/` files + relevant `vision/` files (phase file lists its dependencies) |
| Debugging a cross-module behavior | `vision/system-architecture.md` + `spec/common-behaviors.md` |
| Authoring or modifying IDL or QoS | `vision/data-model.md` |
| Modifying the build system | `vision/technology.md` + `implementation/phase-1-foundation.md` |
| Security design or implementation | `vision/security.md` + `spec/security.md` + `implementation/phase-7-security.md` |
| Release versioning or milestone scoping | `vision/versioning.md` + `vision/capabilities.md` |
| Quick reference on non-negotiable rules | `vision/README.md` — System Contracts section |
| Understanding agent conduct during implementation | [workflow.md](workflow.md) — process policies, session discipline, escalation, quality gates |
| Running or evaluating performance benchmarks | `vision/performance-baseline.md` + `spec/performance-baseline.md` — metrics, thresholds, harness usage, baseline recording policy |
| Authoring or configuring simulators | `vision/simulation-model.md` — scenario profiles, simulation fidelity, cross-signal correlation, seed configuration |
| Debugging or troubleshooting DDS issues | `vision/tooling.md` — diagnostic tools, RTI Admin Console/DDS Spy usage, scenario-to-tool mapping |
| Understanding documentation handoff | `vision/documentation.md` — Documentation Handoff section — progressive transfer from `docs/agent/` to module READMEs and `docs/architecture/` |
| Extending the project after initial implementation | This file (Evolution Mode) + `vision/capabilities.md` + `vision/versioning.md` |
| Auditing project compliance | [workflow.md](workflow.md) (Section 7 — Quality Gates) + `spec/` + `vision/coding-standards.md` |
| Diagnosing DDS runtime issues | `vision/tooling.md` + `vision/system-architecture.md` + `spec/common-behaviors.md` |

---

## Directories

| Document / Directory | Purpose |
|----------------------|---------|
| [workflow.md](workflow.md) | Agent workflow policies — session discipline, strict boundaries, escalation process, incident recording, quality gates |
| [vision/](vision/) | System contracts, domain architecture, data model (IDL + QoS), technology stack, V1 capability scope, security architecture, simulation model, tooling & diagnostics |
| [spec/](spec/) | GWT behavioral specs per module, cross-cutting behavior specs (partition isolation, durability, QoS, routing), tagging conventions |
| [implementation/](implementation/) | Phased work plan, per-phase step-by-step work items, test gates, phase dependency graph, resumption guide |

---

## Document Change Governance

For process-level policies governing how an implementing agent conducts itself (session discipline, strict boundaries, escalation, quality gates), see [workflow.md](workflow.md). The rules below govern changes to the planning documents themselves.

### Cascade Rule

Changes to documents in this framework propagate downstream:

```
vision/  →  spec/  →  implementation/
```

- **A change to a `vision/` document** requires revisiting the affected `spec/` file(s) to verify scenarios still reflect the updated architecture. Update any scenarios that reference changed topics, domain names, QoS profiles, partition formats, or behavioral contracts.
- **A change to a `spec/` document** requires revisiting the affected `implementation/` phase file(s) to verify work items, test gates, and acceptance criteria still align. Update any steps that reference changed scenario names, behaviors, or test preconditions.

### Approval Rule

**After implementation has started (i.e., any Phase 1 work has been committed), no autonomous changes to `vision/`, `spec/`, or `implementation/` documents are permitted.**

All proposed changes to these documents must be:
1. Presented to the operator with a clear description of what is changing and why
2. Explicitly approved before any edit is made
3. Followed by the cascade review above (spec updated if vision changed, implementation updated if spec changed)

This rule exists because changes to planning documents after implementation has begun can silently invalidate passing tests, break behavioral contracts, or introduce inconsistencies between what is specified and what is built. The operator must be the decision point for any such change.

### Relationship to the Versioning Policy

Document changes after implementation has started also carry versioning consequences. Before proposing a change, consider which version increment it warrants per [vision/versioning.md](vision/versioning.md):

| Change type | Version impact |
|-------------|----------------|
| New spec scenarios for an existing milestone scope | Minor increment (e.g. V1.0.0 → V1.1.0) or Patch if fixing an incorrect scenario |
| New module, integration gateway, or Connext service introduced | Major increment — new milestone scope |
| Vision architecture change that alters existing behavioral contracts | Requires spec cascade review; if tests must change, it is a breaking change and warrants a Major increment proposal |
| Bug fix, doc correction, config fix, no behavioral change | Patch increment |
| Expanding a future milestone's scope (V2, V3) before that milestone is in-progress | No version impact — roadmap edit only; still requires operator approval |

When proposing a change, always state the intended version increment alongside the description of what is changing. Changes that cannot be cleanly categorized should be escalated to the operator for a versioning decision before any edit is made.

---

## Agent Transitions

Five preconfigured agents exist in `.github/agents/`. Each agent is
specialized for a specific lifecycle phase. This section defines the
handoff criteria — when to transition from one agent to another.

### Transition Map

| From | To | Trigger | Gate |
|------|----|---------|------|
| `@planner` | `@implementer` | Design Readiness Audit passes | All criteria in Design Readiness Gate are met, and the user has explicitly stated: "The design is complete. Begin implementation." |
| `@implementer` | `@reviewer` | Phase complete (before milestone tag) | All steps in the phase are done, all tests pass. User requests a compliance audit. |
| `@reviewer` | `@implementer` | Findings require code changes | Reviewer reports non-compliant findings. User directs Implementer to fix them. |
| `@implementer` | `@debugger` | Runtime issue during testing | System is running but exhibiting unexpected DDS behavior (data not flowing, QoS mismatch, discovery failure, etc.). |
| `@debugger` | `@implementer` | Root cause identified, fix proposed | Debugger has diagnosed the issue and proposed a fix. User approves. Implementer applies it. |
| `@implementer` | `@extender` | All original phases complete | Full implementation plan is done, a versioned release (e.g., V1.0) has been tagged, and the user wants to add new capability. |
| `@extender` | `@reviewer` | Extension phase complete | Extension implementation is done. User requests a compliance audit before tagging the new version. |
| Any | `@reviewer` | On demand | User can invoke the Reviewer at any point for a compliance check. |
| Any | `@debugger` | On demand | User can invoke the Debugger whenever the system is running and exhibiting issues. |

### Handoff Rules

1. **Only the user initiates transitions.** Agents suggest when a
   transition is appropriate, but the user must explicitly switch.
   No agent may autonomously invoke another agent.
2. **Gate before handoff.** The outgoing agent must verify its gate
   criteria are met before suggesting a transition. The Planner runs
   the Design Readiness Audit; the Implementer runs the full test
   suite; the Extender runs impact + test verification.
3. **State is in the repo.** Agents do not pass state to each other
   through conversation. The incoming agent reads `docs/agent/` and
   the repo state (tests, git log, incidents) to orient itself.
4. **Incidents carry across.** Open incidents in `docs/agent/incidents.md`
   are visible to all agents. An incident opened by the Implementer
   can be investigated by the Debugger and resolved by any agent.
