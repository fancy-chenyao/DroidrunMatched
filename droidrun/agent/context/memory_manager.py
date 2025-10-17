from __future__ import annotations

import time
from typing import Dict, Any, List, Optional

from .experience_storage import ExperienceStorage


class TaskMemoryManager:
    """
    Minimal task memory manager that
    - saves successful executions as reusable experiences
    - retrieves similar experiences for hot start
    """

    def __init__(self, storage: Optional[ExperienceStorage] = None) -> None:
        self.storage = storage or ExperienceStorage()

    def save_experience(
        self,
        goal: str,
        page_sequence: List[Dict[str, Any]],
        action_sequence: List[Dict[str, Any]],
        success: bool,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        exp = {
            "goal": goal,
            "success": bool(success),
            "timestamp": time.time(),
            "page_sequence": page_sequence,
            "action_sequence": action_sequence,
            "metadata": metadata or {},
        }
        return self.storage.save(exp)

    def find_similar(self, goal: str, threshold: float = 0.9) -> List[Dict[str, Any]]:
        return self.storage.find_by_goal_similarity(goal, threshold=threshold)


