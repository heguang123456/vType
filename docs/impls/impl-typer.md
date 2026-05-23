# Implementation Doc: M-05 core/typer.py — 键盘模拟输出引擎

> 版本: v0.1.0 | 关联 Spec: docs/specs/feat-typer.md | 日期: 2026-05-23

## 1. 实现概述

`core/typer.py` 实现消费者线程的后半段：从 `result_queue` 获取 ASR 识别的文本，通过 pynput 键盘模拟输出到当前光标位置，权限失败时自动降级为剪贴板粘贴方案。

**核心设计亮点**：
- **双路径策略**：pynput 主路径（逐字输入，5ms 间隙）+ 剪贴板兜底（save→copy→paste→restore）
- **内容保护**：剪贴板兜底前保存原始内容，`finally` 块确保恢复，避免用户数据丢失
- **鲁棒性边界处理**：空字符串/None/纯空格三重跳过，main 循环三态异常分类处理
- **模块解耦**：剪贴板操作委托给 M-08 `ClipboardManager`，typer.py 本身不直接 import `pyperclip`

## 2. 类与方法清单

| 类/方法 | 功能 | 关键决策 |
|---------|------|---------|
| `TypeWriterError` | 基础异常类 | 继承 `Exception`，所有输出引擎异常的根 |
| `TypeWriterPermissionError` | 权限被拒 + 降级禁用异常 | 继承 `TypeWriterError`，CLIPBOARD_FALLBACK=False 触发 |
| `TypeWriter.__init__()` | 初始化 pynput Controller + ClipboardManager | `_create_keyboard_controller()` 静态方法，pynput 未安装时抛 TypeWriterError |
| `TypeWriter.type_text()` | 主入口：分级输出 | None/空/纯空格跳过 → pynput 逐字 → 权限异常降级剪贴板 |
| `TypeWriter._type_via_pynput()` | pynput 逐字输入 | `for char in text: controller.type(char); sleep(TYPE_DELAY)` |
| `TypeWriter._type_via_clipboard()` | 剪贴板兜底 | save→copy→simulate_paste→restore，`finally` 确保恢复 |
| `TypeWriter.run()` | 消费者主循环 | `queue.Empty` 超时 0.2s，三层异常分类（TypeWriterError / Exception / 正常） |

## 3. type_text() 数据流详解

```
type_text(text)
    │
    ├── not text or not text.strip()  → return (skip)
    │
    └── try _type_via_pynput(text)
            │
            ├── 成功  → 文本逐字出现在光标位置
            │
            └── PermissionError / OSError
                    │
                    ├── CLIPBOARD_FALLBACK=False  → raise TypeWriterPermissionError
                    │
                    └── CLIPBOARD_FALLBACK=True  → _type_via_clipboard(text)
                            │
                            ├── 1. original = clipboard.get_text()
                            ├── 2. clipboard.copy(text)
                            ├── 3. clipboard.simulate_paste()
                            ├── 4. time.sleep(0.1)
                            └── 5. finally: clipboard.copy(original)  [if original]
```

## 4. 消费者主循环设计

```python
def run(self, result_queue, stop_event):
    while not stop_event.is_set():
        try:
            text = result_queue.get(timeout=0.2)
            if text and text.strip():
                self.type_text(text)
        except queue.Empty:
            continue                              # idle, no text to output
        except TypeWriterError as e:
            logger.error("TypeWriter error: %s", e)  # known error, continue
        except Exception:
            logger.exception("Unexpected typewriter error")  # unknown, log & continue
```

## 5. 与 Spec 偏差

| Spec | 实现 | 偏差原因 |
|------|------|---------|
| F-T01 逐字输入 | 完全一致 | — |
| F-T02 剪贴板降级 | 额外捕获 `OSError`（macOS CGEvent） | macOS 权限被拒可能抛 OSError 而非 PermissionError |
| F-T03 剪贴板恢复 | `finally` 块确保恢复，失败仅 warning | 防御性：恢复失败不应阻断主流程 |
| F-T04 跨平台 | 完全一致（委托 M-08） | — |
| F-T05 消费者循环 | 完全一致 | — |
| F-T06 空文本 | None/空/纯空格三重检查 | `text.strip()` 覆盖 "   " 和 "\n\t" |
| F-T07 可配置延迟 | 完全一致 | `TYPE_DELAY` 在 `__init__` 参数中 |
| F-T08 降级开关 | 完全一致 | `CLIPBOARD_FALLBACK=False` 时 `_clipboard=None` |

## 6. 测试覆盖

| 测试类 | 用例数 | 覆盖 |
|--------|--------|------|
| TestTypeTextPynput | 3 | 正常英文 / 中文 / 标点混合 |
| TestTypeTextEmpty | 4 | None / 空字符串 / 纯空格 / 换行空白 |
| TestTypeTextFallback | 5 | PermissionError 降级 / OSError 降级 / 原始恢复 / 空原始跳过恢复 / 降级禁用抛异常 |
| TestPynputDelay | 1 | sleep(TYPE_DELAY) 逐字符调用 |
| TestRunLoop | 5 | 正常处理 / queue.Empty 继续 / stop_event 退出 / TypeWriterError 日志继续 / 空文本跳过 |
| TestInit | 2 | 默认值 / clipboard_fallback=False 时 _clipboard=None |
| **合计** | **20** | |

## 7. 跨平台适配

| 平台 | 主方案 | 降级方案 | 权限要求 |
|------|--------|---------|---------|
| Windows | pynput SendInput | Clipboard Ctrl+V | 无需额外权限 |
| macOS | pynput CGEvent | Clipboard Cmd+V | 需辅助功能权限 |
| Linux | pynput Xlib/uinput | Clipboard Ctrl+V | 可能需要 input 组 |

## 8. M-05 ↔ M-08 依赖图

```
M-05 core/typer.py                    M-08 utils/clipboard.py
═══════════════════                    ═══════════════════════
TypeWriter.__init__()
  │
  ├─ _create_keyboard_controller()     → pynput.keyboard.Controller
  │
  └─ ClipboardManager()                ──► ClipboardManager.__init__()
                                          │
TypeWriter._type_via_pynput()          ──► controller.type(char)
TypeWriter._type_via_clipboard()       ──► mgr.get_text()
                                      ──► mgr.copy(text)
                                      ──► mgr.simulate_paste()
                                      ──► mgr.copy(original)
```
