"""
Core Manager — Glue layer connecting all vType submodules.
===========================================================
Creates submodule instances, manages 3-level queue pipeline,
coordinates multi-thread lifecycle, and exposes a unified
start/stop/pause/resume API.

Data Flow:
    AudioCapture (PortAudio) → raw_queue (internal)
    → VoiceDetector [Thread A] → task_queue
    → Recognizer [Thread B] → result_queue
    → TypeWriter [Thread C] → keyboard output

Lifecycle State Machine:
    IDLE ─start()─► RUNNING ─pause()─► PAUSED
                      ▲                  │
                      └──resume()────────┘
                      │                  │
                      ▼                  ▼
                   STOPPING ──stop()──► IDLE

Thread Topology:
    PortAudio callback thread (sounddevice internal)
    Thread A: detector.run(raw_queue, task_queue, stop_event)
    Thread B: recognizer.run(task_queue, result_queue, stop_event)
    Thread C: typer.run(result_queue, stop_event)
"""

import logging
import queue
import threading
from enum import Enum, auto
from typing import Any, Dict, Optional

import config
from core.audio import AudioCapture
from core.detector import VoiceDetector
from core.recognizer import Recognizer
from core.typer import TypeWriter

logger = logging.getLogger(__name__)


# ============================================================================
# Status Enum
# ============================================================================


class ManagerStatus(Enum):
    """Manager lifecycle states."""

    IDLE = auto()       # Not started or fully stopped
    RUNNING = auto()    # Actively capturing and processing
    PAUSED = auto()     # Audio capture paused, threads alive
    STOPPING = auto()   # In graceful shutdown


# ============================================================================
# CoreManager
# ============================================================================


class CoreManager:
    """Central orchestrator for the vType voice input pipeline.

    Creates all submodules, manages queues and threads, and exposes
    a unified control surface for the CLI entry point.

    Full lifecycle:

        >>> mgr = CoreManager(model_size="base", language="zh")
        >>> mgr.status    # ManagerStatus.IDLE
        >>> mgr.start()
        >>> mgr.status    # ManagerStatus.RUNNING
        >>> mgr.pause()   # Audio paused, threads alive
        >>> mgr.resume()  # Audio resumed
        >>> mgr.stop()    # Graceful shutdown, back to IDLE
    """

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the manager with optional config overrides.

        Args:
            **kwargs: Optional keyword arguments to override config
                defaults. Any key from config.py can be passed here
                (e.g. model_size="small", language="en").
        """
        # Merge defaults with caller overrides
        self._cfg: Dict[str, Any] = {
            # Audio
            "sample_rate": kwargs.get("sample_rate", config.SAMPLE_RATE),
            "channels": kwargs.get("channels", config.CHANNELS),
            "block_size": kwargs.get("block_size", config.BLOCK_SIZE),
            "dtype": kwargs.get("dtype", config.DTYPE),
            "device_id": kwargs.get("device_id", None),
            # VAD
            "frame_duration_ms": kwargs.get(
                "frame_duration_ms", config.FRAME_DURATION_MS
            ),
            "vad_aggressiveness": kwargs.get(
                "vad_aggressiveness", config.VAD_AGGRESSIVENESS
            ),
            "silence_frame_limit": kwargs.get(
                "silence_frame_limit", config.SILENCE_FRAME_LIMIT
            ),
            # ASR
            "model_size": kwargs.get("model_size", config.MODEL_SIZE),
            "compute_type": kwargs.get("compute_type", config.COMPUTE_TYPE),
            "device": kwargs.get("device", config.DEVICE),
            "language": kwargs.get("language", config.LANGUAGE),
            "beam_size": kwargs.get("beam_size", config.BEAM_SIZE),
            # Output
            "type_delay": kwargs.get("type_delay", config.TYPE_DELAY),
            "clipboard_fallback": kwargs.get(
                "clipboard_fallback", config.CLIPBOARD_FALLBACK
            ),
            # Queue
            "queue_maxsize": kwargs.get("queue_maxsize", config.QUEUE_MAXSIZE),
        }

        # Submodules (created in start())
        self._audio: Optional[AudioCapture] = None
        self._detector: Optional[VoiceDetector] = None
        self._recognizer: Optional[Recognizer] = None
        self._typer: Optional[TypeWriter] = None

        # Queues (created in start())
        self._task_queue: Optional[queue.Queue] = None    # Detector → Recognizer
        self._result_queue: Optional[queue.Queue] = None  # Recognizer → TypeWriter

        # Threads (created in start())
        self._detector_thread: Optional[threading.Thread] = None
        self._recognizer_thread: Optional[threading.Thread] = None
        self._typer_thread: Optional[threading.Thread] = None

        # Control
        self._stop_event: Optional[threading.Event] = None
        self._status: ManagerStatus = ManagerStatus.IDLE

        logger.info(
            "CoreManager initialized: model=%s, language=%s, device=%s",
            self._cfg["model_size"],
            self._cfg["language"],
            self._cfg["device"],
        )

    # ------------------------------------------------------------------
    # Public API — Status
    # ------------------------------------------------------------------

    @property
    def status(self) -> ManagerStatus:
        """Current manager lifecycle state."""
        return self._status

    @property
    def statistics(self) -> Dict[str, Any]:
        """Aggregate statistics from all submodules.

        Returns a dictionary with keys: status, detector_state,
        detector_slices, audio_running, audio_paused, and
        per-thread alive flags.
        """
        stats: Dict[str, Any] = {
            "status": self._status.name,
        }

        if self._detector is not None:
            stats["detector_state"] = self._detector.state.name
            stats["detector_slices"] = self._detector.total_slices

        if self._audio is not None:
            stats["audio_running"] = self._audio.is_running
            stats["audio_paused"] = self._audio.is_paused

        stats["detector_thread_alive"] = (
            self._detector_thread is not None
            and self._detector_thread.is_alive()
        )
        stats["recognizer_thread_alive"] = (
            self._recognizer_thread is not None
            and self._recognizer_thread.is_alive()
        )
        stats["typer_thread_alive"] = (
            self._typer_thread is not None
            and self._typer_thread.is_alive()
        )

        return stats

    # ------------------------------------------------------------------
    # Public API — Lifecycle Control
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Create submodules, open audio stream, and start worker threads.

        This is the heavy initialization step. It creates all 4 submodules
        (including loading the Whisper model), opens the PortAudio stream,
        and launches 3 background worker threads.

        Must be called from IDLE state. Idempotent: duplicate calls
        while RUNNING or PAUSED log a warning and return safely.

        Raises:
            DeviceNotFoundError: If no suitable microphone is available.
            ModelNotFoundError: If Whisper model fails to load.
        """
        if self._status == ManagerStatus.RUNNING:
            logger.warning(
                "CoreManager.start() called while already RUNNING — ignored"
            )
            return

        if self._status == ManagerStatus.PAUSED:
            logger.warning(
                "CoreManager.start() called while PAUSED — "
                "call resume() instead"
            )
            return

        if self._status == ManagerStatus.STOPPING:
            logger.warning(
                "CoreManager.start() called while STOPPING — "
                "wait for stop() to complete first"
            )
            return

        self._status = ManagerStatus.RUNNING

        try:
            # 1. Create all submodules (order: recognizer first for
            #    early failure on model loading)
            self._create_modules()

            # 2. Create inter-thread communication queues
            self._task_queue = queue.Queue(maxsize=self._cfg["queue_maxsize"])
            self._result_queue = queue.Queue(maxsize=self._cfg["queue_maxsize"])

            # 3. Create shared stop event (all threads check this)
            self._stop_event = threading.Event()
            self._stop_event.clear()

            # 4. Open audio stream (raw_queue is inside AudioCapture)
            self._audio.start()  # type: ignore[union-attr]

            # 5. Launch 3 worker threads
            self._start_threads()

            logger.info(
                "CoreManager started — microphones open, "
                "3 worker threads running"
            )
        except Exception:
            # Rollback: clean up partial state, re-raise
            logger.exception("CoreManager.start() failed — rolling back")
            self._status = ManagerStatus.IDLE
            self._cleanup()
            raise

    def stop(self) -> None:
        """Gracefully shutdown all threads and release resources.

        Stop sequence (5-step graceful exit):
            1. Set status to STOPPING
            2. Signal stop_event → all threads begin exiting
            3. Join detector thread   (timeout 3.0s)
            4. Join recognizer thread (timeout 5.0s, ASR is slower)
            5. Join typer thread      (timeout 3.0s)
            6. Stop AudioCapture stream
            7. Clean up references, return to IDLE

        Safe to call from any state. Idempotent: duplicate calls
        are no-ops when already IDLE.
        """
        if self._status == ManagerStatus.IDLE:
            return

        prev_status = self._status
        self._status = ManagerStatus.STOPPING
        logger.info(
            "CoreManager stopping (prev_status=%s)...", prev_status.name
        )

        try:
            # Step 1: Signal all threads to stop
            if self._stop_event is not None:
                self._stop_event.set()

            # Step 2-4: Join worker threads (ordered by dependency:
            # detector feeds recognizer, recognizer feeds typer)
            self._join_thread(
                self._detector_thread, "detector", timeout=3.0
            )
            self._join_thread(
                self._recognizer_thread, "recognizer", timeout=5.0
            )
            self._join_thread(
                self._typer_thread, "typer", timeout=3.0
            )

            # Step 5: Stop audio capture
            if self._audio is not None:
                try:
                    self._audio.stop()
                except Exception:
                    logger.exception("Error stopping AudioCapture")

            # Step 6: Release all references
            self._cleanup()

        finally:
            self._status = ManagerStatus.IDLE
            logger.info("CoreManager stopped")

    def pause(self) -> None:
        """Pause audio capture without stopping background threads.

        The microphone stream is paused (data discarded in callback),
        but all 3 worker threads remain alive and polling their queues.
        This allows fast resume without re-creating threads or re-loading
        the Whisper model.
        """
        if self._status != ManagerStatus.RUNNING:
            logger.warning(
                "CoreManager.pause() called while status=%s "
                "(expected RUNNING)",
                self._status.name,
            )
            return

        if self._audio is not None:
            self._audio.pause()
        self._status = ManagerStatus.PAUSED
        logger.info("CoreManager paused")

    def resume(self) -> None:
        """Resume audio capture after pause.

        Restores from PAUSED to RUNNING. No-op if already RUNNING.
        """
        if self._status != ManagerStatus.PAUSED:
            logger.warning(
                "CoreManager.resume() called while status=%s "
                "(expected PAUSED)",
                self._status.name,
            )
            return

        if self._audio is not None:
            self._audio.resume()
        self._status = ManagerStatus.RUNNING
        logger.info("CoreManager resumed")

    # ------------------------------------------------------------------
    # Internal: Module Creation
    # ------------------------------------------------------------------

    def _create_modules(self) -> None:
        """Create all 4 submodule instances.

        Creation order:
        1. Recognizer first — model loading is the slowest step (5–15s)
           and the most likely to fail. Failing early avoids creating
           other submodules unnecessarily.
        2. AudioCapture — validates device availability.
        3. VoiceDetector — lightweight, just webrtcvad init.
        4. TypeWriter — lightweight, optional pynput init.
        """
        logger.info("Creating submodules...")

        # 1. Recognizer (heavy: model download/loading)
        self._recognizer = Recognizer(
            model_size=self._cfg["model_size"],
            compute_type=self._cfg["compute_type"],
            device=self._cfg["device"],
            language=self._cfg["language"],
            beam_size=self._cfg["beam_size"],
        )

        # 2. AudioCapture (validates microphone availability)
        self._audio = AudioCapture(
            sample_rate=self._cfg["sample_rate"],
            channels=self._cfg["channels"],
            block_size=self._cfg["block_size"],
            dtype=self._cfg["dtype"],
            device_id=self._cfg["device_id"],
        )

        # 3. VoiceDetector (lightweight VAD engine)
        self._detector = VoiceDetector(
            sample_rate=self._cfg["sample_rate"],
            frame_duration_ms=self._cfg["frame_duration_ms"],
            aggressiveness=self._cfg["vad_aggressiveness"],
            silence_frame_limit=self._cfg["silence_frame_limit"],
        )

        # 4. TypeWriter (keyboard output engine)
        self._typer = TypeWriter(
            type_delay=self._cfg["type_delay"],
            clipboard_fallback=self._cfg["clipboard_fallback"],
        )

        logger.info("All 4 submodules created")

    # ------------------------------------------------------------------
    # Internal: Thread Management
    # ------------------------------------------------------------------

    def _start_threads(self) -> None:
        """Launch all 3 worker threads as daemon threads.

        Thread topology (see module docstring for full data-flow diagram):
        - Thread A: detector.run(raw_queue, task_queue, stop_event)
        - Thread B: recognizer.run(task_queue, result_queue, stop_event)
        - Thread C: typer.run(result_queue, stop_event)

        All threads are daemon=True so they won't block process exit.
        """
        logger.info("Starting worker threads...")

        # Thread A: VoiceDetector — raw_queue → task_queue
        self._detector_thread = threading.Thread(
            target=self._detector.run,  # type: ignore[union-attr]
            args=(
                self._audio.raw_queue,  # type: ignore[union-attr]
                self._task_queue,
                self._stop_event,
            ),
            name="vType-Detector",
            daemon=True,
        )
        self._detector_thread.start()

        # Thread B: Recognizer — task_queue → result_queue
        self._recognizer_thread = threading.Thread(
            target=self._recognizer.run,  # type: ignore[union-attr]
            args=(self._task_queue, self._result_queue, self._stop_event),
            name="vType-Recognizer",
            daemon=True,
        )
        self._recognizer_thread.start()

        # Thread C: TypeWriter — result_queue → keyboard
        self._typer_thread = threading.Thread(
            target=self._typer.run,  # type: ignore[union-attr]
            args=(self._result_queue, self._stop_event),
            name="vType-TypeWriter",
            daemon=True,
        )
        self._typer_thread.start()

        logger.info(
            "Worker threads started: Detector=%s, Recognizer=%s, "
            "TypeWriter=%s",
            self._detector_thread.ident,
            self._recognizer_thread.ident,
            self._typer_thread.ident,
        )

    @staticmethod
    def _join_thread(
        thread: Optional[threading.Thread],
        name: str,
        timeout: float,
    ) -> None:
        """Join a thread with a timeout. Logs a warning on timeout.

        Python threads cannot be forcibly killed, so the timeout is
        a best-effort safety net. After timeout, the thread may still
        be running but will eventually exit when its loop checks
        stop_event.

        Args:
            thread: Thread to join, or None (no-op).
            name: Human-readable name for log messages.
            timeout: Maximum seconds to wait for the thread.
        """
        if thread is None:
            return

        thread.join(timeout=timeout)
        if thread.is_alive():
            logger.warning(
                "%s thread did not exit within %.1fs (continuing shutdown)",
                name,
                timeout,
            )
        else:
            logger.debug("%s thread stopped", name)

    # ------------------------------------------------------------------
    # Internal: Cleanup
    # ------------------------------------------------------------------

    def _cleanup(self) -> None:
        """Release all internal references.

        Sets all submodule, queue, thread, and event references to None.
        Called after stop() to prevent accidental reuse of stale objects.
        """
        self._audio = None
        self._detector = None
        self._recognizer = None
        self._typer = None
        self._task_queue = None
        self._result_queue = None
        self._detector_thread = None
        self._recognizer_thread = None
        self._typer_thread = None
        self._stop_event = None
