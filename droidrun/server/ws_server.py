"""
WebSocket 服务器 - 接收 APP 端连接并提供设备控制服务
"""
import asyncio
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
import os
from droidrun.agent.utils.logging_utils import LoggingUtils
from droidrun.server.session_manager import SessionManager
from droidrun.server.message_protocol import MessageProtocol, MessageType
from droidrun.server.message_router import MessageRouter
from droidrun.server.upload_http import UploadHTTPServer, UploadConfig
# 延迟导入 TaskExecutor 以避免循环导入
# from droidrun.server.task_executor import TaskExecutor

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
        self._upload_server: Optional[UploadHTTPServer] = None
        self._upload_tmp_root = os.path.join(os.path.abspath(os.getcwd()), "tmp", "droidrun")
        # 存储请求头信息（用于设备ID提取）
        self._request_headers_cache = {}
        # 设备ID -> WebSocketTools 实例的映射（用于响应处理）
        self._device_tools_map: Dict[str, Any] = {}
        # 设备ID -> TaskExecutor 实例的映射（用于任务执行）
        self._device_task_executors: Dict[str, Any] = {}
        # 待处理的二进制数据（device_id -> request_id -> data）
        self._pending_binary_data: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # 待处理的响应（device_id -> request_id -> response_message）
        self._pending_responses: Dict[str, Dict[str, Dict[str, Any]]] = {}
        
        # 初始化消息路由器（Phase 3）
        self.message_router = MessageRouter()
        self._setup_message_handlers()
        
        # 注册到全局（用于同一进程内的访问）
        set_global_server(self)
        
        LoggingUtils.log_info("WebSocketServer", "WebSocketServer initialized (host={host}, port={port}, path={path})", 
                             host=host, port=port, path=websocket_path)
    
    async def _handle_client(self, websocket):
        """
        处理客户端连接
        
        Args:
            websocket: WebSocket 连接对象
        """
        device_id = None
        try:
            # 获取客户端地址
            try:
                remote_addr = websocket.remote_address
                client_address = f"{remote_addr[0]}:{remote_addr[1]}"
            except (AttributeError, TypeError):
                client_address = "unknown"
            
            # 从websocket对象获取路径（包含查询参数）
            # 尝试多个属性来获取完整路径
            path = None
            query_string = None
            
            # 方法1: 尝试从 request_uri 获取（最可靠的方法）
            if hasattr(websocket, 'request_uri'):
                try:
                    uri = websocket.request_uri
                    path = uri.path if hasattr(uri, 'path') else None
                    # 尝试多种方式获取查询参数
                    if hasattr(uri, 'query'):
                        query_string = uri.query
                    elif hasattr(uri, 'query_string'):
                        query_string = uri.query_string
                    # 如果 query 是空字符串，尝试从 raw_path 解析
                    if not query_string and hasattr(uri, 'raw_path'):
                        raw_path = uri.raw_path
                        if '?' in raw_path:
                            query_string = raw_path.split('?', 1)[1]
                except (AttributeError, TypeError, Exception) as e:
                    LoggingUtils.log_debug("WebSocketServer", "Error accessing request_uri: {error}", error=e)
                    pass
            
            # 方法2: 尝试从 request 对象获取（这是最可能的方法，因为日志显示request有path属性）
            if hasattr(websocket, 'request'):
                try:
                    request = websocket.request
                    # request.path 可能包含完整路径和查询参数
                    if hasattr(request, 'path'):
                        request_path = request.path
                        LoggingUtils.log_debug("WebSocketServer", "request.path = {path}", path=request_path)
                        # 检查path是否包含查询参数
                        if '?' in str(request_path):
                            path_part, query_part = str(request_path).split('?', 1)
                            if path is None:
                                path = path_part
                            if not query_string:
                                query_string = query_part
                                LoggingUtils.log_info("WebSocketServer", "Found query string from request.path: {query}", query=query_string)
                        elif path is None:
                            path = request_path
                    
                    # 如果还没有查询参数，尝试从其他属性获取
                    if not query_string:
                        if hasattr(request, 'query_string'):
                            query_string = request.query_string
                            if query_string:
                                LoggingUtils.log_info("WebSocketServer", "Found query string from request.query_string: {query}", query=query_string)
                        elif hasattr(request, 'query'):
                            query_string = request.query
                            if query_string:
                                LoggingUtils.log_info("WebSocketServer", "Found query string from request.query: {query}", query=query_string)
                        elif hasattr(request, 'raw_path'):
                            raw_path = request.raw_path
                            if raw_path and '?' in str(raw_path):
                                query_string = str(raw_path).split('?', 1)[1]
                                if query_string:
                                    LoggingUtils.log_info("WebSocketServer", "Found query string from request.raw_path: {query}", query=query_string)
                except (AttributeError, TypeError, Exception) as e:
                    LoggingUtils.log_debug("WebSocketServer", "Error accessing request: {error}", error=e)
                    pass
            
            # 方法3: 从websocket.path获取（如果前面没有获取到）
            if path is None and hasattr(websocket, 'path'):
                path = websocket.path
            
            # 方法4: 使用默认路径
            if path is None:
                path = getattr(websocket, 'path', self.websocket_path)
            
            # 组合路径和查询参数
            if query_string:
                path_str = f"{path}?{query_string}"
            else:
                path_str = str(path) if not isinstance(path, str) else path
            
            # 调试：如果路径中没有查询参数，记录websocket对象的属性
            if "?" not in path_str:
                # 尝试从所有可能的属性中查找查询参数
                debug_info = []
                # 打印所有属性
                all_attrs = dir(websocket)
                for attr in ['request_uri', 'request', 'path', 'headers', 'raw_request', 'request_headers']:
                    if hasattr(websocket, attr):
                        try:
                            value = getattr(websocket, attr)
                            debug_info.append(f"{attr}={type(value).__name__}")
                            # 如果是request对象，检查其属性
                            if attr == 'request' and hasattr(value, '__dict__'):
                                request_attrs = list(value.__dict__.keys())[:10]
                                debug_info.append(f"  request attrs: {request_attrs}")
                                # 尝试获取查询参数
                                if hasattr(value, 'query_string'):
                                    debug_info.append(f"  query_string: {value.query_string}")
                                if hasattr(value, 'query'):
                                    debug_info.append(f"  query: {value.query}")
                                if hasattr(value, 'raw_path'):
                                    debug_info.append(f"  raw_path: {value.raw_path}")
                        except Exception as e:
                            debug_info.append(f"{attr}=error:{str(e)[:50]}")
                
                # 尝试直接从 request_uri 获取
                if hasattr(websocket, 'request_uri'):
                    try:
                        uri = websocket.request_uri
                        debug_info.append(f"request_uri.path={uri.path}")
                        debug_info.append(f"request_uri.query={uri.query}")
                        if uri.query:
                            query_string = uri.query
                            path_str = f"{path}?{query_string}"
                            LoggingUtils.log_info("WebSocketServer", "Found query string from request_uri: {query}", query=query_string)
                    except Exception as e:
                        debug_info.append(f"request_uri access error: {str(e)[:50]}")
                
                LoggingUtils.log_info("WebSocketServer", "WebSocket attributes: {attrs}", attrs=", ".join(debug_info))
            
            # 验证路径
            if not (path_str == self.websocket_path or (path_str.startswith(self.websocket_path) and (len(path_str) == len(self.websocket_path) or path_str[len(self.websocket_path)] in ['?', '/']))):
                LoggingUtils.log_warning("WebSocketServer", "Invalid path: {path}, rejecting connection from {address}", 
                                       path=path_str, address=client_address)
                await websocket.close(code=4004, reason="Path not found")
                return
            
            LoggingUtils.log_info("WebSocketServer", "New client connected from {address}, path: {path}", 
                                address=client_address, path=path_str)
            
            # 从查询参数或首部获取设备ID
            device_id = await self._extract_device_id(websocket, path_str)
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
                    # 记录接收到的消息（用于调试）
                    if isinstance(message, bytes):
                        # 检查是否是二进制数据消息（我们的自定义协议）
                        if len(message) > 0 and message[0] == 0x01:
                            # 二进制数据消息
                            LoggingUtils.log_info("WebSocketServer", "Received binary data message from device {device_id}: size={size} bytes", 
                                                 device_id=device_id, size=len(message))
                            await self._handle_binary_message(device_id, message)
                        else:
                            # 尝试解码为文本
                            try:
                                message_str = message.decode('utf-8')
                                LoggingUtils.log_info("WebSocketServer", "Received message from device {device_id}: {msg}", 
                                                     device_id=device_id, msg=message_str[:200])
                                await self._handle_message(device_id, message_str)
                            except UnicodeDecodeError:
                                LoggingUtils.log_warning("WebSocketServer", "Received binary message that cannot be decoded as UTF-8 from device {device_id}", 
                                                        device_id=device_id)
                    else:
                        message_str = message
                        LoggingUtils.log_info("WebSocketServer", "Received message from device {device_id}: {msg}", 
                                             device_id=device_id, msg=message_str[:200])
                        await self._handle_message(device_id, message_str)
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
            path: 请求路径（字符串）
            request_headers: 请求头
            
        Returns:
            None 如果路径匹配，否则抛出异常或返回HTTP响应
        """
        try:
            # 处理path为None的情况
            if path is None:
                path = ""
            
            # 确保path是字符串
            path_str = str(path) if not isinstance(path, str) else path
            
            # 验证路径
            # 匹配 /ws 或 /ws?device_id=xxx 格式
            # 使用 startswith 匹配，因为 /ws?xxx 以 /ws 开头
            if path_str == self.websocket_path or (path_str.startswith(self.websocket_path) and (len(path_str) == len(self.websocket_path) or path_str[len(self.websocket_path)] in ['?', '/'])):
                # 缓存请求头（用于后续设备ID提取）
                # 使用路径作为临时key，后续连接建立时会匹配
                self._request_headers_cache[path_str] = request_headers
                return None  # 允许连接
            else:
                # 路径不匹配，抛出异常让websockets库处理
                from websockets.exceptions import InvalidHandshake
                raise InvalidHandshake(f"Path not found: {path_str}")
        except Exception as e:
            # 记录错误并重新抛出，让websockets库处理
            LoggingUtils.log_error("WebSocketServer", "Error in _process_request: {error}, path: {path}", 
                                 error=e, path=path)
            # 如果是InvalidHandshake，直接抛出
            if isinstance(e, Exception) and "InvalidHandshake" in str(type(e)):
                raise
            # 否则抛出InvalidHandshake异常
            from websockets.exceptions import InvalidHandshake
            raise InvalidHandshake(f"Internal server error: {str(e)}")
    
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
        
        # 注册任务请求处理器（延迟导入以避免循环导入）
        # 注意：_handle_task_request 方法内部会导入 TaskExecutor
        self.message_router.register_handler(
            MessageType.TASK_REQUEST,
            self._handle_task_request
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
            
            msg_len = len(message_str or "")
            t0 = datetime.now()
            LoggingUtils.log_debug("WebSocketServer", "Processing message from device {device_id}: len={length}, head={head}", 
                                 device_id=device_id, length=msg_len, head=message_str[:200])
            
            # 使用消息协议解析（Phase 3）
            parsed_message, parse_error = MessageProtocol.parse_message(message_str)
            parse_ms = int((datetime.now() - t0).total_seconds() * 1000)
            
            if parsed_message:
                mtype = parsed_message.get("type")
                rid = parsed_message.get("request_id")
                data = parsed_message.get("data") or {}
                data_size = 0
                try:
                    data_size = len(json.dumps(data, ensure_ascii=False))
                except Exception:
                    pass
                extra = ""
                if isinstance(data, dict):
                    if "screenshot_base64" in data:
                        try:
                            extra += f", screenshot_len={len(data.get('screenshot_base64') or '')}"
                        except Exception:
                            pass
                    if "a11y_tree" in data:
                        try:
                            extra += f", a11y_len={len(data.get('a11y_tree') or [])}"
                        except Exception:
                            pass
                LoggingUtils.log_info("WebSocketServer", "Parsed message: type={type}, request_id={rid}, data_size={dsize}B, parse_time={ms}ms{extra}", 
                                      type=mtype, rid=rid, dsize=data_size, ms=parse_ms, extra=extra)
            
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
    
    async def _handle_task_request(self, device_id: str, message: Dict[str, Any]):
        """
        处理任务请求消息
        
        Args:
            device_id: 设备ID
            message: 任务请求消息
        """
        try:
            # 延迟导入 TaskExecutor 以避免循环导入
            from droidrun.server.task_executor import TaskExecutor
            
            request_id = message.get("request_id")
            if not request_id:
                LoggingUtils.log_error("WebSocketServer", "Task request missing request_id from device {device_id}", 
                                     device_id=device_id)
                error_response = MessageProtocol.create_task_response(
                    request_id="unknown",
                    status="error",
                    error="Missing request_id",
                    device_id=device_id
                )
                await self.session_manager.send_to_device(device_id, error_response)
                return
            
            data = message.get("data", {})
            goal = data.get("goal")
            if not goal:
                LoggingUtils.log_error("WebSocketServer", "Task request missing goal from device {device_id}", 
                                     device_id=device_id)
                error_response = MessageProtocol.create_task_response(
                    request_id=request_id,
                    status="error",
                    error="Missing goal in task request",
                    device_id=device_id
                )
                await self.session_manager.send_to_device(device_id, error_response)
                return
            
            options = data.get("options", {})
            
            LoggingUtils.log_info("WebSocketServer", "Received task request from device {device_id}: goal={goal}", 
                                device_id=device_id, goal=goal[:100])
            
            # 创建或获取任务执行器
            if device_id not in self._device_task_executors:
                self._device_task_executors[device_id] = TaskExecutor(device_id)
            
            executor = self._device_task_executors[device_id]
            
            # 定义状态回调函数
            async def status_callback(status: str, progress: float, message_text: str):
                """发送任务状态更新"""
                try:
                    status_msg = MessageProtocol.create_task_status(
                        request_id=request_id,
                        status=status,
                        progress=progress,
                        message=message_text,
                        device_id=device_id
                    )
                    await self.session_manager.send_to_device(device_id, status_msg)
                except Exception as e:
                    LoggingUtils.log_error("WebSocketServer", "Failed to send task status update: {error}", error=e)
            
            # 在后台任务中执行（避免阻塞消息处理）
            async def execute_in_background():
                """在后台执行任务"""
                try:
                    LoggingUtils.log_info("WebSocketServer", "Background task started for device {device_id}, request_id={request_id}", 
                                        device_id=device_id, request_id=request_id)
                    
                    # 发送开始状态
                    try:
                        await status_callback("running", 0.0, "任务开始执行...")
                    except Exception as e:
                        LoggingUtils.log_error("WebSocketServer", "Failed to send initial status: {error}", error=e)
                    
                    LoggingUtils.log_info("WebSocketServer", "Calling executor.execute_task()...")
                    
                    # 执行任务
                    result = await executor.execute_task(
                        goal=goal,
                        request_id=request_id,
                        options=options,
                        status_callback=status_callback
                    )
                    
                    LoggingUtils.log_info("WebSocketServer", "Task execution completed, result: {result}", result=result)
                    
                    # 发送成功响应
                    response = MessageProtocol.create_task_response(
                        request_id=request_id,
                        status="success",
                        result=result,
                        device_id=device_id
                    )
                    await self.session_manager.send_to_device(device_id, response)
                    
                    LoggingUtils.log_info("WebSocketServer", "Task completed successfully for device {device_id}, request_id={request_id}", 
                                        device_id=device_id, request_id=request_id)
                    
                except Exception as e:
                    LoggingUtils.log_error("WebSocketServer", "Error executing task for device {device_id}: {error}", 
                                         device_id=device_id, error=e)
                    import traceback
                    error_trace = traceback.format_exc()
                    LoggingUtils.log_error("WebSocketServer", "Task execution traceback: {traceback}", traceback=error_trace)
                    
                    # 发送错误响应
                    error_response = MessageProtocol.create_task_response(
                        request_id=request_id,
                        status="error",
                        error=f"Task execution failed: {str(e)}",
                        device_id=device_id
                    )
                    try:
                        await self.session_manager.send_to_device(device_id, error_response)
                    except Exception as send_error:
                        LoggingUtils.log_error("WebSocketServer", "Failed to send error response: {error}", error=send_error)
            
            # 启动后台任务
            asyncio.create_task(execute_in_background())
            
            LoggingUtils.log_info("WebSocketServer", "Task execution started for device {device_id}, request_id={request_id}", 
                                device_id=device_id, request_id=request_id)
            
        except Exception as e:
            LoggingUtils.log_error("WebSocketServer", "Error handling task request from device {device_id}: {error}", 
                                 device_id=device_id, error=e)
            # 尝试发送错误响应
            try:
                request_id = message.get("request_id", "unknown")
                error_response = MessageProtocol.create_task_response(
                    request_id=request_id,
                    status="error",
                    error=f"Failed to process task request: {str(e)}",
                    device_id=device_id
                )
                await self.session_manager.send_to_device(device_id, error_response)
            except Exception:
                pass
    
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
    
    async def _handle_binary_message(self, device_id: str, message_bytes: bytes):
        """
        处理二进制消息（自定义协议）
        
        协议格式:
        [消息类型:1字节][请求ID长度:2字节][请求ID UTF-8][数据类型长度:1字节][数据类型 UTF-8][数据长度:4字节][数据二进制]
        
        Args:
            device_id: 设备ID
            message_bytes: 二进制消息数据
        """
        try:
            if len(message_bytes) < 8:
                LoggingUtils.log_error("WebSocketServer", "Binary message too short: {size} bytes", size=len(message_bytes))
                return
            
            offset = 0
            
            # 读取消息类型（应该是0x01）
            msg_type = message_bytes[offset]
            offset += 1
            if msg_type != 0x01:
                LoggingUtils.log_error("WebSocketServer", "Unknown binary message type: {type}", type=msg_type)
                return
            
            # 读取请求ID长度（2字节，big-endian）
            request_id_len = (message_bytes[offset] << 8) | message_bytes[offset + 1]
            offset += 2
            
            if offset + request_id_len > len(message_bytes):
                LoggingUtils.log_error("WebSocketServer", "Invalid request_id length: {len}", len=request_id_len)
                return
            
            # 读取请求ID
            request_id = message_bytes[offset:offset + request_id_len].decode('utf-8')
            offset += request_id_len
            
            # 读取数据类型长度（1字节）
            if offset >= len(message_bytes):
                LoggingUtils.log_error("WebSocketServer", "Message truncated at data_type length")
                return
            data_type_len = message_bytes[offset]
            offset += 1
            
            if offset + data_type_len > len(message_bytes):
                LoggingUtils.log_error("WebSocketServer", "Invalid data_type length: {len}", len=data_type_len)
                return
            
            # 读取数据类型
            data_type = message_bytes[offset:offset + data_type_len].decode('utf-8')
            offset += data_type_len
            
            # 读取数据长度（4字节，big-endian）
            if offset + 4 > len(message_bytes):
                LoggingUtils.log_error("WebSocketServer", "Message truncated at data length")
                return
            data_len = (message_bytes[offset] << 24) | (message_bytes[offset + 1] << 16) | (message_bytes[offset + 2] << 8) | message_bytes[offset + 3]
            offset += 4
            
            if offset + data_len > len(message_bytes):
                LoggingUtils.log_error("WebSocketServer", "Invalid data length: {len}, available: {avail}", 
                                      len=data_len, avail=len(message_bytes) - offset)
                return
            
            # 读取数据
            data_bytes = message_bytes[offset:offset + data_len]
            
            LoggingUtils.log_info("WebSocketServer", "Parsed binary message: request_id={rid}, data_type={dtype}, data_size={size} bytes", 
                                 rid=request_id, dtype=data_type, size=len(data_bytes))
            
            # 处理二进制数据
            await self._process_binary_data(device_id, request_id, data_type, data_bytes)
            
        except Exception as e:
            LoggingUtils.log_error("WebSocketServer", "Error parsing binary message: {error}", error=e)
            import traceback
            LoggingUtils.log_error("WebSocketServer", "Traceback: {tb}", tb=traceback.format_exc())
    
    async def _process_binary_data(self, device_id: str, request_id: str, data_type: str, data_bytes: bytes):
        """
        处理二进制数据
        
        Args:
            device_id: 设备ID
            request_id: 请求ID
            data_type: 数据类型 ("screenshot" 或 "a11y_tree")
            data_bytes: 二进制数据
        """
        try:
            # 查找对应的WebSocketTools实例
            if device_id not in self._device_tools_map:
                LoggingUtils.log_warning("WebSocketServer", "No WebSocketTools instance for device {device_id}", device_id=device_id)
                return
            
            tools_instance = self._device_tools_map[device_id]
            
            if data_type == "screenshot":
                # 处理截图数据
                # 对于take_screenshot命令，截图是单独的数据，可以直接完成响应
                # 对于get_state命令，截图需要与a11y_tree和phone_state合并
                
                # 检查是否是get_state命令（通过检查是否有pending的a11y_tree）
                if (hasattr(self, '_pending_binary_data') and 
                    device_id in self._pending_binary_data and 
                    request_id in self._pending_binary_data[device_id] and
                    'a11y_tree' in self._pending_binary_data[device_id][request_id]):
                    # 这是get_state命令，存储screenshot等待合并
                    if not hasattr(self, '_pending_binary_data'):
                        self._pending_binary_data = {}
                    if device_id not in self._pending_binary_data:
                        self._pending_binary_data[device_id] = {}
                    if request_id not in self._pending_binary_data[device_id]:
                        self._pending_binary_data[device_id][request_id] = {}
                    
                    self._pending_binary_data[device_id][request_id]['screenshot'] = data_bytes
                    LoggingUtils.log_info("WebSocketServer", "Stored screenshot binary data for get_state: request_id={rid}, size={size} bytes", 
                                         rid=request_id, size=len(data_bytes))
                    
                    # 检查是否可以直接完成响应
                    await self._try_complete_response_with_binary_data(device_id, request_id, tools_instance)
                else:
                    # 这是take_screenshot命令，直接完成响应
                    import base64
                    screenshot_base64 = base64.b64encode(data_bytes).decode('utf-8')
                    
                    response_data = {
                        "image_data": screenshot_base64,
                        "screenshot_base64": screenshot_base64,
                        "format": "JPEG",
                        "size": len(data_bytes)
                    }
                    
                    response_message = {
                        "type": "command_response",
                        "request_id": request_id,
                        "status": "success",
                        "data": response_data,
                        "device_id": device_id
                    }
                    
                    if hasattr(tools_instance, '_handle_response'):
                        tools_instance._handle_response(response_message)
                    
                    LoggingUtils.log_info("WebSocketServer", "Processed screenshot binary data for take_screenshot: request_id={rid}, size={size} bytes", 
                                         rid=request_id, size=len(data_bytes))
                
            elif data_type == "a11y_tree":
                # 处理a11y_tree JSON数据
                import json
                try:
                    a11y_tree_json = json.loads(data_bytes.decode('utf-8'))
                    
                    # 存储a11y_tree数据，等待与command_response合并
                    if not hasattr(self, '_pending_binary_data'):
                        self._pending_binary_data = {}
                    
                    if device_id not in self._pending_binary_data:
                        self._pending_binary_data[device_id] = {}
                    
                    if request_id not in self._pending_binary_data[device_id]:
                        self._pending_binary_data[device_id][request_id] = {}
                    
                    self._pending_binary_data[device_id][request_id]['a11y_tree'] = a11y_tree_json
                    
                    LoggingUtils.log_info("WebSocketServer", "Stored a11y_tree binary data: request_id={rid}, nodes={nodes}", 
                                         rid=request_id, nodes=len(a11y_tree_json) if isinstance(a11y_tree_json, list) else "unknown")
                    
                    # 检查是否可以直接完成响应（如果command_response已经到达）
                    await self._try_complete_response_with_binary_data(device_id, request_id, tools_instance)
                    
                except json.JSONDecodeError as e:
                    LoggingUtils.log_error("WebSocketServer", "Failed to parse a11y_tree JSON: {error}", error=e)
                except UnicodeDecodeError as e:
                    LoggingUtils.log_error("WebSocketServer", "Failed to decode a11y_tree as UTF-8: {error}", error=e)
            else:
                LoggingUtils.log_warning("WebSocketServer", "Unknown data type: {dtype}", dtype=data_type)
                
        except Exception as e:
            LoggingUtils.log_error("WebSocketServer", "Error processing binary data: {error}", error=e)
            import traceback
            LoggingUtils.log_error("WebSocketServer", "Traceback: {tb}", tb=traceback.format_exc())
    
    async def _try_complete_response_with_binary_data(self, device_id: str, request_id: str, tools_instance):
        """
        尝试使用二进制数据完成响应
        
        检查是否有pending的command_response，如果有则合并二进制数据并完成响应
        
        Args:
            device_id: 设备ID
            request_id: 请求ID
            tools_instance: WebSocketTools实例
        """
        try:
            if not hasattr(self, '_pending_binary_data'):
                return
            
            if device_id not in self._pending_binary_data:
                return
            
            if request_id not in self._pending_binary_data[device_id]:
                return
            
            pending_data = self._pending_binary_data[device_id][request_id]
            
            # 检查是否有pending的command_response需要合并二进制数据
            if hasattr(self, '_pending_responses'):
                if device_id in self._pending_responses and request_id in self._pending_responses[device_id]:
                    # 有pending的response，合并二进制数据
                    pending_response = self._pending_responses[device_id][request_id]
                    await self._merge_binary_data_into_response(device_id, request_id, pending_response, tools_instance)
                else:
                    # 没有pending的response，检查是否所有二进制数据都已到达
                    # 对于get_state命令，我们需要等待command_response
                    # 但如果command_response先到达，会存储在_pending_responses中
                    # 所以这里我们只记录日志
                    LoggingUtils.log_debug("WebSocketServer", "Binary data received but no pending response yet: request_id={rid}", rid=request_id)
            
        except Exception as e:
            LoggingUtils.log_error("WebSocketServer", "Error completing response with binary data: {error}", error=e)
    
    async def _merge_binary_data_into_response(self, device_id: str, request_id: str, response_message: Dict[str, Any], tools_instance):
        """
        将二进制数据合并到响应消息中，并完成响应
        
        Args:
            device_id: 设备ID
            request_id: 请求ID
            response_message: 响应消息
            tools_instance: WebSocketTools实例
        """
        try:
            if not hasattr(self, '_pending_binary_data'):
                return
            
            if device_id not in self._pending_binary_data:
                return
            
            if request_id not in self._pending_binary_data[device_id]:
                return
            
            pending_data = self._pending_binary_data[device_id][request_id]
            data = response_message.get("data") or {}
            
            # 合并a11y_tree
            if 'a11y_tree' in pending_data:
                data['a11y_tree'] = pending_data['a11y_tree']
                LoggingUtils.log_info("WebSocketServer", "Merged a11y_tree from binary data: request_id={rid}, nodes={nodes}", 
                                     rid=request_id, nodes=len(pending_data['a11y_tree']) if isinstance(pending_data['a11y_tree'], list) else "unknown")
            
            # 合并screenshot（如果有）
            if 'screenshot' in pending_data:
                import base64
                screenshot_bytes = pending_data['screenshot']
                screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
                data['image_data'] = screenshot_base64
                data['screenshot_base64'] = screenshot_base64
                data.setdefault('format', 'JPEG')
                LoggingUtils.log_info("WebSocketServer", "Merged screenshot from binary data: request_id={rid}, size={size} bytes", 
                                     rid=request_id, size=len(screenshot_bytes))
            
            # 移除传输状态标志（不再需要）
            data.pop('binary_data_pending', None)
            data.pop('a11y_tree_transmitted', None)
            data.pop('screenshot_transmitted', None)
            data.pop('a11y_tree_size', None)
            data.pop('screenshot_size', None)
            
            # 更新response_message
            response_message['data'] = data
            
            # 清理pending数据
            del self._pending_binary_data[device_id][request_id]
            if not self._pending_binary_data[device_id]:
                del self._pending_binary_data[device_id]
            
            # 清理pending_response
            if hasattr(self, '_pending_responses'):
                if device_id in self._pending_responses and request_id in self._pending_responses[device_id]:
                    del self._pending_responses[device_id][request_id]
                    if not self._pending_responses[device_id]:
                        del self._pending_responses[device_id]
            
            LoggingUtils.log_info("WebSocketServer", "Completed response with binary data: request_id={rid}, has_a11y={has_a11y}, has_screenshot={has_screenshot}", 
                                 rid=request_id, has_a11y='a11y_tree' in data, has_screenshot='screenshot_base64' in data)
            
            # 转发到WebSocketTools
            if hasattr(tools_instance, '_handle_response'):
                tools_instance._handle_response(response_message)
            else:
                LoggingUtils.log_warning("WebSocketServer", "WebSocketTools instance has no _handle_response method")
            
        except Exception as e:
            LoggingUtils.log_error("WebSocketServer", "Error merging binary data into response: {error}", error=e)
            import traceback
            LoggingUtils.log_error("WebSocketServer", "Traceback: {tb}", tb=traceback.format_exc())
    
    async def _handle_command_response_async(self, device_id: str, message: Dict[str, Any]):
        """
        处理命令响应消息（Phase 3 - 异步版本，用于路由器）
        
        Args:
            device_id: 设备ID
            message: 命令响应消息
        """
        # 在转发前，若 data 中包含 screenshot_ref，则读取文件并回填为 image_data/screenshot_base64
        # 或者检查是否有待处理的二进制数据
        try:
            # 忽略中间态回包（accepted），仅在最终 success/error 时完成请求
            status = message.get("status")
            if status == "accepted":
                LoggingUtils.log_debug("WebSocketServer", "Received interim 'accepted' for device {device_id}, request_id={rid}", 
                                       device_id=device_id, rid=message.get("request_id"))
                return
            
            request_id = message.get("request_id")
            data = message.get("data") or {}
            
            # 检查是否有binary_data_pending标志（表示还有二进制数据待发送）
            binary_data_pending = data.get("binary_data_pending") or data.get("a11y_tree_transmitted") is not None or data.get("screenshot_transmitted") is not None
            
            # 检查是否有待处理的二进制数据
            has_pending_binary = False
            if request_id and hasattr(self, '_pending_binary_data'):
                if device_id in self._pending_binary_data and request_id in self._pending_binary_data[device_id]:
                    has_pending_binary = True
                    pending_data = self._pending_binary_data[device_id][request_id]
                    
                    # 合并a11y_tree（如果有）
                    if 'a11y_tree' in pending_data and 'a11y_tree' not in data:
                        data['a11y_tree'] = pending_data['a11y_tree']
                        LoggingUtils.log_info("WebSocketServer", "Merged a11y_tree from binary data: request_id={rid}", rid=request_id)
                    
                    # 合并screenshot（如果有）
                    if 'screenshot' in pending_data:
                        import base64
                        screenshot_bytes = pending_data['screenshot']
                        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
                        data['image_data'] = screenshot_base64
                        data['screenshot_base64'] = screenshot_base64
                        data.setdefault('format', 'JPEG')
                        LoggingUtils.log_info("WebSocketServer", "Merged screenshot from binary data: request_id={rid}, size={size} bytes", 
                                             rid=request_id, size=len(screenshot_bytes))
                    
                    # 清理已处理的数据
                    del self._pending_binary_data[device_id][request_id]
                    if not self._pending_binary_data[device_id]:
                        del self._pending_binary_data[device_id]
                    
                    # 更新message中的data
                    message['data'] = data
            
            # 如果还有二进制数据待发送，等待二进制数据到达
            if binary_data_pending and not has_pending_binary:
                # 存储响应，等待二进制数据
                if not hasattr(self, '_pending_responses'):
                    self._pending_responses = {}
                if device_id not in self._pending_responses:
                    self._pending_responses[device_id] = {}
                self._pending_responses[device_id][request_id] = message
                LoggingUtils.log_info("WebSocketServer", "Stored command_response, waiting for binary data: request_id={rid}", rid=request_id)
                return  # 不立即转发，等待二进制数据
            
            # 处理screenshot_ref（原有逻辑）
            if isinstance(data, dict) and "screenshot_ref" in data:
                ref = data.get("screenshot_ref") or {}
                ref_path = ref.get("path")
                if ref_path and os.path.exists(ref_path):
                    # 读取文件并转为base64
                    import base64
                    with open(ref_path, "rb") as f:
                        img_bytes = f.read()
                    b64 = base64.b64encode(img_bytes).decode("utf-8")
                    # 兼容两种字段：image_data（WebSocketTools.take_screenshot）与 screenshot_base64（get_state）
                    data["image_data"] = b64
                    data["screenshot_base64"] = b64
                    # 尽量推断格式
                    fmt = "JPEG" if ref_path.lower().endswith(".jpg") or ref_path.lower().endswith(".jpeg") else "PNG"
                    data.setdefault("format", fmt)
                    # 记录尺寸日志（仅长度）
                    LoggingUtils.log_info("WebSocketServer", "Resolved screenshot_ref to base64: bytes={size}B, b64_len={b64len}", 
                                          size=len(img_bytes), b64len=len(b64))
                else:
                    LoggingUtils.log_warning("WebSocketServer", "screenshot_ref path not found: {path}", path=ref_path)
            # 解析 a11y_ref -> a11y_tree
            if isinstance(data, dict) and "a11y_ref" in data and "a11y_tree" not in data:
                aref = data.get("a11y_ref") or {}
                apath = aref.get("path")
                if apath and os.path.exists(apath):
                    try:
                        import json as _json
                        with open(apath, "r", encoding="utf-8") as f:
                            a11y = _json.load(f)
                        # 规范：若文件根是对象且包含 a11y_tree，则取其字段；否则直接作为数组
                        if isinstance(a11y, dict) and "a11y_tree" in a11y:
                            data["a11y_tree"] = a11y["a11y_tree"]
                        else:
                            data["a11y_tree"] = a11y
                        LoggingUtils.log_info("WebSocketServer", "Resolved a11y_ref to a11y_tree (nodes approx) ok")
                    except Exception as e:
                        LoggingUtils.log_error("WebSocketServer", "Failed to resolve a11y_ref: {error}", error=e)
                else:
                    LoggingUtils.log_warning("WebSocketServer", "a11y_ref path not found: {path}", path=apath)
        except Exception as e:
            LoggingUtils.log_error("WebSocketServer", "Error resolving screenshot_ref: {error}", error=e)
        
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
    
    async def _run_cleanup_task(self):
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
            import os
            
            LoggingUtils.log_info("WebSocketServer", "Starting WebSocket server on {host}:{port}{path}", 
                                host=self.host, port=self.port, path=self.websocket_path)
            
            # 创建WebSocket服务器
            # 注意：新版本websockets的回调函数只接收websocket参数，path需要从websocket对象获取
            self.server = await websockets.serve(
                self._handle_client,
                self.host,
                self.port,
                max_size=int(self.config_manager.get("server.websocket_max_message_bytes", 20 * 1024 * 1024)),
                compression="deflate"
            )
            
            self.is_running = True
            
            # 启动清理任务
            self._cleanup_task = asyncio.create_task(self._run_cleanup_task())

            # 启动HTTP上传服务（端口默认使用 self.port+1，可通过配置覆盖）
            try:
                upload_port = int(self.config_manager.get("server.upload_port", self.port + 1))
            except Exception:
                upload_port = self.port + 1
            ttl_seconds = int(self.config_manager.get("server.upload_ttl_seconds", 3600))
            os.makedirs(self._upload_tmp_root, exist_ok=True)
            self._upload_server = UploadHTTPServer(
                UploadConfig(
                    host=self.host,
                    port=upload_port,
                    tmp_root=self._upload_tmp_root,
                    ttl_seconds=ttl_seconds,
                )
            )
            await self._upload_server.start()
            LoggingUtils.log_info("WebSocketServer", "HTTP upload server running on {host}:{port}", host=self.host, port=upload_port)
            
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
        
        # 停止HTTP上传服务
        if self._upload_server:
            try:
                await self._upload_server.stop()
            except Exception:
                pass
        
        LoggingUtils.log_success("WebSocketServer", "WebSocket server stopped")

