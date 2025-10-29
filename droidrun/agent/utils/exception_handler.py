"""
统一异常处理模块
提供一致的异常处理和日志记录策略
"""
import logging
from typing import Any, Callable, Optional
from droidrun.config.constants import ExceptionConstants

logger = logging.getLogger("droidrun")


class ExceptionHandler:
    """统一的异常处理器"""
    
    @staticmethod
    def handle_file_operation_error(
        error: Exception, 
        context: str,
        reraise: bool = False,
        return_value: Any = False
    ) -> Any:
        """
        处理文件操作错误
        
        Args:
            error: 异常对象
            context: 上下文信息
            reraise: 是否重新抛出异常
            return_value: 不抛出异常时返回的值
            
        Returns:
            根据 reraise 参数返回相应值
        """
        logger.warning(f"[{context}] File operation failed: {type(error).__name__}: {error}")
        if reraise:
            raise
        return return_value
    
    @staticmethod
    def handle_data_parsing_error(
        error: Exception,
        context: str,
        reraise: bool = False,
        return_value: Any = None
    ) -> Any:
        """
        处理数据解析错误
        
        Args:
            error: 异常对象
            context: 上下文信息
            reraise: 是否重新抛出异常
            return_value: 不抛出异常时返回的值
            
        Returns:
            根据 reraise 参数返回相应值
        """
        logger.debug(f"[{context}] Data parsing failed: {type(error).__name__}: {error}")
        if reraise:
            raise
        return return_value
    
    @staticmethod
    def handle_runtime_error(
        error: Exception,
        context: str,
        reraise: bool = True,
        return_value: Any = None
    ) -> Any:
        """
        处理运行时错误
        
        Args:
            error: 异常对象
            context: 上下文信息
            reraise: 是否重新抛出异常
            return_value: 不抛出异常时返回的值
            
        Returns:
            根据 reraise 参数返回相应值
        """
        logger.error(f"[{context}] Runtime error: {type(error).__name__}: {error}")
        if reraise:
            raise
        return return_value
    
    @staticmethod
    def handle_network_error(
        error: Exception,
        context: str,
        reraise: bool = False,
        return_value: Any = None
    ) -> Any:
        """
        处理网络错误
        
        Args:
            error: 异常对象
            context: 上下文信息
            reraise: 是否重新抛出异常
            return_value: 不抛出异常时返回的值
            
        Returns:
            根据 reraise 参数返回相应值
        """
        logger.warning(f"[{context}] Network error: {type(error).__name__}: {error}")
        if reraise:
            raise
        return return_value
    
    @staticmethod
    def handle_index_error(
        error: Exception,
        context: str,
        reraise: bool = False,
        return_value: Any = None
    ) -> Any:
        """
        处理索引错误
        
        Args:
            error: 异常对象
            context: 上下文信息
            reraise: 是否重新抛出异常
            return_value: 不抛出异常时返回的值
            
        Returns:
            根据 reraise 参数返回相应值
        """
        logger.warning(f"[{context}] Index error: {type(error).__name__}: {error}")
        if reraise:
            raise
        return return_value


def safe_execute(
    func: Callable,
    error_context: str,
    exception_types: tuple = ExceptionConstants.RUNTIME_EXCEPTIONS,
    log_level: str = "error",
    reraise: bool = True,
    return_on_error: Any = None,
    *args,
    **kwargs
) -> Any:
    """
    安全执行函数，自动处理异常
    
    Args:
        func: 要执行的函数
        error_context: 错误上下文
        exception_types: 要捕获的异常类型
        log_level: 日志级别
        reraise: 是否重新抛出异常
        return_on_error: 出错时返回的值
        *args: 函数位置参数
        **kwargs: 函数关键字参数
        
    Returns:
        函数返回值或 return_on_error
    """
    try:
        return func(*args, **kwargs)
    except exception_types as e:
        log_level_func = getattr(logger, log_level)
        log_level_func(
            f"[{error_context}] {type(e).__name__}: {str(e)}"
        )
        if reraise:
            raise
        return return_on_error


def log_error(context: str, error: Exception, level: str = "error") -> None:
    """
    统一的错误日志格式
    
    Args:
        context: 上下文信息
        error: 异常对象
        level: 日志级别
    """
    message = f"[{context}] {type(error).__name__}: {str(error)}"
    getattr(logger, level)(message)

