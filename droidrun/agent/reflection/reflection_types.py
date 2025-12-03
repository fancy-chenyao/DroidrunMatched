"""
失败反思模块的数据类型定义

定义了失败上下文（FailureContext）和反思结果（FailureReflection）两个核心数据类型。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class FailureContext:
    """
    失败场景的完整上下文信息
    
    该类封装了执行失败时的所有相关信息，供反思器分析使用。
    
    Attributes:
        failure_type: 失败类型 ("hot_start" | "cold_start" | "action_error" | "task_incomplete")
        goal: 原始任务目标
        failed_action: 失败的动作 {"action": "tap_by_index", "params": {...}}
        error_message: 错误信息
        error_step: 第几步失败（从 0 开始）
        pre_ui_state: 执行前的 UI 状态（a11y_tree 字典）
        post_ui_state: 执行后的 UI 状态
        recent_actions: 最近 3-5 个动作的列表
        trajectory: 完整的 Trajectory 对象（可选，用于深度分析）
        expected_action: 热启动时的预期动作（历史记录）
        adapted_params: 参数适配的详细信息
        current_step_description: 当前步骤的任务描述（冷启动专用）
    """
    
    # 基础信息
    failure_type: str
    goal: str
    error_message: str
    error_step: int
    
    # 失败动作
    failed_action: Optional[Dict[str, Any]] = None
    
    # UI 状态对比
    pre_ui_state: Optional[Dict[str, Any]] = None
    post_ui_state: Optional[Dict[str, Any]] = None
    
    # 执行历史
    recent_actions: List[Dict[str, Any]] = field(default_factory=list)
    trajectory: Optional[Any] = None  # Trajectory 对象
    
    # 热启动特有字段
    expected_action: Optional[Dict[str, Any]] = None
    adapted_params: Optional[Dict[str, Any]] = None
    
    # 冷启动特有字段
    current_step_description: Optional[str] = None
    
    @classmethod
    def from_hot_start_failure(
        cls,
        goal: str,
        failed_action: Optional[Dict[str, Any]],
        error_message: str,
        error_step: int,
        pre_ui_state: Optional[Dict[str, Any]] = None,
        post_ui_state: Optional[Dict[str, Any]] = None,
        recent_actions: Optional[List[Dict[str, Any]]] = None,
        expected_action: Optional[Dict[str, Any]] = None,
        adapted_params: Optional[Dict[str, Any]] = None,
        trajectory: Optional[Any] = None,
    ) -> "FailureContext":
        """
        从热启动失败创建上下文
        
        Args:
            goal: 原始任务目标
            failed_action: 失败的动作
            error_message: 错误信息
            error_step: 失败步骤
            pre_ui_state: 执行前 UI 状态
            post_ui_state: 执行后 UI 状态
            recent_actions: 最近执行的动作列表
            expected_action: 预期动作（来自历史记录）
            adapted_params: 参数适配信息
            trajectory: 完整轨迹
            
        Returns:
            FailureContext 实例
        """
        return cls(
            failure_type="hot_start",
            goal=goal,
            failed_action=failed_action,
            error_message=error_message,
            error_step=error_step,
            pre_ui_state=pre_ui_state,
            post_ui_state=post_ui_state,
            recent_actions=recent_actions or [],
            expected_action=expected_action,
            adapted_params=adapted_params,
            trajectory=trajectory,
        )
    
    @classmethod
    def from_action_failure(
        cls,
        goal: str,
        failed_action: Dict[str, Any],
        error_message: str,
        error_step: int,
        pre_ui_state: Optional[Dict[str, Any]] = None,
        post_ui_state: Optional[Dict[str, Any]] = None,
        current_step_description: Optional[str] = None,
        recent_actions: Optional[List[Dict[str, Any]]] = None,
    ) -> "FailureContext":
        """
        从单个动作失败创建上下文（冷启动场景）
        
        Args:
            goal: 原始任务目标
            failed_action: 失败的动作
            error_message: 错误信息
            error_step: 失败步骤
            pre_ui_state: 执行前 UI 状态
            post_ui_state: 执行后 UI 状态
            current_step_description: 当前子任务描述
            recent_actions: 最近执行的动作列表
            
        Returns:
            FailureContext 实例
        """
        return cls(
            failure_type="cold_start_action",
            goal=goal,
            failed_action=failed_action,
            error_message=error_message,
            error_step=error_step,
            pre_ui_state=pre_ui_state,
            post_ui_state=post_ui_state,
            current_step_description=current_step_description,
            recent_actions=recent_actions or [],
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典（用于日志和序列化）
        
        Returns:
            包含所有字段的字典
        """
        return {
            "failure_type": self.failure_type,
            "goal": self.goal,
            "error_message": self.error_message,
            "error_step": self.error_step,
            "failed_action": self.failed_action,
            "has_pre_ui": self.pre_ui_state is not None,
            "has_post_ui": self.post_ui_state is not None,
            "recent_actions_count": len(self.recent_actions),
            "expected_action": self.expected_action,
            "current_step_description": self.current_step_description,
        }


@dataclass
class FailureReflection:
    """
    失败分析反思结果
    
    该类包含反思器对失败场景的完整分析结果和改进建议。
    
    Attributes:
        problem_type: 问题类型
            - "ui_changed": UI 改版，元素索引/位置变化
            - "wrong_element": 点击了错误的元素
            - "action_ineffective": 动作类型不对（如应该 long_press 而非 tap）
            - "parameter_mismatch": 参数适配错误（文本不匹配等）
            - "environment_error": 环境问题（网络、权限等）
        root_cause: 根本原因分析（1-2句话）
        ui_changed: 执行前后 UI 是否变化
        ui_change_summary: UI 变化的描述（如有变化）
        recommended_strategy: 推荐的策略
            - "fallback_cold_start": 立即回退到冷启动
            - "retry_with_adjustment": 重试（带调整）
            - "skip_and_continue": 跳过该步骤
            - "reset_ui_state": 重置 UI 状态
        specific_advice: 具体可执行的建议（2-3句话，针对当前 UI 状态）
        suggested_action: 建议的替代动作（可选）
        suggested_params: 建议的参数调整（可选）
        confidence: 反思建议的置信度（0.0-1.0）
    """
    
    # 问题诊断
    problem_type: str
    root_cause: str
    
    # UI 状态分析
    ui_changed: bool
    ui_change_summary: Optional[str] = None
    
    # 决策建议
    recommended_strategy: str = "fallback_cold_start"
    specific_advice: str = ""
    
    # 调整参数（可选）
    suggested_action: Optional[Dict[str, Any]] = None
    suggested_params: Optional[Dict[str, Any]] = None
    
    # 置信度
    confidence: float = 0.5
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FailureReflection":
        """
        从字典创建 FailureReflection 对象（用于从 LLM 响应解析）
        
        Args:
            data: 包含反思结果的字典
            
        Returns:
            FailureReflection 实例
        """
        return cls(
            problem_type=data.get("problem_type", "unknown"),
            root_cause=data.get("root_cause", ""),
            ui_changed=data.get("ui_changed", False),
            ui_change_summary=data.get("ui_change_summary"),
            recommended_strategy=data.get("recommended_strategy", "fallback_cold_start"),
            specific_advice=data.get("specific_advice", ""),
            suggested_action=data.get("suggested_action"),
            suggested_params=data.get("suggested_params"),
            confidence=data.get("confidence", 0.5),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典（用于日志和序列化）
        
        Returns:
            包含所有字段的字典
        """
        return {
            "problem_type": self.problem_type,
            "root_cause": self.root_cause,
            "ui_changed": self.ui_changed,
            "ui_change_summary": self.ui_change_summary,
            "recommended_strategy": self.recommended_strategy,
            "specific_advice": self.specific_advice,
            "suggested_action": self.suggested_action,
            "suggested_params": self.suggested_params,
            "confidence": self.confidence,
        }
    
    def should_apply_advice(self, threshold: float = 0.6) -> bool:
        """
        判断是否应该应用反思建议
        
        Args:
            threshold: 置信度阈值（默认 0.6）
            
        Returns:
            True 如果置信度足够高，False 否则
        """
        return self.confidence >= threshold
