"""Tests for AquaWiz integration normalization logic.

Run with: python -m pytest integrations/test_aquawiz.py -v
"""

import pytest
from datetime import datetime, timezone

from integrations.aquawiz import (
    _safe_div,
    _safe_int,
    _parse_timestamp,
    _telemetry,
    AquaWizIntegration,
)
# ─── _safe_div ──────────────────────────────────────────────────────────────

class TestSafeDiv:
    def test_integer_divides_correctly(self):
        assert _safe_div(7566, 1000) == 7.566

    def test_zero_divides_correctly(self):
        assert _safe_div(0, 1000) == 0.0

    def test_negative_divides_correctly(self):
        assert _safe_div(-132, 1000) == -0.132

    def test_float_input(self):
        assert _safe_div(7500.0, 1000) == 7.5

    def test_none_returns_none(self):
        assert _safe_div(None, 1000) is None

    def test_string_number_parses(self):
        assert _safe_div("7566", 1000) == 7.566

    def test_invalid_string_returns_none(self):
        assert _safe_div("abc", 1000) is None

    def test_empty_string_returns_none(self):
        assert _safe_div("", 1000) is None


# ─── _safe_int ──────────────────────────────────────────────────────────────

class TestSafeInt:
    def test_integer_passthrough(self):
        assert _safe_int(65) == 65

    def test_zero(self):
        assert _safe_int(0) == 0

    def test_string_number(self):
        assert _safe_int("65") == 65

    def test_float_truncated(self):
        assert _safe_int(65.7) == 65

    def test_none_returns_none(self):
        assert _safe_int(None) is None

    def test_invalid_string_returns_none(self):
        assert _safe_int("abc") is None


# ─── _parse_timestamp ───────────────────────────────────────────────────────

class TestParseTimestamp:
    def test_epoch_millis_converts(self):
        # 1727272140000 ms = 2024-09-25T13:49:00Z
        result = _parse_timestamp(1727272140000)
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt.year == 2024
        assert dt.month == 9
        assert dt.day == 25
        assert dt.hour == 13
        assert dt.minute == 49

    def test_none_returns_none(self):
        assert _parse_timestamp(None) is None

    def test_invalid_returns_none(self):
        assert _parse_timestamp("not-a-timestamp") is None

    def test_zero_returns_epoch(self):
        result = _parse_timestamp(0)
        assert result is not None
        dt = datetime.fromisoformat(result)
        assert dt.year == 1970


# ─── KH normalization ───────────────────────────────────────────────────────

class TestKHNormalization:
    def test_kh_primary_fields(self):
        integration = AquaWizIntegration()
        raw = {
            "latest_kh": 7566,
            "latest_ph1": 7834,
            "field8": 7500,
            "latest_dos": 0,
            "latest_time": 1727272140000,
        }
        result = integration._normalize(raw, "kh", "KH1-00-02544")

        names = {r["parameter_name"]: r for r in result}

        assert "kh" in names
        assert names["kh"]["value"] == 7.566
        assert names["kh"]["unit"] == "dKH"

        assert "ph" in names
        assert names["ph"]["value"] == 7.834
        assert names["ph"]["unit"] == ""

        assert "kh_target" in names
        assert names["kh_target"]["value"] == 7.5
        assert names["kh_target"]["unit"] == "dKH"

        assert "kh_dosing" in names
        assert names["kh_dosing"]["value"] == 0
        assert names["kh_dosing"]["unit"] == "ml"

    def test_kh_missing_fields_yield_none(self):
        integration = AquaWizIntegration()
        raw = {"latest_time": 1727272140000}
        result = integration._normalize(raw, "kh", "KH1-00-02544")
        # Empty or missing numeric fields should produce no entries
        assert len(result) == 0

    def test_kh_null_values(self):
        integration = AquaWizIntegration()
        raw = {
            "latest_kh": None,
            "latest_ph1": None,
            "latest_dos": None,
            "latest_time": 1727272140000,
        }
        result = integration._normalize(raw, "kh", "KH1-00-02544")
        assert len(result) == 0

    def test_kh_negative_dosing(self):
        integration = AquaWizIntegration()
        raw = {"latest_kh": 7566, "latest_dos": -50, "latest_time": 1727272140000}
        result = integration._normalize(raw, "kh", "KH1-00-02544")
        names = {r["parameter_name"]: r for r in result}
        assert names["kh_dosing"]["value"] == -50


# ─── CaRx normalization ─────────────────────────────────────────────────────

class TestCaRxNormalization:
    def test_carx_primary_fields(self):
        integration = AquaWizIntegration()
        raw = {
            "latest_kh": -132,
            "latest_dos": 65,
            "serial": "CA1-00-00646",
            "latest_time": 1727268480000,
        }
        result = integration._normalize(raw, "carx", "CA1-00-00646")

        names = {r["parameter_name"]: r for r in result}

        assert "delta_kh" in names
        assert names["delta_kh"]["value"] == -0.132
        assert names["delta_kh"]["unit"] == "dKH"

        assert "co2_bubbles" in names
        assert names["co2_bubbles"]["value"] == 65
        assert names["co2_bubbles"]["unit"] == ""

    def test_carx_preserves_negative_sign(self):
        integration = AquaWizIntegration()
        raw = {"latest_kh": -132, "latest_dos": 0, "latest_time": 1727272140000}
        result = integration._normalize(raw, "carx", "CA1-00-00646")
        names = {r["parameter_name"]: r for r in result}
        assert names["delta_kh"]["value"] == -0.132

    def test_carx_missing_fields(self):
        integration = AquaWizIntegration()
        raw = {"latest_time": 1727272140000}
        result = integration._normalize(raw, "carx", "CA1-00-00646")
        assert len(result) == 0

    def test_carx_dos_different_interpretation(self):
        """Verify latest_dos is CO2 Bubbles for CaRx, not KH Dosing."""
        integration = AquaWizIntegration()
        raw = {"latest_kh": -5, "latest_dos": 120, "latest_time": 1727272140000}
        result = integration._normalize(raw, "carx", "CA1-00-00646")
        names = {r["parameter_name"]: r for r in result}
        assert "co2_bubbles" in names
        assert names["co2_bubbles"]["value"] == 120
        assert "kh_dosing" not in names


# ─── Device-specific behavior ──────────────────────────────────────────────

class TestDeviceSpecificBehavior:
    def test_kh_does_not_include_delta_kh(self):
        integration = AquaWizIntegration()
        raw = {"latest_kh": 7566, "latest_time": 1727272140000}
        result = integration._normalize(raw, "kh", "KH1-00-02544")
        names = {r["parameter_name"]: r for r in result}
        assert "delta_kh" not in names

    def test_carx_does_not_include_kh_dosing(self):
        integration = AquaWizIntegration()
        raw = {"latest_kh": -132, "latest_dos": 65, "latest_time": 1727272140000}
        result = integration._normalize(raw, "carx", "CA1-00-00646")
        names = {r["parameter_name"]: r for r in result}
        assert "kh_dosing" not in names

    def test_kh_does_not_expose_raw_fields(self):
        """Normalized result should never include raw AquaWiz response fields."""
        integration = AquaWizIntegration()
        raw = {
            "latest_kh": 7566,
            "access_token": "secret-token",
            "passcode": "1234",
            "latest_ph2": 7800,
            "latest_ph": 7800,
            "temperature": 25,
            "salinity": 35,
            "PO4": 0.05,
            "NO3": 3,
            "calcium": 430,
            "magnesium": 1350,
            "latest_time": 1727272140000,
        }
        result = integration._normalize(raw, "kh", "KH1-00-02544")
        all_values = [r["parameter_name"] for r in result]
        # None of the excluded fields should appear
        assert "temperature" not in all_values
        assert "salinity" not in all_values
        assert "PO4" not in all_values
        assert "NO3" not in all_values
        assert "calcium" not in all_values
        assert "magnesium" not in all_values

    def test_carx_does_not_expose_raw_fields(self):
        integration = AquaWizIntegration()
        raw = {
            "latest_kh": -132,
            "latest_dos": 65,
            "access_token": "secret",
            "temperature": 25,
            "latest_time": 1727272140000,
        }
        result = integration._normalize(raw, "carx", "CA1-00-00646")
        all_values = [r["parameter_name"] for r in result]
        assert "temperature" not in all_values
        assert "access_token" not in all_values


# ─── Device type detection ─────────────────────────────────────────────────

class TestDeviceTypeDetection:
    def test_kh_serial_detected(self):
        integration = AquaWizIntegration()
        assert integration._detect_device_type({"serial": "KH1-00-02544"}) == "kh"

    def test_carx_serial_detected(self):
        integration = AquaWizIntegration()
        assert integration._detect_device_type({"serial": "CA1-00-00646"}) == "carx"

    def test_lowercase_kh(self):
        integration = AquaWizIntegration()
        assert integration._detect_device_type({"serial": "kh1-00-02544"}) == "kh"

    def test_unknown_serial(self):
        integration = AquaWizIntegration()
        assert integration._detect_device_type({"serial": "XX1-00-00001"}) == "other"

    def test_missing_serial(self):
        integration = AquaWizIntegration()
        assert integration._detect_device_type({}) == "other"
