"""Unit tests for core/typer.py — Keyboard Output Engine.

Covers:
- type_text() with pynput primary path
- type_text() empty / None / whitespace skipping
- type_text() pynput → clipboard fallback
- type_text() fallback disabled → TypeWriterPermissionError
- type_text() clipboard fallback with empty original
- _type_via_pynput() char-by-char delay
- run() consumer loop (normal, queue.Empty, stop_event, exceptions)
"""

import queue
import threading
from unittest import mock

import pytest

from core.typer import TypeWriter, TypeWriterError, TypeWriterPermissionError


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_keyboard_ctrl():
    """Mock pynput.keyboard.Controller."""
    return mock.MagicMock()


@pytest.fixture
def mock_clipboard_mgr():
    """Mock utils.clipboard.ClipboardManager."""
    mgr = mock.MagicMock()
    mgr.get_text.return_value = ""
    return mgr


@pytest.fixture
def typewriter(mock_keyboard_ctrl, mock_clipboard_mgr):
    """Create TypeWriter with mocked pynput and ClipboardManager."""
    with mock.patch.object(
        TypeWriter, "_create_keyboard_controller", return_value=mock_keyboard_ctrl
    ), mock.patch(
        "core.typer.ClipboardManager", return_value=mock_clipboard_mgr
    ):
        tw = TypeWriter()
        return tw


# ============================================================================
# Test: type_text() — pynput primary path
# ============================================================================


class TestTypeTextPynput:
    """type_text() primary pynput path tests."""

    def test_type_text_normal(self, typewriter, mock_keyboard_ctrl):
        """type_text() should type each character via pynput Controller."""
        typewriter.type_text("hello")

        # Should have typed 5 chars
        assert mock_keyboard_ctrl.type.call_count == 5
        chars_typed = [c.args[0] for c in mock_keyboard_ctrl.type.call_args_list]
        assert chars_typed == ["h", "e", "l", "l", "o"]

    def test_type_text_chinese(self, typewriter, mock_keyboard_ctrl):
        """type_text() should handle Chinese characters."""
        typewriter.type_text("你好")

        assert mock_keyboard_ctrl.type.call_count == 2
        chars_typed = [c.args[0] for c in mock_keyboard_ctrl.type.call_args_list]
        assert chars_typed == ["你", "好"]

    def test_type_text_with_punctuation(self, typewriter, mock_keyboard_ctrl):
        """type_text() should handle mixed text with punctuation."""
        typewriter.type_text("Hello, 世界!")

        # "Hello, 世界!" = 10 characters (H-e-l-l-o-,-space-世-界-!)
        assert mock_keyboard_ctrl.type.call_count == 10


# ============================================================================
# Test: type_text() — empty / None / whitespace
# ============================================================================


class TestTypeTextEmpty:
    """type_text() edge cases for empty input."""

    def test_type_text_none(self, typewriter, mock_keyboard_ctrl):
        """type_text(None) should skip without calling keyboard."""
        typewriter.type_text(None)
        mock_keyboard_ctrl.type.assert_not_called()

    def test_type_text_empty_string(self, typewriter, mock_keyboard_ctrl):
        """type_text('') should skip."""
        typewriter.type_text("")
        mock_keyboard_ctrl.type.assert_not_called()

    def test_type_text_whitespace_only(self, typewriter, mock_keyboard_ctrl):
        """type_text('   ') should skip."""
        typewriter.type_text("   ")
        mock_keyboard_ctrl.type.assert_not_called()

    def test_type_text_newline_only(self, typewriter, mock_keyboard_ctrl):
        """type_text with only whitespace chars should skip."""
        typewriter.type_text("\n\t  ")
        mock_keyboard_ctrl.type.assert_not_called()


# ============================================================================
# Test: type_text() — clipboard fallback
# ============================================================================


class TestTypeTextFallback:
    """type_text() clipboard fallback path tests."""

    def test_fallback_on_permission_error(
        self, typewriter, mock_keyboard_ctrl, mock_clipboard_mgr
    ):
        """type_text() should fall back to clipboard on PermissionError."""
        mock_keyboard_ctrl.type.side_effect = PermissionError("access denied")

        typewriter.type_text("fallback text")

        # Verify clipboard save → copy → paste → restore sequence
        mock_clipboard_mgr.get_text.assert_called_once()
        mock_clipboard_mgr.copy.assert_any_call("fallback text")
        mock_clipboard_mgr.simulate_paste.assert_called_once()

    def test_fallback_on_os_error(
        self, typewriter, mock_keyboard_ctrl, mock_clipboard_mgr
    ):
        """type_text() should fall back to clipboard on OSError (macOS CGEvent)."""
        mock_keyboard_ctrl.type.side_effect = OSError("CGEventPost failed")

        typewriter.type_text("macos text")

        mock_clipboard_mgr.copy.assert_any_call("macos text")
        mock_clipboard_mgr.simulate_paste.assert_called_once()

    def test_fallback_restores_original(
        self, typewriter, mock_keyboard_ctrl, mock_clipboard_mgr
    ):
        """Clipboard fallback should restore original clipboard content."""
        mock_keyboard_ctrl.type.side_effect = PermissionError("denied")
        mock_clipboard_mgr.get_text.return_value = "original_content"

        typewriter.type_text("new text")

        # Verify restore: copy(original) called after paste
        mock_clipboard_mgr.copy.assert_any_call("original_content")

    def test_fallback_empty_original_skips_restore(
        self, typewriter, mock_keyboard_ctrl, mock_clipboard_mgr
    ):
        """Clipboard fallback should skip restore when original was empty."""
        mock_keyboard_ctrl.type.side_effect = PermissionError("denied")
        mock_clipboard_mgr.get_text.return_value = ""

        typewriter.type_text("new text")

        # copy should only be called once (for the new text), not twice
        mock_clipboard_mgr.copy.assert_called_once_with("new text")

    def test_fallback_disabled_raises_permission_error(
        self, mock_keyboard_ctrl
    ):
        """type_text() should raise TypeWriterPermissionError when fallback disabled."""
        mock_keyboard_ctrl.type.side_effect = PermissionError("denied")

        with mock.patch.object(
            TypeWriter, "_create_keyboard_controller", return_value=mock_keyboard_ctrl
        ):
            tw = TypeWriter(clipboard_fallback=False)
            with pytest.raises(TypeWriterPermissionError, match="CLIPBOARD_FALLBACK"):
                tw.type_text("text")


# ============================================================================
# Test: _type_via_pynput() delay
# ============================================================================


class TestPynputDelay:
    """_type_via_pynput() character delay tests."""

    def test_type_delay_between_chars(self, typewriter, mock_keyboard_ctrl):
        """_type_via_pynput should sleep between characters."""
        with mock.patch("time.sleep") as mock_sleep:
            typewriter._type_via_pynput("abc")

        # Should sleep after each character (3 chars = 3 sleeps)
        assert mock_sleep.call_count == 3
        mock_sleep.assert_called_with(0.005)


# ============================================================================
# Test: run() consumer loop
# ============================================================================


class TestRunLoop:
    """run() consumer main loop tests."""

    def test_run_processes_text(self, typewriter):
        """run() should consume from result_queue and call type_text()."""
        q = queue.Queue()
        stop = threading.Event()

        with mock.patch.object(typewriter, "type_text") as mock_type:
            # Put a text item, then stop
            q.put("hello world")

            def stop_after_delay():
                import time
                time.sleep(0.05)
                stop.set()

            t = threading.Thread(target=stop_after_delay, daemon=True)
            t.start()
            typewriter.run(q, stop)
            t.join(timeout=1.0)

        mock_type.assert_called_once_with("hello world")

    def test_run_handles_queue_empty(self, typewriter):
        """run() should continue on queue.Empty without exiting."""
        q = queue.Queue()
        stop = threading.Event()

        # Start run in a thread, let it loop a bit, then stop
        def _run():
            typewriter.run(q, stop)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        # Let it encounter a few queue.Empty iterations
        import time
        time.sleep(0.3)
        stop.set()
        t.join(timeout=1.0)

        # Should not crash
        assert not t.is_alive()

    def test_run_stop_event_exits(self, typewriter):
        """run() should exit when stop_event is set."""
        q = queue.Queue()
        stop = threading.Event()
        stop.set()  # Immediately set before calling run

        typewriter.run(q, stop)
        # Should return immediately without error

    def test_run_handles_typewriter_error(self, typewriter, mock_keyboard_ctrl):
        """run() should log and continue on TypeWriterError."""
        q = queue.Queue()
        stop = threading.Event()
        mock_keyboard_ctrl.type.side_effect = PermissionError("denied")

        with mock.patch.object(typewriter, "type_text") as mock_type:
            mock_type.side_effect = TypeWriterError("simulated error")

            q.put("text")
            q.put("text2")

            def stop_after():
                import time
                time.sleep(0.1)
                stop.set()

            t = threading.Thread(target=stop_after, daemon=True)
            t.start()
            typewriter.run(q, stop)
            t.join(timeout=1.0)

        # type_text should have been called despite error on first item
        assert mock_type.call_count >= 1

    def test_run_skips_empty_text(self, typewriter):
        """run() should skip empty/whitespace items from queue."""
        q = queue.Queue()
        stop = threading.Event()

        with mock.patch.object(typewriter, "type_text") as mock_type:
            q.put("")  # empty
            q.put("   ")  # whitespace only

            def stop_after():
                import time
                time.sleep(0.05)
                stop.set()

            t = threading.Thread(target=stop_after, daemon=True)
            t.start()
            typewriter.run(q, stop)
            t.join(timeout=1.0)

        # type_text should not be called for empty items
        mock_type.assert_not_called()


# ============================================================================
# Test: Initialization
# ============================================================================


class TestInit:
    """TypeWriter initialization tests."""

    def test_init_defaults(self, mock_keyboard_ctrl):
        """TypeWriter should initialize with default config values."""
        with mock.patch.object(
            TypeWriter, "_create_keyboard_controller", return_value=mock_keyboard_ctrl
        ), mock.patch("core.typer.ClipboardManager") as _mock_cm:
            tw = TypeWriter()
            assert tw._type_delay == 0.005
            assert tw._clipboard_fallback is True
            assert tw._clipboard is not None

    def test_init_clipboard_fallback_disabled(self, mock_keyboard_ctrl):
        """TypeWriter should not init ClipboardManager when fallback disabled."""
        with mock.patch.object(
            TypeWriter, "_create_keyboard_controller", return_value=mock_keyboard_ctrl
        ), mock.patch("core.typer.ClipboardManager") as mock_cm:
            tw = TypeWriter(clipboard_fallback=False)
            assert tw._clipboard_fallback is False
            assert tw._clipboard is None
            mock_cm.assert_not_called()
