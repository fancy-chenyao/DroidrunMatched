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
    
    def __init__(self, device_id: str, websocket, protocol: str = "json"):
        self.device_id = device_id
        self.websocket = websocket
        self.connected_at = datetime.now()
        self.last_heartbeat = datetime.now()
        self.is_active = True
        self.protocol = protocol or "json"
        
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
        # 出站发送相关：每设备一个发送队列与单发送协程，控制背压
        self._sender_tasks: Dict[str, asyncio.Task] = {}
        self._send_queue_max = 200
        # 记录入队时间用于排查阻塞（按 request_id）
        self._enqueue_ts: Dict[str, float] = {}
        LoggingUtils.log_info("SessionManager", "SessionManager initialized (heartbeat_timeout={timeout}s)", 
                             timeout=heartbeat_timeout)
    
    async def register_session(self, device_id: str, websocket, protocol: str = "json") -> bool:
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
            
            session = DeviceSession(device_id, websocket, protocol=protocol)
            # 为会话创建发送队列
            try:
                session.out_queue = asyncio.Queue(maxsize=self._send_queue_max)
            except Exception:
                session.out_queue = asyncio.Queue()
            self.sessions[device_id] = session
            LoggingUtils.log_info("SessionManager", "Device {device_id} registered (total sessions: {count})", 
                                device_id=device_id, count=len(self.sessions))
            # 启动发送协程
            try:
                task = asyncio.create_task(self._sender_loop(device_id))
                self._sender_tasks[device_id] = task
            except Exception as e:
                LoggingUtils.log_error("SessionManager", "Failed to start sender task for {device_id}: {error}", 
                                     device_id=device_id, error=e)
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
                # 停止发送任务
                task = self._sender_tasks.pop(device_id, None)
                if task:
                    try:
                        task.cancel()
                    except Exception:
                        pass
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
            # 入队，实施背压（满则丢弃最旧一条并告警）
            q = getattr(session, "out_queue", None)
            if q is None:
                # 兼容：若无队列，直接按旧逻辑发送一次
                import json
                await session.websocket.send(json.dumps(message))
                return True
            try:
                # 记录入队
                try:
                    rid = message.get("request_id") if isinstance(message, dict) else None
                    if rid:
                        self._enqueue_ts[rid] = time.time()
                except Exception:
                    pass
                q.put_nowait(message)
                try:
                    mtype = message.get("type") if isinstance(message, dict) else None
                    LoggingUtils.log_debug("SessionManager", "Enqueued message type={mtype}, request_id={rid}, qsize={qsize}",
                                           mtype=mtype, rid=rid, qsize=getattr(q, "qsize", lambda: -1)())
                except Exception:
                    pass
                return True
            except asyncio.QueueFull:
                try:
                    _ = q.get_nowait()
                    q.put_nowait(message)
                    LoggingUtils.log_warning("SessionManager", "Send queue full for device {device_id}, dropped oldest", 
                                           device_id=device_id)
                    return True
                except Exception as ex:
                    LoggingUtils.log_error("SessionManager", "Failed to enqueue message for {device_id}: {error}", 
                                          device_id=device_id, error=ex)
                    return False
        except Exception as e:
            LoggingUtils.log_error("SessionManager", "Failed to send message to device {device_id}: {error}", 
                                 device_id=device_id, error=e)
            await self.unregister_session(device_id)
            return False

    async def _sender_loop(self, device_id: str):
        """单连接发送协程：串行从队列读取并发送，避免乱序与并发阻塞"""
        try:
            while True:
                # 获取会话与队列
                async with self._lock:
                    session = self.sessions.get(device_id)
                if not session or not getattr(session, "is_active", False):
                    await asyncio.sleep(0.05)
                    continue
                q = getattr(session, "out_queue", None)
                if q is None:
                    await asyncio.sleep(0.05)
                    continue
                message = await q.get()
                try:
                    # 发送前记录延迟
                    try:
                        rid = message.get("request_id") if isinstance(message, dict) else None
                        mtype = message.get("type") if isinstance(message, dict) else None
                        t_enq = self._enqueue_ts.pop(rid, None) if rid else None
                        if t_enq is not None:
                            delay_ms = int((time.time() - t_enq) * 1000)
                            LoggingUtils.log_info("SessionManager", "Dequeued for send type={mtype}, request_id={rid}, enqueue_delay_ms={d}",
                                                  mtype=mtype, rid=rid, d=delay_ms)
                        else:
                            LoggingUtils.log_info("SessionManager", "Dequeued for send type={mtype}, request_id={rid}",
                                                  mtype=mtype, rid=rid)
                    except Exception:
                        pass
                    # Decide encoding by session protocol (rollout guarded)
                    protocol = getattr(session, "protocol", "json")
                    send_bin_enabled = False  # 与上游保持一致，先关闭二进制下行
                    if send_bin_enabled and protocol == "bin_v1":
                        try:
                            import msgpack  # type: ignore
                            payload = msgpack.packb(message, use_bin_type=True)
                            await session.websocket.send(payload)
                            continue
                        except Exception:
                            pass
                    import json
                    await session.websocket.send(json.dumps(message))
                    try:
                        LoggingUtils.log_debug("SessionManager", "Sent message type={mtype}, request_id={rid}", mtype=mtype, rid=rid)
                    except Exception:
                        pass
                except Exception as e:
                    LoggingUtils.log_error("SessionManager", "Sender loop failed to send to {device_id}: {error}", 
                                         device_id=device_id, error=e)
                    # 发送失败，尝试注销会话以触发上层清理
                    try:
                        await self.unregister_session(device_id)
                    except Exception:
                        pass
        except asyncio.CancelledError:
            # 任务被取消，正常退出
            return
    
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
                # 停止对应发送任务
                task = self._sender_tasks.pop(device_id, None)
                if task:
                    try:
                        task.cancel()
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












