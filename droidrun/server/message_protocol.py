"""
消息协议定义 - 定义 WebSocket 通信的消息格式和类型
"""
import json
import time
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum


class MessageType(Enum):
    """消息类型枚举"""
    # 连接相关
    SERVER_READY = "server_ready"
    CLIENT_CONNECTED = "client_connected"
    
    # 心跳相关
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"
    
    # 命令相关
    COMMAND = "command"
    COMMAND_RESPONSE = "command_response"
    
    # 错误相关
    ERROR = "error"
    INVALID_MESSAGE = "invalid_message"
    
    # 状态相关
    STATUS_UPDATE = "status_update"
    NOTIFICATION = "notification"


class MessageProtocol:
    """消息协议工具类"""
    
    # 协议版本
    PROTOCOL_VERSION = "1.0"
    
    @staticmethod
    def create_message(
        message_type: MessageType,
        data: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        error: Optional[str] = None,
        device_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        创建标准消息
        
        Args:
            message_type: 消息类型
            data: 消息数据（可选）
            request_id: 请求ID（用于匹配请求-响应）
            error: 错误信息（可选）
            device_id: 设备ID（可选）
            **kwargs: 其他字段
            
        Returns:
            标准化的消息字典
        """
        message = {
            "version": MessageProtocol.PROTOCOL_VERSION,
            "type": message_type.value if isinstance(message_type, MessageType) else message_type,
            "timestamp": datetime.now().isoformat(),
        }
        
        # 添加请求ID（如果提供）
        if request_id:
            message["request_id"] = request_id
        
        # 添加设备ID（如果提供）
        if device_id:
            message["device_id"] = device_id
        
        # 添加数据或错误
        if error:
            message["error"] = error
            message["status"] = "error"
        else:
            message["status"] = "success"
            if data is not None:
                message["data"] = data
        
        # 添加其他字段
        message.update(kwargs)
        
        return message
    
    @staticmethod
    def create_command_message(
        command: str,
        params: Dict[str, Any],
        request_id: str,
        device_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        创建命令消息
        
        Args:
            command: 命令名称
            params: 命令参数
            request_id: 请求ID
            device_id: 设备ID（可选）
            
        Returns:
            命令消息字典
        """
        return MessageProtocol.create_message(
            MessageType.COMMAND,
            data={
                "command": command,
                "params": params
            },
            request_id=request_id,
            device_id=device_id
        )
    
    @staticmethod
    def create_command_response(
        request_id: str,
        status: str = "success",
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        device_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        创建命令响应消息
        
        Args:
            request_id: 原始请求ID
            status: 响应状态 ("success" 或 "error")
            data: 响应数据（成功时）
            error: 错误信息（失败时）
            device_id: 设备ID（可选）
            
        Returns:
            命令响应消息字典
        """
        message = MessageProtocol.create_message(
            MessageType.COMMAND_RESPONSE,
            request_id=request_id,
            device_id=device_id
        )
        
        # 覆盖状态
        message["status"] = status
        
        if status == "error":
            message["error"] = error
        else:
            if data is not None:
                message["data"] = data
        
        return message
    
    @staticmethod
    def create_heartbeat_message(device_id: Optional[str] = None) -> Dict[str, Any]:
        """
        创建心跳消息
        
        Args:
            device_id: 设备ID（可选）
            
        Returns:
            心跳消息字典
        """
        return MessageProtocol.create_message(
            MessageType.HEARTBEAT,
            device_id=device_id
        )
    
    @staticmethod
    def create_heartbeat_ack(device_id: Optional[str] = None) -> Dict[str, Any]:
        """
        创建心跳确认消息
        
        Args:
            device_id: 设备ID（可选）
            
        Returns:
            心跳确认消息字典
        """
        return MessageProtocol.create_message(
            MessageType.HEARTBEAT_ACK,
            device_id=device_id
        )
    
    @staticmethod
    def create_error_message(
        error: str,
        request_id: Optional[str] = None,
        device_id: Optional[str] = None,
        error_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        创建错误消息
        
        Args:
            error: 错误描述
            request_id: 请求ID（如果与某个请求相关）
            device_id: 设备ID（可选）
            error_code: 错误代码（可选）
            
        Returns:
            错误消息字典
        """
        message = MessageProtocol.create_message(
            MessageType.ERROR,
            error=error,
            request_id=request_id,
            device_id=device_id
        )
        
        if error_code:
            message["error_code"] = error_code
        
        return message
    
    @staticmethod
    def validate_message(message: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        验证消息格式
        
        Args:
            message: 消息字典
            
        Returns:
            (是否有效, 错误信息)
        """
        # 必需字段检查
        if "type" not in message:
            return False, "Missing 'type' field"
        
        # 版本检查（可选，但建议包含）
        if "version" in message:
            version = message["version"]
            # 可以在这里添加版本兼容性检查
            if not isinstance(version, str):
                return False, "Invalid 'version' field type"
        
        # 时间戳检查（可选）
        if "timestamp" in message:
            timestamp = message["timestamp"]
            if not isinstance(timestamp, str):
                return False, "Invalid 'timestamp' field type"
        
        # 根据消息类型进行特定验证
        message_type = message.get("type")
        
        # 命令消息必须包含 command 和 request_id
        if message_type == MessageType.COMMAND.value:
            if "request_id" not in message:
                return False, "Command message missing 'request_id'"
            if "data" in message:
                data = message["data"]
                if not isinstance(data, dict) or "command" not in data:
                    return False, "Command message missing 'command' in data"
        
        # 命令响应必须包含 request_id
        if message_type == MessageType.COMMAND_RESPONSE.value:
            if "request_id" not in message:
                return False, "Command response missing 'request_id'"
        
        return True, None
    
    @staticmethod
    def parse_message(message_str: str) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        解析消息字符串
        
        Args:
            message_str: JSON 字符串
            
        Returns:
            (消息字典, 错误信息)
        """
        try:
            message = json.loads(message_str)
            if not isinstance(message, dict):
                return None, "Message is not a dictionary"
            
            # 验证消息格式
            is_valid, error = MessageProtocol.validate_message(message)
            if not is_valid:
                return None, error
            
            return message, None
        except json.JSONDecodeError as e:
            return None, f"Invalid JSON: {str(e)}"
        except Exception as e:
            return None, f"Parse error: {str(e)}"

