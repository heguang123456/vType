# Feature Spec: M-03 core/detector.py — 人声检测与静音切片

> 版本: v0.1.0 | 状态: 实现阶段 | 关联: REQUIREMENTS.md §8.2 M-03

## 1. 功能概述

`core/detector.py` 是生产者线程的后半段，从 `audio.py` 的 `raw_queue` 消费原始音频帧，通过 `webrtcvad` 进行人声检测，实现静音切片状态机，将完整的语音段合并后推送给 ASR 推理线程。

## 2. 功能需求

| 编号 | 需求 | 优先级 | 验收标准 |
|------|------|--------|---------|
| F-D01 | 20ms 滑动窗口分割 | P0 | 将 320-sample 帧分割为 VAD 可处理的 20ms 帧 |
| F-D02 | VAD 人声判定 | P0 | `webrtcvad.Vad(3).is_speech()` 正确返回人声/静音 |
| F-D03 | LISTENING 状态 | P0 | 持续监听，检测到人声切换 RECORDING |
| F-D04 | RECORDING 状态 | P0 | 缓存语音帧，统计连续静音帧数 |
| F-D05 | 静音切片触发 | P0 | 连续静音 ≥ SILENCE_FRAME_LIMIT 时切片发送 |
| F-D06 | 防抖机制 | P0 | 中间间歇静音帧保留在缓冲区，不丢弃 |
| F-D07 | 音频合并 | P0 | 切片时合并所有缓存帧为单个 NumPy 数组 |
| F-D08 | 队列交互 | P0 | 从 raw_queue 消费，切片后推入 task_queue |

## 3. 技术方案

### 状态机

```
LISTENING ──(检测到人声)──► RECORDING
    ▲                          │
    └──(切片发送完成)──────────┘
```

### 滑动窗口算法

```
原始音频: [s1][s2][s3]...[s320] (320 samples for 20ms frame)
         ↓ split into 20ms frames
VAD帧:    [20ms 帧] [20ms 帧] [20ms 帧] ...

每帧 = BLOCK_SIZE * 2 bytes (int16) = 640 bytes
```

## 4. 接口设计

```python
class VoiceDetector:
    def __init__(self, ...) -> None
    def run(self, raw_queue: Queue, task_queue: Queue, stop_event: Event) -> None
    def _split_frames(self, audio: np.ndarray) -> List[bytes]
    def _handle_listening(self, is_speech: bool) -> None
    def _handle_recording(self, is_speech: bool) -> None
    def _emit_slice(self) -> None
```

## 5. 测试计划

| 场景 | Mock 策略 |
|------|----------|
| 状态机 LISTENING→RECORDING | Mock `webrtcvad.Vad.is_speech()` 返回 True |
| 静音切片触发 | 连续返回 False ≥ SILENCE_FRAME_LIMIT 次 |
| 防抖（中间短静音不切片） | 返回 [True, False, False, True, False×40] |
| 音频合并正确性 | 验证合并后的数组形状和采样点数量 |
| 线程退出信号 | stop_event.set() 后正确退出循环 |
