"""
测试客户端（droidrun/com/testClient.py）

该模块实现测试用客户端的消息发送与回包接收流程：
- 连接测试服务器并按序发送 I/XML/截图/E；
- 每步发送后尝试接收服务器返回的确认回包（ack 动作）。
"""

from typing import Optional
try:
    # 包内相对导入
    from .com import ComClient, log
except ImportError:
    # 作为脚本运行时的本地导入回退
    from com import ComClient, log


def start_client(host: str, port: int) -> ComClient:
    """启动测试客户端并建立连接。

    参数:
        host: 服务器地址
        port: 服务器端口
    返回:
        ComClient: 已连接的客户端实例
    """
    client = ComClient(host=host, port=port)
    log("测试客户端已创建", role="client")
    return client


def run_client_sequence(host: str, port: int) -> ComClient:
    """运行客户端侧的通信序列：I/XML/截图/E。

    参数:
        host: 服务器地址
        port: 服务器端口
    返回:
        ComClient: 执行完序列的客户端实例
    """
    client = start_client(host, port)

    # 1) 指令(I)
    client.send_instruction("帮我请假")
    r1 = client.receive_one(timeout=1.0)
    log(f"收到指令回包: {r1}", role="client")

    # 2) XML(X)
    xml_text = "<hierarchy><node text='设置'/></hierarchy>"
    client.send_xml(xml_text)
    r2 = client.receive_one(timeout=1.0)
    log(f"收到 XML 回包: {r2}", role="client")

    # 3) 截图(S)
    fake_shot = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00"
    client.send_screenshot(fake_shot)
    r3 = client.receive_one(timeout=1.0)
    log(f"收到截图回包: {r3}", role="client")

    # 4) 错误(E)
    client.send_error("页面没变化")
    r4 = client.receive_one(timeout=1.0)
    log(f"收到错误回包: {r4}", role="client")

    return client