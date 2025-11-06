"""
WebSocket 服务器 - 接收 APP 端连接并提供设备控制服务
"""
import asyncio
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from droidrun.agent.utils.logging_utils import LoggingUtils
from droidrun.server.session_manager import SessionManager
from droidrun.server.message_protocol import MessageProtocol, MessageType
from droidrun.server.message_router import MessageRouter

logger = logging.getLogger("droidrun.server")

# 全局服务器实例（用于同一进程内的服务器共享）
_global_server: Optional['WebSocketServer'] = None


def set_global_server(server: 'WebSocketServer'):
    """
    设置全局服务器实例（用于同一进程内的服务器共享）
    
    Args:
        server: WebSocketServer 实例
    """
    global _global_server
    _global_server = server
    LoggingUtils.log_debug("WebSocketServer", "Global server instance registered")


def get_global_server() -> Optional['WebSocketServer']:
    """
    获取全局服务器实例（用于同一进程内的服务器访问）
    
    Returns:
        WebSocketServer 实例或 None
    """
    return _global_server


class WebSocketServer:
    """WebSocket 服务器类"""
    
    def __init__(self, config_manager, host: str = "0.0.0.0", port: int = 8765, 
                 websocket_path: str = "/ws", heartbeat_interval: int = 30):
        """
        初始化 WebSocket 服务器
        
        Args:
            config_manager: 配置管理器实例
            host: 监听地址
            port: 监听端口
            websocket_path: WebSocket 路径
            heartbeat_interval: 心跳间隔（秒）
        """
        self.config_manager = config_manager
        self.host = host
        self.port = port
        self.websocket_path = websocket_path
        self.heartbeat_interval = heartbeat_interval
        
        self.session_manager = SessionManager(heartbeat_timeout=heartbeat_interval * 2)
        self.server = None
        self.is_running = False
        self._cleanup_task = None
        # 存储请求头信息（用于设备ID提取）
        self._request_headers_cache = {}
        # 设备ID -> WebSocketTools 实例的映射（用于响应处理）
        self._device_tools_map: Dict[str, Any] = {}
        
        # 初始化消息路由器（Phase 3）
        self.message_router = MessageRouter()
        self._setup_message_handlers()
        
        # 注册到全局（用于同一进程内的访问）
        set_global_server(self)
        
        LoggingUtils.log_info("WebSocketServer", "WebSocketServer initialized (host={host}, port={port}, path={path})", 
                             host=host, port=port, path=websocket_path)
    
    async def _handle_client(self, websocket, path: str = None):
        """
        处理客户端连接
        
        Args:
            websocket: WebSocket 连接对象
            path: 连接路径（从 websockets.serve 传入）
        """
        device_id = None
        try:
            # 获取客户端地址
            try:
                remote_addr = websocket.remote_address
                client_address = f"{remote_addr[0]}:{remote_addr[1]}"
            except (AttributeError, TypeError):
                client_address = "unknown"
            
            # 获取路径
            if path is None:
                path = getattr(websocket, 'path', self.websocket_path)
            
            LoggingUtils.log_info("WebSocketServer", "New client connected from {address}, path: {path}", 
                                address=client_address, path=path)
            
            # 从查询参数或首部获取设备ID（headers已在_process_request中保存）
            device_id = await self._extract_device_id(websocket, path)
            if not device_id:
                LoggingUtils.log_warning("WebSocketServer", "No device ID provided, rejecting connection from {address}", 
                                       address=client_address)
                await websocket.close(code=4001, reason="Device ID required")
                return
            
            # 注册会话
            await self.session_manager.register_session(device_id, websocket)
            LoggingUtils.log_info("WebSocketServer", "Device {device_id} connected from {address}", 
                                device_id=device_id, address=client_address)
            
            # 发送欢迎消息
            await self._send_welcome_message(websocket, device_id)
            
            # 消息循环
            async for message in websocket:
                try:
                    await self._handle_message(device_id, message)
                except Exception as e:
                    LoggingUtils.log_error("WebSocketServer", "Error handling message from device {device_id}: {error}", 
                                         device_id=device_id, error=e)
                    break
            
        except asyncio.CancelledError:
            LoggingUtils.log_info("WebSocketServer", "Connection cancelled for device {device_id}", device_id=device_id)
        except Exception as e:
            LoggingUtils.log_error("WebSocketServer", "Connection error for device {device_id}: {error}", 
                                 device_id=device_id, error=e)
        finally:
            # 清理会话
            if device_id:
                await self.session_manager.unregister_session(device_id)
                LoggingUtils.log_info("WebSocketServer", "Device {device_id} disconnected", device_id=device_id)
    
    async def _process_request(self, path, request_headers):
        """
        处理WebSocket请求，验证路径并缓存请求头
        
        Args:
            path: 请求路径
            request_headers: 请求头
            
        Returns:
            None 如果路径匹配，否则返回HTTP响应
        """
        # 验证路径
        if path == self.websocket_path or path.startswith(self.websocket_path):
            # 缓存请求头（用于后续设备ID提取）
            # 使用路径作为临时key，后续连接建立时会匹配
            self._request_headers_cache[path] = request_headers
            return None  # 允许连接
        else:
            from websockets.http import Response
            return Response(404, [], b"Path not found")
    
    async def _extract_device_id(self, websocket, path: str) -> Optional[str]:
        """
        从连接中提取设备ID
        
        Args:
            websocket: WebSocket 连接对象
            path: 连接路径
            
        Returns:
            设备ID或None
        """
        # 方法1: 从查询参数中获取 (例如: /ws?device_id=xxx)
        if "?" in path:
            query_string = path.split("?")[1]
            params = {}
            for param in query_string.split("&"):
                if "=" in param:
                    key, value = param.split("=", 1)
                    params[key] = value
            if "device_id" in params:
                device_id = params["device_id"]
                # 清理缓存
                self._request_headers_cache.pop(path, None)
                return device_id
        
        # 方法2: 从请求头中获取（从缓存中读取）
        if path in self._request_headers_cache:
            request_headers = self._request_headers_cache[path]
            # 查找设备ID头（不区分大小写）
            device_id_header = self.config_manager.get("server.device_id_header", "X-Device-ID")
            for key, value in request_headers.items():
                if key.lower() == device_id_header.lower():
                    device_id = value
                    # 清理缓存
                    self._request_headers_cache.pop(path, None)
                    return device_id
            # 清理缓存（即使没找到）
            self._request_headers_cache.pop(path, None)
        
        # 方法3: 从第一个消息中获取（如果APP端通过消息发送设备ID）
        # Phase 1: 暂时返回None，Phase 2会实现
        # 为了支持Phase 1的完整性，这里可以返回一个临时ID或等待第一个消息
        # 但为了简化，Phase 1要求设备ID必须通过方法1或2提供
        
        return None
    
    def _setup_message_handlers(self):
        """设置消息处理器（Phase 3）"""
        # 注册心跳处理器
        self.message_router.register_handler(
            MessageType.HEARTBEAT,
            self._handle_heartbeat
        )
        
        # 注册命令响应处理器
        self.message_router.register_handler(
            MessageType.COMMAND_RESPONSE,
            self._handle_command_response_async
        )
        
        # 注册默认处理器（处理未知消息类型）
        self.message_router.register_default_handler(
            self._handle_unknown_message
        )
        
        LoggingUtils.log_info("MessageRouter", "Message handlers registered")
    
    async def _send_welcome_message(self, websocket, device_id: str):
        """发送欢迎消息（使用标准协议）"""
        welcome = MessageProtocol.create_message(
            MessageType.SERVER_READY,
            data={
                "message": "WebSocket server connected",
                "server_version": MessageProtocol.PROTOCOL_VERSION
            },
            device_id=device_id
        )
        try:
            await websocket.send(json.dumps(welcome))
        except Exception as e:
            LoggingUtils.log_error("WebSocketServer", "Failed to send welcome message: {error}", error=e)
    
    async def _handle_message(self, device_id: str, message):
        """
        处理来自客户端的消息（使用消息协议和路由器，Phase 3）
        
        Args:
            device_id: 设备ID
            message: 消息内容（字符串或字节）
        """
        try:
            # 解析消息
            if isinstance(message, bytes):
                message_str = message.decode('utf-8')
            else:
                message_str = message
            
            # 使用消息协议解析（Phase 3）
            parsed_message, parse_error = MessageProtocol.parse_message(message_str)
            
            if parse_error:
                LoggingUtils.log_error("WebSocketServer", "Failed to parse message from device {device_id}: {error}", 
                                     device_id=device_id, error=parse_error)
                # 发送错误响应
                error_response = MessageProtocol.create_error_message(
                    error=parse_error,
                    device_id=device_id,
                    error_code="INVALID_MESSAGE"
                )
                await self.session_manager.send_to_device(device_id, error_response)
                return
            
            # 使用路由器处理消息（Phase 3）
            await self.message_router.route(device_id, parsed_message)
            
        except Exception as e:
            LoggingUtils.log_error("WebSocketServer", "Error processing message from device {device_id}: {error}", 
                                 device_id=device_id, error=e)
            # 发送错误响应
            try:
                error_response = MessageProtocol.create_error_message(
                    error=f"Internal server error: {str(e)}",
                    device_id=device_id,
                    error_code="INTERNAL_ERROR"
                )
                await self.session_manager.send_to_device(device_id, error_response)
            except Exception:
                pass  # 如果发送错误响应也失败，忽略
    
    async def _handle_heartbeat(self, device_id: str, message: Dict[str, Any]):
        """
        处理心跳消息（Phase 3）
        
        Args:
            device_id: 设备ID
            message: 心跳消息
        """
        await self.session_manager.update_heartbeat(device_id)
        
        # 发送心跳确认（使用标准协议）
        ack_message = MessageProtocol.create_heartbeat_ack(device_id=device_id)
        await self.session_manager.send_to_device(device_id, ack_message)
        
        LoggingUtils.log_debug("WebSocketServer", "Heartbeat received from device {device_id}", device_id=device_id)
    
    async def _handle_command_response_async(self, device_id: str, message: Dict[str, Any]):
        """
        处理命令响应消息（Phase 3 - 异步版本，用于路由器）
        
        Args:
            device_id: 设备ID
            message: 命令响应消息
        """
        # 转发响应到对应的 WebSocketTools 实例
        if device_id in self._device_tools_map:
            tools_instance = self._device_tools_map[device_id]
            if hasattr(tools_instance, '_handle_response'):
                # 调用 _handle_response（它会处理异步调度）
                tools_instance._handle_response(message)
            else:
                LoggingUtils.log_warning("WebSocketServer", "WebSocketTools instance for device {device_id} has no _handle_response method", 
                                       device_id=device_id)
        else:
            LoggingUtils.log_debug("WebSocketServer", "No WebSocketTools instance registered for device {device_id}", 
                                 device_id=device_id)
    
    async def _handle_unknown_message(self, device_id: str, message: Dict[str, Any]):
        """
        处理未知类型的消息（Phase 3）
        
        Args:
            device_id: 设备ID
            message: 消息
        """
        message_type = message.get("type", "unknown")
        LoggingUtils.log_warning("WebSocketServer", "Unknown message type {type} from device {device_id}", 
                               type=message_type, device_id=device_id)
        
        # 可以选择发送错误响应或忽略
        # 这里选择发送错误响应，让客户端知道消息类型不支持
        error_response = MessageProtocol.create_error_message(
            error=f"Unknown message type: {message_type}",
            device_id=device_id,
            error_code="UNKNOWN_MESSAGE_TYPE",
            request_id=message.get("request_id")
        )
        await self.session_manager.send_to_device(device_id, error_response)
    
    async def _handle_command_response(self, device_id: str, response_data: Dict[str, Any]):
        """
        处理命令响应消息（向后兼容方法，Phase 3 中已由 _handle_command_response_async 替代）
        
        Args:
            device_id: 设备ID
            response_data: 响应数据
        """
        # 委托给异步版本
        await self._handle_command_response_async(device_id, response_data)
    
    def register_tools_instance(self, device_id: str, tools_instance):
        """
        注册 WebSocketTools 实例（用于响应处理）
        
        Args:
            device_id: 设备ID
            tools_instance: WebSocketTools 实例
        """
        self._device_tools_map[device_id] = tools_instance
        LoggingUtils.log_debug("WebSocketServer", "Registered WebSocketTools instance for device {device_id}", 
                             device_id=device_id)
    
    def unregister_tools_instance(self, device_id: str):
        """
        注销 WebSocketTools 实例
        
        Args:
            device_id: 设备ID
        """
        if device_id in self._device_tools_map:
            del self._device_tools_map[device_id]
            LoggingUtils.log_debug("WebSocketServer", "Unregistered WebSocketTools instance for device {device_id}", 
                                 device_id=device_id)
    
    def get_connected_devices(self) -> List[str]:
        """
        获取已连接设备列表（同步方法，用于快速查询）
        
        Returns:
            已连接设备ID列表
        """
        # 使用同步方式获取活跃设备（SessionManager.get_active_devices 是同步方法）
        return list(self.session_manager.get_active_devices())
    
    def is_device_connected(self, device_id: str) -> bool:
        """
        检查设备是否已连接（同步方法，用于快速查询）
        
        Args:
            device_id: 设备ID
            
        Returns:
            设备是否已连接
        """
        return device_id in self.session_manager.get_active_devices()
    
    async def _cleanup_task(self):
        """定期清理超时会话的任务"""
        while self.is_running:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                await self.session_manager.cleanup_timeout_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                LoggingUtils.log_error("WebSocketServer", "Error in cleanup task: {error}", error=e)
    
    async def start(self):
        """启动 WebSocket 服务器"""
        try:
            # 导入 websockets 库（需要安装: pip install websockets）
            import websockets
            
            LoggingUtils.log_info("WebSocketServer", "Starting WebSocket server on {host}:{port}{path}", 
                                host=self.host, port=self.port, path=self.websocket_path)
            
            # 创建WebSocket服务器
            # 使用 process_request 处理路径验证和请求头缓存
            self.server = await websockets.serve(
                lambda ws, path: self._handle_client(ws, path),
                self.host,
                self.port,
                process_request=self._process_request
            )
            
            self.is_running = True
            
            # 启动清理任务
            self._cleanup_task = asyncio.create_task(self._cleanup_task())
            
            LoggingUtils.log_success("WebSocketServer", "WebSocket server started successfully on {host}:{port}", 
                                   host=self.host, port=self.port)
            
            # 等待服务器关闭
            await self.server.wait_closed()
            
        except ImportError:
            LoggingUtils.log_error("WebSocketServer", "websockets library not installed. Install with: pip install websockets")
            raise
        except Exception as e:
            LoggingUtils.log_error("WebSocketServer", "Failed to start WebSocket server: {error}", error=e)
            raise
    
    async def stop(self):
        """停止 WebSocket 服务器"""
        LoggingUtils.log_info("WebSocketServer", "Stopping WebSocket server...")
        
        self.is_running = False
        
        # 取消清理任务
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # 关闭所有连接
        active_devices = self.session_manager.get_active_devices()
        for device_id in active_devices:
            await self.session_manager.unregister_session(device_id)
        
        # 关闭服务器
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        
        LoggingUtils.log_success("WebSocketServer", "WebSocket server stopped")

