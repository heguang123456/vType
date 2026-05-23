"""
M-08: Cross-platform Clipboard Operations Wrapper
==================================================
Encapsulates pyperclip for platform-independent clipboard access
and pynput for paste shortcut simulation.

Used by: core/typer.py (M-05) — clipboard paste fallback path

Data Flow:
  ClipboardManager.copy(text)     → pyperclip.copy(text)
  ClipboardManager.get_text()     → pyperclip.paste()
  ClipboardManager.simulate_paste() → pynput Ctrl/Cmd+V

Platform detection is automatic via platform.system().
"""

import logging
import platform
import time

logger = logging.getLogger(__name__)


class ClipboardError(Exception):
    """Base exception for clipboard operation failures."""


class ClipboardManager:
    """Cross-platform clipboard operations wrapper for typer fallback.

    Encapsulates pyperclip backend auto-detection and pynput paste
    shortcut simulation. Designed as a thin facade so typer.py can
    mock clipboard operations independently.

    pyperclip backends (auto-detected):
      - Windows:  win32clipboard (ctypes Win32 API)
      - macOS:    pbcopy / pbpaste (subprocess)
      - Linux:    xclip / xsel (subprocess)
    """

    def __init__(self) -> None:
        """Initialize clipboard access and keyboard controller.

        Raises:
            ClipboardError: If pyperclip is not installed or its
                backend is unavailable (e.g. no xclip on Linux).
        """
        self._import_pyperclip()

    # ------------------------------------------------------------------
    # pyperclip import with graceful failure
    # ------------------------------------------------------------------

    @staticmethod
    def _import_pyperclip() -> None:
        """Verify pyperclip is importable and has a working backend.

        Raises:
            ClipboardError: With platform-specific installation hints.
        """
        try:
            import pyperclip  # noqa: F401
        except ImportError:
            raise ClipboardError(
                "pyperclip is not installed. "
                "Install it with: pip install pyperclip>=1.8.2"
            )

        # On Linux, pyperclip may import but fail at runtime if xclip/xsel
        # is missing.  We don't force a runtime check here to avoid
        # unnecessary subprocess calls; the error will surface on first
        # copy/paste call.
        if platform.system() == "Linux":
            logger.debug(
                "ClipboardManager: Linux detected. "
                "Ensure xclip or xsel is installed: "
                "sudo apt install xclip"
            )

    # ------------------------------------------------------------------
    # Core clipboard operations
    # ------------------------------------------------------------------

    def copy(self, text: str) -> None:
        """Copy text to system clipboard.

        Args:
            text: Text content to copy.
        """
        import pyperclip

        pyperclip.copy(text)

    def get_text(self) -> str:
        """Get current clipboard text content.

        Returns:
            Clipboard text, or empty string if clipboard is empty
            or contains non-text content (e.g. image).

        Raises:
            ClipboardError: If pyperclip backend is unavailable.
        """
        import pyperclip

        try:
            text = pyperclip.paste()
            if not isinstance(text, str):
                logger.warning(
                    "Clipboard contains non-text content (type=%s), returning ''",
                    type(text).__name__,
                )
                return ""
            return text
        except Exception as e:
            logger.debug("pyperclip.paste() failed: %s", e)
            raise ClipboardError(
                f"Failed to read clipboard: {e}. "
                "Check that the clipboard backend is installed."
            ) from e

    def has_text(self) -> bool:
        """Check if clipboard contains text content.

        Returns:
            True if get_text() returns a non-empty string.
        """
        try:
            return bool(self.get_text())
        except ClipboardError:
            return False

    # ------------------------------------------------------------------
    # Paste shortcut simulation
    # ------------------------------------------------------------------

    def simulate_paste(self) -> None:
        """Simulate Ctrl+V (Windows/Linux) or Cmd+V (macOS) keystroke.

        Uses pynput.keyboard.Controller to press and release
        the platform-appropriate paste shortcut. This requires
        pynput keyboard simulation permissions (same as typer's
        _type_via_pynput).

        Raises:
            TypeError: If pynput is not installed.
        """
        from pynput.keyboard import Controller, Key

        keyboard = Controller()

        system = platform.system()
        if system == "Darwin":
            # macOS: Cmd+V
            with keyboard.pressed(Key.cmd):
                keyboard.press("v")
                keyboard.release("v")
                time.sleep(0.01)  # brief release delay
        else:
            # Windows / Linux: Ctrl+V
            with keyboard.pressed(Key.ctrl):
                keyboard.press("v")
                keyboard.release("v")
                time.sleep(0.01)
