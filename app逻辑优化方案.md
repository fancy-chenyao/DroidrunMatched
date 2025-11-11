# APP端适配服务端WebSocket协议完整实现方案

## 一、方案概述

### 1.1 目标

将APP端从Socket（TCP）通信迁移到WebSocket通信，适配服务端的标准消息协议，实现服务端主动控制APP端执行自动化任务。

### 1.2 核心改动

- 通信方式：Socket → WebSocket

- 消息协议：自定义二进制协议 → 标准JSON协议

- 工作模式：APP主动推送 → 服务端主动命令

- 响应机制：无结构化响应 → 标准响应格式（含request_id）

### 1.3 技术栈

- WebSocket客户端：OkHttp WebSocket

- JSON处理：org.json（Android内置）

- 线程管理：Handler/Looper

- 数据持久化：SharedPreferences（设备ID存储）

## 二、架构设计

### 2.1 组件结构APP端架构├── WebSocketClient.kt     (新建) - WebSocket连接管理├── MessageProtocol.kt     (新建) - 消息协议定义├── StateConverter.kt      (新建) - 数据格式转换├── CommandHandler.kt      (新建) - 命令处理器├── MobileService.kt       (修改) - 服务主类├── MobileGPTGlobal.kt      (修改) - 配置管理└── ElementController.kt     (复用) - UI操作（无需修改）

### 2.2 数据流服务端 WebSocket Server  ↓ (发送命令消息)WebSocketClient (接收)  ↓ (解析JSON)CommandHandler (路由)  ↓ (执行UI操作)ElementController (现有功能)  ↓ (获取结果)StateConverter (格式化)  ↓ (构建响应)WebSocketClient (发送响应)  ↓ (返回响应消息)服务端 WebSocket Server

## 三、详细实现步骤

### 阶段一：环境准备和基础组件

#### 步骤1：添加依赖和权限配置

1.1 修改 App/app/build.gradle.kts

- 添加OkHttp

   WebSocket依赖

   dependencies {

     implementation("com.squareup.okhttp3:okhttp:4.12.0")

     // 其他现有依赖保持不变

   }

1.2 检查 App/app/src/main/AndroidManifest.xml

- 确认已添加网络权限：

   <uses-permission android:name="android.permission.INTERNET" />

   <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />

1.3 修改配置常量

- 文件：App/app/src/main/java/Agent/MobileGPTGlobal.kt

- 添加WebSoc

  ket相关配置：

   // WebSocket服务器配置

   const val WS_HOST_IP = "192.168.100.32" // 可配置，建议从SharedPreferences读取

   const val WS_PORT = 8765         // 服务端WebSocket端口

   const val WS_PATH = "/ws"         // WebSocket路径

   

   // 设备ID配置

   const val DEVICE_ID_KEY = "device_id"   // SharedPreferences键名

   const val HEARTBEAT_INTERVAL = 30000L   // 心跳间隔30秒

   const val CONNECTION_TIMEOUT = 10L    // 连接超时10秒

   const val COMMAND_TIMEOUT = 30000L    // 命令执行超时30秒

#### 步骤2：创建消息协议定义类

2.1 创建文件：App/app/src/main/java/Agent/MessageProtocol.kt

功能：

- 定义消息类型常量

- 提供消息创建方法

- 提供消息解析方法

- 消息验证方法

需要实现的方法：

// 消息类型

object MessageType {

  const val SERVER_READY = "server_ready"

  const val HEARTBEAT = "heartbeat"

  const val HEARTBEAT_ACK = "heartbeat_ack"

  const val COMMAND = "command"

  const val COMMAND_RESPONSE = "command_response"

  const val ERROR = "error"

}

// 创建消息的方法

fun createHeartbeatMessage(deviceId: String): JSONObject

fun createCommandResponse(requestId: String, status: String, data: JSONObject?, error: String?): JSONObject

fun createErrorMessage(requestId: String?, error: String): JSONObject

// 解析消息的方法

fun parseMessage(jsonString: String): JSONObject?

fun validateMessage(message: JSONObject): Boolean

#### 步骤3：创建WebSocket客户端类

3.1 创建文件：App/app/src/main/java/Agent/WebSocketClient.kt

核心功能：

- WebSocket连接管理

- 消息发送/接收

- 心跳机制

- 自动重连

- 连接状态管理

需要实现的接口：

interface WebSocketListener {

  fun onConnected()

  fun onDisconnected(reason: String)

  fun onMessageReceived(message: JSONObject)

  fun onError(error: String)

}

class WebSocketClient {

  // 连接方法

  fun connect(host: String, port: Int, deviceId: String, listener: WebSocketListener)

  

  // 断开连接

  fun disconnect()

  

  // 发送消息

  fun sendMessage(message: JSONObject): Boolean

  

  // 发送心跳

  fun sendHeartbeat()

  

  // 获取连接状态

  fun isConnected(): Boolean

}

实现细节：

1. 连接URL格式：ws://{host}:{port}/ws?device_id={deviceId}

1. 使用OkHttp的WebSocket API

1. 心跳任务：每30秒发送一次心跳消息

1. 消息队列：连接断开时缓存未发送消息

1. 自动重连：连接断开后自动重连（最多3次，间隔5秒）

1. 线程安全：所有操作在后台线程，回调通过Handler切换到主线程

### 阶段二：服务集成和协议适配

#### 步骤4：创建数据格式转换工具

4.1 创建文件：App/app/src/main/java/Agent/StateConverter.kt

功能：

- 将GenericElement树转换为服务端期望的JSON格式

- 获取设备状态信息

- 截图Base64编码

需要实现的方法：

object StateConverter {

  // 将GenericElement转换为a11y_tree格式

  fun convertElementTreeToA11yTree(element: GenericElement): JSONArray

  

  // 获取设备状态

  fun getPhoneState(activity: Activity?): JSONObject

  

  // 构建完整的get_state响应

  fun buildStateResponse(activity: Activity?, elementTree: GenericElement, screenshot: Bitmap?): JSONObject

  

  // 截图转Base64

  fun bitmapToBase64(bitmap: Bitmap): String

}

数据格式要求：

- a11y_tree：JSON数组，每个元素包含：

- index: Int

- resourceId: String

- className: String

- text: String

- contentDesc: String

- bounds: JSONObject {left, top, right, bottom}

- clickable: Boolean

- enabled: Boolean

- children: JSONArray（递归）

- phone_state：JSONObject，包含：

- package: String（当前包名）

- activity: String（当前Activity类名）

- screen_width: Int（屏幕宽度dp）

- screen_height: Int（屏幕高度dp）

#### 步骤5：创建命令处理器

5.1 创建文件：App/app/src/main/java/Agent/CommandHandler.kt

功能：

- 路由命令到对应的处理器

- 执行UI操作

- 构建响应消息

- 错误处理

需要实现的命令处理器：

object CommandHandler {

  // 主处理方法

  fun handleCommand(

​    command: String,

​    params: JSONObject,

​    requestId: String,

​    activity: Activity?,

​    callback: (JSONObject) -> Unit

  )

  

  // 各命令处理器

  private fun handleGetState(requestId: String, params: JSONObject, activity: Activity?, callback: (JSONObject) -> Unit)

  private fun handleTap(requestId: String, params: JSONObject, activity: Activity?, callback: (JSONObject) -> Unit)

  private fun handleSwipe(requestId: String, params: JSONObject, activity: Activity?, callback: (JSONObject) -> Unit)

  private fun handleInputText(requestId: String, params: JSONObject, activity: Activity?, callback: (JSONObject) -> Unit)

  private fun handleBack(requestId: String, params: JSONObject, activity: Activity?, callback: (JSONObject) -> Unit)

  private fun handlePressKey(requestId: String, params: JSONObject, activity: Activity?, callback: (JSONObject) -> Unit)

  private fun handleStartApp(requestId: String, params: JSONObject, activity: Activity?, callback: (JSONObject) -> Unit)

}

命令映射表：

| 服务端命令 | 处理器方法      | 参数说明                                      | 响应格式                               |
| :--------- | :-------------- | :-------------------------------------------- | :------------------------------------- |
| get_state  | handleGetState  | 无参数                                        | {a11y_tree: [...], phone_state: {...}} |
| tap        | handleTap       | {x: Int, y: Int}                              | {status: "success"}                    |
| swipe      | handleSwipe     | {start_x, start_y, end_x, end_y, duration_ms} | {status: "success"}                    |
| input_text | handleInputText | {text: String}                                | {status: "success"}                    |
| back       | handleBack      | 无参数                                        | {status: "success"}                    |
| press_key  | handlePressKey  | {keycode: Int}                                | {status: "success"}                    |
| start_app  | handleStartApp  | {package: String, activity?: String}          | {status: "success"}                    |

实现要点：

1. 参数验证：检查必需参数是否存在

1. Activity检查：确保有有效的Activity实例

1. 异步执行：UI操作在主线程，网络操作在后台线程

1. 超时处理：命令执行超过30秒返回超时错误

1. 错误响应：执行失败返回详细错误信息

### 阶段三：服务主类修改

#### 步骤6：修改MobileService类

6.1 修改 App/app/src/main/java/Agent/MobileService.kt

修改点1：替换网络客户端

- 移除：private var mClient: MobileGPTClient? = null

- 添加：private var wsClient: WebSocketClient? = null

- 添加：private var wsListener: WebSocketClient.WebSocketListener? = null

修改点2：重写 initNetworkConnection() 方法

private fun initNetworkConnection() {

  // 1. 获取设备ID（从SharedPreferences或生成新ID）

  val deviceId = getOrCreateDeviceId()

  

  // 2. 创建WebSocket客户端

  wsClient = WebSocketClient()

  

  // 3. 创建监听器

  wsListener = object : WebSocketClient.WebSocketListener {

​    override fun onConnected() {

​      Log.d(TAG, "WebSocket连接成功")

​      // 启动心跳任务

​      startHeartbeatTask()

​    }

​    

​    override fun onDisconnected(reason: String) {

​      Log.w(TAG, "WebSocket断开连接: $reason")

​      // 停止心跳任务

​      stopHeartbeatTask()

​      // 可选：实现自动重连

​    }

​    

​    override fun onMessageReceived(message: JSONObject) {

​      // 处理接收到的消息

​      handleWebSocketMessage(message)

​    }

​    

​    override fun onError(error: String) {

​      Log.e(TAG, "WebSocket错误: $error")

​    }

  }

  

  // 4. 连接到服务器

  wsClient?.connect(

​    host = MobileGPTGlobal.WS_HOST_IP,

​    port = MobileGPTGlobal.WS_PORT,

​    deviceId = deviceId,

​    listener = wsListener!!

  )

}

修改点3：实现 handleWebSocketMessage() 方法

private fun handleWebSocketMessage(message: JSONObject) {

  try {

​    val messageType = message.optString("type", "")

​    

​    when (messageType) {

​      MessageType.SERVER_READY -> {

​        Log.d(TAG, "收到服务器就绪消息")

​        // 服务器已准备好，可以开始接收命令

​      }

​      

​      MessageType.HEARTBEAT_ACK -> {

​        Log.d(TAG, "收到心跳确认")

​        // 心跳正常，无需处理

​      }

​      

​      MessageType.COMMAND -> {

​        // 处理命令消息

​        handleCommandMessage(message)

​      }

​      

​      MessageType.ERROR -> {

​        val error = message.optString("error", "Unknown error")

​        Log.e(TAG, "收到错误消息: $error")

​      }

​      

​      else -> {

​        Log.w(TAG, "未知消息类型: $messageType")

​    }

  } catch (e: Exception) {

​    Log.e(TAG, "处理WebSocket消息时发生异常", e)

  }

}

修改点4：实现 handleCommandMessage() 方法

private fun handleCommandMessage(message: JSONObject) {

  try {

​    val requestId = message.optString("request_id", "")

​    val data = message.optJSONObject("data")

​    

​    if (data == null) {

​      sendErrorResponse(requestId, "Command message missing data field")

​      return

​    }

​    

​    val command = data.optString("command", "")

​    val params = data.optJSONObject("params") ?: JSONObject()

​    

​    if (command.isEmpty()) {

​      sendErrorResponse(requestId, "Command name is empty")

​      return

​    }

​    

​    // 获取当前Activity

​    val currentActivity = ActivityTracker.getCurrentActivity()

​    

​    // 使用CommandHandler处理命令

​    CommandHandler.handleCommand(

​      command = command,

​      params = params,

​      requestId = requestId,

​      activity = currentActivity

​    ) { response ->

​      // 发送响应

​      sendCommandResponse(requestId, "success", response, null)

​    }

​    

  } catch (e: Exception) {

​    Log.e(TAG, "处理命令消息时发生异常", e)

​    val requestId = message.optString("request_id", "")

​    sendErrorResponse(requestId, "Exception: ${e.message}")

  }

}

修改点5：实现响应发送方法

private fun sendCommandResponse(

  requestId: String,

  status: String,

  data: JSONObject?,

  error: String?

) {

  val response = MessageProtocol.createCommandResponse(

​    requestId = requestId,

​    status = status,

​    data = data,

​    error = error,

​    deviceId = getOrCreateDeviceId()

  )

  

  wsClient?.sendMessage(response)

}

private fun sendErrorResponse(requestId: String, error: String) {

  sendCommandResponse(requestId, "error", null, error)

}

修改点6：实现心跳任务

private var heartbeatRunnable: Runnable? = null

private var heartbeatHandler: Handler? = null

private fun startHeartbeatTask() {

  heartbeatHandler = Handler(Looper.getMainLooper())

  heartbeatRunnable = object : Runnable {

​    override fun run() {

​      val heartbeat = MessageProtocol.createHeartbeatMessage(getOrCreateDeviceId())

​      wsClient?.sendHeartbeat()

​      heartbeatHandler?.postDelayed(this, MobileGPTGlobal.HEARTBEAT_INTERVAL)

​    }

  }

  heartbeatHandler?.post(heartbeatRunnable!!)

}

private fun stopHeartbeatTask() {

  heartbeatRunnable?.let {

​    heartbeatHandler?.removeCallbacks(it)

  }

  heartbeatRunnable = null

}

修改点7：实现设备ID管理

private fun getOrCreateDeviceId(): String {

  val prefs = getSharedPreferences("droidrun_prefs", Context.MODE_PRIVATE)

  var deviceId = prefs.getString(MobileGPTGlobal.DEVICE_ID_KEY, null)

  

  if (deviceId == null) {

​    // 生成新的设备ID（使用UUID或Android ID）

​    deviceId = UUID.randomUUID().toString()

​    prefs.edit().putString(MobileGPTGlobal.DEVICE_ID_KEY, deviceId).apply()

  }

  

  return deviceId

}

修改点8：清理资源

- 在 onDestroy() 中：

- 停止心跳任务

- 断开WebSocket连接

- 清理监听器引用

### 阶段四：命令处理器详细实现

#### 步骤7：实现get_state命令

7.1 在 CommandHandler.kt 中实现 handleGetState()

实现逻辑：

private fun handleGetState(

  requestId: String,

  params: JSONObject,

  activity: Activity?,

  callback: (JSONObject) -> Unit

) {

  if (activity == null) {

​    callback(createErrorResponse("No active activity"))

​    return

  }

  

  // 在主线程执行UI操作

  Handler(Looper.getMainLooper()).post {

​    try {

​      // 1. 获取元素树

​      ElementController.getCurrentElementTree(activity) { elementTree ->

​        // 2. 获取截图（可选）

​        val screenshot = takeScreenshot(activity)

​        

​        // 3. 转换数据格式

​        val stateResponse = StateConverter.buildStateResponse(

​          activity = activity,

​          elementTree = elementTree,

​          screenshot = screenshot

​        )

​        

​        // 4. 返回响应

​        callback(stateResponse)

​      }

​    } catch (e: Exception) {

​      callback(createErrorResponse("Failed to get state: ${e.message}"))

​    }

  }

}

#### 步骤8：实现tap命令

8.1 在 CommandHandler.kt 中实现 handleTap()

实现逻辑：

private fun handleTap(

  requestId: String,

  params: JSONObject,

  activity: Activity?,

  callback: (JSONObject) -> Unit

) {

  // 参数验证

  if (!params.has("x") || !params.has("y")) {

​    callback(createErrorResponse("Missing x or y parameter"))

​    return

  }

  

  val x = params.getInt("x")

  val y = params.getInt("y")

  

  if (activity == null) {

​    callback(createErrorResponse("No active activity"))

​    return

  }

  

  // 在主线程执行点击

  Handler(Looper.getMainLooper()).post {

​    try {

​      // 使用NativeController执行坐标点击（dp单位）

​      NativeController.clickByCoordinateDp(activity, x.toFloat(), y.toFloat()) { success ->

​        if (success) {

​          callback(createSuccessResponse())

​        } else {

​          callback(createErrorResponse("Tap action failed"))

​        }

​      }

​    } catch (e: Exception) {

​      callback(createErrorResponse("Exception: ${e.message}"))

​    }

  }

}

#### 步骤9：实现swipe命令

9.1 在 CommandHandler.kt 中实现 handleSwipe()

实现逻辑：

private fun handleSwipe(

  requestId: String,

  params: JSONObject,

  activity: Activity?,

  callback: (JSONObject) -> Unit

) {

  // 参数验证

  val requiredParams = listOf("start_x", "start_y", "end_x", "end_y")

  for (param in requiredParams) {

​    if (!params.has(param)) {

​      callback(createErrorResponse("Missing parameter: $param"))

​      return

​    }

  }

  

  val startX = params.getInt("start_x")

  val startY = params.getInt("start_y")

  val endX = params.getInt("end_x")

  val endY = params.getInt("end_y")

  val duration = params.optInt("duration_ms", 300)

  

  if (activity == null) {

​    callback(createErrorResponse("No active activity"))

​    return

  }

  

  Handler(Looper.getMainLooper()).post {

​    try {

​      NativeController.swipe(

​        activity = activity,

​        startXDp = startX.toFloat(),

​        startYDp = startY.toFloat(),

​        endXDp = endX.toFloat(),

​        endYDp = endY.toFloat(),

​        durationMs = duration

​      ) { success ->

​        if (success) {

​          callback(createSuccessResponse())

​        } else {

​          callback(createErrorResponse("Swipe action failed"))

​        }

​      }

​    } catch (e: Exception) {

​      callback(createErrorResponse("Exception: ${e.message}"))

​    }

  }

}

#### 步骤10：实现input_text命令

10.1 在 CommandHandler.kt 中实现 handleInputText()

实现逻辑：

private fun handleInputText(

  requestId: String,

  params: JSONObject,

  activity: Activity?,

  callback: (JSONObject) -> Unit

) {

  // 参数验证

  if (!params.has("text")) {

​    callback(createErrorResponse("Missing text parameter"))

​    return

  }

  

  val text = params.getString("text")

  

  if (activity == null) {

​    callback(createErrorResponse("No active activity"))

​    return

  }

  

  Handler(Looper.getMainLooper()).post {

​    try {

​      // 使用NativeController输入文本

​      NativeController.inputText(activity, text) { success ->

​        if (success) {

​          callback(createSuccessResponse())

​        } else {

​          callback(createErrorResponse("Input text action failed"))

​        }

​      }

​    } catch (e: Exception) {

​      callback(createErrorResponse("Exception: ${e.message}"))

​    }

  }

}

#### 步骤11：实现back命令

11.1 在 CommandHandler.kt 中实现 handleBack()

实现逻辑：

private fun handleBack(

  requestId: String,

  params: JSONObject,

  activity: Activity?,

  callback: (JSONObject) -> Unit

) {

  if (activity == null) {

​    callback(createErrorResponse("No active activity"))

​    return

  }

  

  Handler(Looper.getMainLooper()).post {

​    try {

​      NativeController.goBack(activity) { success ->

​        if (success) {

​          callback(createSuccessResponse())

​        } else {

​          callback(createErrorResponse("Back action failed"))

​        }

​      }

​    } catch (e: Exception) {

​      callback(createErrorResponse("Exception: ${e.message}"))

​    }

  }

}

#### 步骤12：实现press_key和start_app命令

12.1 实现 handlePressKey() - 按键操作

- 使用 Instrumentation 或 KeyEvent 发送按键事件

- 支持常用按键码（BACK=4, HOME=3等）

12.2 实现 handleStartApp() - 启动应用

- 使用 Intent 启动指定包名的应用

- 支持指定Activity启动

### 阶段五：错误处理和优化

#### 步骤13：完善错误处理

13.1 统一错误响应格式

private fun createErrorResponse(message: String): JSONObject {

  val response = JSONObject()

  response.put("status", "error")

  response.put("error", message)

  return response

}

private fun createSuccessResponse(data: JSONObject? = null): JSONObject {

  val response = JSONObject()

  response.put("status", "success")

  if (data != null) {

​    // 合并data内容

  }

  return response

}

13.2 超时处理

- 为每个命令设置超时（30秒）

- 超时后返回超时错误响应

13.3 异常捕获

- 所有命令处理器都要有try-catch

- 记录详细错误日志

#### 步骤14：性能优化

14.1 UI树缓存

- 缓存最近一次获取的UI树

- get_state时如果页面未变化，返回缓存

14.2 异步处理

- 复杂操作异步执行

- 快速返回响应，后台执行操作

14.3 资源管理

- 及时释放Bitmap资源

- 避免内存泄漏

## 四、测试验证方案

### 4.1 单元测试清单

阶段一测试：

- [ ] WebSocket连接成功

- [ ] 收到server_ready消息

- [ ] 心跳发送和接收正常

阶段二测试：

- [ ] 能正确解析命令消息

- [ ] 能正确构建响应消息

- [ ] 数据格式符合服务端要求

阶段三测试：

- [ ] get_state命令返回正确数据

- [ ] tap命令能正确执行点击

- [ ] swipe命令能正确执行滑动

- [ ] input_text命令能正确输入文本

- [ ] back命令能正确返回

### 4.2 集成测试

测试场景1：完整任务流程

1. APP启动，自动连接WebSocket

1. 服务端发送get_state命令

1. APP返回UI状态

1. 服务端发送tap命令

1. APP执行点击并返回响应

1. 验证任务完成

测试场景2：错误处理

1. 发送无效命令，验证错误响应

1. 断开网络，验证重连机制

1. 命令执行失败，验证错误响应

### 4.3 性能测试

- 连接建立时间 < 2秒

- 命令响应时间 < 1秒（简单命令）

- get_state响应时间 < 3秒

- 内存占用 < 100MB

## 五、部署和配置

### 5.1 配置项

需要在APP中可配置的项：

1. 服务端IP地址（默认从MobileGPTGlobal读取，支持运行时修改）

1. 服务端端口（默认8765）

1. 设备ID（自动生成，支持手动设置）

1. 心跳间隔（默认30秒）

1. 连接超时（默认10秒）

### 5.2 向后兼容

建议保留原有Socket客户端代码：

- 通过配置开关选择通信方式

- 逐步迁移，降低风险

## 六、实施时间估算

| 阶段   | 步骤      | 预计时间 | 累计时间 |
| :----- | :-------- | :------- | :------- |
| 阶段一 | 步骤1-3   | 4小时    | 4小时    |
| 阶段二 | 步骤4-5   | 6小时    | 10小时   |
| 阶段三 | 步骤6     | 8小时    | 18小时   |
| 阶段四 | 步骤7-12  | 12小时   | 30小时   |
| 阶段五 | 步骤13-14 | 4小时    | 34小时   |
| 测试   | 完整测试  | 8小时    | 42小时   |

总计：约5-6个工作日（按8小时/天计算）

## 七、风险点和应对

### 7.1 技术风险

| 风险                | 影响 | 应对措施                           |
| :------------------ | :--- | :--------------------------------- |
| WebSocket连接不稳定 | 高   | 实现自动重连机制，增加连接状态监控 |
| 命令执行超时        | 中   | 优化命令执行逻辑，设置合理超时时间 |
| UI树获取性能问题    | 中   | 实现UI树缓存，优化遍历算法         |
| 线程安全问题        | 高   | 严格遵循线程切换规则，使用Handler  |

### 7.2 兼容性风险

| 风险              | 影响 | 应对措施                     |
| :---------------- | :--- | :--------------------------- |
| Android版本兼容性 | 低   | 测试Android 7.0+版本         |
| 不同设备适配      | 中   | 测试不同屏幕尺寸和分辨率     |
| 服务端协议变更    | 中   | 版本化消息协议，支持协议协商 |

## 八、总结

该方案包含：

1. 5个阶段，14个详细步骤

1. 新建4个核心类，修改2个现有类

1. 完整的错误处理和性能优化

1. 详细的测试验证方案

按此方案执行可实现：

- APP端完全适配服务端WebSocket协议

- 支持服务端主动控制APP执行自动化任务

- 稳定的连接和错误处理机制

- 良好的性能和可维护性

建议按阶段逐步实施，每完成一个阶段进行测试验证，确保质量后再进入下一阶段。