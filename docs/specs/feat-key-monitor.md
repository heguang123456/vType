# Feature Spec: M-09 utils/key_monitor.py — 全局热键监听

> 版本: v0.1.0 | 状态: 设计阶段 | 关联: REQUIREMENTS.md §8.4 M-09

## 1. 功能概述

`utils/key_monitor.py` 是 vType 的全局热键监听模块。它通过 `pynput.keyboard.Listener` 在后台监听用户自定义的按键组合，实现按住即说（push-to-talk）交互模式。当用户在任意应用中按下热键时触发录音开始，松开时触发录音停止，无缝衔接语音输入流程。

与 CoreManager 联动：热键按下 → `manager.start()`，热键释放 → `manager.stop()`，将全局热键事件转化为 CoreManager 的生命周期调用。

## 2. 功能需求

| 编号 | 需求 | 优先级 | 验收标准 |
|------|------|--------|---------|
| F-KM01 | 全局热键注册 | P0 | 通过 `pynput.keyboard.GlobalHotKeys` 注册自定义按键组合（默认 CapsLock），监听全局按键事件 |
| F-KM02 | 热键按下回调 | P0 | 按下热键时触发 `on_press` 回调，调用 CoreManager.start() |
| F-KM03 | 热键释放回调 | P0 | 释放热键时触发 `on_release` 回调，调用 CoreManager.stop() |
| F-KM04 | 热键可配置 | P1 | 支持通过构造函数传入自定义热键字符串（如 `<ctrl>+<alt>+v`），不硬编码按键 |
| F-KM05 | 权限降级提示 | P1 | macOS 无辅助功能权限导致监听失败时，打印清晰的权限授予指引，不崩溃 |
| F-KM06 | 重复按下防护 | P1 | 快速连按热键时防止重复触发 start/stop，通过状态锁或去抖动实现 |
| F-KM07 | 后台线程运行 | P0 | `start()` 方法在独立线程中启动 Listener，不阻塞调用方 |
| F-KM08 | 优雅停止 | P0 | `stop()` 方法停止 Listener 并清理资源，支持 `with` 上下文管理器 |

## 3. 技术方案

### 3.1 按键监听机制

使用 `pynput.keyboard` 的两层 API：

1. **`pynput.keyboard.Listener`**：底层监听器，灵活但需手动管理按键状态
2. **`pynput.keyboard.GlobalHotKeys`**：高层热键封装，自动处理组合键匹配

本项目使用 **Listener + 手动按下/释放追踪** 方案（而非 GlobalHotKeys），原因：
- `GlobalHotKeys` 回调在按下瞬间触发一次，缺少持续的"按住"状态感知
- 按住即说模式需要区分"按下"和"释放"两个事件
- Listener 提供 `on_press(key)` 和 `on_release(key)` 两个独立钩子

### 3.2 状态机

```
      start()                      按下热键
IDLE ────────► LISTENING    IDLE ──────────► RECORDING
  ▲              │             ▲                │
  │    stop()    │             │  释放热键       │
  │◄─────────────┘             │◄───────────────┘
```

- **KeyMonitor 状态**：`IDLE` ↔ `LISTENING`（Listener 运行/停止）
- **热键状态**：`IDLE` → `RECORDING` → `IDLE`（热键按下/释放，与 CoreManager 联动）

### 3.3 去抖动策略

```
热键按下 → 检查 _is_recording
  ├── True  → 忽略（已在录音中）
  └── False → 设置 _is_recording=True，调用 callback.on_press()
  
热键释放 → 检查 _is_recording
  ├── False → 忽略（未在录音）
  └── True  → 设置 _is_recording=False，调用 callback.on_release()
```

使用布尔标志 `_is_recording` 实现简单去抖，防止操作系统重复发送按下事件时的多次触发。

### 3.4 热键规范

| 热键 | 类型 | 用途 | 默认值 |
|------|------|------|--------|
| push_to_talk | 按下/释放 | 按住说话，松开停止 | `Key.caps_lock` |
| toggle_pause | 按下切换 | 切换暂停/恢复（备用） | `None`（暂不启用） |

热键字符串格式遵循 `pynput` 约定：`<ctrl>+<alt>+v`、`<shift>+f1`，单键直接使用 `Key.caps_lock` 或字符 `'v'`。

## 4. 接口设计

### 4.1 公开类

```python
from enum import Enum
from pynput.keyboard import Key, KeyCode

class KeyMonitorState(Enum):
    """KeyMonitor 运行状态。"""
    IDLE = "idle"
    LISTENING = "listening"

class KeyMonitor:
    """全局热键监听器。
    
    在后台线程中监听按键的按下/释放事件，
    通过回调机制与 CoreManager 联动实现按住即说。
    
    Example:
        def on_press():
            manager.start()
        def on_release():
            manager.stop()
        
        with KeyMonitor(on_press, on_release) as km:
            km.start()
            # ... 应用主循环
    """
```

### 4.2 公开方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(on_press: Callable, on_release: Callable, hotkey: str \| Key = Key.caps_lock)` | 构造监听器，注册按键回调 |
| `start()` | `-> None` | 在后台线程启动 Listener |
| `stop()` | `-> None` | 停止 Listener，join 线程 |
| `is_listening` | `-> bool (property)` | 是否正在监听 |
| `is_recording` | `-> bool (property)` | 热键是否当前被按住（录音中） |
| `state` | `-> KeyMonitorState (property)` | 当前状态 |

### 4.3 异常类

```python
class KeyMonitorError(Exception):
    """KeyMonitor 基础异常。"""
    pass

class KeyMonitorPermissionError(KeyMonitorError):
    """权限不足异常（macOS 辅助功能权限未授予）。"""
    pass
```

### 4.4 上下文管理器

```python
def __enter__(self) -> "KeyMonitor":
    return self

def __exit__(self, exc_type, exc_val, exc_tb) -> None:
    self.stop()
```

## 5. 回调约定

### 5.1 回调签名

```python
on_press: Callable[[], None]    # 热键按下时调用，无参数无返回值
on_release: Callable[[], None]  # 热键释放时调用，无参数无返回值
```

### 5.2 回调线程安全

- 回调在 `pynput.Listener` 的线程中执行（即 `on_press`/`on_release` 线程）
- 回调方（CoreManager）需保证自身方法是线程安全的（CoreManager 已实现 `threading.Lock` 保护状态）
- KeyMonitor 不对回调做额外线程包装，保持零开销

## 6. 权限处理

### 6.1 平台检测

```python
import platform

if platform.system() == "Darwin":
    # macOS: 检查辅助功能权限
    # - 有权限: 正常使用 Listener
    # - 无权限: 抛出 KeyMonitorPermissionError，但 start() 不崩溃
    pass
```

### 6.2 降级策略

| 平台 | 权限不足时行为 |
|------|--------------|
| **Windows** | 通常无需额外权限，`Listener` 直接可用 |
| **macOS** | 打印清晰指引（系统偏好设置 → 安全性与隐私 → 辅助功能 → 添加终端/iTerm），`start()` 返回并记录 warning |
| **Linux** | 可能需要 `input` 组权限，`Listener` 抛异常时记录 warning |

### 6.3 macOS 权限指引

权限不足时输出：

```
⚠️  pynput 需要「辅助功能」权限才能监听全局热键。

授权步骤：
1. 打开「系统设置」→「隐私与安全性」→「辅助功能」
2. 点击 + 号，找到并添加你的终端应用（Terminal / iTerm）
3. 确保开关已开启
4. 重新 запустить vType

当前将在无热键模式下运行。可使用 Ctrl+C 手动控制。
```

## 7. 测试计划

| 测试类 | 用例数 | 覆盖内容 |
|--------|--------|---------|
| `TestKeyMonitorState` | 2 | 枚举值、字符串表示 |
| `TestKeyMonitorInit` | 3 | 默认构造、自定义热键、回调注册 |
| `TestKeyMonitorLifecycle` | 4 | start/stop、上下文管理器、重复 start 幂等 |
| `TestKeyMonitorHotkeyEvents` | 5 | 按下回调、释放回调、去抖、未注册按键忽略 |
| `TestKeyMonitorPermissions` | 2 | macOS 权限错误不崩溃、权限指引输出 |
| `TestKeyMonitorThreading` | 3 | 后台线程运行、stop join、多次启停 |

**预计总计：~19 个测试**

### Mock 策略

- Mock `pynput.keyboard.Listener` 实例，通过手动调用 `on_press(key)` / `on_release(key)` 模拟按键事件
- Mock `pynput.keyboard.Key` 枚举值（`Key.caps_lock` 等）
- Mock `platform.system()` 返回值测试权限分支
- 不创建真实的系统级键盘监听器

## 8. 依赖与前置条件

| 依赖 | 说明 |
|------|------|
| `pynput` (≥ 1.7.6) | 键盘监听底层 API |
| `threading` (stdlib) | 后台线程 |
| `logging` (stdlib) | 日志输出 |
| `enum` (stdlib) | 状态枚举 |
| `platform` (stdlib) | 系统检测 |

无内部模块依赖（M-09 是独立工具模块，不依赖 core/*）。

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| macOS 权限被拒 | 中 | 热键不可用，用户需手动控制 | 权限指引 + 降级运行 |
| pynput 版本兼容 | 低 | Listener API 变更 | 锁定 pynput ≥ 1.7.6 |
| 快速连按抖动 | 中 | 重复触发 start/stop | `_is_recording` 布尔去抖 |
| CapsLock 键行为变更 | 低 | 系统可能切换大写锁定状态 | 文档提示用户可选其他键 |
| Linux X11/Wayland | 低 | Wayland 下全局监听受限 | 文档注明 Linux 推荐 X11 |

## 10. 与 CoreManager 的集成模式

```
┌──────────────────┐        ┌─────────────────┐
│   KeyMonitor     │  回调   │  CoreManager    │
│                  │───────►│                  │
│ on_press() ──────┼─ start()│                  │
│ on_release() ────┼─ stop() │                  │
│                  │         │                  │
│ 线程: listener   │         │ 线程: 主         │
└──────────────────┘        └─────────────────┘
```

集成在 `main.py` 中进行：
1. 创建 `CoreManager` 实例
2. 创建 `KeyMonitor(on_press=manager.start, on_release=manager.stop)`
3. `key_monitor.start()` 启动后台监听
4. 主线程进入 `key_monitor._listener.join()` 等待（或 `signal.pause()`）
