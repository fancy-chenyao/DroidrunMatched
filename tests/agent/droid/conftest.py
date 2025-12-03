"""
Configuration for droid agent integration tests.
"""
import pytest


def pytest_collection_modifyitems(items):
    """Skip trio backend tests as they are not used in this project."""
    for item in items:
        if "[trio]" in item.nodeid:
            item.add_marker(pytest.mark.skip(reason="Trio backend is not used in this project."))
