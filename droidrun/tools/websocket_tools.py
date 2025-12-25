"""
WebSocket Tools - 通过 WebSocket 与 APP 端通信的工具实现
"""
import asyncio
import json
import base64
import time
import logging
import uuid
import os
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from pathlib import Path
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
        timeout: int = 5,
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
        
        # a11y_tree 导出配置
        self.export_a11y_tree = False
        self.a11y_export_dir = "./a11y_exports"
        self.a11y_export_counter = 0
        
        if config_manager:
            self.export_a11y_tree = config_manager.get("tools.export_a11y_tree", False)
            self.a11y_export_dir = config_manager.get("tools.a11y_export_dir", "./a11y_exports")
            
            if self.export_a11y_tree:
                Path(self.a11y_export_dir).mkdir(parents=True, exist_ok=True)
                LoggingUtils.log_info("WebSocketTools", "a11y_tree export enabled, directory: {dir}", 
                                    dir=self.a11y_export_dir)
        
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.request_counter = 0
        self._request_lock = asyncio.Lock()
        
        self._ctx = None
        
        self.clickable_elements_cache: List[Dict[str, Any]] = []
        self.last_screenshot = None
        self.reason = None
        self.success = None
        self.finished = False
        
        self.memory: List[str] = []
        self.screenshots: List[Dict[str, Any]] = []
        self.save_trajectories = "none"
        
        # Phase 4: 当前任务ID（由 DroidAgent 注入，用于 ask_user）
        self._current_task_id: Optional[str] = None
        
        # Phase 3: 交互管理器（WebSocket 回调将在后续设置）
        from droidrun.agent.interaction import InteractionManager
        self.interaction_manager = InteractionManager(websocket_send_callback=self._send_websocket_message)
    
    def _set_context(self, ctx: Context):
        self._ctx = ctx
    
    def _generate_request_id(self) -> str:
        """生成请求ID"""
        self.request_counter += 1
        return f"{self.device_id}_{self.request_counter}_{uuid.uuid4().hex[:8]}"
    
    async def _send_websocket_message(self, message: Dict[str, Any]) -> None:
        """发送 WebSocket 消息（用于 InteractionManager 回调）
        
        Args:
            message: 要发送的消息字典
        """
        try:
            # 通过 session_manager 发送消息到指定设备
            success = await self.session_manager.send_to_device(self.device_id, message)
            if success:
                LoggingUtils.log_debug(
                    "WebSocketTools",
                    "Message sent via WebSocket: type={type}",
                    type=message.get("type")
                )
            else:
                LoggingUtils.log_error(
                    "WebSocketTools",
                    "Failed to send message to device {device_id}",
                    device_id=self.device_id
                )
                raise RuntimeError(f"Failed to send message to device {self.device_id}")
        except Exception as e:
            LoggingUtils.log_error(
                "WebSocketTools",
                "Failed to send WebSocket message: {error}",
                error=str(e)
            )
            raise
    
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
        
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        
        async with self._request_lock:
            self.pending_requests[request_id] = future
        
        request_message = MessageProtocol.create_command_message(
            command=command,
            params=params,
            request_id=request_id,
            device_id=self.device_id
        )
        
        try:
            send_start_time = time.time()
            
            success = await self.session_manager.send_to_device(self.device_id, request_message)
            if not success:
                async with self._request_lock:
                    self.pending_requests.pop(request_id, None)
                raise ValueError(f"Failed to send request to device {self.device_id}")
            
            try:
                if command in {"tap_by_index", "tap", "scroll", "input_text", "swipe", "press_key", "start_app", "drag"}:
                    await asyncio.sleep(0)
            except Exception:
                pass
            
            try:
                response = await asyncio.wait_for(future, timeout=timeout)
                
                execution_time = time.time() - send_start_time
                receive_timestamp = time.strftime("%H:%M:%S", time.localtime())
                if command != "get_state":
                    LoggingUtils.log_info("WebSocketTools", "✅ 移动端完成操作: {cmd} at {time}, 耗时: {duration:.2f}s", 
                                        cmd=command, time=receive_timestamp, duration=execution_time)
                
                if isinstance(response, dict) and "data" in response:
                    return response["data"]
                return response
            except asyncio.TimeoutError:
                async with self._request_lock:
                    self.pending_requests.pop(request_id, None)
                try:
                    waited_ms = int((time.time() - t_create) * 1000)
                    timeout_timestamp = time.strftime("%H:%M:%S", time.localtime())
                    LoggingUtils.log_error("WebSocketTools", "⏱️ [{time}] 命令超时 | command={cmd} | 等待={ms}ms | 超时阈值={to}s | request_id={rid}", 
                                         time=timeout_timestamp, cmd=command, ms=waited_ms, to=timeout, rid=request_id)
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
        
        Args:
            response_data: 响应数据字典，应包含 request_id 字段
        """
        request_id = response_data.get("request_id")
        if not request_id:
            LoggingUtils.log_warning("WebSocketTools", "Response missing request_id, ignoring")
            return
        
        try:
            future = self.pending_requests.get(request_id)
            if future and not future.done():
                future_loop = getattr(future, '_loop', None)
                
                if response_data.get("status") == "error":
                    error_msg = response_data.get("error", "Unknown error")
                    if future_loop and future_loop.is_running():
                        future_loop.call_soon_threadsafe(future.set_exception, ValueError(error_msg))
                    else:
                        future.set_exception(ValueError(error_msg))
                else:
                    if future_loop and future_loop.is_running():
                        future_loop.call_soon_threadsafe(future.set_result, response_data)
                    else:
                        future.set_result(response_data)
                self.pending_requests.pop(request_id, None)
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error handling response for request {rid}: {err}", 
                                 rid=request_id, err=e)
    
    def _sync_wait(self, coro):
        """
        同步等待异步操作
        
        Args:
            coro: 协程对象
            
        Returns:
            协程的返回值
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                try:
                    return future.result(timeout=self.timeout)
                except concurrent.futures.TimeoutError:
                    raise TimeoutError(f"Operation timed out after {self.timeout} seconds")
            else:
                return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)
    
    def _export_a11y_tree_to_json(self, a11y_tree: List[Dict[str, Any]]) -> None:
        """
        将 a11y_tree 导出为 JSON 文件
        
        Args:
            a11y_tree: 可访问性树数据
        """
        if not self.export_a11y_tree or not a11y_tree:
            return
        
        try:
            self.a11y_export_counter += 1
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"a11y_tree_{timestamp}_{self.a11y_export_counter:04d}.json"
            filepath = os.path.join(self.a11y_export_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(a11y_tree, f, ensure_ascii=False, indent=2)
            
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Failed to export a11y_tree: {error}", error=e)
    
    async def get_state_async(self, include_screenshot: bool = True) -> Dict[str, Any]:
        """
        异步获取设备状态
        """
        try:
            get_state_start = time.time()
            response = await self._send_request_and_wait("get_state", {"include_screenshot": include_screenshot})

            if response.get("status") == "error":
                error_msg = response.get("error", "Unknown error")
                return {"error": "Error", "message": error_msg}

            if "a11y_tree" not in response and "a11y_ref" not in response:
                return {"error": "Missing Data", "message": "a11y_tree/a11y_ref not found in response"}
            if "phone_state" not in response:
                return {"error": "Missing Data", "message": "phone_state not found in response"}

            def filter_children_recursive(children):
                result = []
                for c in children:
                    filtered = {k: v for k, v in c.items() if k != "type"}
                    if "children" in c:
                        filtered["children"] = filter_children_recursive(c["children"])
                    result.append(filtered)
                return result
            
            elements = response.get("a11y_tree", [])
            filtered_elements = []
            
            if isinstance(elements, list) and elements:
                for element in elements:
                    filtered_element = {k: v for k, v in element.items() if k != "type"}
                    if "children" in element:
                        filtered_element["children"] = filter_children_recursive(element["children"])
                    filtered_elements.append(filtered_element)
                self.clickable_elements_cache = filtered_elements
                
                self._export_a11y_tree_to_json(filtered_elements)
            

            result = {
                "a11y_tree": filtered_elements,
                "phone_state": response.get("phone_state", {}),
            }
            
            if "screenshot_base64" in response:
                result["screenshot_base64"] = response.get("screenshot_base64")
                self.last_screenshot = response.get("screenshot_base64")
            
            get_state_duration = time.time() - get_state_start
            # 只使用 LoggingUtils，移除 print 重复
            LoggingUtils.log_info("Performance", "⏱️ get_state total: {duration:.2f}s (elements: {count})", 
                                duration=get_state_duration, count=len(filtered_elements))
            
            return result
        except TimeoutError as e:
            LoggingUtils.log_error("WebSocketTools", "Timeout getting state: {error}", error=e)
            return {"error": "Timeout", "message": str(e)}
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error getting state: {error}", error=e)
            return {"error": "Error", "message": str(e)}

    async def get_state(self, include_screenshot: bool = True) -> Dict[str, Any]:
        """
        获取设备状态
        
        Returns:
            包含 'a11y_tree' 和 'phone_state' 的字典
        """
        try:
            response = await self.get_state_async(include_screenshot=include_screenshot)
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

    async def refresh_ui(self) -> str:
        """
        刷新当前 UI 状态，获取最新的界面元素列表。
        
        使用场景：
        - 执行了某个操作后（如点击、输入），UI 可能发生变化
        - 需要查看最新的 UI 元素以继续后续操作
        - 例如：点击日期字段后，日期选择器出现，需要刷新 UI 才能看到选择器中的元素
        
        Returns:
            str: UI 元素的文本描述，包含所有可交互元素的信息
            
        Example:
            ```python
            # 点击日期字段
            tap_by_index(111)
            
            # 刷新 UI 以查看新出现的日期选择器
            ui_info = refresh_ui()
            
            # 现在可以看到日期选择器中的元素并进行操作
            tap_by_index(165)  # 点击日期
            ```
        """
        try:
            state = await self.get_state_async(include_screenshot=False)
            
            if "error" in state:
                error_msg = state.get("message", "Unknown error")
                return f"Error refreshing UI: {error_msg}"
            
            a11y_tree = state.get("a11y_tree", [])
            
            if not a11y_tree:
                return "UI refreshed, but no elements found"
            
            element_count = len(a11y_tree)
            ui_description = f"UI refreshed successfully. Found {element_count} top-level elements.\n"
            ui_description += "You can now see the updated UI elements and continue your operations.\n"
            ui_description += f"Total clickable elements in cache: {len(self.clickable_elements_cache)}"
            
            return ui_description
            
        except Exception as e:
            return f"Error refreshing UI: {str(e)}"

    @Tools.ui_action
    async def tap_by_index(self, index: int) -> str:
        """
        通过索引点击元素
        
        Args:
            index: 元素索引
            
        Returns:
            操作结果消息
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "[async] Tapping element at index {index}", index=index)
            if not self.clickable_elements_cache:
                return "Error: No UI elements cached. Call get_state first."
            response = await self._send_request_and_wait("tap_by_index", {"index": index})
            status = response.get("status") or "success"
            if status == "success":
                message = response.get("message", f"Tapped element at index {index}")
                
                if self._ctx:
                    element = self._find_element_by_index(index)
                    if element:
                        llm_comment = None
                        if hasattr(self, '_action_comments') and self._action_comments:
                            for func_call, comment in self._action_comments.items():
                                if f'tap_by_index({index})' in func_call:
                                    llm_comment = comment
                                    break
                        
                        if llm_comment and message:
                            import re
                            match = re.search(r'\(([^)]+)\)\s+at\s+coordinates\s+\(([^)]+)\)', message)
                            if match:
                                class_name = match.group(1)
                                coords = match.group(2)
                                final_description = f"Tap element at index {index}: {llm_comment} ({class_name}) at coordinates ({coords})"
                            else:
                                final_description = f"{llm_comment} - {message}"
                        else:
                            final_description = message
                        
                        tap_event = TapActionEvent(
                            action_type="tap",
                            description=final_description,
                            specific_behavior=llm_comment,
                            x=response.get("x", 0),
                            y=response.get("y", 0),
                            element_index=index,
                            element_text=element.get("text", ""),
                            element_bounds=element.get("bounds", ""),
                        )
                        self._ctx.write_event_to_stream(tap_event)
                        
                        if (hasattr(self, '_manual_event_recording') and self._manual_event_recording 
                            and hasattr(self, '_trajectory') and self._trajectory):
                            self._trajectory.macro.append(tap_event)
                
                return message
            else:
                error_msg = response.get("error", "Unknown error")
                return f"Error: {error_msg}"
        except TimeoutError as e:
            LoggingUtils.log_error("WebSocketTools", "Timeout tapping element at index {index}: {error}", index=index, error=e)
            return f"Error: Timeout tapping element at index {index}: {str(e)}"
        except Exception as e:
            LoggingUtils.log_error("WebSocketTools", "Error tapping element at index {index}: {error}", index=index, error=e)
            return f"Error: Failed to tap element at index {index}: {str(e)}"
    
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
    async def swipe(
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
            LoggingUtils.log_debug("WebSocketTools", "[async] Swiping from ({start_x}, {start_y}) to ({end_x}, {end_y})", 
                                 start_x=start_x, start_y=start_y, end_x=end_x, end_y=end_y)
            
            response = await self._send_request_and_wait("swipe", {
                "start_x": start_x,
                "start_y": start_y,
                "end_x": end_x,
                "end_y": end_y,
                "duration_ms": duration_ms
            })
            
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
    async def input_text(self, text: str, index: Optional[int] = None) -> str:
        """
        输入文本
        
        Args:
            text: 要输入的文本
            index: 可选的元素索引，如果提供则由移动端直接在该元素中输入文本
            
        Returns:
            操作结果消息
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "[async] Inputting text: {text} {index_info}", 
                                 text=text[:50], index_info=f"at index {index}" if index is not None else "")
            
            encoded_text = base64.b64encode(text.encode()).decode()
            
            params = {
                "text": text,
                "base64_text": encoded_text
            }
            if index is not None:
                params["index"] = index
                
            response = await self._send_request_and_wait("input_text", params)
            
            status = response.get("status", "success")
            if status == "success" or not response.get("error"):
                message = response.get("message", f"Text input completed: {text[:50]}")
                
                llm_comment = None
                if hasattr(self, '_action_comments') and self._action_comments:
                    # 调试：输出所有 input_text 相关的注释
                    input_text_comments = {k: v for k, v in self._action_comments.items() if 'input_text(' in k}
                    if input_text_comments:
                        LoggingUtils.log_debug("WebSocketTools", "Available input_text comments: {comments}", 
                                             comments=list(input_text_comments.keys()))
                        LoggingUtils.log_debug("WebSocketTools", "Searching for: text[:20]=\"{text}\", index={idx}", 
                                             text=text[:20], idx=index)
                    
                    for func_call, comment in self._action_comments.items():
                        if 'input_text(' in func_call and f'"{text[:20]}' in func_call:
                            llm_comment = comment
                            LoggingUtils.log_debug("WebSocketTools", "✅ Matched by text: {func_call}", func_call=func_call)
                            break
                        elif 'input_text(' in func_call and index is not None and f'{index}' in func_call:
                            llm_comment = comment
                            LoggingUtils.log_debug("WebSocketTools", "✅ Matched by index: {func_call}", func_call=func_call)
                            break
                
                final_description = f"Input text: '{text[:50]}{'...' if len(text) > 50 else ''}'" + (f" at index {index}" if index is not None else "")
                input_event = InputTextActionEvent(
                    action_type="input_text",
                    description=final_description,
                    specific_behavior=llm_comment,
                    text=text,
                    index=index
                )
                
                if self._ctx:
                    self._ctx.write_event_to_stream(input_event)
                
                if (hasattr(self, '_manual_event_recording') and self._manual_event_recording 
                    and hasattr(self, '_trajectory') and self._trajectory):
                    self._trajectory.macro.append(input_event)
                
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
    async def back(self) -> str:
        """
        按返回键
        
        Returns:
            操作结果消息
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "[async] Pressing back button")
            
            response = await self._send_request_and_wait("back", {})
            
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
    async def press_key(self, keycode: int) -> str:
        """
        按键操作
        
        Args:
            keycode: 按键代码
            
        Returns:
            操作结果消息
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "[async] Pressing key: {keycode}", keycode=keycode)
            
            response = await self._send_request_and_wait("press_key", {"keycode": keycode})
            
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
    async def start_app(self, package: str, activity: str = "") -> str:
        """
        启动应用
        
        Args:
            package: 应用包名
            activity: Activity名称（可选）
            
        Returns:
            操作结果消息
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "[async] Starting app: {package}", package=package)
            
            params = {"package": package}
            if activity:
                params["activity"] = activity
                
            response = await self._send_request_and_wait("start_app", params)
            
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
    
    async def take_screenshot(self, hide_overlay: bool = True) -> Tuple[str, bytes]:
        """
        截屏
        
        Args:
            hide_overlay: 是否隐藏覆盖层
            
        Returns:
            (image_format, image_data) 元组
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "[async] Taking screenshot")
            
            response = await self._send_request_and_wait("take_screenshot", {"hide_overlay": hide_overlay})
            
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
    
    async def list_packages(self, include_system_apps: bool = False) -> List[str]:
        """
        列出应用包名
        
        Args:
            include_system_apps: 是否包含系统应用
            
        Returns:
            应用包名列表
        """
        try:
            LoggingUtils.log_debug("WebSocketTools", "[async] Listing packages")
            
            response = await self._send_request_and_wait("list_packages", {"include_system_apps": include_system_apps})
            
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
    
    async def remember(self, information: str) -> str:
        """
        记住信息
        
        Args:
            information: 要记住的信息
            
        Returns:
            操作结果消息
        """
        self.memory.append(information)
        LoggingUtils.log_debug("WebSocketTools", "Remembered information: {info}", info=information[:50])
        return f"Remembered: {information[:50]}"
    
    async def get_memory(self) -> List[str]:
        """
        获取记忆
        
        Returns:
            记忆信息列表
        """
        return self.memory.copy()
    
    async def complete(self, success: bool, reason: str = "") -> None:
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
    
    async def ask_user(
        self,
        question: str,
        question_type: str = "text",
        options: List[str] = None,
        default_value: str = None,
        timeout_seconds: float = 60.0
    ) -> str:
        """
        询问用户问题（Phase 3: 交互式执行）
        
        这是 LLM 可以调用的工具方法，用于在执行过程中询问用户。
        
        使用场景：
        - 需要用户确认关键操作
        - 需要用户提供缺失的信息
        - 需要用户从多个选项中选择
        - 需要用户解决歧义
        
        Args:
            question: 要询问的问题（清晰、具体）
            question_type: 问题类型
                - "text": 文本输入（默认）
                - "choice": 从选项中选择
                - "confirm": 是/否确认
            options: 选项列表（用于 choice 类型）
            default_value: 默认值（超时时使用）
            timeout_seconds: 超时秒数（默认 60 秒）
        
        Returns:
            用户的回答字符串
        
        Example:
            >>> # 询问文本
            >>> name = await ask_user("请输入您的姓名：", default_value="用户")
            >>> 
            >>> # 询问选择
            >>> choice = await ask_user(
            ...     "请选择日期格式：",
            ...     question_type="choice",
            ...     options=["2025-12-05", "12/05/2025", "05-Dec-2025"],
            ...     default_value="2025-12-05"
            ... )
            >>> 
            >>> # 询问确认
            >>> confirmed = await ask_user(
            ...     "确认要删除此项吗？",
            ...     question_type="confirm",
            ...     default_value="no"
            ... )
        
        Note:
            这是一个非阻塞方法，会立即返回用户答案或超时后的默认值。
            问题会通过 WebSocket 发送到 Android 端显示对话框。
        """
        # 验证参数
        if not question or not question.strip():
            raise ValueError("Question cannot be empty")
        
        if question_type not in ["text", "choice", "confirm"]:
            raise ValueError(f"Invalid question_type: {question_type}. Must be 'text', 'choice', or 'confirm'")
        
        if question_type == "choice" and not options:
            raise ValueError("Options are required for 'choice' question type")
        
        # 获取任务ID（优先使用 DroidAgent 注入的 task_id）
        task_id = getattr(self, '_current_task_id', None) or f"task_{self.device_id}_{uuid.uuid4().hex[:8]}"
        
        # 确保任务已注册
        from droidrun.agent.interaction import TaskExecutionContext
        if not self.interaction_manager.get_task(task_id):
            # 创建任务上下文（如果 DroidAgent 没有注入，则创建临时任务）
            temp_task = TaskExecutionContext(task_id, f"交互式任务 (device: {self.device_id})")
            self.interaction_manager.register_task(temp_task)
            LoggingUtils.log_debug(
                "WebSocketTools",
                "Created temporary task context: {task_id}",
                task_id=task_id
            )
        
        try:
            # 通过 InteractionManager 发送问题
            question_id = await self.interaction_manager.ask_user_async(
                task_id=task_id,
                question_text=question,
                question_type=question_type,
                options=options or [],
                default_value=default_value or "",
                timeout_seconds=timeout_seconds,
                resume_context=None,
                on_answer_callback=None,
                on_timeout_callback=None
            )
            
            LoggingUtils.log_info(
                "WebSocketTools",
                "Question sent via InteractionManager: {question} (id: {id})",
                question=question[:50],
                id=question_id
            )
            
            # 获取问题对象并等待 Future
            pending_question = self.interaction_manager.get_question(question_id)
            if not pending_question or not pending_question.future:
                raise RuntimeError(f"Failed to create question: {question_id}")
            
            # 等待用户回答（通过 Future）
            answer = await pending_question.future
            
            LoggingUtils.log_info(
                "WebSocketTools",
                "User answered: {answer}",
                answer=answer
            )
            
            return str(answer) if answer is not None else (default_value or "")
        
        except asyncio.TimeoutError:
            # 超时，返回默认值
            LoggingUtils.log_warning(
                "WebSocketTools",
                "Question timeout after {timeout}s, using default: {default}",
                timeout=timeout_seconds,
                default=default_value
            )
            return default_value or ""
        
        except Exception as e:
            # 其他错误
            LoggingUtils.log_error(
                "WebSocketTools",
                "Error asking user: {error}",
                error=str(e)
            )
            return default_value or ""
    
    async def handle_user_answer(self, answer_message: Dict[str, Any]) -> bool:
        """处理来自 Android 端的用户答案
        
        这个方法应该在 WebSocket 消息处理器中被调用，
        当收到 "user_answer" 类型的消息时。
        
        Args:
            answer_message: 答案消息
                {
                    "type": "user_answer",
                    "question_id": "q-abc123",
                    "answer": "用户的回答",
                    "timestamp": 1234567890
                }
        
        Returns:
            True 如果成功处理，False 如果失败
        
        Example:
            >>> # 在 WebSocket 消息处理器中
            >>> if message["type"] == "user_answer":
            >>>     await tools.handle_user_answer(message)
        """
        try:
            question_id = answer_message.get("question_id")
            answer = answer_message.get("answer")
            
            if not question_id:
                LoggingUtils.log_error(
                    "WebSocketTools",
                    "Invalid answer message: missing question_id"
                )
                return False
            
            # 路由到 InteractionManager
            success = await self.interaction_manager.provide_answer(
                question_id=question_id,
                answer=answer,
                additional_data=answer_message
            )
            
            if success:
                LoggingUtils.log_info(
                    "WebSocketTools",
                    "User answer processed: question_id={id}, answer={answer}",
                    id=question_id,
                    answer=answer
                )
            else:
                LoggingUtils.log_warning(
                    "WebSocketTools",
                    "Question not found: {id}",
                    id=question_id
                )
            
            return success
        
        except Exception as e:
            LoggingUtils.log_error(
                "WebSocketTools",
                "Error handling user answer: {error}",
                error=str(e)
            )
            return False
    

