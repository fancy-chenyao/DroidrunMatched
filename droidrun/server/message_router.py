"""
消息路由器 - 根据消息类型路由到相应的处理器
"""
import asyncio
import traceback
from typing import Dict, Any, Optional, Callable, Awaitable
from droidrun.agent.utils.logging_utils import LoggingUtils
from droidrun.server.message_protocol import MessageProtocol, MessageType


class MessageRouter:
    """消息路由器 - 负责将消息路由到相应的处理器"""
    
    def __init__(self):
        """初始化消息路由器"""
        # 消息类型 -> 处理器的映射
        self._handlers: Dict[str, Callable[[str, Dict[str, Any]], Awaitable[None]]] = {}
        
        # 默认处理器（用于未注册的消息类型）
        self._default_handler: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None
        
        LoggingUtils.log_info("MessageRouter", "MessageRouter initialized")
    
    def register_handler(
        self,
        message_type: MessageType,
        handler: Callable[[str, Dict[str, Any]], Awaitable[None]]
    ):
        """
        注册消息处理器
        
        Args:
            message_type: 消息类型
            handler: 异步处理函数，签名: async def handler(device_id: str, message: Dict[str, Any]) -> None
        """
        type_str = message_type.value if isinstance(message_type, MessageType) else message_type
        self._handlers[type_str] = handler
        LoggingUtils.log_debug("MessageRouter", "Registered handler for message type: {type}", type=type_str)
    
    def register_default_handler(
        self,
        handler: Callable[[str, Dict[str, Any]], Awaitable[None]]
    ):
        """
        注册默认处理器（处理未注册的消息类型）
        
        Args:
            handler: 异步处理函数
        """
        self._default_handler = handler
        LoggingUtils.log_debug("MessageRouter", "Registered default handler")
    
    async def route(self, device_id: str, message: Dict[str, Any]) -> bool:
        """
        路由消息到相应的处理器（增强错误处理，Phase 3）
        
        Args:
            device_id: 设备ID
            message: 消息字典
            
        Returns:
            bool: 是否成功处理
        """
        message_type = message.get("type")
        
        if not message_type:
            LoggingUtils.log_error("MessageRouter", "Message missing 'type' field from device {device_id}", 
                                 device_id=device_id)
            return False
        
        # 查找处理器
        handler = self._handlers.get(message_type)
        
        if handler:
            try:
                await handler(device_id, message)
                LoggingUtils.log_debug("MessageRouter", "Successfully processed message type {type} from device {device_id}", 
                                     type=message_type, device_id=device_id)
                return True
            except asyncio.CancelledError:
                # 任务被取消，重新抛出
                raise
            except Exception as e:
                LoggingUtils.log_error("MessageRouter", "Error in handler for message type {type} from device {device_id}: {error}", 
                                     type=message_type, device_id=device_id, error=e)
                # 记录详细的错误信息
                LoggingUtils.log_error("MessageRouter", "Traceback: {traceback}", 
                                     traceback=traceback.format_exc())
                return False
        elif self._default_handler:
            # 使用默认处理器
            try:
                await self._default_handler(device_id, message)
                return True
            except asyncio.CancelledError:
                # 任务被取消，重新抛出
                raise
            except Exception as e:
                LoggingUtils.log_error("MessageRouter", "Error in default handler for message type {type} from device {device_id}: {error}", 
                                     type=message_type, device_id=device_id, error=e)
                return False
        else:
            # 没有处理器
            LoggingUtils.log_warning("MessageRouter", "No handler registered for message type {type} from device {device_id}", 
                                   type=message_type, device_id=device_id)
            return False
    
    def unregister_handler(self, message_type: MessageType):
        """
        注销消息处理器
        
        Args:
            message_type: 消息类型
        """
        type_str = message_type.value if isinstance(message_type, MessageType) else message_type
        if type_str in self._handlers:
            del self._handlers[type_str]
            LoggingUtils.log_debug("MessageRouter", "Unregistered handler for message type: {type}", type=type_str)
    
    def get_registered_types(self) -> list[str]:
        """
        获取已注册的消息类型
        
        Returns:
            消息类型列表
        """
        return list(self._handlers.keys())

