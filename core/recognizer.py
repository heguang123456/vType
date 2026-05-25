"""
ASR Inference Engine (Consumer Thread - First Half)
====================================================
Loads faster-whisper model once and transcribes audio segments from
the detector into text. Designed for CPU inference with int8 quantization.

Data Flow:
    task_queue (np.ndarray float32) → Recognizer.transcribe()
    → WhisperModel.transcribe(language, beam_size, initial_prompt, vad_filter=False)
    → segments → merged text → zhconv T2S fallback → result_queue (str)

The model is loaded once in __init__ (heavy, 5-15s) and reused for all
subsequent transcribe() calls.
"""

import logging
import queue
import threading

import numpy as np

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None  # type: ignore[assignment]

try:
    from zhconv import convert as _zhconv_convert
except ImportError:
    _zhconv_convert = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# ============================================================================
# Exceptions
# ============================================================================


class RecognizerError(Exception):
    """Base exception for recognizer errors."""


class ModelNotFoundError(RecognizerError):
    """Whisper model could not be found or downloaded."""


# ============================================================================
# Recognizer
# ============================================================================


class Recognizer:
    """Whisper ASR inference engine.

    Loads the faster-whisper model once at initialization and provides
    transcribe() for repeated inference on audio segments.

    Thread Safety:
        - __init__ loads model (call once from main thread).
        - transcribe() is NOT thread-safe; should be called from a single
          consumer thread.
        - run() provides the standard consumer loop pattern.

    Example:
        >>> rec = Recognizer(model_size="base", compute_type="int8")
        >>> text = rec.transcribe(audio_array)
        >>> # Or in a thread:
        >>> rec.run(task_queue, result_queue, stop_event)
    """

    def __init__(
        self,
        model_size: str = "base",
        compute_type: str = "int8",
        device: str = "cpu",
        language: str = "zh",
        beam_size: int = 3,
        initial_prompt: str = "以下是普通话的句子。",
    ) -> None:
        """Load the WhisperModel. Heavy operation, done once.

        Args:
            model_size: Whisper model size (tiny/base/small/medium/large).
            compute_type: CTranslate2 compute type (int8/int8_float16/float16).
            device: Inference device (cpu/cuda).
            language: Recognition language (zh/en/auto).
            beam_size: Beam search width (1-10).
            initial_prompt: Prompt to guide output style. Use Simplified Chinese
                text to prevent the model from defaulting to Traditional Chinese.

        Raises:
            ModelNotFoundError: If faster-whisper is not installed.
            RuntimeError: If model download fails.
        """
        if WhisperModel is None:
            raise ModelNotFoundError(
                "faster-whisper is not installed. "
                "Install with: pip install faster-whisper>=1.0.3\n"
                "For China mainland users, set HF_ENDPOINT=https://hf-mirror.com "
                "before first run to use the HuggingFace mirror."
            )

        self._model_size = model_size
        self._compute_type = compute_type
        self._device = device
        self._language = language
        self._beam_size = beam_size
        self._initial_prompt = initial_prompt

        logger.info(
            "正在加载 Whisper 模型: 尺寸=%s, 计算类型=%s, 设备=%s...",
            model_size,
            compute_type,
            device,
        )

        try:
            self._model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
                download_root=None,
            )
        except Exception as e:
            raise ModelNotFoundError(
                f"Failed to load Whisper model '{model_size}': {e}\n"
                "If you are in China mainland, try setting environment variable:\n"
                "  HF_ENDPOINT=https://hf-mirror.com"
            ) from e

        logger.info(
            "Whisper 模型加载成功: 尺寸=%s, 计算类型=%s, 设备=%s",
            model_size,
            compute_type,
            device,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def model_size(self) -> str:
        """Return the loaded model size."""
        return self._model_size

    @property
    def language(self) -> str:
        """Return the configured recognition language."""
        return self._language

    @property
    def initial_prompt(self) -> str:
        """Return the configured initial prompt."""
        return self._initial_prompt

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a float32 audio array to text.

        The audio must be float32, 16kHz, mono, and normalized to [-1, 1]
        as produced by detector.py's _emit_slice().

        Args:
            audio: Float32 numpy array (16kHz, mono, [-1, 1]).

        Returns:
            Recognized text string. Empty string if no speech detected
            or audio is empty.
        """
        # Fast path: empty audio
        if audio is None or len(audio) == 0:
            return ""

        # Ensure float32 for Whisper
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        # Ensure 1D (mono); if 2D with shape (n, 1), flatten
        if audio.ndim == 2 and audio.shape[1] == 1:
            audio = audio.flatten()

        logger.debug(
            "正在转录音频: %d 采样 (%.2f 秒)",
            len(audio),
            len(audio) / 16000.0,
        )

        # Perform inference
        # vad_filter=False because detector.py already handles VAD
        # initial_prompt guides Whisper to output Simplified Chinese instead of Traditional
        segments, info = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=self._beam_size,
            initial_prompt=self._initial_prompt,
            vad_filter=False,
        )

        # Merge all segments into a single text string
        texts = [seg.text for seg in segments]
        result = "".join(texts).strip()

        # Fallback: convert Traditional Chinese to Simplified Chinese
        # zhconv handles the rare cases where initial_prompt alone
        # doesn't fully prevent Traditional output
        if result and self._language == "zh" and _zhconv_convert is not None:
            result = _zhconv_convert(result, "zh-cn")

        logger.debug(
            "转录结果 (%d 片段, 语言=%s): %r",
            len(texts),
            info.language,
            result,
        )

        return result

    def run(
        self,
        task_queue: queue.Queue,
        result_queue: queue.Queue,
        stop_event: threading.Event,
    ) -> None:
        """Consumer main loop.

        Blocks on task_queue for audio slices, transcribes each one,
        and pushes recognized text to result_queue.

        Args:
            task_queue: Queue of np.ndarray audio slices from detector.
            result_queue: Queue to push recognized text strings.
            stop_event: Signals graceful shutdown.
        """
        logger.info("识别器循环已启动")

        while not stop_event.is_set():
            try:
                audio = task_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                text = self.transcribe(audio)
                if text:
                    try:
                        result_queue.put(text, timeout=1.0)
                    except queue.Full:
                        logger.warning(
                            "结果队列已满，丢弃: %r", text[:50]
                        )
            except Exception:
                logger.exception(
                    "转录过程中发生意外错误"
                )
                # Continue processing — don't crash the consumer loop

        logger.info("识别器循环已停止")
