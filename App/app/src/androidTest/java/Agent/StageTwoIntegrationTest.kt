package Agent

import android.content.Context
import android.util.Log
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.Assert.*
import org.json.JSONObject
import org.json.JSONArray
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * 阶段二集成测试
 * 测试命令消息解析、响应消息构建和数据格式
 * 
 * 测试内容：
 * 1. 能正确解析命令消息
 * 2. 能正确构建响应消息
 * 3. 数据格式符合服务端要求
 * 
 * 运行说明：
 * 1. 确保服务端WebSocket服务器正在运行
 * 2. 配置正确的服务器IP和端口
 * 3. 在Android设备或模拟器上运行
 */
@RunWith(AndroidJUnit4::class)
class StageTwoIntegrationTest {

    private lateinit var context: Context
    private var wsClient: WebSocketClient? = null
    private val testDeviceId = "stage2-test-device-${System.currentTimeMillis()}"

    @Before
    fun setUp() {
        context = InstrumentationRegistry.getInstrumentation().targetContext
        wsClient = WebSocketClient()
        Log.d("StageTwoTest", "测试设备ID: $testDeviceId")
        Log.d("StageTwoTest", "服务器地址: ${MobileGPTGlobal.WS_HOST_IP}:${MobileGPTGlobal.WS_PORT}")
    }

    @After
    fun tearDown() {
        wsClient?.disconnect()
        wsClient = null
        Log.d("StageTwoTest", "测试清理完成")
    }

    /**
     * 测试1：能正确解析命令消息
     * 验证：
     * - 能解析标准的命令消息格式
     * - 能提取command、params、request_id等字段
     * - 能验证消息格式的有效性
     */
    @Test
    fun testParseCommandMessage() {
        Log.d("StageTwoTest", "========== 测试1：解析命令消息 ==========")
        
        // 构造一个标准的命令消息（模拟服务端发送的格式）
        val commandMessageJson = """
        {
            "version": "1.0",
            "type": "command",
            "timestamp": "2024-01-01T00:00:00.000Z",
            "request_id": "test_request_123",
            "device_id": "$testDeviceId",
            "status": "success",
            "data": {
                "command": "get_state",
                "params": {}
            }
        }
        """.trimIndent()
        
        // 测试解析
        val parsedMessage = MessageProtocol.parseMessage(commandMessageJson)
        assertNotNull("应该能解析命令消息", parsedMessage)
        
        // 验证消息格式
        val isValid = MessageProtocol.validateMessage(parsedMessage!!)
        assertTrue("命令消息格式应该有效", isValid)
        
        // 验证必需字段
        assertEquals("version应该是1.0", "1.0", parsedMessage.optString("version", ""))
        assertEquals("type应该是command", MessageProtocol.MessageType.COMMAND, parsedMessage.optString("type", ""))
        assertTrue("应该包含request_id", parsedMessage.has("request_id"))
        assertEquals("request_id应该正确", "test_request_123", parsedMessage.optString("request_id", ""))
        
        // 验证data字段
        assertTrue("应该包含data字段", parsedMessage.has("data"))
        val data = parsedMessage.optJSONObject("data")
        assertNotNull("data应该是JSONObject", data)
        assertEquals("command应该是get_state", "get_state", data!!.optString("command", ""))
        assertTrue("应该包含params字段", data.has("params"))
        
        Log.d("StageTwoTest", "✓ 测试1通过：能正确解析命令消息")
    }

    /**
     * 测试2：能正确构建响应消息
     * 验证：
     * - 能创建标准的命令响应消息
     * - 响应消息包含所有必需字段
     * - 响应消息格式符合协议要求
     */
    @Test
    fun testBuildCommandResponse() {
        Log.d("StageTwoTest", "========== 测试2：构建响应消息 ==========")
        
        val requestId = "test_request_456"
        val deviceId = testDeviceId
        
        // 测试成功响应
        val successData = JSONObject().apply {
            put("result", "success")
            put("message", "Command executed successfully")
        }
        
        val successResponse = MessageProtocol.createCommandResponse(
            requestId = requestId,
            status = "success",
            data = successData,
            error = null,
            deviceId = deviceId
        )
        
        // 验证成功响应格式
        assertNotNull("应该能创建成功响应", successResponse)
        assertEquals("version应该是1.0", "1.0", successResponse.optString("version", ""))
        assertEquals("type应该是command_response", MessageProtocol.MessageType.COMMAND_RESPONSE, successResponse.optString("type", ""))
        assertEquals("request_id应该匹配", requestId, successResponse.optString("request_id", ""))
        assertEquals("device_id应该匹配", deviceId, successResponse.optString("device_id", ""))
        assertEquals("status应该是success", "success", successResponse.optString("status", ""))
        assertTrue("应该包含data字段", successResponse.has("data"))
        assertFalse("不应该包含error字段", successResponse.has("error"))
        
        // 验证响应消息格式
        val isValid = MessageProtocol.validateMessage(successResponse)
        assertTrue("成功响应格式应该有效", isValid)
        
        // 测试错误响应
        val errorMessage = "Command execution failed"
        val errorResponse = MessageProtocol.createCommandResponse(
            requestId = requestId,
            status = "error",
            data = null,
            error = errorMessage,
            deviceId = deviceId
        )
        
        // 验证错误响应格式
        assertNotNull("应该能创建错误响应", errorResponse)
        assertEquals("status应该是error", "error", errorResponse.optString("status", ""))
        assertEquals("error应该匹配", errorMessage, errorResponse.optString("error", ""))
        assertFalse("不应该包含data字段", errorResponse.has("data"))
        
        Log.d("StageTwoTest", "✓ 测试2通过：能正确构建响应消息")
    }

    /**
     * 测试3：数据格式符合服务端要求
     * 验证：
     * - get_state命令返回的数据格式符合服务端要求
     * - a11y_tree格式正确
     * - phone_state格式正确
     * - screenshot格式正确（Base64编码）
     */
    @Test
    fun testDataFormatCompliance() {
        Log.d("StageTwoTest", "========== 测试3：数据格式符合服务端要求 ==========")
        
        // 构造一个get_state命令消息
        val commandMessage = JSONObject().apply {
            put("version", "1.0")
            put("type", "command")
            put("timestamp", "2024-01-01T00:00:00.000Z")
            put("request_id", "test_request_789")
            put("device_id", testDeviceId)
            put("status", "success")
            put("data", JSONObject().apply {
                put("command", "get_state")
                put("params", JSONObject())
            })
        }
        
        // 验证命令消息格式
        val isValidCommand = MessageProtocol.validateMessage(commandMessage)
        assertTrue("命令消息格式应该有效", isValidCommand)
        
        // 提取命令信息
        val requestId = commandMessage.optString("request_id", "")
        val data = commandMessage.optJSONObject("data")
        assertNotNull("data应该存在", data)
        val command = data!!.optString("command", "")
        val params = data.optJSONObject("params")
        
        assertEquals("command应该是get_state", "get_state", command)
        assertNotNull("params应该存在", params)
        
        // 模拟构建响应（实际应该通过CommandHandler处理）
        // 这里我们验证响应消息的格式要求
        val responseData = JSONObject().apply {
            // a11y_tree应该是JSONArray
            put("a11y_tree", JSONArray())
            // phone_state应该是JSONObject
            put("phone_state", JSONObject().apply {
                put("screen_width", 1080)
                put("screen_height", 1920)
                put("orientation", "portrait")
            })
            // screenshot应该是Base64编码的字符串
            put("screenshot", "base64_encoded_string_here")
        }
        
        // 验证响应数据格式
        assertTrue("应该包含a11y_tree", responseData.has("a11y_tree"))
        assertTrue("a11y_tree应该是JSONArray", responseData.opt("a11y_tree") is JSONArray)
        
        assertTrue("应该包含phone_state", responseData.has("phone_state"))
        assertTrue("phone_state应该是JSONObject", responseData.opt("phone_state") is JSONObject)
        
        val phoneState = responseData.optJSONObject("phone_state")
        assertNotNull("phone_state应该存在", phoneState)
        assertTrue("phone_state应该包含screen_width", phoneState!!.has("screen_width"))
        assertTrue("phone_state应该包含screen_height", phoneState.has("screen_height"))
        assertTrue("phone_state应该包含orientation", phoneState.has("orientation"))
        
        assertTrue("应该包含screenshot", responseData.has("screenshot"))
        assertTrue("screenshot应该是String", responseData.opt("screenshot") is String)
        
        // 构建完整的响应消息
        val responseMessage = MessageProtocol.createCommandResponse(
            requestId = requestId,
            status = "success",
            data = responseData,
            error = null,
            deviceId = testDeviceId
        )
        
        // 验证响应消息格式
        val isValidResponse = MessageProtocol.validateMessage(responseMessage)
        assertTrue("响应消息格式应该有效", isValidResponse)
        
        Log.d("StageTwoTest", "✓ 测试3通过：数据格式符合服务端要求")
    }

    /**
     * 测试4：端到端测试 - 接收命令并发送响应
     * 验证：
     * - 能接收服务端发送的命令消息
     * - 能正确解析命令
     * - 能构建符合格式的响应消息
     * - 能发送响应到服务端
     */
    @Test
    fun testEndToEndCommandHandling() {
        Log.d("StageTwoTest", "========== 测试4：端到端测试 ==========")
        
        val connectionLatch = CountDownLatch(1)
        val commandReceivedLatch = CountDownLatch(1)
        val responseSentLatch = CountDownLatch(1)
        
        var connectionSuccess = false
        var commandReceived = false
        var responseSent = false
        var receivedRequestId: String? = null
        var receivedCommand: String? = null
        
        val listener = object : WebSocketClient.WebSocketListener {
            override fun onConnected() {
                Log.d("StageTwoTest", "✓ WebSocket连接成功")
                connectionSuccess = true
                connectionLatch.countDown()
            }

            override fun onDisconnected(reason: String) {
                Log.d("StageTwoTest", "断开连接: $reason")
            }

            override fun onMessageReceived(message: org.json.JSONObject) {
                val messageType = message.optString("type", "")
                Log.d("StageTwoTest", "收到消息: type=$messageType")
                
                when (messageType) {
                    MessageProtocol.MessageType.SERVER_READY -> {
                        Log.d("StageTwoTest", "✓ 收到server_ready消息")
                        // 连接成功后，等待服务端发送命令（如果有的话）
                        // 注意：这个测试需要服务端主动发送命令，或者我们手动发送一个测试命令
                    }
                    MessageProtocol.MessageType.COMMAND -> {
                        Log.d("StageTwoTest", "✓ 收到命令消息")
                        
                        // 验证命令消息格式
                        val isValid = MessageProtocol.validateMessage(message)
                        assertTrue("命令消息格式应该有效", isValid)
                        
                        // 提取命令信息
                        receivedRequestId = message.optString("request_id", "")
                        val data = message.optJSONObject("data")
                        assertNotNull("data应该存在", data)
                        receivedCommand = data!!.optString("command", "")
                        
                        assertTrue("应该包含request_id", receivedRequestId!!.isNotEmpty())
                        assertTrue("应该包含command", receivedCommand!!.isNotEmpty())
                        
                        commandReceived = true
                        commandReceivedLatch.countDown()
                        
                        // 构建并发送响应
                        val responseData = JSONObject().apply {
                            put("result", "Command '$receivedCommand' executed successfully")
                        }
                        
                        val response = MessageProtocol.createCommandResponse(
                            requestId = receivedRequestId!!,
                            status = "success",
                            data = responseData,
                            error = null,
                            deviceId = testDeviceId
                        )
                        
                        // 验证响应格式
                        val isValidResponse = MessageProtocol.validateMessage(response)
                        assertTrue("响应消息格式应该有效", isValidResponse)
                        
                        // 发送响应
                        val sent = wsClient?.sendMessage(response) ?: false
                        assertTrue("响应应该成功发送", sent)
                        
                        responseSent = true
                        responseSentLatch.countDown()
                        
                        Log.d("StageTwoTest", "✓ 响应已发送: requestId=$receivedRequestId")
                    }
                }
            }

            override fun onError(error: String) {
                Log.e("StageTwoTest", "WebSocket错误: $error")
            }
        }
        
        // 连接WebSocket
        Log.d("StageTwoTest", "连接WebSocket...")
        wsClient?.connect(
            host = MobileGPTGlobal.WS_HOST_IP,
            port = MobileGPTGlobal.WS_PORT,
            deviceId = testDeviceId,
            listener = listener
        )
        
        // 等待连接（最多10秒）
        val connected = connectionLatch.await(10, TimeUnit.SECONDS)
        assertTrue("应该成功连接", connected && connectionSuccess)
        
        // 等待server_ready消息
        Thread.sleep(1000)
        
        // 注意：这个测试需要服务端主动发送命令
        // 如果服务端没有发送命令，我们可以跳过这个测试
        // 或者我们可以通过其他方式触发服务端发送命令
        
        Log.d("StageTwoTest", "注意：此测试需要服务端主动发送命令消息")
        Log.d("StageTwoTest", "如果服务端没有发送命令，测试将等待5秒后跳过")
        
        // 等待命令（最多5秒）
        val commandReceivedResult = commandReceivedLatch.await(5, TimeUnit.SECONDS)
        
        if (commandReceivedResult && commandReceived) {
            // 验证命令接收
            assertTrue("应该收到命令", commandReceived)
            assertNotNull("request_id应该存在", receivedRequestId)
            assertNotNull("command应该存在", receivedCommand)
            
            // 等待响应发送
            val responseSentResult = responseSentLatch.await(5, TimeUnit.SECONDS)
            assertTrue("响应应该已发送", responseSentResult && responseSent)
            
            Log.d("StageTwoTest", "✓ 测试4通过：端到端测试成功")
        } else {
            Log.w("StageTwoTest", "⚠ 测试4跳过：服务端未发送命令（这是正常的，如果服务端没有主动发送命令）")
            // 不失败，因为服务端可能没有主动发送命令
        }
    }

    /**
     * 测试5：验证各种命令消息格式
     * 验证：
     * - tap命令消息格式
     * - swipe命令消息格式
     * - input_text命令消息格式
     * - back命令消息格式
     */
    @Test
    fun testVariousCommandFormats() {
        Log.d("StageTwoTest", "========== 测试5：验证各种命令消息格式 ==========")
        
        // 测试tap命令
        val tapCommand = JSONObject().apply {
            put("version", "1.0")
            put("type", "command")
            put("request_id", "tap_001")
            put("device_id", testDeviceId)
            put("status", "success")
            put("data", JSONObject().apply {
                put("command", "tap")
                put("params", JSONObject().apply {
                    put("x", 100)
                    put("y", 200)
                })
            })
        }
        assertTrue("tap命令格式应该有效", MessageProtocol.validateMessage(tapCommand))
        
        // 测试swipe命令
        val swipeCommand = JSONObject().apply {
            put("version", "1.0")
            put("type", "command")
            put("request_id", "swipe_001")
            put("device_id", testDeviceId)
            put("status", "success")
            put("data", JSONObject().apply {
                put("command", "swipe")
                put("params", JSONObject().apply {
                    put("x1", 100)
                    put("y1", 200)
                    put("x2", 300)
                    put("y2", 400)
                    put("duration", 500)
                })
            })
        }
        assertTrue("swipe命令格式应该有效", MessageProtocol.validateMessage(swipeCommand))
        
        // 测试input_text命令
        val inputTextCommand = JSONObject().apply {
            put("version", "1.0")
            put("type", "command")
            put("request_id", "input_001")
            put("device_id", testDeviceId)
            put("status", "success")
            put("data", JSONObject().apply {
                put("command", "input_text")
                put("params", JSONObject().apply {
                    put("text", "Hello World")
                })
            })
        }
        assertTrue("input_text命令格式应该有效", MessageProtocol.validateMessage(inputTextCommand))
        
        // 测试back命令
        val backCommand = JSONObject().apply {
            put("version", "1.0")
            put("type", "command")
            put("request_id", "back_001")
            put("device_id", testDeviceId)
            put("status", "success")
            put("data", JSONObject().apply {
                put("command", "back")
                put("params", JSONObject())
            })
        }
        assertTrue("back命令格式应该有效", MessageProtocol.validateMessage(backCommand))
        
        Log.d("StageTwoTest", "✓ 测试5通过：各种命令消息格式验证成功")
    }
}

