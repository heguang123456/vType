# vType — CLI Voice Input 需求文档

> **项目名称**：vType (Voice Type)  
> **版本**：v0.1.0-dev  
> **仓库**：vtype  
> **文档状态**：需求定义阶段  
> **更新日期**：2026-05-23

---

## 目录

1. [GitHub 仓库提交规范与文档编写规范](#1-github-仓库提交规范与文档编写规范)
2. [技术架构](#2-技术架构)
3. [技术选型](#3-技术选型)
4. [技术优缺点综合对比](#4-技术优缺点综合对比)
5. [交付验收标准与交付内容](#5-交付验收标准与交付内容)
6. [关键技术问题与解决方案](#6-关键技术问题与解决方案)
7. [后续进阶拓展优化](#7-后续进阶拓展优化)
8. [功能模块划分与实现顺序](#8-功能模块划分与实现顺序)
9. [测试策略与测试文档总结](#9-测试策略与测试文档总结)
10. [Agent 工作流规范](#10-agent-工作流规范)

---

## 1. GitHub 仓库提交规范与文档编写规范

### 1.1 分支管理（Git Flow）

本项目严格遵循 **Git Flow** 工作流：

| 分支类型 | 命名规则 | 用途 | 生命周期 |
|---------|---------|------|---------|
| `develop` | 固定名称 | 日常开发集成分支 | 永久保留 |
| `feat/*` | `feat/<模块>-<简述>` | 功能开发分支 | 合入 develop 后删除 |
| `fix/*` | `fix/<模块>-<简述>` | Bug 修复分支 | 合入 develop 后删除 |
| `release/*` | `release/v<版本号>` | 发布准备分支 | 合入 main 后删除 |
| `main` | 固定名称 | 生产发布分支 | 永久保留 |

**分支操作规则**：

- **禁止直接操作 main 分支**：除 Release 阶段外，禁止向 main 提交或推送。
- **功能开发流程**：
  1. 从 `develop` 创建 `feat/*` 分支
  2. 在 `feat/*` 上开发并提交
  3. 提交前执行 `git fetch origin && git rebase origin/develop` 保持线性历史
  4. 通过 `git merge --no-ff` 合入 `develop`，保留拓扑结构
- **个人分支推送**：使用 `git push --force-with-lease`（仅限个人分支，禁止在共享分支强制推送）。

**示例流程**：

```bash
# 1. 从 develop 创建功能分支
git checkout develop
git pull origin develop
git checkout -b feat/audio-stream-capture

# 2. 开发并提交（多人协作时先 rebase）
git fetch origin
git rebase origin/develop

# 3. 推送个人分支
git push --force-with-lease origin feat/audio-stream-capture

# 4. 合入 develop（使用 --no-ff）
git checkout develop
git merge --no-ff feat/audio-stream-capture
git push origin develop
```

### 1.2 提交消息规范（Conventional Commits）

**格式**：`<type>(<scope>): <subject>`

| 字段 | 说明 | 要求 |
|------|------|------|
| `type` | 提交类型 | 必须从 `[feat, fix, refactor, docs, test, chore, perf]` 中选择 |
| `scope` | 影响模块 | 如 `audio`, `detector`, `recognizer`, `typer`, `manager`, `config`, `deps` |
| `subject` | 简短描述 | 中文、动词开头、不超过 50 字 |

**Type 定义**：

| Type | 说明 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat(recognizer): 实现 faster-whisper int8 量化推理引擎` |
| `fix` | Bug 修复 | `fix(detector): 修复静音切片边界帧丢失问题` |
| `refactor` | 代码重构 | `refactor(audio): 将回调逻辑拆分为独立帧处理器` |
| `docs` | 文档更新 | `docs(readme): 补充安装步骤与环境依赖说明` |
| `test` | 测试相关 | `test(detector): 增加 VAD 状态机切换单元测试` |
| `chore` | 构建/工具 | `chore(deps): 锁定 faster-whisper 版本至 1.0.3` |
| `perf` | 性能优化 | `perf(recognizer): 调整 beam_size 参数降低推理延迟` |

**提交前检查（Pre-commit Audit）**：

1. 执行 `git status` 和 `git diff --stat` 确认变更范围
2. 如变更涉及多个功能模块，**强制拆分**为多次提交
3. 提交前必须通过语法检查：`python -m compileall core/`
4. 如修改 `requirements.txt`，需确认版本号已锁定（禁止使用 `>=` 或 `latest`）
5. 修改依赖后更新 `requirements-lock.txt`

### 1.3 GitHub 文档编写规范

**仓库结构要求**：

```
vtype/
├── README.md                # 项目概述、快速开始、使用说明
├── REQUIREMENTS.md           # 本需求文档
├── ARCHITECTURE.md           # 架构设计文档（开发阶段编写）
├── CONTRIBUTING.md           # 贡献指南
├── CHANGELOG.md              # 版本变更日志
├── LICENSE                   # 开源许可（MIT）
├── docs/
│   ├── setup.md              # 环境安装详细指南
│   ├── usage.md              # 用户使用手册
│   ├── api.md                # 模块 API 参考
│   └── troubleshooting.md    # 常见问题排查
├── tests/
│   └── README.md             # 测试说明
└── .github/
    ├── workflows/            # CI/CD 配置
    └── ISSUE_TEMPLATE/       # Issue 模板
```

**文档编写规则**：

- 所有 Markdown 文档使用 UTF-8 编码
- 标题层级不超过 4 级（`####`）
- 代码块指定语言标识
- 表格使用对齐格式
- README.md 必须包含：项目简介、安装步骤、快速使用示例、技术栈说明、许可证信息
- CHANGELOG.md 遵循 [Keep a Changelog](https://keepachangelog.com/) 规范

---

## 2. 技术架构

### 2.1 架构总览

vType 采用 **生产者-消费者双线程事件驱动架构**，核心目标是在本地 CPU 上进行实时语音识别时，防止 AI 推理的同步阻塞导致麦克风硬件丢帧。

```
┌──────────────────────────────────────────────────────────────┐
│                        main.py (Click CLI)                   │
│              多线程启动 · 信号处理 · 优雅退出                    │
└──────────────────────┬───────────────────────────────────────┘
                       │
         ┌─────────────┴─────────────┐
         │                           │
         ▼                           ▼
┌─────────────────┐         ┌─────────────────┐
│   Thread A      │  Queue  │   Thread B      │
│   生产者         ├────────►│   消费者         │
│                 │         │                 │
│ ┌─────────────┐ │         │ ┌─────────────┐ │
│ │ audio.py    │ │         │ │recognizer.py│ │
│ │ 音频流捕获   │ │         │ │ ASR 推理    │ │
│ └──────┬──────┘ │         │ └──────┬──────┘ │
│        ▼        │         │        ▼        │
│ ┌─────────────┐ │         │ ┌─────────────┐ │
│ │detector.py  │ │         │ │  typer.py   │ │
│ │ 人声检测+切片│ │         │ │ 键盘模拟输出 │ │
│ └─────────────┘ │         │ └─────────────┘ │
└─────────────────┘         └─────────────────┘
         │                           │
         ▼                           ▼
    sounddevice               pynput / Clipboard
    (PortAudio)               (OS Input API)
```

### 2.2 数据拓扑流

```
硬件麦克风
  │
  ▼
sounddevice InputStream (回调: 极简, 只做 put)
  │
  ▼ NumPy 数组 (float32, 16kHz, 单声道)
audio.py (原始音频队列)
  │
  ▼ 拆分为 20ms 滑动窗口帧 (320 samples × int16)
detector.py (webrtcvad 状态机)
  │
  ├── LISTENING 状态: 持续检测人声
  ├── RECORDING 状态: 缓存语音帧, 统计连续静音
  │
  ▼ 静音超阈值 → 合并全部帧为单个 NumPy 数组
TaskQueue (thread-safe Queue)
  │
  ▼ 阻塞等待新任务
recognizer.py (faster-whisper int8)
  │
  ▼ 识别文本
typer.py (pynput / Clipboard fallback)
  │
  ▼ 逐字输入到当前光标位置
系统应用程序
```

### 2.3 并发状态机

**采集器状态（Thread A）**：

| 状态 | 说明 | 触发条件 |
|------|------|---------|
| `LISTENING` | 静音监听中 | 初始化后默认状态；发送切片后自动进入 |
| `RECORDING` | 人声录制中 | 检测到连续语音帧 |

```
LISTENING ──(检测到人声)──► RECORDING
    ▲                        │
    └──(切片发送完成)────────┘
```

**消费者状态（Thread B）**：

| 状态 | 说明 | 触发条件 |
|------|------|---------|
| `IDLE` | 空闲等待 | 初始化后默认；输出完成后 |
| `TRANSCRIBING` | AI 推理中 | TaskQueue 有数据 |
| `TYPING` | 正在打字输出 | 推理完成，开始模拟输入 |

```
IDLE ──(TaskQueue.get)──► TRANSCRIBING ──(推理完成)──► TYPING ──(输出完成)──► IDLE
```

### 2.4 目录结构（高内聚低耦合）

```
vtype/
├── config.py                 # 全局配置中心
├── main.py                   # Click CLI 入口 + 多线程生命周期管理
├── core/
│   ├── __init__.py
│   ├── manager.py            # 核心调度器（TaskQueue、线程生命周期）
│   ├── audio.py              # 生产者：sounddevice 硬件流 + NumPy 数据捕获
│   ├── detector.py           # 状态机：VAD 滑动窗口 + 静音切片逻辑
│   ├── recognizer.py         # 消费者：faster-whisper int8 本地推理
│   └── typer.py              # 输出：pynput 键盘模拟 + 剪贴板兜底
├── utils/
│   ├── __init__.py
│   ├── key_monitor.py        # 全局热键监听（预留接口）
│   └── clipboard.py          # 跨平台剪贴板操作封装
├── tests/
│   ├── __init__.py
│   ├── test_audio.py
│   ├── test_detector.py
│   ├── test_recognizer.py
│   ├── test_typer.py
│   └── test_integration.py
├── docs/
├── requirements.txt
├── requirements-lock.txt
├── setup.py
├── README.md
├── REQUIREMENTS.md           # 本文档
├── ARCHITECTURE.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── Makefile
└── .gitignore
```

---

## 3. 技术选型

### 3.1 技术栈总览

| 层级 | 技术 | 版本要求 | 用途 |
|------|------|---------|------|
| 语言 | Python | ≥ 3.10 (推荐 3.12) | 全栈开发语言 |
| 音频采集 | `sounddevice` | ≥ 0.4.6 | 硬件级麦克风流捕获 |
| 人声检测 | `webrtcvad` (或 `webrtcvad-wheels`) | ≥ 2.0.10 | Google VAD 算法封装 |
| 语音识别 | `faster-whisper` | ≥ 1.0.3 | CTranslate2 Whisper C++ 推理 |
| 键盘模拟 | `pynput` | ≥ 1.7.6 | 系统级键盘输入模拟 |
| 剪贴板 | `pyperclip` | ≥ 1.8.2 | 跨平台剪贴板兜底方案 |
| CLI 框架 | `click` | ≥ 8.1 | 命令行参数解析 |
| 数值计算 | `numpy` | ≥ 1.24 | 音频数据处理 |
| 测试 | `pytest` + `pytest-mock` | ≥ 7.4 | 单元测试与 Mock |
| 代码质量 | `ruff` + `mypy` | 最新 | 代码检查与类型验证 |

### 3.2 核心技术选型理由

#### 3.2.1 sounddevice（音频采集）

**选择理由**：
- **零拷贝 NumPy 数组**：`InputStream` 回调直接返回 `numpy.ndarray`，无需手动转换字节码，避免内存拷贝开销。
- **PortAudio 绑定**：底层基于 C 语言 PortAudio 库，稳定运行超 20 年，跨 Windows/macOS/Linux API。
- **流模式（Stream Callback）**：直接在硬件中断上下文获取数据，延迟 < 5ms，远优于轮询模式。
- **PyPI 活跃维护**：截至 2026 年持续更新，社区成熟。

**已知限制**：
- macOS 首次使用需授权麦克风权限
- Linux 需 ALSA/PulseAudio 配置正确
- Windows WASAPI 独占模式可能冲突

#### 3.2.2 webrtcvad（人声检测）

**选择理由**：
- **μs 级推理**：基于纯时域特征分析（高斯混合模型），单帧推理时间 < 10μs，CPU 占用接近 0%。
- **轻量级**：无需 GPU，无需模型文件，纯 C 实现编译为动态库。
- **帧级精度**：支持 10/20/30ms 帧长，与 Whisper 16kHz 采样率天然对齐。
- **Google 开源**：已在 WebRTC 项目中全球大规模验证。

**灵敏度模式**：

| 模式 | 值 | 适用场景 |
|------|---|---------|
| 安静环境 | 0 | 安静房间、录音棚 |
| 普通环境 | 1 | 家庭、办公室 |
| 嘈杂环境 | 2 | 咖啡厅、开放空间 |
| 高灵敏度 | 3 | 极嘈杂环境（可能误触发） |

项目默认使用 **模式 3**（最激进的人声判定），确保在嘈杂环境中不遗漏语音。

#### 3.2.3 faster-whisper（语音识别）

**选择理由**：
- **4 倍加速**：基于 CTranslate2 将 Whisper Transformer 模型转为 C++ 推理，CPU 推理速度达 openai/whisper 的 4 倍。
- **int8 量化**：模型内存占用降低 2-4 倍，在 8GB 内存设备上即可流畅运行 base 模型。
- **CPU 优先**：`device="cpu"` + `compute_type="int8"` 专为本地 CPU 推理优化，无需 GPU。
- **多模型可选**：tiny/base/small/medium/large 覆盖不同精度需求。

**模型选择建议**：

| 模型 | 参数量 | 内存占用 | 推理速度 | 中文准确率 | 适用场景 |
|------|--------|---------|---------|-----------|---------|
| `tiny` | 39M | ~150MB | 极快 | 一般 | 资源受限设备 |
| `base` | 74M | ~300MB | 快 | 良好 | **默认推荐** |
| `small` | 244M | ~1GB | 中等 | 较好 | 高精度需求 |
| `medium` | 769M | ~3GB | 较慢 | 优秀 | 专业场景 |
| `large-v3` | 1.5B | ~6GB | 慢 | 最优 | 服务器部署 |

项目默认使用 **`base` + `int8`**，平衡速度与精度。

#### 3.2.4 pynput + 剪贴板兜底（文本输出）

**选择理由**：
- **pynput**：直接调用 OS 底层 API（Windows `SendInput` / macOS `CGEvent` / Linux `Xlib/uinput`），实现后台全局键盘模拟。
- **剪贴板兜底**：macOS/Linux 可能因权限问题导致 pynput 失败，使用 `pyperclip` + `Ctrl/Cmd+V` 粘贴作为降级方案。

**跨平台适配**：

| 平台 | 主方案 | API | 权限要求 | 兜底方案 |
|------|--------|-----|---------|---------|
| Windows | `pynput` (SendInput) | Win32 API | 无需额外权限 | Ctrl+V 粘贴 |
| macOS | `pynput` (CGEvent) | Quartz Event | **需辅助功能权限** | Cmd+V 粘贴 |
| Linux | `pynput` (Xlib/uinput) | X11/uinput | 可能需要 input 组 | Ctrl+V 粘贴 |

---

## 4. 技术优缺点综合对比

### 4.1 Python 语音识别方案对比

| 方案 | 推理引擎 | 速度 | 内存 | 离线 | 跨平台 | 量化 | 推荐度 |
|------|---------|------|------|------|--------|------|--------|
| **faster-whisper** | CTranslate2 | ★★★★★ | ★★★★ | ✅ | ✅ | int8 | **推荐** |
| openai/whisper | PyTorch | ★★ | ★★ | ✅ | ✅ | ❌ | 备选 |
| whisper.cpp | ggml | ★★★★ | ★★★★★ | ✅ | ✅ | int8 | 备选 |
| Vosk | Kaldi | ★★★ | ★★★ | ✅ | ✅ | ❌ | 备选 |
| SpeechRecognition | 各 API | ★ | ★ | ❌ | ✅ | ❌ | 不推荐 |
| 云端 ASR (讯飞等) | 云服务 | ★★★★ | ★★★★★ | ❌ | ✅ | N/A | 不符合离线定位 |

**结论**：`faster-whisper` 在**离线 + CPU 推理 + 速度**三项核心指标上综合最优。

### 4.2 Python 音频采集方案对比

| 方案 | 延迟 | NumPy 原生 | 跨平台 | 回调模式 | 活跃维护 |
|------|------|-----------|--------|---------|---------|
| **sounddevice** | <5ms | ✅ | ✅ | ✅ | ✅ |
| PyAudio | ~10ms | ❌ | ✅ | ✅ | ❌ (停更) |
| pyaudiowpatch | ~10ms | ❌ | Windows only | ✅ | 一般 |
| audioread | 高 | ❌ | ✅ | ❌ | 一般 |

**结论**：`sounddevice` 在延迟和 NumPy 原生支持方面具有决定性优势。

### 4.3 人声检测方案对比

| 方案 | 推理时间 | 准确性 | 模型大小 | CPU 占用 |
|------|---------|--------|---------|---------|
| **webrtcvad** | <10μs | ★★★★ | 0 (纯算法) | <1% |
| Silero VAD | ~1ms | ★★★★★ | ~1MB | ~5% |
| 能量阈值法 | <1μs | ★★ | 0 | ≈0% |

**结论**：`webrtcvad` 在速度与资源消耗上最优，适合实时场景。若需更高准确率可后续升级至 `Silero VAD`。

### 4.4 整体技术栈风险矩阵

| 风险项 | 严重度 | 概率 | 缓解措施 |
|--------|--------|------|---------|
| macOS 权限拒绝导致 pynput 不可用 | 高 | 中 | 剪贴板兜底方案 |
| faster-whisper 模型下载失败 | 高 | 中 | 国内镜像 + 离线模型包 |
| sounddevice 设备冲突 | 中 | 低 | 提供设备列表选择功能 |
| Python 3.13+ 兼容性问题 | 中 | 低 | 锁定 Python 3.10-3.12 |
| 中文识别准确率不足 | 中 | 中 | 支持模型升级至 small/medium |
| 长音频推理延迟 | 低 | 中 | 流式推理（streaming decode）预留 |

---

## 5. 交付验收标准与交付内容

### 5.1 交付物清单

| 序号 | 交付物 | 格式 | 说明 |
|------|--------|------|------|
| 1 | 完整源代码 | Python 包 | 包含 core/、utils/、config.py、main.py |
| 2 | 依赖声明 | requirements.txt + requirements-lock.txt | 锁定所有依赖版本 |
| 3 | 安装脚本 | setup.py / pyproject.toml | pip install 可安装 |
| 4 | 用户文档 | README.md + docs/usage.md | 安装与使用说明 |
| 5 | 架构文档 | ARCHITECTURE.md | 详细架构设计 |
| 6 | API 文档 | docs/api.md | 模块接口说明 |
| 7 | 单元测试 | tests/ | 覆盖率 ≥ 80% |
| 8 | 集成测试 | tests/test_integration.py | 端到端验证 |
| 9 | 变更日志 | CHANGELOG.md | 版本变更记录 |
| 10 | 贡献指南 | CONTRIBUTING.md | 开发规范 |

### 5.2 功能验收标准

| 编号 | 验收项 | 验收标准 | 测试方法 |
|------|--------|---------|---------|
| F-001 | 音频流捕获 | `sounddevice` 成功打开默认麦克风，回调接收 NumPy 数组 | 运行 `main.py`，观察日志输出音频帧计数 |
| F-002 | 人声检测 | `webrtcvad` 准确区分人声/静音，误检率 < 5% | 用预录测试音频验证状态切换 |
| F-003 | 静音切片 | 连续静音 800ms 后正确切片，不漏帧 | 边界条件测试：0.8s/1.6s/3.2s 静音间隔 |
| F-004 | ASR 推理 | `faster-whisper base int8` 在 3s 内完成 5 秒音频识别 | 基准测试脚本，记录推理延迟 |
| F-005 | 中文识别 | 清晰普通话标准句准确率 ≥ 90%（base 模型） | 百句测试集验证 |
| F-006 | 键盘输出 | `pynput` 正确逐字输入到当前焦点应用 | Windows 记事本 / macOS 文本编辑实测 |
| F-007 | 剪贴板兜底 | pynput 失败时自动切换粘贴模式 | macOS 无权限环境测试 |
| F-008 | 优雅退出 | `Ctrl+C` 后音频流正确关闭，无死锁 | 重复启停 20 次无异常 |
| F-009 | 内存稳定 | 运行 1 小时后内存增长 < 50MB | 内存监控脚本 |
| F-010 | 跨平台 | Windows 10+、macOS 12+、Ubuntu 20.04+ 通过全部验收 | 三平台实测 |

### 5.3 性能验收标准

| 指标 | 目标值 | 测量方法 |
|------|--------|---------|
| 音频回调延迟 | < 5ms | `sounddevice` 内置 latency 统计 |
| VAD 单帧推理 | < 20μs | `time.perf_counter` 打点 |
| 切片到入队延迟 | < 1ms | `queue.put` 前后计时 |
| ASR 实时率 (RTF) | < 0.5（base 模型） | 推理时间 ÷ 音频时长 |
| 键盘字符间延迟 | 5ms ± 2ms | `time.sleep` 验证 |
| 内存占用 (稳态) | < 500MB | `psutil` 监控 |
| CPU 占用 (IDLE) | < 1% | 任务管理器 / `top` |
| CPU 占用 (推理时) | < 50%（4 核） | 任务管理器 / `top` |

---

## 6. 关键技术问题与解决方案

### 6.1 问题一：硬件丢帧

**问题描述**：ASR 推理属于 CPU 密集型操作（Transformer 解码），若在音频采集回调线程中同步执行，会导致回调超时，`sounddevice` 底层输入缓冲区溢出，丢弃硬件音频数据。

**解决方案**：
- **架构层面**：严格分离生产者线程（采集）与消费者线程（推理），通过 `queue.Queue` 解耦。
- **回调极简化**：`audio.py` 的 `InputStream` 回调函数仅执行 `queue.put(data)`，绝不做耗时操作。
- **队列容量警戒**：`TaskQueue` 设置 `maxsize=10`，当消费者跟不上时主动丢弃老数据而非阻塞生产者。

### 6.2 问题二：静音切片边界帧丢失

**问题描述**：说话人短暂停顿（如思考时）可能触发切分，导致一句话被拆成多段，影响识别准确率。

**解决方案**：
- **防抖机制**：`SILENCE_LIMIT_MS = 800`（连续 800ms 静音才算说话结束），经验证该值在中文口语中平衡性最佳。
- **帧缓存策略**：`RECORDING` 状态时缓存所有语音帧（含中间的短暂静音），切片时合并为连续的 NumPy 数组，不丢弃间歇帧。
- **可配置参数**：`SILENCE_LIMIT_MS` 通过 `config.py` 暴露，用户可根据语速调整。

### 6.3 问题三：macOS 权限拒绝导致无法模拟输入

**问题描述**：macOS 从 10.14 起要求应用获取「辅助功能」权限才能使用 `CGEvent` API 模拟键盘事件。首次运行或权限被拒绝时，`pynput` 的 `Controller.type()` 将抛出异常。

**解决方案**：
- **双重策略**：
  1. 优先使用 `pynput.keyboard.Controller` 逐字模拟输入
  2. `try-except` 捕获权限异常，自动降级为剪贴板方案：`pyperclip.copy(text)` + `Ctrl/Cmd+V` 粘贴
- **用户提示**：首次运行时探测权限，若无权限则在终端打印清晰的授权指引。
- **全局热键绕过**：macOS 的 `pynput` 全局热键监听也可能需要权限，`utils/key_monitor.py` 同样需要降级处理。

### 6.4 问题四：faster-whisper 模型下载（中国大陆网络环境）

**问题描述**：`faster-whisper` 默认从 HuggingFace Hub 下载模型文件（`~/.cache/huggingface/`），中国大陆直接下载极慢或失败。

**解决方案**：
- **环境变量**：支持 `HF_ENDPOINT=https://hf-mirror.com` 使用国内镜像。
- **离线模型包**：提供模型手动下载 + 本地路径加载方案（`WhisperModel(path)`）。
- **自动重试**：下载失败时重试 3 次，间隔递增。
- **进度显示**：使用 `tqdm` 或简单日志输出下载进度。

### 6.5 问题五：webrtcvad 在 Python 3.12+ 的兼容性

**问题描述**：`webrtcvad` 依赖 C 扩展编译，可能在新 Python 版本上编译失败。

**解决方案**：
- **优先使用 `webrtcvad-wheels`**：该 fork 提供预编译 wheel，支持 Python 3.8-3.12。
- **回退方案**：若 wheel 不可用，自动尝试源码编译。
- **CI 矩阵测试**：在 Python 3.10/3.11/3.12 上分别验证。

### 6.6 问题六：多麦克风设备选择

**问题描述**：用户可能连接多个音频设备（USB 麦克风、蓝牙耳机、Webcam 麦克风），默认设备不一定是期望的输入源。

**解决方案**：
- `config.py` 中保留 `AUDIO_DEVICE_ID` 配置项（默认 `None` = 系统默认）。
- CLI 参数 `--list-devices` 列出所有音频设备供选择。
- 首次启动时自动检测并提示。

---

## 7. 后续进阶拓展优化

### 7.1 近期拓展（v0.2 - v0.3）

| 编号 | 拓展项 | 说明 | 优先级 |
|------|--------|------|-------|
| E-001 | 全局热键暂停/恢复 | `Alt+V` 切换 `IS_PAUSED`，架构已预留 `utils/key_monitor.py` 接口 | P0 |
| E-002 | 中英混合识别 | `language="auto"` 自适应，`beam_size=5` 提升混合语言准确率 | P0 |
| E-003 | 多模型切换 | CLI `--model_size` 扩展支持 tiny/base/small/medium | P1 |
| E-004 | 设备选择 | `--list-devices` + `--device-id` 支持指定输入设备 | P1 |
| E-005 | 流式输出 | 不等整句结束，边推理边输出（streaming decode） | P1 |

### 7.2 中期拓展（v0.4 - v0.5）

| 编号 | 拓展项 | 说明 |
|------|--------|------|
| E-006 | VAD 升级至 Silero | 用 Silero VAD 替代 webrtcvad，提高嘈杂环境准确率 |
| E-007 | 系统托盘图标 | Windows/macOS/Linux 系统托盘，显示录音/推理状态 |
| E-008 | 多语种支持 | 添加日/韩/英/法/德等主要语种 |
| E-009 | 音频降噪 | 集成 RNNoise 或 speexdsp 降噪预处理 |
| E-010 | 性能面板 | Web 或 CLI 实时展示延迟/RTF/内存等指标 |
| E-011 | 自定义热词 | 支持用户添加专有名词、术语词典提升识别率 |

### 7.3 远期展望（v0.6+）

| 编号 | 拓展项 | 说明 |
|------|--------|------|
| E-012 | 标点与格式化 | 集成标点恢复模型，自动添加句号逗号 |
| E-013 | 语音指令 | "换行"、"删除"、"全选" 等语音控制指令 |
| E-014 | 历史记录 | 保存识别历史，支持搜索与回放 |
| E-015 | 插件系统 | 可扩展的输出后端（如直接输出到 IDE、终端） |
| E-016 | GPU 加速 | 支持 CUDA/Metal 加速推理 |
| E-017 | 分布式部署 | 采集端与推理端分离，低配设备采集+高配设备推理 |

---

## 8. 功能模块划分与实现顺序

### 8.1 模块总览

| 模块 | 文件 | 职责 | 优先级 | 依赖 |
|------|------|------|--------|------|
| M-01 | `config.py` | 全局参数配置 | **Phase 1** | 无 |
| M-02 | `core/audio.py` | 音频流捕获 | **Phase 1** | M-01 |
| M-03 | `core/detector.py` | 人声检测与切片 | **Phase 1** | M-01, M-02 |
| M-04 | `core/recognizer.py` | ASR 推理引擎 | **Phase 2** | M-01 |
| M-05 | `core/typer.py` | 键盘模拟输出 | **Phase 2** | M-01 |
| M-06 | `core/manager.py` | 核心调度器 | **Phase 2** | M-02, M-03, M-04, M-05 |
| M-07 | `main.py` | CLI 入口 | **Phase 3** | M-06 |
| M-08 | `utils/clipboard.py` | 剪贴板操作 | **Phase 2** | M-01 |
| M-09 | `utils/key_monitor.py` | 全局热键监听 | **Phase 3** | M-01 |
| M-10 | `tests/*` | 测试套件 | 随模块并行 | 对应模块 |

### 8.2 Phase 1：基础设施层（音频采集 + 人声检测）

#### M-01：`config.py` — 全局配置中心

**功能说明**：
- 定义所有可配置参数的默认值
- 支持环境变量覆盖（`VTYPE_SAMPLE_RATE` 等前缀）
- 参数类型验证

**核心参数**：

```python
# === 音频参数 ===
SAMPLE_RATE = 16000           # Whisper 强制标准输入
CHANNELS = 1                  # 单声道，webrtcvad 强制标准
BLOCK_SIZE = 320              # 16000 * 0.02 = 320 samples/帧
DTYPE = "int16"               # VAD 要求的输入格式

# === VAD 参数 ===
FRAME_DURATION_MS = 20        # 滑动窗口（仅 10/20/30）
VAD_AGGRESSIVENESS = 3        # 灵敏度 0-3
SILENCE_LIMIT_MS = 800        # 静音阈值 (ms)
SILENCE_FRAME_LIMIT = SILENCE_LIMIT_MS // FRAME_DURATION_MS  # 自动计算

# === 识别参数 ===
MODEL_SIZE = "base"           # tiny/base/small/medium/large
COMPUTE_TYPE = "int8"         # int8/int8_float16/float16
DEVICE = "cpu"                # cpu/cuda
BEAM_SIZE = 3                 # 束搜索宽度
LANGUAGE = "zh"               # 识别语言

# === 输出参数 ===
TYPE_DELAY = 0.005            # 逐字输入间隔 (s)
CLIPBOARD_FALLBACK = True     # 启用剪贴板兜底

# === 队列参数 ===
QUEUE_MAXSIZE = 10            # TaskQueue 最大容量
```

#### M-02：`core/audio.py` — 音频流捕获（生产者前半段）

**功能说明**：
- 打开 `sounddevice.InputStream` 流模式
- 回调函数极简：仅将数据 `put` 到原始音频队列
- 支持启动/停止/暂停控制

**核心设计**：

```
class AudioCapture:
    - sample_rate: int
    - channels: int
    - block_size: int
    - stream: sounddevice.InputStream
    - raw_queue: queue.Queue        # 原始音频帧队列
    - is_running: threading.Event
    
    方法：
    + start() -> None                # 启动音频流
    + stop() -> None                 # 停止音频流（优雅关闭）
    + pause() -> None                # 暂停（热键触发）
    + resume() -> None               # 恢复
    - _audio_callback(indata, frames, time, status) -> None  # 回调函数
```

**实现要点**：
1. `_audio_callback` 只做三件事：检查 `is_running` → 复制 `indata.copy()` → `raw_queue.put()`
2. 使用 `sounddevice.InputStream(..., callback=self._audio_callback)` 而非阻塞模式
3. `stop()` 调用 `stream.stop()` + `stream.close()`，确保资源释放

#### M-03：`core/detector.py` — 人声检测与切片（生产者后半段）

**功能说明**：
- 从原始音频队列消费数据
- 实现 20ms 滑动窗口分割
- 运行 `webrtcvad` 状态机
- 静音超阈值时切片并发送至 `TaskQueue`

**核心设计**：

```
class VoiceDetector:
    - vad: webrtcvad.Vad
    - sample_rate: int
    - frame_duration_ms: int
    - silence_frame_limit: int
    - state: Literal["LISTENING", "RECORDING"]
    - frame_buffer: List[np.ndarray]     # 当前缓冲区
    - silence_count: int
    - task_queue: queue.Queue            # 共享的跨线程队列
    
    方法：
    + run(raw_queue: Queue, task_queue: Queue) -> None  # 主循环
    - _split_into_frames(audio: np.ndarray) -> List[bytes]  # 滑动窗口
    - _is_speech(frame: bytes) -> bool      # VAD 判定
    - _handle_listening(is_speech: bool) -> None  # LISTENING 状态处理
    - _handle_recording(is_speech: bool) -> None  # RECORDING 状态处理
    - _emit_slice() -> None                 # 切片发出
```

**状态机逻辑**：

```
LISTENING 状态：
  if is_speech:
      → 切换到 RECORDING，清空缓冲区，添加当前帧
  else:
      → 保持 LISTENING

RECORDING 状态：
  if is_speech:
      → silence_count = 0，添加帧到缓冲区
  else:
      → silence_count += 1
      → if silence_count >= silence_frame_limit:
          → _emit_slice()（合并缓冲区 → task_queue.put）
          → 切换到 LISTENING
      → else:
          → 添加帧到缓冲区（保留间歇静音）
```

### 8.3 Phase 2：推理与输出层

#### M-04：`core/recognizer.py` — ASR 推理引擎（消费者前半段）

**功能说明**：
- 单例加载 `faster-whisper` 模型
- 从 `TaskQueue` 阻塞获取音频
- 执行 `int8` 量化推理
- 输出识别文本

**核心设计**：

```
class Recognizer:
    - model: WhisperModel
    - model_size: str
    - compute_type: str
    - device: str
    - language: str
    - beam_size: int
    
    方法：
    + __init__(model_size, compute_type, device)  # 模型加载
    + transcribe(audio: np.ndarray) -> str         # 同步推理
    + run(task_queue: Queue, result_queue: Queue) -> None  # 消费者主循环
```

**实现要点**：
1. 模型在 `__init__` 中加载一次（耗时操作），`transcribe` 复用模型实例
2. 使用 `np.frombuffer` 将字节流转为 `float32`，归一化到 [-1, 1]
3. `transcribe()` 参数锁死 `language="zh"`, `beam_size=3`, `vad_filter=False`（已有前置 VAD）
4. 推理完成后将文本放入 `result_queue`

#### M-05：`core/typer.py` — 键盘模拟输出（消费者后半段）

**功能说明**：
- 从结果队列获取识别文本
- 通过 `pynput` 逐字输入到当前光标位置
- 权限失败时自动切换剪贴板方案

**核心设计**：

```
class TypeWriter:
    - type_delay: float
    - clipboard_fallback: bool
    - keyboard: pynput.keyboard.Controller
    
    方法：
    + type_text(text: str) -> None              # 主输出方法
    - _type_via_pynput(text: str) -> None       # pynput 方案
    - _type_via_clipboard(text: str) -> None    # 剪贴板方案
    + run(result_queue: Queue) -> None           # 消费者主循环
```

**降级逻辑**：

```python
def type_text(self, text: str) -> None:
    try:
        self._type_via_pynput(text)
    except (PermissionError, OSError) as e:
        logger.warning(f"pynput failed: {e}, falling back to clipboard")
        self._type_via_clipboard(text)
```

#### M-06：`core/manager.py` — 核心调度器

**功能说明**：
- 初始化 `TaskQueue` 和其他共享资源
- 创建并管理生产者/消费者线程生命周期
- 协调优雅退出

**核心设计**：

```
class CoreManager:
    - raw_queue: queue.Queue
    - task_queue: queue.Queue
    - result_queue: queue.Queue
    - audio_thread: threading.Thread
    - detector_thread: threading.Thread
    - recognizer_thread: threading.Thread
    - typer_thread: threading.Thread
    - is_running: threading.Event
    
    方法：
    + start() -> None               # 启动所有线程
    + stop() -> None                # 优雅停止
    + pause() -> None               # 全局暂停
    + resume() -> None              # 全局恢复
    - _signal_stop() -> None        # 发送停止信号
```

**线程拓扑**：

```
Thread A (生产者):
  audio.py callback → raw_queue → detector.py 主循环 → task_queue

Thread B (消费者):
  recognizer.py 主循环 → result_queue → typer.py 主循环
```

#### M-08：`utils/clipboard.py` — 剪贴板操作封装

**功能说明**：
- 封装 `pyperclip` 的 copy/paste 操作
- 处理剪贴板为空等边界情况
- 跨平台兼容

### 8.4 Phase 3：入口与交互层

#### M-07：`main.py` — CLI 入口

**功能说明**：
- `click` 命令行参数解析
- 信号处理（`Ctrl+C` 优雅退出）
- 启动 `CoreManager`

**CLI 参数设计**：

```
Usage: vtype [OPTIONS]

Options:
  --model-size TEXT       Whisper 模型大小 [tiny|base|small|medium]
                          (默认: base)
  --compute-type TEXT     推理精度 [int8|float16] (默认: int8)
  --language TEXT         识别语言 (默认: zh)
  --silence-limit INT     静音阈值 ms (默认: 800)
  --list-devices           列出可用音频设备
  --device-id INT          指定音频输入设备 ID
  --verbose / --quiet      详细日志输出
  --help                   显示帮助
```

**信号处理**：

```python
import signal

def signal_handler(signum, frame):
    logger.info("Received signal, shutting down...")
    manager.stop()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
```

#### M-09：`utils/key_monitor.py` — 全局热键监听（预留）

**功能说明**：
- 监听 `Alt+V` 全局热键
- 切换 `IS_PAUSED` 布尔值
- 与 `CoreManager.pause()/resume()` 联动

**实现预留**：
- 使用 `pynput.keyboard.GlobalHotKeys` 实现
- macOS 需辅助功能权限
- 权限不足时打印警告而非崩溃

### 8.5 实现顺序规范

**依赖图**：

```
Phase 1 (并行):
  M-01 config.py          ────────────────────────┐
  M-02 core/audio.py       ──► M-03 core/detector.py
                                                  │
Phase 2 (串行):                                   │
  M-04 core/recognizer.py ◄───────────────────────┘
  M-05 core/typer.py                              │
  M-08 utils/clipboard.py                         │
  M-06 core/manager.py    ◄── 依赖 M-02~M-05 ────┘
                                                  │
Phase 3 (串行):                                   │
  M-09 utils/key_monitor.py                       │
  M-07 main.py             ◄── 依赖 M-06, M-09 ──┘
```

**实现顺序**：

| 阶段 | 任务 | 预计产出 | 前置条件 |
|------|------|---------|---------|
| Phase 1 | M-01 config.py | 所有配置参数定义 | 无 |
| Phase 1 | M-02 audio.py | 硬件音频流捕获 + 单元测试 | M-01 |
| Phase 1 | M-03 detector.py | VAD 状态机 + 切片逻辑 + 单元测试 | M-01, M-02 |
| Phase 2 | M-04 recognizer.py | 模型加载 + 推理引擎 + 单元测试 | M-01 |
| Phase 2 | M-05 typer.py | 键盘模拟 + 剪贴板降级 + 单元测试 | M-01 |
| Phase 2 | M-08 clipboard.py | 剪贴板封装 | M-01 |
| Phase 2 | M-06 manager.py | 线程调度 + 集成测试 | M-02~M-05 |
| Phase 3 | M-09 key_monitor.py | 全局热键监听 | M-01 |
| Phase 3 | M-07 main.py | CLI 入口 + 端到端测试 | M-06, M-09 |

---

## 9. 测试策略与测试文档总结

### 9.1 测试金字塔

```
         ┌──────┐
         │ E2E  │  ← 端到端测试：完整语音输入流程
         ├──────┤
         │ 集成  │  ← 集成测试：线程协作、线程安全队列
         ├──────┤
         │ 单元  │  ← 单元测试：每个模块独立测试
         └──────┘
```

### 9.2 测试分层策略

#### 9.2.1 单元测试（覆盖率目标 ≥ 80%）

| 模块 | 测试文件 | 测试要点 | Mock 策略 |
|------|---------|---------|----------|
| `config.py` | `test_config.py` | 参数默认值、类型验证、环境变量覆盖 | 无需 Mock |
| `core/audio.py` | `test_audio.py` | 回调函数数据格式、启动/停止流、设备枚举 | Mock `sounddevice.InputStream` |
| `core/detector.py` | `test_detector.py` | 滑动窗口分割、状态机切换、静音切片、防抖逻辑 | Mock `webrtcvad.Vad` 控制返回值 |
| `core/recognizer.py` | `test_recognizer.py` | 模型加载、transcribe 调用参数、音频格式转换 | Mock `WhisperModel`（避免实际加载模型） |
| `core/typer.py` | `test_typer.py` | pynput 输入、剪贴板降级、字符间延迟 | Mock `pynput.keyboard.Controller` 和 `pyperclip` |
| `core/manager.py` | `test_manager.py` | 线程创建/停止、队列传递、资源清理 | Mock 各子模块 |
| `utils/clipboard.py` | `test_clipboard.py` | copy/paste 基础操作、空剪贴板处理 | Mock `pyperclip` |

#### 9.2.2 集成测试

| 测试场景 | 测试文件 | 验证目标 |
|---------|---------|---------|
| 音频采集 → VAD 切片 | `test_integration.py::test_audio_to_vad` | 使用预录 wav 文件，模拟 sounddevice 回调，验证 VAD 正确切片 |
| VAD 切片 → ASR 推理 | `test_integration.py::test_vad_to_asr` | 使用预录 + 标注文本，验证 ASR 精度达标 |
| ASR 推理 → 键盘输出 | `test_integration.py::test_asr_to_typer` | 验证识别文本正确传递给 typer 模块 |
| 线程生命周期 | `test_integration.py::test_thread_lifecycle` | 验证 start/stop 10 次无死锁、资源泄露 |
| 优雅退出 | `test_integration.py::test_graceful_shutdown` | 模拟 Ctrl+C，验证所有流正确关闭 |

#### 9.2.3 端到端测试（E2E）

| 测试场景 | 方法 | 验证目标 |
|---------|------|---------|
| 完整语音输入流程 | 预录 wav → `main.py` → 输出文本 | 端到端延迟、识别准确率 |
| 跨平台验证 | Windows 10+ / macOS 12+ / Ubuntu 20.04+ | F-001 ~ F-010 全部验收项 |
| 长时间运行稳定性 | 运行 1 小时，监控内存/CPU | 内存增长 < 50MB |
| 异常恢复 | 拔麦克风、杀进程、权限撤销 | 不崩溃、提示清晰 |

### 9.3 测试数据准备

| 资源 | 说明 | 来源 |
|------|------|------|
| `tests/fixtures/silence_1s.wav` | 1 秒纯静音 | 生成 |
| `tests/fixtures/speech_short.wav` | 短句「今天天气真好」 | 录制 |
| `tests/fixtures/speech_long.wav` | 长句 > 30 秒 | 录制 |
| `tests/fixtures/speech_pause.wav` | 含 0.5s/1s/2s 停顿的语音 | 录制/合成 |
| `tests/fixtures/noise.wav` | 白噪声/环境噪音 | 生成 |
| `tests/fixtures/expected/` | 对应音频的标注文本 | 人工标注 |

### 9.4 测试执行规范

```bash
# 单元测试
pytest tests/ -m "not slow and not integration" -v --cov=core --cov-report=html

# 集成测试（需要已下载模型）
pytest tests/ -m "integration" -v

# E2E 测试（需要真实麦克风硬件）
pytest tests/ -m "e2e" -v

# 全量测试
pytest tests/ -v --cov=core --cov-report=term-missing

# 代码质量检查
ruff check core/ tests/
mypy core/ --ignore-missing-imports
```

### 9.5 测试文档总结

| 文档 | 位置 | 内容 |
|------|------|------|
| 测试策略 | `tests/README.md` | 测试分层、执行方法、覆盖率目标 |
| 测试用例说明 | 各 `test_*.py` 文件顶部的 docstring | 每个测试类的目的和覆盖范围 |
| 测试数据说明 | `tests/fixtures/README.md` | 测试音频的来源、标注、用途 |

### 9.6 CI/CD 集成

```yaml
# .github/workflows/test.yml
name: Test

on:
  push:
    branches: [develop]
  pull_request:
    branches: [develop]

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -r requirements.txt
      - run: pip install -r requirements-dev.txt
      - run: pytest tests/ -v --cov
      - run: ruff check core/
```

---

## 10. Agent 工作流规范

本项目采用 **三阶段 Agent 工作流**，确保每次开发任务的质量和可追溯性。

### 10.1 工作流总览

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  阶段一       │     │  阶段二       │     │  阶段三       │
│  需求文档     │────►│  编码实现     │────►│  实现文档     │
│               │     │               │     │               │
│  · 需求分析   │     │  · 编码       │     │  · API 文档   │
│  · 功能拆分   │     │  · 单元测试   │     │  · 实现日志   │
│  · 技术方案   │     │  · 集成测试   │     │  · 变更记录   │
│  · 接口设计   │     │  · 代码审查   │     │  · 设计决策   │
└──────────────┘     └──────────────┘     └──────────────┘
```

### 10.2 阶段一：编写需求文档

**触发条件**：每个功能模块/Feature 开始前

**输入**：
- 用户需求描述
- `REQUIREMENTS.md`（本文档）
- 相关模块的现有代码

**输出**：
- 模块级需求文档（`docs/specs/feat-xxx.md`）

**规范流程**：

```
步骤 1: 需求分析
  - 阅读 REQUIREMENTS.md 和 prompt.md 了解整体定位
  - 分析目标模块的功能边界和依赖关系
  - 明确输入/输出数据格式

步骤 2: 功能拆分
  - 将模块功能拆分为可独立测试的子功能
  - 为每个子功能编写验收标准
  - 标注优先级：P0（必须）/ P1（重要）/ P2（可选）

步骤 3: 技术方案
  - 选择技术实现路径
  - 设计类结构和接口
  - 考虑边界条件和异常路径
  - 评估性能影响

步骤 4: 接口设计
  - 定义公开 API（类名、方法签名、参数类型）
  - 定义内部数据流
  - 定义线程安全策略（如适用）

步骤 5: 产出文档
  - 编写结构化需求文档
  - 提交至 docs/specs/ 目录
  - 在文档中标注模块实现顺序和依赖
```

**需求文档模板**：

```markdown
# Feature Spec: [功能名称]

> 版本: v0.1.0 | 状态: 设计阶段 | 作者: [Agent]

## 1. 功能概述
[1-2 段说明该功能做什么、为什么需要]

## 2. 功能需求
| 编号 | 需求 | 优先级 | 验收标准 |
|------|------|--------|---------|
| F-xxx | ... | P0/P1/P2 | ... |

## 3. 技术方案
[技术选型、关键算法、数据流]

## 4. 接口设计
### 公开 API
### 内部数据结构
### 线程安全策略

## 5. 测试计划
[测试策略、测试用例概要]

## 6. 依赖与前置条件
[依赖哪些模块/库]

## 7. 风险与缓解
| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
```

### 10.3 阶段二：编码实现

**触发条件**：需求文档完成并审查通过

**输入**：
- 模块需求文档
- `ARCHITECTURE.md`（架构约束）
- 现有代码库

**输出**：
- 模块源代码（`core/*.py`）
- 单元测试（`tests/*.py`）
- 类型注解 (mypy 通过)

**规范流程**：

```
步骤 1: 环境准备
  - 确认在正确的 feat/* 分支
  - 安装依赖：pip install -r requirements.txt
  - 加载相关模块的现有代码

步骤 2: 编码实现
  - 按需求文档的接口设计实现
  - 遵循目录结构约束（core/、utils/）
  - 核心逻辑不省略、不简化
  - 在类/方法/状态机处添加数据流向注释
  - 使用 type hints 标注参数和返回值

步骤 3: 单元测试
  - 为每个公开方法编写测试
  - Mock 外部依赖（sounddevice, whisper, pynput）
  - 覆盖正常路径 + 异常路径 + 边界条件
  - 确保测试可独立运行（不依赖硬件）

步骤 4: 代码审查（自查）
  - 检查回调函数是否极简（audio.py）
  - 检查线程安全（Queue 是否正确使用）
  - 检查资源释放（__del__ / context manager）
  - 检查权限降级路径（typer.py）
  - ruff check + mypy 通过

步骤 5: 提交
  - 按 Conventional Commits 规范提交
  - 单模块单提交（不混入无关变更）
  - git fetch origin && git rebase origin/develop
```

**编码硬性指标**（来自 prompt.md）：

| 文件 | 硬性要求 |
|------|---------|
| `config.py` | 必须包含 6 项核心参数（SAMPLE_RATE/CHANNELS/FRAME_DURATION_MS/SILENCE_LIMIT_MS/MODEL_SIZE/COMPUTE_TYPE） |
| `core/audio.py` | 回调函数必须极简，只做 `queue.put()` |
| `core/detector.py` | 滑动窗口必须拆分为 320 samples/帧，防抖机制必须实现 |
| `core/recognizer.py` | 模型单例加载，`int8` 量化，`beam_size=3` |
| `core/typer.py` | 字符间延迟 5ms，`try-except` 兜底剪贴板 |
| `main.py` | `Ctrl+C` 信号捕获，优雅关闭所有线程 |

### 10.4 阶段三：输出实现文档

**触发条件**：模块编码完成并通过测试

**输入**：
- 已实现的模块代码
- 测试结果
- 模块需求文档

**输出**：
- 实现文档（`docs/impls/impl-xxx.md`）
- API 参考更新（`docs/api.md`）
- 变更日志更新（`CHANGELOG.md`）

**规范流程**：

```
步骤 1: 实现文档编写
  - 记录实际的类结构和方法签名
  - 补充需求阶段未预见的实现细节
  - 标注与需求文档的偏差及原因
  - 记录关键设计决策

步骤 2: API 文档更新
  - 更新 docs/api.md 中对应模块的接口说明
  - 添加使用示例代码
  - 标注参数类型和返回值

步骤 3: 变更日志更新
  - 在 CHANGELOG.md [Unreleased] 区域添加条目
  - 格式：Added / Changed / Fixed

步骤 4: 归档
  - 将 impl-xxx.md 提交至 docs/impls/
  - 关联 spec-xxx.md 与 impl-xxx.md（交叉引用）
```

**实现文档模板**：

```markdown
# Implementation Doc: [模块名称]

> 版本: v0.1.0 | 关联 Spec: docs/specs/feat-xxx.md

## 1. 实现概述
[实际实现与需求的对应关系]

## 2. 类与方法清单
| 类/方法 | 功能 | 关键决策 |
|---------|------|---------|

## 3. 与需求的偏差
| 编号 | 需求 | 实际实现 | 原因 |
|------|------|---------|------|

## 4. 测试覆盖
| 测试文件 | 测试数量 | 覆盖率 |
|---------|---------|--------|

## 5. 已知问题
| 编号 | 描述 | 影响 | 计划 |
|------|------|------|------|

## 6. 性能基准
| 指标 | 目标 | 实际 | 状态 |
|------|------|------|------|
```

### 10.5 Agent 协作规范

**单 Agent 工作模式**：

```
[需求文档 Agent] → 产出 spec-xxx.md
        ↓
[编码 Agent]     → 产出 模块代码 + 测试
        ↓
[文档 Agent]     → 产出 impl-xxx.md + 更新 CHANGELOG
```

**多 Agent 并行规则**：

- 不同模块可并行开发（如 Phase 1 的 audio.py 和 config.py）
- 同一模块的三个阶段必须串行
- 共享模块（config.py, manager.py）修改时需要通知其他 Agent

---

## 附录 A：环境要求

| 组件 | 最低版本 | 推荐版本 | 说明 |
|------|---------|---------|------|
| Python | 3.10 | 3.12 | 3.13+ 待验证 |
| pip | 23.0 | 24.0 | |
| PortAudio | 19.6 | 19.7 | sounddevice 底层依赖 |
| CTranslate2 | 4.0 | 4.5 | faster-whisper 底层依赖 |
| 操作系统 | Windows 10 | Windows 11 | |
| | macOS 12 (Monterey) | macOS 14 (Sonoma) | |
| | Ubuntu 20.04 | Ubuntu 24.04 | |
| 内存 | 4GB | 8GB+ | base 模型 ~300MB |
| 磁盘空间 | 1GB | 2GB+ | 含模型文件 |

## 附录 B：参考资源

| 资源 | 链接 |
|------|------|
| faster-whisper GitHub | https://github.com/SYSTRAN/faster-whisper |
| sounddevice 文档 | https://python-sounddevice.readthedocs.io/ |
| webrtcvad GitHub | https://github.com/wiseman/py-webrtcvad |
| pynput 文档 | https://pynput.readthedocs.io/ |
| CTranslate2 | https://github.com/OpenNMT/CTranslate2 |
| Whisper 模型对比 | https://github.com/openai/whisper#available-models-and-languages |
| HuggingFace 镜像 | https://hf-mirror.com |

---

> **文档维护**：本文档随项目迭代持续更新。重大变更需经过设计审查后合入 `develop` 分支。
