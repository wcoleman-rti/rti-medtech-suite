# syntax=docker/dockerfile:1
FROM ubuntu:24.04

ARG CONNEXT_VERSION=7.6.0
ARG CONNEXTDDS_ARCH=x64Linux4gcc8.5.0
ARG DEBIAN_FRONTEND=noninteractive

# Python runtime (no Qt dependencies — NiceGUI runs in the browser)
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Connext shared libraries from additional build context "connext"
COPY --from=connext lib/${CONNEXTDDS_ARCH}/ /opt/rti.com/rti_connext_dds-${CONNEXT_VERSION}/lib/${CONNEXTDDS_ARCH}/

ENV NDDSHOME=/opt/rti.com/rti_connext_dds-${CONNEXT_VERSION}
ENV CONNEXTDDS_DIR=${NDDSHOME}
ENV LD_LIBRARY_PATH="${NDDSHOME}/lib/${CONNEXTDDS_ARCH}"

EXPOSE 8080
ENV NICEGUI_STORAGE_PATH=/data/nicegui

# Create venv and install Python dependencies
RUN python3 -m venv /opt/medtech/.venv
ENV PATH="/opt/medtech/.venv/bin:${PATH}"

COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

WORKDIR /opt/medtech
