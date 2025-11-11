"""
统一配置管理器 - 主要接口
"""
import os
from typing import Optional, Dict, Any
import logging
from .unified_config import DroidRunUnifiedConfig, SystemConfig, MemoryConfig, AgentConfig, ToolsConfig, APIConfig, ServerConfig
from .loader import ConfigLoader

logger = logging.getLogger("droidrun")

class UnifiedConfigManager:
    """统一配置管理器"""
    
    _instance: Optional['UnifiedConfigManager'] = None
    _initialized: bool = False
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化配置管理器"""
        if not self._initialized:
            self.config = self._load_configuration()
            self._initialized = True
            logger.info("🔧 UnifiedConfigManager initialized")
    
    def _load_configuration(self) -> DroidRunUnifiedConfig:
        """加载配置"""
        try:
            # 1. 创建默认配置
            default_config = DroidRunUnifiedConfig.create_default()
            
            # 2. 加载外部配置
            loader = ConfigLoader()
            external_config = loader.load()
            
            # 3. 合并配置
            merged_dict = self._merge_configurations(default_config.to_dict(), external_config)
            
            # 4. 创建最终配置
            final_config = DroidRunUnifiedConfig.from_dict(merged_dict)
            
            # 5. 验证配置
            if final_config.validate():
                logger.info("✅ Configuration loaded and validated successfully")
                return final_config
            else:
                logger.warning("⚠️ Configuration validation failed, using defaults")
                return default_config
                
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            logger.info("Using default configuration")
            return DroidRunUnifiedConfig.create_default()
    
    def _merge_configurations(self, default_dict: Dict[str, Any], external_dict: Dict[str, Any]) -> Dict[str, Any]:
        """合并配置字典"""
        result = default_dict.copy()
        
        for section, values in external_dict.items():
            if section in result and isinstance(result[section], dict) and isinstance(values, dict):
                result[section].update(values)
            else:
                result[section] = values
        
        return result
    
    def get(self, path: str, default: Any = None) -> Any:
        """获取配置值（支持点分路径）"""
        return self.config.get(path, default)
    
    def set(self, path: str, value: Any) -> bool:
        """设置配置值（支持点分路径）"""
        return self.config.set(path, value)
    
    def get_system_config(self) -> SystemConfig:
        """获取系统配置"""
        return self.config.system
    
    def get_memory_config(self) -> MemoryConfig:
        """获取记忆配置（向后兼容）"""
        return self.config.memory
    
    def get_agent_config(self) -> AgentConfig:
        """获取Agent配置"""
        return self.config.agent
    
    def get_tools_config(self) -> ToolsConfig:
        """获取工具配置"""
        return self.config.tools
    
    def get_api_config(self) -> APIConfig:
        """获取API配置"""
        return self.config.api
    
    def get_server_config(self) -> ServerConfig:
        """获取服务端配置"""
        return self.config.server
    
    def reload(self):
        """重新加载配置"""
        logger.info("🔄 Reloading configuration...")
        self.config = self._load_configuration()
        logger.info("✅ Configuration reloaded")
    
    def save_to_file(self, filepath: str) -> bool:
        """保存配置到文件"""
        try:
            import yaml
            
            config_data = {"droidrun": self.config.to_dict()}
            
            with open(filepath, 'w', encoding='utf-8') as f:
                yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)
            
            logger.info(f"💾 Configuration saved to: {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save configuration to {filepath}: {e}")
            return False
    
    def get_summary(self) -> str:
        """获取配置摘要"""
        return f"""
🔧 DroidRun Configuration Summary
================================
📊 System:
  - Debug: {self.config.system.debug}
  - Log Level: {self.config.system.log_level}
  - Timeout: {self.config.system.timeout}s

🧠 Memory:
  - Enabled: {self.config.memory.enabled}
  - Similarity Threshold: {self.config.memory.similarity_threshold}
  - Storage Dir: {self.config.memory.storage_dir}
  - Max Experiences: {self.config.memory.max_experiences}

🤖 Agent:
  - Max Steps: {self.config.agent.max_steps}
  - Reasoning: {self.config.agent.reasoning}
  - Reflection: {self.config.agent.reflection}
  - Vision: {self.config.agent.vision}

🔧 Tools:
  - Action Wait Time: {self.config.tools.action_wait_time}s
  - Screenshot Wait Time: {self.config.tools.screenshot_wait_time}s

🌐 API:
  - Model: {self.config.api.model}
  - API Base: {self.config.api.api_base}
  - Timeout: {self.config.api.timeout}s

🖥️ Server:
  - Mode: {self.config.server.mode}
  - Host: {self.config.server.server_host}
  - Port: {self.config.server.server_port}
  - WebSocket Path: {self.config.server.websocket_path}
"""

# 全局配置管理器实例
config_manager = UnifiedConfigManager()

def get_config_manager() -> UnifiedConfigManager:
    """获取全局配置管理器实例"""
    return config_manager
