"""Unit tests for config.py — Global Configuration Center.

Covers:
- Default value correctness
- Environment variable override
- Type validation and boundary checks
- Automatic derived value computation
- Boolean parsing
"""

import os
import sys
import importlib
from unittest import mock

import pytest


# ============================================================================
# Fixtures: reload config module for each test
# ============================================================================


@pytest.fixture(autouse=True)
def reset_config_module():
    """Reset config module and environment before each test.

    We re-import config.py to ensure it picks up the current os.environ state.
    """
    # Clear VTYPE_* env vars from this test
    keys_to_remove = [k for k in os.environ if k.startswith("VTYPE_")]
    for k in keys_to_remove:
        del os.environ[k]

    # Remove config from sys.modules so importlib.reload works
    for mod_name in list(sys.modules.keys()):
        if mod_name == "config" or mod_name.startswith("config."):
            del sys.modules[mod_name]

    yield

    # Cleanup after test
    keys_to_remove = [k for k in os.environ if k.startswith("VTYPE_")]
    for k in keys_to_remove:
        del os.environ[k]


def _reload_config():
    """Helper: import (or re-import) config module."""
    if "config" in sys.modules:
        del sys.modules["config"]
    import config
    return config


# ============================================================================
# Default Values
# ============================================================================


class TestDefaultValues:
    """Verify all default configuration values match REQUIREMENTS.md."""

    def test_sample_rate_default(self):
        config = _reload_config()
        assert config.SAMPLE_RATE == 16000

    def test_channels_default(self):
        config = _reload_config()
        assert config.CHANNELS == 1

    def test_frame_duration_ms_default(self):
        config = _reload_config()
        assert config.FRAME_DURATION_MS == 20

    def test_block_size_default(self):
        config = _reload_config()
        # 16000 * 20 / 1000 = 320
        assert config.BLOCK_SIZE == 320

    def test_dtype_default(self):
        config = _reload_config()
        assert config.DTYPE == "int16"

    def test_vad_aggressiveness_default(self):
        config = _reload_config()
        assert config.VAD_AGGRESSIVENESS == 3

    def test_silence_limit_ms_default(self):
        config = _reload_config()
        assert config.SILENCE_LIMIT_MS == 800

    def test_silence_frame_limit_default(self):
        config = _reload_config()
        assert config.SILENCE_FRAME_LIMIT == 40  # 800 // 20

    def test_model_size_default(self):
        config = _reload_config()
        assert config.MODEL_SIZE == "base"

    def test_compute_type_default(self):
        config = _reload_config()
        assert config.COMPUTE_TYPE == "int8"

    def test_device_default(self):
        config = _reload_config()
        assert config.DEVICE == "cpu"

    def test_beam_size_default(self):
        config = _reload_config()
        assert config.BEAM_SIZE == 3

    def test_language_default(self):
        config = _reload_config()
        assert config.LANGUAGE == "zh"

    def test_type_delay_default(self):
        config = _reload_config()
        assert config.TYPE_DELAY == 0.005

    def test_clipboard_fallback_default(self):
        config = _reload_config()
        assert config.CLIPBOARD_FALLBACK is True

    def test_queue_maxsize_default(self):
        config = _reload_config()
        assert config.QUEUE_MAXSIZE == 10


# ============================================================================
# Environment Variable Override
# ============================================================================


class TestEnvOverride:
    """Verify environment variable override works for each parameter."""

    def test_override_sample_rate(self):
        os.environ["VTYPE_SAMPLE_RATE"] = "44100"
        config = _reload_config()
        assert config.SAMPLE_RATE == 44100

    def test_override_model_size(self):
        os.environ["VTYPE_MODEL_SIZE"] = "small"
        config = _reload_config()
        assert config.MODEL_SIZE == "small"

    def test_override_silence_limit(self):
        os.environ["VTYPE_SILENCE_LIMIT_MS"] = "1200"
        config = _reload_config()
        assert config.SILENCE_LIMIT_MS == 1200

    def test_override_clipboard_fallback_false(self):
        os.environ["VTYPE_CLIPBOARD_FALLBACK"] = "false"
        config = _reload_config()
        assert config.CLIPBOARD_FALLBACK is False

    def test_override_clipboard_fallback_0(self):
        os.environ["VTYPE_CLIPBOARD_FALLBACK"] = "0"
        config = _reload_config()
        assert config.CLIPBOARD_FALLBACK is False

    def test_override_clipboard_fallback_no(self):
        os.environ["VTYPE_CLIPBOARD_FALLBACK"] = "no"
        config = _reload_config()
        assert config.CLIPBOARD_FALLBACK is False

    def test_override_clipboard_fallback_true(self):
        os.environ["VTYPE_CLIPBOARD_FALLBACK"] = "true"
        config = _reload_config()
        assert config.CLIPBOARD_FALLBACK is True

    def test_override_clipboard_fallback_1(self):
        os.environ["VTYPE_CLIPBOARD_FALLBACK"] = "1"
        config = _reload_config()
        assert config.CLIPBOARD_FALLBACK is True

    def test_override_clipboard_fallback_yes(self):
        os.environ["VTYPE_CLIPBOARD_FALLBACK"] = "yes"
        config = _reload_config()
        assert config.CLIPBOARD_FALLBACK is True

    def test_override_language(self):
        os.environ["VTYPE_LANGUAGE"] = "en"
        config = _reload_config()
        assert config.LANGUAGE == "en"

    def test_override_compute_type(self):
        os.environ["VTYPE_COMPUTE_TYPE"] = "float16"
        config = _reload_config()
        assert config.COMPUTE_TYPE == "float16"

    def test_override_vad_aggressiveness(self):
        os.environ["VTYPE_VAD_AGGRESSIVENESS"] = "1"
        config = _reload_config()
        assert config.VAD_AGGRESSIVENESS == 1

    def test_override_type_delay(self):
        os.environ["VTYPE_TYPE_DELAY"] = "0.01"
        config = _reload_config()
        assert config.TYPE_DELAY == 0.01

    def test_override_queue_maxsize(self):
        os.environ["VTYPE_QUEUE_MAXSIZE"] = "20"
        config = _reload_config()
        assert config.QUEUE_MAXSIZE == 20


# ============================================================================
# Derived Value Computation
# ============================================================================


class TestDerivedValues:
    """Verify automatically computed values are correct."""

    def test_silence_frame_limit_computation(self):
        os.environ["VTYPE_SILENCE_LIMIT_MS"] = "1000"
        os.environ["VTYPE_FRAME_DURATION_MS"] = "20"
        config = _reload_config()
        assert config.SILENCE_FRAME_LIMIT == 50  # 1000 // 20

    def test_silence_frame_limit_with_custom_frame_duration(self):
        os.environ["VTYPE_SILENCE_LIMIT_MS"] = "900"
        os.environ["VTYPE_FRAME_DURATION_MS"] = "30"
        config = _reload_config()
        assert config.SILENCE_FRAME_LIMIT == 30  # 900 // 30

    def test_block_size_computation(self):
        os.environ["VTYPE_SAMPLE_RATE"] = "16000"
        os.environ["VTYPE_FRAME_DURATION_MS"] = "30"
        config = _reload_config()
        assert config.BLOCK_SIZE == 480  # 16000 * 30 / 1000


# ============================================================================
# Validation
# ============================================================================


class TestValidate:
    """Verify validate_config() catches invalid values."""

    def test_all_defaults_valid(self):
        config = _reload_config()
        errors = config.validate_config()
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_invalid_frame_duration(self):
        os.environ["VTYPE_FRAME_DURATION_MS"] = "25"
        config = _reload_config()
        errors = config.validate_config()
        assert any("FRAME_DURATION_MS" in e for e in errors)

    def test_invalid_vad_aggressiveness(self):
        os.environ["VTYPE_VAD_AGGRESSIVENESS"] = "5"
        config = _reload_config()
        errors = config.validate_config()
        assert any("VAD_AGGRESSIVENESS" in e for e in errors)

    def test_invalid_model_size(self):
        os.environ["VTYPE_MODEL_SIZE"] = "huge"
        config = _reload_config()
        errors = config.validate_config()
        assert any("MODEL_SIZE" in e for e in errors)

    def test_invalid_compute_type(self):
        os.environ["VTYPE_COMPUTE_TYPE"] = "int4"
        config = _reload_config()
        errors = config.validate_config()
        assert any("COMPUTE_TYPE" in e for e in errors)

    def test_invalid_device(self):
        os.environ["VTYPE_DEVICE"] = "tpu"
        config = _reload_config()
        errors = config.validate_config()
        assert any("DEVICE" in e for e in errors)

    def test_invalid_beam_size_too_large(self):
        os.environ["VTYPE_BEAM_SIZE"] = "20"
        config = _reload_config()
        errors = config.validate_config()
        assert any("BEAM_SIZE" in e for e in errors)

    def test_invalid_beam_size_zero(self):
        os.environ["VTYPE_BEAM_SIZE"] = "0"
        config = _reload_config()
        errors = config.validate_config()
        assert any("BEAM_SIZE" in e for e in errors)

    def test_invalid_silence_limit_too_small(self):
        os.environ["VTYPE_SILENCE_LIMIT_MS"] = "50"
        config = _reload_config()
        errors = config.validate_config()
        assert any("SILENCE_LIMIT_MS" in e for e in errors)

    def test_invalid_type_delay_negative(self):
        os.environ["VTYPE_TYPE_DELAY"] = "-0.001"
        config = _reload_config()
        errors = config.validate_config()
        assert any("TYPE_DELAY" in e for e in errors)

    def test_invalid_queue_maxsize_zero(self):
        os.environ["VTYPE_QUEUE_MAXSIZE"] = "0"
        config = _reload_config()
        errors = config.validate_config()
        assert any("QUEUE_MAXSIZE" in e for e in errors)

    def test_invalid_channels(self):
        os.environ["VTYPE_CHANNELS"] = "2"
        config = _reload_config()
        errors = config.validate_config()
        assert any("CHANNELS" in e for e in errors)

    def test_invalid_dtype(self):
        os.environ["VTYPE_DTYPE"] = "uint8"
        config = _reload_config()
        errors = config.validate_config()
        assert any("DTYPE" in e for e in errors)

    def test_block_size_inconsistency(self):
        os.environ["VTYPE_SAMPLE_RATE"] = "16000"
        os.environ["VTYPE_FRAME_DURATION_MS"] = "20"
        os.environ["VTYPE_BLOCK_SIZE"] = "999"  # inconsistent
        config = _reload_config()
        errors = config.validate_config()
        assert any("BLOCK_SIZE" in e for e in errors)


# ============================================================================
# Helper Functions
# ============================================================================


class TestGetConfigDict:
    """Verify get_config_dict() returns correct data."""

    def test_returns_dict(self):
        config = _reload_config()
        d = config.get_config_dict()
        assert isinstance(d, dict)
        assert len(d) > 10

    def test_contains_all_keys(self):
        config = _reload_config()
        d = config.get_config_dict()
        expected_keys = [
            "sample_rate", "channels", "block_size", "dtype",
            "frame_duration_ms", "vad_aggressiveness",
            "silence_limit_ms", "silence_frame_limit",
            "model_size", "compute_type", "device", "beam_size", "language",
            "type_delay", "clipboard_fallback", "queue_maxsize",
        ]
        for key in expected_keys:
            assert key in d, f"Missing key: {key}"

    def test_values_match_constants(self):
        config = _reload_config()
        d = config.get_config_dict()
        assert d["sample_rate"] == config.SAMPLE_RATE
        assert d["model_size"] == config.MODEL_SIZE
        assert d["silence_frame_limit"] == config.SILENCE_FRAME_LIMIT

    def test_is_independent_copy(self):
        """Modifying the returned dict should not affect config module."""
        config = _reload_config()
        d = config.get_config_dict()
        d["sample_rate"] = 99999
        assert config.SAMPLE_RATE == 16000  # unchanged


class TestPrintConfig:
    """Verify print_config() runs without error."""

    def test_print_config_no_error(self, capsys):
        config = _reload_config()
        config.print_config()
        captured = capsys.readouterr()
        assert "vType Configuration Summary" in captured.out

    def test_print_config_with_warnings(self, capsys):
        os.environ["VTYPE_FRAME_DURATION_MS"] = "25"
        config = _reload_config()
        config.print_config()
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
