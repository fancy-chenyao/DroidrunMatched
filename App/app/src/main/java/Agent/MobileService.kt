package Agent

//import Agent.AskPopUp
import android.R
import android.annotation.SuppressLint
import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Binder
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import android.view.WindowManager
 
 
 
import org.json.JSONObject
 
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
 

/**
 * MobileGPT普通服务类，负责处理与服务器通信
 */
class MobileService : Service() {
    companion object {
        private const val TAG = "MobileService"
        private const val NOTIFICATION_ID = 1
        private const val CHANNEL_ID = "MobileGPTServiceChannel"
    }

    private val binder = LocalBinder()
    private lateinit var wm: WindowManager
    private var mClient: MobileGPTClient? = null  // 保留旧客户端用于向后兼容
    private var wsClient: WebSocketClient? = null  // WebSocket客户端
    private var wsListener: WebSocketClient.WebSocketListener? = null
    private lateinit var mSpeech: MobileGPTSpeechRecognizer
    private lateinit var agentFloatingWindow: AgentFloatingWindowManager
    private var mMobileGPTGlobal: MobileGPTGlobal? = null
    private var questionHandler: InteractionQuestionHandler? = null  // Phase 3: 交互式问答处理器
    
    private var instruction: String? = null
    private var targetPackageName: String? = null
    private lateinit var mExecutorService: ExecutorService
    private val mainThreadHandler = Handler(Looper.getMainLooper())
    

    // WebSocket相关变量
    private var heartbeatRunnable: Runnable? = null
    private var heartbeatHandler: Handler? = null
    private var pendingInstruction: String? = null  // 待发送的指令（连接建立后发送）
    private var isConnecting = false  // 是否正在连接

    

    /**
     * 本地绑定器类
     */
    inner class LocalBinder : Binder() {
        fun getService(): MobileService = this@MobileService
    }

    /**
     * 广播接收器，用于接收指令和答案
     */
    private val stringReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                MobileGPTGlobal.STRING_ACTION -> {
                    val receivedInstruction = intent.getStringExtra(MobileGPTGlobal.INSTRUCTION_EXTRA)
                    if (receivedInstruction != null) {
                        Log.d(TAG, "收到任务指令: $receivedInstruction")
                        
                        // 保存待发送的指令
                        pendingInstruction = receivedInstruction
                        
                        // 检查WebSocket连接状态
                        if (wsClient?.isConnected() == true) {
                            // 已连接，直接发送指令
                            Log.d(TAG, "WebSocket已连接，直接发送任务指令")
                            sendTaskInstruction(receivedInstruction)
                    } else {
                            // 未连接，先建立连接
                            // 注意：pendingInstruction已在上面保存，连接成功后会自动发送
                            Log.d(TAG, "WebSocket未连接，开始建立连接...")
                            mExecutorService.execute {
                                ensureWebSocketConnection { success ->
                                    if (success) {
                                        Log.d(TAG, "WebSocket连接成功，任务指令将在连接回调中自动发送")
                                    } else {
                                        Log.e(TAG, "WebSocket连接失败，无法发送任务指令")
                                        // 清除待发送的指令
                                        pendingInstruction = null
                                        // 可以显示错误提示给用户
                                    }
                                }
                            }
                        }
                        
                    // 初始化页面变化的参数
//                        xmlPending = true
//                        screenNeedUpdate = true
//                        firstScreen = true
//                    WaitScreenUpdate()
                    } else {
                        Log.e(TAG, "Received null instruction from intent")
                    }
                }
                MobileGPTGlobal.ANSWER_ACTION -> {
                    // 处理答案接收
                    val infoName = intent.getStringExtra(MobileGPTGlobal.INFO_NAME_EXTRA)
                    val question = intent.getStringExtra(MobileGPTGlobal.QUESTION_EXTRA)
                    val answer = intent.getStringExtra(MobileGPTGlobal.ANSWER_EXTRA)
                    val timestamp = intent.getLongExtra("timestamp", 0L)
                    
                    if (infoName != null && question != null && answer != null) {
                        Log.d(TAG, "收到答案: $infoName - $question - $answer (时间戳: $timestamp)")
                        
                        // 验证答案有效性
                        if (answer.isNotBlank()) {
                            // 避免网络请求在主线程：放入执行器
                            mExecutorService.execute {
                                sendAnswer(infoName, question, answer)
                                Log.d(TAG, "答案已发送到服务器")
                            }
                        } else {
                            Log.w(TAG, "收到空答案，忽略")
                        }
                    } else {
                        Log.e(TAG, "收到不完整的答案数据: infoName=$infoName, question=$question, answer=$answer")
                    }
                }
            }
        }
    }

    /**
     * 创建通知渠道 (Android 8.0+)
     */
    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "MobileGPT Service Channel",
                NotificationManager.IMPORTANCE_LOW
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    /**
     * 创建前台服务通知
     */
    private fun createNotification(): Notification {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
                .setContentTitle("MobileGPT Service")
                .setContentText("MobileGPT service is running")
                .setSmallIcon(android.R.drawable.ic_menu_info_details) // 使用系统图标
                .build()
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
                .setContentTitle("MobileGPT Service")
                .setContentText("MobileGPT service is running")
                .setSmallIcon(android.R.drawable.ic_menu_info_details)
                .build()
        }
    }

    /**
     * 服务绑定时返回IBinder
     */
    override fun onBind(intent: Intent): IBinder {
        return binder
    }

    /**
     * 服务创建时的初始化
     */
    override fun onCreate() {
        super.onCreate()
        Log.d(TAG, "MobileService onCreate")
        
        // 创建前台服务通知
        createNotificationChannel()
        val notification = createNotification()
        startForeground(NOTIFICATION_ID, notification)
        
        mExecutorService = Executors.newSingleThreadExecutor()
        
        // 注册广播接收器
        val intentFilter = IntentFilter(MobileGPTGlobal.STRING_ACTION)
        intentFilter.addAction(MobileGPTGlobal.ANSWER_ACTION)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(stringReceiver, intentFilter, RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("UnspecifiedRegisterReceiverFlag")
            registerReceiver(stringReceiver, intentFilter)
        }

        wm = getSystemService(WINDOW_SERVICE) as WindowManager
        mSpeech = MobileGPTSpeechRecognizer(this)
        mMobileGPTGlobal = MobileGPTGlobal.getInstance()

        // 不再在服务启动时自动建立连接
        // 连接将在用户点击发送指令时建立

        
        Log.d(TAG, "MobileService 初始化完成")
        
    }


    /**
     * 服务启动时调用
     */
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        return START_STICKY
    }

    /**
     * 发送回答
     */
    fun sendAnswer(infoName: String, question: String, answer: String) {
        val qaString = "$infoName\\$question\\$answer"
        val message = MobileGPTMessage().createQAMessage(qaString)
        mClient?.sendMessage(message)
    }

    /**
     * 服务关闭
     * 清理所有资源，防止内存泄漏
     */
    override fun onDestroy() {
        try {

            // 清理其他资源
            unregisterReceiver(stringReceiver)
            
            // Phase 3: 清理交互式问答处理器
            questionHandler?.cleanup()
            questionHandler = null
            Log.d(TAG, "InteractionQuestionHandler 已清理")
            
            // 清理WebSocket连接
            stopHeartbeatTask()
            wsClient?.disconnect()
            wsClient = null
            wsListener = null
            
            // 清理旧客户端（向后兼容）
            mClient?.disconnect()
            
            // 清理悬浮窗资源
            if (::agentFloatingWindow.isInitialized) {
                agentFloatingWindow.cleanup()
            }
            
            // 关闭线程池
            if (::mExecutorService.isInitialized) {
                mExecutorService.shutdown()
            }
            
            Log.d(TAG, "MobileService已销毁，所有资源已清理")
        } catch (e: Exception) {
            Log.e(TAG, "销毁服务时发生异常", e)
        } finally {
        super.onDestroy()
        }
    }

    

    /**
     * 确保WebSocket连接已建立（如果未连接则建立连接）
     * @param callback 连接结果回调（true=成功，false=失败）
     */
    private fun ensureWebSocketConnection(callback: (Boolean) -> Unit) {
        // 如果已经连接，直接返回成功
        if (wsClient?.isConnected() == true) {
            Log.d(TAG, "WebSocket已连接，无需重新连接")
            callback(true)
            return
        }
        
        // 如果正在连接，等待连接完成
        if (isConnecting) {
            Log.d(TAG, "WebSocket正在连接中，等待连接完成...")
            // 使用Handler延迟检查连接状态
            val handler = Handler(Looper.getMainLooper())
            var checkCount = 0
            val maxChecks = 30  // 最多检查30次（约15秒）
            
            val checkRunnable = object : Runnable {
                override fun run() {
                    checkCount++
                    if (wsClient?.isConnected() == true) {
                        isConnecting = false
                        callback(true)
                    } else if (checkCount >= maxChecks) {
                        isConnecting = false
                        Log.e(TAG, "等待WebSocket连接超时")
                        callback(false)
                    } else {
                        handler.postDelayed(this, 500)  // 每500ms检查一次
                    }
                }
            }
            handler.postDelayed(checkRunnable, 500)
            return
        }
        
        // 开始建立连接
        isConnecting = true
        Log.d(TAG, "开始建立WebSocket连接...")
        
        try {
            // 1. 获取设备ID（从SharedPreferences或生成新ID）
            val deviceId = getOrCreateDeviceId()
            Log.d(TAG, "设备ID: $deviceId")
            
            // 2. 如果WebSocket客户端不存在，创建它
            if (wsClient == null) {
                wsClient = WebSocketClient()
                // Phase 3: 创建交互式问答处理器
                questionHandler = InteractionQuestionHandler(this@MobileService, wsClient!!)
                Log.d(TAG, "InteractionQuestionHandler 已初始化")
            }
            
            // 3. 创建监听器（如果还没有，或者需要更新回调）
            // 注意：如果监听器已存在，我们需要确保新的连接尝试能够正确回调
            val currentCallback = callback  // 保存当前回调
            wsListener = object : WebSocketClient.WebSocketListener {
                override fun onConnected() {
                    Log.d(TAG, "WebSocket连接成功")
                    isConnecting = false
                    // 启动心跳任务
                    startHeartbeatTask()
                    // 连接成功，调用回调
                    currentCallback(true)
                    // 如果有待发送的指令，发送它
                    pendingInstruction?.let { instruction ->
                        Log.d(TAG, "连接成功后发送待发送的指令: $instruction")
                        sendTaskInstruction(instruction)
                        pendingInstruction = null
                    }
                }
                
                override fun onDisconnected(reason: String) {
                    Log.w(TAG, "WebSocket断开连接: $reason")
                    isConnecting = false
                    // 停止心跳任务
                    stopHeartbeatTask()
                    // 可选：实现自动重连（WebSocketClient已实现）
                }
                
                override fun onMessageReceived(message: JSONObject) {
                    // 处理接收到的消息
                    handleWebSocketMessage(message)
                }
                
                override fun onError(error: String) {
                    Log.e(TAG, "WebSocket错误: $error")
                    isConnecting = false
                    currentCallback(false)
                }
            }
            
            // 4. 连接到服务器
            wsClient?.connect(
                host = MobileGPTGlobal.WS_HOST_IP,
                port = MobileGPTGlobal.WS_PORT,
                deviceId = deviceId,
                listener = wsListener!!
            )
            
            Log.d(TAG, "正在连接到WebSocket服务器: ${MobileGPTGlobal.WS_HOST_IP}:${MobileGPTGlobal.WS_PORT}")
            
            // 设置连接超时检查
            Handler(Looper.getMainLooper()).postDelayed({
                if (isConnecting && wsClient?.isConnected() != true) {
                    isConnecting = false
                    Log.e(TAG, "WebSocket连接超时")
                    callback(false)
                }
            }, 10000)  // 10秒超时
            
        } catch (e: Exception) {
            isConnecting = false
            Log.e(TAG, "WebSocket连接初始化失败: ${e.message}", e)
            callback(false)
        }
    }
    
    /**
     * 通过WebSocket发送任务指令
     * 注意：此方法假设连接已建立
     */
    private fun sendTaskInstruction(instruction: String) {
        if (wsClient?.isConnected() != true) {
            Log.e(TAG, "WebSocket未连接，无法发送任务指令")
            return
        }
        
        try {
            val deviceId = getOrCreateDeviceId()
            val requestId = java.util.UUID.randomUUID().toString()
            // 使用协议定义的 task_request 消息（goal 即为指令）
            val message = MessageProtocol.createTaskRequest(
                goal = instruction,
                requestId = requestId,
                deviceId = deviceId,
                options = null
            )
            
            // 发送消息
            val sent = wsClient?.sendMessage(message) ?: false
            if (sent) {
                Log.d(TAG, "任务指令已发送: $instruction")
            } else {
                Log.e(TAG, "任务指令发送失败")
            }
        } catch (e: Exception) {
            Log.e(TAG, "发送任务指令时发生异常", e)
        }
    }
    
    /**
     * 处理WebSocket消息
     */
    private fun handleWebSocketMessage(message: JSONObject) {
        try {
            val messageType = message.optString("type", "")
            
            when (messageType) {
                MessageProtocol.MessageType.SERVER_READY -> {
                    Log.d(TAG, "收到服务器就绪消息")
                    // 服务器已准备好，可以开始接收命令
                }
                
                MessageProtocol.MessageType.TASK_STATUS -> {
                    val data = message.optJSONObject("data")
                    val status = data?.optString("status", "")
                    val progress = data?.optDouble("progress", 0.0) ?: 0.0
                    val msg = data?.optString("message", "")
                    Log.d(TAG, "任务状态更新: status=$status, progress=$progress, message=$msg")
                }
                
                MessageProtocol.MessageType.TASK_RESPONSE -> {
                    val status = message.optString("status", "")
                    if (status == "success") {
                        val result = message.optJSONObject("result")
                        Log.d(TAG, "任务完成: result=$result")
                    } else {
                        val error = message.optString("error", "unknown")
                        Log.e(TAG, "任务失败: $error")
                    }
                }
                
                MessageProtocol.MessageType.HEARTBEAT_ACK -> {
                    Log.d(TAG, "收到心跳确认")
                    // 心跳正常，无需处理
                }
                
                MessageProtocol.MessageType.COMMAND -> {
                    // 处理命令消息
                    handleCommandMessage(message)
                }
                
                MessageProtocol.MessageType.ERROR -> {
                    val error = message.optString("error", "Unknown error")
                    Log.e(TAG, "收到错误消息: $error")
                }
                
                "user_question" -> {
                    // Phase 3: 处理交互式问答
                    Log.d(TAG, "收到用户问题消息")
                    questionHandler?.handleQuestionMessage(message) ?: run {
                        Log.e(TAG, "InteractionQuestionHandler 未初始化，无法处理问题")
                        // 发送默认答案
                        val questionId = message.optString("question_id", "")
                        val defaultValue = message.optString("default_value", "")
                        if (questionId.isNotEmpty()) {
                            val answerMessage = JSONObject().apply {
                                put("type", "user_answer")
                                put("question_id", questionId)
                                put("answer", defaultValue)
                            }
                            wsClient?.sendMessage(answerMessage)
                        }
                    }
                }
                
                else -> {
                    Log.w(TAG, "未知消息类型: $messageType")
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "处理WebSocket消息时发生异常", e)
        }
    }
    
    /**
     * 处理命令消息
     */
    private fun handleCommandMessage(message: JSONObject) {
        try {
            val requestId = message.optString("request_id", "")
            val data = message.optJSONObject("data")
            
            if (data == null) {
                sendErrorResponse(requestId, "Command message missing data field")
                return
            }
            
            val command = data.optString("command", "")
            val params = data.optJSONObject("params") ?: org.json.JSONObject()
            
            if (command.isEmpty()) {
                sendErrorResponse(requestId, "Command name is empty")
                return
            }
            
            // 获取当前Activity
            val currentActivity = ActivityTracker.getCurrentActivity()
            
            // 两阶段响应：立即发送“accepted”以避免服务端长时间阻塞
            try {
                sendCommandResponse(requestId, "accepted", null, null)
            } catch (e: Exception) {
                Log.w(TAG, "发送accepted中间态失败（忽略）", e)
            }
            
            // 使用CommandHandler处理命令
            CommandHandler.handleCommand(
                command = command,
                params = params,
                requestId = requestId,
                activity = currentActivity
            ) { response ->
                // CommandHandler返回的response已经包含status字段
                val status = response.optString("status", "success")
                val error = response.optString("error", null)
                
                if (status == "error") {
                    // 错误响应：提取error字段
                    sendCommandResponse(requestId, "error", null, error)
                } else {
                    // 成功响应：提取data部分（response中除了status和error之外的所有字段）
                    val data = org.json.JSONObject()
                    val keys = response.keys()
                    while (keys.hasNext()) {
                        val key = keys.next()
                        // 跳过status和error字段，它们已经在消息的顶层
                        if (key != "status" && key != "error") {
                            data.put(key, response.get(key))
                        }
                    }
                    // 如果data为空，传入null；否则传入data对象
                    sendCommandResponse(
                        requestId, 
                        "success", 
                        if (data.length() > 0) data else null, 
                        null
                    )
                }
            }
            
        } catch (e: Exception) {
            Log.e(TAG, "处理命令消息时发生异常", e)
            val requestId = message.optString("request_id", "")
            sendErrorResponse(requestId, "Exception: ${e.message}")
        }
    }
    
    /**
     * 发送命令响应
     */
    private fun sendCommandResponse(
        requestId: String,
        status: String,
        data: org.json.JSONObject?,
        error: String?
    ) {
        val response = MessageProtocol.createCommandResponse(
            requestId = requestId,
            status = status,
            data = data,
            error = error,
            deviceId = getOrCreateDeviceId()
        )
        
        wsClient?.sendMessage(response)
    }
    
    /**
     * 发送错误响应
     */
    private fun sendErrorResponse(requestId: String, error: String) {
        sendCommandResponse(requestId, "error", null, error)
    }
    
    /**
     * 启动心跳任务
     */
    private fun startHeartbeatTask() {
        heartbeatHandler = Handler(Looper.getMainLooper())
        heartbeatRunnable = object : Runnable {
            override fun run() {
                val deviceId = getOrCreateDeviceId()
                wsClient?.sendHeartbeat(deviceId)
                heartbeatHandler?.postDelayed(this, MobileGPTGlobal.HEARTBEAT_INTERVAL)
            }
        }
        heartbeatHandler?.post(heartbeatRunnable!!)
    }
    
    /**
     * 停止心跳任务
     */
    private fun stopHeartbeatTask() {
        heartbeatRunnable?.let {
            heartbeatHandler?.removeCallbacks(it)
        }
        heartbeatRunnable = null
    }
    
    /**
     * 获取或创建设备ID
     */
    private fun getOrCreateDeviceId(): String {
        val prefs = getSharedPreferences("droidrun_prefs", Context.MODE_PRIVATE)
        var deviceId = prefs.getString(MobileGPTGlobal.DEVICE_ID_KEY, null)
        
        if (deviceId == null) {
            // 生成新的设备ID（使用UUID）
            deviceId = java.util.UUID.randomUUID().toString()
            prefs.edit().putString(MobileGPTGlobal.DEVICE_ID_KEY, deviceId).apply()
            Log.d(TAG, "生成新设备ID: $deviceId")
        }
        
        return deviceId
    }
}
