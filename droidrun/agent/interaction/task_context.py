"""任务执行上下文

管理任务的完整生命周期，支持暂停和恢复
"""

from typing import Dict, Any, List, Callable, Optional
import time

from .task_state import TaskState
from .resume_context import ResumeContext


class TaskExecutionContext:
    """任务执行上下文
    
    管理单个任务的完整生命周期，包括状态、变量、暂停/恢复等
    
    Attributes:
        task_id: 任务唯一标识
        goal: 任务目标描述
        task_type: 任务类型（可选）
        state: 当前状态
        created_at: 创建时间
        updated_at: 最后更新时间
        current_step: 当前步骤索引
        executed_actions: 已执行的动作列表
        variables: 任务变量字典
        current_resume_context: 当前的恢复上下文
        pending_question_id: 待处理的问题ID
        resume_callback: 恢复时的回调函数
        result: 任务结果
        error: 错误信息
    """
    
    def __init__(
        self, 
        task_id: str, 
        goal: str, 
        task_type: str = None
    ):
        """初始化任务上下文
        
        Args:
            task_id: 任务唯一标识
            goal: 任务目标描述
            task_type: 任务类型（可选）
        """
        self.task_id = task_id
        self.goal = goal
        self.task_type = task_type
        
        # 状态管理
        self.state = TaskState.INITIALIZED
        self.created_at = time.time()
        self.updated_at = time.time()
        
        # 执行进度
        self.current_step = 0
        self.executed_actions: List[Dict[str, Any]] = []
        
        # 任务变量（用于存储中间结果）
        self.variables: Dict[str, Any] = {}
        
        # 暂停/恢复相关
        self.current_resume_context: Optional[ResumeContext] = None
        self.pending_question_id: Optional[str] = None
        self.resume_callback: Optional[Callable] = None
        
        # 结果
        self.result = None
        self.error = None
    
    def set_state(self, new_state: TaskState, reason: str = None):
        """更新任务状态
        
        Args:
            new_state: 新状态
            reason: 状态变更原因（用于日志）
        """
        old_state = self.state
        self.state = new_state
        self.updated_at = time.time()
        
        print(
            f"[TaskContext] {self.task_id[:8]}... "
            f"State: {old_state.value} → {new_state.value}"
            + (f" (reason: {reason})" if reason else "")
        )
    
    def pause_for_user_input(
        self,
        question_id: str,
        resume_context: ResumeContext,
        resume_callback: Callable,
        reason: str = None
    ):
        """暂停任务等待用户输入
        
        Args:
            question_id: 问题ID
            resume_context: 恢复上下文
            resume_callback: 恢复时的回调函数
            reason: 暂停原因
        """
        if self.state == TaskState.WAITING_USER:
            print(
                f"[TaskContext] ⚠️ Task {self.task_id[:8]}... "
                "already waiting for user input"
            )
            return
        
        self.current_resume_context = resume_context
        self.pending_question_id = question_id
        self.resume_callback = resume_callback
        
        self.set_state(TaskState.WAITING_USER, reason or "User input required")
        
        print(
            f"[TaskContext] ⏸️ Task {self.task_id[:8]}... paused, "
            f"question: {question_id}, "
            f"action: {resume_context.action_name}"
        )
    
    def resume_with_answer(self, answer: Any, additional_data: Dict = None):
        """使用用户回答恢复任务
        
        Args:
            answer: 用户的回答
            additional_data: 额外数据（可选）
        
        Raises:
            ValueError: 如果当前状态不允许恢复
        """
        if self.state != TaskState.WAITING_USER:
            raise ValueError(
                f"Cannot resume task in state: {self.state.value}"
            )
        
        if not self.current_resume_context:
            raise ValueError("No resume context available")
        
        # 应用用户回答到恢复上下文
        self.current_resume_context.apply_answer(answer, additional_data)
        
        # 更新状态
        self.set_state(TaskState.RUNNING, "Resumed with user answer")
        
        print(
            f"[TaskContext] ▶️ Task {self.task_id[:8]}... resumed, "
            f"answer: {str(answer)[:50]}"
        )
        
        # 触发回调
        if self.resume_callback:
            try:
                self.resume_callback(self.current_resume_context, answer)
            except Exception as e:
                print(f"[TaskContext] ❌ Resume callback error: {e}")
                self.error = str(e)
    
    def record_action(
        self, 
        action_name: str, 
        args: tuple = None,
        kwargs: Dict = None,
        result: Any = None,
        error: str = None
    ):
        """记录已执行的动作
        
        Args:
            action_name: 动作名称
            args: 位置参数
            kwargs: 关键字参数
            result: 执行结果
            error: 错误信息（如果有）
        """
        action_record = {
            "step": self.current_step,
            "action": action_name,
            "args": args,
            "kwargs": kwargs,
            "result": result,
            "error": error,
            "timestamp": time.time()
        }
        
        self.executed_actions.append(action_record)
        self.current_step += 1
    
    def set_variable(self, key: str, value: Any):
        """设置任务变量
        
        Args:
            key: 变量名
            value: 变量值
        """
        self.variables[key] = value
    
    def get_variable(self, key: str, default: Any = None) -> Any:
        """获取任务变量
        
        Args:
            key: 变量名
            default: 默认值
        
        Returns:
            变量值
        """
        return self.variables.get(key, default)
    
    def complete(self, result: Any):
        """标记任务完成
        
        Args:
            result: 任务结果
        """
        self.set_state(TaskState.COMPLETED, "Task completed successfully")
        self.result = result
        
        print(
            f"[TaskContext] ✅ Task {self.task_id[:8]}... completed, "
            f"steps: {self.current_step}"
        )
    
    def fail(self, error: str):
        """标记任务失败
        
        Args:
            error: 错误信息
        """
        self.set_state(TaskState.FAILED, f"Task failed: {error}")
        self.error = error
        
        print(
            f"[TaskContext] ❌ Task {self.task_id[:8]}... failed: {error}"
        )
    
    def cancel(self, reason: str = None):
        """取消任务
        
        Args:
            reason: 取消原因
        """
        self.set_state(TaskState.CANCELLED, reason or "Task cancelled")
        
        print(
            f"[TaskContext] 🚫 Task {self.task_id[:8]}... cancelled"
            + (f": {reason}" if reason else "")
        )
    
    def get_summary(self) -> Dict[str, Any]:
        """获取任务摘要
        
        Returns:
            包含关键信息的字典
        """
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "task_type": self.task_type,
            "state": self.state.value,
            "current_step": self.current_step,
            "executed_actions_count": len(self.executed_actions),
            "is_waiting_user": self.state == TaskState.WAITING_USER,
            "pending_question_id": self.pending_question_id,
            "has_result": self.result is not None,
            "has_error": self.error is not None,
            "age_seconds": time.time() - self.created_at,
            "last_activity_age": time.time() - self.updated_at
        }
    
    def __repr__(self) -> str:
        """字符串表示"""
        return (
            f"TaskExecutionContext(id={self.task_id[:8]}..., "
            f"state={self.state.value}, step={self.current_step})"
        )
