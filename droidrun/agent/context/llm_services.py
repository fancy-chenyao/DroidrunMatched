"""
LLM服务模块 - 封装所有LLM调用
"""
# 标准库导入
import json
import re
from typing import Any, Dict, List, Optional
from droidrun.agent.utils.logging_utils import LoggingUtils

# 第三方库导入
from llama_index.core.llms.llm import LLM

class LLMServices:
    """LLM服务封装类"""
    
    def __init__(self, llm: LLM):
        self.llm = llm
        LoggingUtils.log_info("LLMServices", "LLMServices initialized")
    
    def _create_experience_summary(self, experience: Dict, index: int) -> Dict:
        """
        创建经验的精简摘要，用于LLM选择
        
        优化：仅传入核心决策信息，移除大数据字段（action_sequence、page_sequence、ui_states）
        Token减少：95%+，从 ~50,000 降至 ~1,000
        """
        # 统计动作类型分布
        action_types = {}
        for action in experience.get("action_sequence", []):
            action_type = action.get("action", "unknown")
            action_types[action_type] = action_types.get(action_type, 0) + 1
        
        summary = {
            "index": index,  # 用于返回原始经验的索引
            "goal": experience.get("goal", ""),
            "success": experience.get("success", False),
            "similarity_score": experience.get("similarity_score", 0.0),
            "metadata": {
                "steps": experience.get("metadata", {}).get("steps", 0),
                "execution_time": experience.get("metadata", {}).get("execution_time", 0),
                "is_hot_start": experience.get("metadata", {}).get("is_hot_start", False),
            },
            "statistics": {
                "action_count": len(experience.get("action_sequence", [])),
                "action_types": action_types,
            }
        }
        return summary
    
    def select_best_experience(self, experiences: List[Dict], goal: str) -> Optional[Dict]:
        """
        选择最佳经验
        
        优化：使用精简摘要代替完整数据，大幅减少Token消耗（95%+）
        """
        if not experiences:
            return None
        
        try:
            # 创建精简摘要（仅包含核心决策信息）
            summaries = [self._create_experience_summary(exp, i) for i, exp in enumerate(experiences)]
            
            prompt = f"""
从以下经验摘要中选择最适合新目标的最佳经验：

新目标: {goal}

可用经验摘要（已优化，仅包含核心决策信息）:
{json.dumps(summaries, ensure_ascii=False, indent=2)}

说明：
- goal: 任务目标（核心决策依据）
- success: 是否成功执行
- similarity_score: 与新目标的语义相似度（0-1）
- metadata.steps: 执行步骤数
- metadata.execution_time: 执行耗时（秒）
- statistics.action_count: 动作数量
- statistics.action_types: 动作类型分布

请分析并返回JSON格式：
{{
    "best_experience_index": 0,
    "reason": "选择理由（重点说明为何该经验最适合新目标）",
    "confidence": 0.0-1.0
}}
"""
            LoggingUtils.log_info("LLMServices", "Selecting best from {count} experience summaries (optimized input, ~95% token reduction)", 
                                count=len(summaries))
            response = self.llm.complete(prompt)
            
            # 解析JSON响应
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if json_match:
                selection = json.loads(json_match.group())
                best_index = selection.get("best_experience_index", 0)
                if 0 <= best_index < len(experiences):
                    LoggingUtils.log_info("LLMServices", "Selected best experience: {reason}", 
                                        reason=selection.get('reason', 'No reason provided'))
                    return experiences[best_index]
            
            # 如果解析失败，返回第一个经验
            LoggingUtils.log_warning("LLMServices", "Could not parse best experience selection, using first experience")
            return experiences[0]
                
        except Exception as e:
            LoggingUtils.log_warning("LLMServices", "Best experience selection failed: {error}", error=e)
            return experiences[0] if experiences else None

    def detect_changed_actions(self, experience_goal: str, new_goal: str, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """使用LLM通用识别需要参数适配/微冷启动的动作索引，严禁领域词硬编码。

        约束：
        - 返回窗口级一次触发点（打开/选择/确认链条仅返回一个代表性索引）
        - 仅输出JSON，字段：{"changed_indices": [int,...], "reasons": ["..."]}
        - 若LLM不可用，返回空列表作为兜底
        """
        try:
            # 为LLM提供精简且结构化的动作视图
            simplified_actions = []
            for i, a in enumerate(actions or []):
                simplified_actions.append({
                    "index": i,
                    "action": (a or {}).get("action") or (a or {}).get("name") or "",
                    "params": (a or {}).get("params") or (a or {}).get("parameters") or {},
                    "description": str((a or {}).get("description", ""))[:200]
                })

            prompt = f"""
你是一个通用的人机操作差异对齐器。现有一个历史经验（旧目标）与一个新目标，以及该经验的动作序列（每步含动作类型、简述与参数概览）。
任务：比较新旧目标，找出动作序列中那些因为目标参数变化而需要调整参数或重做的动作步骤索引。只返回这些索引和对应的详细子目标。

关键点：
- 只基于新旧目标的语义差异和动作描述进行判断。
- 重点关注与目标参数直接相关的动作，如输入文本、选择日期、选择选项等。
- **特别注意**：仔细检查新目标中是否有历史序列中**完全不存在**的操作需求。

**变更类型判断规则**：
1. **Changed（修改）**：历史动作序列中已存在该动作，但参数需要调整
   - 例如：历史中有"填写开始日期2024年1月1日"，新任务需要"2025年11月10日"
   - 标记为 changed，索引为该动作在序列中的位置（如 index=3）
   
2. **Added（新增）**：新任务需要的动作在历史序列中完全不存在
   - 例如：历史序列中只有"填写开始日期"，但新任务需要"填写开始日期"**和"填写结束日期"**
   - **重要识别方法**：
     * 对比新旧目标，识别新目标中额外的参数或字段
     * 检查历史动作序列中是否有对应的操作
     * 如果没有，就是 Added 动作
   - 标记为 added，索引使用小数表示插入位置
   - **插入位置规则**：
     * index=X.1 表示插入到 index=X **之后**
     * index=X.2 表示插入到 index=X.1 之后
     * **关键**：插入位置应该基于**业务逻辑的顺序**，而不是简单地插入到序列末尾
   - **插入位置示例**：
     * 历史序列：[3]开始日期 → [4]确认 → [5]事由
     * 新增"结束日期"应该在"开始日期"之后、"确认"之前
     * 正确：Added [3.1] 结束日期 ✅（紧跟开始日期）
     * 错误：Added [4.1] 结束日期 ❌（在确认之后，逻辑错误）
   - **常见 Added 场景**：
     * 日期范围：历史只有"开始日期"，新任务需要"开始日期+结束日期"
     * 额外字段：历史只填写"事由"，新任务需要"事由+备注"
     * 多选项：历史选择1个选项，新任务需要选择2个选项
   
3. **Removed（删除）**：历史序列中存在但新任务不需要的动作
   - 例如：历史中有"选择审批人"，但新任务不需要
   - 标记为 removed，索引为该动作在历史序列中的位置

**重要**：仔细区分 Changed 和 Added！
- 如果历史序列中已有该动作（即使参数不同），应标记为 Changed，而不是 Added
- 只有历史序列中完全没有的动作才标记为 Added
- **识别 Added 的关键步骤**：
  1. 逐一对比新旧目标的每个参数/字段
  2. 对于新目标中的每个参数，检查历史序列是否有对应操作
  3. 如果没有，标记为 Added
- **新增动作的插入位置必须符合业务逻辑**：
  * 日期相关的动作应该连续（开始日期 → 结束日期 → 确认）
  * 不要把新增动作插入到不相关的动作之后

**完整示例**（重点：日期范围的 Added 场景）：
- 旧目标："请2025年11月25日的年休假，事由是休息"
- 新目标："请2025年11月28到11月29这两天的年休假，事由是休息"
- 历史动作序列：
  * [3] 点击选择"2025年11月25日"（开始日期）
  * [4] 点击"确认"按钮
  * [5] 输入请假事由"休息"
- 正确识别：
  * Changed: [3]（开始日期从25改为28）
  * Added: [3.1]（需要新增填写结束日期29，插入在开始日期和确认之间）
  * Changed: [5]（事由不变，但可能需要重新输入）

**子目标格式要求**：
- 使用中文，20-40字，面向业务，清晰描述要完成什么操作
- 避免技术细节（如索引、坐标等）
- 使用"完成"、"填写"、"选择"等业务动词，避免"改为"、"修改"、"调整"等技术动词
- 示例：
  * ✅ "完成开始日期的填写，选择2025年11月10日"
  * ✅ "完成结束日期的填写，选择2025年11月15日"
  * ✅ "输入请假事由：去海南旅游"
  * ❌ "将开始日期改为2025年11月10日"

仅返回JSON格式，字段如下：
{{\n  "changed_indices": [整数数组],\n  "changed_reasons": [字符串数组，每个元素对应changed_indices中索引的详细子目标],
\n  "added_indices": [浮点数数组],\n  "added_reasons": [字符串数组，每个元素对应added_indices中索引的详细子目标],
\n  "removed_indices": [整数数组],\n  "removed_reasons": [字符串数组，每个元素对应removed_indices中索引的详细子目标],
\n}}
不要输出任何其他文字。

旧目标：{experience_goal}
新目标：{new_goal}
动作序列（精简）：{json.dumps(simplified_actions, ensure_ascii=False)}
"""
            # logger.info(f"[LLM][detect_changed_actions] Prompt:\n{prompt}")
            rsp = self.llm.complete(prompt)
            text = getattr(rsp, 'text', str(rsp))
            LoggingUtils.log_debug("LLMServices", "Detect changed actions response: {text}", text=text)
            
            # 解析严格JSON
            m = re.search(r'\{[\s\S]*\}$', text.strip())
            data = json.loads(m.group()) if m else json.loads(text)
            
            # 解析变更动作
            changed_indices_raw = data.get("changed_indices", [])
            changed_reasons_raw = data.get("changed_reasons", data.get("reasons", []))  # 兼容旧字段名
            
            # 解析新增动作
            added_indices_raw = data.get("added_indices", [])
            added_reasons_raw = data.get("added_reasons", [])
            
            # 解析删除动作
            removed_indices_raw = data.get("removed_indices", [])
            removed_reasons_raw = data.get("removed_reasons", [])
            
            # 添加INFO级别日志显示LLM识别结果
            LoggingUtils.log_info("LLMServices", 
                                "🔍 LLM detected: changed={changed}, added={added}, removed={removed}", 
                                changed=len(changed_indices_raw), 
                                added=len(added_indices_raw),
                                removed=len(removed_indices_raw))
            
            # 规范化变更动作索引为整数
            norm_changed_indices: List[int] = []
            for i in changed_indices_raw:
                try:
                    ii = int(str(i))
                    norm_changed_indices.append(ii)
                except Exception:
                    continue
            
            # 规范化新增动作索引为浮点数
            norm_added_indices: List[float] = []
            for i in added_indices_raw:
                try:
                    ff = float(str(i))
                    norm_added_indices.append(ff)
                except Exception:
                    continue
            
            # 规范化删除动作索引为整数
            norm_removed_indices: List[int] = []
            for i in removed_indices_raw:
                try:
                    ii = int(str(i))
                    norm_removed_indices.append(ii)
                except Exception:
                    continue
            
            # 构造 index->reason 对齐表（变更动作）
            index_reasons = []
            for pos, idx in enumerate(norm_changed_indices):
                reason = changed_reasons_raw[pos] if pos < len(changed_reasons_raw) else ""
                index_reasons.append({"index": idx, "reason": str(reason), "type": "changed"})
            
            # 添加新增动作到对齐表
            for pos, idx in enumerate(norm_added_indices):
                reason = added_reasons_raw[pos] if pos < len(added_reasons_raw) else ""
                index_reasons.append({"index": idx, "reason": str(reason), "type": "added"})
            
            # 添加删除动作到对齐表
            for pos, idx in enumerate(norm_removed_indices):
                reason = removed_reasons_raw[pos] if pos < len(removed_reasons_raw) else ""
                index_reasons.append({"index": idx, "reason": str(reason), "type": "removed"})
            
            # 供旧逻辑使用的去重排序集合
            changed_sorted = sorted(set(norm_changed_indices))
            
            return {
                "changed_indices": changed_sorted, 
                "index_reasons": index_reasons,
                "added_indices": norm_added_indices,
                "removed_indices": norm_removed_indices,
                "reasons": changed_reasons_raw  # 保持向后兼容
            }
        except Exception:
            LoggingUtils.log_warning("LLMServices", "Detect changed actions: LLM解析失败，返回空集合作为兜底")
            return {"changed_indices": []}

    def generate_micro_goal(self, action: Dict[str, Any], diffs: Dict[str, Any], new_goal: str) -> str:
        """使用LLM生成通用微冷启动子目标：
        - 单句中文，面向业务、可执行
        - 禁止出现索引/坐标/资源ID等实现细节
        - 聚焦当前子阶段，避免概括全流程
        - 严禁使用任何领域词硬编码（本函数内不写死任何关键词）
        """
        name = (action or {}).get("action") or (action or {}).get("name") or ""
        desc = str((action or {}).get("description", ""))

        # 将 diffs 压缩为自然语言摘要供LLM参考（不引入领域词判断，仅透传）
        try:
            diffs_text = json.dumps(diffs, ensure_ascii=False)
        except Exception:
            diffs_text = "{}"

        try:
            prompt = f"""
你是通用的人机交互子目标生成器。基于给定动作的自然语言描述、整体新任务目标，以及两者之间的语义差异摘要，为当前动作所在的子流程生成一个"可直接执行的、面向业务的目标描述"。

要求：
- 输出中文，20-40字内；
- 禁止出现索引、坐标、资源ID等实现细节；
- 只聚焦当前子阶段的可完成目标，避免覆盖整个流程；
- 用词中立，避免依赖任何特定应用/字段名；
- **关键**：使用"完成"、"填写"、"选择"等业务动词，避免使用"改为"、"修改"、"调整"等技术动词
  * ✅ 正确示例："完成结束日期的填写，选择2025年11月15日"
  * ✅ 正确示例："在日期选择器中选择2025年11月15日并确认"
  * ❌ 错误示例："将结束日期改为2025年11月15日"
  * ❌ 错误示例："修改日期为2025年11月15日"
- 如果涉及日期，使用完整年月日格式

动作描述：{desc or name}
新任务目标：{new_goal}
差异摘要（供参考）：{diffs_text}
"""
            LoggingUtils.log_debug("LLMServices", "Generate micro goal prompt: {prompt}", prompt=prompt)
            rsp = self.llm.complete(prompt)
            text = getattr(rsp, 'text', str(rsp)).strip().splitlines()[0]
            LoggingUtils.log_debug("LLMServices", "Generate micro goal text: {text}", text=text)
            # 兜底：若返回空或包含明显实现细节，退回到更泛化的子阶段表达
            if not text:
                raise ValueError("empty micro goal")
            if any(k in text for k in ("index", "坐标", "resource-id", "id=", "@id/")):
                raise ValueError("goal contains low-level detail")
            return text
        except Exception:
            # 最小兜底：返回动作描述或极泛化短句，保持通用
            return desc or "完成当前子阶段"