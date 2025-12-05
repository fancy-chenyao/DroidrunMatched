"""超时管理器

统一管理异步超时，支持取消和清理
"""

import asyncio
import time
from typing import Dict, Callable, Any, Optional
from dataclasses import dataclass


@dataclass
class TimeoutTask:
    """超时任务
    
    Attributes:
        timeout_id: 超时任务唯一标识
        delay_seconds: 延迟秒数
        callback: 超时回调函数
        callback_args: 回调函数参数
        created_at: 创建时间
        task: asyncio Task 对象
    """
    timeout_id: str
    delay_seconds: float
    callback: Callable
    callback_args: tuple
    created_at: float
    task: Optional[asyncio.Task] = None


class TimeoutManager:
    """超时管理器
    
    统一管理所有超时任务，支持：
    - 异步延迟执行
    - 取消超时
    - 自动清理
    - 异常处理
    
    Example:
        >>> manager = TimeoutManager()
        >>> 
        >>> # 设置超时
        >>> timeout_id = await manager.set_timeout(
        ...     timeout_id="q-1",
        ...     delay_seconds=30.0,
        ...     callback=on_timeout,
        ...     callback_args=("q-1", "timeout")
        ... )
        >>> 
        >>> # 取消超时
        >>> success = manager.cancel_timeout("q-1")
    """
    
    def __init__(self):
        """初始化超时管理器"""
        self._timeouts: Dict[str, TimeoutTask] = {}
        self._running = True
    
    async def set_timeout(
        self,
        timeout_id: str,
        delay_seconds: float,
        callback: Callable,
        callback_args: tuple = ()
    ) -> str:
        """设置超时任务
        
        Args:
            timeout_id: 超时任务唯一标识
            delay_seconds: 延迟秒数
            callback: 超时回调函数（可以是同步或异步）
            callback_args: 回调函数参数
        
        Returns:
            timeout_id: 超时任务ID
        
        Raises:
            ValueError: 如果 timeout_id 已存在
        """
        if timeout_id in self._timeouts:
            raise ValueError(f"Timeout ID '{timeout_id}' already exists")
        
        # 创建超时任务
        timeout_task = TimeoutTask(
            timeout_id=timeout_id,
            delay_seconds=delay_seconds,
            callback=callback,
            callback_args=callback_args,
            created_at=time.time()
        )
        
        # 创建异步任务
        task = asyncio.create_task(
            self._run_timeout(timeout_task)
        )
        timeout_task.task = task
        
        # 保存
        self._timeouts[timeout_id] = timeout_task
        
        return timeout_id
    
    async def _run_timeout(self, timeout_task: TimeoutTask):
        """运行超时任务（内部方法）
        
        Args:
            timeout_task: 超时任务对象
        """
        try:
            # 等待延迟时间
            await asyncio.sleep(timeout_task.delay_seconds)
            
            # 执行回调
            if asyncio.iscoroutinefunction(timeout_task.callback):
                # 异步回调
                await timeout_task.callback(*timeout_task.callback_args)
            else:
                # 同步回调
                timeout_task.callback(*timeout_task.callback_args)
        
        except asyncio.CancelledError:
            # 任务被取消，正常情况
            pass
        
        except Exception as e:
            # 回调执行出错
            print(f"❌ Timeout callback error for '{timeout_task.timeout_id}': {e}")
        
        finally:
            # 清理
            if timeout_task.timeout_id in self._timeouts:
                del self._timeouts[timeout_task.timeout_id]
    
    def cancel_timeout(self, timeout_id: str) -> bool:
        """取消超时任务
        
        Args:
            timeout_id: 超时任务ID
        
        Returns:
            True 如果成功取消，False 如果任务不存在
        """
        timeout_task = self._timeouts.get(timeout_id)
        if not timeout_task:
            return False
        
        # 取消异步任务
        if timeout_task.task and not timeout_task.task.done():
            timeout_task.task.cancel()
        
        # 从字典中移除
        if timeout_id in self._timeouts:
            del self._timeouts[timeout_id]
        
        return True
    
    def has_timeout(self, timeout_id: str) -> bool:
        """检查超时任务是否存在
        
        Args:
            timeout_id: 超时任务ID
        
        Returns:
            True 如果存在，False 否则
        """
        return timeout_id in self._timeouts
    
    def get_remaining_time(self, timeout_id: str) -> Optional[float]:
        """获取超时任务的剩余时间
        
        Args:
            timeout_id: 超时任务ID
        
        Returns:
            剩余秒数，如果任务不存在返回 None
        """
        timeout_task = self._timeouts.get(timeout_id)
        if not timeout_task:
            return None
        
        elapsed = time.time() - timeout_task.created_at
        remaining = timeout_task.delay_seconds - elapsed
        return max(0.0, remaining)
    
    def cancel_all(self):
        """取消所有超时任务"""
        timeout_ids = list(self._timeouts.keys())
        for timeout_id in timeout_ids:
            self.cancel_timeout(timeout_id)
    
    def get_active_count(self) -> int:
        """获取活跃的超时任务数量
        
        Returns:
            活跃任务数量
        """
        return len(self._timeouts)
    
    def get_summary(self) -> Dict[str, Any]:
        """获取超时管理器状态摘要
        
        Returns:
            包含状态信息的字典
        """
        return {
            "active_timeouts": self.get_active_count(),
            "timeout_ids": list(self._timeouts.keys()),
            "running": self._running
        }
    
    async def shutdown(self):
        """关闭超时管理器，取消所有任务"""
        self._running = False
        self.cancel_all()
        
        # 等待所有任务完成
        tasks = [t.task for t in self._timeouts.values() if t.task]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    def __repr__(self) -> str:
        """字符串表示"""
        return f"TimeoutManager(active={self.get_active_count()})"
