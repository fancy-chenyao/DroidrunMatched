"""恢复上下文

保存完整的动作上下文，支持暂停后精确恢复
"""

from dataclasses import dataclass, field
from typing import Callable, Any, Dict, Optional, Tuple
import time
import asyncio

from .task_state import ResumeStrategy


@dataclass
class ResumeContext:
    """完整的恢复上下文
    
    保存动作执行所需的所有信息，使得任务暂停后能精确恢复
    
    Attributes:
        resume_id: 唯一标识
        step_index: 步骤索引
        action_name: 动作名称（如 "tap_by_index", "input_text"）
        action_func: 动作函数
        original_args: 原始位置参数
        original_kwargs: 原始关键字参数
        strategy: 恢复策略
        created_at: 创建时间
        context_data: 额外的上下文数据
        modified_args: 修改后的位置参数
        modified_kwargs: 修改后的关键字参数
    """
    
    resume_id: str
    step_index: int
    action_name: str
    action_func: Callable
    original_args: tuple = field(default_factory=tuple)
    original_kwargs: Dict[str, Any] = field(default_factory=dict)
    strategy: ResumeStrategy = ResumeStrategy.REPLACE_PARAM
    created_at: float = field(default_factory=lambda: time.time())
    context_data: Dict[str, Any] = field(default_factory=dict)
    
    # 用户回答后修改的参数
    modified_args: Optional[tuple] = None
    modified_kwargs: Optional[Dict[str, Any]] = None
    
    def apply_answer(
        self, 
        answer: Any,
        additional_data: Dict[str, Any] = None
    ) -> Tuple[tuple, Dict[str, Any]]:
        """应用用户回答到参数
        
        根据不同的恢复策略，将用户回答应用到原始参数中
        
        Args:
            answer: 用户的回答
            additional_data: 额外的数据（可选）
        
        Returns:
            (modified_args, modified_kwargs): 修改后的参数
        """
        args = list(self.original_args)
        kwargs = self.original_kwargs.copy()
        
        if self.strategy == ResumeStrategy.REPLACE_PARAM:
            # 策略1: 替换参数
            # 优先替换kwargs中的关键参数
            if "text" in kwargs:
                kwargs["text"] = answer
            elif "value" in kwargs:
                kwargs["value"] = answer
            elif len(args) > 0:
                # 替换第一个位置参数
                args[0] = answer
        
        elif self.strategy == ResumeStrategy.CONFIRM_CANCEL:
            # 策略2: 确认/取消
            confirmed = self._parse_confirmation(answer)
            kwargs["__user_confirmed"] = confirmed
        
        elif self.strategy == ResumeStrategy.PARAMETER_FILL:
            # 策略3: 填充参数
            param_name = self.context_data.get("param_name")
            if param_name:
                kwargs[param_name] = answer
            else:
                # 如果没有指定参数名，添加到kwargs
                kwargs["user_input"] = answer
        
        elif self.strategy == ResumeStrategy.ELEMENT_SELECTION:
            # 策略4: 元素选择
            # answer可能是索引或元素标识
            if isinstance(answer, (int, str)):
                kwargs["selected_element"] = answer
        
        # 合并额外数据
        if additional_data:
            kwargs.update(additional_data)
        
        self.modified_args = tuple(args)
        self.modified_kwargs = kwargs
        
        return (self.modified_args, self.modified_kwargs)
    
    def _parse_confirmation(self, answer: Any) -> bool:
        """解析确认/取消回答
        
        Args:
            answer: 用户回答
        
        Returns:
            True表示确认，False表示取消
        """
        if isinstance(answer, bool):
            return answer
        
        answer_str = str(answer).lower().strip()
        
        # 取消的关键词（优先检查，避免误判）
        negative_keywords = [
            "否", "no", "n", "取消", "false", "0", "停止", "不", "不同意"
        ]
        
        # 确认的关键词
        positive_keywords = [
            "是", "yes", "y", "确定", "确认", "ok", "okay", 
            "true", "1", "继续", "同意"
        ]
        
        # 先检查否定（避免"不同意"被"同意"匹配）
        if any(keyword in answer_str for keyword in negative_keywords):
            return False
        
        # 再检查肯定
        if any(keyword in answer_str for keyword in positive_keywords):
            return True
        
        # 默认为取消（安全策略）
        return False
    
    async def execute_with_modified_params(self) -> Any:
        """使用修改后的参数执行动作
        
        Returns:
            动作执行结果
        
        Raises:
            ValueError: 如果尚未应用用户回答
            UserCancelledError: 如果用户取消了操作
        """
        if self.modified_args is None or self.modified_kwargs is None:
            raise ValueError("Must call apply_answer() before executing")
        
        # 对于确认/取消策略，检查用户是否确认
        if self.strategy == ResumeStrategy.CONFIRM_CANCEL:
            if not self.modified_kwargs.get("__user_confirmed", False):
                raise UserCancelledError(
                    f"User cancelled action: {self.action_name}"
                )
            # 移除标记，避免传递给实际函数
            self.modified_kwargs.pop("__user_confirmed", None)
        
        # 执行动作（支持同步和异步函数）
        if asyncio.iscoroutinefunction(self.action_func):
            return await self.action_func(
                *self.modified_args, 
                **self.modified_kwargs
            )
        else:
            return self.action_func(
                *self.modified_args, 
                **self.modified_kwargs
            )
    
    def get_summary(self) -> Dict[str, Any]:
        """获取上下文摘要
        
        Returns:
            包含关键信息的字典
        """
        return {
            "resume_id": self.resume_id,
            "step_index": self.step_index,
            "action_name": self.action_name,
            "strategy": self.strategy.value,
            "has_applied_answer": self.modified_args is not None,
            "created_at": self.created_at,
            "age_seconds": time.time() - self.created_at
        }


class UserCancelledError(Exception):
    """用户取消操作异常
    
    当用户明确取消某个操作时抛出此异常
    """
    pass
