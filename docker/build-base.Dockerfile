FROM ubuntu:22.04

ARG CONNEXT_VERSION=7.6.0
ARG CONNEXTDDS_ARCH=x64Linux4gcc8.5.0
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        git \
        python3 \
        python3-pip \
        python3-venv \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy full Connext installation from additional build context "connext"
# Build with: --build-context connext=$NDDSHOME
COPY --from=connext . /opt/rti.com/rti_connext_dds-${CONNEXT_VERSION}/

ENV NDDSHOME=/opt/rti.com/rti_connext_dds-${CONNEXT_VERSION}
ENV CONNEXTDDS_ARCH=${CONNEXTDDS_ARCH}
ENV PATH="${NDDSHOME}/bin:${PATH}"
ENV LD_LIBRARY_PATH="${NDDSHOME}/lib/${CONNEXTDDS_ARCH}"

WORKDIR /workspace
