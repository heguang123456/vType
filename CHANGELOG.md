# Changelog

All notable changes to vType will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- M-01: `config.py` — 全局配置中心，16 项核心参数，环境变量覆盖支持（`VTYPE_*` 前缀）
- M-02: `core/audio.py` — sounddevice 流模式音频捕获，极简回调设计，32 个测试
- M-03: `core/detector.py` — WebRTC VAD 状态机 + 静音切片，防抖缓冲机制，31 个测试
- M-04: `core/recognizer.py` — faster-whisper int8 量化推理引擎，单例模型加载，25 个测试
- 项目骨架：`requirements.txt`、`requirements-dev.txt`、`.gitignore`、目录结构
- 需求文档：`REQUIREMENTS.md`（完整 10 章）、`prompt.md`（设计 prompt）

- M-05: `core/typer.py` — pynput 键盘模拟输出引擎，剪贴板粘贴兜底，20 个测试
- M-08: `utils/clipboard.py` — 跨平台剪贴板操作封装，pyperclip + pynput 快捷键模拟，16 个测试
- M-06: `core/manager.py` — 核心调度器，3 线程拓扑 + 生命周期状态机 + 优雅停止序列，39 个测试
- M-09: `utils/key_monitor.py` — 全局热键监听，push-to-talk 交互模式，Listener + 手动追踪 + 组合键支持，29 个测试
- M-07: `main.py` — CLI 入口（Click 框架），`vtype start/devices/config` 命令，信号处理 + KeyMonitor 集成，31 个测试

### Fixed

- 测试排序 Bug：`pytest tests/` 按字母序运行时 hang（根因：`test_config.py` autouse fixture 删除 `sys.modules["config"]` 未恢复，导致 `test_main.py` 模块身份不一致触发死锁）
- **T-01**：模型重复加载 — `CoreManager._cleanup()` 保留 `_recognizer` 引用，`_create_modules()` 复用已加载模型（`core/manager.py:376-395, 500-505`）
- **T-06**：Git remote URL 含明文 PAT Token — 切换为 SSH（`git@github.com:heguang123456/vType.git`）

### Documentation

- **T-02**：README 新增「中国大陆用户：加速模型下载」章节（`HF_ENDPOINT` 镜像配置）
- **T-03**：README 新增「Windows 用户：文件系统兼容性设置」章节（symlinks 警告处理）
- **T-04**：README 扩展 Git Flow 标准工作流 + 发布流程 + Phase 2-3 教训
- `docs/OPTIMIZATION.md`：优化日志重构，按时间倒序，记录 4 项已修复 + 2 项流程记录

- `docs/specs/feat-config.md` — M-01 需求规格
- `docs/specs/feat-audio.md` — M-02 需求规格
- `docs/specs/feat-detector.md` — M-03 需求规格
- `docs/specs/feat-recognizer.md` — M-04 需求规格
- `docs/specs/feat-typer.md` — M-05 需求规格
- `docs/specs/feat-clipboard.md` — M-08 需求规格
- `docs/impls/impl-config.md` — M-01 实现文档
- `docs/impls/impl-audio.md` — M-02 实现文档
- `docs/impls/impl-detector.md` — M-03 实现文档
- `docs/impls/impl-recognizer.md` — M-04 实现文档
- `docs/impls/impl-typer.md` — M-05 实现文档
- `docs/impls/impl-clipboard.md` — M-08 实现文档
- `docs/impls/impl-manager.md` — M-06 实现文档
- `docs/impls/impl-key-monitor.md` — M-09 实现文档
- `docs/specs/feat-manager.md` — M-06 需求规格
- `docs/specs/feat-key-monitor.md` — M-09 需求规格
- `docs/specs/feat-main.md` — M-07 需求规格
