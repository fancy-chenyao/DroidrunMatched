"""
任务请求客户端示例

演示如何从移动端向服务端发送任务请求并接收执行结果。
"""
import asyncio
import json
import sys
import uuid
import argparse
import websockets
from droidrun.server.message_protocol import MessageProtocol, MessageType


async def send_task_request_example(device_id: str = "test_device_001", 
                                   server_url: str = "ws://localhost:8765/ws",
                                   goal: str = "打开设置应用"):
    """发送任务请求示例"""
    uri = f"{server_url}?device_id={device_id}"
    
    print("=" * 60)
    print("📱 任务请求客户端示例")
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
            print(f"📨 收到欢迎消息: {welcome_data.get('type')}")
            print()
            
            # 构建任务请求
            request_id = str(uuid.uuid4())
            
            task_request = MessageProtocol.create_task_request(
                goal=goal,
                request_id=request_id,
                device_id=device_id,
                options={
                    "max_steps": 10,
                    "vision": False,
                    "reasoning": False,
                    "debug": False
                }
            )
            
            print(f"📤 发送任务请求:")
            print(f"   请求ID: {request_id}")
            print(f"   任务目标: {goal}")
            print()
            
            # 发送任务请求
            await websocket.send(json.dumps(task_request))
            
            # 监听响应
            print("👂 监听任务执行状态和结果...")
            print()
            
            task_completed = False
            
            async for message in websocket:
                try:
                    msg_data = json.loads(message)
                    msg_type = msg_data.get("type")
                    
                    if msg_type == "task_status":
                        # 任务状态更新
                        data = msg_data.get("data", {})
                        status = data.get("status")
                        progress = data.get("progress", 0.0)
                        message_text = data.get("message", "")
                        
                        print(f"📊 任务状态更新:")
                        print(f"   状态: {status}")
                        print(f"   进度: {progress:.1%}")
                        print(f"   消息: {message_text}")
                        print()
                    
                    elif msg_type == "task_response":
                        # 任务执行结果
                        status = msg_data.get("status")
                        
                        print(f"📥 收到任务响应:")
                        print(f"   状态: {status}")
                        
                        if status == "success":
                            result = msg_data.get("result", {})
                            success = result.get("success", False)
                            output = result.get("output", "")
                            steps = result.get("steps", 0)
                            reason = result.get("reason", "")
                            
                            print(f"   执行成功: {success}")
                            print(f"   输出: {output}")
                            print(f"   执行步骤: {steps}")
                            if reason:
                                print(f"   原因: {reason}")
                        else:
                            error = msg_data.get("error", "Unknown error")
                            print(f"   错误: {error}")
                        
                        print()
                        task_completed = True
                        break
                    
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
            
            if task_completed:
                print("✅ 任务请求处理完成")
            else:
                print("⚠️  任务请求未完成（连接可能已断开）")
            
    except KeyboardInterrupt:
        print()
        print("🛑 用户中断")
    except websockets.exceptions.ConnectionClosed:
        print("🔌 连接已关闭")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="任务请求客户端示例")
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
    parser.add_argument(
        "--goal",
        default="打开设置应用",
        help="任务目标（默认: 打开设置应用）"
    )
    
    args = parser.parse_args()
    
    asyncio.run(send_task_request_example(
        device_id=args.device_id,
        server_url=args.url,
        goal=args.goal
    ))


if __name__ == "__main__":
    main()

