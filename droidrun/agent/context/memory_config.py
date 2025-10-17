"""
记忆系统配置
"""
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
import json
import os
import logging

logger = logging.getLogger("droidrun")

@dataclass
class MemoryConfig:
    """记忆系统配置类"""
    enabled: bool = True
    similarity_threshold: float = 0.8
    storage_dir: str = "experiences"
    max_experiences: int = 1000
    llm_model: Optional[str] = None
    fallback_enabled: bool = True
    monitoring_enabled: bool = True
    hot_start_enabled: bool = True
    parameter_adaptation_enabled: bool = True
    experience_quality_threshold: float = 0.7
    max_consecutive_failures: int = 3
    step_timeout: float = 30.0
    max_steps_before_fallback: int = 20
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'MemoryConfig':
        """从字典创建配置"""
        return cls(**config_dict)
    
    def save_to_file(self, filepath: str):
        """保存配置到文件"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            logger.info(f"💾 Memory config saved to: {filepath}")
        except Exception as e:
            logger.error(f"Failed to save memory config: {e}")
            raise
    
    @classmethod
    def load_from_file(cls, filepath: str) -> 'MemoryConfig':
        """从文件加载配置"""
        try:
            if not os.path.exists(filepath):
                logger.info(f"Config file not found: {filepath}, using default config")
                return cls()
            
            with open(filepath, 'r', encoding='utf-8') as f:
                config_dict = json.load(f)
            return cls.from_dict(config_dict)
        except Exception as e:
            logger.warning(f"Failed to load memory config from {filepath}: {e}")
            return cls()
    
    def validate(self) -> bool:
        """验证配置的有效性"""
        try:
            # 检查数值范围
            if not 0.0 <= self.similarity_threshold <= 1.0:
                logger.error(f"Invalid similarity_threshold: {self.similarity_threshold}")
                return False
            
            if not 0.0 <= self.experience_quality_threshold <= 1.0:
                logger.error(f"Invalid experience_quality_threshold: {self.experience_quality_threshold}")
                return False
            
            if self.max_experiences <= 0:
                logger.error(f"Invalid max_experiences: {self.max_experiences}")
                return False
            
            if self.max_consecutive_failures <= 0:
                logger.error(f"Invalid max_consecutive_failures: {self.max_consecutive_failures}")
                return False
            
            if self.step_timeout <= 0:
                logger.error(f"Invalid step_timeout: {self.step_timeout}")
                return False
            
            if self.max_steps_before_fallback <= 0:
                logger.error(f"Invalid max_steps_before_fallback: {self.max_steps_before_fallback}")
                return False
            
            # 检查存储目录
            if self.storage_dir:
                try:
                    os.makedirs(self.storage_dir, exist_ok=True)
                except Exception as e:
                    logger.error(f"Cannot create storage directory {self.storage_dir}: {e}")
                    return False
            
            logger.info("✅ Memory config validation passed")
            return True
            
        except Exception as e:
            logger.error(f"Config validation error: {e}")
            return False
    
    def get_summary(self) -> str:
        """获取配置摘要"""
        return f"""
Memory System Configuration:
- Enabled: {self.enabled}
- Similarity Threshold: {self.similarity_threshold}
- Storage Directory: {self.storage_dir}
- Max Experiences: {self.max_experiences}
- Hot Start: {self.hot_start_enabled}
- Parameter Adaptation: {self.parameter_adaptation_enabled}
- Monitoring: {self.monitoring_enabled}
- Fallback: {self.fallback_enabled}
- Quality Threshold: {self.experience_quality_threshold}
- Max Consecutive Failures: {self.max_consecutive_failures}
- Step Timeout: {self.step_timeout}s
- Max Steps Before Fallback: {self.max_steps_before_fallback}
"""

# 默认配置
DEFAULT_MEMORY_CONFIG = MemoryConfig()

# 配置工厂函数
def create_memory_config(
    enabled: bool = True,
    similarity_threshold: float = 0.8,
    storage_dir: str = "experiences",
    max_experiences: int = 1000,
    llm_model: Optional[str] = None,
    fallback_enabled: bool = True,
    monitoring_enabled: bool = True,
    hot_start_enabled: bool = True,
    parameter_adaptation_enabled: bool = True,
    experience_quality_threshold: float = 0.7,
    max_consecutive_failures: int = 3,
    step_timeout: float = 30.0,
    max_steps_before_fallback: int = 20
) -> MemoryConfig:
    """创建记忆配置"""
    config = MemoryConfig(
        enabled=enabled,
        similarity_threshold=similarity_threshold,
        storage_dir=storage_dir,
        max_experiences=max_experiences,
        llm_model=llm_model,
        fallback_enabled=fallback_enabled,
        monitoring_enabled=monitoring_enabled,
        hot_start_enabled=hot_start_enabled,
        parameter_adaptation_enabled=parameter_adaptation_enabled,
        experience_quality_threshold=experience_quality_threshold,
        max_consecutive_failures=max_consecutive_failures,
        step_timeout=step_timeout,
        max_steps_before_fallback=max_steps_before_fallback
    )
    
    if config.validate():
        logger.info("✅ Memory config created successfully")
        return config
    else:
        logger.error("❌ Invalid memory config, using defaults")
        return DEFAULT_MEMORY_CONFIG

