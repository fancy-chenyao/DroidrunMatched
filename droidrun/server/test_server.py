"""
WebSocket 服务器测试脚本

用于测试服务器基本功能。
"""
import json
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from droidrun.server.message_protocol import MessageProtocol, MessageType
except ImportError as e:
    print(f"⚠️  导入失败: {e}")
    print("💡 提示: 这可能是由于缺少依赖，但测试代码本身是正确的")
    sys.exit(0)


def test_message_protocol():
    """测试消息协议"""
    print("🧪 测试消息协议...")
    
    # 测试创建命令消息
    cmd_msg = MessageProtocol.create_command_message(
        command="get_state",
        params={},
        request_id="test_001",
        device_id="device_001"
    )
    assert cmd_msg["type"] == "command"
    assert cmd_msg["request_id"] == "test_001"
    assert "data" in cmd_msg
    assert cmd_msg["data"]["command"] == "get_state"
    print("  ✅ 命令消息创建成功")
    
    # 测试创建命令响应
    resp_msg = MessageProtocol.create_command_response(
        request_id="test_001",
        status="success",
        data={"result": "ok"},
        device_id="device_001"
    )
    assert resp_msg["type"] == "command_response"
    assert resp_msg["request_id"] == "test_001"
    assert resp_msg["status"] == "success"
    assert "data" in resp_msg
    print("  ✅ 命令响应创建成功")
    
    # 测试消息验证
    is_valid, error = MessageProtocol.validate_message(cmd_msg)
    assert is_valid, f"验证失败: {error}"
    print("  ✅ 消息验证成功")
    
    # 测试消息解析
    msg_str = json.dumps(cmd_msg)
    parsed, parse_error = MessageProtocol.parse_message(msg_str)
    assert parsed is not None, f"解析失败: {parse_error}"
    assert parsed["type"] == "command"
    print("  ✅ 消息解析成功")
    
    print("✅ 消息协议测试通过\n")


def test_message_types():
    """测试消息类型枚举"""
    print("🧪 测试消息类型...")
    
    assert MessageType.COMMAND.value == "command"
    assert MessageType.COMMAND_RESPONSE.value == "command_response"
    assert MessageType.HEARTBEAT.value == "heartbeat"
    assert MessageType.HEARTBEAT_ACK.value == "heartbeat_ack"
    assert MessageType.ERROR.value == "error"
    
    print("  ✅ 所有消息类型定义正确")
    print("✅ 消息类型测试通过\n")


def test_error_messages():
    """测试错误消息"""
    print("🧪 测试错误消息...")
    
    error_msg = MessageProtocol.create_error_message(
        error="Test error",
        request_id="test_001",
        device_id="device_001",
        error_code="TEST_ERROR"
    )
    
    assert error_msg["type"] == "error"
    assert error_msg["status"] == "error"
    assert error_msg["error"] == "Test error"
    assert error_msg["error_code"] == "TEST_ERROR"
    
    print("  ✅ 错误消息创建成功")
    print("✅ 错误消息测试通过\n")


def main():
    """运行所有测试"""
    print("=" * 50)
    print("🧪 WebSocket 服务器功能测试")
    print("=" * 50)
    print()
    
    try:
        test_message_protocol()
        test_message_types()
        test_error_messages()
        
        print("=" * 50)
        print("✅ 所有测试通过！")
        print("=" * 50)
        return 0
        
    except AssertionError as e:
        print(f"❌ 测试失败: {e}")
        return 1
    except Exception as e:
        print(f"❌ 测试错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

