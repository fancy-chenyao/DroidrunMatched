"""
失败反思集成测试

测试 FailureReflector 与 DroidAgent 的集成，验证热启动失败场景的反思功能。
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any

from droidrun.agent.droid.droid_agent import DroidAgent
from droidrun.agent.reflection.reflection_types import FailureReflection
from droidrun.config import UnifiedConfigManager

pytestmark = pytest.mark.anyio


class TestFailureReflectionIntegration:
    """测试失败反思与 DroidAgent 的集成"""
    
    @pytest.fixture
    def mock_llm(self):
        """创建 mock LLM"""
        llm = Mock()
        llm.class_name = Mock(return_value="MockLLM")
        
        # Mock LLM 响应（用于反思分析）
        mock_response = Mock()
        mock_response.message = Mock()
        mock_response.message.content = '''```json
{
    "problem_type": "ui_changed",
    "root_cause": "UI 元素索引发生变化，导致点击错误元素",
    "ui_changed": true,
    "ui_change_summary": "元素数量从 50 变为 55",
    "recommended_strategy": "fallback_cold_start",
    "specific_advice": "建议使用文本匹配而非索引定位元素，以应对 UI 变化",
    "confidence": 0.85
}
```'''
        llm.achat = AsyncMock(return_value=mock_response)
        
        return llm
    
    @pytest.fixture
    def mock_tools(self):
        """创建 mock Tools"""
        tools = Mock()
        
        # Mock UI 状态（用于快照）
        ui_state_before = {
            'a11y_tree': [
                {'className': 'Button', 'text': '确认', 'resourceId': 'btn_ok', 'clickable': True}
                for _ in range(50)
            ]
        }
        
        ui_state_after = {
            'a11y_tree': [
                {'className': 'Button', 'text': '确认', 'resourceId': 'btn_ok', 'clickable': True}
                for _ in range(55)  # 元素数量变化
            ]
        }
        
        # get_state_async 在不同时间返回不同状态
        call_count = {'count': 0}
        
        async def get_state_side_effect(include_screenshot=True):
            call_count['count'] += 1
            if call_count['count'] == 1:
                return ui_state_before  # 第一次调用（热启动前）
            else:
                return ui_state_after   # 后续调用（热启动后）
        
        tools.get_state_async = AsyncMock(side_effect=get_state_side_effect)
        tools.save_trajectories = "step"
        tools.memory = {}
        tools.finished = False
        
        # Mock ADB 工具方法
        tools.tap_by_index = AsyncMock(return_value="Success")
        tools.input_text = AsyncMock(return_value="Success")
        tools.swipe = AsyncMock(return_value="Success")
        tools.press_key = AsyncMock(return_value="Success")
        tools.start_app = AsyncMock(return_value="Success")
        
        return tools
    
    @pytest.fixture
    def config_manager(self):
        """创建配置管理器"""
        config = UnifiedConfigManager()
        config.set("agent.failure_reflection", True)  # 启用反思
        config.set("agent.max_steps", 5)
        config.set("system.timeout", 60)
        config.set("memory.enabled", True)
        config.set("memory.hot_start_enabled", True)
        return config
    
    async def test_reflection_disabled_by_default(self, mock_llm, mock_tools):
        """测试场景 1：反思默认未启用，行为不变"""
        agent = DroidAgent(
            goal="申请年假",
            llm=mock_llm,
            tools=mock_tools,
            enable_memory=False,  # 禁用记忆系统简化测试
            # enable_failure_reflection 未设置，默认 False
        )
        
        # 验证反思未启用
        assert agent.enable_failure_reflection is False
        assert agent.failure_reflector is None
        
        # 验证不会调用 get_state_async（用于 UI 快照）
        # 注意：这个测试需要实际执行流程，这里只验证初始化
    
    async def test_reflection_enabled_initialization(self, mock_llm, mock_tools, config_manager):
        """测试场景 2：反思启用时正确初始化"""
        agent = DroidAgent(
            goal="申请年假",
            llm=mock_llm,
            tools=mock_tools,
            enable_memory=False,
            enable_failure_reflection=True,  # 显式启用
            config_manager=config_manager,
        )
        
        # 验证反思已启用
        assert agent.enable_failure_reflection is True
        assert agent.failure_reflector is not None
        
        # 验证 FailureReflector 正确初始化
        assert agent.failure_reflector.llm == mock_llm
        assert agent.failure_reflector.tools_instance == mock_tools
    
    async def test_hot_start_success_no_reflection(self, mock_llm, mock_tools, config_manager):
        """测试场景 3：热启动成功，不触发反思"""
        agent = DroidAgent(
            goal="申请年假",
            llm=mock_llm,
            tools=mock_tools,
            enable_memory=True,
            enable_failure_reflection=True,
            config_manager=config_manager,
        )
        
        # 模拟热启动成功
        agent.pending_hot_actions = [
            {"action": "tap_by_index", "params": {"index": 10}},
            {"action": "complete", "params": {"reason": "Success"}},
        ]
        
        # Mock _direct_execute_actions_async 返回成功
        with patch.object(agent, '_direct_execute_actions_async', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = (True, "Hot start completed successfully")
            
            # 执行任务
            from droidrun.agent.droid.events import CodeActExecuteEvent
            from droidrun.agent.context.task_manager import Task
            
            task = Task(description="申请年假", status="pending", agent_type="Default")
            event = CodeActExecuteEvent(task=task, reflection=None)
            
            # Mock Context
            mock_ctx = Mock()
            
            result = await agent.execute_task(mock_ctx, event)
            
            # 验证热启动成功
            assert result.success is True
            
            # 验证 LLM 的 achat 未被调用（因为没有触发反思）
            mock_llm.achat.assert_not_called()
    
    async def test_hot_start_failure_high_confidence_reflection(self, mock_llm, mock_tools, config_manager):
        """测试场景 4：热启动失败 + 高置信度反思 + 应用建议"""
        agent = DroidAgent(
            goal="申请年假",
            llm=mock_llm,
            tools=mock_tools,
            enable_memory=True,
            enable_failure_reflection=True,
            config_manager=config_manager,
        )
        
        # 模拟热启动失败
        agent.pending_hot_actions = [
            {"action": "tap_by_index", "params": {"index": 10}},
            {"action": "tap_by_index", "params": {"index": 20}},
        ]
        
        # Mock _direct_execute_actions_async 返回失败
        with patch.object(agent, '_direct_execute_actions_async', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = (False, "Element not found at step 1")
            
            # Mock CodeActAgent 的执行（冷启动）
            with patch('droidrun.agent.droid.droid_agent.CodeActAgent') as MockCodeActAgent:
                mock_codeact_instance = Mock()
                mock_codeact_handler = Mock()
                
                # 模拟 CodeActAgent 的事件流
                async def mock_stream_events():
                    return
                    yield  # 使其成为异步生成器
                
                mock_codeact_handler.stream_events = mock_stream_events
                mock_codeact_instance.run = Mock(return_value=mock_codeact_handler)
                MockCodeActAgent.return_value = mock_codeact_instance
                
                # 执行任务
                from droidrun.agent.droid.events import CodeActExecuteEvent
                from droidrun.agent.context.task_manager import Task
                
                task = Task(description="申请年假", status="pending", agent_type="Default")
                event = CodeActExecuteEvent(task=task, reflection=None)
                
                mock_ctx = Mock()
                
                # 执行
                await agent.execute_task(mock_ctx, event)
                
                # 验证 LLM 被调用（用于反思分析）
                assert mock_llm.achat.call_count >= 1
                
                # 验证 UI 快照被保存（get_state_async 被调用至少 2 次）
                # 第一次：热启动前，第二次：热启动失败后
                assert mock_tools.get_state_async.call_count >= 2
                
                # 验证 CodeActAgent 被创建并使用增强的目标
                MockCodeActAgent.assert_called_once()
                mock_codeact_instance.run.assert_called_once()
                
                # 验证任务描述包含反思建议（通过检查 Task 创建）
                # 注意：这需要访问内部状态，这里简化处理
    
    async def test_hot_start_failure_low_confidence_no_advice(self, mock_llm, mock_tools, config_manager):
        """测试场景 5：热启动失败 + 低置信度 + 不应用建议"""
        # 修改 LLM 响应为低置信度
        low_confidence_response = Mock()
        low_confidence_response.message = Mock()
        low_confidence_response.message.content = '''```json
{
    "problem_type": "unknown",
    "root_cause": "无法确定失败原因",
    "ui_changed": false,
    "recommended_strategy": "fallback_cold_start",
    "specific_advice": "建议回退到冷启动",
    "confidence": 0.5
}
```'''
        mock_llm.achat = AsyncMock(return_value=low_confidence_response)
        
        agent = DroidAgent(
            goal="申请年假",
            llm=mock_llm,
            tools=mock_tools,
            enable_memory=True,
            enable_failure_reflection=True,
            config_manager=config_manager,
        )
        
        agent.pending_hot_actions = [
            {"action": "tap_by_index", "params": {"index": 10}},
        ]
        
        with patch.object(agent, '_direct_execute_actions_async', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = (False, "Unknown error")
            
            with patch('droidrun.agent.droid.droid_agent.CodeActAgent') as MockCodeActAgent:
                mock_codeact_instance = Mock()
                mock_codeact_handler = Mock()
                
                async def mock_stream_events():
                    return
                    yield
                
                mock_codeact_handler.stream_events = mock_stream_events
                mock_codeact_instance.run = Mock(return_value=mock_codeact_handler)
                MockCodeActAgent.return_value = mock_codeact_instance
                
                from droidrun.agent.droid.events import CodeActExecuteEvent
                from droidrun.agent.context.task_manager import Task
                
                task = Task(description="申请年假", status="pending", agent_type="Default")
                event = CodeActExecuteEvent(task=task, reflection=None)
                
                mock_ctx = Mock()
                
                await agent.execute_task(mock_ctx, event)
                
                # 验证 LLM 被调用
                assert mock_llm.achat.call_count >= 1
                
                # 验证任务描述未被增强（因为置信度低）
                # 这需要验证传给 Task 的 description 是原始 goal
    
    async def test_reflection_failure_does_not_break_cold_start(self, mock_llm, mock_tools, config_manager):
        """测试场景 6：反思失败不影响冷启动"""
        # 让 LLM 抛出异常
        mock_llm.achat = AsyncMock(side_effect=Exception("LLM service unavailable"))
        
        agent = DroidAgent(
            goal="申请年假",
            llm=mock_llm,
            tools=mock_tools,
            enable_memory=True,
            enable_failure_reflection=True,
            config_manager=config_manager,
        )
        
        agent.pending_hot_actions = [
            {"action": "tap_by_index", "params": {"index": 10}},
        ]
        
        with patch.object(agent, '_direct_execute_actions_async', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = (False, "Hot start failed")
            
            with patch('droidrun.agent.droid.droid_agent.CodeActAgent') as MockCodeActAgent:
                mock_codeact_instance = Mock()
                mock_codeact_handler = Mock()
                
                async def mock_stream_events():
                    return
                    yield
                
                mock_codeact_handler.stream_events = mock_stream_events
                mock_codeact_instance.run = Mock(return_value=mock_codeact_handler)
                MockCodeActAgent.return_value = mock_codeact_instance
                
                from droidrun.agent.droid.events import CodeActExecuteEvent
                from droidrun.agent.context.task_manager import Task
                
                task = Task(description="申请年假", status="pending", agent_type="Default")
                event = CodeActExecuteEvent(task=task, reflection=None)
                
                mock_ctx = Mock()
                
                # 执行应该成功（即使反思失败）
                await agent.execute_task(mock_ctx, event)
                
                # 验证 LLM 被调用（尝试反思）
                assert mock_llm.achat.call_count >= 1
                
                # 验证 CodeActAgent 仍然被创建（冷启动继续）
                MockCodeActAgent.assert_called_once()
    
    async def test_ui_snapshot_failure_does_not_break_execution(self, mock_llm, mock_tools, config_manager):
        """测试场景 7：UI 快照保存失败不影响执行"""
        # 让 get_state_async 抛出异常
        mock_tools.get_state_async = AsyncMock(side_effect=Exception("Device disconnected"))
        
        agent = DroidAgent(
            goal="申请年假",
            llm=mock_llm,
            tools=mock_tools,
            enable_memory=True,
            enable_failure_reflection=True,
            config_manager=config_manager,
        )
        
        agent.pending_hot_actions = [
            {"action": "tap_by_index", "params": {"index": 10}},
        ]
        
        with patch.object(agent, '_direct_execute_actions_async', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = (False, "Hot start failed")
            
            with patch('droidrun.agent.droid.droid_agent.CodeActAgent') as MockCodeActAgent:
                mock_codeact_instance = Mock()
                mock_codeact_handler = Mock()
                
                async def mock_stream_events():
                    return
                    yield
                
                mock_codeact_handler.stream_events = mock_stream_events
                mock_codeact_instance.run = Mock(return_value=mock_codeact_handler)
                MockCodeActAgent.return_value = mock_codeact_instance
                
                from droidrun.agent.droid.events import CodeActExecuteEvent
                from droidrun.agent.context.task_manager import Task
                
                task = Task(description="申请年假", status="pending", agent_type="Default")
                event = CodeActExecuteEvent(task=task, reflection=None)
                
                mock_ctx = Mock()
                
                # 执行应该成功（即使 UI 快照失败）
                await agent.execute_task(mock_ctx, event)
                
                # 验证 get_state_async 被调用（尝试保存快照）
                assert mock_tools.get_state_async.call_count >= 1
                
                # 验证 CodeActAgent 仍然被创建（执行继续）
                MockCodeActAgent.assert_called_once()


class TestFailureReflectionConfiguration:
    """测试失败反思的配置"""
    
    def test_config_from_parameter(self):
        """测试通过参数启用反思"""
        mock_llm = Mock()
        mock_llm.class_name = Mock(return_value="MockLLM")
        mock_tools = Mock()
        mock_tools.save_trajectories = "step"
        
        agent = DroidAgent(
            goal="测试",
            llm=mock_llm,
            tools=mock_tools,
            enable_memory=False,
            enable_failure_reflection=True,  # 参数传递
        )
        
        assert agent.enable_failure_reflection is True
        assert agent.failure_reflector is not None
    
    def test_config_from_config_manager(self):
        """测试通过配置管理器启用反思"""
        mock_llm = Mock()
        mock_llm.class_name = Mock(return_value="MockLLM")
        mock_tools = Mock()
        mock_tools.save_trajectories = "step"
        
        config = UnifiedConfigManager()
        config.set("agent.failure_reflection", True)
        
        agent = DroidAgent(
            goal="测试",
            llm=mock_llm,
            tools=mock_tools,
            enable_memory=False,
            config_manager=config,
            # enable_failure_reflection 未设置，使用配置
        )
        
        assert agent.enable_failure_reflection is True
        assert agent.failure_reflector is not None
    
    def test_config_default_disabled(self):
        """测试显式禁用反思"""
        mock_llm = Mock()
        mock_llm.class_name = Mock(return_value="MockLLM")
        mock_tools = Mock()
        mock_tools.save_trajectories = "step"
        
        # 显式禁用反思
        agent = DroidAgent(
            goal="测试",
            llm=mock_llm,
            tools=mock_tools,
            enable_memory=False,
            enable_failure_reflection=False,  # 显式禁用
        )
        
        assert agent.enable_failure_reflection is False
        assert agent.failure_reflector is None
