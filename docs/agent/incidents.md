# Incident Log

This file records incidents discovered during implementation.
See [workflow.md](workflow.md) Section 5 for the incident recording
process and format.

Incidents are numbered sequentially and are never deleted, even
after closure. They form the project's decision log.

---

## INC-001: rti.connext pip package vs rti.connextdds runtime import

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-23
- **Phase/Step:** Phase 1 / Step 1.1
- **Documents involved:** `vision/technology.md`, `implementation/phase-1-foundation.md`
- **Description:** The pip package is named `rti.connext` (installed via
  `pip install rti.connext==7.6.0`), but the runtime Python import is
  `rti.connextdds` (i.e., `import rti.connextdds as dds`). The import
  `import rti.connext` raises `ModuleNotFoundError`. This is the expected
  RTI packaging convention — the pip distribution name and the importable
  module name differ. Phase 1 test gate language
  (`.venv/bin/python -c "import rti.connext"`) uses the pip package name
  rather than the importable module name.
- **Possible resolutions:**
  1. Treat the test gate literally and consider `import rti.connextdds`
     as satisfying the intent (validate that the Connext Python package
     is installed and functional).
  2. Request a spec clarification to update the test gate wording.
- **Resolution:** Resolution 1 adopted. The test gate intent is to confirm
  the Connext Python package is installed and usable.
  `import rti.connextdds` succeeds and is the correct runtime import.
  All application code and future tests use `import rti.connextdds as dds`
  per the RTI API convention documented in `vision/technology.md`.
- **Date closed:** 2026-03-23
