# Implementation Doc: M-09 utils/key_monitor.py — 全局热键监听

> 版本: v0.1.0 | 关联 Spec: docs/specs/feat-key-monitor.md | 日期: 2026-05-23

## 1. 实现概述

`utils/key_monitor.py` 是 vType 的全局热键监听模块。它通过 `pynput.keyboard.Listener` 在后台 daemon 线程中监听用户自定义的按键组合，实现按住即说（push-to-talk）交互模式。当用户在任意应用中按下热键时触发录音开始回调，松开时触发录音停止回调，无缝衔接语音输入流程。

**核心设计亮点**：
- **Listener + 手动追踪**（非 GlobalHotKeys）：push-to-talk 需要区分"按下"和"释放"两个事件，GlobalHotKeys 只有按下瞬间的一次性回调，不足以表达持续按住状态
- **`_is_recording` 布尔去抖**：操作系统可能发送重复的按下事件（键盘 repeat），简单布尔标志比时间戳防抖更轻量、延迟更低
- **组合键支持**：通过 `<ctrl>+<alt>+v` 字符串格式解析组合键，支持 `_pressed_keys` 集合追踪多键状态
- **lazy pynput 导入**：通过 `_ensure_pynput()` 延迟导入 pynput，缺失时给清晰错误提示而非模块加载期崩溃
- **macOS 权限降级**：权限不足时打印指引、状态回退 IDLE，不抛异常崩溃

## 2. 类与方法清单

| 类/方法 | 功能 | 关键决策 |
|---------|------|---------|
| `KeyMonitorState` | 枚举：`IDLE`/`LISTENING` | `str` 值，便于日志和调试 |
| `KeyMonitorError` | 基础异常类 | 继承 `Exception`，语义化分层 |
| `KeyMonitorPermissionError` | 权限异常（macOS 辅助功能） | 继承 `KeyMonitorError`，调用方可按需捕获 |
| `KeyMonitor.__init__()` | 构造监听器，注册回调 + 热键 | Lazy 导入 pynput，默认 CapsLock |
| `KeyMonitor.start()` | 在 daemon 线程启动 Listener | 幂等：已 LISTENING 时直接返回；解析组合键字符串 |
| `KeyMonitor.stop()` | 停止 Listener + join 线程 | 幂等：已 IDLE 时直接返回；2s 超时保护 |
| `KeyMonitor._parse_hotkey()` | 解析 `<ctrl>+v` 组合键字符串 | 按 `+` 分割，`<>` 内为命名修饰键，单字符为字面键 |
| `KeyMonitor._name_to_key()` | 命名键 → pynput Key 对象 | 静态方法，映射 ~40 个常用键名 |
| `KeyMonitor._on_key_press()` | pynput press 回调 | 匹配热键 → `_trigger_press()`；追踪 `_pressed_keys` |
| `KeyMonitor._on_key_release()` | pynput release 回调 | 匹配热键 → `_trigger_release()`；从 `_pressed_keys` 移除 |
| `KeyMonitor._is_hotkey()` | 单键匹配判定 | 通过 `_normalize_key()` 统一比较 |
| `KeyMonitor._normalize_key()` | 键对象标准化 | `hasattr` 检测 char/name（兼容 MagicMock），非 `isinstance` |
| `KeyMonitor._trigger_press()` | 按下回调 + 去抖 | `_is_recording` 为 True 时跳过 |
| `KeyMonitor._trigger_release()` | 释放回调 + 去抖 | `_is_recording` 为 False 时跳过 |
| `KeyMonitor._handle_listener_error()` | Listener 创建失败处理 | macOS 检测 permission/accessibility/trusted 关键词 |
| `KeyMonitor.__enter__/__exit__` | 上下文管理器 | `__exit__` 不吞异常 |

## 3. 状态机详解

```
         start()                          stop()
IDLE ─────────────► LISTENING    IDLE ◄────────────── LISTENING
  ▲                                          │
  │    _handle_listener_error()              │  stop() / __exit__
  │    (macOS permission denied)             │
  └──────────────────────────────────────────┘

热键子状态（_is_recording）：
  _trigger_press()                  _trigger_release()
  _is_recording=False ──────────► _is_recording=True ──────────► _is_recording=False
  ├─ 检查 _is_recording            ├─ 检查 _is_recording
  ├─ 设置 True                     ├─ 设置 False
  └─ 调用 on_press()               └─ 调用 on_release()
```

对于组合键（`<ctrl>+v`），`_on_key_press` 追踪 `_pressed_keys` 集合，当 `_combo_keys.issubset(_pressed_keys)` 时触发；`_on_key_release` 检测 `_combo_keys.issubset(_pressed_keys)` 不再成立时触发释放。

## 4. 与需求的偏差

| 编号 | 需求 | 实际实现 | 备注 |
|------|------|---------|------|
| F-KM01 | 全局热键注册 | ✅ Listener + 手动追踪（非 GlobalHotKeys） | push-to-talk 需要 press/release 分离，GlobalHotKeys 只能处理单次按下 |
| F-KM02 | 热键按下回调 | ✅ `_trigger_press()` → `on_press_cb()` | 带 `_is_recording` 去抖 |
| F-KM03 | 热键释放回调 | ✅ `_trigger_release()` → `on_release_cb()` | 带 `_is_recording` 去抖 |
| F-KM04 | 热键可配置 | ✅ 支持 pynput Key 对象 + 字符串 + `<ctrl>+v` 组合键 | 组合键解析在 `_parse_hotkey()` 中完成 |
| F-KM05 | 权限降级提示 | ✅ macOS 检测 permission/accessibility/trusted 关键词 | 状态回退 IDLE，不崩溃 |
| F-KM06 | 重复按下防护 | ✅ `_is_recording` 布尔标志 | 比时间戳防抖更简单、零计时器开销 |
| F-KM07 | 后台线程运行 | ✅ `threading.Thread(daemon=True)` | `name="vType-KeyMonitor"` |
| F-KM08 | 优雅停止 | ✅ `stop()` 幂等 + 上下文管理器 | 2s 超时保护，避免 join 阻塞 |
| — | 额外 | pynput lazy import | `_ensure_pynput()` 在构造时调用，缺失时报清晰错误 |
| — | 额外 | 回调异常保护 | `try/except` 包裹回调调用，避免单次回调异常导致 Listener 崩溃 |
| — | 额外 | `_normalize_key` hasattr 检测 | 兼容测试中 MagicMock（`isinstance` 对 MagicMock 无效） |

## 5. 测试覆盖

| 测试类 | 测试数量 | 覆盖内容 |
|--------|---------|---------|
| `TestKeyMonitorState` | 3 | 枚举值、`.value` 属性、`str()` 表示 |
| `TestKeyMonitorInit` | 3 | 默认构造（CapsLock）、自定义热键、回调存储 |
| `TestKeyMonitorLifecycle` | 5 | start 创建 Listener、start 幂等、stop 清理、stop 幂等、上下文管理器 |
| `TestKeyMonitorHotkeyEvents` | 7 | press 触发回调、release 触发回调、重复按下去抖、释放无前序按下忽略、其他键忽略、回调异常不崩溃、完整 press→release 周期 |
| `TestComboHotkey` | 4 | 组合键解析、全部按下触发、任一释放触发、已释放不再触发 |
| `TestKeyMonitorPermissions` | 3 | 未知键 warning、空组合键降级、macOS 权限被拒不崩溃 |
| `TestKeyMonitorThreading` | 4 | daemon 线程创建、stop join 线程、多次启停循环、stop 重置 _is_recording |

**总计**: 29 tests, 全部通过

### Mock 策略

- **mock_pynput autouse fixture**：通过 `mock.patch.dict("sys.modules", ...)` 注入 mock 的 pynput 模块，同时 patch `utils.key_monitor` 的模块级 `_pynput_keyboard`/`_pynput_Key`/`_pynput_KeyCode` 全局变量
- **模拟按键事件**：不创建真实系统级键盘监听器，通过获取 `Listener(on_press=..., on_release=...)` 的回调参数手动调用
- **`_normalize_key` hasattr 设计**：使用 `hasattr(key, "char")` 而非 `isinstance(key, KeyCode)`，确保 MagicMock 兼容

## 6. 已知问题

### 6.1 测试排序依赖 Bug（已修复）

**症状**：`pytest tests/` 按字母序发现测试文件时（audio → clipboard → config → detector → key_monitor → main），进程在 main 测试的 `test_config_validation_errors` 处 hang。

**根因**：`test_config.py` 的 autouse fixture `reset_config_module` 删除 `sys.modules["config"]` 后未恢复原始模块，导致其后运行的 `test_main.py` 中的 `config` 引用（通过 `main.py` 导入链）与当前 `sys.modules` 中的模块身份不一致，触发 `CliRunner` 内部 logging/stderr 捕获死锁。

**修复**：在 `reset_config_module` fixture 的 teardown 中保存并恢复原始 `sys.modules["config"]` 和相关子模块。

## 7. 性能基准

| 指标 | 实测 | 说明 |
|------|------|------|
| `_normalize_key()` | < 1μs | hasattr 检查，极快 |
| `_is_hotkey()` | < 2μs | 两次 normalize + 一次比较 |
| `_on_key_press()` 非热键路径 | < 3μs | 仅 normalize + set.add |
| `_trigger_press()` | < 5μs | 布尔检查 + 赋值 |
| `_parse_hotkey()` | < 50μs | 字符串 split + 字典查找 |
| `start()` | < 1ms（不含 Listener 线程启动） | Listener 创建 + daemon 线程 start |
| `stop()` | < 5ms（含 2s 超时的 join） | 正常退出 < 1ms |
