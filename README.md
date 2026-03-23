# Medtech Suite

A multi-domain DDS simulation platform built on RTI Connext Professional
7.6.0, demonstrating real-time surgical robotics, patient monitoring,
clinical decision support, and hospital-wide coordination on a layered
databus architecture.

## Platform Support

| Platform | Status |
|----------|--------|
| Linux x86-64 (`x64Linux4gcc8.5.0`) | Supported |
| Windows x64 | Planned (V3.0) |
| macOS ARM / x64 | Planned (V3.0) |
| QNX AArch64 | Planned (V3.0) |

## System Requirements

| Component | Version |
|-----------|---------|
| RTI Connext DDS Professional | 7.6.0 |
| GCC | 8.5+ |
| CMake | 3.16+ |
| Python | 3.10+ |
| Docker | Latest stable |
| Docker Compose | V2 |

## Compiler / Toolchain

- Language standard: **C++17**
- Target architecture: `x64Linux4gcc8.5.0`
- Python standard: 3.10+

## Quick Start

```bash
# 1. Source Connext environment
source $NDDSHOME/resource/scripts/rtisetenv_x64Linux4gcc8.5.0.bash

# 2. Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Build and install
cmake -B build -S .
cmake --build build
cmake --install build

# 4. Activate runtime environment
source install/setup.bash

# 5. Run tests
pytest tests/
```

## Project Structure

```text
medtech-suite/
├── interfaces/          # IDL types, QoS XML, domain library
│   ├── idl/             # IDL type definitions
│   ├── qos/             # QoS profile XML hierarchy
│   └── domains/         # Domain library XML
├── modules/             # Application modules
│   ├── surgical-procedure/
│   ├── hospital-dashboard/
│   ├── clinical-alerts/
│   └── shared/          # Shared utilities (medtech_gui, medtech_logging)
├── services/            # Infrastructure services (Routing, CDS, etc.)
├── resources/           # Shared GUI assets (fonts, images, stylesheets)
├── tests/               # Test suites
│   ├── integration/     # DDS integration tests
│   ├── performance/     # Benchmark harness and baselines
│   └── lint/            # Code and documentation linters
├── tools/               # Diagnostic and development tools
├── docker/              # Dockerfiles for base images
└── docs/agent/          # Planning and specification documents
```

## Documentation

See [docs/agent/](docs/agent/README.md) for detailed planning documentation
including architecture vision, behavioral specifications, and the phased
implementation plan.
