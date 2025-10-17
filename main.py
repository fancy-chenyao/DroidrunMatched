#!/usr/bin/env python3
import asyncio
import time
from datetime import datetime, timedelta
from droidrun import AdbTools, DroidAgent
from llama_index.llms.openai_like import OpenAILike

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
    
    # set up 阿里百炼 llm
    llm = OpenAILike(
        model="qwen-plus",  # 阿里百炼的模型名称
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",  # 阿里百炼的OpenAI兼容接口
        api_key="sk-c2cc873160714661aa76b6d5ab7239bf",  # 你的阿里百炼API密钥
        is_chat_model=True,  # droidrun需要聊天模型支持
    )
    
    llm_init_time = time.time()
    print(f"🤖 LLM 初始化完成 (耗时: {llm_init_time - tools_init_time:.2f}秒)")
    
    # Create agent with memory system enabled
    agent_init_start = time.time()
    agent = DroidAgent(
        goal="打开EmpLab应用，进入请休假系统，提交2025年10月28日到2025年11月29日的年休假申请。请假事由：计划休息，拟前往地区：北京。请尝试完成整个流程，包括登录（如果需要的话）和提交申请。",
        llm=llm,
        tools=tools,
        enable_memory=True,  # 启用记忆系统
        memory_similarity_threshold=0.85,  # 相似度阈值
        memory_storage_dir="experiences",  # 存储目录
        save_trajectories="step",  # 保存轨迹
        debug=True,  # 启用调试模式
        max_steps=20,  # 增加最大步数
        reasoning=False    # 启用推理模式，让Agent更智能地处理复杂任务
    )
    
    agent_init_time = time.time()
    print(f"🧠 记忆系统已启用 (Agent初始化耗时: {agent_init_time - agent_init_start:.2f}秒)")
    print("📁 经验存储目录: experiences/")
    print("💾 轨迹保存级别: step")
    print("🎯 目标: 打开EmpLab应用并完成请假申请流程")
    
    # 检查是否有相似经验
    memory_check_start = time.time()
    if hasattr(agent, 'memory_manager') and agent.memory_manager:
        similar_experiences = agent.memory_manager.find_similar_experiences(
            "打开EmpLab应用并完成请假申请流程", 
            threshold=0.8
        )
        memory_check_time = time.time()
        print(f"🔍 记忆检查完成 (耗时: {memory_check_time - memory_check_start:.2f}秒)")
        
        if similar_experiences:
            print(f"🔥 发现 {len(similar_experiences)} 个相似经验，将使用热启动")
            for i, exp in enumerate(similar_experiences[:3]):
                print(f"  {i+1}. {exp.goal} (相似度: {exp.similarity_score:.2f})")
        else:
            print("❄️ 未发现相似经验，将使用冷启动")
    
    print(f"\n🚀 开始执行任务... (总初始化耗时: {memory_check_time - start_time:.2f}秒)")
    
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
    print(f"  🔧 初始化时间: {(memory_check_time - start_time):.2f}秒")
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
        if experiences:
            latest_exp = experiences[-1]
            print(f"最新经验: {latest_exp.goal}")
            print(f"执行成功: {latest_exp.success}")
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