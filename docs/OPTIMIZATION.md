# vType 优化日志

> 记录项目 v0.1.0 完成后的优化项，按时间倒序排列。

---

## 2026-05-25

### 修复 3：Git remote URL 明文 Token 泄露（T-06）

**严重度**：高

**现象**：`origin` remote URL 中嵌入了 GitHub Personal Access Token（`https://ghp_xxx@github.com/...`），任何可访问 `.git/config` 的人都能获取 Token。

**修复**：`git remote set-url origin git@github.com:heguang123456/vType.git` 切换为 SSH 方式。

**后续**：需在 GitHub Settings → Developer settings → Personal access tokens 中吊销已暴露的 Token。

**涉及文件**：`.git/config`

---

### 修复 4：模型重复加载（T-01）

**严重度**：中

**现象**：`CoreManager.stop()` + `start()` 时，`_cleanup()` 将 `self._recognizer` 置 None，下次 `start()` → `_create_modules()` 必须重新 `Recognizer(...)` 并加载 Whisper 模型（5-15 秒）。

**根因**：`_cleanup()` 无条件释放所有子模块引用，包括已加载的模型。

**修复**：
1. `_cleanup()` 保留 `self._recognizer` 引用（不置 None）
2. `_create_modules()` 新增 `_recognizer_matches_cfg()` 检查：`model_size` 和 `language` 不变则复用已有模型
3. 新增 `TestRecognizerReuse` 测试类（3 个用例）

**涉及文件**：`core/manager.py:376-395`, `core/manager.py:500-505`, `tests/test_manager.py`

---

### 文档 1：HF Hub 国内镜像配置（T-02）

**严重度**：中

**内容**：在 `README.md` 安装指南中新增「中国大陆用户：加速模型下载」章节，详细说明：
- 临时/永久设置 `HF_ENDPOINT=https://hf-mirror.com` 环境变量
- 备选镜像列表
- 模型缓存路径说明

**涉及文件**：`README.md:174-208`

---

### 文档 2：Windows symlinks 兼容性（T-03）

**严重度**：低

**内容**：在 `README.md` 安装指南中新增「Windows 用户：文件系统兼容性设置」章节，提供两种方案：
- **方案 A**：`HF_HUB_DISABLE_SYMLINKS_WARNING=1` 消隐警告（推荐）
- **方案 B**：开启 Windows 开发者模式启用真正符号链接

**涉及文件**：`README.md:210-231`

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

### T-04：Phase 2-3 未遵循 Git Flow

**描述**：Phase 2（M-04/M-05）和 Phase 3（M-06~M-09）的 5 个 commit 直接落在 develop 分支，未创建 `feat/phase2-*` 和 `feat/phase3-*` 分支。

**建议**：后续新功能严格走 `feat/* → develop → main` 流程，合入使用 `--no-ff`。此条为流程记录，无需代码变更。commit 历史无法改写，作为教训记录。

---

### T-05：git user.name 不正确

**描述**：仓库 local git config 中 `user.name` 为 `FFY`，非 heguang 本人的名字。

**状态**：✅ 已修复（`git config user.name "heguang"`）
