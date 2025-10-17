import os
import json
import time
from typing import Dict, List, Any, Optional


class ExperienceStorage:
    """
    Lightweight JSON-file based storage for task experiences.

    - Stores one JSON file per experience under a base directory
    - Provides simple retrieval and similarity search by goal
    """

    def __init__(self, base_dir: str = "experiences") -> None:
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _safe_filename(self, name: str) -> str:
        keep = [c if c.isalnum() or c in ("-", "_") else "_" for c in name.strip()]
        cleaned = "".join(keep)
        return cleaned[:64] if cleaned else str(int(time.time()))

    def save(self, experience: Dict[str, Any]) -> str:
        """
        Save a single experience JSON and return its path.
        Required keys in experience: goal, success, timestamp
        """
        goal = experience.get("goal", "experience")
        ts = int(experience.get("timestamp", time.time()))
        fname = f"{self._safe_filename(goal)}_{ts}.json"
        fpath = os.path.join(self.base_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(experience, f, ensure_ascii=False, indent=2)
        return fpath

    def list_all(self) -> List[str]:
        return [
            os.path.join(self.base_dir, p)
            for p in os.listdir(self.base_dir)
            if p.endswith(".json")
        ]

    def load(self, path: str) -> Optional[Dict[str, Any]]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return [t for t in (text or "").lower().replace("\n", " ").split() if t]

    @staticmethod
    def _jaccard(a: List[str], b: List[str]) -> float:
        sa, sb = set(a), set(b)
        if not sa and not sb:
            return 1.0
        if not sa or not sb:
            return 0.0
        inter = len(sa.intersection(sb))
        union = len(sa.union(sb))
        return inter / union if union else 0.0

    def find_by_goal_similarity(self, goal: str, threshold: float = 0.9) -> List[Dict[str, Any]]:
        """
        Simple similarity search over goals using Jaccard on whitespace tokens.
        Returns list of matching experiences (dicts) sorted by similarity desc.
        """
        target_tokens = self._tokenize(goal)
        results: List[Dict[str, Any]] = []
        for path in self.list_all():
            obj = self.load(path)
            if not obj:
                continue
            sim = self._jaccard(target_tokens, self._tokenize(obj.get("goal", "")))
            if sim >= threshold:
                obj["_similarity"] = sim
                obj["_path"] = path
                results.append(obj)
        results.sort(key=lambda x: x.get("_similarity", 0.0), reverse=True)
        return results



