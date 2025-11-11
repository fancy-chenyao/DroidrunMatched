"""
WebSocket 服务器集成示例

展示如何将 WebSocketTools 集成到 DroidAgent 中。
"""
import asyncio
from droidrun.agent.droid import DroidAgent
from droidrun.tools import WebSocketTools
from droidrun.server import WebSocketServer, SessionManager
from droidrun.config import get_config_manager
from llama_index.llms.openai_like import OpenAILike


async def main():
    """主函数"""
    print("🚀 WebSocket 服务器集成示例")
    print("=" * 50)
    
    # 1. 获取配置管理器
    config_manager = get_config_manager()
    server_config = config_manager.get_server_config()
    api_config = config_manager.get_api_config()
    
    # 2. 启动 WebSocket 服务器（在后台）
    server = WebSocketServer(
        config_manager=config_manager,
        host=server_config.server_host,
        port=server_config.server_port,
        websocket_path=server_config.websocket_path,
        heartbeat_interval=server_config.heartbeat_interval,
    )
    
    # 启动服务器任务
    server_task = asyncio.create_task(server.start())
    print(f"✅ WebSocket 服务器已启动 (端口: {server_config.server_port})")
    
    # 等待服务器初始化
    await asyncio.sleep(1)
    
    # 3. 创建 SessionManager
    session_manager = SessionManager(heartbeat_timeout=server_config.heartbeat_interval * 2)
    
    # 4. 创建 WebSocketTools 实例
    # 注意：这需要 APP 端已经连接到服务器
    device_id = "example_device_001"
    tools = WebSocketTools(
        device_id=device_id,
        session_manager=session_manager,
        config_manager=config_manager,
        timeout=server_config.timeout,
    )
    
    # 5. 注册工具实例到服务器（用于响应处理）
    server.register_tools_instance(device_id, tools)
    print(f"✅ WebSocketTools 已创建并注册 (设备ID: {device_id})")
    
    # 6. 创建 LLM（如果需要运行 Agent）
    if api_config.api_key:
        llm = OpenAILike(
            model=api_config.model,
            api_base=api_config.api_base,
            api_key=api_config.api_key,
            is_chat_model=True,
        )
        
        # 7. 创建 DroidAgent（使用 WebSocketTools）
        agent = DroidAgent(
            goal="测试 WebSocket 连接",
            llm=llm,
            tools=tools,
            config_manager=config_manager,
        )
        
        print("✅ DroidAgent 已创建（使用 WebSocketTools）")
        print("⚠️  注意：需要 APP 端连接到服务器才能执行任务")
        print()
        print("在另一个终端运行:")
        print(f"  python -m droidrun.server.example_client")
        print()
        print("或等待 APP 端连接...")
        
        # 等待连接（实际使用时应该等待 APP 端连接）
        await asyncio.sleep(5)
        
        # 8. 运行 Agent（示例）
        # result = await agent.run()
        # print(f"执行结果: {result}")
    else:
        print("⚠️  未配置 API 密钥，跳过 Agent 创建")
        print("💡 提示：设置环境变量 ALIYUN_API_KEY 以启用 LLM 功能")
    
    # 清理
    print("\n正在停止服务器...")
    await server.stop()
    server_task.cancel()
    print("✅ 服务器已停止")


if __name__ == "__main__":
    asyncio.run(main())







