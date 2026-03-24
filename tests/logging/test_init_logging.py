"""Tests for medtech_logging (Step 1.7 test gates)."""

import pytest
from medtech_logging import ModuleLogger, ModuleName, init_logging


class TestInitLogging:
    """init_logging returns a ModuleLogger for valid module names."""

    def test_surgical_procedure(self):
        log = init_logging(ModuleName.SURGICAL_PROCEDURE)
        assert isinstance(log, ModuleLogger)

    def test_hospital_dashboard(self):
        log = init_logging(ModuleName.HOSPITAL_DASHBOARD)
        assert isinstance(log, ModuleLogger)

    def test_clinical_alerts(self):
        log = init_logging(ModuleName.CLINICAL_ALERTS)
        assert isinstance(log, ModuleLogger)


class TestModuleNameEnum:
    """ModuleName enum values match module directory names."""

    def test_surgical_procedure_value(self):
        assert ModuleName.SURGICAL_PROCEDURE == "surgical-procedure"

    def test_hospital_dashboard_value(self):
        assert ModuleName.HOSPITAL_DASHBOARD == "hospital-dashboard"

    def test_clinical_alerts_value(self):
        assert ModuleName.CLINICAL_ALERTS == "clinical-alerts"

    def test_is_str(self):
        assert isinstance(ModuleName.SURGICAL_PROCEDURE, str)

    def test_member_count(self):
        assert len(ModuleName) == 3


class TestInputValidation:
    """init_logging rejects non-enum arguments."""

    def test_raw_string_raises(self):
        with pytest.raises(TypeError, match="Expected a ModuleName"):
            init_logging("surgical-procedure")

    def test_empty_string_raises(self):
        with pytest.raises(TypeError, match="Expected a ModuleName"):
            init_logging("")

    def test_none_raises(self):
        with pytest.raises(TypeError, match="Expected a ModuleName"):
            init_logging(None)


class TestNoVerbositySetting:
    """init_logging does not set verbosity programmatically."""

    def test_returns_module_logger(self):
        log = init_logging(ModuleName.SURGICAL_PROCEDURE)
        assert isinstance(log, ModuleLogger)


class TestUserLogMessage:
    """User-category log messages can be written without error.

    The module prefix is added automatically — callers pass only
    the message body.
    """

    def test_notice(self):
        log = init_logging(ModuleName.SURGICAL_PROCEDURE)
        log.notice("Test log message — notice level")

    def test_warning(self):
        log = init_logging(ModuleName.CLINICAL_ALERTS)
        log.warning("Test log message — warning level")

    def test_error(self):
        log = init_logging(ModuleName.HOSPITAL_DASHBOARD)
        log.error("Test log message — error level")

    def test_informational(self):
        log = init_logging(ModuleName.SURGICAL_PROCEDURE)
        log.informational("Test log message — informational level")

    def test_debug(self):
        log = init_logging(ModuleName.CLINICAL_ALERTS)
        log.debug("Test log message — debug level")
