"""任务状态定义

定义任务执行状态和恢复策略
"""

from enum import Enum


class TaskState(Enum):
    """任务状态枚举"""
    
    INITIALIZED = "initialized"  # 已初始化，未开始
    RUNNING = "running"          # 正在运行
    WAITING_USER = "waiting_user"  # 等待用户输入
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败
    CANCELLED = "cancelled"      # 已取消


class ResumeStrategy(Enum):
    """恢复策略
    
    定义不同类型的用户交互场景下，如何应用用户回答
    """
    
    REPLACE_PARAM = "replace_param"
    """替换参数：直接用用户回答替换原参数（如修改输入文本）"""
    
    ELEMENT_SELECTION = "element_select"
    """元素选择：用户选择了某个UI元素（如从多个选项中选择）"""
    
    CONFIRM_CANCEL = "confirm_cancel"
    """确认/取消：用户确认或取消操作（如关键操作确认）"""
    
    PARAMETER_FILL = "parameter_fill"
    """参数填充：用户填充缺失的参数（如补充缺失的日期）"""
