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
    help="Silence threshold in ms (default: 800)",
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
def start(model_size, compute_type, language, silence_limit, hotkey, verbose, quiet):
    """Launch the voice input service.

    Hold the hotkey (default CapsLock), speak, and release.
    The recognized text is typed at the cursor automatically.

    Press Ctrl+C to stop.
    """
    global _manager, _monitor, _started_at

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

    # 3. Validate config
    errors = config.validate_config()
    if errors:
        click.echo("Configuration errors detected:", err=True)
        for err in errors:
            click.echo(f"  - {err}", err=True)
        sys.exit(1)

    # 4. Create CoreManager (stores config, no heavy work yet)
    click.echo("vType initializing...")
    try:
        _manager = CoreManager(**kwargs)
    except Exception as exc:
        click.echo(f"Failed to initialize CoreManager: {exc}", err=True)
        click.echo(
            "Tip: Set HF_ENDPOINT=https://hf-mirror.com for faster model download "
            "in China.",
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
    _print_welcome(model_size, compute_type, language, silence_limit, hotkey)

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

    click.echo("Available audio input devices:")
    click.echo()

    all_devices = sd.query_devices()
    default_input = sd.default.device[0] if sd.default.device else None
    found_any = False

    for idx, dev in enumerate(all_devices):
        # Check if device supports input
        if dev["max_input_channels"] > 0:
            found_any = True
            is_default = (idx == default_input or default_input is None and idx == 0)
            marker = " (default)" if is_default else ""
            click.echo(f"  {idx}: {dev['name']}{marker}")
            click.echo(f"      channels: {dev['max_input_channels']} input, "
                       f"{dev['max_output_channels']} output")
            click.echo(f"      samplerate: {dev['default_samplerate']:.0f} Hz")

    if not found_any:
        click.echo("  No input devices found.", err=True)
        click.echo("  Make sure a microphone is connected.", err=True)


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

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    logger.debug("Logging configured: level=%s", logging.getLevelName(level))


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
        logger.debug("Manager status: %s → %s", old.name, new.name)

    return on_status_change


# ============================================================================
# Internal: Hotkey Callbacks
# ============================================================================


def _on_hotkey_press() -> None:
    """Called when the push-to-talk hotkey is pressed."""
    global _manager
    if _manager is not None:
        try:
            _manager.start()
        except Exception:
            logger.exception("Failed to start CoreManager on hotkey press")


def _on_hotkey_release() -> None:
    """Called when the push-to-talk hotkey is released."""
    global _manager
    if _manager is not None:
        try:
            _manager.stop()
        except Exception:
            logger.exception("Failed to stop CoreManager on hotkey release")


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

    logger.info("Received signal %d, shutting down...", signum)
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
        logger.debug("Stopping KeyMonitor...")
        _monitor.stop()

    if _manager is not None:
        logger.debug("Stopping CoreManager...")
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
    hotkey: Optional[str],
) -> None:
    """Print the welcome banner after startup."""
    model = model_size or config.MODEL_SIZE
    lang = language or config.LANGUAGE
    sil = silence_limit or config.SILENCE_LIMIT_MS
    hk = hotkey or "CapsLock"

    click.echo()
    click.echo("╔══════════════════════════════════════════════╗")
    click.echo("║          vType v0.1.0 — Ready               ║")
    click.echo("╠══════════════════════════════════════════════╣")
    click.echo("║  Hold the hotkey, speak, release to type     ║")
    click.echo("║  Press Ctrl+C to quit                        ║")
    click.echo("║                                              ║")
    click.echo(f"║  Model: {model:<5} | Language: {lang:<3} | "
               f"Silence: {sil}ms   ║")
    click.echo(f"║  Hotkey: {hk}                              ║")
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
    click.echo("vType stopped.")
    click.echo("─────────────────────────")
    click.echo(f"  Duration:    {duration_str}")
    click.echo(f"  Segments:    {segments}")
    click.echo(f"  Final state: {final_status}")
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
