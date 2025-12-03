# Failure Reflection 使用指南

## 📋 概述

Failure Reflection（失败反思）是 DroidRun 的智能诊断功能，当热启动失败时自动分析原因并提供建议。

**核心功能**:
- 🤔 自动分析热启动失败原因
- 💡 提供具体的修复建议
- ✨ 增强冷启动任务描述
- 📝 保存失败经验到 Memory

---

## 🚀 快速开始

### 1. 启用功能

在配置文件中启用：

```yaml
# droidrun.yaml
agent:
  failure_reflection: true  # 启用失败反思
```

或在代码中启用：

```python
from droidrun.agent.droid import DroidAgent

agent = DroidAgent(
    goal="填写请假单",
    llm=llm,
    tools=tools,
    enable_failure_reflection=True  # 启用反思
)
```

### 2. 执行任务

```python
result = await agent.execute_task(event)
```

### 3. 查看效果

当热启动失败时，系统会自动：

1. 📸 捕获失败时的 UI 状态
2. 🤔 调用 LLM 分析失败原因
3. 💡 生成具体修复建议
4. ✨ 增强冷启动任务描述
5. 📝 保存反思到 trajectory 和 experience

---

## 💡 工作原理

### 失败检测

热启动失败时触发反思：

```
尝试热启动
    ↓
执行历史动作
    ↓
失败？
    ↓ YES
触发反思分析 ✨
```

### 反思流程

```
1. 捕获失败上下文
   - 失败的动作
   - 错误信息
   - 前后 UI 状态
   - 最近 5 个动作

2. 分析失败原因
   - UI 是否变化
   - 参数是否匹配
   - 环境是否不同
   - 时序是否有问题

3. 生成建议
   - 问题类型
   - 根本原因
   - 具体建议
   - 置信度评分

4. 应用建议
   - 置信度 ≥ 0.7 → 增强任务描述
   - 置信度 < 0.7 → 使用原任务描述
```

---

## 📖 使用示例

### 示例 1：基本使用

```python
from droidrun.agent.droid import DroidAgent
from droidrun.tools.websocket_tools import WebSocketTools

# 创建 Agent（启用反思）
agent = DroidAgent(
    goal="填写请假单",
    llm=llm,
    tools=tools,
    enable_failure_reflection=True  # ✅ 启用
)

# 执行任务
result = await agent.execute_task(event)

# 检查是否使用了反思
if hasattr(agent.trajectory, 'failure_reflections'):
    reflections = agent.trajectory.failure_reflections
    print(f"触发了 {len(reflections)} 次反思")
    
    for reflection in reflections:
        print(f"问题类型: {reflection['problem_type']}")
        print(f"建议: {reflection['specific_advice']}")
        print(f"置信度: {reflection['confidence']}")
```

### 示例 2：自定义配置

```python
# 通过配置管理器
from droidrun.config.unified_config import get_config_manager

config = get_config_manager()
config.set("agent.failure_reflection", True)

agent = DroidAgent(
    goal="填写请假单",
    llm=llm,
    tools=tools,
    config_manager=config
)
```

### 示例 3：禁用反思

```python
# 方法 1：配置文件
# droidrun.yaml
agent:
  failure_reflection: false

# 方法 2：代码
agent = DroidAgent(
    goal="填写请假单",
    llm=llm,
    tools=tools,
    enable_failure_reflection=False  # ❌ 禁用
)
```

---

## 🔧 配置选项

### 全局配置

```yaml
# droidrun.yaml
agent:
  failure_reflection: true  # 是否启用反思
```

### 运行时配置

```python
# 在创建 Agent 时配置
agent = DroidAgent(
    goal="...",
    llm=llm,
    tools=tools,
    enable_failure_reflection=True,  # 启用反思
    debug=True  # 启用调试日志
)
```

---

## 📊 输出格式

### 反思结果结构

```python
{
    "problem_type": "ui_changed",           # 问题类型
    "root_cause": "UI 元素位置发生变化",     # 根本原因
    "ui_changed": true,                     # UI 是否变化
    "recommended_strategy": "fallback_cold_start",  # 推荐策略
    "specific_advice": "建议使用更稳定的元素定位方式",  # 具体建议
    "confidence": 0.85,                     # 置信度
    "timestamp": 1701594000,                # 时间戳
    "failed_action": {...},                 # 失败的动作
    "error_step": 3                         # 失败步骤
}
```

### 问题类型

| 类型 | 说明 | 建议 |
|------|------|------|
| `ui_changed` | UI 元素变化 | 使用更稳定的定位方式 |
| `param_mismatch` | 参数不匹配 | 检查任务参数是否正确 |
| `env_diff` | 环境差异 | 检查设备状态和环境 |
| `timing` | 时序问题 | 增加等待时间 |
| `unknown` | 未知原因 | 使用冷启动 |

---

## 📝 日志输出

### 正常流程日志

```
[DroidAgent] 🔥 Hot start failed, falling back to cold start
[DroidAgent] 🤔 Analyzing failure with reflector...
[FailureReflector] 🔍 Analyzing failure: type=hot_start, step=3
[FailureReflector] 🤖 Calling LLM for failure analysis...
[FailureReflector] ✅ LLM response received: 245 chars
[FailureReflector] ✅ Successfully parsed LLM response: ui_changed
[FailureReflector] Confidence: base=0.70, adjustments=[0.1, 0.05], final=0.85
[FailureReflector] ✅ Analysis complete: problem=ui_changed, confidence=0.85, time=2.34s
[DroidAgent] 📝 Failure reflection saved to trajectory
[DroidAgent] 💡 Reflection complete: ui_changed (confidence: 0.85)
[DroidAgent] ✨ Task description enhanced with reflection advice
[DroidAgent] ❄️ Starting cold start with enhanced task description
```

### 缓存命中日志

```
[FailureReflector] 🔍 Analyzing failure: type=hot_start, step=3
[FailureReflector] ✅ Using cached reflection (time=0.001s)
[DroidAgent] 💡 Reflection complete: ui_changed (confidence: 0.85)
```

### 低置信度日志

```
[FailureReflector] ✅ Analysis complete: problem=unknown, confidence=0.45, time=2.10s
[DroidAgent] Reflection confidence too low (0.45), not applying advice
[DroidAgent] ❄️ Starting cold start with original task description
```

---

## 🎯 最佳实践

### 1. 何时启用反思

✅ **建议启用**:
- 任务重复执行（热启动场景多）
- UI 频繁变化
- 需要智能诊断

❌ **可以禁用**:
- 一次性任务
- 对延迟敏感（增加 2-3 秒）
- LLM 成本敏感

### 2. 置信度阈值

**默认**: 0.7

**调整建议**:
- 提高阈值（如 0.8）：更保守，只应用高置信度建议
- 降低阈值（如 0.6）：更激进，应用更多建议

**修改方式**:
```python
# 在 FailureReflection 中修改 should_apply_advice() 方法
def should_apply_advice(self) -> bool:
    return self.confidence >= 0.8  # 提高阈值
```

### 3. 性能优化

**缓存**:
- 相同失败场景自动使用缓存
- 缓存命中响应时间 <10ms

**Token 优化**:
- UI 状态只处理前 50 个元素
- 差异分析只检查前 10 个元素

**超时控制**:
- LLM 调用默认超时（由 LLM 配置决定）
- 建议设置合理的超时时间

---

## 🐛 故障排除

### 问题 1：反思功能未生效

**症状**: 热启动失败但没有看到反思日志

**检查**:
```python
# 1. 检查配置
config = get_config_manager()
enabled = config.get("agent.failure_reflection", False)
print(f"Reflection enabled: {enabled}")

# 2. 检查 Agent
print(f"Agent reflection enabled: {agent.enable_failure_reflection}")
print(f"Reflector exists: {agent.failure_reflector is not None}")

# 3. 检查日志级别
import logging
logging.basicConfig(level=logging.DEBUG)
```

**解决**: 确保配置正确启用

---

### 问题 2：LLM 调用失败

**症状**: 看到 "LLM analysis failed" 错误

**原因**:
- LLM 服务不可用
- API 密钥无效
- 网络问题

**解决**:
```python
# 检查 LLM 配置
try:
    response = await llm.achat([{"role": "user", "content": "test"}])
    print("LLM is working")
except Exception as e:
    print(f"LLM error: {e}")
```

**回退**: 系统会自动回退到默认策略，不影响任务执行

---

### 问题 3：反思结果不准确

**症状**: 反思给出的建议不适用

**原因**:
- LLM 能力限制
- 提示词需要优化
- 上下文信息不足

**解决**:
1. 检查置信度（低置信度说明不确定）
2. 收集更多案例优化提示词
3. 提供更多上下文信息

---

## 📊 监控和分析

### 查看反思历史

```python
# 从 Trajectory 查看
reflections = agent.trajectory.failure_reflections
for r in reflections:
    print(f"{r['problem_type']}: {r['specific_advice']}")

# 从 Experience 查看
experience = memory.load_experience(exp_id)
reflections = experience.metadata.get("failure_reflections", [])
```

### 统计分析

```python
# 统计问题类型分布
from collections import Counter

problem_types = [r["problem_type"] for r in reflections]
distribution = Counter(problem_types)
print(distribution)
# 输出: {'ui_changed': 15, 'param_mismatch': 3, 'unknown': 2}
```

### 评估反思质量

```python
# 计算平均置信度
confidences = [r["confidence"] for r in reflections]
avg_confidence = sum(confidences) / len(confidences)
print(f"Average confidence: {avg_confidence:.2f}")

# 高置信度反思占比
high_conf = [c for c in confidences if c >= 0.7]
ratio = len(high_conf) / len(confidences)
print(f"High confidence ratio: {ratio:.2%}")
```

---

## 🔒 隐私和安全

### 数据收集

**收集的数据**:
- ✅ 任务目标（goal）
- ✅ 失败的动作
- ✅ UI 状态（简化版）
- ✅ 错误信息

**不收集**:
- ❌ 用户个人信息
- ❌ 敏感业务数据
- ❌ 完整截图

### LLM 调用

**发送到 LLM**:
- 任务描述
- 失败信息
- 简化的 UI 状态

**建议**:
- 使用自己部署的 LLM（避免数据外泄）
- 检查提示词，确保不包含敏感信息
- 启用日志审计

---

## 📈 性能影响

### 时间开销

| 场景 | 额外时间 |
|------|---------|
| 热启动成功 | 0s（不触发） |
| 热启动失败（首次） | 2-3s（LLM 调用） |
| 热启动失败（缓存命中） | <10ms |

### Token 消耗

**每次反思**:
- 输入 Token: ~500-1000（简化后）
- 输出 Token: ~200-300
- **总计**: ~700-1300 Token

**优化**:
- UI 状态简化（减少 70% Token）
- 缓存机制（避免重复调用）

---

## ✅ 验收清单

### 部署前检查

- [ ] 配置正确（`failure_reflection: true`）
- [ ] LLM 服务可用
- [ ] 日志级别合适
- [ ] 测试反思功能正常
- [ ] 检查性能影响可接受

### 监控指标

- [ ] 反思触发次数
- [ ] 平均置信度
- [ ] LLM 调用时间
- [ ] 缓存命中率
- [ ] Token 消耗

---

## 📚 相关文档

- **设计文档**: `failure_reflection_implementation.md`
- **API 文档**: 代码注释和类型提示
- **测试文档**: `step*_integration_test_guide.md`
- **开发文档**: 各 Step 完成报告

---

## 🆘 获取帮助

### 问题反馈

如果遇到问题：
1. 检查日志输出
2. 参考故障排除章节
3. 查看相关文档
4. 联系开发团队

### 功能请求

如果需要新功能：
1. 描述使用场景
2. 说明预期效果
3. 提供示例数据

---

**文档版本**: v1.0  
**创建时间**: 2025-12-03 15:20  
**适用版本**: DroidRun v1.0+
