package Agent

import android.content.Context
import android.util.Log
import org.json.JSONObject

/**
 * 交互式问答集成示例
 * 
 * 展示如何在 MobileService 或其他组件中集成 InteractionQuestionHandler
 */
class InteractionIntegrationExample(
    private val context: Context,
    private val webSocketClient: WebSocketClient
) {
    
    companion object {
        private const val TAG = "InteractionIntegration"
    }
    
    // 交互式问答处理器
    private val questionHandler = InteractionQuestionHandler(context, webSocketClient)
    
    /**
     * 处理 WebSocket 消息
     * 这个方法应该在 WebSocketClient.WebSocketListener.onMessageReceived 中调用
     */
    fun handleWebSocketMessage(message: JSONObject) {
        val messageType = message.optString("type", "")
        
        Log.d(TAG, "收到消息类型: $messageType")
        
        when (messageType) {
            MessageProtocol.MessageType.USER_QUESTION -> {
                // 处理用户问题
                handleUserQuestion(message)
            }
            MessageProtocol.MessageType.COMMAND -> {
                // 处理命令（原有逻辑）
                handleCommand(message)
            }
            MessageProtocol.MessageType.TASK_REQUEST -> {
                // 处理任务请求（原有逻辑）
                handleTaskRequest(message)
            }
            // 其他消息类型...
            else -> {
                Log.d(TAG, "未处理的消息类型: $messageType")
            }
        }
    }
    
    /**
     * 处理用户问题消息
     */
    private fun handleUserQuestion(message: JSONObject) {
        try {
            Log.d(TAG, "处理用户问题...")
            questionHandler.handleQuestionMessage(message)
        } catch (e: Exception) {
            Log.e(TAG, "处理用户问题失败", e)
        }
    }
    
    /**
     * 处理命令（原有逻辑占位符）
     */
    private fun handleCommand(message: JSONObject) {
        // 原有的命令处理逻辑
        Log.d(TAG, "处理命令: ${message.optJSONObject("data")?.optString("command")}")
    }
    
    /**
     * 处理任务请求（原有逻辑占位符）
     */
    private fun handleTaskRequest(message: JSONObject) {
        // 原有的任务请求处理逻辑
        Log.d(TAG, "处理任务请求: ${message.optJSONObject("data")?.optString("goal")}")
    }
    
    /**
     * 清理资源
     * 这个方法应该在 Service 的 onDestroy 中调用
     */
    fun cleanup() {
        questionHandler.cleanup()
    }
}

/**
 * 使用示例（在 MobileService 中）：
 * 
 * class MobileService : Service() {
 *     private lateinit var webSocketClient: WebSocketClient
 *     private lateinit var interactionIntegration: InteractionIntegrationExample
 *     
 *     override fun onCreate() {
 *         super.onCreate()
 *         
 *         // 创建 WebSocket 客户端
 *         webSocketClient = WebSocketClient()
 *         
 *         // 创建交互集成
 *         interactionIntegration = InteractionIntegrationExample(this, webSocketClient)
 *         
 *         // 连接 WebSocket
 *         webSocketClient.connect(
 *             host = "192.168.1.100",
 *             port = 8765,
 *             deviceId = "device-001",
 *             listener = object : WebSocketClient.WebSocketListener {
 *                 override fun onConnected() {
 *                     Log.d(TAG, "WebSocket 连接成功")
 *                 }
 *                 
 *                 override fun onDisconnected(reason: String) {
 *                     Log.d(TAG, "WebSocket 断开: $reason")
 *                 }
 *                 
 *                 override fun onMessageReceived(message: JSONObject) {
 *                     // 使用交互集成处理消息
 *                     interactionIntegration.handleWebSocketMessage(message)
 *                 }
 *                 
 *                 override fun onError(error: String) {
 *                     Log.e(TAG, "WebSocket 错误: $error")
 *                 }
 *             }
 *         )
 *     }
 *     
 *     override fun onDestroy() {
 *         super.onDestroy()
 *         interactionIntegration.cleanup()
 *     }
 * }
 */
