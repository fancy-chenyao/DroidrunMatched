"""
DroidRun 失败分析型反思模块

该模块提供失败场景的自动分析和改进建议功能，用于提高任务执行的成功率和鲁棒性。

主要组件：
- FailureContext: 失败场景的完整上下文信息
- FailureReflection: 反思分析的结果
- FailureReflector: 核心反思分析引擎

使用示例：
    from droidrun.agent.reflection import FailureReflector, FailureContext
    
    # 创建反思器
    reflector = FailureReflector(llm=llm, tools_instance=tools, debug=True)
    
    # 构建失败上下文
    context = FailureContext.from_hot_start_failure(
        goal="申请年假",
        failed_action={"action": "tap_by_index", "params": {"index": 19}},
        error_message="Element at index 19 not found",
        error_step=3
    )
    
    # 执行反思分析
    reflection = await reflector.analyze_failure(context)
    
    # 使用反思结果
    print(f"问题类型: {reflection.problem_type}")
    print(f"根本原因: {reflection.root_cause}")
    print(f"建议: {reflection.specific_advice}")
"""

from droidrun.agent.reflection.reflection_types import (
    FailureContext,
    FailureReflection,
)
from droidrun.agent.reflection.failure_reflector import FailureReflector

__all__ = [
    "FailureContext",
    "FailureReflection",
    "FailureReflector",
]

__version__ = "1.0.0"
