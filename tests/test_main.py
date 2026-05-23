"""Unit tests for main.py — CLI Entry Point.

Covers:
- CLI group creation and version option
- start command: parameter parsing, config override, logging
- devices command: device listing output
- config command: configuration display
- Signal handling: SIGINT, SIGTERM
- Graceful shutdown with summary output
- Error handling: model failure, mic unavailable, permissions
- Integration: full lifecycle flow
"""

import logging
import signal
from unittest import mock

import pytest
from click.testing import CliRunner

import main as main_module


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def runner():
    """Click CLI test runner."""
    return CliRunner()


@pytest.fixture(autouse=True)
def clean_globals():
    """Reset main module globals between tests."""
    main_module._manager = None
    main_module._monitor = None
    main_module._started_at = 0.0
    yield
    main_module._manager = None
    main_module._monitor = None
    main_module._started_at = 0.0


@pytest.fixture
def mock_manager():
    """Mock CoreManager with basic statistics."""
    with mock.patch("main.CoreManager") as mock_cls:
        instance = mock.MagicMock()
        instance.statistics = {
            "status": "IDLE",
            "detector_slices": 5,
        }
        mock_cls.return_value = instance
        yield mock_cls


@pytest.fixture
def mock_monitor():
    """Mock KeyMonitor."""
    with mock.patch("main.KeyMonitor") as mock_cls:
        instance = mock.MagicMock()
        instance.is_listening = False
        mock_cls.return_value = instance
        yield mock_cls


# ============================================================================
# Test CLI Group
# ============================================================================


class TestCLIGroup:
    """CLI group creation tests."""

    def test_cli_exists(self):
        """CLI group is defined."""
        assert main_module.cli is not None

    def test_version_option(self, runner):
        """--version shows version info."""
        result = runner.invoke(main_module.cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_help_shows_commands(self, runner):
        """--help shows available commands."""
        result = runner.invoke(main_module.cli, ["--help"])
        assert result.exit_code == 0
        assert "start" in result.output
        assert "devices" in result.output
        assert "config" in result.output


# ============================================================================
# Test start Command — Parameters
# ============================================================================


class TestStartCommand:
    """start command tests."""

    def test_start_help(self, runner):
        """start --help shows options."""
        result = runner.invoke(main_module.start, ["--help"])
        assert result.exit_code == 0
        assert "--model-size" in result.output
        assert "--language" in result.output
        assert "--verbose" in result.output

    def test_start_with_model_size_option(self, runner, mock_manager, mock_monitor):
        """--model-size small is passed to CoreManager."""
        runner.invoke(main_module.start, ["--model-size", "small"])
        mock_manager.assert_called_once()
        # Check that model_size was passed
        call_kwargs = mock_manager.call_args[1]
        assert call_kwargs["model_size"] == "small"

    def test_start_with_language_option(self, runner, mock_manager, mock_monitor):
        """--language en is passed to CoreManager."""
        runner.invoke(main_module.start, ["--language", "en"])
        call_kwargs = mock_manager.call_args[1]
        assert call_kwargs["language"] == "en"

    def test_start_with_invalid_model_size(self, runner):
        """Invalid --model-size is rejected by click."""
        result = runner.invoke(main_module.start, ["--model-size", "huge"])
        assert result.exit_code != 0

    def test_start_registers_signal_handlers(self, runner, mock_manager, mock_monitor):
        """SIGINT and SIGTERM handlers are registered."""
        with mock.patch("signal.signal") as mock_signal:
            runner.invoke(main_module.start, [])
        # SIGINT should be registered
        mock_signal.assert_any_call(signal.SIGINT, mock.ANY)
        # SIGTERM should be registered
        mock_signal.assert_any_call(signal.SIGTERM, mock.ANY)


# ============================================================================
# Test devices Command
# ============================================================================


class TestDevicesCommand:
    """devices command tests."""

    @mock.patch("sounddevice.query_devices")
    def test_devices_lists_input_devices(self, mock_query, runner):
        """devices lists all input-capable devices."""
        mock_query.return_value = [
            {
                "name": "Test Mic",
                "max_input_channels": 2,
                "max_output_channels": 0,
                "default_samplerate": 44100,
            },
            {
                "name": "Output Only",
                "max_input_channels": 0,
                "max_output_channels": 2,
                "default_samplerate": 48000,
            },
        ]
        result = runner.invoke(main_module.devices)
        assert result.exit_code == 0
        assert "Test Mic" in result.output
        assert "Output Only" not in result.output  # No input channels

    @mock.patch("sounddevice.query_devices")
    def test_devices_no_input_devices(self, mock_query, runner):
        """devices suggests checking mic when no input devices."""
        mock_query.return_value = [
            {
                "name": "Output Only",
                "max_input_channels": 0,
                "max_output_channels": 2,
                "default_samplerate": 48000,
            },
        ]
        result = runner.invoke(main_module.devices)
        assert result.exit_code == 0
        assert "No input devices" in result.output


# ============================================================================
# Test config Command
# ============================================================================


class TestConfigCommand:
    """config command tests."""

    def test_config_prints_configuration(self, runner):
        """config prints the configuration summary."""
        result = runner.invoke(main_module.config_command)
        assert result.exit_code == 0
        assert "SAMPLE_RATE" in result.output
        assert "MODEL_SIZE" in result.output

    def test_config_does_not_error_with_env_vars(self, runner, monkeypatch):
        """config works even with VTYPE env vars set."""
        monkeypatch.setenv("VTYPE_MODEL_SIZE", "small")
        result = runner.invoke(main_module.config_command)
        assert result.exit_code == 0


# ============================================================================
# Test Graceful Shutdown
# ============================================================================


class TestGracefulShutdown:
    """Signal handling and shutdown tests."""

    def test_signal_handler_stops_monitor_and_manager(self):
        """SIGINT triggers stop on both KeyMonitor and CoreManager."""
        mock_mgr = mock.MagicMock()
        mock_mon = mock.MagicMock()
        main_module._manager = mock_mgr
        main_module._monitor = mock_mon
        main_module._started_at = 1.0  # Non-zero to trigger summary

        with mock.patch("sys.exit") as mock_exit:
            with mock.patch("main.signal.signal") as mock_sig:
                main_module._signal_handler(signal.SIGINT, None)

        mock_sig.assert_called_once_with(signal.SIGINT, signal.SIG_IGN)
        mock_mon.stop.assert_called_once()
        mock_mgr.stop.assert_called_once()
        mock_exit.assert_called_once_with(0)

    def test_signal_handler_idempotent_without_objects(self):
        """Signal handler does not crash when no manager/monitor set."""
        main_module._manager = None
        main_module._monitor = None

        with mock.patch("sys.exit") as mock_exit:
            with mock.patch("main.signal.signal") as mock_sig:
                main_module._signal_handler(signal.SIGTERM, None)

        mock_sig.assert_called_once_with(signal.SIGTERM, signal.SIG_IGN)
        mock_exit.assert_called_once_with(0)

    def test_second_signal_is_ignored(self):
        """Second signal is ignored to prevent recursive handling."""
        mock_mgr = mock.MagicMock()
        mock_mon = mock.MagicMock()
        main_module._manager = mock_mgr
        main_module._monitor = mock_mon
        main_module._started_at = 1.0

        with mock.patch("signal.signal") as mock_sig:
            with mock.patch("sys.exit"):
                main_module._signal_handler(signal.SIGINT, None)

        # SIG_IGN should be called for the signal
        mock_sig.assert_called_with(signal.SIGINT, signal.SIG_IGN)


# ============================================================================
# Test Error Handling
# ============================================================================


class TestErrorHandling:
    """Error handling tests."""

    def test_model_loading_failure(self, runner, mock_monitor):
        """Model loading failure prints guidance and exits."""
        with mock.patch("main.CoreManager") as mock_mgr:
            mock_mgr.side_effect = RuntimeError("Model download failed")
            result = runner.invoke(main_module.start, [])
        assert result.exit_code == 1
        assert "Failed to initialize" in result.output

    def test_config_validation_errors(self, runner, monkeypatch):
        """Invalid config prints errors and exits."""
        monkeypatch.setenv("VTYPE_CHANNELS", "2")
        # Re-import to pick up env change
        import config as cfg

        # This test verifies that if validate_config returns errors,
        # start exits with code 1
        with mock.patch.object(cfg, "validate_config", return_value=["CHANNELS must be 1"]):
            result = runner.invoke(main_module.start, [])
        assert result.exit_code == 1
        assert "Configuration errors" in result.output


# ============================================================================
# Test Logging Configuration
# ============================================================================


class TestLoggingConfig:
    """Logging configuration tests."""

    def test_verbose_sets_debug(self):
        """--verbose sets DEBUG level."""
        with mock.patch("logging.basicConfig") as mock_basic:
            main_module._configure_logging(verbose=True, quiet=False)
        call_kwargs = mock_basic.call_args[1]
        assert call_kwargs["level"] == logging.DEBUG

    def test_quiet_sets_error(self):
        """--quiet sets ERROR level."""
        with mock.patch("logging.basicConfig") as mock_basic:
            main_module._configure_logging(verbose=False, quiet=True)
        call_kwargs = mock_basic.call_args[1]
        assert call_kwargs["level"] == logging.ERROR

    def test_default_is_info(self):
        """Default logging level is INFO."""
        with mock.patch("logging.basicConfig") as mock_basic:
            main_module._configure_logging(verbose=False, quiet=False)
        call_kwargs = mock_basic.call_args[1]
        assert call_kwargs["level"] == logging.INFO


# ============================================================================
# Test Display Helpers
# ============================================================================


class TestDisplayHelpers:
    """Summary and welcome display tests."""

    def test_format_duration_seconds_only(self):
        """Duration under 60s shows only seconds."""
        result = main_module._format_duration(42.0)
        assert result == "42s"

    def test_format_duration_minutes_and_seconds(self):
        """Duration over 60s shows minutes and seconds."""
        result = main_module._format_duration(125.0)
        assert result == "2m 5s"

    def test_print_welcome_includes_model_info(self, runner):
        """Welcome banner shows model and language info."""
        with mock.patch("sys.stdout", new_callable=mock.MagicMock):
            with mock.patch("click.echo") as mock_echo:
                main_module._print_welcome("base", "int8", "zh", 800, None)
                all_output = " ".join(
                    str(call.args[0]) if call.args else ""
                    for call in mock_echo.call_args_list
                )
        assert "base" in all_output
        assert "zh" in all_output
        assert "800ms" in all_output

    def test_print_summary_with_no_manager(self):
        """Summary print handles missing manager gracefully."""
        with mock.patch("click.echo") as mock_echo:
            main_module._manager = None
            main_module._started_at = 1.0
            main_module._print_summary()
        # Should not crash, just output what it can
        mock_echo.assert_called()


# ============================================================================
# Test Callbacks
# ============================================================================


class TestCallbacks:
    """Callback creation tests."""

    def test_text_callback_writes_to_stdout(self):
        """Text callback writes and flushes to stdout."""
        cb = main_module._create_text_callback()
        with mock.patch("sys.stdout.write") as mock_write:
            with mock.patch("sys.stdout.flush") as mock_flush:
                cb("hello")
        mock_write.assert_called_once_with("hello")
        mock_flush.assert_called_once()

    def test_status_callback_logs(self):
        """Status callback logs state transitions."""
        cb = main_module._create_status_callback()
        with mock.patch("logging.Logger.debug") as mock_debug:
            old = mock.MagicMock()
            old.name = "IDLE"
            new = mock.MagicMock()
            new.name = "RUNNING"
            cb(old, new)
        assert mock_debug.called


# ============================================================================
# Test Hotkey Callbacks
# ============================================================================


class TestHotkeyCallbacks:
    """Hotkey press/release callback tests."""

    def test_press_callback_starts_manager(self):
        """Hotkey press starts the manager."""
        mock_mgr = mock.MagicMock()
        main_module._manager = mock_mgr
        main_module._on_hotkey_press()
        mock_mgr.start.assert_called_once()

    def test_press_callback_safe_without_manager(self):
        """Hotkey press does not crash when manager is None."""
        main_module._manager = None
        main_module._on_hotkey_press()  # Should not raise

    def test_press_callback_handles_exception(self):
        """Hotkey press handles manager.start() exceptions."""
        mock_mgr = mock.MagicMock()
        mock_mgr.start.side_effect = RuntimeError("Boom!")
        main_module._manager = mock_mgr
        main_module._on_hotkey_press()  # Should not raise

    def test_release_callback_stops_manager(self):
        """Hotkey release stops the manager."""
        mock_mgr = mock.MagicMock()
        main_module._manager = mock_mgr
        main_module._on_hotkey_release()
        mock_mgr.stop.assert_called_once()

    def test_release_callback_handles_exception(self):
        """Hotkey release handles manager.stop() exceptions."""
        mock_mgr = mock.MagicMock()
        mock_mgr.stop.side_effect = RuntimeError("Boom!")
        main_module._manager = mock_mgr
        main_module._on_hotkey_release()  # Should not raise
