"""
DroidRun 配置常量
统一管理项目中的代码级常量（开发者使用的固定常量）

注意：
- 用户可配置的运行时参数应使用统一配置系统（unified_config.py）
- 这里只保留代码级的固定常量，如异常类型定义
"""

# 异常处理常量
class ExceptionConstants:
    """异常处理相关常量 - 用于异常捕获和分类"""
    
    # 文件操作异常
    FILE_OPERATION_EXCEPTIONS = (OSError, IOError, PermissionError)
    
    # 网络操作异常
    NETWORK_EXCEPTIONS = (ConnectionError, TimeoutError)
    
    # 数据解析异常
    DATA_PARSING_EXCEPTIONS = (ValueError, TypeError, AttributeError, KeyError)
    
    # 运行时异常
    RUNTIME_EXCEPTIONS = (RuntimeError, ValueError, TypeError, AttributeError)
    
    # 索引相关异常
    INDEX_EXCEPTIONS = (IndexError, TypeError, AttributeError)
    
    # 通用异常（谨慎使用）
    GENERAL_EXCEPTIONS = Exception