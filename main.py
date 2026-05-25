"""
vType CLI Entry Point — Command-line voice input.
===================================================
Provides a click-based CLI with subcommands for starting the
voice input pipeline, listing audio devices, and viewing config.

Architecture:
    main.py
        ├── click.group("vtype")           # Root CLI
        │   ├── start                      # Launch voice input
        │   ├── devices                    # List audio devices
        │   └── config                     # Print config summary
        └── signal handlers                # SIGINT / SIGTERM

Example:
    $ vtype start
    $ vtype start --model-size small --language en
    $ vtype devices
    $ vtype config
"""

import logging
import signal
import sys
import time
from typing import Callable, Optional

import click

import config
from core.manager import CoreManager
from utils.key_monitor import KeyMonitor


__version__ = "0.1.0"

logger = logging.getLogger(__name__)

# Global references for signal handler access
_manager: Optional[CoreManager] = None
_monitor: Optional[KeyMonitor] = None
_started_at: float = 0.0
_record_mode: Optional[str] = None


# ============================================================================
# CLI Definition
# ============================================================================


@click.group()
@click.version_option(
    version=__version__,
    prog_name="vType",
    message="vType %(version)s — CLI Voice Input",
)
def cli():
    """vType — CLI Voice Input.

    Fully local, lightweight, cross-platform voice typing.
    Hold the hotkey (default CapsLock) and speak — recognized
    text is typed at the cursor.

    Powered by faster-whisper (CPU, int8 quantization).
    """
    pass


# ============================================================================
# start Command
# ============================================================================


@cli.command()
@click.option(
    "--model-size",
    default=None,
    type=click.Choice(["tiny", "base", "small", "medium"]),
    help="Whisper model size (default: base)",
)
@click.option(
    "--compute-type",
    default=None,
    type=click.Choice(["int8", "int8_float16", "float16"]),
    help="Compute precision (default: int8)",
)
@click.option(
    "--language",
    default=None,
    help="Recognition language code (default: zh)",
)
@click.option(
    "--silence-limit",
    type=int,
    default=None,
    help="Silence threshold in ms (default: 1500)",
)
@click.option(
    "--record-mode",
    default=None,
    type=click.Choice(["vad", "push_to_talk"]),
    help="Recording mode (default: vad)",
)
@click.option(
    "--hotkey",
    default=None,
    help="Hotkey string in pynput format (default: Key.caps_lock)",
)
@click.option(
    "--verbose",
    is_flag=True,
    help="Verbose debug logging",
)
@click.option(
    "--quiet",
    is_flag=True,
    help="Quiet mode — only errors",
)
def start(model_size, compute_type, language, silence_limit, record_mode, hotkey, verbose, quiet):
    """Launch the voice input service.

    Hold the hotkey (default CapsLock), speak, and release.
    The recognized text is typed at the cursor automatically.

    Press Ctrl+C to stop.
    """
    global _manager, _monitor, _started_at, _record_mode

    # 1. Configure logging
    _configure_logging(verbose, quiet)

    # 2. Build kwargs from CLI options (only non-None ones)
    kwargs = {}
    if model_size is not None:
        kwargs["model_size"] = model_size
    if compute_type is not None:
        kwargs["compute_type"] = compute_type
    if language is not None:
        kwargs["language"] = language
    if silence_limit is not None:
        # Convert ms → frame count
        kwargs["silence_frame_limit"] = silence_limit // config.FRAME_DURATION_MS
    if record_mode is not None:
        kwargs["record_mode"] = record_mode

    # 3. Validate config
    errors = config.validate_config()
    if errors:
        click.echo("检测到配置错误:", err=True)
        for err in errors:
            click.echo(f"  - {err}", err=True)
        sys.exit(1)

    # 4. Create CoreManager (stores config, no heavy work yet)
    click.echo("vType 初始化中...")
    _record_mode = record_mode  # store for hotkey callbacks
    try:
        _manager = CoreManager(**kwargs)
    except Exception as exc:
        click.echo(f"初始化核心管理器失败: {exc}", err=True)
        click.echo(
            "提示: 在中国大陆可设置 HF_ENDPOINT=https://hf-mirror.com 加速模型下载。",
            err=True,
        )
        sys.exit(1)

    # 5. Create callbacks
    text_cb = _create_text_callback()
    status_cb = _create_status_callback()

    # 6. Patch callbacks onto the manager (for real-time output)
    _manager._text_callback = text_cb
    _manager._status_callback = status_cb

    # 7. Create KeyMonitor
    _monitor = KeyMonitor(
        on_press=_on_hotkey_press,
        on_release=_on_hotkey_release,
        hotkey=hotkey,
    )

    # 8. Register signal handlers
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    if sys.platform == "win32":
        try:
            signal.signal(signal.SIGBREAK, _signal_handler)  # type: ignore[attr-defined]
        except AttributeError:
            pass

    # 9. Start key monitor
    _monitor.start()

    # 10. Print welcome banner
    _started_at = time.time()
    _print_welcome(model_size, compute_type, language, silence_limit, record_mode, hotkey)

    # 11. Wait for shutdown (listener.join or sleep loop)
    try:
        while _monitor.is_listening:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass

    # 12. Graceful shutdown
    _shutdown()


# ============================================================================
# devices Command
# ============================================================================


@cli.command()
def devices():
    """List available audio input devices."""
    import sounddevice as sd

    click.echo("可用音频输入设备:")
    click.echo()

    all_devices = sd.query_devices()
    default_input = sd.default.device[0] if sd.default.device else None
    found_any = False

    for idx, dev in enumerate(all_devices):
        # Check if device supports input
        if dev["max_input_channels"] > 0:
            found_any = True
            is_default = (idx == default_input or default_input is None and idx == 0)
            marker = " (默认)" if is_default else ""
            click.echo(f"  {idx}: {dev['name']}{marker}")
            click.echo(f"      声道: {dev['max_input_channels']} 输入, "
                       f"{dev['max_output_channels']} 输出")
            click.echo(f"      采样率: {dev['default_samplerate']:.0f} Hz")

    if not found_any:
        click.echo("  未找到输入设备。", err=True)
        click.echo("  请确保麦克风已连接。", err=True)


# ============================================================================
# config Command
# ============================================================================


@cli.command()
def config_command():
    """Print the current vType configuration."""
    config.print_config()


# ============================================================================
# Internal: Logging
# ============================================================================


class _LocalizedFormatter(logging.Formatter):
    """Translate common third-party library log messages to Chinese."""

    _TRANSLATIONS = {
        "Processing audio with duration": "正在处理音频，时长",
        "HTTP Request:": "HTTP 请求:",
    }

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        for en, zh in self._TRANSLATIONS.items():
            if en in msg:
                record.msg = msg.replace(en, zh)
                record.args = ()
                break
        return super().format(record)


def _configure_logging(verbose: bool, quiet: bool) -> None:
    """Configure logging level based on CLI flags.

    Args:
        verbose: If True, set level to DEBUG.
        quiet: If True, set level to ERROR.
        (neither): Default to INFO.
    """
    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.ERROR
    else:
        level = logging.INFO

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        _LocalizedFormatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logging.basicConfig(
        level=level,
        handlers=[handler],
    )
    logger.debug("日志已配置: 级别=%s", logging.getLevelName(level))


# ============================================================================
# Internal: Callbacks
# ============================================================================


def _create_text_callback() -> Callable[[str], None]:
    """Create a callback that prints recognized text to stdout.

    Text is output without a newline to simulate "blind typing" —
    the recognized text appears directly at the cursor position.
    """
    def on_text(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    return on_text


def _create_status_callback() -> Callable:
    """Create a callback that logs status changes at DEBUG level."""
    def on_status_change(old, new) -> None:
        logger.debug("管理器状态: %s → %s", old.name, new.name)

    return on_status_change


# ============================================================================
# Internal: Hotkey Callbacks
# ============================================================================


def _on_hotkey_press() -> None:
    """Called when the push-to-talk hotkey is pressed."""
    global _manager, _record_mode
    if _manager is not None:
        try:
            rm = _record_mode or config.RECORD_MODE
            if rm == "push_to_talk":
                _manager.start_recording()
            else:
                _manager.start()
        except Exception:
            logger.exception("按下快捷键时启动核心管理器失败")


def _on_hotkey_release() -> None:
    """Called when the push-to-talk hotkey is released."""
    global _manager, _record_mode
    if _manager is not None:
        try:
            rm = _record_mode or config.RECORD_MODE
            if rm == "push_to_talk":
                _manager.stop_recording()
            else:
                _manager.stop()
        except Exception:
            logger.exception("松开快捷键时停止核心管理器失败")


# ============================================================================
# Internal: Signal Handling
# ============================================================================


def _signal_handler(signum, frame) -> None:
    """Handle SIGINT (Ctrl+C), SIGTERM, and SIGBREAK (Windows).

    Triggers graceful shutdown: stops KeyMonitor first, then
    CoreManager, then prints summary and exits.
    """
    # Prevent recursive signal handling
    signal.signal(signum, signal.SIG_IGN)

    logger.info("收到信号 %d，正在关闭...", signum)
    _shutdown()
    sys.exit(0)


# ============================================================================
# Internal: Shutdown
# ============================================================================


def _shutdown() -> None:
    """Perform graceful shutdown of KeyMonitor and CoreManager."""
    global _manager, _monitor

    # Capture statistics BEFORE stop() — stop() triggers _cleanup()
    # which nullifies submodule references, making statistics()
    # return zeroed-out values (e.g. detector_slices=0).
    stats: Optional[dict] = None
    if _manager is not None:
        try:
            stats = _manager.statistics
        except Exception:
            logger.exception("Failed to capture statistics")

    if _monitor is not None:
        logger.debug("正在停止快捷键监听器...")
        _monitor.stop()

    if _manager is not None:
        logger.debug("正在停止核心管理器...")
        _manager.stop()

    _print_summary(stats)
    _monitor = None
    _manager = None


# ============================================================================
# Internal: Display
# ============================================================================


def _print_welcome(
    model_size: Optional[str],
    compute_type: Optional[str],
    language: Optional[str],
    silence_limit: Optional[int],
    record_mode: Optional[str],
    hotkey: Optional[str],
) -> None:
    """Print the welcome banner after startup."""
    model = model_size or config.MODEL_SIZE
    lang = language or config.LANGUAGE
    sil = silence_limit or config.SILENCE_LIMIT_MS
    rm = record_mode or config.RECORD_MODE
    hk = hotkey or "CapsLock"

    click.echo()
    click.echo("╔══════════════════════════════════════════════╗")
    click.echo("║          vType v0.1.0 — 就绪                ║")
    click.echo("╠══════════════════════════════════════════════╣")
    if rm == "push_to_talk":
        click.echo("║  按住快捷键说话，松开后识别输入              ║")
    else:
        click.echo("║  按住快捷键说话，松开后输入文字              ║")
    click.echo("║  按 Ctrl+C 退出                              ║")
    click.echo("║                                              ║")
    click.echo(f"║  模型: {model:<5} | 语言: {lang:<3} | "
               f"静音: {sil}ms   ║")
    click.echo(f"║  模式: {rm:<12} | 快捷键: {hk}              ║")
    click.echo("╚══════════════════════════════════════════════╝")
    click.echo()


def _print_summary(stats: Optional[dict] = None) -> None:
    """Print a statistics summary after shutdown.

    Args:
        stats: Pre-captured statistics dict from CoreManager.statistics.
            Must be captured before stop() to avoid zeroed-out values.
    """
    global _started_at

    if _started_at == 0.0:
        return

    elapsed = time.time() - _started_at
    duration_str = _format_duration(elapsed)

    segments = 0
    final_status = "IDLE"

    if stats is not None:
        segments = stats.get("detector_slices", 0)
        final_status = stats.get("status", "IDLE")

    click.echo()
    click.echo("vType 已停止。")
    click.echo("─────────────────────────")
    click.echo(f"  运行时长:    {duration_str}")
    click.echo(f"  语音片段:    {segments}")
    click.echo(f"  最终状态:    {final_status}")
    click.echo("─────────────────────────")


def _format_duration(seconds: float) -> str:
    """Format duration in human-readable form.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like "5m 12s" or "42s".
    """
    seconds = int(seconds)
    minutes = seconds // 60
    secs = seconds % 60

    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


# ============================================================================
# Entry Point
# ============================================================================


if __name__ == "__main__":
    cli()
