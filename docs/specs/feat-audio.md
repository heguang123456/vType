# Feature Spec: M-02 core/audio.py — 音频流捕获

> 版本: v0.1.0 | 状态: 实现阶段 | 关联: REQUIREMENTS.md §8.2 M-02

## 1. 功能概述

`core/audio.py` 是生产者线程的前半段，负责通过 `sounddevice.InputStream` 流模式捕获硬件麦克风音频数据。

**核心约束**：回调函数必须极简化——只做 `queue.put(data.copy())`，绝不能在回调中执行任何耗时操作（包括 VAD、ASR、I/O），否则将导致 `sounddevice` 底层输入缓冲区溢出，丢失硬件音频帧。

## 2. 功能需求

| 编号 | 需求 | 优先级 | 验收标准 |
|------|------|--------|---------|
| F-A01 | 打开默认麦克风流 | P0 | `sounddevice.InputStream` 成功打开，采样率 16kHz、单声道 |
| F-A02 | 流模式回调捕获 | P0 | 回调接收 `(indata, frames, time, status)` 四元组，推送 `indata.copy()` 到原始队列 |
| F-A03 | 状态控制（启动/停止/暂停/恢复） | P0 | `start()/stop()/pause()/resume()` 正确控制音频流生命周期 |
| F-A04 | 优雅停止 | P0 | `stop()` 调用后释放 PortAudio 资源，无死锁 |
| F-A05 | 设备枚举 | P1 | 支持列出可用音频输入设备列表 |
| F-A06 | 指定设备 ID | P1 | 支持通过 `device_id` 参数选择特定麦克风 |

## 3. 技术方案

### 数据流

```
硬件麦克风
  ↓ (PortAudio WASAPI/CoreAudio/ALSA)
sounddevice.InputStream 回调
  ↓ indata (numpy.ndarray, shape=(frames, channels), dtype=float32)
raw_queue.put(indata.copy())
  ↓
detector.py 消费（在独立线程中）
```

### 回调极简化原则

```python
def _audio_callback(self, indata, frames, time_info, status):
    """回调函数：仅做数据复制和入队。耗时 < 50μs。"""
    if status:
        logger.warning(f"Audio stream status: {status}")
    if not self._is_running.is_set():
        raise sounddevice.CallbackStop  # 优雅停止信号
    # 关键：copy() 避免 NumPy 数组被复用
    self._raw_queue.put(indata.copy())
```

## 4. 接口设计

### 类：`AudioCapture`

```python
class AudioCapture:
    """
    Hardware microphone audio capture using sounddevice InputStream.

    Thread Safety:
        - Callback runs in PortAudio's internal high-priority thread.
        - start/stop/pause/resume are called from the main/manager thread.
        - _is_running is a threading.Event for cross-thread signaling.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        block_size: int = 320,
        dtype: str = "int16",
        device_id: Optional[int] = None,
    ) -> None: ...

    @property
    def is_running(self) -> bool: ...

    @property
    def is_paused(self) -> bool: ...

    def start(self) -> None:
        """Open and start the audio input stream."""

    def stop(self) -> None:
        """Gracefully stop and close the audio stream."""

    def pause(self) -> None:
        """Pause audio capture without closing the stream."""

    def resume(self) -> None:
        """Resume audio capture after pause."""

    @staticmethod
    def list_devices() -> List[Dict[str, Any]]:
        """List available audio input devices."""

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: Any,
    ) -> None:
        """PortAudio stream callback. MUST be minimal."""
```

## 5. 测试计划

| 测试场景 | Mock 策略 |
|---------|----------|
| 回调函数数据格式 | Mock `sounddevice.InputStream`，构造伪造 `indata` 数组传入回调 |
| start/stop 生命周期 | 验证流 API 调用次数和参数 |
| pause/resume 状态切换 | 验证 `_is_running` 和 `_is_paused` 事件状态 |
| 设备列表枚举 | Mock `sounddevice.query_devices()` |
| 异常处理（设备不可用） | Mock `InputStream.__init__` 抛出 `PortAudioError` |

## 6. 依赖与前置条件

- 依赖 M-01：`config.py`（SAMPLE_RATE, CHANNELS, BLOCK_SIZE, DTYPE）
- 依赖 `sounddevice`, `numpy`
- 被 M-03 `detector.py` 和 M-06 `manager.py` 依赖

## 7. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 回调函数超时导致丢帧 | 高 | 高 | 回调极简化（< 50μs），仅做 copy + put |
| 设备被其他应用独占 | 中 | 中 | 捕获 PortAudioError，提供清晰的错误提示 |
| 拔出 USB 麦克风 | 低 | 中 | status 参数检测，记录日志，不崩溃 |
| macOS 未授权麦克风权限 | 高 | 高 | 启动时检测并提示用户授权 |
