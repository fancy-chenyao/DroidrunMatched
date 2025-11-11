"""
WebSocket 客户端示例

这是一个简单的 WebSocket 客户端示例，用于测试服务器功能。

使用方法：
    python -m droidrun.server.example_client

或者自定义设备ID和服务器地址：
    python -m droidrun.server.example_client --device-id my_device --url ws://localhost:8765/ws
"""
import asyncio
import json
import sys
import argparse
import websockets
from droidrun.server.message_protocol import MessageProtocol, MessageType


async def test_client(device_id: str = "test_device_001", server_url: str = "ws://localhost:8765/ws"):
    """
    测试客户端
    
    Args:
        device_id: 设备ID
        server_url: 服务器URL（不包含设备ID参数）
    """
    # 构建完整的连接URL（通过查询参数传递设备ID）
    uri = f"{server_url}?device_id={device_id}"
    
    print("=" * 60)
    print("🧪 WebSocket 客户端测试")
    print("=" * 60)
    print(f"📡 服务器地址: {uri}")
    print(f"📱 设备ID: {device_id}")
    print()
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ 已连接到服务器")
            print()
            
            # 接收欢迎消息
            welcome = await websocket.recv()
            welcome_data = json.loads(welcome)
            print(f"📨 收到欢迎消息:")
            print(f"   类型: {welcome_data.get('type')}")
            print(f"   内容: {json.dumps(welcome_data, indent=2, ensure_ascii=False)}")
            print()
            
            # 发送心跳
            print("💓 发送心跳消息...")
            heartbeat = MessageProtocol.create_heartbeat_message(device_id=device_id)
            await websocket.send(json.dumps(heartbeat))
            
            # 接收心跳确认
            ack = await websocket.recv()
            ack_data = json.loads(ack)
            print(f"📨 收到心跳确认: {ack_data.get('type')}")
            print()
            
            # 监听服务器命令（持续运行）
            print("👂 开始监听服务器命令...")
            print("   (按 Ctrl+C 停止)")
            print()
            
            async def listen_for_commands():
                """监听服务器命令"""
                async for message in websocket:
                    try:
                        msg_data = json.loads(message)
                        msg_type = msg_data.get("type")
                        
                        if msg_type == "command":
                            # 收到命令
                            request_id = msg_data.get("request_id")
                            command_data = msg_data.get("data", {})
                            command = command_data.get("command")
                            
                            print(f"📥 收到命令:")
                            print(f"   请求ID: {request_id}")
                            print(f"   命令: {command}")
                            print(f"   参数: {json.dumps(command_data.get('params', {}), indent=2, ensure_ascii=False)}")
                            print()
                            
                            # 模拟命令执行
                            result = {
                                "executed": True,
                                "command": command,
                                "result": f"Command '{command}' executed successfully"
                            }
                            
                            # 发送命令响应
                            response = MessageProtocol.create_command_response(
                                request_id=request_id,
                                status="success",
                                data=result,
                                device_id=device_id
                            )
                            await websocket.send(json.dumps(response))
                            print(f"📤 发送命令响应:")
                            print(f"   请求ID: {request_id}")
                            print(f"   状态: success")
                            print(f"   结果: {json.dumps(result, indent=2, ensure_ascii=False)}")
                            print()
                        
                        elif msg_type == "heartbeat_ack":
                            # 心跳确认（静默处理）
                            pass
                        
                        else:
                            print(f"📨 收到其他消息: {msg_type}")
                            print(f"   内容: {json.dumps(msg_data, indent=2, ensure_ascii=False)}")
                            print()
                    
                    except json.JSONDecodeError:
                        print(f"⚠️  收到非JSON消息: {message}")
                    except Exception as e:
                        print(f"❌ 处理消息错误: {e}")
                        import traceback
                        traceback.print_exc()
            
            # 持续监听命令
            await listen_for_commands()
            
    except KeyboardInterrupt:
        print()
        print("🛑 用户中断，正在断开连接...")
    except websockets.exceptions.ConnectionClosed:
        print("🔌 连接已关闭")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print("✅ 测试完成")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="WebSocket 客户端测试工具")
    parser.add_argument(
        "--device-id",
        default="test_device_001",
        help="设备ID（默认: test_device_001）"
    )
    parser.add_argument(
        "--url",
        default="ws://localhost:8765/ws",
        help="服务器URL（默认: ws://localhost:8765/ws）"
    )
    
    args = parser.parse_args()
    
    asyncio.run(test_client(device_id=args.device_id, server_url=args.url))


if __name__ == "__main__":
    print("🧪 WebSocket 客户端测试")
    print("=" * 40)
    asyncio.run(test_client())

