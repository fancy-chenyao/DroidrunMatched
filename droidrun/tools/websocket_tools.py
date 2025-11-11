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
        t_create = time.time()
        try:
            LoggingUtils.log_debug("WebSocketTools", "Create request {rid} cmd={cmd} timeout={to}s", rid=request_id, cmd=command, to=timeout)
        except Exception:
            pass
        
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
                    try:
                        waited_ms = int((time.time() - t_create) * 1000)
                        LoggingUtils.log_debug("WebSocketTools", "Request {rid} completed in {ms}ms (cmd={cmd})", rid=request_id, ms=waited_ms, cmd=command)
                    except Exception:
                        pass
                    return response["data"]
                try:
                    waited_ms = int((time.time() - t_create) * 1000)
                    LoggingUtils.log_debug("WebSocketTools", "Request {rid} completed in {ms}ms (cmd={cmd})", rid=request_id, ms=waited_ms, cmd=command)
                except Exception:
                    pass
                return response
            except asyncio.TimeoutError:
                async with self._request_lock:
                    self.pending_requests.pop(request_id, None)
                try:
                    waited_ms = int((time.time() - t_create) * 1000)
                    LoggingUtils.log_error("WebSocketTools", "Request {rid} timeout after {to}s (waited {ms}ms, cmd={cmd})", rid=request_id, to=timeout, ms=waited_ms, cmd=command)
                except Exception:
                    pass
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
                
                t0 = time.time()
                thread = threading.Thread(target=run_in_new_loop, daemon=True)
                try:
                    LoggingUtils.log_debug("WebSocketTools", "_sync_wait spawning thread and joining up to {secs}s", secs=self.timeout + 5)
                except Exception:
                    pass
                thread.start()
                thread.join(timeout=self.timeout + 5)  # 给一些额外时间
                join_ms = int((time.time() - t0) * 1000)
                try:
                    LoggingUtils.log_debug("WebSocketTools", "_sync_wait join elapsed {ms}ms", ms=join_ms)
                except Exception:
                    pass
                
                if thread.is_alive():
                    try:
                        LoggingUtils.log_error("WebSocketTools", "_sync_wait thread still alive after join timeout ({secs}s)", secs=self.timeout + 5)
                    except Exception:
                        pass
                    raise TimeoutError(f"Operation timed out after {self.timeout + 5} seconds")
                
                if 'exception' in exception_container:
                    raise exception_container['exception']
                if 'result' in result_container:
                    return result_container['result']
                raise RuntimeError("No result or exception from async operation")
            else:
                t0 = time.time()
                try:
                    LoggingUtils.log_debug("WebSocketTools", "_sync_wait blocking run_until_complete on idle loop")
                except Exception:
                    pass
                result = loop.run_until_complete(coro)
                try:
                    LoggingUtils.log_debug("WebSocketTools", "_sync_wait run_until_complete elapsed {ms}ms", ms=int((time.time()-t0)*1000))
                except Exception:
                    pass
                return result
        except RuntimeError:
            # 如果没有事件循环，创建一个新的
            t0 = time.time()
            try:
                LoggingUtils.log_debug("WebSocketTools", "_sync_wait using asyncio.run path")
            except Exception:
                pass
            result = asyncio.run(coro)
            try:
                LoggingUtils.log_debug("WebSocketTools", "_sync_wait asyncio.run elapsed {ms}ms", ms=int((time.time()-t0)*1000))
            except Exception:
                pass
            return result
    
    async def get_state_async(self, include_screenshot: bool = True) -> Dict[str, Any]:
        """
        异步获取设备状态（包含 a11y_tree 和 phone_state）。仅传引用，不回填大对象。
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "[async] Getting state from device {device_id}", device_id=self.device_id)
            response = await self._send_request_and_wait("get_state", {"include_screenshot": include_screenshot})

            if response.get("status") == "error":
                error_msg = response.get("error", "Unknown error")
                LoggingUtils.log_error("WebSocketTools", "Error in get_state response: {error}", error=error_msg)
                return {"error": "Error", "message": error_msg}

            # 验证必需字段（允许仅返回引用）
            if "a11y_tree" not in response and "a11y_ref" not in response:
                LoggingUtils.log_error("WebSocketTools", "Response missing a11y_tree/a11y_ref field")
                return {"error": "Missing Data", "message": "a11y_tree/a11y_ref not found in response"}
            if "phone_state" not in response:
                LoggingUtils.log_error("WebSocketTools", "Response missing phone_state field")
                return {"error": "Missing Data", "message": "phone_state not found in response"}

            # 内联 a11y_tree 时进行过滤，保持与 AdbTools 一致
            elements = response.get("a11y_tree", [])
            if isinstance(elements, list) and elements:
                filtered_elements = []
                for element in elements:
                    filtered_element = {k: v for k, v in element.items() if k != "type"}
                    if "children" in element:
                        def filter_children_recursive(children):
                            result = []
                            for c in children:
                                filtered = {k: v for k, v in c.items() if k != "type"}
                                if "children" in c:
                                    filtered["children"] = filter_children_recursive(c["children"])
                                result.append(filtered)
                            return result
                        filtered_element["children"] = filter_children_recursive(element["children"])
                    filtered_elements.append(filtered_element)
                self.clickable_elements_cache = filtered_elements
                result = {
                    "a11y_tree": filtered_elements,
                    "phone_state": response.get("phone_state", {}),
                    "elements": filtered_elements
                }
            else:
                # 仅引用返回 - 需要从 HTTP 服务器下载 a11y_tree 以更新 clickable_elements_cache
                a11y_ref = response.get("a11y_ref")
                if a11y_ref and isinstance(a11y_ref, dict):
                    file_path = a11y_ref.get("path")
                    if file_path:
                        try:
                            import json
                            with open(file_path, 'r', encoding='utf-8') as f:
                                a11y_data = json.load(f)
                                # 上传的 JSON 文件直接是 a11y_tree 数组，不是包含 a11y_tree 键的对象
                                if isinstance(a11y_data, list):
                                    elements = a11y_data
                                else:
                                    elements = a11y_data.get("a11y_tree", [])
                                if isinstance(elements, list) and elements:
                                    filtered_elements = []
                                    for element in elements:
                                        filtered_element = {k: v for k, v in element.items() if k != "type"}
                                        if "children" in element:
                                            def filter_children_recursive(children):
                                                result = []
                                                for c in children:
                                                    filtered = {k: v for k, v in c.items() if k != "type"}
                                                    if "children" in c:
                                                        filtered["children"] = filter_children_recursive(c["children"])
                                                    result.append(filtered)
                                                return result
                                            filtered_element["children"] = filter_children_recursive(element["children"])
                                        filtered_elements.append(filtered_element)
                                    self.clickable_elements_cache = filtered_elements
                                    LoggingUtils.log_debug("WebSocketTools", "[async] Updated clickable_elements_cache from a11y_ref, count={count}", count=len(filtered_elements))
                        except Exception as e:
                            LoggingUtils.log_warning("WebSocketTools", "Failed to load a11y_tree from {path}: {error}", path=file_path, error=e)
                
                result = {
                    "a11y_ref": response.get("a11y_ref"),
                    "screenshot_ref": response.get("screenshot_ref"),
                    "phone_state": response.get("phone_state", {}),
                }
            LoggingUtils.log_debug("WebSocketTools", "[async] State retrieved ok")
            return result
        except TimeoutError as e:
            LoggingUtils.log_error("WebSocketTools", "Timeout getting state: {error}", error=e)
            return {"error": "Timeout", "message": str(e)}
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error getting state: {error}", error=e)
            return {"error": "Error", "message": str(e)}

    def get_state(self, include_screenshot: bool = True) -> Dict[str, Any]:
        """
        获取设备状态（包含 a11y_tree 和 phone_state）
        
        Returns:
            包含 'a11y_tree' 和 'phone_state' 的字典
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "Getting state from device {device_id}", device_id=self.device_id)
            
            # 复用异步实现，避免重复逻辑与阻塞
            response = self._sync_wait(self.get_state_async(include_screenshot=include_screenshot))
            return response
            
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

    async def take_screenshot_async(self, hide_overlay: bool = True) -> Tuple[str, bytes]:
        """异步截屏，返回 (format, bytes)"""
        try:
            LoggingUtils.log_debug("WebSocketTools", "[async] Taking screenshot")
            response = await self._send_request_and_wait("take_screenshot", {"hide_overlay": hide_overlay})
            if response.get("status") == "success":
                image_data_base64 = response.get("image_data", "")
                if not image_data_base64:
                    raise ValueError("No image data in response")
                image_bytes = base64.b64decode(image_data_base64)
                img_format = response.get("format", "PNG")
                self.screenshots.append({
                    "timestamp": time.time(),
                    "image_data": image_bytes,
                    "format": img_format,
                })
                self.last_screenshot = image_bytes
                return (img_format, image_bytes)
            else:
                error_msg = response.get("error", "Unknown error")
                raise ValueError(f"Failed to take screenshot: {error_msg}")
        except TimeoutError as e:
            LoggingUtils.log_error("WebSocketTools", "Timeout taking screenshot: {error}", error=e)
            raise ValueError(f"Timeout taking screenshot: {str(e)}")
        except Exception:
            raise

    async def tap_by_index_async(self, index: int) -> str:
        """异步通过索引点击元素"""
        try:
            LoggingUtils.log_debug("WebSocketTools", "[async] Tapping element at index {index}", index=index)
            if not self.clickable_elements_cache:
                return "Error: No UI elements cached. Call get_state first."
            response = await self._send_request_and_wait("tap_by_index", {"index": index})
            status = response.get("status") or "success"
            if status == "success":
                message = response.get("message", f"Tapped element at index {index}")
                return message
            else:
                error_msg = response.get("error", "Unknown error")
                return f"Error: {error_msg}"
        except TimeoutError as e:
            return f"Error: Timeout - {str(e)}"
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error tapping element: {error}", error=e)
            return f"Error: {str(e)}"

    async def input_text_async(self, text: str) -> str:
        """异步输入文本"""
        try:
            LoggingUtils.log_debug("WebSocketTools", "[async] Inputting text: {text}", text=text[:50])
            encoded_text = base64.b64encode(text.encode()).decode()
            response = await self._send_request_and_wait("input_text", {
                "text": text,
                "base64_text": encoded_text
            })
            if response.get("status") == "success":
                message = response.get("message", f"Text input completed: {text[:50]}")
                return message
            else:
                error_msg = response.get("error", "Unknown error")
                return f"Error: {error_msg}"
        except TimeoutError as e:
            return f"Error: Timeout - {str(e)}"
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error inputting text: {error}", error=e)
            return f"Error: {str(e)}"

    async def swipe_async(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 300) -> bool:
        """异步滑动操作"""
        try:
            LoggingUtils.log_debug("WebSocketTools", "[async] Swiping from ({start_x}, {start_y}) to ({end_x}, {end_y})", 
                                 start_x=start_x, start_y=start_y, end_x=end_x, end_y=end_y)
            response = await self._send_request_and_wait("swipe", {
                "start_x": start_x,
                "start_y": start_y,
                "end_x": end_x,
                "end_y": end_y,
                "duration_ms": duration_ms
            })
            return response.get("status") == "success"
        except TimeoutError:
            LoggingUtils.log_error("WebSocketTools", "Timeout during swipe")
            return False
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error during swipe: {error}", error=e)
            return False

    async def press_key_async(self, keycode: int) -> str:
        """异步按键操作"""
        try:
            LoggingUtils.log_debug("WebSocketTools", "[async] Pressing key: {keycode}", keycode=keycode)
            response = await self._send_request_and_wait("press_key", {"keycode": keycode})
            if response.get("status") == "success":
                message = response.get("message", f"Key {keycode} pressed")
                return message
            else:
                error_msg = response.get("error", "Unknown error")
                return f"Error: {error_msg}"
        except TimeoutError as e:
            return f"Error: Timeout - {str(e)}"
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error pressing key: {error}", error=e)
            return f"Error: {str(e)}"

    async def start_app_async(self, package: str, activity: str = "") -> str:
        """异步启动应用"""
        try:
            LoggingUtils.log_debug("WebSocketTools", "[async] Starting app: {package} with activity: {activity}", 
                                 package=package, activity=activity)
            response = await self._send_request_and_wait("start_app", {
                "package": package,
                "activity": activity
            })
            if response.get("status") == "success":
                message = response.get("message", f"App started: {package}")
                return message
            else:
                error_msg = response.get("error", "Unknown error")
                return f"Error: {error_msg}"
        except TimeoutError as e:
            return f"Error: Timeout - {str(e)}"
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error starting app: {error}", error=e)
            return f"Error: {str(e)}"
    
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

