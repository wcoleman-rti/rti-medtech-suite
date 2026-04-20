# Routing Service — official RTI image from Docker Hub.
# https://hub.docker.com/r/rticom/routing-service
FROM rticom/routing-service:7.6.0

# Workaround: the base image does not add the Connext target lib directory
# to the runtime library path, so Monitoring Library 2.0 (librtimonitoring2.so)
# cannot be found.  See:
# https://hub.docker.com/r/rticom/collector-service#rti-infrastructure-services-cannot-emit-telemetry-data
ENV LD_LIBRARY_PATH=/opt/rti.com/rti_connext_dds-7.6.0/lib/x64Linux4gcc8.5.0
