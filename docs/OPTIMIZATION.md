# vType 优化日志

> 记录项目 v0.1.0 完成后的优化项，按时间倒序排列。

---

## 2026-05-24

### 修复 1：Shutdown 摘要 Segments 始终为 0

**严重度**：中

**现象**：每次退出时 Summary 显示 `Segments: 0`，但 Detector 实际处理了多段语音。

**根因**：`_shutdown()` 中 `_manager.stop()` 先于 `_print_summary()` 执行，stop() 内部调用 `_cleanup()` 将 `self._detector` 置为 None，导致 `statistics` 属性无法读取 `detector_slices`。

**修复**：`_shutdown()` 中在调用 `_manager.stop()` 之前通过 `_manager.statistics` 快照统计数据，然后将快照传入 `_print_summary(stats)`。

**涉及文件**：`main.py:352-429`

---

### 修复 2：模型加载提示错位

**严重度**：低

**现象**：启动时先输出 "Loading faster-whisper base model..."，紧接着 "Model loaded (CPU, int8)."，但实际模型加载发生在用户首次按热键后，两者时间差可达数分钟。

**根因**：`CoreManager.__init__()` 仅存储配置参数，无任何重量操作。但 start 命令在 `__init__` 前后用 `click.echo` 输出了加载提示。实际模型加载发生在 `start()` → `_create_modules()` → `Recognizer.__init__()`。

**修复**：移除两条误导性 echo，替换为 "vType initializing..."。模型加载的实际日志由 `core.recognizer` logger 输出（INFO 级别）。

**涉及文件**：`main.py:145-150`

---

## 已知待优化项（未实施）

### T-01：模型重复加载

**描述**：当前 `main.py` 启动时会通过 `CoreManager.__init__()` 不加载模型，但首次按热键时 `CoreManager.start()` → `_create_modules()` → `Recognizer()` 会加载模型。如果用户两次按热键之间调用了 `stop()` + `start()`，模型会被重新加载。

**建议**：让 `CoreManager` 在构造时延迟模型加载，并在 `_cleanup()` 中保留已加载的模型实例而不是置 None，避免重复加载。

**影响**：每次模型加载约 3-20 秒，影响用户体验。

---

### T-02：HuggingFace 未认证下载慢

**描述**：国内下载 HF Hub 模型时受限速和镜像问题，日志中出现 `Warning: You are sending unauthenticated requests to the HF Hub`。

**建议**：
- 设置环境变量 `HF_ENDPOINT=https://hf-mirror.com` 使用国内镜像
- 设置 `HF_TOKEN` 提升速率限制
- Windows 下设置 `HF_HUB_DISABLE_SYMLINKS_WARNING=1` 消除 symlinks 警告

**影响**：首次运行下载模型时间长。

---

### T-03：Windows symlinks 警告

**描述**：Windows 未开启开发者模式时，`huggingface_hub` 缓存系统降级为文件复制（而非 symlinks），多占磁盘空间并输出警告。

**建议**：文档中说明两种解决方案：(1) 开启 Windows 开发者模式；(2) 设 `HF_HUB_DISABLE_SYMLINKS_WARNING=1` 环境变量。

---

### T-04：Phase 2-3 未遵循 Git Flow

**描述**：Phase 2（M-04/M-05）和 Phase 3（M-06~M-09）的 5 个 commit 直接落在 develop 分支，未创建 `feat/phase2-*` 和 `feat/phase3-*` 分支。

**建议**：后续新功能严格走 `feat/* → develop → main` 流程，合入使用 `--no-ff`。此条为流程记录，无需代码变更。

---

### T-05：git user.name 不正确

**描述**：仓库 local git config 中 `user.name` 为 `FFY`，非 heguang 本人的名字。

**建议**：执行 `git config user.name "heguang"` 修正。

---

### T-06：remote URL 含明文 Token

**描述**：`origin` remote URL 中嵌入了 GitHub Personal Access Token (`https://ghp_xxx@github.com/...`)。

**建议**：替换为 SSH 方式 (`git@github.com:heguang123456/vType.git`)，或使用 Git credential manager 存储 token。

**影响**：仓库 `.git/config` 文件泄露风险。
