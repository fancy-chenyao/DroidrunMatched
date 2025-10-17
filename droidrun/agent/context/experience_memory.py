"""
经验记忆系统 - 核心记忆管理模块
负责经验的存储、检索、匹配和适配
"""
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import json
import os
import re
import uuid
import logging

logger = logging.getLogger("droidrun")

@dataclass
class TaskExperience:
    """任务经验数据结构"""
    id: str
    goal: str
    success: bool
    timestamp: float
    page_sequence: List[Dict[str, Any]]
    action_sequence: List[Dict[str, Any]]
    ui_states: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    similarity_score: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskExperience':
        """从字典创建对象"""
        # 兼容旧格式的经验文件
        if 'id' not in data:
            data['id'] = str(uuid.uuid4())
        if 'ui_states' not in data:
            data['ui_states'] = []
        if 'similarity_score' not in data:
            data['similarity_score'] = None
        return cls(**data)

class ExperienceMemory:
    """经验记忆管理器"""
    
    def __init__(self, storage_dir: str = "experiences", llm=None):
        self.storage_dir = storage_dir
        self.llm = llm
        self.experiences: List[TaskExperience] = []
        self._ensure_storage_dir()
        self._load_experiences()
        logger.info(f"🧠 ExperienceMemory initialized with {len(self.experiences)} experiences")
    
    def _ensure_storage_dir(self):
        """确保存储目录存在"""
        os.makedirs(self.storage_dir, exist_ok=True)
    
    def _load_experiences(self):
        """从存储目录加载所有经验"""
        self.experiences = []
        if not os.path.exists(self.storage_dir):
            return
        
        for filename in os.listdir(self.storage_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.storage_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        experience = TaskExperience.from_dict(data)
                        self.experiences.append(experience)
                except Exception as e:
                    logger.warning(f"Failed to load experience from {filename}: {e}")
    
    def find_similar_experiences(self, goal: str, threshold: float = 0.8) -> List[TaskExperience]:
        """查找相似经验 - 使用LLM进行语义匹配"""
        if not self.llm:
            logger.warning("No LLM provided for similarity matching")
            return []
        
        similar_experiences = []
        
        for experience in self.experiences:
            try:
                similarity = self._calculate_similarity(goal, experience.goal)
                # 记录每条经验的相似度与阈值比较
                try:
                    logger.info(f"[SIM][calc] similarity={similarity:.2f} threshold={threshold:.2f} goal={experience.goal}")
                except Exception:
                    pass
                if similarity >= threshold:
                    experience.similarity_score = similarity
                    similar_experiences.append(experience)
                else:
                    try:
                        logger.info(f"[SIM][drop] similarity={similarity:.2f} < threshold={threshold:.2f} goal={experience.goal}")
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Failed to calculate similarity for experience {experience.id}: {e}")
        
        # 按相似度排序
        similar_experiences.sort(key=lambda x: x.similarity_score or 0, reverse=True)
        logger.info(f"Found {len(similar_experiences)} similar experiences for goal: {goal}")
        return similar_experiences
    
    def _calculate_similarity(self, goal1: str, goal2: str) -> float:
        """使用LLM计算语义相似度"""
        if not self.llm:
            # 如果没有LLM，使用简单的文本相似度
            return self._simple_text_similarity(goal1, goal2)
        
        try:
            prompt = f"""
请计算以下两个任务描述的语义相似度，返回0-1之间的数值：

任务1: {goal1}
任务2: {goal2}

请只返回一个0-1之间的数字，表示相似度分数：
"""
            response = self.llm.complete(prompt)
            similarity_text = response.text.strip()
            
            # 尝试提取数字

            numbers = re.findall(r'0\.\d+|1\.0|0|1', similarity_text)
            if numbers:
                similarity = float(numbers[0])
                return max(0.0, min(1.0, similarity))  # 确保在0-1范围内
            else:
                logger.warning(f"Could not parse similarity score from: {similarity_text}")
                return self._simple_text_similarity(goal1, goal2)
                
        except Exception as e:
            logger.warning(f"LLM similarity calculation failed: {e}")
            return self._simple_text_similarity(goal1, goal2)
    
    def _simple_text_similarity(self, goal1: str, goal2: str) -> float:
        """简单的文本相似度计算（Jaccard相似度）"""
        words1 = set(goal1.lower().split())
        words2 = set(goal2.lower().split())
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0
    
    def save_experience(self, experience: TaskExperience) -> str:
        """保存经验到存储"""
        try:
            # 生成文件名
            safe_goal = "".join(c if c.isalnum() or c in "._-" else "_" for c in experience.goal)
            filename = f"{safe_goal}_{int(experience.timestamp)}.json"
            filepath = os.path.join(self.storage_dir, filename)
            
            # 保存到文件
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(experience.to_dict(), f, indent=2, ensure_ascii=False)
            
            # 添加到内存列表
            self.experiences.append(experience)
            
            logger.info(f"💾 Experience saved: {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"Failed to save experience: {e}")
            raise
    
    def adapt_parameters(self, experience: TaskExperience, new_goal: str) -> List[Dict]:
        """参数自适应 - 使用LLM调整动作序列"""
        if not self.llm:
            logger.warning("No LLM provided for parameter adaptation")
            return experience.action_sequence
        
        try:
            prompt = f"""
基于以下历史经验，为新的目标任务调整动作序列：

历史经验目标: {experience.goal}
历史动作序列: {json.dumps(experience.action_sequence, ensure_ascii=False, indent=2)}

新目标: {new_goal}

请分析新目标与历史目标的差异，并返回调整后的动作序列。
返回格式应该是JSON数组，每个动作包含action和params字段。

调整后的动作序列：
"""
            response = self.llm.complete(prompt)
            
            # 尝试解析JSON响应
            json_match = re.search(r'\[.*\]', response.text, re.DOTALL)
            if json_match:
                adapted_actions = json.loads(json_match.group())
                # 保留/回填 description 字段，保证下游 changed_indices 检测可用
                try:
                    original_actions = experience.action_sequence or []
                    for i, a in enumerate(adapted_actions or []):
                        if isinstance(a, dict) and "description" not in a:
                            if 0 <= i < len(original_actions):
                                desc = (original_actions[i] or {}).get("description")
                                if desc:
                                    a["description"] = desc
                except Exception:
                    pass
                logger.info(f"🔄 Parameters adapted for new goal: {new_goal}")
                return adapted_actions
            else:
                logger.warning("Could not parse adapted actions from LLM response")
                return experience.action_sequence
                
        except Exception as e:
            logger.warning(f"Parameter adaptation failed: {e}")
            return experience.action_sequence
    
    def get_experience_by_id(self, experience_id: str) -> Optional[TaskExperience]:
        """根据ID获取经验"""
        for exp in self.experiences:
            if exp.id == experience_id:
                return exp
        return None
    
    def get_all_experiences(self) -> List[TaskExperience]:
        """获取所有经验"""
        return self.experiences.copy()
    
    def clear_experiences(self):
        """清空所有经验"""
        self.experiences = []
        # 清空存储目录
        if os.path.exists(self.storage_dir):
            for filename in os.listdir(self.storage_dir):
                if filename.endswith('.json'):
                    os.remove(os.path.join(self.storage_dir, filename))
        logger.info("🧹 All experiences cleared")

