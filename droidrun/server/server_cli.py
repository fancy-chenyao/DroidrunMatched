"""
WebSocket 服务器 CLI 命令
"""
import asyncio
import click
from rich.console import Console
from droidrun.config import get_config_manager
from droidrun.server import WebSocketServer
from droidrun.agent.utils.logging_utils import LoggingUtils

console = Console()


@click.command(name="server")
@click.option(
    "--host",
    help="服务器监听地址",
    default=None,
)
@click.option(
    "--port",
    type=int,
    help="服务器监听端口",
    default=None,
)
@click.option(
    "--path",
    help="WebSocket 路径",
    default=None,
)
@click.option(
    "--heartbeat-interval",
    type=int,
    help="心跳间隔（秒）",
    default=None,
)
@click.option(
    "--debug",
    is_flag=True,
    help="启用调试日志",
    default=False,
)
def server_cli(host, port, path, heartbeat_interval, debug):
    """
    启动 WebSocket 服务器，接收 APP 端连接并提供设备控制服务。
    
    示例:
        droidrun server --host 0.0.0.0 --port 8765
        droidrun server --port 9000 --debug
    """
    try:
        # 获取配置管理器
        config_manager = get_config_manager()
        server_config = config_manager.get_server_config()
        
        # 使用命令行参数覆盖配置（如果提供）
        final_host = host or server_config.server_host
        final_port = port or server_config.server_port
        final_path = path or server_config.websocket_path
        final_heartbeat = heartbeat_interval or server_config.heartbeat_interval
        
        console.print(f"[bold blue]🚀 启动 WebSocket 服务器...[/]")
        console.print(f"  监听地址: [cyan]{final_host}[/]")
        console.print(f"  监听端口: [cyan]{final_port}[/]")
        console.print(f"  WebSocket 路径: [cyan]{final_path}[/]")
        console.print(f"  心跳间隔: [cyan]{final_heartbeat}秒[/]")
        console.print(f"  调试模式: [cyan]{'开启' if debug else '关闭'}[/]")
        console.print()
        
        # 构建完整的连接URL
        ws_url = f"ws://{final_host if final_host != '0.0.0.0' else 'localhost'}:{final_port}{final_path}"
        
        console.print("[bold yellow]📱 APP 端连接方式:[/]")
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
        
        # 启动服务器
        console.print("[bold green]✅ 服务器已启动，等待客户端连接...[/]")
        console.print("[yellow]按 Ctrl+C 停止服务器[/]")
        console.print()
        console.print("[dim]提示: 可以使用以下命令测试连接:[/]")
        console.print(f"[dim]  python -m droidrun.server.example_client --device-id test_device[/]")
        console.print()
        
        asyncio.run(server.start())
        
    except KeyboardInterrupt:
        console.print("\n[yellow]正在停止服务器...[/]")
        try:
            asyncio.run(server.stop())
        except:
            pass
        console.print("[bold green]服务器已停止[/]")
    except Exception as e:
        console.print(f"[bold red]错误: {e}[/]")
        if debug:
            import traceback
            traceback.print_exc()
        raise

