"""
会话管理器 - 管理设备与 WebSocket 连接的映射关系
"""
import asyncio
import time
from typing import Dict, Optional, Set
from datetime import datetime, timedelta
from droidrun.agent.utils.logging_utils import LoggingUtils


class DeviceSession:
    """设备会话信息"""
    
    def __init__(self, device_id: str, websocket):
        self.device_id = device_id
        self.websocket = websocket
        self.connected_at = datetime.now()
        self.last_heartbeat = datetime.now()
        self.is_active = True
        
    def update_heartbeat(self):
        """更新心跳时间"""
        self.last_heartbeat = datetime.now()
    
    def is_timeout(self, timeout_seconds: int = 60) -> bool:
        """检查是否超时"""
        if not self.is_active:
            return True
        elapsed = (datetime.now() - self.last_heartbeat).total_seconds()
        return elapsed > timeout_seconds


class SessionManager:
    """会话管理器 - 管理多个设备的 WebSocket 连接"""
    
    def __init__(self, heartbeat_timeout: int = 60):
        """
        初始化会话管理器
        
        Args:
            heartbeat_timeout: 心跳超时时间（秒）
        """
        self.sessions: Dict[str, DeviceSession] = {}
        self.heartbeat_timeout = heartbeat_timeout
        self._lock = asyncio.Lock()
        LoggingUtils.log_info("SessionManager", "SessionManager initialized (heartbeat_timeout={timeout}s)", 
                             timeout=heartbeat_timeout)
    
    async def register_session(self, device_id: str, websocket) -> bool:
        """
        注册设备会话
        
        Args:
            device_id: 设备ID
            websocket: WebSocket 连接对象
            
        Returns:
            bool: 注册是否成功
        """
        async with self._lock:
            # 如果设备已存在，先关闭旧连接
            if device_id in self.sessions:
                old_session = self.sessions[device_id]
                if old_session.is_active:
                    LoggingUtils.log_warning("SessionManager", "Device {device_id} already connected, closing old session", 
                                           device_id=device_id)
                    try:
                        await old_session.websocket.close()
                    except Exception:
                        pass
            
            session = DeviceSession(device_id, websocket)
            self.sessions[device_id] = session
            LoggingUtils.log_info("SessionManager", "Device {device_id} registered (total sessions: {count})", 
                                device_id=device_id, count=len(self.sessions))
            return True
    
    async def unregister_session(self, device_id: str):
        """
        注销设备会话
        
        Args:
            device_id: 设备ID
        """
        async with self._lock:
            if device_id in self.sessions:
                session = self.sessions[device_id]
                session.is_active = False
                del self.sessions[device_id]
                LoggingUtils.log_info("SessionManager", "Device {device_id} unregistered (remaining sessions: {count})", 
                                    device_id=device_id, count=len(self.sessions))
    
    async def get_session(self, device_id: str) -> Optional[DeviceSession]:
        """
        获取设备会话
        
        Args:
            device_id: 设备ID
            
        Returns:
            DeviceSession 或 None
        """
        async with self._lock:
            session = self.sessions.get(device_id)
            if session and session.is_active:
                return session
            return None
    
    async def send_to_device(self, device_id: str, message: dict) -> bool:
        """
        向指定设备发送消息
        
        Args:
            device_id: 设备ID
            message: 消息字典
            
        Returns:
            bool: 发送是否成功
        """
        session = await self.get_session(device_id)
        if not session:
            LoggingUtils.log_warning("SessionManager", "Device {device_id} not found or inactive", device_id=device_id)
            return False
        
        try:
            import json
            await session.websocket.send(json.dumps(message))
            return True
        except Exception as e:
            LoggingUtils.log_error("SessionManager", "Failed to send message to device {device_id}: {error}", 
                                 device_id=device_id, error=e)
            await self.unregister_session(device_id)
            return False
    
    async def update_heartbeat(self, device_id: str):
        """
        更新设备心跳
        
        Args:
            device_id: 设备ID
        """
        session = await self.get_session(device_id)
        if session:
            session.update_heartbeat()
    
    async def cleanup_timeout_sessions(self):
        """清理超时的会话"""
        async with self._lock:
            timeout_devices = []
            for device_id, session in self.sessions.items():
                if session.is_timeout(self.heartbeat_timeout):
                    timeout_devices.append(device_id)
            
            for device_id in timeout_devices:
                LoggingUtils.log_warning("SessionManager", "Device {device_id} timeout, removing session", 
                                       device_id=device_id)
                session = self.sessions[device_id]
                session.is_active = False
                try:
                    await session.websocket.close()
                except Exception:
                    pass
                del self.sessions[device_id]
            
            if timeout_devices:
                LoggingUtils.log_info("SessionManager", "Cleaned up {count} timeout sessions", count=len(timeout_devices))
    
    def get_active_devices(self) -> Set[str]:
        """
        获取所有活跃的设备ID
        
        Returns:
            Set[str]: 活跃设备ID集合
        """
        return {device_id for device_id, session in self.sessions.items() if session.is_active}
    
    def get_session_count(self) -> int:
        """获取当前会话数量"""
        return len([s for s in self.sessions.values() if s.is_active])

