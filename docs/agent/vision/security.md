# Security Architecture

Security for the medtech suite is built on RTI Connext Security Plugins and is designed in from the start, even though implementation is deferred to V2.0.0. The architecture, governance posture, and identity model are defined here so that all modules are compatible with the security layer when it is enabled.

Security design is scoped and documented here **before** implementation begins. No security implementation proceeds without a corresponding entry in this document.

---

## Principles

- **Default deny.** All domains default to denying unauthenticated participants and unauthorized topic access unless explicitly permitted.
- **Least privilege.** Each participant is granted only the permissions it needs — no more. Dashboards read; controllers write.
- **Defense in depth.** Domain-level governance, topic-level protection, and participant-level identity are independent layers.
- **Separation of criticality.** Domain tags already isolate data by risk class. Security governance reinforces this by applying stronger protection requirements to higher-criticality domain tags.
- **Configuration-driven.** All security artifacts (governance, permissions, certificates) are referenced from participant QoS XML via `dds.sec.*` properties — no programmatic security API calls.

---

## STRIDE Threat Model

The medtech suite threat model follows RTI's STRIDE framework for DDS Security. The network is the primary adversary — the DDS Security specification protects data in motion between applications through an untrusted network.

### Trust Boundaries

Two kinds of trust boundaries exist within the medtech suite:

| Boundary Type | Instances | Description |
|---------------|-----------|-------------|
| **Domain Trust Boundary** | Procedure, Hospital, Observability | Separates authorized domain members from unauthorized outsiders. Crossing requires valid credentials (PKI certs + permissions grant, or PSK passphrase). |
| **Topic Trust Boundary** | Per-topic within each domain (reinforced by domain tags in the Procedure domain) | Separates authorized topic publishers/subscribers from unauthorized domain insiders. Crossing requires topic-level permissions grant. |

### Attacker Roles

| Attacker Role | Description | Medtech Suite Example |
|---------------|-------------|-----------------------|
| **Domain Outsider** | Actor with physical/network access to the DDS network but no valid domain credentials. | Rogue device plugged into the OR network; container on the Docker network without valid certs or PSK. |
| **Domain Insider** | Actor with stolen or compromised credentials that grant domain join, but targets resources outside their authorized scope. | Compromised camera-sim container attempts to inject RobotCommand messages on the `control` tag. |
| **Topic Outsider** | Actor authorized to join the domain but not authorized to publish/subscribe to the target topic. | Hospital-dashboard participant (authorized on Hospital domain) attempts to subscribe to `RobotCommand` on the Procedure domain. |
| **Topic Insider** | Actor authorized to interact with a topic who impersonates another authorized participant or exceeds their pub/sub direction. | Compromised bedside-monitor (authorized to publish `PatientVitals`) attempts to publish `RobotCommand` using stolen robot-controller credentials. |

### Threat Matrix

The table below maps each STRIDE category to concrete medtech suite threats and the governance/permissions settings that mitigate them.

| STRIDE | Threat | Affected Trust Boundary | Example Attack | Mitigation (Governance/Permissions) |
|--------|--------|------------------------|----------------|-------------------------------------|
| **S** — Spoofing | Impersonate a legitimate participant | Domain | Attacker publishes `RobotCommand` as `robot-controller` | PKI mutual authentication (`enable_join_access_control=TRUE`); unique per-participant identity certificates |
| **S** — Spoofing | Impersonate a specific data source within a topic | Topic | Domain insider publishes fake `RobotState` from a non-robot-controller identity | Origin authentication (`ENCRYPT_WITH_ORIGIN_AUTHENTICATION` on `control`-tag `metadata_protection_kind`); per-participant receiver-specific MACs |
| **T** — Tampering | Modify in-flight control commands | Domain / Topic | Man-in-the-middle alters `RobotCommand` payload between operator and robot | `data_protection_kind=ENCRYPT` + `metadata_protection_kind=ENCRYPT_WITH_ORIGIN_AUTHENTICATION` on `control`-tag topics |
| **T** — Tampering | Modify discovery information to corrupt topic matching | Domain | Attacker injects malicious discovery data to redirect subscriptions | `discovery_protection_kind=ENCRYPT` on Procedure and Hospital domains; PSK protection on bootstrap traffic |
| **R** — Repudiation | Deny having issued a safety interlock release | Topic | Operator claims they did not issue the interlock-clear command | Origin authentication on `SafetyInterlock` topic; Connext Logging API captures all security events, forwarded to Grafana Loki via Monitoring Library 2.0 and Collector Service |
| **I** — Information Disclosure | Eavesdrop on patient vitals | Topic | Network sniffer captures `PatientVitals` PHI data | `data_protection_kind=ENCRYPT` on `clinical`-tag topics; `metadata_protection_kind=ENCRYPT` prevents topic name leakage |
| **I** — Information Disclosure | Discover system topology | Domain | Attacker reads unprotected discovery traffic to enumerate participants and topics | `discovery_protection_kind=ENCRYPT` encrypts endpoint announcements |
| **D** — Denial of Service | Exploit RTPS sequence numbers to force message drops | Domain | Attacker injects RTPS messages with spoofed sequence numbers | `rtps_protection_kind=SIGN` ensures RTPS integrity; `rtps_psk_protection_kind=SIGN` protects bootstrap phase |
| **D** — Denial of Service | Flood with invalid authentication handshakes | Domain | Unauthorized participant triggers repeated auth handshakes consuming CPU | `allow_unauthenticated_participants=FALSE` rejects pre-auth; PSK protection filters outsiders before handshake |
| **E** — Elevation of Privilege | Gain write access to topics beyond permissions | Topic | Camera-sim (operational-tag only) attempts to publish `RobotCommand` (control-tag) | `enable_write_access_control=TRUE` + per-topic permissions grants; domain tag isolation enforces separate participants |

### Protection Level Summary

The table below summarizes the DDS Security protection level achieved per domain, per the governance settings defined in this document.

| Domain | Domain Outsider Protection | Domain Insider Protection | Topic Outsider Protection | Topic Insider Protection |
|--------|---------------------------|--------------------------|--------------------------|-------------------------|
| **Procedure** (`control` tag) | STIDE | STDE | STIDE | STDE + I (write-only actors) |
| **Procedure** (`clinical` tag) | STIDE | STDE | STIDE | I (write-only actors) |
| **Procedure** (`operational` tag) | STDE | STDE | STDE | — |
| **Hospital** | STIDE | STDE | STIDE | I (write-only actors) |
| **Observability** | STDE | — | STDE | — |

**Legend:** S = Spoofing, T = Tampering, I = Information Disclosure, D = Denial of Service, E = Elevation of Privilege.

Procedure `control`-tag topics achieve the highest protection level (comparable to RTI's "Aviation Services Malicious Device" reference architecture) because origin authentication is enabled on both RTPS and metadata. Clinical and operational tags have progressively reduced protection aligned to their risk classification.

---

## Identity Model

### PKI Hierarchy

The medtech suite uses a two-tier PKI:

| Certificate Authority | Purpose | Key Usage |
|-----------------------|---------|-----------|
| **Identity CA** (`identity_ca.pem`) | Trust anchor for participant authentication. Validates leaf identity certificates during mutual DTLS handshake. | Signs leaf identity certificates |
| **Permissions CA** (`permissions_ca.pem`) | Trust anchor for access control. Validates signed governance and permissions documents. | Signs governance XML (`.p7s`) and permissions XML (`.p7s`) |

Both CAs are self-signed. The Identity CA and Permissions CA **may** be the same CA for simplicity in a single-hospital deployment, but are kept as separate artifacts to allow independent rotation and organizational separation in multi-facility (V3.0) deployments.

### Leaf Certificates

Each deployed participant receives a unique X.509 identity certificate signed by the Identity CA. The certificate subject name encodes the **participant role** using a structured naming convention:

```
CN=<role>/<instance>, O=MedtechSuite, OU=<module>
```

#### Participant Role Inventory

| Role Name | Module | Subject Name | Domain(s) |
|-----------|--------|-------------|-----------|
| `robot-controller` | surgical-procedure | `CN=robot-controller/OR-1, O=MedtechSuite, OU=surgical-procedure` | Procedure (`control` tag) |
| `bedside-monitor` | surgical-procedure | `CN=bedside-monitor/OR-1, O=MedtechSuite, OU=surgical-procedure` | Procedure (`clinical` tag) |
| `camera-sim` | surgical-procedure | `CN=camera-sim/OR-1, O=MedtechSuite, OU=surgical-procedure` | Procedure (`operational` tag) |
| `procedure-publisher` | surgical-procedure | `CN=procedure-publisher/OR-1, O=MedtechSuite, OU=surgical-procedure` | Procedure (`operational` tag) |
| `device-telemetry-gw` | surgical-procedure | `CN=device-telemetry-gw/OR-1, O=MedtechSuite, OU=surgical-procedure` | Procedure (`clinical` tag) |
| `digital-twin` | surgical-procedure | `CN=digital-twin/OR-1, O=MedtechSuite, OU=surgical-procedure` | Procedure (`control` tag) |
| `hospital-dashboard` | hospital-dashboard | `CN=hospital-dashboard/dash-1, O=MedtechSuite, OU=hospital-dashboard` | Hospital |
| `clinical-alerts-engine` | clinical-alerts | `CN=clinical-alerts-engine/cds-1, O=MedtechSuite, OU=clinical-alerts` | Hospital |
| `resource-sim` | hospital-dashboard | `CN=resource-sim/sim-1, O=MedtechSuite, OU=hospital-dashboard` | Hospital |
| `routing-service` | services/routing | `CN=routing-service/rs-1, O=MedtechSuite, OU=routing` | Procedure (all 3 tags) + Orchestration + Hospital |
| `cloud-discovery-service` | services | `CN=cloud-discovery-service/cds-infra-1, O=MedtechSuite, OU=infrastructure` | Infrastructure (discovery only) |

The `/<instance>` suffix (e.g., `/OR-1`, `/dash-1`) distinguishes multiple deployments of the same role. Permissions are granted using `<subject_name_expression>` with POSIX `fnmatch()` wildcard matching on `CN=<role>/*, O=MedtechSuite, OU=<module>`, so adding a new OR or dashboard instance requires only a new leaf cert — no permissions changes.

> **Important:** The `<subject_name_expression>` element (not `<subject_name>`) is required for wildcard matching. The `<subject_name>` element performs exact-match only. The agent must always use `<subject_name_expression>` in permission grants.

### Certificate Revocation

- **CRL distribution:** A single CRL file (`crl.pem`) is maintained per Identity CA and placed in the shared security directory (`interfaces/security/crl/`).
- **File polling:** Connext 7.6.0 automatically detects changes to the CRL file on disk. The CRL is referenced via the `dds.sec.auth.crl` property using a `file:` URI.
- **Polling interval:** The CRL file is checked for updates by the middleware on each new authentication handshake. For mid-session revocation, Connext supports **dynamic certificate revocation** — a revoked participant's existing sessions are terminated when the updated CRL is detected.
- **Operational target:** Revocation takes effect within **60 seconds** of CRL file update (bounded by the authentication plugin's re-evaluation cycle).

### Certificate Rotation

Connext 7.6.0 supports **dynamic certificate renewal** — when a participant's identity certificate file is replaced on disk, the middleware detects the change via the file tracker (`files_poll_interval`) and propagates the updated certificate to peers without restarting the participant process. This is configured via the same `file:` URI properties and requires no additional application code.

**Constraints on dynamic renewal:**
- The new certificate **must** retain the same **subject name** and **public key** as the original. These are immutable for the lifetime of the DomainParticipant.
- Because the public key is unchanged, no new authentication handshake is required — the update is propagated to peers as a certificate refresh, not a full re-authentication.
- If a **new key pair** is required (e.g., key compromise), the participant process **must be restarted** with the new certificate and private key. Dynamic renewal does not support public key changes.
- Dynamic renewal of the **private key** alone (without restarting) is not documented as supported. The private key file should only be updated alongside a restart when key rotation is needed.

Certificate renewal target: updated certificates are picked up within **120 seconds** of file replacement.

### Pre-Shared Key (PSK) Authentication

PSK is supported as a lightweight alternative to PKI for constrained or embedded devices (V2+ device gateways). PSK is **not used for V2 core modules** — it is reserved for V2+ device integration gateways where a full PKI deployment is impractical. All V2 core modules use full PKI authentication.

#### PSK Configuration

PSK uses a **file-based passphrase** that is deployed alongside the application and can be updated at runtime when passphrase cycling is required due to identified threats. The passphrase file is monitored by the Security Plugins' file tracker.

```xml
<property>
  <value>
    <element>
      <name>dds.sec.crypto.rtps_psk_secret_passphrase</name>
      <value>file:${MEDTECH_SECURITY_DIR}/psk/procedure_domain_psk.txt</value>
    </element>
  </value>
</property>
```

The passphrase file content uses the format `<passphrase_id>:<passphrase>`:

```text
1:Base64OrOtherHighEntropyPassphraseValue
```

The `passphrase_id` is a numeric identifier that **must change** when the passphrase is rotated. The Security Plugins' file tracker (configured via `com.rti.serv.secure.files_poll_interval`) detects the file change and reloads the passphrase without restarting the participant.

#### PSK Runtime Rotation

For zero-message-loss passphrase rotation, use the `dds.sec.crypto.rtps_psk_secret_passphrase_extra` property to maintain the old passphrase during the transition window:

1. Deploy the **new** passphrase as the `_extra` passphrase file on all participants (file tracker detects the change).
2. Once all participants have loaded the new `_extra` passphrase, swap — update the **primary** passphrase file to the new value.
3. After all participants have loaded the new primary, remove the `_extra` file (or update it to prepare for the next rotation).

> **Note:** RTI warns that if both primary and extra passphrase files change simultaneously, the file tracker may not detect both changes in the same poll cycle. Follow the sequential update pattern above.

#### PSK File Layout

```
interfaces/security/psk/
├── procedure_domain_psk.txt          # Primary PSK passphrase for Procedure domain
├── procedure_domain_psk_extra.txt    # Transition PSK (used during rotation only)
├── hospital_domain_psk.txt           # Primary PSK passphrase for Hospital domain
└── hospital_domain_psk_extra.txt     # Transition PSK (used during rotation only)
```

#### PSK Governance Integration

PSK protection coexists with (does not replace) RTPS protection in the Builtin Security Plugins. In the governance `<domain_rule>`:

- `rtps_protection_kind` — protects RTPS traffic **after** authentication (uses PKI-derived symmetric keys)
- `rtps_psk_protection_kind` — protects RTPS traffic **before** authentication completes (uses the shared PSK)

For domains that include PSK participants, both values are set:

```xml
<rtps_protection_kind>SIGN</rtps_protection_kind>
<rtps_psk_protection_kind>SIGN</rtps_psk_protection_kind>
```

PSK participants are enabled via the built-in QoS snippet `BuiltinQosSnippetLib::Feature.LightweightSecurity.Enable`.

#### PSK + PKI Rationale

The medtech suite uses PSK **alongside** full PKI (Builtin Security Plugins), not as a replacement. This is a deliberate defense-in-depth decision based on how Connext 7.6.0 partitions protection responsibility between the two mechanisms:

| Communication Phase | Protected By | Without PSK |
|---------------------|-------------|-------------|
| **Bootstrap** — SPDP discovery, authentication handshake, secure key exchange, locator pings | `rtps_psk_protection_kind` (PSK) | **Unprotected** — outsiders can inject, tamper with, or eavesdrop on pre-auth traffic |
| **Steady-state** — post-authentication RTPS user/meta traffic | `rtps_protection_kind` (PKI-derived AXK keys) | Protected (same either way) |

**Key facts:**
- **No double encryption on steady-state traffic.** When both `rtps_protection_kind` and `rtps_psk_protection_kind` are non-`NONE`, PSK protects only bootstrap RTPS messages. After authentication completes, AXK-based protection takes over. There is zero additional steady-state overhead.
- **Bootstrap traffic is otherwise unprotected.** Without PSK, the SPDP participant discovery, authentication messages, key exchange channel, and locator pings are sent unprotected — even when full PKI is enabled. This is by design in the DDS Security specification; `rtps_protection_kind` does not cover bootstrap traffic.
- **PSK filters outsiders before the auth handshake.** An attacker without the PSK cannot produce valid protected bootstrap messages, so they are rejected before the PKI authentication flow is triggered. This reduces the attack surface for denial-of-service attacks that exploit pre-auth code paths.
- **RTI's STRIDE threat model explicitly associates Domain Outsider Protection with PSK.** The Medical System Malicious Device example (Ch. 10.5.3) uses `rtps_psk_protection_kind=SIGN` alongside `enable_join_access_control=TRUE` for complete Domain Outsider STDE protection.

**Justification for the medtech suite:**
1. **Near-zero runtime cost** — overhead is limited to bootstrap/discovery phase only
2. **Closes the last unprotected gap** — without PSK, bootstrap traffic is the only RTPS path not integrity-protected in our architecture
3. **Docker network is a shared environment** — containers on the same Docker network can inject traffic; PSK provides a first-pass filter
4. **Low operational burden** — one passphrase file per domain, already in the file structure, managed via file tracker
5. **Aligns with RTI's recommended medical posture** — RTI's own medical STRIDE example uses PSK for Domain Outsider Protection

**When to omit PSK:** If the deployment network is physically isolated with no possibility of unauthorized device attachment and operational simplicity is paramount, PKI alone is defensible. The PSK+PKI decision should be revisited per deployment site.

---

## Domain Governance

Governance documents define **how** each domain is protected — join policy, discovery protection, and per-topic data/metadata protection levels. Each governance document is signed by the Permissions CA and stored as a PKCS#7 signed file (`.p7s`).

### File Layout

```
interfaces/security/governance/
├── Governance_Procedure.xml          # Procedure domain governance (source)
├── Governance_Procedure_signed.p7s   # Signed — referenced by participants
├── Governance_Hospital.xml           # Hospital domain governance (source)
├── Governance_Hospital_signed.p7s    # Signed — referenced by participants
├── Governance_Observability.xml      # Observability domain governance (source)
└── Governance_Observability_signed.p7s # Signed — referenced by Monitoring Library 2.0 dedicated participants
```

One governance document per functional domain. Routing Service participants reference the governance document of each domain they join (Procedure + Hospital governance for the cross-domain bridge). The Observability domain governance applies to the dedicated telemetry participants created by Monitoring Library 2.0.

### Procedure Domain Governance

The Procedure domain uses domain tags for risk-class isolation. Governance reinforces domain tags with cryptographic protection aligned to risk classification:

| Domain Tag | Risk Class | `data_protection_kind` | `metadata_protection_kind` | Rationale |
|------------|-----------|----------------------|---------------------------|-----------|
| `control` | Class C/III (safety-critical) | `ENCRYPT` | `ENCRYPT_WITH_ORIGIN_AUTHENTICATION` | Highest protection. Origin authentication prevents spoofed commands from reaching the robot controller. Encryption protects proprietary control algorithms. |
| `clinical` | Class B/II (clinical significance) | `ENCRYPT` | `ENCRYPT` | Patient vitals and alarms are PHI. Encrypted in transit to prevent eavesdropping. |
| `operational` | Class A/I (non-critical) | `SIGN` | `SIGN` | Procedure metadata, camera frames, and context are integrity-protected but not encrypted. This reduces computational overhead for high-bandwidth camera streams while ensuring data has not been tampered with. Camera frames in this system are synthetic simulation data and do not contain PHI. If a deployment uses real surgical camera imagery that constitutes PHI, the `CameraFrame` topic should be upgraded to `data_protection_kind=ENCRYPT` via a more-specific `topic_rule` that overrides the general operational-tag SIGN default (see [Confidentiality Escalation for CameraFrame](#confidentiality-escalation-for-cameraframe)). |

> **Governance XML Structure — Three `domain_rule` Entries Required**
>
> Because governance `topic_access_rules` within a single `domain_rule` cannot differentiate protection by domain tag — they match by topic expression only — `Governance_Procedure.xml` **must** contain **three separate `<domain_rule>` entries**, one per domain tag:
>
> 1. A `<domain_rule>` selecting `<tag>control</tag>` on the Procedure domain ID, with `topic_access_rules` specifying `ENCRYPT` / `ENCRYPT_WITH_ORIGIN_AUTHENTICATION` for control-tag topics.
> 2. A `<domain_rule>` selecting `<tag>clinical</tag>` on the Procedure domain ID, with `topic_access_rules` specifying `ENCRYPT` / `ENCRYPT` for clinical-tag topics.
> 3. A `<domain_rule>` selecting `<tag>operational</tag>` on the Procedure domain ID, with `topic_access_rules` specifying `SIGN` / `SIGN` for operational-tag topics.
>
> A single `<domain_rule>` with `<tag_expression>*</tag_expression>` would apply the **same** topic protection to all three tags, defeating risk-class isolation. Each rule must explicitly select its tag via `<tag>` or `<tag_expression>`. Topic rules are processed top-to-bottom within the matched `domain_rule`; the first matching `topic_rule` applies.

**Domain-level settings** (shared by all three `domain_rule` entries):

| Element | Value | Rationale |
|---------|-------|-----------|
| `allow_unauthenticated_participants` | `FALSE` | Default deny — no anonymous participants on the Procedure domain |
| `enable_join_access_control` | `TRUE` | Permissions must grant domain join |
| `discovery_protection_kind` | `ENCRYPT` | Endpoint announcements are encrypted — prevents topology reconnaissance |
| `liveliness_protection_kind` | `SIGN` | Liveliness messages are integrity-protected |
| `rtps_protection_kind` | `SIGN` | RTPS-level integrity on all messages |
| `enable_key_revision` | `TRUE` | Required for dynamic CRL revocation and certificate renewal propagation. Default in 7.6.0 but set explicitly for clarity. All participants must share the same value — mismatched `enable_key_revision` prevents communication. |

**Topic rules** apply the tag-aligned protection from the table above. Since domain tags partition discovery, each tag's topics are only visible to participants with that tag — governance adds cryptographic enforcement on top of the existing tag isolation.

Example topic rule for `control`-tag topics:

```xml
<topic_rule>
  <topic_expression>RobotCommand</topic_expression>
  <enable_discovery_protection>TRUE</enable_discovery_protection>
  <enable_liveliness_protection>TRUE</enable_liveliness_protection>
  <enable_read_access_control>TRUE</enable_read_access_control>
  <enable_write_access_control>TRUE</enable_write_access_control>
  <metadata_protection_kind>ENCRYPT_WITH_ORIGIN_AUTHENTICATION</metadata_protection_kind>
  <data_protection_kind>ENCRYPT</data_protection_kind>
</topic_rule>
```

#### Confidentiality Escalation for CameraFrame

The default `operational`-tag protection is `SIGN` (integrity only, no encryption). This is appropriate when camera frames are synthetic simulation data with no patient-identifiable content. If a deployment uses **real surgical camera imagery** that constitutes PHI or is otherwise sensitive, the `CameraFrame` topic should be escalated to `ENCRYPT` by adding a **more-specific `topic_rule`** above the general operational-tag wildcard rule in the `operational` `domain_rule`:

```xml
<!-- Place BEFORE the general operational-tag wildcard topic_rule -->
<topic_rule>
  <topic_expression>CameraFrame</topic_expression>
  <enable_discovery_protection>TRUE</enable_discovery_protection>
  <enable_liveliness_protection>TRUE</enable_liveliness_protection>
  <enable_read_access_control>TRUE</enable_read_access_control>
  <enable_write_access_control>TRUE</enable_write_access_control>
  <metadata_protection_kind>ENCRYPT</metadata_protection_kind>
  <data_protection_kind>ENCRYPT</data_protection_kind>
</topic_rule>
```

This override does not affect `ProcedureContext` or `ProcedureStatus`, which remain at `SIGN`.

### Hospital Domain Governance

The Hospital domain has no domain tags. All topics receive uniform protection:

| Element | Value | Rationale |
|---------|-------|-----------|
| `allow_unauthenticated_participants` | `FALSE` | Default deny |
| `enable_join_access_control` | `TRUE` | Permissions must grant domain join |
| `discovery_protection_kind` | `ENCRYPT` | Encrypted discovery |
| `liveliness_protection_kind` | `SIGN` | Signed liveliness |
| `rtps_protection_kind` | `SIGN` | RTPS-level integrity |
| `enable_key_revision` | `TRUE` | Required for dynamic CRL revocation. Default in 7.6.0 but set explicitly. |

**Per-topic protection** (uniform for all Hospital domain topics):

| Setting | Value | Rationale |
|---------|-------|-----------|
| `data_protection_kind` | `ENCRYPT` | All Hospital domain data contains PHI (patient vitals, risk scores, alerts, resource status) |
| `metadata_protection_kind` | `ENCRYPT` | Submessage metadata encrypted |
| `enable_discovery_protection` | `TRUE` | — |
| `enable_read_access_control` | `TRUE` | — |
| `enable_write_access_control` | `TRUE` | — |

### Observability Domain Governance

The Observability domain carries telemetry from Monitoring Library 2.0 — metrics, forwarded application logs (which may contain PHI-adjacent information such as patient IDs in log messages), and security events. It receives its own governance document:

| Element | Value | Rationale |
|---------|-------|-----------|
| `allow_unauthenticated_participants` | `FALSE` | Default deny |
| `enable_join_access_control` | `TRUE` | Permissions must grant domain join |
| `discovery_protection_kind` | `SIGN` | Signed (not encrypted) — Collector Service needs lightweight discovery |
| `liveliness_protection_kind` | `NONE` | Telemetry participants do not require liveliness protection |
| `enable_key_revision` | `TRUE` | Required for dynamic CRL revocation. Default in 7.6.0 but set explicitly. |

**Per-topic protection** (applies to all Monitoring Library 2.0 internal telemetry topics):

| Setting | Value | Rationale |
|---------|-------|-----------|
| `data_protection_kind` | `ENCRYPT` | Telemetry data may contain PHI-adjacent information (patient IDs in forwarded log messages, vital values in debug traces) |
| `metadata_protection_kind` | `SIGN` | Signed but not encrypted — sufficient for telemetry metadata |
| `enable_write_access_control` | `TRUE` | Every authenticated participant's Monitoring Library 2.0 dedicated participant is granted write — but the grant is explicit |
| `enable_read_access_control` | `TRUE` | Only Collector Service is granted read |

---

## Permissions Model

Permissions documents define **who can do what** — per-participant authorization for topic publish/subscribe, domain join, and partition access. Each permissions document is signed by the Permissions CA.

### File Layout

```
interfaces/security/permissions/
├── Permissions_RobotController.xml          # Source
├── Permissions_RobotController_signed.p7s   # Signed — referenced by participant
├── Permissions_BedsideMonitor.xml
├── Permissions_BedsideMonitor_signed.p7s
├── Permissions_CameraSim.xml
├── Permissions_CameraSim_signed.p7s
├── Permissions_ProcedurePublisher.xml
├── Permissions_ProcedurePublisher_signed.p7s
├── Permissions_DeviceTelemetryGw.xml
├── Permissions_DeviceTelemetryGw_signed.p7s
├── Permissions_DigitalTwin.xml
├── Permissions_DigitalTwin_signed.p7s
├── Permissions_HospitalDashboard.xml
├── Permissions_HospitalDashboard_signed.p7s
├── Permissions_ClinicalAlertsEngine.xml
├── Permissions_ClinicalAlertsEngine_signed.p7s
├── Permissions_ResourceSim.xml
├── Permissions_ResourceSim_signed.p7s
├── Permissions_RoutingService.xml
├── Permissions_RoutingService_signed.p7s
├── Permissions_CloudDiscoveryService.xml
└── Permissions_CloudDiscoveryService_signed.p7s
```

One permissions file per participant role. Multiple instances of the same role (e.g., robot-controller in OR-1 and OR-3) share the same permissions file — instance differentiation is in the identity certificate subject name, and the grant matches on `CN=<role>/*`.

### Default Deny Posture

Every permissions document uses a **default deny** structure: an explicit `<deny_rule>` at the end of the grant catches any topic or domain not covered by a preceding `<allow_rule>`. The agent must never omit the trailing deny rule.

> **Tag behavior asymmetry in permissions rules:** In Connext 7.6.0, omitted tags in `<allow_rule>` default to the **empty tag** (matching only participants with no domain tag), while omitted tags in `<deny_rule>` behave like **`*`** (matching all tags). This asymmetry means that `<allow_rule>` entries **must** explicitly specify the target domain tag when granting access to tagged domains — omitting the tag will not match tagged participants. The trailing `<deny_rule>` does not need an explicit tag because it already matches all tags by default.

```xml
<grant name="RobotController">
  <subject_name_expression>CN=robot-controller/*,O=MedtechSuite,OU=surgical-procedure</subject_name_expression>
  <validity>
    <not_before>2026-01-01T00:00:00</not_before>
    <not_after>2028-01-01T00:00:00</not_after>
  </validity>

  <!-- Explicit allows -->
  <allow_rule>
    <domains><id_range><min>0</min><max>230</max></id_range></domains>
    <publish>...</publish>
    <subscribe>...</subscribe>
  </allow_rule>

  <!-- Default deny everything else -->
  <deny_rule>
    <domains><id_range><min>0</min><max>230</max></id_range></domains>
  </deny_rule>
</grant>
```

### Permission Grants — Summary

The table below shows the topic-level grants for each participant role. **P** = publish, **S** = subscribe. Unlisted topics are denied.

#### Procedure Domain (by tag)

| Role | Tag | `RobotCommand` | `RobotState` | `SafetyInterlock` | `OperatorInput` | `PatientVitals` | `WaveformData` | `AlarmMessages` | `DeviceTelemetry` | `CameraFrame` | `ProcedureContext` | `ProcedureStatus` |
|------|-----|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| robot-controller | `control` | S | P | S | S | — | — | — | — | — | — | — |
| digital-twin | `control` | — | S | S | — | — | — | — | — | — | — | — |
| bedside-monitor | `clinical` | — | — | — | — | P | P | P | — | — | — | — |
| device-telemetry-gw | `clinical` | — | — | — | — | — | — | — | P | — | — | — |
| camera-sim | `operational` | — | — | — | — | — | — | — | — | P | — | — |
| procedure-publisher | `operational` | — | — | — | — | — | — | — | — | — | P | P |
| routing-service | `control` | — | S | — | — | — | — | — | — | — | — | — |
| routing-service | `clinical` | — | — | — | — | S | — | S | S | — | — | — |
| routing-service | `operational` | — | — | — | — | — | — | — | — | — | S | S |

#### Hospital Domain

| Role | `ProcedureStatus` | `PatientVitals` | `AlarmMessages` | `DeviceTelemetry` | `RobotState` | `ClinicalAlert` | `RiskScore` | `ResourceAvailability` |
|------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| routing-service | P | P | P | P | P | — | — | — |
| hospital-dashboard | S | S | S | S | S | S | S | S |
| clinical-alerts-engine | — | S | — | — | — | P | P | — |
| resource-sim | — | — | — | — | — | — | — | P |

### Partition-Aware Permissions

Procedure domain participants are partition-scoped to their room/procedure context. Permissions use wildcard partition expressions to grant access without enumerating every room:

```xml
<publish>
  <topics><topic>RobotState</topic></topics>
  <partitions><partition>room/*/procedure/*</partition></partitions>
</publish>
```

This means a robot-controller in any room can publish `RobotState` on its room partition, but cannot publish on a partition belonging to a different room (enforced at the security plugin level, in addition to the application-level partition assignment).

The hospital-dashboard subscribes with a wildcard partition (`*`) to aggregate data from all rooms — its permissions grant `<partition>*</partition>` on subscribe.

---

## Origin Authentication

Origin authentication verifies the identity of the **data source** at the DDS level, not just the transport channel. This is critical for safety-class data paths where a spoofed command could cause physical harm.

### Implementation

Origin authentication is enabled in governance via `metadata_protection_kind` with the `_WITH_ORIGIN_AUTHENTICATION` suffix:

- `ENCRYPT_WITH_ORIGIN_AUTHENTICATION` — encrypts + authenticates origin
- `SIGN_WITH_ORIGIN_AUTHENTICATION` — signs + authenticates origin (no encryption)

These values are set on `metadata_protection_kind` (not `data_protection_kind`).

### Where Applied

| Topic | `metadata_protection_kind` | Rationale |
|-------|---------------------------|-----------|
| `RobotCommand` | `ENCRYPT_WITH_ORIGIN_AUTHENTICATION` | Commands to the robot must be verified as originating from an authenticated operator input source. A spoofed command is a physical safety risk. |
| `SafetyInterlock` | `ENCRYPT_WITH_ORIGIN_AUTHENTICATION` | Interlock state must be trustworthy — a spoofed "interlock clear" could disable safety systems. |
| `OperatorInput` | `ENCRYPT_WITH_ORIGIN_AUTHENTICATION` | High-rate operator input directly controls robot motion. Origin must be verified. |
| `RobotState` | `ENCRYPT_WITH_ORIGIN_AUTHENTICATION` | Robot state is consumed by the safety interlock system and the digital twin. A spoofed state could mask a dangerous condition. |

All four are `control`-tag topics. Clinical and operational topics use `ENCRYPT` or `SIGN` respectively (without origin authentication) — the reduced computational overhead is acceptable because those topics do not control physical actuators.

---

## Design Considerations

This section captures performance, scalability, and operational factors that the agent must account for when generating security artifacts, drawn from RTI's Security Plugins Design Considerations (Ch. 11) and Best Practices (Ch. 12).

### File Tracking

The Security Plugins file tracker monitors mutable security files (CRL, identity certificates, permissions documents, PSK passphrase files) and reloads them when changes are detected.

| Property | Value | Rationale |
|----------|-------|-----------|
| `com.rti.serv.secure.files_poll_interval` | `5` | Default value. Meets the 60-second CRL revocation target with margin. Lower values (1s) increase CPU overhead; higher values (60s) risk approaching the revocation SLA boundary. |

This property is set at participant creation time and is **not mutable**. It applies to all tracked files: CRL, identity certs, permissions documents, and PSK passphrase files.

> **Note:** Some RTI Infrastructure Services depend on file tracking. Never set `files_poll_interval` to `0` in the medtech suite — CRL revocation and certificate rotation both require active file tracking.

### Origin Authentication Tuning

The `cryptography.max_receiver_specific_macs` property controls how many per-receiver MACs are included in messages protected with `_WITH_ORIGIN_AUTHENTICATION`. Each receiver-specific MAC adds **20 bytes** to the message footer.

| Property | Value | Rationale |
|----------|-------|-----------|
| `com.rti.serv.secure.cryptography.max_receiver_specific_macs` | `16` | Sized for ~10–15 participants per domain. Exceeding this count causes round-robin MAC sharing, which weakens origin authentication between grouped participants. |

> **Critical:** The default value of `max_receiver_specific_macs` is **0**, which **disables** origin authentication entirely. This property **must** be explicitly set on every participant that uses `_WITH_ORIGIN_AUTHENTICATION` governance rules. The agent must include this property in every control-tag participant's QoS profile.

### MTU and Fragmentation

Origin authentication MACs increase message size. To avoid IP fragmentation on standard Ethernet (1500-byte MTU):

- Maximum receiver-specific MACs without fragmentation: `(message_size_max - usable_rtps_size) / 20`
- With `message_size_max=1472` (UDP/Ethernet) and ~1kB usable RTPS size, approximately **23 MACs** can fit without fragmentation.
- The medtech suite's `max_receiver_specific_macs=16` stays within this budget.

### Startup Scalability

Security adds approximately **3× discovery traffic** per pair of DomainParticipants (authentication handshake + key exchange). For the medtech suite's ~11 participants across 3 functional domains:

- Procedure domain: ~8 participants → additional ~84 key exchanges (8 × 7 / 2 × 3)
- Hospital domain: ~5 participants → additional ~30 key exchanges
- Observability domain: ~11 participants (Monitoring Library 2.0 dedicated participants) → additional ~165 key exchanges

This is well within normal capacity for a Docker-based deployment but must be accounted for in startup timing and Docker health-check grace periods.

### Per-Participant Permissions Documents

RTI best practice: use **individual permissions documents** per participant. The medtech suite already follows this — one permissions file per role (see [Permissions File Layout](#file-layout-1)). This reduces permissions exchange overhead from O(N² × total-grants) to O(N² × 1-grant), saving substantial network traffic.

### Protection Kind Layering

RTI guidance: combine `SIGN` RTPS protection with `ENCRYPT` submessage protection for layered defense. The medtech suite aligns:

- `rtps_protection_kind=SIGN` — RTPS-level integrity on all messages (lightweight, domain-wide)
- `metadata_protection_kind=ENCRYPT` or `ENCRYPT_WITH_ORIGIN_AUTHENTICATION` — topic-level confidentiality + integrity

This avoids redundant triple-encryption (`data_protection_kind` + `metadata_protection_kind` + `rtps_protection_kind` all set to `ENCRYPT`) while maintaining the required protection level.

### Compression Restriction

RTI discourages using data compression with encryption because compression occurs before security protection in the Connext pipeline. For confidential data, this can enable CRIME/BREACH-style length-oracle attacks if an attacker has partial control over compressed plaintext. The medtech suite does not enable DDS compression on any encrypted topic. If compression is needed for high-bandwidth operational data (e.g., `CameraFrame`), it may only be applied on topics where `data_protection_kind=SIGN` (not `ENCRYPT`).

### Forward Compatibility

When generating governance XML, use `must_interpret="false"` on elements that may not be recognized by older Security Plugins versions. This allows mixed-version deployments to parse governance documents without validation failures.

---

## Routing Service Security

Routing Service is the trust boundary between the Procedure domain and the Hospital domain. It must be authenticated and authorized on both sides.

### Identity

Routing Service receives a single identity certificate (`CN=routing-service/<instance>`) but creates **4 DomainParticipants** (3 on the Procedure domain, 1 on the Hospital domain). All 4 participants share the same identity certificate and private key. Each participant independently authenticates with its peers. Each participant references the governance document appropriate to its domain:

> **Trade-off — single identity across trust zones:** Using one certificate for all 4 Routing Service participants is functionally valid in Connext 7.6.0 (multiple DomainParticipants in the same process may share the same cert/key). The accepted consequences are: (1) revocation or renewal affects all 4 participants atomically, (2) audit trails cannot distinguish which internal RS participant performed a given action, (3) all 4 participants share one cryptographic identity across different domains and tags. For production deployments with strict regulatory auditability requirements, consider separate certificates per Routing Service DomainParticipant (or at minimum, per domain).

| RS Participant | Domain | Tag | Governance |
|----------------|--------|-----|-----------|
| Procedure-control | Procedure | `control` | `Governance_Procedure_signed.p7s` |
| Procedure-clinical | Procedure | `clinical` | `Governance_Procedure_signed.p7s` |
| Procedure-operational | Procedure | `operational` | `Governance_Procedure_signed.p7s` |
| Hospital-bridge | Hospital | *(none)* | `Governance_Hospital_signed.p7s` |

### Permissions

Routing Service permissions grant:
- **Subscribe** on Procedure domain for each bridged topic on its respective tag (see [Permission Grants — Procedure Domain](#procedure-domain-by-tag))
- **Publish** on Hospital domain for the bridged topics (see [Permission Grants — Hospital Domain](#hospital-domain))
- **No publish** on the Procedure domain — Routing Service is strictly one-way (Procedure → Hospital)
- **No subscribe** on the Hospital domain — data does not flow back

This enforces the architectural invariant: data flows from Procedure → Hospital via Routing Service, never the reverse.

### Secure-to-Secure Bridge

All 4 Routing Service participants are fully authenticated participants on their respective domains. The bridge operates as a secure-to-secure relay — data is decrypted from the Procedure domain side, re-encrypted for the Hospital domain side, and published with Routing Service's own identity. The Hospital domain subscriber sees Routing Service as the origin (not the original Procedure domain publisher).

---

## Cloud Discovery Service Security

Cloud Discovery Service provides multicast-free discovery for all participants in the Docker deployment. It must be secured to prevent unauthorized discovery injection.

### Identity

Cloud Discovery Service receives an identity certificate (`CN=cloud-discovery-service/<instance>`) and is authenticated by all participants via the shared Identity CA.

### Transport Security

Discovery traffic between participants and Cloud Discovery Service uses **secure transport**. The Cloud Discovery Service deployment references the same Identity CA and its own leaf certificate. The relevant participant QoS properties are the same `dds.sec.*` properties used by all other participants.

### Permissions

Cloud Discovery Service does not publish or subscribe to application topics. Its permissions grant only domain join on all functional domains (Procedure, Hospital, Observability) — required for it to relay discovery information. No topic-level publish or subscribe grants are needed.

---

## Security QoS Property Reference

All security artifacts are referenced from participant QoS XML via the standard `dds.sec.*` properties. The agent must wire these properties into the participant profiles in `Participants.xml`.

```xml
<domain_participant_qos>
  <property>
    <value>
      <!-- Authentication -->
      <element>
        <name>dds.sec.auth.identity_ca</name>
        <value>file:${MEDTECH_SECURITY_DIR}/ca/identity_ca.pem</value>
      </element>
      <element>
        <name>dds.sec.auth.identity_certificate</name>
        <value>file:${MEDTECH_SECURITY_DIR}/certs/${PARTICIPANT_ROLE}.pem</value>
      </element>
      <element>
        <name>dds.sec.auth.private_key</name>
        <value>file:${MEDTECH_SECURITY_DIR}/private/${PARTICIPANT_ROLE}_key.pem</value>
      </element>
      <element>
        <name>dds.sec.auth.crl</name>
        <value>file:${MEDTECH_SECURITY_DIR}/crl/crl.pem</value>
      </element>

      <!-- Access Control -->
      <element>
        <name>dds.sec.access.permissions_ca</name>
        <value>file:${MEDTECH_SECURITY_DIR}/ca/permissions_ca.pem</value>
      </element>
      <element>
        <name>dds.sec.access.governance</name>
        <value>file:${MEDTECH_SECURITY_DIR}/governance/${DOMAIN}_Governance_signed.p7s</value>
      </element>
      <element>
        <name>dds.sec.access.permissions</name>
        <value>file:${MEDTECH_SECURITY_DIR}/permissions/${PARTICIPANT_ROLE}_Permissions_signed.p7s</value>
      </element>

      <!-- File Tracking -->
      <element>
        <name>com.rti.serv.secure.files_poll_interval</name>
        <value>5</value>
      </element>

      <!-- Origin Authentication (control-tag participants only) -->
      <element>
        <name>com.rti.serv.secure.cryptography.max_receiver_specific_macs</name>
        <value>16</value>
      </element>
    </value>
  </property>
</domain_participant_qos>
```

The `com.rti.serv.secure.cryptography.max_receiver_specific_macs` property is required **only** for participants on domains where `_WITH_ORIGIN_AUTHENTICATION` governance rules apply (`control`-tag topics on the Procedure domain). Participants that do not participate in origin-authenticated topics (e.g., hospital-dashboard, resource-sim) may omit this property.

The `${MEDTECH_SECURITY_DIR}` environment variable points to `interfaces/security/` in the install tree. `setup.bash` exports this variable alongside the existing `MEDTECH_CONFIG_DIR` and `NDDS_QOS_PROFILES`.

---

## Security File Structure

The complete file layout under `interfaces/security/`:

```
interfaces/security/
├── ca/
│   ├── identity_ca.pem              # Identity CA certificate
│   ├── identity_ca_key.pem          # Identity CA private key (offline — not deployed)
│   ├── permissions_ca.pem           # Permissions CA certificate
│   └── permissions_ca_key.pem       # Permissions CA private key (offline — not deployed)
├── certs/
│   ├── robot-controller.pem         # Leaf identity certs (one per role)
│   ├── bedside-monitor.pem
│   ├── camera-sim.pem
│   ├── procedure-publisher.pem
│   ├── device-telemetry-gw.pem
│   ├── digital-twin.pem
│   ├── hospital-dashboard.pem
│   ├── clinical-alerts-engine.pem
│   ├── resource-sim.pem
│   ├── routing-service.pem
│   └── cloud-discovery-service.pem
├── private/
│   ├── robot-controller_key.pem     # Private keys (one per role)
│   ├── bedside-monitor_key.pem
│   ├── ...                          # (one per cert above)
│   └── cloud-discovery-service_key.pem
├── crl/
│   └── crl.pem                      # Certificate Revocation List
├── psk/
│   ├── procedure_domain_psk.txt     # Primary PSK passphrase (Procedure domain)
│   ├── procedure_domain_psk_extra.txt  # Transition PSK (rotation only)
│   ├── hospital_domain_psk.txt      # Primary PSK passphrase (Hospital domain)
│   └── hospital_domain_psk_extra.txt   # Transition PSK (rotation only)
├── governance/
│   ├── Governance_Procedure.xml
│   ├── Governance_Procedure_signed.p7s
│   ├── Governance_Hospital.xml
│   ├── Governance_Hospital_signed.p7s
│   ├── Governance_Observability.xml
│   └── Governance_Observability_signed.p7s
└── permissions/
    ├── Permissions_RobotController.xml
    ├── Permissions_RobotController_signed.p7s
    ├── Permissions_BedsideMonitor.xml
    ├── Permissions_BedsideMonitor_signed.p7s
    ├── Permissions_CameraSim.xml
    ├── Permissions_CameraSim_signed.p7s
    ├── Permissions_ProcedurePublisher.xml
    ├── Permissions_ProcedurePublisher_signed.p7s
    ├── Permissions_DeviceTelemetryGw.xml
    ├── Permissions_DeviceTelemetryGw_signed.p7s
    ├── Permissions_DigitalTwin.xml
    ├── Permissions_DigitalTwin_signed.p7s
    ├── Permissions_HospitalDashboard.xml
    ├── Permissions_HospitalDashboard_signed.p7s
    ├── Permissions_ClinicalAlertsEngine.xml
    ├── Permissions_ClinicalAlertsEngine_signed.p7s
    ├── Permissions_ResourceSim.xml
    ├── Permissions_ResourceSim_signed.p7s
    ├── Permissions_RoutingService.xml
    ├── Permissions_RoutingService_signed.p7s
    ├── Permissions_CloudDiscoveryService.xml
    └── Permissions_CloudDiscoveryService_signed.p7s
```

**Deployment note:** CA private keys (`identity_ca_key.pem`, `permissions_ca_key.pem`) are used only for signing during the build/deploy phase. They are **never** deployed to runtime containers. Only the CA certificates (public keys) are deployed.

---

## Security Artifact Generation

Security artifacts divide into two categories with different lifecycle characteristics:

| Artifact Class | Changes When... | Generation Tool | Invocation |
|---|---|---|---|
| **PKI ceremony** — CA certs/keys, leaf certs/keys, CRL, PSK passphrases | New role added, key compromise, revocation test, passphrase rotation | Python script (`scripts/generate_pki.py`) | Manual or CI setup — not part of the CMake build |
| **PKCS#7 signing** — governance `.p7s`, permissions `.p7s` | Governance or permissions XML edited | CMake `add_custom_command` calling `openssl smime` | Automatic at build time — re-signs when source XML changes |

This separation exists because:
- CA and leaf **key material must not regenerate on every clean build** — that would invalidate every certificate in the tree and break deterministic builds.
- Governance and permissions **signed files must stay in sync with their source XML** — a stale `.p7s` after an XML edit causes a cryptic runtime PKCS#7 validation failure. CMake dependency tracking eliminates that class of bugs.

### PKI Ceremony — Python Script

The PKI ceremony script (`scripts/generate_pki.py`) uses the Python `cryptography` library for all key generation, certificate issuance, CRL management, and PSK passphrase creation. No platform-specific shell scripting — the script runs identically on Linux, Windows, and macOS.

**Subcommands:**

| Subcommand | Description |
|---|---|
| `generate_pki.py init` | Full PKI bootstrap: creates both CAs, all 11 leaf certs, empty CRL, PSK passphrase files, and the complete `interfaces/security/` directory tree. Idempotent — skips existing artifacts unless `--force` is passed. |
| `generate_pki.py issue --role <role> --instance <instance> --module <module>` | Issue a single new leaf certificate (e.g., adding a new OR). |
| `generate_pki.py revoke --serial <n>` | Add a serial number to the CRL and re-sign it. |
| `generate_pki.py rotate-psk --domain <domain>` | Generate a new high-entropy PSK passphrase for the specified domain, following the primary+extra rotation pattern. |

The participant role inventory (role names, instance suffixes, module OUs, domain assignments) is defined as a data structure within the script, derived from the [Participant Role Inventory](#participant-role-inventory). Adding a new role requires adding one entry to this table.

**Dependencies:**
- `cryptography` — added to `requirements.txt` (or `requirements-dev.txt` if build-time and runtime deps are separated)
- Python 3.10+ — already a project requirement

**Output layout:** The script writes directly to `interfaces/security/` following the [Security File Structure](#security-file-structure). Source XML files (governance, permissions) are **not** generated by this script — they are authored by hand and committed to version control.

### PKCS#7 Signing — CMake + OpenSSL

Governance and permissions XML files are authored in the source tree. Their PKCS#7 signed counterparts (`.p7s`) are generated at **build time** by CMake custom commands that call the `openssl` CLI directly.

**OpenSSL discovery:** `find_package(OpenSSL)` must be called **after** `find_package(RTIConnextDDS)` so that the RTI-provided `FindOpenSSL.cmake` module (from `rticonnextdds-cmake-utils`) is on the module path. This prefers the OpenSSL installation bundled with the user's Connext host target, ensuring version compatibility between the `openssl` CLI used for signing at build time and the OpenSSL library linked at runtime by the Security Plugins.

```cmake
# Top-level CMakeLists.txt (after RTIConnextDDS is found)
find_package(OpenSSL REQUIRED)
```

**CMake integration** (`interfaces/security/CMakeLists.txt`):

```cmake
# --- Governance signing ---
set(PERMISSIONS_CA "${CMAKE_CURRENT_SOURCE_DIR}/ca/permissions_ca.pem")
set(PERMISSIONS_CA_KEY "${CMAKE_CURRENT_SOURCE_DIR}/ca/permissions_ca_key.pem")

foreach(domain Procedure Hospital Observability)
  set(GOV_XML "${CMAKE_CURRENT_SOURCE_DIR}/governance/Governance_${domain}.xml")
  set(GOV_P7S "${CMAKE_CURRENT_BINARY_DIR}/governance/Governance_${domain}_signed.p7s")

  add_custom_command(
    OUTPUT  ${GOV_P7S}
    COMMAND ${OPENSSL_RUNTIME_EXECUTABLE} smime -sign
            -in ${GOV_XML}
            -signer ${PERMISSIONS_CA}
            -inkey ${PERMISSIONS_CA_KEY}
            -outform PEM -nodetach
            -out ${GOV_P7S}
    DEPENDS ${GOV_XML} ${PERMISSIONS_CA} ${PERMISSIONS_CA_KEY}
    COMMENT "Signing Governance_${domain}.xml"
  )
  list(APPEND SIGNED_ARTIFACTS ${GOV_P7S})
endforeach()

# --- Permissions signing (same pattern) ---
set(PERM_ROLES
  RobotController BedsideMonitor CameraSim ProcedurePublisher
  DeviceTelemetryGw DigitalTwin HospitalDashboard
  ClinicalAlertsEngine ResourceSim RoutingService CloudDiscoveryService
)

foreach(role ${PERM_ROLES})
  set(PERM_XML "${CMAKE_CURRENT_SOURCE_DIR}/permissions/Permissions_${role}.xml")
  set(PERM_P7S "${CMAKE_CURRENT_BINARY_DIR}/permissions/Permissions_${role}_signed.p7s")

  add_custom_command(
    OUTPUT  ${PERM_P7S}
    COMMAND ${OPENSSL_RUNTIME_EXECUTABLE} smime -sign
            -in ${PERM_XML}
            -signer ${PERMISSIONS_CA}
            -inkey ${PERMISSIONS_CA_KEY}
            -outform PEM -nodetach
            -out ${PERM_P7S}
    DEPENDS ${PERM_XML} ${PERMISSIONS_CA} ${PERMISSIONS_CA_KEY}
    COMMENT "Signing Permissions_${role}.xml"
  )
  list(APPEND SIGNED_ARTIFACTS ${PERM_P7S})
endforeach()

add_custom_target(security_artifacts ALL DEPENDS ${SIGNED_ARTIFACTS})

install(DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/governance/
        DESTINATION security/governance FILES_MATCHING PATTERN "*.p7s")
install(DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/permissions/
        DESTINATION security/permissions FILES_MATCHING PATTERN "*.p7s")
```

**Key properties:**
- Source XML is in the source tree and committed to version control.
- `.p7s` outputs go to the **build tree** — never committed.
- Editing a governance or permissions XML file triggers automatic re-signing on the next `cmake --build`.
- `cmake --install` copies the signed `.p7s` files to the install tree under `security/`.
- The Permissions CA private key must be present in the source tree for signing. It is excluded from Docker deploy artifacts at the `install()` / Dockerfile level (see [Security File Structure](#security-file-structure) deployment note).

### Artifact Source-of-Truth Summary

| Artifact | Lives In | Committed? | Generated By |
|---|---|---|---|
| CA certs + keys | `interfaces/security/ca/` (source tree) | Yes (keys in `.gitignore` or encrypted) | `generate_pki.py init` |
| Leaf certs | `interfaces/security/certs/` (source tree) | Yes | `generate_pki.py init` or `issue` |
| Leaf private keys | `interfaces/security/private/` (source tree) | Yes (in `.gitignore` or encrypted) | `generate_pki.py init` or `issue` |
| CRL | `interfaces/security/crl/` (source tree) | Yes | `generate_pki.py init` or `revoke` |
| PSK passphrases | `interfaces/security/psk/` (source tree) | Yes (in `.gitignore` or encrypted) | `generate_pki.py init` or `rotate-psk` |
| Governance XML | `interfaces/security/governance/` (source tree) | Yes | Authored by hand |
| Governance `.p7s` | `<build>/governance/` → installed to `security/governance/` | No (build output) | CMake `add_custom_command` |
| Permissions XML | `interfaces/security/permissions/` (source tree) | Yes | Authored by hand |
| Permissions `.p7s` | `<build>/permissions/` → installed to `security/permissions/` | No (build output) | CMake `add_custom_command` |

> **Secret management note:** Private keys and PSK passphrase files should be excluded from version control via `.gitignore` for public/shared repositories. For the medtech suite demo, committing them to a private repository is acceptable since all keys are self-signed demo artifacts with no production trust. For production deployments, use a secrets manager or encrypted storage.

---

## Concrete Requirements Summary

| Requirement | Value |
|-------------|-------|
| Unauthenticated participant join policy | `FALSE` on all secured domains (Procedure, Hospital, Observability) |
| `control`-tag data protection | `ENCRYPT` |
| `control`-tag metadata protection | `ENCRYPT_WITH_ORIGIN_AUTHENTICATION` |
| `clinical`-tag data protection | `ENCRYPT` |
| `clinical`-tag metadata protection | `ENCRYPT` |
| `operational`-tag data protection | `SIGN` |
| `operational`-tag metadata protection | `SIGN` |
| Hospital domain data protection | `ENCRYPT` |
| Hospital domain metadata protection | `ENCRYPT` |
| Discovery protection (Procedure, Hospital) | `ENCRYPT` |
| Discovery protection (Observability) | `SIGN` |
| Observability domain data protection | `ENCRYPT` |
| Observability domain metadata protection | `SIGN` |
| RTPS protection (all domains) | `SIGN` |
| PSK protection (domains with PSK participants) | `SIGN` |
| CRL revocation effective within | 60 s of CRL file update |
| Certificate rotation pickup | 120 s of certificate file replacement |
| Certificate validity period | 2 years (per leaf cert `<validity>`) |
| Permissions validity period | 2 years (per grant `<validity>`) |
| PSK usage scope | V2+ device gateways only — not for core modules |
| PSK passphrase source | `file:` URI — never inline `data:,` |
| PSK rotation strategy | Primary + extra passphrase files, sequential update |
| `files_poll_interval` | `5` seconds (all participants) |
| `max_receiver_specific_macs` | `16` (control-tag participants with origin auth) |
| Permissions grant wildcard element | `<subject_name_expression>` (not `<subject_name>`) |
| Permissions document granularity | One file per participant role |
| Compression + encryption | **Discouraged** — CRIME/BREACH risk |
| Symmetric cipher algorithm | AES-256-GCM (default) |
| STRIDE protection level (control tag) | STIDE Domain Outsider + STDE Domain/Topic Insider + STIDE Topic Outsider |
| `enable_key_revision` | `TRUE` on all secured domains |
| Governance `domain_rule` structure (Procedure) | Three separate `<domain_rule>` entries (one per tag) |
| PKI ceremony tool | `scripts/generate_pki.py` (Python `cryptography` library) |
| PKCS#7 signing tool | CMake `add_custom_command` calling `openssl smime` |
| OpenSSL CMake discovery | `find_package(OpenSSL)` after `find_package(RTIConnextDDS)` — prefers RTI-provided `FindOpenSSL.cmake` |
