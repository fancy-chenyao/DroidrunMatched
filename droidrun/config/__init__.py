"""
DroidRun 配置管理模块

配置管理分层：
- 统一配置系统 (unified_config.py): 用户可配置的运行时参数
- 常量系统 (constants.py): 开发者使用的代码级固定常量（如异常类型）
"""

from .unified_manager import UnifiedConfigManager, get_config_manager
from .unified_config import DroidRunUnifiedConfig, SystemConfig, MemoryConfig, AgentConfig, ToolsConfig, APIConfig, ServerConfig
from .constants import ExceptionConstants

# 导出主要接口
__all__ = [
    # 统一配置系统接口
    'UnifiedConfigManager',
    'get_config_manager', 
    'DroidRunUnifiedConfig',
    'SystemConfig',
    'MemoryConfig', 
    'AgentConfig',
    'ToolsConfig',
    'APIConfig',
    'ServerConfig',
    # 代码级常量
    'ExceptionConstants'
]
