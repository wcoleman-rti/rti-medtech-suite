# Third-Party Notices

This file documents third-party software and materials used by the
medtech-suite project. These components are fetched automatically
during CMake configure or build — they are not system prerequisites
and are not committed to the source tree.

For Docker container base images used in the observability stack, see
the [Docker Images](#docker-images) section.

---

## Google Fonts

| Field | Value |
|-------|-------|
| **Components** | Inter, Roboto Condensed, Montserrat, Roboto Mono (variable-weight TTF) |
| **License** | [SIL Open Font License 1.1 (OFL-1.1)](https://scripts.sil.org/OFL) |
| **Source** | <https://github.com/google/fonts> |
| **Pinned commit** | `3d6da8b416357e1f6a32fbff76b22d52ad1e9bc5` |
| **Fetched by** | `resources/fonts/CMakeLists.txt` via `file(DOWNLOAD)` at configure time |
| **Verification** | SHA-256 hash per file |
| **Usage** | GUI typography in NiceGUI applications (see `modules/shared/medtech/gui/`) |

The OFL permits free use, redistribution, and bundling in software
products, provided font files are not sold by themselves.

---

## GoogleTest

| Field | Value |
|-------|-------|
| **Component** | Google Test (gtest + gmock) |
| **Version** | v1.14.0 |
| **License** | [BSD 3-Clause](https://github.com/google/googletest/blob/main/LICENSE) |
| **Source** | <https://github.com/google/googletest> |
| **Fetched by** | `CMakeLists.txt` via `FetchContent_Declare` at configure time (guarded by `BUILD_TESTING`) |
| **Usage** | C++ unit and integration tests only — not included in release builds |

---

## RTI Connext DDS CMake Utilities

| Field | Value |
|-------|-------|
| **Component** | rticonnextdds-cmake-utils |
| **Version** | `main` branch (tip at configure time) |
| **License** | [Apache License 2.0](https://github.com/rticommunity/rticonnextdds-cmake-utils/blob/main/LICENSE) |
| **Source** | <https://github.com/rticommunity/rticonnextdds-cmake-utils> |
| **Fetched by** | `CMakeLists.txt` via `FetchContent_Declare` at configure time |
| **Usage** | CMake `find_package(RTIConnextDDS)` module and code generation macros |

---

## Python Packages

Python dependencies are declared in `requirements.txt` and installed
into the project virtual environment via `pip install -r requirements.txt`.
Versions are pinned in that file — refer to it for current pins.

| Package | License | Usage |
|---------|---------|-------|
| `rti.connext` | RTI Commercial (requires Connext Professional license) | RTI Connext DDS Python API — DDS entity creation, data publishing/subscribing |
| `nicegui` | [MIT](https://github.com/zauberzeug/nicegui/blob/main/LICENSE) | Web-based GUI framework (FastAPI + Vue/Quasar) |
| `pytest` | [MIT](https://github.com/pytest-dev/pytest/blob/main/LICENSE) | Python test framework |
| `black` | [MIT](https://github.com/psf/black/blob/main/LICENSE) | Python code formatter |
| `isort` | [MIT](https://github.com/PyCQA/isort/blob/main/LICENSE) | Python import sorter |
| `ruff` | [MIT](https://github.com/astral-sh/ruff/blob/main/LICENSE) | Python linter |
| `click` | [BSD-3-Clause](https://github.com/pallets/click/blob/main/LICENSE.txt) | CLI framework for `medtech` command |

When adding a new Python dependency:

1. Add it to `requirements.txt` with a version pin.
2. Add a row to this table with the package name, SPDX license, and usage.
3. Verify the license is compatible with the project (no GPL-only
   dependencies in application code; LGPL and permissive licenses are
   acceptable).

---

## Docker Images

These images are pulled at runtime for the Docker-based infrastructure
and observability stack. They are not fetched during CMake configure/build.

| Image | Version | License | Usage |
|-------|---------|---------|-------|
| `ubuntu` | 22.04 | Various (see [Ubuntu licensing](https://ubuntu.com/legal/open-source-licences)) | Base image for CDS, build, and runtime containers |
| `rticom/collector-service` | 7.6.0 | RTI Commercial (requires Connext Professional license) | DDS metrics/logs collection for observability pipeline |
| `prom/prometheus` | v2.51.0 | [Apache-2.0](https://github.com/prometheus/prometheus/blob/main/LICENSE) | Metrics scraping and storage |
| `grafana/loki` | 2.9.0 | [AGPL-3.0](https://github.com/grafana/loki/blob/main/LICENSE) | Log aggregation |
| `grafana/grafana` | 10.4.0 | [AGPL-3.0](https://github.com/grafana/grafana/blob/main/LICENSE) | Dashboards and visualization |
| `dockgraph/dockgraph` | latest | [BSL-1.1](https://github.com/dockgraph/dockgraph/blob/main/LICENSE) (converts to Apache-2.0 after 4 years) | Optional Docker topology visualization sidecar (`medtech launch --dockgraph`) |
