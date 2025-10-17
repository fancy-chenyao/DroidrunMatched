"""
LLM服务模块 - 封装所有LLM调用
"""
from typing import List, Dict, Any, Optional
from llama_index.core.llms.llm import LLM
import json
import re
import logging
import time

logger = logging.getLogger("droidrun")

class LLMServices:
    """LLM服务封装类"""
    
    def __init__(self, llm: LLM):
        self.llm = llm
        logger.info("🤖 LLMServices initialized")
    
    
#     def analyze_execution_anomaly(self, execution_log: List[Dict]) -> Dict[str, Any]:
#         """分析执行异常"""
#         try:
#             prompt = f"""
# 分析以下执行日志，检测是否存在异常：

# 执行日志: {json.dumps(execution_log, ensure_ascii=False, indent=2)}

# 请分析并返回JSON格式：
# {{
#     "has_anomaly": true/false,
#     "anomaly_type": "异常类型",
#     "confidence": 0.0-1.0,
#     "description": "异常描述",
#     "suggestion": "建议的回退策略"
# }}
# """
#             response = self.llm.complete(prompt)
            
#             # 解析JSON响应
#             json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
#             if json_match:
#                 analysis = json.loads(json_match.group())
#                 logger.info(f"🔍 LLM execution analysis completed")
#                 return analysis
#             else:
#                 logger.warning("Could not parse anomaly analysis from LLM response")
#                 return {
#                     "has_anomaly": False,
#                     "anomaly_type": "unknown",
#                     "confidence": 0.5,
#                     "description": "Could not parse LLM response",
#                     "suggestion": "Continue with current execution"
#                 }
                
#         except Exception as e:
#             logger.warning(f"LLM anomaly analysis failed: {e}")
#             return {
#                 "has_anomaly": False,
#                 "anomaly_type": "analysis_error",
#                 "confidence": 0.3,
#                 "description": f"Analysis failed: {str(e)}",
#                 "suggestion": "Continue with current execution"
#             }
    
    def extract_page_sequence(self, trajectory: Dict) -> List[Dict]:
        """从轨迹中提取页面序列"""
        try:
            prompt = f"""
从以下执行轨迹中提取页面转换序列：

轨迹数据: {json.dumps(trajectory, ensure_ascii=False, indent=2)}

请返回页面序列，每个页面包含：
- page_name: 页面名称
- page_features: 页面特征描述
- transition_action: 转换动作
- ui_elements: 关键UI元素

返回JSON格式的数组：
"""
            response = self.llm.complete(prompt)
            
            # 解析JSON响应
            json_match = re.search(r'\[.*\]', response.text, re.DOTALL)
            if json_match:
                page_sequence = json.loads(json_match.group())
                logger.info(f"📄 Extracted {len(page_sequence)} pages from trajectory")
                return page_sequence
            else:
                logger.warning("Could not parse page sequence from LLM response")
                return []
                
        except Exception as e:
            logger.warning(f"Page sequence extraction failed: {e}")
            return []

    
    def select_best_experience(self, experiences: List[Dict], goal: str) -> Optional[Dict]:
        """选择最佳经验"""
        if not experiences:
            return None
        
        try:
            prompt = f"""
从以下经验中选择最适合新目标的最佳经验：

新目标: {goal}

可用经验:
{json.dumps(experiences, ensure_ascii=False, indent=2)}

请分析并返回JSON格式：
{{
    "best_experience_index": 0,
    "reason": "选择理由",
    "confidence": 0.0-1.0
}}
"""
            response = self.llm.complete(prompt)
            
            # 解析JSON响应
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if json_match:
                selection = json.loads(json_match.group())
                best_index = selection.get("best_experience_index", 0)
                if 0 <= best_index < len(experiences):
                    logger.info(f"🎯 Selected best experience: {selection.get('reason', 'No reason provided')}")
                    return experiences[best_index]
            
            # 如果解析失败，返回第一个经验
            logger.warning("Could not parse best experience selection, using first experience")
            return experiences[0]
                
        except Exception as e:
            logger.warning(f"Best experience selection failed: {e}")
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
任务：找出那些因为新旧目标差异而需要“参数适配或重做”的动作索引，并返回代表性索引。

- 只基于语义差异与动作描述进行判断。
- 仅返回JSON，字段：\n{{\n  "changed_indices": [整数数组],\n  "reasons": [每个索引对应的简短理由，不需要体现原目标参数是什么，只需要指出新目标参数是什么即可。如果理由中有涉及到日期等进行，尽量按照年月日给出日期的完整信息]\n}}\n不要输出任何解释性文字。

旧目标：{experience_goal}
新目标：{new_goal}
动作序列（精简）：{json.dumps(simplified_actions, ensure_ascii=False)}
"""
            # logger.info(f"[LLM][detect_changed_actions] Prompt:\n{prompt}")
            rsp = self.llm.complete(prompt)
            text = getattr(rsp, 'text', str(rsp))
            logger.info(f"[LLM][detect_changed_actions] Response:\n{text}")
            # 解析严格JSON
            m = re.search(r'\{[\s\S]*\}$', text.strip())
            data = json.loads(m.group()) if m else json.loads(text)
            indices_raw = data.get("changed_indices", [])
            reasons_raw = data.get("reasons", [])
            # 规范化索引为整数（保留原有顺序，用于与 reasons 对齐）
            norm_indices: List[int] = []
            for i in indices_raw:
                try:
                    ii = int(str(i))
                    norm_indices.append(ii)
                except Exception:
                    continue
            # 构造 index->reason 对齐表
            index_reasons = []
            for pos, idx in enumerate(norm_indices):
                reason = reasons_raw[pos] if pos < len(reasons_raw) else ""
                index_reasons.append({"index": idx, "reason": str(reason)})
            # 供旧逻辑使用的去重排序集合
            changed_sorted = sorted(set(norm_indices))
            return {"changed_indices": changed_sorted, "index_reasons": index_reasons, "reasons": reasons_raw}
        except Exception:
            logger.warning("detect_changed_actions: LLM解析失败，返回空集合作为兜底")
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
你是通用的人机交互子目标生成器。基于给定动作的自然语言描述、整体新任务目标，以及两者之间的语义差异摘要，为当前动作所在的子流程生成一个“可直接执行的、面向业务的一句话目标”。

要求：
- 仅输出一行中文，20-30字内；
- 禁止出现索引、坐标、资源ID等实现细节；
- 只聚焦当前子阶段的可完成目标，避免覆盖整个流程；
- 用词中立，避免依赖任何特定应用/字段名；

动作描述：{desc or name}
新任务目标：{new_goal}
差异摘要（供参考）：{diffs_text}
"""
            logger.info(f"[LLM][generate_micro_goal] Prompt:\n{prompt}")
            rsp = self.llm.complete(prompt)
            text = getattr(rsp, 'text', str(rsp)).strip().splitlines()[0]
            logger.info(f"[LLM][generate_micro_goal] Text:\n{text}")
            # 兜底：若返回空或包含明显实现细节，退回到更泛化的子阶段表达
            if not text:
                raise ValueError("empty micro goal")
            if any(k in text for k in ("index", "坐标", "resource-id", "id=", "@id/")):
                raise ValueError("goal contains low-level detail")
            return text
        except Exception:
            # 最小兜底：返回动作描述或极泛化短句，保持通用
            return desc or "完成该窗口的当前子阶段"
    
#     def generate_fallback_strategy(self, anomaly_type: str, anomaly_details: Dict) -> str:
#         """生成回退策略"""
#         try:
#             prompt = f"""
# 基于以下异常信息，生成具体的回退策略：

# 异常类型: {anomaly_type}
# 异常详情: {json.dumps(anomaly_details, ensure_ascii=False, indent=2)}

# 请提供具体的回退策略，包括：
# 1. 回退步骤
# 2. 参数调整
# 3. 预期结果

# 回退策略：
# """
#             response = self.llm.complete(prompt)
#             strategy = response.text.strip()
#             logger.info(f"🔄 Generated fallback strategy for {anomaly_type}")
#             return strategy
            
#         except Exception as e:
#             logger.warning(f"Fallback strategy generation failed: {e}")
#             return f"Default fallback strategy for {anomaly_type}"
    
#     def validate_ui_state(self, ui_state: Dict, expected_elements: List[str]) -> Dict[str, Any]:
#         """验证UI状态"""
#         try:
#             prompt = f"""
# 验证当前UI状态是否包含期望的元素：

# 当前UI状态: {json.dumps(ui_state, ensure_ascii=False, indent=2)}
# 期望元素: {expected_elements}

# 请返回JSON格式：
# {{
#     "is_valid": true/false,
#     "found_elements": ["找到的元素"],
#     "missing_elements": ["缺失的元素"],
#     "confidence": 0.0-1.0,
#     "suggestion": "建议"
# }}
# """
#             response = self.llm.complete(prompt)
            
#             # 解析JSON响应
#             json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
#             if json_match:
#                 validation = json.loads(json_match.group())
#                 logger.info(f"✅ UI state validation completed")
#                 return validation
#             else:
#                 logger.warning("Could not parse UI validation from LLM response")
#                 return {
#                     "is_valid": False,
#                     "found_elements": [],
#                     "missing_elements": expected_elements,
#                     "confidence": 0.3,
#                     "suggestion": "Could not validate UI state"
#                 }
                
#         except Exception as e:
#             logger.warning(f"UI state validation failed: {e}")
#             return {
#                 "is_valid": False,
#                 "found_elements": [],
#                 "missing_elements": expected_elements,
#                 "confidence": 0.3,
#                 "suggestion": f"Validation failed: {str(e)}"
#             }