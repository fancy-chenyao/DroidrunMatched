"""
统一配置管理 - 配置加载器
"""
import os
import yaml
import toml
import json
from typing import Dict, Any
from droidrun.agent.utils.logging_utils import LoggingUtils


class ConfigLoader:
    """配置加载器"""
    
    def __init__(self):
        self.env_mapping = {
            # API配置
            'ALIYUN_API_KEY': 'api.api_key',
            'ALIYUN_MODEL': 'api.model',
            'ALIYUN_API_BASE': 'api.api_base',
            
            # 记忆系统配置
            'MEMORY_SIMILARITY_THRESHOLD': 'memory.similarity_threshold',
            'MEMORY_STORAGE_DIR': 'memory.storage_dir',
            'MEMORY_MAX_EXPERIENCES': 'memory.max_experiences',
            'MEMORY_ENABLED': 'memory.enabled',
            
            # Agent配置
            'MAX_STEPS': 'agent.max_steps',
            'DEFAULT_MAX_STEPS': 'agent.default_max_steps',
            'REASONING': 'agent.reasoning',
            'REFLECTION': 'agent.reflection',
            'VISION': 'agent.vision',
            
            # 系统配置
            'DEBUG_MODE': 'system.debug',
            'LOG_LEVEL': 'system.log_level',
            'TIMEOUT': 'system.timeout',
            
            # 工具配置
            'ACTION_WAIT_TIME': 'tools.action_wait_time',
            'SCREENSHOT_WAIT_TIME': 'tools.screenshot_wait_time',
            
            # 服务端配置
            'SERVER_MODE': 'server.mode',
            'SERVER_PORT': 'server.server_port',
            'SERVER_HOST': 'server.server_host',
            'WEBSOCKET_PATH': 'server.websocket_path',
            'HEARTBEAT_INTERVAL': 'server.heartbeat_interval',
        }
    
    def _load_env_vars(self) -> Dict[str, Any]:
        """加载环境变量"""
        env_config = {}
        
        for env_var, config_path in self.env_mapping.items():
            value = os.getenv(env_var)
            if value is not None:
                # 类型转换
                converted_value = self._convert_env_value(value)
                self._set_nested_value(env_config, config_path, converted_value)
                LoggingUtils.log_debug("ConfigLoader", "Loaded env var {env_var}={value} -> {config_path}={converted_value}", 
                                     env_var=env_var, value=value, config_path=config_path, converted_value=converted_value)
        
        return env_config
    
    def _convert_env_value(self, value: str) -> Any:
        """转换环境变量值的类型"""
        # 布尔值转换
        if value.lower() in ('true', 'false'):
            return value.lower() == 'true'
        
        # 数字转换
        try:
            if '.' in value:
                return float(value)
            else:
                return int(value)
        except ValueError:
            pass
        
        # 字符串
        return value
    
    def _set_nested_value(self, config: Dict[str, Any], path: str, value: Any):
        """设置嵌套字典的值"""
        keys = path.split('.')
        current = config
        
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        
        current[keys[-1]] = value
    
    def _load_file_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        config_files = [
            "droidrun.yaml",
            "droidrun.yml", 
            "droidrun.toml",
            "config.yaml",
            "config.yml",
            "config.toml",
            ".droidrun.yaml",
            ".droidrun.yml",
            ".droidrun.toml"
        ]
        
        for config_file in config_files:
            if os.path.exists(config_file):
                try:
                    LoggingUtils.log_info("ConfigLoader", "Loading config from: {file}", file=config_file)
                    return self._parse_config_file(config_file)
                except Exception as e:
                    LoggingUtils.log_warning("ConfigLoader", "Failed to load config from {file}: {error}", 
                                           file=config_file, error=e)
                    continue
        
        LoggingUtils.log_info("ConfigLoader", "No config file found, using defaults")
        return {}
    
    def _parse_config_file(self, filepath: str) -> Dict[str, Any]:
        """解析配置文件"""
        with open(filepath, 'r', encoding='utf-8') as f:
            if filepath.endswith(('.yaml', '.yml')):
                data = yaml.safe_load(f)
            elif filepath.endswith('.toml'):
                data = toml.load(f)
            else:
                # 默认尝试JSON
                data = json.load(f)
        
        # 提取droidrun配置部分
        if isinstance(data, dict) and 'droidrun' in data:
            return data['droidrun']
        elif isinstance(data, dict):
            return data
        else:
            return {}
    
    def _deep_update(self, base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
        """深度更新字典"""
        result = base.copy()
        
        for key, value in update.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_update(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def load(self) -> Dict[str, Any]:
        """加载并合并配置"""
        # 1. 加载环境变量
        env_config = self._load_env_vars()
        
        # 2. 加载配置文件
        file_config = self._load_file_config()
        
        # 3. 合并配置（环境变量优先）
        merged_config = self._deep_update(file_config, env_config)
        
        LoggingUtils.log_info("ConfigLoader", "Configuration loaded: {env_count} env vars, {file_count} file configs", 
                             env_count=len(env_config), file_count=len(file_config))
        return merged_config
