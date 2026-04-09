# Multi-stage Dockerfile: builds the entire medtech-suite project inside
# Docker and produces both C++ and Python runtime images.
#
# Usage:
#   docker build --target cpp-runtime -t medtech/app-cpp \
#       -f docker/medtech-app.Dockerfile .
#   docker build --target python-runtime -t medtech/app-python \
#       -f docker/medtech-app.Dockerfile .

# ── Stage 1: Builder ──────────────────────────────────────────────
FROM medtech/build-base AS builder

ARG CONNEXT_VERSION=7.6.0
ARG CONNEXTDDS_ARCH=x64Linux4gcc8.5.0

COPY . /workspace

RUN cmake -B /tmp/build -S /workspace \
        -DCMAKE_INSTALL_PREFIX=/opt/medtech \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_TESTING=OFF \
    && cmake --build /tmp/build --parallel "$(nproc)" \
    && cmake --install /tmp/build

# ── Stage 2a: C++ Runtime ────────────────────────────────────────
FROM medtech/runtime-cpp AS cpp-runtime

COPY --from=builder /opt/medtech/bin/ /opt/medtech/bin/
COPY --from=builder /opt/medtech/lib/ /opt/medtech/lib/
COPY --from=builder /opt/medtech/share/ /opt/medtech/share/

ENV PATH="/opt/medtech/bin:${PATH}"
ENV LD_LIBRARY_PATH="/opt/medtech/lib:${LD_LIBRARY_PATH}"
ENV NDDS_QOS_PROFILES="/opt/medtech/share/qos/Snippets.xml;/opt/medtech/share/qos/Patterns.xml;/opt/medtech/share/qos/Topics.xml;/opt/medtech/share/qos/Participants.xml;/opt/medtech/share/domains/Domains.xml;/opt/medtech/share/participants/SurgicalParticipants.xml"
ENV MEDTECH_CONFIG_DIR="/opt/medtech/etc"

WORKDIR /opt/medtech

# ── Stage 2b: Python Runtime ─────────────────────────────────────
FROM medtech/runtime-python AS python-runtime

COPY --from=builder /opt/medtech/lib/python/ /opt/medtech/lib/python/
COPY --from=builder /opt/medtech/share/ /opt/medtech/share/

ENV PYTHONPATH="/opt/medtech/lib/python/site-packages"
ENV NDDS_QOS_PROFILES="/opt/medtech/share/qos/Snippets.xml;/opt/medtech/share/qos/Patterns.xml;/opt/medtech/share/qos/Topics.xml;/opt/medtech/share/qos/Participants.xml;/opt/medtech/share/domains/Domains.xml;/opt/medtech/share/participants/SurgicalParticipants.xml"
ENV MEDTECH_CONFIG_DIR="/opt/medtech/etc"

# Health check: liveness probe via the FastAPI /health endpoint
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Default: launch the unified NiceGUI application (all GUI modules)
CMD ["python", "-m", "medtech.gui.app"]

WORKDIR /opt/medtech
