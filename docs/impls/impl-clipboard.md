# Implementation Doc: M-08 utils/clipboard.py — 跨平台剪贴板操作封装

> 版本: v0.1.0 | 关联 Spec: docs/specs/feat-clipboard.md | 日期: 2026-05-23

## 1. 实现概述

`utils/clipboard.py` 封装 `pyperclip` 的跨平台剪贴板操作和 `pynput` 的粘贴快捷键模拟，为 `typer.py` 的粘贴兜底方案提供统一接口。采用薄门面模式，`typer.py` 不直接 import `pyperclip`，便于独立测试。

**核心设计亮点**：
- **薄门面**：`ClipboardManager` 仅 4 个公开方法，无多余抽象
- **graceful degradation**：`get_text()` 异常不崩溃，返回空字符串；`has_text()` 异常返回 False
- **平台透明**：`simulate_paste()` 自动检测 OS 选择 `Ctrl+V` 或 `Cmd+V`

## 2. 类与方法清单

| 类/方法 | 功能 | 关键决策 |
|---------|------|---------|
| `ClipboardError` | 基础异常类 | 继承 `Exception`，剪贴板所有异常的根 |
| `ClipboardManager.__init__()` | 验证 pyperclip 可用 | `_import_pyperclip()` 静态方法，ImportError 时抛出 ClipboardError |
| `ClipboardManager.copy(text)` | 文本复制到剪贴板 | 直接委托 `pyperclip.copy()` |
| `ClipboardManager.get_text()` | 读取剪贴板文本 | 非字符串内容返回 ""；pyperclip 异常包装为 ClipboardError |
| `ClipboardManager.has_text()` | 检测剪贴板有文本 | 调用 `get_text()` 并 bool 化；异常时返回 False |
| `ClipboardManager.simulate_paste()` | 发送 Ctrl/Cmd+V | 本地 import pynput，`with keyboard.pressed()` 上下文管理器 |

## 3. simulate_paste() 平台适配

```
platform.system()
    │
    ├── "Darwin"  → with keyboard.pressed(Key.cmd):  press("v")
    │
    └── "Windows" / "Linux"  → with keyboard.pressed(Key.ctrl):  press("v")
```

## 4. 与 Spec 偏差

| Spec | 实现 | 偏差原因 |
|------|------|---------|
| F-C01 copy | 完全一致 | — |
| F-C02 get_text | 额外处理非 str 返回值 | 防御性：pyperclip 可能返回 bytes |
| F-C03 has_text | 完全一致 | — |
| F-C04 simulate_paste | 增加 `time.sleep(0.01)` 释放间隙 | 避免连续粘贴时按键事件丢失 |
| F-C05 跨平台 | 完全一致 | — |

## 5. 测试覆盖

| 测试类 | 用例数 | 覆盖 |
|--------|--------|------|
| TestPyperclipImport | 2 | 正常导入 / ImportError → ClipboardError |
| TestCopy | 3 | 正常文本 / 空字符串 / 中文 |
| TestGetText | 4 | 正常 / 空 / 非字符串 / 异常 |
| TestHasText | 3 | True / False (空) / False (异常) |
| TestSimulatePaste | 4 | Windows Ctrl / macOS Cmd / Linux Ctrl / pynput ImportError |
| **合计** | **16** | |

## 6. M-05 ↔ M-08 协作

```
M-05 core/typer.py                    M-08 utils/clipboard.py
═══════════════════                    ═══════════════════════
TypeWriter.__init__()                  ClipboardManager()
  └─ self._clipboard = mgr               └─ _import_pyperclip()

TypeWriter._type_via_clipboard()
  ├─ mgr.get_text()                   → pyperclip.paste()
  ├─ mgr.copy(text)                   → pyperclip.copy(text)
  ├─ mgr.simulate_paste()             → pynput Ctrl/Cmd+V
  └─ mgr.copy(original)               → pyperclip.copy(original)
```
