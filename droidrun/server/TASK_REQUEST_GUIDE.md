# 移动端任务请求指南

## 概述

移动端可以通过 WebSocket 向服务端发送任务请求，服务端会执行完整的 DroidAgent 流程（类似 `main.py`），并将执行结果返回给移动端。

## 消息格式

### 1. 任务请求消息 (TASK_REQUEST)

移动端发送任务请求：

```json
{
  "version": "1.0",
  "type": "task_request",
  "request_id": "unique_request_id_123",
  "device_id": "your_device_id",
  "timestamp": "2024-01-01T00:00:00.000Z",
  "data": {
    "goal": "请帮我请十一月10号到15号的年假,去海南旅游。",
    "options": {
      "max_steps": 15,
      "vision": true,
      "reasoning": false,
      "reflection": false,
      "debug": false,
      "save_trajectory": "step"
    }
  }
}
```

**字段说明**:
- `request_id`: 唯一请求ID，用于匹配响应
- `goal`: 任务目标（自然语言描述，必需）
- `options`: 任务选项（可选）
  - `max_steps`: 最大执行步数（默认：从配置读取）
  - `vision`: 是否启用视觉能力（默认：从配置读取）
  - `reasoning`: 是否启用推理模式（默认：从配置读取）
  - `reflection`: 是否启用反思（默认：从配置读取）
  - `debug`: 是否启用调试模式（默认：从配置读取）
  - `save_trajectory`: 轨迹保存级别（"none", "step", "action"，默认：从配置读取）

### 2. 任务状态更新消息 (TASK_STATUS)

服务端在执行过程中会发送状态更新：

```json
{
  "version": "1.0",
  "type": "task_status",
  "request_id": "unique_request_id_123",
  "device_id": "your_device_id",
  "timestamp": "2024-01-01T00:00:00.000Z",
  "status": "success",
  "data": {
    "status": "running",
    "progress": 0.3,
    "message": "执行任务中..."
  }
}
```

**状态值**:
- `running`: 任务执行中
- `completed`: 任务完成
- `failed`: 任务失败

### 3. 任务响应消息 (TASK_RESPONSE)

任务执行完成后，服务端发送最终响应：

**成功响应**:
```json
{
  "version": "1.0",
  "type": "task_response",
  "request_id": "unique_request_id_123",
  "device_id": "your_device_id",
  "timestamp": "2024-01-01T00:00:00.000Z",
  "status": "success",
  "result": {
    "success": true,
    "output": "任务执行成功",
    "steps": 5,
    "reason": "任务已完成",
    "trajectory_id": "optional_trajectory_id"
  }
}
```

**失败响应**:
```json
{
  "version": "1.0",
  "type": "task_response",
  "request_id": "unique_request_id_123",
  "device_id": "your_device_id",
  "timestamp": "2024-01-01T00:00:00.000Z",
  "status": "error",
  "error": "任务执行失败: 具体错误信息"
}
```

## 完整流程示例

### Android/Kotlin 示例

```kotlin
import org.json.JSONObject
import java.util.UUID

class TaskRequestExample {
    private val webSocketClient: WebSocketClient = // 你的 WebSocket 客户端实例
    
    /**
     * 发送任务请求
     */
    fun sendTaskRequest(goal: String) {
        val requestId = UUID.randomUUID().toString()
        
        // 构建任务请求消息
        val taskRequest = MessageProtocol.createTaskRequest(
            goal = goal,
            requestId = requestId,
            deviceId = "your_device_id",
            options = mapOf(
                "max_steps" to 15,
                "vision" to true,
                "reasoning" to false
            )
        )
        
        // 发送请求
        webSocketClient.sendMessage(taskRequest)
        
        // 监听响应（在 WebSocketClient 的 onMessageReceived 中处理）
    }
    
    /**
     * 处理任务响应
     */
    fun handleTaskResponse(message: JSONObject) {
        val type = message.getString("type")
        
        when (type) {
            "task_status" -> {
                // 处理状态更新
                val data = message.getJSONObject("data")
                val status = data.getString("status")
                val progress = data.optDouble("progress", 0.0)
                val messageText = data.optString("message", "")
                
                println("任务状态: $status, 进度: $progress, 消息: $messageText")
            }
            
            "task_response" -> {
                // 处理最终响应
                val status = message.getString("status")
                
                if (status == "success") {
                    val result = message.getJSONObject("result")
                    val success = result.getBoolean("success")
                    val output = result.optString("output", "")
                    val steps = result.optInt("steps", 0)
                    
                    println("任务执行成功: $output, 步骤数: $steps")
                } else {
                    val error = message.getString("error")
                    println("任务执行失败: $error")
                }
            }
        }
    }
}
```

### Python 示例

```python
import asyncio
import json
import websockets
import uuid
from droidrun.server.message_protocol import MessageProtocol, MessageType

async def send_task_request():
    """发送任务请求示例"""
    device_id = "my_device_001"
    uri = f"ws://localhost:8765/ws?device_id={device_id}"
    
    async with websockets.connect(uri) as websocket:
        # 接收欢迎消息
        welcome = await websocket.recv()
        print(f"已连接: {json.loads(welcome)}")
        
        # 发送任务请求
        request_id = str(uuid.uuid4())
        task_request = MessageProtocol.create_task_request(
            goal="请帮我请十一月10号到15号的年假,去海南旅游。",
            request_id=request_id,
            device_id=device_id,
            options={
                "max_steps": 15,
                "vision": True,
                "reasoning": False
            }
        )
        
        await websocket.send(json.dumps(task_request))
        print(f"已发送任务请求: {task_request['data']['goal']}")
        
        # 监听响应
        async for message in websocket:
            msg = json.loads(message)
            msg_type = msg.get("type")
            
            if msg_type == "task_status":
                # 处理状态更新
                data = msg.get("data", {})
                status = data.get("status")
                progress = data.get("progress", 0.0)
                message_text = data.get("message", "")
                print(f"任务状态: {status}, 进度: {progress:.1%}, 消息: {message_text}")
            
            elif msg_type == "task_response":
                # 处理最终响应
                status = msg.get("status")
                if status == "success":
                    result = msg.get("result", {})
                    print(f"任务执行成功: {result.get('output')}")
                    print(f"执行步骤: {result.get('steps')}")
                else:
                    error = msg.get("error")
                    print(f"任务执行失败: {error}")
                break

if __name__ == "__main__":
    asyncio.run(send_task_request())
```

## 执行流程

1. **移动端连接**: 移动端通过 WebSocket 连接到服务器
2. **发送任务请求**: 移动端发送 `TASK_REQUEST` 消息，包含 `goal` 和可选 `options`
3. **服务端接收**: 服务端接收请求，创建 `TaskExecutor` 实例
4. **初始化阶段**: 
   - 创建 `WebSocketTools` 实例
   - 加载 LLM（根据配置）
   - 创建 `DroidAgent` 实例
5. **执行阶段**: 
   - 服务端执行完整的 DroidAgent 流程
   - 期间发送 `TASK_STATUS` 状态更新
6. **完成阶段**: 
   - 任务执行完成后，发送 `TASK_RESPONSE` 响应
   - 包含执行结果（success, output, steps 等）

## 注意事项

1. **请求ID**: 每个任务请求必须有唯一的 `request_id`，用于匹配响应
2. **异步执行**: 任务在后台异步执行，不会阻塞其他消息处理
3. **状态更新**: 服务端会定期发送状态更新，移动端可以显示进度
4. **错误处理**: 如果执行失败，会发送包含错误信息的响应
5. **设备连接**: 确保设备已连接到服务器，否则任务会失败
6. **LLM配置**: 确保服务端已配置 LLM API Key，否则任务无法执行

## 错误处理

如果任务执行失败，响应会包含错误信息：

```json
{
  "type": "task_response",
  "status": "error",
  "error": "Task execution failed: 具体错误信息"
}
```

常见错误：
- `Missing goal in task request`: 任务请求缺少 goal 字段
- `未配置 LLM API Key`: 服务端未配置 LLM API Key
- `设备未连接到服务器`: 设备未连接或已断开
- `Task execution failed: ...`: 任务执行过程中的错误

## 完整示例代码

参考 `droidrun/server/example_task_client.py` 查看完整的 Python 示例代码。












