# 角色与任务
你是一个精通 Python 异步并发编程、音频信号处理（DSP）以及操作系统底层 API 的资深系统架构师。
请根据以下详细的Prompt文档，为我编写一套高性能、高稳定性、离线运行的“命令行语音输入法（CLI Voice Input）”的需求文档。

---

## 一、 项目整体定位
一款完全运行在本地、轻量级、跨平台的命令行语音输入法。
- **核心体验**：用户在后台运行该工具，直接用麦克风说话，程序自动在当前系统光标处“盲打”吐出对应的文字。
- **设计哲学**：高内聚低耦合，严格防范硬件丢帧，极限榨干本地 CPU 推理性能，面向 Vibe Coding 的模块化设计。

---

## 二、 核心技术选型与底层原理
请严格基于以下技术栈进行开发，不得自行替换核心库：
1. **音频采集层 (`sounddevice`)**：使用流模式（Stream Callback）捕获硬件音频。原理：直接获取硬件中断的 NumPy 数组，规避传统字节码转换。
2. **人声检测层 (`webrtcvad`)**：谷歌开源 C 语言 VAD 算法的 Python 封装。原理：通过高频、轻量的时域特征分析判断人声，单帧推理 $\mu s$ 级，CPU 占用接近 0%。
3. **语音识别层 (`faster-whisper`)**：基于 CTranslate2 的 Whisper C++ 移植版。原理：采用 `int8` 量化加速推理，将传统 Transformer 本地推理的内存与 CPU 损耗降低 4 倍以上。
4. **输出模拟层 (`pynput` + 剪贴板兜底)**：调用系统底层 API（Windows `SendInput` / macOS `CGEvent`）实现后台全局模拟敲击。

---

## 三、 系统高可用架构（核心：生产者-消费者双线程事件驱动）
为了防止本地 ASR 推理时发生同步阻塞导致麦克风丢帧，必须严格采用以下**双线程 + 线程安全队列（Queue）**架构：

### 1. 数据拓扑流
- **线程 A（采集与检测线程 - 生产者）**：
  硬件麦克风 -> `sounddevice` 流回调 -> 拆分为 20ms 滑动窗口帧 -> `webrtcvad` 判断状态 -> 触发“静音切片事件” -> 将整段有效人声音频（NumPy Array）塞入 `TaskQueue`。
- **线程 B（推理与输出线程 - 消费者）**：
  持续监听 `TaskQueue` -> 阻塞等待直到有新任务 -> 唤醒 `faster-whisper` 推理 -> 得到文本 -> 调度 `TypeWriter` 写入光标 -> 重新进入休眠。

### 2. 并发状态机控制
- **采集器状态**：`LISTENING`（静音监听） <-> `RECORDING`（人声录制中）
- **消费者状态**：`IDLE`（空闲等待） <-> `TRANSCRIBING`（AI 推理与打印中）

---

## 四、 目录结构设计（严格对齐）
请按照以下结构组织模块，严禁写成单个过程式长脚本：
voicetype-cli/
├── config.py             # 全局配置（参数见下文）
├── main.py               # Click 命令行入口、多线程启动与优雅退出
└── core/
    ├── __init__.py
    ├── manager.py        # 核心调度器：初始化 TaskQueue，管理生产者/消费者生命周期
    ├── audio.py          # 生产者：sounddevice 硬件流监听与 NumPy 数据捕获
    ├── detector.py       # 状态机：webrtcvad 20ms 滑动窗口切片逻辑
    ├── recognizer.py     # 消费者：faster-whisper int8 量化本地推理后端
    └── typer.py          # 消费者：pynput 键盘模拟输入与剪贴板权限兜底

---

## 五、 各模块深度防翻车设计要点（开发硬性指标）

### 1. `config.py`（参数配置）
必须包含且不限于：
- `SAMPLE_RATE = 16000`（Whisper 强制标准输入）
- `CHANNELS = 1`（单声道，webrtcvad 强制标准）
- `FRAME_DURATION_MS = 20`（滑动窗口大小，只能是 10/20/30）
- `SILENCE_LIMIT_MS = 800`（连续静音超过此阈值即切片发送给 ASR）
- `MODEL_SIZE = "base"`（默认模型大小）
- `COMPUTE_TYPE = "int8"`（强制 CPU 量化加速）

### 2. `core/audio.py` & `core/detector.py`（生产者控制）
- `audio.py` 的 `InputStream` 回调函数必须保持极简，只负责把数据 `put` 到内部的原始音频队列，绝不能在回调里做耗时计算。
- `detector.py` 必须实现滑动窗口算法：把捕获的音频分割成每帧 320 个采样点（即 16000Hz * 0.02s）的 `int16` 字节流，喂给 `webrtcvad.Vad(3).is_speech()`。
- **状态切换防抖**：当处于 `RECORDING` 状态，且连续错失的语音帧时长（计满次数）超过 `SILENCE_LIMIT_MS` 时，将缓存的全部帧合并为单个 NumPy 数组，塞入全局 `TaskQueue`。

### 3. `core/recognizer.py`（消费者推理）
- 初始化时，在独立消费者线程中单例加载 `WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")`。
- 接收到音频后，调用 `transcribe()` 并在参数中锁死 `language="zh"`（或支持中英自适应），`beam_size=3`平衡速度与精度。

### 4. `core/typer.py`（输出与系统权限防翻车）
- **键盘流式或匀速打印**：使用 `pynput.keyboard.Controller` 逐字输入，字符间加入 `time.sleep(0.005)` 防止在某些敏感终端里因速度过快被系统拦截。
- **跨平台鲁棒性兜底**：必须使用 `try-except` 包裹 `pynput` 的调用。一旦发生操作系统权限拒绝（如 macOS 未获 Accessibility 授权），自动切换为**隐式兜底方案**：将文本写入系统剪贴板（如使用 `pyperclip` 或原生 API），然后模拟触发一次 `Ctrl+V` (Windows/Linux) 或 `Cmd+V` (macOS)。

### 5. `main.py` & `utils/key_monitor.py`（全局生命周期与快捷键）
- 使用 `click` 包装 CLI，允许用户启动时指定 `--model_size`。
- 必须实现 `Ctrl+C` 信号捕获，退出时优雅关闭 `sounddevice` 音频流，清空线程，避免导致终端硬件音频常驻死锁。
- **后续拓展预留**：请在架构中预留一个全局热键监听接口（如通过 `pynput` 全局监听 `Alt+V`），按下后可以切换一个布尔值 `IS_PAUSED`，用来暂停/恢复 `audio.py` 的录音行为。

---

## 六、 交付要求
1. **代码质量**：在代码实现过程中，不省略核心逻辑。
2. **清晰注释**：在代码实现过程中，在每个类、核心异步循环、状态机切换处写明数据流向和设计意图。