# RTI DDS Spy (`rtiddsspy`) — Usage Guide

`rtiddsspy` is a CLI tool that subscribes to all topics on a domain
and prints received samples to stdout. Lightweight alternative to
Admin Console for quick checks.

## Prerequisites

Source the project environment first:

```bash
source install/setup.bash
```

## Usage Examples

### Spy on the Procedure domain (all topics)

```bash
rtiddsspy -domainId 10 -printSample
```

### Spy on the Hospital domain

```bash
rtiddsspy -domainId 11 -printSample
```

### Spy with a specific partition

```bash
rtiddsspy -domainId 10 -partition "room/OR-3/*" -printSample
```

### Monitor a specific topic

```bash
rtiddsspy -domainId 10 -topic PatientVitals -printSample
```

### Watch for a limited duration

```bash
rtiddsspy -domainId 10 -printSample -maxWait 10
```

## Docker Usage

When the Docker Compose stack is running, `rtiddsspy` can connect
via Cloud Discovery Service:

```bash
# From the host, discover through CDS
rtiddsspy -domainId 10 -printSample -peer "rtps@udpv4://localhost:7400"

# From inside a container on surgical-net
docker exec -it vitals-sim-or1 bash -c "rtiddsspy -domainId 10 -printSample"
```

### Surgical Procedure Module Topics (Domain 10)

```bash
# Watch PatientVitals (1 Hz from each OR)
rtiddsspy -domainId 10 -topic PatientVitals -printSample

# Watch RobotState (100 Hz from each OR)
rtiddsspy -domainId 10 -topic RobotState -printSample

# Watch CameraFrame (30 Hz)
rtiddsspy -domainId 10 -topic CameraFrame -printSample

# Watch DeviceTelemetry (write-on-change)
rtiddsspy -domainId 10 -topic DeviceTelemetry -printSample

# Watch ProcedureContext and ProcedureStatus (TRANSIENT_LOCAL)
rtiddsspy -domainId 10 -topic ProcedureContext -printSample
rtiddsspy -domainId 10 -topic ProcedureStatus -printSample
```

## Notes

- Use `Ctrl+C` to stop monitoring
- Add `-noMonitoring` to suppress Monitoring Library 2.0 telemetry
  from the spy's own participant
- In Docker environments, run from within a container on the target
  network for direct discovery, or use Cloud Discovery Service for
  cross-network access
