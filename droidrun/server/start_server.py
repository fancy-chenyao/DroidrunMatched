#!/usr/bin/env python3
"""
WebSocket 服务器启动脚本

独立启动脚本，可以直接运行而不需要通过 CLI。
"""
import asyncio
import sys
import signal
from droidrun.config import get_config_manager
from droidrun.server import WebSocketServer
from droidrun.agent.utils.logging_utils import LoggingUtils


async def main():
    """主函数"""
    try:
        # 获取配置管理器
        config_manager = get_config_manager()
        server_config = config_manager.get_server_config()
        
        # 检查服务器模式
        if server_config.mode != "server":
            LoggingUtils.log_warning("Server", "Server mode is not enabled in config. Set server.mode='server' to enable.")
            LoggingUtils.log_info("Server", "Starting server anyway...")
        
        # 创建服务器实例
        server = WebSocketServer(
            config_manager=config_manager,
            host=server_config.server_host,
            port=server_config.server_port,
            websocket_path=server_config.websocket_path,
            heartbeat_interval=server_config.heartbeat_interval,
        )
        
        # 设置信号处理
        def signal_handler(sig, frame):
            LoggingUtils.log_info("Server", "Received interrupt signal, shutting down...")
            asyncio.create_task(server.stop())
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        LoggingUtils.log_info("Server", "WebSocket server starting...")
        LoggingUtils.log_info("Server", "Host: {host}, Port: {port}, Path: {path}", 
                             host=server_config.server_host, 
                             port=server_config.server_port, 
                             path=server_config.websocket_path)
        
        # 启动服务器（这会阻塞直到服务器关闭）
        await server.start()
        
    except KeyboardInterrupt:
        LoggingUtils.log_info("Server", "Server stopped by user")
    except Exception as e:
        LoggingUtils.log_error("Server", "Server error: {error}", error=e)
        import traceback
        LoggingUtils.log_error("Server", "Traceback: {traceback}", traceback=traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

