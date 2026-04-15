# Spec: Security

Behavioral specifications for the security layer of the medtech suite. All scenarios here correspond to Connext Security Plugins behaviors: authentication, access control, topic-level protection, governance enforcement, origin authentication, PSK, and certificate lifecycle.

All scenarios are tagged `@security` and require Connext Security Plugins, governance files, and permissions files to be present. Security spec scenarios are derived from the threat model and architecture defined in [vision/security.md](../vision/security.md).

---

## Summary of Concrete Requirements

| Requirement | Value | Source |
|-------------|-------|--------|
| Unauthenticated participant join policy | `FALSE` on all secured domains (Procedure, Hospital, Observability) | vision/security.md — Domain Governance |
| `enable_key_revision` | `TRUE` on all secured domains | vision/security.md — Domain Governance |
| Governance `domain_rule` structure (Procedure) | Three separate `<domain_rule>` entries (one per tag) | vision/security.md — Procedure Domain Governance |
| `control`-tag data protection | `ENCRYPT` | vision/security.md — Procedure Domain Governance |
| `control`-tag metadata protection | `ENCRYPT_WITH_ORIGIN_AUTHENTICATION` | vision/security.md — Procedure Domain Governance |
| `clinical`-tag data protection | `ENCRYPT` | vision/security.md — Procedure Domain Governance |
| `clinical`-tag metadata protection | `ENCRYPT` | vision/security.md — Procedure Domain Governance |
| `operational`-tag data protection | `SIGN` | vision/security.md — Procedure Domain Governance |
| `operational`-tag metadata protection | `SIGN` | vision/security.md — Procedure Domain Governance |
| Hospital Integration databus data/metadata protection | `ENCRYPT` / `ENCRYPT` | vision/security.md — Hospital Domain Governance |
| Observability domain data/metadata protection | `ENCRYPT` / `SIGN` | vision/security.md — Observability Domain Governance |

| CRL revocation effective within | 60 s of CRL file update | vision/security.md — Certificate Revocation |
| Certificate rotation pickup | 120 s of certificate file replacement (same subject name and public key required) | vision/security.md — Certificate Rotation |
| `files_poll_interval` | `5` seconds | vision/security.md — Design Considerations |
| `max_receiver_specific_macs` | `16` (control-tag participants) | vision/security.md — Design Considerations |
| PSK passphrase source | `file:` URI (never inline `data:,`) | vision/security.md — PSK Configuration |
| Permissions grant wildcard element | `<subject_name_expression>` | vision/security.md — Identity Model |
| Permissions document granularity | One file per participant role | vision/security.md — Permissions Model |

---

## Authentication

### Scenario: Authenticated participant joins the Procedure DDS domain

`@security` `@integration`

**Given** a participant with a valid identity certificate signed by the Identity CA, and a permissions document granting domain join on the Procedure DDS domain
**When** the participant creates a DomainParticipant on the Procedure DDS domain
**Then** the DomainParticipant is created successfully, and the participant completes mutual authentication with other Procedure DDS domain participants

### Scenario: Unauthenticated participant is rejected from the Procedure databuses

`@security` `@integration`

**Given** a participant with no identity certificate (or an unsigned/self-signed certificate not chained to the Identity CA)
**When** the participant attempts to create a DomainParticipant on the Procedure DDS domain
**Then** DomainParticipant creation fails, and no data is exchanged with other Procedure DDS domain participants

### Scenario: Participant with expired certificate is rejected

`@security` `@integration`

**Given** a participant whose identity certificate has a `notAfter` date in the past
**When** the participant attempts to create a DomainParticipant on any secured domain
**Then** DomainParticipant creation fails

### Scenario: PSK-authenticated participant joins via Lightweight Security Plugins

`@security` `@integration`

**Given** a V2+ device gateway participant configured with `BuiltinQosSnippetLib::Feature.LightweightSecurity.Enable` and a PSK passphrase file at the `file:` URI specified in `dds.sec.crypto.rtps_psk_secret_passphrase`
**When** the participant creates a DomainParticipant on a domain with `rtps_psk_protection_kind != NONE`
**Then** the participant joins the domain, and RTPS bootstrap traffic is protected by the PSK

### Scenario: PSK participant with wrong passphrase is rejected

`@security` `@integration`

**Given** a participant configured with a PSK passphrase that does not match the domain's expected passphrase
**When** the participant attempts to join the domain
**Then** the participant cannot communicate with any existing domain participants

---

## Access Control

### Scenario: Authorized publisher writes to a permitted topic

`@security` `@integration`

**Given** a `robot-controller` participant with permissions granting subscribe on `RobotCommand` (control tag)
**When** another participant with write permissions publishes a `RobotCommand` sample
**Then** the `robot-controller` receives the sample

### Scenario: Unauthorized publisher is denied write access

`@security` `@integration`

**Given** a `camera-sim` participant (operational-tag only) with no write permission on `RobotCommand`
**When** the `camera-sim` attempts to create a DataWriter for `RobotCommand`
**Then** DataWriter creation fails, and no data is published to `RobotCommand`

### Scenario: Unauthorized subscriber receives no data

`@security` `@integration`

**Given** a `resource-sim` participant with no subscribe permission on `PatientVitals`
**When** a `bedside-monitor` publishes `PatientVitals` samples
**Then** the `resource-sim` receives zero samples on `PatientVitals` (DataReader creation fails or receives no matched data)

### Scenario: Dashboard participant is read-only across all Hospital Integration databus topics

`@security` `@integration`

**Given** a `hospital-dashboard` participant whose permissions grant only subscribe on Hospital Integration databus topics
**When** the `hospital-dashboard` attempts to create a DataWriter for any Hospital Integration databus topic
**Then** DataWriter creation fails for every Hospital Integration databus topic

### Scenario: Default deny rule blocks unlisted topics

`@security` `@integration`

**Given** a `bedside-monitor` participant whose permissions explicitly allow publish on `PatientVitals`, `WaveformData`, and `AlarmMessages` only
**When** the `bedside-monitor` attempts to create a DataWriter for `RobotCommand`
**Then** DataWriter creation fails due to the trailing `<deny_rule>` in the permissions grant

---

## Topic Protection

### Scenario: Control-tag topic data is encrypted in transit

`@security` `@integration`

**Given** the Procedure DDS domain governance specifies `data_protection_kind=ENCRYPT` for `control`-tag topics
**When** a `robot-controller` publishes a `RobotState` sample
**Then** the RTPS payload on the wire is encrypted (not readable by a passive network observer), and an authorized subscriber decrypts and receives the sample correctly

### Scenario: Clinical-tag topic data is encrypted in transit

`@security` `@integration`

**Given** the Procedure DDS domain governance specifies `data_protection_kind=ENCRYPT` for `clinical`-tag topics
**When** a `bedside-monitor` publishes a `PatientVitals` sample
**Then** the RTPS payload on the wire is encrypted, and an authorized subscriber decrypts and receives the sample correctly

### Scenario: Operational-tag topic data is signed but not encrypted

`@security` `@integration`

**Given** the Procedure DDS domain governance specifies `data_protection_kind=SIGN` for `operational`-tag topics
**When** a `camera-sim` publishes a `CameraFrame` sample
**Then** the RTPS payload on the wire is integrity-protected (signed) but readable by a passive observer, and an authorized subscriber verifies integrity and receives the sample

### Scenario: Participant without decryption keys receives no encrypted data

`@security` `@integration`

**Given** a rogue participant that has domain-join permission but no topic-level subscribe permission on an `ENCRYPT`-protected topic
**When** samples are published on that topic
**Then** the rogue participant cannot decrypt the data (no key material is exchanged for unauthorized endpoints)

---

## Origin Authentication

### Scenario: Subscriber verifies origin of control-tag sample

`@security` `@integration`

**Given** the Procedure DDS domain governance specifies `metadata_protection_kind=ENCRYPT_WITH_ORIGIN_AUTHENTICATION` for `RobotCommand`, and `max_receiver_specific_macs=16` is set on all control-tag participants
**When** a `robot-controller` receives a `RobotCommand` sample
**Then** the `robot-controller` can verify the sample originated from the specific DomainParticipant that published it (receiver-specific MAC validation succeeds)

### Scenario: Spoofed origin is detected and rejected

`@security` `@integration`

**Given** origin authentication is enabled on `SafetyInterlock`
**When** an attacker replays a captured `SafetyInterlock` message with a forged origin
**Then** the receiver detects the MAC mismatch and discards the message; a security event is logged via the Connext Logging API

### Scenario: Origin authentication is NOT applied to operational-tag topics

`@security` `@integration`

**Given** the Procedure DDS domain governance specifies `metadata_protection_kind=SIGN` (without `_WITH_ORIGIN_AUTHENTICATION`) for `operational`-tag topics
**When** a `camera-sim` publishes a `CameraFrame` sample
**Then** no receiver-specific MACs are included in the message (origin authentication overhead is avoided for high-bandwidth operational data)

---

## Governance Enforcement

### Scenario: Governance rejects participant that cannot join

`@security` `@integration`

**Given** the Procedure DDS domain governance sets `enable_join_access_control=TRUE`
**When** a participant whose permissions do not include a domain-join grant for the Procedure DDS domain attempts to create a DomainParticipant
**Then** DomainParticipant creation fails

### Scenario: Discovery traffic is encrypted on the Procedure DDS domain

`@security` `@integration`

**Given** the Procedure DDS domain governance sets `discovery_protection_kind=ENCRYPT`
**When** two authenticated participants discover each other on the Procedure DDS domain
**Then** endpoint announcement traffic is encrypted on the wire (not readable by a passive observer without domain keys)

### Scenario: PSK protection covers bootstrap discovery

`@security` `@integration`

**Given** the Procedure DDS domain governance sets `rtps_psk_protection_kind=SIGN`
**When** a new participant begins the initial discovery handshake before PKI authentication completes
**Then** the bootstrap RTPS messages are integrity-protected by the PSK, and a domain outsider without the PSK cannot inject discovery traffic

---

## Routing Service

### Scenario: Routing Service bridges authorized topics from Procedure to Hospital

`@security` `@integration` `@routing`

**Given** a `routing-service` participant with a valid identity certificate and permissions granting subscribe on Procedure DDS domain topics (`RobotState`, `PatientVitals`, `AlarmMessages`, `DeviceTelemetry`, `ProcedureContext`, `ProcedureStatus`) and publish on the corresponding Hospital Integration databus topics
**When** data is published on the Procedure DDS domain
**Then** the `routing-service` subscribes, decrypts, re-encrypts, and publishes the data on the Hospital Integration databus; Hospital Integration databus subscribers receive the data

### Scenario: Routing Service cannot publish back to the Procedure DDS domain

`@security` `@integration` `@routing`

**Given** the `routing-service` permissions grant **no publish** on any Procedure DDS domain topic
**When** the `routing-service` attempts to create a DataWriter on a Procedure DDS domain topic
**Then** DataWriter creation fails — data flow is strictly Procedure → Hospital

### Scenario: Routing Service with invalid certificate is rejected

`@security` `@integration` `@routing`

**Given** a Routing Service instance configured with an identity certificate not signed by the Identity CA
**When** the Routing Service attempts to create DomainParticipants on the Procedure and Hospital Integration databuses
**Then** both DomainParticipant creations fail; no bridging occurs

---

## Certificate Lifecycle

### Scenario: Revoked certificate is rejected after CRL update

`@security` `@integration`

**Given** a `bedside-monitor` participant is actively publishing `PatientVitals`, and the CRL file is updated to include the `bedside-monitor`'s certificate serial number
**When** the Security Plugins' file tracker detects the CRL change (within `files_poll_interval` seconds)
**Then** existing sessions with the revoked participant are terminated within 60 seconds of the CRL file update, and subsequent authentication handshakes with the revoked certificate are rejected

### Scenario: Rotated certificate is picked up without restart

`@security` `@integration`

**Given** a `robot-controller` participant is running with identity certificate `robot-controller.pem`
**When** the certificate file is replaced on disk with a new certificate signed by the same Identity CA, retaining the same subject name and public key
**Then** the `robot-controller` propagates the updated certificate to peers within 120 seconds of file replacement, without restarting the participant process and without a full re-authentication handshake

### Scenario: PSK passphrase rotation via file update

`@security` `@integration`

**Given** all Procedure DDS domain PSK participants are using passphrase file `procedure_domain_psk.txt` with passphrase ID `1`
**When** the passphrase file is updated to contain a new passphrase with ID `2` (following the primary+extra rotation pattern described in vision/security.md)
**Then** within `files_poll_interval` seconds, all participants load the new passphrase and continue communicating without message loss

---

## Security Logging

### Scenario: Security events are captured via the Connext Logging API

`@security` `@integration`

**Given** all participants have the Connext Logging API configured with USER category verbosity and Monitoring Library 2.0 forwarding user logs to Collector Service
**When** a security event occurs (e.g., authentication failure, permission denial, CRL revocation)
**Then** the security event is logged via the Connext Logging API and forwarded by Monitoring Library 2.0 to Collector Service, where it is exported to Grafana Loki and received by the log aggregation backend

---

*All scenarios above are tagged `@security` and are gated on V2.0. They must all pass before Phase 7 (Security) is considered complete.*
