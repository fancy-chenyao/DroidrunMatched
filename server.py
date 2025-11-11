#!/usr/bin/env python3
"""
DroidRun WebSocket 服务器独立启动脚本

一键启动 WebSocket 服务器，接收移动端连接和任务指令。
不依赖 CLI 系统，不需要 LLM 初始化。

使用方法:
    python server.py
    或
    python server.py --host 0.0.0.0 --port 8765
"""
import asyncio
import sys
import signal
import argparse
from rich.console import Console
from droidrun.config import get_config_manager
from droidrun.server import WebSocketServer
from droidrun.agent.utils.logging_utils import LoggingUtils

console = Console()


def setup_logging(debug: bool = False):
    """设置日志"""
    import logging
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="DroidRun WebSocket 服务器 - 接收移动端连接和任务指令",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python server.py
  python server.py --host 0.0.0.0 --port 8765
  python server.py --port 9000 --debug
        """
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="服务器监听地址（默认: 从配置文件读取）"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="服务器监听端口（默认: 从配置文件读取）"
    )
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="WebSocket 路径（默认: /ws）"
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=int,
        default=None,
        help="心跳间隔（秒，默认: 30）"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用调试日志"
    )
    
    args = parser.parse_args()
    
    # 设置日志
    setup_logging(debug=args.debug)
    
    try:
        # 获取配置管理器（不触发 LLM 初始化）
        config_manager = get_config_manager()
        server_config = config_manager.get_server_config()
        
        # 使用命令行参数覆盖配置（如果提供）
        final_host = args.host or server_config.server_host
        final_port = args.port or server_config.server_port
        final_path = args.path or server_config.websocket_path
        final_heartbeat = args.heartbeat_interval or server_config.heartbeat_interval
        
        # 显示启动信息
        console.print("\n[bold blue]🚀 启动 DroidRun WebSocket 服务器[/]")
        console.print("=" * 60)
        console.print(f"  监听地址: [cyan]{final_host}[/]")
        console.print(f"  监听端口: [cyan]{final_port}[/]")
        console.print(f"  WebSocket 路径: [cyan]{final_path}[/]")
        console.print(f"  心跳间隔: [cyan]{final_heartbeat}秒[/]")
        console.print(f"  调试模式: [cyan]{'开启' if args.debug else '关闭'}[/]")
        console.print()
        
        # 构建完整的连接URL
        ws_url = f"ws://{final_host if final_host != '0.0.0.0' else 'localhost'}:{final_port}{final_path}"
        
        console.print("[bold yellow]📱 移动端连接方式:[/]")
        console.print(f"  [cyan]{ws_url}?device_id=your_device_id[/]")
        console.print()
        
        # 创建服务器实例
        server = WebSocketServer(
            config_manager=config_manager,
            host=final_host,
            port=final_port,
            websocket_path=final_path,
            heartbeat_interval=final_heartbeat,
        )
        
        # 设置信号处理（优雅关闭）
        def signal_handler(sig, frame):
            console.print("\n[yellow]收到停止信号，正在关闭服务器...[/]")
            asyncio.create_task(server.stop())
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # 启动服务器
        console.print("[bold green]✅ 服务器已启动，等待移动端连接...[/]")
        console.print("[yellow]按 Ctrl+C 停止服务器[/]")
        console.print()
        console.print("[dim]提示:[/]")
        console.print("[dim]  - 移动端连接后，可以通过 WebSocket 发送任务指令[/]")
        console.print("[dim]  - 使用以下命令测试连接:[/]")
        console.print(f"[dim]    python -m droidrun.server.example_client --device-id test_device[/]")
        console.print()
        
        # 启动服务器（阻塞直到关闭）
        await server.start()
        
    except KeyboardInterrupt:
        console.print("\n[yellow]用户中断，正在关闭服务器...[/]")
        try:
            await server.stop()
        except:
            pass
        console.print("[bold green]服务器已停止[/]")
    except Exception as e:
        console.print(f"\n[bold red]❌ 错误: {e}[/]")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]服务器已停止[/]")
        sys.exit(0)












