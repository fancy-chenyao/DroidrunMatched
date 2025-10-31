"""
通信与会话抽象（com.py）

该模块抽象了原 test/server.py 与 test/session_manager.py 的通信能力与多会话管理能力，
提供通用的服务端与客户端工具，便于在独立脚本中进行 APP 连接与消息交互测试。

注意：本模块仅依赖标准库，默认实现了旧格式消息（首字节类型 I/X/S/A/E/G）与
简化版 JSON 格式消息的接收逻辑，发送动作使用 JSON 格式。
"""

import socket
import threading
import time
import json
import uuid
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timedelta


# -------------------------------
# 基础工具与常量
# -------------------------------

class Message_types:
    """消息类型常量集中定义。

    说明:
    - 将原先分散在代码中的 `messageType` 取值统一收敛为类变量，避免魔法字符串；
    - 仅包含消息体字段 `messageType` 的值，不包含动作 `action.type` 的取值；
    - 保持与现有协议一致，值均为字符串，替换后不影响兼容性。
    """

    instruction = "instruction"
    xml = "xml"
    screenshot = "screenshot"
    qa = "qa"
    error = "error"
    get_actions = "get_actions"
    action = "action"




def log(msg: str, role: Optional[str] = None):
    """简单日志输出函数，支持角色前缀。

    参数:
        msg: 消息文本
        role: 角色标识（可选），如 "server" 或 "client"，用于明确日志来源。
    """
    prefix = f"[com] " + (f"[{role}] " if role else "")
    print(f"{prefix}{msg}")


# -------------------------------
# 会话数据结构与管理
# -------------------------------

@dataclass
class ClientSession:
    """客户端会话数据结构。

    字段:
        session_id: 会话唯一ID
        client_socket: 客户端套接字
        client_address: 客户端地址元组
        created_at: 创建时间
        last_activity: 最后活动时间
        is_active: 会话是否有效
        screen_count: 会话级截图计数
        prebuffer: 预缓冲（在业务未就绪时暂存收到的数据）
    """

    session_id: str
    client_socket: Any
    client_address: tuple
    created_at: datetime
    last_activity: datetime
    is_active: bool = True
    screen_count: int = 0
    prebuffer: Optional[dict] = None

    def update_activity(self) -> None:
        """更新最后活动时间与初始化预缓冲。"""
        self.last_activity = datetime.now()
        if self.prebuffer is None:
            self.prebuffer = {"xmls": [], "shots": []}

    def is_expired(self, timeout_minutes: int = 30) -> bool:
        """判断会话是否过期。

        参数:
            timeout_minutes: 过期时间阈值（分钟）
        返回:
            bool: 是否过期
        """
        if not self.is_active:
            return True
        return datetime.now() - self.last_activity > timedelta(minutes=timeout_minutes)

    def close(self) -> None:
        """关闭会话套接字。"""
        try:
            if self.client_socket:
                self.client_socket.close()
        except Exception:
            pass


class SessionManager:
    """会话管理器（简化版单例）。"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例创建逻辑。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化会话存储与清理线程。"""
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self.sessions: Dict[str, ClientSession] = {}
        self.session_locks: Dict[str, threading.RLock] = {}
        self.running = True
        self.cleanup_thread = threading.Thread(target=self._cleanup_worker, daemon=True)
        self.cleanup_thread.start()
        log("会话清理线程已启动", role="server")

    def create_session(self, client_socket: Any, client_address: tuple) -> ClientSession:
        """创建一个新的客户端会话。

        参数:
            client_socket: 客户端套接字
            client_address: 客户端地址
        返回:
            ClientSession: 新会话对象
        """
        session_id = str(uuid.uuid4())
        lock = threading.RLock()
        self.session_locks[session_id] = lock
        session = ClientSession(
            session_id=session_id,
            client_socket=client_socket,
            client_address=client_address,
            created_at=datetime.now(),
            last_activity=datetime.now(),
        )
        with lock:
            self.sessions[session_id] = session
            log(f"创建新会话: {session_id} from {client_address}", role="server")
        return session

    def get_session(self, session_id: str) -> Optional[ClientSession]:
        """获取指定会话，过期则移除。"""
        session = self.sessions.get(session_id)
        if not session:
            return None
        if session.is_expired():
            self.remove_session(session_id)
            return None
        session.update_activity()
        return session

    def get_session_by_socket(self, client_socket: Any) -> Optional[ClientSession]:
        """通过套接字查找会话。"""
        for s in list(self.sessions.values()):
            if s.client_socket == client_socket:
                if s.is_expired():
                    self.remove_session(s.session_id)
                    return None
                s.update_activity()
                return s
        return None

    def remove_session(self, session_id: str) -> bool:
        """移除会话并释放资源。"""
        if session_id not in self.sessions:
            return False
        lock = self.session_locks.get(session_id, threading.RLock())
        with lock:
            session = self.sessions.pop(session_id, None)
            self.session_locks.pop(session_id, None)
            if session:
                try:
                    session.close()
                except Exception:
                    pass
                log(f"移除会话: {session_id}", role="server")
        return True

    def get_active_sessions(self) -> Dict[str, ClientSession]:
        """获取当前活跃会话字典，并清理过期会话。"""
        active: Dict[str, ClientSession] = {}
        expired = []
        for sid, s in list(self.sessions.items()):
            if s.is_expired():
                expired.append(sid)
            else:
                active[sid] = s
        for sid in expired:
            self.remove_session(sid)
        return active

    def shutdown(self) -> None:
        """关闭会话管理器并清理所有会话。"""
        self.running = False
        for sid in list(self.sessions.keys()):
            self.remove_session(sid)
        log("会话管理器已关闭", role="server")

    def _cleanup_worker(self) -> None:
        """后台清理线程，定期移除过期会话。"""
        while self.running:
            try:
                time.sleep(300)
                expired = []
                for sid, s in list(self.sessions.items()):
                    if s.is_expired():
                        expired.append(sid)
                for sid in expired:
                    self.remove_session(sid)
                if expired:
                    log(f"清理过期会话数量: {len(expired)}", role="server")
            except Exception as e:
                log(f"清理线程异常: {e}", role="server")


# -------------------------------
# 通信服务端
# -------------------------------

class ComServer:
    """通用通信服务端，支持多会话与消息分发。"""

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None, buffer_size: int = 4096) -> None:
        """初始化服务端。

        参数:
            host: 绑定主机地址，默认从本机网络获取
            port: 绑定端口，默认 6666
            buffer_size: 接收缓冲区大小
        """
        self.host = host or "0.0.0.0"
        self.port = port or 6666
        self.buffer_size = buffer_size
        self.session_manager = SessionManager()
        self._server_socket: Optional[socket.socket] = None
        self._running = False

    # 消息预处理逻辑（只处理并返回消息，不执行动作）
    def _handle_instruction(self, session: ClientSession, message: dict) -> dict:
        """预处理指令消息。
        
        参数:
            session: 客户端会话
            message: 原始消息
        返回:
            dict: 预处理后的消息，包含处理结果
        """
        text = message.get("instruction", "")
        log(f"[预处理] 收到指令: {text}", role="server")
        return {
            "messageType": Message_types.instruction,
            "original": message,
            "processed": {
                "instruction_text": text,
                "session_id": session.session_id
            }
        }

    def _handle_xml(self, session: ClientSession, message: dict) -> dict:
        """预处理 XML 消息。
        
        参数:
            session: 客户端会话
            message: 原始消息
        返回:
            dict: 预处理后的消息，包含处理结果
        """
        xml_text = message.get("xml", "")
        log(f"[预处理] 收到 XML（长度={len(xml_text)}）", role="server")
        return {
            "messageType": Message_types.xml,
            "original": message,
            "processed": {
                "xml_content": xml_text,
                "xml_length": len(xml_text),
                "session_id": session.session_id
            }
        }

    def _handle_screenshot(self, session: ClientSession, message: dict) -> dict:
        """预处理截图消息。
        
        参数:
            session: 客户端会话
            message: 原始消息
        返回:
            dict: 预处理后的消息，包含处理结果
        """
        content = message.get("screenshot", b"")
        log(f"[预处理] 收到截图（长度={len(content)}）", role="server")
        return {
            "messageType": Message_types.screenshot,
            "original": message,
            "processed": {
                "screenshot_data": content,
                "screenshot_length": len(content),
                "session_id": session.session_id
            }
        }

    def _handle_qa(self, session: ClientSession, message: dict) -> dict:
        """预处理 QA 消息。
        
        参数:
            session: 客户端会话
            message: 原始消息
        返回:
            dict: 预处理后的消息，包含处理结果
        """
        qa_text = message.get("qa", "")
        log(f"[预处理] 收到 QA: {qa_text}", role="server")
        return {
            "messageType": Message_types.qa,
            "original": message,
            "processed": {
                "qa_text": qa_text,
                "session_id": session.session_id
            }
        }

    def _handle_error(self, session: ClientSession, message: dict) -> dict:
        """预处理错误消息。
        
        参数:
            session: 客户端会话
            message: 原始消息
        返回:
            dict: 预处理后的消息，包含处理结果
        """
        err_text = message.get("error", "")
        log(f"[预处理] 收到错误: {err_text}", role="server")
        return {
            "messageType": Message_types.error,
            "original": message,
            "processed": {
                "error_text": err_text,
                "session_id": session.session_id
            }
        }

    def _handle_get_actions(self, session: ClientSession, message: dict) -> dict:
        """预处理获取动作请求。
        
        参数:
            session: 客户端会话
            message: 原始消息
        返回:
            dict: 预处理后的消息，包含处理结果
        """
        log("[预处理] 收到 get_actions 请求", role="server")
        return {
            "messageType": Message_types.get_actions,
            "original": message,
            "processed": {
                "request_type": Message_types.get_actions,
                "session_id": session.session_id
            }
        }

    def start(self) -> None:
        """启动服务端，绑定并开始监听连接。"""
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen()
        self._running = True

        real_ip = self._detect_real_ip()
        log("--------------------------------------------------------", role="server")
        log(f"Server listening on {real_ip}:{self.port}，请在 APP 中输入该 IP", role="server")

        threading.Thread(target=self._accept_loop, name="com-accept", daemon=True).start()

    def stop(self) -> None:
        """停止服务端并关闭所有资源。"""
        self._running = False
        try:
            if self._server_socket:
                self._server_socket.close()
        except Exception:
            pass
        self.session_manager.shutdown()

    def send_action(self, session: ClientSession, action: dict) -> None:
        """向指定会话发送动作（JSON格式）。

        参数:
            session: 会话对象
            action: 动作字典，如 {"type": "tap", "x": 100, "y": 200}
        """
        payload = {"messageType": Message_types.action, "action": action}
        self._send_json(session.client_socket, payload)

    # 内部方法
    def _accept_loop(self) -> None:
        """连接接收循环，针对每个客户端创建会话与处理线程。"""
        assert self._server_socket is not None
        while self._running:
            try:
                client_socket, client_address = self._server_socket.accept()
                session = self.session_manager.create_session(client_socket, client_address)
                t = threading.Thread(target=self._handle_client, args=(session,), name=f"com-client-{session.session_id}")
                t.start()
            except Exception as e:
                # 在正常关闭过程中，关闭套接字会导致 accept 抛出异常，属预期行为，忽略日志。
                if self._running:
                    log(f"accept 异常: {e}", role="server")
                else:
                    break

    def _handle_client(self, session: ClientSession) -> None:
        """处理单个客户端连接的消息循环。"""
        log(f"处理客户端会话: {session.session_id} from {session.client_address}", role="server")
        client_file = None
        try:
            client_file = session.client_socket.makefile("rb")
            while self._running:
                message = self._receive_message(client_file)
                if not message:
                    log("客户端断开连接", role="server")
                    break
                session.update_activity()
                # 获取预处理后的消息
                processed_message = self._dispatch_message(session, message)
                if processed_message:
                    # 调用消息处理完成后的回调（子类可覆写）
                    self._on_message_processed(session, processed_message)
        except Exception as e:
            # 在正常关闭过程中，读循环可能抛出异常，属预期行为，忽略日志。
            if self._running:
                log(f"处理客户端异常: {e}", role="server")
        finally:
            try:
                if client_file:
                    client_file.close()
            except Exception:
                pass
            self.session_manager.remove_session(session.session_id)

    def _on_message_processed(self, session: ClientSession, processed_message: dict) -> None:
        """消息预处理完成后的回调（基类默认实现，子类可覆写）。
        
        参数:
            session: 客户端会话
            processed_message: 预处理后的消息
        """
        # 基类默认不执行任何动作，仅记录日志
        mtype = processed_message.get("messageType", "")
        log(f"[基类] 消息预处理完成: {mtype}", role="server")

    def _dispatch_message(self, session: ClientSession, message: dict) -> Optional[dict]:
        """根据 messageType 分发到预处理逻辑并返回处理后的消息。
        
        参数:
            session: 客户端会话
            message: 原始消息
        返回:
            Optional[dict]: 预处理后的消息，如果处理失败则返回 None
        """
        mtype = message.get("messageType", "")
        log(f"收到消息类型: {mtype} 会话={session.session_id}", role="server")
        try:
            if mtype == Message_types.instruction:
                return self._handle_instruction(session, message)
            elif mtype == Message_types.xml:
                return self._handle_xml(session, message)
            elif mtype == Message_types.screenshot:
                return self._handle_screenshot(session, message)
            elif mtype == Message_types.qa:
                return self._handle_qa(session, message)
            elif mtype == Message_types.error:
                return self._handle_error(session, message)
            elif mtype == Message_types.get_actions:
                return self._handle_get_actions(session, message)
            else:
                log(f"未知消息类型: {mtype}", role="server")
                return None
        except Exception as e:
            log(f"预处理异常[{mtype}]: {e}", role="server")
            return None

    def _receive_message(self, client_file) -> Optional[dict]:
        """接收消息：支持旧格式与简化 JSON 格式。"""
        try:
            type_byte = client_file.read(1)
            if not type_byte:
                return None
            type_char = type_byte.decode()
            if type_char in ["I", "X", "S", "A", "E", "G"]:
                return self._receive_legacy_message(client_file, type_char)
            else:
                return self._receive_json_message(client_file, type_char)
        except Exception as e:
            log(f"接收消息异常: {e}", role="server")
            return None

    def _receive_legacy_message(self, client_file, type_char: str) -> Optional[dict]:
        """接收旧格式消息。"""
        try:
            if type_char == "I":
                line = client_file.readline()
                if not line:
                    return None
                return {"messageType": Message_types.instruction, "instruction": line.decode().strip()}
            elif type_char == "X":
                length_line = client_file.readline()
                if not length_line:
                    return None
                length = int(length_line.decode().strip())
                xml_bytes = client_file.read(length)
                if len(xml_bytes) != length:
                    return None
                return {"messageType": Message_types.xml, "xml": xml_bytes.decode("utf-8")}
            elif type_char == "S":
                length_line = client_file.readline()
                if not length_line:
                    return None
                length = int(length_line.decode().strip())
                shot_bytes = client_file.read(length)
                if len(shot_bytes) != length:
                    return None
                return {"messageType": Message_types.screenshot, "screenshot": shot_bytes}
            elif type_char == "A":
                qa_line = client_file.readline()
                if not qa_line:
                    return None
                return {"messageType": Message_types.qa, "qa": qa_line.decode().strip()}
            elif type_char == "E":
                length_line = client_file.readline()
                if not length_line:
                    return None
                length = int(length_line.decode().strip())
                err_bytes = client_file.read(length)
                if len(err_bytes) != length:
                    return None
                return {"messageType": Message_types.error, "error": err_bytes.decode("utf-8")}
            elif type_char == "G":
                return {"messageType": Message_types.get_actions}
            else:
                return None
        except Exception as e:
            log(f"解析旧格式异常: {e}", role="server")
            return None

    def _receive_json_message(self, client_file, type_char: str) -> Optional[dict]:
        """接收简化版 JSON 格式消息：首字节为占位，后跟长度与 JSON 数据。"""
        try:
            length_line = client_file.readline()
            if not length_line:
                return None
            try:
                length = int(length_line.decode().strip())
            except ValueError:
                return None
            data = client_file.read(length)
            if len(data) != length:
                return None
            return json.loads(data.decode("utf-8"))
        except Exception as e:
            log(f"解析 JSON 异常: {e}", role="server")
            return None

    def _send_json(self, sock: socket.socket, payload: dict) -> None:
        """以简化 JSON 格式发送消息："J" + 长度 + JSON。"""
        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            header = f"{len(body)}\n".encode("utf-8")
            sock.sendall(b"J" + header + body)
        except Exception as e:
            log(f"发送 JSON 异常: {e}", role="server")

    def _detect_real_ip(self) -> str:
        """探测本机外网可见 IP（用于提示 APP 连接地址）。"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            real_ip = s.getsockname()[0]
        except Exception:
            real_ip = self.host
        finally:
            s.close()
        return real_ip


# -------------------------------
# 通信客户端（用于本地联调测试）
# -------------------------------

class ComClient:
    """简易通信客户端，用于联调与测试。"""

    def __init__(self, host: str, port: int) -> None:
        """初始化客户端并建立 TCP 连接。"""
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        log(f"客户端已连接到 {host}:{port}", role="client")

    def close(self) -> None:
        """关闭客户端连接。"""
        try:
            self.sock.close()
            log("客户端连接已关闭", role="client")
        except Exception:
            pass

    def send_instruction(self, text: str) -> None:
        """发送指令消息（旧格式 I）。"""
        data = (text + "\n").encode("utf-8")
        self.sock.sendall(b"I" + data)
        log(f"客户端发送指令: {text}", role="client")

    def send_xml(self, xml_text: str) -> None:
        """发送 XML 消息（旧格式 X）。"""
        body = xml_text.encode("utf-8")
        header = f"{len(body)}\n".encode("utf-8")
        self.sock.sendall(b"X" + header + body)
        log(f"客户端发送 XML（长度={len(body)}）", role="client")

    def send_screenshot(self, content: bytes) -> None:
        """发送截图消息（旧格式 S）。"""
        header = f"{len(content)}\n".encode("utf-8")
        self.sock.sendall(b"S" + header + content)
        log(f"客户端发送截图（长度={len(content)}）", role="client")

    def send_error(self, error_text: str) -> None:
        """发送错误消息（旧格式 E）。"""
        body = error_text.encode("utf-8")
        header = f"{len(body)}\n".encode("utf-8")
        self.sock.sendall(b"E" + header + body)
        log(f"客户端发送错误: {error_text}", role="client")

    def request_actions(self) -> None:
        """发送获取动作请求（旧格式 G）。"""
        self.sock.sendall(b"G")
        log("客户端请求动作列表", role="client")

    def send_json(self, payload: dict) -> None:
        """发送简化 JSON 消息。"""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        header = f"{len(body)}\n".encode("utf-8")
        self.sock.sendall(b"J" + header + body)
        log(f"客户端发送 JSON（长度={len(body)}）", role="client")

    def receive_one(self, timeout: float = 1.0) -> Optional[dict]:
        """接收一条来自服务器的消息（阻塞最多 timeout 秒）。

        参数:
            timeout: 超时时间（秒）
        返回:
            dict 或 None: 解析后的消息字典
        """
        self.sock.settimeout(timeout)
        try:
            type_byte = self.sock.recv(1)
            if not type_byte:
                return None
            type_char = type_byte.decode()
            if type_char in ["I", "X", "S", "A", "E", "G"]:
                # 旧格式（客户端一般不会收到该类型，保留兼容）
                # 尝试按 JSON 处理以避免复杂分支
                length_line = self._recv_until_newline()
                if length_line is None:
                    return None
                try:
                    length = int(length_line)
                except ValueError:
                    return None
                data = self._recv_exact(length)
                if data is None:
                    return None
                try:
                    return json.loads(data.decode("utf-8"))
                except Exception:
                    return {"raw": data.decode("utf-8", errors="ignore")}
            else:
                # 简化 JSON 格式：首字节占位，随后长度与 JSON
                length_line = self._recv_until_newline()
                if length_line is None:
                    return None
                try:
                    length = int(length_line)
                except ValueError:
                    return None
                data = self._recv_exact(length)
                if data is None:
                    return None
                return json.loads(data.decode("utf-8"))
        except socket.timeout:
            return None
        except Exception:
            return None

    def _recv_until_newline(self) -> Optional[str]:
        """辅助函数：接收直到换行并返回不含换行的文本。"""
        buf = bytearray()
        while True:
            b = self.sock.recv(1)
            if not b:
                return None
            if b == b"\n":
                break
            buf.extend(b)
        try:
            return buf.decode("utf-8")
        except Exception:
            return None

    def _recv_exact(self, n: int) -> Optional[bytes]:
        """辅助函数：精确接收 n 字节，失败返回 None。"""
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)