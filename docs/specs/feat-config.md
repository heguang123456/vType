# Feature Spec: M-01 config.py — 全局配置中心

> 版本: v0.1.0 | 状态: 实现阶段 | 关联: REQUIREMENTS.md §8.2 M-01

## 1. 功能概述

`config.py` 是 vType 项目的**全局配置中枢**，承担以下职责：
- 统一定义所有可配置参数的默认值
- 提供类型安全的参数访问接口
- 支持运行时通过环境变量覆盖参数（便于调试和容器化部署）
- 输出配置摘要（启动时打印关键参数，帮助用户确认运行状态）

## 2. 功能需求

| 编号 | 需求 | 优先级 | 验收标准 |
|------|------|--------|---------|
| F-C01 | 定义音频采集参数 | P0 | SAMPLE_RATE=16000, CHANNELS=1, BLOCK_SIZE=320, DTYPE="int16" |
| F-C02 | 定义 VAD 参数 | P0 | FRAME_DURATION_MS=20 (仅10/20/30), VAD_AGGRESSIVENESS=3 |
| F-C03 | 定义静音切片参数 | P0 | SILENCE_LIMIT_MS=800, SILENCE_FRAME_LIMIT=40 (自动计算) |
| F-C04 | 定义 ASR 推理参数 | P0 | MODEL_SIZE="base", COMPUTE_TYPE="int8", DEVICE="cpu", BEAM_SIZE=3, LANGUAGE="zh" |
| F-C05 | 定义键盘输出参数 | P0 | TYPE_DELAY=0.005, CLIPBOARD_FALLBACK=True |
| F-C06 | 定义队列/线程参数 | P1 | QUEUE_MAXSIZE=10 |
| F-C07 | 环境变量覆盖支持 | P1 | 所有参数可通过 VTYPE_ 前缀环境变量覆盖 |
| F-C08 | 类型验证与边界检查 | P1 | FRAME_DURATION_MS 仅允许 10/20/30, VAD_AGGRESSIVENESS 0-3 |
| F-C09 | 配置摘要输出 | P2 | `print_config()` 格式化打印当前配置 |

## 3. 技术方案

采用 **模块级常量 + 环境变量覆盖函数** 模式，避免引入第三方配置库（保持零额外依赖）：

```python
# 模块级常量（默认值）
SAMPLE_RATE: Final[int] = 16000

# 环境变量覆盖
def _env_int(name: str, default: int) -> int: ...
def _env_str(name: str, default: str) -> str: ...

# 运行时覆盖
SAMPLE_RATE = _env_int("VTYPE_SAMPLE_RATE", 16000)
```

环境变量前缀统一为 `VTYPE_`，映射规则：参数名大写 + 前缀（如 `SAMPLE_RATE` → `VTYPE_SAMPLE_RATE`）。

## 4. 接口设计

### 暴露的公共常量

| 常量 | 类型 | 默认值 | 环境变量 | 约束 |
|------|------|--------|---------|------|
| `SAMPLE_RATE` | int | 16000 | VTYPE_SAMPLE_RATE | 必须为 8000 的倍数 |
| `CHANNELS` | int | 1 | VTYPE_CHANNELS | 必须为 1 |
| `BLOCK_SIZE` | int | 320 | VTYPE_BLOCK_SIZE | = SAMPLE_RATE × FRAME_DURATION_MS / 1000 |
| `DTYPE` | str | "int16" | VTYPE_DTYPE | "int16" 或 "float32" |
| `FRAME_DURATION_MS` | int | 20 | VTYPE_FRAME_DURATION_MS | 10 / 20 / 30 |
| `VAD_AGGRESSIVENESS` | int | 3 | VTYPE_VAD_AGGRESSIVENESS | 0-3 |
| `SILENCE_LIMIT_MS` | int | 800 | VTYPE_SILENCE_LIMIT_MS | ≥ 100 |
| `SILENCE_FRAME_LIMIT` | int | 40 | 无（自动计算） | = SILENCE_LIMIT_MS // FRAME_DURATION_MS |
| `MODEL_SIZE` | str | "base" | VTYPE_MODEL_SIZE | tiny/base/small/medium/large |
| `COMPUTE_TYPE` | str | "int8" | VTYPE_COMPUTE_TYPE | int8/int8_float16/float16 |
| `DEVICE` | str | "cpu" | VTYPE_DEVICE | cpu/cuda |
| `BEAM_SIZE` | int | 3 | VTYPE_BEAM_SIZE | 1-10 |
| `LANGUAGE` | str | "zh" | VTYPE_LANGUAGE | ISO 639-1 语言代码 |
| `TYPE_DELAY` | float | 0.005 | VTYPE_TYPE_DELAY | ≥ 0 |
| `CLIPBOARD_FALLBACK` | bool | True | VTYPE_CLIPBOARD_FALLBACK | true/false |
| `QUEUE_MAXSIZE` | int | 10 | VTYPE_QUEUE_MAXSIZE | ≥ 1 |

### 公共函数

```python
def print_config() -> None:
    """打印当前生效的完整配置（格式化输出）"""
    
def validate_config() -> List[str]:
    """验证所有参数合法性，返回错误信息列表（空列表 = 通过）"""
    
def get_config_dict() -> Dict[str, Any]:
    """返回当前配置的字典副本（用于序列化/调试）"""
```

## 5. 测试计划

| 测试场景 | 测试方法 |
|---------|---------|
| 默认值正确性 | 导入模块后逐个验证常量值 |
| 环境变量覆盖 | mock `os.environ`，验证覆盖生效 |
| 类型验证 | 传入非法值（如 FRAME_DURATION_MS=25），验证 `validate_config()` 返回错误 |
| 自动计算 | 修改 SILENCE_LIMIT_MS 和 FRAME_DURATION_MS，验证 SILENCE_FRAME_LIMIT 自动更新 |
| 布尔值解析 | VTYPE_CLIPBOARD_FALLBACK="false" 验证解析为 False |

## 6. 依赖与前置条件

- 无模块依赖（config.py 是基础层，不被其他模块依赖在代码层面，但被所有模块导入使用）
- Python 标准库：`os`, `typing`, `sys`

## 7. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 环境变量拼写错误 | 中 | 低 | `validate_config()` 仅验证值合法性，不忽略未知变量 |
| 布尔值解析不一致 | 低 | 中 | 统一使用 `("true","1","yes")` 为 True |
