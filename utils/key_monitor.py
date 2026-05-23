"""
Global Hotkey Monitor — Push-to-talk listener for vType.
===========================================================
Uses pynput.keyboard.Listener to detect press/release of a
user-configurable hotkey (default CapsLock). Press triggers
recording start, release triggers recording stop.

Design Decisions (see docs/specs/feat-key-monitor.md):
- Listener + manual press/release tracking (not GlobalHotKeys),
  because push-to-talk needs continuous hold state awareness.
- _is_recording boolean flag for debounce (OS may send duplicate
  press events on key repeat).
- macOS permission denial is caught and handled gracefully
  (prints guidance, does not crash).

Example:
    def on_press():
        manager.start()

    def on_release():
        manager.stop()

    with KeyMonitor(on_press, on_release) as km:
        km.start()
        # ... app main loop
"""

import logging
import platform
import threading
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Lazy import: pynput is optional (graceful degradation on missing deps)
# Type is Any because the actual types are resolved lazily at runtime by
# _ensure_pynput(). Mypy cannot verify attribute access on union with None.
_pynput_keyboard: Any = None
_pynput_Key: Any = None
_pynput_KeyCode: Any = None


def _ensure_pynput() -> None:
    """Lazy-load pynput.keyboard module.

    Raises:
        ImportError: If pynput is not installed.
    """
    global _pynput_keyboard, _pynput_Key, _pynput_KeyCode
    if _pynput_keyboard is not None:
        return
    try:
        from pynput import keyboard as _pynput_keyboard
        from pynput.keyboard import Key as _pynput_Key
        from pynput.keyboard import KeyCode as _pynput_KeyCode
    except ImportError:
        raise ImportError(
            "pynput is required for KeyMonitor. "
            "Install with: pip install pynput"
        )


# ============================================================================
# State Enum
# ============================================================================


class KeyMonitorState(Enum):
    """KeyMonitor lifecycle states."""

    IDLE = "idle"
    LISTENING = "listening"


# ============================================================================
# Exceptions
# ============================================================================


class KeyMonitorError(Exception):
    """Base exception for KeyMonitor errors."""
    pass


class KeyMonitorPermissionError(KeyMonitorError):
    """Raised when the OS denies global keyboard access (macOS Accessibility)."""
    pass


# ============================================================================
# KeyMonitor
# ============================================================================


class KeyMonitor:
    """Global hotkey listener for push-to-talk voice input.

    Press the hotkey → triggers on_press callback (start recording).
    Release the hotkey → triggers on_release callback (stop recording).

    Lifecycle:
        km = KeyMonitor(on_press, on_release, hotkey)
        km.start()   # Launch background listener thread
        km.stop()    # Stop listener and join thread
        # Or use as context manager:
        with KeyMonitor(on_press, on_release) as km:
            km.start()
            ...

    Attributes:
        state: Current KeyMonitorState.
        is_listening: True if the listener thread is active.
        is_recording: True if the hotkey is currently held down.
    """

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        hotkey=None,
    ) -> None:
        """Initialize the key monitor.

        Args:
            on_press: Callback invoked when hotkey is pressed.
            on_release: Callback invoked when hotkey is released.
            hotkey: The hotkey to listen for. Defaults to CapsLock.
                Can be a pynput Key (Key.caps_lock), KeyCode, or a
                character string (e.g. '<ctrl>+<alt>+v').
        """
        _ensure_pynput()

        self._on_press_cb = on_press
        self._on_release_cb = on_release
        self._hotkey = hotkey if hotkey is not None else _pynput_Key.caps_lock

        # Internal state
        self._state = KeyMonitorState.IDLE
        self._is_recording = False      # Debounce: hotkey held down?
        self._listener: Optional[_pynput_keyboard.Listener] = None
        self._listener_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # For parsing string hotkeys (deferred to start())
        self._hotkey_is_combo = False
        self._combo_keys: set = set()

        # Track which modifier/keys are currently pressed
        # (for combo hotkey support)
        self._pressed_keys: set = set()

        logger.info(
            "KeyMonitor initialized: hotkey=%s",
            self._hotkey,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> KeyMonitorState:
        return self._state

    @property
    def is_listening(self) -> bool:
        return self._state == KeyMonitorState.LISTENING

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the keyboard listener in a background daemon thread.

        Safe to call multiple times (idempotent). If already LISTENING,
        logs a warning and returns without action.
        """
        with self._lock:
            if self._state == KeyMonitorState.LISTENING:
                logger.warning(
                    "KeyMonitor.start() called while already LISTENING"
                )
                return
            self._state = KeyMonitorState.LISTENING

        # Parse combo hotkeys (e.g. '<ctrl>+<alt>+v')
        self._parse_hotkey()

        try:
            self._listener = _pynput_keyboard.Listener(
                on_press=self._on_key_press,
                on_release=self._on_key_release,
            )
        except Exception as exc:
            self._state = KeyMonitorState.IDLE
            self._handle_listener_error(exc)
            return

        # Run listener in a separate daemon thread so it doesn't block
        self._listener_thread = threading.Thread(
            target=self._listener.run,
            name="vType-KeyMonitor",
            daemon=True,
        )
        self._listener_thread.start()

        logger.info("KeyMonitor started (hotkey=%s)", self._hotkey)

    def stop(self) -> None:
        """Stop the keyboard listener and join the background thread.

        Safe to call from any state. Idempotent: duplicate calls
        when already IDLE are no-ops.
        """
        with self._lock:
            if self._state == KeyMonitorState.IDLE:
                return
            self._state = KeyMonitorState.IDLE
            self._is_recording = False

        try:
            if self._listener is not None:
                # Stop the listener (this is thread-safe in pynput)
                self._listener.stop()

            if self._listener_thread is not None:
                self._listener_thread.join(timeout=2.0)
                if self._listener_thread.is_alive():
                    logger.warning("KeyMonitor listener thread did not exit within 2s")
        except Exception:
            logger.exception("Error during KeyMonitor.stop()")

        self._listener = None
        self._listener_thread = None
        logger.info("KeyMonitor stopped")

    # ------------------------------------------------------------------
    # Context Manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "KeyMonitor":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Internal: Hotkey Parsing
    # ------------------------------------------------------------------

    def _parse_hotkey(self) -> None:
        """Parse composite hotkey strings like '<ctrl>+<alt>+v'.

        If the hotkey is a pynput Key or KeyCode object (e.g., Key.caps_lock),
        no parsing is needed — it's a single-key hotkey.

        If the hotkey is a string containing '<' and '>', it's treated as
        a pynput-style composite hotkey. The keys are split by '+' and
        parsed into a set of Key/KeyCode objects for matching.
        """
        # Single key hotkey (Key/KeyCode object) — nothing to parse
        if not isinstance(self._hotkey, str):
            self._hotkey_is_combo = False
            return

        # Simple character hotkey (e.g. 'v', 'F1')
        if '<' not in self._hotkey and '>' not in self._hotkey:
            self._hotkey_is_combo = False
            return

        # Composite hotkey: '<ctrl>+<alt>+v'
        self._hotkey_is_combo = True
        self._combo_keys = set()

        parts = self._hotkey.split("+")
        for part in parts:
            part = part.strip()

            # Modifier key: <ctrl>, <alt>, <shift>, <cmd>
            if part.startswith("<") and part.endswith(">"):
                key_name = part[1:-1]  # Strip <> brackets
                key_obj = self._name_to_key(key_name)
                if key_obj is not None:
                    self._combo_keys.add(key_obj)
                else:
                    logger.warning("Unknown combo key: %s", part)
            else:
                # Regular character: 'v', '1', etc.
                if len(part) == 1:
                    self._combo_keys.add(_pynput_KeyCode.from_char(part))
                else:
                    # Might be a named key like 'f1', 'enter'
                    key_obj = self._name_to_key(part)
                    if key_obj is not None:
                        self._combo_keys.add(key_obj)
                    else:
                        logger.warning("Unknown combo key: %s", part)

        if not self._combo_keys:
            logger.warning(
                "Failed to parse any keys from hotkey string: %s",
                self._hotkey,
            )
            self._hotkey_is_combo = False

    @staticmethod
    def _name_to_key(name: str):
        """Convert a key name string to a pynput Key object.

        Args:
            name: Key name like 'ctrl', 'alt', 'shift', 'cmd',
                'caps_lock', 'f1', 'enter', etc.

        Returns:
            pynput Key object, or None if the name is not recognized.
        """
        _ensure_pynput()

        # Map common names to pynput Key attributes
        key_map = {
            "ctrl": _pynput_Key.ctrl,
            "ctrl_l": _pynput_Key.ctrl_l,
            "ctrl_r": _pynput_Key.ctrl_r,
            "alt": _pynput_Key.alt,
            "alt_l": _pynput_Key.alt_l,
            "alt_r": _pynput_Key.alt_r,
            "shift": _pynput_Key.shift,
            "shift_l": _pynput_Key.shift_l,
            "shift_r": _pynput_Key.shift_r,
            "cmd": _pynput_Key.cmd,
            "cmd_l": _pynput_Key.cmd_l,
            "cmd_r": _pynput_Key.cmd_r,
            "caps_lock": _pynput_Key.caps_lock,
            "capslock": _pynput_Key.caps_lock,
            "tab": _pynput_Key.tab,
            "enter": _pynput_Key.enter,
            "esc": _pynput_Key.esc,
            "escape": _pynput_Key.esc,
            "space": _pynput_Key.space,
            "backspace": _pynput_Key.backspace,
            "delete": _pynput_Key.delete,
            "up": _pynput_Key.up,
            "down": _pynput_Key.down,
            "left": _pynput_Key.left,
            "right": _pynput_Key.right,
            "home": _pynput_Key.home,
            "end": _pynput_Key.end,
            "page_up": _pynput_Key.page_up,
            "page_down": _pynput_Key.page_down,
            "insert": _pynput_Key.insert,
            "f1": _pynput_Key.f1,
            "f2": _pynput_Key.f2,
            "f3": _pynput_Key.f3,
            "f4": _pynput_Key.f4,
            "f5": _pynput_Key.f5,
            "f6": _pynput_Key.f6,
            "f7": _pynput_Key.f7,
            "f8": _pynput_Key.f8,
            "f9": _pynput_Key.f9,
            "f10": _pynput_Key.f10,
            "f11": _pynput_Key.f11,
            "f12": _pynput_Key.f12,
        }

        return key_map.get(name.lower())

    # ------------------------------------------------------------------
    # Internal: Keyboard Event Handlers
    # ------------------------------------------------------------------

    def _on_key_press(self, key) -> None:
        """Called by pynput Listener when any key is pressed.

        Checks if the pressed key matches our hotkey. If so, and
        we are not already recording, triggers the on_press callback.
        """
        # Track pressed keys for combo matching
        self._pressed_keys.add(self._normalize_key(key))

        if self._hotkey_is_combo:
            # Check if all combo keys are now pressed
            if self._combo_keys.issubset(self._pressed_keys):
                self._trigger_press()
        elif self._is_hotkey(key):
            self._trigger_press()

    def _on_key_release(self, key) -> None:
        """Called by pynput Listener when any key is released.

        Checks if the released key matches our hotkey. If so, and
        we are currently recording, triggers the on_release callback.
        """
        self._pressed_keys.discard(self._normalize_key(key))

        if self._hotkey_is_combo:
            # For combo hotkeys, release triggers when ANY combo key is
            # released (the combo is broken)
            if self._is_recording and not self._combo_keys.issubset(
                self._pressed_keys
            ):
                self._trigger_release()
        elif self._is_hotkey(key):
            self._trigger_release()

    def _is_hotkey(self, key) -> bool:
        """Check if the given key matches our configured hotkey.

        For simple (non-combo) hotkeys, this does a direct comparison
        with the configured hotkey Key/KeyCode object.
        """
        # Compare by value (Key objects support == by identity)
        # But we normalize to handle KeyCode.from_char('v') vs KeyCode(char='v')
        normalized = self._normalize_key(key)
        hotkey_normalized = self._normalize_key(self._hotkey)
        return normalized == hotkey_normalized

    @staticmethod
    def _normalize_key(key):
        """Normalize a key object for reliable comparison.

        pynput KeyCodes created by from_char('v') vs from_dead('v') have
        different internal representations but should match.

        Uses hasattr checks instead of isinstance to be compatible with
        mocked pynput during testing (MagicMock fails isinstance).
        """
        if key is None:
            return None

        # If it looks like a KeyCode, normalize to char or name
        if hasattr(key, "char") and key.char is not None:
            return key.char
        if hasattr(key, "name") and key.name is not None:
            return key.name

        # Otherwise return as-is (Key enum values, strings, etc.)
        return key

    def _trigger_press(self) -> None:
        """Trigger the on_press callback with debounce protection."""
        if self._is_recording:
            return  # Already recording (debounce)

        self._is_recording = True
        logger.debug("Hotkey pressed → triggering on_press callback")
        try:
            self._on_press_cb()
        except Exception:
            logger.exception("Error in on_press callback")

    def _trigger_release(self) -> None:
        """Trigger the on_release callback with debounce protection."""
        if not self._is_recording:
            return  # Not recording (already released or debounce)

        self._is_recording = False
        logger.debug("Hotkey released → triggering on_release callback")
        try:
            self._on_release_cb()
        except Exception:
            logger.exception("Error in on_release callback")

    # ------------------------------------------------------------------
    # Internal: Error Handling
    # ------------------------------------------------------------------

    def _handle_listener_error(self, exc: Exception) -> None:
        """Handle errors during Listener creation.

        On macOS, pynput may fail due to missing Accessibility permissions.
        We detect this case and provide clear guidance.
        """
        error_msg = str(exc).lower()

        if platform.system() == "Darwin" and (
            "permission" in error_msg
            or "accessibility" in error_msg
            or "not permitted" in error_msg
            or "trusted" in error_msg
        ):
            logger.warning(
                "KeyMonitor: macOS Accessibility permission not granted.\n"
                "\n"
                "  Authorisation steps:\n"
                "  1. Open System Settings → Privacy & Security "
                "→ Accessibility\n"
                "  2. Click + and add your terminal app "
                "(Terminal.app / iTerm.app)\n"
                "  3. Make sure the toggle is ON\n"
                "  4. Restart vType\n"
                "\n"
                "  Running in hotkey-disabled mode. Use Ctrl+C to control."
            )
            # Don't raise — allow degraded operation
        else:
            logger.error(
                "Failed to create keyboard listener: %s", exc
            )
