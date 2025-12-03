"""
反思模块测试配置
"""

import pytest


def pytest_collection_modifyitems(config, items):
    """修改测试收集，跳过 trio 后端的测试"""
    for item in items:
        # 如果测试名称包含 [trio]，标记为跳过
        if "[trio]" in item.nodeid:
            item.add_marker(pytest.mark.skip(reason="Trio backend not used in this project"))
