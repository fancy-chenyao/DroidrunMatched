from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
import logging
from typing import Tuple, Dict, Callable, Any, Optional
from functools import wraps
import sys

# Get a logger for this module
logger = logging.getLogger(__name__)


class Tools(ABC):
    """
    Abstract base class for all tools.
    This class provides a common interface for all tools to implement.
    """

    @staticmethod
    def ui_action(func):
        """
        Decorator to capture screenshots and UI states for actions that modify the UI.
        Now supports async functions.
        """
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            self = args[0]
            result = await func(*args, **kwargs)
            
            # Check if save_trajectories attribute exists and is set to "action"
            if hasattr(self, 'save_trajectories') and self.save_trajectories == "action":
                frame = sys._getframe(1)
                caller_globals = frame.f_globals
                
                step_screenshots = caller_globals.get('step_screenshots')
                step_ui_states = caller_globals.get('step_ui_states')
                
                # For async tools, we should use async methods if available
                if hasattr(self, 'get_state_async'):
                    if step_screenshots is not None:
                        # Use async screenshot if available
                        if hasattr(self, 'take_screenshot_async'):
                            step_screenshots.append((await self.take_screenshot_async())[1])
                        else:
                            step_screenshots.append(self.take_screenshot()[1])
                    if step_ui_states is not None:
                        step_ui_states.append(await self.get_state_async())
                else:
                    # Fallback to sync methods
                    if step_screenshots is not None:
                        step_screenshots.append(self.take_screenshot()[1])
                    if step_ui_states is not None:
                        step_ui_states.append(self.get_state())
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            self = args[0]
            result = func(*args, **kwargs)
            
            # Check if save_trajectories attribute exists and is set to "action"
            if hasattr(self, 'save_trajectories') and self.save_trajectories == "action":
                frame = sys._getframe(1)
                caller_globals = frame.f_globals
                
                step_screenshots = caller_globals.get('step_screenshots')
                step_ui_states = caller_globals.get('step_ui_states')
                
                # 避免在事件循环线程内调用同步方法导致阻塞：
                # 若工具实现了异步API（如 get_state_async），则不在装饰器里执行同步截图/取状态
                if not hasattr(self, 'get_state_async'):
                    if step_screenshots is not None:
                        step_screenshots.append(self.take_screenshot()[1])
                    if step_ui_states is not None:
                        step_ui_states.append(self.get_state())
            return result
        
        # Return appropriate wrapper based on whether function is async
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    @abstractmethod
    async def get_state(self) -> Dict[str, Any]:
        """
        Get the current state of the tool.
        """
        pass

    @abstractmethod
    async def tap_by_index(self, index: int) -> str:
        """
        Tap the element at the given index.
        """
        pass

    #@abstractmethod
    #async def tap_by_coordinates(self, x: int, y: int) -> bool:
    #    pass

    @abstractmethod
    async def swipe(
        self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 300
    ) -> bool:
        """
        Swipe from the given start coordinates to the given end coordinates.
        """
        pass

    @abstractmethod
    async def drag(
        self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 3000
    ) -> bool:
        """
        Drag from the given start coordinates to the given end coordinates.
        """
        pass

    @abstractmethod
    async def input_text(self, text: str, index: Optional[int] = None) -> str:
        """
        Input the given text into an input field.
        
        Args:
            text: Text to input
            index: Optional element index to target specific input field.
                  If provided, will directly input text into that element without needing to tap first.
                  Recommended usage: input_text("your text", element_index) for better efficiency.
        
        Examples:
            input_text("Hello")  # Input into currently focused field
            input_text("Beijing", 5)  # Input "Beijing" directly into element at index 5
        """
        pass

    @abstractmethod
    async def back(self) -> str:
        """
        Press the back button.
        """
        pass

    @abstractmethod
    async def press_key(self, keycode: int) -> str:
        """
        Enter the given keycode.
        """
        pass

    @abstractmethod
    async def start_app(self, package: str, activity: str = "") -> str:
        """
        Start the given app.
        """
        pass

    @abstractmethod
    async def take_screenshot(self) -> Tuple[str, bytes]:
        """
        Take a screenshot of the device.
        """
        pass

    @abstractmethod
    async def list_packages(self, include_system_apps: bool = False) -> List[str]:
        """
        List all packages on the device.
        """
        pass

    @abstractmethod
    async def remember(self, information: str) -> str:
        """
        Remember the given information. This is used to store information in the tool's memory.
        """
        pass

    @abstractmethod
    async def get_memory(self) -> List[str]:
        """
        Get the memory of the tool.
        """
        pass

    @abstractmethod
    async def complete(self, success: bool, reason: str = "") -> None:
        """
        Complete the tool. This is used to indicate that the tool has completed its task.
        """
        pass


def describe_tools(tools: Tools, exclude_tools: Optional[List[str]] = None) -> Dict[str, Callable[..., Any]]:
    """
    Describe the tools available for the given Tools instance.

    Args:
        tools: The Tools instance to describe.
        exclude_tools: List of tool names to exclude from the description.

    Returns:
        A dictionary mapping tool names to their descriptions.
    """
    exclude_tools = exclude_tools or []

    description = {
        # UI interaction
        "swipe": tools.swipe,
        "input_text": tools.input_text,
        "press_key": tools.press_key,
        "tap_by_index": tools.tap_by_index,
        "drag": tools.drag,
        # App management
        "start_app": tools.start_app,
        "list_packages": tools.list_packages,
        # state management
        "remember": tools.remember,
        "complete": tools.complete,
    }

    # Remove excluded tools
    for tool_name in exclude_tools:
        description.pop(tool_name, None)

    return description
