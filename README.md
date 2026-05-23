# vType — CLI Voice Input

> **Command-line voice typing tool | 命令行语音输入法**

[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue?logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)
[![Phase 1](https://img.shields.io/badge/phase-1%20complete-brightgreen)](#-phase-1--infrastructure-foundation)

**vType** is a fully local, lightweight, cross-platform CLI voice input tool. Speak into your microphone and the recognized text is automatically typed at the current cursor position — like a virtual keyboard driven by your voice.

Built for **Vibe Coding** workflows: high cohesion, low coupling, aggressive CPU optimization, and zero network dependency.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Development](#development)
- [Roadmap](#roadmap)
- [License](#license)

---

## Features

- **100% Local**: No cloud API, no internet required. All processing runs on your CPU.
- **Cross-Platform**: Windows (SendInput), macOS (CGEvent), Linux (Xlib) — with clipboard fallback.
- **Low Latency**: Producer-Consumer dual-thread architecture prevents audio frame drops during inference.
- **CPU Optimized**: `faster-whisper` with `int8` quantization — 4x memory reduction vs. standard Whisper.
- **Smart VAD**: Google WebRTC Voice Activity Detection with silence-based auto-slicing and debounce.
- **Graceful Degradation**: Automatic clipboard paste fallback when OS permissions are denied.
- **Environment Variable Override**: All parameters can be customized via `VTYPE_*` environment variables.

---

## Architecture

### Dual-Thread Producer-Consumer Model

```
┌─────────────────────────────────────────────────────────┐
│                     THREAD A (Producer)                  │
│                                                         │
│  Mic ──► sounddevice InputStream ──► Raw Audio Queue    │
│                                          │               │
│                                          ▼               │
│                            webrtcvad VAD (20ms frames)   │
│                                          │               │
│                              ┌───────────┴───────────┐   │
│                              │  LISTENING ↔ RECORDING │   │
│                              └───────────┬───────────┘   │
│                                          │               │
│                           Silence slice (800ms)          │
│                                    │                     │
└────────────────────────────────────┼─────────────────────┘
                                     │
                              TaskQueue (thread-safe)
                                     │
┌────────────────────────────────────┼─────────────────────┐
│                     THREAD B (Consumer)                  │
│                                    ▼                     │
│                   faster-whisper (int8, CPU)             │
│                                    │                     │
│                              Recognized Text             │
│                                    │                     │
│                    ┌───────────────┴───────────────┐     │
│                    │  IDLE ↔ TRANSCRIBING ↔ TYPING  │     │
│                    └───────────────┬───────────────┘     │
│                                    │                     │
│              pynput Keyboard Controller / Clipboard      │
│                                    │                     │
│                              Cursor Output               │
└─────────────────────────────────────────────────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Callback minimal (< 50μs) | Only `copy + put_nowait` in audio callback, zero computation |
| 20ms sliding window | WebRTC VAD native frame size for μs-level inference |
| int8 quantization | 4x memory reduction, 2-3x speedup on CPU |
| Silence debounce (800ms) | Prevents mid-sentence splits; short pauses preserved |
| Clipboard fallback | macOS Accessibility denial → `Cmd+V` paste instead of failure |

---

## Tech Stack

| Layer | Library | Purpose |
|-------|---------|---------|
| Audio Capture | `sounddevice` (PortAudio) | Hardware mic stream → NumPy arrays |
| Voice Detection | `webrtcvad` / `webrtcvad-wheels` | Google VAD, μs-level inference |
| Speech Recognition | `faster-whisper` (CTranslate2) | Whisper C++ port, int8 CPU inference |
| Keyboard Simulation | `pynput` | Windows `SendInput` / macOS `CGEvent` / Linux Xlib |
| Clipboard Fallback | `pyperclip` | Cross-platform clipboard access |
| CLI Framework | `click` | Command-line argument parsing |
| Testing | `pytest` + `pytest-mock` | Unit testing with mock support |
| Code Quality | `ruff` + `mypy` | Linting and static type checking |

---

## Project Structure

```
vType/
├── README.md                    # This file
├── REQUIREMENTS.md              # Detailed requirements & design specs
├── prompt.md                    # Original project prompt definition
├── config.py                    # Global configuration center (17 constants)
├── main.py                      # CLI entry point (Phase 2)
├── requirements.txt             # Production dependencies
├── requirements-dev.txt         # Development dependencies
├── core/
│   ├── __init__.py
│   ├── audio.py                 # M-02: Audio capture (sounddevice InputStream)
│   ├── detector.py              # M-03: Voice detection & silence slicing
│   ├── recognizer.py            # M-04: ASR inference (faster-whisper) [TODO]
│   ├── typer.py                 # M-05: Keyboard simulation & clipboard [TODO]
│   └── manager.py               # M-06: Core scheduler & thread lifecycle [TODO]
├── utils/
│   ├── __init__.py
│   ├── clipboard.py             # M-08: Cross-platform clipboard wrapper [TODO]
│   └── key_monitor.py           # M-09: Global hotkey listener [TODO]
├── tests/
│   ├── __init__.py
│   ├── test_config.py           # 53 tests
│   ├── test_audio.py            # 32 tests
│   └── test_detector.py         # 31 tests
└── docs/
    ├── specs/                   # Design specifications
    │   ├── feat-config.md
    │   ├── feat-audio.md
    │   └── feat-detector.md
    └── impls/                   # Implementation documentation
        ├── impl-config.md
        ├── impl-audio.md
        └── impl-detector.md
```

---

## Installation

### Prerequisites

- **Python ≥ 3.10** (recommended: 3.12)
- **pip** (Python package manager)
- A working microphone

### Quick Install

```bash
# Clone the repository
git clone https://github.com/yourusername/vType.git
cd vType

# Create and activate a virtual environment (recommended)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install production dependencies
pip install -r requirements.txt

# (China mainland users) Set HuggingFace mirror for faster model downloads
# PowerShell: $env:HF_ENDPOINT = "https://hf-mirror.com"
# Bash:      export HF_ENDPOINT=https://hf-mirror.com
```

### Platform-Specific Notes

| Platform | Notes |
|----------|-------|
| **Windows** | Works out of the box. No additional permissions needed. |
| **macOS** | Grant **Accessibility** permission in System Preferences → Security & Privacy → Privacy. Without it, clipboard fallback is used automatically. |
| **Linux** | May require `libportaudio2` (`sudo apt install libportaudio2`). Xlib permissions are typically available by default. |

### Python 3.12+ Note

For Python 3.12+, `webrtcvad-wheels` is used instead of the original `webrtcvad` to avoid C extension compilation issues:

```bash
pip install webrtcvad-wheels>=2.0.10
```

---

## Usage

> ⚠️ **Phase 1** (infrastructure) is complete — modules M-01 through M-03 are implemented and tested. The full CLI will be available in **Phase 2**.

### Validate Configuration (Available Now)

```python
from config import validate_config, print_config

errors = validate_config()
if errors:
    for e in errors:
        print(f"  - {e}")
else:
    print("Configuration OK")

print_config()  # Pretty-printed config summary
```

### Run Tests (Available Now)

```bash
# Run all tests
pytest tests/ -v

# Run specific module tests
pytest tests/test_config.py -v
pytest tests/test_audio.py -v
pytest tests/test_detector.py -v

# With coverage report
pytest tests/ --cov=. --cov-report=term-missing
```

### Full CLI (Phase 2 Target)

```bash
# Start voice typing (default model: base, int8 quantization)
vtype

# Specify model size
vtype --model small

# Run with verbose logging
vtype --verbose

# Graceful shutdown: Ctrl+C
```

---

## Configuration

All parameters have sensible defaults and can be overridden via environment variables with the `VTYPE_` prefix.

### Audio Capture

| Parameter | Default | Env Var | Description |
|-----------|---------|---------|-------------|
| `SAMPLE_RATE` | 16000 | `VTYPE_SAMPLE_RATE` | Audio sample rate (Hz). Whisper requires 16000. |
| `CHANNELS` | 1 | `VTYPE_CHANNELS` | Mono audio. Required by webrtcvad. |
| `FRAME_DURATION_MS` | 20 | `VTYPE_FRAME_DURATION_MS` | VAD frame duration (10/20/30ms). |
| `BLOCK_SIZE` | 320 | `VTYPE_BLOCK_SIZE` | Samples per frame (derived: rate × duration / 1000). |
| `DTYPE` | int16 | `VTYPE_DTYPE` | Sample data type. |

### Voice Detection

| Parameter | Default | Env Var | Description |
|-----------|---------|---------|-------------|
| `VAD_AGGRESSIVENESS` | 3 | `VTYPE_VAD_AGGRESSIVENESS` | VAD sensitivity (0=quiet, 3=noisy). |
| `SILENCE_LIMIT_MS` | 800 | `VTYPE_SILENCE_LIMIT_MS` | Silence threshold before slicing (ms). |

### Speech Recognition

| Parameter | Default | Env Var | Description |
|-----------|---------|---------|-------------|
| `MODEL_SIZE` | base | `VTYPE_MODEL_SIZE` | Whisper model (tiny/base/small/medium/large). |
| `COMPUTE_TYPE` | int8 | `VTYPE_COMPUTE_TYPE` | CTranslate2 compute type. |
| `DEVICE` | cpu | `VTYPE_DEVICE` | Inference device (cpu/cuda). |
| `BEAM_SIZE` | 3 | `VTYPE_BEAM_SIZE` | Beam search width (1-10). |
| `LANGUAGE` | zh | `VTYPE_LANGUAGE` | Recognition language. |

### Keyboard Output

| Parameter | Default | Env Var | Description |
|-----------|---------|---------|-------------|
| `TYPE_DELAY` | 0.005 | `VTYPE_TYPE_DELAY` | Inter-keystroke delay (seconds). |
| `CLIPBOARD_FALLBACK` | true | `VTYPE_CLIPBOARD_FALLBACK` | Enable clipboard paste fallback. |

### Threading

| Parameter | Default | Env Var | Description |
|-----------|---------|---------|-------------|
| `QUEUE_MAXSIZE` | 10 | `VTYPE_QUEUE_MAXSIZE` | Cross-thread task queue capacity. |

---

## Development

### Git Workflow (Git Flow)

```
main         ─── Production releases
  └── develop ─── Daily integration
        ├── feat/*  ─── Feature branches
        ├── fix/*   ─── Bug fix branches
        └── release/* ── Release preparation
```

**Rules:**
- **Never commit directly to `main`**.
- Feature branches rebase onto `develop` before merge.
- Merge into `develop` uses `--no-ff` to preserve topology.
- Personal branches use `--force-with-lease` for pushes.

### Commit Convention (Conventional Commits)

```
<type>(<scope>): <subject>

Types: feat | fix | refactor | docs | test | chore | perf
Scope: config | audio | detector | recognizer | typer | manager | deps
Subject: Chinese description, verb-first, ≤ 50 chars
```

Examples:
```
feat(audio): implement hardware microphone stream capture
fix(detector): correct enum equality checks after module reload
test(config): add boundary validation for silence parameters
```

### Development Setup

```bash
# Install all dependencies (production + dev)
pip install -r requirements.txt -r requirements-dev.txt

# Run linter
ruff check .

# Run type checker
mypy config.py core/

# Run full test suite
pytest tests/ -v

# Run tests with coverage
pytest tests/ --cov=. --cov-report=html
```

---

## Roadmap

### ✅ Phase 1 — Infrastructure Foundation (Complete)

| Module | File | Tests | Status |
|--------|------|-------|--------|
| M-01 | `config.py` — Global configuration center | 53 ✅ | Done |
| M-02 | `core/audio.py` — Audio capture stream | 32 ✅ | Done |
| M-03 | `core/detector.py` — Voice detection & slicing | 31 ✅ | Done |

**Phase 1 total: 116 tests passing.**

### 🔴 Phase 2 — Core Pipeline (Next)

| Module | File | Description |
|--------|------|-------------|
| M-04 | `core/recognizer.py` | faster-whisper int8 ASR inference |
| M-05 | `core/typer.py` | Keyboard simulation + clipboard fallback |
| M-08 | `utils/clipboard.py` | Cross-platform clipboard wrapper |
| M-06 | `core/manager.py` | Core scheduler, thread lifecycle management |

### 🔴 Phase 3 — CLI & UX

| Module | File | Description |
|--------|------|-------------|
| M-07 | `main.py` | Click CLI entry point, graceful shutdown |
| M-09 | `utils/key_monitor.py` | Global hotkey listener (pause/resume) |

### 🔴 Phase 4 — Polish & Release

- Performance benchmarking and optimization
- Cross-platform integration testing
- PyPI package publishing
- CI/CD pipeline setup

---

## License

MIT License

---

## Acknowledgments

- [OpenAI Whisper](https://github.com/openai/whisper) — Speech recognition model
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — CTranslate2 optimized inference
- [Google WebRTC VAD](https://webrtc.org/) — Voice activity detection algorithm
- [sounddevice](https://python-sounddevice.readthedocs.io/) — PortAudio Python bindings
