# vType 项目状态 — 交接日志

> 最后更新：2026-05-25 19:33
> 压缩方式：Context Compressor v1.0

## 版本信息

- **当前版本**：v0.1.0
- **分支**：`develop`（已合入 `main`，worktree clean）
- **状态**：可发布 — 核心功能全部完成

## 核心指标

| 指标 | 数值 |
|------|------|
| 模块完成度 | **9/9（100%）** |
| 测试总数 | **279** |
| 测试通过率 | **100%（279 passed）** |
| 源代码行数 | 2,105 行 |
| 测试代码行数 | 3,754 行 |
| 测试/源码比 | 1.78:1 |
| 上次全量测试 | 2026-05-24 14:51 |

## 模块进度

| # | 模块 | 文件 | 测试数 | 状态 |
|---|------|------|--------|------|
| M-01 | 配置中心 | `config.py` | 53 | ✅ |
| M-02 | 音频捕获 | `core/audio.py` | 32 | ✅ |
| M-03 | 人声检测 | `core/detector.py` | 31 | ✅ |
| M-04 | ASR 推理 | `core/recognizer.py` | 25 | ✅ |
| M-05 | 键盘模拟 | `core/typer.py` | 20 | ✅ |
| M-06 | 核心调度 | `core/manager.py` | 42 | ✅ |
| M-07 | CLI 入口 | `main.py` | 31 | ✅ |
| M-08 | 剪贴板 | `utils/clipboard.py` | 16 | ✅ |
| M-09 | 快捷键监听 | `utils/key_monitor.py` | 29 | ✅ |

## 当前任务（TODO）

- [x] **T-01**：模型重复加载 — `_cleanup()` 保留 `_recognizer` 引用，`_create_modules()` 检查参数匹配（`core/manager.py`）
- [x] **T-02**：HF Hub 国内下载慢 — README 新增「加速模型下载」章节（`README.md:174-208`）
- [x] **T-03**：Windows symlinks 警告 — README 新增「文件系统兼容性设置」章节（`README.md:210-231`）
- [x] **T-04**：Git Flow 流程规范 — README 新增详细标准工作流 + 发布流程 + Phase 2-3 教训（`README.md:353-410`）
- [x] **T-06**：Remote URL 含明文 PAT Token — 切换为 SSH（`git@github.com:heguang123456/vType.git`）

> ✅ 全部 5 项待办已于 2026-05-25 完成。T-05（git user.name）已于 05-24 修复。

## 目录树快照

```
└── vType/
    ├── core/ 核心模块（音频、检测、识别、打字、调度）
    │   ├── __init__.py
    │   ├── audio.py ← 音频捕获：sounddevice 流模式，PortAudio 回调线程
    │   ├── detector.py ← 人声检测：WebRTC VAD 状态机，静音切片 + 防抖缓冲
    │   ├── manager.py ← 核心调度器：3 线程拓扑 + 生命周期状态机
    │   ├── recognizer.py ← ASR 推理：faster-whisper int8 量化，单例模型加载
    │   └── typer.py ← 键盘模拟：pynput 输出引擎，剪贴板粘贴兜底
    ├── docs/ 文档（需求规格 specs、实现文档 impls）
    │   ├── impls/（8 份实现文档）
    │   ├── specs/（9 份需求规格）
    │   └── OPTIMIZATION.md
    ├── tests/ 测试套件（pytest，10 个测试文件）
    ├── utils/ 工具模块
    │   ├── clipboard.py ← 剪贴板操作：pyperclip + pynput 快捷键模拟
    │   └── key_monitor.py ← 全局热键监听：push-to-talk 交互，组合键支持
    ├── config.py ← 全局配置中心：16 项核心参数，环境变量 VTYPE_* 覆盖
    ├── main.py ← CLI 入口：Click 框架，vtype start/devices/config 命令
    └── [配置文件] requirements.txt, requirements-dev.txt, CHANGELOG.md, README.md
```

## 最近变更（最近 3 天）

- **fix**: Git remote URL 含明文 PAT Token — 切换为 SSH（T-06，安全修复）
- **fix**: 模型重复加载 — `_cleanup()` 保留 Recognizer 引用，stop+start 复用模型（T-01）
- **docs**: README 新增 HF Hub 国内镜像配置 + Windows symlinks 兼容性章节（T-02, T-03）
- **docs**: README 扩展 Git Flow 标准工作流 + 发布流程 + Phase 2-3 教训（T-04）
- **test**: manager 新增 3 个 Recognizer 复用测试，总数 279
- **fix**: Shutdown 摘要 Segments 始终为 0 — stop() 前快照 statistics
- **fix**: 模型加载提示错位 — 移除误导性 echo
- **docs**: 创建 `docs/OPTIMIZATION.md`，记录 2 项已修复 + 6 项待优化
- **chore**: 修正 git user.name (FFY → heguang)

## 已知风险

| 风险 | 严重程度 | 状态 |
|------|----------|------|
| ~~Remote URL 含明文 GitHub PAT Token~~ | ~~高~~ | ✅ 已修复（T-06，切换 SSH） |
| ~~stop/start 导致模型重复加载~~ | ~~中~~ | ✅ 已修复（T-01，模型缓存） |
| HF Hub 国内未认证下载慢 | 中 | ✅ 已文档化（README 镜像配置） |
| Windows symlinks 警告 | 低 | ✅ 已文档化（README 兼容性章节） |
| Enum 身份 vs importlib.reload 跨文件污染 | 中 | ✅ 已知陷阱，测试已规避 |
| webrtcvad None guard 防御 | 低 | ✅ 已加 ImportError 守卫 |
| 模块级常量作为函数默认参数 | 低 | ✅ 已知陷阱，测试显式传参 |

## 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python ≥ 3.10（推荐 3.12） |
| 音频 | `sounddevice`（PortAudio）+ `webrtcvad-wheels` |
| ASR | `faster-whisper`（CTranslate2，int8 量化） |
| 键盘 | `pynput`（SendInput/CGEvent/Xlib）+ `pyperclip` 兜底 |
| CLI | `click` |
| 测试 | `pytest` + `pytest-mock` |
| 质量 | `ruff` + `mypy` |

## 架构要点

- **线程拓扑**：3 工作线程（detector/recognizer/typer）+ 1 PortAudio 回调线程
- **数据管道**：`audio_queue (Queue[bytes])` → `text_queue (Queue[str])` 两阶段
- **状态机**：采集器 LISTENING↔RECORDING，消费者 IDLE↔TRANSCRIBING↔TYPING
- **硬性指标**：SAMPLE_RATE=16000, CHANNELS=1, FRAME_DURATION=20ms, SILENCE_LIMIT=800ms, MODEL=base, COMPUTE=int8

<!-- SPLIT: status | todo | architecture -->
<!-- status: 版本信息 + 核心指标 -->
<!-- todo: 当前任务 + 已知风险 -->
<!-- architecture: 目录树快照 + 技术栈 + 架构要点 -->
