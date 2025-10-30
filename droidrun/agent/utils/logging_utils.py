"""
统一日志记录工具
提供一致的日志格式和级别管理
"""
import logging
from typing import Any, Optional
from functools import wraps

logger = logging.getLogger("droidrun")


class LoggingUtils:
    """统一日志记录工具类"""
    
    @staticmethod
    def log_info(context: str, message: str, **kwargs) -> None:
        """
        统一的信息日志格式
        
        Args:
            context: 上下文信息（模块/功能）
            message: 日志消息
            **kwargs: 额外的格式化参数
        """
        if kwargs:
            formatted_message = f"[{context}] {message}".format(**kwargs)
        else:
            formatted_message = f"[{context}] {message}"
        logger.info(formatted_message)
    
    @staticmethod
    def log_warning(context: str, message: str, **kwargs) -> None:
        """
        统一的警告日志格式
        
        Args:
            context: 上下文信息（模块/功能）
            message: 日志消息
            **kwargs: 额外的格式化参数
        """
        if kwargs:
            formatted_message = f"[{context}] {message}".format(**kwargs)
        else:
            formatted_message = f"[{context}] {message}"
        logger.warning(formatted_message)
    
    @staticmethod
    def log_error(context: str, message: str, **kwargs) -> None:
        """
        统一的错误日志格式
        
        Args:
            context: 上下文信息（模块/功能）
            message: 日志消息
            **kwargs: 额外的格式化参数
        """
        if kwargs:
            formatted_message = f"[{context}] {message}".format(**kwargs)
        else:
            formatted_message = f"[{context}] {message}"
        logger.error(formatted_message)
    
    @staticmethod
    def log_debug(context: str, message: str, **kwargs) -> None:
        """
        统一的调试日志格式
        
        Args:
            context: 上下文信息（模块/功能）
            message: 日志消息
            **kwargs: 额外的格式化参数
        """
        if kwargs:
            formatted_message = f"[{context}] {message}".format(**kwargs)
        else:
            formatted_message = f"[{context}] {message}"
        logger.debug(formatted_message)
    
    @staticmethod
    def log_success(context: str, message: str, **kwargs) -> None:
        """
        统一的成功日志格式（使用info级别）
        
        Args:
            context: 上下文信息（模块/功能）
            message: 日志消息
            **kwargs: 额外的格式化参数
        """
        if kwargs:
            formatted_message = f"[{context}] ✅ {message}".format(**kwargs)
        else:
            formatted_message = f"[{context}] ✅ {message}"
        logger.info(formatted_message)
    
    @staticmethod
    def log_progress(context: str, message: str, **kwargs) -> None:
        """
        统一的进度日志格式（使用info级别）
        
        Args:
            context: 上下文信息（模块/功能）
            message: 日志消息
            **kwargs: 额外的格式化参数
        """
        if kwargs:
            formatted_message = f"[{context}] 🔄 {message}".format(**kwargs)
        else:
            formatted_message = f"[{context}] 🔄 {message}"
        logger.info(formatted_message)


def log_function_call(context: str, level: str = "debug"):
    """
    函数调用日志装饰器
    
    Args:
        context: 上下文信息
        level: 日志级别
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            log_func = getattr(LoggingUtils, f"log_{level}")
            log_func(context, f"Calling {func.__name__}")
            try:
                result = func(*args, **kwargs)
                log_func(context, f"Completed {func.__name__}")
                return result
            except Exception as e:
                LoggingUtils.log_error(context, f"Failed {func.__name__}: {e}")
                raise
        return wrapper
    return decorator


def log_execution_time(context: str, level: str = "debug"):
    """
    执行时间日志装饰器
    
    Args:
        context: 上下文信息
        level: 日志级别
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            import time
            start_time = time.time()
            log_func = getattr(LoggingUtils, f"log_{level}")
            log_func(context, f"Starting {func.__name__}")
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                log_func(context, f"Completed {func.__name__} in {execution_time:.2f}s")
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                LoggingUtils.log_error(context, f"Failed {func.__name__} after {execution_time:.2f}s: {e}")
                raise
        return wrapper
    return decorator


# 便捷函数
def log_info(context: str, message: str, **kwargs) -> None:
    """便捷的信息日志函数"""
    LoggingUtils.log_info(context, message, **kwargs)


def log_warning(context: str, message: str, **kwargs) -> None:
    """便捷的警告日志函数"""
    LoggingUtils.log_warning(context, message, **kwargs)


def log_error(context: str, message: str, **kwargs) -> None:
    """便捷的错误日志函数"""
    LoggingUtils.log_error(context, message, **kwargs)


def log_debug(context: str, message: str, **kwargs) -> None:
    """便捷的调试日志函数"""
    LoggingUtils.log_debug(context, message, **kwargs)


def log_success(context: str, message: str, **kwargs) -> None:
    """便捷的成功日志函数"""
    LoggingUtils.log_success(context, message, **kwargs)


def log_progress(context: str, message: str, **kwargs) -> None:
    """便捷的进度日志函数"""
    LoggingUtils.log_progress(context, message, **kwargs)
