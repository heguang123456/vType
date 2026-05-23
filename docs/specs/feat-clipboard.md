# Feature Spec: M-08 utils/clipboard.py — 跨平台剪贴板操作封装

> 版本: v0.1.0 | 状态: 设计阶段 | 关联: REQUIREMENTS.md §8.3 M-08, M-05

## 1. 功能概述

`utils/clipboard.py` 封装了 `pyperclip` 的跨平台剪贴板操作，为 `typer.py` 的粘贴兜底方案提供统一接口。核心职责：
- **copy/paste 基础操作**：`pyperclip.copy()` / `pyperclip.paste()` 封装
- **粘贴快捷键模拟**：跨平台 `Ctrl/Cmd+V` 按键发送（用于 typer 粘贴后恢复光标焦点）
- **内容保护**：保存/恢复原始剪贴板内容，避免数据丢失

## 2. 功能需求

| 编号 | 需求 | 优先级 | 验收标准 |
|------|------|--------|---------|
| F-C01 | 文本复制到剪贴板 | P0 | `copy(text)` 调用后，系统剪贴板内容 = text |
| F-C02 | 读取剪贴板文本 | P0 | `get_text()` 返回当前剪贴板文本内容；空时返回 `""` |
| F-C03 | 检测剪贴板有文本 | P1 | `has_text()` 返回 True/False |
| F-C04 | 粘贴快捷键模拟 | P0 | `simulate_paste()` 发送 `Ctrl+V`（Windows/Linux）或 `Cmd+V`（macOS） |
| F-C05 | 跨平台快捷键 | P0 | 自动检测 OS 选择正确的修饰键 |

## 3. 技术方案

### 3.1 ClipboardManager 类

```python
class ClipboardManager:
    """Cross-platform clipboard operations wrapper for typer fallback."""

    def __init__(self) -> None:
        """Initialize clipboard access.

        Note: pyperclip auto-detects the best backend:
        - Windows: win32clipboard
        - macOS: pbcopy/pbpaste (subprocess)
        - Linux: xclip/xsel (subprocess)
        """

    def copy(self, text: str) -> None:
        """Copy text to system clipboard.

        Args:
            text: Text content to copy.
        """

    def get_text(self) -> str:
        """Get current clipboard text content.

        Returns:
            Clipboard text. Empty string if clipboard is empty
            or contains non-text content.
        """

    def has_text(self) -> bool:
        """Check if clipboard contains text content."""

    def simulate_paste(self) -> None:
        """
        Simulate Ctrl+V (Windows/Linux) or Cmd+V (macOS) keystroke.

        Uses pynput.keyboard.Controller to press and release
        the platform-appropriate paste shortcut.
        This requires pynput keyboard simulation permissions
        (same as typer's _type_via_pynput).
        """
```

### 3.2 粘贴快捷键实现

```python
def simulate_paste(self) -> None:
    from pynput.keyboard import Controller, Key

    keyboard = Controller()

    if platform.system() == "Darwin":
        # macOS: Cmd+V
        with keyboard.pressed(Key.cmd):
            keyboard.press("v")
            keyboard.release("v")
    else:
        # Windows / Linux: Ctrl+V
        with keyboard.pressed(Key.ctrl):
            keyboard.press("v")
            keyboard.release("v")
```

### 3.3 pyperclip 后端自动检测

```
pyperclip 根据 OS 自动选择后端：
  Windows  → win32clipboard (ctypes 调用 Win32 API)
  macOS    → pbcopy/pbpaste (subprocess)
  Linux    → xclip 或 xsel (subprocess)
             如无可用 → gtk/gtk3/PyQt5 Clipboard
```

## 4. 边界条件

| 场景 | 行为 |
|------|------|
| 剪贴板为空 | `get_text()` 返回 `""` |
| 剪贴板含非文本（图片等） | `get_text()` 返回 `""` 或 pyperclip 抛异常（捕获后返回 `""`） |
| pyperclip 后端不可用 | `__init__` 抛出 `ClipboardError`，含安装提示 |
| Linux 无 xclip/xsel | `__init__` 抛出 `ClipboardError`，提示安装 `sudo apt install xclip` |

## 5. 自定义异常

```python
class ClipboardError(Exception):
    """Base exception for clipboard errors."""
```

## 6. 测试计划

| 测试场景 | Mock 策略 | 验证点 |
|---------|----------|--------|
| copy 调用 | Mock `pyperclip.copy()` | 验证传入正确的 text |
| get_text 正常 | Mock `pyperclip.paste()` 返回固定文本 | 验证返回值正确 |
| get_text 空 | Mock `pyperclip.paste()` 返回 `""` | 验证返回 `""` |
| get_text 异常 | Mock `pyperclip.paste()` 抛异常 | 验证返回 `""` 不崩溃 |
| has_text True | Mock `pyperclip.paste()` 返回非空文本 | 验证返回 `True` |
| has_text False | Mock `pyperclip.paste()` 返回 `""` | 验证返回 `False` |
| simulate_paste Windows | Mock `platform.system()` → `"Windows"`，Mock `Controller` | 验证 `Ctrl+V` 被发送 |
| simulate_paste macOS | Mock `platform.system()` → `"Darwin"`，Mock `Controller` | 验证 `Cmd+V` 被发送 |
| simulate_paste Linux | Mock `platform.system()` → `"Linux"`，Mock `Controller` | 验证 `Ctrl+V` 被发送 |
| pyperclip 不可用 | Mock `import pyperclip` 失败 | 验证抛出 `ClipboardError` |

## 7. 依赖

### Python 包
- `pyperclip` ≥ 1.8.2（跨平台剪贴板访问）
- `pynput` ≥ 1.7.6（simulate_paste 的快捷键发送）

### 被依赖
- `core/typer.py`（M-05）：粘贴兜底方案的剪贴板操作
