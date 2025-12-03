"""
测试失败反思模块的数据类型
"""

import pytest
from droidrun.agent.reflection.reflection_types import FailureContext, FailureReflection


class TestFailureContext:
    """测试 FailureContext 数据类"""
    
    def test_from_hot_start_failure_basic(self):
        """测试从热启动失败创建上下文（基础信息）"""
        context = FailureContext.from_hot_start_failure(
            goal="申请年假",
            failed_action={"action": "tap_by_index", "params": {"index": 19}},
            error_message="Element at index 19 not found",
            error_step=3
        )
        
        assert context.failure_type == "hot_start"
        assert context.goal == "申请年假"
        assert context.error_step == 3
        assert context.error_message == "Element at index 19 not found"
        assert context.failed_action["action"] == "tap_by_index"
        assert context.failed_action["params"]["index"] == 19
    
    def test_from_hot_start_failure_with_ui_states(self):
        """测试从热启动失败创建上下文（包含 UI 状态）"""
        pre_ui = {"a11y_tree": [{"className": "Button", "text": "确认"}]}
        post_ui = {"a11y_tree": [{"className": "Button", "text": "确认"}, {"className": "TextView", "text": "错误"}]}
        
        context = FailureContext.from_hot_start_failure(
            goal="申请年假",
            failed_action={"action": "tap_by_index", "params": {"index": 19}},
            error_message="Element not found",
            error_step=3,
            pre_ui_state=pre_ui,
            post_ui_state=post_ui,
            recent_actions=[
                {"action": "tap_by_index", "params": {"index": 10}},
                {"action": "input_text", "params": {"index": 15, "text": "年假"}},
            ]
        )
        
        assert context.pre_ui_state is not None
        assert context.post_ui_state is not None
        assert len(context.recent_actions) == 2
        assert len(context.pre_ui_state["a11y_tree"]) == 1
        assert len(context.post_ui_state["a11y_tree"]) == 2
    
    def test_from_action_failure(self):
        """测试从单个动作失败创建上下文"""
        context = FailureContext.from_action_failure(
            goal="申请年假",
            failed_action={"action": "tap_by_index", "params": {"index": 25}},
            error_message="Element not clickable",
            error_step=5,
            current_step_description="填写开始日期"
        )
        
        assert context.failure_type == "cold_start_action"
        assert context.current_step_description == "填写开始日期"
        assert context.error_step == 5
    
    def test_to_dict(self):
        """测试转换为字典"""
        context = FailureContext.from_hot_start_failure(
            goal="申请年假",
            failed_action={"action": "tap_by_index", "params": {"index": 19}},
            error_message="Element not found",
            error_step=3,
            pre_ui_state={"a11y_tree": []},
            post_ui_state={"a11y_tree": []},
            recent_actions=[{"action": "tap_by_index"}]
        )
        
        context_dict = context.to_dict()
        
        assert context_dict["failure_type"] == "hot_start"
        assert context_dict["goal"] == "申请年假"
        assert context_dict["error_step"] == 3
        assert context_dict["has_pre_ui"] is True
        assert context_dict["has_post_ui"] is True
        assert context_dict["recent_actions_count"] == 1


class TestFailureReflection:
    """测试 FailureReflection 数据类"""
    
    def test_from_dict_complete(self):
        """测试从完整字典创建反思结果"""
        data = {
            "problem_type": "ui_changed",
            "root_cause": "UI 布局发生变化",
            "ui_changed": True,
            "ui_change_summary": "元素数量增加",
            "recommended_strategy": "fallback_cold_start",
            "specific_advice": "建议回退到冷启动",
            "suggested_action": {"action": "tap_by_index", "params": {"index": 25}},
            "suggested_params": {"text": "新文本"},
            "confidence": 0.9
        }
        
        reflection = FailureReflection.from_dict(data)
        
        assert reflection.problem_type == "ui_changed"
        assert reflection.root_cause == "UI 布局发生变化"
        assert reflection.ui_changed is True
        assert reflection.ui_change_summary == "元素数量增加"
        assert reflection.recommended_strategy == "fallback_cold_start"
        assert reflection.specific_advice == "建议回退到冷启动"
        assert reflection.suggested_action["action"] == "tap_by_index"
        assert reflection.confidence == 0.9
    
    def test_from_dict_minimal(self):
        """测试从最小字典创建反思结果"""
        data = {
            "problem_type": "unknown",
            "root_cause": "未知错误",
        }
        
        reflection = FailureReflection.from_dict(data)
        
        assert reflection.problem_type == "unknown"
        assert reflection.root_cause == "未知错误"
        assert reflection.ui_changed is False
        assert reflection.recommended_strategy == "fallback_cold_start"
        assert reflection.confidence == 0.5
    
    def test_to_dict(self):
        """测试转换为字典"""
        reflection = FailureReflection(
            problem_type="action_ineffective",
            root_cause="动作无效果",
            ui_changed=False,
            recommended_strategy="retry_with_adjustment",
            specific_advice="尝试长按",
            confidence=0.7
        )
        
        reflection_dict = reflection.to_dict()
        
        assert reflection_dict["problem_type"] == "action_ineffective"
        assert reflection_dict["root_cause"] == "动作无效果"
        assert reflection_dict["ui_changed"] is False
        assert reflection_dict["confidence"] == 0.7
    
    def test_should_apply_advice_high_confidence(self):
        """测试高置信度时应该应用建议"""
        reflection = FailureReflection(
            problem_type="ui_changed",
            root_cause="测试",
            ui_changed=True,
            confidence=0.8
        )
        
        assert reflection.should_apply_advice(threshold=0.6) is True
        assert reflection.should_apply_advice(threshold=0.9) is False
    
    def test_should_apply_advice_low_confidence(self):
        """测试低置信度时不应该应用建议"""
        reflection = FailureReflection(
            problem_type="unknown",
            root_cause="测试",
            ui_changed=False,
            confidence=0.4
        )
        
        assert reflection.should_apply_advice(threshold=0.6) is False
        assert reflection.should_apply_advice(threshold=0.3) is True
    
    def test_default_values(self):
        """测试默认值"""
        reflection = FailureReflection(
            problem_type="test",
            root_cause="test reason",
            ui_changed=True
        )
        
        assert reflection.ui_change_summary is None
        assert reflection.recommended_strategy == "fallback_cold_start"
        assert reflection.specific_advice == ""
        assert reflection.suggested_action is None
        assert reflection.suggested_params is None
        assert reflection.confidence == 0.5


class TestDataTypesIntegration:
    """测试数据类型的集成使用"""
    
    def test_full_workflow(self):
        """测试完整的数据流转"""
        # 1. 创建失败上下文
        context = FailureContext.from_hot_start_failure(
            goal="申请年假",
            failed_action={"action": "tap_by_index", "params": {"index": 19}},
            error_message="Element not found",
            error_step=3,
            pre_ui_state={"a11y_tree": [{"text": "开始日期"}]},
            post_ui_state={"a11y_tree": [{"text": "开始日期"}, {"text": "新元素"}]}
        )
        
        # 2. 模拟反思结果
        reflection_data = {
            "problem_type": "ui_changed",
            "root_cause": "UI 元素增加",
            "ui_changed": True,
            "ui_change_summary": "新增了 1 个元素",
            "recommended_strategy": "fallback_cold_start",
            "specific_advice": "使用文本匹配定位元素",
            "confidence": 0.85
        }
        
        reflection = FailureReflection.from_dict(reflection_data)
        
        # 3. 验证数据流转
        assert context.failure_type == "hot_start"
        assert reflection.problem_type == "ui_changed"
        assert reflection.should_apply_advice(threshold=0.8) is True
        
        # 4. 序列化
        context_dict = context.to_dict()
        reflection_dict = reflection.to_dict()
        
        assert context_dict["failure_type"] == "hot_start"
        assert reflection_dict["confidence"] == 0.85
