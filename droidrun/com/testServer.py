"""
测试服务器（droidrun/com/testServer.py）

该模块实现测试用服务器，聚合服务端的动作决策逻辑：
- com.py 负责消息预处理，testServer.py 负责根据预处理后的消息执行动作决策；
- 通过覆写 `_on_message_processed` 方法，实现测试侧可控的动作决策逻辑；
- 其他底层能力（会话管理、消息接收、预处理函数与日志）仍复用 com.py，保持解耦。
"""

import time
import click
from typing import Optional
try:
    # 包内相对导入
    from .com import ComServer, log, ClientSession, Message_types
except ImportError:
    # 作为脚本运行时的本地导入回退
    from com import ComServer, log, ClientSession, Message_types


class TestComServer(ComServer):
    """测试服务器：覆写动作决策逻辑。

    说明:
    - 继承 `ComServer` 并覆写 `_on_message_processed`，实现测试侧可控的动作决策逻辑。
    - 复用基类的消息接收与预处理能力，专注于动作决策与执行。
    """

    def _handle_client(self, session: ClientSession) -> None:
        """处理单个客户端连接的消息循环。

        参数:
            session: 当前客户端会话
        """
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
                # 使用当前类覆写的分发逻辑
                self._dispatch_message(session, message)
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
        """消息预处理完成后的动作决策逻辑（测试侧覆写）。

        参数:
            session: 当前客户端会话
            processed_message: 预处理后的消息字典
        """
        mtype = processed_message.get("messageType", "")
        processed_data = processed_message.get("processed", {})
        
        log(f"[测试服务器] 开始处理预处理后的消息: {mtype} 会话={session.session_id}", role="server")
        
        try:
            if mtype == Message_types.instruction:
                # 对指令消息的动作决策
                instruction_text = processed_data.get("instruction_text", "")
                log(f"[接受指令] {instruction_text}", role="server")
                
            elif mtype == Message_types.xml:
                # 对XML消息的动作决策
                xml_length = processed_data.get("xml_length", 0)
                self.send_action(session, {
                    "name": "click",
                    "parameters": {"index": 23}
                })
                log(f"[接受XML] 确认XML长度: {xml_length}", role="server")
                
            elif mtype == Message_types.screenshot:
                # 对截图消息的动作决策
                screenshot_length = processed_data.get("screenshot_length", 0)
                self.send_action(session, {
                    "type": "ack_screenshot", 
                    "length": screenshot_length,
                    "timestamp": time.time()
                })
                log(f"[接受截图] 确认截图长度: {screenshot_length}", role="server")
                
            elif mtype == Message_types.qa:
                # 对QA消息的动作决策
                qa_text = processed_data.get("qa_text", "")
                log(f"[接受QA] 确认QA文本: {qa_text}", role="server")
                
            elif mtype == Message_types.error:
                # 对错误消息的动作决策
                error_text = processed_data.get("error_text", "")
                self.send_action(session, {
                    "name": "click",
                    "parameters": {"index": 23}
                })
                log(f"[接受错误] 确认错误文本: {error_text}", role="server")
                
                
            else:
                log(f"[接受未知] 未知消息类型: {mtype}", role="server")
                
        except Exception as e:
            log(f"[接受未知] 处理异常[{mtype}]: {e}", role="server")


def start_server(host: str = "127.0.0.1", port: int = 7777) -> TestComServer:
    """启动测试服务器并返回实例。

    参数:
        host: 绑定地址
        port: 绑定端口
    返回:
        TestComServer: 已启动的测试服务器实例
    """
    server = TestComServer(host=host, port=port)
    server.start()
    log("测试服务器已启动，等待 APP 连接与消息...", role="server")
    return server


def _noop_llm_enabled() -> bool:
    """占位函数：返回是否启用大模型（CLI 开关控制）。

    为保持与用户需求一致，默认返回 False。后续如需接入 LLM，可在此处挂载实际检查逻辑。
    """
    return False


def _noop_memory_enabled() -> bool:
    """占位函数：返回是否启用记忆模块（CLI 开关控制）。

    为保持与用户需求一致，默认返回 False。后续如需接入记忆模块，可在此处挂载实际检查逻辑。
    """
    return False


@click.group()
def cli() -> None:
    """轻量 CLI 入口（只做通信，不启用 LLM 与记忆）。"""
    pass


@cli.command()
@click.option("--host", default="0.0.0.0", help="服务器绑定地址")
@click.option("--port", default=6666, type=int, help="服务器绑定端口")
@click.option("--enable-llm", is_flag=True, default=False, help="是否启用大模型（默认关闭）")
@click.option("--enable-memory", is_flag=True, default=False, help="是否启用记忆模块（默认关闭）")
def serve(host: str, port: int, enable_llm: bool, enable_memory: bool) -> None:
    """启动通信服务器，供 APP 连接。

    参数:
        host: 绑定地址
        port: 绑定端口
        enable_llm: 是否启用大模型（测试默认关闭）
        enable_memory: 是否启用记忆模块（测试默认关闭）
    """
    # 记录开关（当前仅占位，不在此启用任何 LLM 或记忆逻辑）
    _ = enable_llm or _noop_llm_enabled()
    _ = enable_memory or _noop_memory_enabled()

    server = ComServer(host=host, port=port)

    # 启动服务并阻塞当前进程（交由后台线程处理连接），
    # 消息处理逻辑与日志输出均在 com.py 内置。
    server.start()
    log("服务器已启动，等待 APP 连接与消息...（按 Ctrl+C 结束）")

    # 简单阻塞循环，保持进程存活
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("收到中断，准备关闭服务器...")
    finally:
        server.stop()
        log("服务器已关闭")


if __name__ == "__main__":
    cli()