# Feature Spec: M-04 core/recognizer.py — ASR 推理引擎

> 版本: v0.1.0 | 状态: 设计阶段 | 关联: REQUIREMENTS.md §8.3 M-04

## 1. 功能概述

`recognizer.py` 是消费者线程的前半段，负责将 detector 产出的语音切片（float32 numpy 数组）通过 `faster-whisper` 引擎转写为文本。**核心约束**：模型单例加载（`__init__` 中完成一次），`transcribe()` 复用模型实例执行推理；推理参数锁死 `vad_filter=False`（前置 VAD 已由 detector 完成）、`language="zh"`、`beam_size=3`。

## 2. 功能需求

| 编号 | 需求 | 优先级 | 验收标准 |
|------|------|--------|---------|
| F-R01 | 单例加载 WhisperModel | P0 | `__init__` 加载一次，后续 `transcribe()` 复用，不重新加载 |
| F-R02 | float32 音频推理 | P0 | 输入 float32 numpy 数组（16kHz, mono, [-1,1]），输出 str |
| F-R03 | int8 量化推理 | P0 | `compute_type="int8"`，内存占用降低 4 倍 |
| F-R04 | 空音频处理 | P0 | 输入全零或极短音频时返回 `""`，不抛异常 |
| F-R05 | 多 segment 合并 | P0 | 长音频可能返回多个 segment，需合并全部 `.text` |
| F-R06 | 消费者主循环 | P0 | `run(task_queue, result_queue, stop_event)` 阻塞等待任务 |
| F-R07 | 模型下载失败提示 | P1 | 捕获 ImportError/ConnectionError，输出含 HF_ENDPOINT 镜像的友好提示 |
| F-R08 | 可配置参数 | P1 | 支持 MODEL_SIZE / COMPUTE_TYPE / DEVICE / BEAM_SIZE / LANGUAGE 覆盖 |

## 3. 技术方案

### 3.1 数据流

```
task_queue (Queue[np.ndarray])
    │
    ▼
Recognizer.transcribe(audio: np.ndarray)
    │
    ▼ WhisperModel.transcribe(audio, language="zh", beam_size=3, vad_filter=False)
    │
    ▼ segments → List[Segment]
    │
    ▼ "".join(seg.text for seg in segments).strip()
    │
    ▼ str
    │
    ▼ result_queue.put(text)
```

### 3.2 模型加载策略

```python
# 模型在 __init__ 中加载一次（耗时操作，约 5-15 秒）
self._model = WhisperModel(
    model_size,           # "base"
    device=device,        # "cpu"
    compute_type=compute_type,  # "int8"
    download_root=None,   # 默认 ~/.cache/huggingface/
)
```

### 3.3 transcribe 方法核心逻辑

```python
def transcribe(self, audio: np.ndarray) -> str:
    # 1. 空数组快速返回
    if len(audio) == 0:
        return ""

    # 2. 确保 float32 格式
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)

    # 3. 执行推理（vad_filter=False 因为 detector 已完成 VAD）
    segments, info = self._model.transcribe(
        audio,
        language=self._language,
        beam_size=self._beam_size,
        vad_filter=False,
    )

    # 4. 合并 segments
    text = "".join(seg.text for seg in segments).strip()
    return text
```

### 3.4 消费者主循环

```python
def run(self, task_queue, result_queue, stop_event):
    while not stop_event.is_set():
        try:
            audio = task_queue.get(timeout=0.2)
            text = self.transcribe(audio)
            if text:
                result_queue.put(text)
        except queue.Empty:
            continue
        except Exception as e:
            logger.error("Transcription error: %s", e)
```

## 4. 接口设计

### 4.1 Recognizer 类

```python
class Recognizer:
    """
    Whisper ASR inference engine (consumer thread - first half).

    Loads faster-whisper model once at init and provides transcribe()
    for repeated inference on audio segments from the detector.
    """

    def __init__(
        self,
        model_size: str = "base",
        compute_type: str = "int8",
        device: str = "cpu",
        language: str = "zh",
        beam_size: int = 3,
    ) -> None:
        """
        Load the WhisperModel. This is a heavy operation (5-15s).

        Args:
            model_size: Whisper model (tiny/base/small/medium/large).
            compute_type: int8 / int8_float16 / float16 / float32.
            device: cpu / cuda.
            language: Recognition language (zh / en / auto).
            beam_size: Beam search width (1-10).
        """

    def transcribe(self, audio: np.ndarray) -> str:
        """
        Transcribe a float32 audio array to text.

        Args:
            audio: Float32 numpy array (16kHz, mono, [-1, 1]).

        Returns:
            Recognized text. Empty string if no speech detected.
        """

    def run(
        self,
        task_queue: queue.Queue,
        result_queue: queue.Queue,
        stop_event: threading.Event,
    ) -> None:
        """
        Consumer main loop. Blocks on task_queue, transcribes, outputs to result_queue.

        Args:
            task_queue: Queue of np.ndarray slices from detector.
            result_queue: Queue to push recognized text strings.
            stop_event: Signals graceful shutdown.
        """
```

### 4.2 自定义异常

```python
class RecognizerError(Exception):
    """Base exception for recognizer errors."""

class ModelNotFoundError(RecognizerError):
    """Whisper model not found and download failed."""
```

## 5. 测试计划

| 测试场景 | Mock 策略 |
|---------|----------|
| 参数初始化 | 不 mock 模型加载（直接测试属性存储） |
| transcribe 正常文本 | Mock `WhisperModel.transcribe` 返回可控 segments |
| transcribe 空输入 | 测试空数组快速返回 |
| transcribe 多 segment | Mock 返回多个 segment，验证合并逻辑 |
| transcribe float32 转换 | 输入 int16 数组，验证自动转换 |
| transcribe 空结果 | Mock segments 为空，验证返回 `""` |
| run 主循环 | Mock task_queue + result_queue，控制队列内容 |
| 模型未安装 | Mock `faster_whisper` 为 None，验证 ImportError |
| stop_event 退出 | 设置 stop_event，验证循环退出 |
| 异常处理 | Mock transcribe 抛异常，验证日志和继续运行 |

## 6. 依赖与前置条件

### 项目内依赖
- `config.py`：MODEL_SIZE / COMPUTE_TYPE / DEVICE / BEAM_SIZE / LANGUAGE

### Python 包依赖
- `faster-whisper` ≥ 1.0.3（CTranslate2 引擎）
- `numpy` ≥ 1.24

### 被依赖关系
- `core/manager.py`（M-06）：创建 Recognizer 实例并启动消费者线程

## 7. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| faster-whisper 模型下载失败 | 中 | 高 | 环境变量 `HF_ENDPOINT` 镜像支持；离线模型路径预留 |
| int8 推理精度不足 | 低 | 中 | 支持 `--compute-type float16` 切换 |
| 长音频推理超时 | 低 | 中 | `timeout` 参数预留；流式解码（E-005）远期规划 |
| Python 3.12+ CTranslate2 兼容 | 低 | 低 | 锁定 `faster-whisper >= 1.0.3`，CI 多版本矩阵测试 |
