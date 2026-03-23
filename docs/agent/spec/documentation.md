# Spec: Documentation Standard

Behavioral specifications for README compliance across all module and service directories.
The documentation standard is defined in
[vision/documentation.md](../vision/documentation.md).

---

## Summary of Concrete Requirements

| Requirement | Value |
|-------------|-------|
| Markdownlint errors permitted | 0 |
| Markdownlint warnings permitted | 0 |
| Inline suppression comments permitted | None — never |
| Maximum line length (prose) | 100 characters |
| Required README sections | 7, in prescribed order |
| Fenced code blocks without language identifier | 0 permitted |
| Top-level headings (`#`) per file | Exactly 1, must be first line |
| CI enforcement | markdownlint + section-order lint script must both pass |

*This table must be updated whenever a concrete value in the scenarios below is added or
changed.*

---

## Markdownlint Compliance

### Scenario: README passes markdownlint with zero errors `@unit`

**Given** a module or service `README.md` exists
**When** `markdownlint` is run against it using the project-root `.markdownlint.json`
  configuration
**Then** the output contains zero errors and zero warnings

### Scenario: README contains no inline suppression comments `@unit`

**Given** a module or service `README.md` exists
**When** the file is scanned for markdownlint suppression patterns
  (`markdownlint-disable`, `markdownlint-disable-next-line`, `markdownlint-enable`)
**Then** no such patterns are found anywhere in the file

### Scenario: README has exactly one top-level heading as its first line `@unit`

**Given** a module or service `README.md` exists
**When** the file structure is analysed
**Then** the first non-empty line is a top-level heading (`# `)
**And** no other top-level heading exists in the file

### Scenario: All fenced code blocks declare a language identifier `@unit`

**Given** a module or service `README.md` contains one or more fenced code blocks
**When** every fenced code block opener (` ``` `) is examined
**Then** each one is followed immediately by a language identifier (e.g., `bash`, `cmake`,
  `xml`, `python`)
**And** no bare ` ``` ` openers exist

### Scenario: No bare URLs appear in the README `@unit`

**Given** a module or service `README.md` exists
**When** the file is scanned for bare URL patterns
**Then** all URLs appear inside a Markdown link (`[text](url)`) or a fenced code block
**And** no raw `http://` or `https://` strings appear outside of link syntax or code blocks

### Scenario: Prose line length does not exceed 100 characters `@unit`

**Given** a module or service `README.md` exists
**When** each line of prose content is measured
**Then** no prose line exceeds 100 characters
**And** lines within fenced code blocks, tables, and headings are exempt from this limit

---

## Section Structure Compliance

### Scenario: All required sections are present `@unit`

**Given** a module or service `README.md` exists
**When** the heading structure is extracted
**Then** the following `##`-level headings are present, in this order:
  1. `## Overview`
  2. `## Quick Start`
  3. `## Architecture`
  4. `## Configuration Reference`
  5. `## Testing`
  6. `## Going Further`
**And** no required section is absent or renamed

### Scenario: Required sections appear before any additional sections `@unit`

**Given** a `README.md` contains additional `##`-level sections beyond the required six
**When** the heading order is examined
**Then** all six required sections appear before any additional sections
**And** the additional sections appear only after `## Going Further`

### Scenario: Overview section contains a Connext features table `@unit`

**Given** a module or service `README.md` has an `## Overview` section
**When** the section content is examined
**Then** a Markdown table is present listing the Connext features used and how each is used
**And** the table has at minimum a `Connext Feature` column and a `How It Is Used` column

### Scenario: Quick Start section contains required subsections `@unit`

**Given** a module or service `README.md` has a `## Quick Start` section
**When** the section content is examined
**Then** the following subsections are present: Prerequisites, Build, Configure, Run
**And** each subsection contains at least one fenced code block with a language identifier

### Scenario: Architecture section documents DDS entities `@unit`

**Given** a module or service `README.md` has an `## Architecture` section
**When** the section content is examined
**Then** a **DDS Entities** subsection is present
**And** it documents every `DomainParticipant`, `DataWriter`, and `DataReader` the module
  creates, including the topic name, QoS profile name, and domain tag for each

### Scenario: Architecture section documents the threading model `@unit`

**Given** a module or service `README.md` has an `## Architecture` section
**When** the threading model description is examined
**Then** it explicitly identifies which thread performs DDS I/O
**And** it confirms DDS I/O does not occur on the main thread or UI event loop

### Scenario: Configuration Reference section provides an environment variables table `@unit`

**Given** a module or service `README.md` has a `## Configuration Reference` section
**When** the section content is examined
**Then** an **Environment Variables** subsection is present as a table
**And** each row documents the variable name, type, default value, and description
**And** the domain partition variable is explicitly listed with the required format
  (`room/<room_id>/procedure/<procedure_id>` or equivalent)

### Scenario: Testing section provides runnable commands `@unit`

**Given** a module or service `README.md` has a `## Testing` section
**When** the section content is examined
**Then** at least one fenced `bash` code block contains test run command(s)
**And** a table is present summarising coverage by scenario tag
**And** instructions for running a tagged subset of tests are included

### Scenario: Going Further section links to all required related documents `@unit`

**Given** a module or service `README.md` has a `## Going Further` section
**When** the links in the section are examined
**Then** links to the following documents are present:
  - The module's spec file under `spec/`
  - `vision/data-model.md`
  - `vision/system-architecture.md`
  - The module's implementation phase file

---

## CI Enforcement

### Scenario: CI pipeline fails if any README fails markdownlint `@integration`

**Given** a pull request modifies or adds a `README.md` under `modules/` or `services/`
**When** the CI pipeline runs
**Then** the markdownlint step executes against the changed README(s)
**And** the pipeline fails if any error or warning is reported
**And** the failure message identifies the file, line number, and rule violated

### Scenario: CI pipeline fails if any README is missing a required section `@integration`

**Given** a pull request modifies or adds a `README.md` under `modules/` or `services/`
**When** the CI pipeline runs the section-order lint script under `tests/lint/`
**Then** the pipeline fails if any required section heading is absent or out of order
**And** the failure message identifies the missing or misplaced section

### Scenario: CI pipeline fails if any suppression comment is present `@integration`

**Given** a pull request modifies or adds a `README.md` under `modules/` or `services/`
**When** the CI pipeline scans for inline markdownlint suppression patterns
**Then** the pipeline fails immediately if any suppression comment is found
**And** the failure message identifies the file and line containing the suppression
