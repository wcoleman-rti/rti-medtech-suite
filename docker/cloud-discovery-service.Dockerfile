FROM ubuntu:22.04

ARG CONNEXT_VERSION=7.6.0
ARG CONNEXT_ARCH=x64Linux4gcc8.5.0
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        netcat-openbsd \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy CDS binary from additional build context "connext"
COPY --from=connext \
    resource/app/bin/${CONNEXT_ARCH}/rticlouddiscoveryserviceapp \
    /opt/rti.com/rti_connext_dds-${CONNEXT_VERSION}/bin/rticlouddiscoveryserviceapp

# Copy required shared libraries
COPY --from=connext lib/${CONNEXT_ARCH}/librticlouddiscoveryservice.so \
    lib/${CONNEXT_ARCH}/librtiroutingservice.so \
    lib/${CONNEXT_ARCH}/librtidlc.so \
    lib/${CONNEXT_ARCH}/librticonnextmsgc.so \
    lib/${CONNEXT_ARCH}/libnddsmetp.so \
    lib/${CONNEXT_ARCH}/librtiapputilsc.so \
    lib/${CONNEXT_ARCH}/librtixml2.so \
    lib/${CONNEXT_ARCH}/libnddsc.so \
    lib/${CONNEXT_ARCH}/libnddscore.so \
    /opt/rti.com/rti_connext_dds-${CONNEXT_VERSION}/lib/${CONNEXT_ARCH}/

ENV NDDSHOME=/opt/rti.com/rti_connext_dds-${CONNEXT_VERSION}
ENV LD_LIBRARY_PATH="${NDDSHOME}/lib/${CONNEXT_ARCH}"
ENV PATH="${NDDSHOME}/bin:${PATH}"

WORKDIR /home/rtiuser

ENTRYPOINT ["rticlouddiscoveryserviceapp"]
