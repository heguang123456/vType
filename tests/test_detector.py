"""Unit tests for core/detector.py — Voice Activity Detection & Silence Slicing.

Covers:
- State machine transitions (LISTENING ↔ RECORDING)
- Silence slicing with SILENCE_FRAME_LIMIT
- Debounce: short silences during speech are preserved
- Frame splitting algorithm (20ms sliding window)
- Audio merging (bytes → int16 → float32 normalization)
- Queue interaction (raw_queue → task_queue)
- Graceful shutdown via stop_event
- VAD mock control
"""

import queue
import struct
import threading
from unittest import mock

import numpy as np
import pytest

from core.detector import DetectorState, VoiceDetector


# ============================================================================
# Mock VAD
# ============================================================================


class MockVad:
    """Mock VAD that returns controlled speech/no-speech values."""

    def __init__(self, aggressiveness=3):
        self.aggressiveness = aggressiveness
        self._responses: list = []
        self._call_count = 0

    def set_responses(self, responses: list):
        """Set a sequence of bool responses for consecutive is_speech() calls."""
        self._responses = responses
        self._call_count = 0

    def is_speech(self, frame_bytes, sample_rate):
        if self._call_count < len(self._responses):
            result = self._responses[self._call_count]
            self._call_count += 1
            return result
        return False  # default to silence after sequence exhausted


# ============================================================================
# Helpers
# ============================================================================


def make_raw_frame(duration_ms=20, sample_rate=16000, channels=1):
    """Create a fake raw audio numpy array simulating microphone input."""
    samples = sample_rate * duration_ms // 1000 * channels
    return np.random.randn(samples, channels).astype(np.float32)


def make_silence_frame(duration_ms=20, sample_rate=16000, channels=1):
    """Create a silent audio frame."""
    samples = sample_rate * duration_ms // 1000 * channels
    return np.zeros((samples, channels), dtype=np.float32)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_vad_class():
    """Patch webrtcvad.Vad with MockVad."""
    with mock.patch("core.detector.webrtcvad.Vad", new=MockVad):
        yield


@pytest.fixture
def detector(mock_vad_class):
    """Create a VoiceDetector with default settings (vad mode)."""
    return VoiceDetector(
        sample_rate=16000,
        frame_duration_ms=20,
        aggressiveness=3,
        silence_frame_limit=40,  # 800ms at 20ms/frame (old default)
    )


# ============================================================================
# Initialization
# ============================================================================


class TestInit:
    """Verify VoiceDetector initialization."""

    def test_initial_state_is_listening(self, detector):
        assert detector.state.name == "LISTENING"
        assert detector.state.value == DetectorState.LISTENING.value

    def test_initial_stats_zero(self, detector):
        assert detector.total_slices == 0

    def test_custom_silence_limit(self, mock_vad_class):
        det = VoiceDetector(silence_frame_limit=20)
        assert det._silence_frame_limit == 20

    def test_missing_webrtcvad(self):
        """Verify clean ImportError when webrtcvad is unavailable.

        When core.detector.webrtcvad is None, VoiceDetector.__init__ should
        raise a clear ImportError instead of a cryptic AttributeError.
        """
        import core.detector as det_mod

        saved = det_mod.webrtcvad
        try:
            det_mod.webrtcvad = None
            with pytest.raises(ImportError, match="webrtcvad"):
                det_mod.VoiceDetector()
        finally:
            det_mod.webrtcvad = saved


# ============================================================================
# Frame Splitting
# ============================================================================


class TestSplitFrames:
    """Verify the 20ms sliding window algorithm."""

    def test_split_20ms_frame(self, detector):
        """One 20ms frame should produce exactly 1 VAD frame."""
        audio = make_raw_frame(duration_ms=20)
        frames = detector._split_frames(audio)
        assert len(frames) == 1
        # 16000 * 0.02 = 320 samples, int16 = 640 bytes
        assert len(frames[0]) == 640

    def test_split_40ms_audio(self, detector):
        """40ms should produce 2 frames."""
        audio = make_raw_frame(duration_ms=40)
        frames = detector._split_frames(audio)
        assert len(frames) == 2

    def test_split_100ms_audio(self, detector):
        """100ms should produce 5 frames (100/20=5)."""
        audio = make_raw_frame(duration_ms=100)
        frames = detector._split_frames(audio)
        assert len(frames) == 5

    def test_incomplete_frame_at_end(self, detector):
        """Partial frame at the end should be discarded."""
        # 45ms = 2 complete frames + 5ms partial
        audio = make_raw_frame(duration_ms=45)
        frames = detector._split_frames(audio)
        assert len(frames) == 2  # only 2 complete frames

    def test_frame_bytes_format(self, detector):
        """Each frame should be int16 bytes (640 bytes for 20ms@16kHz)."""
        audio = make_raw_frame(duration_ms=20)
        frames = detector._split_frames(audio)
        assert all(len(f) == 640 for f in frames)

    def test_silence_split(self, detector):
        """Silent audio should still split into correct frames."""
        audio = make_silence_frame(duration_ms=60)
        frames = detector._split_frames(audio)
        assert len(frames) == 3


# ============================================================================
# State Machine: LISTENING → RECORDING
# ============================================================================


class TestListeningToRecording:
    """Verify transition from LISTENING to RECORDING on speech detection."""

    def test_transitions_on_speech(self, detector):
        """First speech frame triggers LISTENING → RECORDING."""
        detector._handle_listening(is_speech=True, frame_bytes=b"x" * 640)
        assert detector.state.name == "RECORDING"
        assert detector.state.value == DetectorState.RECORDING.value

    def test_stays_listening_on_silence(self, detector):
        """Silence frames should keep the state in LISTENING."""
        detector._handle_listening(is_speech=False, frame_bytes=b"x" * 640)
        assert detector.state.name == "LISTENING"
        assert detector.state.value == DetectorState.LISTENING.value

    def test_buffer_cleared_on_transition(self, detector):
        """Buffer should be cleared when entering RECORDING."""
        # Pre-populate buffer
        detector._frame_buffer = [b"old data"]
        detector._handle_listening(is_speech=True, frame_bytes=b"new" * 320)
        assert len(detector._frame_buffer) == 1
        assert detector._frame_buffer[0] == b"new" * 320

    def test_silence_count_reset_on_transition(self, detector):
        """Silence count should reset on entering RECORDING."""
        detector._silence_count = 10
        detector._handle_listening(is_speech=True, frame_bytes=b"x" * 640)
        assert detector._silence_count == 0


# ============================================================================
# State Machine: RECORDING → LISTENING (Silence Slicing)
# ============================================================================


class TestRecordingToListening:
    """Verify transition from RECORDING to LISTENING on sustained silence."""

    def setup_method(self):
        """Put detector in RECORDING state before each test."""
        self.task_queue = queue.Queue()
        self.detector = VoiceDetector(silence_frame_limit=5)  # smaller limit for testing
        self.detector._state = DetectorState.RECORDING

    def test_speech_resets_silence_count(self):
        """After speech, silence counter should be 0."""
        self.detector._silence_count = 3
        self.detector._handle_recording(
            is_speech=True, frame_bytes=b"x" * 640, task_queue=self.task_queue
        )
        assert self.detector._silence_count == 0

    def test_short_silence_accumulates(self):
        """Short silences increment counter and buffer frame."""
        self.detector._silence_count = 0
        self.detector._handle_recording(
            is_speech=False, frame_bytes=b"x" * 640, task_queue=self.task_queue
        )
        assert self.detector._silence_count == 1
        assert len(self.detector._frame_buffer) == 1

    def test_silence_limit_triggers_slice(self):
        """Exact silence_frame_limit consecutive silences should trigger slice."""
        start_slices = self.detector._total_slices
        # Must have at least 1 frame in buffer for _emit_slice to emit
        self.detector._frame_buffer = [b"x" * 640]
        self.detector._silence_count = 4  # one away from limit=5

        self.detector._handle_recording(
            is_speech=False, frame_bytes=b"x" * 640, task_queue=self.task_queue
        )

        # Should have emitted a slice
        assert self.detector.state.name == "LISTENING"
        assert self.detector.state.value == DetectorState.LISTENING.value
        assert self.detector._total_slices == start_slices + 1
        assert self.detector._silence_count == 0

    def test_silence_limit_puts_data_in_queue(self):
        """Slice should push merged audio to task_queue."""
        # Add some frames to buffer first
        self.detector._frame_buffer = [b"a" * 640, b"b" * 640]
        self.detector._silence_count = 4  # one away from limit=5

        self.detector._handle_recording(
            is_speech=False, frame_bytes=b"c" * 640, task_queue=self.task_queue
        )

        assert not self.task_queue.empty()
        audio = self.task_queue.get(timeout=0.1)
        assert isinstance(audio, np.ndarray)
        assert audio.dtype == np.float32

    def test_debounce_mixed(self):
        """Speech → short silence → speech should not trigger slice."""
        det = self.detector
        tq = self.task_queue

        # Speech
        det._handle_recording(True, b"s1" * 320, tq)
        assert det._silence_count == 0

        # Short silence (2 frames, below limit of 5)
        det._handle_recording(False, b"sl" * 320, tq)
        det._handle_recording(False, b"sl" * 320, tq)
        assert det._silence_count == 2
        assert det.state.name == "RECORDING"  # still recording

        # Speech resumes
        det._handle_recording(True, b"s2" * 320, tq)
        assert det._silence_count == 0  # counter reset
        assert det.state.name == "RECORDING"  # still recording

        # Buffer should have all 4 frames (2 speech + 2 silence)
        assert len(det._frame_buffer) == 4

    def test_debounce_buffer_preserves_intermittent_silence(self):
        """Short silences during speech are NOT discarded from buffer."""
        det = self.detector
        tq = self.task_queue

        det._handle_recording(True, b"speech1" + b"\x00" * 632, tq)
        det._handle_recording(False, b"pause1" + b"\x00" * 634, tq)
        det._handle_recording(True, b"speech2" + b"\x00" * 632, tq)

        assert len(det._frame_buffer) == 3


# ============================================================================
# Emit Slice (Audio Merging)
# ============================================================================


class TestEmitSlice:
    """Verify audio merging and queue interaction."""

    def test_emit_creates_float32_array(self):
        det = VoiceDetector()
        det._frame_buffer = [b"a" * 640, b"b" * 640]
        tq = queue.Queue()

        det._emit_slice(tq)

        audio = tq.get(timeout=0.1)
        assert audio.dtype == np.float32

    def test_emit_normalizes_to_range(self):
        """Output should be normalized to roughly [-1, 1]."""
        det = VoiceDetector()
        # Create a frame with known int16 values
        frame = struct.pack("<" + "h" * 320, *([16000] * 320))
        det._frame_buffer = [frame]
        tq = queue.Queue()

        det._emit_slice(tq)

        audio = tq.get(timeout=0.1)
        # 16000 / 32768 ≈ 0.488
        assert np.allclose(audio, 16000 / 32768, atol=1e-3)

    def test_emit_handles_empty_buffer(self):
        """Empty buffer should be a no-op."""
        det = VoiceDetector()
        tq = queue.Queue()

        det._emit_slice(tq)
        assert tq.empty()

    def test_emit_increments_slice_counter(self):
        det = VoiceDetector()
        det._frame_buffer = [b"x" * 640]
        tq = queue.Queue()

        assert det._total_slices == 0
        det._emit_slice(tq)
        assert det._total_slices == 1

    def test_emit_handles_full_queue(self):
        """When task_queue is full, drop oldest and retry."""
        det = VoiceDetector()
        det._frame_buffer = [b"x" * 640]
        tq = queue.Queue(maxsize=1)
        tq.put_nowait(np.zeros(100))  # fill it

        det._emit_slice(tq)
        # Should not raise — either dropped or replaced
        result = tq.get(timeout=0.1)
        assert result is not None

    def test_emit_correct_audio_length(self):
        """Merged audio should have the correct number of samples."""
        det = VoiceDetector()
        # 5 frames × 320 samples = 1600 samples
        det._frame_buffer = [b"x" * 640] * 5
        tq = queue.Queue()

        det._emit_slice(tq)
        audio = tq.get(timeout=0.1)
        assert len(audio) == 1600  # 5 × 320


# ============================================================================
# Full Run Loop (Integration)
# ============================================================================


class TestRunLoop:
    """Verify the run() method processes audio from queue."""

    def test_processes_audio_from_queue(self, mock_vad_class):
        """Basic smoke test: run() processes frames and emits slices."""
        import time

        raw_queue = queue.Queue()
        task_queue = queue.Queue()
        stop_event = threading.Event()

        # Put speech audio into the queue
        audio = make_raw_frame(duration_ms=2000)  # 2 seconds = 100 frames

        # Configure mock VAD: speech for 20 frames, then silence to trigger slice
        det = VoiceDetector(silence_frame_limit=5)
        mock_vad = det._vad
        # Speech for 20 frames, then silence for 80 → should emit a slice
        responses = [True] * 20 + [False] * 80
        mock_vad.set_responses(responses)

        raw_queue.put(audio)

        # Run detector in a thread so we can signal stop after processing
        def run_detector():
            det.run(raw_queue, task_queue, stop_event)

        thread = threading.Thread(target=run_detector, daemon=True)
        thread.start()

        # Wait briefly for processing, then signal stop
        time.sleep(0.5)
        stop_event.set()
        thread.join(timeout=2.0)

        # Should have emitted at least one slice
        assert det.total_slices >= 1

    def test_exits_on_stop_event(self, mock_vad_class):
        """stop_event.set() should cause run() to exit cleanly."""
        raw_queue = queue.Queue()
        task_queue = queue.Queue()
        stop_event = threading.Event()
        stop_event.set()  # immediately signal stop

        det = VoiceDetector()
        det.run(raw_queue, task_queue, stop_event)
        # Should exit without error

    def test_flushes_buffer_on_stop(self, mock_vad_class):
        """On stop, any buffered speech should be emitted."""
        raw_queue = queue.Queue()
        task_queue = queue.Queue()
        stop_event = threading.Event()

        det = VoiceDetector()
        # Manually set state to RECORDING with buffered frames
        det._state = DetectorState.RECORDING
        det._frame_buffer = [b"x" * 640] * 10
        stop_event.set()

        det.run(raw_queue, task_queue, stop_event)

        # Buffer should be flushed as a slice
        assert not task_queue.empty()

    def test_handles_empty_queue_timeout(self, mock_vad_class):
        """Empty raw_queue should not block (timeout mechanism)."""
        raw_queue = queue.Queue()
        task_queue = queue.Queue()
        stop_event = threading.Event()

        det = VoiceDetector()

        # Set stop after a brief moment (simulated by immediate stop)
        stop_event.set()

        det.run(raw_queue, task_queue, stop_event)
        # Should exit without error


# ============================================================================
# Process Audio Pipeline
# ============================================================================


class TestProcessAudio:
    """Verify _process_audio end-to-end pipeline."""

    def test_full_speech_to_silence_cycle(self, mock_vad_class):
        """Simulate: speech → silence → slice."""
        det = VoiceDetector(silence_frame_limit=3)
        tq = queue.Queue()

        # Create mock VAD that returns speech for 5 frames then silence
        mock_vad = det._vad
        mock_vad.set_responses([True] * 5 + [False] * 10)

        audio = make_raw_frame(duration_ms=300)  # 15 frames

        det._process_audio(audio, tq)

        # Should have emitted at least one slice (from 5 speech + ≥3 silence)
        assert det._total_slices >= 1


# ============================================================================
# Push-to-Talk Mode
# ============================================================================


class TestPushToTalkMode:
    """Verify push_to_talk recording mode behavior."""

    def test_ptt_init(self, mock_vad_class):
        """Push-to-talk detector initializes with correct mode."""
        det = VoiceDetector(record_mode="push_to_talk")
        assert det.record_mode == "push_to_talk"
        assert det.state.name == "LISTENING"

    def test_vad_mode_default(self, mock_vad_class):
        """Default mode is vad."""
        det = VoiceDetector()
        assert det.record_mode == "vad"

    def test_start_recording_transitions_to_recording(self, mock_vad_class):
        """start_recording() transitions LISTENING → RECORDING."""
        det = VoiceDetector(record_mode="push_to_talk")
        det.start_recording()
        assert det.state.name == "RECORDING"

    def test_start_recording_idempotent(self, mock_vad_class):
        """Double start_recording() is a no-op."""
        det = VoiceDetector(record_mode="push_to_talk")
        det.start_recording()
        det.start_recording()
        assert det.state.name == "RECORDING"

    def test_start_recording_warns_in_vad_mode(self, mock_vad_class):
        """start_recording() logs warning in vad mode."""
        det = VoiceDetector(record_mode="vad")
        with mock.patch("core.detector.logger.warning") as mock_warn:
            det.start_recording()
        mock_warn.assert_called_once()
        assert det.state.name == "LISTENING"

    def test_stop_recording_emits_slice(self, mock_vad_class):
        """stop_recording() emits buffered audio and returns to LISTENING."""
        det = VoiceDetector(record_mode="push_to_talk")
        det.start_recording()
        # Buffer some audio manually
        det._frame_buffer = [b"x" * 640] * 5
        tq = queue.Queue()
        det.stop_recording(tq)
        assert det.state.name == "LISTENING"
        assert det._total_slices == 1
        audio = tq.get(timeout=0.1)
        assert isinstance(audio, np.ndarray)
        assert audio.dtype == np.float32

    def test_stop_recording_clears_buffer(self, mock_vad_class):
        """After stop_recording(), buffer and silence count are reset."""
        det = VoiceDetector(record_mode="push_to_talk")
        det.start_recording()
        det._frame_buffer = [b"x" * 640] * 3
        det._silence_count = 5
        tq = queue.Queue()
        det.stop_recording(tq)
        assert len(det._frame_buffer) == 0
        assert det._silence_count == 0

    def test_stop_recording_warns_in_vad_mode(self, mock_vad_class):
        """stop_recording() logs warning in vad mode."""
        det = VoiceDetector(record_mode="vad")
        with mock.patch("core.detector.logger.warning") as mock_warn:
            det.stop_recording(queue.Queue())
        mock_warn.assert_called_once()

    def test_ptt_buffers_all_frames_in_recording(self, mock_vad_class):
        """In PTT RECORDING state, all frames are buffered (no VAD filtering)."""
        det = VoiceDetector(record_mode="push_to_talk")
        det.start_recording()
        tq = queue.Queue()
        audio = make_raw_frame(duration_ms=100)  # 5 frames
        det._process_audio_ptt(audio, tq)
        assert len(det._frame_buffer) == 5

    def test_ptt_discards_frames_in_listening(self, mock_vad_class):
        """In PTT LISTENING state, frames are discarded."""
        det = VoiceDetector(record_mode="push_to_talk")
        tq = queue.Queue()
        audio = make_raw_frame(duration_ms=100)  # 5 frames
        det._process_audio_ptt(audio, tq)
        assert len(det._frame_buffer) == 0

    def test_ptt_full_cycle(self, mock_vad_class):
        """Full PTT cycle: start → buffer → stop → emit."""
        det = VoiceDetector(record_mode="push_to_talk")
        tq = queue.Queue()

        # Start recording
        det.start_recording()
        assert det.state.name == "RECORDING"

        # Feed audio
        audio = make_raw_frame(duration_ms=200)  # 10 frames
        det._process_audio_ptt(audio, tq)
        assert len(det._frame_buffer) == 10

        # Stop recording — should emit entire buffer
        det.stop_recording(tq)
        assert det.state.name == "LISTENING"
        assert det._total_slices == 1
        result = tq.get(timeout=0.1)
        assert len(result) == 10 * 320  # 10 frames × 320 samples
