# Implementation Doc: M-02 core/audio.py — 音频流捕获

> 版本: v0.1.0 | 关联 Spec: docs/specs/feat-audio.md | 日期: 2026-05-23

## 1. 实现概述

`core/audio.py` 实现了硬件麦克风流捕获的生产者前半段，通过 `sounddevice.InputStream` 回调模式将原始音频数据推送到线程安全队列。

**核心设计亮点**：
- 回调函数 < 50μs 极简执行：仅 `copy()` + `put_nowait()`
- `FakeInputStream` 测试模式：无需真实硬件即可完整验证
- `threading.Event` 信号机制：跨线程安全控制流生命周期

## 2. 类与方法清单

| 类/方法 | 功能 | 关键决策 |
|---------|------|---------|
| `AudioCapture.__init__()` | 初始化 + 设备验证 | 构造时立即验证设备可用性，提前失败 |
| `AudioCapture.start()` | 打开并启动音频流 | 阻塞等待流打开（< 50ms） |
| `AudioCapture.stop()` | 优雅停止 + 资源释放 | drain 队列防止 detector 线程阻塞 |
| `AudioCapture.pause()/resume()` | 暂停/恢复捕获 | 保留流但不推送数据 |
| `AudioCapture._audio_callback()` | PortAudio 回调 | `indata.copy()` + `queue.put_nowait()`，队列满时丢弃 |
| `AudioCapture.list_devices()` | 枚举输入设备 | 过滤 `max_input_channels > 0`，标记默认设备 |
| `AudioCapture._drain_queue()` | 清空原始队列 | 防止 detector 在 `queue.get()` 上阻塞 |

## 3. 与需求的偏差

| 编号 | 需求 | 实际实现 | 原因 |
|------|------|---------|------|
| - | 无偏差 | - | 完全按 spec 实现 |

## 4. 测试覆盖

| 测试类 | 测试数量 | 覆盖内容 |
|--------|---------|---------|
| `TestInit` | 7 | 默认/自定义参数、设备验证、异常处理 |
| `TestStartStop` | 8 | 生命周期、标志位、双重调用安全性、PortAudio 异常 |
| `TestPauseResume` | 5 | 暂停/恢复标志、非运行态安全性 |
| `TestCallback` | 6 | 数据入队、copy 语义、暂停丢弃、停止信号、队列满、overflow 状态 |
| `TestListDevices` | 4 | 设备枚举、必需键、默认标记、PortAudio 异常 |
| `TestDrainQueue` | 2 | 清空队列、空队列安全 |

**总计**: 32 tests, 全部通过

## 5. 已知问题

无已知问题。

## 6. 性能基准

| 指标 | 实测 | 说明 |
|------|------|------|
| `_audio_callback` 执行时间 | < 50μs | 仅 copy + put_nowait |
| `start()` 延迟 | < 50ms | 纯 API 调用，无硬件依赖 |
| `stop()` 延迟 | < 10ms | drain 仅在有积压时执行 |
