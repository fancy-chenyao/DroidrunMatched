"""
通信能力自测主程序（droidrun/com/test.py）

该脚本仅负责编排测试流程：
- 启动测试服务器（testServer.py）；
- 启动测试客户端（testClient.py）并执行通信序列；
- 完成后进行资源清理。
"""

import threading
import time
from typing import Tuple

try:
    # 优先包内相对导入
    from .com import log
    from .testServer import start_server
    from .testClient import run_client_sequence
except ImportError:
    # 作为脚本直接运行时的本地导入回退
    from com import log
    from testServer import start_server
    from testClient import run_client_sequence


def tlog(role: str, message: str) -> None:
    """测试日志输出函数：为消息追加角色前缀。

    参数:
        role: 角色标识，例如 "client"、"server"、"test"
        message: 实际日志内容
    """
    log(f"[{role}] {message}")


# 测试开关：置为 True 时，仅测试通信，不调用大模型与记忆
ENABLE_PURE_COMMUNICATION_TEST = True


def start_mock_server(host: str = "127.0.0.1", port: int = 7777):
    """启动测试服务器（委托 testServer 模块）。

    参数:
        host: 绑定地址
        port: 绑定端口
    返回:
        已启动的测试服务器实例
    """
    tlog("server", f"准备启动测试服务器 host={host} port={port}")
    server = start_server(host=host, port=port)
    tlog("server", "服务器已启动并开始监听连接")
    return server


def start_mock_client(host: str, port: int):
    """启动测试客户端（委托 testClient 模块执行通信序列）。"""
    tlog("client", f"创建客户端并连接到 {host}:{port}")
    client = run_client_sequence(host=host, port=port)
    tlog("client", "客户端已完成通信序列")
    return client


def run_connection_test(host: str = "127.0.0.1", port: int = 7777):
    """运行通信能力自测：启动测试服务器与测试客户端并执行序列。

    返回:
        (server, client): 测试服务器与客户端实例
    """
    server = start_mock_server(host, port)
    # 等待服务器就绪
    tlog("server", "等待服务器就绪 0.3 秒")
    time.sleep(0.3)
    client = start_mock_client(host, port)

    # 保持一段时间以便交互完成
    tlog("test", "交互完成，等待 0.5 秒用于收尾")
    time.sleep(0.5)

    return server, client


def main() -> None:
    """手动运行入口：根据开关执行纯通信测试。"""
    if ENABLE_PURE_COMMUNICATION_TEST:
        tlog("test", "启动纯通信能力测试（不启用LLM与记忆模块）...")
        server, client = run_connection_test()
        tlog("test", "测试完成，即将清理资源...")
        try:
            client.close()
        except Exception:
            pass
        try:
            server.stop()
        except Exception:
            pass
        tlog("test", "资源清理完成。")
    else:
        tlog("test", "当前测试开关关闭，未执行通信能力测试。")


if __name__ == "__main__":
    main()