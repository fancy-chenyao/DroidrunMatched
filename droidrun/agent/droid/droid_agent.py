"""
DroidAgent - A wrapper class that coordinates the planning and execution of tasks
to achieve a user's goal on an Android device.
"""

import logging
import time
import uuid
import json
import re
import glob
import os
from typing import List, Optional, Dict

from llama_index.core.llms.llm import LLM
from llama_index.core.workflow import step, StartEvent, StopEvent, Workflow, Context
from llama_index.core.workflow.handler import WorkflowHandler
from droidrun.agent.droid.events import *
from droidrun.agent.codeact import CodeActAgent
from droidrun.agent.codeact.events import EpisodicMemoryEvent
from droidrun.agent.planner import PlannerAgent
from droidrun.agent.context.task_manager import TaskManager
from droidrun.agent.utils.trajectory import Trajectory
from droidrun.tools import Tools, describe_tools
from droidrun.agent.common.events import ScreenshotEvent, MacroEvent, RecordUIStateEvent
from droidrun.agent.common.default import MockWorkflow
from droidrun.agent.context import ContextInjectionManager
from droidrun.agent.context.agent_persona import AgentPersona
from droidrun.agent.context.personas import DEFAULT
from droidrun.agent.oneflows.reflector import Reflector
from droidrun.agent.context.experience_memory import ExperienceMemory, TaskExperience
from droidrun.agent.context.execution_monitor import ExecutionMonitor, MonitorResult
from droidrun.agent.context.llm_services import LLMServices
from droidrun.agent.context.memory_config import MemoryConfig, create_memory_config
from droidrun.telemetry import (
    capture,
    flush,
    DroidAgentInitEvent,
    DroidAgentFinalizeEvent,
)

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
        # Only configure if no handlers exist (avoid duplicate configuration)
        if not logger.handlers:
            # Create a console handler
            handler = logging.StreamHandler()

            # Set format
            if debug:
                formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s", "%H:%M:%S")
            else:
                formatter = logging.Formatter("%(message)s")

            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG if debug else logging.INFO)
            logger.propagate = False

    def __init__(
        self,
        goal: str,
        llm: LLM,
        tools: Tools,
        personas: List[AgentPersona] = [DEFAULT],
        max_steps: int = 15,
        timeout: int = 1000,
        vision: bool = False,
        reasoning: bool = False,
        reflection: bool = False,
        enable_tracing: bool = False,
        debug: bool = False,
        save_trajectories: str = "none",
        excluded_tools: List[str] = None,
        # 新增记忆系统参数
        enable_memory: bool = True,
        memory_similarity_threshold: float = 0.7,
        memory_storage_dir: str = "experiences",
        memory_config: Optional[MemoryConfig] = None,
        *args,
        **kwargs,
    ):
        """
        Initialize the DroidAgent wrapper.

        Args:
            goal: The user's goal or command to execute
            llm: The language model to use for both agents
            max_steps: Maximum number of steps for both agents
            timeout: Timeout for agent execution in seconds
            reasoning: Whether to use the PlannerAgent for complex reasoning (True)
                      or send tasks directly to CodeActAgent (False)
            reflection: Whether to reflect on steps the CodeActAgent did to give the PlannerAgent advice
            enable_tracing: Whether to enable Arize Phoenix tracing
            debug: Whether to enable verbose debug logging
            save_trajectories: Trajectory saving level. Can be:
                - "none" (no saving)
                - "step" (save per step)
                - "action" (save per action)
            **kwargs: Additional keyword arguments to pass to the agents
        """
        self.user_id = kwargs.pop("user_id", None)
        super().__init__(timeout=timeout, *args, **kwargs)
        # Configure default logging if not already configured
        self._configure_default_logging(debug=debug)
        
        # 初始化记忆系统
        self.memory_enabled = enable_memory
        if self.memory_enabled:
            # 创建记忆配置
            if memory_config is None:
                self.memory_config = create_memory_config(
                    enabled=enable_memory,
                    similarity_threshold=memory_similarity_threshold,
                    storage_dir=memory_storage_dir
                )
            else:
                self.memory_config = memory_config
            
            # 初始化记忆组件
            self.memory_manager = ExperienceMemory(
                storage_dir=self.memory_config.storage_dir,
                llm=llm
            )
            self.execution_monitor = ExecutionMonitor(llm=llm)
            self.llm_services = LLMServices(llm)
            # 热启动直执动作队列与上下文
            self.pending_hot_actions: List[Dict] = []
            self.pending_hot_context: Dict = {}
            
            logger.info("🧠 Memory system initialized")
        else:
            self.memory_manager = None
            self.execution_monitor = None
            self.llm_services = None
            self.pending_hot_actions = []
            self.pending_hot_context = {}
            logger.info("🚫 Memory system disabled")

        # Setup global tracing first if enabled
        if enable_tracing:
            try:
                from llama_index.core import set_global_handler

                set_global_handler("arize_phoenix")
                logger.info("🔍 Arize Phoenix tracing enabled globally")
            except ImportError:
                logger.warning("⚠️ Arize Phoenix package not found, tracing disabled")
                enable_tracing = False

        self.goal = goal
        self.llm = llm
        self.vision = vision
        self.max_steps = max_steps
        self.max_codeact_steps = max_steps
        self.timeout = timeout
        self.reasoning = reasoning
        self.reflection = reflection
        self.debug = debug

        self.event_counter = 0
        # Handle backward compatibility: bool -> str mapping
        if isinstance(save_trajectories, bool):
            self.save_trajectories = "step" if save_trajectories else "none"
        else:
            # Validate string values
            valid_values = ["none", "step", "action"]
            if save_trajectories not in valid_values:
                logger.warning(
                    f"Invalid save_trajectories value: {save_trajectories}. Using 'none' instead."
                )
                self.save_trajectories = "none"
            else:
                self.save_trajectories = save_trajectories

        # 生成共享的experience_id，用于experiences和trajectories的一致性
        self.experience_id = str(uuid.uuid4())
        
        self.trajectory = Trajectory(goal=goal, experience_id=self.experience_id)
        self.task_manager = TaskManager()
        self.task_iter = None

        self.cim = ContextInjectionManager(personas=personas)
        self.current_episodic_memory = None

        logger.info("🤖 Initializing DroidAgent...")
        logger.info(f"💾 Trajectory saving level: {self.save_trajectories}")

        self.tool_list = describe_tools(tools, excluded_tools)
        self.tools_instance = tools

        self.tools_instance.save_trajectories = self.save_trajectories

        if self.reasoning:
            logger.info("📝 Initializing Planner Agent...")
            self.planner_agent = PlannerAgent(
                goal=goal,
                llm=llm,
                vision=vision,
                personas=personas,
                task_manager=self.task_manager,
                tools_instance=tools,
                timeout=timeout,
                debug=debug,
            )
            self.max_codeact_steps = 5

            if self.reflection:
                self.reflector = Reflector(llm=llm, debug=debug)

        else:
            logger.debug("🚫 Planning disabled - will execute tasks directly with CodeActAgent")
            self.planner_agent = None

        capture(
            DroidAgentInitEvent(
                goal=goal,
                llm=llm.class_name(),
                tools=",".join(self.tool_list),
                personas=",".join([p.name for p in personas]),
                max_steps=max_steps,
                timeout=timeout,
                vision=vision,
                reasoning=reasoning,
                reflection=reflection,
                enable_tracing=enable_tracing,
                debug=debug,
                save_trajectories=save_trajectories,
            ),
            self.user_id,
        )

        logger.info("✅ DroidAgent initialized successfully.")

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

        logger.info(f"🔧 Executing task: {task.description}")

        # 新增：执行监控
        if self.memory_enabled and self.memory_config.monitoring_enabled:
            self.execution_monitor.start_step_monitoring({
                "task": task.description,
                "step": self.step_counter,
                "timestamp": time.time()
            })

        try:
            # 热启动直执分支：若有待执行动作，直接绕过 CodeAct
            if self.memory_enabled and getattr(self, 'pending_hot_actions', None):
                logger.info(f"🚀 Directly executing {len(self.pending_hot_actions)} hot-start actions")
                success, reason = await self._direct_execute_actions_async(self.pending_hot_actions)
                # 记录热启动执行结果
                if hasattr(self, 'trajectory') and self.trajectory:
                    from droidrun.agent.codeact.events import TaskEndEvent
                    self.trajectory.events.append(TaskEndEvent(success=success, reason=reason, task=task))
                    logger.info(f"[HOT] 📝 Hot start execution recorded in trajectory")
                # 用完即清空
                self.pending_hot_actions = []
                return CodeActResultEvent(success=success, reason=reason, task=task, steps=self.step_counter)

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
                    logger.warning(f"⚠️ Execution anomaly detected: {monitor_result.message}")
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
            logger.error(f"Error during task execution: {e}")
            if self.debug:
                import traceback

                logger.error(traceback.format_exc())
            return CodeActResultEvent(success=False, reason=f"Error: {str(e)}", task=task, steps=0)

    @step
    async def handle_codeact_execute(
        self, ctx: Context, ev: CodeActResultEvent
    ) -> FinalizeEvent | ReflectionEvent | ReasoningLogicEvent:
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

            if self.reflection and ev.success:
                return ReflectionEvent(task=task)

            # Reasoning is enabled but reflection is disabled.
            # Success: mark complete and proceed to next step in reasoning loop.
            # Failure: mark failed and trigger planner immediately without advancing to the next queued task.
            if ev.success:
                self.task_manager.complete_task(task, message=ev.reason)
                return ReasoningLogicEvent()
            else:
                self.task_manager.fail_task(task, failure_reason=ev.reason)
                return ReasoningLogicEvent(force_planning=True)

        except Exception as e:
            logger.error(f"❌ Error during DroidAgent execution: {e}")
            if self.debug:
                import traceback

                logger.error(traceback.format_exc())
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
    async def reflect(
        self, ctx: Context, ev: ReflectionEvent
    ) -> ReasoningLogicEvent | CodeActExecuteEvent:
        task = ev.task
        if ev.task.agent_type == "AppStarterExpert":
            self.task_manager.complete_task(task)
            return ReasoningLogicEvent()

        reflection = await self.reflector.reflect_on_episodic_memory(
            episodic_memory=self.current_episodic_memory, goal=task.description
        )

        if reflection.goal_achieved:
            self.task_manager.complete_task(task)
            return ReasoningLogicEvent()

        else:
            self.task_manager.fail_task(task)
            return ReasoningLogicEvent(reflection=reflection)

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
                        logger.info("Planning next steps...")

                logger.debug(f"Planning step {self.step_counter}/{self.max_steps}")

                handler = self.planner_agent.run(
                    remembered_info=self.tools_instance.memory, reflection=None
                )

            async for nested_ev in handler.stream_events():
                self.handle_stream_event(nested_ev, ctx)

            result = await handler

            self.tasks = self.task_manager.get_all_tasks()
            self.task_iter = iter(self.tasks)

            if self.task_manager.goal_completed:
                logger.info(f"✅ Goal completed: {self.task_manager.message}")
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
                logger.warning("No tasks generated by planner")
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
            logger.error(f"❌ Error during DroidAgent execution: {e}")
            if self.debug:
                import traceback

                logger.error(traceback.format_exc())
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
        logger.info(f"🚀 Running DroidAgent to achieve goal: {self.goal}")
        ctx.write_event_to_stream(ev)

        self.step_counter = 0
        self.retry_counter = 0

        # 新增：热启动检查
        if self.memory_enabled and self.memory_config.hot_start_enabled:
            similar_experiences = self.memory_manager.find_similar_experiences(
                self.goal, 
                threshold=self.memory_config.similarity_threshold
            )
            # 打印命中集合的相似度（检索阶段结果）
            try:
                if similar_experiences:
                    for exp in similar_experiences:
                        if hasattr(exp, "similarity_score") and exp.similarity_score is not None:
                            logger.info(f"[SIM][kept] similarity={exp.similarity_score:.2f} goal={exp.goal}")
            except Exception:
                pass
            # 打印本次检索对所有经验的相似度，便于排查为何未达阈值
            try:
                for exp in (self.memory_manager.get_all_experiences() or []):
                    try:
                        score = self.memory_manager._calculate_similarity(self.goal, exp.goal)
                        logger.info(f"[SIM] Similarity {score:.2f} to experience goal: {exp.goal}")
                    except Exception:
                        continue
            except Exception:
                pass
            
            if similar_experiences:
                logger.info(f"🔥 Hot start: Found {len(similar_experiences)} similar experiences")
                
                # 使用LLM选择最佳经验
                best_experience = self.llm_services.select_best_experience(
                    [exp.to_dict() for exp in similar_experiences], 
                    self.goal
                )
                
                if best_experience:
                    try:
                        # 参数自适应
                        if self.memory_config.parameter_adaptation_enabled:
                            adapted_actions = self.memory_manager.adapt_parameters(
                                TaskExperience.from_dict(best_experience), 
                                self.goal
                            )
                            logger.info(f"🔄 Parameters adapted for hot start")
                        else:
                            adapted_actions = best_experience.get("action_sequence", [])
                        
                        # 直执：将动作放入队列，并用 LLM 预判哪些索引是“变更点击步”
                        self.pending_hot_actions = adapted_actions or []
                        if self.pending_hot_actions:
                            logger.info(f"🔥 Hot start direct-execution prepared with {len(self.pending_hot_actions)} actions")
                            self.pending_hot_context = {
                                "experience_goal": best_experience.get("goal", ""),
                                "experience_actions": best_experience.get("action_sequence", []),
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
                                # 在传入前，对仍缺 description 的动作进行通用语义补齐
                                for a in self.pending_hot_actions:
                                    if isinstance(a, dict) and not a.get("description"):
                                        name = (a or {}).get("action") or (a or {}).get("name") or ""
                                        params = (a or {}).get("params") or (a or {}).get("parameters") or {}
                                        a["description"] = f"{name} with params {json.dumps(params, ensure_ascii=False)}"

                                det = self.llm_services.detect_changed_actions(
                                    self.pending_hot_context["experience_goal"],
                                    self.goal,
                                    self.pending_hot_actions
                                )
                                self.pending_hot_context["changed_indices"] = det.get("changed_indices", [])
                                # 保存 index->reason，用于更具体的微冷启动子目标
                                self.pending_hot_context["changed_index_reasons"] = det.get("index_reasons", [])
                                logger.info(f"[HOT] Changed action indices predicted: {self.pending_hot_context['changed_indices']}")
                            except Exception as _:
                                pass
                            task = Task(
                                description="[HOT] Directly execute adapted actions",
                                status=self.task_manager.STATUS_PENDING,
                                agent_type="Default",
                            )
                            return CodeActExecuteEvent(task=task, reflection=None)
                    except Exception as e:
                        logger.warning(f"Hot start failed, falling back to cold start: {e}")
                        # 如果热启动失败，继续执行冷启动逻辑
            else:
                logger.info("❄️ Cold start: No similar experiences found")

        if not self.reasoning:
            logger.info(f"🔄 Direct execution mode - executing goal: {self.goal}")
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

        if self.trajectory and self.save_trajectories != "none":
            self.trajectory.save_trajectory()
            
            # 轨迹保存完成后，保存经验到记忆系统
            if self.memory_enabled and ev.success:
                try:
                    import asyncio
                    await asyncio.sleep(0.5)  # 确保macro.json已经生成
                    
                    experience = self._build_experience_from_execution(ev)
                    saved_path = self.memory_manager.save_experience(experience)
                    logger.info(f"💾 Experience saved to: {saved_path}")
                except Exception as e:
                    logger.warning(f"Failed to save experience: {e}")

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
            except Exception:
                pass
            ctx.write_event_to_stream(ev)

            if isinstance(ev, ScreenshotEvent):
                self.trajectory.screenshots.append(ev.screenshot)
            elif isinstance(ev, MacroEvent):
                self.trajectory.macro.append(ev)
            elif isinstance(ev, RecordUIStateEvent):
                self.trajectory.ui_states.append(ev.ui_state)
            else:
                self.trajectory.events.append(ev)
    
    async def _direct_execute_actions_async(self, actions: List[Dict]) -> tuple[bool, str]:
        """
        直接执行热启动动作（异步），必要时触发微冷启动子流程。
        """
        try:
            tools = self.tools_instance
            step_count = 0
            import time
            # 初始化UI
            logger.info("[HOT] Initializing UI state cache...")
            try:
                ui_state = tools.get_state()
                logger.info(f"[HOT] ✅ UI state initialized with {len(ui_state.get('elements', []))} elements")
                try:
                    screenshot = tools.take_screenshot()
                    if screenshot:
                        logger.info("[HOT] 📸 Initial screenshot captured")
                except Exception as e:
                    logger.warning(f"[HOT] ⚠️ Failed to capture initial screenshot: {e}")
            except Exception as e:
                logger.error(f"[HOT] ❌ Failed to initialize UI state: {e}")
                return False, f"Failed to initialize UI state: {e}"
            executed_actions = []
            # 基于 changed_indices 的微冷启动触发记录，避免重复触发同一索引
            triggered_changed_steps: Dict[int, bool] = {}
            for idx_action, act in enumerate(actions):
                name = (act or {}).get("action") or (act or {}).get("name")
                params = (act or {}).get("params", {}) or (act or {}).get("parameters", {})
                desc = str((act or {}).get("description", ""))
                logger.info(f"[HOT] executing action {idx_action+1}/{len(actions)}: {name} params={params}")
                try:
                    if name in ("tap_by_index", "tap", "tap_index"):
                        idx_val = params.get("index", params.get("idx"))
                        try:
                            idx = int(idx_val) if idx_val is not None else -1
                        except Exception:
                            idx = -1
                        if idx >= 0:
                            # 变化参数且为点击 → 基于 changed_indices 直接触发微冷启动（无窗口 gating）
                            if self._is_changed_param_click_step(idx_action, act) and not triggered_changed_steps.get(idx_action):
                                ok = await self._micro_coldstart_handle_click_step(idx_action, act)
                                triggered_changed_steps[idx_action] = True
                                if ok:
                                    step_count += 1
                                    try:
                                        tools.get_state()
                                    except Exception:
                                        pass
                                    if idx_action < len(actions) - 1:
                                        time.sleep(0.5)
                                    # 成功后继续到下一步（不再执行原点击）
                                    continue
                                else:
                                    logger.warning(f"[HOT] ⚠️ Micro-coldstart failed for step {idx_action}, fallback to direct tap")
                            tools.tap_by_index(idx)
                            time.sleep(1.0)
                            try:
                                tools.get_state()
                            except Exception:
                                pass
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
                        # 不再在直执中做就地文本适配，保持经验参数或上层已适配结果
                        if text:
                            tools.input_text(text)
                            time.sleep(0.5)
                            try:
                                tools.get_state()
                            except Exception:
                                pass
                            step_count += 1
                            executed_actions.append({
                                "action": "input_text",
                                "params": {"text": text},
                                "success": True,
                                "timestamp": time.time()
                            })
                    elif name == "swipe":
                        start = params.get("start") or params.get("from") or {}
                        end = params.get("end") or params.get("to") or {}
                        sx = int(params.get("start_x", start[0] if isinstance(start, (list, tuple)) and len(start) >= 2 else start.get("x", 0)))
                        sy = int(params.get("start_y", start[1] if isinstance(start, (list, tuple)) and len(start) >= 2 else start.get("y", 0)))
                        ex = int(params.get("end_x", end[0] if isinstance(end, (list, tuple)) and len(end) >= 2 else end.get("x", 0)))
                        ey = int(params.get("end_y", end[1] if isinstance(end, (list, tuple)) and len(end) >= 2 else end.get("y", 0)))
                        dur = int(params.get("duration_ms", params.get("duration", 300)))
                        tools.swipe(sx, sy, ex, ey, dur)
                        time.sleep(1.0)
                        step_count += 1
                    elif name == "start_app":
                        pkg = params.get("package", params.get("pkg", ""))
                        pkg = str(pkg) if pkg is not None else ""
                        if pkg and hasattr(tools, "start_app"):
                            tools.start_app(pkg)
                            time.sleep(2.0)
                            step_count += 1
                    elif name == "press_key":
                        key_val = params.get("keycode", params.get("key", 0))
                        try:
                            keycode = int(key_val)
                        except Exception:
                            keycode = 0
                        if keycode:
                            tools.press_key(keycode)
                            time.sleep(0.5)
                            step_count += 1
                    elif name in ("sleep", "wait"):
                        import time as _t
                        ms = int(params.get("ms", params.get("milliseconds", 0)))
                        sec = int(params.get("sec", 0))
                        delay = sec if sec > 0 else (ms / 1000.0 if ms > 0 else 0)
                        if delay > 0:
                            _t.sleep(delay)
                            step_count += 1
                    elif name == "complete":
                        reason = str(params.get("reason", "Hot start direct execution finished"))
                        return True, reason
                    else:
                        logger.warning(f"[HOT] Unknown action type: {name}, skipping...")
                except Exception as action_error:
                    logger.error(f"[HOT] ❌ Action {idx_action+1} failed: {action_error}")
                    try:
                        tools.get_state()
                    except Exception:
                        pass
                    continue
                if idx_action < len(actions) - 1:
                    time.sleep(0.5)
            # 写回到轨迹 - 使用事件对象而不是字典
            if executed_actions:
                try:
                    from droidrun.agent.codeact.events import TaskExecutionEvent
                    for a in executed_actions:
                        # 创建TaskExecutionEvent对象而不是字典
                        event_data = {
                            "event_type": "task_execution",
                            "action": a["action"],
                            "params": a["params"],
                            "timestamp": a["timestamp"],
                            "success": a.get("success", True)
                        }
                        # 创建事件对象
                        event = TaskExecutionEvent(
                            code=f"{a['action']}({a['params']})",
                            globals={},
                            locals=event_data
                        )
                        self.trajectory.events.append(event)
                except Exception as e:
                    logger.warning(f"Failed to create trajectory events: {e}")
            if step_count == 0:
                return False, "No hot-start actions were executed (unrecognized schema)."
            return True, f"Hot-start direct execution finished with {step_count} actions"
        except Exception as e:
            logger.error(f"[HOT] ❌ Direct execution failed: {e}")
            return False, f"Direct execution failed: {e}"

    def _is_changed_param_click_step(self, step_index: int, action: Dict) -> bool:
        try:
            name = (action or {}).get("action") or (action or {}).get("name")
            if name in ("input_text", "type", "input"):
                return False
            # 仅在 LLM 识别出的索引上触发微冷启动
            changed = (self.pending_hot_context or {}).get("changed_indices", [])
            return step_index in changed
        except Exception:
            return False

    async def _micro_coldstart_handle_click_step(self, step_index: int, action: Dict) -> bool:
        """微冷启动处理单步点击操作 - 优先使用 changed_indices 的具体理由作为子目标"""
        try:
            action_name = action.get('action', 'unknown')
            params = action.get('params', {})
            desc = str(action.get('description', ''))
            # 若 detect_changed_actions 提供了 index->reason，则优先用作微目标
            micro_goal = None
            try:
                for ir in (self.pending_hot_context or {}).get("changed_index_reasons", []):
                    if ir.get("index") == step_index and ir.get("reason"):
                        micro_goal = str(ir.get("reason"))
                        break
            except Exception:
                micro_goal = None
            
            # 若未命中具体 reason，再调用通用生成逻辑
            if not micro_goal:
                micro_goal = self.llm_services.generate_micro_goal(action, {}, self.goal)
            
            logger.info(f"🔄 Micro cold start for step {step_index}: {micro_goal}")
            logger.info(f"🔄 Action details: {action_name} with params {params}")
            logger.info(f"🔄 [MICRO-COLD] Task description: '{micro_goal}'")
            
            from droidrun.agent.codeact import CodeActAgent as _CA
            agent = _CA(
                llm=self.llm,
                persona=self.cim.get_persona("Default"),
                vision=self.vision,
                max_steps=5,  # 限制为5步，避免长链思考
                all_tools_list=self.tool_list,
                tools_instance=self.tools_instance,
                debug=self.debug,
                timeout=min(self.timeout, 60),  # 减少超时时间
            )
            
            # 执行聚焦的微冷启动
            handler = agent.run(input=micro_goal, remembered_info=self.tools_instance.memory, reflection=None)
            async for _ in handler.stream_events():
                pass
            result = await handler
            
            success = bool(result.get("success", False))
            if success:
                logger.info(f"✅ Micro cold start completed for step {step_index}")
            else:
                logger.warning(f"⚠️ Micro cold start failed for step {step_index}")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Micro cold start error for step {step_index}: {e}")
            return False

    # 按你的要求移除不通用的就地适配辅助方法（保留占位以避免误调用）。
    # 如后续需要从更上层适配参数，可在 LLMServices 中集中处理。
    
    def _handle_fallback(self, monitor_result: MonitorResult, task: Task) -> CodeActResultEvent:
        """处理回退逻辑"""
        fallback_strategy = self.execution_monitor.suggest_fallback(monitor_result)
        logger.warning(f"🔄 Applying fallback strategy: {fallback_strategy}")
        
        # 根据回退类型选择策略
        if monitor_result.fallback_type == "consecutive_failures":
            # 回退到冷启动
            logger.info("🔄 Falling back to cold start mode")
            return CodeActResultEvent(
                success=False,
                reason=f"Fallback triggered: {monitor_result.message}",
                task=task,
                steps=0
            )
        elif monitor_result.fallback_type == "timeout":
            # 简化任务
            logger.info("🔄 Simplifying task due to timeout")
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
        # 提取页面序列
        page_sequence = []
        if self.trajectory and self.trajectory.ui_states:
            page_sequence = self.llm_services.extract_page_sequence({
                "ui_states": self.trajectory.ui_states,
                "events": [e.__dict__ for e in self.trajectory.events]
            })
        
        # 提取动作序列
        action_sequence = []
        if self.trajectory and self.trajectory.events:
            action_sequence = self._extract_actions_from_trajectory_with_descriptions()
        
        # 构建经验
        experience = TaskExperience(
            id=self.experience_id,  # 使用共享的experience_id
            goal=self.goal,
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
                "model": self.llm.class_name() if hasattr(self.llm, 'class_name') else "unknown"
            }
        )
        
        return experience

    def _extract_actions_from_trajectory_with_descriptions(self) -> List[Dict]:
        """从轨迹中提取带有描述的动作序列，直接使用macro.json的actions"""
        try:
            # 直接从 macro.json 中获取动作序列
            macro_actions = self._load_macro_actions()
            
            if macro_actions:
                logger.info(f"🎬 Using {len(macro_actions)} actions from macro.json with original descriptions")
                return macro_actions
            else:
                # 如果无法加载macro.json，回退到原有逻辑
                logger.warning("Failed to load macro.json, falling back to trajectory extraction")
                return self._extract_actions_from_trajectory_fallback()
                
        except Exception as e:
            logger.warning(f"Failed to extract actions from macro.json: {e}")
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
        
        logger.info(f"🎬 Extracted {len(actions)} actions from trajectory (fallback)")
        return actions

    def _load_macro_actions(self) -> List[Dict]:
        """加载 macro.json 中的完整动作序列"""
        try:
            # 查找最新的 macro.json 文件
            trajectory_dirs = glob.glob("trajectories/*/macro.json")
            if trajectory_dirs:
                # 按修改时间排序，获取最新的
                latest_macro = max(trajectory_dirs, key=os.path.getmtime)
                
                logger.info(f"📋 Loading macro.json from: {latest_macro}")
                
                with open(latest_macro, 'r', encoding='utf-8') as f:
                    macro_data = json.load(f)
                    actions = macro_data.get('actions', [])
                    
                    logger.info(f"📋 Found {len(actions)} actions in macro.json")
                    
                    if not actions:
                        logger.warning("📋 No actions found in macro.json")
                        return []
                    
                    # 转换格式以匹配 TaskExperience 的 action_sequence 格式
                    converted_actions = []
                    for i, action in enumerate(actions):
                        description = action.get('description', '')
                        logger.info(f"📋 Action {i}: type={action.get('type')}, description='{description[:50]}...'")
                        
                        converted_action = {
                            "action": self._convert_action_type(action.get('type', '')),
                            "params": self._convert_action_params(action),
                            "success": True,  # macro.json 中的动作都是成功的
                            "timestamp": action.get('timestamp', time.time()),
                            "description": description  # 直接使用macro.json中的description
                        }
                        converted_actions.append(converted_action)
                    
                    logger.info(f"📋 Loaded {len(converted_actions)} actions from macro.json with descriptions")
                    return converted_actions
            else:
                logger.warning("📋 No macro.json files found in trajectories directory")
                return []
        except Exception as e:
            logger.warning(f"Failed to load macro actions: {e}")
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
