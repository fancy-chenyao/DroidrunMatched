"""
WebSocketTools 异步方法补丁文件
用于将所有同步方法改为异步实现
"""

from droidrun.agent.common.events import InputTextActionEvent
from droidrun.agent.utils.logging_utils import LoggingUtils

# 以下是所有需要修改的同步方法，改为异步后直接调用对应的 _async 方法

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
        LoggingUtils.log_error("WebSocketTools", "Timeout tapping element at index {index}: {error}", index=index, error=e)
        return f"Error: Timeout tapping element at index {index}: {str(e)}"
    except Exception as e:
        LoggingUtils.log_error("WebSocketTools", "Error tapping element at index {index}: {error}", index=index, error=e)
        return f"Error: Failed to tap element at index {index}: {str(e)}"

async def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 300) -> bool:
    """
    滑动操作
    
    Args:
        start_x: 起始X坐标
        start_y: 起始Y坐标
        end_x: 结束X坐标
        end_y: 结束Y坐标
        duration_ms: 滑动持续时间（毫秒）
        
    Returns:
        是否成功
    """
    try:
        LoggingUtils.log_debug("WebSocketTools", "[async] Swiping from ({x1},{y1}) to ({x2},{y2})", 
                              x1=start_x, y1=start_y, x2=end_x, y2=end_y)
        response = await self._send_request_and_wait("swipe", {
            "start_x": start_x,
            "start_y": start_y,
            "end_x": end_x,
            "end_y": end_y,
            "duration_ms": duration_ms
        })
        return response.get("status") == "success"
    except TimeoutError as e:
        LoggingUtils.log_error("WebSocketTools", "Timeout swiping: {error}", error=e)
        return False
    except Exception as e:
        LoggingUtils.log_error("WebSocketTools", "Error swiping: {error}", error=e)
        return False

async def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 3000) -> bool:
    """
    拖拽操作
    
    Args:
        start_x: 起始X坐标
        start_y: 起始Y坐标
        end_x: 结束X坐标
        end_y: 结束Y坐标
        duration_ms: 拖拽持续时间（毫秒）
        
    Returns:
        是否成功
    """
    try:
        LoggingUtils.log_debug("WebSocketTools", "[async] Dragging from ({x1},{y1}) to ({x2},{y2})", 
                              x1=start_x, y1=start_y, x2=end_x, y2=end_y)
        response = await self._send_request_and_wait("drag", {
            "start_x": start_x,
            "start_y": start_y,
            "end_x": end_x,
            "end_y": end_y,
            "duration_ms": duration_ms
        })
        return response.get("status") == "success"
    except TimeoutError as e:
        LoggingUtils.log_error("WebSocketTools", "Timeout dragging: {error}", error=e)
        return False
    except Exception as e:
        LoggingUtils.log_error("WebSocketTools", "Error dragging: {error}", error=e)
        return False

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
        
        params = {"text": text}
        # 直接将 index 信息传递给移动端，由移动端处理元素定位和输入
        if index is not None:
            params["index"] = index
            
        response = await self._send_request_and_wait("input_text", params)
        
        # 检查响应状态，兼容不同的响应格式
        status = response.get("status", "success")  # 默认为 success
        if status == "success" or not response.get("error"):
            message = response.get("message", f"Text input completed: {text[:50]}")
            
            # 创建 InputTextActionEvent
            input_event = InputTextActionEvent(
                action_type="input_text",
                description=f"Input text: '{text[:50]}{'...' if len(text) > 50 else ''}'" + (f" at index {index}" if index is not None else ""),
                text=text,
                index=index
            )
            
            if self._ctx:
                self._ctx.write_event_to_stream(input_event)
            else:
                LoggingUtils.log_warning("WebSocketTools", "⚠️ Context is None, InputTextActionEvent not recorded")
            
            return message
        else:
            error_msg = response.get("error", "Unknown error")
            return f"Error: {error_msg}"
    except TimeoutError as e:
        LoggingUtils.log_error("WebSocketTools", "Timeout inputting text: {error}", error=e)
        return f"Error: Timeout inputting text: {str(e)}"
    except Exception as e:
        LoggingUtils.log_error("WebSocketTools", "Error inputting text: {error}", error=e)
        return f"Error: Failed to input text: {str(e)}"

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
            return message
        else:
            error_msg = response.get("error", "Unknown error")
            return f"Error: {error_msg}"
    except TimeoutError as e:
        LoggingUtils.log_error("WebSocketTools", "Timeout pressing back: {error}", error=e)
        return f"Error: Timeout pressing back: {str(e)}"
    except Exception as e:
        LoggingUtils.log_error("WebSocketTools", "Error pressing back: {error}", error=e)
        return f"Error: Failed to press back: {str(e)}"

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
            return message
        else:
            error_msg = response.get("error", "Unknown error")
            return f"Error: {error_msg}"
    except TimeoutError as e:
        LoggingUtils.log_error("WebSocketTools", "Timeout pressing key: {error}", error=e)
        return f"Error: Timeout pressing key: {str(e)}"
    except Exception as e:
        LoggingUtils.log_error("WebSocketTools", "Error pressing key: {error}", error=e)
        return f"Error: Failed to press key: {str(e)}"

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
            message = response.get("message", f"App {package} started")
            return message
        else:
            error_msg = response.get("error", "Unknown error")
            return f"Error: {error_msg}"
    except TimeoutError as e:
        LoggingUtils.log_error("WebSocketTools", "Timeout starting app: {error}", error=e)
        return f"Error: Timeout starting app: {str(e)}"
    except Exception as e:
        LoggingUtils.log_error("WebSocketTools", "Error starting app: {error}", error=e)
        return f"Error: Failed to start app: {str(e)}"

async def take_screenshot(self) -> tuple:
    """
    截图
    
    Returns:
        (image_format, image_data) 元组
    """
    try:
        LoggingUtils.log_debug("WebSocketTools", "[async] Taking screenshot")
        response = await self._send_request_and_wait("take_screenshot", {})
        
        if response.get("status") == "success":
            image_data = response.get("image_data")
            img_format = response.get("format", "png")
            
            if not image_data:
                raise ValueError("No image data in response")
            
            # 解码base64
            import base64
            image_bytes = base64.b64decode(image_data)
            
            # 更新缓存
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
    except Exception as e:
        LoggingUtils.log_error("WebSocketTools", "Error taking screenshot: {error}", error=e)
        raise

async def get_state(self, include_screenshot: bool = True) -> Dict[str, Any]:
    """
    获取设备状态
    
    Args:
        include_screenshot: 是否包含截图
        
    Returns:
        设备状态字典
    """
    try:
        LoggingUtils.log_debug("WebSocketTools", "[async] Getting state from device {device_id}", device_id=self.device_id)
        response = await self._send_request_and_wait("get_state", {"include_screenshot": include_screenshot})

        if response.get("status") == "error":
            error_msg = response.get("error", "Unknown error")
            LoggingUtils.log_error("WebSocketTools", "Error in get_state response: {error}", error=error_msg)
            return {"error": "Error", "message": error_msg}

        # 验证必需字段（允许仅返回引用）
        required_fields = ["a11y_tree", "phone_state"]
        for field in required_fields:
            if field not in response:
                LoggingUtils.log_error("WebSocketTools", "Missing required field '{field}' in get_state response", field=field)
                return {"error": "Error", "message": f"Missing required field: {field}"}

        # 更新缓存
        self.a11y_tree_cache = response.get("a11y_tree", {})
        self.phone_state_cache = response.get("phone_state", {})
        self.clickable_elements_cache = self._extract_clickable_elements(self.a11y_tree_cache)

        # 处理截图（如果存在）
        if include_screenshot and "screenshot_ref" in response:
            screenshot_ref = response["screenshot_ref"]
            if screenshot_ref in self.screenshots:
                self.last_screenshot = self.screenshots[screenshot_ref]["image_data"]
            else:
                LoggingUtils.log_warning("WebSocketTools", "Screenshot reference {ref} not found in cache", ref=screenshot_ref)

        # 返回完整状态（包含截图数据，如果需要）
        result = {
            "a11y_tree": self.a11y_tree_cache,
            "phone_state": self.phone_state_cache,
            "clickable_elements": self.clickable_elements_cache,
        }

        if include_screenshot:
            if "screenshot_ref" in response:
                result["screenshot_ref"] = response["screenshot_ref"]
            elif self.last_screenshot:
                result["screenshot_base64"] = base64.b64encode(self.last_screenshot).decode('utf-8')

        return result

    except TimeoutError as e:
        LoggingUtils.log_error("WebSocketTools", "Timeout getting state: {error}", error=e)
        return {"error": "Error", "message": f"Timeout getting state: {str(e)}"}
    except Exception as e:
        LoggingUtils.log_error("WebSocketTools", "Error getting state: {error}", error=e)
        return {"error": "Error", "message": f"Error getting state: {str(e)}"}

async def list_packages(self, include_system_apps: bool = False) -> List[str]:
    """
    列出设备上的所有应用包
    
    Args:
        include_system_apps: 是否包含系统应用
        
    Returns:
        应用包名列表
    """
    try:
        LoggingUtils.log_debug("WebSocketTools", "[async] Listing packages (include_system={include})", include=include_system_apps)
        response = await self._send_request_and_wait("list_packages", {"include_system_apps": include_system_apps})
        if response.get("status") == "success":
            packages = response.get("packages", [])
            return packages
        else:
            error_msg = response.get("error", "Unknown error")
            LoggingUtils.log_error("WebSocketTools", "Error listing packages: {error}", error=error_msg)
            return []
    except TimeoutError as e:
        LoggingUtils.log_error("WebSocketTools", "Timeout listing packages: {error}", error=e)
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
    try:
        LoggingUtils.log_debug("WebSocketTools", "[async] Remembering information: {info}", info=information[:100])
        if not hasattr(self, 'memory'):
            self.memory = []
        self.memory.append(information)
        return f"Information remembered: {information[:100]}..."
    except Exception as e:
        LoggingUtils.log_error("WebSocketTools", "Error remembering information: {error}", error=e)
        return f"Error: Failed to remember information: {str(e)}"

async def get_memory(self) -> List[str]:
    """
    获取记忆中的信息
    
    Returns:
        记忆信息列表
    """
    try:
        LoggingUtils.log_debug("WebSocketTools", "[async] Getting memory")
        if not hasattr(self, 'memory'):
            self.memory = []
        return self.memory
    except Exception as e:
        LoggingUtils.log_error("WebSocketTools", "Error getting memory: {error}", error=e)
        return []

async def complete(self, success: bool, reason: str = "") -> None:
    """
    完成工具
    
    Args:
        success: 是否成功
        reason: 完成原因
    """
    try:
        LoggingUtils.log_debug("WebSocketTools", "[async] Completing task (success={success}, reason={reason})", 
                              success=success, reason=reason[:100])
        # 这里可以添加完成任务的逻辑，比如发送完成事件等
        if self._ctx:
            complete_event = TaskCompletionEvent(
                success=success,
                reason=reason
            )
            self._ctx.write_event_to_stream(complete_event)
    except Exception as e:
        LoggingUtils.log_error("WebSocketTools", "Error completing task: {error}", error=e)
