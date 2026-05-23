"""Unit tests for utils/clipboard.py — Cross-platform Clipboard Operations.

Covers:
- pyperclip import handling
- copy() / get_text() / has_text()
- simulate_paste() across Windows, macOS, Linux
- Edge cases: empty clipboard, non-text content, pyperclip unavailable
"""

from unittest import mock

import pytest

from utils.clipboard import ClipboardError, ClipboardManager


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_pyperclip():
    """Mock pyperclip module with copy/paste."""
    mock_pc = mock.MagicMock()
    mock_pc.paste.return_value = ""
    with mock.patch.dict("sys.modules", {"pyperclip": mock_pc}):
        yield mock_pc


@pytest.fixture
def clipboard(mock_pyperclip):
    """Create ClipboardManager with mocked pyperclip."""
    return ClipboardManager()


# ============================================================================
# Test: pyperclip import
# ============================================================================


class TestPyperclipImport:
    """pyperclip availability checks."""

    def test_init_success(self, mock_pyperclip):
        """ClipboardManager should initialize when pyperclip is available."""
        mgr = ClipboardManager()
        assert mgr is not None

    def test_init_import_error(self):
        """ClipboardManager raises ClipboardError when pyperclip is not installed."""
        with mock.patch.dict("sys.modules", {"pyperclip": None}):
            with pytest.raises(ClipboardError, match="pyperclip is not installed"):
                ClipboardManager()


# ============================================================================
# Test: copy()
# ============================================================================


class TestCopy:
    """copy() method tests."""

    def test_copy_text(self, clipboard, mock_pyperclip):
        """copy() should call pyperclip.copy() with the correct text."""
        clipboard.copy("hello world")
        mock_pyperclip.copy.assert_called_once_with("hello world")

    def test_copy_empty_string(self, clipboard, mock_pyperclip):
        """copy() should handle empty string."""
        clipboard.copy("")
        mock_pyperclip.copy.assert_called_once_with("")

    def test_copy_chinese(self, clipboard, mock_pyperclip):
        """copy() should handle Chinese text."""
        clipboard.copy("你好世界")
        mock_pyperclip.copy.assert_called_once_with("你好世界")


# ============================================================================
# Test: get_text()
# ============================================================================


class TestGetText:
    """get_text() method tests."""

    def test_get_text_normal(self, clipboard, mock_pyperclip):
        """get_text() should return pyperclip.paste() result."""
        mock_pyperclip.paste.return_value = "clipboard content"
        assert clipboard.get_text() == "clipboard content"

    def test_get_text_empty(self, clipboard, mock_pyperclip):
        """get_text() should return '' when clipboard is empty."""
        mock_pyperclip.paste.return_value = ""
        assert clipboard.get_text() == ""

    def test_get_text_non_string(self, clipboard, mock_pyperclip):
        """get_text() should return '' when clipboard contains non-string data."""
        mock_pyperclip.paste.return_value = b"bytes"
        assert clipboard.get_text() == ""

    def test_get_text_exception(self, clipboard, mock_pyperclip):
        """get_text() raises ClipboardError when pyperclip.paste() fails."""
        mock_pyperclip.paste.side_effect = RuntimeError("backend crash")
        with pytest.raises(ClipboardError, match="Failed to read clipboard"):
            clipboard.get_text()


# ============================================================================
# Test: has_text()
# ============================================================================


class TestHasText:
    """has_text() method tests."""

    def test_has_text_true(self, clipboard, mock_pyperclip):
        """has_text() returns True when clipboard has text."""
        mock_pyperclip.paste.return_value = "some text"
        assert clipboard.has_text() is True

    def test_has_text_false_empty(self, clipboard, mock_pyperclip):
        """has_text() returns False when clipboard is empty."""
        mock_pyperclip.paste.return_value = ""
        assert clipboard.has_text() is False

    def test_has_text_false_error(self, clipboard, mock_pyperclip):
        """has_text() returns False when get_text() raises ClipboardError."""
        mock_pyperclip.paste.side_effect = RuntimeError("fail")
        assert clipboard.has_text() is False


# ============================================================================
# Test: simulate_paste()
# ============================================================================


class TestSimulatePaste:
    """simulate_paste() platform-specific shortcut tests."""

    @staticmethod
    def _inject_mock_pynput(mock_ctrl, mock_key):
        """Inject mock pynput.keyboard into sys.modules so the local
        'from pynput.keyboard import ...' in simulate_paste() resolves."""
        mock_keyboard = mock.MagicMock()
        mock_keyboard.Controller = mock.MagicMock(return_value=mock_ctrl)
        mock_keyboard.Key = mock_key

        mock_pynput = mock.MagicMock()
        mock_pynput.keyboard = mock_keyboard

        # Ensure sys.modules has the mock; restore after test
        return mock.patch.dict("sys.modules", {"pynput": mock_pynput, "pynput.keyboard": mock_keyboard})

    def test_simulate_paste_windows(self, mock_pyperclip):
        """simulate_paste() should send Ctrl+V on Windows."""
        mock_ctrl = mock.MagicMock()
        mock_key = mock.MagicMock()
        mock_key.ctrl = mock.sentinel.CTRL_KEY

        with mock.patch("platform.system", return_value="Windows"), \
             self._inject_mock_pynput(mock_ctrl, mock_key):
            mgr = ClipboardManager()
            mgr.simulate_paste()

        mock_ctrl.pressed.assert_called_once_with(mock.sentinel.CTRL_KEY)

    def test_simulate_paste_macos(self, mock_pyperclip):
        """simulate_paste() should send Cmd+V on macOS."""
        mock_ctrl = mock.MagicMock()
        mock_key = mock.MagicMock()
        mock_key.cmd = mock.sentinel.CMD_KEY

        with mock.patch("platform.system", return_value="Darwin"), \
             self._inject_mock_pynput(mock_ctrl, mock_key):
            mgr = ClipboardManager()
            mgr.simulate_paste()

        mock_ctrl.pressed.assert_called_once_with(mock.sentinel.CMD_KEY)

    def test_simulate_paste_linux(self, mock_pyperclip):
        """simulate_paste() should send Ctrl+V on Linux."""
        mock_ctrl = mock.MagicMock()
        mock_key = mock.MagicMock()
        mock_key.ctrl = mock.sentinel.CTRL_KEY

        with mock.patch("platform.system", return_value="Linux"), \
             self._inject_mock_pynput(mock_ctrl, mock_key):
            mgr = ClipboardManager()
            mgr.simulate_paste()

        mock_ctrl.pressed.assert_called_once_with(mock.sentinel.CTRL_KEY)

    def test_simulate_paste_pynput_error(self, mock_pyperclip):
        """simulate_paste() propagates pynput ImportError."""
        # Remove pynput from sys.modules to trigger ImportError
        with mock.patch.dict("sys.modules", {"pynput": None, "pynput.keyboard": None}):
            mgr = ClipboardManager()
            with pytest.raises(ImportError):
                mgr.simulate_paste()
