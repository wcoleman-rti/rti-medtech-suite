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

---

## INC-002: Python codegen sys.path.append breaks flat install layout

- **Status:** Closed
- **Category:** Discovery
- **Date opened:** 2026-03-23
- **Phase/Step:** Phase 1 / Step 1.2
- **Documents involved:** `interfaces/CMakeLists.txt`,
  `vision/technology.md`
- **Description:** By default, `rtiddsgen -language Python` emits
  `sys.path.append(os.path.join(os.path.dirname(__file__), '<dep>/')))`
  and `from <dep> import *` at the top of each generated `.py` file.
  These stanzas assume that dependent IDL modules are in subdirectories
  relative to the importing file (e.g., `surgery/common/common.py`).
  When all generated files are installed flat into
  `lib/python/site-packages/` (as required by the install tree spec),
  the relative path does not resolve and imports fail with
  `NameError: name 'Common' is not defined`.
- **Possible resolutions:**
  1. Use the `-noSysPathGeneration` rtiddsgen flag to suppress the
     `sys.path.append` stanzas. Imports then resolve via `PYTHONPATH`
     which already includes the install `site-packages` directory.
  2. Restructure the install tree to mirror rtiddsgen's expected
     subdirectory layout (rejected — violates the flat
     `site-packages` convention in `vision/technology.md`).
- **Resolution:** Resolution 1 adopted. Added
  `EXTRA_ARGS -noSysPathGeneration` to the Python
  `connextdds_rtiddsgen_run()` calls in `interfaces/CMakeLists.txt`.
  See RTI documentation:
  <https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/connext_dds_professional/code_generator/users_manual/code_generator/users_manual/GeneratingCode.htm#4.1.4.2_Python_Import_Path>
- **Date closed:** 2026-03-23
