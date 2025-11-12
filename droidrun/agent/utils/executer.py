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
        
        # 添加详细的时间戳日志
        start_time = time.time()
        logger.info(f"🕐 [SimpleCodeExecutor] execute 开始 | timestamp={time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}")
        
        # Update UI elements before execution
        self.globals['ui_state'] = await ctx.store.get("ui_state", None)
        self.globals['step_screenshots'] = []
        self.globals['step_ui_states'] = []
        
        if self.tools_instance and isinstance(self.tools_instance, AdbTools):
            self.tools_instance._set_context(ctx)

        # Capture stdout and stderr
        stdout = io.StringIO()
        stderr = io.StringIO()

        output = ""
        try:
            # Execute with captured output in a thread to avoid blocking
            thread_exception = []
            
            def execute_code():
                try:
                    exec_start = time.time()
                    logger.info(f"🕐 [SimpleCodeExecutor] 线程中开始执行代码 | timestamp={time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}")
                    
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        exec(code, self.globals, self.locals)
                    
                    exec_end = time.time()
                    exec_duration = int((exec_end - exec_start) * 1000)
                    logger.info(f"🕐 [SimpleCodeExecutor] 线程中代码执行完成 | 耗时={exec_duration}ms | timestamp={time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}")
                    
                except Exception as e:
                    import traceback
                    logger.error(f"🕐 [SimpleCodeExecutor] 线程中代码执行异常 | error={e} | timestamp={time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}")
                    thread_exception.append((e, traceback.format_exc()))

            # Run in thread executor to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            
            thread_start = time.time()
            logger.info(f"🕐 [SimpleCodeExecutor] 提交到线程池前 | timestamp={time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}")
            
            await loop.run_in_executor(None, execute_code)
            
            thread_end = time.time()
            thread_duration = int((thread_end - thread_start) * 1000)
            logger.info(f"🕐 [SimpleCodeExecutor] 线程池执行完成 | 耗时={thread_duration}ms | timestamp={time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}")

            # Get output
            output = stdout.getvalue()
            if stderr.getvalue():
                output += "\n" + stderr.getvalue()
            if thread_exception:
                e, tb = thread_exception[0]
                output += f"\nError: {type(e).__name__}: {str(e)}\n{tb}"

        except Exception as e:
            # Capture exception information
            logger.error(f"🕐 [SimpleCodeExecutor] execute 方法异常 | error={e} | timestamp={time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}")
            output = f"Error: {type(e).__name__}: {str(e)}\n"
            output += traceback.format_exc()

        total_duration = int((time.time() - start_time) * 1000)
        logger.info(f"🕐 [SimpleCodeExecutor] execute 完成 | 总耗时={total_duration}ms | timestamp={time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}")

        result = {
            'output': output,
            'screenshots': self.globals['step_screenshots'],
            'ui_states': self.globals['step_ui_states'],
        }
        return result
