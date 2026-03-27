# Revision: Docker Build Workflow — In-Container Compilation

**Goal:** Eliminate the host-compiled-binary-mounted-into-container
anti-pattern that causes GLIBCXX/GLIBC ABI mismatches. All C++ binaries
and shared libraries must be compiled inside Docker using the same
toolchain and runtime libraries that the container will use at runtime.

**Trigger:** `robot-controller` crashes at startup in Docker with
`GLIBCXX_3.4.xx not found` when host-built binaries are volume-mounted
into `ubuntu:24.04`-based containers. The host GCC/libstdc++ version
differs from the container's, making the mounted binaries ABI-incompatible.

**Scope:** Docker workflow, Dockerfiles, `docker-compose.yml`, CI pipeline,
and planning document updates. No DDS architecture, topic, QoS, or
application logic changes. No new modules or features.

**Version impact:** Patch (V1.0.x) — infrastructure change only. All
existing tests must continue to pass.

---

## Root Cause

The current workflow builds C++ targets on the **host** via
`cmake --build build && cmake --install build`, then mounts the host
`./install/` tree into Docker containers using `x-install-volumes`:

```yaml
x-install-volumes: &install-volumes
  - ./install/lib:/opt/medtech/lib:ro
  - ./install/bin:/opt/medtech/bin:ro
```

This means `robot-controller` (compiled with the host's GCC and linked
against the host's libstdc++) runs against the container's Ubuntu 24.04
runtime libraries — a fundamental ABI mismatch when the host toolchain
differs from the container's.

**Additional finding:** `vision/technology.md` § Docker Base Images
documents `Ubuntu 22.04` as the pinned base, but the actual Dockerfiles
(`build-base.Dockerfile`, `runtime-cpp.Dockerfile`,
`runtime-python.Dockerfile`) use `ubuntu:24.04`. Only
`cloud-discovery-service.Dockerfile` uses `ubuntu:22.04`. This
inconsistency is corrected in Step R.3.

---

## Prerequisites

- All existing tests pass before starting any revision step
- `vision/technology.md` § Docker Integration (which already documents
  the correct multi-stage pattern) is the design reference
- No concurrent modifications to Docker or CI files

---

## Step R.1 — Multi-Stage Application Dockerfile

### Work

- Create `docker/medtech-app.Dockerfile` — a multi-stage Dockerfile that
  builds the entire project inside Docker and produces both C++ and
  Python runtime images:

  **Stage 1 (`builder`):**
  - `FROM medtech/build-base AS builder`
  - `COPY` the full project source into the builder
  - Run the CMake configure/build/install sequence:

    ```bash
    cmake -B /tmp/build -S /workspace \
        -DCMAKE_INSTALL_PREFIX=/opt/medtech \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_TESTING=OFF
    cmake --build /tmp/build --parallel "$(nproc)"
    cmake --install /tmp/build
    ```

  - The install tree at `/opt/medtech` now contains binaries compiled
    with the container's toolchain

  **Stage 2a (`cpp-runtime`):**
  - `FROM medtech/runtime-cpp AS cpp-runtime`
  - `COPY --from=builder /opt/medtech/bin/ /opt/medtech/bin/`
  - `COPY --from=builder /opt/medtech/lib/ /opt/medtech/lib/`
  - `COPY --from=builder /opt/medtech/share/ /opt/medtech/share/`
  - Set `PATH`, `LD_LIBRARY_PATH`, `NDDS_QOS_PROFILES`, `MEDTECH_CONFIG_DIR`

  **Stage 2b (`python-runtime`):**
  - `FROM medtech/runtime-python AS python-runtime`
  - `COPY --from=builder /opt/medtech/lib/python/ /opt/medtech/lib/python/`
  - `COPY --from=builder /opt/medtech/share/ /opt/medtech/share/`
  - Set `PYTHONPATH`, `NDDS_QOS_PROFILES`, `MEDTECH_CONFIG_DIR`

- The Dockerfile must parameterize `CONNEXT_VERSION` and
  `CONNEXTDDS_ARCH` via `ARG` (consistent with existing base images)
- No application code changes in this step

### Test Gate

- [ ] `docker build --target cpp-runtime -t medtech/app-cpp -f docker/medtech-app.Dockerfile .` succeeds
- [ ] `docker build --target python-runtime` for
      `medtech-app.Dockerfile` succeeds
- [ ] `docker run --rm medtech/app-cpp ldd /opt/medtech/bin/robot-controller`
      shows all libraries resolved (no "not found")
- [ ] `robot-controller` smoke invocation inside `app-cpp` does not
      crash with GLIBCXX errors
- [ ] `docker run --rm medtech/app-python python3 -c "import surgery; print('OK')"` succeeds
- [ ] All existing host-side tests pass (no regression)

---

## Step R.2 — Update docker-compose.yml

### Work

- **Replace `x-install-volumes`** with a new `x-config-volumes` anchor
  that mounts only configuration files and the RTI license — no compiled
  binaries or shared libraries:

  ```yaml
  x-config-volumes: &config-volumes
    - ./interfaces/qos:/opt/medtech/share/qos:ro
    - ./interfaces/domains:/opt/medtech/share/domains:ro
    - ./install/share/participants:/opt/medtech/share/participants:ro
    - ./install/share/resources:/opt/medtech/share/resources:ro
    - ${RTI_LICENSE_FILE:-./rti_license.dat}:/opt/rti.com/rti_connext_dds-7.6.0/rti_license.dat:ro
  ```

- **Update C++ service definitions** (`robot-controller-or1`,
  `robot-controller-or3`) to:
  - Use `image: medtech/app-cpp` (the multi-stage built image)
  - Use `volumes: *config-volumes` (no binary mounts)
  - Remove the `LD_LIBRARY_PATH` override that patched in `/opt/medtech/lib`
    (binaries are now baked into the image with correct RPATH/runpath)

- **Update Python service definitions** (`procedure-context-*`,
  `vitals-sim-*`, `camera-sim-*`, `device-telemetry-*`,
  `digital-twin-*`) to:
  - Use `image: medtech/app-python` (the multi-stage built image)
  - Use `volumes: *config-volumes` (no binary/Python-package mounts)

- **Add build entries** for the new multi-stage images in the
  `build`-profile section:

  ```yaml
  app-cpp:
    image: medtech/app-cpp
    build:
      context: .
      dockerfile: docker/medtech-app.Dockerfile
      target: cpp-runtime
      additional_contexts:
        connext: "${NDDSHOME:-/opt/rti.com/rti_connext_dds-7.6.0}"
      args:
        <<: *build-args
    profiles: ["build"]

  app-python:
    image: medtech/app-python
    build:
      context: .
      dockerfile: docker/medtech-app.Dockerfile
      target: python-runtime
      additional_contexts:
        connext: "${NDDSHOME:-/opt/rti.com/rti_connext_dds-7.6.0}"
      args:
        <<: *build-args
    profiles: ["build"]
  ```

- **Preserve the old `x-install-volumes` temporarily** as
  `x-dev-volumes` with a YAML comment: `# DEV ONLY — host-mount for
  local iteration; never use for CI or integration tests`. This will be
  removed in Step R.6 if no longer needed.

### Test Gate

- [ ] `docker compose --profile build build` builds all images
      (base + app) without errors
- [ ] `docker compose up -d` starts the full suite
- [ ] `robot-controller-or1` container starts without GLIBCXX errors
      (check with `docker logs robot-controller-or1`)
- [ ] `procedure-context-or1` container starts and publishes data
- [ ] All `@e2e` / `@integration` Docker-based tests pass
- [ ] All existing host-side tests pass (no regression)

---

## Step R.3 — Reconcile Docker Base Image Versions in Vision Doc

### Work

Update `vision/technology.md` to reconcile the documented vs actual
Docker base image versions:

- **§ Docker Base Images table:** Change `Ubuntu 22.04` to match the
  actual base image version used across all Dockerfiles. All runtime
  and build images must use the **same** Ubuntu LTS release. If the
  project standardizes on `ubuntu:24.04` (as the current Dockerfiles
  suggest), update the table accordingly. If `ubuntu:22.04` is
  preferred, update the Dockerfiles instead — but all must agree.
- **§ Platform Support table:** Update the `Docker base images` row
  to match the chosen version.
- **§ Docker Base Images text:** Add: *"All Dockerfiles must use the
  same Ubuntu LTS release to guarantee ABI consistency across base
  images. Mixing Ubuntu versions (e.g., 22.04 build-base with 24.04
  runtime) risks glibc/libstdc++ mismatches."*
- **`cloud-discovery-service.Dockerfile`:** If it currently uses a
  different Ubuntu version than the rest, update it to match.

### Test Gate

- [ ] `grep -r "FROM ubuntu:" docker/` returns the same version for
      every Dockerfile
- [ ] `vision/technology.md` § Docker Base Images table matches the
      actual Dockerfiles
- [ ] `docker compose --profile build build` succeeds after any
      Dockerfile base image changes
- [ ] All existing tests pass (no regression)

---

## Step R.4 — Add Docker Build Prohibition to Vision and Workflow

### Work

Update planning documents to add guardrails that prevent regression:

**`vision/technology.md` § Docker Integration (after the multi-stage
build example):**

Add a new subsection **"Container Build Integrity Rule"**:

> C++ binaries and project shared libraries must be compiled inside the
> Docker build stage using the container's toolchain. Mounting
> host-compiled binaries into containers
> (`-v ./install/bin:/opt/medtech/bin`) is prohibited for CI,
> integration tests, and deployment.
>
> The host-mount pattern is permitted **only** for:
>
> - XML configuration files (QoS, domain, participant XML)
> - Python source files during local development iteration
> - The RTI license file
>
> Rationale: the host toolchain's GCC/libstdc++ version may differ
> from the container's runtime libraries, causing ABI mismatches
> (GLIBCXX_x.y.z not found, segmentation faults from vtable
> incompatibility). Building inside the container eliminates this
> class of error entirely.

**`vision/technology.md` § Docker Integration:**

Add a new subsection **"Development Inner Loop"** documenting how to
compile inside the build-base container for fast iteration:

> For development iteration without rebuilding the full Docker image,
> compile inside the build-base container:
>
> ```bash
> docker run --rm \
>   -v "$(pwd)":/workspace \
>   -w /workspace \
>   medtech/build-base \
>   bash -c "cmake -B /tmp/build -S . \
>     -DCMAKE_INSTALL_PREFIX=/workspace/install && \
>     cmake --build /tmp/build -j && \
>     cmake --install /tmp/build"
> ```
>
> This uses the container's toolchain while writing output to the host
> filesystem. The resulting `install/` tree is ABI-compatible with the
> runtime containers.

**`workflow.md` § Section 4 (Strict Boundaries) — Prohibited Actions
table:**

Add a new row:

| Prohibited action | Rationale |
|-------------------|----------|
| Mount host-compiled C++ binaries or shared libraries into Docker containers | Host toolchain ABI may differ from container runtime libraries, causing GLIBCXX/GLIBC mismatches. Compile inside the container. |

**`workflow.md` § Section 7 (Quality Gates) — Gates table:**

Add a new row:

| Gate             | Check    |
|------------------|----------|
| **Docker build** | `docker compose --profile build build` succeeds. Multi-stage application images build without errors. `robot-controller` runs inside `cpp-runtime` container without library version mismatches. |

### Test Gate

- [ ] `vision/technology.md` contains "Container Build Integrity Rule"
      subsection
- [ ] `vision/technology.md` contains "Development Inner Loop"
      subsection
- [ ] `workflow.md` § Section 4 table contains the host-binary-mount
      prohibition row
- [ ] `workflow.md` § Section 7 table contains the Docker build gate row
- [ ] All docs pass markdownlint
- [ ] No structural or section-ordering changes to either document beyond
      the specified additions

---

## Step R.5 — Update CI Pipeline

### Work

Update `scripts/ci.sh` to add a Docker build gate:

- **After Gate 1 (Build + Install),** add a new gate:
  **Gate 1b: Docker multi-stage build**

  ```bash
  gate "Docker multi-stage build"
  docker compose --profile build build 2>&1 | tail -5 \
      || fail "docker compose build failed"
  ```

- **After the existing gates,** add a container smoke-test gate:
  **Gate N: Container runtime smoke test**

  ```bash
  gate "Container runtime smoke test"
  # Verify C++ binary runs without GLIBCXX errors
  docker run --rm medtech/app-cpp \
      /opt/medtech/bin/robot-controller --version 2>&1 \
      || fail "robot-controller failed in container"
  # Verify Python imports resolve
  docker run --rm medtech/app-python \
      python3 -c "import surgery; import monitoring; print('OK')" 2>&1 \
      || fail "Python type imports failed in container"
  ```

- The existing Gate 1 (host build + install) remains — it continues
  to serve local development and host-native test execution. The new
  Docker gates run in addition, not as a replacement.

### Test Gate

- [ ] `bash scripts/ci.sh` runs all gates including the new Docker
      gates (requires Docker daemon)
- [ ] The Docker build gate fails if the multi-stage Dockerfile has
      a compilation error (verified by introducing a deliberate break
      and confirming gate failure, then reverting)
- [ ] All existing CI gates still pass
- [ ] All existing tests pass (no regression)

---

## Step R.6 — Update Implementation Docs and Clean Up

### Work

**`implementation/README.md`:**

- Add this revision file to the **Phase Files** table under V1.0.0:

  | File | Phase | Depends On | Key Deliverables |
  |------|-------|------------|------------------|
  | `revision-docker-build-workflow.md` | Docker Build Workflow | Phase 1 | Multi-stage Dockerfile, in-container compilation, compose update, CI Docker gates, doc guardrails |

- In the **Test Policy** section, add a clarification:

  > **Docker test execution:** Integration and E2E tests that run in
  > Docker must use images built via the multi-stage Dockerfile
  > (`docker/medtech-app.Dockerfile`), not host-mounted install trees.
  > The `x-dev-volumes` pattern in `docker-compose.yml` is a local
  > development convenience and must not be used in CI or as the basis
  > for test results.

**`spec/common-behaviors.md`:**

Add a new scenario under a **"Container Build Integrity"** section:

> ### Scenario: C++ binary built inside Docker runs without ABI errors `@e2e`
>
> **Given** the project is built inside a Docker multi-stage build
> using `docker/medtech-app.Dockerfile`
> **When** `robot-controller` starts in the `cpp-runtime` container
> **Then** it does not encounter GLIBCXX, GLIBC, or other shared
> library resolution errors
> **And** it successfully creates a DDS DomainParticipant
>
> ### Scenario: Python modules import successfully in Docker `@e2e`
>
> **Given** the project is built inside a Docker multi-stage build
> using `docker/medtech-app.Dockerfile`
> **When** the `python-runtime` container executes
> `import surgery; import monitoring`
> **Then** all generated type modules import without errors

**Clean up:**

- Remove the `x-dev-volumes` anchor from `docker-compose.yml` if no
  service still references it. If it is still used by a development
  override file, keep it with the cautionary comment added in Step R.2.
- Verify that no documentation references the old `x-install-volumes`
  pattern for production/CI use.

### Test Gate

- [ ] `implementation/README.md` phase table includes this revision
- [ ] `implementation/README.md` test policy includes Docker test
      execution clarification
- [ ] `spec/common-behaviors.md` contains both new container build
      scenarios
- [ ] The new `@e2e` scenarios have corresponding test implementations
- [ ] No stale references to `x-install-volumes` remain in docs
- [ ] All docs pass markdownlint
- [ ] Full test suite passes (no regression)

---

## Completion Criteria

All steps R.1–R.6 are complete when:

- [ ] Multi-stage Dockerfile builds C++ and Python runtime images
      without errors
- [ ] `robot-controller` runs in Docker without GLIBCXX/GLIBC errors
- [ ] `docker-compose.yml` no longer mounts host-compiled binaries
      for any non-dev service
- [ ] All Docker base images use the same Ubuntu LTS version
- [ ] `vision/technology.md` documents the container build integrity
      rule and development inner loop
- [ ] `workflow.md` prohibits host-binary mounting and includes a
      Docker build quality gate
- [ ] `scripts/ci.sh` includes Docker build and container smoke-test
      gates
- [ ] `spec/common-behaviors.md` includes testable E2E scenarios for
      container build integrity
- [ ] Full test suite (host + Docker) passes
- [ ] No open incidents related to this revision
