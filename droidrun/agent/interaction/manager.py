"""交互管理器

管理用户交互的核心组件，支持非阻塞询问和消息路由
"""

import asyncio
import uuid
from typing import Dict, Callable, Any, Optional
from dataclasses import dataclass, field
import time

from .task_context import TaskExecutionContext
from .resume_context import ResumeContext
from .timeout_manager import TimeoutManager


@dataclass
class PendingQuestion:
    """待处理的问题
    
    Attributes:
        question_id: 问题唯一标识
        task_id: 关联的任务ID
        question_text: 问题文本
        question_type: 问题类型（text, choice, confirm等）
        options: 选项列表（用于 choice 类型）
        default_value: 默认值
        timeout_seconds: 超时秒数
        created_at: 创建时间
        future: 用于等待答案的 Future
        resume_context: 恢复上下文
        on_answer_callback: 收到答案的回调
        on_timeout_callback: 超时的回调
    """
    question_id: str
    task_id: str
    question_text: str
    question_type: str = "text"
    options: list = field(default_factory=list)
    default_value: Any = None
    timeout_seconds: float = 60.0
    created_at: float = field(default_factory=lambda: time.time())
    
    # 异步通信
    future: Optional[asyncio.Future] = None
    
    # 恢复相关
    resume_context: Optional[ResumeContext] = None
    on_answer_callback: Optional[Callable] = None
    on_timeout_callback: Optional[Callable] = None


class InteractionManager:
    """交互管理器
    
    核心功能：
    1. 非阻塞询问机制：使用 Future 实现异步等待
    2. 消息路由：将用户答案路由到对应的任务
    3. 超时管理：自动处理超时情况
    4. 任务管理：管理多个任务的交互
    
    Example:
        >>> manager = InteractionManager()
        >>> 
        >>> # 创建任务
        >>> task_ctx = TaskExecutionContext("task-1", "测试任务")
        >>> manager.register_task(task_ctx)
        >>> 
        >>> # 非阻塞询问
        >>> question_id = await manager.ask_user_async(
        ...     task_id="task-1",
        ...     question_text="请输入用户名:",
        ...     question_type="text",
        ...     resume_context=resume_ctx,
        ...     on_answer_callback=on_answer
        ... )
        >>> 
        >>> # 用户回答（通常从 WebSocket 调用）
        >>> await manager.provide_answer(question_id, "张三")
    """
    
    def __init__(self, websocket_send_callback: Optional[Callable] = None):
        """初始化交互管理器
        
        Args:
            websocket_send_callback: WebSocket 发送回调函数
                签名: async def callback(message: dict) -> None
        """
        # 任务管理
        self._tasks: Dict[str, TaskExecutionContext] = {}
        
        # 问题管理
        self._pending_questions: Dict[str, PendingQuestion] = {}
        
        # 超时管理
        self._timeout_manager = TimeoutManager()
        
        # 运行状态
        self._running = True
        
        # WebSocket 发送回调
        self._websocket_send_callback = websocket_send_callback
    
    def register_task(self, task_context: TaskExecutionContext):
        """注册任务
        
        Args:
            task_context: 任务执行上下文
        """
        self._tasks[task_context.task_id] = task_context
    
    def unregister_task(self, task_id: str) -> bool:
        """注销任务
        
        Args:
            task_id: 任务ID
        
        Returns:
            True 如果成功注销，False 如果任务不存在
        """
        if task_id in self._tasks:
            # 取消该任务的所有待处理问题
            self._cancel_task_questions(task_id)
            del self._tasks[task_id]
            return True
        return False
    
    def get_task(self, task_id: str) -> Optional[TaskExecutionContext]:
        """获取任务上下文
        
        Args:
            task_id: 任务ID
        
        Returns:
            任务上下文，如果不存在返回 None
        """
        return self._tasks.get(task_id)
    
    async def ask_user_async(
        self,
        task_id: str,
        question_text: str,
        question_type: str = "text",
        options: list = None,
        default_value: Any = None,
        timeout_seconds: float = 60.0,
        resume_context: ResumeContext = None,
        on_answer_callback: Callable = None,
        on_timeout_callback: Callable = None
    ) -> str:
        """非阻塞询问用户（异步）
        
        这是核心方法，使用 Future 实现非阻塞等待：
        1. 创建问题记录
        2. 发送问题到 Android 端（通过 WebSocket）
        3. 设置超时
        4. 立即返回 question_id
        5. 用户回答通过 provide_answer() 到达
        
        Args:
            task_id: 任务ID
            question_text: 问题文本
            question_type: 问题类型（text, choice, confirm）
            options: 选项列表（用于 choice 类型）
            default_value: 默认值
            timeout_seconds: 超时秒数
            resume_context: 恢复上下文
            on_answer_callback: 收到答案的回调
            on_timeout_callback: 超时的回调
        
        Returns:
            question_id: 问题唯一标识
        
        Raises:
            ValueError: 如果任务不存在
        """
        # 验证任务存在
        task_ctx = self.get_task(task_id)
        if not task_ctx:
            raise ValueError(f"Task '{task_id}' not found")
        
        # 生成问题ID
        question_id = f"q-{uuid.uuid4().hex[:8]}"
        
        # 创建 Future 用于异步等待（使用当前运行的事件循环）
        try:
            future = asyncio.get_running_loop().create_future()
        except RuntimeError:
            # 如果没有运行的事件循环，回退到 get_event_loop()
            future = asyncio.get_event_loop().create_future()
        
        # 创建问题记录
        question = PendingQuestion(
            question_id=question_id,
            task_id=task_id,
            question_text=question_text,
            question_type=question_type,
            options=options or [],
            default_value=default_value,
            timeout_seconds=timeout_seconds,
            future=future,
            resume_context=resume_context,
            on_answer_callback=on_answer_callback,
            on_timeout_callback=on_timeout_callback
        )
        
        # 保存问题
        self._pending_questions[question_id] = question
        
        # 设置超时
        await self._timeout_manager.set_timeout(
            timeout_id=question_id,
            delay_seconds=timeout_seconds,
            callback=self._on_question_timeout,
            callback_args=(question_id,)
        )
        
        # 通过 WebSocket 发送问题到 Android 端
        if self._websocket_send_callback:
            try:
                message = {
                    "type": "user_question",
                    "question_id": question_id,
                    "question_text": question_text,
                    "question_type": question_type,
                    "options": options,
                    "default_value": default_value,
                    "timeout_seconds": timeout_seconds
                }
                await self._websocket_send_callback(message)
                print(f"✅ [InteractionManager] Question sent via WebSocket: {question_id}")
            except Exception as e:
                print(f"❌ [InteractionManager] Failed to send question: {e}")
        else:
            # 如果没有 WebSocket 回调，只打印日志（用于测试）
            print(f"📤 [InteractionManager] Question sent (no WebSocket): {question_id}")
            print(f"   Task: {task_id}")
            print(f"   Question: {question_text}")
            print(f"   Type: {question_type}")
            if options:
                print(f"   Options: {options}")
        
        # 立即返回 question_id（非阻塞）
        return question_id
    
    async def provide_answer(
        self,
        question_id: str,
        answer: Any,
        additional_data: Dict[str, Any] = None
    ) -> bool:
        """提供问题答案（通常从 WebSocket 调用）
        
        这个方法会：
        1. 找到对应的问题
        2. 取消超时
        3. 触发回调
        4. 解决 Future
        5. 清理问题记录
        
        Args:
            question_id: 问题ID
            answer: 用户答案
            additional_data: 额外数据
        
        Returns:
            True 如果成功处理，False 如果问题不存在
        """
        question = self._pending_questions.get(question_id)
        if not question:
            print(f"⚠️  [InteractionManager] Question not found: {question_id}")
            return False
        
        print(f"📥 [InteractionManager] Answer received: {question_id}")
        print(f"   Answer: {answer}")
        
        # 取消超时
        self._timeout_manager.cancel_timeout(question_id)
        
        # 触发回调
        if question.on_answer_callback:
            try:
                if asyncio.iscoroutinefunction(question.on_answer_callback):
                    await question.on_answer_callback(
                        question.resume_context,
                        answer,
                        additional_data
                    )
                else:
                    question.on_answer_callback(
                        question.resume_context,
                        answer,
                        additional_data
                    )
            except Exception as e:
                print(f"❌ [InteractionManager] Callback error: {e}")
        
        # 解决 Future
        if question.future and not question.future.done():
            question.future.set_result(answer)
        
        # 清理
        if question_id in self._pending_questions:
            del self._pending_questions[question_id]
        
        return True
    
    def _on_question_timeout(self, question_id: str):
        """问题超时处理（内部方法）
        
        Args:
            question_id: 问题ID
        """
        question = self._pending_questions.get(question_id)
        if not question:
            return
        
        print(f"⏰ [InteractionManager] Question timeout: {question_id}")
        
        # 使用默认值
        answer = question.default_value
        
        # 触发超时回调
        if question.on_timeout_callback:
            try:
                question.on_timeout_callback(question.resume_context, answer)
            except Exception as e:
                print(f"❌ [InteractionManager] Timeout callback error: {e}")
        
        # 解决 Future（使用默认值）
        if question.future and not question.future.done():
            question.future.set_result(answer)
        
        # 清理
        if question_id in self._pending_questions:
            del self._pending_questions[question_id]
    
    def _cancel_task_questions(self, task_id: str):
        """取消任务的所有待处理问题（内部方法）
        
        Args:
            task_id: 任务ID
        """
        question_ids = [
            qid for qid, q in self._pending_questions.items()
            if q.task_id == task_id
        ]
        
        for question_id in question_ids:
            self.cancel_question(question_id)
    
    def cancel_question(self, question_id: str) -> bool:
        """取消问题
        
        Args:
            question_id: 问题ID
        
        Returns:
            True 如果成功取消，False 如果问题不存在
        """
        question = self._pending_questions.get(question_id)
        if not question:
            return False
        
        # 取消超时
        self._timeout_manager.cancel_timeout(question_id)
        
        # 取消 Future
        if question.future and not question.future.done():
            question.future.cancel()
        
        # 清理
        if question_id in self._pending_questions:
            del self._pending_questions[question_id]
        
        return True
    
    def get_pending_questions(self, task_id: str = None) -> list:
        """获取待处理的问题列表
        
        Args:
            task_id: 可选的任务ID，如果提供则只返回该任务的问题
        
        Returns:
            问题ID列表
        """
        if task_id:
            return [
                qid for qid, q in self._pending_questions.items()
                if q.task_id == task_id
            ]
        return list(self._pending_questions.keys())
    
    def has_pending_question(self, question_id: str) -> bool:
        """检查问题是否待处理
        
        Args:
            question_id: 问题ID
        
        Returns:
            True 如果存在，False 否则
        """
        return question_id in self._pending_questions
    
    def get_question(self, question_id: str) -> Optional[PendingQuestion]:
        """获取问题详情
        
        Args:
            question_id: 问题ID
        
        Returns:
            问题对象，如果不存在返回 None
        """
        return self._pending_questions.get(question_id)
    
    def get_summary(self) -> Dict[str, Any]:
        """获取管理器状态摘要
        
        Returns:
            包含状态信息的字典
        """
        return {
            "running": self._running,
            "registered_tasks": len(self._tasks),
            "task_ids": list(self._tasks.keys()),
            "pending_questions": len(self._pending_questions),
            "question_ids": list(self._pending_questions.keys()),
            "timeout_manager": self._timeout_manager.get_summary()
        }
    
    async def shutdown(self):
        """关闭管理器，清理所有资源"""
        self._running = False
        
        # 取消所有问题
        question_ids = list(self._pending_questions.keys())
        for question_id in question_ids:
            self.cancel_question(question_id)
        
        # 关闭超时管理器
        await self._timeout_manager.shutdown()
        
        # 清理任务
        self._tasks.clear()
    
    def __repr__(self) -> str:
        """字符串表示"""
        return (
            f"InteractionManager("
            f"tasks={len(self._tasks)}, "
            f"questions={len(self._pending_questions)})"
        )
