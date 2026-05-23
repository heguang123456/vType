"""
vType Global Configuration Center
==================================
Centralized configuration with environment variable override support.

Data Flow:
  Default values → env var override (VTYPE_* prefix) → runtime constant

All parameters are imported by other modules as module-level constants.
"""

import os
import sys
from typing import Any, Dict, Final, List

# ============================================================================
# Helper: read environment variables with type coercion
# ============================================================================


def _env_int(name: str, default: int) -> int:
    """Read integer env var, fall back to default."""
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        print(f"[WARN] {name}={val} is not a valid integer, using default={default}", file=sys.stderr)
        return default


def _env_float(name: str, default: float) -> float:
    """Read float env var, fall back to default."""
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        print(f"[WARN] {name}={val} is not a valid float, using default={default}", file=sys.stderr)
        return default


def _env_str(name: str, default: str) -> str:
    """Read string env var, fall back to default."""
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool) -> bool:
    """Read boolean env var, fall back to default.

    True values:  "true", "1", "yes" (case-insensitive)
    False values: "false", "0", "no" (case-insensitive)
    """
    val = os.environ.get(name)
    if val is None:
        return default
    val_lower = val.strip().lower()
    if val_lower in ("true", "1", "yes"):
        return True
    elif val_lower in ("false", "0", "no"):
        return False
    else:
        print(f"[WARN] {name}={val} is not a valid boolean, using default={default}", file=sys.stderr)
        return default


# ============================================================================
# Audio Capture Parameters
# ============================================================================

SAMPLE_RATE: Final[int] = _env_int("VTYPE_SAMPLE_RATE", 16000)
"""Audio sample rate in Hz. Whisper requires 16000."""

CHANNELS: Final[int] = _env_int("VTYPE_CHANNELS", 1)
"""Audio channels. Must be 1 (mono) for webrtcvad."""

FRAME_DURATION_MS: Final[int] = _env_int("VTYPE_FRAME_DURATION_MS", 20)
"""VAD frame duration in ms. Must be 10, 20, or 30."""

# BLOCK_SIZE is derived: SAMPLE_RATE * FRAME_DURATION_MS / 1000
# User can override via VTYPE_BLOCK_SIZE, but it will be validated.
# Default calculation: 16000 * 20 / 1000 = 320 samples/frame
_env_bs = _env_int("VTYPE_BLOCK_SIZE", -1)
if _env_bs > 0:
    BLOCK_SIZE: Final[int] = _env_bs
else:
    BLOCK_SIZE: Final[int] = SAMPLE_RATE * FRAME_DURATION_MS // 1000

DTYPE: Final[str] = _env_str("VTYPE_DTYPE", "int16")
"""Audio sample data type. 'int16' for VAD, 'float32' for Whisper input."""


# ============================================================================
# Voice Activity Detection (VAD) Parameters
# ============================================================================

VAD_AGGRESSIVENESS: Final[int] = _env_int("VTYPE_VAD_AGGRESSIVENESS", 3)
"""VAD aggressiveness mode. 0=quiet, 1=normal, 2=noisy, 3=very noisy."""


# ============================================================================
# Silence Detection & Slicing Parameters
# ============================================================================

SILENCE_LIMIT_MS: Final[int] = _env_int("VTYPE_SILENCE_LIMIT_MS", 800)
"""Consecutive silence duration (ms) before slicing and sending to ASR."""

SILENCE_FRAME_LIMIT: Final[int] = SILENCE_LIMIT_MS // FRAME_DURATION_MS
"""Derived: number of consecutive silent frames before slicing.
Calculated as SILENCE_LIMIT_MS / FRAME_DURATION_MS.
Example: 800ms / 20ms = 40 frames.
"""


# ============================================================================
# ASR Inference Parameters (faster-whisper)
# ============================================================================

MODEL_SIZE: Final[str] = _env_str("VTYPE_MODEL_SIZE", "base")
"""Whisper model size: tiny, base, small, medium, large, large-v2, large-v3."""

COMPUTE_TYPE: Final[str] = _env_str("VTYPE_COMPUTE_TYPE", "int8")
"""CTranslate2 compute type: int8, int8_float16, float16.
int8 is recommended for CPU inference (4x memory reduction).
"""

DEVICE: Final[str] = _env_str("VTYPE_DEVICE", "cpu")
"""Inference device: cpu or cuda."""

BEAM_SIZE: Final[int] = _env_int("VTYPE_BEAM_SIZE", 3)
"""Beam search width. 3 balances speed and accuracy for Chinese."""

LANGUAGE: Final[str] = _env_str("VTYPE_LANGUAGE", "zh")
"""Recognition language. 'zh' for Chinese, 'auto' for auto-detection."""


# ============================================================================
# Keyboard Output Parameters
# ============================================================================

TYPE_DELAY: Final[float] = _env_float("VTYPE_TYPE_DELAY", 0.005)
"""Delay between keystrokes in seconds. Prevents OS-level rate limiting."""

CLIPBOARD_FALLBACK: Final[bool] = _env_bool("VTYPE_CLIPBOARD_FALLBACK", True)
"""Enable clipboard paste fallback when pynput permission is denied."""


# ============================================================================
# Queue & Threading Parameters
# ============================================================================

QUEUE_MAXSIZE: Final[int] = _env_int("VTYPE_QUEUE_MAXSIZE", 10)
"""Maximum size of the cross-thread task queue.
When full, the producer will drop old frames to prevent blocking.
"""


# ============================================================================
# Configuration Validation
# ============================================================================

def validate_config() -> List[str]:
    """Validate all configuration parameters.

    Returns:
        List of error messages. Empty list means all parameters are valid.
    """
    errors: List[str] = []

    # Audio parameters
    if SAMPLE_RATE not in (8000, 16000, 32000, 44100, 48000):
        errors.append(f"SAMPLE_RATE={SAMPLE_RATE} is unusual; expected 8000/16000/32000/44100/48000")

    if CHANNELS != 1:
        errors.append(f"CHANNELS={CHANNELS}; webrtcvad requires mono (CHANNELS=1)")

    if FRAME_DURATION_MS not in (10, 20, 30):
        errors.append(f"FRAME_DURATION_MS={FRAME_DURATION_MS}; must be 10, 20, or 30")

    if DTYPE not in ("int16", "float32"):
        errors.append(f"DTYPE='{DTYPE}'; must be 'int16' or 'float32'")

    # Validate BLOCK_SIZE consistency
    expected_block = SAMPLE_RATE * FRAME_DURATION_MS // 1000
    if BLOCK_SIZE != expected_block:
        errors.append(
            f"BLOCK_SIZE={BLOCK_SIZE} inconsistent with "
            f"SAMPLE_RATE={SAMPLE_RATE} × FRAME_DURATION_MS={FRAME_DURATION_MS} / 1000 = {expected_block}"
        )

    # VAD parameters
    if VAD_AGGRESSIVENESS < 0 or VAD_AGGRESSIVENESS > 3:
        errors.append(f"VAD_AGGRESSIVENESS={VAD_AGGRESSIVENESS}; must be 0-3")

    if SILENCE_LIMIT_MS < 100:
        errors.append(f"SILENCE_LIMIT_MS={SILENCE_LIMIT_MS}; must be >= 100ms")

    # ASR parameters
    valid_models = {"tiny", "base", "small", "medium", "large", "large-v2", "large-v3"}
    if MODEL_SIZE not in valid_models:
        errors.append(f"MODEL_SIZE='{MODEL_SIZE}'; must be one of {sorted(valid_models)}")

    valid_compute = {"int8", "int8_float16", "float16", "float32"}
    if COMPUTE_TYPE not in valid_compute:
        errors.append(f"COMPUTE_TYPE='{COMPUTE_TYPE}'; must be one of {sorted(valid_compute)}")

    if DEVICE not in ("cpu", "cuda", "auto"):
        errors.append(f"DEVICE='{DEVICE}'; must be 'cpu', 'cuda', or 'auto'")

    if BEAM_SIZE < 1 or BEAM_SIZE > 10:
        errors.append(f"BEAM_SIZE={BEAM_SIZE}; must be 1-10")

    # Output parameters
    if TYPE_DELAY < 0:
        errors.append(f"TYPE_DELAY={TYPE_DELAY}; must be >= 0")

    if QUEUE_MAXSIZE < 1:
        errors.append(f"QUEUE_MAXSIZE={QUEUE_MAXSIZE}; must be >= 1")

    return errors


def print_config() -> None:
    """Print the current configuration in a formatted table."""
    errors = validate_config()
    status = "OK" if not errors else f"{len(errors)} WARNING(S)"

    print(f"""
╔══════════════════════════════════════════════════════════╗
║              vType Configuration Summary                  ║
╠══════════════════════════════════════════════════════════╣
║  Audio Capture:                                          ║
║    SAMPLE_RATE         = {SAMPLE_RATE:>6} Hz                       ║
║    CHANNELS            = {CHANNELS:>6} (mono)                      ║
║    BLOCK_SIZE          = {BLOCK_SIZE:>6} samples/frame              ║
║    DTYPE               = {DTYPE:>6}                                ║
╠══════════════════════════════════════════════════════════╣
║  Voice Activity Detection:                                ║
║    FRAME_DURATION_MS   = {FRAME_DURATION_MS:>6} ms                       ║
║    VAD_AGGRESSIVENESS  = {VAD_AGGRESSIVENESS:>6} (0-3)                      ║
╠══════════════════════════════════════════════════════════╣
║  Silence Slicing:                                         ║
║    SILENCE_LIMIT_MS    = {SILENCE_LIMIT_MS:>6} ms                       ║
║    SILENCE_FRAME_LIMIT = {SILENCE_FRAME_LIMIT:>6} frames                    ║
╠══════════════════════════════════════════════════════════╣
║  ASR Inference:                                           ║
║    MODEL_SIZE          = {MODEL_SIZE:>6}                                ║
║    COMPUTE_TYPE        = {COMPUTE_TYPE:>6}                                ║
║    DEVICE              = {DEVICE:>6}                                ║
║    BEAM_SIZE           = {BEAM_SIZE:>6}                                  ║
║    LANGUAGE            = {LANGUAGE:>6}                                ║
╠══════════════════════════════════════════════════════════╣
║  Keyboard Output:                                         ║
║    TYPE_DELAY          = {TYPE_DELAY:>6} s                               ║
║    CLIPBOARD_FALLBACK  = {str(CLIPBOARD_FALLBACK):>6}                                ║
╠══════════════════════════════════════════════════════════╣
║  Queue & Threading:                                       ║
║    QUEUE_MAXSIZE       = {QUEUE_MAXSIZE:>6}                                  ║
╠══════════════════════════════════════════════════════════╣
║  Validation: {status:<44}║
╚══════════════════════════════════════════════════════════╝
""".strip())

    if errors:
        print("\n⚠ Configuration Warnings:")
        for err in errors:
            print(f"  - {err}")


def get_config_dict() -> Dict[str, Any]:
    """Return a dictionary copy of the current configuration.

    Useful for serialization, debugging, or passing config to other components.
    """
    return {
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
        "block_size": BLOCK_SIZE,
        "dtype": DTYPE,
        "frame_duration_ms": FRAME_DURATION_MS,
        "vad_aggressiveness": VAD_AGGRESSIVENESS,
        "silence_limit_ms": SILENCE_LIMIT_MS,
        "silence_frame_limit": SILENCE_FRAME_LIMIT,
        "model_size": MODEL_SIZE,
        "compute_type": COMPUTE_TYPE,
        "device": DEVICE,
        "beam_size": BEAM_SIZE,
        "language": LANGUAGE,
        "type_delay": TYPE_DELAY,
        "clipboard_fallback": CLIPBOARD_FALLBACK,
        "queue_maxsize": QUEUE_MAXSIZE,
    }
