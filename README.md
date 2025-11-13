# DroidAgent

<div align="center">

![DroidAgent Logo](docs/logo/droidagent-logo.png)

**🤖 基于大语言模型的 Android 设备智能控制框架**

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.3.9-orange.svg)](pyproject.toml)

[English](README_EN.md) | 中文

</div>

## 📖 概述

DroidAgent 是一个强大的 Android 设备自动化控制框架，通过大语言模型（LLM）智能理解用户意图，自动执行复杂的移动设备操作任务。支持传统 ADB 连接和现代 WebSocket 通信两种方式，为移动应用测试、自动化运维和智能交互提供完整解决方案。

## ✨ 核心特性

### 🧠 智能代理系统
- **CodeActAgent**: 基于 ReAct 循环的代码生成执行代理
- **DroidAgent**: 专门针对 Android 设备优化的智能控制代理
- **记忆系统**: 支持情景记忆，从历史经验中学习优化

### 🌐 双通信模式
- **ADB 模式**: 传统 USB/TCP 连接，稳定可靠
- **WebSocket 模式**: 现代化实时通信，支持多设备并发

### 🛠️ 丰富的工具集
- **UI 操作**: 点击、滑动、输入、截图等基础操作
- **应用管理**: 安装、卸载、启动、停止应用
- **系统控制**: 设备状态查询、系统设置修改
- **文件操作**: 文件传输、目录管理

### 🎯 高级功能
- **视觉理解**: 支持截图分析和 UI 元素识别
- **多模型支持**: OpenAI、Anthropic、Google Gemini、阿里通义千问等
- **配置管理**: 统一的 YAML 配置系统
- **性能监控**: 详细的执行日志和性能分析

## 🚀 快速开始

### 环境要求

- Python 3.11+
- Android 设备（启用开发者选项和 USB 调试）
- ADB 工具（可选，用于 ADB 模式）

### 安装

```bash
# 克隆项目
git clone https://github.com/droidagent/droidagent.git
cd droidagent

# 安装依赖
pip install -e .

# 或使用 uv（推荐）
uv sync
```

### 配置

1. **复制配置文件**
```bash
cp droidagent.yaml.example droidagent.yaml
```

2. **设置环境变量**
```bash
# 创建 .env 文件
echo "ALIYUN_API_KEY=your_api_key_here" > .env
```

3. **修改配置文件**
```yaml
# droidagent.yaml
droidagent:
  api:
    api_key: null  # 从环境变量获取
    model: "qwen-plus"
    api_base: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  
  agent:
    max_steps: 20
    vision: true
  
  memory:
    enabled: true
    similarity_threshold: 0.85
```

### 使用方式

#### 方式 1: WebSocket 服务器模式（推荐）

```bash
# 启动 WebSocket 服务器
python server.py

# 自定义配置
python server.py --host 0.0.0.0 --port 8765 --debug

# 完整参数示例
python server.py --host 0.0.0.0 --port 8765 --path /ws --heartbeat-interval 30 --debug
```

**优点**:
- ✅ 不依赖 CLI 系统
- ✅ 不需要 LLM 初始化
- ✅ 一键启动，简单快速
- ✅ 支持命令行参数配置

#### 方式 2: 传统 ADB 模式

```bash
# 直接运行主程序
python main.py

# 使用 CLI 命令
droidagent run --task "打开微信"
```

#### 方式 3: 编程接口

```python
import asyncio
from droidagent import AdbTools, DroidAgent
from droidagent.config import get_config_manager
from llama_index.llms.openai_like import OpenAILike

async def main():
    # 初始化工具和配置
    tools = AdbTools()
    config_manager = get_config_manager()
    
    # 设置 LLM
    llm = OpenAILike(
        model="qwen-plus",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="your_api_key"
    )
    
    # 创建代理
    agent = DroidAgent(llm=llm, tools=tools)
    
    # 执行任务
    result = await agent.run("帮我打开微信并发送消息给张三")
    print(f"任务结果: {result}")

asyncio.run(main())
```

## 📱 支持的操作

### 基础 UI 操作
- **点击**: 通过坐标、索引或文本点击元素
- **滑动**: 支持各种方向的滑动手势
- **输入**: 文本输入和特殊按键
- **截图**: 获取设备屏幕截图
- **等待**: 智能等待元素出现或状态变化

### 应用管理
- **安装/卸载**: 应用包管理
- **启动/停止**: 应用生命周期控制
- **权限管理**: 动态权限授予
- **数据清理**: 应用数据和缓存清理

### 系统控制
- **设备信息**: 获取设备状态和属性
- **网络管理**: WiFi 和移动网络控制
- **文件操作**: 文件传输和目录管理
- **系统设置**: 各种系统参数调整

## 🧠 智能特性

### 视觉理解
```python
# 启用视觉功能
agent = DroidAgent(llm=llm, tools=tools, vision=True)

# 智能识别和操作
await agent.run("找到登录按钮并点击")
await agent.run("滚动到页面底部找到提交按钮")
```

### 记忆系统
```python
# 配置记忆功能
droidagent:
  memory:
    enabled: true
    similarity_threshold: 0.85
    max_experiences: 1000

# 代理会自动学习和优化操作
await agent.run("像上次一样登录微信")  # 会复用之前的成功经验
```

### 多步骤任务
```python
# 复杂任务自动分解
await agent.run("""
请帮我完成以下任务：
1. 打开淘宝应用
2. 搜索"iPhone 15"
3. 选择价格在8000-10000之间的商品
4. 加入购物车
5. 截图保存结果
""")
```

## 🔧 配置详解

### API 配置
```yaml
droidagent:
  api:
    # 阿里通义千问
    api_key: null  # 从环境变量 ALIYUN_API_KEY 获取
    model: "qwen-plus"
    api_base: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    # OpenAI
    # api_key: "sk-..."
    # model: "gpt-4"
    # api_base: "https://api.openai.com/v1"
    
    timeout: 30
    max_retries: 3
```

### 代理配置
```yaml
droidagent:
  agent:
    max_steps: 20              # 最大执行步数
    vision: true               # 启用视觉理解
    reasoning: false           # 启用推理模式
    reflection: false          # 启用反思机制
    save_trajectories: "step"  # 保存执行轨迹
```

### 工具配置
```yaml
droidagent:
  tools:
    action_wait_time: 0.5      # 操作间隔时间
    screenshot_wait_time: 1.0  # 截图等待时间
    default_swipe_duration: 300 # 滑动持续时间
```

## 📊 性能监控

### 执行日志
```python
# 启用详细日志
droidagent:
  system:
    debug: true
    log_level: "DEBUG"

# 查看执行统计
result = await agent.run("打开设置")
print(f"执行步数: {result['codeact_steps']}")
print(f"代码执行次数: {result['code_executions']}")
```

### 性能分析
- **WebSocket vs ADB**: 详见 [性能分析文档](docs/performance_analysis_adb_vs_websocket.md)
- **二进制传输优化**: 详见 [传输优化分析](docs/websocket_binary_transmission_analysis.md)

## 🌐 WebSocket 服务器

### 启动服务器
```bash
# 启动 WebSocket 服务器
python server.py --host 0.0.0.0 --port 8765

# 查看服务器状态
curl http://localhost:8765/health
```

### 客户端连接
```python
import websocket
import json

def on_message(ws, message):
    data = json.loads(message)
    print(f"收到消息: {data}")

def on_open(ws):
    # 发送心跳
    ws.send(json.dumps({
        "type": "heartbeat",
        "device_id": "test_device"
    }))

ws = websocket.WebSocketApp(
    "ws://localhost:8765/ws?device_id=test_device",
    on_message=on_message,
    on_open=on_open
)
ws.run_forever()
```

## 🧪 测试和调试

### 运行测试
```bash
# 运行单元测试
python -m pytest tests/

# 运行集成测试
python -m pytest tests/integration/

# 性能测试
python -m pytest tests/performance/
```

### 调试模式
```bash
# 启用调试模式
python main.py --debug

# 查看详细日志
tail -f logs/droidagent.log
```

## 📚 文档和示例

### 完整文档
- [API 参考](docs/v3/sdk/)
- [架构设计](docs/v3/architecture/)
- [最佳实践](docs/v3/best-practices/)

### 示例代码
- [基础操作示例](examples/basic_operations.py)
- [复杂任务示例](examples/complex_tasks.py)
- [WebSocket 客户端示例](examples/websocket_client.py)

## 🤝 贡献指南

### 开发环境设置
```bash
# 克隆项目
git clone https://github.com/droidagent/droidagent.git
cd droidagent

# 安装开发依赖
uv sync --group dev

# 运行代码检查
ruff check .
ruff format .

# 运行安全检查
bandit -r droidagent/
safety check
```

### 提交规范
- 使用语义化提交信息
- 添加相应的测试用例
- 更新相关文档
- 通过所有 CI 检查

## 📄 许可证

本项目采用 [MIT 许可证](LICENSE)。

## 🙏 致谢

感谢所有为 DroidAgent 项目做出贡献的开发者和用户。

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给我们一个 Star！**

[GitHub](https://github.com/droidagent/droidagent) | [文档](https://docs.droidagent.ai/) | [问题反馈](https://github.com/droidagent/droidagent/issues)

</div>

