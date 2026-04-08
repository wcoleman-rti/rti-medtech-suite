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
import pytest
import rti.connextdds as dds
import surgery
from hospital_dashboard.dashboard import nicegui_dashboard as dashboard_module
from medtech.gui import BRAND_COLORS, ICONS, NICEGUI_QUASAR_CONFIG

pytestmark = [
    pytest.mark.gui,
    pytest.mark.integration,
    pytest.mark.dashboard,
    pytest.mark.xdist_group("dashboard"),
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
        assert len(scheduled) == 7
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
        assert "splitter" in kinds
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
        assert BRAND_COLORS["blue"] == "#004C97"
