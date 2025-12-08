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
        # 事件循环健康监控任务
        self._watchdog_task: Optional[asyncio.Task] = None
        # 启动事件循环看门狗（仅日志用途）
        try:
            self._watchdog_task = asyncio.create_task(self._event_loop_watchdog())
        except Exception:
            pass
    
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
            # 为会话创建发送队列（使用优先级队列）
            try:
                # 使用 PriorityQueue: (priority, counter, message)
                # priority: 0=command/command_response (最高), 1=task_response (中), 2=heartbeat (低)
                import queue
                session.out_queue = asyncio.PriorityQueue(maxsize=self._send_queue_max)
                session._msg_counter = 0  # 用于保证相同优先级的消息按入队顺序发送
            except Exception:
                session.out_queue = asyncio.Queue()
            self.sessions[device_id] = session
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
            t_enqueue_start = time.time()
            # 入队，实施背压（满则丢弃最旧一条并告警）
            q = getattr(session, "out_queue", None)
            if q is None:
                # 兼容：若无队列，直接按旧逻辑发送一次
                import json
                await session.websocket.send(json.dumps(message))
                return True
            try:
                # 根据消息类型确定优先级
                priority = self._get_message_priority(message)
                
                # 使用计数器保证相同优先级的消息按顺序发送
                counter = getattr(session, "_msg_counter", 0)
                session._msg_counter = counter + 1
                
                # 入队: (priority, counter, message)
                q.put_nowait((priority, counter, message))
                return True
            except asyncio.QueueFull:
                try:
                    # 队列满时，丢弃最旧的低优先级消息
                    _ = q.get_nowait()
                    
                    # 重新入队当前消息
                    priority = self._get_message_priority(message)
                    
                    counter = getattr(session, "_msg_counter", 0)
                    session._msg_counter = counter + 1
                    q.put_nowait((priority, counter, message))
                    
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
            # 记录上一次出队时间，用于判断事件循环是否出现长时间停顿
            last_dequeue_ts = time.time()
            while True:
                # 获取会话与队列（避免在热路径上获取全局锁，降低锁竞争风险）
                session = self.sessions.get(device_id)
                if not session or not getattr(session, "is_active", False):
                    # 会话不活跃时，短暂等待后重试，避免CPU占用过高
                    await asyncio.sleep(0.001)  # 1毫秒，而不是50毫秒
                    continue
                q = getattr(session, "out_queue", None)
                if q is None:
                    # 队列不存在时，短暂等待后重试
                    await asyncio.sleep(0.001)  # 1毫秒，而不是50毫秒
                    continue
                
                # 使用超时等待，避免无限期阻塞
                try:
                    item = await asyncio.wait_for(q.get(), timeout=0.1)  # 100毫秒超时
                except asyncio.TimeoutError:
                    # 队列为空时继续循环，不阻塞
                    continue
                # 从优先级队列中提取消息
                if isinstance(item, tuple) and len(item) == 3:
                    priority, counter, message = item
                else:
                    # 兼容旧格式
                    message = item
                    priority = 2
                
                try:
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
                    # 记录从出队到调度发送前的准备耗时
                    t_prep_start = time.time()
                    send_start = time.time()
                    
                    # 使用 create_task 实现非阻塞发送，避免大消息阻塞队列
                    async def send_async():
                        try:
                            # 将序列化放入发送任务内，避免阻塞出队主循环
                            import json
                            message_str = json.dumps(message)
                            message_size = len(message_str)
                            
                            # 获取消息信息
                            mtype = message.get("type") if isinstance(message, dict) else None
                            rid = message.get("request_id") if isinstance(message, dict) else None
                            
                            await session.websocket.send(message_str)
                            send_duration = int((time.time() - send_start) * 1000)
                        except Exception as e:
                            LoggingUtils.log_error("SessionManager", "Failed to send message: {error}", error=e)
                    
                    # 创建发送任务并等待完成，确保消息及时发送
                    await send_async()
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

    async def _event_loop_watchdog(self):
        """事件循环看门狗：周期性检测 sleep 漂移，辅助定位全局阻塞源（仅日志用途）。"""
        try:
            interval = 0.2
            loop = asyncio.get_running_loop()
            last = loop.time()
            while True:
                await asyncio.sleep(interval)
                now = loop.time()
                drift = (now - last) - interval
                last = now
                drift_ms = int(drift * 1000)
                if drift_ms > 1000:
                    try:
                        # 汇总活跃会话与各队列长度，帮助判断是队列积压还是纯事件循环阻塞
                        active = self.get_active_devices()
                        qstats = []
                        for did in list(active):
                            sess = self.sessions.get(did)
                            if not sess:
                                continue
                            q = getattr(sess, "out_queue", None)
                            qsize = getattr(q, "qsize", lambda: -1)() if q else -1
                            qstats.append(f"{did}:{qsize}")
                        qstat_str = ",".join(qstats[:8])  # 避免过长日志
                        LoggingUtils.log_info("SessionManager", "EventLoop stall detected | drift_ms={d} | active={n} | qsizes=[{qs}]",
                                              d=drift_ms, n=len(active), qs=qstat_str)
                    except Exception:
                        pass
        except asyncio.CancelledError:
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
            
            # 同时清理过期的入队时间记录
            self._cleanup_old_enqueue_timestamps()
    
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
    
    def _get_message_priority(self, message: dict) -> int:
        """获取消息优先级"""
        mtype = message.get("type") if isinstance(message, dict) else None
        if mtype in ["command", "command_response"]:
            return 0  # 最高优先级
        elif mtype in ["task_response", "user_question"]:
            return 1  # 中等优先级（用户问题需要及时显示）
        else:
            return 2  # 低优先级（包括heartbeat_ack）
    
    def _cleanup_old_enqueue_timestamps(self):
        """清理过期的入队时间记录，防止内存泄漏"""
        try:
            current_time = time.time()
            # 清理超过5分钟的记录
            expired_keys = [
                rid for rid, timestamp in self._enqueue_ts.items()
                if current_time - timestamp > 300
            ]
            for rid in expired_keys:
                self._enqueue_ts.pop(rid, None)
        except Exception as e:
            LoggingUtils.log_error("SessionManager", "Error cleaning up enqueue timestamps: {error}", error=e)