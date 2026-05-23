# Feature Spec: M-06 core/manager.py — 核心调度器

> 版本: v0.1.0 | 状态: 设计阶段 | 关联: REQUIREMENTS.md §8.3 M-06

## 1. 功能概述

`manager.py` 是 vType 的**"胶水层"**，负责创建所有子模块、管理 3 级队列管道、协调多线程生命周期，并对外暴露统一的 `start/stop/pause/resume` API。

**核心职责**：

1. **模块创建**：按 config 参数创建 AudioCapture、VoiceDetector、Recognizer、TypeWriter 四个子模块
2. **队列管理**：创建并连接 raw_queue（AudioCapture 内部）→ task_queue → result_queue 三级管道
3. **线程调度**：启动 3 个工作线程（Detector / Recognizer / TypeWriter），协调共享 `stop_event`
4. **生命周期**：提供 `start()` / `stop()` / `pause()` / `resume()` 统一控制面
5. **状态报告**：提供 `status` 属性，暴露当前运行状态和子模块统计

**架构位置**：Manager 位于 Phase 2 最后一块，依赖 M-02 ~ M-05 全部子模块，被 M-07 CLI 入口调用。

## 2. 功能需求

| 编号 | 需求 | 优先级 | 验收标准 |
|------|------|--------|---------|
| F-M01 | 子模块创建 | P0 | `start()` 时按 config 参数创建 AudioCapture / VoiceDetector / Recognizer / TypeWriter 实例 |
| F-M02 | 队列管道 | P0 | 创建 task_queue 和 result_queue（maxsize=QUEUE_MAXSIZE），raw_queue 由 AudioCapture 内部管理 |
| F-M03 | 多线程启动 | P0 | 启动 3 个工作线程：Detector（消费 raw_queue）、Recognizer（消费 task_queue 产出 result_queue）、TypeWriter（消费 result_queue） |
| F-M04 | 优雅停止 | P0 | `stop()` 设置 stop_event → join 所有线程（含超时）→ 停止 AudioCapture → 释放资源 |
| F-M05 | 全局暂停 | P1 | `pause()` 调用 AudioCapture.pause()，暂停音频捕获，线程保持运行 |
| F-M06 | 全局恢复 | P1 | `resume()` 调用 AudioCapture.resume()，恢复音频捕获 |
| F-M07 | 状态查询 | P1 | `status` property 返回 `ManagerStatus` 枚举（IDLE / RUNNING / PAUSED / STOPPING） |
| F-M08 | 启动幂等 | P1 | 重复 `start()` 不创建重复线程，打印警告 |
| F-M09 | 停止幂等 | P1 | 重复 `stop()` 安全无副作用 |
| F-M10 | 异常隔离 | P0 | 单个线程崩溃不拖垮整个进程，`stop()` 必须保证资源释放（在 finally 块） |

## 3. 技术方案

### 3.1 数据流（三级管道）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        CoreManager Data Flow                              │
│                                                                           │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐              │
│  │ AudioCapture  │     │ VoiceDetector│     │  Recognizer  │              │
│  │ (PortAudio)   │────►│   [Thread A] │────►│   [Thread B] │              │
│  │               │     │              │     │              │              │
│  │ raw_queue     │     │ VAD state    │     │ faster-      │              │
│  │ (internal)    │     │ machine      │     │ whisper      │              │
│  │               │     │              │     │              │              │
│  └──────┬───────┘     └──────┬───────┘     └──────┬───────┘              │
│         │                    │                    │                       │
│         ▼                    ▼                    ▼                       │
│    raw_queue           task_queue           result_queue                   │
│  (AudioCapture)     (Manager 创建)        (Manager 创建)                   │
│  Queue[np.ndarray]   Queue[np.ndarray]     Queue[str]                     │
│         │                    │                    │                       │
│         └────────────────────┴────────────────────┘                       │
│                                          │                                │
│                            ┌─────────────▼─────────────┐                  │
│                            │      TypeWriter            │                  │
│                            │       [Thread C]           │                  │
│                            │                            │                  │
│                            │  pynput type() /           │                  │
│                            │  clipboard paste           │                  │
│                            └─────────────┬──────────────┘                  │
│                                          │                                │
│                                          ▼                                │
│                                  当前光标位置                              │
└─────────────────────────────────────────────────────────────────────────┘

stop_event: 一个共享的 threading.Event，所有线程在 while 循环中检查
```

### 3.2 类设计

```python
class ManagerStatus(Enum):
    """Manager 运行状态"""
    IDLE = auto()       # 未启动
    RUNNING = auto()    # 正常运行中
    PAUSED = auto()     # 音频捕获暂停
    STOPPING = auto()   # 正在停止

class CoreManager:
    """核心调度器 — 连接所有子模块并管理线程生命周期"""
    
    # === 子模块 ===
    _audio: Optional[AudioCapture]
    _detector: Optional[VoiceDetector]
    _recognizer: Optional[Recognizer]
    _typer: Optional[TypeWriter]
    
    # === 队列 ===
    _task_queue: queue.Queue        # Detector → Recognizer
    _result_queue: queue.Queue      # Recognizer → TypeWriter
    
    # === 线程 ===
    _detector_thread: Optional[threading.Thread]
    _recognizer_thread: Optional[threading.Thread]
    _typer_thread: Optional[threading.Thread]
    
    # === 控制 ===
    _stop_event: threading.Event    # 共享停止信号
    _status: ManagerStatus
    
    # === Public API ===
    def __init__(self, **kwargs)        # 接收可选的 config 覆盖
    def start() -> None                 # 创建模块 + 启动线程
    def stop() -> None                  # 发送停止信号 + join 线程 + 释放资源
    def pause() -> None                 # 暂停音频捕获
    def resume() -> None               # 恢复音频捕获
    
    @property
    def status -> ManagerStatus
    
    @property
    def statistics -> Dict[str, Any]    # 子模块统计汇总
    
    # === Internal ===
    def _create_modules() -> None
    def _start_threads() -> None
    def _stop_threads() -> None
    def _cleanup() -> None
```

### 3.3 线程拓扑

```
┌─────────────────────────────────────────────────────────────┐
│                        Thread Topology                       │
├──────────────┬───────────────────┬──────────────────────────┤
│ Thread       │ Target            │ 输入队列 → 输出队列       │
├──────────────┼───────────────────┼──────────────────────────┤
│ PortAudio    │ _audio_callback   │ Mic → raw_queue          │
│ (sounddevice │ (PortAudio 内部)   │                          │
│  内部线程)    │                   │                          │
├──────────────┼───────────────────┼──────────────────────────┤
│ Thread A     │ detector.run()    │ raw_queue → task_queue   │
│ (detector)   │                   │ (VAD + 切片)             │
├──────────────┼───────────────────┼──────────────────────────┤
│ Thread B     │ recognizer.run()  │ task_queue → result_queue│
│ (recognizer) │                   │ (ASR 推理)               │
├──────────────┼───────────────────┼──────────────────────────┤
│ Thread C     │ typer.run()       │ result_queue → 键盘输出  │
│ (typer)      │                   │ (pynput / clipboard)     │
└──────────────┴───────────────────┴──────────────────────────┘

总共：1 个 PortAudio 回调线程 + 3 个 Python 工作线程
```

> **注**：与 REQUIREMENTS.md 中的双线程概念模型的区别 —— 原始设计将 Recognizer 和 TypeWriter 视为同一"消费者线程"。实际实现中，由于两个模块各自有独立的 `run()` 循环，将它们拆分到两个线程中更自然，且不会增加死锁风险（它们通过 `result_queue` 解耦）。此偏差不改变架构语义。

### 3.4 生命周期状态机

```
              start()
    IDLE ────────────────► RUNNING
     ▲                       │  ▲
     │                       │  │
     │              pause()  │  │ resume()
     │                       ▼  │
     │                     PAUSED
     │                       │
     │              stop()   │
     │                       ▼
     │                    STOPPING ──(threads joined)──► IDLE
     │
     └──────────── stop() (any state) ─────────────────┘
```

### 3.5 停止序列（优雅退出）

```
stop() 调用
  │
  ├─ 1. _status = STOPPING
  ├─ 2. _stop_event.set()              ← 所有线程的 while 循环检测到，退出
  │
  ├─ 3. join _detector_thread (timeout=3.0s)
  │      └─ detector.run() 内部 flush 剩余 speech buffer
  │
  ├─ 4. join _recognizer_thread (timeout=5.0s)
  │      └─ 等待 task_queue 中的音频处理完毕
  │
  ├─ 5. join _typer_thread (timeout=3.0s)
  │      └─ 等待 result_queue 中的文本输出完毕
  │
  ├─ 6. _audio.stop()                  ← 关闭 PortAudio 流
  │
  └─ 7. _status = IDLE
```

**join 超时处理**：超时后不强制 kill（Python 不支持），仅打印警告日志。

### 3.6 异常处理策略

| 场景 | 处理方式 |
|------|---------|
| AudioCapture 设备不存在 | `start()` 阶段抛出 `DeviceNotFoundError`，不启动任何线程 |
| Recognizer 模型加载失败 | `start()` 阶段抛出 `ModelNotFoundError`，不启动任何线程 |
| 线程内 `run()` 异常 | 子模块各自捕获，打印日志，继续循环（不崩溃） |
| `stop()` 中 `join()` 超时 | 打印警告，继续清理 |
| `stop()` 中 `_audio.stop()` 异常 | 捕获并记录，继续释放其他资源 |
| `pause()` 时未运行 | 打印警告，不抛异常 |
| `resume()` 时未运行 | 打印警告，不抛异常 |

## 4. 配置参数

`CoreManager.__init__()` 接受以下可选关键字参数，用于覆盖 config.py 的默认值：

| 参数 | 类型 | 默认值 | 来源 | 传递给 |
|------|------|--------|------|--------|
| `sample_rate` | int | `SAMPLE_RATE` | config | AudioCapture, VoiceDetector |
| `channels` | int | `CHANNELS` | config | AudioCapture |
| `block_size` | int | `BLOCK_SIZE` | config | AudioCapture |
| `dtype` | str | `DTYPE` | config | AudioCapture |
| `device_id` | int\|None | None | config | AudioCapture |
| `frame_duration_ms` | int | `FRAME_DURATION_MS` | config | VoiceDetector |
| `vad_aggressiveness` | int | `VAD_AGGRESSIVENESS` | config | VoiceDetector |
| `silence_frame_limit` | int | `SILENCE_FRAME_LIMIT` | config | VoiceDetector |
| `model_size` | str | `MODEL_SIZE` | config | Recognizer |
| `compute_type` | str | `COMPUTE_TYPE` | config | Recognizer |
| `device` | str | `DEVICE` | config | Recognizer |
| `language` | str | `LANGUAGE` | config | Recognizer |
| `beam_size` | int | `BEAM_SIZE` | config | Recognizer |
| `type_delay` | float | `TYPE_DELAY` | config | TypeWriter |
| `clipboard_fallback` | bool | `CLIPBOARD_FALLBACK` | config | TypeWriter |
| `queue_maxsize` | int | `QUEUE_MAXSIZE` | config | task_queue, result_queue |

## 5. 接口约定

### 5.1 Public API

```python
# 创建 Manager（模块和线程在 start() 时才创建）
mgr = CoreManager(model_size="base", language="zh")
assert mgr.status == ManagerStatus.IDLE

# 启动
mgr.start()
assert mgr.status == ManagerStatus.RUNNING
# 此时：AudioCapture 已打开流，3 个工作线程已在运行

# 暂停
mgr.pause()
assert mgr.status == ManagerStatus.PAUSED
# 此时：音频捕获暂停，线程仍存活

# 恢复
mgr.resume()
assert mgr.status == ManagerStatus.RUNNING

# 停止
mgr.stop()
assert mgr.status == ManagerStatus.IDLE
# 此时：所有线程已 join，AudioCapture 已关闭

# 查询统计
stats = mgr.statistics
# {
#     "status": "RUNNING",
#     "detector_slices": 42,
#     "detector_state": "RECORDING",
# }
```

### 5.2 依赖的现有模块接口

| 模块 | 创建方法 | run() 签名 |
|------|---------|------------|
| `AudioCapture` | `AudioCapture(sample_rate, channels, block_size, dtype, device_id)` | N/A（`start()/stop()` 管理 PortAudio 流） |
| `VoiceDetector` | `VoiceDetector(sample_rate, frame_duration_ms, aggressiveness, silence_frame_limit)` | `detector.run(raw_queue, task_queue, stop_event)` |
| `Recognizer` | `Recognizer(model_size, compute_type, device, language, beam_size)` | `recognizer.run(task_queue, result_queue, stop_event)` |
| `TypeWriter` | `TypeWriter(type_delay, clipboard_fallback)` | `typer.run(result_queue, stop_event)` |

### 5.3 raw_queue 所有权

`raw_queue` 由 `AudioCapture.__init__()` 内部创建（`self.raw_queue = queue.Queue()`），不设 maxsize（PortAudio 回调中 `put_nowait`，满则丢弃）。Manager 通过 `_audio.raw_queue` 访问。

## 6. 测试计划

### 6.1 单元测试场景（约 15 个）

| 编号 | 测试场景 | 测试点 |
|------|---------|--------|
| T-M01 | `__init__` 默认状态 | status=IDLE，所有线程/模块为 None |
| T-M02 | `start()` 创建所有子模块 | AudioCapture / VoiceDetector / Recognizer / TypeWriter 均已创建 |
| T-M03 | `start()` 启动所有线程 | 3 个线程均已启动且 target 正确 |
| T-M04 | `start()` 后 status=RUNNING | status 变为 RUNNING |
| T-M05 | 重复 `start()` 幂等 | 第二次调用不创建新线程，打印警告 |
| T-M06 | `pause()` 流转到 PAUSED | status=PAUSED，AudioCapture.pause() 被调用 |
| T-M07 | `resume()` 流转到 RUNNING | status=RUNNING，AudioCapture.resume() 被调用 |
| T-M08 | `stop()` 设置 stop_event | stop_event.is_set() 为 True |
| T-M09 | `stop()` join 所有线程 | 3 个线程的 join() 均被调用 |
| T-M10 | `stop()` 停止 AudioCapture | AudioCapture.stop() 被调用 |
| T-M11 | `stop()` 后 status=IDLE | status 回到 IDLE |
| T-M12 | 任意状态 `stop()` | IDLE/PAUSED/RUNNING 都能安全调用 stop() |
| T-M13 | 子模块创建失败不启动线程 | DeviceNotFoundError 时线程数为 0 |
| T-M14 | `statistics` 返回有效数据 | 字典包含子模块信息 |
| T-M15 | pause 时未运行警告 | status != RUNNING 时调用 pause() 打印警告 |

### 6.2 Mock 策略

- Mock 所有子模块类（`core.audio.AudioCapture`、`core.detector.VoiceDetector`、`core.recognizer.Recognizer`、`core.typer.TypeWriter`）
- 不真正启动 PortAudio 流或加载 Whisper 模型
- 线程的 `start()` / `join()` 通过 Mock 验证调用

## 7. 与需求偏差

| 偏差项 | 原始设计（REQUIREMENTS.md） | 实现决策 | 理由 |
|--------|---------------------------|---------|------|
| 线程数量 | 4 个（audio_thread + detector_thread + recognizer_thread + typer_thread） | 3 个工作线程（detector / recognizer / typer） | AudioCapture 使用 PortAudio 内部回调线程，Manager 不直接管理；去除了无意义的 audio_thread |
| 线程拓扑 | Thread B 包含 recognizer + typer 串联 | recognizer 和 typer 各自独立线程 | 两者均有独立 `run()` 方法，拆分更自然，通过 result_queue 解耦 |
| raw_queue 管理 | Manager 创建 raw_queue | AudioCapture 内部创建 raw_queue | AudioCapture 在 `__init__` 中就创建了 raw_queue，Manager 通过 `_audio.raw_queue` 访问 |

## 8. 遗留风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| Thread join 超时后资源泄漏 | 低 | 超时仅打警告，Python 线程无法强制 kill；等待 GC 回收 |
| 3 线程架构 vs 2 线程设计的性能差异 | 极低 | 多一个线程的上下文切换成本 (~μs) 远小于 ASR 推理延迟 (~100ms) |
| Manager 测试无法覆盖真实 PortAudio/Whisper 行为 | 中 | 单元测试通过 Mock 验证调用；集成测试由 M-07 CLI 入口的 e2e 测试覆盖 |
