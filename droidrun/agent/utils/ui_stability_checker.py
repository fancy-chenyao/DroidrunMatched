"""
UI 稳定性检测工具

用于动态等待 UI 稳定，避免固定延迟的时间浪费和不确定性
"""
import asyncio
import time
from typing import Dict, Any, Optional
from droidrun.agent.utils.logging_utils import LoggingUtils


class UIStabilityChecker:
    """UI 稳定性检测器"""
    
    def __init__(self, tools_instance):
        """
        初始化 UI 稳定性检测器
        
        Args:
            tools_instance: Tools 实例（WebSocketTools 或 AdbTools）
        """
        self.tools = tools_instance
        self.last_ui_hash = None
        
    def _calculate_ui_hash(self, ui_state: Dict[str, Any]) -> str:
        """
        计算 UI 状态的哈希值，用于判断 UI 是否发生变化
        
        Args:
            ui_state: UI 状态字典
            
        Returns:
            UI 状态的简化哈希字符串
        """
        try:
            a11y_tree = ui_state.get('a11y_tree', [])
            if not a11y_tree:
                return ""
            
            # 提取关键信息：元素数量、类型、文本
            elements_info = []
            for elem in a11y_tree[:50]:  # 只检查前50个元素，避免性能问题
                elem_info = (
                    elem.get('className', ''),
                    elem.get('text', ''),
                    elem.get('resourceId', ''),
                    elem.get('clickable', False)
                )
                elements_info.append(elem_info)
            
            # 简单哈希：转换为字符串
            return str(hash(str(elements_info)))
        except Exception as e:
            LoggingUtils.log_warning("UIStabilityChecker", "Failed to calculate UI hash: {error}", error=str(e))
            return ""
    
    async def wait_for_ui_stable(
        self, 
        action_type: str,
        max_wait: float = 3.0,
        check_interval: float = 0.1,
        stable_duration: float = 0.3
    ) -> bool:
        """
        动态等待 UI 稳定
        
        策略：
        1. 每隔 check_interval 秒检查一次 UI 状态
        2. 连续 stable_duration 秒内 UI 无变化，认为稳定
        3. 最多等待 max_wait 秒
        
        Args:
            action_type: 动作类型（用于日志）
            max_wait: 最大等待时间（秒）
            check_interval: 检查间隔（秒）
            stable_duration: 稳定判定时长（秒）
            
        Returns:
            True: UI 已稳定，False: 超时
        """
        start_time = time.time()
        last_stable_time = None
        stable_hash = None
        check_count = 0
        
        LoggingUtils.log_debug("UIStabilityChecker", 
            "⏳ Waiting for UI to stabilize after {action} (max {max}s)...", 
            action=action_type, max=max_wait)
        
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
                    last_stable_time = time.time()
                    await asyncio.sleep(check_interval)
                    continue
                
                # UI 发生变化
                if current_hash != stable_hash:
                    LoggingUtils.log_debug("UIStabilityChecker", 
                        "🔄 UI changed (check #{count}), resetting stability timer", 
                        count=check_count)
                    stable_hash = current_hash
                    last_stable_time = time.time()
                    await asyncio.sleep(check_interval)
                    continue
                
                # UI 未变化，检查是否已稳定足够时长
                if time.time() - last_stable_time >= stable_duration:
                    elapsed = time.time() - start_time
                    LoggingUtils.log_success("UIStabilityChecker", 
                        "✅ UI stable after {elapsed:.2f}s ({count} checks)", 
                        elapsed=elapsed, count=check_count)
                    return True
                
                # 继续等待
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                LoggingUtils.log_warning("UIStabilityChecker", 
                    "⚠️ Error checking UI stability: {error}", error=str(e))
                await asyncio.sleep(check_interval)
        
        # 超时
        elapsed = time.time() - start_time
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
        
        # 根据动作类型设置最大等待时间
        max_wait_map = {
            'tap': 2.0,
            'input': 1.5,
            'swipe': 2.0,
            'start_app': 4.0,
            'press_key': 1.5,
        }
        max_wait = max_wait_map.get(action_type, 2.0)
        
        # 尝试动态等待
        is_stable = await self.wait_for_ui_stable(
            action_type=action_type,
            max_wait=max_wait,
            check_interval=0.1,
            stable_duration=0.3
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
