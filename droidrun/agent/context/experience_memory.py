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
import time
from droidrun.agent.utils.logging_utils import LoggingUtils

logger = logging.getLogger("droidrun")

@dataclass
class TaskExperience:
    """任务经验数据结构"""
    id: str
    goal: str
    type: Optional[str]
    success: bool
    timestamp: float
    page_sequence: List[Dict[str, Any]]
    action_sequence: List[Dict[str, Any]]
    ui_states: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    similarity_score: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = asdict(self)
        
        # 修复BUG：确保字段名正确，防止出现空字符串键
        if '' in result:
            LoggingUtils.log_warning("TaskExperience", "Detected empty string key in experience dict, fixing...")
            # 将空字符串键的值移动到 action_sequence
            result['action_sequence'] = result.pop('')
        
        # 确保所有必需字段存在
        required_fields = ['id', 'goal', 'type', 'success', 'timestamp', 'page_sequence', 'action_sequence', 'ui_states', 'metadata']
        for field in required_fields:
            if field not in result:
                LoggingUtils.log_warning("TaskExperience", f"Missing required field: {field}")
        
        return result
    
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
        # self.experiences: List[TaskExperience] = []
        self.type_experience_cache: Dict[str, List[TaskExperience]] = {}
        self.supported_types = ["请休假", "员工差旅"]
        self._ensure_storage_dirs()
        self._load_type_experiences()
        # LoggingUtils.log_info("ExperienceMemory", "ExperienceMemory initialized with {count} experiences", count=len(self.experiences))
    
    def _ensure_storage_dir(self):
        """确保存储目录存在"""
        os.makedirs(self.storage_dir, exist_ok=True)

    def _ensure_storage_dirs(self):
        """确保存储目录存在"""
        os.makedirs(self.storage_dir, exist_ok=True)

        for type_name in self.supported_types:
            # 处理特殊字符（避免文件夹命名非法）
            safe_type_name = re.sub(r'[<>:"/\\|?*]', '_', type_name)
            type_dir = os.path.join(self.storage_dir, safe_type_name)
            os.makedirs(type_dir, exist_ok=True)

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
                    LoggingUtils.log_warning("ExperienceMemory", "Failed to load experience from {filename}: {error}",
                                            filename=filename, error=e)

    def _load_type_experiences(self):
        """预加载所有类型文件夹下的经验，按类型缓存到 type_experience_cache"""
        # 遍历根目录下的所有子文件夹（即 task_type 文件夹）
        if not os.path.exists(self.storage_dir):
            return

        for type_dir in os.listdir(self.storage_dir):
            type_dir_path = os.path.join(self.storage_dir, type_dir)
            if not os.path.isdir(type_dir_path):
                continue  # 跳过非文件夹

            task_type = type_dir

            # 加载该文件夹下的所有经验
            experiences = []
            for filename in os.listdir(type_dir_path):
                if filename.endswith('.json'):
                    filepath = os.path.join(type_dir_path, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            exp = TaskExperience.from_dict(data)
                            experiences.append(exp)
                    except Exception as e:
                        LoggingUtils.log_warning("ExperienceMemory", f"Failed to load {filename}: {e}")

            # 缓存该类型的经验
            self.type_experience_cache[task_type] = experiences
            LoggingUtils.log_info("ExperienceMemory", f"Preloaded {len(experiences)} experiences for type: {task_type}")

    def find_similar_experiences(self, goal: str, threshold: float = 0.8) -> List[TaskExperience]:
        """查找相似经验 - 使用LLM进行语义匹配"""
        if not self.llm:
            LoggingUtils.log_warning("ExperienceMemory", "No LLM provided for similarity matching")
            return []
        
        similar_experiences = []
        
        for experience in self.experiences:
            try:
                similarity = self._calculate_similarity(goal, experience.goal)
                print("experience goal:", experience.goal)
                print("similarity:", similarity)
                # 记录每条经验的相似度与阈值比较
                try:
                    LoggingUtils.log_debug("ExperienceMemory", "Similarity calculation: {similarity:.2f} threshold={threshold:.2f} goal={goal}", 
                                         similarity=similarity, threshold=threshold, goal=experience.goal)
                except Exception:
                    pass
                if similarity >= threshold:
                    experience.similarity_score = similarity
                    similar_experiences.append(experience)
                else:
                    try:
                        LoggingUtils.log_debug("ExperienceMemory", "Similarity below threshold: {similarity:.2f} < {threshold:.2f} goal={goal}", 
                                             similarity=similarity, threshold=threshold, goal=experience.goal)
                    except Exception:
                        pass
            except Exception as e:
                LoggingUtils.log_warning("ExperienceMemory", "Failed to calculate similarity for experience {exp_id}: {error}", 
                                        exp_id=experience.id, error=e)
        
        # 按相似度排序
        similar_experiences.sort(key=lambda x: x.similarity_score or 0, reverse=True)
        LoggingUtils.log_info("ExperienceMemory", "Found {count} similar experiences for goal: {goal}", 
                             count=len(similar_experiences), goal=goal)
        return similar_experiences
    
    def _calculate_similarity(self, goal1: str, goal2: str) -> float:
        """使用LLM计算语义相似度"""
        if not self.llm:
            # 如果没有LLM，使用简单的文本相似度
            return self._simple_text_similarity(goal1, goal2)
        
        try:
            prompt = f"""
            请判断以下两个任务是否为“相似任务”，并返回0-1之间的相似度分数（1表示完全相同，0表示完全无关）。

            判断标准：
1. 核心目标是否一致：最终要达成的结果是否相同（如“发送消息”和“提交信息”目标不同；“发送消息”和“发送一条文本”目标一致）；
2. 关键对象是否一致：任务操作的核心实体是否相同（如“给张三发消息”和“给李四发消息”的关键对象都是“消息”，一致；“发消息”和“传文件”的关键对象不同）；
3. 核心操作是否一致：完成任务的核心动作是否相同（如“发送消息”和“提交消息”的核心操作都是“发送/提交”，一致；“删除消息”和“转发消息”操作不同）。

忽略参数差异（如“给张三发消息”和“给李四发消息”仅参数不同，视为高相似度），也忽略表面表达差异（如同义词、句式变化）。

            任务1: {goal1}
            任务2: {goal2}

            请只返回一个0-1之间的数字（保留2位小数），例如0.95、1.00、0.30：
            """
            response = self.llm.complete(prompt)
            similarity_text = response.text.strip()
            
            # 尝试提取数字

            numbers = re.findall(r'0\.\d+|1\.0|0|1', similarity_text)
            if numbers:
                similarity = float(numbers[0])
                return max(0.0, min(1.0, similarity))  # 确保在0-1范围内
            else:
                LoggingUtils.log_warning("ExperienceMemory", "Could not parse similarity score from: {text}", 
                                        text=similarity_text)
                return self._simple_text_similarity(goal1, goal2)
                
        except Exception as e:
            LoggingUtils.log_warning("ExperienceMemory", "LLM similarity calculation failed: {error}", error=e)
            return self._simple_text_similarity(goal1, goal2)

    def batch_find_similar_experiences(self, goal: str, task_type: str, threshold: float = 0.8) -> List[TaskExperience]:
        """查找相似经验 - 使用LLM进行语义匹配"""
        if not self.llm:
            LoggingUtils.log_warning("ExperienceMemory", "No LLM provided for batch similarity matching")
            return []

        # 改成经验按照功能存在不同文件夹，直接调用
        type_experiences = self.type_experience_cache.get(task_type)

        # 实时遍历所有经验，筛选出类型匹配的经验.
        # type_experiences = [
        #     exp for exp in self.experiences
        #     if hasattr(exp, 'type') and exp.type == task_type  # 检查经验是否有type属性，且与任务类型一致
        # ]
        if not type_experiences:
            LoggingUtils.log_info("ExperienceMemory", f"No experiences found for type: {task_type}")
            return []  #返回空列表，后续直接冷启动

        # 记录相似度计算与排序开始时间
        llm_start_time = time.time()
        start_timestamp = time.strftime("%H:%M:%S", time.localtime())
        LoggingUtils.log_info(
                "ExperienceMemory",
                f"🤔 开始相似度计算与排序 at {start_timestamp}"
        )

        type_experiences_goals = [exp.goal for exp in type_experiences]
        similarity_scores = self._batch_calculate_similarity(goal, type_experiences_goals)

        similar_experiences = []

        # all_experiences_goals = [exp.goal for exp in self.experiences]
        # similarity_scores = self._batch_calculate_similarity(goal, all_experiences_goals)

        for i, experience in enumerate(type_experiences):
            try:
                similarity = similarity_scores[i]
                # 记录相似度日志
                try:
                    LoggingUtils.log_debug("ExperienceMemory",
                                       "Similarity calculation: {similarity:.2f} threshold={threshold:.2f} goal={goal}",
                                       similarity=similarity, threshold=threshold, goal=experience.goal)
                except Exception:
                    pass
                if similarity >= threshold:
                    experience.similarity_score = similarity
                    similar_experiences.append(experience)
                else:
                    try:
                        LoggingUtils.log_debug("ExperienceMemory",
                                               "Similarity below threshold: {similarity:.2f} < {threshold:.2f} goal={goal}",
                                               similarity=similarity, threshold=threshold, goal=experience.goal)
                    except Exception:
                        pass
            except Exception as e:
                LoggingUtils.log_warning("ExperienceMemory", "Failed to process experience {exp_id}: {error}",
                                         exp_id=experience.id, error=e)
        # 按相似度排序
        similar_experiences.sort(key=lambda x: x.similarity_score or 0, reverse=True)
        LoggingUtils.log_info("ExperienceMemory", "Found {count} similar experiences for goal: {goal}",
                                      count=len(similar_experiences), goal=goal)

        # 计算并记录相似度计算与排序耗时
        thinking_time = time.time() - llm_start_time
        end_timestamp = time.strftime("%H:%M:%S", time.localtime())
        LoggingUtils.log_info(
            "ExperienceMemory",
            f"💡 完成相似度计算与排序 at {end_timestamp}, 耗时: {thinking_time:.2f}s"
        )

        return similar_experiences

    def _batch_calculate_similarity(self, goal:str, experience_goals:List[str])-> List[float]:
        """批量计算目标与所有经验的相似度"""
        if not self.llm:
            return [self._simple_text_similarity(goal, exp_goal) for exp_goal in experience_goals]
        try:
            batch_prompt = f"""
            请判断以下目标与每条经验是否为“相似任务”，并为每条经验返回0-1之间的相似度分数（1表示完全相同，0表示完全无关）。
            
            判断标准：
1. 核心目标是否一致：最终要达成的结果是否相同（如“发送消息”和“提交信息”目标不同；“发送消息”和“发送一条文本”目标一致）；
2. 关键对象是否一致：任务操作的核心实体是否相同（如“给张三发消息”和“给李四发消息”的关键对象都是“消息”，一致；“发消息”和“传文件”的关键对象不同）；
3. 核心操作是否一致：完成任务的核心动作是否相同（如“发送消息”和“提交消息”的核心操作都是“发送/提交”，一致；“删除消息”和“转发消息”操作不同）；
4. 信息维度是否一致：任务所包含的信息维度是否相同，若一方存在另一方没有的独立信息维度（非参数值差异、非表述简化），则视为覆盖范围不一致，信息维度完全匹配的，视为一致。（如目标包含 “拟前往地区” ，经验任务无此信息，那信息维度不一致）。

忽略参数差异（如“给张三发消息”和“给李四发消息”仅参数不同，视为高相似度），也忽略表面表达差异（如同义词、句式变化）。

            目标任务: {goal}

请为以下每条经验返回相似度分数（保留2位小数），格式为“经验X: 分数”（例如“经验1: 0.95”）：
            
            """
            for i, exp_goal in enumerate(experience_goals, 1):
                batch_prompt += f"经验{i}: {exp_goal}\n"
            batch_prompt += "\n请严格按照上述格式返回，不要添加额外解释，确保分数与经验顺序一一对应。"

            response = self.llm.complete(batch_prompt)
            similarity_text = response.text.strip()

            scores = []
            for line in similarity_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                match = re.match(r'经验\d+:\s*(\d+\.\d+|\d+)', line)
                if match:
                    try:
                        score = float(match.group(1))
                        scores.append(max(0.0, min(1.0, score)))
                    except ValueError:
                        scores.append(0.0)
            while len(scores) < len(experience_goals):
                scores.append(0.0)
            return scores[:len(experience_goals)]
        except Exception as e:
            LoggingUtils.log_warning("ExperienceMemory", "Batch LLM calculation failed, fallback to single calls",
                                     error=e)
            # 批量失败时，降级为逐条计算（保证功能可用）
            return [self._calculate_similarity(goal, exp_goal) for exp_goal in experience_goals]

    def find_and_rank_similar_experiences(self, goal: str, task_type: str, threshold: float = 0.8) -> List[TaskExperience]:
        """
        合并优化：一次LLM调用同时完成相似度计算和排序

        Args:
            goal: 目标任务
            threshold: 相似度阈值

        Returns:
            按相似度排序的经验列表（已过滤低于阈值的）
        """
        if not self.llm:
            LoggingUtils.log_warning("ExperienceMemory", "No LLM provided for similarity matching")
            return []

        # 经验按照类型存在不同文件夹，直接调用对应类型的经验
        type_experiences = self.type_experience_cache.get(task_type)

        if not type_experiences:
            return []

        try:
            # 记录LLM思考开始时间
            llm_start_time = time.time()
            start_timestamp = time.strftime("%H:%M:%S", time.localtime())
            LoggingUtils.log_info(
                "ExperienceMemory",
                f"🤔 LLM 开始相似度计算与排序 at {start_timestamp}"
            )

            # 构建合并的提示词：同时计算相似度和排序
            prompt = f"""
请判断目标任务与以下每条历史经验的相似度，并按相似度从高到低排序。

判断标准：
1. 核心目标是否一致：最终要达成的结果是否相同
2. 关键对象是否一致：任务操作的核心实体是否相同
3. 核心操作是否一致：完成任务的核心动作是否相同

忽略参数差异和表面表达差异。

目标任务: {goal}

历史经验列表：
"""
            for i, exp in enumerate(type_experiences, 1):
                prompt += f"{i}. {exp.goal}\n"

            prompt += f"""
请返回JSON格式的结果，包含每条经验的相似度分数和排序：
{{
    "ranked_experiences": [
        {{"index": 1, "similarity": 0.95, "reason": "简短理由"}},
        {{"index": 3, "similarity": 0.85, "reason": "简短理由"}},
        ...
    ]
}}

要求：
1. 只返回相似度 >= {threshold} 的经验
2. 按相似度从高到低排序
3. index 是历史经验列表中的序号（1-{len(type_experiences)}）
4. similarity 是 0-1 之间的分数（保留2位小数）
5. reason 控制在15字以内
"""

            LoggingUtils.log_info("ExperienceMemory",
                                "🚀 Merged LLM call: calculating similarity and ranking for {count} experiences",
                                count=len(type_experiences))

            response = self.llm.complete(prompt)
            response_text = response.text.strip()

            # 解析JSON响应
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                LoggingUtils.log_warning("ExperienceMemory", "Could not parse JSON from merged response, fallback to batch method")
                return self.batch_find_similar_experiences(goal, task_type, threshold)

            result = json.loads(json_match.group())
            ranked_list = result.get("ranked_experiences", [])

            # 构建结果列表
            similar_experiences = []
            for item in ranked_list:
                idx = item.get("index", 0) - 1  # 转换为0-based索引
                similarity = item.get("similarity", 0.0)
                reason = item.get("reason", "")

                if 0 <= idx < len(type_experiences) and similarity >= threshold:
                    exp = type_experiences[idx]
                    exp.similarity_score = similarity
                    similar_experiences.append(exp)
                    LoggingUtils.log_debug("ExperienceMemory",
                                         "✓ Matched: {goal} (similarity={score:.2f}, reason={reason})",
                                         goal=exp.goal, score=similarity, reason=reason)

            LoggingUtils.log_success("ExperienceMemory",
                                   "✅ Merged call completed: found {count} similar experiences in 1 LLM call (saved {saved} calls)",
                                   count=len(similar_experiences),
                                   saved=len(type_experiences))
            # 计算并记录LLM思考耗时
            thinking_time = time.time() - llm_start_time
            end_timestamp = time.strftime("%H:%M:%S", time.localtime())
            LoggingUtils.log_info(
                "ExperienceMemory",
                f"💡 LLM 完成相似度计算与排序 at {end_timestamp}, 耗时: {thinking_time:.2f}s"
            )
            return similar_experiences

        except Exception as e:
            LoggingUtils.log_warning("ExperienceMemory",
                                   "Merged LLM call failed: {error}, fallback to batch method",
                                   error=e)
            return self.batch_find_similar_experiences(goal, task_type, threshold)

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
            task_type = experience.type
            # 处理特殊字符，确保文件夹名称合法
            safe_type_name = re.sub(r'[<>:"/\\|?*]', '_', task_type)
            # 构建类型子文件夹路径
            type_dir = os.path.join(self.storage_dir, safe_type_name)
            os.makedirs(type_dir, exist_ok=True)

            # 生成文件名
            safe_goal = "".join(c if c.isalnum() or c in "._-" else "_" for c in experience.goal)
            filename = f"{safe_goal}_{int(experience.timestamp)}.json"
            filepath = os.path.join(type_dir, filename)
            
            # 保存到文件
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(experience.to_dict(), f, indent=2, ensure_ascii=False)
            
            # 添加到内存列表
            # self.experiences.append(experience)
            self.type_experience_cache[task_type].append(experience)

            LoggingUtils.log_success("ExperienceMemory", "Experience saved: {path}", path=filepath)
            return filepath
            
        except Exception as e:
            LoggingUtils.log_error("ExperienceMemory", "Failed to save experience: {error}", error=e)
            raise
    
    def adapt_parameters(self, experience: TaskExperience, new_goal: str) -> List[Dict]:
        """参数自适应 - 使用LLM调整动作序列"""
        if not self.llm:
            LoggingUtils.log_warning("ExperienceMemory", "No LLM provided for parameter adaptation")
            return experience.action_sequence
        
        try:
            prompt = f"""
基于以下历史经验，为新的目标任务调整动作序列：

历史经验目标: {experience.goal}
历史动作序列: {json.dumps(experience.action_sequence, ensure_ascii=False, indent=2)}

新目标: {new_goal}

**重要约束**：
1. 只修改动作的参数值（如日期、文本内容、索引等）
2. 必须保持动作的顺序完全不变
3. 特别注意：确认按钮、提交按钮、页面跳转等流程控制动作必须保留
4. 如果某个动作的参数不需要修改，保持原值不变

请分析新目标与历史目标的差异，并返回调整后的动作序列。
返回格式应该是JSON数组，每个动作包含action和params字段。

调整后的动作序列：
"""
            response = self.llm.complete(prompt)
            
            # 尝试解析JSON响应
            json_match = re.search(r'\[.*\]', response.text, re.DOTALL)
            if json_match:
                adapted_actions = json.loads(json_match.group())
                # 保留/回填 description 和 specific_behavior 字段，保证下游 changed_indices 检测可用
                try:
                    original_actions = experience.action_sequence or []
                    for i, a in enumerate(adapted_actions or []):
                        if isinstance(a, dict):
                            if 0 <= i < len(original_actions):
                                # 回填 description
                                if "description" not in a:
                                    desc = (original_actions[i] or {}).get("description")
                                    if desc:
                                        a["description"] = desc
                                # 回填 specific_behavior
                                if "specific_behavior" not in a:
                                    specific_behavior = (original_actions[i] or {}).get("specific_behavior")
                                    if specific_behavior is not None:  # 允许 None 值
                                        a["specific_behavior"] = specific_behavior
                except Exception:
                    pass
                LoggingUtils.log_progress("ExperienceMemory", "Parameters adapted for new goal: {goal}", goal=new_goal)
                return adapted_actions
            else:
                LoggingUtils.log_warning("ExperienceMemory", "Could not parse adapted actions from LLM response")
                return experience.action_sequence
                
        except Exception as e:
            LoggingUtils.log_warning("ExperienceMemory", "Parameter adaptation failed: {error}", error=e)
            return experience.action_sequence
    
    def get_experience_by_id(self, experience_id: str) -> Optional[TaskExperience]:
        """根据ID获取经验"""
        # for exp in self.experiences:
        #     if exp.id == experience_id:
        #         return exp
        # return None
        for experiences in self.type_experience_cache.values():  # 遍历所有类型的经验列表
            for exp in experiences:
                if exp.id == experience_id:  # 匹配唯一ID
                    return exp
        return None  # 未找到时返回None

    def get_all_experiences(self) -> List[TaskExperience]:
        """获取所有经验"""
        # return self.experiences.copy()
        all_experiences = []
        # 遍历所有类型的缓存，汇总所有经验
        for experiences in self.type_experience_cache.values():
            all_experiences.extend(experiences)
        return all_experiences.copy()  # 返回副本，避免外部修改缓存

    def clear_experiences(self):
        """清空所有经验"""
        # self.experiences = []
        # # 清空存储目录
        # if os.path.exists(self.storage_dir):
        #     for filename in os.listdir(self.storage_dir):
        #         if filename.endswith('.json'):
        #             os.remove(os.path.join(self.storage_dir, filename))
        # logger.info("🧹 All experiences cleared")
        # 清空缓存
        self.type_experience_cache.clear()
        # 清空存储目录
        if os.path.exists(self.storage_dir):
            for root, dirs, files in os.walk(self.storage_dir):
                for filename in files:
                    if filename.endswith('.json'):
                        os.remove(os.path.join(root, filename))
        LoggingUtils.log_info("ExperienceMemory", "🧹 All experiences (files + cache) cleared")

    def determine_task_type(self, goal: str) -> Optional[str]:
        """用大模型判断任务类型，必须属于支持的类型清单"""
        # 记录 LLM 思考开始时间
        llm_start_time = time.time()
        start_timestamp = time.strftime("%H:%M:%S", time.localtime())
        LoggingUtils.log_info(
            "ExperienceMemory",
            f"🤔 LLM 开始思考判断任务类型 at {start_timestamp} "
        )

        try:
            # 构建类型判断提示词   # 这里需要对接一下
            prompt = f"""
请判断以下任务属于哪种功能类型（只能从给定的类型清单中选择，若都不符合则返回"未知"）。

支持的类型清单：{self.supported_types}  

任务：{goal}

请只返回类型名称（如"请休假"），不要添加任何解释。若不属于任何类型，返回"未知"。
"""
            response = self.llm.complete(prompt)
            task_type = response.text.strip()

            # 计算并记录 LLM 思考耗时
            thinking_time = time.time() - llm_start_time
            end_timestamp = time.strftime("%H:%M:%S", time.localtime())
            LoggingUtils.log_info(
                "ExperienceMemory",
                f"💡 LLM 完成思考判断任务类型 at {end_timestamp}, 耗时: {thinking_time:.2f}s"
            )

            # 校验返回的类型是否在支持的清单内
            if task_type in self.supported_types:
                LoggingUtils.log_info("ExperienceMemory", f"Task type '{task_type}'")
                return task_type
            else:
                LoggingUtils.log_info("ExperienceMemory", f"Task type '{task_type}' not in supported list")
                return None
        except Exception as e:
            LoggingUtils.log_error("ExperienceMemory", f"Failed to determine task type: {e}")
            return None