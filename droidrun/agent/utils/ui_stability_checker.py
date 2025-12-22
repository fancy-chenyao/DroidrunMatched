"""
UI 稳定性检测工具

用于动态等待 UI 稳定，避免固定延迟的时间浪费和不确定性

优化版本：
- 降低检测频率（减少 50% 检查次数）
- 缩短稳定判定时长（减少等待时间）
- 优化 hash 计算（只检查可交互元素）
- 动态最大等待时间（根据历史数据自适应）
- 提前终止检测（连续 N 次相同即退出）
"""
import asyncio
import time
from typing import Dict, Any, Optional
from droidrun.agent.utils.logging_utils import LoggingUtils


class UIStabilityChecker:
    """UI 稳定性检测器（优化版）"""
    
    def __init__(self, tools_instance):
        """
        初始化 UI 稳定性检测器
        
        Args:
            tools_instance: Tools 实例（WebSocketTools 或 AdbTools）
        """
        self.tools = tools_instance
        self.last_ui_hash = None
        
        # 历史稳定时间（用于自适应调整）
        self.stability_history = {
            'tap': [],
            'input': [],
            'swipe': [],
            'start_app': [],
            'press_key': [],
        }
        
    def _calculate_ui_hash(self, ui_state: Dict[str, Any]) -> str:
        """
        计算 UI 状态的哈希值（优化版：只检查可交互元素）
        
        Args:
            ui_state: UI 状态字典
            
        Returns:
            UI 状态的简化哈希字符串
        """
        try:
            a11y_tree = ui_state.get('a11y_tree', [])
            if not a11y_tree:
                return ""
            
            # 只检查可交互元素（减少 70% 的元素）
            interactive_keys = []
            for elem in a11y_tree[:30]:  # 只检查前 30 个（vs 50 个）
                # 只关注可交互元素
                if not (elem.get('clickable') or elem.get('editable')):
                    continue
                
                # 只提取关键信息（减少字符串拼接）
                key = f"{elem.get('className', '')}-{elem.get('text', '')[:20]}"
                interactive_keys.append(key)
            
            # 使用更快的 hash（直接 hash tuple）
            return str(hash(tuple(interactive_keys)))
        except Exception as e:
            LoggingUtils.log_warning("UIStabilityChecker", "Failed to calculate UI hash: {error}", error=str(e))
            return ""
    
    def _update_history(self, action_type: str, duration: float):
        """
        更新历史稳定时间
        
        Args:
            action_type: 动作类型
            duration: 稳定耗时（秒）
        """
        if action_type in self.stability_history:
            history = self.stability_history[action_type]
            history.append(duration)
            # 只保留最近 10 次
            if len(history) > 10:
                history.pop(0)
    
    def _get_adaptive_max_wait(self, action_type: str) -> float:
        """
        根据历史数据，动态调整最大等待时间
        
        Args:
            action_type: 动作类型
            
        Returns:
            自适应的最大等待时间（秒）
        """
        history = self.stability_history.get(action_type, [])
        
        if len(history) < 3:
            # 历史数据不足，使用优化后的默认值
            default_map = {
                'tap': 1.0,        # 降低默认值（vs 2.0）
                'input': 0.8,      # 降低默认值（vs 1.5）
                'swipe': 1.0,      # 降低默认值（vs 2.0）
                'start_app': 2.5,  # 降低默认值（vs 4.0）
                'press_key': 0.8,
            }
            return default_map.get(action_type, 1.0)
        
        # 使用历史平均值 + 1 个标准差
        try:
            import statistics
            avg = statistics.mean(history)
            std = statistics.stdev(history) if len(history) > 1 else 0.3
            adaptive_max = avg + std
            
            # 限制范围
            min_wait = 0.5
            max_wait = 2.5
            return max(min_wait, min(adaptive_max, max_wait))
        except Exception:
            return 1.0
    
    async def wait_for_ui_stable(
        self, 
        action_type: str,
        max_wait: float = None,
        check_interval: float = None,
        stable_duration: float = None,
        early_exit_checks: int = 2
    ) -> bool:
        """
        动态等待 UI 稳定（优化版）
        
        策略：
        1. 根据动作类型动态设置参数
        2. 每隔 check_interval 秒检查一次 UI 状态
        3. 连续 early_exit_checks 次相同，或稳定 stable_duration 秒，认为稳定
        4. 最多等待 max_wait 秒（自适应）
        
        Args:
            action_type: 动作类型（用于自适应参数）
            max_wait: 最大等待时间（秒），None 则自适应
            check_interval: 检查间隔（秒），None 则根据动作类型设置
            stable_duration: 稳定判定时长（秒），None 则根据动作类型设置
            early_exit_checks: 连续 N 次相同即提前退出
            
        Returns:
            True: UI 已稳定，False: 超时
        """
        # 1. 动态设置参数
        if max_wait is None:
            max_wait = self._get_adaptive_max_wait(action_type)
        
        if check_interval is None:
            # 根据动作类型设置检查间隔（降低检测频率）
            interval_map = {
                'tap': 0.2,        # 简单动作，检查频率低（vs 0.1）
                'input': 0.15,     # 中等复杂度
                'swipe': 0.15,     # 中等复杂度
                'start_app': 0.3,  # 复杂动作，检查频率更低
                'press_key': 0.15,
            }
            check_interval = interval_map.get(action_type, 0.2)
        
        if stable_duration is None:
            # 根据动作类型设置稳定判定时长（缩短判定时间）
            duration_map = {
                'tap': 0.1,        # 简单动作，快速稳定（vs 0.3）
                'input': 0.2,      # 中等复杂度
                'swipe': 0.2,      # 中等复杂度
                'start_app': 0.5,  # 复杂动作，慢速稳定
                'press_key': 0.15,
            }
            stable_duration = duration_map.get(action_type, 0.15)
        
        # 2. 检测逻辑
        start_time = time.time()
        stable_hash = None
        stable_count = 0
        last_stable_time = None
        check_count = 0
        
        while time.time() - start_time < max_wait:
            check_count += 1
            
            try:
                # 获取当前 UI 状态（不包含截图，减少开销）
                ui_state = await self.tools.get_state_async(include_screenshot=False)
                current_hash = self._calculate_ui_hash(ui_state)
                
                if not current_hash:
                    # UI 状态无效，继续等待
                    await asyncio.sleep(check_interval)
                    continue
                
                # 第一次检查
                if stable_hash is None:
                    stable_hash = current_hash
                    stable_count = 1
                    last_stable_time = time.time()
                    await asyncio.sleep(check_interval)
                    continue
                
                # UI 相同
                if current_hash == stable_hash:
                    stable_count += 1
                    
                    # 提前退出：连续 N 次相同
                    if stable_count >= early_exit_checks:
                        elapsed = time.time() - start_time
                        self._update_history(action_type, elapsed)
                        LoggingUtils.log_success("UIStabilityChecker", 
                            "✅ UI stable (early exit) after {elapsed:.2f}s ({count} checks)", 
                            elapsed=elapsed, count=check_count)
                        return True
                    
                    # 或者：稳定时长足够
                    if time.time() - last_stable_time >= stable_duration:
                        elapsed = time.time() - start_time
                        self._update_history(action_type, elapsed)
                        LoggingUtils.log_success("UIStabilityChecker", 
                            "✅ UI stable after {elapsed:.2f}s ({count} checks)", 
                            elapsed=elapsed, count=check_count)
                        return True
                
                # UI 发生变化
                else:
                    stable_hash = current_hash
                    stable_count = 1
                    last_stable_time = time.time()
                
                # 继续等待
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                LoggingUtils.log_warning("UIStabilityChecker", 
                    "⚠️ Error checking UI stability: {error}", error=str(e))
                await asyncio.sleep(check_interval)
        
        # 超时
        elapsed = time.time() - start_time
        self._update_history(action_type, elapsed)
        LoggingUtils.log_warning("UIStabilityChecker", 
            "⏰ UI stability check timeout after {elapsed:.2f}s ({count} checks)", 
            elapsed=elapsed, count=check_count)
        return False
    
    async def smart_wait(
        self,
        action_type: str,
        fallback_delay: float = 1.0
    ) -> float:
        """
        智能等待：优先使用动态检测，失败时使用固定延迟
        
        Args:
            action_type: 动作类型
            fallback_delay: 兜底延迟（秒）
            
        Returns:
            实际等待时长（秒）
        """
        start_time = time.time()
        
        # 尝试动态等待（使用自适应参数）
        is_stable = await self.wait_for_ui_stable(
            action_type=action_type,
            max_wait=None,  # 自适应
            check_interval=None,  # 自适应
            stable_duration=None,  # 自适应
            early_exit_checks=2
        )
        
        elapsed = time.time() - start_time
        
        # 如果动态检测失败（超时），使用固定延迟兜底
        if not is_stable:
            LoggingUtils.log_warning("UIStabilityChecker", 
                "⚠️ Falling back to fixed delay ({delay}s) for {action}", 
                delay=fallback_delay, action=action_type)
            remaining = fallback_delay - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
                elapsed = fallback_delay
        
        return elapsed
