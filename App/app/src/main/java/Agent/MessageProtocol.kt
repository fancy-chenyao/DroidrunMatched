package Agent

import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.*

/**
 * 消息协议定义类
 * 用于创建和解析WebSocket消息
 */
object MessageProtocol {
    
    // 协议版本
    const val PROTOCOL_VERSION = "1.0"
    
    // 线程安全的时间格式化器（使用 ThreadLocal 避免 SimpleDateFormat 的线程安全问题）
    private val dateFormatter = ThreadLocal.withInitial {
        val format = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US)
        format.timeZone = TimeZone.getTimeZone("UTC")
        format
    }
    
    /**
     * 消息类型常量
     */
    object MessageType {
        const val SERVER_READY = "server_ready"
        const val HEARTBEAT = "heartbeat"
        const val HEARTBEAT_ACK = "heartbeat_ack"
        const val COMMAND = "command"
        const val COMMAND_RESPONSE = "command_response"
        // 任务流相关
        const val TASK_REQUEST = "task_request"
        const val TASK_STATUS = "task_status"
        const val TASK_RESPONSE = "task_response"
        const val ERROR = "error"
    }
    
    /**
     * 创建标准消息
     */
    private fun createBaseMessage(
        messageType: String,
        requestId: String? = null,
        deviceId: String? = null,
        data: JSONObject? = null,
        error: String? = null
    ): JSONObject {
        val message = JSONObject()
        message.put("version", PROTOCOL_VERSION)
        message.put("type", messageType)
        message.put("timestamp", getCurrentTimestamp())
        
        if (requestId != null) {
            message.put("request_id", requestId)
        }
        
        if (deviceId != null) {
            message.put("device_id", deviceId)
        }
        
        if (error != null) {
            message.put("status", "error")
            message.put("error", error)
        } else {
            message.put("status", "success")
            if (data != null) {
                message.put("data", data)
            }
        }
        
        return message
    }
    
    /**
     * 创建任务请求消息（task_request）
     * @param goal 任务目标（自然语言）
     * @param requestId 唯一请求ID
     * @param deviceId 设备ID
     * @param options 可选参数（可为空）
     */
    fun createTaskRequest(
        goal: String,
        requestId: String,
        deviceId: String,
        options: Map<String, Any?>? = null
    ): JSONObject {
        val data = JSONObject().apply {
            put("goal", goal)
            if (options != null && options.isNotEmpty()) {
                val opt = JSONObject()
                options.forEach { (k, v) ->
                    when (v) {
                        null -> {} // 跳过null
                        is Boolean, is Number, is String -> opt.put(k, v)
                        is Map<*, *> -> opt.put(k, JSONObject(v))
                        else -> opt.put(k, v.toString())
                    }
                }
                put("options", opt)
            }
        }
        return createBaseMessage(
            messageType = MessageType.TASK_REQUEST,
            requestId = requestId,
            deviceId = deviceId,
            data = data
        )
    }
    
    /**
     * 创建心跳消息
     */
    fun createHeartbeatMessage(deviceId: String): JSONObject {
        return createBaseMessage(
            messageType = MessageType.HEARTBEAT,
            deviceId = deviceId
        )
    }
    
    /**
     * 创建命令响应消息
     */
    fun createCommandResponse(
        requestId: String,
        status: String,
        data: JSONObject?,
        error: String?,
        deviceId: String
    ): JSONObject {
        val message = createBaseMessage(
            messageType = MessageType.COMMAND_RESPONSE,
            requestId = requestId,
            deviceId = deviceId,
            data = data,
            error = error
        )
        // 覆盖状态
        message.put("status", status)
        return message
    }
    
    /**
     * 创建错误消息
     */
    fun createErrorMessage(requestId: String?, error: String, deviceId: String? = null): JSONObject {
        return createBaseMessage(
            messageType = MessageType.ERROR,
            requestId = requestId,
            deviceId = deviceId,
            error = error
        )
    }
    
    /**
     * 解析消息字符串
     */
    fun parseMessage(jsonString: String): JSONObject? {
        return try {
            JSONObject(jsonString)
        } catch (e: Exception) {
            null
        }
    }
    
    /**
     * 验证消息格式
     */
    fun validateMessage(message: JSONObject): Boolean {
        // 检查必需字段
        if (!message.has("type")) {
            return false
        }
        
        // 检查版本（可选，但建议包含）
        if (message.has("version")) {
            val version = message.optString("version", "")
            if (version != PROTOCOL_VERSION) {
                // 可以在这里添加版本兼容性检查
            }
        }
        
        // 命令消息必须包含 request_id
        val messageType = message.optString("type", "")
        if (messageType == MessageType.COMMAND) {
            if (!message.has("request_id")) {
                return false
            }
            if (message.has("data")) {
                val data = message.optJSONObject("data")
                if (data == null || !data.has("command")) {
                    return false
                }
            }
        }
        
        // 命令响应必须包含 request_id
        if (messageType == MessageType.COMMAND_RESPONSE) {
            if (!message.has("request_id")) {
                return false
            }
        }
        
        // 任务请求必须包含 request_id 和 data.goal
        if (messageType == MessageType.TASK_REQUEST) {
            if (!message.has("request_id")) return false
            val data = message.optJSONObject("data") ?: return false
            if (!data.has("goal")) return false
        }
        
        return true
    }
    
    /**
     * 获取当前时间戳（ISO 8601格式）
     * 使用线程安全的方式生成时间戳
     */
    private fun getCurrentTimestamp(): String {
        return dateFormatter.get().format(Date())
    }
}

