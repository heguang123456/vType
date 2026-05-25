"""
M-05: Keyboard Output Engine (Consumer Thread - Second Half)
=============================================================
Retrieves recognized text from result_queue and types it
at the current cursor position using pynput keyboard simulation.
Falls back to clipboard paste when pynput permission is denied.

Data Flow:
  result_queue (Queue[str]) → TypeWriter.run()
    → TypeWriter.type_text()
      ├── _type_via_pynput()     [primary]
      └── _type_via_clipboard()  [fallback, via M-08 ClipboardManager]

Platform support:
  - Windows:  SendInput API (no extra permissions)
  - macOS:    CGEvent (needs Accessibility permission)
  - Linux:    Xlib / uinput (may need input group)

Config (from config.py):
  - TYPE_DELAY:         delay between keystrokes (default 0.005s)
  - CLIPBOARD_FALLBACK: enable clipboard paste fallback (default True)
"""

import logging
import queue
import threading
import time
from typing import Optional

from config import CLIPBOARD_FALLBACK, TYPE_DELAY
from utils.clipboard import ClipboardManager

logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================


class TypeWriterError(Exception):
    """Base exception for typewriter errors."""


class TypeWriterPermissionError(TypeWriterError):
    """Pynput permission denied and clipboard fallback is disabled."""


# ============================================================================
# TypeWriter
# ============================================================================


class TypeWriter:
    """Keyboard output engine (consumer thread - second half).

    Retrieves recognized text from result_queue and types it
    at the current cursor position using pynput keyboard simulation.
    Falls back to clipboard paste when pynput permission is denied.
    """

    def __init__(
        self,
        type_delay: float = TYPE_DELAY,
        clipboard_fallback: bool = CLIPBOARD_FALLBACK,
    ) -> None:
        """Initialize keyboard controller and clipboard manager.

        Args:
            type_delay: Delay between keystrokes in seconds (0-0.1).
            clipboard_fallback: Enable clipboard paste fallback.

        Raises:
            TypeWriterError: If pynput is not installed and clipboard
                fallback is disabled (without pynput, simulate_paste
                also cannot work).
        """
        self._type_delay = type_delay
        self._clipboard_fallback = clipboard_fallback

        # pynput keyboard controller (primary typing path)
        self._keyboard = self._create_keyboard_controller()

        # Clipboard manager (fallback path, M-08)
        self._clipboard: Optional[ClipboardManager] = None
        if self._clipboard_fallback:
            self._clipboard = ClipboardManager()

    # ------------------------------------------------------------------
    # pynput Controller initialization
    # ------------------------------------------------------------------

    @staticmethod
    def _create_keyboard_controller():
        """Create pynput keyboard Controller.

        Returns:
            pynput.keyboard.Controller instance.

        Raises:
            TypeWriterError: If pynput is not installed.
        """
        try:
            from pynput.keyboard import Controller as KbController

            return KbController()
        except ImportError:
            raise TypeWriterError(
                "pynput is not installed. Install it with: pip install pynput>=1.7.6"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def type_text(self, text: Optional[str]) -> None:
        """Type text at current cursor position.

        Primary path: pynput.keyboard.Controller.type() character-by-character.
        Fallback path: clipboard paste (save → copy → paste → restore).

        Args:
            text: Recognized text from ASR engine. None or empty strings
                  are silently skipped.

        Raises:
            TypeWriterPermissionError: If pynput permission denied and
                CLIPBOARD_FALLBACK is disabled.
            TypeWriterError: If both primary and fallback paths fail.
        """
        # Skip empty / None / whitespace-only text
        if not text or not text.strip():
            return

        try:
            self._type_via_pynput(text)
        except (PermissionError, OSError) as e:
            if not self._clipboard_fallback:
                raise TypeWriterPermissionError(
                    "pynput keyboard simulation permission denied and "
                    "CLIPBOARD_FALLBACK is disabled. "
                    "Set VTYPE_CLIPBOARD_FALLBACK=true to enable clipboard fallback, or "
                    "grant keyboard simulation permissions to your terminal."
                ) from e

            logger.warning(
                "pynput 权限被拒绝 (%s)，回退到剪贴板粘贴。", e
            )
            self._type_via_clipboard(text)

    def run(
        self,
        result_queue: queue.Queue,
        stop_event: threading.Event,
    ) -> None:
        """Consumer main loop (second half).

        Blocks on result_queue for recognized text from Recognizer,
        outputs via type_text(), and loops until stop_event is set.

        Args:
            result_queue: Queue of recognized text strings from Recognizer.
            stop_event: Signals graceful shutdown.
        """
        logger.info("打字机消费者循环已启动。")

        while not stop_event.is_set():
            try:
                text = result_queue.get(timeout=0.2)
                if text and text.strip():
                    self.type_text(text)
            except queue.Empty:
                continue
            except TypeWriterError as e:
                logger.error("打字机错误: %s", e)
            except Exception:
                logger.exception("打字机发生未预期错误")

        logger.info("打字机消费者循环已停止。")

    # ------------------------------------------------------------------
    # Private: Primary typing path (pynput)
    # ------------------------------------------------------------------

    def _type_via_pynput(self, text: str) -> None:
        """Simulate keyboard input character by character via pynput.

        Each character is typed individually with TYPE_DELAY spacing
        to prevent OS-level keyboard buffer overflow.

        Args:
            text: Cleaned text (non-empty, stripped).
        """
        for char in text:
            self._keyboard.type(char)
            time.sleep(self._type_delay)

    # ------------------------------------------------------------------
    # Private: Fallback typing path (clipboard)
    # ------------------------------------------------------------------

    def _type_via_clipboard(self, text: str) -> None:
        """Fallback: copy text to clipboard and simulate Ctrl/Cmd+V.

        Saves original clipboard content before pasting and restores
        it after paste completes to avoid data loss.

        Args:
            text: Cleaned text (non-empty, stripped).

        Raises:
            TypeWriterError: If clipboard operations fail.
        """
        if self._clipboard is None:
            raise TypeWriterError(
                "剪贴板回退已禁用且 pynput 失败。"
                "设置 VTYPE_CLIPBOARD_FALLBACK=true 以启用。"
            )

        original = self._clipboard.get_text()

        try:
            self._clipboard.copy(text)
            self._clipboard.simulate_paste()
            time.sleep(0.1)  # Brief delay to let paste complete
        except Exception as e:
            raise TypeWriterError(
                f"剪贴板粘贴回退失败: {e}"
            ) from e
        finally:
            # Restore original clipboard content
            if original:
                try:
                    self._clipboard.copy(original)
                except Exception as e:
                    logger.warning(
                        "恢复原始剪贴板内容失败: %s", e
                    )
