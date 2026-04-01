"""Tests for Phase 3 Steps 3.2–3.3 — Hospital Dashboard Application Skeleton
and Procedure List View.

Covers test gate items from phase-3-dashboard.md Steps 3.2 and 3.3:
- Application launches without errors
- DDS participant is created on the Hospital domain with correct QoS
- UI renders placeholder layout with all panels visible
- DDS worker thread does not block the Qt main thread
- Dashboard displays all active procedures
- New procedure appears automatically when a new surgical instance starts
- Completed procedure status is updated in display

Spec coverage: hospital-dashboard.md — Procedure List, GUI Threading
Tags: @gui @integration @dashboard
"""

from __future__ import annotations

import inspect

import app_names
import clinical_alerts
import hospital
import monitoring
import pytest
import rti.connextdds as dds
import surgery
from hospital_dashboard.dashboard.hospital_dashboard import HospitalDashboard
from medtech.dds import initialize_connext
from PySide6.QtWidgets import QFrame, QSplitter, QStackedWidget

pytestmark = [
    pytest.mark.gui,
    pytest.mark.integration,
    pytest.mark.dashboard,
    pytest.mark.xdist_group("dashboard"),
]

dash_names = app_names.MedtechEntityNames.HospitalDashboard

HOSPITAL_DOMAIN_ID = 11


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_injected_readers(participant_factory):
    """Create seven injected DataReaders for HospitalDashboard tests.

    Uses IDL-generated types on domain 0 (test isolation).
    Returns a dict of keyword arguments for HospitalDashboard.__init__.
    """
    p = participant_factory(domain_id=0)
    sub = dds.Subscriber(p)

    def _reader(data_type, topic_name):
        topic = dds.Topic(p, topic_name, data_type)
        return dds.DataReader(sub, topic, dds.DataReaderQos())

    return {
        "procedure_status_reader": _reader(
            surgery.Surgery.ProcedureStatus, "ProcedureStatus"
        ),
        "procedure_context_reader": _reader(
            surgery.Surgery.ProcedureContext, "ProcedureContext"
        ),
        "patient_vitals_reader": _reader(
            monitoring.Monitoring.PatientVitals, "PatientVitals"
        ),
        "alarm_messages_reader": _reader(
            monitoring.Monitoring.AlarmMessage, "AlarmMessages"
        ),
        "robot_state_reader": _reader(surgery.Surgery.RobotState, "RobotState"),
        "clinical_alert_reader": _reader(
            clinical_alerts.ClinicalAlerts.ClinicalAlert, "ClinicalAlert"
        ),
        "resource_availability_reader": _reader(
            hospital.Hospital.ResourceAvailability, "ResourceAvailability"
        ),
    }


# ---------------------------------------------------------------------------
# TestDashboardCreation — Skeleton launches without errors
# ---------------------------------------------------------------------------


class TestDashboardCreation:
    """Dashboard skeleton can be instantiated with injected readers."""

    def test_dashboard_creates_without_errors(self, qapp, participant_factory):
        """HospitalDashboard instantiates without raising."""
        readers = _make_injected_readers(participant_factory)
        dashboard = HospitalDashboard(**readers)
        assert dashboard is not None
        dashboard.close_dds()

    def test_dashboard_window_title(self, qapp, participant_factory):
        """Window title matches the expected branding."""
        readers = _make_injected_readers(participant_factory)
        dashboard = HospitalDashboard(**readers)
        assert "Hospital Dashboard" in dashboard.windowTitle()
        dashboard.close_dds()

    def test_dashboard_default_size(self, qapp, participant_factory):
        """Dashboard has a reasonable default size."""
        readers = _make_injected_readers(participant_factory)
        dashboard = HospitalDashboard(**readers)
        assert dashboard.width() >= 800
        assert dashboard.height() >= 600
        dashboard.close_dds()


# ---------------------------------------------------------------------------
# TestDDSParticipant — Participant is created on the Hospital domain
# ---------------------------------------------------------------------------


class TestDDSParticipant:
    """DDS participant is created on the Hospital domain with correct QoS."""

    @pytest.fixture(scope="class")
    def dashboard_participant(self):
        """Create a HospitalDashboard participant (class scope, auto-cleanup)."""
        initialize_connext()
        provider = dds.QosProvider.default
        p = provider.create_participant_from_config(dash_names.HOSPITAL_DASHBOARD)
        partition = "room/*/procedure/*"
        qos = p.qos
        qos.partition.name = [partition]
        p.qos = qos
        p.enable()
        yield p
        try:
            p.close()
        except dds.AlreadyClosedError:
            pass

    def test_participant_on_hospital_domain(self, dashboard_participant):
        """Participant is on the Hospital domain (domain ID 11)."""
        assert dashboard_participant.domain_id == HOSPITAL_DOMAIN_ID

    def test_participant_has_wildcard_partition(self, dashboard_participant):
        """Participant partition is set to wildcard for facility-wide aggregation."""
        partitions = list(dashboard_participant.qos.partition.name)
        assert "room/*/procedure/*" in partitions

    def test_procedure_status_reader_exists(self, dashboard_participant):
        """ProcedureStatusReader found via entity name constant."""
        r = dashboard_participant.find_datareader(dash_names.PROCEDURE_STATUS_READER)
        assert r is not None, f"Reader not found: {dash_names.PROCEDURE_STATUS_READER}"

    def test_patient_vitals_reader_exists(self, dashboard_participant):
        """PatientVitalsReader found via entity name constant."""
        r = dashboard_participant.find_datareader(dash_names.PATIENT_VITALS_READER)
        assert r is not None, f"Reader not found: {dash_names.PATIENT_VITALS_READER}"

    def test_alarm_messages_reader_exists(self, dashboard_participant):
        """AlarmMessagesReader found via entity name constant."""
        r = dashboard_participant.find_datareader(dash_names.ALARM_MESSAGES_READER)
        assert r is not None, f"Reader not found: {dash_names.ALARM_MESSAGES_READER}"

    def test_robot_state_reader_exists(self, dashboard_participant):
        """RobotStateReader found via entity name constant."""
        r = dashboard_participant.find_datareader(dash_names.ROBOT_STATE_READER)
        assert r is not None, f"Reader not found: {dash_names.ROBOT_STATE_READER}"

    def test_clinical_alert_reader_exists(self, dashboard_participant):
        """ClinicalAlertReader found via entity name constant."""
        r = dashboard_participant.find_datareader(dash_names.CLINICAL_ALERT_READER)
        assert r is not None, f"Reader not found: {dash_names.CLINICAL_ALERT_READER}"

    def test_resource_availability_reader_exists(self, dashboard_participant):
        """ResourceAvailabilityReader found via entity name constant."""
        r = dashboard_participant.find_datareader(
            dash_names.RESOURCE_AVAILABILITY_READER
        )
        assert (
            r is not None
        ), f"Reader not found: {dash_names.RESOURCE_AVAILABILITY_READER}"

    def test_procedure_context_reader_exists(self, dashboard_participant):
        """ProcedureContextReader found via entity name constant."""
        r = dashboard_participant.find_datareader(dash_names.PROCEDURE_CONTEXT_READER)
        assert r is not None, f"Reader not found: {dash_names.PROCEDURE_CONTEXT_READER}"

    def test_device_telemetry_reader_exists(self, dashboard_participant):
        """DeviceTelemetryReader found via entity name constant."""
        r = dashboard_participant.find_datareader(dash_names.DEVICE_TELEMETRY_READER)
        assert r is not None, f"Reader not found: {dash_names.DEVICE_TELEMETRY_READER}"


# ---------------------------------------------------------------------------
# TestQosConfiguration — Reader QoS matches XML profiles
# ---------------------------------------------------------------------------


class TestQosConfiguration:
    """Reader QoS is loaded from GuiHospitalTopics profiles."""

    @pytest.fixture(scope="class")
    def dashboard_participant(self):
        """Create a HospitalDashboard participant for QoS verification."""
        initialize_connext()
        provider = dds.QosProvider.default
        p = provider.create_participant_from_config(dash_names.HOSPITAL_DASHBOARD)
        p.enable()
        yield p
        try:
            p.close()
        except dds.AlreadyClosedError:
            pass

    @staticmethod
    def _reader_qos(participant, entity_name):
        """Look up a reader by entity name and return its QoS."""
        r = participant.find_datareader(entity_name)
        assert r is not None, f"Reader not found: {entity_name}"
        return dds.DataReader(r).qos

    def test_procedure_status_reliable(self, dashboard_participant):
        """ProcedureStatus reader uses RELIABLE reliability."""
        qos = self._reader_qos(
            dashboard_participant, dash_names.PROCEDURE_STATUS_READER
        )
        assert qos.reliability.kind == dds.ReliabilityKind.RELIABLE

    def test_procedure_status_transient_local(self, dashboard_participant):
        """ProcedureStatus reader uses TRANSIENT_LOCAL durability."""
        qos = self._reader_qos(
            dashboard_participant, dash_names.PROCEDURE_STATUS_READER
        )
        assert qos.durability.kind == dds.DurabilityKind.TRANSIENT_LOCAL

    def test_patient_vitals_reliable(self, dashboard_participant):
        """PatientVitals reader uses RELIABLE reliability."""
        qos = self._reader_qos(dashboard_participant, dash_names.PATIENT_VITALS_READER)
        assert qos.reliability.kind == dds.ReliabilityKind.RELIABLE

    def test_robot_state_reliable(self, dashboard_participant):
        """RobotState reader uses RELIABLE reliability."""
        qos = self._reader_qos(dashboard_participant, dash_names.ROBOT_STATE_READER)
        assert qos.reliability.kind == dds.ReliabilityKind.RELIABLE

    def test_clinical_alert_reliable(self, dashboard_participant):
        """ClinicalAlert reader uses RELIABLE reliability."""
        qos = self._reader_qos(dashboard_participant, dash_names.CLINICAL_ALERT_READER)
        assert qos.reliability.kind == dds.ReliabilityKind.RELIABLE

    def test_resource_availability_transient_local(self, dashboard_participant):
        """ResourceAvailability reader uses TRANSIENT_LOCAL durability."""
        qos = self._reader_qos(
            dashboard_participant, dash_names.RESOURCE_AVAILABILITY_READER
        )
        assert qos.durability.kind == dds.DurabilityKind.TRANSIENT_LOCAL


# ---------------------------------------------------------------------------
# TestUILayout — UI renders placeholder layout with all panels
# ---------------------------------------------------------------------------


class TestUILayout:
    """UI renders placeholder layout with all panels visible."""

    @pytest.fixture()
    def dashboard(self, qapp, participant_factory):
        """Create a dashboard with injected readers for layout tests."""
        readers = _make_injected_readers(participant_factory)
        d = HospitalDashboard(**readers)
        yield d
        d.close_dds()

    def test_procedure_list_panel_exists(self, dashboard):
        """Left panel (procedure list) is present."""
        panel = dashboard.findChild(QFrame, "procedureListPanel")
        assert panel is not None, "Procedure list panel not found"

    def test_detail_panel_exists(self, dashboard):
        """Right panel (detail view) is present."""
        panel = dashboard.findChild(QFrame, "detailPanel")
        assert panel is not None, "Detail panel not found"

    def test_alert_feed_panel_exists(self, dashboard):
        """Bottom panel (alert feed) is present."""
        panel = dashboard.findChild(QFrame, "alertFeedPanel")
        assert panel is not None, "Alert feed panel not found"

    def test_main_splitter_exists(self, dashboard):
        """Horizontal splitter divides procedure list and detail view."""
        splitter = dashboard.findChild(QSplitter, "mainSplitter")
        assert splitter is not None, "Main splitter not found"

    def test_procedure_list_has_stacked_widget(self, dashboard):
        """Procedure list panel uses a QStackedWidget for empty/populated states."""
        stacks = dashboard.findChildren(QStackedWidget)
        assert len(stacks) >= 1, "Expected at least one QStackedWidget"

    def test_procedure_list_shows_empty_state(self, dashboard):
        """Procedure list starts showing the empty state (index 0)."""
        assert dashboard._procedure_list_stack.currentIndex() == 0

    def test_detail_shows_empty_state(self, dashboard):
        """Detail panel starts showing the empty state."""
        assert dashboard._detail_stack.currentIndex() == 0

    def test_alert_feed_shows_empty_state(self, dashboard):
        """Alert feed starts showing the empty state."""
        assert dashboard._alert_stack.currentIndex() == 0

    def test_robot_status_shows_empty_state(self, dashboard):
        """Robot status starts showing the empty state."""
        assert dashboard._robot_stack.currentIndex() == 0


# ---------------------------------------------------------------------------
# TestNonBlockingReads — DDS worker thread does not block Qt main thread
# ---------------------------------------------------------------------------


class TestNonBlockingReads:
    """DDS data processing does not block the Qt main thread."""

    def test_start_is_coroutine(self, qapp, participant_factory):
        """start() is an async coroutine function (never blocks UI thread)."""
        readers = _make_injected_readers(participant_factory)
        dashboard = HospitalDashboard(**readers)
        assert inspect.iscoroutinefunction(
            dashboard.start
        ), "start() must be an async coroutine"
        dashboard.close_dds()

    def test_close_dds_releases_participant(self, qapp, participant_factory):
        """close_dds() releases the DDS participant."""
        readers = _make_injected_readers(participant_factory)
        dashboard = HospitalDashboard(**readers)
        dashboard.close_dds()
        assert dashboard.participant is None

    def test_reader_accessors_return_datareaders(self, qapp, participant_factory):
        """All reader accessors return DataReader objects."""
        readers = _make_injected_readers(participant_factory)
        dashboard = HospitalDashboard(**readers)
        assert isinstance(dashboard.procedure_status_reader, dds.DataReader)
        assert isinstance(dashboard.patient_vitals_reader, dds.DataReader)
        assert isinstance(dashboard.alarm_messages_reader, dds.DataReader)
        assert isinstance(dashboard.robot_state_reader, dds.DataReader)
        assert isinstance(dashboard.clinical_alert_reader, dds.DataReader)
        assert isinstance(dashboard.resource_reader, dds.DataReader)
        dashboard.close_dds()

    def test_receive_procedure_status_is_coroutine(self, qapp, participant_factory):
        """_receive_procedure_status is an async coroutine."""
        readers = _make_injected_readers(participant_factory)
        dashboard = HospitalDashboard(**readers)
        assert inspect.iscoroutinefunction(dashboard._receive_procedure_status)
        dashboard.close_dds()

    def test_receive_procedure_context_is_coroutine(self, qapp, participant_factory):
        """_receive_procedure_context is an async coroutine."""
        readers = _make_injected_readers(participant_factory)
        dashboard = HospitalDashboard(**readers)
        assert inspect.iscoroutinefunction(dashboard._receive_procedure_context)
        dashboard.close_dds()


# ---------------------------------------------------------------------------
# TestProcedureCard — ProcedureCard widget unit tests
# ---------------------------------------------------------------------------

ProcedurePhase = surgery.Surgery.ProcedurePhase


class TestProcedureCard:
    """ProcedureCard widget renders procedure info with color-coded status."""

    def test_card_initial_state(self, qapp):
        """New card shows placeholder text."""
        from hospital_dashboard.dashboard.hospital_dashboard import ProcedureCard

        card = ProcedureCard("proc-001")
        assert card.procedure_id == "proc-001"
        assert "—" in card._room_label.text()
        assert "Unknown" in card._phase_label.text()

    def test_update_status_in_progress(self, qapp):
        """Updating with IN_PROGRESS phase shows green indicator."""
        from hospital_dashboard.dashboard.hospital_dashboard import ProcedureCard

        card = ProcedureCard("proc-001")
        card.update_status(int(ProcedurePhase.IN_PROGRESS), "Surgery underway")
        assert "In Progress" in card._phase_label.text()
        assert "#A4D65E" in card._status_dot.styleSheet()

    def test_update_status_completing(self, qapp):
        """Updating with COMPLETING phase shows amber indicator."""
        from hospital_dashboard.dashboard.hospital_dashboard import ProcedureCard

        card = ProcedureCard("proc-001")
        card.update_status(int(ProcedurePhase.COMPLETING), "Closing")
        assert "Completing" in card._phase_label.text()
        assert "#FFA300" in card._status_dot.styleSheet()

    def test_update_status_alert(self, qapp):
        """Updating with ALERT phase shows red indicator."""
        from hospital_dashboard.dashboard.hospital_dashboard import ProcedureCard

        card = ProcedureCard("proc-001")
        card.update_status(int(ProcedurePhase.ALERT), "Emergency!")
        assert "Alert" in card._phase_label.text()
        assert "#D32F2F" in card._status_dot.styleSheet()

    def test_update_context(self, qapp):
        """Updating context populates room, patient, type, surgeon."""
        from hospital_dashboard.dashboard.hospital_dashboard import ProcedureCard

        card = ProcedureCard("proc-001")
        card.update_context("OR-3", "John Doe", "Appendectomy", "Dr. Smith")
        assert "OR-3" in card._room_label.text()
        assert "John Doe" in card._patient_label.text()
        assert "Appendectomy" in card._type_label.text()
        assert "Dr. Smith" in card._surgeon_label.text()


# ---------------------------------------------------------------------------
# TestProcedureList — Procedure list data integration
# ---------------------------------------------------------------------------


class TestProcedureList:
    """Procedure list populates from DDS ProcedureStatus data."""

    @pytest.fixture()
    def dashboard_and_writers(self, qapp, participant_factory):
        """Create dashboard with injected readers + matching writers."""
        p = participant_factory(domain_id=0)
        sub = dds.Subscriber(p)
        pub = dds.Publisher(p)

        def _reader(data_type, topic_name):
            topic = dds.Topic(p, topic_name, data_type)
            return dds.DataReader(sub, topic, dds.DataReaderQos())

        def _writer(data_type, topic_name):
            topic = dds.Topic.find(p, topic_name)
            wqos = dds.DataWriterQos()
            wqos.reliability.kind = dds.ReliabilityKind.RELIABLE
            return dds.DataWriter(pub, topic, wqos)

        readers = {
            "procedure_status_reader": _reader(
                surgery.Surgery.ProcedureStatus, "ProcedureStatus"
            ),
            "procedure_context_reader": _reader(
                surgery.Surgery.ProcedureContext, "ProcedureContext"
            ),
            "patient_vitals_reader": _reader(
                monitoring.Monitoring.PatientVitals, "PatientVitals"
            ),
            "alarm_messages_reader": _reader(
                monitoring.Monitoring.AlarmMessage, "AlarmMessages"
            ),
            "robot_state_reader": _reader(surgery.Surgery.RobotState, "RobotState"),
            "clinical_alert_reader": _reader(
                clinical_alerts.ClinicalAlerts.ClinicalAlert, "ClinicalAlert"
            ),
            "resource_availability_reader": _reader(
                hospital.Hospital.ResourceAvailability, "ResourceAvailability"
            ),
        }

        status_writer = _writer(surgery.Surgery.ProcedureStatus, "ProcedureStatus")
        context_writer = _writer(surgery.Surgery.ProcedureContext, "ProcedureContext")

        dashboard = HospitalDashboard(**readers)
        yield dashboard, status_writer, context_writer
        dashboard.close_dds()

    def test_card_created_from_status(self, dashboard_and_writers):
        """ProcedureStatus sample creates a card in the procedure list.

        spec: Dashboard displays all active procedures @e2e @gui
        """
        dashboard, status_writer, _ = dashboard_and_writers
        status = surgery.Surgery.ProcedureStatus(
            procedure_id="proc-001",
            phase=ProcedurePhase.IN_PROGRESS,
            status_message="Surgery active",
        )
        status_writer.write(status)
        # Direct call to simulate async receive (tests don't run event loop)
        dashboard._get_or_create_card("proc-001").update_status(
            int(ProcedurePhase.IN_PROGRESS), "Surgery active"
        )
        assert "proc-001" in dashboard.procedure_cards
        assert dashboard._procedure_list_stack.currentIndex() == 1

    def test_multiple_procedures_displayed(self, dashboard_and_writers):
        """Multiple ProcedureStatus samples create multiple cards.

        spec: Dashboard displays all active procedures @e2e @gui
        """
        dashboard, _, _ = dashboard_and_writers
        for pid in ["proc-001", "proc-002"]:
            dashboard._get_or_create_card(pid).update_status(
                int(ProcedurePhase.IN_PROGRESS), "Active"
            )
        assert len(dashboard.procedure_cards) == 2
        assert "proc-001" in dashboard.procedure_cards
        assert "proc-002" in dashboard.procedure_cards

    def test_new_procedure_auto_added(self, dashboard_and_writers):
        """New procedure appears automatically (no manual refresh).

        spec: New procedure appears automatically @e2e @gui
        """
        dashboard, _, _ = dashboard_and_writers
        dashboard._get_or_create_card("proc-001")
        assert len(dashboard.procedure_cards) == 1

        # Second procedure arrives
        dashboard._get_or_create_card("proc-002")
        assert len(dashboard.procedure_cards) == 2

    def test_status_update_changes_indicator(self, dashboard_and_writers):
        """Phase change updates the card's status indicator.

        spec: Completed procedure status is updated in display @e2e @gui
        """
        dashboard, _, _ = dashboard_and_writers
        card = dashboard._get_or_create_card("proc-001")
        card.update_status(int(ProcedurePhase.IN_PROGRESS), "Active")
        assert "In Progress" in card._phase_label.text()

        card.update_status(int(ProcedurePhase.COMPLETING), "Closing")
        assert "Completing" in card._phase_label.text()
        assert "#FFA300" in card._status_dot.styleSheet()

    def test_context_updates_card(self, dashboard_and_writers):
        """ProcedureContext data updates the card's room/patient/surgeon info."""
        dashboard, _, _ = dashboard_and_writers
        card = dashboard._get_or_create_card("proc-001")
        card.update_context("OR-3", "Jane Doe", "Cholecystectomy", "Dr. Jones")
        assert "OR-3" in card._room_label.text()
        assert "Jane Doe" in card._patient_label.text()

    def test_duplicate_status_reuses_card(self, dashboard_and_writers):
        """Multiple status updates for the same procedure reuse the same card."""
        dashboard, _, _ = dashboard_and_writers
        card1 = dashboard._get_or_create_card("proc-001")
        card2 = dashboard._get_or_create_card("proc-001")
        assert card1 is card2
        assert len(dashboard.procedure_cards) == 1

    def test_empty_state_hidden_when_populated(self, dashboard_and_writers):
        """Empty state is hidden when at least one procedure card exists."""
        dashboard, _, _ = dashboard_and_writers
        assert dashboard._procedure_list_stack.currentIndex() == 0
        dashboard._get_or_create_card("proc-001")
        assert dashboard._procedure_list_stack.currentIndex() == 1


# ---------------------------------------------------------------------------
# Step 3.4 — Vitals Overview
# ---------------------------------------------------------------------------


class TestVitalsRow:
    """VitalsRow widget displays HR, SpO2, BP with color-coded severity."""

    def test_vitals_row_initial_state(self, qapp):
        """New VitalsRow shows placeholder text."""
        from hospital_dashboard.dashboard.hospital_dashboard import VitalsRow

        row = VitalsRow("patient-001")
        assert row.patient_id == "patient-001"
        assert "—" in row._hr_label.text()
        assert "—" in row._spo2_label.text()

    def test_vitals_normal_hr(self, qapp):
        """Normal HR (< 100) shows green color.

        spec: Vitals are color-coded by severity @e2e @gui
        """
        from hospital_dashboard.dashboard.hospital_dashboard import VitalsRow

        row = VitalsRow("patient-001")
        row.update_vitals(hr=75.0, spo2=98.0, systolic=120.0, diastolic=80.0)
        assert "75" in row._hr_label.text()
        assert "#A4D65E" in row._hr_label.styleSheet()

    def test_vitals_warning_hr(self, qapp):
        """Warning HR (>= 100, < 120) shows amber color.

        spec: HR exceeds 100 bpm → warning color (yellow/amber)
        """
        from hospital_dashboard.dashboard.hospital_dashboard import VitalsRow

        row = VitalsRow("patient-001")
        row.update_vitals(hr=105.0, spo2=97.0, systolic=120.0, diastolic=80.0)
        assert "105" in row._hr_label.text()
        assert "#ED8B00" in row._hr_label.styleSheet()

    def test_vitals_critical_hr(self, qapp):
        """Critical HR (>= 120) shows red color.

        spec: HR exceeds 120 bpm → critical color (red)
        """
        from hospital_dashboard.dashboard.hospital_dashboard import VitalsRow

        row = VitalsRow("patient-001")
        row.update_vitals(hr=130.0, spo2=97.0, systolic=120.0, diastolic=80.0)
        assert "130" in row._hr_label.text()
        assert "#D32F2F" in row._hr_label.styleSheet()

    def test_vitals_spo2_normal(self, qapp):
        """Normal SpO2 (> 94%) shows green."""
        from hospital_dashboard.dashboard.hospital_dashboard import VitalsRow

        row = VitalsRow("patient-001")
        row.update_vitals(hr=75.0, spo2=98.0, systolic=120.0, diastolic=80.0)
        assert "98" in row._spo2_label.text()
        assert "#A4D65E" in row._spo2_label.styleSheet()

    def test_vitals_spo2_warning(self, qapp):
        """Warning SpO2 (<= 94%, > 90%) shows amber."""
        from hospital_dashboard.dashboard.hospital_dashboard import VitalsRow

        row = VitalsRow("patient-001")
        row.update_vitals(hr=75.0, spo2=93.0, systolic=120.0, diastolic=80.0)
        assert "93" in row._spo2_label.text()
        assert "#ED8B00" in row._spo2_label.styleSheet()

    def test_vitals_spo2_critical(self, qapp):
        """Critical SpO2 (<= 90%) shows red."""
        from hospital_dashboard.dashboard.hospital_dashboard import VitalsRow

        row = VitalsRow("patient-001")
        row.update_vitals(hr=75.0, spo2=88.0, systolic=120.0, diastolic=80.0)
        assert "88" in row._spo2_label.text()
        assert "#D32F2F" in row._spo2_label.styleSheet()

    def test_vitals_bp_normal(self, qapp):
        """Normal systolic BP (91-159) shows green."""
        from hospital_dashboard.dashboard.hospital_dashboard import VitalsRow

        row = VitalsRow("patient-001")
        row.update_vitals(hr=75.0, spo2=98.0, systolic=120.0, diastolic=80.0)
        assert "120/80" in row._bp_label.text()
        assert "#A4D65E" in row._bp_label.styleSheet()

    def test_vitals_bp_high_warning(self, qapp):
        """High systolic BP (>= 160, < 180) shows amber."""
        from hospital_dashboard.dashboard.hospital_dashboard import VitalsRow

        row = VitalsRow("patient-001")
        row.update_vitals(hr=75.0, spo2=98.0, systolic=165.0, diastolic=95.0)
        assert "165/95" in row._bp_label.text()
        assert "#ED8B00" in row._bp_label.styleSheet()

    def test_vitals_bp_critical(self, qapp):
        """Critical systolic BP (>= 180) shows red."""
        from hospital_dashboard.dashboard.hospital_dashboard import VitalsRow

        row = VitalsRow("patient-001")
        row.update_vitals(hr=75.0, spo2=98.0, systolic=190.0, diastolic=110.0)
        assert "190/110" in row._bp_label.text()
        assert "#D32F2F" in row._bp_label.styleSheet()


class TestVitalsIntegration:
    """Vitals rows are created and managed by the dashboard."""

    @pytest.fixture()
    def dashboard(self, qapp, participant_factory):
        """Create dashboard with injected readers."""
        readers = _make_injected_readers(participant_factory)
        d = HospitalDashboard(**readers)
        yield d
        d.close_dds()

    def test_vitals_row_created(self, dashboard):
        """_get_or_create_vitals_row creates a VitalsRow for a patient.

        spec: Summarized vitals shown per procedure @e2e @gui
        """
        row = dashboard._get_or_create_vitals_row("patient-001")
        assert "patient-001" in dashboard.vitals_rows
        assert row.patient_id == "patient-001"
        assert dashboard._detail_stack.currentIndex() == 1

    def test_multiple_vitals_rows(self, dashboard):
        """Multiple patients create separate VitalsRow widgets."""
        dashboard._get_or_create_vitals_row("patient-001")
        dashboard._get_or_create_vitals_row("patient-002")
        assert len(dashboard.vitals_rows) == 2

    def test_duplicate_reuses_row(self, dashboard):
        """Same patient_id reuses the same VitalsRow."""
        row1 = dashboard._get_or_create_vitals_row("patient-001")
        row2 = dashboard._get_or_create_vitals_row("patient-001")
        assert row1 is row2
        assert len(dashboard.vitals_rows) == 1

    def test_vitals_empty_state_initially(self, dashboard):
        """Vitals detail panel shows empty state before data."""
        assert dashboard._detail_stack.currentIndex() == 0

    def test_vitals_populated_state(self, dashboard):
        """Vitals detail panel shows populated state after data arrives."""
        dashboard._get_or_create_vitals_row("patient-001")
        assert dashboard._detail_stack.currentIndex() == 1

    def test_receive_patient_vitals_is_coroutine(self, dashboard):
        """_receive_patient_vitals is an async coroutine."""
        assert inspect.iscoroutinefunction(dashboard._receive_patient_vitals)


# ---------------------------------------------------------------------------
# Step 3.5 — Alert Feed
# ---------------------------------------------------------------------------

AlertSeverity = clinical_alerts.ClinicalAlerts.AlertSeverity


class TestAlertEntry:
    """AlertEntry widget displays alert details with severity styling."""

    def test_alert_entry_severity_critical(self, qapp):
        """CRITICAL alert shows red color and exclamation icon."""
        from hospital_dashboard.dashboard.hospital_dashboard import AlertEntry

        entry = AlertEntry(
            alert_id="alert-001",
            severity=int(AlertSeverity.CRITICAL),
            room="OR-1",
            patient_name="John Doe",
            message="Heart rate critical",
        )
        assert entry.alert_id == "alert-001"
        assert entry.severity_int == int(AlertSeverity.CRITICAL)
        assert "#D32F2F" in entry._severity_label.styleSheet()
        assert "CRITICAL" in entry._severity_label.text()

    def test_alert_entry_severity_warning(self, qapp):
        """WARNING alert shows amber color."""
        from hospital_dashboard.dashboard.hospital_dashboard import AlertEntry

        entry = AlertEntry(
            alert_id="alert-002",
            severity=int(AlertSeverity.WARNING),
            room="OR-3",
            patient_name="Jane Doe",
            message="SpO2 low",
        )
        assert "#ED8B00" in entry._severity_label.styleSheet()
        assert "WARNING" in entry._severity_label.text()

    def test_alert_entry_severity_info(self, qapp):
        """INFO alert shows blue color."""
        from hospital_dashboard.dashboard.hospital_dashboard import AlertEntry

        entry = AlertEntry(
            alert_id="alert-003",
            severity=int(AlertSeverity.INFO),
            room="OR-1",
            patient_name="John Doe",
            message="Vitals stable",
        )
        assert "#004C97" in entry._severity_label.styleSheet()
        assert "INFO" in entry._severity_label.text()

    def test_alert_entry_displays_room(self, qapp):
        """Alert entry shows room identifier."""
        from hospital_dashboard.dashboard.hospital_dashboard import AlertEntry

        entry = AlertEntry(
            alert_id="alert-001",
            severity=int(AlertSeverity.CRITICAL),
            room="OR-5",
            patient_name="J. Doe",
            message="Test",
        )
        assert "OR-5" in entry._room_label.text()

    def test_alert_entry_displays_patient(self, qapp):
        """Alert entry shows patient name."""
        from hospital_dashboard.dashboard.hospital_dashboard import AlertEntry

        entry = AlertEntry(
            alert_id="alert-001",
            severity=int(AlertSeverity.WARNING),
            room="OR-1",
            patient_name="Jane Smith",
            message="BP elevated",
        )
        assert "Jane Smith" in entry._patient_label.text()

    def test_alert_entry_displays_message(self, qapp):
        """Alert entry shows alert message."""
        from hospital_dashboard.dashboard.hospital_dashboard import AlertEntry

        entry = AlertEntry(
            alert_id="alert-001",
            severity=int(AlertSeverity.INFO),
            room="OR-1",
            patient_name="J. Doe",
            message="Patient vitals normalized",
        )
        assert "Patient vitals normalized" in entry._msg_label.text()

    def test_alert_highlight(self, qapp):
        """highlight() activates visual highlight."""
        from hospital_dashboard.dashboard.hospital_dashboard import AlertEntry

        entry = AlertEntry(
            alert_id="alert-001",
            severity=int(AlertSeverity.CRITICAL),
            room="OR-1",
            patient_name="J. Doe",
            message="Test",
        )
        entry.highlight()
        assert entry._highlight_active
        assert "background-color" in entry.styleSheet()


class TestAlertFeedIntegration:
    """Alert feed management in the dashboard."""

    @pytest.fixture()
    def dashboard(self, qapp, participant_factory):
        """Create dashboard with injected readers."""
        readers = _make_injected_readers(participant_factory)
        d = HospitalDashboard(**readers)
        yield d
        d.close_dds()

    def _make_alert_entry(self, alert_id, severity, room, patient="Test", msg="Alert"):
        from hospital_dashboard.dashboard.hospital_dashboard import AlertEntry

        return AlertEntry(
            alert_id=alert_id,
            severity=severity,
            room=room,
            patient_name=patient,
            message=msg,
        )

    def test_add_alert_populates_feed(self, dashboard):
        """Adding an alert switches from empty to populated state.

        spec: Alerts from all ORs appear in unified feed @e2e @gui
        """
        entry = self._make_alert_entry("a1", int(AlertSeverity.CRITICAL), "OR-1")
        dashboard._add_alert(entry)
        assert len(dashboard.alert_entries) == 1
        assert dashboard._alert_stack.currentIndex() == 1

    def test_alerts_from_multiple_rooms(self, dashboard):
        """Alerts from multiple rooms appear in unified feed.

        spec: Alerts from all ORs appear in unified feed @e2e @gui
        """
        e1 = self._make_alert_entry("a1", int(AlertSeverity.WARNING), "OR-1")
        e2 = self._make_alert_entry("a2", int(AlertSeverity.CRITICAL), "OR-3")
        dashboard._add_alert(e1)
        dashboard._add_alert(e2)
        assert len(dashboard.alert_entries) == 2

    def test_severity_filter_critical_only(self, dashboard):
        """Severity filter shows only matching alerts.

        spec: Feed is filterable by severity @e2e @gui
        """
        e_info = self._make_alert_entry("a1", int(AlertSeverity.INFO), "OR-1")
        e_warn = self._make_alert_entry("a2", int(AlertSeverity.WARNING), "OR-1")
        e_crit = self._make_alert_entry("a3", int(AlertSeverity.CRITICAL), "OR-3")
        for e in (e_info, e_warn, e_crit):
            dashboard._add_alert(e)

        # Set severity filter to CRITICAL
        dashboard._alert_severity_filter = int(AlertSeverity.CRITICAL)
        dashboard._apply_alert_filters()

        assert e_info.isHidden()
        assert e_warn.isHidden()
        assert not e_crit.isHidden()

    def test_severity_filter_cleared(self, dashboard):
        """Clearing severity filter shows all alerts.

        spec: Filter can be cleared to show all alerts again
        """
        e_info = self._make_alert_entry("a1", int(AlertSeverity.INFO), "OR-1")
        e_crit = self._make_alert_entry("a2", int(AlertSeverity.CRITICAL), "OR-3")
        for e in (e_info, e_crit):
            dashboard._add_alert(e)

        # Filter then clear
        dashboard._alert_severity_filter = int(AlertSeverity.CRITICAL)
        dashboard._apply_alert_filters()
        assert e_info.isHidden()

        dashboard._alert_severity_filter = None
        dashboard._apply_alert_filters()
        assert not e_info.isHidden()
        assert not e_crit.isHidden()

    def test_room_filter(self, dashboard):
        """Room filter shows only alerts from selected room.

        spec: Feed is filterable by room @e2e @gui
        """
        e1 = self._make_alert_entry("a1", int(AlertSeverity.WARNING), "OR-1")
        e2 = self._make_alert_entry("a2", int(AlertSeverity.CRITICAL), "OR-3")
        for e in (e1, e2):
            dashboard._add_alert(e)

        dashboard._alert_room_filter = "OR-1"
        dashboard._apply_alert_filters()
        assert not e1.isHidden()
        assert e2.isHidden()

    def test_room_filter_cleared(self, dashboard):
        """Clearing room filter shows all alerts."""
        e1 = self._make_alert_entry("a1", int(AlertSeverity.INFO), "OR-1")
        e2 = self._make_alert_entry("a2", int(AlertSeverity.WARNING), "OR-3")
        for e in (e1, e2):
            dashboard._add_alert(e)

        dashboard._alert_room_filter = "OR-1"
        dashboard._apply_alert_filters()
        assert e2.isHidden()

        dashboard._alert_room_filter = None
        dashboard._apply_alert_filters()
        assert not e1.isHidden()
        assert not e2.isHidden()

    def test_combined_severity_and_room_filter(self, dashboard):
        """Both filters can be active simultaneously."""
        e1 = self._make_alert_entry("a1", int(AlertSeverity.WARNING), "OR-1")
        e2 = self._make_alert_entry("a2", int(AlertSeverity.CRITICAL), "OR-1")
        e3 = self._make_alert_entry("a3", int(AlertSeverity.CRITICAL), "OR-3")
        for e in (e1, e2, e3):
            dashboard._add_alert(e)

        dashboard._alert_severity_filter = int(AlertSeverity.CRITICAL)
        dashboard._alert_room_filter = "OR-1"
        dashboard._apply_alert_filters()
        assert e1.isHidden()  # wrong severity
        assert not e2.isHidden()  # matches both
        assert e3.isHidden()  # wrong room

    def test_new_room_added_to_combo(self, dashboard):
        """New rooms are dynamically added to the room filter combo."""
        e1 = self._make_alert_entry("a1", int(AlertSeverity.INFO), "OR-1")
        dashboard._add_alert(e1)
        items = [
            dashboard._room_combo.itemText(i)
            for i in range(dashboard._room_combo.count())
        ]
        assert "OR-1" in items

    def test_alert_highlighted_on_add(self, dashboard):
        """New alerts get visual highlight on addition.

        spec: New alerts appear within 2 seconds with visual highlight
        """
        entry = self._make_alert_entry("a1", int(AlertSeverity.CRITICAL), "OR-1")
        dashboard._add_alert(entry)
        assert entry._highlight_active
        assert "background-color" in entry.styleSheet()

    def test_receive_clinical_alerts_is_coroutine(self, dashboard):
        """_receive_clinical_alerts is an async coroutine."""
        assert inspect.iscoroutinefunction(dashboard._receive_clinical_alerts)

    def test_empty_state_initially(self, dashboard):
        """Alert feed shows empty state before any alerts."""
        assert dashboard._alert_stack.currentIndex() == 0
        assert len(dashboard.alert_entries) == 0
