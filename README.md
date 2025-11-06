# DroidRun 移动端自动化执行系统

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./static/droidrun-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="./static/droidrun.png">
  <img src="./static/droidrun.png"  width="full">
</picture>

[![GitHub stars](https://img.shields.io/github/stars/droidrun/droidrun?style=social)](https://github.com/droidrun/droidrun/stargazers)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## 📖 项目概述

DroidRun 是一个基于 LLM 的移动端自动化执行系统，通过**移动端与服务端分离架构**实现智能设备控制。系统支持通过自然语言指令控制 Android 设备，实现复杂的自动化任务执行。

### 🏗️ 系统架构

```
┌─────────────────┐         WebSocket 协议        ┌─────────────────┐
│                 │   ◄─────────────────────────►  │                 │
│   移动端 APP    │                                │   服务端        │
│   (Android)     │   ◄─ 命令响应 / UI状态        │   (Python)      │
│                 │                                │                 │
│  - WebSocket    │   ──► 执行命令 / UI操作       │  - LLM Agent    │
│  - 无障碍服务   │                                │  - WebSocket    │
│  - UI控制       │                                │  - 记忆系统     │
└─────────────────┘                                └─────────────────┘
```

### ✨ 核心特性

- 🤖 **智能Agent控制**：基于 LLM 的智能决策，支持自然语言任务描述
- 📱 **移动端分离架构**：移动端 APP 通过 WebSocket 连接服务端，无需 ADB
- 🔄 **实时双向通信**：WebSocket 协议实现服务端与移动端的实时通信
- 🧠 **记忆系统**：学习历史执行经验，提升任务执行效率
- 🎯 **多设备支持**：支持多设备并发连接和控制
- 🔧 **灵活配置**：支持多种 LLM 提供商（OpenAI、Anthropic、Gemini、Ollama、DeepSeek 等）
- 📸 **视觉理解**：支持截图分析和 UI 状态识别

## 📁 项目结构

```
droidrun/
├── App/                    # 移动端 Android 应用
│   └── app/
│       └── src/main/
│           └── java/
│               ├── Agent/          # Agent 客户端代码
│               └── controller/     # UI 控制器
│
├── droidrun/               # 服务端核心代码
│   ├── server/            # WebSocket 服务器
│   │   ├── ws_server.py           # WebSocket 服务器实现
│   │   ├── session_manager.py     # 会话管理
│   │   ├── message_protocol.py    # 消息协议定义
│   │   └── APP_CONNECTION_GUIDE.md # APP 连接指南
│   │
│   ├── agent/             # LLM Agent 实现
│   │   ├── droid/         # DroidAgent 核心逻辑
│   │   ├── planner/       # 任务规划
│   │   └── context/       # 上下文管理
│   │
│   ├── tools/             # 设备控制工具
│   │   ├── websocket_tools.py    # WebSocket 工具实现
│   │   ├── adb.py                # ADB 工具（备用）
│   │   └── tools.py               # 工具基类
│   │
│   ├── config/            # 配置管理
│   │   ├── unified_config.py     # 统一配置
│   │   └── loader.py              # 配置加载器
│   │
│   └── cli/               # 命令行接口
│       └── main.py                # CLI 主程序
│
└── Server/                # 备用服务端实现（可选）
    └── main.py            # 旧版服务器入口
```

## 🚀 快速开始

### 环境要求

- Python 3.11+
- Android 设备或模拟器
- LLM API 密钥（OpenAI、Anthropic、Gemini 等）

### 安装步骤

#### 1. 安装服务端依赖

```bash
# 克隆项目
git clone <repository-url>
cd droidrun

# 安装 Python 依赖
pip install 'droidrun[google,anthropic,openai,deepseek,ollama,dev]'
```

#### 2. 配置环境变量

创建 `.env` 文件：

```bash
# LLM API 配置（选择一种）
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
GOOGLE_API_KEY=your_google_key

# 或使用阿里云百炼
ALIYUN_API_KEY=your_aliyun_key
```

或创建 `droidrun.yaml` 配置文件：

```yaml
droidrun:
  api:
    api_key: ${ALIYUN_API_KEY}
    model: "qwen-plus"
    api_base: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  
  system:
    debug: false
    timeout: 300
  
  memory:
    enabled: true
    similarity_threshold: 0.85
    storage_dir: "experiences"
```

#### 3. 编译并安装移动端 APP

```bash
cd App
./gradlew assembleDebug
adb install app/build/outputs/apk/debug/app-debug.apk
```

或使用 Android Studio 打开 `App` 目录进行编译安装。

#### 4. 配置移动端

在移动端 APP 中配置服务端地址：

- 打开 APP 设置
- 输入服务端 IP 地址和端口（默认：`localhost:8765`）
- 确保移动端与服务端在同一网络或使用端口转发

#### 5. 启动服务端

```bash
# 启动 WebSocket 服务器
droidrun server --host 0.0.0.0 --port 8765

# 或使用调试模式
droidrun server --debug
```

#### 6. 连接移动端

启动移动端 APP，APP 会自动连接到服务端（通过 WebSocket）。

#### 7. 执行任务

```bash
# 使用 CLI 执行任务
droidrun run "打开EmpLab应用，进入请休假系统，提交年休假申请"

# 或指定设备ID
droidrun run "打开设置并找到WiFi选项" --device-id your_device_id
```

## 📚 使用指南

### 服务端命令

```bash
# 启动服务器
droidrun server [选项]

选项:
  --host HOST        # 监听地址（默认: 0.0.0.0）
  --port PORT        # 监听端口（默认: 8765）
  --debug            # 启用调试模式
```

### 执行任务

```bash
# 基本用法
droidrun run "任务描述"

# 高级选项
droidrun run "任务描述" \
  --provider openai \
  --model gpt-4 \
  --steps 50 \
  --vision \
  --debug
```

### 配置说明

#### 服务器模式配置

在 `droidrun.yaml` 中配置：

```yaml
droidrun:
  server:
    mode: "server"           # "client" | "server"
    server_host: "0.0.0.0"    # 监听地址
    server_port: 8765        # 监听端口
    websocket_path: "/ws"     # WebSocket 路径
    heartbeat_interval: 30    # 心跳间隔（秒）
    timeout: 30               # 超时时间（秒）
```

## 🔌 APP 端连接指南

移动端 APP 通过 WebSocket 连接到服务端，详细连接指南请参考：

- **[APP 端连接指南](./droidrun/server/APP_CONNECTION_GUIDE.md)** - 包含完整的连接示例和消息协议说明

### 快速连接示例

**Python 示例：**
```python
import asyncio
import websockets

async def connect():
    device_id = "my_device_001"
    uri = f"ws://localhost:8765/ws?device_id={device_id}"
    async with websockets.connect(uri) as websocket:
        # 接收欢迎消息
        welcome = await websocket.recv()
        print(f"已连接: {welcome}")
```

**Android/Kotlin 示例：**
```kotlin
val deviceId = "my_device_001"
val url = "ws://192.168.1.100:8765/ws?device_id=$deviceId"
val request = Request.Builder().url(url).build()
val client = OkHttpClient()
val webSocket = client.newWebSocket(request, webSocketListener)
```

## 📡 消息协议

服务端与移动端通过标准化的消息协议通信：

### 消息格式

```json
{
  "version": "1.0",
  "type": "message_type",
  "timestamp": 1234567890,
  "request_id": "optional_request_id",
  "device_id": "device_identifier",
  "status": "success" | "error",
  "data": { ... }
}
```

### 主要消息类型

- `server_ready` - 服务器就绪（连接成功后发送）
- `heartbeat` - 心跳消息（保持连接）
- `command` - 服务器发送的命令
- `command_response` - 命令执行响应
- `error` - 错误消息

详细协议说明请参考 [APP_CONNECTION_GUIDE.md](./droidrun/server/APP_CONNECTION_GUIDE.md)

## 🎯 使用场景

- **自动化测试**：移动应用 UI 自动化测试
- **任务自动化**：执行重复性移动端操作
- **智能助手**：通过自然语言控制设备
- **远程协助**：远程控制移动设备执行任务
- **工作流自动化**：创建复杂的多步骤自动化流程

## 🛠️ 开发指南

### 添加新的命令类型

1. 在 `droidrun/server/message_protocol.py` 中添加消息类型
2. 在 `droidrun/tools/websocket_tools.py` 中实现命令处理
3. 在移动端实现对应的命令执行逻辑

### 扩展功能

- 添加新的设备控制命令
- 实现自定义 Agent 策略
- 扩展记忆系统功能
- 添加新的 LLM 提供商支持

## 📝 配置参考

完整配置选项请参考 `droidrun.yaml.example`：

```yaml
droidrun:
  # API 配置
  api:
    api_key: null
    model: "qwen-plus"
    api_base: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  
  # 系统配置
  system:
    debug: false
    timeout: 300
  
  # 记忆系统
  memory:
    enabled: true
    similarity_threshold: 0.85
    storage_dir: "experiences"
  
  # Agent 配置
  agent:
    max_steps: 20
    reasoning: false
    reflection: false
    vision: false
```

## 🔍 故障排查

### 连接问题

1. **移动端无法连接服务端**
   - 检查服务端是否启动：`droidrun server`
   - 检查网络连接和防火墙设置
   - 确认服务端 IP 和端口配置正确

2. **设备 ID 未识别**
   - 确保通过查询参数或 HTTP 头提供设备 ID
   - 检查设备 ID 格式是否正确

### 执行问题

1. **任务执行失败**
   - 启用调试模式：`droidrun run --debug`
   - 检查 LLM API 配置是否正确
   - 查看服务端日志获取详细错误信息

2. **命令执行超时**
   - 增加超时时间配置
   - 检查网络连接稳定性
   - 查看移动端日志确认命令是否收到

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件。

## 🤝 贡献

欢迎贡献！请随时提交 Pull Request。

## 📞 支持

- 问题反馈：[GitHub Issues](https://github.com/droidrun/droidrun/issues)
- 文档：[项目文档](./docs/)
- APP 连接指南：[APP_CONNECTION_GUIDE.md](./droidrun/server/APP_CONNECTION_GUIDE.md)

## 🙏 致谢

基于 [DroidRun](https://github.com/droidrun/droidrun) 框架开发，感谢原项目的贡献者。

---

**注意**：本项目是移动端自动化执行系统，移动端 APP 需要与服务端配合使用。确保在合法合规的前提下使用本系统。
