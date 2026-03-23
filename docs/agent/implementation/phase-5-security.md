# Phase 5: Security

**Goal:** Enable RTI Connext Security Plugins across all domains, establish governance and permissions infrastructure, and verify all security spec scenarios from `spec/security.md`.

**Depends on:** Phases 1–4 (all functional modules must be complete and passing before security is layered on)
**Blocks:** Nothing (terminal phase for V2.0)

---

## Step 5.1 — PKI Setup & Certificate Issuance

**Work:** Author the `scripts/generate_pki.py` Python script and run the initial PKI ceremony. See [vision/security.md — Security Artifact Generation](../vision/security.md#security-artifact-generation) for the generation architecture.

1. **Author `scripts/generate_pki.py`.** Implement the PKI ceremony script using the Python `cryptography` library. The script must support the `init`, `issue`, `revoke`, and `rotate-psk` subcommands described in vision/security.md. The participant role inventory (role names, instance suffixes, module OUs) is a data structure within the script, derived from the [Participant Role Inventory](../vision/security.md#participant-role-inventory).
2. **Add `cryptography` to `requirements.txt`** (or `requirements-dev.txt` if build/runtime deps are separated).
3. **Run `generate_pki.py init`.** This bootstraps the full PKI:
   - Identity CA (`identity_ca.pem` / `identity_ca_key.pem`) — RSA-2048 or ECDSA P-256, 10-year validity
   - Permissions CA (`permissions_ca.pem` / `permissions_ca_key.pem`) — same key type/validity
   - All 11 leaf identity certificates with subject `CN=<role>/<instance>, O=MedtechSuite, OU=<module>`, signed by Identity CA, 2-year validity
   - Empty CRL signed by the Identity CA
   - PSK passphrase files: `procedure_domain_psk.txt` and `hospital_domain_psk.txt` with `1:<high-entropy-passphrase>` format
   - Complete `interfaces/security/` directory tree per [vision/security.md — Security File Structure](../vision/security.md#security-file-structure)
4. **Verify idempotency.** Running `generate_pki.py init` a second time must skip existing artifacts (no regeneration). Running with `--force` must regenerate everything.

**Test gate:**
- [ ] `generate_pki.py init` completes without errors on Linux (and Windows/macOS if available)
- [ ] All 11 leaf certificates validate against the Identity CA (`openssl verify` or programmatic check)
- [ ] CRL file is parseable and initially contains zero revoked serial numbers
- [ ] PSK passphrase files exist with valid `<id>:<passphrase>` format
- [ ] CA private keys are present in the source tree but excluded from deploy/Docker artifacts
- [ ] `generate_pki.py revoke --serial <n>` adds the serial to the CRL and re-signs it
- [ ] `generate_pki.py issue --role <role> --instance <instance> --module <module>` produces a valid leaf cert

---

## Step 5.2 — Governance Documents

**Work:** Author the three governance XML files and sign them with the Permissions CA.

1. **Author `Governance_Procedure.xml`.** Implement the Procedure domain governance from [vision/security.md — Procedure Domain Governance](../vision/security.md#procedure-domain-governance). **This file must contain three separate `<domain_rule>` entries** — one per domain tag (`control`, `clinical`, `operational`) — because `topic_access_rules` within a single `domain_rule` cannot differentiate protection by domain tag. Each `domain_rule` selects its tag via `<tag>` and contains the tag-appropriate `topic_access_rules`:
   - Shared domain-level settings (all three rules): `allow_unauthenticated_participants=FALSE`, `enable_join_access_control=TRUE`, `discovery_protection_kind=ENCRYPT`, `liveliness_protection_kind=SIGN`, `rtps_protection_kind=SIGN`, `rtps_psk_protection_kind=SIGN`, `enable_key_revision=TRUE`
   - `control` tag rule: `ENCRYPT` data / `ENCRYPT_WITH_ORIGIN_AUTHENTICATION` metadata
   - `clinical` tag rule: `ENCRYPT` / `ENCRYPT`
   - `operational` tag rule: `SIGN` / `SIGN`
   - All topic rules: `enable_discovery_protection=TRUE`, `enable_read_access_control=TRUE`, `enable_write_access_control=TRUE`
2. **Author `Governance_Hospital.xml`.** Implement the Hospital domain governance table from [vision/security.md — Hospital Domain Governance](../vision/security.md#hospital-domain-governance). Include `enable_key_revision=TRUE`.
3. **Author `Governance_Observability.xml`.** Implement the Observability domain governance table from [vision/security.md — Observability Domain Governance](../vision/security.md#observability-domain-governance). Include `enable_key_revision=TRUE`.
4. **Wire CMake signing for governance.**** Add `interfaces/security/CMakeLists.txt` with `add_custom_command` targets that call `openssl smime -sign` on each governance XML, as described in [vision/security.md — PKCS#7 Signing — CMake + OpenSSL](../vision/security.md#pkcs7-signing--cmake--openssl). `find_package(OpenSSL)` must be called **after** `find_package(RTIConnextDDS)` to prefer the RTI-provided `FindOpenSSL.cmake` module, which can locate the OpenSSL bundled with the Connext host target installation.
5. **Verify build-time signing.** Run `cmake --build` and confirm the `.p7s` files are produced in the build tree. Edit a governance XML and rebuild — the `.p7s` must regenerate.

**Test gate:**
- [ ] Each governance XML validates against the RTI governance XSD schema
- [ ] Each signed `.p7s` file verifies against the Permissions CA
- [ ] `must_interpret="false"` is used on any elements that may not be recognized by older Security Plugins versions
- [ ] `Governance_Procedure.xml` contains exactly three `<domain_rule>` entries (one per domain tag)
- [ ] `enable_key_revision=TRUE` is set in all governance documents
- [ ] Editing a governance XML and rebuilding regenerates the corresponding `.p7s`
- [ ] `find_package(OpenSSL)` is called after `find_package(RTIConnextDDS)` in CMakeLists.txt

---

## Step 5.3 — Participant Permissions

**Work:** Author per-participant permissions files and sign them with the Permissions CA.

1. **Author one permissions XML per participant role** (11 files total). Each file contains:
   - A single `<grant>` with `<subject_name_expression>` matching the role's wildcard pattern (e.g., `CN=robot-controller/*,O=MedtechSuite,OU=surgical-procedure`)
   - `<validity>` with 2-year window matching the leaf cert validity period
   - `<allow_rule>` entries granting only the pub/sub permissions listed in the [Permission Grants — Summary](../vision/security.md#permission-grants--summary)
   - Partition-aware permissions using wildcard expressions (e.g., `room/*/procedure/*`) where applicable
   - A trailing `<deny_rule>` catching all unlisted topics/domains (default deny posture)
2. **Wire CMake signing for permissions.** Add `add_custom_command` targets for each permissions XML in `interfaces/security/CMakeLists.txt` (same pattern as governance signing). Verify build-time re-signing on XML edit.

**Test gate:**
- [ ] Each permissions XML validates against the RTI permissions XSD schema
- [ ] Each signed `.p7s` file verifies against the Permissions CA
- [ ] Every grant uses `<subject_name_expression>` (not `<subject_name>`)
- [ ] Every grant ends with a `<deny_rule>`
- [ ] Permissions grant matrix matches the vision/security.md permission tables exactly
- [ ] Editing a permissions XML and rebuilding regenerates the corresponding `.p7s`

---

## Step 5.4 — Enable Security in All Modules

**Work:** Wire the `dds.sec.*` QoS properties into every participant's XML configuration.

1. **Add security QoS properties** to each participant profile in `Participants.xml`, using the template from [vision/security.md — Security QoS Property Reference](../vision/security.md#security-qos-property-reference):
   - `dds.sec.auth.identity_ca`, `dds.sec.auth.identity_certificate`, `dds.sec.auth.private_key`, `dds.sec.auth.crl`
   - `dds.sec.access.permissions_ca`, `dds.sec.access.governance`, `dds.sec.access.permissions`
   - `com.rti.serv.secure.files_poll_interval=5`
2. **Add origin authentication tuning** for control-tag participants: `com.rti.serv.secure.cryptography.max_receiver_specific_macs=16`
   > **CRITICAL:** The default value of `max_receiver_specific_macs` is **0**, which **silently disables** origin authentication even when governance specifies `ENCRYPT_WITH_ORIGIN_AUTHENTICATION`. Omitting this property from control-tag participant profiles is the highest-severity failure mode for the safety-critical data path — commands to the robot would lack source verification. This property **must** be explicitly set on every participant that joins a domain with `_WITH_ORIGIN_AUTHENTICATION` governance rules.
3. **Configure `${MEDTECH_SECURITY_DIR}`** in `setup.bash` pointing to `interfaces/security/`.
4. **Verify all modules start and communicate** with security enabled — every Phase 1–4 functional behavior must continue to work.

**Test gate:**
- [ ] All 11 participant types start successfully with security enabled
- [ ] Mutual authentication handshakes complete between all participant pairs on each domain
- [ ] All Phase 1 through Phase 4 functional tests pass with zero regressions

---

## Step 5.5 — Routing Service Security

**Work:** Configure Routing Service as an authenticated, authorized secure bridge.

1. **Wire security QoS properties** into all 4 Routing Service DomainParticipant profiles (Procedure-control, Procedure-clinical, Procedure-operational, Hospital-bridge).
   - Each references the governance document for its domain
   - All share the `routing-service` identity certificate
2. **Verify one-way bridge enforcement.** Routing Service can subscribe on Procedure and publish on Hospital, but cannot publish on Procedure or subscribe on Hospital.
3. **Verify secure-to-secure relay.** Data is decrypted from Procedure domain, re-encrypted for Hospital domain.

**Test gate:**
- [ ] `routing-service` authenticates on both Procedure and Hospital domains
- [ ] Bridged topics arrive correctly on Hospital domain
- [ ] DataWriter creation on Procedure domain is denied for `routing-service`
- [ ] DataReader creation on Hospital domain is denied for `routing-service`

---

## Step 5.6 — Cloud Discovery Service Security

**Work:** Secure the discovery relay to prevent unauthorized discovery injection.

1. **Wire security QoS properties** into the Cloud Discovery Service configuration.
   - Identity certificate: `cloud-discovery-service.pem`
   - Governance: references all domain governance files (Procedure + Hospital + Observability)
   - Permissions: domain-join only on all functional domains, no topic pub/sub grants
2. **Verify authenticated discovery.** Authenticated participants discover each other via CDS; unauthenticated participants are rejected.

**Test gate:**
- [ ] Cloud Discovery Service starts with security enabled
- [ ] Authenticated participants discover each other through CDS
- [ ] A participant without valid credentials cannot discover other participants through CDS

---

## Step 5.7 — Certificate Lifecycle

**Work:** Validate dynamic CRL revocation and certificate rotation.

1. **CRL revocation test.** Revoke a participant's certificate by adding its serial number to the CRL, replacing the CRL file on disk, and verifying the participant is ejected within 60 seconds.
2. **Certificate rotation test.** Replace a participant's identity certificate on disk with a new certificate (signed by the same Identity CA, retaining the **same subject name and public key**). Verify the updated certificate is propagated to peers within 120 seconds without process restart. Note: dynamic renewal does not support public key changes — if a new key pair is required, the participant must be restarted.
3. **PSK rotation test.** Follow the primary+extra rotation procedure described in [vision/security.md — PSK Runtime Rotation](../vision/security.md#psk-runtime-rotation). Verify all PSK participants continue communicating with zero message loss during the transition.

**Test gate:**
- [ ] Revoked participant loses communication within 60 seconds of CRL update
- [ ] Rotated certificate is picked up within 120 seconds
- [ ] PSK rotation via file update succeeds without message loss
- [ ] `files_poll_interval=5` is verified as the polling rate used by all participants

---

## Step 5.8 — Security Spec Verification

**Work:** Execute every scenario in `spec/security.md` and confirm all pass.

1. **Run all `@security` scenarios.** Every GWT scenario in `spec/security.md` must pass.
2. **Run all Phase 1–4 tests with security enabled.** Zero regressions allowed — security is transparent to functional behavior.
3. **Negative testing.** Verify that every denial scenario (unauthenticated join, unauthorized pub/sub, revoked cert, wrong PSK) produces the expected rejection and a corresponding security log event via the Connext Logging API (forwarded to Grafana Loki through Collector Service).

**Test gate:**
- [ ] All `spec/security.md` scenarios pass
- [ ] All Phase 1–4 tests pass unchanged with security enabled
- [ ] Unauthorized participants are rejected across all domains
- [ ] Revoked participants are denied after CRL update
- [ ] Routing Service bridges only authorized topics
- [ ] Security events are logged via the Connext Logging API and forwarded to Grafana Loki for all denial scenarios
- [ ] `max_receiver_specific_macs=16` is confirmed active on all control-tag participants
- [ ] No DDS compression is enabled on any `ENCRYPT`-protected topic
