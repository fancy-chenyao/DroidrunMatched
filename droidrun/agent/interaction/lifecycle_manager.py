"""任务生命周期管理器

管理任务的完整生命周期，协调 TaskExecutionContext 和 InteractionManager
"""

from typing import Dict, Any, Optional
import uuid

from .task_context import TaskExecutionContext
from .task_state import TaskState
from .manager import InteractionManager


class LifecycleManager:
    """任务生命周期管理器
    
    职责：
    1. 创建和管理 TaskExecutionContext
    2. 协调 InteractionManager
    3. 管理任务状态转换
    4. 提供统一的任务管理接口
    
    Example:
        >>> lifecycle = LifecycleManager()
        >>> 
        >>> # 开始任务
        >>> task_ctx = lifecycle.start_task("填写表单")
        >>> 
        >>> # 记录动作
        >>> lifecycle.record_action(task_ctx.task_id, "tap_by_index", {"index": 100})
        >>> 
        >>> # 完成任务
        >>> lifecycle.complete_task(task_ctx.task_id, success=True)
    """
    
    def __init__(self, interaction_manager: InteractionManager = None):
        """初始化生命周期管理器
        
        Args:
            interaction_manager: InteractionManager 实例，如果为 None 则创建新实例
        """
        self.interaction_manager = interaction_manager or InteractionManager()
        self._tasks: Dict[str, TaskExecutionContext] = {}
        self._current_task_id: Optional[str] = None
    
    def start_task(
        self,
        goal: str,
        task_type: str = "default",
        task_id: str = None
    ) -> TaskExecutionContext:
        """开始一个新任务
        
        Args:
            goal: 任务目标描述
            task_type: 任务类型
            task_id: 任务ID（可选，如果不提供则自动生成）
        
        Returns:
            TaskExecutionContext: 任务执行上下文
        """
        # 生成任务ID
        if not task_id:
            task_id = f"task-{uuid.uuid4().hex[:8]}"
        
        # 创建任务上下文
        task_ctx = TaskExecutionContext(
            task_id=task_id,
            goal=goal,
            task_type=task_type
        )
        
        # 设置为运行状态
        task_ctx.set_state(TaskState.RUNNING, "Task started")
        
        # 保存任务
        self._tasks[task_id] = task_ctx
        self._current_task_id = task_id
        
        # 注册到 InteractionManager
        self.interaction_manager.register_task(task_ctx)
        
        return task_ctx
    
    def get_task(self, task_id: str = None) -> Optional[TaskExecutionContext]:
        """获取任务上下文
        
        Args:
            task_id: 任务ID，如果为 None 则返回当前任务
        
        Returns:
            TaskExecutionContext 或 None
        """
        if task_id is None:
            task_id = self._current_task_id
        
        return self._tasks.get(task_id)
    
    def get_current_task(self) -> Optional[TaskExecutionContext]:
        """获取当前任务
        
        Returns:
            TaskExecutionContext 或 None
        """
        return self.get_task(self._current_task_id)
    
    def record_action(
        self,
        task_id: str,
        action_name: str,
        action_params: Dict[str, Any] = None,
        result: Any = None
    ):
        """记录任务动作
        
        Args:
            task_id: 任务ID
            action_name: 动作名称
            action_params: 动作参数（字典）
            result: 动作结果（可选）
        """
        task_ctx = self.get_task(task_id)
        if task_ctx:
            # TaskExecutionContext.record_action 接受 args, kwargs
            # 我们将 action_params 作为 kwargs 传递
            task_ctx.record_action(
                action_name=action_name,
                args=None,
                kwargs=action_params or {},
                result=result
            )
    
    def set_variable(self, task_id: str, key: str, value: Any):
        """设置任务变量
        
        Args:
            task_id: 任务ID
            key: 变量名
            value: 变量值
        """
        task_ctx = self.get_task(task_id)
        if task_ctx:
            task_ctx.set_variable(key, value)
    
    def get_variable(self, task_id: str, key: str, default: Any = None) -> Any:
        """获取任务变量
        
        Args:
            task_id: 任务ID
            key: 变量名
            default: 默认值
        
        Returns:
            变量值或默认值
        """
        task_ctx = self.get_task(task_id)
        if task_ctx:
            return task_ctx.get_variable(key, default)
        return default
    
    def complete_task(
        self,
        task_id: str,
        success: bool,
        reason: str = "",
        result: Any = None
    ):
        """完成任务
        
        Args:
            task_id: 任务ID
            success: 是否成功
            reason: 原因
            result: 结果数据
        """
        task_ctx = self.get_task(task_id)
        if task_ctx:
            if success:
                task_ctx.complete(result)
            else:
                task_ctx.fail(reason)
            
            # 从 InteractionManager 注销
            self.interaction_manager.unregister_task(task_id)
            
            # 如果是当前任务，清除当前任务ID
            if self._current_task_id == task_id:
                self._current_task_id = None
    
    def cancel_task(self, task_id: str, reason: str = ""):
        """取消任务
        
        Args:
            task_id: 任务ID
            reason: 取消原因
        """
        task_ctx = self.get_task(task_id)
        if task_ctx:
            task_ctx.cancel(reason)
            
            # 从 InteractionManager 注销
            self.interaction_manager.unregister_task(task_id)
            
            # 如果是当前任务，清除当前任务ID
            if self._current_task_id == task_id:
                self._current_task_id = None
    
    def get_task_summary(self, task_id: str = None) -> Dict[str, Any]:
        """获取任务摘要
        
        Args:
            task_id: 任务ID，如果为 None 则返回当前任务摘要
        
        Returns:
            任务摘要字典
        """
        task_ctx = self.get_task(task_id)
        if task_ctx:
            return task_ctx.get_summary()
        return {}
    
    def get_all_tasks_summary(self) -> Dict[str, Dict[str, Any]]:
        """获取所有任务的摘要
        
        Returns:
            任务ID到摘要的映射
        """
        return {
            task_id: task_ctx.get_summary()
            for task_id, task_ctx in self._tasks.items()
        }
    
    def cleanup_finished_tasks(self):
        """清理已完成/失败/取消的任务"""
        finished_states = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
        
        task_ids_to_remove = [
            task_id for task_id, task_ctx in self._tasks.items()
            if task_ctx.state in finished_states
        ]
        
        for task_id in task_ids_to_remove:
            # 从 InteractionManager 注销
            self.interaction_manager.unregister_task(task_id)
            # 从字典中删除
            del self._tasks[task_id]
    
    async def shutdown(self):
        """关闭生命周期管理器"""
        # 取消所有运行中的任务
        for task_id, task_ctx in list(self._tasks.items()):
            if task_ctx.state in {TaskState.RUNNING, TaskState.WAITING_USER}:
                self.cancel_task(task_id, "Lifecycle manager shutdown")
        
        # 关闭 InteractionManager
        await self.interaction_manager.shutdown()
        
        # 清理
        self._tasks.clear()
        self._current_task_id = None
    
    def __repr__(self) -> str:
        """字符串表示"""
        return (
            f"LifecycleManager("
            f"tasks={len(self._tasks)}, "
            f"current={self._current_task_id})"
        )
