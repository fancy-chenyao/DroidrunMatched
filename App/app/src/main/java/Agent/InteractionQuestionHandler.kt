package Agent

import android.app.AlertDialog
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.LayoutInflater
import android.widget.EditText
import android.widget.Toast
import org.json.JSONArray
import org.json.JSONObject

/**
 * 交互式问答处理器
 * 
 * 处理来自服务器的用户问题，显示对话框，并将答案发送回服务器。
 * 支持三种问题类型：text（文本输入）、choice（单选）、confirm（确认）
 * 
 * @property context Android 上下文
 * @property webSocketClient WebSocket 客户端用于发送答案
 */
class InteractionQuestionHandler(
    private val context: Context,
    private val webSocketClient: WebSocketClient
) {
    
    companion object {
        private const val TAG = "InteractionQuestionHandler"
        
        // 问题类型
        const val TYPE_TEXT = "text"
        const val TYPE_CHOICE = "choice"
        const val TYPE_CONFIRM = "confirm"
    }
    
    private var currentDialog: AlertDialog? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    
    /**
     * 处理用户问题消息
     * 
     * @param message 问题消息
     *   {
     *       "type": "user_question",
     *       "question_id": "q-abc123",
     *       "question_text": "请输入您的姓名",
     *       "question_type": "text|choice|confirm",
     *       "options": [...],  // 可选，choice 类型时使用
     *       "default_value": "默认值",  // 可选
     *       "timeout_seconds": 60.0
     *   }
     */
    fun handleQuestionMessage(message: JSONObject) {
        try {
            val questionId = message.getString("question_id")
            val questionText = message.getString("question_text")
            val questionType = message.getString("question_type")
            val defaultValue = message.optString("default_value", "")
            val timeoutSeconds = message.optDouble("timeout_seconds", 60.0)
            
            Log.d(TAG, "收到问题: id=$questionId, type=$questionType")
            Log.d(TAG, "问题文本: $questionText")
            
            // 在主线程中显示对话框
            mainHandler.post {
                when (questionType) {
                    TYPE_TEXT -> showTextInputDialog(
                        questionId, 
                        questionText, 
                        defaultValue,
                        timeoutSeconds
                    )
                    TYPE_CHOICE -> {
                        val options = message.optJSONArray("options") ?: JSONArray()
                        showChoiceDialog(
                            questionId,
                            questionText,
                            options,
                            defaultValue,
                            timeoutSeconds
                        )
                    }
                    TYPE_CONFIRM -> showConfirmDialog(
                        questionId,
                        questionText,
                        defaultValue,
                        timeoutSeconds
                    )
                    else -> {
                        Log.e(TAG, "未知的问题类型: $questionType")
                        sendAnswer(questionId, defaultValue)
                    }
                }
            }
            
        } catch (e: Exception) {
            Log.e(TAG, "处理问题消息失败", e)
        }
    }
    
    /**
     * 显示文本输入对话框
     */
    private fun showTextInputDialog(
        questionId: String,
        questionText: String,
        defaultValue: String,
        timeoutSeconds: Double
    ) {
        // 关闭之前的对话框（如果有）
        dismissCurrentDialog()
        
        // 创建输入框
        val input = EditText(context).apply {
            setText(defaultValue)
            setSingleLine()
            // 自动选择所有文本
            post {
                selectAll()
                requestFocus()
            }
        }
        
        // 创建对话框
        val dialog = AlertDialog.Builder(context)
            .setTitle("Agent 询问")
            .setMessage(questionText)
            .setView(input)
            .setPositiveButton("确定") { dialog, _ ->
                val answer = input.text.toString()
                sendAnswer(questionId, answer)
                Log.d(TAG, "用户输入: $answer")
                dialog.dismiss()
            }
            .setNegativeButton("取消") { dialog, _ ->
                sendAnswer(questionId, defaultValue)
                Log.d(TAG, "用户取消，使用默认值: $defaultValue")
                dialog.dismiss()
            }
            .setCancelable(false)
            .create()
        
        dialog.show()
        currentDialog = dialog
        
        // 设置超时
        if (timeoutSeconds > 0) {
            setupTimeout(questionId, defaultValue, timeoutSeconds)
        }
    }
    
    /**
     * 显示单选对话框
     */
    private fun showChoiceDialog(
        questionId: String,
        questionText: String,
        options: JSONArray,
        defaultValue: String,
        timeoutSeconds: Double
    ) {
        // 关闭之前的对话框（如果有）
        dismissCurrentDialog()
        
        // 转换选项
        val items = Array(options.length()) { i ->
            options.getString(i)
        }
        
        if (items.isEmpty()) {
            Log.e(TAG, "选项列表为空")
            sendAnswer(questionId, defaultValue)
            return
        }
        
        // 找到默认选中项
        val defaultIndex = items.indexOf(defaultValue).let { 
            if (it >= 0) it else 0 
        }
        var selectedIndex = defaultIndex
        
        // 创建对话框
        val dialog = AlertDialog.Builder(context)
            .setTitle("Agent 询问")
            .setMessage(questionText)
            .setSingleChoiceItems(items, defaultIndex) { _, which ->
                selectedIndex = which
            }
            .setPositiveButton("确定") { dialog, _ ->
                val answer = items[selectedIndex]
                sendAnswer(questionId, answer)
                Log.d(TAG, "用户选择: $answer")
                dialog.dismiss()
            }
            .setNegativeButton("取消") { dialog, _ ->
                sendAnswer(questionId, defaultValue)
                Log.d(TAG, "用户取消，使用默认值: $defaultValue")
                dialog.dismiss()
            }
            .setCancelable(false)
            .create()
        
        dialog.show()
        currentDialog = dialog
        
        // 设置超时
        if (timeoutSeconds > 0) {
            setupTimeout(questionId, defaultValue, timeoutSeconds)
        }
    }
    
    /**
     * 显示确认对话框
     */
    private fun showConfirmDialog(
        questionId: String,
        questionText: String,
        defaultValue: String,
        timeoutSeconds: Double
    ) {
        // 关闭之前的对话框（如果有）
        dismissCurrentDialog()
        
        // 创建对话框
        val dialog = AlertDialog.Builder(context)
            .setTitle("Agent 询问")
            .setMessage(questionText)
            .setPositiveButton("是") { dialog, _ ->
                sendAnswer(questionId, "yes")
                Log.d(TAG, "用户确认: yes")
                dialog.dismiss()
            }
            .setNegativeButton("否") { dialog, _ ->
                sendAnswer(questionId, "no")
                Log.d(TAG, "用户拒绝: no")
                dialog.dismiss()
            }
            .setCancelable(false)
            .create()
        
        dialog.show()
        currentDialog = dialog
        
        // 设置超时
        if (timeoutSeconds > 0) {
            setupTimeout(questionId, defaultValue, timeoutSeconds)
        }
    }
    
    /**
     * 设置超时自动回答
     */
    private fun setupTimeout(
        questionId: String,
        defaultValue: String,
        timeoutSeconds: Double
    ) {
        val timeoutMs = (timeoutSeconds * 1000).toLong()
        
        mainHandler.postDelayed({
            if (currentDialog?.isShowing == true) {
                currentDialog?.dismiss()
                sendAnswer(questionId, defaultValue)
                
                Toast.makeText(
                    context,
                    "超时未回答，已使用默认值",
                    Toast.LENGTH_SHORT
                ).show()
                
                Log.d(TAG, "超时自动回答: $defaultValue")
            }
        }, timeoutMs)
    }
    
    /**
     * 发送答案到服务器
     * 
     * @param questionId 问题ID
     * @param answer 用户答案
     */
    private fun sendAnswer(questionId: String, answer: String) {
        try {
            val answerMessage = JSONObject().apply {
                put("type", "user_answer")
                put("question_id", questionId)
                put("answer", answer)
                put("timestamp", System.currentTimeMillis())
            }
            
            webSocketClient.sendMessage(answerMessage)
            Log.d(TAG, "答案已发送: question_id=$questionId, answer=$answer")
            
        } catch (e: Exception) {
            Log.e(TAG, "发送答案失败", e)
        }
    }
    
    /**
     * 关闭当前对话框
     */
    private fun dismissCurrentDialog() {
        currentDialog?.let { dialog ->
            if (dialog.isShowing) {
                dialog.dismiss()
            }
        }
        currentDialog = null
    }
    
    /**
     * 清理资源
     */
    fun cleanup() {
        dismissCurrentDialog()
        mainHandler.removeCallbacksAndMessages(null)
    }
}
