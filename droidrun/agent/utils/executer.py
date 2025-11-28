import io
import contextlib
import ast
import traceback
import logging
from typing import Any, Dict
from llama_index.core.workflow import Context
import asyncio
from asyncio import AbstractEventLoop
import threading
from droidrun.tools.adb import AdbTools
from droidrun.tools.websocket_tools import WebSocketTools

logger = logging.getLogger("droidrun")


class SimpleCodeExecutor:
    """
    A simple code executor that runs Python code with state persistence.

    This executor maintains a global and local state between executions,
    allowing for variables to persist across multiple code runs.

    NOTE: not safe for production use! Use with caution.
    """

    def __init__(
        self,
        loop: AbstractEventLoop,
        locals: Dict[str, Any] = {},
        globals: Dict[str, Any] = {},
        tools={},
        tools_instance=None,
        use_same_scope: bool = True,
    ):
        """
        Initialize the code executor.

        Args:
            locals: Local variables to use in the execution context
            globals: Global variables to use in the execution context
            tools: List of tools available for execution
            tools_instance: Original tools instance (e.g., AdbTools instance)
        """

        self.tools_instance = tools_instance

        # loop throught tools and add them to globals, provide sync wrappers for async tools
        # e.g. tools = {'tool_name': tool_function}

        # check if tools is a dictionary
        if isinstance(tools, dict):
            logger.debug(
                f"🔧 Initializing SimpleCodeExecutor with tools: {tools.items()}"
            )
            for tool_name, tool_function in tools.items():
                if asyncio.iscoroutinefunction(tool_function):
                    # Create a sync wrapper that schedules the async function properly
                    def create_sync_wrapper(async_func):
                        def sync_wrapper(*args, **kwargs):
                            # Get the current event loop
                            try:
                                loop = asyncio.get_running_loop()
                                # Schedule the coroutine in the current loop and wait for result
                                future = asyncio.run_coroutine_threadsafe(async_func(*args, **kwargs), loop)
                                return future.result(timeout=5)  # 5秒超时，避免30秒延迟
                            except RuntimeError:
                                # No event loop running, use asyncio.run
                                return asyncio.run(async_func(*args, **kwargs))
                            except Exception as e:
                                logger.error(f"Error in sync wrapper for {async_func.__name__}: {e}")
                                raise
                        return sync_wrapper
                    
                    # Add sync wrapper to globals
                    globals[tool_name] = create_sync_wrapper(tool_function)
                else:
                    # Add sync function directly
                    globals[tool_name] = tool_function
        elif isinstance(tools, list):
            logger.debug(f"🔧 Initializing SimpleCodeExecutor with tools: {tools}")
            # If tools is a list, convert it to a dictionary with tool name as key and function as value
            for tool in tools:
                if asyncio.iscoroutinefunction(tool):
                    # Create a sync wrapper that schedules the async function properly
                    def create_sync_wrapper(async_func):
                        def sync_wrapper(*args, **kwargs):
                            # Get the current event loop
                            try:
                                loop = asyncio.get_running_loop()
                                # Schedule the coroutine in the current loop and wait for result
                                future = asyncio.run_coroutine_threadsafe(async_func(*args, **kwargs), loop)
                                return future.result(timeout=5)  # 5秒超时，避免30秒延迟
                            except RuntimeError:
                                # No event loop running, use asyncio.run
                                return asyncio.run(async_func(*args, **kwargs))
                            except Exception as e:
                                logger.error(f"Error in sync wrapper for {async_func.__name__}: {e}")
                                raise
                        return sync_wrapper
                    
                    # Add sync wrapper to globals
                    globals[tool.__name__] = create_sync_wrapper(tool)
                else:
                    # Add sync function directly
                    globals[tool.__name__] = tool
        else:
            raise ValueError("Tools must be a dictionary or a list of functions.")

        import time

        globals["time"] = time

        self.globals = globals
        self.locals = locals
        self.loop = loop
        self.use_same_scope = use_same_scope
        self.tools = tools
        if self.use_same_scope:
            # If using the same scope, set the globals and locals to the same dictionary
            self.globals = self.locals = {
                **self.locals,
                **{k: v for k, v in self.globals.items() if k not in self.locals},
            }

    def _normalize_func_call(self, func_call: str) -> str:
        """
        标准化函数调用格式，将关键字参数转换为位置参数
        
        例如：
        - input_text("text", index=14) → input_text("text", 14)
        - tap_by_index(index=64) → tap_by_index(64)
        """
        import re
        
        # 处理 input_text 的 index= 参数
        func_call = re.sub(r'input_text\(([^,]+),\s*index=(\d+)\)', r'input_text(\1, \2)', func_call)
        
        # 处理 tap_by_index 的 index= 参数
        func_call = re.sub(r'tap_by_index\(index=(\d+)\)', r'tap_by_index(\1)', func_call)
        
        return func_call
    
    def _extract_action_comments(self, code: str) -> Dict[str, str]:
        """
        提取代码中动作函数调用前的注释
        
        Returns:
            Dict[函数调用, 注释内容]
            例如: {"tap_by_index(64)": "点击"年休假"选项"}
        """
        action_comments = {}
        lines = code.split('\n')
        last_comment = None
        
        for line in lines:
            stripped = line.strip()
            
            # 如果是注释行
            if stripped.startswith('#'):
                last_comment = stripped[1:].strip()
            # 如果是函数调用且前面有注释
            elif stripped and not stripped.startswith('#'):
                # 检查是否是工具函数调用
                if any(func in stripped for func in ['tap_by_index', 'input_text', 'swipe', 'long_press', 'start_app']):
                    if last_comment:
                        # 提取函数调用部分（去除赋值等）
                        if '=' in stripped:
                            func_call = stripped.split('=', 1)[1].strip()
                        else:
                            func_call = stripped
                        
                        # 标准化：将关键字参数格式转换为位置参数格式，保证与热启动加载的格式一致
                        # 例如：input_text("text", index=14) → input_text("text", 14)
                        func_call = self._normalize_func_call(func_call)
                        
                        action_comments[func_call] = last_comment
                last_comment = None  # 重置注释
        
        return action_comments
    
    async def execute(self, ctx: Context, code: str) -> Dict[str, Any]:
        """
        Execute Python code and capture output and return values.
        Now uses proper async wrappers that don't block the event loop.

        Args:
            code: Python code to execute

        Returns:
            Dict with 'output', 'screenshots', and 'ui_states'
        """
        import time
        
        start_time = time.time()
        
        # 提取代码中的动作注释
        action_comments = self._extract_action_comments(code)
        
        # Update UI elements before execution
        self.globals['ui_state'] = await ctx.store.get("ui_state", None)
        self.globals['step_screenshots'] = []
        self.globals['step_ui_states'] = []
        
        # 为工具实例设置上下文，用于事件流记录
        if self.tools_instance:
            if isinstance(self.tools_instance, (AdbTools, WebSocketTools)):
                self.tools_instance._set_context(ctx)
                # 传递动作注释信息（合并而不是覆盖，避免丢失热启动预加载的注释）
                if hasattr(self.tools_instance, '_action_comments') and self.tools_instance._action_comments:
                    # 保留原有注释（来自热启动），添加新注释（来自当前代码）
                    self.tools_instance._action_comments.update(action_comments)
                else:
                    # 首次设置
                    self.tools_instance._action_comments = action_comments

        # Capture stdout and stderr
        stdout = io.StringIO()
        stderr = io.StringIO()

        output = ""
        try:
            # Execute with captured output in a thread to avoid blocking
            thread_exception = []
            
            def execute_code():
                try:
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        exec(code, self.globals, self.locals)
                    
                except Exception as e:
                    import traceback
                    thread_exception.append((e, traceback.format_exc()))

            # Run in thread executor to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            
            await loop.run_in_executor(None, execute_code)

            # Get output
            output = stdout.getvalue()
            if stderr.getvalue():
                output += "\n" + stderr.getvalue()
            if thread_exception:
                e, tb = thread_exception[0]
                output += f"\nError: {type(e).__name__}: {str(e)}\n{tb}"

        except Exception as e:
            # Capture exception information
            logger.error(f"SimpleCodeExecutor execute error: {e}")
            output = f"Error: {type(e).__name__}: {str(e)}\n"
            output += traceback.format_exc()


        result = {
            'output': output,
            'screenshots': self.globals['step_screenshots'],
            'ui_states': self.globals['step_ui_states'],
        }
        return result
