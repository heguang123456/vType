"""
Voice Activity Detection & Silence Slicing Module (Producer Thread - Second Half)
=================================================================================
Consumes raw audio from AudioCapture.raw_queue, runs webrtcvad state machine,
and emits complete speech segments to the ASR task_queue.

Data Flow:
    raw_queue (AudioCapture) → sliding window → webrtcvad.is_speech()
    → state machine (LISTENING ↔ RECORDING) → silence slicing
    → merged NumPy array → task_queue (Recognizer)

State Machine:
    LISTENING ──(speech detected)──► RECORDING
        ▲                              │
        └──(slice emitted)─────────────┘

Recording Modes:
    - 'vad': Auto-slicing on sustained silence (SILENCE_FRAME_LIMIT frames).
             Short pauses are debounced; only consecutive silence triggers slice.
    - 'push_to_talk': External start/stop control via start_recording() /
             stop_recording(). On stop, the entire buffer is emitted as one slice.
             VAD is bypassed — audio is always buffered during RECORDING state.
"""

import logging
import queue
import threading
from enum import Enum, auto
from typing import List

import numpy as np

try:
    import webrtcvad
except ImportError:
    # Fallback: try webrtcvad_wheels
    try:
        import webrtcvad_wheels as webrtcvad  # type: ignore[no-redef]
    except ImportError:
        raise ImportError(
            "Neither 'webrtcvad' nor 'webrtcvad-wheels' is installed. "
            "Install with: pip install webrtcvad-wheels"
        )

logger = logging.getLogger(__name__)


# ============================================================================
# State Machine
# ============================================================================


class DetectorState(Enum):
    """Voice detector state machine states."""

    LISTENING = auto()  # Waiting for speech to start
    RECORDING = auto()  # Actively capturing speech frames


# ============================================================================
# VoiceDetector
# ============================================================================


class VoiceDetector:
    """Voice activity detector with silence-based slicing.

    Consumes raw audio frames from the audio capture queue and emits
    complete speech segments after detecting a sustained silence period.

    Thread Safety:
        - run() runs on its own thread (the producer thread).
        - raw_queue and task_queue are thread-safe.
        - stop_event is a threading.Event for cross-thread signaling.

    Example:
        >>> vad = VoiceDetector(sample_rate=16000, frame_duration_ms=20)
        >>> # In a separate thread:
        >>> vad.run(raw_queue, task_queue, stop_event)
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_duration_ms: int = 20,
        aggressiveness: int = 3,
        silence_frame_limit: int = 40,
        record_mode: str = "vad",
    ) -> None:
        """Initialize the voice detector.

        Args:
            sample_rate: Audio sample rate (must be 8000/16000/32000/48000).
            frame_duration_ms: VAD frame duration (10, 20, or 30 ms).
            aggressiveness: VAD sensitivity (0=least, 3=most aggressive).
            silence_frame_limit: Consecutive silent frames before slicing.
            record_mode: 'vad' for auto-slicing, 'push_to_talk' for
                         manual start/stop recording.
        """
        self._sample_rate = sample_rate
        self._frame_duration_ms = frame_duration_ms
        self._silence_frame_limit = silence_frame_limit
        self._record_mode = record_mode

        # Guard against webrtcvad being unavailable (e.g., set to None at runtime)
        if webrtcvad is None:
            raise ImportError(
                "Neither 'webrtcvad' nor 'webrtcvad-wheels' is installed. "
                "Install with: pip install webrtcvad-wheels"
            )

        # Initialize the WebRTC VAD engine
        self._vad = webrtcvad.Vad(aggressiveness)

        # State machine
        self._state = DetectorState.LISTENING

        # Accumulated speech frames during RECORDING
        # Each frame is raw bytes (int16, 320 samples × 2 bytes = 640 bytes)
        self._frame_buffer: List[bytes] = []

        # Counter for consecutive silent frames
        self._silence_count = 0

        # Push-to-talk control
        self._recording_requested = threading.Event()

        # Statistics (for debugging / monitoring)
        self._total_slices = 0
        self._total_speech_frames = 0

        logger.info(
            "语音检测器已初始化: 采样率=%d, 帧时长=%dms, "
            "攻击性=%d, 静音限制=%d 帧, 录制模式=%s",
            sample_rate,
            frame_duration_ms,
            aggressiveness,
            silence_frame_limit,
            record_mode,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> DetectorState:
        """Current detector state (LISTENING or RECORDING)."""
        return self._state

    @property
    def total_slices(self) -> int:
        """Total number of speech slices emitted since start."""
        return self._total_slices

    @property
    def record_mode(self) -> str:
        """Current recording mode ('vad' or 'push_to_talk')."""
        return self._record_mode

    def start_recording(self) -> None:
        """Start recording in push_to_talk mode.

        Switches state to RECORDING and begins buffering audio frames.
        No-op if already in RECORDING state.
        """
        if self._record_mode != "push_to_talk":
            logger.warning("start_recording() 仅在 push_to_talk 模式下有效")
            return
        if self._state == DetectorState.RECORDING:
            return
        self._state = DetectorState.RECORDING
        self._frame_buffer.clear()
        self._silence_count = 0
        self._recording_requested.set()
        logger.info("按键录制已开始 → 录制中")

    def stop_recording(self, task_queue: queue.Queue) -> None:
        """Stop recording in push_to_talk mode and emit the buffered slice.

        Args:
            task_queue: Queue to push the merged audio slice to.
        """
        if self._record_mode != "push_to_talk":
            logger.warning("stop_recording() 仅在 push_to_talk 模式下有效")
            return
        if self._state != DetectorState.RECORDING:
            return
        self._emit_slice(task_queue)
        self._state = DetectorState.LISTENING
        self._frame_buffer.clear()
        self._silence_count = 0
        self._recording_requested.clear()
        logger.debug("按键录制已停止 → 监听中")

    def run(
        self,
        raw_queue: queue.Queue,
        task_queue: queue.Queue,
        stop_event: threading.Event,
    ) -> None:
        """Main detector loop. Runs in producer thread.

        Continuously reads raw audio frames from raw_queue, processes them
        through the VAD state machine, and emits speech slices to task_queue.

        In 'push_to_talk' mode, audio frames are always buffered during
        RECORDING state (started by start_recording()), and the buffer is
        emitted when stop_recording() is called.

        Args:
            raw_queue: Queue of raw numpy.ndarray from AudioCapture.
            task_queue: Queue to push complete speech segments to.
            stop_event: Signal to gracefully exit the loop.
        """
        logger.info("检测器循环已启动（状态=%s, 模式=%s）", self._state.name, self._record_mode)

        while not stop_event.is_set():
            try:
                # Block with timeout so we can check stop_event periodically
                audio = raw_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if self._record_mode == "push_to_talk":
                self._process_audio_ptt(audio, task_queue)
            else:
                # Process this audio chunk through the state machine
                self._process_audio(audio, task_queue)

        # Flush any remaining speech in the buffer on exit
        if self._frame_buffer:
            self._emit_slice(task_queue)

        logger.info(
            "检测器循环已停止。总切片数: %d, 语音帧: %d",
            self._total_slices,
            self._total_speech_frames,
        )

    # ------------------------------------------------------------------
    # Audio Processing Pipeline
    # ------------------------------------------------------------------

    def _process_audio(
        self,
        audio: np.ndarray,
        task_queue: queue.Queue,
    ) -> None:
        """Process one raw audio chunk through the VAD state machine.

        Used in 'vad' mode only.

        Data Flow:
            audio (numpy array) → split into 20ms frames → VAD per frame
            → state machine → accumulate or emit slice

        Args:
            audio: Raw audio data from the microphone (numpy.ndarray).
            task_queue: Queue to push slices to.
        """
        # Split into VAD-sized frames (20ms each)
        frames = self._split_frames(audio)

        for frame_bytes in frames:
            is_speech = self._is_speech(frame_bytes)

            if self._state == DetectorState.LISTENING:
                self._handle_listening(is_speech, frame_bytes)
            elif self._state == DetectorState.RECORDING:
                self._handle_recording(is_speech, frame_bytes, task_queue)

    def _process_audio_ptt(
        self,
        audio: np.ndarray,
        task_queue: queue.Queue,
    ) -> None:
        """Process one raw audio chunk in push_to_talk mode.

        When in RECORDING state (started by start_recording()), all frames
        are buffered regardless of VAD result. When in LISTENING state,
        frames are discarded.

        Args:
            audio: Raw audio data from the microphone (numpy.ndarray).
            task_queue: Queue to push slices to (used only on stop).
        """
        if self._state != DetectorState.RECORDING:
            return

        # Split into frames and buffer them all
        frames = self._split_frames(audio)
        for frame_bytes in frames:
            self._frame_buffer.append(frame_bytes)

    def _split_frames(self, audio: np.ndarray) -> List[bytes]:
        """Split a raw audio chunk into VAD-compatible frames.

        Each frame is 20ms (320 samples × 2 bytes = 640 bytes for int16).

        Args:
            audio: Raw audio as numpy array.

        Returns:
            List of raw byte frames suitable for webrtcvad.is_speech().
        """
        frames: List[bytes] = []

        # Ensure int16 format for VAD
        if audio.dtype != np.int16:
            # Convert float32 [-1, 1] → int16 [-32768, 32767]
            audio_i16 = (audio * 32767).astype(np.int16)
        else:
            audio_i16 = audio

        # Calculate frame size
        # For int16: each sample is 2 bytes
        frame_samples = self._sample_rate * self._frame_duration_ms // 1000
        frame_bytes_count = frame_samples * 2  # int16 = 2 bytes per sample

        # Convert entire chunk to bytes and split
        audio_bytes = audio_i16.tobytes()

        for i in range(0, len(audio_bytes), frame_bytes_count):
            frame = audio_bytes[i : i + frame_bytes_count]
            # Only yield complete frames
            if len(frame) == frame_bytes_count:
                frames.append(frame)

        return frames

    def _is_speech(self, frame_bytes: bytes) -> bool:
        """Check if a raw audio frame contains speech.

        Args:
            frame_bytes: Raw int16 bytes for one VAD frame.

        Returns:
            True if speech detected, False if silence.
        """
        return self._vad.is_speech(frame_bytes, self._sample_rate)

    # ------------------------------------------------------------------
    # State Machine Handlers
    # ------------------------------------------------------------------

    def _handle_listening(self, is_speech: bool, frame_bytes: bytes) -> None:
        """Handle LISTENING state: detect speech onset.

        State Transition:
            LISTENING + speech detected → RECORDING (start buffering)
            LISTENING + silence → stay in LISTENING

        Args:
            is_speech: Whether the current frame contains speech.
            frame_bytes: Raw frame bytes (added to buffer on speech).
        """
        if is_speech:
            # Speech detected! Switch to RECORDING and start buffering
            self._state = DetectorState.RECORDING
            self._frame_buffer.clear()
            self._silence_count = 0
            self._frame_buffer.append(frame_bytes)
            logger.debug("监听中 → 录制中（检测到语音）")

    def _handle_recording(
        self,
        is_speech: bool,
        frame_bytes: bytes,
        task_queue: queue.Queue,
    ) -> None:
        """Handle RECORDING state: accumulate frames and detect silence.

        State Transition:
            RECORDING + speech → reset silence counter, buffer frame
            RECORDING + silence < limit → increment counter, buffer frame (debounce)
            RECORDING + silence >= limit → emit slice → LISTENING

        The debounce mechanism ensures short pauses during speech are preserved
        rather than fragmenting the sentence across multiple slices.

        Args:
            is_speech: Whether the current frame contains speech.
            frame_bytes: Raw frame bytes.
            task_queue: Queue to push completed slices to.
        """
        if is_speech:
            # Speech continues — reset silence counter and store frame
            self._silence_count = 0
            self._frame_buffer.append(frame_bytes)
            self._total_speech_frames += 1
        else:
            # Silence detected
            self._silence_count += 1

            if self._silence_count >= self._silence_frame_limit:
                # Sustained silence — end of utterance detected
                # Include the silence frames in the slice
                # (last few frames of silence help boundaries)
                self._emit_slice(task_queue)

                # Reset for next utterance
                self._state = DetectorState.LISTENING
                self._frame_buffer.clear()
                self._silence_count = 0
                logger.debug("录制中 → 监听中（达到静音阈值）")
            else:
                # Short silence — keep in buffer (debounce: might be a pause)
                self._frame_buffer.append(frame_bytes)

    def _emit_slice(self, task_queue: queue.Queue) -> None:
        """Merge buffered frames into a single audio array and push to task_queue.

        Converts raw int16 bytes back to float32 numpy array for Whisper input.

        Data Flow:
            frame_buffer (List[bytes]) → merge → np.ndarray(float32) → task_queue

        Args:
            task_queue: Queue to push the merged audio to.
        """
        if not self._frame_buffer:
            return

        # Merge all buffered frames into a single bytes object
        merged_bytes = b"".join(self._frame_buffer)

        # Convert to int16 numpy array
        audio_i16 = np.frombuffer(merged_bytes, dtype=np.int16)

        # Convert to float32 and normalize to [-1, 1] for Whisper
        audio_f32 = audio_i16.astype(np.float32) / 32768.0

        self._total_slices += 1

        try:
            task_queue.put_nowait(audio_f32)
        except queue.Full:
            # ASR thread is falling behind — drop the oldest task
            logger.warning("任务队列已满，丢弃语音片段 #%d", self._total_slices)
            # Try to make room and retry
            try:
                task_queue.get_nowait()
                task_queue.put_nowait(audio_f32)
            except queue.Empty:
                pass

        logger.debug(
            "发送片段 #%d: %d 帧, %.2f 秒音频",
            self._total_slices,
            len(self._frame_buffer),
            len(audio_f32) / self._sample_rate,
        )
