package Agent

/**
 * MobileGPT全局配置类
 */
class MobileGPTGlobal private constructor() {
    
    companion object {
        // 将此IP地址替换为服务器的IP地址
//        const val HOST_IP = "198.18.0.1"
//        const val HOST_IP = "192.168.18.53"
          const val HOST_IP = "192.168.100.26"
//        const val HOST_IP = "192.168.31.182"
//        const val HOST_IP = "198.18.0.1"
        const val HOST_PORT = 12345
        
        // WebSocket服务器配置
        // 注意：
        // - 如果使用Android模拟器，必须使用 "10.0.2.2" 访问宿主机
        // - 如果使用真机，使用宿主机在局域网中的实际IP地址（如 "192.168.1.100"）
        const val WS_HOST_IP = "10.0.2.2"  // 模拟器模式：访问宿主机
        // const val WS_HOST_IP = "192.168.100.32"  // 真机模式：使用实际IP
        const val WS_PORT = 8765                  // 服务端WebSocket端口
        const val WS_PATH = "/ws"                 // WebSocket路径
        // HTTP上传端口（默认 WS_PORT+1）
        const val UPLOAD_PORT = WS_PORT + 1
        const val UPLOAD_PATH = "/upload"
        fun uploadBaseUrl(): String = "http://$WS_HOST_IP:$UPLOAD_PORT$UPLOAD_PATH"
        const val USE_BIN_PROTOCOL = false
        
        // 设备ID配置
        const val DEVICE_ID_KEY = "device_id"     // SharedPreferences键名
        const val HEARTBEAT_INTERVAL = 60000L     // 心跳间隔60秒
        const val CONNECTION_TIMEOUT = 10L        // 连接超时10秒
        const val COMMAND_TIMEOUT = 30000L        // 命令执行超时30秒
        
        const val STRING_ACTION = "com.example.MobileGPT.STRING_ACTION"
        const val INSTRUCTION_EXTRA = "com.example.MobileGPT.INSTRUCTION_EXTRA"
        const val APP_NAME_EXTRA = "com.example.MobileGPT.APP_NAME_EXTRA"
        
        // Ask功能相关常量
        const val ANSWER_ACTION = "com.example.MobileGPT.ANSWER_ACTION"
        const val INFO_NAME_EXTRA = "com.example.MobileGPT.INFO_NAME_EXTRA"
        const val QUESTION_EXTRA = "com.example.MobileGPT.QUESTION_EXTRA"
        const val ANSWER_EXTRA = "com.example.MobileGPT.ANSWER_EXTRA"
        
        
        @Volatile
        private var sInstance: MobileGPTGlobal? = null
        
        /**
         * 获取单例实例
         * @return MobileGPTGlobal实例
         */
        @Synchronized
        fun getInstance(): MobileGPTGlobal {
            return sInstance ?: MobileGPTGlobal().also { sInstance = it }
        }
        
        /**
         * 重置单例实例
         * @return 新的MobileGPTGlobal实例
         */
        @Synchronized
        fun reset(): MobileGPTGlobal {
            sInstance = MobileGPTGlobal()
            return sInstance!!
        }
    }
}
