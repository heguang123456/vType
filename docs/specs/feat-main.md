# Feature Spec: M-07 main.py — CLI 入口

> 版本: v0.1.0 | 状态: 设计阶段 | 关联: REQUIREMENTS.md §8.4 M-07

## 1. 功能概述

`main.py` 是 vType 的命令行入口，基于 `click` 框架提供子命令结构。它负责解析命令行参数、配置全局日志、初始化 KeyMonitor + CoreManager 组合、处理操作系统信号（SIGINT/SIGTERM），并将整个语音输入流水线串联为可用的终端应用。

## 2. 功能需求

| 编号 | 需求 | 优先级 | 验收标准 |
|------|------|--------|---------|
| F-M01 | CLI 子命令结构 | P0 | 提供 `vtype start` 主命令 + `vtype config` 查看配置 + `vtype devices` 列出音频设备 |
| F-M02 | 语音输入启动 | P0 | `vtype start` 启动 KeyMonitor（按住 CapsLock）+ CoreManager 流水线 |
| F-M03 | 信号处理 | P0 | `Ctrl+C` (SIGINT) 和 `SIGTERM` 触发优雅停止，清理 KeyMonitor 和 CoreManager |
| F-M04 | 参数覆盖 | P1 | `--model-size`、`--compute-type`、`--language`、`--silence-limit` 覆盖 config.py 默认值 |
| F-M05 | 日志级别控制 | P1 | `--verbose` / `--quiet` 控制日志输出详细程度 |
| F-M06 | 设备列表 | P1 | `vtype devices` 列出系统所有音频输入设备 |
| F-M07 | 配置查看 | P2 | `vtype config` 打印当前所有配置项 |
| F-M08 | 版本信息 | P2 | `vtype --version` 输出版本号 |
| F-M09 | 优雅退出提示 | P0 | 停止时输出识别统计摘要（总识别次数、运行时长） |

## 3. CLI 设计

### 3.1 命令结构

```
vtype
├── start         # 启动语音输入（默认命令）
│   ├── --model-size TEXT
│   ├── --compute-type TEXT
│   ├── --language TEXT
│   ├── --silence-limit INT
│   ├── --hotkey TEXT
│   ├── --verbose / --quiet
│   └── --list-devices
├── devices       # 列出音频设备
├── config        # 查看当前配置
└── --version     # 版本信息
```

### 3.2 start 命令详细参数

```
Usage: vtype start [OPTIONS]

  启动语音输入服务。
  按住热键（默认 CapsLock）说话，松开自动识别并输出文字。
  按 Ctrl+C 停止。

Options:
  --model-size TEXT       Whisper 模型 [tiny|base|small|medium]
                          (默认: base)
  --compute-type TEXT     计算精度 [int8|float16]
                          (默认: int8)
  --language TEXT         识别语言代码
                          (默认: zh)
  --silence-limit INTEGER 静音阈值 (ms)
                          (默认: 800)
  --hotkey TEXT           热键字符串 (pynput 格式)
                          (默认: Key.caps_lock)
  --verbose               详细日志输出
  --quiet                 静默模式（仅输出错误）
  --help                  显示帮助
```

### 3.3 工具命令

```bash
# 列出音频设备
$ vtype devices
可用的音频输入设备:
  0: Microsoft Sound Mapper - Input (默认)
  1: Microphone (Realtek High Definition Audio)
  2: CABLE Output (VB-Audio Virtual Cable)

# 查看配置
$ vtype config
vType 配置:
  SAMPLE_RATE:         16000
  CHANNELS:            1
  FRAME_DURATION_MS:   20
  SILENCE_LIMIT_MS:    800
  MODEL_SIZE:          base
  COMPUTE_TYPE:        int8
  DEVICE:              cpu
  LANGUAGE:            zh
  TYPE_DELAY:          0.005
  CLIPBOARD_FALLBACK:  True
  QUEUE_MAXSIZE:       10
```

## 4. 技术方案

### 4.1 主流程（start 命令）

```
vtype start
    │
    ▼
1. 解析 CLI 参数 → 覆盖 config.py 默认值
    │
    ▼
2. 配置 logging（--verbose → DEBUG, --quiet → ERROR, 默认 → INFO）
    │
    ▼
3. 初始化 CoreManager
    │   callback: 实时打印识别文本
    │   status_callback: 日志输出状态变更
    ▼
4. 初始化 KeyMonitor
    │   on_press: manager.start()
    │   on_release: manager.stop()
    │   hotkey: 用户指定的热键
    ▼
5. 注册信号处理器 (SIGINT, SIGTERM)
    │
    ▼
6. key_monitor.start()  → 后台监听线程启动
    │
    ▼
7. 输出欢迎信息 + 提示
    │   "vType 已启动，按住 CapsLock 说话..."
    │
    ▼
8. 主线程等待（listener.join() 或 signal.pause()）
    │
    ▼
9. 收到 Ctrl+C → 优雅停止
    │   key_monitor.stop()
    │   manager.stop()
    │   输出统计摘要
    │   sys.exit(0)
```

### 4.2 优雅停止流程

```
SIGINT/SIGTERM 信号
    │
    ▼
1. logging.info("正在停止 vType...")
    │
    ▼
2. key_monitor.stop()     ← 停止热键监听
    │
    ▼
3. manager.stop()          ← 停止 CoreManager（5 步优雅序列）
    │
    ▼
4. 输出统计摘要:
    │   "vType 已停止。运行时长: 12m30s, 识别次数: 42"
    ▼
5. sys.exit(0)
```

### 4.3 错误处理

| 场景 | 处理方式 |
|------|---------|
| 模型下载失败 | 打印清晰的镜像/离线指引，退出码 1 |
| 麦克风不可用 | 打印设备列表，建议 `--list-devices` 选择 |
| 热键权限不足 | 打印权限指引（macOS），降级到 Ctrl+C 模式 |
| 未知参数 | click 自动处理，显示帮助信息 |

## 5. 接口设计

### 5.1 click 命令定义

```python
import click
from config import (
    SAMPLE_RATE, CHANNELS, FRAME_DURATION_MS, SILENCE_LIMIT_MS,
    MODEL_SIZE, COMPUTE_TYPE, DEVICE, LANGUAGE,
    TYPE_DELAY, CLIPBOARD_FALLBACK, QUEUE_MAXSIZE,
    print_config,
)
from core.manager import CoreManager
from utils.key_monitor import KeyMonitor

@click.group()
@click.version_option(version="0.1.0", prog_name="vType")
def cli():
    """vType — CLI Voice Input，完全本地运行的语音输入法。"""
    pass

@cli.command()
@click.option("--model-size", default=None, help="Whisper 模型大小")
@click.option("--compute-type", default=None, help="计算精度")
@click.option("--language", default=None, help="识别语言")
@click.option("--silence-limit", type=int, default=None, help="静音阈值 (ms)")
@click.option("--hotkey", default=None, help="热键字符串")
@click.option("--verbose", is_flag=True, help="详细日志")
@click.option("--quiet", is_flag=True, help="静默模式")
def start(model_size, compute_type, language, silence_limit, hotkey, verbose, quiet):
    """启动语音输入服务。"""
    _configure_logging(verbose, quiet)
    _apply_overrides(model_size, compute_type, language, silence_limit)
    _run(hotkey)

@cli.command()
def devices():
    """列出可用的音频输入设备。"""
    _list_devices()

@cli.command()
def config():
    """查看当前配置。"""
    print_config()

def _configure_logging(verbose: bool, quiet: bool) -> None:
    ...

def _apply_overrides(model_size, compute_type, language, silence_limit) -> None:
    ...

def _run(hotkey: str | None) -> None:
    ...

def _list_devices() -> None:
    ...

def _signal_handler(signum, frame) -> None:
    ...
```

### 5.2 回调函数

```python
def _create_text_callback():
    """创建实时文本输出回调。"""
    def on_text(text: str):
        # 不换行打印，模拟"盲打"体验
        sys.stdout.write(text)
        sys.stdout.flush()
    return on_text

def _create_status_callback():
    """创建状态变更回调。"""
    def on_status_change(old, new):
        logging.debug(f"状态变更: {old.name} → {new.name}")
    return on_status_change
```

### 5.3 信号处理

```python
import signal
import sys

_manager: CoreManager | None = None
_monitor: KeyMonitor | None = None

def _signal_handler(signum, frame):
    """SIGINT/SIGTERM 处理器。"""
    global _manager, _monitor
    logging.info("收到退出信号，正在停止...")
    
    if _monitor:
        _monitor.stop()
    if _manager:
        _manager.stop()
    
    sys.exit(0)

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)
```

## 6. 统计摘要输出

停止时的输出示例：

```
vType 已停止。
─────────────────────────
  运行时长:    12m 30s
  识别次数:    42 次
  最后状态:    IDLE
─────────────────────────
```

统计信息获取：

```python
def _print_summary(manager: CoreManager, started_at: float) -> None:
    elapsed = time.time() - started_at
    stats = manager.statistics
    click.echo()
    click.echo("vType 已停止。")
    click.echo("─────────────────────────")
    click.echo(f"  运行时长:    {_format_duration(elapsed)}")
    click.echo(f"  识别次数:    {stats['recognizer']['segments_transcribed']} 次")
    click.echo(f"  最后状态:    {stats['status'].upper()}")
    click.echo("─────────────────────────")
```

## 7. 测试计划

| 测试类 | 用例数 | 覆盖内容 |
|--------|--------|---------|
| `TestCLIGroup` | 3 | cli 组创建、版本选项、帮助文本 |
| `TestStartCommand` | 5 | 参数解析、覆盖 config、日志配置、信号注册、欢迎信息 |
| `TestDevicesCommand` | 2 | 设备列表输出、无设备时提示 |
| `TestConfigCommand` | 2 | 配置输出、环境变量覆盖显示 |
| `TestGracefulShutdown` | 3 | SIGINT 处理、SIGTERM 处理、统计摘要输出 |
| `TestErrorHandling` | 3 | 模型下载失败、麦克风不可用、热键权限降级 |
| `TestIntegration` | 2 | 完整 start → 运行 → stop 流程、多次启停 |

**预计总计：~20 个测试**

### Mock 策略

- Mock `CoreManager` 和 `KeyMonitor`（避免真实硬件/模型依赖）
- 使用 `click.testing.CliRunner` 测试 CLI 命令
- Mock `logging` 验证日志级别
- Mock `signal.signal` 验证信号注册
- Mock `sys.exit` 验证退出码

## 8. 依赖与前置条件

| 依赖 | 说明 |
|------|------|
| `click` (≥ 8.1) | CLI 框架 |
| `core.manager.CoreManager` | 语音输入流水线调度器 |
| `utils.key_monitor.KeyMonitor` | 全局热键监听 |
| `config.py` | 全局配置，包括 `print_config()` |
| `signal` (stdlib) | 信号处理 |
| `logging` (stdlib) | 日志系统 |
| `time` (stdlib) | 运行时长统计 |

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| `click` 与 `signal` 冲突 | 低 | 信号可能在 click 事件循环中被吞 | 使用 `signal.signal` 而非 `signal.sigaction`，在主线程注册 |
| 热键权限导致无法启动 | 中 | 用户不知道如何开始语音输入 | 降级到 Ctrl+C 模式 + 清晰提示 |
| 模型下载阻塞启动 | 高 | 首次运行长时间无响应 | 在 `start` 命令开始时立即提示"正在加载模型..." |
| Windows 终端 Ctrl+C 行为差异 | 低 | `KeyboardInterrupt` 可能不触发 | 同时注册 `SIGINT` 和 `SIGBREAK`（Windows 特有） |

## 10. 用户交互流程

```
$ vtype start
正在加载 faster-whisper base 模型...
模型加载完成 (CPU, int8)。

╔══════════════════════════════════════════════╗
║          vType v0.1.0 已启动 🎤               ║
╠══════════════════════════════════════════════╣
║  按住 CapsLock 开始说话，松开自动识别输出       ║
║  按 Ctrl+C 退出                                ║
║                                              ║
║  模型: base  |  语言: zh  |  静音: 800ms      ║
╚══════════════════════════════════════════════╝

[等待热键按下...]

今天天气真不错            ← 松开热键后自动输出识别文本

^C
vType 已停止。
─────────────────────────
  运行时长:    5m 12s
  识别次数:    8 次
  最后状态:    IDLE
─────────────────────────
```
