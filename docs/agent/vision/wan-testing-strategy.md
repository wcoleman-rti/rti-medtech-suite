# WAN Testing Strategy

This document defines the validation strategy for all WAN-spanning capabilities
introduced in V3.0.0. It is the authoritative reference for how WAN behavior —
packet loss, latency, bandwidth, and NAT traversal — is tested across all
implementation phases that touch `UDPv4_WAN`, Cloud Discovery Service (CDS), and
the Routing Service WAN bridge.

---

## Scope

This strategy applies to every V3.0.0 phase that involves:

- RTI Real-Time WAN Transport (`UDPv4_WAN`)
- Cloud Discovery Service cross-site discovery
- Routing Service WAN bridge between facilities
- Connext Security Plugins over WAN connections
- ClinicalAlerts High Availability (primary/backup engine pair across sites)
- Multi-segment deployment with CDS multi-initial-peer HA

---

## Why Not Containernet

Containernet (Docker + Mininet) was evaluated and **explicitly rejected** as the
primary WAN test mechanism for this project. The reason is fundamental: Containernet
operates on a **flat L2 model** (Linux bridges, no L3 routing between subnets). The
`UDPv4_WAN` + CDS NAT traversal path — which is the core value of RTI's WAN
transport layer — requires:

- Separate private subnets per site
- Explicit L3 routing between them
- Real SNAT/MASQUERADE that translates source addresses before reaching CDS

A flat L2 emulation will never produce NAT-translated source addresses, so CDS
cannot exercise its locator-resolution path. The topology would pass because it
bypasses the problem entirely, not because the problem is solved.

The right answer — privileged router containers with `iptables` + `tc` — already
delivers everything Containernet offers (impairment injection) plus NAT traversal,
in a standard Docker Compose model. Adding Containernet would add complexity and a
model mismatch with no benefit.

---

## Three-Tier Validation Architecture

WAN tests are organized in three tiers with different run frequencies and infrastructure
requirements.

| Tier | Name | Mechanism | When Runs | What It Validates |
|------|------|-----------|-----------|-------------------|
| **A** | Impairment CI | Router containers + `tc netem` (no NAT) | Every commit / nightly | Loss/latency/jitter, RS reconnection, QoS degradation, CDS HA failover |
| **B** | NAT Integration | Router containers + `iptables MASQUERADE` + `tc netem` | Nightly / pre-milestone | CDS NAT traversal, public/private locator correctness, cone-NAT P2P path |
| **C** | Pre-release qualification | Real routed infrastructure or public cloud VMs | Pre-release / demo prep | MTU path behavior, firewall ACLs, WAN brownout recovery, real NAT timeout |

**Tier A** is a required gate for every V3.0 phase. **Tier B** is a required gate
before each V3.0 milestone is cut. **Tier C** is advisory during development and
required before a public demo or external stakeholder review.

---

## Docker WAN Topology

All Tier A and Tier B tests use the following topology, implemented as a Docker
Compose service set.

### Network layout

```
┌────────────────────────────┐       ┌────────────────────────────┐
│  siteA_lan  10.10.1.0/24  │       │  siteB_lan  10.20.1.0/24  │
│                            │       │                            │
│  appA / rsA                │       │  appB / rsB               │
│  default gw = natA         │       │  default gw = natB        │
└────────────┬───────────────┘       └───────────┬────────────────┘
             │                                   │
        ┌────┴────┐     wan_net              ┌───┴─────┐
        │  natA   ├──── 172.30.0.0/24 ───── │  natB   │
        └─────────┘          │               └─────────┘
                         ┌───┴────┐
                         │  cds   │  (public, well-known addr on wan_net)
                         └────────┘
                         (+ optional impair container for centralized shaping)
```

### Container roles

| Container | Networks | Role |
|-----------|----------|------|
| `appA` / `rsA` | `siteA_lan` only | Application / Routing Service gateway at Site A |
| `appB` / `rsB` | `siteB_lan` only | Application / Routing Service gateway at Site B |
| `natA` | `siteA_lan` + `wan_net` | Privileged router — SNAT Site A → WAN, `tc` impairment on WAN egress |
| `natB` | `siteB_lan` + `wan_net` | Privileged router — SNAT Site B → WAN, `tc` impairment on WAN egress |
| `cds` | `wan_net` only | Cloud Discovery Service — stable public IP/port, no NAT required |
| `impair` *(optional)* | `wan_net` | Middle router for centralized/asymmetric WAN shaping |

### Linux primitives used

**NAT router containers (`natA`, `natB`)** — must run privileged:

```bash
# Enable IP forwarding
sysctl -w net.ipv4.ip_forward=1

# SNAT outbound WAN traffic (cone NAT — destination-independent mapping)
iptables -t nat -A POSTROUTING -o eth-wan -j MASQUERADE

# Static DNAT for any well-known service port (if needed)
iptables -t nat -A PREROUTING -i eth-wan -p udp --dport <port> -j DNAT \
  --to-destination <private-ip>:<port>

# WAN impairment on egress (Tier A: loss/latency; Tier B: combined with NAT above)
tc qdisc add dev eth-wan root netem delay 80ms 20ms loss 1%

# Bandwidth cap (optional — use tbf or htb)
tc qdisc add dev eth-wan root tbf rate 10mbit burst 32kbit latency 200ms
```

**Why `MASQUERADE` and not symmetric NAT:** RTI's CDS NAT traversal documentation
explicitly states that direct peer-to-peer `UDPv4_WAN` communication between
participants behind NATs works only with **cone NATs**. Linux `MASQUERADE` produces
cone-like NAPT behavior (destination-independent UDP mappings for outbound
connections), which satisfies the RTI-documented requirement. Do not use `nftables`
rules or `conntrack` constraints that would produce symmetric NAT behavior — that
would cause justified test failures and is not representative of the supported
deployment model.

---

## RTI Configuration Requirements

These settings apply to any participant or service that must communicate over the
simulated WAN path.

| Setting | Required Value | Notes |
|---------|---------------|-------|
| `transport_builtin.mask` | `UDPv4_WAN` | On all WAN-side participants (RS WAN endpoints) |
| `initial_peers` | `rtps@udpv4_wan://<cds-wan-ip>:<port>` | Point to CDS public address on `wan_net` |
| `accept_unknown_peers` | `true` | RTI default — do not override; required for CDS-assisted P2P |
| `dds.transport.UDPv4_WAN.builtin.comm_ports` | Single-port mapping recommended | Simplifies NAT rules, firewall mapping, and packet capture in CI |
| CDS `receive_port` | Stable port on `wan_net` | CDS must be at a well-known address — no NAT needed if CDS is directly on `wan_net` |

**Local application participants** (on `siteA_lan` / `siteB_lan`) do **not** use
`UDPv4_WAN`. They use LAN transport and communicate only with the Routing Service
gateway on their local segment. The RS gateway participant bridges to the WAN domain
using `UDPv4_WAN`. This separation is the "LAN-local DDS + WAN bridge/gateway"
pattern from the V3.0 architecture.

**Do not hardcode public addresses in application code.** The public WAN address of
any participant behind NAT is resolved dynamically by CDS. Only CDS's own address
needs to be a known constant (in `initial_peers`).

---

## NAT Traversal Validation Checklist

Every Tier B test run must verify the following five conditions. They confirm that
NAT traversal was actually exercised and not accidentally bypassed by flat Docker
bridge reachability.

1. **CDS sees translated source addresses.** `tcpdump` or packet capture on the
   `cds` container must show incoming packets with `natA`/`natB` WAN-side IPs as
   the source — never the private `10.10.x.x` / `10.20.x.x` site addresses.

2. **Source translation is confirmed on NAT egress.** `tcpdump` on the WAN interface
   of `natA` and `natB` must show translated source IPs on outbound packets.

3. **Post-discovery data flow is peer-to-peer.** After CDS resolves and forwards
   participant locators, data traffic must flow **directly** between the translated
   WAN addresses of `rsA` and `rsB` — not relayed through CDS. CDS is not a data
   relay.

4. **Negative test passes.** Block the return path through one NAT (drop `FORWARD`
   on `natB` WAN ingress) and verify that peer-to-peer communication fails. This
   proves the NAT is a real constraint and not bypassed by Docker's default bridge
   reachability.

5. **CDS locator resolution logs are clean.** Run CDS with `-verbosity 5` (ALL) and
   confirm locator resolution messages show the expected public address derivation
   with no error or warning entries.

---

## Impairment Profiles

Standard named profiles used across Tier A and Tier B test cases. These are applied
via `tc netem` on the WAN-facing interface of `natA` and/or `natB`.

| Profile Name | `tc netem` Parameters | Purpose |
|---|---|---|
| `baseline` | none | Verify nominal WAN connectivity |
| `lan-quality` | `delay 5ms loss 0.01%` | Near-LAN reference for latency comparison |
| `good-wan` | `delay 50ms 10ms loss 0.1%` | Typical low-loss intercontinental WAN |
| `degraded-wan` | `delay 120ms 30ms loss 2%` | Degraded link — tests reliability recovery |
| `lossy` | `delay 80ms loss 5% corrupt 0.1%` | High-loss — exercises RELIABLE QoS retransmission |
| `burst-loss` | `delay 80ms loss 10% 25%` | Burstable loss (Gilbert model) — stresses durable endpoints |
| `brownout` | `delay 200ms 80ms loss 15%` | Severe degradation — exercises deadline/liveliness timeouts |
| `blackhole` | `loss 100%` | Full route outage — validates reconnection / CDS re-registration |

Apply a profile by name in test setup via `docker exec natA tc qdisc change ...`.
The `blackhole` profile should be applied for a bounded window and then removed to
verify recovery, not left on for the duration of a test.

---

## Observability During WAN Tests

Pair impairment injection (Linux `tc`) with RTI tooling for assertions and diagnosis.

| Observation Need | Tool |
|-----------------|------|
| Route state and sample counts | RTI Admin Console → Routing Service view |
| Throughput / latency per topic | Grafana Data Flow and Sample Latency dashboards |
| Discovery timeline and locator visibility | Admin Console → participant discovery view |
| CDS locator resolution behavior | CDS `-verbosity 5` log output |
| WAN packet capture and NAT translation confirmation | `tcpdump` on `natA`/`natB` WAN interfaces |
| Routing Service reconnection events | RTI distributed logging + `medtech-diag` |

The pairing principle: **inject impairments with Linux, observe DDS behavior with
RTI tooling.** Never infer DDS correctness from network-level packet captures alone.

---

## Phase Gate Mapping

| V3.0 Phase Scope | Tier A Required | Tier B Required |
|-----------------|-----------------|-----------------|
| Routing Service WAN bridge (basic connectivity) | ✓ | ✓ |
| CDS multi-initial-peer HA | ✓ | ✓ |
| WAN reliability under loss / reconnection | ✓ | ✓ |
| Cross-facility domain bridging (partition + topic routing) | ✓ | — |
| Security Plugins over WAN | ✓ | ✓ |
| Cloud Command Center (3rd databus layer) | ✓ | ✓ |

Tier B gates (marked ✓) must pass before the corresponding V3.0 milestone is cut.
Tier A gates are required at every phase step, the same as other integration tests
in the project.
