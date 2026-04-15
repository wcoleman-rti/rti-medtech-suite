"""Tests for the NiceGUI Hospital Dashboard migration.

Tags: @gui @integration @dashboard
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import app_names
import clinical_alerts
import hospital
import monitoring
import orchestration
import pytest
import rti.connextdds as dds
import surgery
from hospital_dashboard.dashboard import dashboard as dashboard_module
from medtech.gui import BRAND_COLORS, ICONS, NICEGUI_QUASAR_CONFIG

pytestmark = [
    pytest.mark.gui,
    pytest.mark.integration,
    pytest.mark.dashboard,
]

dash_names = app_names.MedtechEntityNames.HospitalDashboard


@dataclass
class FakeElement:
    kind: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    styles: list[str] = field(default_factory=list)
    class_calls: list[tuple[Any, ...]] = field(default_factory=list)
    children: list[Any] = field(default_factory=list)
    value: Any = None

    def __enter__(self) -> "FakeElement":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    @property
    def before(self) -> "FakeElement":
        return self

    @property
    def after(self) -> "FakeElement":
        return self

    def classes(self, *args: Any, **kwargs: Any) -> "FakeElement":
        self.class_calls.append(args)
        return self

    def style(self, value: str) -> "FakeElement":
        self.styles.append(value)
        return self

    def props(self, *args: Any, **kwargs: Any) -> "FakeElement":
        return self

    def bind_value(self, *args: Any, **kwargs: Any) -> "FakeElement":
        return self


class RefreshableWrapper:
    def __init__(self, func: Any) -> None:
        self.func = func

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.func(*args, **kwargs)

    def refresh(self) -> None:
        return None


@dataclass(eq=False)
class FakeTask:
    name: str
    cancelled: bool = False

    def done(self) -> bool:
        return self.cancelled

    def cancel(self) -> None:
        self.cancelled = True


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any], FakeElement]] = []

    def record(self, kind: str, *args: Any, **kwargs: Any) -> FakeElement:
        element = FakeElement(
            kind=kind, args=args, kwargs=kwargs, value=kwargs.get("value")
        )
        self.calls.append((kind, args, kwargs, element))
        return element


def _patch_ui(monkeypatch: pytest.MonkeyPatch, recorder: Recorder) -> None:
    monkeypatch.setattr(
        dashboard_module.ui,
        "column",
        lambda *args, **kwargs: recorder.record("column", *args, **kwargs),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "row",
        lambda *args, **kwargs: recorder.record("row", *args, **kwargs),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "card",
        lambda *args, **kwargs: recorder.record("card", *args, **kwargs),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "splitter",
        lambda *args, **kwargs: recorder.record("splitter", *args, **kwargs),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "tabs",
        lambda *args, **kwargs: recorder.record("tabs", *args, **kwargs),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "tab_panels",
        lambda *args, **kwargs: recorder.record("tab_panels", *args, **kwargs),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "tab_panel",
        lambda *args, **kwargs: recorder.record("tab_panel", *args, **kwargs),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "scroll_area",
        lambda *args, **kwargs: recorder.record("scroll_area", *args, **kwargs),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "select",
        lambda *args, **kwargs: recorder.record("select", *args, **kwargs),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "timer",
        lambda interval, callback, *, active=True, once=False, immediate=True: recorder.record(
            "timer", interval, callback, active=active, once=once, immediate=immediate
        ),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "echart",
        lambda *args, **kwargs: recorder.record("echart", *args, **kwargs),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "notification",
        lambda *args, **kwargs: recorder.record("notification", *args, **kwargs),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "aggrid",
        lambda *args, **kwargs: recorder.record("aggrid", *args, **kwargs),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "chip",
        lambda *args, **kwargs: recorder.record("chip", *args, **kwargs),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "label",
        lambda *args, **kwargs: recorder.record("label", *args, **kwargs),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "space",
        lambda *args, **kwargs: recorder.record("space", *args, **kwargs),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "icon",
        lambda *args, **kwargs: recorder.record("icon", *args, **kwargs),
    )
    monkeypatch.setattr(
        dashboard_module.ui,
        "refreshable",
        lambda func: RefreshableWrapper(func),
    )


def _make_injected_readers(participant_factory):
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
        "service_catalog_reader": _reader(
            orchestration.Orchestration.ServiceCatalog, "ServiceCatalog"
        ),
    }


class TestDashboardBackend:
    def test_backend_can_be_injected(self, participant_factory):
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)
        assert backend.name == "HospitalDashboard"
        asyncio.run(backend.close())

    def test_backend_updates_state_from_samples(self, participant_factory):
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(dashboard_module.ui, "notification", lambda *a, **k: None)

        backend.update_procedure_status(
            SimpleNamespace(
                procedure_id="proc-001",
                phase=int(surgery.Surgery.ProcedurePhase.IN_PROGRESS),
                status_message="Surgery active",
            )
        )
        backend.update_procedure_context(
            SimpleNamespace(
                procedure_id="proc-001",
                room="OR-3",
                patient=SimpleNamespace(id="patient-001", name="Jane Doe"),
                procedure_type="Appendectomy",
                surgeon="Dr. Smith",
            )
        )
        backend.update_patient_vitals(
            SimpleNamespace(
                patient_id="patient-001",
                heart_rate=105.0,
                spo2=93.0,
                systolic_bp=165.0,
                diastolic_bp=95.0,
            )
        )
        backend.update_robot_state(
            SimpleNamespace(procedure_id="proc-001", room="OR-3", mode="OPERATIONAL")
        )
        backend.update_clinical_alert(
            SimpleNamespace(
                alert_id="alert-001",
                severity="CRITICAL",
                room="OR-3",
                patient=SimpleNamespace(name="Jane Doe"),
                category="Vitals",
                message="Heart rate critical",
            )
        )
        backend.update_resource_availability(
            SimpleNamespace(
                name="OR-3",
                kind="Operating Room",
                status="AVAILABLE",
                location="North Wing",
            )
        )

        assert backend.procedures["proc-001"].phase == "In Progress"
        assert backend.procedures["proc-001"].room == "OR-3"
        assert backend.procedures["proc-001"].vitals["heart_rate"] == 105.0
        assert backend.procedures["proc-001"].robot_state == "OPERATIONAL"
        assert backend.alerts[0].highlighted is True
        assert backend.resources["OR-3"].status == "AVAILABLE"
        monkeypatch.undo()
        asyncio.run(backend.close())

    def test_start_schedules_background_tasks(self, participant_factory, monkeypatch):
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)
        scheduled: list[str] = []

        def _fake_create(coroutine):
            scheduled.append(getattr(coroutine, "__name__", "task"))
            coroutine.close()
            return FakeTask(name=scheduled[-1])

        monkeypatch.setattr(
            dashboard_module.background_tasks,
            "create",
            _fake_create,
        )

        asyncio.run(backend.start())
        assert len(scheduled) == 9
        asyncio.run(backend.close())


class TestDashboardPage:
    def test_main_uses_default_nicegui_browser_behavior(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("MEDTECH_NICEGUI_STORAGE_SECRET", "test-secret")
        calls: list[dict[str, Any]] = []

        def _fake_run(*args: Any, **kwargs: Any) -> None:
            calls.append(kwargs)

        monkeypatch.setattr(dashboard_module.ui, "run", _fake_run)

        dashboard_module.main()

        assert calls and "show" not in calls[0]

    def test_backend_close_cleans_up_rti_dispatcher(
        self, participant_factory, monkeypatch
    ):
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)

        called = False

        async def _fake_close() -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(dashboard_module.rti.asyncio, "close", _fake_close)

        asyncio.run(backend.close())

        assert called is True

    def test_main_swallows_keyboard_interrupt(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MEDTECH_NICEGUI_STORAGE_SECRET", "test-secret")
        monkeypatch.setattr(
            dashboard_module.ui,
            "run",
            lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
        )

        dashboard_module.main()

    def test_page_builds_dashboard_shell(self, monkeypatch: pytest.MonkeyPatch):
        recorder = Recorder()
        _patch_ui(monkeypatch, recorder)
        monkeypatch.setattr(dashboard_module, "init_theme", lambda: None)
        monkeypatch.setattr(
            dashboard_module,
            "create_header",
            lambda title="Medtech Suite": recorder.record("header", title),
        )
        monkeypatch.setattr(
            dashboard_module,
            "backend",
            SimpleNamespace(
                procedures={},
                alerts=[
                    dashboard_module.AlertEntry(
                        alert_id="alert-001",
                        severity="CRITICAL",
                        room="OR-3",
                        patient_name="Jane Doe",
                        category="Vitals",
                        message="Heart rate critical",
                    )
                ],
                resources={},
                rooms={},
                severity_filter="ALL",
                room_filter="ALL",
                filtered_alerts=lambda: [
                    dashboard_module.AlertEntry(
                        alert_id="alert-001",
                        severity="CRITICAL",
                        room="OR-3",
                        patient_name="Jane Doe",
                        category="Vitals",
                        message="Heart rate critical",
                    )
                ],
            ),
        )

        dashboard_module.dashboard_page()

        kinds = [call[0] for call in recorder.calls]
        assert "header" in kinds
        assert "tab_panels" in kinds
        assert "scroll_area" in kinds
        assert "select" in kinds
        assert "timer" in kinds
        assert "echart" in kinds

    def test_quasar_icon_set_constant(self):
        assert NICEGUI_QUASAR_CONFIG["iconSet"] == "material-icons-outlined"


class TestConstants:
    def test_icon_constants_exist(self):
        assert ICONS["dashboard"] == "space_dashboard"
        assert BRAND_COLORS["blue"] == "#004A8A"


# ---------------------------------------------------------------------------
# Step N.7 test gate — Robot Status, Liveliness, Resource Panel, CFT, Burst
# ---------------------------------------------------------------------------


class TestRobotStatusDisplay:
    """Gate: Robot state per OR with mode indicator; E-STOP prominently displayed."""

    def test_robot_mode_label_operational(self):
        mode_int = int(surgery.Surgery.RobotMode.OPERATIONAL)
        label = dashboard_module._robot_mode_label(mode_int)
        assert label == "OPERATIONAL"

    def test_robot_mode_label_emergency_stop(self):
        mode_int = int(surgery.Surgery.RobotMode.EMERGENCY_STOP)
        label = dashboard_module._robot_mode_label(mode_int)
        assert label == "E-STOP"

    def test_robot_mode_label_paused(self):
        mode_int = int(surgery.Surgery.RobotMode.PAUSED)
        assert dashboard_module._robot_mode_label(mode_int) == "PAUSED"

    def test_robot_mode_label_passthrough_str(self):
        assert dashboard_module._robot_mode_label("OPERATIONAL") == "OPERATIONAL"

    def test_robot_mode_color_emergency_stop_is_red(self):
        mode_int = int(surgery.Surgery.RobotMode.EMERGENCY_STOP)
        color = dashboard_module._robot_mode_color(mode_int)
        assert color == BRAND_COLORS["red"]

    def test_robot_mode_color_operational_is_green(self):
        mode_int = int(surgery.Surgery.RobotMode.OPERATIONAL)
        color = dashboard_module._robot_mode_color(mode_int)
        assert color == BRAND_COLORS["green"]

    def test_update_robot_state_maps_idl_enum(self, participant_factory):
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)

        # Simulate a real DDS RobotState sample with operational_mode enum int
        backend.update_procedure_context(
            SimpleNamespace(
                procedure_id="proc-R1",
                room="OR-5",
                patient=SimpleNamespace(id="p-R1", name="Alice"),
                procedure_type="Spine",
                surgeon="Dr. T",
            )
        )
        sample = SimpleNamespace(
            robot_id="robot-001",
            procedure_id="proc-R1",
            operational_mode=int(surgery.Surgery.RobotMode.OPERATIONAL),
        )
        backend.update_robot_state(sample)

        entry = backend.procedures["proc-R1"]
        assert entry.robot_state == "OPERATIONAL"
        assert entry.robot_color == BRAND_COLORS["green"]
        assert entry.robot_disconnected is False

        asyncio.run(backend.close())

    def test_update_robot_state_estop(self, participant_factory):
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)

        backend.update_procedure_context(
            SimpleNamespace(
                procedure_id="proc-R2",
                room="OR-6",
                patient=SimpleNamespace(id="p-R2", name="Bob"),
                procedure_type="Knee",
                surgeon="Dr. M",
            )
        )
        sample = SimpleNamespace(
            robot_id="robot-002",
            procedure_id="proc-R2",
            operational_mode=int(surgery.Surgery.RobotMode.EMERGENCY_STOP),
        )
        backend.update_robot_state(sample)

        entry = backend.procedures["proc-R2"]
        assert entry.robot_state == "E-STOP"
        assert entry.robot_color == BRAND_COLORS["red"]
        assert entry.robot_disconnected is False

        asyncio.run(backend.close())


class TestLivelinessDisconnect:
    """Gate: Robot disconnect detected via liveliness."""

    def test_mark_robot_disconnected_by_id(self, participant_factory):
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(dashboard_module.ui, "notification", lambda *a, **k: None)

        # Set up a robot → procedure mapping
        backend.update_procedure_context(
            SimpleNamespace(
                procedure_id="proc-L1",
                room="OR-1",
                patient=SimpleNamespace(id="pL1", name="Carol"),
                procedure_type="Hip",
                surgeon="Dr. X",
            )
        )
        backend.update_robot_state(
            SimpleNamespace(
                robot_id="robot-L1",
                procedure_id="proc-L1",
                operational_mode=int(surgery.Surgery.RobotMode.OPERATIONAL),
            )
        )
        assert backend.procedures["proc-L1"].robot_state == "OPERATIONAL"

        # Simulate liveliness loss
        backend.mark_robot_disconnected("robot-L1")

        entry = backend.procedures["proc-L1"]
        assert entry.robot_state == "Disconnected"
        assert entry.robot_color == BRAND_COLORS["light_gray"]
        assert entry.robot_disconnected is True

        monkeypatch.undo()
        asyncio.run(backend.close())

    def test_mark_robot_disconnected_unknown_id_marks_all(self, participant_factory):
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)

        backend.update_procedure_context(
            SimpleNamespace(
                procedure_id="proc-L2",
                room="OR-2",
                patient=SimpleNamespace(id="pL2", name="Dave"),
                procedure_type="Shoulder",
                surgeon="Dr. Y",
            )
        )
        # No robot_id mapping — simulate losing an unknown robot
        backend.mark_robot_disconnected("")

        entry = backend.procedures["proc-L2"]
        assert entry.robot_state == "Disconnected"
        assert entry.robot_disconnected is True
        asyncio.run(backend.close())

    def test_monitor_liveliness_task_marks_disconnected(
        self, participant_factory, monkeypatch
    ):
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)

        # Prime a known robot_id → procedure mapping
        backend.update_procedure_context(
            SimpleNamespace(
                procedure_id="proc-L3",
                room="OR-3",
                patient=SimpleNamespace(id="pL3", name="Eve"),
                procedure_type="Wrist",
                surgeon="Dr. Z",
            )
        )
        backend.update_robot_state(
            SimpleNamespace(
                robot_id="robot-L3",
                procedure_id="proc-L3",
                operational_mode=int(surgery.Surgery.RobotMode.OPERATIONAL),
            )
        )

        # Mock liveliness_changed_status to report lost liveliness
        class _MockStatus:
            alive_count = 0
            not_alive_count = 1

        monkeypatch.setattr(
            type(backend._robot_state_reader),
            "liveliness_changed_status",
            property(lambda self: _MockStatus()),
        )

        async def _run_one_poll() -> None:
            backend._running = True
            # Run one iteration of the monitor loop
            status = backend._robot_state_reader.liveliness_changed_status
            if status.alive_count == 0 and status.not_alive_count > 0:
                for robot_id in list(backend._robot_id_to_procedure.keys()):
                    backend.mark_robot_disconnected(robot_id)

        asyncio.run(_run_one_poll())

        entry = backend.procedures["proc-L3"]
        assert entry.robot_state == "Disconnected"
        assert entry.robot_disconnected is True
        asyncio.run(backend.close())


class TestResourcePanel:
    """Gate: Resource panel displays and updates in real-time."""

    def test_update_resource_availability(self, participant_factory):
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)

        backend.update_resource_availability(
            SimpleNamespace(
                name="OR-3",
                kind="Operating Room",
                status="AVAILABLE",
                location="North Wing",
                resource_name="",
                resource_kind="",
                availability_status="",
            )
        )
        assert "OR-3" in backend.resources
        assert backend.resources["OR-3"].status == "AVAILABLE"
        assert backend.resources["OR-3"].kind == "Operating Room"
        asyncio.run(backend.close())

    def test_resource_panel_renders_aggrid(
        self, participant_factory, monkeypatch: pytest.MonkeyPatch
    ):
        recorder = Recorder()
        _patch_ui(monkeypatch, recorder)
        monkeypatch.setattr(dashboard_module, "init_theme", lambda: None)
        monkeypatch.setattr(
            dashboard_module,
            "create_header",
            lambda title="Medtech Suite": recorder.record("header", title),
        )

        rp = dashboard_module.ResourceEntry(
            name="OR-4", kind="OR", status="AVAILABLE", location="East"
        )
        monkeypatch.setattr(
            dashboard_module,
            "backend",
            SimpleNamespace(
                procedures={},
                alerts=[],
                resources={"OR-4": rp},
                rooms={},
                severity_filter="ALL",
                room_filter="ALL",
                filtered_alerts=lambda: [],
            ),
        )

        dashboard_module.dashboard_page()

        kinds = [call[0] for call in recorder.calls]
        assert "aggrid" in kinds

    def test_resource_updates_in_place(self, participant_factory):
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)

        backend.update_resource_availability(
            SimpleNamespace(
                name="OR-5",
                kind="OR",
                status="AVAILABLE",
                location="South",
                resource_name="",
                resource_kind="",
                availability_status="",
            )
        )
        assert backend.resources["OR-5"].status == "AVAILABLE"

        # Update the same resource
        backend.update_resource_availability(
            SimpleNamespace(
                name="OR-5",
                kind="OR",
                status="UNAVAILABLE",
                location="South",
                resource_name="",
                resource_kind="",
                availability_status="",
            )
        )
        assert backend.resources["OR-5"].status == "UNAVAILABLE"
        assert len(backend.resources) == 1  # no duplicate entry
        asyncio.run(backend.close())


class TestContentFilteredTopic:
    """Gate: Content-filtered topic delivers only matching patient data."""

    def test_select_patient_filter_noop_without_participant(self, participant_factory):
        """In injection mode (no participant), select_patient_filter is a no-op."""
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)
        original_reader = backend._patient_vitals_reader

        backend.select_patient_filter("patient-001")

        assert backend._patient_vitals_reader is original_reader
        asyncio.run(backend.close())

    def test_select_patient_filter_rejects_invalid_chars(self, participant_factory):
        """Filter method must reject patient_id values containing SQL metacharacters."""
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)
        original_reader = backend._patient_vitals_reader

        backend.select_patient_filter("patient' OR '1'='1")

        assert backend._patient_vitals_reader is original_reader
        asyncio.run(backend.close())

    @pytest.mark.integration
    @pytest.mark.filtering
    def test_content_filtered_topic_delivers_only_matching_patient(
        self, participant_factory
    ):
        """CFT with patient_id filter delivers only matching patient data."""
        import monitoring

        p_write = participant_factory(domain_id=0)
        p_read = participant_factory(domain_id=0)

        topic_w = dds.Topic(
            p_write, "PatientVitals_CFT", monitoring.Monitoring.PatientVitals
        )
        topic_r = dds.Topic(
            p_read, "PatientVitals_CFT", monitoring.Monitoring.PatientVitals
        )

        cft = dds.ContentFilteredTopic(
            topic_r,
            "PatientVitals_CFT_filtered",
            dds.Filter("patient_id = 'patient-001'"),
        )

        pub = dds.Publisher(p_write)
        sub = dds.Subscriber(p_read)

        w_qos = dds.DataWriterQos()
        r_qos = dds.DataReaderQos()

        writer = dds.DataWriter(pub, topic_w, w_qos)
        reader = dds.DataReader(sub, cft, r_qos)

        # Wait for discovery
        from tests.conftest import wait_for_discovery

        assert wait_for_discovery(writer, reader)

        # Write for matching patient
        s1 = monitoring.Monitoring.PatientVitals()
        s1.patient_id = "patient-001"
        s1.heart_rate = 72.0
        writer.write(s1)

        # Write for non-matching patient
        s2 = monitoring.Monitoring.PatientVitals()
        s2.patient_id = "patient-002"
        s2.heart_rate = 90.0
        writer.write(s2)

        # Wait for data to arrive
        from tests.conftest import wait_for_data

        assert wait_for_data(
            reader, timeout_sec=2.0
        ), "Expected filtered data for patient-001"

        received = reader.take_data()
        received_ids = [str(s.patient_id) for s in received]

        assert "patient-001" in received_ids, "Matching patient data must arrive"
        assert (
            "patient-002" not in received_ids
        ), "Non-matching patient data must be filtered out"


class TestDDSBurstResponsiveness:
    """Gate: DDS data processing does not block the UI thread."""

    def test_receive_methods_are_async_coroutines(self, participant_factory):
        """All receive tasks must be coroutine functions (non-blocking by contract)."""
        import inspect

        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)

        async_methods = [
            backend._receive_procedure_status,
            backend._receive_procedure_context,
            backend._receive_patient_vitals,
            backend._receive_alarm_messages,
            backend._receive_robot_state,
            backend._receive_clinical_alerts,
            backend._receive_resource_availability,
            backend._receive_service_catalog,
            backend._monitor_robot_liveliness,
        ]

        for method in async_methods:
            assert inspect.iscoroutinefunction(
                method
            ), f"{method.__name__} must be an async def coroutine function"

        asyncio.run(backend.close())

    def test_burst_of_samples_updates_state_without_error(self, participant_factory):
        """Backend processes a burst of mixed samples without raising exceptions."""
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(dashboard_module.ui, "notification", lambda *a, **k: None)
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)

        # Populate a procedure context first
        backend.update_procedure_context(
            SimpleNamespace(
                procedure_id="proc-burst",
                room="OR-B",
                patient=SimpleNamespace(id="burst-patient", name="Frank"),
                procedure_type="Burst Test",
                surgeon="Dr. Burst",
            )
        )

        # Burst: vitals + robot state + alert + resource — all in rapid succession
        for i in range(20):
            backend.update_patient_vitals(
                SimpleNamespace(
                    patient_id="burst-patient",
                    heart_rate=60.0 + i,
                    spo2=95.0,
                    systolic_bp=120.0,
                    diastolic_bp=80.0,
                )
            )
            backend.update_robot_state(
                SimpleNamespace(
                    robot_id="robot-burst",
                    procedure_id="proc-burst",
                    operational_mode=int(surgery.Surgery.RobotMode.OPERATIONAL),
                )
            )
            backend.update_clinical_alert(
                SimpleNamespace(
                    alert_id=f"alert-burst-{i}",
                    severity="INFO",
                    room="OR-B",
                    patient=SimpleNamespace(name="Frank"),
                    category="Test",
                    message=f"burst {i}",
                )
            )
            backend.update_resource_availability(
                SimpleNamespace(
                    name=f"resource-{i % 5}",
                    kind="OR",
                    status="AVAILABLE",
                    location="Test",
                    resource_name="",
                    resource_kind="",
                    availability_status="",
                )
            )

        # All 20 vitals samples update the same entry — last value wins
        assert backend.procedures["proc-burst"].vitals["heart_rate"] == 79.0
        # 20 alerts should have been accumulated
        assert len(backend.alerts) >= 20
        # Resources indexed by name mod 5 → 5 unique keys
        assert len(backend.resources) == 5

        monkeypatch.undo()
        asyncio.run(backend.close())


# ---------------------------------------------------------------------------
# Room Card aggregation from ServiceCatalog (Step UX.3)
# ---------------------------------------------------------------------------


class TestRoomCards:
    """Room card aggregation from ServiceCatalog samples."""

    def test_service_catalog_creates_room(self, participant_factory):
        """A ServiceCatalog with room_id property creates a RoomEntry."""
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)
        backend.update_service_catalog(
            SimpleNamespace(
                host_id="host-1",
                service_id="svc-1",
                display_name="Robot Arm",
                properties=[
                    SimpleNamespace(name="room_id", current_value="OR-1"),
                ],
            )
        )
        assert "OR-1" in backend.rooms
        assert backend.rooms["OR-1"].service_total == 1
        asyncio.run(backend.close())

    def test_room_shows_procedure_indicator(self, participant_factory):
        """Room with procedure_id property shows active procedure."""
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)
        backend.update_service_catalog(
            SimpleNamespace(
                host_id="host-1",
                service_id="svc-1",
                display_name="Robot Arm",
                properties=[
                    SimpleNamespace(name="room_id", current_value="OR-1"),
                    SimpleNamespace(name="procedure_id", current_value="proc-100"),
                ],
            )
        )
        assert backend.rooms["OR-1"].procedure_id == "proc-100"
        asyncio.run(backend.close())

    def test_room_aggregates_service_counts(self, participant_factory):
        """Multiple services in the same room increment service_total."""
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)
        for i in range(3):
            backend.update_service_catalog(
                SimpleNamespace(
                    host_id=f"host-{i}",
                    service_id=f"svc-{i}",
                    display_name=f"Service {i}",
                    properties=[
                        SimpleNamespace(name="room_id", current_value="OR-2"),
                    ],
                )
            )
        assert backend.rooms["OR-2"].service_total == 3
        asyncio.run(backend.close())

    def test_room_collects_gui_urls(self, participant_factory):
        """Room card collects gui_url entries for action links."""
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)
        backend.update_service_catalog(
            SimpleNamespace(
                host_id="host-1",
                service_id="twin-svc",
                display_name="Digital Twin",
                properties=[
                    SimpleNamespace(name="room_id", current_value="OR-1"),
                    SimpleNamespace(name="gui_url", current_value="http://twin:8081"),
                ],
            )
        )
        assert "Digital Twin" in backend.rooms["OR-1"].gui_urls
        assert backend.rooms["OR-1"].gui_urls["Digital Twin"] == "http://twin:8081"
        asyncio.run(backend.close())

    def test_new_rooms_auto_appear(self, participant_factory):
        """New rooms auto-appear as ServiceCatalog samples arrive."""
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)
        assert len(backend.rooms) == 0
        backend.update_service_catalog(
            SimpleNamespace(
                host_id="h1",
                service_id="s1",
                display_name="Svc",
                properties=[
                    SimpleNamespace(name="room_id", current_value="OR-A"),
                ],
            )
        )
        assert len(backend.rooms) == 1
        backend.update_service_catalog(
            SimpleNamespace(
                host_id="h2",
                service_id="s2",
                display_name="Svc2",
                properties=[
                    SimpleNamespace(name="room_id", current_value="OR-B"),
                ],
            )
        )
        assert len(backend.rooms) == 2
        asyncio.run(backend.close())

    def test_room_without_gui_url_has_empty_links(self, participant_factory):
        """Room card without gui_url entries has no action links."""
        readers = _make_injected_readers(participant_factory)
        backend = dashboard_module.DashboardBackend(**readers)
        backend.update_service_catalog(
            SimpleNamespace(
                host_id="h1",
                service_id="s1",
                display_name="Robot Arm",
                properties=[
                    SimpleNamespace(name="room_id", current_value="OR-1"),
                ],
            )
        )
        assert len(backend.rooms["OR-1"].gui_urls) == 0
        asyncio.run(backend.close())
