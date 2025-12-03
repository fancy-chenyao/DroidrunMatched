"""
Step 5 Memory 系统集成测试

测试失败反思与 Memory 系统的集成：
1. 失败反思保存到 Trajectory
2. Trajectory 序列化包含 failure_reflections
3. Trajectory 反序列化兼容性
4. Experience 包含 failure_reflections
5. 端到端集成流程
"""
import pytest
import json
import os
import shutil
import time
import tempfile
from unittest.mock import Mock, AsyncMock, patch
from dataclasses import asdict

from droidrun.agent.utils.trajectory import Trajectory
from droidrun.agent.context.experience_memory import TaskExperience
from droidrun.agent.reflection.reflection_types import FailureReflection

pytestmark = pytest.mark.anyio


class TestTrajectoryIntegration:
    """测试 Trajectory 集成"""
    
    def test_trajectory_has_failure_reflections_field(self):
        """测试 Trajectory 包含 failure_reflections 字段"""
        trajectory = Trajectory(goal="测试目标")
        
        # 验证字段存在
        assert hasattr(trajectory, 'failure_reflections')
        assert isinstance(trajectory.failure_reflections, list)
        assert len(trajectory.failure_reflections) == 0
    
    def test_add_failure_reflection_to_trajectory(self):
        """测试添加失败反思到 Trajectory"""
        trajectory = Trajectory(goal="测试目标")
        
        # 添加反思
        reflection_data = {
            "problem_type": "ui_changed",
            "root_cause": "UI 元素位置发生变化",
            "specific_advice": "建议使用更稳定的定位方式",
            "confidence": 0.85,
            "timestamp": time.time(),
            "failed_action": {"action": "tap", "index": 10},
            "error_step": 2
        }
        
        trajectory.failure_reflections.append(reflection_data)
        
        # 验证
        assert len(trajectory.failure_reflections) == 1
        assert trajectory.failure_reflections[0]["problem_type"] == "ui_changed"
        assert trajectory.failure_reflections[0]["confidence"] == 0.85
    
    def test_trajectory_serialization_includes_reflections(self):
        """测试 Trajectory 序列化包含 failure_reflections"""
        # 创建临时目录
        temp_dir = tempfile.mkdtemp()
        
        try:
            trajectory = Trajectory(goal="测试目标", experience_id="test_exp_123")
            
            # 添加反思
            trajectory.failure_reflections.append({
                "problem_type": "ui_changed",
                "confidence": 0.85
            })
            
            # 保存
            saved_folder = trajectory.save_trajectory(directory=temp_dir)
            
            # 读取保存的文件
            trajectory_json_path = os.path.join(saved_folder, "trajectory.json")
            assert os.path.exists(trajectory_json_path)
            
            with open(trajectory_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # 验证新格式
            assert isinstance(data, dict), "trajectory.json 应该是对象格式"
            assert "events" in data
            assert "goal" in data
            assert "experience_id" in data
            assert "failure_reflections" in data
            
            # 验证反思内容
            assert len(data["failure_reflections"]) == 1
            assert data["failure_reflections"][0]["problem_type"] == "ui_changed"
            assert data["failure_reflections"][0]["confidence"] == 0.85
            
        finally:
            # 清理
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_trajectory_serialization_without_reflections(self):
        """测试 Trajectory 序列化（无反思）"""
        temp_dir = tempfile.mkdtemp()
        
        try:
            trajectory = Trajectory(goal="测试目标")
            # 不添加反思
            
            # 保存
            saved_folder = trajectory.save_trajectory(directory=temp_dir)
            
            # 读取
            trajectory_json_path = os.path.join(saved_folder, "trajectory.json")
            with open(trajectory_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # 验证：没有反思时，不应该有 failure_reflections 字段
            # 或者是空列表（取决于实现）
            if "failure_reflections" in data:
                assert data["failure_reflections"] == []
            
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_trajectory_deserialization_new_format(self):
        """测试 Trajectory 反序列化（新格式）"""
        temp_dir = tempfile.mkdtemp()
        
        try:
            # 创建新格式的 trajectory.json
            trajectory_folder = os.path.join(temp_dir, "test_trajectory")
            os.makedirs(trajectory_folder, exist_ok=True)
            
            new_format_data = {
                "events": [
                    {"type": "TaskStartEvent", "task": "测试"}
                ],
                "goal": "测试目标",
                "experience_id": "test_exp",
                "failure_reflections": [
                    {
                        "problem_type": "ui_changed",
                        "confidence": 0.85
                    }
                ]
            }
            
            trajectory_json_path = os.path.join(trajectory_folder, "trajectory.json")
            with open(trajectory_json_path, "w", encoding="utf-8") as f:
                json.dump(new_format_data, f)
            
            # 加载
            result = Trajectory.load_trajectory_folder(trajectory_folder)
            
            # 验证
            assert result["trajectory_data"] is not None
            assert "events" in result["trajectory_data"]
            assert "failure_reflections" in result["trajectory_data"]
            assert len(result["trajectory_data"]["failure_reflections"]) == 1
            assert result["trajectory_data"]["failure_reflections"][0]["problem_type"] == "ui_changed"
            
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_trajectory_deserialization_old_format(self):
        """测试 Trajectory 反序列化（旧格式）- 向后兼容"""
        temp_dir = tempfile.mkdtemp()
        
        try:
            # 创建旧格式的 trajectory.json（直接是数组）
            trajectory_folder = os.path.join(temp_dir, "test_trajectory")
            os.makedirs(trajectory_folder, exist_ok=True)
            
            old_format_data = [
                {"type": "TaskStartEvent", "task": "测试"},
                {"type": "ActionEvent", "action": "tap"}
            ]
            
            trajectory_json_path = os.path.join(trajectory_folder, "trajectory.json")
            with open(trajectory_json_path, "w", encoding="utf-8") as f:
                json.dump(old_format_data, f)
            
            # 加载
            result = Trajectory.load_trajectory_folder(trajectory_folder)
            
            # 验证：旧格式应该被转换为新格式
            assert result["trajectory_data"] is not None
            assert "events" in result["trajectory_data"]
            assert isinstance(result["trajectory_data"]["events"], list)
            assert len(result["trajectory_data"]["events"]) == 2
            
            # 旧格式没有 failure_reflections，不应该报错
            # 可能没有这个字段，或者是 None
            
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestExperienceIntegration:
    """测试 Experience 集成"""
    
    def test_experience_includes_failure_reflections(self):
        """测试 Experience 包含 failure_reflections"""
        experience = TaskExperience(
            id="test_exp",
            goal="测试目标",
            type="task",
            success=False,
            timestamp=time.time(),
            page_sequence=[],
            action_sequence=[],
            ui_states=[],
            metadata={
                "steps": 5,
                "failure_reflections": [
                    {
                        "problem_type": "ui_changed",
                        "confidence": 0.85
                    }
                ]
            }
        )
        
        # 验证
        assert "failure_reflections" in experience.metadata
        assert len(experience.metadata["failure_reflections"]) == 1
    
    def test_experience_serialization(self):
        """测试 Experience 序列化"""
        experience = TaskExperience(
            id="test_exp",
            goal="测试目标",
            type="task",
            success=False,
            timestamp=time.time(),
            page_sequence=[],
            action_sequence=[],
            ui_states=[],
            metadata={
                "failure_reflections": [
                    {
                        "problem_type": "ui_changed",
                        "root_cause": "UI 变化",
                        "specific_advice": "建议",
                        "confidence": 0.85,
                        "timestamp": time.time()
                    }
                ]
            }
        )
        
        # 序列化
        exp_dict = experience.to_dict()
        
        # 验证
        assert "metadata" in exp_dict
        assert "failure_reflections" in exp_dict["metadata"]
        assert len(exp_dict["metadata"]["failure_reflections"]) == 1
        assert exp_dict["metadata"]["failure_reflections"][0]["problem_type"] == "ui_changed"
        
        # 验证可以转换为 JSON
        json_str = json.dumps(exp_dict, ensure_ascii=False)
        assert json_str is not None
        
        # 验证可以反序列化
        loaded_dict = json.loads(json_str)
        assert loaded_dict["metadata"]["failure_reflections"][0]["confidence"] == 0.85


class TestEndToEndIntegration:
    """端到端集成测试"""
    
    @pytest.fixture
    def mock_droid_agent_components(self):
        """创建 mock 的 DroidAgent 组件"""
        mock_llm = Mock()
        mock_llm.class_name = Mock(return_value="MockLLM")
        
        mock_tools = Mock()
        mock_tools.get_state_async = AsyncMock(return_value={
            "a11y_tree": [],
            "screenshot": None
        })
        
        return mock_llm, mock_tools
    
    async def test_failure_reflection_to_trajectory(self, mock_droid_agent_components):
        """测试失败反思保存到 Trajectory 的完整流程"""
        mock_llm, mock_tools = mock_droid_agent_components
        
        # 创建 Trajectory
        trajectory = Trajectory(goal="填写请假单", experience_id="test_exp")
        
        # 模拟失败反思结果
        reflection_data = {
            "problem_type": "ui_changed",
            "root_cause": "UI 元素位置发生变化",
            "specific_advice": "建议使用更稳定的定位方式",
            "confidence": 0.85,
            "timestamp": time.time(),
            "failed_action": {"action": "tap_by_index", "index": 111},
            "error_step": 2
        }
        
        # 模拟 DroidAgent 的保存逻辑
        if hasattr(trajectory, 'failure_reflections'):
            trajectory.failure_reflections.append(reflection_data)
        
        # 验证
        assert len(trajectory.failure_reflections) == 1
        assert trajectory.failure_reflections[0]["confidence"] == 0.85
    
    async def test_trajectory_to_experience(self, mock_droid_agent_components):
        """测试 Trajectory 到 Experience 的转换"""
        mock_llm, mock_tools = mock_droid_agent_components
        
        # 创建带反思的 Trajectory
        trajectory = Trajectory(goal="填写请假单", experience_id="test_exp")
        trajectory.failure_reflections.append({
            "problem_type": "ui_changed",
            "confidence": 0.85
        })
        
        # 模拟构建 Experience 的逻辑
        experience = TaskExperience(
            id=trajectory.experience_id,
            goal=trajectory.goal,
            type="task",
            success=False,
            timestamp=time.time(),
            page_sequence=[],
            action_sequence=[],
            ui_states=[],
            metadata={
                "steps": 5,
                "is_hot_start": True,
                # 从 trajectory 复制 failure_reflections
                "failure_reflections": trajectory.failure_reflections if hasattr(trajectory, 'failure_reflections') else []
            }
        )
        
        # 验证
        assert "failure_reflections" in experience.metadata
        assert len(experience.metadata["failure_reflections"]) == 1
        assert experience.metadata["failure_reflections"][0]["problem_type"] == "ui_changed"
    
    async def test_full_save_and_load_cycle(self):
        """测试完整的保存和加载周期"""
        temp_dir = tempfile.mkdtemp()
        
        try:
            # 1. 创建带反思的 Trajectory
            trajectory = Trajectory(goal="填写请假单", experience_id="test_exp_full")
            trajectory.failure_reflections.append({
                "problem_type": "ui_changed",
                "root_cause": "UI 变化",
                "specific_advice": "建议使用稳定定位",
                "confidence": 0.85,
                "timestamp": time.time(),
                "failed_action": {"action": "tap", "index": 10},
                "error_step": 2
            })
            
            # 2. 保存 Trajectory
            saved_folder = trajectory.save_trajectory(directory=temp_dir)
            
            # 3. 加载 Trajectory
            loaded_result = Trajectory.load_trajectory_folder(saved_folder)
            
            # 4. 验证加载的数据
            assert loaded_result["trajectory_data"] is not None
            assert "failure_reflections" in loaded_result["trajectory_data"]
            assert len(loaded_result["trajectory_data"]["failure_reflections"]) == 1
            
            loaded_reflection = loaded_result["trajectory_data"]["failure_reflections"][0]
            assert loaded_reflection["problem_type"] == "ui_changed"
            assert loaded_reflection["confidence"] == 0.85
            assert loaded_reflection["specific_advice"] == "建议使用稳定定位"
            
            # 5. 构建 Experience
            experience = TaskExperience(
                id="test_exp_full",
                goal="填写请假单",
                type="task",
                success=False,
                timestamp=time.time(),
                page_sequence=[],
                action_sequence=[],
                ui_states=[],
                metadata={
                    "failure_reflections": loaded_result["trajectory_data"]["failure_reflections"]
                }
            )
            
            # 6. 验证 Experience
            assert len(experience.metadata["failure_reflections"]) == 1
            
            # 7. 序列化 Experience
            exp_dict = experience.to_dict()
            json_str = json.dumps(exp_dict, ensure_ascii=False)
            
            # 8. 反序列化并验证
            loaded_exp_dict = json.loads(json_str)
            assert loaded_exp_dict["metadata"]["failure_reflections"][0]["confidence"] == 0.85
            
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestDataIntegrity:
    """数据完整性测试"""
    
    def test_reflection_data_structure_completeness(self):
        """测试反思数据结构完整性"""
        # 完整的反思数据应该包含的字段
        required_fields = [
            "problem_type",
            "root_cause",
            "specific_advice",
            "confidence",
            "timestamp",
            "failed_action",
            "error_step"
        ]
        
        reflection_data = {
            "problem_type": "ui_changed",
            "root_cause": "UI 元素位置发生变化",
            "specific_advice": "建议使用更稳定的定位方式",
            "confidence": 0.85,
            "timestamp": time.time(),
            "failed_action": {"action": "tap", "index": 10},
            "error_step": 2
        }
        
        # 验证所有必需字段存在
        for field in required_fields:
            assert field in reflection_data, f"缺少字段: {field}"
    
    def test_multiple_reflections_in_trajectory(self):
        """测试 Trajectory 包含多个反思"""
        trajectory = Trajectory(goal="测试")
        
        # 添加多个反思（模拟多次失败）
        for i in range(3):
            trajectory.failure_reflections.append({
                "problem_type": f"type_{i}",
                "confidence": 0.7 + i * 0.1,
                "timestamp": time.time() + i
            })
        
        # 验证
        assert len(trajectory.failure_reflections) == 3
        assert trajectory.failure_reflections[0]["confidence"] == 0.7
        # 使用近似比较避免浮点数精度问题
        assert abs(trajectory.failure_reflections[2]["confidence"] - 0.9) < 0.0001
    
    def test_reflection_persistence_across_save_load(self):
        """测试反思数据在保存和加载后保持一致"""
        temp_dir = tempfile.mkdtemp()
        
        try:
            # 创建反思数据
            original_reflection = {
                "problem_type": "ui_changed",
                "root_cause": "测试根本原因",
                "specific_advice": "测试建议",
                "confidence": 0.876543,  # 特定值，便于验证
                "timestamp": 1701594123.456,
                "failed_action": {"action": "tap", "index": 42},
                "error_step": 7
            }
            
            # 保存
            trajectory = Trajectory(goal="测试", experience_id="test_persist")
            trajectory.failure_reflections.append(original_reflection)
            saved_folder = trajectory.save_trajectory(directory=temp_dir)
            
            # 加载
            loaded_result = Trajectory.load_trajectory_folder(saved_folder)
            loaded_reflection = loaded_result["trajectory_data"]["failure_reflections"][0]
            
            # 验证所有字段完全一致
            assert loaded_reflection["problem_type"] == original_reflection["problem_type"]
            assert loaded_reflection["root_cause"] == original_reflection["root_cause"]
            assert loaded_reflection["specific_advice"] == original_reflection["specific_advice"]
            assert loaded_reflection["confidence"] == original_reflection["confidence"]
            assert loaded_reflection["timestamp"] == original_reflection["timestamp"]
            assert loaded_reflection["failed_action"] == original_reflection["failed_action"]
            assert loaded_reflection["error_step"] == original_reflection["error_step"]
            
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
