# DroidRun WebSocket 服务器

## 概述

DroidRun WebSocket 服务器提供了通过 WebSocket 协议与移动 APP 端通信的能力，替代了传统的 ADB 通信方式。

## 功能特性

- ✅ 支持多设备并发连接
- ✅ 标准化的消息协议
- ✅ 灵活的消息路由机制
- ✅ 心跳保活机制
- ✅ 会话管理
- ✅ 错误处理和日志记录

## 快速开始

### 1. 启动服务器

#### 方式 1: 使用独立启动脚本（推荐）⭐

```bash
# 使用默认配置（最简单）
python server.py

# 自定义端口和主机
python server.py --host 0.0.0.0 --port 8765

# 启用调试模式
python server.py --debug

# 完整参数示例
python server.py --host 0.0.0.0 --port 8765 --path /ws --heartbeat-interval 30 --debug
```

**优点**:
- ✅ 不依赖 CLI 系统
- ✅ 不需要 LLM 初始化
- ✅ 一键启动，简单快速
- ✅ 支持命令行参数配置

#### 方式 2: 使用 CLI 命令

```bash
# 使用默认配置
droidrun server

# 自定义端口和主机
droidrun server --host 0.0.0.0 --port 8765

# 启用调试模式
droidrun server --debug
```

#### 方式 3: 使用独立模块脚本

```bash
python -m droidrun.server.start_server
```

#### 方式 4: 在代码中启动

```python
import asyncio
from droidrun.config import get_config_manager
from droidrun.server import WebSocketServer

async def main():
    config_manager = get_config_manager()
    server = WebSocketServer(config_manager=config_manager)
    await server.start()

asyncio.run(main())
```

### 2. 配置

在 `droidrun.yaml` 或环境变量中配置：

```yaml
server:
  mode: "server"  # "client" | "server"
  server_host: "0.0.0.0"
  server_port: 8765
  websocket_path: "/ws"
  device_id_header: "X-Device-ID"
  timeout: 30
  heartbeat_interval: 30
  max_connections: 100
```

或使用环境变量：

```bash
export SERVER_MODE=server
export SERVER_PORT=8765
export SERVER_HOST=0.0.0.0
```

### 3. APP 端连接

APP 端只需要通过标准的 WebSocket URL 连接即可使用服务端的所有能力。

**连接方式：**

```python
# 方式 1: 通过查询参数（推荐）
ws://localhost:8765/ws?device_id=your_device_id

# 方式 2: 通过 HTTP 头
URL: ws://localhost:8765/ws
Header: X-Device-ID: your_device_id
```

**详细连接指南：**

请参考 [APP_CONNECTION_GUIDE.md](./APP_CONNECTION_GUIDE.md)，包含：
- 完整的 Python/Java/JavaScript 示例代码
- 消息协议说明
- 常见命令示例
- 故障排查指南

## 消息协议

### 消息格式

所有消息遵循统一格式：

```json
{
  "version": "1.0",
  "type": "message_type",
  "timestamp": "2024-01-01T00:00:00",
  "request_id": "optional_request_id",
  "device_id": "optional_device_id",
  "status": "success" | "error",
  "data": { ... },
  "error": "error_message"
}
```

### 消息类型

- `server_ready` - 服务器就绪消息
- `heartbeat` - 心跳消息
- `heartbeat_ack` - 心跳确认
- `command` - 命令消息
- `command_response` - 命令响应
- `error` - 错误消息

### 命令消息示例

```json
{
  "version": "1.0",
  "type": "command",
  "timestamp": "2024-01-01T00:00:00",
  "request_id": "req_123",
  "device_id": "device_001",
  "status": "success",
  "data": {
    "command": "get_state",
    "params": {}
  }
}
```

### 命令响应示例

```json
{
  "version": "1.0",
  "type": "command_response",
  "timestamp": "2024-01-01T00:00:00",
  "request_id": "req_123",
  "device_id": "device_001",
  "status": "success",
  "data": {
    "a11y_tree": [...],
    "phone_state": {...}
  }
}
```

## 使用 WebSocketTools

在代码中使用 WebSocketTools 替代 AdbTools：

```python
from droidrun.tools import WebSocketTools
from droidrun.server import SessionManager
from droidrun.config import get_config_manager

config_manager = get_config_manager()
session_manager = SessionManager()

# 创建 WebSocketTools 实例
tools = WebSocketTools(
    device_id="device_001",
    session_manager=session_manager,
    config_manager=config_manager
)

# 注册到服务器（用于响应处理）
server.register_tools_instance("device_001", tools)

# 使用工具
state = tools.get_state()
tools.tap_by_index(0)
```

## 测试

### 运行测试客户端

```bash
python -m droidrun.server.example_client
```

### 测试服务器连接

```bash
# 使用 websocat (需要安装)
echo '{"type":"heartbeat","version":"1.0","timestamp":"2024-01-01T00:00:00"}' | websocat ws://localhost:8765/ws?device_id=test
```

## 架构说明

### 组件

1. **WebSocketServer** - WebSocket 服务器主类
2. **SessionManager** - 会话管理器
3. **MessageProtocol** - 消息协议定义
4. **MessageRouter** - 消息路由器
5. **WebSocketTools** - WebSocket 工具实现

### 消息流程

```
APP 端                    WebSocketServer                WebSocketTools
  |                            |                              |
  |--- 连接请求 --------------->|                              |
  |<-- server_ready -----------|                              |
  |                            |                              |
  |--- heartbeat ------------>|                              |
  |                            |-- 更新心跳                    |
  |<-- heartbeat_ack ---------|                              |
  |                            |                              |
  |                            |--- command ---------------->|
  |                            |                              |
  |<-- command ----------------|                              |
  |                            |                              |
  |--- command_response ------>|                              |
  |                            |-- 路由到处理器               |
  |                            |                              |
  |                            |--- 响应 -------------------->|
```

## 故障排除

### 常见问题

1. **连接被拒绝**
   - 检查服务器是否启动
   - 检查端口是否被占用
   - 检查防火墙设置

2. **设备 ID 未识别**
   - 确保通过查询参数或 HTTP 头提供设备 ID
   - 检查设备 ID 格式是否正确

3. **消息格式错误**
   - 确保消息遵循标准协议格式
   - 检查消息类型是否正确
   - 验证必需字段是否存在

## 开发

### 添加新的消息类型

1. 在 `MessageType` 枚举中添加新类型
2. 在 `MessageProtocol` 中添加创建方法（如需要）
3. 在 `WebSocketServer._setup_message_handlers()` 中注册处理器
4. 实现处理器方法

### 扩展功能

- 添加认证机制
- 添加消息压缩
- 添加消息加密
- 添加性能监控
- 添加统计信息

## 许可证

与 DroidRun 项目相同。

