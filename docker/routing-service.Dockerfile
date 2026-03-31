FROM ubuntu:24.04

ARG CONNEXT_VERSION=7.6.0
ARG CONNEXTDDS_ARCH=x64Linux4gcc8.5.0
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        netcat-openbsd \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy Routing Service binary from additional build context "connext"
COPY --from=connext \
    resource/app/bin/${CONNEXTDDS_ARCH}/rtiroutingserviceapp \
    /opt/rti.com/rti_connext_dds-${CONNEXT_VERSION}/bin/rtiroutingserviceapp

# Copy required shared libraries (same set as CDS minus CDS-specific lib)
COPY --from=connext \
    lib/${CONNEXTDDS_ARCH}/librtiroutingservice.so \
    lib/${CONNEXTDDS_ARCH}/librtidlc.so \
    lib/${CONNEXTDDS_ARCH}/librticonnextmsgc.so \
    lib/${CONNEXTDDS_ARCH}/libnddsmetp.so \
    lib/${CONNEXTDDS_ARCH}/librtiapputilsc.so \
    lib/${CONNEXTDDS_ARCH}/librtixml2.so \
    lib/${CONNEXTDDS_ARCH}/libnddsc.so \
    lib/${CONNEXTDDS_ARCH}/libnddscore.so \
    /opt/rti.com/rti_connext_dds-${CONNEXT_VERSION}/lib/${CONNEXTDDS_ARCH}/

ENV NDDSHOME=/opt/rti.com/rti_connext_dds-${CONNEXT_VERSION}
ENV LD_LIBRARY_PATH="${NDDSHOME}/lib/${CONNEXTDDS_ARCH}"
ENV PATH="${NDDSHOME}/bin:${PATH}"

WORKDIR /home/rtiuser

ENTRYPOINT ["rtiroutingserviceapp"]
