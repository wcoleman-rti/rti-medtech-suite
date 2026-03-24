# RTI Admin Console — Connection Guide

RTI Admin Console is a GUI application for live inspection of DDS
systems: participants, topics, endpoints, QoS policies, and data
visualization.

## Connecting to the Medtech Suite

### Via Cloud Discovery Service (Recommended)

1. Start the Docker Compose stack:

   ```bash
   docker compose up -d
   ```

2. Open RTI Admin Console on the host machine.

3. Add a discovery peer pointing to the Cloud Discovery Service
   container's forwarded port:

   ```text
   7@builtin.udpv4://localhost:7400
   ```

4. Admin Console discovers all participants across all domains that
   Cloud Discovery Service serves (Procedure and Hospital).

### Via Docker Host Networking

1. Start the stack: `docker compose up -d`

2. Inspect Docker network IPs:

   ```bash
   docker network inspect surgical-net
   docker network inspect hospital-net
   ```

3. Configure Admin Console's initial peers to the container IPs on
   the Docker bridge networks.

## Common Tasks

| Task | Steps |
|------|-------|
| Check endpoint matching | Join domain → Subscription Matched tab |
| Inspect topic QoS | Right-click topic → View DataWriter/DataReader QoS |
| View live data | Right-click topic → Subscribe → monitor samples |
| Check QoS compatibility | Endpoints tab → look for incompatible QoS status |
| System topology | Domain view → inspect all discovered participants |
