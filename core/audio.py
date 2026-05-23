"""
Audio Capture Module (Producer Thread - First Half)
====================================================
Hardware microphone capture via sounddevice InputStream.

Data Flow:
    Microphone → PortAudio callback → raw_queue (numpy.ndarray) → detector.py

CRITICAL Design Constraint:
    The InputStream callback runs in PortAudio's internal high-priority thread.
    It MUST be minimal — only copy data and put into queue.
    Any blocking operation here will cause buffer underrun and audio frame loss.

Thread Safety:
    - _audio_callback: runs in PortAudio internal thread
    - start/stop/pause/resume: called from main thread
    - _is_running / _is_paused: threading.Event for cross-thread signaling
"""

import logging
import queue
import threading
from typing import Any, Dict, List, Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


class AudioCaptureError(Exception):
    """Base exception for audio capture failures."""

    pass


class DeviceNotFoundError(AudioCaptureError):
    """Raised when no suitable audio input device is found."""

    pass


class AudioCapture:
    """Hardware microphone capture using sounddevice InputStream.

    Opens a low-latency audio input stream and delivers raw NumPy arrays
    to a queue for downstream VAD processing.

    Example:
        >>> cap = AudioCapture(sample_rate=16000)
        >>> cap.start()
        >>> # Detector consumes from cap.raw_queue in another thread
        >>> cap.stop()
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        block_size: int = 320,
        dtype: str = "int16",
        device_id: Optional[int] = None,
    ) -> None:
        """Initialize audio capture.

        Args:
            sample_rate: Audio sample rate in Hz (default 16000 for Whisper).
            channels: Number of channels (default 1 for mono).
            block_size: Samples per callback frame.
            dtype: Audio data type ('int16' or 'float32').
            device_id: Specific input device ID, or None for system default.

        Raises:
            DeviceNotFoundError: If no audio input device is available.
        """
        self._sample_rate = sample_rate
        self._channels = channels
        self._block_size = block_size
        self._dtype = dtype
        self._device_id = device_id

        # Cross-thread signaling
        self._is_running = threading.Event()
        self._is_paused = threading.Event()

        # Raw audio queue: callback → detector
        self.raw_queue: queue.Queue = queue.Queue()

        # sounddevice stream handle (created in start())
        self._stream: Optional[sd.InputStream] = None

        # Validate device availability
        devices = sd.query_devices()
        input_devices = [d for d in devices if d["max_input_channels"] > 0]
        if not input_devices:
            raise DeviceNotFoundError(
                "No audio input device found. Please check your microphone connection."
            )

        if device_id is not None:
            try:
                device_info = sd.query_devices(device_id)
                # query_devices(id) returns a dict with device info
                # If mock returns a list (fallback), try indexing
                if isinstance(device_info, list):
                    if 0 <= device_id < len(device_info):
                        device_info = device_info[device_id]
                    else:
                        raise DeviceNotFoundError(f"Device {device_id} not found")
                if device_info.get("max_input_channels", 0) == 0:
                    raise DeviceNotFoundError(
                        f"Device {device_id} ({device_info.get('name', 'unknown')}) has no input channels."
                    )
            except (sd.PortAudioError, IndexError) as e:
                raise DeviceNotFoundError(f"Device {device_id} not found: {e}") from e

        logger.info(
            "AudioCapture initialized: sample_rate=%d, channels=%d, "
            "block_size=%d, dtype=%s, device_id=%s",
            sample_rate,
            channels,
            block_size,
            dtype,
            device_id,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Whether the audio stream is currently active."""
        return self._is_running.is_set()

    @property
    def is_paused(self) -> bool:
        """Whether capture is paused (stream open but not delivering data)."""
        return self._is_paused.is_set()

    def start(self) -> None:
        """Open and start the audio input stream.

        This method is blocking until the stream is opened (typically < 50ms).
        After start(), audio data flows through the callback into raw_queue.

        Raises:
            AudioCaptureError: If the stream fails to open.
        """
        if self._is_running.is_set():
            logger.warning("AudioCapture.start() called while already running")
            return

        try:
            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype=self._dtype,
                blocksize=self._block_size,
                device=self._device_id,
                callback=self._audio_callback,
            )
            self._stream.start()
            self._is_running.set()
            self._is_paused.clear()
            logger.info("Audio stream started successfully")
        except sd.PortAudioError as e:
            raise AudioCaptureError(
                f"Failed to open audio stream: {e}. "
                f"Please check your microphone settings and permissions."
            ) from e

    def stop(self) -> None:
        """Gracefully stop and close the audio stream.

        This method:
        1. Signals the callback to stop (via _is_running)
        2. Waits for the stream to drain
        3. Closes and releases PortAudio resources

        Safe to call multiple times. Does not raise on double-stop.
        """
        if not self._is_running.is_set():
            return

        logger.info("Stopping audio stream...")
        # Signal callback to stop accepting new data
        self._is_running.clear()
        self._is_paused.clear()

        if self._stream is not None:
            try:
                # Stop the stream first, then close to release resources
                self._stream.stop()
                self._stream.close()
            except sd.PortAudioError as e:
                logger.warning("Error during stream stop/close: %s", e)
            finally:
                self._stream = None

        # Drain the raw queue so detector thread can exit cleanly
        self._drain_queue()

        logger.info("Audio stream stopped")

    def pause(self) -> None:
        """Pause audio capture without closing the stream.

        When paused, the callback still runs but discards data.
        Use resume() to continue capture.
        """
        if not self._is_running.is_set():
            logger.warning("AudioCapture.pause() called while not running")
            return
        self._is_paused.set()
        logger.info("Audio capture paused")

    def resume(self) -> None:
        """Resume audio capture after pause."""
        if not self._is_running.is_set():
            logger.warning("AudioCapture.resume() called while not running")
            return
        self._is_paused.clear()
        logger.info("Audio capture resumed")

    @staticmethod
    def list_devices() -> List[Dict[str, Any]]:
        """List available audio input devices.

        Returns:
            List of dicts with keys: id, name, channels, sample_rate, is_default.
        """
        devices: List[Dict[str, Any]] = []
        try:
            all_devices = sd.query_devices()
            default_input = sd.default.device[0]  # default input device ID
        except sd.PortAudioError as e:
            logger.error("Failed to query audio devices: %s", e)
            return devices

        for i, dev in enumerate(all_devices):
            if dev["max_input_channels"] > 0:
                devices.append(
                    {
                        "id": i,
                        "name": dev["name"],
                        "channels": dev["max_input_channels"],
                        "sample_rate": int(dev["default_samplerate"]),
                        "is_default": i == default_input,
                    }
                )
        return devices

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: Any,
    ) -> None:
        """PortAudio stream callback. MUST remain minimal (< 50μs).

        Data Flow:
            indata → copy() → raw_queue.put()

        Args:
            indata: Raw audio data (numpy.ndarray, shape=(frames, channels)).
            frames: Number of frames in this callback.
            time_info: PortAudio time info (ADC capture time, etc.).
            status: Callback status flags (overflow, underflow warnings).

        Raises:
            sd.CallbackStop: Signals PortAudio to stop the stream gracefully.
        """
        # Check for hardware issues
        if status:
            if status.input_overflow:
                logger.warning("Audio input overflow — frames were dropped!")
            if status.input_underflow:
                logger.warning("Audio input underflow")

        # Graceful stop signal from stop()
        if not self._is_running.is_set():
            raise sd.CallbackStop

        # Paused: skip data delivery but keep stream alive
        if self._is_paused.is_set():
            return

        # CRITICAL: copy() prevents NumPy from reusing the buffer
        # Without copy(), the same ndarray is reused across callbacks
        try:
            self.raw_queue.put_nowait(indata.copy())
        except queue.Full:
            # Queue is full — detector thread is falling behind
            # Drop this frame rather than blocking the audio callback
            logger.warning("Raw audio queue is full, dropping frame")

    def _drain_queue(self) -> None:
        """Drain remaining frames from raw_queue after stop.

        This prevents the detector thread from blocking on queue.get()
        after the audio stream has stopped.
        """
        drained = 0
        while not self.raw_queue.empty():
            try:
                self.raw_queue.get_nowait()
                drained += 1
            except queue.Empty:
                break
        if drained > 0:
            logger.debug("Drained %d frames from raw queue", drained)
