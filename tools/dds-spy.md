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

When running inside Docker containers, ensure `rtiddsspy` is
available in the container (it ships with Connext runtime):

```bash
docker exec -it <container> bash -c "source /app/install/setup.bash && rtiddsspy -domainId 10 -printSample"
```

## Notes

- Use `Ctrl+C` to stop monitoring
- Add `-noMonitoring` to suppress Monitoring Library 2.0 telemetry
  from the spy's own participant
- In Docker environments, run from within a container on the target
  network for direct discovery, or use Cloud Discovery Service for
  cross-network access
