"""
失败反思器 - 核心分析引擎

该模块实现了失败场景的自动分析功能，包括 UI 状态对比、LLM 驱动的原因分析和建议生成。
"""

import json
import logging
import hashlib
import time
from typing import Dict, Any, Optional, Tuple, List
from llama_index.core.base.llms.types import ChatMessage
from llama_index.core.llms.llm import LLM

from droidrun.agent.reflection.reflection_types import FailureContext, FailureReflection
from droidrun.agent.reflection.reflection_prompts import (
    HOT_START_FAILURE_SYSTEM_PROMPT,
    COLD_START_FAILURE_SYSTEM_PROMPT,
    build_hot_start_failure_user_message,
    build_cold_start_failure_user_message,
)
from droidrun.agent.utils.logging_utils import LoggingUtils

logger = logging.getLogger("droidrun")


class FailureReflector:
    """
    失败分析反思器
    
    该类负责分析任务执行失败的原因，并提供具体的改进建议。
    主要功能包括：
    1. UI 状态对比分析
    2. LLM 驱动的失败原因分析
    3. 建议生成和置信度计算
    
    使用示例：
        reflector = FailureReflector(llm=llm, tools_instance=tools, debug=True)
        context = FailureContext.from_hot_start_failure(...)
        reflection = await reflector.analyze_failure(context)
    """
    
    def __init__(
        self,
        llm: LLM,
        tools_instance: Any = None,
        debug: bool = False,
    ):
        """
        初始化反思器
        
        Args:
            llm: LLM 实例，用于生成反思分析
            tools_instance: Tools 实例，用于 UI hash 计算（可选）
            debug: 是否启用调试模式
        """
        self.llm = llm
        self.tools_instance = tools_instance
        self.debug = debug
        self._init_prompts()
        
        # 反思结果缓存（会话级别）
        self._reflection_cache: Dict[str, FailureReflection] = {}
        
        LoggingUtils.log_info("FailureReflector", "✨ Failure reflector initialized")
    
    def _init_prompts(self):
        """初始化提示词"""
        self.hot_start_system_prompt = HOT_START_FAILURE_SYSTEM_PROMPT
        self.cold_start_system_prompt = COLD_START_FAILURE_SYSTEM_PROMPT
    
    async def analyze_failure(
        self, 
        context: FailureContext
    ) -> FailureReflection:
        """
        分析失败并生成反思
        
        这是核心方法，执行完整的失败分析流程。
        
        Args:
            context: 失败场景的完整上下文
            
        Returns:
            FailureReflection: 包含问题诊断和改进建议的反思结果
            
        Raises:
            Exception: LLM 调用失败或 JSON 解析错误时
        """
        start_time = time.time()  # 开始计时
        
        LoggingUtils.log_info(
            "FailureReflector",
            "🔍 Analyzing failure: type={type}, step={step}",
            type=context.failure_type,
            step=context.error_step
        )
        
        # 检查缓存
        cache_key = self._get_failure_cache_key(context)
        if cache_key in self._reflection_cache:
            elapsed = time.time() - start_time
            LoggingUtils.log_debug(
                "FailureReflector", 
                "✅ Using cached reflection (time={time:.3f}s)",
                time=elapsed
            )
            return self._reflection_cache[cache_key]
        
        try:
            # 1. 分析 UI 变化（不需要 LLM）
            ui_changed, ui_change_summary = self._analyze_ui_change(
                context.pre_ui_state, 
                context.post_ui_state
            )
            
            # 2. 调用 LLM 进行深度分析
            reflection = await self._call_llm_for_analysis(
                context, 
                ui_changed, 
                ui_change_summary
            )
            
            # 3. 增强反思结果（只在 LLM 未提供时补充）
            # 注意：不要强制覆盖 LLM 的判断，否则置信度计算中的一致性检查会失效
            if reflection.ui_change_summary is None and ui_change_summary:
                reflection.ui_change_summary = ui_change_summary
            
            # 4. 缓存结果
            self._reflection_cache[cache_key] = reflection
            
            # 记录总耗时
            elapsed = time.time() - start_time
            LoggingUtils.log_success(
                "FailureReflector",
                "✅ Analysis complete: problem={problem}, confidence={conf:.2f}, time={time:.2f}s",
                problem=reflection.problem_type,
                conf=reflection.confidence,
                time=elapsed
            )
            
            return reflection
            
        except Exception as e:
            elapsed = time.time() - start_time
            LoggingUtils.log_error(
                "FailureReflector",
                "Failed to analyze failure after {time:.2f}s: {error}",
                time=elapsed,
                error=str(e)
            )
            if self.debug:
                import traceback
                LoggingUtils.log_error("FailureReflector", "{trace}", trace=traceback.format_exc())
            
            # 返回保守的回退策略
            return self._create_fallback_reflection(context)
    
    def _analyze_ui_change(
        self, 
        pre_ui: Optional[Dict[str, Any]], 
        post_ui: Optional[Dict[str, Any]]
    ) -> Tuple[bool, Optional[str]]:
        """
        对比执行前后的 UI 状态
        
        Args:
            pre_ui: 执行前的 UI 状态
            post_ui: 执行后的 UI 状态
            
        Returns:
            (ui_changed, ui_change_summary): 是否变化和变化描述
        """
        if not pre_ui or not post_ui:
            return False, None
        
        try:
            # 1. 对比元素数量
            pre_elements = pre_ui.get('a11y_tree', [])
            post_elements = post_ui.get('a11y_tree', [])
            
            pre_count = len(pre_elements)
            post_count = len(post_elements)
            
            if pre_count != post_count:
                change_desc = f"元素数量从 {pre_count} 变为 {post_count}"
                if post_count > pre_count:
                    change_desc += f"（新增了 {post_count - pre_count} 个元素）"
                else:
                    change_desc += f"（减少了 {pre_count - post_count} 个元素）"
                return True, change_desc
            
            # 2. 对比 UI hash（使用增强的 hash 计算）
            pre_hash = self._calculate_enhanced_ui_hash(pre_ui)
            post_hash = self._calculate_enhanced_ui_hash(post_ui)
            
            if pre_hash != post_hash:
                # 3. 详细分析变化内容
                diff_summary = self._analyze_ui_differences(pre_elements, post_elements)
                return True, diff_summary
            
            return False, None
            
        except Exception as e:
            LoggingUtils.log_warning(
                "FailureReflector",
                "Failed to analyze UI change: {error}",
                error=str(e)
            )
            return False, None
    
    def _calculate_enhanced_ui_hash(self, ui_state: Dict[str, Any]) -> str:
        """
        计算 UI 状态的增强 hash（借鉴 UIStabilityChecker 的实现）
        
        Args:
            ui_state: UI 状态字典
            
        Returns:
            hash 字符串
        """
        try:
            a11y_tree = ui_state.get('a11y_tree', [])
            if not a11y_tree:
                return ""
            
            # 提取关键信息：前 50 个元素的详细信息
            elements_info = []
            for elem in a11y_tree[:50]:
                elem_info = (
                    elem.get('className', ''),
                    elem.get('text', ''),
                    elem.get('resourceId', ''),
                    elem.get('clickable', False),
                )
                elements_info.append(elem_info)
            
            return str(hash(str(elements_info)))
        except Exception as e:
            LoggingUtils.log_warning("FailureReflector", "Hash calculation failed: {error}", error=str(e))
            return ""
    
    def _analyze_ui_differences(
        self, 
        pre_elements: List[Dict[str, Any]], 
        post_elements: List[Dict[str, Any]]
    ) -> str:
        """
        详细分析 UI 元素的变化
        
        Args:
            pre_elements: 执行前的元素列表
            post_elements: 执行后的元素列表
            
        Returns:
            人类可读的变化描述
        """
        try:
            changes = []
            
            # 对比前 10 个元素的文本变化
            check_count = min(10, len(pre_elements), len(post_elements))
            for i in range(check_count):
                pre_text = pre_elements[i].get('text', '')
                post_text = post_elements[i].get('text', '')
                
                if pre_text != post_text:
                    if pre_text and post_text:
                        changes.append(f"索引 {i} 的文本从 '{pre_text}' 变为 '{post_text}'")
                    elif not pre_text and post_text:
                        changes.append(f"索引 {i} 新增文本 '{post_text}'")
                    elif pre_text and not post_text:
                        changes.append(f"索引 {i} 的文本 '{pre_text}' 被移除")
            
            if changes:
                return "UI 元素发生变化: " + "; ".join(changes[:3])  # 最多显示 3 个变化
            else:
                return "UI 布局或元素属性发生了变化"
                
        except Exception as e:
            LoggingUtils.log_warning("FailureReflector", "UI diff analysis failed: {error}", error=str(e))
            return "UI 发生了变化"
    
    async def _call_llm_for_analysis(
        self,
        context: FailureContext,
        ui_changed: bool,
        ui_change_summary: Optional[str],
    ) -> FailureReflection:
        """
        调用 LLM 进行失败分析
        
        Args:
            context: 失败上下文
            ui_changed: UI 是否变化
            ui_change_summary: UI 变化描述
            
        Returns:
            FailureReflection: 反思结果
        """
        try:
            # 1. 准备系统提示词
            system_prompt = (
                HOT_START_FAILURE_SYSTEM_PROMPT 
                if context.failure_type == "hot_start" 
                else COLD_START_FAILURE_SYSTEM_PROMPT
            )
            
            # 2. 构建用户消息
            if context.failure_type == "hot_start":
                # 准备数据
                pre_count = len(context.pre_ui_state.get('a11y_tree', [])) if context.pre_ui_state else 0
                post_count = len(context.post_ui_state.get('a11y_tree', [])) if context.post_ui_state else 0
                
                # 格式化最近动作
                recent_actions_str = ""
                if context.recent_actions:
                    recent_actions_str = "\n".join([
                        f"{i+1}. {action.get('action', 'unknown')}({action.get('params', {})})"
                        for i, action in enumerate(context.recent_actions[-5:])  # 最近 5 个
                    ])
                
                user_message = build_hot_start_failure_user_message(
                    goal=context.goal,
                    failed_action=str(context.failed_action),
                    error_message=context.error_message,
                    error_step=context.error_step,
                    ui_changed=ui_changed,
                    ui_change_summary=ui_change_summary or "无明显变化",
                    expected_action=str(context.expected_action) if context.expected_action else None,
                    pre_ui_elements_count=pre_count,
                    post_ui_elements_count=post_count,
                    recent_actions=recent_actions_str,
                )
            else:
                user_message = build_cold_start_failure_user_message(
                    goal=context.goal,
                    failed_action=str(context.failed_action),
                    error_message=context.error_message,
                    current_step_description=context.current_step_description or "当前步骤",
                    ui_changed=ui_changed,
                    ui_change_summary=ui_change_summary,
                )
            
            # 3. 构建消息列表
            messages = [
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_message),
            ]
            
            LoggingUtils.log_debug(
                "FailureReflector",
                "🤖 Calling LLM for failure analysis..."
            )
            
            # 4. 调用 LLM
            response = await self.llm.achat(messages=messages)
            
            LoggingUtils.log_debug(
                "FailureReflector",
                "✅ LLM response received: {length} chars",
                length=len(response.message.content)
            )
            
            # 5. 解析 JSON 响应
            reflection = self._parse_llm_response(response.message.content)
            
            # 6. 计算最终置信度
            reflection.confidence = self._calculate_confidence(reflection, context, ui_changed)
            
            return reflection
            
        except Exception as e:
            LoggingUtils.log_error(
                "FailureReflector",
                "LLM analysis failed: {error}",
                error=str(e)
            )
            if self.debug:
                import traceback
                LoggingUtils.log_error("FailureReflector", "{trace}", trace=traceback.format_exc())
            
            # 返回回退反思
            return self._create_fallback_reflection(context)
    
    def _parse_llm_response(self, response_content: str) -> FailureReflection:
        """
        解析 LLM 的 JSON 响应
        
        Args:
            response_content: LLM 返回的文本内容
            
        Returns:
            FailureReflection: 解析后的反思结果
            
        Raises:
            json.JSONDecodeError: JSON 解析失败
        """
        try:
            # 清理响应内容
            content = response_content.strip()
            
            # 移除 markdown 代码块格式
            if content.startswith('```json'):
                content = content[7:]
            elif content.startswith('```'):
                content = content[3:]
            
            if content.endswith('```'):
                content = content[:-3]
            
            content = content.strip()
            
            # 解析 JSON
            data = json.loads(content)
            
            # 创建 FailureReflection 对象
            reflection = FailureReflection.from_dict(data)
            
            LoggingUtils.log_debug(
                "FailureReflector",
                "✅ Successfully parsed LLM response: {type}",
                type=reflection.problem_type
            )
            
            return reflection
            
        except json.JSONDecodeError as e:
            LoggingUtils.log_error(
                "FailureReflector",
                "Failed to parse JSON response: {error}",
                error=str(e)
            )
            LoggingUtils.log_error(
                "FailureReflector",
                "Raw response: {content}",
                content=response_content[:200]
            )
            raise
    
    def _calculate_confidence(
        self, 
        reflection: FailureReflection, 
        context: FailureContext,
        ui_changed: bool
    ) -> float:
        """
        计算反思建议的置信度
        
        Args:
            reflection: 初步的反思结果
            context: 失败上下文
            ui_changed: UI 是否变化
            
        Returns:
            置信度值（0.0-1.0）
        """
        # 基础置信度（来自 LLM）
        base_confidence = reflection.confidence
        
        # 调整因子
        adjustments = []
        
        # 1. UI 变化检测一致性
        if reflection.ui_changed == ui_changed:
            adjustments.append(0.1)  # 一致性加分
        else:
            adjustments.append(-0.1)  # 不一致扣分
        
        # 2. 错误信息明确性
        if context.error_message and len(context.error_message) > 10:
            adjustments.append(0.05)  # 有明确错误信息
        
        # 3. 建议的具体性
        if reflection.specific_advice and len(reflection.specific_advice) > 20:
            adjustments.append(0.05)  # 建议足够具体
        
        # 4. 热启动场景：有预期动作对比
        if context.failure_type == "hot_start" and context.expected_action:
            adjustments.append(0.1)  # 有更多信息
        
        # 5. 有建议的替代动作
        if reflection.suggested_action or reflection.suggested_params:
            adjustments.append(0.05)  # 提供了可执行的建议
        
        # 计算最终置信度
        final_confidence = base_confidence + sum(adjustments)
        
        # 限制在 0.0-1.0 范围内
        final_confidence = max(0.0, min(1.0, final_confidence))
        
        LoggingUtils.log_debug(
            "FailureReflector",
            "Confidence: base={base:.2f}, adjustments={adj}, final={final:.2f}",
            base=base_confidence,
            adj=adjustments,
            final=final_confidence
        )
        
        return final_confidence
    
    def _create_fallback_reflection(self, context: FailureContext) -> FailureReflection:
        """
        创建回退反思结果（当分析失败时使用）
        
        Args:
            context: 失败上下文
            
        Returns:
            FailureReflection: 保守的回退策略
        """
        return FailureReflection(
            problem_type="unknown",
            root_cause=f"Failed to analyze: {context.error_message}",
            ui_changed=False,
            ui_change_summary=None,
            recommended_strategy="fallback_cold_start",
            specific_advice="无法分析具体原因，建议回退到冷启动",
            confidence=0.3,
        )
    
    def _get_failure_cache_key(self, context: FailureContext) -> str:
        """
        生成失败场景的缓存 key
        
        Args:
            context: 失败上下文
            
        Returns:
            缓存 key 字符串
        """
        return f"{context.goal}_{context.failure_type}_{context.error_message}_{context.error_step}"
    
    def clear_cache(self):
        """清空反思结果缓存"""
        self._reflection_cache.clear()
        LoggingUtils.log_debug("FailureReflector", "Reflection cache cleared")
