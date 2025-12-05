"""交互式执行模块

提供任务暂停、用户询问、恢复执行等交互能力
"""

# Phase 1: 基础数据结构
from .task_state import TaskState, ResumeStrategy
from .resume_context import ResumeContext, UserCancelledError
from .task_context import TaskExecutionContext

# Phase 2: 交互管理器
from .timeout_manager import TimeoutManager, TimeoutTask
from .manager import InteractionManager, PendingQuestion

# Phase 4: 生命周期管理器
from .lifecycle_manager import LifecycleManager

# Phase 5: WebSocket 消息处理
from .websocket_handler import InteractionWebSocketHandler

__all__ = [
    # Phase 1
    "TaskState",
    "ResumeStrategy",
    "ResumeContext",
    "UserCancelledError",
    "TaskExecutionContext",
    # Phase 2
    "TimeoutManager",
    "TimeoutTask",
    "InteractionManager",
    "PendingQuestion",
    # Phase 4
    "LifecycleManager",
    # Phase 5
    "InteractionWebSocketHandler",
]
