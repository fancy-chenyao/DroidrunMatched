# Step 5 集成测试指南

## 📋 概述

Step 5 集成测试验证失败反思与 Memory 系统的集成，确保：
- 反思数据正确保存到 Trajectory
- Trajectory 序列化包含反思
- Trajectory 反序列化兼容新旧格式
- Experience 正确包含反思
- 端到端流程正常工作

**测试文件**: `tests/agent/reflection/test_step5_memory_integration.py`

---

## 🎯 测试目标

### 核心验证点

| 维度 | 测试目标 |
|------|---------|
| **Trajectory 集成** | 字段存在、添加反思、序列化、反序列化 |
| **Experience 集成** | 包含反思、序列化正确 |
| **端到端流程** | Trajectory → Experience → 持久化 |
| **数据完整性** | 字段完整、多反思、持久化一致 |
| **向后兼容** | 旧格式可以加载 |

---

## 📁 测试结构

```
test_step5_memory_integration.py
├── TestTrajectoryIntegration          # Trajectory 集成（7 个测试）
│   ├── test_trajectory_has_failure_reflections_field
│   ├── test_add_failure_reflection_to_trajectory
│   ├── test_trajectory_serialization_includes_reflections
│   ├── test_trajectory_serialization_without_reflections
│   ├── test_trajectory_deserialization_new_format
│   └── test_trajectory_deserialization_old_format
│
├── TestExperienceIntegration          # Experience 集成（2 个测试）
│   ├── test_experience_includes_failure_reflections
│   └── test_experience_serialization
│
├── TestEndToEndIntegration            # 端到端集成（3 个测试）
│   ├── test_failure_reflection_to_trajectory
│   ├── test_trajectory_to_experience
│   └── test_full_save_and_load_cycle
│
└── TestDataIntegrity                  # 数据完整性（3 个测试）
    ├── test_reflection_data_structure_completeness
    ├── test_multiple_reflections_in_trajectory
    └── test_reflection_persistence_across_save_load
```

**总计**: 4 个测试类，15 个测试用例

---

## 🧪 测试用例详解

### 1. Trajectory 集成测试

#### 测试 1.1：Trajectory 包含字段
```python
def test_trajectory_has_failure_reflections_field():
    """
    验证：Trajectory 对象包含 failure_reflections 字段
    
    断言：
    - hasattr(trajectory, 'failure_reflections')
    - isinstance(trajectory.failure_reflections, list)
    - 初始为空列表
    """
```

**预期结果**:
```
✅ Trajectory 包含 failure_reflections 字段
✅ 类型是 list
✅ 初始为空
```

---

#### 测试 1.2：添加反思
```python
def test_add_failure_reflection_to_trajectory():
    """
    验证：可以添加反思到 Trajectory
    
    步骤：
    1. 创建 Trajectory
    2. 添加反思数据
    3. 验证反思内容
    """
```

---

#### 测试 1.3：序列化包含反思
```python
def test_trajectory_serialization_includes_reflections():
    """
    验证：save_trajectory() 保存反思到文件
    
    步骤：
    1. 创建 Trajectory 并添加反思
    2. 调用 save_trajectory()
    3. 读取 trajectory.json
    4. 验证格式和内容
    
    断言：
    - trajectory.json 是对象（非数组）
    - 包含 events, goal, failure_reflections
    - 反思内容正确
    """
```

**预期 trajectory.json**:
```json
{
  "events": [...],
  "goal": "测试目标",
  "experience_id": "test_exp_123",
  "failure_reflections": [
    {
      "problem_type": "ui_changed",
      "confidence": 0.85
    }
  ]
}
```

---

#### 测试 1.4：反序列化新格式
```python
def test_trajectory_deserialization_new_format():
    """
    验证：load_trajectory_folder() 正确加载新格式
    
    步骤：
    1. 创建新格式的 trajectory.json
    2. 调用 load_trajectory_folder()
    3. 验证反思数据正确加载
    """
```

---

#### 测试 1.5：反序列化旧格式（向后兼容）
```python
def test_trajectory_deserialization_old_format():
    """
    验证：旧格式可以正常加载
    
    步骤：
    1. 创建旧格式 trajectory.json（数组）
    2. 调用 load_trajectory_folder()
    3. 验证转换为新格式
    
    断言：
    - 旧格式（数组）可以加载
    - 自动转换为 {"events": [...]}
    - 不报错
    """
```

**旧格式示例**:
```json
[
  {"type": "TaskStartEvent"},
  {"type": "ActionEvent"}
]
```

---

### 2. Experience 集成测试

#### 测试 2.1：Experience 包含反思
```python
def test_experience_includes_failure_reflections():
    """
    验证：TaskExperience.metadata 包含 failure_reflections
    
    断言：
    - metadata.failure_reflections 存在
    - 内容正确
    """
```

---

#### 测试 2.2：Experience 序列化
```python
def test_experience_serialization():
    """
    验证：Experience 可以正确序列化和反序列化
    
    步骤：
    1. 创建带反思的 Experience
    2. 调用 to_dict()
    3. 转换为 JSON
    4. 从 JSON 反序列化
    5. 验证数据一致
    """
```

---

### 3. 端到端集成测试

#### 测试 3.1：反思到 Trajectory
```python
async def test_failure_reflection_to_trajectory():
    """
    验证：失败反思正确保存到 Trajectory
    
    模拟 DroidAgent 的保存逻辑
    """
```

---

#### 测试 3.2：Trajectory 到 Experience
```python
async def test_trajectory_to_experience():
    """
    验证：Trajectory 的反思正确转换到 Experience
    
    模拟 _build_experience_from_execution() 的逻辑
    """
```

---

#### 测试 3.3：完整保存加载周期
```python
async def test_full_save_and_load_cycle():
    """
    验证：完整的保存和加载流程
    
    步骤：
    1. 创建带反思的 Trajectory
    2. 保存到磁盘
    3. 从磁盘加载
    4. 构建 Experience
    5. 序列化 Experience
    6. 反序列化并验证
    
    这是最重要的端到端测试！
    """
```

**数据流**:
```
Trajectory + 反思
    ↓
save_trajectory()
    ↓
trajectory.json
    ↓
load_trajectory_folder()
    ↓
构建 Experience
    ↓
experience.to_dict()
    ↓
JSON 序列化
    ↓
验证完整性 ✅
```

---

### 4. 数据完整性测试

#### 测试 4.1：数据结构完整性
```python
def test_reflection_data_structure_completeness():
    """
    验证：反思数据包含所有必需字段
    
    必需字段：
    - problem_type
    - root_cause
    - specific_advice
    - confidence
    - timestamp
    - failed_action
    - error_step
    """
```

---

#### 测试 4.2：多个反思
```python
def test_multiple_reflections_in_trajectory():
    """
    验证：Trajectory 可以包含多个反思
    
    场景：任务多次失败，每次都有反思
    """
```

---

#### 测试 4.3：持久化一致性
```python
def test_reflection_persistence_across_save_load():
    """
    验证：保存和加载后数据完全一致
    
    使用特定值（如 0.876543）验证精度
    """
```

---

## 🚀 运行测试

### 运行所有 Step 5 测试

```bash
pytest tests/agent/reflection/test_step5_memory_integration.py -v
```

### 运行特定测试类

```bash
# Trajectory 集成
pytest tests/agent/reflection/test_step5_memory_integration.py::TestTrajectoryIntegration -v

# Experience 集成
pytest tests/agent/reflection/test_step5_memory_integration.py::TestExperienceIntegration -v

# 端到端集成
pytest tests/agent/reflection/test_step5_memory_integration.py::TestEndToEndIntegration -v

# 数据完整性
pytest tests/agent/reflection/test_step5_memory_integration.py::TestDataIntegrity -v
```

### 运行特定测试用例

```bash
# 测试序列化
pytest tests/agent/reflection/test_step5_memory_integration.py::TestTrajectoryIntegration::test_trajectory_serialization_includes_reflections -v

# 测试完整周期
pytest tests/agent/reflection/test_step5_memory_integration.py::TestEndToEndIntegration::test_full_save_and_load_cycle -v
```

### 生成覆盖率报告

```bash
pytest tests/agent/reflection/test_step5_memory_integration.py \
    --cov=droidrun.agent.utils.trajectory \
    --cov=droidrun.agent.context.experience_memory \
    --cov-report=html \
    --cov-report=term-missing
```

---

## 📊 预期测试结果

### 成功输出

```
tests/agent/reflection/test_step5_memory_integration.py::TestTrajectoryIntegration::test_trajectory_has_failure_reflections_field PASSED
tests/agent/reflection/test_step5_memory_integration.py::TestTrajectoryIntegration::test_add_failure_reflection_to_trajectory PASSED
tests/agent/reflection/test_step5_memory_integration.py::TestTrajectoryIntegration::test_trajectory_serialization_includes_reflections PASSED
tests/agent/reflection/test_step5_memory_integration.py::TestTrajectoryIntegration::test_trajectory_serialization_without_reflections PASSED
tests/agent/reflection/test_step5_memory_integration.py::TestTrajectoryIntegration::test_trajectory_deserialization_new_format PASSED
tests/agent/reflection/test_step5_memory_integration.py::TestTrajectoryIntegration::test_trajectory_deserialization_old_format PASSED
tests/agent/reflection/test_step5_memory_integration.py::TestExperienceIntegration::test_experience_includes_failure_reflections PASSED
tests/agent/reflection/test_step5_memory_integration.py::TestExperienceIntegration::test_experience_serialization PASSED
tests/agent/reflection/test_step5_memory_integration.py::TestEndToEndIntegration::test_failure_reflection_to_trajectory[asyncio] PASSED
tests/agent/reflection/test_step5_memory_integration.py::TestEndToEndIntegration::test_trajectory_to_experience[asyncio] PASSED
tests/agent/reflection/test_step5_memory_integration.py::TestEndToEndIntegration::test_full_save_and_load_cycle[asyncio] PASSED
tests/agent/reflection/test_step5_memory_integration.py::TestDataIntegrity::test_reflection_data_structure_completeness PASSED
tests/agent/reflection/test_step5_memory_integration.py::TestDataIntegrity::test_multiple_reflections_in_trajectory PASSED
tests/agent/reflection/test_step5_memory_integration.py::TestDataIntegrity::test_reflection_persistence_across_save_load PASSED

========== 15 passed in 1.5s ==========
```

---

## 🎯 测试覆盖率目标

### 代码覆盖率

| 模块 | 目标覆盖率 | 说明 |
|------|-----------|------|
| `trajectory.py` | ≥85% | Trajectory 序列化/反序列化 |
| `experience_memory.py` | ≥80% | Experience 处理 |
| `droid_agent.py` (相关部分) | ≥75% | 反思保存逻辑 |

### 功能覆盖率

| 功能 | 测试用例数 | 覆盖率 |
|------|-----------|--------|
| Trajectory 集成 | 6 | 100% |
| Experience 集成 | 2 | 100% |
| 端到端流程 | 3 | 100% |
| 数据完整性 | 3 | 100% |
| 向后兼容 | 1 | 100% |

---

## 🐛 常见问题

### Q1: 临时文件清理失败

**问题**:
```
PermissionError: [WinError 32] The process cannot access the file
```

**解决**:
```python
# 使用 ignore_errors=True
finally:
    shutil.rmtree(temp_dir, ignore_errors=True)
```

---

### Q2: 异步测试不运行

**问题**: `async def test_*` 没有执行

**解决**:
```python
# 确保添加了 pytestmark
pytestmark = pytest.mark.anyio

# 或者在测试上添加装饰器
@pytest.mark.anyio
async def test_something():
    ...
```

---

### Q3: JSON 序列化错误

**问题**: `TypeError: Object of type X is not JSON serializable`

**解决**:
- 确保所有数据都是基本类型
- 使用 `ensure_ascii=False` 支持中文
- 检查 timestamp 是 float 类型

---

## 📈 性能基准

### 测试性能基准

| 测试 | 目标时间 | 说明 |
|------|---------|------|
| 单个测试 | <0.1s | 非常快 |
| 序列化测试 | <0.2s | 包含文件 I/O |
| 端到端测试 | <0.5s | 完整流程 |
| 全部测试 | <2s | 15 个测试 |

---

## 🔍 测试覆盖的场景

### 正常场景 ✅

- ✅ 单个反思保存和加载
- ✅ 多个反思保存和加载
- ✅ 完整的端到端流程
- ✅ 新格式的序列化和反序列化

### 边界场景 ✅

- ✅ 没有反思的 Trajectory
- ✅ 旧格式的兼容性
- ✅ 空反思列表

### 异常场景

以下场景在单元测试中覆盖：
- 无效的反思数据
- 损坏的 JSON 文件
- 缺少字段

---

## ✅ 验收标准

### Step 5 测试验收

- ✅ 至少 15 个测试用例
- ✅ 所有测试通过
- ✅ 代码覆盖率 ≥80%
- ✅ 端到端测试通过
- ✅ 向后兼容性验证

---

## 📚 参考资料

- [pytest 文档](https://docs.pytest.org/)
- [pytest-anyio 文档](https://anyio.readthedocs.io/)
- Step 4 测试: `tests/agent/reflection/test_step4_optimizations.py`
- Step 3 测试: `tests/agent/droid/test_failure_reflection_integration.py`

---

**文档版本**: v1.0  
**创建时间**: 2025-12-03 15:12  
**适用范围**: Step 5 Memory 系统集成测试
