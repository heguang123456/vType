# vType — 命令行语音输入法

> **Command-line voice typing tool | CLI Voice Input**

[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue?logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)
[![Phase 3](https://img.shields.io/badge/phase-3%20完成-brightgreen)](#-phase-1--基础设施)

**vType** 是一款完全运行在本地、轻量级、跨平台的命令行语音输入工具。对着麦克风说话，识别出的文字会自动输出到当前光标位置——就像用声音驱动的虚拟键盘。

专为 **Vibe Coding** 工作流设计：高内聚、低耦合、极致 CPU 优化、零网络依赖。

---

## 目录

- [特性](#特性)
- [架构设计](#架构设计)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [安装指南](#安装指南)
- [使用说明](#使用说明)
- [配置参数](#配置参数)
- [开发指南](#开发指南)
- [路线图](#路线图)
- [许可证](#许可证)

---

## 特性

- **100% 本地运行**：无需云端 API，无需网络连接，所有处理均在 CPU 上完成。
- **跨平台支持**：Windows（SendInput）、macOS（CGEvent）、Linux（Xlib），均配备剪贴板兜底方案。
- **低延迟设计**：生产者-消费者双线程架构，推理期间不丢音频帧。
- **CPU 极致优化**：`faster-whisper` + `int8` 量化，相比标准 Whisper 内存占用降低 4 倍。
- **智能人声检测**：Google WebRTC VAD，基于静音检测的自动切片与防抖机制。
- **优雅降级**：当操作系统权限被拒绝时，自动切换为剪贴板粘贴方案。
- **环境变量覆盖**：所有参数均可通过 `VTYPE_*` 环境变量自定义。

---

## 架构设计

### 生产者-消费者双线程模型

```
┌─────────────────────────────────────────────────────────┐
│                     线程 A（生产者）                       │
│                                                         │
│  麦克风 ──► sounddevice InputStream ──► 原始音频队列       │
│                                            │             │
│                                            ▼             │
│                              webrtcvad VAD（20ms 帧）     │
│                                            │             │
│                                ┌───────────┴───────────┐ │
│                                │  监听 ↔ 录制            │ │
│                                └───────────┬───────────┘ │
│                                            │             │
│                            静音切片（800ms 阈值）         │
│                                      │                   │
└──────────────────────────────────────┼───────────────────┘
                                       │
                              任务队列（线程安全）
                                       │
┌──────────────────────────────────────┼───────────────────┐
│                     线程 B（消费者）                       │
│                                      ▼                   │
│                   faster-whisper（int8, CPU）            │
│                                      │                   │
│                               识别出的文字                 │
│                                      │                   │
│                    ┌─────────────────┴─────────────────┐ │
│                    │ 空闲 ↔ 转写中 ↔ 输出中              │ │
│                    └─────────────────┬─────────────────┘ │
│                                      │                   │
│              pynput 键盘控制 / 剪贴板粘贴                  │
│                                      │                   │
│                               光标处输出                  │
└─────────────────────────────────────────────────────────┘
```

### 关键设计决策

| 决策 | 理由 |
|------|------|
| 回调内极简执行（< 50μs） | 音频回调中仅做 `copy + put_nowait`，零计算 |
| 20ms 滑动窗口 | WebRTC VAD 原生帧长，微秒级推理 |
| int8 量化 | 内存降低 4 倍，CPU 推理加速 2-3 倍 |
| 静音防抖（800ms） | 防止句中短暂停顿被误切分 |
| 剪贴板兜底 | macOS 辅助功能权限被拒时，降级为 `Cmd+V` 粘贴 |

---

## 技术栈

| 层级 | 库 | 用途 |
|------|-----|------|
| 音频采集 | `sounddevice`（PortAudio） | 硬件麦克风流 → NumPy 数组 |
| 人声检测 | `webrtcvad` / `webrtcvad-wheels` | Google VAD 算法，微秒级推理 |
| 语音识别 | `faster-whisper`（CTranslate2） | Whisper C++ 移植，int8 CPU 推理 |
| 键盘模拟 | `pynput` | Windows `SendInput` / macOS `CGEvent` / Linux Xlib |
| 剪贴板兜底 | `pyperclip` | 跨平台剪贴板访问 |
| CLI 框架 | `click` | 命令行参数解析 |
| 测试框架 | `pytest` + `pytest-mock` | 单元测试与 mock 支持 |
| 代码质量 | `ruff` + `mypy` | 代码规范检查与静态类型检查 |

---

## 项目结构

```
vType/
├── README.md                    # 项目说明（本文件）
├── REQUIREMENTS.md              # 详细需求规格文档
├── prompt.md                    # 原始项目定义
├── config.py                    # 全局配置中心（17 个常量）
├── main.py                      # M-07：CLI 入口（click 框架）
├── requirements.txt             # 生产依赖
├── requirements-dev.txt         # 开发依赖
├── core/
│   ├── __init__.py
│   ├── audio.py                 # M-02：音频捕获（sounddevice InputStream）
│   ├── detector.py              # M-03：人声检测与静音切片
│   ├── recognizer.py            # M-04：ASR 推理（faster-whisper, int8）
│   ├── typer.py                 # M-05：键盘模拟 + 剪贴板兜底
│   └── manager.py               # M-06：核心调度与线程生命周期
├── utils/
│   ├── __init__.py
│   ├── clipboard.py             # M-08：跨平台剪贴板封装
│   └── key_monitor.py           # M-09：全局热键监听（push-to-talk）
├── tests/
│   ├── __init__.py
│   ├── test_config.py           # 53 个测试
│   ├── test_audio.py            # 32 个测试
│   ├── test_detector.py         # 31 个测试
│   ├── test_recognizer.py       # 25 个测试
│   ├── test_typer.py            # 20 个测试
│   ├── test_clipboard.py        # 16 个测试
│   ├── test_manager.py          # 39 个测试
│   ├── test_main.py             # 31 个测试
│   └── test_key_monitor.py      # 29 个测试
└── docs/
    ├── specs/                   # 设计规格文档（9 篇）
    └── impls/                   # 实现文档（9 篇）
```

---

## 安装指南

### 前置条件

- **Python ≥ 3.10**（推荐 3.12）
- **pip**（Python 包管理器）
- 可正常工作的麦克风

### 快速安装

```bash
# 克隆仓库
git clone https://github.com/heguang123456/vType.git
cd vType

# 创建并激活虚拟环境（推荐）
python -m venv .venv
# Windows：
.venv\Scripts\activate
# macOS / Linux：
source .venv/bin/activate

# 安装生产依赖
pip install -r requirements.txt

# （中国大陆用户）设置 HuggingFace 镜像加速模型下载
# PowerShell：$env:HF_ENDPOINT = "https://hf-mirror.com"
# Bash：     export HF_ENDPOINT=https://hf-mirror.com
```

### 各平台注意事项

| 平台 | 说明 |
|------|------|
| **Windows** | 开箱即用，无需额外权限配置。 |
| **macOS** | 需在「系统设置 → 隐私与安全性 → 辅助功能」中授予权限。未授权时自动使用剪贴板兜底方案。 |
| **Linux** | 可能需要安装 `libportaudio2`（`sudo apt install libportaudio2`）。Xlib 权限通常默认可用。 |

### Python 3.12+ 用户注意

Python 3.12+ 请使用 `webrtcvad-wheels` 替代原版 `webrtcvad`，避免 C 扩展编译问题：

```bash
pip install webrtcvad-wheels>=2.0.10
```

---

## 使用说明

> ⚠️ **全部模块已实现** — 9 个模块 276 个测试全部通过。可使用 `vtype start` 启动语音输入。需先安装依赖并下载 Whisper 模型。

### 配置验证（当前可用）

```python
from config import validate_config, print_config

errors = validate_config()
if errors:
    for e in errors:
        print(f"  - {e}")
else:
    print("配置检查通过")

print_config()  # 格式化输出配置摘要
```

### 运行测试（当前可用）

```bash
# 运行全部测试
pytest tests/ -v

# 运行指定模块测试
pytest tests/test_config.py -v
pytest tests/test_audio.py -v
pytest tests/test_detector.py -v

# 带覆盖率报告
pytest tests/ --cov=. --cov-report=term-missing
```

### 完整 CLI（Phase 2 目标）

```bash
# 启动语音输入（默认模型：base，int8 量化）
vtype

# 指定模型大小
vtype --model small

# 开启详细日志
vtype --verbose

# 优雅退出：Ctrl+C
```

---

## 配置参数

所有参数均有合理默认值，可通过 `VTYPE_` 前缀的环境变量覆盖。

### 音频采集

| 参数 | 默认值 | 环境变量 | 说明 |
|------|--------|----------|------|
| `SAMPLE_RATE` | 16000 | `VTYPE_SAMPLE_RATE` | 采样率（Hz），Whisper 要求 16000 |
| `CHANNELS` | 1 | `VTYPE_CHANNELS` | 单声道，webrtcvad 要求 |
| `FRAME_DURATION_MS` | 20 | `VTYPE_FRAME_DURATION_MS` | VAD 帧长（10/20/30ms） |
| `BLOCK_SIZE` | 320 | `VTYPE_BLOCK_SIZE` | 每帧采样数（由采样率×帧长/1000 导出） |
| `DTYPE` | int16 | `VTYPE_DTYPE` | 采样数据类型 |

### 人声检测

| 参数 | 默认值 | 环境变量 | 说明 |
|------|--------|----------|------|
| `VAD_AGGRESSIVENESS` | 3 | `VTYPE_VAD_AGGRESSIVENESS` | VAD 灵敏度（0=安静环境，3=嘈杂环境） |
| `SILENCE_LIMIT_MS` | 800 | `VTYPE_SILENCE_LIMIT_MS` | 触发切片的静音阈值（毫秒） |

### 语音识别

| 参数 | 默认值 | 环境变量 | 说明 |
|------|--------|----------|------|
| `MODEL_SIZE` | base | `VTYPE_MODEL_SIZE` | Whisper 模型（tiny/base/small/medium/large） |
| `COMPUTE_TYPE` | int8 | `VTYPE_COMPUTE_TYPE` | CTranslate2 计算精度 |
| `DEVICE` | cpu | `VTYPE_DEVICE` | 推理设备（cpu/cuda） |
| `BEAM_SIZE` | 3 | `VTYPE_BEAM_SIZE` | 束搜索宽度（1-10） |
| `LANGUAGE` | zh | `VTYPE_LANGUAGE` | 识别语言 |

### 键盘输出

| 参数 | 默认值 | 环境变量 | 说明 |
|------|--------|----------|------|
| `TYPE_DELAY` | 0.005 | `VTYPE_TYPE_DELAY` | 按键间隔（秒） |
| `CLIPBOARD_FALLBACK` | true | `VTYPE_CLIPBOARD_FALLBACK` | 启用剪贴板粘贴兜底 |

### 线程调度

| 参数 | 默认值 | 环境变量 | 说明 |
|------|--------|----------|------|
| `HOTKEY` | caps_lock | `VTYPE_HOTKEY` | push-to-talk 热键（pynput 格式） |

---

## 开发指南

### Git 工作流（Git Flow）

```
main          ─── 生产发布
  └── develop ─── 日常集成
        ├── feat/*  ─── 功能分支
        ├── fix/*   ─── 缺陷修复分支
        └── release/* ── 发布准备分支
```

**规则：**
- **禁止直接向 `main` 提交**。
- 功能分支在合并前需 rebase 到 `develop`。
- 合并到 `develop` 使用 `--no-ff` 保留分支拓扑。
- 个人分支推送使用 `--force-with-lease`。

### 提交规范（Conventional Commits）

```
<type>(<scope>): <subject>

类型（type）：feat | fix | refactor | docs | test | chore | perf
范围（scope）：config | audio | detector | recognizer | typer | manager | deps
主题（subject）：中文描述，动词开头，不超过 50 字
```

示例：
```
feat(audio): 实现硬件麦克风流采集
fix(detector): 修复模块重载后枚举值相等性判断
test(config): 添加静音参数的边界值校验
```

### 开发环境搭建

```bash
# 安装全部依赖（生产 + 开发）
pip install -r requirements.txt -r requirements-dev.txt

# 代码规范检查
ruff check .

# 静态类型检查
mypy config.py core/

# 运行全部测试
pytest tests/ -v

# 带覆盖率报告的测试
pytest tests/ --cov=. --cov-report=html
```

---

## 路线图

### ✅ Phase 1 — 基础设施（已完成）

| 模块 | 文件 | 测试 | 状态 |
|------|------|------|------|
| M-01 | `config.py` — 全局配置中心 | 53 ✅ | 完成 |
| M-02 | `core/audio.py` — 音频捕获流 | 32 ✅ | 完成 |
| M-03 | `core/detector.py` — 人声检测与切片 | 31 ✅ | 完成 |

**Phase 1 合计：116 个测试全部通过。**

**全部模块：9/9 完成，276 tests 全部通过。**

### ✅ Phase 2 — 核心管线（已完成）

| 模块 | 文件 | 测试 | 状态 |
|------|------|------|------|
| M-04 | `core/recognizer.py` | 25 ✅ | 完成 |
| M-05 | `core/typer.py` | 20 ✅ | 完成 |
| M-08 | `utils/clipboard.py` | 16 ✅ | 完成 |
| M-06 | `core/manager.py` | 39 ✅ | 完成 |

### ✅ Phase 3 — CLI 与交互（已完成）

| 模块 | 文件 | 测试 | 状态 |
|------|------|------|------|
| M-07 | `main.py` | 31 ✅ | 完成 |
| M-09 | `utils/key_monitor.py` | 29 ✅ | 完成 |

### 🔴 Phase 4 — 打磨与发布

- 性能基准测试与优化
- 跨平台集成测试
- PyPI 包发布
- CI/CD 流水线搭建

---

## 许可证

MIT License

---

## 致谢

- [OpenAI Whisper](https://github.com/openai/whisper) — 语音识别模型
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — CTranslate2 优化推理引擎
- [Google WebRTC VAD](https://webrtc.org/) — 人声活动检测算法
- [sounddevice](https://python-sounddevice.readthedocs.io/) — PortAudio Python 绑定
