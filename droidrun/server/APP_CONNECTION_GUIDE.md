# APP 端连接指南

## 概述

DroidRun WebSocket 服务器启动后，APP 端只需要通过标准的 WebSocket URL 连接即可使用服务端的所有能力。

## 连接方式

### 1. 服务器地址

服务器启动后会在指定端口监听，默认地址为：
```
ws://localhost:8765/ws
```

或使用服务器IP地址：
```
ws://192.168.1.100:8765/ws
```

### 2. 设备ID传递方式

APP 端连接时必须提供设备ID，有两种方式：

#### 方式 1: 通过查询参数（推荐）
```
ws://localhost:8765/ws?device_id=your_device_id
```

**优点：**
- 简单直接，URL 中直接包含设备ID
- 易于调试和测试
- 适用于大多数场景

#### 方式 2: 通过 HTTP 头
```
URL: ws://localhost:8765/ws
Header: X-Device-ID: your_device_id
```

**优点：**
- 更符合 RESTful 风格
- 设备ID不会出现在 URL 中（更安全）

## 完整示例

### Python 示例

```python
import asyncio
import json
import websockets
from droidrun.server.message_protocol import MessageProtocol, MessageType

async def connect_to_server():
    """连接到 DroidRun WebSocket 服务器"""
    # 方式 1: 通过查询参数传递设备ID
    device_id = "my_device_001"
    uri = f"ws://localhost:8765/ws?device_id={device_id}"
    
    try:
        async with websockets.connect(uri) as websocket:
            print(f"✅ 已连接到服务器: {uri}")
            
            # 1. 接收欢迎消息（服务器连接成功后自动发送）
            welcome = await websocket.recv()
            welcome_data = json.loads(welcome)
            print(f"📨 收到欢迎消息: {welcome_data}")
            
            # 2. 发送心跳（保持连接）
            async def send_heartbeat():
                while True:
                    heartbeat = MessageProtocol.create_heartbeat_message(device_id=device_id)
                    await websocket.send(json.dumps(heartbeat))
                    await asyncio.sleep(30)  # 每30秒发送一次心跳
            
            # 启动心跳任务
            heartbeat_task = asyncio.create_task(send_heartbeat())
            
            # 3. 监听服务器命令
            async def listen_commands():
                async for message in websocket:
                    try:
                        msg_data = json.loads(message)
                        msg_type = msg_data.get("type")
                        
                        if msg_type == "command":
                            # 处理服务器发送的命令
                            command = msg_data.get("data", {}).get("command")
                            request_id = msg_data.get("request_id")
                            
                            print(f"📥 收到命令: {command}")
                            
                            # 执行命令（这里是示例，实际需要调用 Android 系统 API）
                            result = execute_command(command)
                            
                            # 发送命令响应
                            response = MessageProtocol.create_command_response(
                                request_id=request_id,
                                status="success" if result else "error",
                                data={"result": result},
                                device_id=device_id
                            )
                            await websocket.send(json.dumps(response))
                            print(f"📤 发送命令响应: {response}")
                        
                        elif msg_type == "heartbeat_ack":
                            # 心跳确认
                            print("💓 收到心跳确认")
                        
                    except Exception as e:
                        print(f"❌ 处理消息错误: {e}")
            
            # 启动命令监听任务
            listen_task = asyncio.create_task(listen_commands())
            
            # 等待任务完成
            await asyncio.gather(heartbeat_task, listen_task)
            
    except Exception as e:
        print(f"❌ 连接错误: {e}")
        import traceback
        traceback.print_exc()

def execute_command(command: str):
    """执行命令（示例，实际需要调用 Android 系统 API）"""
    # 这里应该调用 Android 无障碍服务或系统 API 来执行命令
    # 例如：获取 UI 状态、点击、滑动等
    return {"executed": True, "command": command}

if __name__ == "__main__":
    asyncio.run(connect_to_server())
```

### Android/Java 示例

```java
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import okio.ByteString;
import org.json.JSONObject;

public class DroidRunClient {
    private static final String SERVER_URL = "ws://192.168.1.100:8765/ws";
    private static final String DEVICE_ID = "my_device_001";
    private WebSocket webSocket;
    private OkHttpClient client;
    
    public void connect() {
        // 方式 1: 通过查询参数传递设备ID
        String url = SERVER_URL + "?device_id=" + DEVICE_ID;
        
        Request request = new Request.Builder()
            .url(url)
            .build();
        
        client = new OkHttpClient();
        webSocket = client.newWebSocket(request, new WebSocketListener() {
            @Override
            public void onOpen(WebSocket webSocket, Response response) {
                System.out.println("✅ 已连接到服务器");
            }
            
            @Override
            public void onMessage(WebSocket webSocket, String text) {
                try {
                    JSONObject message = new JSONObject(text);
                    String type = message.getString("type");
                    
                    if ("server_ready".equals(type)) {
                        System.out.println("📨 收到欢迎消息: " + message);
                        // 开始发送心跳
                        startHeartbeat();
                    } else if ("command".equals(type)) {
                        // 处理服务器命令
                        handleCommand(message);
                    } else if ("heartbeat_ack".equals(type)) {
                        System.out.println("💓 收到心跳确认");
                    }
                } catch (Exception e) {
                    System.err.println("❌ 处理消息错误: " + e.getMessage());
                }
            }
            
            @Override
            public void onFailure(WebSocket webSocket, Throwable t, Response response) {
                System.err.println("❌ 连接失败: " + t.getMessage());
            }
            
            @Override
            public void onClosed(WebSocket webSocket, int code, String reason) {
                System.out.println("🔌 连接已关闭");
            }
        });
    }
    
    private void startHeartbeat() {
        // 每30秒发送一次心跳
        new Thread(() -> {
            while (webSocket != null) {
                try {
                    JSONObject heartbeat = new JSONObject();
                    heartbeat.put("version", "1.0");
                    heartbeat.put("type", "heartbeat");
                    heartbeat.put("device_id", DEVICE_ID);
                    heartbeat.put("timestamp", System.currentTimeMillis());
                    
                    webSocket.send(heartbeat.toString());
                    Thread.sleep(30000);
                } catch (Exception e) {
                    System.err.println("❌ 发送心跳错误: " + e.getMessage());
                    break;
                }
            }
        }).start();
    }
    
    private void handleCommand(JSONObject commandMessage) {
        try {
            String requestId = commandMessage.getString("request_id");
            JSONObject data = commandMessage.getJSONObject("data");
            String command = data.getString("command");
            
            System.out.println("📥 收到命令: " + command);
            
            // 执行命令（调用 Android 系统 API）
            JSONObject result = executeCommand(command);
            
            // 发送响应
            JSONObject response = new JSONObject();
            response.put("version", "1.0");
            response.put("type", "command_response");
            response.put("request_id", requestId);
            response.put("device_id", DEVICE_ID);
            response.put("status", "success");
            response.put("data", result);
            response.put("timestamp", System.currentTimeMillis());
            
            webSocket.send(response.toString());
            System.out.println("📤 发送命令响应");
            
        } catch (Exception e) {
            System.err.println("❌ 处理命令错误: " + e.getMessage());
        }
    }
    
    private JSONObject executeCommand(String command) {
        // 这里应该调用 Android 无障碍服务或系统 API 来执行命令
        // 例如：获取 UI 状态、点击、滑动等
        JSONObject result = new JSONObject();
        result.put("executed", true);
        result.put("command", command);
        return result;
    }
    
    public void disconnect() {
        if (webSocket != null) {
            webSocket.close(1000, "Normal closure");
        }
        if (client != null) {
            client.dispatcher().executorService().shutdown();
        }
    }
}
```

### JavaScript/Web 示例

```javascript
// 在 Web 环境中使用
const DEVICE_ID = 'my_device_001';
const SERVER_URL = `ws://localhost:8765/ws?device_id=${DEVICE_ID}`;

const ws = new WebSocket(SERVER_URL);

ws.onopen = () => {
    console.log('✅ 已连接到服务器');
};

ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    const type = message.type;
    
    if (type === 'server_ready') {
        console.log('📨 收到欢迎消息:', message);
        // 开始发送心跳
        startHeartbeat();
    } else if (type === 'command') {
        // 处理服务器命令
        handleCommand(message);
    } else if (type === 'heartbeat_ack') {
        console.log('💓 收到心跳确认');
    }
};

ws.onerror = (error) => {
    console.error('❌ 连接错误:', error);
};

ws.onclose = () => {
    console.log('🔌 连接已关闭');
};

function startHeartbeat() {
    setInterval(() => {
        const heartbeat = {
            version: '1.0',
            type: 'heartbeat',
            device_id: DEVICE_ID,
            timestamp: Date.now()
        };
        ws.send(JSON.stringify(heartbeat));
    }, 30000); // 每30秒发送一次
}

function handleCommand(commandMessage) {
    const requestId = commandMessage.request_id;
    const command = commandMessage.data.command;
    
    console.log('📥 收到命令:', command);
    
    // 执行命令（这里是示例，实际需要调用相应的 API）
    const result = executeCommand(command);
    
    // 发送响应
    const response = {
        version: '1.0',
        type: 'command_response',
        request_id: requestId,
        device_id: DEVICE_ID,
        status: 'success',
        data: result,
        timestamp: Date.now()
    };
    
    ws.send(JSON.stringify(response));
    console.log('📤 发送命令响应');
}

function executeCommand(command) {
    // 执行命令的逻辑
    return { executed: true, command: command };
}
```

## 消息协议

### 服务器发送的消息类型

1. **server_ready** - 服务器就绪消息（连接成功后立即发送）
```json
{
  "version": "1.0",
  "type": "server_ready",
  "device_id": "your_device_id",
  "timestamp": 1234567890,
  "data": {
    "message": "Server is ready"
  }
}
```

2. **command** - 服务器发送的命令
```json
{
  "version": "1.0",
  "type": "command",
  "request_id": "unique_request_id",
  "device_id": "your_device_id",
  "timestamp": 1234567890,
  "data": {
    "command": "get_state",
    "params": {}
  }
}
```

3. **heartbeat_ack** - 心跳确认
```json
{
  "version": "1.0",
  "type": "heartbeat_ack",
  "device_id": "your_device_id",
  "timestamp": 1234567890
}
```

### APP 端发送的消息类型

1. **heartbeat** - 心跳消息
```json
{
  "version": "1.0",
  "type": "heartbeat",
  "device_id": "your_device_id",
  "timestamp": 1234567890
}
```

2. **command_response** - 命令响应
```json
{
  "version": "1.0",
  "type": "command_response",
  "request_id": "unique_request_id",
  "device_id": "your_device_id",
  "status": "success",
  "timestamp": 1234567890,
  "data": {
    "result": "命令执行结果"
  }
}
```

## 连接流程

1. **APP 端发起连接**
   - 使用 WebSocket URL 连接服务器
   - 通过查询参数或 HTTP 头传递设备ID

2. **服务器验证设备ID**
   - 如果设备ID有效，连接成功
   - 如果设备ID缺失，连接被拒绝（返回 4001 错误码）

3. **服务器发送欢迎消息**
   - 连接成功后立即发送 `server_ready` 消息

4. **APP 端开始发送心跳**
   - 每30秒（可配置）发送一次心跳消息
   - 服务器收到心跳后回复 `heartbeat_ack`

5. **服务器发送命令**
   - 当 CLI 执行任务时，服务器会向对应设备发送命令
   - APP 端收到命令后执行并返回响应

6. **APP 端断开连接**
   - 正常断开或异常断开都会被服务器检测到
   - 服务器会清理对应的会话

## 常见命令示例

### 获取 UI 状态
```json
{
  "version": "1.0",
  "type": "command",
  "request_id": "req_001",
  "data": {
    "command": "get_state"
  }
}
```

响应：
```json
{
  "version": "1.0",
  "type": "command_response",
  "request_id": "req_001",
  "status": "success",
  "data": {
    "a11y_tree": {...},
    "phone_state": {...}
  }
}
```

### 点击操作
```json
{
  "version": "1.0",
  "type": "command",
  "request_id": "req_002",
  "data": {
    "command": "tap",
    "params": {
      "x": 100,
      "y": 200
    }
  }
}
```

### 滑动操作
```json
{
  "version": "1.0",
  "type": "command",
  "request_id": "req_003",
  "data": {
    "command": "swipe",
    "params": {
      "x1": 100,
      "y1": 200,
      "x2": 300,
      "y2": 400,
      "duration": 500
    }
  }
}
```

## 注意事项

1. **设备ID必须唯一**：每个连接的设备必须有唯一的设备ID
2. **心跳必须保持**：如果超过60秒（默认）未收到心跳，服务器会断开连接
3. **命令响应必须包含 request_id**：确保服务器能正确匹配请求和响应
4. **错误处理**：APP 端应该妥善处理连接断开、命令执行失败等情况
5. **线程安全**：在 Android 中，WebSocket 操作应该在后台线程进行

## 测试连接

可以使用提供的测试客户端：

```bash
python -m droidrun.server.example_client
```

或使用在线 WebSocket 测试工具：
- 访问：`ws://localhost:8765/ws?device_id=test_device`
- 查看服务器日志确认连接成功

## 故障排查

### 连接被拒绝
- 检查设备ID是否正确传递
- 检查服务器是否正在运行
- 检查端口是否被占用

### 收不到命令
- 检查心跳是否正常发送
- 检查消息格式是否正确
- 查看服务器日志确认命令是否发送

### 响应超时
- 检查命令执行时间是否过长
- 检查网络连接是否稳定
- 考虑增加超时时间配置

