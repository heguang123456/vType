"""Unit tests for utils/key_monitor.py — Global Hotkey Monitor.

Covers:
- KeyMonitorState enum values
- KeyMonitor construction with callbacks and hotkey
- Lifecycle (start/stop, context manager, idempotency)
- Hotkey press/release event handling with debounce
- Combo hotkey parsing and matching
- macOS permission error handling
- Thread safety and background threading
"""

from unittest import mock

import pytest

from utils.key_monitor import (
    KeyMonitor,
    KeyMonitorState,
)


# ============================================================================
# Mock pynput setup (same pattern as test_typer.py)
# ============================================================================


@pytest.fixture(autouse=True)
def mock_pynput():
    """Inject mock pynput modules so tests run without pynput installed."""
    mock_keyboard = mock.MagicMock()
    mock_key = mock.MagicMock()
    mock_keycode = mock.MagicMock()

    # Configure Key constants
    mock_key.caps_lock = "Key.caps_lock"
    mock_key.ctrl = "Key.ctrl"
    mock_key.ctrl_l = "Key.ctrl_l"
    mock_key.alt = "Key.alt"
    mock_key.shift = "Key.shift"
    mock_key.cmd = "Key.cmd"
    mock_key.enter = "Key.enter"
    mock_key.esc = "Key.esc"
    mock_key.space = "Key.space"
    mock_key.tab = "Key.tab"
    mock_key.f1 = "Key.f1"
    mock_key.f2 = "Key.f2"
    mock_key.f3 = "Key.f3"

    # KeyCode.from_char should return a consistent value
    mock_keycode.from_char = lambda c: f"KeyCode.char.{c}"

    # Listener mock
    mock_listener_class = mock.MagicMock()
    mock_keyboard.Listener = mock_listener_class

    with mock.patch.dict("sys.modules", {
        "pynput": mock.MagicMock(),
        "pynput.keyboard": mock_keyboard,
    }):
        # Also patch the module-level globals in key_monitor
        with mock.patch("utils.key_monitor._pynput_keyboard", mock_keyboard):
            with mock.patch("utils.key_monitor._pynput_Key", mock_key):
                with mock.patch("utils.key_monitor._pynput_KeyCode", mock_keycode):
                    yield {
                        "keyboard": mock_keyboard,
                        "Key": mock_key,
                        "KeyCode": mock_keycode,
                    }


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def callbacks():
    """Create a pair of mock callbacks for on_press/on_release."""
    return mock.MagicMock(), mock.MagicMock()


@pytest.fixture
def monitor(callbacks):
    """Create a fresh KeyMonitor for each test."""
    on_press, on_release = callbacks
    return KeyMonitor(on_press, on_release)


# ============================================================================
# Test KeyMonitorState Enum
# ============================================================================


class TestKeyMonitorState:
    """KeyMonitorState enum tests."""

    def test_idle_value(self):
        assert KeyMonitorState.IDLE.value == "idle"

    def test_listening_value(self):
        assert KeyMonitorState.LISTENING.value == "listening"

    def test_enum_str(self):
        assert str(KeyMonitorState.IDLE) == "KeyMonitorState.IDLE"


# ============================================================================
# Test KeyMonitor Construction
# ============================================================================


class TestKeyMonitorInit:
    """KeyMonitor __init__ tests."""

    def test_default_constructor(self, callbacks):
        """Default constructor uses CapsLock as hotkey."""
        on_press, on_release = callbacks
        km = KeyMonitor(on_press, on_release)
        assert km.state == KeyMonitorState.IDLE
        assert km.is_listening is False
        assert km.is_recording is False
        assert km._hotkey == "Key.caps_lock"

    def test_custom_hotkey(self, callbacks):
        """Custom hotkey is stored."""
        on_press, on_release = callbacks
        km = KeyMonitor(on_press, on_release, hotkey="Key.ctrl")
        assert km._hotkey == "Key.ctrl"

    def test_callbacks_stored(self, callbacks):
        """Callbacks are stored correctly."""
        on_press, on_release = callbacks
        km = KeyMonitor(on_press, on_release)
        assert km._on_press_cb is on_press
        assert km._on_release_cb is on_release


# ============================================================================
# Test KeyMonitor Lifecycle
# ============================================================================


class TestKeyMonitorLifecycle:
    """KeyMonitor start/stop lifecycle tests."""

    def test_start_creates_listener(self, monitor, mock_pynput):
        """start() creates a pynput Listener and starts a thread."""
        monitor.start()
        mock_pynput["keyboard"].Listener.assert_called_once()
        assert monitor.state == KeyMonitorState.LISTENING
        assert monitor.is_listening is True

    def test_start_idempotent(self, monitor, mock_pynput):
        """Calling start() twice does not create a second listener."""
        monitor.start()
        call_count = mock_pynput["keyboard"].Listener.call_count
        monitor.start()  # Second call
        # No additional listener created
        assert mock_pynput["keyboard"].Listener.call_count == call_count
        assert monitor.state == KeyMonitorState.LISTENING

    def test_stop_stops_listener(self, monitor, mock_pynput):
        """stop() calls listener.stop() and resets state."""
        monitor.start()
        # Get the mock listener instance
        listener_instance = mock_pynput["keyboard"].Listener.return_value

        monitor.stop()
        listener_instance.stop.assert_called_once()
        assert monitor.state == KeyMonitorState.IDLE
        assert monitor.is_listening is False

    def test_stop_idempotent(self, monitor):
        """Calling stop() twice is safe."""
        monitor.stop()
        monitor.stop()
        assert monitor.state == KeyMonitorState.IDLE

    def test_context_manager(self, monitor, mock_pynput):
        """KeyMonitor works as a context manager."""
        with monitor as km:
            km.start()
            assert km is monitor
            assert km.state == KeyMonitorState.LISTENING
        # After context exit, listener is stopped
        assert monitor.state == KeyMonitorState.IDLE


# ============================================================================
# Test Hotkey Press/Release Events
# ============================================================================


class TestKeyMonitorHotkeyEvents:
    """Hotkey press/release event handling with debounce."""

    def test_press_triggers_callback(self, monitor, callbacks, mock_pynput):
        """Pressing the hotkey calls on_press callback exactly once."""
        on_press, on_release = callbacks
        monitor.start()

        # Simulate pressing CapsLock
        _ = mock_pynput["keyboard"].Listener.return_value
        # Get the on_press handler
        press_handler = mock_pynput["keyboard"].Listener.call_args[1]["on_press"]

        press_handler("Key.caps_lock")
        on_press.assert_called_once()
        on_release.assert_not_called()

    def test_release_triggers_callback(self, monitor, callbacks, mock_pynput):
        """Releasing the hotkey after press calls on_release."""
        on_press, on_release = callbacks
        monitor.start()

        press_handler = mock_pynput["keyboard"].Listener.call_args[1]["on_press"]
        release_handler = mock_pynput["keyboard"].Listener.call_args[1]["on_release"]

        press_handler("Key.caps_lock")
        on_press.assert_called_once()

        release_handler("Key.caps_lock")
        on_release.assert_called_once()

    def test_debounce_duplicate_press(self, monitor, callbacks, mock_pynput):
        """Duplicate press events are debounced (only first triggers)."""
        on_press, on_release = callbacks
        monitor.start()

        press_handler = mock_pynput["keyboard"].Listener.call_args[1]["on_press"]

        press_handler("Key.caps_lock")
        press_handler("Key.caps_lock")  # Duplicate
        press_handler("Key.caps_lock")  # Duplicate

        # Only called once
        on_press.assert_called_once()

    def test_debounce_release_without_press(self, monitor, callbacks, mock_pynput):
        """Release without prior press does not trigger callback."""
        on_press, on_release = callbacks
        monitor.start()

        release_handler = mock_pynput["keyboard"].Listener.call_args[1]["on_release"]

        release_handler("Key.caps_lock")
        on_release.assert_not_called()

    def test_other_keys_ignored(self, monitor, callbacks, mock_pynput):
        """Non-hotkey presses are ignored."""
        on_press, on_release = callbacks
        monitor.start()

        press_handler = mock_pynput["keyboard"].Listener.call_args[1]["on_press"]
        release_handler = mock_pynput["keyboard"].Listener.call_args[1]["on_release"]

        press_handler("Key.enter")
        press_handler("Key.esc")
        press_handler("KeyCode.char.a")

        on_press.assert_not_called()

        release_handler("Key.enter")
        on_release.assert_not_called()

    def test_callback_exception_handled(self, monitor, callbacks, mock_pynput):
        """Exception in callback does not crash the listener."""
        on_press, on_release = callbacks
        on_press.side_effect = RuntimeError("Boom!")

        monitor.start()
        press_handler = mock_pynput["keyboard"].Listener.call_args[1]["on_press"]

        # Should not raise
        press_handler("Key.caps_lock")
        # State is still recording (exception doesn't reset it)
        assert monitor.is_recording is True

    def test_full_cycle_press_release(self, monitor, callbacks, mock_pynput):
        """Full press → release cycle transitions correctly."""
        on_press, on_release = callbacks
        monitor.start()

        press_handler = mock_pynput["keyboard"].Listener.call_args[1]["on_press"]
        release_handler = mock_pynput["keyboard"].Listener.call_args[1]["on_release"]

        assert monitor.is_recording is False

        press_handler("Key.caps_lock")
        assert monitor.is_recording is True
        on_press.assert_called_once()

        release_handler("Key.caps_lock")
        assert monitor.is_recording is False
        on_release.assert_called_once()


# ============================================================================
# Test Combo Hotkey
# ============================================================================


class TestComboHotkey:
    """Composite hotkey (<ctrl>+v, etc.) tests."""

    def test_combo_hotkey_parsing(self, callbacks, mock_pynput):
        """Combo hotkey string is parsed into combo key set."""
        on_press, on_release = callbacks
        km = KeyMonitor(on_press, on_release, hotkey="<ctrl>+v")
        km.start()  # _parse_hotkey() is called inside start()
        assert km._hotkey_is_combo is True
        assert len(km._combo_keys) == 2

    def test_combo_press_triggers_when_all_keys_down(self, callbacks, mock_pynput):
        """Combo hotkey fires only when all keys are simultaneously pressed."""
        on_press, on_release = callbacks
        km = KeyMonitor(on_press, on_release, hotkey="<ctrl>+v")
        km.start()

        press_handler = mock_pynput["keyboard"].Listener.call_args[1]["on_press"]

        # Press just ctrl → no trigger
        press_handler("Key.ctrl")
        on_press.assert_not_called()

        # Press 'v' → now combo is complete → trigger
        press_handler("KeyCode.char.v")
        on_press.assert_called_once()

    def test_combo_release_triggers_when_broken(self, callbacks, mock_pynput):
        """Releasing any combo key triggers on_release."""
        on_press, on_release = callbacks
        km = KeyMonitor(on_press, on_release, hotkey="<ctrl>+v")
        km.start()

        press_handler = mock_pynput["keyboard"].Listener.call_args[1]["on_press"]
        release_handler = mock_pynput["keyboard"].Listener.call_args[1]["on_release"]

        # Press both keys
        press_handler("Key.ctrl")
        press_handler("KeyCode.char.v")
        on_press.assert_called_once()

        # Release ctrl → combo broken → release triggers
        release_handler("Key.ctrl")
        on_release.assert_called_once()

    def test_combo_debounce(self, callbacks, mock_pynput):
        """Combo debounce: releasing while still pressed does not re-trigger."""
        on_press, on_release = callbacks
        km = KeyMonitor(on_press, on_release, hotkey="<ctrl>+v")
        km.start()

        press_handler = mock_pynput["keyboard"].Listener.call_args[1]["on_press"]
        release_handler = mock_pynput["keyboard"].Listener.call_args[1]["on_release"]

        # Full cycle 1
        press_handler("Key.ctrl")
        press_handler("KeyCode.char.v")
        release_handler("Key.ctrl")
        on_press.assert_called_once()
        on_release.assert_called_once()

        # Second release (of 'v') should be ignored
        on_release.reset_mock()
        release_handler("KeyCode.char.v")
        on_release.assert_not_called()


# ============================================================================
# Test Permissions & Error Handling
# ============================================================================


class TestKeyMonitorPermissions:
    """macOS permission error handling."""

    def test_unknown_key_warning(self, callbacks, mock_pynput):
        """Unknown key in combo string logs a warning but doesn't crash."""
        on_press, on_release = callbacks
        km = KeyMonitor(on_press, on_release, hotkey="<ctrl>+<bogus>")
        km.start()
        # Should not crash, just log warning
        assert km.is_listening is True

    def test_empty_combo_no_crash(self, callbacks, mock_pynput):
        """Completely unparseable hotkey string falls back gracefully."""
        on_press, on_release = callbacks
        km = KeyMonitor(on_press, on_release, hotkey="<><>")
        km.start()
        assert km._hotkey_is_combo is False
        assert km.is_listening is True

    @mock.patch("utils.key_monitor.platform")
    def test_macos_permission_error_handled(self, mock_platform, callbacks, mock_pynput):
        """macOS permission error does not raise, prints guidance."""
        mock_platform.system.return_value = "Darwin"

        # Make Listener constructor raise a permission error
        mock_pynput["keyboard"].Listener.side_effect = RuntimeError(
            "This process is not trusted! Input event monitoring "
            "will not be possible until it is added to "
            "accessibility clients."
        )

        on_press, on_release = callbacks
        km = KeyMonitor(on_press, on_release)
        km.start()

        # Should not raise, should be back in IDLE
        assert km.state == KeyMonitorState.IDLE


# ============================================================================
# Test Threading
# ============================================================================


class TestKeyMonitorThreading:
    """Thread safety and background threading tests."""

    def test_start_creates_daemon_thread(self, monitor, mock_pynput):
        """Listener runs in a daemon thread."""
        with mock.patch("utils.key_monitor.threading.Thread") as mock_thread:
            monitor.start()

            # The listener thread should be daemon=True
            call_kwargs = mock_thread.call_args[1]
            assert call_kwargs["daemon"] is True
            assert call_kwargs["name"] == "vType-KeyMonitor"

    def test_stop_joins_thread(self, monitor, mock_pynput):
        """stop() joins the listener thread."""
        mock_thread = mock.MagicMock()
        mock_thread.is_alive.return_value = False

        monitor.start()
        monitor._listener_thread = mock_thread
        monitor.stop()

        mock_thread.join.assert_called_once()

    def test_multiple_start_stop_cycles(self, monitor, mock_pynput):
        """Multiple start/stop cycles are safe."""
        for _ in range(3):
            monitor.start()
            assert monitor.is_listening is True
            monitor.stop()
            assert monitor.is_listening is False

    def test_stop_resets_recording_state(self, monitor, mock_pynput):
        """stop() resets _is_recording to False."""
        monitor.start()

        press_handler = mock_pynput["keyboard"].Listener.call_args[1]["on_press"]
        press_handler("Key.caps_lock")
        assert monitor.is_recording is True

        monitor.stop()
        assert monitor.is_recording is False
        assert monitor.state == KeyMonitorState.IDLE
