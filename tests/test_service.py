"""Unit tests for medtech.Service abstract interface.

A MockService implements the interface and verifies state transitions:
  STOPPED -> STARTING -> RUNNING -> (stop) -> STOPPING -> STOPPED
  STOPPED -> STARTING -> FAILED (on simulated error)
Also verifies stop() is non-blocking while run() is in progress.

Tags: @unit @orchestration
"""

from __future__ import annotations

import asyncio
import time

import pytest
from medtech.service import Service, ServiceState


class MockService(Service):
    """Concrete mock implementing medtech.Service for testing."""

    def __init__(self, *, simulate_failure: bool = False) -> None:
        self._state = ServiceState.STOPPED
        self._stop_event: asyncio.Event | None = None
        self._simulate_failure = simulate_failure

    async def run(self) -> None:
        self._state = ServiceState.STARTING

        if self._simulate_failure:
            self._state = ServiceState.FAILED
            return

        self._stop_event = asyncio.Event()
        self._state = ServiceState.RUNNING
        await self._stop_event.wait()

        self._state = ServiceState.STOPPING
        # simulate teardown
        self._state = ServiceState.STOPPED

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    @property
    def name(self) -> str:
        return "MockService"

    @property
    def state(self) -> ServiceState:
        return self._state


class TestServiceInitialState:
    def test_initial_state_is_stopped(self):
        svc = MockService()
        assert svc.state == ServiceState.STOPPED

    def test_name_is_stable(self):
        svc = MockService()
        assert svc.name == svc.name
        assert len(svc.name) > 0


class TestServiceLifecycle:
    @pytest.mark.asyncio
    async def test_full_lifecycle_transitions(self):
        svc = MockService()
        assert svc.state == ServiceState.STOPPED

        task = asyncio.create_task(svc.run())

        # Yield to let run() progress
        await asyncio.sleep(0.01)
        assert svc.state == ServiceState.RUNNING

        svc.stop()
        await task

        assert svc.state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_stop_is_non_blocking(self):
        svc = MockService()
        task = asyncio.create_task(svc.run())

        await asyncio.sleep(0.01)
        assert svc.state == ServiceState.RUNNING

        start = time.monotonic()
        svc.stop()
        elapsed = time.monotonic() - start

        assert elapsed < 0.1, f"stop() blocked for {elapsed:.3f}s"

        await task

    @pytest.mark.asyncio
    async def test_failed_state_on_error(self):
        svc = MockService(simulate_failure=True)
        assert svc.state == ServiceState.STOPPED

        await svc.run()

        assert svc.state == ServiceState.FAILED


class TestServiceStateIsIDLGenerated:
    def test_state_returns_idl_type(self):
        svc = MockService()
        assert isinstance(svc.state, ServiceState)

    def test_all_enum_values_exist(self):
        assert hasattr(ServiceState, "STOPPED")
        assert hasattr(ServiceState, "STARTING")
        assert hasattr(ServiceState, "RUNNING")
        assert hasattr(ServiceState, "STOPPING")
        assert hasattr(ServiceState, "FAILED")
        assert hasattr(ServiceState, "UNKNOWN")
