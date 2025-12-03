"""
测试失败反思器
"""

import pytest
from unittest.mock import Mock, AsyncMock
from droidrun.agent.reflection import FailureReflector, FailureContext, FailureReflection

# 配置 pytest 使用 anyio
pytestmark = pytest.mark.anyio


class TestFailureReflector:
    """测试 FailureReflector 类"""
    
    @pytest.fixture
    def mock_llm(self):
        """创建 mock LLM"""
        llm = Mock()
        
        # 创建 mock 响应
        mock_response = Mock()
        mock_response.message = Mock()
        mock_response.message.content = '''```json
{
    "problem_type": "ui_changed",
    "root_cause": "UI 布局发生变化",
    "ui_changed": true,
    "ui_change_summary": "元素数量增加",
    "recommended_strategy": "fallback_cold_start",
    "specific_advice": "建议回退到冷启动重新执行",
    "confidence": 0.8
}
```'''
        
        llm.achat = AsyncMock(return_value=mock_response)
        return llm
    
    @pytest.fixture
    def reflector(self, mock_llm):
        """创建反思器实例"""
        return FailureReflector(llm=mock_llm, debug=True)
    
    async def test_analyze_failure_basic(self, reflector):
        """测试基本的失败分析"""
        context = FailureContext.from_hot_start_failure(
            goal="申请年假",
            failed_action={"action": "tap_by_index", "params": {"index": 19}},
            error_message="Element not found",
            error_step=3
        )
        
        reflection = await reflector.analyze_failure(context)
        
        # 验证返回的是 FailureReflection 对象
        assert isinstance(reflection, FailureReflection)
        assert reflection.problem_type is not None
        assert reflection.root_cause is not None
        assert reflection.confidence >= 0.0 and reflection.confidence <= 1.0
    
    async def test_analyze_failure_with_ui_states(self, reflector):
        """测试带 UI 状态的失败分析"""
        pre_ui = {"a11y_tree": [{"className": "Button", "text": "确认"}]}
        post_ui = {"a11y_tree": [
            {"className": "Button", "text": "确认"}, 
            {"className": "TextView", "text": "新元素"}
        ]}
        
        context = FailureContext.from_hot_start_failure(
            goal="申请年假",
            failed_action={"action": "tap_by_index", "params": {"index": 19}},
            error_message="Element not found",
            error_step=3,
            pre_ui_state=pre_ui,
            post_ui_state=post_ui
        )
        
        reflection = await reflector.analyze_failure(context)
        
        # 应该检测到 UI 变化
        assert reflection.ui_changed is True
        assert reflection.ui_change_summary is not None
    
    async def test_analyze_failure_cache(self, reflector):
        """测试反思结果缓存"""
        context = FailureContext.from_hot_start_failure(
            goal="申请年假",
            failed_action={"action": "tap_by_index", "params": {"index": 19}},
            error_message="Element not found",
            error_step=3
        )
        
        # 第一次调用
        reflection1 = await reflector.analyze_failure(context)
        
        # 第二次调用（应该使用缓存）
        reflection2 = await reflector.analyze_failure(context)
        
        # 验证返回的是同一个对象（从缓存）
        assert reflection1 is reflection2
    
    async def test_clear_cache(self, reflector):
        """测试清空缓存"""
        context = FailureContext.from_hot_start_failure(
            goal="申请年假",
            failed_action={"action": "tap_by_index", "params": {"index": 19}},
            error_message="Element not found",
            error_step=3
        )
        
        # 第一次调用
        reflection1 = await reflector.analyze_failure(context)
        
        # 清空缓存
        reflector.clear_cache()
        
        # 第二次调用（应该重新生成）
        reflection2 = await reflector.analyze_failure(context)
        
        # 验证是不同的对象
        assert reflection1 is not reflection2
    
    def test_analyze_ui_change_no_change(self, reflector):
        """测试 UI 无变化的检测"""
        ui_state = {"a11y_tree": [{"className": "Button", "text": "确认"}]}
        
        ui_changed, ui_change_summary = reflector._analyze_ui_change(ui_state, ui_state)
        
        assert ui_changed is False
        assert ui_change_summary is None
    
    def test_analyze_ui_change_element_count(self, reflector):
        """测试 UI 元素数量变化的检测"""
        pre_ui = {"a11y_tree": [{"className": "Button", "text": "确认"}]}
        post_ui = {"a11y_tree": [
            {"className": "Button", "text": "确认"}, 
            {"className": "TextView", "text": "新元素"}
        ]}
        
        ui_changed, ui_change_summary = reflector._analyze_ui_change(pre_ui, post_ui)
        
        assert ui_changed is True
        assert "1" in ui_change_summary  # 元素数量从 1 变为 2
        assert "新增" in ui_change_summary
    
    def test_analyze_ui_change_missing_ui(self, reflector):
        """测试缺少 UI 状态时的处理"""
        ui_state = {"a11y_tree": [{"className": "Button"}]}
        
        # 缺少 pre_ui
        ui_changed1, summary1 = reflector._analyze_ui_change(None, ui_state)
        assert ui_changed1 is False
        assert summary1 is None
        
        # 缺少 post_ui
        ui_changed2, summary2 = reflector._analyze_ui_change(ui_state, None)
        assert ui_changed2 is False
        assert summary2 is None
    
    def test_calculate_enhanced_ui_hash(self, reflector):
        """测试增强 UI hash 计算"""
        ui_state = {"a11y_tree": [
            {"className": "Button", "text": "确认", "resourceId": "btn_ok", "clickable": True},
            {"className": "TextView", "text": "标题", "resourceId": "tv_title", "clickable": False}
        ]}
        
        hash1 = reflector._calculate_enhanced_ui_hash(ui_state)
        hash2 = reflector._calculate_enhanced_ui_hash(ui_state)
        
        # 相同的 UI 应该产生相同的 hash
        assert hash1 == hash2
        assert hash1 != ""
    
    def test_calculate_enhanced_ui_hash_different(self, reflector):
        """测试不同 UI 产生不同 hash"""
        ui_state1 = {"a11y_tree": [{"className": "Button", "text": "确认"}]}
        ui_state2 = {"a11y_tree": [{"className": "Button", "text": "取消"}]}
        
        hash1 = reflector._calculate_enhanced_ui_hash(ui_state1)
        hash2 = reflector._calculate_enhanced_ui_hash(ui_state2)
        
        assert hash1 != hash2
    
    def test_calculate_enhanced_ui_hash_empty(self, reflector):
        """测试空 UI 状态的 hash"""
        ui_state = {"a11y_tree": []}
        
        hash_value = reflector._calculate_enhanced_ui_hash(ui_state)
        
        assert hash_value == ""
    
    def test_create_fallback_reflection(self, reflector):
        """测试创建回退反思结果"""
        context = FailureContext.from_hot_start_failure(
            goal="申请年假",
            failed_action={"action": "tap_by_index", "params": {"index": 19}},
            error_message="Element not found",
            error_step=3
        )
        
        reflection = reflector._create_fallback_reflection(context)
        
        assert reflection.problem_type == "unknown"
        assert reflection.recommended_strategy == "fallback_cold_start"
        assert reflection.confidence == 0.3
    
    def test_get_failure_cache_key(self, reflector):
        """测试缓存 key 生成"""
        context = FailureContext.from_hot_start_failure(
            goal="申请年假",
            failed_action={"action": "tap_by_index", "params": {"index": 19}},
            error_message="Element not found",
            error_step=3
        )
        
        key1 = reflector._get_failure_cache_key(context)
        key2 = reflector._get_failure_cache_key(context)
        
        # 相同的上下文应该产生相同的 key
        assert key1 == key2
        assert "申请年假" in key1
        assert "hot_start" in key1
    
    def test_get_failure_cache_key_different(self, reflector):
        """测试不同上下文产生不同 key"""
        context1 = FailureContext.from_hot_start_failure(
            goal="申请年假",
            failed_action={"action": "tap_by_index", "params": {"index": 19}},
            error_message="Element not found",
            error_step=3
        )
        
        context2 = FailureContext.from_hot_start_failure(
            goal="申请病假",
            failed_action={"action": "tap_by_index", "params": {"index": 19}},
            error_message="Element not found",
            error_step=3
        )
        
        key1 = reflector._get_failure_cache_key(context1)
        key2 = reflector._get_failure_cache_key(context2)
        
        assert key1 != key2


class TestFailureReflectorLLMIntegration:
    """测试反思器与 LLM 的集成"""
    
    @pytest.fixture
    def mock_llm(self):
        """创建 mock LLM（模拟真实响应）"""
        llm = Mock()
        
        # 创建 mock 响应
        mock_response = Mock()
        mock_response.message = Mock()
        mock_response.message.content = '''```json
{
    "problem_type": "ui_changed",
    "root_cause": "UI 布局发生变化，元素索引改变",
    "ui_changed": true,
    "ui_change_summary": "元素数量增加",
    "recommended_strategy": "fallback_cold_start",
    "specific_advice": "建议回退到冷启动，使用文本匹配而非索引定位元素",
    "confidence": 0.85
}
```'''
        
        llm.achat = AsyncMock(return_value=mock_response)
        return llm
    
    @pytest.fixture
    def reflector(self, mock_llm):
        """创建反思器实例"""
        return FailureReflector(llm=mock_llm, debug=True)
    
    async def test_hot_start_failure_llm_response(self, reflector):
        """测试热启动失败的 LLM 响应解析"""
        context = FailureContext.from_hot_start_failure(
            goal="申请年假",
            failed_action={"action": "tap_by_index", "params": {"index": 19}},
            error_message="Element not found",
            error_step=3
        )
        
        reflection = await reflector.analyze_failure(context)
        
        # 验证 LLM 响应被正确解析
        assert reflection.problem_type == "ui_changed"
        assert reflection.recommended_strategy == "fallback_cold_start"
        assert reflection.confidence >= 0.8  # 可能被置信度计算调整
        assert "索引" in reflection.specific_advice or "元素" in reflection.specific_advice
    
    async def test_cold_start_failure_llm_response(self, reflector, mock_llm):
        """测试冷启动失败的 LLM 响应解析"""
        # 为冷启动场景设置不同的响应
        mock_response = Mock()
        mock_response.message = Mock()
        mock_response.message.content = '''```json
{
    "problem_type": "action_ineffective",
    "root_cause": "点击动作未产生预期效果",
    "ui_changed": false,
    "recommended_strategy": "retry_with_adjustment",
    "specific_advice": "建议尝试长按（long_press）该元素",
    "confidence": 0.75
}
```'''
        mock_llm.achat.return_value = mock_response
        
        context = FailureContext.from_action_failure(
            goal="申请年假",
            failed_action={"action": "tap_by_index", "params": {"index": 25}},
            error_message="Element not clickable",
            error_step=5,
            current_step_description="填写开始日期"
        )
        
        reflection = await reflector.analyze_failure(context)
        
        # 验证响应正确解析
        assert reflection.problem_type == "action_ineffective"
        assert reflection.recommended_strategy == "retry_with_adjustment"
        assert reflection.confidence >= 0.7
