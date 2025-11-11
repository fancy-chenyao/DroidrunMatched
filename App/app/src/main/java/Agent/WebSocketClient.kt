package Agent

import android.os.Handler
import android.os.Looper
import android.util.Log
import okhttp3.*
import okio.ByteString
import org.json.JSONObject
import java.util.*
import java.util.concurrent.TimeUnit

/**
 * WebSocket客户端类
 * 负责管理与服务端的WebSocket连接
 */
class WebSocketClient {
    
    companion object {
        private const val TAG = "WebSocketClient"
        private const val MAX_RECONNECT_ATTEMPTS = 3
        private const val RECONNECT_DELAY_MS = 5000L
    }
    
    private var client: OkHttpClient? = null
    private var webSocket: WebSocket? = null
    private var listener: WebSocketListener? = null
    private var isConnected = false
    private var reconnectAttempts = 0
    private var reconnectHandler: Handler? = null
    private var reconnectRunnable: Runnable? = null
    @Volatile
    private var pendingMessages: MutableList<JSONObject> = Collections.synchronizedList(mutableListOf<JSONObject>())
    
    // 保存连接参数用于重连
    private var connectionHost: String? = null
    private var connectionPort: Int? = null
    private var connectionDeviceId: String? = null
    
    /**
     * WebSocket事件监听器接口
     */
    interface WebSocketListener {
        fun onConnected()
        fun onDisconnected(reason: String)
        fun onMessageReceived(message: JSONObject)
        fun onError(error: String)
    }
    
    /**
     * 连接到WebSocket服务器
     */
    fun connect(host: String, port: Int, deviceId: String, listener: WebSocketListener) {
        this.listener = listener
        reconnectHandler = Handler(Looper.getMainLooper())
        
        // 保存连接参数用于重连
        connectionHost = host
        connectionPort = port
        connectionDeviceId = deviceId
        
        // 构建WebSocket URL
        val url = "ws://$host:$port/ws?device_id=$deviceId"
        Log.d(TAG, "正在连接到WebSocket服务器: $url")
        
        // 创建OkHttpClient
        client = OkHttpClient.Builder()
            .connectTimeout(MobileGPTGlobal.CONNECTION_TIMEOUT, TimeUnit.SECONDS)
            .readTimeout(MobileGPTGlobal.COMMAND_TIMEOUT, TimeUnit.MILLISECONDS)
            .writeTimeout(MobileGPTGlobal.COMMAND_TIMEOUT, TimeUnit.MILLISECONDS)
            .build()
        
        // 创建WebSocket请求
        val request = Request.Builder()
            .url(url)
            .build()
        
        // 创建WebSocket监听器
        val wsListener = object : okhttp3.WebSocketListener() {
            override fun onOpen(webSocket: okhttp3.WebSocket, response: Response) {
                Log.d(TAG, "WebSocket连接已建立")
                this@WebSocketClient.webSocket = webSocket
                isConnected = true
                reconnectAttempts = 0
                
                // 发送待发送的消息
                sendPendingMessages()
                
                // 通知监听器
                Handler(Looper.getMainLooper()).post {
                    listener?.onConnected()
                }
            }
            
            override fun onMessage(webSocket: okhttp3.WebSocket, text: String) {
                Log.d(TAG, "收到文本消息: $text")
                try {
                    val message = MessageProtocol.parseMessage(text)
                    if (message != null && MessageProtocol.validateMessage(message)) {
                        Handler(Looper.getMainLooper()).post {
                            listener?.onMessageReceived(message)
                        }
                    } else {
                        Log.w(TAG, "收到无效消息格式")
                        Handler(Looper.getMainLooper()).post {
                            listener?.onError("Invalid message format")
                        }
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "解析消息时发生异常", e)
                    Handler(Looper.getMainLooper()).post {
                        listener?.onError("Parse error: ${e.message}")
                    }
                }
            }
            
            override fun onMessage(webSocket: okhttp3.WebSocket, bytes: ByteString) {
                Log.d(TAG, "收到二进制消息，长度: ${bytes.size}")
                // 如果需要处理二进制消息，可以在这里实现
            }
            
            override fun onClosing(webSocket: okhttp3.WebSocket, code: Int, reason: String) {
                Log.d(TAG, "WebSocket正在关闭: code=$code, reason=$reason")
                webSocket.close(1000, null)
            }
            
            override fun onClosed(webSocket: okhttp3.WebSocket, code: Int, reason: String) {
                Log.d(TAG, "WebSocket已关闭: code=$code, reason=$reason")
                isConnected = false
                this@WebSocketClient.webSocket = null
                
                Handler(Looper.getMainLooper()).post {
                    listener?.onDisconnected("Closed: $reason")
                }
            }
            
            override fun onFailure(webSocket: okhttp3.WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WebSocket连接失败", t)
                isConnected = false
                this@WebSocketClient.webSocket = null
                
                val errorMsg = t.message ?: "Unknown error"
                Handler(Looper.getMainLooper()).post {
                    listener?.onError(errorMsg)
                    listener?.onDisconnected("Failed: $errorMsg")
                }
                
                // 尝试自动重连
                attemptReconnect()
            }
        }
        
        // 建立WebSocket连接
        webSocket = client!!.newWebSocket(request, wsListener)
    }
    
    /**
     * 断开WebSocket连接
     */
    fun disconnect() {
        Log.d(TAG, "断开WebSocket连接")
        cancelReconnect()
        webSocket?.close(1000, "Normal closure")
        webSocket = null
        isConnected = false
        pendingMessages.clear()
        // 清除连接参数
        connectionHost = null
        connectionPort = null
        connectionDeviceId = null
    }
    
    /**
     * 发送消息
     */
    fun sendMessage(message: JSONObject): Boolean {
        if (!isConnected || webSocket == null) {
            Log.w(TAG, "WebSocket未连接，消息将加入待发送队列")
            pendingMessages.add(message)
            return false
        }
        
        return try {
            val messageStr = message.toString()
            Log.d(TAG, "准备发送消息: type=${message.optString("type", "unknown")}, length=${messageStr.length}")
            Log.d(TAG, "消息内容: ${messageStr.take(500)}")  // 记录前500个字符
            val result = webSocket!!.send(messageStr)
            if (result) {
                Log.d(TAG, "✓ 消息已成功发送: type=${message.optString("type", "unknown")}")
            } else {
                Log.w(TAG, "✗ 消息发送失败，加入待发送队列")
                pendingMessages.add(message)
            }
            result
        } catch (e: Exception) {
            Log.e(TAG, "发送消息时发生异常", e)
            pendingMessages.add(message)
            false
        }
    }
    
    /**
     * 发送二进制消息
     * @param bytes 二进制数据
     * @return 是否发送成功
     */
    fun sendBinaryMessage(bytes: ByteArray): Boolean {
        if (!isConnected || webSocket == null) {
            Log.w(TAG, "WebSocket未连接，无法发送二进制消息")
            return false
        }
        
        return try {
            val byteString = ByteString.of(*bytes)
            val result = webSocket!!.send(byteString)
            if (result) {
                Log.d(TAG, "✓ 二进制消息已成功发送: size=${bytes.size} bytes")
            } else {
                Log.w(TAG, "✗ 二进制消息发送失败")
            }
            result
        } catch (e: Exception) {
            Log.e(TAG, "发送二进制消息时发生异常", e)
            false
        }
    }
    
    /**
     * 发送文本消息（字符串）
     * @param text 文本内容
     * @return 是否发送成功
     */
    fun sendTextMessage(text: String): Boolean {
        if (!isConnected || webSocket == null) {
            Log.w(TAG, "WebSocket未连接，无法发送文本消息")
            return false
        }
        
        return try {
            val result = webSocket!!.send(text)
            if (result) {
                Log.d(TAG, "✓ 文本消息已成功发送: length=${text.length}")
            } else {
                Log.w(TAG, "✗ 文本消息发送失败")
            }
            result
        } catch (e: Exception) {
            Log.e(TAG, "发送文本消息时发生异常", e)
            false
        }
    }
    
    /**
     * 发送心跳消息
     */
    fun sendHeartbeat(deviceId: String) {
        val heartbeat = MessageProtocol.createHeartbeatMessage(deviceId)
        sendMessage(heartbeat)
    }
    
    /**
     * 获取连接状态
     */
    fun isConnected(): Boolean {
        return isConnected && webSocket != null
    }
    
    /**
     * 发送待发送的消息
     */
    private fun sendPendingMessages() {
        if (pendingMessages.isEmpty()) {
            return
        }
        
        Log.d(TAG, "发送 ${pendingMessages.size} 条待发送消息")
        val messagesToSend = ArrayList(pendingMessages)
        pendingMessages.clear()
        
        for (message in messagesToSend) {
            sendMessage(message)
        }
    }
    
    /**
     * 尝试自动重连
     */
    private fun attemptReconnect() {
        if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            Log.e(TAG, "已达到最大重连次数，停止重连")
            return
        }
        
        // 检查是否有保存的连接参数
        val host = connectionHost
        val port = connectionPort
        val deviceId = connectionDeviceId
        val currentListener = listener
        
        if (host == null || port == null || deviceId == null || currentListener == null) {
            Log.e(TAG, "缺少重连所需的连接参数，无法重连")
            return
        }
        
        reconnectAttempts++
        Log.d(TAG, "准备重连 (尝试 $reconnectAttempts/$MAX_RECONNECT_ATTEMPTS)")
        
        reconnectRunnable = Runnable {
            Log.d(TAG, "执行重连...")
            connect(host, port, deviceId, currentListener)
        }
        
        reconnectHandler?.postDelayed(reconnectRunnable!!, RECONNECT_DELAY_MS)
    }
    
    /**
     * 取消重连
     */
    private fun cancelReconnect() {
        reconnectRunnable?.let {
            reconnectHandler?.removeCallbacks(it)
        }
        reconnectRunnable = null
        reconnectAttempts = 0
    }
}

