"""
DroidAgent - Android设备任务执行代理

协调规划代理和执行代理，实现用户目标在Android设备上的自动化执行。
支持热启动（复用历史经验）和冷启动（完整LLM规划）两种执行模式。

主要功能：
- 热启动执行：复用相似历史经验，快速完成任务
- 微冷启动：对变更步骤进行局部LLM规划
- 经验记忆：存储和检索历史执行经验
- 参数适配：自动调整历史经验参数以匹配新目标
- 执行监控：检测异常并提供回退机制

使用示例：
    agent = DroidAgent(
        goal="打开计算器并计算2+2",
        llm=llm,
        tools=tools,
        enable_memory=True
    )
    result = await agent.run()
"""
import asyncio
import glob
import json
import logging
import os
import re
import time
import uuid
import traceback
from typing import Dict, List, Optional

from llama_index.core.llms.llm import LLM
from llama_index.core.workflow import Context, StartEvent, StopEvent, Workflow, step, Event
from llama_index.core.workflow.handler import WorkflowHandler

from droidrun.agent.codeact import CodeActAgent
from droidrun.agent.codeact.events import EpisodicMemoryEvent, TaskEndEvent, TaskExecutionEvent
from droidrun.agent.common.events import (
    InputTextActionEvent,
    KeyPressActionEvent,
    MacroEvent,
    RecordUIStateEvent,
    ScreenshotEvent,
    StartAppEvent,
    SwipeActionEvent,
    TapActionEvent,
)
from droidrun.agent.context import ContextInjectionManager
from droidrun.agent.utils.ui_stability_checker import UIStabilityChecker
from droidrun.agent.context.agent_persona import AgentPersona
from droidrun.agent.context.execution_monitor import ExecutionMonitor, MonitorResult
from droidrun.agent.context.experience_memory import ExperienceMemory, TaskExperience
from droidrun.agent.context.llm_services import LLMServices
from droidrun.agent.context.memory_config import MemoryConfig
from droidrun.agent.context.personas import DEFAULT
from droidrun.agent.context.task_manager import TaskManager, Task
from droidrun.agent.droid.events import (
    CodeActExecuteEvent,
    CodeActResultEvent,
    ReasoningLogicEvent,
    FinalizeEvent
)
from droidrun.agent.planner import PlannerAgent
from droidrun.agent.reflection import FailureReflector
from droidrun.agent.reflection.reflection_types import FailureContext
from droidrun.agent.utils.trajectory import Trajectory

from droidrun.config import get_config_manager, UnifiedConfigManager, ExceptionConstants
from droidrun.agent.utils.exception_handler import ExceptionHandler, log_error
from droidrun.agent.utils.logging_utils import LoggingUtils
from droidrun.telemetry import (
    DroidAgentFinalizeEvent,
    DroidAgentInitEvent,
    capture,
    flush,
)
from droidrun.tools import Tools, describe_tools
from droidrun.tools.adb import AdbTools

logger = logging.getLogger("droidrun")


class DroidAgent(Workflow):
    """
    A wrapper class that coordinates between PlannerAgent (creates plans) and
        CodeActAgent (executes tasks) to achieve a user's goal.
    """

    @staticmethod
    def _configure_default_logging(debug: bool = False):
        """
        Configure default logging for DroidAgent if no handlers are present.
        This ensures logs are visible when using DroidAgent directly.
        """
        if not logger.handlers:
            handler = logging.StreamHandler()

            if debug:
                formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s", "%H:%M:%S")
            else:
                formatter = logging.Formatter("%(message)s")

            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG if debug else logging.INFO)
            logger.propagate = False
        
        if not debug:
            logging.getLogger("droidrun.tools.adb").setLevel(logging.INFO)
            logging.getLogger("droidrun.agent.codeact").setLevel(logging.INFO)
            logging.getLogger("droidrun.agent.planner").setLevel(logging.INFO)
            logging.getLogger("droidrun.agent.utils").setLevel(logging.INFO)
            logging.getLogger("droidrun.agent.utils.trajectory").setLevel(logging.INFO)
            logging.getLogger("droidrun.telemetry").setLevel(logging.INFO)

    def __init__(
        self,
        goal: str,
        llm: LLM,
        tools: Tools,
        personas: List[AgentPersona] = [DEFAULT],
        max_steps: Optional[int] = None,
        timeout: Optional[int] = None,
        vision: Optional[bool] = None,
        reasoning: Optional[bool] = None,
        reflection: Optional[bool] = None,
        enable_tracing: bool = False,
        debug: Optional[bool] = None,
        save_trajectories: Optional[str] = None,
        excluded_tools: List[str] = None,
        # 新增记忆系统参数（向后兼容）
        enable_memory: Optional[bool] = None,
        memory_similarity_threshold: Optional[float] = None,
        memory_storage_dir: Optional[str] = None,
        memory_config: Optional[MemoryConfig] = None,
        # 新增失败反思参数
        enable_failure_reflection: Optional[bool] = None,
        # 新增统一配置管理器参数
        config_manager: Optional[UnifiedConfigManager] = None,
        *args,
        **kwargs,
    ):
        """
        Initialize the DroidAgent wrapper.

        Args:
            goal: The user's goal or command to execute
            llm: The language model to use for both agents
            max_steps: Maximum number of steps for both agents (None = use config)
            timeout: Timeout for agent execution in seconds (None = use config)
            reasoning: Whether to use the PlannerAgent for complex reasoning (None = use config)
            reflection: Whether to reflect on steps the CodeActAgent did to give the PlannerAgent advice (None = use config)
            enable_tracing: Whether to enable Arize Phoenix tracing
            debug: Whether to enable verbose debug logging (None = use config)
            save_trajectories: Trajectory saving level (None = use config)
            config_manager: Unified configuration manager (None = use global instance)
            **kwargs: Additional keyword arguments to pass to the agents
        """
        self.user_id = kwargs.pop("user_id", None)
        
        self.config_manager = config_manager or get_config_manager()
        self.max_steps = max_steps if max_steps is not None else self.config_manager.get("agent.max_steps", 20)
        self.timeout = timeout if timeout is not None else self.config_manager.get("system.timeout", 300)
        self.vision = vision if vision is not None else self.config_manager.get("agent.vision", False)
        self.reasoning = reasoning if reasoning is not None else self.config_manager.get("agent.reasoning", False)
        self.reflection = reflection if reflection is not None else self.config_manager.get("agent.reflection", False)
        self.debug = debug if debug is not None else self.config_manager.get("system.debug", False)
        self.save_trajectories = save_trajectories if save_trajectories is not None else self.config_manager.get("agent.save_trajectories", "step")
        
        super().__init__(timeout=self.timeout, *args, **kwargs)
        
        self._configure_default_logging(debug=self.debug)
        memory_enabled = enable_memory if enable_memory is not None else self.config_manager.get("memory.enabled", True)
        self.memory_enabled = memory_enabled
        
        if self.memory_enabled:
            if memory_config is None:
                unified_memory_config = self.config_manager.get_memory_config()
                memory_config_dict = {
                    "enabled": unified_memory_config.enabled,
                    "similarity_threshold": unified_memory_config.similarity_threshold,
                    "storage_dir": unified_memory_config.storage_dir,
                    "max_experiences": unified_memory_config.max_experiences,
                    "llm_model": None,
                    "experience_quality_threshold": unified_memory_config.experience_quality_threshold,
                    "fallback_enabled": unified_memory_config.fallback_enabled,
                    "monitoring_enabled": unified_memory_config.monitoring_enabled,
                    "hot_start_enabled": unified_memory_config.hot_start_enabled,
                    "parameter_adaptation_enabled": unified_memory_config.parameter_adaptation_enabled,
                    "max_consecutive_failures": unified_memory_config.max_consecutive_failures,
                    "step_timeout": unified_memory_config.step_timeout,
                    "max_steps_before_fallback": unified_memory_config.max_steps_before_fallback,
                }
                
                if memory_similarity_threshold is not None:
                    memory_config_dict["similarity_threshold"] = memory_similarity_threshold
                if memory_storage_dir is not None:
                    memory_config_dict["storage_dir"] = memory_storage_dir
                
                self.memory_config = MemoryConfig.from_dict(memory_config_dict)
            else:
                self.memory_config = memory_config
            
            self.memory_manager = ExperienceMemory(
                storage_dir=self.memory_config.storage_dir,
                llm=llm
            )
            self.execution_monitor = ExecutionMonitor(llm=llm)
            self.llm_services = LLMServices(llm)
            self.pending_hot_actions: List[Dict] = []
            self.pending_hot_context: Dict = {}
            
            LoggingUtils.log_info("DroidAgent", "Memory system initialized")
        else:
            self.memory_manager = None
            self.execution_monitor = None
            self.llm_services = None
            self.pending_hot_actions = []
            self.pending_hot_context = {}
            LoggingUtils.log_info("DroidAgent", "Memory system disabled")

        # Setup global tracing first if enabled
        if enable_tracing:
            try:
                from llama_index.core import set_global_handler

                set_global_handler("arize_phoenix")
                LoggingUtils.log_info("DroidAgent", "Arize Phoenix tracing enabled globally")
            except ImportError:
                LoggingUtils.log_warning("DroidAgent", "Arize Phoenix package not found, tracing disabled")
                enable_tracing = False

        self.goal = goal
        self.llm = llm
        self.max_codeact_steps = self.max_steps

        self.event_counter = 0
        self.experience_id = str(uuid.uuid4())
        
        self.trajectory = Trajectory(goal=goal, experience_id=self.experience_id)
        self.task_manager = TaskManager()
        self.task_iter = None

        self.cim = ContextInjectionManager(personas=personas)
        self.current_episodic_memory = None

        LoggingUtils.log_info("DroidAgent", "Initializing DroidAgent...")
        LoggingUtils.log_info("DroidAgent", "Trajectory saving level: {level}", level=self.save_trajectories)

        self.tool_list = describe_tools(tools, excluded_tools)
        self.tools_instance = tools

        self.tools_instance.save_trajectories = self.save_trajectories
        
        # 初始化 UI 稳定性检测器
        self.ui_stability_checker = UIStabilityChecker(self.tools_instance)
        LoggingUtils.log_info("DroidAgent", "UI stability checker initialized")
        
        # 初始化失败反思模块
        self.enable_failure_reflection = (
            enable_failure_reflection 
            if enable_failure_reflection is not None 
            else self.config_manager.get("agent.failure_reflection", False)
        )
        
        if self.enable_failure_reflection:
            self.failure_reflector = FailureReflector(
                llm=llm,
                tools_instance=tools,
                debug=self.debug
            )
            LoggingUtils.log_info("DroidAgent", "✨ Failure reflector initialized")
        else:
            self.failure_reflector = None
            LoggingUtils.log_debug("DroidAgent", "Failure reflection disabled")

        if self.reasoning:
            LoggingUtils.log_info("DroidAgent", "Initializing Planner Agent...")
            self.planner_agent = PlannerAgent(
                goal=goal,
                llm=llm,
                vision=self.vision,
                personas=personas,
                task_manager=self.task_manager,
                tools_instance=tools,
                timeout=self.timeout,
                debug=self.debug,
            )
            self.max_codeact_steps = 5

        else:
            LoggingUtils.log_debug("DroidAgent", "Planning disabled - will execute tasks directly with CodeActAgent")
            self.planner_agent = None

        capture(
            DroidAgentInitEvent(
                goal=goal,
                llm=llm.class_name(),
                tools=",".join(self.tool_list),
                personas=",".join([p.name for p in personas]),
                max_steps=self.max_steps,
                timeout=self.timeout,
                vision=self.vision,
                reasoning=self.reasoning,
                reflection=self.reflection,
                enable_tracing=enable_tracing,
                debug=self.debug,
                save_trajectories=self.save_trajectories,
            ),
            self.user_id,
        )

        LoggingUtils.log_info("DroidAgent", "DroidAgent initialized successfully.")

    def run(self, *args, **kwargs) -> WorkflowHandler:
        """
        Run the DroidAgent workflow.
        """
        return super().run(*args, **kwargs)

    @step
    async def execute_task(self, ctx: Context, ev: CodeActExecuteEvent) -> CodeActResultEvent:
        """
        Execute a single task using the CodeActAgent.

        Args:
            task: Task dictionary with description and status

        Returns:
            Tuple of (success, reason)
        """
        task: Task = ev.task
        reflection = ev.reflection if ev.reflection is not None else None
        persona = self.cim.get_persona(task.agent_type)

        LoggingUtils.log_progress("DroidAgent", "Executing task: {description}", description=task.description)

        # 新增：执行监控
        if self.memory_enabled and self.memory_config.monitoring_enabled:
            self.execution_monitor.start_step_monitoring({
                "task": task.description,
                "step": getattr(self, 'step_counter', 0),  # 使用 getattr 防止 AttributeError
                "timestamp": time.time()
            })

        try:
            if self.memory_enabled and getattr(self, 'pending_hot_actions', None):
                LoggingUtils.log_progress("DroidAgent", "Directly executing {count} hot-start actions", count=len(self.pending_hot_actions))
                self.is_hot_start_execution = True
                
                # ✨ 保存热启动执行前的 UI 快照（用于失败反思）
                pre_ui_state = None
                if self.enable_failure_reflection:
                    try:
                        pre_ui_state = await self.tools_instance.get_state_async(include_screenshot=False)
                        LoggingUtils.log_debug("DroidAgent", "Pre-execution UI snapshot saved for reflection")
                    except Exception as e:
                        LoggingUtils.log_warning("DroidAgent", "Failed to save pre-execution UI snapshot: {error}", error=str(e))
                
                success, reason = await self._direct_execute_actions_async(ctx, self.pending_hot_actions)
                if hasattr(self, 'trajectory') and self.trajectory:
                    self.trajectory.events.append(TaskEndEvent(success=success, reason=reason, task=task))
                    LoggingUtils.log_info("DroidAgent", "Hot start execution recorded in trajectory")
                
                # 清除热启动动作
                pending_actions_backup = self.pending_hot_actions.copy()  # 备份用于反思
                self.pending_hot_actions = []
                
                # 如果热启动成功，直接返回结果
                if success:
                    LoggingUtils.log_success("DroidAgent", "🔥 Hot start completed successfully")
                    return CodeActResultEvent(success=success, reason=reason, task=task, steps=getattr(self, 'step_counter', 0))
                else:
                    # 热启动失败，回退到冷启动
                    LoggingUtils.log_warning("DroidAgent", "🔥 ❄️ Hot start failed, falling back to cold start")
                    
                    # ✨ Step 3: 在热启动失败时调用反思模块
                    reflection_result = None
                    enhanced_goal = self.goal
                    
                    if self.enable_failure_reflection and self.failure_reflector:
                        try:
                            # 保存失败后的 UI 快照
                            post_ui_state = None
                            try:
                                post_ui_state = await self.tools_instance.get_state_async(include_screenshot=False)
                                LoggingUtils.log_debug("DroidAgent", "Post-failure UI snapshot saved for reflection")
                            except Exception as e:
                                LoggingUtils.log_warning("DroidAgent", "Failed to save post-failure UI snapshot: {error}", error=str(e))
                            
                            # 构建失败上下文
                            context_data = FailureContext.from_hot_start_failure(
                                goal=self.goal,
                                failed_action=pending_actions_backup[-1] if pending_actions_backup else {},
                                error_message=reason,
                                error_step=len(pending_actions_backup) - 1 if pending_actions_backup else 0,
                                pre_ui_state=pre_ui_state,
                                post_ui_state=post_ui_state,
                                recent_actions=pending_actions_backup[-5:] if len(pending_actions_backup) > 5 else pending_actions_backup
                            )
                            
                            LoggingUtils.log_info("DroidAgent", "🤔 Analyzing failure with reflector...")
                            
                            # 调用反思分析
                            reflection_result = await self.failure_reflector.analyze_failure(context_data)
                            
                            LoggingUtils.log_info(
                                "DroidAgent",
                                "💡 Reflection complete: {type} (confidence: {conf:.2f})",
                                type=reflection_result.problem_type,
                                conf=reflection_result.confidence
                            )
                            
                            # Step 5: 保存反思结果到 trajectory（Memory 系统集成）
                            if hasattr(self.trajectory, 'failure_reflections'):
                                self.trajectory.failure_reflections.append({
                                    "problem_type": reflection_result.problem_type,
                                    "root_cause": reflection_result.root_cause,
                                    "specific_advice": reflection_result.specific_advice,
                                    "confidence": reflection_result.confidence,
                                    "timestamp": time.time(),
                                    "failed_action": pending_actions_backup[-1] if pending_actions_backup else None,
                                    "error_step": len(pending_actions_backup) - 1 if pending_actions_backup else 0
                                })
                                LoggingUtils.log_debug("DroidAgent", "📝 Failure reflection saved to trajectory")
                            
                            # 使用反思增强任务描述
                            if reflection_result.should_apply_advice():
                                enhanced_goal = f"{self.goal}\n\n【反思建议】{reflection_result.specific_advice}"
                                LoggingUtils.log_info("DroidAgent", "✨ Task description enhanced with reflection advice")
                            else:
                                LoggingUtils.log_debug(
                                    "DroidAgent", 
                                    "Reflection confidence too low ({conf:.2f}), not applying advice",
                                    conf=reflection_result.confidence
                                )
                        
                        except Exception as reflection_error:
                            LoggingUtils.log_error(
                                "DroidAgent",
                                "Failed to analyze failure: {error}",
                                error=str(reflection_error)
                            )
                            if self.debug:
                                import traceback
                                LoggingUtils.log_error("DroidAgent", "{trace}", trace=traceback.format_exc())

                    task = Task(
                        description=enhanced_goal,
                        status=self.task_manager.STATUS_PENDING,
                        agent_type="Default",
                    )
                    LoggingUtils.log_info("DroidAgent", "🔄 Cold start task created with explicit field requirements")

            codeact_agent = CodeActAgent(
                llm=self.llm,
                persona=persona,
                vision=self.vision,
                max_steps=self.max_codeact_steps,
                all_tools_list=self.tool_list,
                tools_instance=self.tools_instance,
                debug=self.debug,
                timeout=self.timeout,
            )

            handler = codeact_agent.run(
                input=task.description,
                remembered_info=self.tools_instance.memory,
                reflection=reflection,
            )

            async for nested_ev in handler.stream_events():
                self.handle_stream_event(nested_ev, ctx)
                # 微让步：planner 事件流处理中适当让步，防止事件循环饥饿
                try:
                    await asyncio.sleep(0)
                except Exception:
                    pass
                # 微让步：每处理一个事件后让出一次事件循环，避免长时间占用
                try:
                    await asyncio.sleep(0)
                except Exception:
                    pass

            result = await handler

            # 新增：执行后监控
            if self.memory_enabled and self.memory_config.monitoring_enabled:
                monitor_result = self.execution_monitor.monitor_step({
                    "task": task.description,
                    "success": result.get("success", False),
                    "steps": result.get("codeact_steps", 0),
                    "timestamp": time.time()
                })
                
                if monitor_result.fallback_needed:
                    LoggingUtils.log_warning("DroidAgent", "Execution anomaly detected: {message}", message=monitor_result.message)
                    # 触发回退逻辑
                    return self._handle_fallback(monitor_result, task)

            if "success" in result and result["success"]:
                return CodeActResultEvent(
                    success=True,
                    reason=result["reason"],
                    task=task,
                    steps=result["codeact_steps"],
                )
            else:
                return CodeActResultEvent(
                    success=False,
                    reason=result["reason"],
                    task=task,
                    steps=result["codeact_steps"],
                )

        except Exception as e:
            log_error("[DroidAgent] Task execution", e, level="error")
            if self.debug:
                
                LoggingUtils.log_error("DroidAgent", "{error}", error=traceback.format_exc())
            return CodeActResultEvent(success=False, reason=f"Error: {str(e)}", task=task, steps=0)

    @step
    async def handle_codeact_execute(
        self, ctx: Context, ev: CodeActResultEvent
    ) -> FinalizeEvent | ReasoningLogicEvent:
        try:
            task = ev.task
            if not self.reasoning:
                return FinalizeEvent(
                    success=ev.success,
                    reason=ev.reason,
                    output=ev.reason,
                    task=[task],
                    tasks=[task],
                    steps=ev.steps,
                )

            # Reasoning is enabled.
            # Success: mark complete and proceed to next step in reasoning loop.
            # Failure: mark failed and trigger planner immediately without advancing to the next queued task.
            if ev.success:
                self.task_manager.complete_task(task, message=ev.reason)
                return ReasoningLogicEvent()
            else:
                self.task_manager.fail_task(task, failure_reason=ev.reason)
                return ReasoningLogicEvent(force_planning=True)

        except ExceptionConstants.RUNTIME_EXCEPTIONS as e:
            log_error("[DroidAgent] Execution", e, level="error")
            if self.debug:
                LoggingUtils.log_error("DroidAgent", "{error}", error=traceback.format_exc())
            tasks = self.task_manager.get_task_history()
            return FinalizeEvent(
                success=False,
                reason=str(e),
                output=str(e),
                task=tasks,
                tasks=tasks,
                steps=self.step_counter,
            )

    @step
    async def handle_reasoning_logic(
        self,
        ctx: Context,
        ev: ReasoningLogicEvent,
    ) -> FinalizeEvent | CodeActExecuteEvent:
        try:
            if self.step_counter >= self.max_steps:
                output = f"Reached maximum number of steps ({self.max_steps})"
                tasks = self.task_manager.get_task_history()
                return FinalizeEvent(
                    success=False,
                    reason=output,
                    output=output,
                    task=tasks,
                    tasks=tasks,
                    steps=self.step_counter,
                )
            self.step_counter += 1

            if ev.reflection:
                handler = self.planner_agent.run(
                    remembered_info=self.tools_instance.memory, reflection=ev.reflection
                )
            else:
                if not ev.force_planning and self.task_iter:
                    try:
                        task = next(self.task_iter)
                        return CodeActExecuteEvent(task=task, reflection=None)
                    except StopIteration as e:
                        LoggingUtils.log_info("DroidAgent", "Planning next steps...")

                LoggingUtils.log_debug("DroidAgent", "Planning step {current}/{max}", current=self.step_counter, max=self.max_steps)

                handler = self.planner_agent.run(
                    remembered_info=self.tools_instance.memory, reflection=None
                )

            async for nested_ev in handler.stream_events():
                self.handle_stream_event(nested_ev, ctx)

            result = await handler

            self.tasks = self.task_manager.get_all_tasks()
            self.task_iter = iter(self.tasks)

            if self.task_manager.goal_completed:
                LoggingUtils.log_success("DroidAgent", "Goal completed: {message}", message=self.task_manager.message)
                tasks = self.task_manager.get_task_history()
                return FinalizeEvent(
                    success=True,
                    reason=self.task_manager.message,
                    output=self.task_manager.message,
                    task=tasks,
                    tasks=tasks,
                    steps=self.step_counter,
                )
            if not self.tasks:
                LoggingUtils.log_warning("DroidAgent", "No tasks generated by planner")
                output = "Planner did not generate any tasks"
                tasks = self.task_manager.get_task_history()
                return FinalizeEvent(
                    success=False,
                    reason=output,
                    output=output,
                    task=tasks,
                    tasks=tasks,
                    steps=self.step_counter,
                )

            return CodeActExecuteEvent(task=next(self.task_iter), reflection=None)

        except Exception as e:
            log_error("[DroidAgent] Planning", e, level="error")
            if self.debug:
                LoggingUtils.log_error("DroidAgent", "{error}", error=traceback.format_exc())
            tasks = self.task_manager.get_task_history()
            return FinalizeEvent(
                success=False,
                reason=str(e),
                output=str(e),
                task=tasks,
                tasks=tasks,
                steps=self.step_counter,
            )

    @step
    async def start_handler(
        self, ctx: Context, ev: StartEvent
    ) -> CodeActExecuteEvent | ReasoningLogicEvent:
        """
        Main execution loop that coordinates between planning and execution.

        Returns:
            Dict containing the execution result
        """
        LoggingUtils.log_info("DroidAgent", "Running DroidAgent to achieve goal: {goal}", goal=self.goal)
        ctx.write_event_to_stream(ev)

        self.step_counter = 0
        self.retry_counter = 0
        
        # 性能分析：记录任务开始时间
        task_start_time = time.time()
        self._task_start_time = task_start_time
        start_time_str = time.strftime("%H:%M:%S", time.localtime(task_start_time))
        LoggingUtils.log_info("Performance", "⏱️ Task started at {time}", time=start_time_str)

        # 判断新任务的类型（必须在支持的清单内）
        type_start = time.time()
        task_type = self.memory_manager.determine_task_type(self.goal)
        if not task_type:
            # 返回错误 Event，而不是字符串
            LoggingUtils.log_error("DroidAgent", "Task type determination failed or unsupported task type")
            return FinalizeEvent(
                success=False,
                steps=0,
                output="",
                reason="暂不支持该功能，或任务类型判断失败",
                task=[],  # 必需字段（已弃用）
                tasks=[]  # 必需字段
            )
        LoggingUtils.log_info("ExperienceMemory", f"Task determined as type: {task_type}")
        self.current_task_type = task_type
        type_duration = time.time() - type_start
        LoggingUtils.log_info("Performance", "⏱️ Task type determination: {duration:.2f}s", duration=type_duration)

        # 新增：热启动检查
        if self.memory_enabled and self.memory_config.hot_start_enabled:
            # similar_experiences = self.memory_manager.batch_find_similar_experiences(
            #     self.goal,
            #     self.current_task_type,
            #     threshold=self.memory_config.similarity_threshold
            # )
            # 使用合并优化：一次LLM调用同时完成相似度计算和排序
            use_merged_optimization = self.config_manager.get("memory.use_merged_similarity_ranking", False)

            # 性能分析：记录经验检索开始时间
            retrieval_start = time.time()
            
            if use_merged_optimization:
                similar_experiences = self.memory_manager.find_and_rank_similar_experiences(
                    self.goal,
                    self.current_task_type,
                    threshold=self.memory_config.similarity_threshold
                )
            else:
                # 旧方法：分别计算相似度和排序
                similar_experiences = self.memory_manager.batch_find_similar_experiences(
                    self.goal,
                    self.current_task_type,
                    threshold=self.memory_config.similarity_threshold
                )
            
            retrieval_duration = time.time() - retrieval_start
            exp_count = len(similar_experiences) if similar_experiences else 0
            LoggingUtils.log_info("Performance", "⏱️ Experience retrieval: {duration:.2f}s (found {count} experiences)", 
                                duration=retrieval_duration, count=exp_count)

            if similar_experiences:
                max_display = self.config_manager.get("memory.max_similar_experiences_display", 3)
                LoggingUtils.log_info("DroidAgent", "🔥 Found {count} similar experiences, using hot start", count=len(similar_experiences))
                for i, exp in enumerate(similar_experiences[:max_display]):
                    LoggingUtils.log_info("DroidAgent", "  {num}. {goal} (similarity: {score:.2f})", 
                                        num=i+1, goal=exp.goal, score=exp.similarity_score)
                # 打印命中集合的相似度（检索阶段结果）
                try:
                    for exp in similar_experiences:
                        if hasattr(exp, "similarity_score") and exp.similarity_score is not None:
                            LoggingUtils.log_debug("DroidAgent", "Similarity kept: {score:.2f} goal={goal}", 
                                                 score=exp.similarity_score, goal=exp.goal)
                except ExceptionConstants.DATA_PARSING_EXCEPTIONS as e:
                    ExceptionHandler.handle_data_parsing_error(e, "[SIM] Similarity calculation")
            else:
                LoggingUtils.log_info("DroidAgent", "❄️ No similar experiences found, using cold start (threshold={threshold})", 
                                    threshold=self.memory_config.similarity_threshold)
            
            # 优化：直接使用已缓存的相似度分数，避免重复计算
            try:
                # 打印所有经验的相似度（使用已计算的值）
                all_experiences = self.memory_manager.get_all_experiences() or []
                for exp in all_experiences:
                    try:
                        # 优先使用已缓存的similarity_score
                        if hasattr(exp, 'similarity_score') and exp.similarity_score is not None:
                            LoggingUtils.log_debug("DroidAgent", "Similarity {score:.2f} to experience goal: {goal}", 
                                                 score=exp.similarity_score, goal=exp.goal)
                        else:
                            # 仅当没有缓存时才重新计算
                            score = self.memory_manager._calculate_similarity(self.goal, exp.goal)
                            LoggingUtils.log_debug("DroidAgent", "Similarity {score:.2f} to experience goal: {goal}", 
                                                 score=score, goal=exp.goal)
                    except ExceptionConstants.DATA_PARSING_EXCEPTIONS as e:
                        ExceptionHandler.handle_data_parsing_error(e, "[SIM] Similarity calculation")
                        continue
            except ExceptionConstants.DATA_PARSING_EXCEPTIONS as e:
                ExceptionHandler.handle_data_parsing_error(e, "[SIM] Experience processing")
            
            if similar_experiences:
                # 合并优化后，经验已经按相似度排序，直接使用第一个（最佳）经验
                use_merged_optimization = self.config_manager.get("memory.use_merged_similarity_ranking", True)

                if use_merged_optimization:
                    # 新方法：直接使用已排序的第一个经验（最佳匹配）
                    best_exp_obj = similar_experiences[0]
                    best_experience = best_exp_obj.to_dict()
                    LoggingUtils.log_success("DroidAgent",
                                           "✅ Using best experience from merged ranking (similarity={score:.2f}), no additional LLM call needed",
                                           score=best_exp_obj.similarity_score)
                else:
                    # 旧方法：检查完美匹配或调用LLM选择
                    perfect_threshold = self.config_manager.get("memory.perfect_match_threshold", 0.999)
                    perfect_matches = [exp for exp in similar_experiences if exp.similarity_score >= perfect_threshold]
                    best_exp_obj = None

                    if perfect_matches:
                        best_exp_obj = max(perfect_matches, key=lambda e: e.similarity_score)
                        best_experience = best_exp_obj.to_dict()
                        LoggingUtils.log_success("DroidAgent", "✅ Perfect match found (similarity={score:.2f}), skipping LLM selection",
                                                score=best_exp_obj.similarity_score)
                    else:
                        LoggingUtils.log_info("DroidAgent", "No perfect match, using LLM to select best from {count} candidates",
                                            count=len(similar_experiences))
                        best_experience = self.llm_services.select_best_experience(
                            [exp.to_dict() for exp in similar_experiences],
                            self.goal
                        )
                
                if best_experience:
                    try:
                        # 获取匹配经验的ID
                        experience_id = best_experience.get("id")
                        experience_goal = best_experience.get("goal", "")
                        LoggingUtils.log_progress("DroidAgent", "Hot start using experience ID: {id}", id=experience_id)
                        
                        # 优化：检测目标是否完全匹配
                        is_perfect_match = (self.goal == experience_goal) or (
                            best_exp_obj is not None and best_exp_obj.similarity_score >= 0.999
                        )
                        
                        # 优先从 macro.json 加载原始动作（最准确）
                        macro_actions = self._load_macro_actions(experience_id)
                        if macro_actions:
                            LoggingUtils.log_success("DroidAgent", "✅ Loaded {count} actions from macro.json (most accurate source)", 
                                                   count=len(macro_actions))
                            original_actions = macro_actions
                        else:
                            # 回退到经验文件的 action_sequence
                            LoggingUtils.log_warning("DroidAgent", "Macro.json not found, fallback to experience action_sequence")
                            original_actions = best_experience.get("action_sequence", [])
                        
                        # 参数自适应
                        if self.memory_config.parameter_adaptation_enabled:
                            # 优化：完美匹配时跳过LLM参数适配
                            if is_perfect_match:
                                LoggingUtils.log_success("DroidAgent", "Perfect match detected, skipping parameter adaptation")
                                self.skip_persist_for_perfect_match = True
                                adapted_actions = original_actions
                            else:
                                LoggingUtils.log_progress("DroidAgent", "Adapting parameters for similar goal (similarity < 1.0)")
                                # 性能分析：记录参数适配耗时
                                adapt_start = time.time()
                                # 创建临时经验对象，使用 macro.json 的动作
                                temp_exp_dict = best_experience.copy()
                                temp_exp_dict["action_sequence"] = original_actions
                                adapted_actions = self.memory_manager.adapt_parameters(
                                    TaskExperience.from_dict(temp_exp_dict), 
                                    self.goal
                                )
                                adapt_duration = time.time() - adapt_start
                                LoggingUtils.log_info("Performance", "⏱️ Parameter adaptation (LLM): {duration:.2f}s", duration=adapt_duration)
                                LoggingUtils.log_progress("DroidAgent", "Parameters adapted for hot start")
                        else:
                            adapted_actions = original_actions
                        
                        # 直执：将动作放入队列，并用 LLM 预判哪些索引是"变更点击步"
                        self.pending_hot_actions = adapted_actions or []
                        if self.pending_hot_actions:
                            LoggingUtils.log_progress("DroidAgent", "Hot start direct-execution prepared with {count} actions", 
                                                    count=len(self.pending_hot_actions))
                            self.pending_hot_context = {
                                "experience_goal": best_experience.get("goal", ""),
                                "experience_actions": best_experience.get("action_sequence", []),
                                "experience_id": experience_id,  # 保存experience_id以备后用
                                "changed_indices": [],
                                "goal_diffs": {}
                            }
                            # 补齐缺失的 description：优先用经验中的描述
                            try:
                                exp_actions = self.pending_hot_context.get("experience_actions", [])
                                for i, act in enumerate(self.pending_hot_actions or []):
                                    if isinstance(act, dict) and not act.get("description"):
                                        if 0 <= i < len(exp_actions):
                                            desc = (exp_actions[i] or {}).get("description")
                                            if desc:
                                                act["description"] = desc
                            except Exception:
                                pass
                            try:
                                # 优化：完美匹配时跳过LLM变更检测
                                if is_perfect_match:
                                    LoggingUtils.log_info("DroidAgent", "Perfect match detected, skipping change detection (no changes expected)")
                                    self.pending_hot_context["changed_indices"] = []
                                    self.pending_hot_context["changed_index_reasons"] = []
                                else:
                                    # 在传入前，对仍缺 description 的动作进行通用语义补齐
                                    for a in self.pending_hot_actions:
                                        if isinstance(a, dict) and not a.get("description"):
                                            name = (a or {}).get("action") or (a or {}).get("name") or ""
                                            params = (a or {}).get("params") or (a or {}).get("parameters") or {}
                                            a["description"] = f"{name} with params {json.dumps(params, ensure_ascii=False)}"

                                    LoggingUtils.log_info("DroidAgent", "Detecting changed actions for similar goal (similarity < 1.0)")
                                    # 性能分析：记录变更检测耗时
                                    detect_start = time.time()
                                    det = self.llm_services.detect_changed_actions(
                                        self.pending_hot_context["experience_goal"],
                                        self.goal,
                                        self.pending_hot_actions
                                    )
                                    detect_duration = time.time() - detect_start
                                    LoggingUtils.log_info("Performance", "⏱️ Change detection (LLM): {duration:.2f}s", duration=detect_duration)
                                    self.pending_hot_context["changed_indices"] = det.get("changed_indices", [])
                                    # 保存 index->reason，用于更具体的微冷启动子目标
                                    self.pending_hot_context["changed_index_reasons"] = det.get("index_reasons", [])

                                    # 使用 INFO 级别确保日志输出
                                    if self.pending_hot_context['changed_indices']:
                                        LoggingUtils.log_info("DroidAgent",
                                                            "🔄 Detected {count} actions need adaptation: indices={indices}",
                                                            count=len(self.pending_hot_context['changed_indices']),
                                                            indices=self.pending_hot_context['changed_indices'])
                                        # 打印每个变更动作的理由
                                        for ir in self.pending_hot_context.get("changed_index_reasons", []):
                                            LoggingUtils.log_info("DroidAgent",
                                                                "  - Action {idx}: {reason}",
                                                                idx=ir.get("index"),
                                                                reason=ir.get("reason"))
                                    else:
                                        LoggingUtils.log_warning("DroidAgent",
                                                               "⚠️ No changed actions detected by LLM (may cause hot-start to fail if parameters differ)")

                                    LoggingUtils.log_debug("DroidAgent", "Changed action indices predicted: {indices}",
                                                         indices=self.pending_hot_context['changed_indices'])
                            except ExceptionConstants.DATA_PARSING_EXCEPTIONS as e:
                                ExceptionHandler.handle_data_parsing_error(e, "[HOT] Change detection")
                            task = Task(
                                description="[HOT] Directly execute adapted actions",
                                status=self.task_manager.STATUS_PENDING,
                                agent_type="Default",
                            )
                            return CodeActExecuteEvent(task=task, reflection=None)
                    except ExceptionConstants.RUNTIME_EXCEPTIONS as e:
                        ExceptionHandler.handle_runtime_error(e, "[HOT] Hot start", reraise=False)
                        # 如果热启动失败，继续执行冷启动逻辑
            else:
                LoggingUtils.log_info("DroidAgent", "Cold start: No similar experiences found")

        if not self.reasoning:
            LoggingUtils.log_progress("DroidAgent", "Direct execution mode - executing goal: {goal}", goal=self.goal)
            task = Task(
                description=self.goal,
                status=self.task_manager.STATUS_PENDING,
                agent_type="Default",
            )

            return CodeActExecuteEvent(task=task, reflection=None)

        return ReasoningLogicEvent()

    @step
    async def finalize(self, ctx: Context, ev: FinalizeEvent) -> StopEvent:
        ctx.write_event_to_stream(ev)
        
        if hasattr(self, '_task_start_time'):
            total_duration = time.time() - self._task_start_time
            LoggingUtils.log_info("Performance", "⏱️ ✅ Task completed in {duration:.2f}s (success={success}, steps={steps})", 
                                duration=total_duration, success=ev.success, steps=ev.steps)
        
        capture(
            DroidAgentFinalizeEvent(
                tasks=",".join([f"{t.agent_type}:{t.description}" for t in ev.task]),
                success=ev.success,
                output=ev.output,
                steps=ev.steps,
            ),
            self.user_id,
        )
        flush()

        result = {
            "success": ev.success,
            # deprecated. use output instead.
            "reason": ev.reason,
            "output": ev.output,
            "steps": ev.steps,
        }
        if getattr(self, 'skip_persist_for_perfect_match', False):
            LoggingUtils.log_info("DroidAgent", "该任务已有高度重合的历史经验，不再持久化该任务")
            return StopEvent(result)
            
        if self.trajectory and self.save_trajectories != "none":
            self.trajectory.save_trajectory()

            # 轨迹保存完成后，保存经验到记忆系统（尽量不阻塞收尾阶段）
            if self.memory_enabled and ev.success:
                try:
                    wait_time = self.config_manager.get("tools.macro_generation_wait_time", 0.5)
                    await asyncio.sleep(wait_time)
                    experience = self._build_experience_from_execution(ev)
                    saved_path = self.memory_manager.save_experience(experience)
                    LoggingUtils.log_success("DroidAgent", "Experience saved to: {path}", path=saved_path)
                except ExceptionConstants.FILE_OPERATION_EXCEPTIONS as e:
                    ExceptionHandler.handle_file_operation_error(e, "[Experience] Save")
                except Exception as e:
                    log_error("[Experience] Save", e, level="warning")

        # Best-effort resource cleanup hooks (e.g., device TCP forwards)
        try:
            tools = getattr(self, "tools", None)
            if tools and isinstance(tools, AdbTools):
                tools.teardown_tcp_forward()
        except Exception:
            pass

        return StopEvent(result)

    def handle_stream_event(self, ev: Event, ctx: Context):
        if isinstance(ev, EpisodicMemoryEvent):
            self.current_episodic_memory = ev.episodic_memory
            return

        if not isinstance(ev, StopEvent):
            # 补齐事件时间戳，保证可排序
            try:
                if not hasattr(ev, "timestamp") or ev.timestamp is None:
                    setattr(ev, "timestamp", time.time())
            except ExceptionConstants.DATA_PARSING_EXCEPTIONS as e:
                ExceptionHandler.handle_data_parsing_error(e, "[Event] Timestamp setting")
            ctx.write_event_to_stream(ev)

            if isinstance(ev, ScreenshotEvent):
                self.trajectory.screenshots.append(ev.screenshot)
            elif isinstance(ev, MacroEvent):
                self.trajectory.macro.append(ev)
            elif isinstance(ev, RecordUIStateEvent):
                self.trajectory.ui_states.append(ev.ui_state)
            else:
                self.trajectory.events.append(ev)
    
    async def _direct_execute_actions_async(self, ctx: Context, actions: List[Dict]) -> tuple[bool, str]:
        """
        直接执行热启动动作（异步），必要时触发微冷启动子流程。
        """
        hot_start_begin = time.time()
        LoggingUtils.log_info("Performance", "🔥 Hot start execution begins with {count} actions", count=len(actions))
        
        try:
            tools = self.tools_instance

            # 为工具设置上下文，确保 MacroEvent 能够正确创建
            if tools and hasattr(tools, '_set_context'):
                tools._set_context(ctx)
            
            if tools:
                tools._trajectory = self.trajectory
                tools._manual_event_recording = True
            
            step_count = 0
            init_ui_start = time.time()
            LoggingUtils.log_debug("DroidAgent", "Initializing UI state cache...")
            try:
                ui_state = await tools.get_state_async(include_screenshot=True)
                init_ui_duration = time.time() - init_ui_start
                LoggingUtils.log_info("Performance", "⏱️ Initial UI state: {duration:.2f}s", duration=init_ui_duration)
                LoggingUtils.log_debug("DroidAgent", "UI state initialized with {count} elements", 
                                     count=len(ui_state.get('elements', [])))
                
                # 创建RecordUIStateEvent并添加到trajectory
                if ui_state and 'a11y_tree' in ui_state:
                    ui_state_event = RecordUIStateEvent(ui_state=ui_state['a11y_tree'])
                    self.trajectory.ui_states.append(ui_state_event.ui_state)
                    LoggingUtils.log_info("DroidAgent", "Initial UI state recorded")
            except ExceptionConstants.FILE_OPERATION_EXCEPTIONS as e:
                LoggingUtils.log_warning("DroidAgent", "Failed to initialize UI state: {error}", error=e)
                return False, f"Failed to initialize UI state: {e}"
            
            reconstruct_start = time.time()
            actions = self._reconstruct_actions_with_changes(actions)
            self.reconstructed_actions_list = actions
            reconstruct_duration = time.time() - reconstruct_start
            LoggingUtils.log_info("Performance", "⏱️ Actions reconstruction: {duration:.2f}s", duration=reconstruct_duration)
            if not hasattr(tools, '_action_comments'):
                tools._action_comments = {}
            else:
                tools._action_comments = {}
            total_actions = 0
            skipped_no_behavior = 0
            skipped_micro_coldstart = 0
            
            for action in actions:
                total_actions += 1
                action_name = action.get('action', '')
                params = action.get('params', {})
                specific_behavior = action.get('specific_behavior')
                
                if action_name == 'micro_coldstart':
                    skipped_micro_coldstart += 1
                    continue
                
                if specific_behavior:
                    if action_name in ['tap_by_index', 'tap', 'tap_index']:
                        index = params.get('index', -1)
                        func_call = f'tap_by_index({index})'
                        tools._action_comments[func_call] = specific_behavior
                    elif action_name in ['input_text', 'type', 'input']:
                        text = params.get('text', params.get('value', ''))
                        index = params.get('index', None)
                        if index is not None:
                            func_call = f'input_text("{text[:20]}", {index})'
                        else:
                            func_call = f'input_text("{text[:20]}")'
                        tools._action_comments[func_call] = specific_behavior
                else:
                    skipped_no_behavior += 1
            
            LoggingUtils.log_info("DroidAgent", "Hot start: loaded {count} specific_behavior from {total} actions (skipped {no_behavior} without behavior, {micro} micro_coldstart)", 
                                count=len(tools._action_comments), total=total_actions, 
                                no_behavior=skipped_no_behavior, micro=skipped_micro_coldstart)

            executed_actions = []
            # 基于 changed_indices 的微冷启动触发记录，避免重复触发同一索引
            triggered_changed_steps: Dict[int, bool] = {}
            
            actions_loop_start = time.time()
            LoggingUtils.log_info("Performance", "🔄 Starting actions loop ({count} actions)", count=len(actions))
            
            for idx_action, act in enumerate(actions):
                action_start = time.time()
                name = (act or {}).get("action") or (act or {}).get("name")
                params = (act or {}).get("params", {}) or (act or {}).get("parameters", {})
                LoggingUtils.log_info("Performance", "➡️ Action {current}/{total}: {name}", 
                                     current=idx_action+1, total=len(actions), name=name)
                LoggingUtils.log_debug("DroidAgent", "Executing action {current}/{total}: {name} params={params}", 
                                     current=idx_action+1, total=len(actions), name=name, params=params)
                try:
                    if name == "micro_coldstart":
                        LoggingUtils.log_info("DroidAgent", "🎯 Executing added action at step {step}", step=idx_action)

                        ok = await self._micro_coldstart_handle_click_step(idx_action, act)
                        if ok:
                            LoggingUtils.log_success("DroidAgent", "✅ Added action completed at step {step}", step=idx_action)
                            step_count += 1
                            await self._capture_ui_state_and_screenshot("added-action")
                            if idx_action < len(actions) - 1:
                                wait_time = self.config_manager.get("tools.action_wait_time", 0.5)
                                time.sleep(wait_time)
                        else:
                            LoggingUtils.log_warning("DroidAgent", "⚠️ Added action failed at step {step}", step=idx_action)
                            return False, f"Added action at step {idx_action} failed"
                        continue

                    if name in ("tap_by_index", "tap", "tap_index"):
                        idx_val = params.get("index", params.get("idx"))
                        try:
                            default_idx = self.config_manager.get("tools.default_index", -1)
                            idx = int(idx_val) if idx_val is not None else default_idx
                        except ExceptionConstants.DATA_PARSING_EXCEPTIONS as e:
                            ExceptionHandler.handle_data_parsing_error(e, "[HOT] Index parsing")
                            idx = self.config_manager.get("tools.default_index", -1)
                        if idx >= 0:
                            is_changed = self._is_changed_param_click_step(idx_action, act)
                            if is_changed and not triggered_changed_steps.get(idx_action):
                                LoggingUtils.log_info("DroidAgent", "🎯 Triggering micro-coldstart for step {step} (action: {action})",
                                                     step=idx_action, action=name)
                                ok = await self._micro_coldstart_handle_click_step(idx_action, act)
                                triggered_changed_steps[idx_action] = True
                                if ok:
                                    LoggingUtils.log_info("DroidAgent", "[DEBUG] Micro-coldstart succeeded, skipping direct tap")
                                    step_count += 1
                                    # 使用通用方法捕获UI状态和截图
                                    await self._capture_ui_state_and_screenshot("micro-coldstart")
                                    if idx_action < len(actions) - 1:
                                        wait_time = self.config_manager.get("tools.action_wait_time", 0.5)
                                        time.sleep(wait_time)
                                    # 微冷启动的 MacroEvent 已经在 _micro_coldstart_handle_click_step 中捕获
                                    # 成功后继续到下一步（不再执行原点击）
                                    continue
                                else:
                                    LoggingUtils.log_warning("DroidAgent", "❄️ Micro-coldstart failed for step {step}, falling back to cold start", 
                                                           step=idx_action)
                                    return False, f"Micro-coldstart failed at step {idx_action}, fallback to cold start"
                            
                            tap_start = time.time()
                            tap_result = await tools.tap_by_index(idx)
                            tap_duration = time.time() - tap_start
                            
                            # 检查动作是否执行成功
                            if tap_result and "Error" in tap_result:
                                LoggingUtils.log_warning("DroidAgent", "❄️ Hot start action failed at step {step}: {error}, falling back to cold start", 
                                                       step=idx_action, error=tap_result)
                                return False, f"Hot start action failed at step {idx_action}: {tap_result}"
                            
                            # 使用动态等待代替固定延迟
                            use_dynamic_wait = self.config_manager.get("tools.use_dynamic_wait", True)
                            if use_dynamic_wait:
                                wait_start = time.time()
                                fallback_delay = self.config_manager.get("tools.screenshot_wait_time", 1.0)
                                wait_duration = await self.ui_stability_checker.smart_wait("tap", fallback_delay)
                                LoggingUtils.log_debug("DroidAgent", "⏱️ Dynamic wait completed in {duration:.2f}s", duration=wait_duration)
                            else:
                                # 传统固定延迟
                                screenshot_wait = self.config_manager.get("tools.screenshot_wait_time", 1.0)
                                wait_start = time.time()
                                time.sleep(screenshot_wait)
                                wait_duration = time.time() - wait_start
                            
                            capture_start = time.time()
                            await self._capture_ui_state_and_screenshot("tap")
                            capture_duration = time.time() - capture_start
                            
                            step_count += 1
                            executed_actions.append({
                                "action": "tap_by_index",
                                "params": {"index": idx},
                                "success": True,
                                "timestamp": time.time()
                            })
                            
                    elif name in ("input_text", "type", "input"):
                        text = params.get("text", params.get("value", ""))
                        text = str(text) if text is not None else ""
                        index = params.get("index", None)
                        if text:
                            input_start = time.time()
                            if index is not None:
                                input_result = await tools.input_text(text, index)
                            else:
                                input_result = await tools.input_text(text)
                            input_duration = time.time() - input_start
                            
                            # 检查动作是否执行成功
                            if input_result and "Error" in input_result:
                                LoggingUtils.log_warning("DroidAgent", "❄️ Hot start action failed at step {step}: {error}, falling back to cold start", 
                                                       step=idx_action, error=input_result)
                                return False, f"Hot start action failed at step {idx_action}: {input_result}"
                            
                            # 使用动态等待代替固定延迟
                            use_dynamic_wait = self.config_manager.get("tools.use_dynamic_wait", True)
                            if use_dynamic_wait:
                                wait_start = time.time()
                                fallback_delay = self.config_manager.get("tools.action_wait_time", 0.5)
                                wait_duration = await self.ui_stability_checker.smart_wait("input", fallback_delay)
                                LoggingUtils.log_debug("DroidAgent", "⏱️ Dynamic wait completed in {duration:.2f}s", duration=wait_duration)
                            else:
                                # 传统固定延迟
                                wait_time = self.config_manager.get("tools.action_wait_time", 0.5)
                                wait_start = time.time()
                                time.sleep(wait_time)
                                wait_duration = time.time() - wait_start
                            
                            capture_start = time.time()
                            await self._capture_ui_state_and_screenshot("input")
                            capture_duration = time.time() - capture_start
                            
                            step_count += 1
                            executed_actions.append({
                                "action": "input_text",
                                "params": {"text": text, "index": index} if index is not None else {"text": text},
                                "success": True,
                                "timestamp": time.time()
                            })
                            
                    elif name == "swipe":
                        start = params.get("start") or params.get("from") or {}
                        end = params.get("end") or params.get("to") or {}
                        default_x = self.config_manager.get("tools.default_x_coordinate", 0)
                        default_y = self.config_manager.get("tools.default_y_coordinate", 0)
                        default_duration = self.config_manager.get("tools.default_swipe_duration", 300)
                        sx = int(params.get("start_x", start[0] if isinstance(start, (list, tuple)) and len(start) >= 2 else start.get("x", default_x)))
                        sy = int(params.get("start_y", start[1] if isinstance(start, (list, tuple)) and len(start) >= 2 else start.get("y", default_y)))
                        ex = int(params.get("end_x", end[0] if isinstance(end, (list, tuple)) and len(end) >= 2 else end.get("x", default_x)))
                        ey = int(params.get("end_y", end[1] if isinstance(end, (list, tuple)) and len(end) >= 2 else end.get("y", default_y)))
                        dur = int(params.get("duration_ms", params.get("duration", default_duration)))
                        swipe_result = await tools.swipe(sx, sy, ex, ey, dur)
                        
                        # 检查动作是否执行成功
                        if swipe_result and "Error" in str(swipe_result):
                            LoggingUtils.log_warning("DroidAgent", "❄️ Hot start action failed at step {step}: {error}, falling back to cold start", 
                                                   step=idx_action, error=swipe_result)
                            return False, f"Hot start action failed at step {idx_action}: {swipe_result}"
                        
                        screenshot_wait = self.config_manager.get("tools.screenshot_wait_time", 1.0)
                        time.sleep(screenshot_wait)
                        await self._capture_ui_state_and_screenshot("swipe")
                        
                        swipe_event = SwipeActionEvent(
                            action_type="swipe",
                            description=f"Swipe from ({sx}, {sy}) to ({ex}, {ey})",
                            start_x=sx,
                            start_y=sy,
                            end_x=ex,
                            end_y=ey,
                            duration_ms=dur
                        )
                        self.trajectory.macro.append(swipe_event)
                        
                        step_count += 1
                    elif name == "start_app":
                        pkg = params.get("package", params.get("pkg", ""))
                        pkg = str(pkg) if pkg is not None else ""
                        if pkg:
                            start_app_result = await tools.start_app(pkg)
                            
                            # 检查动作是否执行成功
                            if start_app_result and "Error" in str(start_app_result):
                                LoggingUtils.log_warning("DroidAgent", "❄️ Hot start action failed at step {step}: {error}, falling back to cold start", 
                                                       step=idx_action, error=start_app_result)
                                return False, f"Hot start action failed at step {idx_action}: {start_app_result}"
                            
                            long_wait = self.config_manager.get("tools.long_wait_time", 2.0)
                            time.sleep(long_wait)
                            try:
                                ui_state = await tools.get_state_async(include_screenshot=True)
                                if ui_state and 'a11y_tree' in ui_state:
                                    ui_state_event = RecordUIStateEvent(ui_state=ui_state['a11y_tree'])
                                    self.trajectory.ui_states.append(ui_state_event.ui_state)
                            except ExceptionConstants.FILE_OPERATION_EXCEPTIONS as e:
                                LoggingUtils.log_warning("DroidAgent", "Failed to capture state after start_app: {error}", error=e)
                            
                            start_app_event = StartAppEvent(
                                action_type="start_app",
                                description=f"Start app: {pkg}",
                                package=pkg
                            )
                            self.trajectory.macro.append(start_app_event)
                            
                            step_count += 1
                    elif name == "press_key":
                        key_val = params.get("keycode", params.get("key", 0))
                        try:
                            keycode = int(key_val)
                        except ExceptionConstants.DATA_PARSING_EXCEPTIONS as e:
                            ExceptionHandler.handle_data_parsing_error(e, "[HOT] Keycode parsing")
                            keycode = 0
                        if keycode:
                            await tools.press_key(keycode)
                            wait_time = self.config_manager.get("tools.action_wait_time", 0.5)
                            time.sleep(wait_time)
                            # 使用通用方法捕获UI状态和截图
                            await self._capture_ui_state_and_screenshot("press_key")
                            
                            # 创建KeyPressActionEvent并添加到macro
                            
                            key_event = KeyPressActionEvent(
                                action_type="press_key",
                                description=f"Press key: {keycode}",
                                keycode=keycode
                            )
                            self.trajectory.macro.append(key_event)
                            
                            step_count += 1
                    elif name in ("sleep", "wait"):
                        
                        ms = int(params.get("ms", params.get("milliseconds", 0)))
                        sec = int(params.get("sec", 0))
                        delay = sec if sec > 0 else (ms / 1000.0 if ms > 0 else 0)
                        if delay > 0:
                            time.sleep(delay)
                            step_count += 1
                    elif name == "complete":
                        reason = str(params.get("reason", "Hot start direct execution finished"))
                        return True, reason
                    else:
                        LoggingUtils.log_warning("DroidAgent", "Unknown action type: {name}, skipping...", name=name)
                except ExceptionConstants.RUNTIME_EXCEPTIONS as action_error:
                    ExceptionHandler.handle_runtime_error(action_error, f"[HOT] Action {idx_action+1}", reraise=False)
                    try:
                        await tools.get_state_async(include_screenshot=False)
                    except ExceptionConstants.FILE_OPERATION_EXCEPTIONS as e:
                        ExceptionHandler.handle_file_operation_error(e, "[HOT] State capture after action failure")
                    continue
                if idx_action < len(actions) - 1:
                    wait_time = self.config_manager.get("tools.action_wait_time", 0.5)
                    time.sleep(wait_time)
            # 写回到轨迹 - 使用事件对象而不是字典
            if executed_actions:
                try:
                    
                    for a in executed_actions:
                        # 创建TaskExecutionEvent对象，locals字段的值必须全部是字符串类型
                        event_data = {
                            "event_type": "task_execution",
                            "action": str(a["action"]),
                            "params": json.dumps(a["params"], ensure_ascii=False) if isinstance(a["params"], dict) else str(a["params"]),
                            "timestamp": str(a["timestamp"]),
                            "success": str(a.get("success", True))
                        }
                        # 创建事件对象
                        event = TaskExecutionEvent(
                            code=f"{a['action']}({a['params']})",
                            globals={},
                            locals=event_data
                        )
                        self.trajectory.events.append(event)
                except ExceptionConstants.DATA_PARSING_EXCEPTIONS as e:
                    ExceptionHandler.handle_data_parsing_error(e, "[HOT] Trajectory event creation")
            
            actions_loop_duration = time.time() - actions_loop_start
            LoggingUtils.log_info("Performance", "⏱️ Actions loop completed: {duration:.2f}s", duration=actions_loop_duration)
            
            hot_start_total = time.time() - hot_start_begin
            LoggingUtils.log_info("Performance", "🔥 Hot start total time: {duration:.2f}s", duration=hot_start_total)
            
            if step_count == 0:
                return False, "No hot-start actions were executed (unrecognized schema)."
            return True, f"Hot-start direct execution finished with {step_count} actions"
        except ExceptionConstants.RUNTIME_EXCEPTIONS as e:
            ExceptionHandler.handle_runtime_error(e, "[HOT] Direct execution", reraise=False)
            return False, f"Direct execution failed: {e}"
        finally:
            # 清理手动事件记录标志，避免影响后续的冷启动
            if tools and hasattr(tools, '_manual_event_recording'):
                tools._manual_event_recording = False
            if tools and hasattr(tools, '_trajectory'):
                tools._trajectory = None

    async def _capture_ui_state_and_screenshot(self, context: str) -> bool:
        """
        捕获UI状态和截图的通用方法（异步）
        
        Args:
            context: 捕获上下文描述，用于日志记录
            
        Returns:
            bool: 是否成功捕获
        """
        try:
            tools = self.tools_instance
            
            # 捕获UI状态（异步）
            ui_state = await tools.get_state_async(include_screenshot=True)
            if ui_state and 'a11y_tree' in ui_state:
                ui_state_event = RecordUIStateEvent(ui_state=ui_state['a11y_tree'])
                self.trajectory.ui_states.append(ui_state_event.ui_state)

            return True
            
        except ExceptionConstants.FILE_OPERATION_EXCEPTIONS as e:
            ExceptionHandler.handle_file_operation_error(e, f"[HOT] State capture after {context}")
            return False

    async def _save_experience_async(self, ev: FinalizeEvent) -> None:
        """
        异步保存经验到记忆系统，不阻塞主流程
        
        Args:
            ev: 最终化事件
        """
        try:
            # 确保macro.json已经生成
            wait_time = self.config_manager.get("tools.macro_generation_wait_time", 0.5)
            await asyncio.sleep(wait_time)
            
            # 构建经验
            experience = self._build_experience_from_execution(ev)
            
            # 保存经验
            saved_path = self.memory_manager.save_experience(experience)
            LoggingUtils.log_success("DroidAgent", "Experience saved to: {path}", path=saved_path)
            
        except ExceptionConstants.FILE_OPERATION_EXCEPTIONS as e:
            ExceptionHandler.handle_file_operation_error(e, "[Experience] Save")

    def _get_time_constant(self, key: str, default: float = 0.5) -> float:
        """从配置中获取时间常量"""
        return self.config_manager.get(f"tools.{key}", default)
    
    def _get_ui_constant(self, key: str, default=0):
        """从配置中获取UI常量"""
        return self.config_manager.get(f"tools.{key}", default)
    
    def _get_memory_constant(self, key: str, default=0.85):
        """从配置中获取内存系统常量"""
        return self.config_manager.get(f"memory.{key}", default)
    
    def _get_agent_constant(self, key: str, default: int = 20) -> int:
        """从配置中获取Agent常量"""
        return self.config_manager.get(f"agent.{key}", default)

    def _reconstruct_actions_with_changes(self, actions: List[Dict]) -> List[Dict]:
        """根据 Added 和 Removed 信息重构 actions 列表

        处理逻辑：
        1. 删除 Removed 动作
        2. 在正确的位置插入 Added 动作
        3. 标记 Changed 动作

        Args:
            actions: 原始动作列表

        Returns:
            重构后的动作列表
        """
        try:
            # 获取变更信息
            changed_index_reasons = (self.pending_hot_context or {}).get("changed_index_reasons", [])

            if not changed_index_reasons:
                LoggingUtils.log_debug("DroidAgent", "No changes detected, using original actions")
                return actions

            # 构建变更信息映射
            removed_indices = set()
            added_actions_map = {}  # {base_index: [(float_index, reason), ...]}
            changed_reasons = {}

            for ir in changed_index_reasons:
                idx = ir.get("index")
                action_type = ir.get("type", "changed")
                reason = ir.get("reason", "")

                if action_type == "removed":
                    removed_indices.add(idx)
                elif action_type == "added" and isinstance(idx, float):
                    base_idx = int(idx)
                    if base_idx not in added_actions_map:
                        added_actions_map[base_idx] = []
                    added_actions_map[base_idx].append((idx, reason))
                elif action_type == "changed":
                    changed_reasons[idx] = reason

            # 第一步：过滤掉 Removed 动作
            filtered_actions = []
            for idx, act in enumerate(actions):
                if idx in removed_indices:
                    LoggingUtils.log_info("DroidAgent", "➖ Removing action [{idx}]: {desc}",
                                        idx=idx, desc=act.get("description", ""))
                else:
                    act = act.copy()  # 避免修改原始字典
                    act["_original_index"] = idx  # 记录原始索引

                    # 标记 Changed 动作
                    if idx in changed_reasons:
                        act["_is_changed"] = True
                        act["_change_reason"] = changed_reasons[idx]

                    filtered_actions.append(act)

            # 第二步：插入 Added 动作
            # 需要从后往前插入，避免索引偏移
            for base_idx in sorted(added_actions_map.keys(), reverse=True):
                added_list = sorted(added_actions_map[base_idx])  # 按浮点索引排序

                # 找到 base_idx 在 filtered_actions 中的位置
                insert_pos = None
                for i, act in enumerate(filtered_actions):
                    original_idx = act.get("_original_index", i)
                    if original_idx == base_idx:
                        insert_pos = i + 1
                        break

                if insert_pos is None:
                    # 如果没找到，可能是因为 base_idx 被 removed 了，插入到末尾
                    insert_pos = len(filtered_actions)

                # 插入所有 Added 动作
                for added_idx, reason in reversed(added_list):
                    added_action = {
                        "action": "micro_coldstart",
                        "params": {"goal": reason},
                        "description": reason,
                        "_is_added": True,
                        "_is_changed": True,  # Added 动作也需要微冷启动
                        "_change_reason": reason,
                        "_added_index": added_idx,
                        "_original_index": added_idx
                    }

                    filtered_actions.insert(insert_pos, added_action)
                    LoggingUtils.log_info("DroidAgent", "➕ Adding action at [{idx}]: {desc}",
                                        idx=added_idx, desc=reason)

            # 统计信息
            removed_count = len(removed_indices)
            added_count = sum(len(v) for v in added_actions_map.values())
            changed_count = len(changed_reasons)

            LoggingUtils.log_info("DroidAgent",
                                "📝 Actions reconstructed: {original} → {final} actions (removed={removed}, added={added}, changed={changed})",
                                original=len(actions),
                                final=len(filtered_actions),
                                removed=removed_count,
                                added=added_count,
                                changed=changed_count)

            return filtered_actions

        except Exception as e:
            LoggingUtils.log_warning("DroidAgent",
                                   "Failed to reconstruct actions: {error}, using original actions",
                                   error=e)
            return actions

    def _is_changed_param_click_step(self, step_index: int, action: Dict) -> bool:
        """检查动作是否需要微冷启动

        在重构后的 actions 列表中，Changed 和 Added 动作都被标记了 _is_changed
        """
        try:
            name = (action or {}).get("action") or (action or {}).get("name")
            if name in ("input_text", "type", "input"):
                return False

            # 检查动作是否被标记为需要变更
            return action.get("_is_changed", False)

        except ExceptionConstants.DATA_PARSING_EXCEPTIONS as e:
            ExceptionHandler.handle_data_parsing_error(e, "[HOT] Click step detection")
            return False

    async def _micro_coldstart_handle_click_step(self, step_index: int, action: Dict) -> bool:
        """微冷启动处理单步点击操作

        在重构后的 actions 列表中，Changed 和 Added 动作都包含 _change_reason
        """
        try:
            action_name = action.get('action', 'unknown')
            params = action.get('params', {})
            desc = str(action.get('description', ''))
            
            # 优先使用动作中的 _change_reason（由重构方法添加）
            micro_goal = action.get('_change_reason')

            # 若未找到，再调用通用生成逻辑
            if not micro_goal:
                micro_goal = self.llm_services.generate_micro_goal(action, {}, self.goal)
            
            LoggingUtils.log_progress("DroidAgent", "Micro cold start for step {step}: {goal}", step=step_index, goal=micro_goal)
            LoggingUtils.log_debug("DroidAgent", "Action details: {name} with params {params}", name=action_name, params=params)
            LoggingUtils.log_debug("DroidAgent", "Task description: '{goal}'", goal=micro_goal)
            
            
            max_micro_steps = self.config_manager.get("agent.max_micro_cold_steps", 5)

            # 重置 tools 状态，避免上一个微冷启动的状态影响当前任务
            self.tools_instance.finished = False
            self.tools_instance.success = None
            self.tools_instance.reason = None
            
            macro_length_before = len(self.trajectory.macro) if self.trajectory else 0
            original_ctx = getattr(self.tools_instance, '_ctx', None)
            original_manual_recording = getattr(self.tools_instance, '_manual_event_recording', False)
            self.tools_instance._manual_event_recording = False
            
            from droidrun.agent.codeact.codeact_agent_micro import CodeActAgentMicro
            
            try:
                agent = CodeActAgentMicro(
                    llm=self.llm,
                    persona=self.cim.get_persona("Default"),
                    vision=self.vision,
                    max_steps=max_micro_steps,
                    all_tools_list=self.tool_list,
                    tools_instance=self.tools_instance,
                    debug=self.debug,
                    timeout=min(self.timeout, self.config_manager.get("agent.micro_cold_timeout", 60)),
                )
                
                handler = agent.run(input=micro_goal, remembered_info=self.tools_instance.memory, reflection=None)
                from droidrun.agent.common.events import MacroEvent, RecordUIStateEvent
                micro_macro_events = []
                micro_ui_states = []
                async for event in handler.stream_events():
                    if isinstance(event, MacroEvent):
                        micro_macro_events.append(event)
                        LoggingUtils.log_debug("DroidAgent", "Captured micro-coldstart MacroEvent: {type}", 
                                             type=type(event).__name__)
                    elif isinstance(event, RecordUIStateEvent):
                        micro_ui_states.append(event.ui_state)
                
                micro_timeout = self.config_manager.get("agent.micro_cold_timeout", 150)
                result = await asyncio.wait_for(handler, timeout=micro_timeout)
                if micro_macro_events:
                    self.trajectory.macro.extend(micro_macro_events)
                    LoggingUtils.log_info("DroidAgent", "Merged {count} MacroEvents from micro-coldstart", 
                                        count=len(micro_macro_events))
                if micro_ui_states:
                    self.trajectory.ui_states.extend(micro_ui_states)
                    LoggingUtils.log_debug("DroidAgent", "Merged {count} UI states from micro-coldstart", 
                                         count=len(micro_ui_states))
            finally:
                if original_ctx:
                    self.tools_instance._set_context(original_ctx)
                self.tools_instance._manual_event_recording = original_manual_recording
            
            success = bool(result.get("success", False))
            if success:
                LoggingUtils.log_success("DroidAgent", "Micro cold start completed for step {step}", step=step_index)
                
                if self.trajectory:
                    macro_length_after = len(self.trajectory.macro)
                    new_actions_count = macro_length_after - macro_length_before
                    
                    LoggingUtils.log_debug("DroidAgent", "Macro length before: {before}, after: {after}, new: {new}",
                                         before=macro_length_before, after=macro_length_after, new=new_actions_count)
                    
                    if new_actions_count > 0:
                        LoggingUtils.log_info("DroidAgent", "✅ Merged {count} actions from micro-coldstart to main trajectory", 
                                            count=new_actions_count)
                        for i in range(macro_length_before, macro_length_after):
                            action = self.trajectory.macro[i]
                            LoggingUtils.log_debug("DroidAgent", "  - Action {idx}: {type}", 
                                                 idx=i, type=type(action).__name__)
                    else:
                        LoggingUtils.log_warning("DroidAgent", "⚠️ No new actions found in micro-coldstart!")
            else:
                LoggingUtils.log_warning("DroidAgent", "Micro cold start failed for step {step}", step=step_index)
            
            return success
        
        except asyncio.TimeoutError:
            LoggingUtils.log_warning("DroidAgent", "⏱️ Micro-coldstart timeout for step {step} (limit: {timeout}s)", 
                                   step=step_index, timeout=self.config_manager.get("agent.micro_cold_timeout", 150))
            return False
            
        except ExceptionConstants.RUNTIME_EXCEPTIONS as e:
            ExceptionHandler.handle_runtime_error(e, f"[MicroColdStart] Step {step_index}", reraise=False)
            return False
    
    def _handle_fallback(self, monitor_result: MonitorResult, task: Task) -> CodeActResultEvent:
        """处理回退逻辑"""
        fallback_strategy = self.execution_monitor.suggest_fallback(monitor_result)
        LoggingUtils.log_warning("DroidAgent", "Applying fallback strategy: {strategy}", strategy=fallback_strategy)
        
        # 根据回退类型选择策略
        if monitor_result.fallback_type == "consecutive_failures":
            # 回退到冷启动
            LoggingUtils.log_info("DroidAgent", "Falling back to cold start mode")
            return CodeActResultEvent(
                success=False,
                reason=f"Fallback triggered: {monitor_result.message}",
                task=task,
                steps=0
            )
        elif monitor_result.fallback_type == "timeout":
            # 简化任务
            LoggingUtils.log_info("DroidAgent", "Simplifying task due to timeout")
            return CodeActResultEvent(
                success=False,
                reason=f"Task timeout: {monitor_result.message}",
                task=task,
                steps=0
            )
        else:
            # 默认回退
            return CodeActResultEvent(
                success=False,
                reason=f"Fallback: {monitor_result.message}",
                task=task,
                steps=0
            )
    
    def _build_experience_from_execution(self, ev: FinalizeEvent) -> TaskExperience:
        """从执行结果构建经验"""
        page_sequence = []
        
        # 提取动作序列
        action_sequence = []
        if self.trajectory and self.trajectory.events:
            # 优先使用 macro.json 中的动作描述
            action_sequence = self._extract_actions_from_trajectory_with_descriptions()
            
            # 热启动且有重构后的动作列表时，验证新增动作
            is_hot_start = getattr(self, 'is_hot_start_execution', False)
            reconstructed_actions = getattr(self, 'reconstructed_actions_list', None)
            
            if is_hot_start and reconstructed_actions:
                # 提取所有新增动作（action == "micro_coldstart"）的信息
                added_actions = [a for a in reconstructed_actions if a.get('_is_added')]
                if added_actions:
                    LoggingUtils.log_info("DroidAgent", "Found {count} added actions in reconstructed list", 
                                        count=len(added_actions))
                    
                    # 微冷启动执行的实际动作已经通过 tools_instance 记录到 self.trajectory.macro 中
                    # _extract_actions_from_trajectory_with_descriptions 会从 macro.json 中提取所有动作
                    # 所以这里只需要验证 action_sequence 的数量是否合理
                    macro_actions_count = len(self.trajectory.macro) if self.trajectory else 0
                    original_actions_count = len([a for a in reconstructed_actions if not a.get('_is_added')])
                    
                    LoggingUtils.log_info("DroidAgent", 
                                        "Action counts: macro={macro}, original={original}, action_sequence={seq}", 
                                        macro=macro_actions_count, 
                                        original=original_actions_count,
                                        seq=len(action_sequence))
                    
                    # 如果 action_sequence 的数量明显少于 macro，说明有问题
                    if len(action_sequence) < macro_actions_count - 2:
                        LoggingUtils.log_warning("DroidAgent", 
                                               "⚠️ Action sequence count mismatch! Expected around {macro}, got {seq}",
                                               macro=macro_actions_count, seq=len(action_sequence))
        
        # 构建经验
        experience = TaskExperience(
            id=self.experience_id,  # 使用共享的experience_id
            goal=self.goal,
            type=self.current_task_type,
            type=self.current_task_type,
            success=ev.success,
            timestamp=time.time(),
            page_sequence=page_sequence,
            action_sequence=action_sequence,
            ui_states=self.trajectory.ui_states if self.trajectory else [],
            metadata={
                "steps": ev.steps,
                "output": ev.output,
                "reason": ev.reason,
                "execution_time": time.time() - getattr(self, 'start_time', time.time()),
                "model": self.llm.class_name() if hasattr(self.llm, 'class_name') else "unknown",
                "is_hot_start": getattr(self, 'is_hot_start_execution', False),
                # Step 5: 添加失败反思信息（Memory 系统集成）
                "failure_reflections": self.trajectory.failure_reflections if self.trajectory and hasattr(self.trajectory, 'failure_reflections') else []
            }
        )
        
        return experience

    def _extract_actions_from_trajectory_with_descriptions(self) -> List[Dict]:
        """从轨迹中提取带有描述的动作序列，直接使用macro.json的actions"""
        try:
            # 直接从 macro.json 中获取动作序列
            macro_actions = self._load_macro_actions()
            
            if macro_actions:
                LoggingUtils.log_info("DroidAgent", "Using {count} actions from macro.json with original descriptions", 
                                    count=len(macro_actions))
                return macro_actions
            else:
                # 如果无法加载macro.json，回退到原有逻辑
                LoggingUtils.log_warning("DroidAgent", "Failed to load macro.json, falling back to trajectory extraction")
                return self._extract_actions_from_trajectory_fallback()
                
        except ExceptionConstants.FILE_OPERATION_EXCEPTIONS as e:
            ExceptionHandler.handle_file_operation_error(e, "[Macro] Extract actions from macro.json")
            return self._extract_actions_from_trajectory_fallback()

    def _extract_actions_from_trajectory_fallback(self) -> List[Dict]:
        """回退方案：从轨迹中提取动作"""
        actions = []
        
        # 从轨迹事件中提取动作
        for event in self.trajectory.events:
            if hasattr(event, 'code') and event.code:
                # 从代码中解析动作
                parsed_actions = self._parse_code_actions(event.code)
                actions.extend(parsed_actions)
            elif hasattr(event, '__dict__'):
                event_dict = event.__dict__
                # 处理直接的动作事件
                if event_dict.get("event_type") in ["tap_action", "input_action"]:
                    action_data = {
                        "action": event_dict.get("action", "unknown"),
                        "params": event_dict.get("params", {}),
                        "success": event_dict.get("success", True),
                        "timestamp": event_dict.get("timestamp", time.time())
                    }
                    actions.append(action_data)
        
        LoggingUtils.log_info("DroidAgent", "Extracted {count} actions from trajectory (fallback)", 
                            count=len(actions))
        return actions

    def _load_macro_actions(self, experience_id: str = None) -> List[Dict]:
        """
        加载 macro.json 中的完整动作序列
        
        Args:
            experience_id: 经验ID，用于直接定位对应的trajectories子文件夹
                          如果为None，则回退到查找最新的macro.json文件
        
        Returns:
            List of actions in TaskExperience format
        """
        try:
            if experience_id:
                # 直接使用experience_id定位macro.json文件
                macro_file = f"trajectories/{experience_id}/macro.json"
                
                if os.path.exists(macro_file):
                    LoggingUtils.log_info("DroidAgent", "Loading macro.json from matched experience: {file}", file=macro_file)
                    
                    with open(macro_file, 'r', encoding='utf-8') as f:
                        macro_data = json.load(f)
                        actions = macro_data.get('actions', [])
                        
                        LoggingUtils.log_info("DroidAgent", "Found {count} actions in matched experience macro.json", 
                                            count=len(actions))
                        
                        if not actions:
                            LoggingUtils.log_warning("DroidAgent", "No actions found in matched experience macro.json")
                            return []
                        
                        # 转换格式以匹配 TaskExperience 的 action_sequence 格式
                        converted_actions = []
                        for i, action in enumerate(actions):
                            description = action.get('description', '')
                            specific_behavior = action.get('specific_behavior', None)  # 保留 specific_behavior ✅
                            LoggingUtils.log_debug("DroidAgent", "Action {index}: type={type}, description='{desc}...', specific_behavior='{behavior}'", 
                                                 index=i, type=action.get('type'), desc=description[:50], 
                                                 behavior=specific_behavior[:30] if specific_behavior else "None")
                            
                            converted_action = {
                                "action": self._convert_action_type(action.get('type', '')),
                                "params": self._convert_action_params(action),
                                "success": True,  # macro.json 中的动作都是成功的
                                "timestamp": action.get('timestamp', time.time()),
                                "description": description,  # 完整描述
                                "specific_behavior": specific_behavior  # ✅ 语义描述（用于热启动设置 _action_comments）
                            }
                            converted_actions.append(converted_action)
                        
                        LoggingUtils.log_info("DroidAgent", "Loaded {count} actions from matched experience macro.json with descriptions", 
                                            count=len(converted_actions))
                        return converted_actions
                else:
                    LoggingUtils.log_warning("DroidAgent", "Macro file not found for experience_id {id}: {file}", 
                                           id=experience_id, file=macro_file)
                    # 回退到查找最新的macro.json
            
            # 回退逻辑：查找最新的 macro.json 文件
            trajectory_dirs = glob.glob("trajectories/*/macro.json")
            if trajectory_dirs:
                # 按修改时间排序，获取最新的
                latest_macro = max(trajectory_dirs, key=os.path.getmtime)
                
                LoggingUtils.log_info("DroidAgent", "Loading macro.json from: {file}", file=latest_macro)
                
                with open(latest_macro, 'r', encoding='utf-8') as f:
                    macro_data = json.load(f)
                    actions = macro_data.get('actions', [])
                    
                    LoggingUtils.log_info("DroidAgent", "Found {count} actions in macro.json", count=len(actions))
                    
                    if not actions:
                        LoggingUtils.log_warning("DroidAgent", "No actions found in macro.json")
                        return []
                    
                    # 转换格式以匹配 TaskExperience 的 action_sequence 格式
                    converted_actions = []
                    for i, action in enumerate(actions):
                        description = action.get('description', '')
                        specific_behavior = action.get('specific_behavior', None)  # 保留 specific_behavior ✅
                        LoggingUtils.log_debug("DroidAgent", "Action {index}: type={type}, description='{desc}...', specific_behavior='{behavior}'", 
                                             index=i, type=action.get('type'), desc=description[:50],
                                             behavior=specific_behavior[:30] if specific_behavior else "None")
                        
                        converted_action = {
                            "action": self._convert_action_type(action.get('type', '')),
                            "params": self._convert_action_params(action),
                            "success": True,  # macro.json 中的动作都是成功的
                            "timestamp": action.get('timestamp', time.time()),
                            "description": description,  # 完整描述
                            "specific_behavior": specific_behavior  # ✅ 语义描述（用于热启动设置 _action_comments）
                        }
                        converted_actions.append(converted_action)
                    
                    LoggingUtils.log_info("DroidAgent", "Loaded {count} actions from macro.json with descriptions", 
                                        count=len(converted_actions))
                    return converted_actions
            else:
                LoggingUtils.log_warning("DroidAgent", "No macro.json files found in trajectories directory")
                return []
        except Exception as e:
            LoggingUtils.log_warning("DroidAgent", "Failed to load macro actions: {error}", error=e)
            return []

    def _convert_action_type(self, macro_type: str) -> str:
        """将macro.json中的action类型转换为标准格式"""
        type_mapping = {
            'TapActionEvent': 'tap_by_index',
            'InputTextActionEvent': 'input_text',
            'SwipeActionEvent': 'swipe',
            'StartAppEvent': 'start_app',
            'KeyPressActionEvent': 'press_key'
        }
        return type_mapping.get(macro_type, macro_type.lower())

    def _convert_action_params(self, action: Dict) -> Dict:
        """将macro.json中的参数转换为标准格式"""
        action_type = action.get('type', '')
        params = {}
        
        if action_type == 'TapActionEvent':
            params['index'] = action.get('element_index', -1)
        elif action_type == 'InputTextActionEvent':
            params['text'] = action.get('text', '')
            if action.get('index') is not None:
                params['index'] = action.get('index')
        elif action_type == 'SwipeActionEvent':
            params.update({
                'start_x': action.get('start_x', 0),
                'start_y': action.get('start_y', 0),
                'end_x': action.get('end_x', 0),
                'end_y': action.get('end_y', 0),
                'duration_ms': action.get('duration_ms', 500)
            })
        elif action_type == 'StartAppEvent':
            params['app_name'] = action.get('package_name', '')
        elif action_type == 'KeyPressActionEvent':
            params['keycode'] = action.get('keycode', 0)
        
        return params


    def _parse_code_actions(self, code: str) -> List[Dict]:
        """从代码字符串中解析动作"""
        actions = []
        
        # 解析 tap_by_index
        tap_pattern = r'tap_by_index\s*\(\s*(\d+)\s*\)'
        for match in re.finditer(tap_pattern, code):
            index = int(match.group(1))
            actions.append({
                "action": "tap_by_index",
                "params": {"index": index},
                "success": True,
                "timestamp": time.time()
            })
        
        # 解析 input_text
        input_pattern = r'input_text\s*\(\s*["\']([^"\']*)["\']\s*\)'
        for match in re.finditer(input_pattern, code):
            text = match.group(1)
            actions.append({
                "action": "input_text",
                "params": {"text": text},
                "success": True,
                "timestamp": time.time()
            })
        
        # 解析 swipe
        swipe_pattern = r'swipe\s*\(\s*start_x\s*=\s*(\d+)\s*,\s*start_y\s*=\s*(\d+)\s*,\s*end_x\s*=\s*(\d+)\s*,\s*end_y\s*=\s*(\d+)\s*,\s*duration_ms\s*=\s*(\d+)\s*\)'
        for match in re.finditer(swipe_pattern, code):
            start_x, start_y, end_x, end_y, duration = map(int, match.groups())
            actions.append({
                "action": "swipe",
                "params": {
                    "start_x": start_x, "start_y": start_y,
                    "end_x": end_x, "end_y": end_y, "duration_ms": duration
                },
                "success": True,
                "timestamp": time.time()
            })
        
        # 解析 start_app
        app_pattern = r'start_app\s*\(\s*["\']([^"\']*)["\']\s*\)'
        for match in re.finditer(app_pattern, code):
            app_name = match.group(1)
            actions.append({
                "action": "start_app",
                "params": {"app_name": app_name},
                "success": True,
                "timestamp": time.time()
            })
        
        return actions
