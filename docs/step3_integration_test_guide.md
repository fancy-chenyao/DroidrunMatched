# Step 3 集成测试指南

## 📋 概述

本文档说明如何对 Step 3（失败反思集成）进行集成测试。

**测试目标**:
- 验证 FailureReflector 正确集成到 DroidAgent
- 验证热启动失败场景触发反思
- 验证反思建议正确应用
- 验证异常情况不影响主流程

---

## 🎯 测试策略

### 测试层次

```
┌─────────────────────────────────────────┐
│         集成测试（Integration Test）      │
│  测试 FailureReflector + DroidAgent      │
└─────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────┐
│         单元测试（Unit Test）            │
│  测试 FailureReflector 独立功能          │
│  (已在 Step 2 完成)                      │
└─────────────────────────────────────────┘
```

### 测试范围

**包含**:
- ✅ DroidAgent 初始化（启用/禁用反思）
- ✅ 热启动失败触发反思
- ✅ UI 快照保存
- ✅ 反思分析调用
- ✅ 建议应用逻辑
- ✅ 异常处理

**不包含**:
- ❌ LLM 的实际调用（使用 mock）
- ❌ 真实设备操作（使用 mock）
- ❌ 完整的端到端流程（单独测试）

---

## 📁 测试文件

**位置**: `tests/agent/droid/test_failure_reflection_integration.py`

**结构**:
```python
TestFailureReflectionIntegration  # 核心集成测试
├── test_reflection_disabled_by_default()        # 场景 1
├── test_reflection_enabled_initialization()     # 场景 2
├── test_hot_start_success_no_reflection()       # 场景 3
├── test_hot_start_failure_high_confidence()     # 场景 4
├── test_hot_start_failure_low_confidence()      # 场景 5
├── test_reflection_failure_does_not_break()     # 场景 6
└── test_ui_snapshot_failure_does_not_break()    # 场景 7

TestFailureReflectionConfiguration  # 配置测试
├── test_config_from_parameter()                 # 参数配置
├── test_config_from_config_manager()            # 配置文件
└── test_config_default_disabled()               # 默认值
```

---

## 🧪 测试场景

### 场景 1：反思默认未启用

**目的**: 验证向后兼容性

```python
async def test_reflection_disabled_by_default():
    agent = DroidAgent(
        goal="申请年假",
        llm=mock_llm,
        tools=mock_tools,
        # enable_failure_reflection 未设置
    )
    
    assert agent.enable_failure_reflection is False
    assert agent.failure_reflector is None
```

**验证点**:
- ✅ `enable_failure_reflection` 默认为 False
- ✅ `failure_reflector` 为 None
- ✅ 不影响现有代码

---

### 场景 2：反思启用时正确初始化

**目的**: 验证反思模块正确初始化

```python
async def test_reflection_enabled_initialization():
    agent = DroidAgent(
        goal="申请年假",
        llm=mock_llm,
        tools=mock_tools,
        enable_failure_reflection=True,  # 启用
    )
    
    assert agent.enable_failure_reflection is True
    assert agent.failure_reflector is not None
    assert agent.failure_reflector.llm == mock_llm
```

**验证点**:
- ✅ `enable_failure_reflection` 为 True
- ✅ `failure_reflector` 正确初始化
- ✅ LLM 和 Tools 正确传递

---

### 场景 3：热启动成功，不触发反思

**目的**: 验证只在失败时才反思

```python
async def test_hot_start_success_no_reflection():
    # 模拟热启动成功
    with patch('_direct_execute_actions_async') as mock_execute:
        mock_execute.return_value = (True, "Success")
        
        await agent.execute_task(...)
        
        # 验证 LLM 未被调用（未触发反思）
        mock_llm.achat.assert_not_called()
```

**验证点**:
- ✅ 热启动成功返回
- ✅ 不调用反思分析
- ✅ 不消耗 LLM 资源

---

### 场景 4：热启动失败 + 高置信度 + 应用建议

**目的**: 验证反思核心流程

```python
async def test_hot_start_failure_high_confidence():
    # Mock LLM 返回高置信度反思
    mock_llm.achat = AsyncMock(return_value=high_confidence_response)
    
    # 模拟热启动失败
    with patch('_direct_execute_actions_async') as mock_execute:
        mock_execute.return_value = (False, "Element not found")
        
        await agent.execute_task(...)
        
        # 验证反思被调用
        assert mock_llm.achat.call_count >= 1
        
        # 验证 UI 快照被保存
        assert mock_tools.get_state_async.call_count >= 2
```

**验证点**:
- ✅ 热启动失败触发反思
- ✅ 保存 pre_ui 和 post_ui
- ✅ 调用 LLM 分析
- ✅ 高置信度（≥0.7）应用建议
- ✅ 任务描述被增强

**预期流程**:
```
1. 保存 pre_ui_state
2. 热启动执行 → 失败
3. 保存 post_ui_state
4. 构建 FailureContext
5. 调用 failure_reflector.analyze_failure()
6. 置信度 = 0.85（≥0.7）
7. 应用建议：goal + "【反思建议】..."
8. 继续冷启动
```

---

### 场景 5：热启动失败 + 低置信度 + 不应用建议

**目的**: 验证置信度阈值机制

```python
async def test_hot_start_failure_low_confidence():
    # Mock LLM 返回低置信度反思
    low_confidence_response.content = '''
    {
        "confidence": 0.5,  # < 0.7
        ...
    }
    '''
    
    await agent.execute_task(...)
    
    # 验证任务描述未被增强
    # goal 保持原样，无【反思建议】
```

**验证点**:
- ✅ 反思被触发
- ✅ LLM 被调用
- ✅ 低置信度（<0.7）不应用建议
- ✅ 避免误导冷启动

**预期流程**:
```
1-5. 同场景 4
6. 置信度 = 0.5（<0.7）
7. 不应用建议：goal 保持原样
8. 继续冷启动
```

---

### 场景 6：反思失败不影响冷启动

**目的**: 验证异常处理

```python
async def test_reflection_failure_does_not_break():
    # 让 LLM 抛出异常
    mock_llm.achat = AsyncMock(side_effect=Exception("LLM unavailable"))
    
    await agent.execute_task(...)
    
    # 验证冷启动仍然执行
    MockCodeActAgent.assert_called_once()
```

**验证点**:
- ✅ LLM 调用失败
- ✅ 记录错误日志
- ✅ 不中断冷启动
- ✅ 使用原始 goal

**异常链**:
```
try:
    reflection = await self.failure_reflector.analyze_failure(...)
except Exception as reflection_error:
    LoggingUtils.log_error(...)  # 记录但不中断
    
# 继续冷启动（无论反思是否成功）
task = Task(description=enhanced_goal or self.goal, ...)
```

---

### 场景 7：UI 快照失败不影响执行

**目的**: 验证 UI 快照的异常处理

```python
async def test_ui_snapshot_failure_does_not_break():
    # 让 get_state_async 抛出异常
    mock_tools.get_state_async = AsyncMock(
        side_effect=Exception("Device disconnected")
    )
    
    await agent.execute_task(...)
    
    # 验证执行继续
    MockCodeActAgent.assert_called_once()
```

**验证点**:
- ✅ UI 快照保存失败
- ✅ 记录警告日志
- ✅ pre_ui_state = None
- ✅ post_ui_state = None
- ✅ FailureContext 接受 None
- ✅ 反思继续（如果可能）
- ✅ 冷启动继续

---

## 🚀 运行测试

### 运行所有集成测试

```bash
pytest tests/agent/droid/test_failure_reflection_integration.py -v
```

### 运行特定场景

```bash
# 场景 4：高置信度反思
pytest tests/agent/droid/test_failure_reflection_integration.py::TestFailureReflectionIntegration::test_hot_start_failure_high_confidence_reflection -v

# 场景 6：反思失败
pytest tests/agent/droid/test_failure_reflection_integration.py::TestFailureReflectionIntegration::test_reflection_failure_does_not_break_cold_start -v
```

### 运行配置测试

```bash
pytest tests/agent/droid/test_failure_reflection_integration.py::TestFailureReflectionConfiguration -v
```

### 生成覆盖率报告

```bash
pytest tests/agent/droid/test_failure_reflection_integration.py --cov=droidrun.agent.droid --cov-report=html
```

---

## 📊 预期测试结果

### 成功输出

```
tests/agent/droid/test_failure_reflection_integration.py::TestFailureReflectionIntegration::test_reflection_disabled_by_default[asyncio] PASSED
tests/agent/droid/test_failure_reflection_integration.py::TestFailureReflectionIntegration::test_reflection_enabled_initialization[asyncio] PASSED
tests/agent/droid/test_failure_reflection_integration.py::TestFailureReflectionIntegration::test_hot_start_success_no_reflection[asyncio] PASSED
tests/agent/droid/test_failure_reflection_integration.py::TestFailureReflectionIntegration::test_hot_start_failure_high_confidence_reflection[asyncio] PASSED
tests/agent/droid/test_failure_reflection_integration.py::TestFailureReflectionIntegration::test_hot_start_failure_low_confidence_no_advice[asyncio] PASSED
tests/agent/droid/test_failure_reflection_integration.py::TestFailureReflectionIntegration::test_reflection_failure_does_not_break_cold_start[asyncio] PASSED
tests/agent/droid/test_failure_reflection_integration.py::TestFailureReflectionIntegration::test_ui_snapshot_failure_does_not_break_execution[asyncio] PASSED
tests/agent/droid/test_failure_reflection_integration.py::TestFailureReflectionConfiguration::test_config_from_parameter PASSED
tests/agent/droid/test_failure_reflection_integration.py::TestFailureReflectionConfiguration::test_config_from_config_manager PASSED
tests/agent/droid/test_failure_reflection_integration.py::TestFailureReflectionConfiguration::test_config_default_disabled PASSED

========== 10 passed, 0 failed in 2.5s ==========
```

---

## 🔧 Mock 设计

### Mock LLM

```python
mock_llm = Mock()
mock_llm.class_name = Mock(return_value="MockLLM")

# Mock 反思响应
mock_response = Mock()
mock_response.message.content = '''
{
    "problem_type": "ui_changed",
    "confidence": 0.85,
    ...
}
'''
mock_llm.achat = AsyncMock(return_value=mock_response)
```

**用途**:
- 模拟 LLM 的反思分析
- 控制置信度以测试不同分支
- 模拟 LLM 失败场景

---

### Mock Tools

```python
mock_tools = Mock()

# Mock UI 状态（不同时间返回不同状态）
ui_state_before = {'a11y_tree': [...]}  # 50 个元素
ui_state_after = {'a11y_tree': [...]}   # 55 个元素

call_count = {'count': 0}

async def get_state_side_effect(include_screenshot=True):
    call_count['count'] += 1
    if call_count['count'] == 1:
        return ui_state_before  # 第一次
    else:
        return ui_state_after   # 第二次
        
mock_tools.get_state_async = AsyncMock(side_effect=get_state_side_effect)
```

**用途**:
- 模拟 UI 快照
- 模拟 UI 变化
- 模拟设备断连

---

### Mock CodeActAgent

```python
with patch('droidrun.agent.droid.droid_agent.CodeActAgent') as MockCodeActAgent:
    mock_codeact_instance = Mock()
    mock_codeact_handler = Mock()
    
    async def mock_stream_events():
        return
        yield  # 异步生成器
    
    mock_codeact_handler.stream_events = mock_stream_events
    mock_codeact_instance.run = Mock(return_value=mock_codeact_handler)
    MockCodeActAgent.return_value = mock_codeact_instance
```

**用途**:
- 避免真实的冷启动执行
- 验证 CodeActAgent 被正确调用
- 验证任务描述是否被增强

---

## 🎯 测试覆盖率目标

### 代码覆盖率

| 模块 | 目标覆盖率 | 说明 |
|------|-----------|------|
| `droid_agent.py` (集成部分) | ≥85% | 热启动失败 + 反思逻辑 |
| `failure_reflector.py` | ≥90% | Step 2 已完成 |
| `reflection_types.py` | 100% | Step 1 已完成 |

### 场景覆盖率

- ✅ 反思未启用：1 个测试
- ✅ 反思启用：6 个测试
- ✅ 配置管理：3 个测试
- **总计**: 10 个测试

---

## 🐛 常见问题

### Q1: 测试运行时 ImportError

**问题**:
```
ImportError: cannot import name 'DroidAgent' from 'droidrun.agent.droid'
```

**解决**:
```bash
# 确保安装了 editable 模式
pip install -e .

# 或重新安装
pip uninstall droidrun
pip install -e .
```

---

### Q2: Async 测试失败

**问题**:
```
RuntimeError: Task got Future attached to a different loop
```

**解决**:
```python
# 确保使用 pytest.mark.anyio
pytestmark = pytest.mark.anyio

# 或在测试方法上标记
@pytest.mark.anyio
async def test_something():
    ...
```

---

### Q3: Mock 未生效

**问题**:
```
Mock 的 achat 被调用但未返回预期值
```

**解决**:
```python
# 确保使用 AsyncMock 而非 Mock
mock_llm.achat = AsyncMock(return_value=mock_response)  # ✅
# 而非
mock_llm.achat = Mock(return_value=mock_response)  # ❌
```

---

## 📝 测试扩展

### 未来可添加的测试

1. **性能测试**:
   - 测试反思对执行时间的影响
   - 测试 UI 快照的性能开销

2. **边界测试**:
   - 极大的 UI 状态（10000+ 元素）
   - 极长的 pending_actions（100+ 动作）

3. **集成测试**:
   - 真实 LLM 调用（需要 API key）
   - 真实设备操作（需要连接设备）

4. **端到端测试**:
   - 完整的热启动 → 失败 → 反思 → 冷启动流程
   - 多轮失败和反思

---

## ✅ 验收标准

### Step 3 集成测试验收

- ✅ 至少 7 个核心场景测试通过
- ✅ 至少 3 个配置测试通过
- ✅ 代码覆盖率 ≥85%
- ✅ 所有异常路径有测试
- ✅ 向后兼容性验证
- ✅ 测试运行时间 <5秒

---

## 📚 参考资料

- [pytest 文档](https://docs.pytest.org/)
- [pytest-asyncio 文档](https://pytest-asyncio.readthedocs.io/)
- [unittest.mock 文档](https://docs.python.org/3/library/unittest.mock.html)
- Step 2 单元测试: `tests/agent/reflection/test_failure_reflector.py`

---

**文档版本**: v1.0  
**创建时间**: 2025-12-03 15:40  
**适用范围**: Step 3 集成测试
