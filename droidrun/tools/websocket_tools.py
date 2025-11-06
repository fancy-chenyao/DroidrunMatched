"""
WebSocket Tools - 通过 WebSocket 与 APP 端通信的工具实现
"""
import asyncio
import json
import base64
import time
import logging
import uuid
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from llama_index.core.workflow import Context
from droidrun.agent.utils.logging_utils import LoggingUtils
from droidrun.agent.common.events import (
    InputTextActionEvent,
    KeyPressActionEvent,
    StartAppEvent,
    SwipeActionEvent,
    TapActionEvent,
    DragActionEvent,
)
from droidrun.tools.tools import Tools
from droidrun.server.session_manager import SessionManager
from droidrun.server.message_protocol import MessageProtocol, MessageType

logger = logging.getLogger("droidrun-tools-websocket")


class WebSocketTools(Tools):
    """通过 WebSocket 与 APP 端通信的工具实现"""
    
    def __init__(
        self,
        device_id: str,
        session_manager: SessionManager,
        config_manager=None,
        timeout: int = 30,
    ) -> None:
        """
        初始化 WebSocketTools 实例
        
        Args:
            device_id: 设备ID
            session_manager: 会话管理器实例
            config_manager: 配置管理器实例（可选）
            timeout: 请求超时时间（秒）
        """
        self.device_id = device_id
        self.session_manager = session_manager
        self.config_manager = config_manager
        self.timeout = timeout
        
        # 请求-响应队列
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.request_counter = 0
        self._request_lock = asyncio.Lock()
        
        # 上下文（用于事件流）
        self._ctx = None
        
        # 缓存数据
        self.clickable_elements_cache: List[Dict[str, Any]] = []
        self.last_screenshot = None
        self.reason = None
        self.success = None
        self.finished = False
        
        # 内存存储
        self.memory: List[str] = []
        self.screenshots: List[Dict[str, Any]] = []
        self.save_trajectories = "none"
        
        LoggingUtils.log_info("WebSocketTools", "WebSocketTools initialized for device {device_id}", 
                            device_id=device_id)
    
    def _generate_request_id(self) -> str:
        """生成请求ID"""
        self.request_counter += 1
        return f"{self.device_id}_{self.request_counter}_{uuid.uuid4().hex[:8]}"
    
    async def _send_request_and_wait(self, command: str, params: Dict[str, Any], timeout: Optional[int] = None) -> Dict[str, Any]:
        """
        发送请求并等待响应
        
        Args:
            command: 命令名称
            params: 命令参数
            timeout: 超时时间（秒），None 使用默认超时
            
        Returns:
            响应数据字典
            
        Raises:
            TimeoutError: 如果超时
            ValueError: 如果响应包含错误
        """
        request_id = self._generate_request_id()
        timeout = timeout or self.timeout
        
        # 创建 Future 用于等待响应
        future = asyncio.Future()
        async with self._request_lock:
            self.pending_requests[request_id] = future
        
        # 构建请求消息（使用标准协议，Phase 3）
        request_message = MessageProtocol.create_command_message(
            command=command,
            params=params,
            request_id=request_id,
            device_id=self.device_id
        )
        
        try:
            # 发送请求
            success = await self.session_manager.send_to_device(self.device_id, request_message)
            if not success:
                async with self._request_lock:
                    self.pending_requests.pop(request_id, None)
                raise ValueError(f"Failed to send request to device {self.device_id}")
            
            LoggingUtils.log_debug("WebSocketTools", "Sent request {request_id} for command {command}", 
                                 request_id=request_id, command=command)
            
            # 等待响应（带超时）
            try:
                response = await asyncio.wait_for(future, timeout=timeout)
                # response 是完整响应，提取 data 部分（如果存在）
                if isinstance(response, dict) and "data" in response:
                    return response["data"]
                return response
            except asyncio.TimeoutError:
                async with self._request_lock:
                    self.pending_requests.pop(request_id, None)
                raise TimeoutError(f"Request {request_id} timed out after {timeout} seconds")
        
        except Exception as e:
            async with self._request_lock:
                self.pending_requests.pop(request_id, None)
            raise
    
    def _handle_response(self, response_data: Dict[str, Any]):
        """
        处理来自 APP 的响应消息（由 WebSocketServer 从异步上下文调用）
        
        注意：这个方法会被 WebSocketServer 从异步上下文调用，需要正确处理异步
        
        Args:
            response_data: 响应数据字典，应包含 request_id 字段
        """
        request_id = response_data.get("request_id")
        if not request_id:
            LoggingUtils.log_warning("WebSocketTools", "Response missing request_id, ignoring")
            return
        
        # 使用异步方式处理响应
        async def _handle_async():
            async with self._request_lock:
                future = self.pending_requests.get(request_id)
                if future and not future.done():
                    # 检查是否有错误
                    if response_data.get("status") == "error":
                        error_msg = response_data.get("error", "Unknown error")
                        future.set_exception(ValueError(error_msg))
                    else:
                        # 设置响应数据（包含完整响应）
                        future.set_result(response_data)
                    LoggingUtils.log_debug("WebSocketTools", "Response received for request {request_id}", 
                                         request_id=request_id)
                else:
                    LoggingUtils.log_warning("WebSocketTools", "No pending request found for request_id {request_id}", 
                                           request_id=request_id)
        
        # 尝试在现有事件循环中调度
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果循环正在运行，创建任务（这是最常见的情况）
                asyncio.create_task(_handle_async())
            else:
                # 如果循环不在运行，直接运行（理论上不应该发生，因为从异步上下文调用）
                loop.run_until_complete(_handle_async())
        except RuntimeError:
            # 如果没有事件循环，在新线程中创建一个
            import threading
            def _run_in_thread():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(_handle_async())
                finally:
                    loop.close()
            thread = threading.Thread(target=_run_in_thread, daemon=True)
            thread.start()
    
    def _sync_wait(self, coro):
        """
        同步等待异步操作（用于同步方法调用异步实现）
        
        Args:
            coro: 协程对象
            
        Returns:
            协程的返回值
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果事件循环正在运行，使用线程池在新线程中运行
                import concurrent.futures
                import threading
                
                result_container = {}
                exception_container = {}
                
                def run_in_new_loop():
                    """在新的事件循环中运行协程"""
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        result = new_loop.run_until_complete(coro)
                        result_container['result'] = result
                    except Exception as e:
                        exception_container['exception'] = e
                    finally:
                        new_loop.close()
                
                thread = threading.Thread(target=run_in_new_loop, daemon=True)
                thread.start()
                thread.join(timeout=self.timeout + 5)  # 给一些额外时间
                
                if thread.is_alive():
                    raise TimeoutError(f"Operation timed out after {self.timeout + 5} seconds")
                
                if 'exception' in exception_container:
                    raise exception_container['exception']
                if 'result' in result_container:
                    return result_container['result']
                raise RuntimeError("No result or exception from async operation")
            else:
                return loop.run_until_complete(coro)
        except RuntimeError:
            # 如果没有事件循环，创建一个新的
            return asyncio.run(coro)
    
    def get_state(self) -> Dict[str, Any]:
        """
        获取设备状态（包含 a11y_tree 和 phone_state）
        
        Returns:
            包含 'a11y_tree' 和 'phone_state' 的字典
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "Getting state from device {device_id}", device_id=self.device_id)
            
            # 发送请求并等待响应
            response = self._sync_wait(
                self._send_request_and_wait("get_state", {})
            )
            
            # 验证响应格式（response 可能是 data 部分或完整响应）
            # 检查是否包含错误
            if response.get("status") == "error":
                error_msg = response.get("error", "Unknown error")
                LoggingUtils.log_error("WebSocketTools", "Error in get_state response: {error}", error=error_msg)
                return {
                    "error": "Error",
                    "message": error_msg
                }
            
            # 验证必需字段
            if "a11y_tree" not in response:
                LoggingUtils.log_error("WebSocketTools", "Response missing a11y_tree field")
                return {
                    "error": "Missing Data",
                    "message": "a11y_tree not found in response",
                }
            
            if "phone_state" not in response:
                LoggingUtils.log_error("WebSocketTools", "Response missing phone_state field")
                return {
                    "error": "Missing Data",
                    "message": "phone_state not found in response",
                }
            
            # 过滤掉 "type" 属性（与 AdbTools 保持一致）
            elements = response.get("a11y_tree", [])
            filtered_elements = []
            for element in elements:
                filtered_element = {k: v for k, v in element.items() if k != "type"}
                # 递归处理子元素
                if "children" in element:
                    filtered_children = []
                    for child in element["children"]:
                        filtered_child = {k: v for k, v in child.items() if k != "type"}
                        if "children" in child:
                            # 递归处理更深层的子元素
                            def filter_children_recursive(children):
                                result = []
                                for c in children:
                                    filtered = {k: v for k, v in c.items() if k != "type"}
                                    if "children" in c:
                                        filtered["children"] = filter_children_recursive(c["children"])
                                    result.append(filtered)
                                return result
                            filtered_child["children"] = filter_children_recursive(child["children"])
                        filtered_children.append(filtered_child)
                    filtered_element["children"] = filtered_children
                filtered_elements.append(filtered_element)
            
            # 更新缓存
            self.clickable_elements_cache = filtered_elements
            
            # 返回格式与 AdbTools 保持一致
            result = {
                "a11y_tree": filtered_elements,
                "phone_state": response.get("phone_state", {}),
                "elements": filtered_elements  # 兼容字段
            }
            
            LoggingUtils.log_debug("WebSocketTools", "State retrieved successfully, {count} elements", 
                                 count=len(filtered_elements))
            return result
            
        except TimeoutError as e:
            LoggingUtils.log_error("WebSocketTools", "Timeout getting state: {error}", error=e)
            return {
                "error": "Timeout",
                "message": str(e)
            }
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error getting state: {error}", error=e)
            return {
                "error": "Error",
                "message": str(e)
            }
    
    @Tools.ui_action
    def tap_by_index(self, index: int) -> str:
        """
        通过索引点击元素
        
        Args:
            index: 元素索引
            
        Returns:
            操作结果消息
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "Tapping element at index {index}", index=index)
            
            # 检查缓存
            if not self.clickable_elements_cache:
                return "Error: No UI elements cached. Call get_state first."
            
            # 发送请求
            response = self._sync_wait(
                self._send_request_and_wait("tap_by_index", {"index": index})
            )
            
            # 处理响应（response 是从 _send_request_and_wait 返回的 data 部分）
            # 如果 response 直接包含 status，说明是完整响应
            status = response.get("status")
            if status is None:
                # 如果没有 status，假设成功
                status = "success"
            
            if status == "success":
                message = response.get("message", f"Tapped element at index {index}")
                
                # 发送事件（如果上下文存在）
                if self._ctx:
                    element = self._find_element_by_index(index)
                    if element:
                        tap_event = TapActionEvent(
                            action_type="tap",
                            description=message,
                            x=response.get("x", 0),
                            y=response.get("y", 0),
                            element_index=index,
                            element_text=element.get("text", ""),
                            element_bounds=element.get("bounds", ""),
                        )
                        self._ctx.write_event_to_stream(tap_event)
                
                return message
            else:
                error_msg = response.get("error", "Unknown error")
                return f"Error: {error_msg}"
                
        except TimeoutError as e:
            return f"Error: Timeout - {str(e)}"
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error tapping element: {error}", error=e)
            return f"Error: {str(e)}"
    
    def _find_element_by_index(self, index: int) -> Optional[Dict[str, Any]]:
        """递归查找指定索引的元素"""
        def find_recursive(elements):
            for item in elements:
                if item.get("index") == index:
                    return item
                children = item.get("children", [])
                result = find_recursive(children)
                if result:
                    return result
            return None
        return find_recursive(self.clickable_elements_cache)
    
    @Tools.ui_action
    def swipe(
        self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 300
    ) -> bool:
        """
        滑动操作
        
        Args:
            start_x: 起始X坐标
            start_y: 起始Y坐标
            end_x: 结束X坐标
            end_y: 结束Y坐标
            duration_ms: 滑动持续时间（毫秒）
            
        Returns:
            操作是否成功
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "Swiping from ({start_x}, {start_y}) to ({end_x}, {end_y})", 
                                 start_x=start_x, start_y=start_y, end_x=end_x, end_y=end_y)
            
            response = self._sync_wait(
                self._send_request_and_wait("swipe", {
                    "start_x": start_x,
                    "start_y": start_y,
                    "end_x": end_x,
                    "end_y": end_y,
                    "duration_ms": duration_ms
                })
            )
            
            if response.get("status") == "success":
                if self._ctx:
                    swipe_event = SwipeActionEvent(
                        action_type="swipe",
                        description=f"Swipe from ({start_x}, {start_y}) to ({end_x}, {end_y})",
                        start_x=start_x,
                        start_y=start_y,
                        end_x=end_x,
                        end_y=end_y,
                        duration_ms=duration_ms
                    )
                    self._ctx.write_event_to_stream(swipe_event)
                
                return True
            else:
                return False
                
        except TimeoutError:
            LoggingUtils.log_error("WebSocketTools", "Timeout during swipe")
            return False
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error during swipe: {error}", error=e)
            return False
    
    @Tools.ui_action
    def drag(
        self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 3000
    ) -> bool:
        """
        拖拽操作
        
        Args:
            start_x: 起始X坐标
            start_y: 起始Y坐标
            end_x: 结束X坐标
            end_y: 结束Y坐标
            duration_ms: 拖拽持续时间（毫秒）
            
        Returns:
            操作是否成功
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "Dragging from ({start_x}, {start_y}) to ({end_x}, {end_y})", 
                                 start_x=start_x, start_y=start_y, end_x=end_x, end_y=end_y)
            
            response = self._sync_wait(
                self._send_request_and_wait("drag", {
                    "start_x": start_x,
                    "start_y": start_y,
                    "end_x": end_x,
                    "end_y": end_y,
                    "duration_ms": duration_ms
                })
            )
            
            if response.get("status") == "success":
                if self._ctx:
                    drag_event = DragActionEvent(
                        action_type="drag",
                        description=f"Drag from ({start_x}, {start_y}) to ({end_x}, {end_y})",
                        start_x=start_x,
                        start_y=start_y,
                        end_x=end_x,
                        end_y=end_y,
                        duration=duration_ms / 1000.0
                    )
                    self._ctx.write_event_to_stream(drag_event)
                
                return True
            else:
                return False
                
        except TimeoutError:
            LoggingUtils.log_error("WebSocketTools", "Timeout during drag")
            return False
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error during drag: {error}", error=e)
            return False
    
    @Tools.ui_action
    def input_text(self, text: str) -> str:
        """
        输入文本
        
        Args:
            text: 要输入的文本
            
        Returns:
            操作结果消息
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "Inputting text: {text}", text=text[:50])
            
            # 编码文本（Base64）
            encoded_text = base64.b64encode(text.encode()).decode()
            
            response = self._sync_wait(
                self._send_request_and_wait("input_text", {
                    "text": text,
                    "base64_text": encoded_text
                })
            )
            
            if response.get("status") == "success":
                message = response.get("message", f"Text input completed: {text[:50]}")
                
                if self._ctx:
                    input_event = InputTextActionEvent(
                        action_type="input_text",
                        description=f"Input text: '{text[:50]}{'...' if len(text) > 50 else ''}'",
                        text=text
                    )
                    self._ctx.write_event_to_stream(input_event)
                
                return message
            else:
                error_msg = response.get("error", "Unknown error")
                return f"Error: {error_msg}"
                
        except TimeoutError as e:
            return f"Error: Timeout - {str(e)}"
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error inputting text: {error}", error=e)
            return f"Error: {str(e)}"
    
    @Tools.ui_action
    def back(self) -> str:
        """
        按返回键
        
        Returns:
            操作结果消息
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "Pressing back button")
            
            response = self._sync_wait(
                self._send_request_and_wait("back", {})
            )
            
            if response.get("status") == "success":
                message = response.get("message", "Back button pressed")
                
                if self._ctx:
                    key_event = KeyPressActionEvent(
                        action_type="press_key",
                        description="Press back button",
                        keycode=4  # Android KEYCODE_BACK
                    )
                    self._ctx.write_event_to_stream(key_event)
                
                return message
            else:
                error_msg = response.get("error", "Unknown error")
                return f"Error: {error_msg}"
                
        except TimeoutError as e:
            return f"Error: Timeout - {str(e)}"
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error pressing back: {error}", error=e)
            return f"Error: {str(e)}"
    
    @Tools.ui_action
    def press_key(self, keycode: int) -> str:
        """
        按键操作
        
        Args:
            keycode: 按键码
            
        Returns:
            操作结果消息
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "Pressing key: {keycode}", keycode=keycode)
            
            response = self._sync_wait(
                self._send_request_and_wait("press_key", {"keycode": keycode})
            )
            
            if response.get("status") == "success":
                message = response.get("message", f"Key {keycode} pressed")
                
                if self._ctx:
                    key_event = KeyPressActionEvent(
                        action_type="press_key",
                        description=f"Press key: {keycode}",
                        keycode=keycode
                    )
                    self._ctx.write_event_to_stream(key_event)
                
                return message
            else:
                error_msg = response.get("error", "Unknown error")
                return f"Error: {error_msg}"
                
        except TimeoutError as e:
            return f"Error: Timeout - {str(e)}"
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error pressing key: {error}", error=e)
            return f"Error: {str(e)}"
    
    @Tools.ui_action
    def start_app(self, package: str, activity: str = "") -> str:
        """
        启动应用
        
        Args:
            package: 应用包名
            activity: Activity名称（可选）
            
        Returns:
            操作结果消息
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "Starting app: {package} with activity: {activity}", 
                                 package=package, activity=activity)
            
            response = self._sync_wait(
                self._send_request_and_wait("start_app", {
                    "package": package,
                    "activity": activity
                })
            )
            
            if response.get("status") == "success":
                message = response.get("message", f"App started: {package}")
                
                if self._ctx:
                    start_app_event = StartAppEvent(
                        action_type="start_app",
                        description=f"Start app: {package}",
                        package=package,
                        activity=activity
                    )
                    self._ctx.write_event_to_stream(start_app_event)
                
                return message
            else:
                error_msg = response.get("error", "Unknown error")
                return f"Error: {error_msg}"
                
        except TimeoutError as e:
            return f"Error: Timeout - {str(e)}"
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error starting app: {error}", error=e)
            return f"Error: {str(e)}"
    
    def take_screenshot(self, hide_overlay: bool = True) -> Tuple[str, bytes]:
        """
        截屏
        
        Args:
            hide_overlay: 是否隐藏覆盖层（默认True）
            
        Returns:
            元组 (format, bytes)
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "Taking screenshot")
            
            response = self._sync_wait(
                self._send_request_and_wait("take_screenshot", {
                    "hide_overlay": hide_overlay
                })
            )
            
            if response.get("status") == "success":
                # 获取截图数据（Base64编码）
                image_data_base64 = response.get("image_data", "")
                if not image_data_base64:
                    raise ValueError("No image data in response")
                
                # 解码Base64
                image_bytes = base64.b64decode(image_data_base64)
                img_format = response.get("format", "PNG")
                
                # 存储截图
                self.screenshots.append({
                    "timestamp": time.time(),
                    "image_data": image_bytes,
                    "format": img_format,
                })
                self.last_screenshot = image_bytes
                
                LoggingUtils.log_debug("WebSocketTools", "Screenshot taken successfully, size: {size} bytes", 
                                     size=len(image_bytes))
                return (img_format, image_bytes)
            else:
                error_msg = response.get("error", "Unknown error")
                raise ValueError(f"Failed to take screenshot: {error_msg}")
                
        except TimeoutError as e:
            LoggingUtils.log_error("WebSocketTools", "Timeout taking screenshot: {error}", error=e)
            raise ValueError(f"Timeout taking screenshot: {str(e)}")
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error taking screenshot: {error}", error=e)
            raise
    
    def list_packages(self, include_system_apps: bool = False) -> List[str]:
        """
        列出应用包名
        
        Args:
            include_system_apps: 是否包含系统应用
            
        Returns:
            包名列表
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "Listing packages (include_system: {include_system})", 
                                 include_system=include_system_apps)
            
            response = self._sync_wait(
                self._send_request_and_wait("list_packages", {
                    "include_system_apps": include_system_apps
                })
            )
            
            if response.get("status") == "success":
                packages = response.get("packages", [])
                LoggingUtils.log_debug("WebSocketTools", "Found {count} packages", count=len(packages))
                return packages
            else:
                error_msg = response.get("error", "Unknown error")
                LoggingUtils.log_error("WebSocketTools", "Error listing packages: {error}", error=error_msg)
                return []
                
        except TimeoutError:
            LoggingUtils.log_error("WebSocketTools", "Timeout listing packages")
            return []
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error listing packages: {error}", error=e)
            return []
    
    def remember(self, information: str) -> str:
        """
        记住信息
        
        Args:
            information: 要记住的信息
            
        Returns:
            确认消息
        """
        self.memory.append(information)
        LoggingUtils.log_debug("WebSocketTools", "Remembered information: {info}", info=information[:50])
        return f"Remembered: {information[:50]}"
    
    def get_memory(self) -> List[str]:
        """
        获取记忆
        
        Returns:
            记忆列表
        """
        return self.memory.copy()
    
    def complete(self, success: bool, reason: str = "") -> None:
        """
        完成任务
        
        Args:
            success: 是否成功
            reason: 原因
        """
        self.success = success
        self.reason = reason
        self.finished = True
        LoggingUtils.log_info("WebSocketTools", "Task completed: success={success}, reason={reason}", 
                            success=success, reason=reason)

