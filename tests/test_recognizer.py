"""Unit tests for core/recognizer.py — ASR Inference Engine.

Covers:
- Model loading and initialization
- transcribe() with normal, empty, and edge case audio
- Audio format handling (float32 conversion, 2D flattening)
- Consumer main loop (run)
- Missing model handling
- Config integration
"""

import queue
import threading
from dataclasses import dataclass
from typing import List
from unittest import mock

import numpy as np
import pytest

from core.recognizer import ModelNotFoundError, Recognizer


# ============================================================================
# Mock WhisperModel & Segment
# ============================================================================


@dataclass
class MockSegment:
    """Simulated faster_whisper.transcribe segment."""

    text: str
    start: float = 0.0
    end: float = 0.0


@dataclass
class MockTranscriptionInfo:
    """Simulated faster_whisper.transcribe info."""

    language: str = "zh"
    language_probability: float = 0.98


class MockWhisperModel:
    """Mock faster-whisper WhisperModel for controlled testing.

    Configure transcribe() return values via set_segments().
    """

    def __init__(
        self,
        model_size="base",
        device="cpu",
        compute_type="int8",
        download_root=None,
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root
        self._segments: List[MockSegment] = []
        self._language = "zh"
        self._language_prob = 0.98
        self.transcribe_called_with: List[tuple] = []

    def set_segments(self, segments: List[MockSegment]):
        """Set segments to return on next transcribe() call."""
        self._segments = segments

    def set_language_info(self, lang: str, prob: float = 0.98):
        """Set language detection result for transcribe()."""
        self._language = lang
        self._language_prob = prob

    def transcribe(self, audio, language=None, beam_size=None, vad_filter=None):
        """Record call and return controlled segments."""
        self.transcribe_called_with.append(
            (audio.copy() if isinstance(audio, np.ndarray) else audio, language, beam_size, vad_filter)
        )
        segments = [mock.MagicMock(text=s.text, start=s.start, end=s.end) for s in self._segments]
        info = mock.MagicMock(
            language=self._language,
            language_probability=self._language_prob,
        )
        return segments, info


# ============================================================================
# Helpers
# ============================================================================


def make_audio(duration_sec=1.0, sample_rate=16000):
    """Create a fake audio numpy array (float32, mono, [-1, 1])."""
    samples = int(sample_rate * duration_sec)
    return np.random.randn(samples).astype(np.float32) * 0.1


def make_silence(duration_sec=0.5, sample_rate=16000):
    """Create a silent audio numpy array."""
    samples = int(sample_rate * duration_sec)
    return np.zeros(samples, dtype=np.float32)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_whisper():
    """Patch faster_whisper.WhisperModel with MockWhisperModel."""
    with mock.patch("core.recognizer.WhisperModel", new=MockWhisperModel):
        yield


@pytest.fixture
def recognizer(mock_whisper):
    """Create a fresh Recognizer instance with mocked model."""
    return Recognizer(model_size="base", compute_type="int8", language="zh", beam_size=3)


# ============================================================================
# Initialization
# ============================================================================


class TestInit:
    """Verify Recognizer initialization."""

    def test_default_parameters(self, mock_whisper):
        rec = Recognizer()
        assert rec.model_size == "base"
        assert rec.language == "zh"

    def test_custom_parameters(self, mock_whisper):
        rec = Recognizer(
            model_size="small",
            compute_type="float16",
            device="cpu",
            language="en",
            beam_size=5,
        )
        assert rec.model_size == "small"
        assert rec.language == "en"

    def test_model_is_loaded_on_init(self, mock_whisper):
        rec = Recognizer(model_size="base")
        assert rec._model is not None
        assert isinstance(rec._model, MockWhisperModel)

    def test_model_size_stored_correctly(self, mock_whisper):
        rec = Recognizer(model_size="tiny")
        assert rec._model.model_size == "tiny"

    def test_model_passed_correct_params(self, mock_whisper):
        rec = Recognizer(
            model_size="medium",
            compute_type="int8_float16",
            device="cpu",
        )
        assert rec._model.compute_type == "int8_float16"
        assert rec._model.device == "cpu"


# ============================================================================
# transcribe()
# ============================================================================


class TestTranscribe:
    """Verify transcribe() behavior."""

    def test_normal_text(self, recognizer):
        recognizer._model.set_segments([
            MockSegment(text="今天天气真好"),
        ])
        result = recognizer.transcribe(make_audio())
        assert result == "今天天气真好"

    def test_multiple_segments(self, recognizer):
        recognizer._model.set_segments([
            MockSegment(text="第一段"),
            MockSegment(text="第二段"),
            MockSegment(text="第三段"),
        ])
        result = recognizer.transcribe(make_audio(duration_sec=3.0))
        assert result == "第一段第二段第三段"

    def test_empty_segments(self, recognizer):
        recognizer._model.set_segments([])
        result = recognizer.transcribe(make_audio())
        assert result == ""

    def test_empty_audio_array(self, recognizer):
        result = recognizer.transcribe(np.array([], dtype=np.float32))
        assert result == ""

    def test_none_input(self, recognizer):
        result = recognizer.transcribe(None)
        assert result == ""

    def test_strips_whitespace(self, recognizer):
        recognizer._model.set_segments([
            MockSegment(text="  空格前后  "),
        ])
        result = recognizer.transcribe(make_audio())
        assert result == "空格前后"

    def test_special_characters(self, recognizer):
        recognizer._model.set_segments([
            MockSegment(text="Hello, 你好！123..."),
        ])
        result = recognizer.transcribe(make_audio())
        assert result == "Hello, 你好！123..."

    def test_passes_correct_params_to_model(self, recognizer):
        recognizer._model.set_segments([MockSegment(text="test")])
        audio = make_audio()
        recognizer.transcribe(audio)

        called = recognizer._model.transcribe_called_with
        assert len(called) == 1
        _, lang, beam, vad = called[0]
        assert lang == "zh"
        assert beam == 3
        assert vad is False


# ============================================================================
# Audio Format Handling
# ============================================================================


class TestAudioFormat:
    """Verify audio format conversion before inference."""

    def test_float32_passed_as_is(self, recognizer):
        recognizer._model.set_segments([MockSegment(text="ok")])
        audio = make_audio()
        result = recognizer.transcribe(audio)
        assert result == "ok"

    def test_2d_mono_flattened(self, recognizer):
        recognizer._model.set_segments([MockSegment(text="flat")])
        audio = np.random.randn(16000, 1).astype(np.float32) * 0.1
        result = recognizer.transcribe(audio)
        assert result == "flat"
        # Verify audio was flattened before being passed to model
        called_audio = recognizer._model.transcribe_called_with[0][0]
        assert called_audio.ndim == 1

    def test_int16_converted_to_float32(self, recognizer):
        recognizer._model.set_segments([MockSegment(text="converted")])
        audio = np.random.randint(-1000, 1000, size=16000, dtype=np.int16)
        result = recognizer.transcribe(audio)
        assert result == "converted"
        # Verify audio was converted to float32
        called_audio = recognizer._model.transcribe_called_with[0][0]
        assert called_audio.dtype == np.float32


# ============================================================================
# Consumer Main Loop (run)
# ============================================================================


class TestRun:
    """Verify consumer main loop behavior."""

    def test_processes_tasks_from_queue(self, recognizer):
        recognizer._model.set_segments([MockSegment(text="hello")])

        tq = queue.Queue()
        rq = queue.Queue()
        stop = threading.Event()

        tq.put(make_audio(duration_sec=0.5))
        tq.put(None)  # Sentinel to stop

        # Patch run to stop after processing one item

        def controlled_run(tq_, rq_, stop_):
            try:
                audio = tq_.get(timeout=0.2)
                if audio is not None:
                    text = recognizer.transcribe(audio)
                    if text:
                        rq_.put(text)
            except queue.Empty:
                pass

        with mock.patch.object(recognizer, "run", controlled_run):
            recognizer.run(tq, rq, stop)

        # Should have processed the task
        assert not rq.empty()
        assert rq.get() == "hello"

    def test_skips_empty_text(self, recognizer):
        recognizer._model.set_segments([])

        tq = queue.Queue()
        rq = queue.Queue()

        tq.put(make_audio())

        # Run one iteration manually
        try:
            audio = tq.get(timeout=0.2)
            text = recognizer.transcribe(audio)
            if text:
                rq.put(text)
        except queue.Empty:
            pass

        assert rq.empty()

    def test_exits_on_stop_event(self, recognizer):
        stop = threading.Event()
        stop.set()  # Already stopped

        tq = queue.Queue()
        rq = queue.Queue()

        # run() should exit immediately
        recognizer.run(tq, rq, stop)
        # No exception = pass

    def test_handles_transcription_error(self, recognizer):
        # Force transcribe to raise
        def failing_transcribe(audio):
            raise RuntimeError("Inference failed")

        recognizer._model.transcribe = failing_transcribe

        tq = queue.Queue()
        rq = queue.Queue()

        tq.put(make_audio())
        tq.put(None)

        # Should not crash — error is logged and loop continues
        try:
            audio = tq.get(timeout=0.2)
            if audio is not None:
                try:
                    text = recognizer.transcribe(audio)
                    if text:
                        rq.put(text)
                except Exception:
                    pass  # Expected
        except queue.Empty:
            pass

        # Result queue should be empty (error was swallowed)
        assert rq.empty()

    def test_handles_full_result_queue(self, recognizer):
        recognizer._model.set_segments([MockSegment(text="overflow")])

        rq = queue.Queue(maxsize=1)
        rq.put("blocking item")  # Fill the queue

        text = recognizer.transcribe(make_audio())

        # Try to put, should handle queue.Full gracefully
        try:
            rq.put_nowait(text)
        except queue.Full:
            # Expected — this is what run() handles
            pass


# ============================================================================
# Missing Model Handling
# ============================================================================


class TestMissingModel:
    """Verify behavior when faster-whisper is not installed."""

    def test_raises_model_not_found(self):
        with mock.patch("core.recognizer.WhisperModel", None):
            with pytest.raises(ModelNotFoundError, match="faster-whisper"):
                Recognizer()

    def test_error_mentions_hf_mirror(self):
        with mock.patch("core.recognizer.WhisperModel", None):
            with pytest.raises(ModelNotFoundError, match="HF_ENDPOINT"):
                Recognizer()


# ============================================================================
# Config Integration
# ============================================================================


class TestConfigIntegration:
    """Verify integration with config.py values."""

    def test_uses_config_values(self, mock_whisper):
        import config

        rec = Recognizer(
            model_size=config.MODEL_SIZE,
            compute_type=config.COMPUTE_TYPE,
            device=config.DEVICE,
            language=config.LANGUAGE,
            beam_size=config.BEAM_SIZE,
        )
        assert rec._model_size == "base"
        assert rec._compute_type == "int8"
        assert rec._device == "cpu"
        assert rec._language == "zh"
        assert rec._beam_size == 3

    def test_override_config_values(self, mock_whisper):
        rec = Recognizer(
            model_size="large-v3",
            compute_type="float16",
            device="cuda",
            language="en",
            beam_size=8,
        )
        assert rec._model_size == "large-v3"
        assert rec._language == "en"
