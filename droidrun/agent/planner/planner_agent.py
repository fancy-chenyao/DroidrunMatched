from droidrun.agent.planner.events import (
    PlanInputEvent,
    PlanCreatedEvent,
    PlanThinkingEvent,
)
from droidrun.agent.planner.prompts import (
    DEFAULT_PLANNER_SYSTEM_PROMPT,
    DEFAULT_PLANNER_USER_PROMPT,
)
import asyncio
from typing import List, TYPE_CHECKING, Union
from droidrun.agent.utils.logging_utils import LoggingUtils

from llama_index.core.base.llms.types import ChatMessage, ChatResponse
from llama_index.core.prompts import PromptTemplate
from llama_index.core.llms.llm import LLM
from llama_index.core.workflow import Workflow, StartEvent, StopEvent, Context, step
from llama_index.core.memory import Memory
from droidrun.agent.usage import get_usage_from_response
from droidrun.agent.utils.executer import SimpleCodeExecutor
from droidrun.agent.utils import chat_utils
from droidrun.agent.context.task_manager import TaskManager
from droidrun.tools import Tools
from droidrun.agent.common.constants import LLM_HISTORY_LIMIT
from droidrun.agent.common.events import RecordUIStateEvent, ScreenshotEvent
from droidrun.agent.context.agent_persona import AgentPersona
from droidrun.tools.adb import AdbTools
from droidrun.agent.context.reflection import Reflection

from dotenv import load_dotenv

load_dotenv()


if TYPE_CHECKING:
    from droidrun.tools import Tools


class PlannerAgent(Workflow):
    def __init__(
        self,
        goal: str,
        llm: LLM,
        vision: bool,
        personas: List[AgentPersona],
        task_manager: TaskManager,
        tools_instance: Tools,
        system_prompt=None,
        user_prompt=None,
        debug=False,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)

        self.llm = llm
        self.goal = goal
        self.task_manager = task_manager
        self.debug = debug
        self.vision = vision

        self.chat_memory = None
        self.remembered_info = None
        self.reflection: Reflection = None

        self.current_retry = 0
        self.steps_counter = 0

        self.tool_list = {}
        self.tool_list[self.task_manager.set_tasks_with_agents.__name__] = (
            self.task_manager.set_tasks_with_agents
        )
        self.tool_list[self.task_manager.complete_goal.__name__] = (
            self.task_manager.complete_goal
        )

        self.tools_description = chat_utils.parse_tool_descriptions(self.tool_list)
        self.tools_instance = tools_instance

        self.personas = personas

        self.system_prompt = system_prompt or DEFAULT_PLANNER_SYSTEM_PROMPT.format(
            tools_description=self.tools_description,
            agents=chat_utils.parse_persona_description(self.personas),
        )
        self.user_prompt = user_prompt or DEFAULT_PLANNER_USER_PROMPT.format(goal=goal)
        self.system_message = ChatMessage(role="system", content=self.system_prompt)
        self.user_message = ChatMessage(role="user", content=self.user_prompt)

        self.executer = SimpleCodeExecutor(
            loop=asyncio.get_event_loop(), globals={}, locals={}, tools=self.tool_list
        )

    @step
    async def prepare_chat(self, ctx: Context, ev: StartEvent) -> PlanInputEvent:
        LoggingUtils.log_info("PlannerAgent", "💬 Preparing planning session...")

        self.chat_memory: Memory = await ctx.store.get(
            "chat_memory", default=Memory.from_defaults()
        )
        await self.chat_memory.aput(self.user_message)

        if ev.remembered_info:
            self.remembered_info = ev.remembered_info

        if ev.reflection:
            self.reflection = ev.reflection
        else:
            self.reflection = None 
        
        assert len(self.chat_memory.get_all()) > 0 or self.user_prompt, "Memory input, user prompt or user input cannot be empty."
        
        await self.chat_memory.aput(ChatMessage(role="user", content=PromptTemplate(self.user_prompt or DEFAULT_PLANNER_USER_PROMPT.format(goal=self.goal))))
        
        input_messages = self.chat_memory.get_all()
        LoggingUtils.log_debug("PlannerAgent", "Memory contains {count} messages", count=len(input_messages))
        return PlanInputEvent(input=input_messages)

    @step
    async def handle_llm_input(
        self, ev: PlanInputEvent, ctx: Context
    ) -> PlanThinkingEvent:
        """Handle LLM input."""
        chat_history = ev.input
        assert len(chat_history) > 0, "Chat history cannot be empty."

        ctx.write_event_to_stream(ev)

        self.steps_counter += 1
        LoggingUtils.log_info("PlannerAgent", "🧠 Thinking about how to plan the goal...")

        # 先获取一次状态（含截图引用），再决定是否抓取截图字节
        state = await self.tools_instance.get_state_async(include_screenshot=True)
        try:
            await ctx.store.set("ui_state", state.get("a11y_tree") or state.get("a11y_ref"))
            await ctx.store.set("phone_state", state.get("phone_state"))
            if state.get("a11y_tree"):
                ctx.write_event_to_stream(RecordUIStateEvent(ui_state=state["a11y_tree"]))
        except Exception:
            pass

        if self.vision:
            # 尝试通过引用下载截图字节（有 URL 时）
            screenshot_bytes = None
            try:
                ref = (state or {}).get("screenshot_ref") or {}
                url = ref.get("url")
                if url:
                    import httpx
                    async with httpx.AsyncClient(timeout=20.0) as client:
                        resp = await client.get(url)
                        resp.raise_for_status()
                        screenshot_bytes = resp.content
            except Exception:
                screenshot_bytes = None
            if screenshot_bytes:
                ctx.write_event_to_stream(ScreenshotEvent(screenshot=screenshot_bytes))
                await ctx.store.set("screenshot", screenshot_bytes)

        # 上面已获取一次状态，这里不再重复同步阻塞调用


        await ctx.store.set("remembered_info", self.remembered_info)
        await ctx.store.set("reflection", self.reflection)

        response = await self._get_llm_response(ctx, chat_history)
        try:
            usage = get_usage_from_response(self.llm.class_name(), response)
        except Exception as e:
            LoggingUtils.log_warning("PlannerAgent", "Could not get llm usage from response: {error}", error=e)
            usage = None
        await self.chat_memory.aput(response.message)

        code, thoughts = chat_utils.extract_code_and_thought(response.message.content)

        event = PlanThinkingEvent(thoughts=thoughts, code=code, usage=usage)
        ctx.write_event_to_stream(event)
        return event

    @step
    async def handle_llm_output(
        self, ev: PlanThinkingEvent, ctx: Context
    ) -> Union[PlanInputEvent, PlanCreatedEvent]:
        """Handle LLM output."""
        LoggingUtils.log_debug("PlannerAgent", "🤖 Processing planning output...")
        code = ev.code
        thoughts = ev.thoughts

        if code:
            try:
                result = await self.executer.execute(ctx, code)
                LoggingUtils.log_info("PlannerAgent", "Planning complete")
                LoggingUtils.log_debug("PlannerAgent", "Planning code executed. Result: {output}", output=result['output'])

                screenshots = result['screenshots']
                for screenshot in screenshots[:-1]: # the last screenshot will be captured by next step
                    ctx.write_event_to_stream(ScreenshotEvent(screenshot=screenshot))
                
                ui_states = result['ui_states']
                for ui_state in ui_states[:-1]:
                    ctx.write_event_to_stream(RecordUIStateEvent(ui_state=ui_state['a11y_tree']))

                await self.chat_memory.aput(
                    ChatMessage(
                        role="user", content=f"Execution Result:\n```\n{result['output']}\n```"
                    )
                )

                self.remembered_info = self.tools_instance.memory

                tasks = self.task_manager.get_all_tasks()
                event = PlanCreatedEvent(tasks=tasks)

                if not self.task_manager.goal_completed:
                    LoggingUtils.log_info("PlannerAgent", "Current plan created with {count} tasks:", count=len(tasks))
                    for i, task in enumerate(tasks):
                        LoggingUtils.log_info("PlannerAgent", "Task {index}: [{status}] [{agent_type}] {description}", 
                                            index=i, status=task.status.upper(), agent_type=task.agent_type, description=task.description)
                    ctx.write_event_to_stream(event)

                return event

            except Exception as e:
                LoggingUtils.log_debug("PlannerAgent", "Error handling Planner: {error}", error=e)
                await self.chat_memory.aput(
                    ChatMessage(
                        role="user",
                        content="""Please either set new tasks using set_tasks_with_agents() or mark the goal as complete using complete_goal() if done.
wrap your code inside this:
```python
<YOUR CODE HERE>
```""",
                    )
                )
                LoggingUtils.log_debug("PlannerAgent", "🔄 Waiting for next plan or completion.")
                return PlanInputEvent(input=self.chat_memory.get_all())
        else:
            await self.chat_memory.aput(
                ChatMessage(
                    role="user",
                    content="""Please either set new tasks using set_tasks_with_agents() or mark the goal as complete using complete_goal() if done.
wrap your code inside this:
```python
<YOUR CODE HERE>
```""",
                )
            )
            LoggingUtils.log_debug("PlannerAgent", "🔄 Waiting for next plan or completion.")
            return PlanInputEvent(input=self.chat_memory.get_all())

    @step
    async def finalize(self, ev: PlanCreatedEvent, ctx: Context) -> StopEvent:
        """Finalize the workflow."""
        await ctx.store.set("chat_memory", self.chat_memory)

        # Best-effort resource cleanup
        try:
            if hasattr(self, "tools_instance") and isinstance(self.tools_instance, AdbTools):
                # Ensure any TCP forwardings are removed
                self.tools_instance.teardown_tcp_forward()
        except Exception:
            # Cleanup errors should not break finalize
            pass

        result = {"tasks": ev.tasks}
        return StopEvent(result=result)

    async def _get_llm_response(
        self, ctx: Context, chat_history: List[ChatMessage]
    ) -> ChatResponse:
        """Get streaming response from LLM."""
        try:
            LoggingUtils.log_debug("PlannerAgent", "Sending {count} messages to LLM", count=len(chat_history))

            model = self.llm.class_name()
            if self.vision == True:
                if model == "DeepSeek":
                    LoggingUtils.log_warning("PlannerAgent", "DeepSeek doesnt support images. Disabling screenshots")
                    self.vision = False
                else:
                    chat_history = await chat_utils.add_screenshot_image_block(
                        await ctx.store.get("screenshot"), chat_history
                    )                   



            chat_history = await chat_utils.add_task_history_block(
                #self.task_manager.get_completed_tasks(),
                #self.task_manager.get_failed_tasks(),
                self.task_manager.get_task_history(),
                chat_history,
            )

            remembered_info = await ctx.store.get("remembered_info", default=None)
            if remembered_info:
                chat_history = await chat_utils.add_memory_block(remembered_info, chat_history)

            reflection = await ctx.store.get("reflection", None)
            if reflection:
                chat_history = await chat_utils.add_reflection_summary(reflection, chat_history)

            chat_history = await chat_utils.add_phone_state_block(await ctx.store.get("phone_state"), chat_history)
            chat_history = await chat_utils.add_ui_text_block(await ctx.store.get("ui_state"), chat_history)

            limited_history = self._limit_history(chat_history)
            messages_to_send = [self.system_message] + limited_history
            messages_to_send = [
                chat_utils.message_copy(msg) for msg in messages_to_send
            ]

            LoggingUtils.log_debug("PlannerAgent", "Final message count: {count}", count=len(messages_to_send))

            response = await self.llm.achat(messages=messages_to_send)
            assert hasattr(
                response, "message"
            ), f"LLM response does not have a message attribute.\nResponse: {response}"
            LoggingUtils.log_debug("PlannerAgent", "Received response from LLM.")
            return response
        except Exception as e:
            LoggingUtils.log_error("PlannerAgent", "Could not get an answer from LLM: {error}", error=repr(e))
            raise e

    def _limit_history(
        self, chat_history: List[ChatMessage]
    ) -> List[ChatMessage]:
        if LLM_HISTORY_LIMIT <= 0:
            return chat_history

        max_messages = LLM_HISTORY_LIMIT * 2
        if len(chat_history) <= max_messages:
            return chat_history

        preserved_head: List[ChatMessage] = []
        if chat_history and chat_history[0].role == "user":
            preserved_head = [chat_history[0]]

        tail = chat_history[-max_messages:]
        if preserved_head and preserved_head[0] in tail:
            preserved_head = []

        return preserved_head + tail
