# DroidRun 失败分析型反思模块 - 设计文档

## 📋 文档信息
- **创建时间**: 2025-12-03
- **版本**: v1.0
- **状态**: 设计阶段

---

## 🎯 项目目标

实现一个失败分析型的反思模块，借鉴 DigitalEmployee 项目的反思机制，在 DroidAgent 执行失败时自动分析失败原因，提供具体可执行的改进建议，从而提高任务成功率和系统鲁棒性。

### 核心价值
1. **失败时反思**：在任务失败时分析原因（而不是成功时验证）
2. **UI 状态对比**：通过对比执行前后的 UI 状态判断动作效果
3. **智能回退**：基于反思结果决定最佳回退策略
4. **知识积累**：将失败经验保存到 memory，避免重复错误

---

## 🏗️ 系统架构

### 模块结构
```
droidrun/agent/reflection/
├── __init__.py                 # 模块导出
├── failure_reflector.py        # 核心反思器
├── reflection_types.py         # 数据类型定义
└── reflection_prompts.py       # 提示词模板
```

### 核心组件

#### 1. FailureContext（失败上下文）
包含失败场景的完整信息：
- 失败类型（热启动/冷启动/动作）
- 失败详情（动作、错误信息、步骤）
- UI 状态对比（执行前后）
- 执行历史（最近动作）

#### 2. FailureReflection（反思结果）
包含失败分析和改进建议：
- 问题类型（UI 变化/参数错误/动作无效等）
- 根本原因分析
- UI 变化分析
- 推荐策略
- 具体建议

#### 3. FailureReflector（反思器）
核心分析引擎：
- UI 状态对比分析
- LLM 驱动的原因分析
- 建议生成
- 置信度计算

---

## 🔄 工作流程

### 热启动失败场景
```
1. 热启动执行动作
   ↓
2. 检测到动作失败（返回 Error）
   ↓
3. 收集失败上下文
   - 失败动作
   - 错误信息
   - 执行前后 UI 状态
   - 预期动作（历史记录）
   ↓
4. 调用 FailureReflector 分析
   - 对比 UI 变化
   - 分析失败原因
   - 生成改进建议
   ↓
5. 根据反思结果决策
   - 高置信度 → 应用建议
   - 低置信度 → 保守回退
   ↓
6. 回退到冷启动（带反思上下文）
   ↓
7. 保存失败反思到 memory
```

---

## 📊 数据流图

```
[DroidAgent] 
    ↓ (失败)
[FailureContext Builder]
    ↓
[UI State Comparator] ← [UIStabilityChecker]
    ↓ (UI 变化分析)
[FailureReflector]
    ├─→ [LLM] (原因分析)
    └─→ [Confidence Calculator]
    ↓
[FailureReflection]
    ├─→ [DroidAgent] (应用建议)
    └─→ [Memory System] (保存教训)
```

---

## 🎯 触发时机

### 层级 1：热启动单步失败 ⭐ 最高优先级
- **场景**: `_direct_execute_actions_async` 中单个动作失败
- **输入**: 失败动作、错误信息、执行前后 UI
- **目标**: 判断 UI/参数/动作问题，提供替代方案

### 层级 2：热启动整体失败
- **场景**: 多步失败或 UI 偏离预期
- **输入**: 动作序列、轨迹、UI 状态
- **目标**: 分析为什么热启动失败，决定回退策略

### 层级 3：冷启动失败（可选）
- **场景**: CodeActAgent 执行失败
- **输入**: 失败动作、当前任务描述、UI 状态
- **目标**: 分析动作失败原因，提供替代建议

---

## 🔍 反思逻辑

### UI 状态对比分析
```
1. 元素数量对比
   ├─ 无变化 → "动作无效果"
   ├─ 增加 → "可能打开新页面/弹窗"
   └─ 减少 → "可能关闭元素"

2. UI Hash 对比
   └─ 不同 → 详细分析变化内容

3. 关键元素检查
   ├─ 目标元素不存在 → "UI 元素索引变化"
   └─ 目标元素状态不同 → "动作效果不符预期"
```

### 问题类型分类
- **ui_changed**: UI 改版，元素位置/索引变化
- **wrong_element**: 点击了错误的元素
- **action_ineffective**: 动作类型不对
- **parameter_mismatch**: 参数适配错误
- **environment_error**: 环境问题（网络、权限）

### 策略推荐
- **fallback_cold_start**: 立即冷启动
- **retry_with_adjustment**: 重试（带调整）
- **skip_and_continue**: 跳过该步骤
- **reset_ui_state**: 重置 UI 状态

---

## ⚙️ 配置项设计

```yaml
agent:
  reflection:
    # 功能开关
    enabled: true
    
    # 触发配置
    trigger_on_hot_start_failure: true
    trigger_on_cold_start_failure: false
    
    # 重试策略
    max_reflection_retries: 0
    reflection_confidence_threshold: 0.6
    
    # 性能优化
    use_lightweight_context: true
    max_ui_elements_in_context: 50
    max_recent_actions: 3
    cache_reflections: true
    
    # 记忆集成
    save_failure_reflections: true
    use_historical_failures: true
    max_lessons_to_apply: 3
```

---

## 📈 预期效果

### 成功指标
- 热启动失败后冷启动成功率提升 >10%
- 相同错误重复率降低 >50%
- 单次反思时间 <5 秒
- Token 消耗 <1500 tokens/次

### 质量指标
- 反思触发率 100%（失败时）
- 反思结果完整性 100%
- 测试覆盖率 >=80%

---

## 🚀 实施计划

### Phase 1: 基础框架（1天）
- [ ] 创建模块目录结构
- [ ] 实现数据类型定义
- [ ] 实现反思器骨架（返回 mock 数据）
- [ ] 编写单元测试

### Phase 2: 核心逻辑（1.5天）
- [ ] 实现 UI 状态对比
- [ ] 实现 LLM 调用逻辑
- [ ] 完善提示词模板
- [ ] 集成测试

### Phase 3: 热启动集成（1天）
- [ ] 修改 DroidAgent 初始化
- [ ] 在热启动失败处集成反思
- [ ] 实现反思结果应用逻辑
- [ ] 端到端测试

### Phase 4: 优化扩展（1天）
- [ ] 性能优化（UI 简化、缓存）
- [ ] 冷启动集成（可选）
- [ ] 反思质量提升

### Phase 5: Memory 集成（1天）
- [ ] 扩展 Experience 数据结构
- [ ] 保存失败反思
- [ ] 检索历史失败经验
- [ ] 应用历史教训

### Phase 6: 测试文档（1天）
- [ ] 全面测试
- [ ] 性能调优
- [ ] 文档完善
- [ ] 代码审查

---

## 🔗 参考资料

### 现有代码结构
- `droidrun/agent/droid/droid_agent.py`: 主 Agent 逻辑
- `droidrun/agent/utils/trajectory.py`: 轨迹数据结构
- `droidrun/agent/utils/ui_stability_checker.py`: UI 状态检测
- `droidrun/agent/oneflows/reflector.py`: 现有反思器（成功验证型）

### DigitalEmployee 参考
- `DigitalEmployee/Reflector_Agent/reflector.py`: 失败分析实现
- `DigitalEmployee/Reflector_Agent/base.py`: 数据类型定义
- `DigitalEmployee/Reflector_Agent/reflector_prompt.py`: 提示词模板

---

## 📝 设计决策

### 为什么不在每个动作后都反思？
- **成本考虑**: 每次反思需要 LLM 调用
- **策略**: 只在失败时反思
- **平衡**: 热启动失败率低，成本可接受

### 为什么需要 UI 状态对比？
- **核心价值**: 判断动作是否生效
- **优势**: DroidRun 已有 UIStabilityChecker 和 a11y_tree
- **准确性**: 比单纯看错误消息更准确

### 反思结果如何应用？
- **热启动**: 直接用于决策（自动化）
- **冷启动**: 增强 LLM 上下文（辅助）
- **长期**: 保存到 memory（知识积累）

---

## 📅 版本历史

- **v1.0** (2025-12-03): 初始设计文档
