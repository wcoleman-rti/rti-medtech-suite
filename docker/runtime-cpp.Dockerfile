FROM ubuntu:22.04

ARG CONNEXT_VERSION=7.6.0
ARG CONNEXT_ARCH=x64Linux4gcc8.5.0
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy only Connext shared libraries from additional build context "connext"
COPY --from=connext lib/${CONNEXT_ARCH}/ /opt/rti.com/rti_connext_dds-${CONNEXT_VERSION}/lib/${CONNEXT_ARCH}/

ENV NDDSHOME=/opt/rti.com/rti_connext_dds-${CONNEXT_VERSION}
ENV LD_LIBRARY_PATH="${NDDSHOME}/lib/${CONNEXT_ARCH}"

WORKDIR /opt/medtech
