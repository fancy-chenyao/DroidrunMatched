#!/usr/bin/env python3
import asyncio
import os
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from droidrun import AdbTools, DroidAgent
from droidrun.config import get_config_manager
from llama_index.llms.openai_like import OpenAILike

# 加载环境变量
load_dotenv()

async def main():
    print("🧠 DroidRun 记忆系统测试")
    print("=" * 40)
    
    # 记录开始时间
    start_time = time.time()
    start_datetime = datetime.now()
    print(f"🕐 开始时间: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Load tools
    tools = AdbTools()
    tools_init_time = time.time()
    print(f"🔧 工具初始化完成 (耗时: {tools_init_time - start_time:.2f}秒)")
    
    # 获取统一配置管理器
    config_manager = get_config_manager()
    
    # 从配置管理器获取API配置
    api_config = config_manager.get_api_config()
    memory_config = config_manager.get_memory_config()
    system_config = config_manager.get_system_config()
    
    # 验证必要的API密钥
    if not api_config.api_key:
        print("❌ 错误: 未找到 ALIYUN_API_KEY 环境变量")
        print("请确保 .env 文件存在并包含正确的 API 密钥")
        return
    
    print(f"🔑 使用模型: {api_config.model}")
    print(f"🌐 API Base: {api_config.api_base}")
    print(f"🎯 相似度阈值: {memory_config.similarity_threshold}")
    print(f"📊 最大步数: {config_manager.get('agent.max_steps', 20)}")
    print(f"🐛 调试模式: {'开启' if system_config.debug else '关闭'}")
    
    # set up 阿里百炼 llm
    llm = OpenAILike(
        model=api_config.model,
        api_base=api_config.api_base,
        api_key=api_config.api_key,
        is_chat_model=True,  # droidrun需要聊天模型支持
    )
    
    llm_init_time = time.time()
    print(f"🤖 LLM 初始化完成 (耗时: {llm_init_time - tools_init_time:.2f}秒)")
    
    # Create agent with unified configuration
    agent_init_start = time.time()
    agent = DroidAgent(
        # goal="打开EmpLab应用，进入请休假系统，提交2025年11月24日到2025年11月25日的年休假申请。请假事由：出去玩，拟前往地区：北京。请尝试完成整个流程，包括登录（如果需要的话）和提交申请。",
        goal="帮我申请一个年休假，12月2号到3号，理由和地点分别为探亲和上海。",
        # goal="请帮我提交一个出差申请，出差人为张博涛，出差日期为2025年11月10日，出差性质为客户拜访，费用责任中心为建行集团金融科技创新中心，非业务专项，预算项目为交通费，预算事项为日常运营，出差事由为拜访客户。",
        # goal="请帮我提交一个出差申请，出差人为张博涛，出差事由为拜访客户。",
        llm=llm,
        tools=tools,
        config_manager=config_manager,  # 使用统一配置管理器
    )
    
    agent_init_time = time.time()
    print(f"🧠 记忆系统已启用 (Agent初始化耗时: {agent_init_time - agent_init_start:.2f}秒)")
    print(f"📁 经验存储目录: {memory_config.storage_dir}")
    print(f"💾 轨迹保存级别: {config_manager.get('agent.save_trajectories', 'step')}")
    print(f"🎯 目标: {agent.goal}")
    
    # 显示配置摘要
    print(f"\n📋 配置摘要:")
    print(config_manager.get_summary())
    
    print(f"\n🚀 开始执行任务... (总初始化耗时: {agent_init_time - start_time:.2f}秒)")
    
    # Run agent
    task_start_time = time.time()
    result = await agent.run()
    task_end_time = time.time()
    
    # 计算总时间
    total_end_time = time.time()
    total_duration = total_end_time - start_time
    task_duration = task_end_time - task_start_time
    end_datetime = datetime.now()
    
    print(f"\n✅ 执行完成!")
    print(f"Success: {result['success']}")
    if result.get('output'):
        print(f"Output: {result['output']}")
    
    # 显示详细的时间统计
    print(f"\n⏱️ 时间统计:")
    print(f"  🕐 开始时间: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  🕐 结束时间: {end_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  ⏰ 总耗时: {total_duration:.2f}秒 ({timedelta(seconds=int(total_duration))})")
    print(f"  🎯 任务执行时间: {task_duration:.2f}秒 ({timedelta(seconds=int(task_duration))})")
    print(f"  🔧 初始化时间: {(agent_init_time - start_time):.2f}秒")
    print(f"  🚀 任务执行占比: {(task_duration/total_duration*100):.1f}%")
    
    # 显示执行步骤统计
    if result.get('steps'):
        steps = result['steps']
        if steps > 0:
            avg_step_time = task_duration / steps
            print(f"  📊 执行步骤: {steps}步")
            print(f"  ⚡ 平均每步耗时: {avg_step_time:.2f}秒")
    
    # 显示记忆系统状态
    if hasattr(agent, 'memory_manager') and agent.memory_manager:
        experiences = agent.memory_manager.get_all_experiences()
        print(f"\n🧠 记忆系统状态:")
        print(f"总经验数量: {len(experiences)}")
        # if experiences:
        #     latest_exp = experiences[-1]
        #     print(f"最新经验: {latest_exp.goal}")
        #     print(f"执行成功: {latest_exp.success}")
        #     print(f"经验ID: {latest_exp.id}")
        # 按时间戳排序，确保获取最新经验（避免依赖列表顺序）
        if experiences:
            # 按 timestamp 降序排序（最新的在最前）
            sorted_experiences = sorted(experiences, key=lambda x: x.timestamp, reverse=True)
            latest_exp = sorted_experiences[0]
            print(f"最新经验: {latest_exp.goal}")
            print(f"执行成功: {latest_exp.success}")
            print(f"经验类型: {latest_exp.type}")  # 新增：显示经验类型（符合按类型存储逻辑）
            print(f"经验ID: {latest_exp.id}")

    # 性能分析
    print(f"\n📈 性能分析:")
    if result['success']:
        print(f"  ✅ 任务执行成功")
        if task_duration < 30:
            print(f"  🚀 执行速度: 快速 (< 30秒)")
        elif task_duration < 60:
            print(f"  🏃 执行速度: 中等 (30-60秒)")
        else:
            print(f"  🐌 执行速度: 较慢 (> 60秒)")
    else:
        print(f"  ❌ 任务执行失败")
    
    print(f"\n📁 检查以下目录查看详细信息:")
    print(f"  - experiences/ (记忆经验)")
    print(f"  - trajectories/ (执行轨迹)")

if __name__ == "__main__":
    asyncio.run(main())