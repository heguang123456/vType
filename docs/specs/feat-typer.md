# Feature Spec: M-05 core/typer.py — 键盘模拟输出

> 版本: v0.1.0 | 状态: 设计阶段 | 关联: REQUIREMENTS.md §8.3 M-05, M-08

## 1. 功能概述

`typer.py` 是消费者线程的后半段，负责从 `result_queue` 获取 ASR 识别的文本，通过操作系统底层 API 将文本逐字输入到当前焦点应用的**光标位置**。核心策略：**pynput 主方案 + 剪贴板粘贴兜底**。

- **pynput 主方案**：调用 OS 底层键盘事件 API（Windows `SendInput` / macOS `CGEvent` / Linux `Xlib`），逐字符模拟键盘输入，带 5ms 字符间延迟
- **剪贴板兜底**：当 pynput 因权限被拒（macOS `CGEvent` 需辅助功能权限）时，自动降级为 `pyperclip.copy()` + `Ctrl/Cmd+V` 粘贴方案

与 M-08 `utils/clipboard.py` 的关系：M-08 封装了跨平台剪贴板的 copy/paste/simulate_paste 操作，M-05 通过 M-08 调用剪贴板兜底。

## 2. 功能需求

| 编号 | 需求 | 优先级 | 验收标准 |
|------|------|--------|---------|
| F-T01 | pynput 逐字输入 | P0 | 调用 `pynput.keyboard.Controller.type()` 逐字符输出，字符间延迟 = `TYPE_DELAY`（默认 5ms） |
| F-T02 | 剪贴板降级 | P0 | `type_text()` 中 try-except 捕获 `PermissionError`/`OSError`，自动切换到剪贴板粘贴方案 |
| F-T03 | 剪贴板恢复 | P0 | 粘贴兜底完成后，恢复原始剪贴板内容（保存→粘贴→恢复） |
| F-T04 | 跨平台快捷键 | P0 | 粘贴兜底自动识别 OS：Windows/Linux 用 `Ctrl+V`，macOS 用 `Cmd+V` |
| F-T05 | 消费者主循环 | P0 | `run(result_queue, stop_event)` 阻塞等待识别文本，调用 `type_text()` 输出 |
| F-T06 | 空文本处理 | P1 | 空字符串/None/纯空格文本直接跳过，不执行任何输入操作 |
| F-T07 | 可配置延迟 | P1 | 支持 `TYPE_DELAY` 覆盖（env: `VTYPE_TYPE_DELAY`），范围 0-0.1s |
| F-T08 | 降级开关 | P1 | `CLIPBOARD_FALLBACK=False` 时禁用剪贴板降级，pynput 失败直接抛异常 |

## 3. 技术方案

### 3.1 数据流

```
result_queue (Queue[str])
    │
    ▼
TypeWriter.run() 消费者主循环
    │
    ▼
TypeWriter.type_text(text: str)
    │
    ├── pynput 可用 ──► _type_via_pynput(text)
    │                      │ pynput.keyboard.Controller.type(text)
    │                      │ 字符间 sleep(TYPE_DELAY)
    │                      ▼
    │                    文本逐字出现在光标位置
    │
    └── pynput 失败 ──► _type_via_clipboard(text)
                           │
                           ├── 1. clipboard.save() → 保存原始内容
                           ├── 2. clipboard.copy(text)
                           ├── 3. clipboard.simulate_paste()
                           │      └── pynput 按 Ctrl/Cmd+V
                           ├── 4. clipboard.restore() → 恢复原始内容
                           │
                           ▼
                          文本一次性粘贴到光标位置
```

### 3.2 TypeWriter 类设计

```python
class TypeWriter:
    """
    Keyboard output engine (consumer thread - second half).

    Retrieves recognized text from result_queue and types it
    at the current cursor position using pynput keyboard simulation.
    Falls back to clipboard paste when pynput permission is denied.
    """

    def __init__(
        self,
        type_delay: float = 0.005,       # 5ms character spacing
        clipboard_fallback: bool = True,  # enable clipboard fallback
    ) -> None:
        """Initialize keyboard controller and clipboard manager."""

    def type_text(self, text: str) -> None:
        """
        Type text at current cursor position.

        Primary: pynput.keyboard.Controller.type()
        Fallback: clipboard paste (if CLIPBOARD_FALLBACK enabled)

        Args:
            text: Recognized text from ASR engine.

        Raises:
            TypeWriterError: If both pynput and clipboard fallback fail.
        """

    def _type_via_pynput(self, text: str) -> None:
        """
        Simulate keyboard input character by character.

        Uses pynput.keyboard.Controller.type() with TYPE_DELAY
        between each character to prevent OS-level rate limiting.
        """

    def _type_via_clipboard(self, text: str) -> None:
        """
        Fallback: copy text to clipboard and simulate Ctrl/Cmd+V.

        Saves original clipboard content before pasting and
        restores it after paste completes to avoid data loss.
        """

    def run(
        self,
        result_queue: queue.Queue,
        stop_event: threading.Event,
    ) -> None:
        """
        Consumer main loop (second half).

        Blocks on result_queue for recognized text,
        outputs via type_text(), and loops until stop_event is set.

        Args:
            result_queue: Queue of recognized text strings from Recognizer.
            stop_event: Signals graceful shutdown.
        """
```

### 3.3 自定义异常

```python
class TypeWriterError(Exception):
    """Base exception for typewriter errors."""

class TypeWriterPermissionError(TypeWriterError):
    """Pynput permission denied and clipboard fallback is disabled."""
```

### 3.4 pynput 逐字输入实现细节

```python
def _type_via_pynput(self, text: str) -> None:
    # pynput.Controller.type() 内部逐字符处理：
    # - 普通字符：直接 press + release 对应键
    # - 大写字母：press Shift + press char + release Shift
    # - 特殊字符（如 !@#）：自动处理 Shift 修饰键
    # - 中文文本：直接模拟 Unicode 字符输入
    self._keyboard.type(text)

    # 注意：pynput 的 type() 不做字符间延迟，
    # 在文本较长时可能导致 OS 输入缓冲区溢出。
    # 以下方案按需选择：
    #
    # 方案 A（默认）：逐字 type() + sleep
    # for char in text:
    #     self._keyboard.type(char)
    #     time.sleep(self._type_delay)
    #
    # 方案 B（快速）：type() 整段文本
    # self._keyboard.type(text)
    #
    # 方案 A 更安全但慢，方案 B 快但有溢出风险。
    # v0.1 默认采用方案 A，后续可通过配置切换。
```

### 3.5 剪贴板兜底实现细节

```python
def _type_via_clipboard(self, text: str) -> None:
    if not self._clipboard_fallback:
        raise TypeWriterPermissionError(
            "pynput permission denied and CLIPBOARD_FALLBACK is disabled"
        )

    # Step 1: Save original clipboard content
    original = self._clipboard.get_text()

    try:
        # Step 2: Copy recognized text to clipboard
        self._clipboard.copy(text)

        # Step 3: Simulate paste shortcut
        self._clipboard.simulate_paste()

        # Step 4: Brief delay to let paste complete
        time.sleep(0.1)
    finally:
        # Step 5: Restore original clipboard content
        if original:
            self._clipboard.copy(original)
```

### 3.6 M-08 `utils/clipboard.py` 接口约定

`typer.py` 依赖 `utils/clipboard.py` 的以下接口：

```python
class ClipboardManager:
    """Cross-platform clipboard operations wrapper."""

    def copy(self, text: str) -> None:
        """Copy text to system clipboard via pyperclip."""

    def get_text(self) -> str:
        """Get current clipboard text content. Returns '' if empty."""

    def simulate_paste(self) -> None:
        """
        Simulate Ctrl+V (Windows/Linux) or Cmd+V (macOS) keystroke
        using pynput to paste current clipboard content at cursor.
        """

    def has_text(self) -> bool:
        """Check if clipboard contains text content."""
```

## 4. 跨平台适配

| 平台 | 主方案 | API | 权限要求 | 兜底方案 |
|------|--------|-----|---------|---------|
| Windows | `pynput` (SendInput) | Win32 API | 无需额外权限 | `Ctrl+V` 粘贴 |
| macOS | `pynput` (CGEvent) | Quartz Event Services | **需辅助功能权限** | `Cmd+V` 粘贴 |
| Linux | `pynput` (Xlib/uinput) | X11 / uinput | 可能需要 input 组 | `Ctrl+V` 粘贴 |

**macOS 权限处理**：
- `CGEventPost` 权限被拒时抛出 `OSError`（macOS 10.14+）
- 捕获后自动降级为剪贴板方案
- 首次运行时若降级，终端输出授权指引：
  ```
  ⚠ pynput keyboard simulation requires Accessibility permission.
    Go to: System Settings → Privacy & Security → Accessibility
    Add your terminal application and enable the toggle.
  ```

## 5. 消费者主循环设计

```python
def run(self, result_queue, stop_event):
    while not stop_event.is_set():
        try:
            text = result_queue.get(timeout=0.2)
            if text and text.strip():
                self.type_text(text)
        except queue.Empty:
            continue
        except TypeWriterError as e:
            logger.error("TypeWriter error: %s", e)
        except Exception as e:
            logger.error("Unexpected typewriter error: %s", e)
```

## 6. 边界条件与异常处理

| 场景 | 行为 |
|------|------|
| 空文本 `""` | 跳过，不执行任何操作 |
| 纯空格 `"   "` | 跳过（`text.strip()` 为空） |
| 文本含 `None` | `type_text()` 入口处 `if not text: return` |
| pynput 正常 | 逐字输入，字符间 `sleep(TYPE_DELAY)` |
| pynput `PermissionError` | 降级剪贴板，输出 warning 日志 |
| pynput `OSError` | 降级剪贴板（含 macOS CGEvent 权限错误） |
| pynput 失败 + 降级禁用 | 抛出 `TypeWriterPermissionError` |
| pyperclip 不可用 | 抛出 `TypeWriterError`，含安装提示 |
| 剪切板粘贴 `Ctrl+V` 失败 | 抛出 `TypeWriterError` |
| 原始剪贴板为空 | 跳过保存/恢复步骤 |
| `stop_event` 被设置 | 循环退出，不阻塞 |

## 7. 测试计划

| 测试场景 | Mock 策略 | 验证点 |
|---------|----------|--------|
| type_text 正常 pynput | Mock `pynput.keyboard.Controller.type()` | 验证调用参数正确 |
| type_text 空文本 | 不 mock | 验证跳过，未调用任何输入方法 |
| type_text 纯空格 | 不 mock | 验证跳过 |
| type_text None | 不 mock | 验证跳过 |
| type_text pynput → 剪贴板降级 | Mock `Controller.type()` 抛 `PermissionError`，Mock `ClipboardManager` | 验证降级链路：save → copy → paste → restore |
| type_text 降级 + 原始剪贴板为空 | Mock `ClipboardManager.get_text()` 返回 `""` | 验证跳过 save/restore |
| type_text 降级已禁用 | `CLIPBOARD_FALLBACK=False`，Mock `Controller.type()` 抛 `PermissionError` | 验证抛出 `TypeWriterPermissionError` |
| type_text 逐字 sleep 间隔 | Mock `Controller.type()`，Mock `time.sleep()` | 验证 `sleep(TYPE_DELAY)` 被调用 |
| run 主循环正常 | Mock `result_queue` 有数据 | 验证 `type_text()` 被调用 |
| run 主循环 queue.Empty | Mock `result_queue.get()` 抛 `queue.Empty` | 验证 `continue` 不退出 |
| run 主循环 stop_event | 设置 `stop_event` | 验证循环退出 |
| run 主循环异常处理 | Mock `type_text()` 抛异常 | 验证日志记录 + 循环继续 |
| 跨平台快捷键 | Mock `platform.system()` 返回值 | macOS → Cmd；Windows/Linux → Ctrl |

## 8. 依赖与前置条件

### 项目内依赖
- `config.py`：`TYPE_DELAY`、`CLIPBOARD_FALLBACK`
- `utils/clipboard.py`（M-08）：`ClipboardManager` 剪贴板操作

### Python 包依赖
- `pynput` ≥ 1.7.6（键盘模拟 + 快捷键发送）
- `pyperclip` ≥ 1.8.2（剪贴板访问，由 M-08 封装）

### 被依赖关系
- `core/manager.py`（M-06）：创建 `TypeWriter` 实例并启动消费者线程的后半段

## 9. 与 M-08 的协作模式

```
M-05 core/typer.py                    M-08 utils/clipboard.py
═══════════════════                    ═══════════════════════
TypeWriter.__init__()  ──────────────► ClipboardManager()
                         创建实例
TypeWriter._type_via_    ─────────────► clipboard.copy(text)
  clipboard(text)                     ► clipboard.get_text()
                                      ► clipboard.simulate_paste()
```

M-05 不直接 import `pyperclip`，所有剪贴板操作通过 M-08 的 `ClipboardManager` 间接调用。这样：
- M-08 可独立测试剪贴板逻辑
- M-05 的测试可完全 Mock `ClipboardManager`，无需真实剪贴板

## 10. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| macOS 辅助功能权限被拒 | 高（首次运行） | 中（自动降级） | 剪贴板兜底 + 终端输出授权指引 |
| pynput 与某些应用不兼容 | 低 | 中 | 剪贴板兜底覆盖 |
| 剪贴板粘贴被安全软件拦截 | 低 | 中 | 输出 error 日志，提示用户检查安全软件 |
| 中文输入法干扰 pynput | 中 | 中 | 建议用户切换到英文输入法；`type()` 模拟 Unicode 字符绕过输入法 |
| 长文本（>1000 字）粘贴延迟 | 低 | 低 | `time.sleep(0.1)` 缓冲区；可配置延迟时间 |
| 剪贴板恢复失败导致内容丢失 | 低 | 高 | `finally` 块确保恢复；恢复失败时输出 warning |
| Linux uinput 权限不足 | 中 | 低 | 剪贴板兜底 + 终端输出 `sudo usermod -aG input $USER` 提示 |
