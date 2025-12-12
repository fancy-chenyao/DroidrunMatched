#!/usr/bin/env python3
"""
测试本地模型配置是否可用
"""
import asyncio
from droidrun.config import get_config_manager
from droidrun.agent.utils.llm_picker import load_llm
from llama_index.core.base.llms.types import ChatMessage


async def test_model():
    """测试模型配置和连接"""
    print("=" * 60)
    print("🧪 测试本地模型配置")
    print("=" * 60)
    
    # 1. 验证配置加载
    print("\n📋 步骤 1: 验证配置文件加载")
    try:
        config_manager = get_config_manager()
        api_config = config_manager.get_api_config()
        
        print(f"✅ 配置加载成功:")
        print(f"  - Model: {api_config.model}")
        print(f"  - API Base: {api_config.api_base}")
        print(f"  - API Key: {'***' if api_config.api_key else 'None'}")
        print(f"  - Timeout: {api_config.timeout}s")
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")
        return False
    
    # 2. 创建 LLM 实例
    print("\n🤖 步骤 2: 创建 LLM 实例")
    try:
        llm = load_llm(
            provider_name="OpenAILike",
            model=api_config.model,
            api_base=api_config.api_base,
            api_key=api_config.api_key or "dummy-key",
            is_chat_model=True,
            timeout=api_config.timeout,
        )
        print("✅ LLM 实例创建成功")
    except Exception as e:
        print(f"❌ LLM 实例创建失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 3. 测试模型响应
    print("\n💬 步骤 3: 测试模型响应")
    try:
        test_message = ChatMessage(
            role="user",
            content="你好，请用一句话介绍你自己。"
        )
        
        print("  发送测试消息: '你好，请用一句话介绍你自己。'")
        print("  等待模型响应...")
        
        response = await llm.achat([test_message])
        
        print(f"✅ 模型响应成功:")
        print(f"  响应内容: {response.message.content}")
        
    except Exception as e:
        print(f"❌ 模型响应失败: {e}")
        print(f"\n💡 可能的原因:")
        print(f"  1. 模型服务未启动")
        print(f"  2. API 地址配置错误")
        print(f"  3. 模型名称不匹配")
        print(f"  4. 网络连接问题")
        return False
    
    # 4. 完整性测试
    print("\n🎯 步骤 4: 完整性测试")
    try:
        test_messages = [
            ChatMessage(role="user", content="1+1等于几？直接回答数字。")
        ]
        
        print("  发送测试问题: '1+1等于几？'")
        response = await llm.achat(test_messages)
        
        print(f"✅ 完整性测试通过:")
        print(f"  响应: {response.message.content}")
        
    except Exception as e:
        print(f"⚠️  完整性测试出现问题: {e}")
        return False
    
    # 成功
    print("\n" + "=" * 60)
    print("✅ 所有测试通过！本地模型配置可用！")
    print("=" * 60)
    print("\n💡 下一步:")
    print("  - 可以直接运行 DroidRun 任务")
    print("  - 模型将自动使用你配置的本地服务")
    print()
    
    return True


if __name__ == "__main__":
    try:
        result = asyncio.run(test_model())
        exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  测试被用户中断")
        exit(1)
    except Exception as e:
        print(f"\n\n❌ 测试出现未预期的错误: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
