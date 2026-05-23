# Implementation Doc: M-07 main.py — CLI 入口

> 版本: v0.1.0 | 关联 Spec: docs/specs/feat-main.md | 日期: 2026-05-23

## 1. 实现概述

`main.py` 是 vType 的命令行入口，基于 `click` 框架构建子命令结构。它将 KeyMonitor（热键监听）和 CoreManager（语音流水线）串联为可交互的终端应用，负责参数解析、日志配置、信号处理、优雅停止和统计摘要输出。

**核心设计亮点**：
- **click 命令组**：`vtype start` / `vtype devices` / `vtype config` 三个子命令，`--version` 全局选项
- **全局变量桥接信号处理器**：`_manager` / `_monitor` / `_started_at` 三个模块级全局变量，使 `_signal_handler` 无需闭包即可访问运行时对象
- **递归信号防护**：`_signal_handler` 入口立即设置 `SIG_IGN`，防止重复信号触发多次关闭
- **Windows SIGBREAK 兼容**：`sys.platform == "win32"` 时额外注册 `SIGBREAK` 处理器，覆盖 Windows 控制台关闭场景
- **热键回调异常隔离**：`_on_hotkey_press/release` 用 `try/except` 包裹 `manager.start/stop`，单次回调异常不中断监听循环

## 2. 函数清单

| 函数 | 功能 | 关键决策 |
|------|------|---------|
| `cli()` | click 根命令组，`@click.version_option` | 显示 `vType 0.1.0 — CLI Voice Input` |
| `start()` | 启动语音输入主命令 | 12 步主流程：日志→覆盖→验证→加载模型→回调→KeyMonitor→信号→监听→欢迎→循环→关闭 |
| `devices()` | 列出音频输入设备 | 懒导入 `sounddevice`，仅 CLI 调用时加载 |
| `config_command()` | 打印当前配置 | 委托 `config.print_config()` |
| `_configure_logging()` | 日志级别分配 | `verbose→DEBUG` / `quiet→ERROR` / 默认→`INFO`，输出到 stderr |
| `_create_text_callback()` | 文本实时输出闭包 | `sys.stdout.write + flush`，不换行模拟"盲打" |
| `_create_status_callback()` | 状态变更日志闭包 | `logger.debug` 记录 `old.name → new.name` |
| `_on_hotkey_press()` | 热键按下回调 | 调用 `_manager.start()`，异常捕获不崩溃 |
| `_on_hotkey_release()` | 热键释放回调 | 调用 `_manager.stop()`，异常捕获不崩溃 |
| `_signal_handler()` | SIGINT/SIGTERM/SIGBREAK 处理器 | 先 SIG_IGN 防递归 → `_shutdown()` → `sys.exit(0)` |
| `_shutdown()` | 优雅停止序列 | monitor.stop → manager.stop → 摘要 → 置 None |
| `_print_welcome()` | 欢迎横幅 | 显示模型/语言/静音阈值/热键信息 |
| `_print_summary()` | 统计摘要 | 运行时长 + 检测切片数 + 最终状态 |
| `_format_duration()` | 时长格式化 | `seconds→"Xm Ys"` 或 `"Xs"` |

## 3. 主流程详解

### 3.1 start 命令执行流程

```
vtype start [OPTIONS]
    │
    ├─ 1. _configure_logging(verbose, quiet)
    │      └─ logging.basicConfig(level=DEBUG/ERROR/INFO, stream=stderr)
    │
    ├─ 2. 构建 kwargs（仅非 None 的 CLI 选项）
    │      └─ silence_limit 转换为 silence_frame_limit（ms→帧数）
    │
    ├─ 3. config.validate_config()
    │      └─ 失败 → click.echo(err=True) + sys.exit(1)
    │
    ├─ 4. CoreManager(**kwargs)
    │      ├─ 成功 → "Model loaded (CPU, int8)."
    │      └─ 失败 → HF_ENDPOINT 镜像提示 + sys.exit(1)
    │
    ├─ 5. 创建回调闭包
    │      ├─ text_cb: stdout.write + flush（盲打）
    │      └─ status_cb: logger.debug（状态变更）
    │
    ├─ 6. 注入回调到 manager
    │      └─ _manager._text_callback / _status_callback
    │
    ├─ 7. KeyMonitor(on_press/on_release, hotkey)
    │
    ├─ 8. signal.signal(SIGINT/SIGTERM/SIGBREAK, _signal_handler)
    │
    ├─ 9. _monitor.start() → daemon 线程启动
    │
    ├─ 10. _print_welcome() — 欢迎横幅
    │
    ├─ 11. while _monitor.is_listening: sleep(0.5)
    │       └─ KeyboardInterrupt → pass
    │
    └─ 12. _shutdown()
           ├─ monitor.stop()
           ├─ manager.stop()
           ├─ _print_summary()
           └─ 全局变量置 None
```

### 3.2 信号处理流程

```
SIGINT/SIGTERM/SIGBREAK
    │
    ▼
_signal_handler(signum, frame)
    │
    ├─ signal.signal(signum, SIG_IGN)    ← 防止递归
    │
    ├─ logger.info("shutting down...")
    │
    ├─ _shutdown()
    │   ├─ _monitor.stop()   (if not None)
    │   ├─ _manager.stop()   (if not None)
    │   └─ _print_summary()
    │
    └─ sys.exit(0)
```

### 3.3 优雅停止序列

```
_shutdown()
    │
    ├─ KeyMonitor.stop()
    │   ├─ Listener.stop()     ← 停止 OS 级键盘钩子
    │   └─ thread.join(2s)     ← 等待 daemon 线程退出
    │
    ├─ CoreManager.stop()
    │   ├─ 停止音频流
    │   ├─ 清空 audio_queue + text_queue
    │   ├─ worker 线程 join
    │   └─ 重置状态机
    │
    ├─ _print_summary()
    │   └─ 运行时长 + 切片数 + 最终状态
    │
    └─ 全局变量 → None
```

## 4. 与需求的偏差

| 编号 | 需求 | 实际实现 | 备注 |
|------|------|---------|------|
| F-M01 | CLI 子命令结构 | ✅ `start` / `devices` / `config` 三个子命令 | click group 模式 |
| F-M02 | 语音输入启动 | ✅ KeyMonitor + CoreManager 串联 | 12 步主流程 |
| F-M03 | 信号处理 | ✅ SIGINT + SIGTERM + SIGBREAK(Windows) | 递归防护 SIG_IGN |
| F-M04 | 参数覆盖 | ✅ `--model-size` / `--compute-type` / `--language` / `--silence-limit` | click.Choice 类型约束 |
| F-M05 | 日志级别控制 | ✅ `--verbose` / `--quiet` | DEBUG/ERROR 两级 |
| F-M06 | 设备列表 | ✅ `vtype devices` | lazy import sounddevice |
| F-M07 | 配置查看 | ✅ `vtype config` | 委托 config.print_config() |
| F-M08 | 版本信息 | ✅ `vtype --version` | `@click.version_option(version="0.1.0")` |
| F-M09 | 优雅退出提示 | ✅ 运行时长 + 检测切片数 + 最终状态 | `_print_summary()` |
| — | 额外 | 热键回调异常隔离 | `try/except` 包裹，避免单次异常中断监听 |
| — | 额外 | 模型加载镜像指引 | 失败时打印 `HF_ENDPOINT` 提示 |
| — | 额外 | click.Choice 类型约束 | `model_size` 和 `compute_type` 使用 Choice 限制有效值 |
| — | 额外 | config 预验证 | `start` 启动前调用 `validate_config()`，不通过则 exit(1) |

## 5. 测试覆盖

| 测试类 | 测试数量 | 覆盖内容 |
|--------|---------|---------|
| `TestCLIGroup` | 3 | CLI 组存在性、`--version` 输出、`--help` 命令列表 |
| `TestStartCommand` | 5 | `--help` 选项、`--model-size` 传递、`--language` 传递、无效值拒绝、信号处理器注册 |
| `TestDevicesCommand` | 2 | 列出输入设备（过滤仅输出设备）、无输入设备提示 |
| `TestConfigCommand` | 2 | 打印配置项（含 SAMPLE_RATE/MODEL_SIZE）、环境变量覆盖不报错 |
| `TestGracefulShutdown` | 3 | SIGINT 触发 monitor+manager stop、无对象时不崩溃、第二次信号被忽略 |
| `TestErrorHandling` | 2 | 模型加载失败退出码 1 + 提示、config 验证失败退出码 1 |
| `TestLoggingConfig` | 3 | `--verbose` → DEBUG、`--quiet` → ERROR、默认 → INFO |
| `TestDisplayHelpers` | 4 | duration 纯秒格式化、分秒组合格式化、欢迎横幅含模型语言信息、摘要处理 None manager |
| `TestCallbacks` | 2 | text callback write+flush、status callback 日志记录 |
| `TestHotkeyCallbacks` | 5 | press 启动 manager、无 manager 不崩溃、start 异常捕获、release 停止 manager、stop 异常捕获 |

**总计**: 31 tests，全部通过

### Mock 策略

- **`mock_manager` / `mock_monitor` fixtures**：使用 `mock.patch("main.CoreManager")` / `mock.patch("main.KeyMonitor")`，mock 实例带 `statistics` 字典和 `is_listening` 属性
- **`clean_globals` autouse fixture**：每个测试前后将 `_manager` / `_monitor` / `_started_at` 重置为 None/0.0，确保测试隔离
- **`CliRunner`**：click 标准测试工具，用于 `invoke()` 命令并捕获 stdout/stderr
- **信号测试**：mock `signal.signal` 验证注册行为，不实际设置 OS 级信号处理器（避免跨测试污染）
- **sounddevice mock**：`devices` 测试使用 `mock.patch("sounddevice.query_devices")` 控制设备列表

## 6. 已知问题

### 6.1 无限循环无超时保护

`start` 命令的等待循环 `while _monitor.is_listening: time.sleep(0.5)` 依赖 `_monitor.is_listening` 被 `stop()` 修改。如果 KeyMonitor 内部状态异常未正确翻转，主线程将永久阻塞。当前设计信任 KeyMonitor 的 `stop()` 幂等性，无额外超时兜底。

### 6.2 click.echo 与测试输出混叠

`_print_welcome()` 和 `_print_summary()` 使用 `click.echo()` 直接输出到 stdout，与 `_create_text_callback` 的 `sys.stdout.write` 共享同一流。在真实终端中无问题，但在测试中 `CliRunner` 捕获所有输出，需要仔细断言输出包含关系。

### 6.3 测试排序依赖（已修复）

`test_config.py` 的 autouse fixture `reset_config_module` 曾删除 `sys.modules["config"]` 未恢复，导致后续 `test_main.py` 运行时 config 模块身份不一致，触发 CliRunner 死锁。已在 `reset_config_module` teardown 中添加 save/restore 逻辑解决。

## 7. 依赖关系

| 依赖 | 类型 | 说明 |
|------|------|------|
| `click` | 外部 | CLI 框架，`@click.group` + `@click.option` + `CliRunner` |
| `core.manager.CoreManager` | 内部 | 语音输入流水线调度器 |
| `utils.key_monitor.KeyMonitor` | 内部 | 全局热键监听 |
| `config` | 内部 | 全局配置 + `validate_config()` + `print_config()` |
| `signal` | stdlib | 操作系统信号处理 |
| `logging` | stdlib | 日志系统 |
| `time` | stdlib | 运行时长统计 |
| `sounddevice` | 外部 | 设备列表查询（懒导入，仅 `devices` 命令） |

## 8. 交互示例

```
$ vtype start --model-size small --language en
Loading faster-whisper small model...
Model loaded (CPU, int8).

╔══════════════════════════════════════════════╗
║          vType v0.1.0 — Ready               ║
╠══════════════════════════════════════════════╣
║  Hold the hotkey, speak, release to type     ║
║  Press Ctrl+C to quit                        ║
║                                              ║
║  Model: small | Language: en | Silence: 800ms║
║  Hotkey: CapsLock                            ║
╚══════════════════════════════════════════════╝

[按住 CapsLock 说话...]
Hello world this is voice typing     ← 松开后自动输出

^C
vType stopped.
─────────────────────────
  Duration:    1m 12s
  Segments:    3
  Final state: IDLE
─────────────────────────
```
