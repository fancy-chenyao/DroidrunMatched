"""
任务执行器 - 处理来自移动端的任务请求并执行 DroidAgent
"""
import asyncio
import logging
from typing import Dict, Any, Optional
from droidrun.agent.droid import DroidAgent
# 不再使用 load_llm，改用与 main.py 相同的 OpenAILike 方式
# from droidrun.agent.utils.llm_picker import load_llm
from droidrun.config import get_config_manager
# 延迟导入以避免循环导入
# from droidrun.tools import WebSocketTools
# from droidrun.server import get_global_server
from droidrun.agent.utils.logging_utils import LoggingUtils

logger = logging.getLogger("droidrun.server.task_executor")


class TaskExecutor:
    """任务执行器 - 负责执行移动端发送的任务请求"""
    
    def __init__(self, device_id: str):
        """
        初始化任务执行器
        
        Args:
            device_id: 设备ID
        """
        self.device_id = device_id
        self.config_manager = get_config_manager()
        self._current_task = None
        self._current_agent = None
    
    async def execute_task(
        self,
        goal: str,
        request_id: str,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        执行任务
        
        Args:
            goal: 任务目标（自然语言描述）
            request_id: 请求ID
            options: 任务选项（可选）
            
        Returns:
            任务执行结果
        """
        try:
            # 1. 获取服务器实例和工具（延迟导入以避免循环导入）
            from droidrun.server import get_global_server
            server = get_global_server()
            if not server:
                raise ValueError("WebSocket服务器未运行")
            
            # 检查设备是否已连接
            if not server.is_device_connected(self.device_id):
                raise ValueError(f"设备 {self.device_id} 未连接到服务器")
            
            # 2. 创建 WebSocketTools（延迟导入以避免循环导入）
            from droidrun.tools import WebSocketTools
            tools = WebSocketTools(
                device_id=self.device_id,
                session_manager=server.session_manager,
                config_manager=self.config_manager,
                timeout=self.config_manager.get_server_config().timeout,
            )
            
            # 注册工具实例到服务器
            server.register_tools_instance(self.device_id, tools)
            
            # 3. 加载 LLM（使用与 main.py 相同的方式）
            api_config = self.config_manager.get_api_config()
            
            if not api_config.api_key:
                raise ValueError("未配置 LLM API Key，请设置环境变量或配置文件")
            
            # 使用与 main.py 相同的方式加载 LLM：直接使用 OpenAILike
            # 这样可以避免 load_llm 中可能的阻塞问题
            try:
                from llama_index.llms.openai_like import OpenAILike
                
                llm = OpenAILike(
                    model=api_config.model,
                    api_base=api_config.api_base,
                    api_key=api_config.api_key,
                    is_chat_model=True,  # droidrun需要聊天模型支持
                )
            except Exception as e:
                LoggingUtils.log_error("TaskExecutor", "Failed to load LLM: {error}", error=e)
                import traceback
                LoggingUtils.log_error("TaskExecutor", "LLM loading traceback: {traceback}", traceback=traceback.format_exc())
                raise
            
            # 4. 解析任务选项
            task_options = options or {}
            max_steps = task_options.get("max_steps") or self.config_manager.get("agent.max_steps", 15)
            vision = task_options.get("vision") if "vision" in task_options else self.config_manager.get("agent.vision", False)
            reasoning = task_options.get("reasoning") if "reasoning" in task_options else self.config_manager.get("agent.reasoning", False)
            reflection = task_options.get("reflection") if "reflection" in task_options else self.config_manager.get("agent.reflection", False)
            debug = task_options.get("debug") if "debug" in task_options else self.config_manager.get("system.debug", False)
            save_trajectory = task_options.get("save_trajectory") or self.config_manager.get("agent.save_trajectories", "none")
            
            # 5. 创建 DroidAgent
            try:
                agent = DroidAgent(
                    goal=goal,
                    llm=llm,
                    tools=tools,
                    config_manager=self.config_manager,
                    max_steps=max_steps,
                    vision=vision,
                    reasoning=reasoning,
                    reflection=reflection,
                    debug=debug,
                    save_trajectories=save_trajectory,
                )
            except Exception as e:
                LoggingUtils.log_error("TaskExecutor", "Failed to create DroidAgent: {error}", error=e)
                import traceback
                LoggingUtils.log_error("TaskExecutor", "DroidAgent creation traceback: {traceback}", traceback=traceback.format_exc())
                raise
            
            self._current_agent = agent
            self._current_task = request_id
            
            # 6. 执行任务
            try:
                # 启动任务级事件循环看门狗（仅日志用途）
                watchdog_task = None
                try:
                    watchdog_task = asyncio.create_task(self._task_watchdog(tag="agent.run"))
                except Exception:
                    watchdog_task = None
                result = await agent.run()
                # 结束看门狗
                if watchdog_task:
                    try:
                        watchdog_task.cancel()
                    except Exception:
                        pass
            except Exception as e:
                LoggingUtils.log_error("TaskExecutor", "Error during agent.run(): {error}", error=e)
                import traceback
                LoggingUtils.log_error("TaskExecutor", "agent.run() traceback: {traceback}", traceback=traceback.format_exc())
                raise
            
            # 7. 构建返回结果
            execution_result = {
                "success": result.get("success", False),
                "output": result.get("output", ""),
                "steps": result.get("steps", 0),
                "reason": result.get("reason", ""),
            }
            
            # 添加额外信息（如果有）
            if "trajectory_id" in result:
                execution_result["trajectory_id"] = result["trajectory_id"]
            
            # 清理
            self._current_agent = None
            self._current_task = None
            
            # 注销工具实例
            server.unregister_tools_instance(self.device_id)
            
            return execution_result
            
        except Exception as e:
            LoggingUtils.log_error("TaskExecutor", "Error executing task: {error}", error=e)
            
            # 清理
            self._current_agent = None
            self._current_task = None
            
            # 尝试注销工具实例
            try:
                server = get_global_server()
                if server:
                    server.unregister_tools_instance(self.device_id)
            except:
                pass
            
            raise

    async def _task_watchdog(self, tag: str = "task"):
        """任务级事件循环看门狗：周期性检测 drift，并带上阶段标签，帮助定位阻塞发生时的业务阶段（仅日志用途）。"""
        try:
            interval = 0.2
            loop = asyncio.get_running_loop()
            last = loop.time()
            while True:
                await asyncio.sleep(interval)
                now = loop.time()
                drift = (now - last) - interval
                last = now
                drift_ms = int(drift * 1000)
                if drift_ms > 1000:
                    LoggingUtils.log_info("TaskExecutor", "EventLoop stall (task) | tag={tag} | drift_ms={d}", tag=tag, d=drift_ms)
        except asyncio.CancelledError:
            return
    
    def cancel_task(self):
        """取消当前任务"""
        if self._current_agent:
            # 这里可以添加取消逻辑
            self._current_agent = None
            self._current_task = None

