"""
统一配置管理 - 分层配置类定义
"""
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
from droidrun.agent.utils.logging_utils import LoggingUtils


@dataclass
class SystemConfig:
    """系统核心配置"""
    debug: bool = False
    log_level: str = "INFO"
    timeout: int = 300
    step_timeout_seconds: int = 60
    default_timeout: int = 300

@dataclass
class MemoryConfig:
    """记忆系统配置"""
    enabled: bool = True
    similarity_threshold: float = 0.85
    perfect_match_threshold: float = 0.999
    storage_dir: str = "experiences"
    max_experiences: int = 1000
    max_similar_experiences_display: int = 3
    experience_quality_threshold: float = 0.7
    fallback_enabled: bool = True
    monitoring_enabled: bool = True
    hot_start_enabled: bool = True
    parameter_adaptation_enabled: bool = True
    max_consecutive_failures: int = 3
    step_timeout: float = 30.0
    max_steps_before_fallback: int = 20

@dataclass
class AgentConfig:
    """Agent配置"""
    max_steps: int = 20
    default_max_steps: int = 20
    max_micro_cold_steps: int = 5
    micro_cold_timeout: int = 60
    reasoning: bool = False
    reflection: bool = False
    vision: bool = False
    save_trajectories: str = "step"

@dataclass
class ToolsConfig:
    """工具配置"""
    # UI相关配置
    default_index: int = -1
    default_x_coordinate: int = 0
    default_y_coordinate: int = 0
    default_swipe_duration: int = 300
    
    # 时间相关配置
    macro_generation_wait_time: float = 0.5
    action_wait_time: float = 0.5
    screenshot_wait_time: float = 1.0
    long_wait_time: float = 2.0

@dataclass
class APIConfig:
    """API配置"""
    api_key: Optional[str] = None
    model: str = "qwen-plus"
    api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    timeout: int = 30
    max_retries: int = 3

@dataclass
class ServerConfig:
    """服务端配置"""
    mode: str = "client"  # "client" | "server"
    server_port: int = 8765
    server_host: str = "0.0.0.0"
    websocket_path: str = "/ws"
    device_id_header: str = "X-Device-ID"
    timeout: int = 30
    heartbeat_interval: int = 30
    max_connections: int = 100

@dataclass
class DroidRunUnifiedConfig:
    """统一配置类"""
    system: SystemConfig
    memory: MemoryConfig
    agent: AgentConfig
    tools: ToolsConfig
    api: APIConfig
    server: ServerConfig
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "system": asdict(self.system),
            "memory": asdict(self.memory),
            "agent": asdict(self.agent),
            "tools": asdict(self.tools),
            "api": asdict(self.api),
            "server": asdict(self.server)
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DroidRunUnifiedConfig':
        """从字典创建配置"""
        return cls(
            system=SystemConfig(**data.get("system", {})),
            memory=MemoryConfig(**data.get("memory", {})),
            agent=AgentConfig(**data.get("agent", {})),
            tools=ToolsConfig(**data.get("tools", {})),
            api=APIConfig(**data.get("api", {})),
            server=ServerConfig(**data.get("server", {}))
        )
    
    @classmethod
    def create_default(cls) -> 'DroidRunUnifiedConfig':
        """创建默认配置"""
        return cls(
            system=SystemConfig(),
            memory=MemoryConfig(),
            agent=AgentConfig(),
            tools=ToolsConfig(),
            api=APIConfig(),
            server=ServerConfig()
        )
    
    def validate(self) -> bool:
        """验证配置的有效性"""
        try:
            # 验证记忆系统配置
            if not 0.0 <= self.memory.similarity_threshold <= 1.0:
                LoggingUtils.log_error("UnifiedConfig", "Invalid similarity_threshold: {threshold}", 
                                     threshold=self.memory.similarity_threshold)
                return False
            
            if not 0.0 <= self.memory.perfect_match_threshold <= 1.0:
                LoggingUtils.log_error("UnifiedConfig", "Invalid perfect_match_threshold: {threshold}", 
                                     threshold=self.memory.perfect_match_threshold)
                return False
            
            if not 0.0 <= self.memory.experience_quality_threshold <= 1.0:
                LoggingUtils.log_error("UnifiedConfig", "Invalid experience_quality_threshold: {threshold}", 
                                     threshold=self.memory.experience_quality_threshold)
                return False
            
            if self.memory.max_experiences <= 0:
                LoggingUtils.log_error("UnifiedConfig", "Invalid max_experiences: {max_exp}", 
                                     max_exp=self.memory.max_experiences)
                return False
            
            # 验证Agent配置
            if self.agent.max_steps <= 0:
                LoggingUtils.log_error("UnifiedConfig", "Invalid max_steps: {steps}", steps=self.agent.max_steps)
                return False
            
            # 验证系统配置
            if self.system.timeout <= 0:
                LoggingUtils.log_error("UnifiedConfig", "Invalid timeout: {timeout}", timeout=self.system.timeout)
                return False
            
            LoggingUtils.log_success("UnifiedConfig", "Unified config validation passed")
            return True
            
        except Exception as e:
            LoggingUtils.log_error("UnifiedConfig", "Config validation error: {error}", error=e)
            return False
    
    def get(self, path: str, default: Any = None) -> Any:
        """获取配置值（支持点分路径）"""
        try:
            keys = path.split('.')
            value = self
            
            for key in keys:
                if hasattr(value, key):
                    value = getattr(value, key)
                else:
                    return default
            
            return value
            
        except Exception as e:
            LoggingUtils.log_warning("UnifiedConfig", "Failed to get config value for path '{path}': {error}", 
                                   path=path, error=e)
            return default
    
    def set(self, path: str, value: Any) -> bool:
        """设置配置值（支持点分路径）"""
        try:
            keys = path.split('.')
            target = self
            
            # 导航到目标对象
            for key in keys[:-1]:
                if hasattr(target, key):
                    target = getattr(target, key)
                else:
                    return False
            
            # 设置值
            setattr(target, keys[-1], value)
            return True
            
        except Exception as e:
            LoggingUtils.log_warning("UnifiedConfig", "Failed to set config value for path '{path}': {error}", 
                                   path=path, error=e)
            return False
