# Revision: Domain ID Migration

**Goal:** Bring all XML configuration, service configuration, application participant
definitions, IDL constants, application code, and tests into alignment with the
decade-offset domain numbering scheme adopted in
[vision/system-architecture.md — Domain Numbering Guide](../vision/system-architecture.md)
and [vision/data-model.md](../vision/data-model.md).

**Trigger:** Architecture revision session (commits `9f60b02`, `054ab6a`,
`8966886`, `e865ace`) updated all vision, spec, and implementation *descriptive*
documents to the new domain IDs and gateway model but did not create an
implementation revision file. Code and service XML therefore still use the
old assignments.

**Version impact:** Patch (`V1.4.x`) — no new capabilities, no IDL type changes,
no QoS semantic changes. All existing spec scenarios must continue to pass
after this revision, with updated domain ID expectations.

**Spec coverage:** No spec scenarios describe raw domain IDs by number
(they reference domains by name per the Domain Naming Rule in
[data-model.md](../vision/data-model.md)). Where tests hard-code domain IDs,
they are updated as part of this revision.

---

## Domain ID Mapping (Before → After)

| Domain Name | Old ID | New ID | Change |
|-------------|--------|--------|--------|
| Procedure (3 tags) | 10 | 10 | No change |
| Hospital (integration) | 11 | 20 | Reassigned |
| Orchestration (room-scoped) | 15 | 11 | Reassigned |
| Room Observability | 20 (Monitoring Library) | 19 | Reassigned + explicit domain entry |
| Hospital Observability | — | 29 | Added (Collector forwarding chain) |

---

## Procedure Controller Plane Decision

The architecture revision also changes the **Procedure Controller** from a
dual-domain application (Orchestration + Hospital) to a **room-level,
Orchestration-only** application. This is captured in
[vision/system-architecture.md — Participant Count Table](../vision/system-architecture.md)
and [vision/capabilities.md](../vision/capabilities.md).

**Consequence:** The `ProcedureController_Hospital` participant (Domain 20
read-only subscriber for `ProcedureStatus`, `ProcedureContext`, `PatientVitals`)
is removed. Procedure context data the controller needs is obtained from:

- `ProcedureStatus` and `ProcedureContext` — read from **Domain 10 operational
  tag** via a new `ProcedureController_Procedure_Operational` participant in
  `SurgicalParticipants.xml`. The controller is in the OR; reading directly
  from Domain 10 is architecturally correct and eliminates the cross-level
  Hospital dependency.
- `PatientVitals` — **dropped** from the controller. Patient vitals monitoring
  is the Hospital Dashboard's responsibility; including it in the room-level
  controller UI contradicts the deployment-plane boundary.

---

## Prerequisites

- All existing tests pass before starting any revision step.
- `vision/system-architecture.md`, `vision/data-model.md`, and
  `vision/capabilities.md` are the authoritative references for every
  change in this revision.

---

## Step DM.1 — Migrate `Domains.xml` ✅ `7506d9b`

### Work

- In `interfaces/domains/Domains.xml`, update the following `domain_id`
  attributes:
  - `Hospital` domain: `domain_id="11"` → `domain_id="20"`
  - `Orchestration` domain: `domain_id="15"` → `domain_id="11"`
  - Update header comments on both domains to reflect new IDs
- Add two new `<domain>` entries to `MedtechDomains`:
  - **`RoomObservability`** — `domain_id="19"`. No registered types or topics
    (Monitoring Library manages its own entities on this domain). Comment:
    "Monitoring Library 2.0 per-room telemetry. Collector Service subscribes
    here and forwards to Domain 29."
  - **`HospitalObservability`** — `domain_id="29"`. No registered types or
    topics. Comment: "Aggregated telemetry: room-forwarded (Dom 19) +
    hospital-native. Collector Service forwards to Domain 39 (V3.0)."
- Update the `<!-- Domain 11 — Hospital -->` comment block to
  `<!-- Domain 20 — Hospital (Integration) -->`.
- Update the `<!-- Domain 15 — Orchestration -->` comment block to
  `<!-- Domain 11 — Orchestration (Room-Scoped) -->`.
- Add a migration note block at the top of the file (XML comment) recording
  the old → new mapping so future readers understand the history.

> **Key insight:** Participant XML files reference domains via `domain_ref`
> using **symbolic names** (e.g., `MedtechDomains::Hospital`), not hard-coded
> IDs. Once this step is complete, all participant libraries automatically
> resolve to the new domain IDs with **no changes to participant XMLs** for
> existing mappings. Only the entries that are being added or removed require
> participant XML changes (Steps DM.3, DM.4).

### Test Gate

- [ ] `cmake --build build` succeeds (DDS XML is loaded and validated at
      runtime; ensure no parse errors from modified `Domains.xml`)
- [ ] `tests/tools/test_xml_validator.py` passes (CI XML schema check)
- [ ] `tests/lint/` passes (no new lint violations)
- [ ] All existing tests pass (`bash scripts/ci.sh` through the lint gate)

---

## Step DM.2 — Migrate Monitoring Library Domain in `Participants.xml` ✅ `7506d9b`

### Work

- In `interfaces/qos/Participants.xml`, locate the `<monitoring>` block
  inside the `Participants::Transport` profile that sets the Monitoring
  Library dedicated participant domain:
  ```xml
  <dedicated_participant>
      <domain_id>20</domain_id>
  </dedicated_participant>
  ```
  Update to:
  ```xml
  <dedicated_participant>
      <domain_id>19</domain_id>
  </dedicated_participant>
  ```
- This is the only numeric domain ID in `Participants.xml`. Update the
  adjacent comment if one exists.

### Test Gate

- [ ] `cmake --build build` succeeds
- [ ] All existing tests pass (no regression)
- [ ] `tests/lint/` passes

---

## Step DM.3 — Migrate `RoutingService.xml` ✅ `7506d9b`

### Work

**a) Fix the Hospital output participant domain ID:**

- Locate the `Hospital` output participant in `ProcedureToHospital`:
  ```xml
  <participant name="Hospital">
      <domain_id>11</domain_id>
  ```
  Update to `<domain_id>20</domain_id>` and update the adjacent comment
  from "Hospital domain (11)" to "Hospital domain (20 — integration)".

**b) Add the Orchestration input participant + ServiceCatalog route:**

Per [vision/system-architecture.md — Routing Service Deployment](../vision/system-architecture.md)
and [vision/data-model.md — Domain 20 Topics](../vision/data-model.md):
the per-room Routing Service must also bridge `ServiceCatalog` from
Domain 11 (Orchestration) → Domain 20 (Hospital) so the dashboard can
discover room GUIs and Service Hosts without joining Domain 11 directly.

- Add a 6th `<participant>` element to `ProcedureToHospital`:
  ```xml
  <!--
      RS::ProcedureOrchestration — reads ServiceCatalog from Domain 11
      (Orchestration, room-scoped) for northbound extraction to Domain 20.
  -->
  <participant name="ProcedureOrchestration">
      <domain_id>11</domain_id>
      <domain_participant_qos base_name="Participants::Transport">
          <partition>
              <name>
                  <element>procedure</element>
              </name>
          </partition>
      </domain_participant_qos>
  </participant>
  ```
- Add a `<topic_route>` in `StatusSession` for `ServiceCatalog`:
  ```xml
  <topic_route name="ServiceCatalogRoute">
      <publish_with_original_info>true</publish_with_original_info>
      <publish_with_original_timestamp>true</publish_with_original_timestamp>
      <input participant="ProcedureOrchestration">
          <topic_name>ServiceCatalog</topic_name>
          <datareader_qos base_name="TopicProfiles::ServiceCatalog"/>
      </input>
      <output participant="Hospital">
          <topic_name>ServiceCatalog</topic_name>
          <datawriter_qos base_name="TopicProfiles::ServiceCatalog"/>
      </output>
  </topic_route>
  ```

**c) Update disabled admin/monitoring domain references:**

- The disabled `<administration>` and `<monitoring>` blocks currently
  contain `<domain_id>20</domain_id>`. Update both to `<domain_id>19</domain_id>`
  (Room Observability) — this is the correct domain for RS telemetry
  per the observability plane design. Update adjacent comments.

**d) Update the top-level header comment** to reflect the 5→6 participant
change, the new domain ID mapping, and the ServiceCatalog route addition.

### Test Gate

- [ ] `tests/integration/test_routing_service.py` — `test_hospital_participant_on_domain_20`
      passes (renamed from `test_hospital_participant_on_domain_11`; asserts
      `domain_id == "20"`)
- [ ] `test_procedure_participants_on_domain_10` still passes
- [ ] New test `test_orchestration_participant_on_domain_11` passes
      (asserts the new `ProcedureOrchestration` input participant has `domain_id == "11"`)
- [ ] New test `test_service_catalog_is_bridged` passes (asserts `ServiceCatalog`
      appears in the `StatusSession` topic routes)
- [ ] `test_hospital_participant_has_no_domain_tag` still passes
- [ ] `test_administration_on_domain_19` and `test_monitoring_on_domain_19`
      pass (renamed from `_on_domain_20`; assertions updated to 19)
- [ ] All other routing service tests pass
- [ ] All existing tests pass (no regression)

---

## Step DM.4 — Migrate `CloudDiscoveryService.xml` ✅ `7506d9b`

### Work

- In `services/cloud-discovery-service/CloudDiscoveryService.xml`, update
  the `<allow_domain_id>` list:
  ```xml
  <allow_domain_id>10,11,15,20</allow_domain_id>
  ```
  Update to:
  ```xml
  <allow_domain_id>10,11,19,20,29</allow_domain_id>
  ```
  - Remove `15` (no longer exists)
  - Keep `10` (Procedure — unchanged)
  - Keep `11` (was Hospital, now Orchestration — correct)
  - Add `19` (Room Observability — new)
  - Keep `20` (now Hospital — correct)
  - Add `29` (Hospital Observability — new)

### Test Gate

- [ ] `tests/lint/` passes (XML schema check on CDS config)
- [ ] All existing tests pass (no regression)

---

## Step DM.5 — Migrate `OrchestrationParticipants.xml` ✅ `7506d9b`

### Work

- Update the file header comment: replace "Orchestration domain (Domain 15)"
  with "Orchestration domain (Domain 11)".
- Remove the `ProcedureController_Hospital` domain participant definition
  entirely (lines ~80–107 of the current file, the participant named
  `ProcedureController_Hospital` on `MedtechDomains::Hospital`). This
  participant, and the read-only subscribers for `ProcedureStatus`,
  `ProcedureContext`, and `PatientVitals` it contained, are replaced by
  the Domain 10 operational reads added in Step DM.6.
- The `HospitalDashboard` participant remains (it is on
  `MedtechDomains::Hospital` and will automatically resolve to Domain 20
  after Step DM.1). No change to its entity definitions is required; the
  `ServiceCatalog` reader should be added if not already present (see below).
- **Add** a `<data_reader>` for `ServiceCatalog` to the `HospitalDashboard`
  participant's `DashboardSubscriber` if it does not already exist:
  ```xml
  <data_reader name="ServiceCatalogReader"
               topic_ref="ServiceCatalog">
      <datareader_qos base_name="TopicProfiles::ServiceCatalog"/>
  </data_reader>
  ```
  This reader enables the dashboard to discover room GUIs and Service Host
  URLs from the `ServiceCatalog` data bridged from Domain 11 via Step DM.3.

### Test Gate

- [ ] `cmake --build build` succeeds (no XML parse errors)
- [ ] `tests/tools/test_xml_validator.py` passes
- [ ] `tests/integration/test_orchestration_e2e.py` — controller lifecycle
      tests pass with no Hospital participant
- [ ] All existing tests pass (no regression)

---

## Step DM.6 — Add `ProcedureController_Procedure_Operational` to `SurgicalParticipants.xml` ✅ `7506d9b`

### Work

- In `interfaces/participants/SurgicalParticipants.xml`, add a new
  `<domain_participant>` entry:
  ```xml
  <!--
      ProcedureController_Procedure_Operational — Controller's read-only
      view of procedure metadata (operational tag, Domain 10).
      Used by: Procedure Controller (hospital-dashboard)
      Reads: ProcedureStatus, ProcedureContext
  -->
  <domain_participant name="ProcedureController_Procedure_Operational"
                      domain_ref="MedtechDomains::Procedure_operational">
      <domain_participant_qos base_name="Participants::Transport"/>
      <subscriber name="ControllerProcOpSubscriber">
          <data_reader name="ProcedureStatusReader"
                       topic_ref="ProcedureStatus">
              <datareader_qos base_name="TopicProfiles::ProcedureStatus"/>
          </data_reader>
          <data_reader name="ProcedureContextReader"
                       topic_ref="ProcedureContext">
              <datareader_qos base_name="TopicProfiles::ProcedureContext"/>
          </data_reader>
      </subscriber>
  </domain_participant>
  ```

### Test Gate

- [ ] `cmake --build build` succeeds (no XML parse errors)
- [ ] `tests/tools/test_xml_validator.py` passes
- [ ] All existing tests pass (no regression)

---

## Step DM.7 — Migrate `app_names.idl` ✅ `7506d9b`

### Work

In `interfaces/idl/app_names.idl`, inside `module OrchestrationParticipants`:

- **Remove** the following constants:
  - `PROCEDURE_CONTROLLER_HOSPITAL`
  - `CTRL_PROCEDURE_STATUS_READER`  (references `ControllerHospSubscriber::`)
  - `CTRL_PROCEDURE_CONTEXT_READER` (references `ControllerHospSubscriber::`)
  - `CTRL_PATIENT_VITALS_READER`    (references `ControllerHospSubscriber::`)

In `interfaces/idl/app_names.idl`, inside `module SurgicalParticipants`
(create this section if it does not exist — add alongside the existing
`SurgicalParticipants` module content):

- **Add** new constants for the new participant:
  ```idl
  // ProcedureController_Procedure_Operational — Domain 10 operational reads
  const string PROCEDURE_CONTROLLER_PROCEDURE_OPERATIONAL =
      "SurgicalParticipants::ProcedureController_Procedure_Operational";
  const string CTRL_PROCEDURE_STATUS_READER =
      "ControllerProcOpSubscriber::ProcedureStatusReader";
  const string CTRL_PROCEDURE_CONTEXT_READER =
      "ControllerProcOpSubscriber::ProcedureContextReader";
  ```

> **Note:** `CTRL_PROCEDURE_STATUS_READER` and `CTRL_PROCEDURE_CONTEXT_READER`
> are being re-added in the `SurgicalParticipants` module using the new
> `ControllerProcOpSubscriber::` prefix. Any code that used these constants
> must be updated to import from the correct module (see Step DM.8).

- Regenerate C++ and Python type-support from `app_names.idl` (the
  `connextdds_rtiddsgen_run()` CMake calls handle this automatically on
  the next build).

### Test Gate

- [ ] `cmake --build build` generates `app_names` type support without
      errors (C++ and Python)
- [ ] Python test: `from app_names.MedtechEntityNames import SurgicalParticipants
      as sn; assert sn.CTRL_PROCEDURE_STATUS_READER ==
      "ControllerProcOpSubscriber::ProcedureStatusReader"`
- [ ] `PROCEDURE_CONTROLLER_HOSPITAL` is no longer accessible from
      `OrchestrationParticipants`
- [ ] All existing tests pass (no regression)

---

## Step DM.8 — Migrate Procedure Controller Application ✅ `7506d9b`

### Work

In `modules/hospital-dashboard/procedure_controller/controller.py`:

**a) Remove the Hospital participant:**

- Remove `self._hosp_participant` field and all references (`_init_dds`,
  `start`, `close`, `hosp_participant` property).
- Remove `self._hospital_readers` list and all references.
- Remove the `_init_dds` block that creates `ProcedureController_Hospital`,
  sets its partition and enables it, finds the three hospital readers, and
  appends them to `self._hospital_readers`.
- Remove the `waitset` entries for `_hospital_readers` in `start()`.
- Remove the `_hospital_readers` teardown loop in `close()`.

**b) Add the Procedure_Operational participant (Domain 10):**

- Add `self._proc_op_participant: dds.DomainParticipant | None = None`
  field initializer.
- Import the new IDL constants: update the `dash_names = ...` / `surg_names
  = ...` references to include the new constants from Step DM.7.
- In `_init_dds`, after creating `_orch_participant`, add:
  ```python
  self._proc_op_participant = provider.create_participant_from_config(
      surg_names.PROCEDURE_CONTROLLER_PROCEDURE_OPERATIONAL
  )
  if self._proc_op_participant is None:
      raise RuntimeError(
          "Failed to create Procedure Controller procedure-operational participant"
      )
  proc_op_qos = self._proc_op_participant.qos
  proc_op_qos.partition.name = [f"room/{self._room_id}/procedure/*"]
  self._proc_op_participant.qos = proc_op_qos
  self._proc_op_participant.enable()

  self._status_proc_reader = self._proc_op_participant.find_datareader(
      surg_names.CTRL_PROCEDURE_STATUS_READER
  )
  self._context_proc_reader = self._proc_op_participant.find_datareader(
      surg_names.CTRL_PROCEDURE_CONTEXT_READER
  )
  ```
- Add `_status_proc_reader` and `_context_proc_reader` to the waitset
  in `start()` and to the teardown in `close()`.
- Replace any UI handler that previously consumed data from
  `_hospital_readers` (for `ProcedureStatus` and `ProcedureContext`) to
  use the new readers instead. The data type and field structure are
  identical — only the source participant changes.

**c) Drop PatientVitals from the controller:**

- Remove any UI component, loop, waitset entry, or state field that
  references `_patient_vitals` or `CTRL_PATIENT_VITALS_READER`. This
  data is the dashboard's responsibility.

**d) Verify the `hosp_participant` property is removed:**

- Any test or integration code that called `controller.hosp_participant`
  must be updated to not expect this property.

### Test Gate

- [ ] Controller starts and reaches ready state without a Hospital participant
- [ ] `ProcedureStatus` and `ProcedureContext` are received on the new
      Domain 10 operational participant (verified by existing controller
      lifecycle spec scenarios)
- [ ] `PatientVitals` is not subscribed by the controller (no `PatientVitals`
      reader in controller teardown or waitset)
- [ ] `controller.hosp_participant` no longer exists (attr lookup raises
      `AttributeError`, or property is removed — verified by test)
- [ ] `tests/integration/test_orchestration_e2e.py` controller lifecycle
      tests pass
- [ ] All existing functional tests pass (no regression)

---

## Step DM.9 — Migrate Test Domain ID Constants ✅ `7506d9b`

### Work

Update hard-coded domain ID integers in integration tests:

- **`tests/integration/test_robot_service_host.py`:**
  - `ORCHESTRATION_DOMAIN_ID = 15` → `ORCHESTRATION_DOMAIN_ID = 11`
  - Update all adjacent comments that reference "domain 15".
- **`tests/integration/test_orchestration_e2e.py`:**
  - `ORCHESTRATION_DOMAIN_ID = 15` → `ORCHESTRATION_DOMAIN_ID = 11`
  - Update all adjacent comments that reference "domain 15".
- **`tests/integration/test_routing_service.py`:**
  - Rename `test_hospital_participant_on_domain_11` →
    `test_hospital_participant_on_domain_20` and update its assertion
    from `assert did == "11"` to `assert did == "20"`.
  - Rename `test_administration_on_domain_20` →
    `test_administration_on_domain_19` and update its assertion to 19.
  - Rename `test_monitoring_on_domain_20` →
    `test_monitoring_on_domain_19` and update its assertion to 19.
  - Add `test_orchestration_participant_on_domain_11` (checks the new
    `ProcedureOrchestration` input participant from Step DM.3).
  - Add `test_service_catalog_is_bridged` (checks `ServiceCatalog` appears
    in `StatusSession` topic routes).
  - Update the `hosp_domain` fixture in the domain isolation test from
    `11` to `20`.

### Test Gate

- [ ] `pytest tests/integration/test_routing_service.py -v` — all tests pass,
      no tests skip or are disabled
- [ ] `pytest tests/integration/test_robot_service_host.py -v` — all tests pass
- [ ] `pytest tests/integration/test_orchestration_e2e.py -v` — all tests pass
- [ ] Full CI gate passes: `bash scripts/ci.sh`

---

## Step DM.10 — Rebuild, Regenerate, and CI Validation ✅ `7506d9b`

### Work

- Run `cmake --build build --target install` from clean to regenerate all
  type-support code from updated IDL.
- Run `bash scripts/ci.sh` to execute the full quality gate sequence.
- Verify no committed generated files have changed unexpectedly (generated
  code is in `build/` and `install/` — not tracked by git in source form,
  but verify the build is clean).
- Run `medtech build` to confirm the CLI build path also works end-to-end.
- Run `medtech status` and `medtech stop` to confirm CLI operational tools
  still function with the new domain IDs.

### Test Gate

- [ ] `cmake --build build --target install` succeeds from clean checkout
- [ ] `bash scripts/ci.sh` passes all gates (lint, unit, integration, e2e)
- [ ] No `@skip`, `xfail`, or `DISABLED_` marks on any test
- [ ] No new failures in existing spec scenario tests
- [ ] `medtech build` succeeds
