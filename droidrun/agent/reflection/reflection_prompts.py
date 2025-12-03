"""
失败反思模块的提示词模板

包含用于不同失败场景的系统提示词，借鉴 DigitalEmployee 的设计理念。
"""

# 热启动失败反思提示词
HOT_START_FAILURE_SYSTEM_PROMPT = """你是一个分析 Android UI 自动化任务失败原因的反思 AI。

你的任务：
1. 对比执行前后的 UI 状态，判断动作是否产生了效果
2. 分析失败的根本原因（UI 变化？参数错误？动作类型错误？）
3. 提供具体的、可执行的改进建议

分析流程：
1. 检查执行前后 UI 的差异
   - 无差异 → 动作无效果
   - 有差异 → 分析是否符合预期
2. 检查动作参数是否合理
   - 索引是否存在？
   - 元素类型是否匹配？
3. 判断问题类型
4. 提供基于当前 UI 状态的具体建议

问题类型分类：
- ui_changed: UI 界面已改版，元素位置/索引变化
- wrong_element: 点击了错误的元素
- action_ineffective: 动作类型不对（应该 long_press 而不是 tap）
- parameter_mismatch: 参数适配错误（文本不匹配等）
- environment_error: 环境问题（网络、权限等）

建议原则：
- 基于当前 UI 状态（执行后的状态）
- 具体到元素索引、文本、动作类型
- 可直接执行，不需要二次推理
- 简洁明确（2-3句话）

输出格式（必须返回有效的 JSON）：
{
  "problem_type": "ui_changed",
  "root_cause": "目标元素索引从19变为25，UI 布局发生了变化",
  "ui_changed": true,
  "ui_change_summary": "多了6个新元素在目标元素之前",
  "recommended_strategy": "fallback_cold_start",
  "specific_advice": "当前 UI 中'开始日期'字段的索引是25而不是19。建议回退到冷启动，让 LLM 重新定位元素",
  "confidence": 0.9
}

重要提示：
- 只返回 JSON 对象，不要额外的文本或格式
- 确保 JSON 有效且可解析
- confidence 必须在 0.0-1.0 之间
- specific_advice 必须基于当前 UI 状态，具体可执行"""


# 冷启动动作失败反思提示词
COLD_START_FAILURE_SYSTEM_PROMPT = """你是一个分析 Android UI 自动化任务失败原因的反思 AI。

当前场景：冷启动执行过程中单个动作失败

你的任务：
1. 分析为什么这个动作失败
2. 对比执行前后的 UI 状态
3. 提供替代动作建议

分析要点：
- LLM 生成的动作是否合理？
- UI 状态是否支持该动作？
- 是否有更好的替代方案？

问题类型：
- ui_changed: UI 状态不符合预期
- wrong_element: 选择了错误的目标元素
- action_ineffective: 动作类型不适用
- parameter_mismatch: 参数错误

输出格式（JSON）：
{
  "problem_type": "wrong_element",
  "root_cause": "点击的元素不可交互",
  "ui_changed": false,
  "ui_change_summary": null,
  "recommended_strategy": "retry_with_adjustment",
  "specific_advice": "建议使用 long_press 而非 tap，或查找其他可交互元素",
  "suggested_action": {"action": "long_press", "params": {"index": 25}},
  "confidence": 0.7
}

只返回 JSON，不要额外文本。"""


# Few-shot 示例
REFLECTION_EXAMPLES = """
## 示例 1：UI 索引变化

输入：
- 失败动作: tap_by_index(19)
- 错误: Element at index 19 not found
- UI 变化: 元素数量从 45 增加到 51
- 执行前后 UI 对比: 前 50 个元素的 hash 不同

分析：
- UI 发生了变化（新增了 6 个元素）
- 目标元素可能仍然存在，但索引已改变
- 需要重新定位元素

输出：
{
  "problem_type": "ui_changed",
  "root_cause": "UI 布局发生变化，新增了 6 个元素，导致目标元素索引从 19 变为 25",
  "ui_changed": true,
  "ui_change_summary": "元素数量从 45 增加到 51，新增元素位于目标元素之前",
  "recommended_strategy": "fallback_cold_start",
  "specific_advice": "建议回退到冷启动，使用文本匹配（而非索引）定位'开始日期'字段。当前 UI 中该字段可能在索引 25 附近",
  "confidence": 0.9
}

---

## 示例 2：动作无效果

输入：
- 失败动作: tap_by_index(111)
- 错误: 执行成功但未达到预期效果
- UI 变化: 执行前后 UI hash 相同（无变化）

分析：
- 动作执行了，但 UI 没有变化
- 可能需要不同的动作类型（如 long_press）
- 或者该元素不可交互

输出：
{
  "problem_type": "action_ineffective",
  "root_cause": "点击动作执行成功，但未触发预期的 UI 变化（日期选择器未出现）",
  "ui_changed": false,
  "ui_change_summary": null,
  "recommended_strategy": "retry_with_adjustment",
  "specific_advice": "建议尝试长按该元素（long_press）以激活日期选择器，或查找是否有独立的日历图标按钮可以点击",
  "suggested_action": {"action": "long_press", "params": {"index": 111}},
  "confidence": 0.7
}

---

## 示例 3：参数适配错误

输入：
- 失败动作: input_text(index=20, text="2025-11-15")
- 错误: Expected format "YYYY年MM月DD日"
- 预期动作: input_text(text="2025年11月15日")

分析：
- 参数格式不匹配
- 适配过程中格式转换错误

输出：
{
  "problem_type": "parameter_mismatch",
  "root_cause": "文本格式不匹配，目标字段期望 'YYYY年MM月DD日' 格式，但提供的是 'YYYY-MM-DD'",
  "ui_changed": false,
  "ui_change_summary": null,
  "recommended_strategy": "retry_with_adjustment",
  "specific_advice": "重新输入正确格式的日期：'2025年11月15日'",
  "suggested_params": {"text": "2025年11月15日"},
  "confidence": 0.95
}
"""


# 构建完整的用户消息模板
def build_hot_start_failure_user_message(
    goal: str,
    failed_action: str,
    error_message: str,
    error_step: int,
    ui_changed: bool,
    ui_change_summary: str,
    expected_action: str = None,
    pre_ui_elements_count: int = 0,
    post_ui_elements_count: int = 0,
    recent_actions: str = "",
) -> str:
    """
    构建热启动失败的用户消息
    
    Args:
        goal: 任务目标
        failed_action: 失败的动作
        error_message: 错误信息
        error_step: 失败步骤
        ui_changed: UI 是否变化
        ui_change_summary: UI 变化描述
        expected_action: 预期动作（来自历史）
        pre_ui_elements_count: 执行前 UI 元素数量
        post_ui_elements_count: 执行后 UI 元素数量
        recent_actions: 最近执行的动作
        
    Returns:
        格式化的用户消息
    """
    message_parts = [
        f"任务目标: {goal}",
        f"失败步骤: 第 {error_step} 步",
        f"失败动作: {failed_action}",
        f"错误信息: {error_message}",
        f"UI 是否变化: {'是' if ui_changed else '否'}",
    ]
    
    if ui_change_summary:
        message_parts.append(f"UI 变化详情: {ui_change_summary}")
    
    if pre_ui_elements_count > 0 or post_ui_elements_count > 0:
        message_parts.append(f"UI 元素数量: 执行前 {pre_ui_elements_count}, 执行后 {post_ui_elements_count}")
    
    if expected_action:
        message_parts.append(f"预期动作（历史记录）: {expected_action}")
    
    if recent_actions:
        message_parts.append(f"最近执行的动作:\n{recent_actions}")
    
    message_parts.append("\n请根据上述信息分析失败原因，并提供具体的改进建议。请以 JSON 格式返回结果。")
    
    return "\n\n".join(message_parts)


def build_cold_start_failure_user_message(
    goal: str,
    failed_action: str,
    error_message: str,
    current_step_description: str,
    ui_changed: bool,
    ui_change_summary: str = None,
) -> str:
    """
    构建冷启动失败的用户消息
    
    Args:
        goal: 任务目标
        failed_action: 失败的动作
        error_message: 错误信息
        current_step_description: 当前子任务描述
        ui_changed: UI 是否变化
        ui_change_summary: UI 变化描述
        
    Returns:
        格式化的用户消息
    """
    message_parts = [
        f"任务目标: {goal}",
        f"当前子任务: {current_step_description}",
        f"失败动作: {failed_action}",
        f"错误信息: {error_message}",
        f"UI 是否变化: {'是' if ui_changed else '否'}",
    ]
    
    if ui_change_summary:
        message_parts.append(f"UI 变化详情: {ui_change_summary}")
    
    message_parts.append("\n请分析为什么这个动作失败，并提供替代方案。请以 JSON 格式返回结果。")
    
    return "\n\n".join(message_parts)
