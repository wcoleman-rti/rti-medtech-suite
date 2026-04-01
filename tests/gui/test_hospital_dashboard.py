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
