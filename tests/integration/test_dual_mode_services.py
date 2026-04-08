"""Tests for dual-mode service construction (Step 5.3).

Verifies that each refactored V1.0 service:
1. Constructs in hosted mode with a pre-created XML participant
2. Raises RuntimeError with the entity name when lookup fails
3. Transitions through STOPPED → STARTING → RUNNING → STOPPING → STOPPED

Tags: @integration @orchestration
"""

from __future__ import annotations

import asyncio

import app_names
import pytest
import rti.connextdds as dds
from conftest import test_participant_qos
from medtech.dds import initialize_connext
from medtech.service import ServiceState
from surgical_procedure.camera_sim.camera_service import CameraService
from surgical_procedure.device_telemetry_sim.device_telemetry_service import (
    DeviceTelemetryService,
)
from surgical_procedure.operator_sim.operator_console_service import (
    OperatorConsoleService,
)
from surgical_procedure.procedure_context_service import ProcedureContextService
from surgical_procedure.vitals_sim.bedside_monitor_service import BedsideMonitorService

names = app_names.MedtechEntityNames.SurgicalParticipants

pytestmark = [
    pytest.mark.integration,
    pytest.mark.orchestration,
]

ROOM_ID = "OR-DM"
PROCEDURE_ID = "proc-dm"
PARTITION = f"room/{ROOM_ID}/procedure/{PROCEDURE_ID}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_xml_participant(config_name: str) -> dds.DomainParticipant:
    """Create a participant from XML config with partition set."""
    initialize_connext()
    provider = dds.QosProvider.default
    p = provider.create_participant_from_config(config_name)
    qos = p.qos
    qos.partition.name = [PARTITION]
    p.qos = qos
    return p


def _bare_participant() -> dds.DomainParticipant:
    """Create a minimal DDS participant with no XML-defined entities."""
    qos = test_participant_qos()
    return dds.DomainParticipant(0, qos)


# ---------------------------------------------------------------------------
# Hosted Mode Construction
# ---------------------------------------------------------------------------


class TestHostedModeConstruction:
    """Each service constructs in hosted mode with a provided participant."""

    def test_bedside_monitor_hosted(self):
        p = _create_xml_participant(names.CLINICAL_MONITOR)
        try:
            svc = BedsideMonitorService(
                room_id=ROOM_ID,
                procedure_id=PROCEDURE_ID,
                participant=p,
            )
            assert svc.state == ServiceState.STOPPED
            assert svc.name == "BedsideMonitorService"
        finally:
            p.close()

    def test_camera_service_hosted(self):
        p = _create_xml_participant(names.OPERATIONAL_PUB)
        try:
            svc = CameraService(
                room_id=ROOM_ID,
                procedure_id=PROCEDURE_ID,
                participant=p,
            )
            assert svc.state == ServiceState.STOPPED
            assert svc.name == "CameraService"
        finally:
            p.close()

    def test_procedure_context_hosted(self):
        p = _create_xml_participant(names.OPERATIONAL_PUB)
        try:
            svc = ProcedureContextService(
                room_id=ROOM_ID,
                procedure_id=PROCEDURE_ID,
                participant=p,
            )
            assert svc.state == ServiceState.STOPPED
            assert svc.name == "ProcedureContextService"
        finally:
            p.close()

    def test_device_telemetry_hosted(self):
        p = _create_xml_participant(names.CLINICAL_DEVICE_GW)
        try:
            svc = DeviceTelemetryService(
                room_id=ROOM_ID,
                procedure_id=PROCEDURE_ID,
                participant=p,
            )
            assert svc.state == ServiceState.STOPPED
            assert svc.name == "DeviceTelemetryService"
        finally:
            p.close()

    def test_operator_console_hosted(self):
        p = _create_xml_participant(names.CONTROL_OPERATOR)
        try:
            svc = OperatorConsoleService(
                room_id=ROOM_ID,
                procedure_id=PROCEDURE_ID,
                participant=p,
            )
            assert svc.state == ServiceState.STOPPED
            assert svc.name == "OperatorConsoleService"
        finally:
            p.close()


# ---------------------------------------------------------------------------
# Entity Lookup Validation
# ---------------------------------------------------------------------------


class TestEntityLookupValidation:
    """Invalid participant config raises RuntimeError with entity name."""

    def test_bedside_monitor_invalid_participant(self):
        p = _bare_participant()
        try:
            with pytest.raises(RuntimeError, match=names.PATIENT_VITALS_WRITER):
                BedsideMonitorService(
                    room_id=ROOM_ID,
                    procedure_id=PROCEDURE_ID,
                    participant=p,
                )
        finally:
            p.close()

    def test_camera_service_invalid_participant(self):
        p = _bare_participant()
        try:
            with pytest.raises(RuntimeError, match=names.CAMERA_FRAME_WRITER):
                CameraService(
                    room_id=ROOM_ID,
                    procedure_id=PROCEDURE_ID,
                    participant=p,
                )
        finally:
            p.close()

    def test_procedure_context_invalid_participant(self):
        p = _bare_participant()
        try:
            with pytest.raises(RuntimeError, match=names.PROCEDURE_CONTEXT_WRITER):
                ProcedureContextService(
                    room_id=ROOM_ID,
                    procedure_id=PROCEDURE_ID,
                    participant=p,
                )
        finally:
            p.close()

    def test_device_telemetry_invalid_participant(self):
        p = _bare_participant()
        try:
            with pytest.raises(RuntimeError, match=names.DEVICE_TELEMETRY_WRITER):
                DeviceTelemetryService(
                    room_id=ROOM_ID,
                    procedure_id=PROCEDURE_ID,
                    participant=p,
                )
        finally:
            p.close()

    def test_operator_console_invalid_participant(self):
        p = _bare_participant()
        try:
            with pytest.raises(RuntimeError, match=names.OPERATOR_INPUT_WRITER):
                OperatorConsoleService(
                    room_id=ROOM_ID,
                    procedure_id=PROCEDURE_ID,
                    participant=p,
                )
        finally:
            p.close()


# ---------------------------------------------------------------------------
# State Transitions
# ---------------------------------------------------------------------------


class TestServiceStateTransitions:
    """Each service transitions STOPPED → STARTING → RUNNING → STOPPING → STOPPED."""

    @pytest.mark.asyncio
    async def test_bedside_monitor_lifecycle(self):
        svc = BedsideMonitorService(room_id=ROOM_ID, procedure_id=PROCEDURE_ID)
        assert svc.state == ServiceState.STOPPED

        task = asyncio.create_task(svc.run())
        await asyncio.sleep(0.2)
        assert svc.state == ServiceState.RUNNING

        svc.stop()
        await asyncio.wait_for(task, timeout=5.0)
        assert svc.state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_camera_service_lifecycle(self):
        svc = CameraService(room_id=ROOM_ID, procedure_id=PROCEDURE_ID)
        assert svc.state == ServiceState.STOPPED

        task = asyncio.create_task(svc.run())
        await asyncio.sleep(0.2)
        assert svc.state == ServiceState.RUNNING

        svc.stop()
        await asyncio.wait_for(task, timeout=5.0)
        assert svc.state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_procedure_context_lifecycle(self):
        svc = ProcedureContextService(room_id=ROOM_ID, procedure_id=PROCEDURE_ID)
        assert svc.state == ServiceState.STOPPED

        task = asyncio.create_task(svc.run())
        await asyncio.sleep(0.2)
        assert svc.state == ServiceState.RUNNING

        svc.stop()
        await asyncio.wait_for(task, timeout=5.0)
        assert svc.state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_device_telemetry_lifecycle(self):
        svc = DeviceTelemetryService(room_id=ROOM_ID, procedure_id=PROCEDURE_ID)
        assert svc.state == ServiceState.STOPPED

        task = asyncio.create_task(svc.run())
        await asyncio.sleep(0.2)
        assert svc.state == ServiceState.RUNNING

        svc.stop()
        await asyncio.wait_for(task, timeout=5.0)
        assert svc.state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_operator_console_lifecycle(self):
        svc = OperatorConsoleService(room_id=ROOM_ID, procedure_id=PROCEDURE_ID)
        assert svc.state == ServiceState.STOPPED

        task = asyncio.create_task(svc.run())
        # OperatorConsoleService has a 2 s discovery sleep before RUNNING
        await asyncio.sleep(2.5)
        assert svc.state == ServiceState.RUNNING

        svc.stop()
        await asyncio.wait_for(task, timeout=5.0)
        assert svc.state == ServiceState.STOPPED
