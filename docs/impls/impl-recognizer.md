# Implementation Doc: M-04 core/recognizer.py — ASR 推理引擎

> 版本: v0.1.0 | 关联 Spec: docs/specs/feat-recognizer.md | 日期: 2026-05-23

## 1. 实现概述

`core/recognizer.py` 实现消费者线程的前半段：单例加载 `faster-whisper` 模型，从 `TaskQueue` 阻塞获取 detector 产出的语音切片（float32 numpy 数组），执行 `int8` 量化推理，将识别文本推送到 `result_queue`。

**核心设计亮点**：
- **模型单例加载**：`__init__` 中完成一次 `WhisperModel(...)` 初始化（耗时 5-15s），`transcribe()` 纯复用，零重复加载
- **三态格式归一化**：`transcribe()` 入口统一处理 None、2D 单声道、int16 格式，保证传入 Whisper 的始终是 1D float32
- **消费者主循环鲁棒**：`run()` 捕获 `transcribe()` 所有异常并继续运行，`result_queue` 满时主动丢弃而非阻塞
- **国内网络友好**：`ModelNotFoundError` 异常消息内置 `HF_ENDPOINT=https://hf-mirror.com` 镜像提示

## 2. 类与方法清单

| 类/方法 | 功能 | 关键决策 |
|---------|------|---------|
| `RecognizerError` | 基础异常类 | 继承 `Exception`，所有识别器异常的根 |
| `ModelNotFoundError` | 模型未找到异常 | 继承 `RecognizerError`，消息含 HF_ENDPOINT 提示 |
| `Recognizer.__init__()` | 加载 WhisperModel + 存储参数 | `faster-whisper` 未安装时立即抛异常 |
| `Recognizer.model_size` | 属性：返回加载的模型大小 | 只读 property，暴露内部状态 |
| `Recognizer.language` | 属性：返回配置的识别语言 | 只读 property |
| `Recognizer.transcribe()` | 核心推理方法：np.ndarray → str | 三合一归一化 + `vad_filter=False` + segment 合并 |
| `Recognizer.run()` | 消费者主循环 | `queue.Empty` 超时 0.2s、`result_queue.put(timeout=1.0)` 防死锁 |

## 3. transcribe() 数据流详解

```
输入: np.ndarray (可能是 float32/int16, 1D/2D, 可能为 None)
    │
    ▼ [Fast Path]
    if audio is None or len(audio) == 0 → return ""
    │
    ▼ [Dtype Normalization]
    if audio.dtype != np.float32 → audio.astype(np.float32)
    │
    ▼ [Shape Normalization]
    if audio.ndim == 2 and audio.shape[1] == 1 → audio.flatten()
    │
    ▼ [Whisper Inference]
    self._model.transcribe(
        audio,
        language=self._language,       # 默认 "zh"
        beam_size=self._beam_size,     # 默认 3
        vad_filter=False,              # detector 已做 VAD
    )
    │
    ▼ segments → List[Segment], info → TranscriptionInfo
    │
    ▼ [Merge & Strip]
    "".join(seg.text for seg in segments).strip()
    │
    ▼ str (空字符串表示无语音/识别失败)
```

## 4. run() 消费者循环详解

```
while not stop_event.is_set():
    │
    ▼ task_queue.get(timeout=0.2)
    ├─ queue.Empty → continue (保持响应 stop_event)
    │
    ▼ audio = task_queue.get() 成功
    │
    ▼ transcribe(audio) → text
    │
    ▼ if text is not empty:
    │   try:
    │       result_queue.put(text, timeout=1.0)
    │   except queue.Full:
    │       logger.warning(...)   # 丢弃，防止阻塞消费者
    │
    ▼ 任何 transcribe 异常 → logger.exception() → continue
```

**设计要点**：
- `task_queue.get(timeout=0.2)` 短超时确保退出的响应性
- `result_queue.put(timeout=1.0)` 防止下游 typer 消费过慢时阻塞推理
- 异常被完全捕获，不传播到线程外部

## 5. 与需求的偏差

| 编号 | 需求 | 实际实现 | 原因 |
|------|------|---------|------|
| F-R01 | 单例加载 WhisperModel | ✅ 完全一致 | `__init__` 加载一次，`transcribe()` 纯复用 |
| F-R02 | float32 音频推理 | ✅ 完全一致，额外增加 int16 自动转换 + 2D flatten + None guard | 增强鲁棒性 |
| F-R03 | int8 量化推理 | ✅ 完全一致 | 默认 `compute_type="int8"` |
| F-R04 | 空音频处理 | ✅ 完全一致 | None 和 `len==0` 均返回 `""` |
| F-R05 | 多 segment 合并 | ✅ 完全一致 | `"".join(seg.text).strip()` |
| F-R06 | 消费者主循环 | ✅ 完全一致 | `run(task_queue, result_queue, stop_event)` |
| F-R07 | 模型下载失败提示 | ✅ 完全一致 | `ModelNotFoundError` 含 `HF_ENDPOINT` 镜像提示 |
| F-R08 | 可配置参数 | ✅ 完全一致 | 5 个参数均可覆盖 |
| — | 额外：属性访问 | `model_size` / `language` property | 便于外部检查和测试断言 |
| — | 额外：int16→float32 | `transcribe()` 自动转换非 float32 输入 | 防御下游格式不一致 |
| — | 额外：2D→1D flatten | `transcribe()` 自动处理 `(n, 1)` 形状 | 兼容 `scipy.io.wavfile.read()` 等输入 |
| — | 额外：result_queue Full 处理 | 主动丢弃而非阻塞 | 防止 typer 慢消费时倒逼消费者阻塞 |

## 6. 测试覆盖

| 测试类 | 测试数量 | 覆盖内容 |
|--------|---------|---------|
| `TestInit` | 5 | 默认参数、自定义参数、模型加载确认、model_size 存储、参数正确传递 |
| `TestTranscribe` | 8 | 正常文本、多 segment 合并、空 segments、空数组、None 输入、空格去除、特殊字符、参数传递验证 |
| `TestAudioFormat` | 3 | float32 直通、2D mono flatten、int16→float32 转换 |
| `TestRun` | 5 | 从队列消费、空文本跳过、stop_event 退出、transcription 异常处理、result_queue 满处理 |
| `TestMissingModel` | 2 | faster-whisper 未安装异常、HF_ENDPOINT 镜像提示 |
| `TestConfigIntegration` | 2 | 使用 config.py 默认值、覆盖参数验证 |

**总计**: 25 tests, 全部通过 (0.42s)

### Mock 策略

| Mock 对象 | 策略 | 说明 |
|-----------|------|------|
| `faster_whisper.WhisperModel` | `mock.patch` 替换为 `MockWhisperModel` 类 | 不实际下载/加载模型，控制 `transcribe()` 返回的 segments |
| `MockWhisperModel` | 自定义类，支持 `model_size/device/compute_type` 属性 | 记录每次 `transcribe()` 调用参数到 `transcribe_called_with` |
| `MockSegment` | dataclass，含 `text/start/end` | 模拟 Whisper segment |
| `MockTranscriptionInfo` | dataclass，含 `language/language_probability` | 模拟语言检测结果 |
| 模型未安装测试 | `mock.patch("core.recognizer.WhisperModel", None)` | 验证 `ModelNotFoundError` |

## 7. 已知问题

无已知问题。

## 8. 性能基准

| 指标 | 实测 / 预期 | 说明 |
|------|-----------|------|
| 模型加载时间 | 5-15s（base 模型） | 首次运行需从 HuggingFace 下载；后续秒开 |
| 模型内存占用 | ~300MB（base + int8） | int8 量化相比 float32 降低 4 倍 |
| `transcribe()` 1s 音频 | < 0.3s (RTF < 0.3) | CPU 推理，base 模型 |
| `transcribe()` 空音频 | < 1μs | Fast path 直接返回 |
| `transcribe()` 格式归一化 | < 100μs | astype + flatten，纯 NumPy |
| `run()` 空循环 | < 1ms | `queue.Empty(timeout=0.2)` 快速路径 |
| 国内模型下载 | 需设置 `HF_ENDPOINT=https://hf-mirror.com` | 否则可能超时失败 |

## 9. 线程安全说明

| 上下文 | 策略 |
|--------|------|
| `__init__()` | 主线程调用一次，非线程安全 |
| `transcribe()` | 单消费者线程调用，非线程安全（WhisperModel 内部状态） |
| `run()` | 消费者主循环，独占 transcribe() 调用 |
| `model_size` / `language` | 只读 property，初始化后不变，无竞态 |
