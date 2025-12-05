# Android 端交互式执行集成指南

## 📋 概述

本文档说明如何在 Android 客户端实现交互式执行功能，使 Agent 能够在执行过程中询问用户问题。

**目标**: 
- 接收来自服务器的问题消息
- 在 Android 端显示对话框
- 将用户答案发送回服务器

## ✅ 已提供的 Kotlin 实现文件

**本项目已包含完整的 Kotlin 实现，开箱即用！**

| 文件 | 位置 | 功能 |
|------|------|------|
| **InteractionQuestionHandler.kt** | `App/app/src/main/java/Agent/` | 问题处理核心类 |
| **MessageProtocol.kt** | `App/app/src/main/java/Agent/` | 消息类型定义（已更新）|
| **InteractionIntegrationExample.kt** | `App/app/src/main/java/Agent/` | 集成示例代码 |

**快速开始**：
1. 查看 `InteractionQuestionHandler.kt` 了解核心实现
2. 查看 `InteractionIntegrationExample.kt` 了解如何集成
3. 在你的 Service 中按照示例集成即可

---

## 🔄 完整流程

```
1. Agent 执行任务
   ↓
2. 需要用户输入
   ↓
3. 服务器发送问题消息（WebSocket）
   {
       "type": "user_question",
       "question_id": "q-abc123",
       "question_text": "请输入用户名",
       "question_type": "text",
       ...
   }
   ↓
4. Android 端接收消息
   ↓
5. 显示对话框
   ↓
6. 用户输入答案
   ↓
7. Android 端发送答案消息（WebSocket）
   {
       "type": "user_answer",
       "question_id": "q-abc123",
       "answer": "用户输入"
   }
   ↓
8. 服务器接收答案
   ↓
9. Agent 继续执行
```

---

## 📨 消息协议

### 1. 问题消息（服务器 → Android）

**消息类型**: `user_question`

**格式**:
```json
{
    "type": "user_question",
    "question_id": "q-abc123",
    "question_text": "请输入您的姓名",
    "question_type": "text",
    "options": [],
    "default_value": "访客",
    "timeout_seconds": 60.0
}
```

**字段说明**:

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `type` | string | ✅ | 固定为 "user_question" |
| `question_id` | string | ✅ | 问题唯一标识（用于关联答案）|
| `question_text` | string | ✅ | 问题文本 |
| `question_type` | string | ✅ | 问题类型：text/choice/confirm |
| `options` | array | ❌ | 选项列表（choice 类型时使用）|
| `default_value` | string | ❌ | 默认值（超时时使用）|
| `timeout_seconds` | number | ✅ | 超时秒数 |

---

### 2. 答案消息（Android → 服务器）

**消息类型**: `user_answer`

**格式**:
```json
{
    "type": "user_answer",
    "question_id": "q-abc123",
    "answer": "用户的答案",
    "additional_data": {}
}
```

**字段说明**:

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `type` | string | ✅ | 固定为 "user_answer" |
| `question_id` | string | ✅ | 问题ID（与接收的问题ID一致）|
| `answer` | string | ✅ | 用户的答案 |
| `additional_data` | object | ❌ | 额外数据（可选）|

---

## 🎨 三种问题类型

### 1. 文本输入 (text)

**用途**: 让用户输入任意文本

**问题消息示例**:
```json
{
    "type": "user_question",
    "question_id": "q-001",
    "question_text": "请输入您的姓名：",
    "question_type": "text",
    "default_value": "访客",
    "timeout_seconds": 60.0
}
```

**UI 实现建议**:
- 显示一个带输入框的对话框
- 输入框预填充 `default_value`（如果有）
- 提供"确定"和"取消"按钮

**答案示例**:
```json
{
    "type": "user_answer",
    "question_id": "q-001",
    "answer": "张三"
}
```

---

### 2. 单选 (choice)

**用途**: 让用户从多个选项中选择一个

**问题消息示例**:
```json
{
    "type": "user_question",
    "question_id": "q-002",
    "question_text": "请选择日期格式：",
    "question_type": "choice",
    "options": ["2025-12-05", "12/05/2025", "05-Dec-2025"],
    "default_value": "2025-12-05",
    "timeout_seconds": 30.0
}
```

**UI 实现建议**:
- 显示一个单选列表
- 默认选中 `default_value` 对应的选项
- 提供"确定"和"取消"按钮

**答案示例**:
```json
{
    "type": "user_answer",
    "question_id": "q-002",
    "answer": "12/05/2025"
}
```

**注意**: 答案必须是 `options` 中的一个值

---

### 3. 确认 (confirm)

**用途**: 让用户确认是否执行某个操作

**问题消息示例**:
```json
{
    "type": "user_question",
    "question_id": "q-003",
    "question_text": "确认要删除所有数据吗？此操作无法撤销。",
    "question_type": "confirm",
    "default_value": "no",
    "timeout_seconds": 30.0
}
```

**UI 实现建议**:
- 显示一个确认对话框
- 提供"是"和"否"按钮（或类似的）
- 默认按钮根据 `default_value` 决定

**答案示例**:
```json
{
    "type": "user_answer",
    "question_id": "q-003",
    "answer": "yes"
}
```

**答案格式**:
- 确认: "yes", "y", "是", "确认", "ok"
- 取消: "no", "n", "否", "取消", "cancel"

---

## 💻 Android 端实现

### 方式 1: 使用已提供的实现（推荐）⭐

**步骤 1**: 查看核心实现

文件位置：`App/app/src/main/java/Agent/InteractionQuestionHandler.kt`

这个类已经完整实现了三种问题类型的处理：
- ✅ 文本输入对话框
- ✅ 单选对话框
- ✅ 确认对话框
- ✅ 超时自动回答
- ✅ 答案发送

**步骤 2**: 集成到你的 Service

参考文件：`App/app/src/main/java/Agent/InteractionIntegrationExample.kt`

```kotlin
// 在你的 Service 中
class MobileService : Service() {
    private lateinit var interactionIntegration: InteractionIntegrationExample
    
    override fun onCreate() {
        super.onCreate()
        
        // 创建交互集成
        interactionIntegration = InteractionIntegrationExample(this, webSocketClient)
    }
    
    // 在 WebSocket 消息回调中
    override fun onMessageReceived(message: JSONObject) {
        interactionIntegration.handleWebSocketMessage(message)
    }
    
    override fun onDestroy() {
        super.onDestroy()
        interactionIntegration.cleanup()
    }
}
```

**步骤 3**: 更新 MessageProtocol（已完成）

文件已更新：`App/app/src/main/java/Agent/MessageProtocol.kt`
- ✅ 已添加 `USER_QUESTION` 消息类型
- ✅ 已添加 `USER_ANSWER` 消息类型

---

### 方式 2: 自定义实现（参考）

如果你需要自定义对话框样式或行为，可以参考以下示例：

```kotlin
// 1. 监听 WebSocket 消息
private fun handleWebSocketMessage(message: JSONObject) {
    when (message.getString("type")) {
        "user_question" -> handleUserQuestion(message)
        // 其他消息类型...
    }
}

// 2. 处理问题消息
private fun handleUserQuestion(message: JSONObject) {
    val questionId = message.getString("question_id")
    val questionText = message.getString("question_text")
    val questionType = message.getString("question_type")
    val defaultValue = message.optString("default_value", "")
    
    when (questionType) {
        "text" -> showTextInputDialog(questionId, questionText, defaultValue)
        "choice" -> {
            val options = message.getJSONArray("options")
            showChoiceDialog(questionId, questionText, options, defaultValue)
        }
        "confirm" -> showConfirmDialog(questionId, questionText, defaultValue)
    }
}

// 3. 显示文本输入对话框
private fun showTextInputDialog(
    questionId: String,
    questionText: String,
    defaultValue: String
) {
    val builder = AlertDialog.Builder(this)
    val input = EditText(this)
    input.setText(defaultValue)
    
    builder.setTitle("Agent 询问")
        .setMessage(questionText)
        .setView(input)
        .setPositiveButton("确定") { dialog, _ ->
            val answer = input.text.toString()
            sendAnswer(questionId, answer)
            dialog.dismiss()
        }
        .setNegativeButton("取消") { dialog, _ ->
            sendAnswer(questionId, defaultValue)
            dialog.dismiss()
        }
        .setCancelable(false)
        .show()
}

// 4. 显示单选对话框
private fun showChoiceDialog(
    questionId: String,
    questionText: String,
    options: JSONArray,
    defaultValue: String
) {
    val items = (0 until options.length()).map { options.getString(it) }.toTypedArray()
    val defaultIndex = items.indexOf(defaultValue).takeIf { it >= 0 } ?: 0
    var selectedIndex = defaultIndex
    
    val builder = AlertDialog.Builder(this)
    builder.setTitle("Agent 询问")
        .setMessage(questionText)
        .setSingleChoiceItems(items, defaultIndex) { _, which ->
            selectedIndex = which
        }
        .setPositiveButton("确定") { dialog, _ ->
            val answer = items[selectedIndex]
            sendAnswer(questionId, answer)
            dialog.dismiss()
        }
        .setNegativeButton("取消") { dialog, _ ->
            sendAnswer(questionId, defaultValue)
            dialog.dismiss()
        }
        .setCancelable(false)
        .show()
}

// 5. 显示确认对话框
private fun showConfirmDialog(
    questionId: String,
    questionText: String,
    defaultValue: String
) {
    val builder = AlertDialog.Builder(this)
    builder.setTitle("Agent 询问")
        .setMessage(questionText)
        .setPositiveButton("是") { dialog, _ ->
            sendAnswer(questionId, "yes")
            dialog.dismiss()
        }
        .setNegativeButton("否") { dialog, _ ->
            sendAnswer(questionId, "no")
            dialog.dismiss()
        }
        .setCancelable(false)
        .show()
}

// 6. 发送答案到服务器
private fun sendAnswer(questionId: String, answer: String) {
    val answerMessage = JSONObject().apply {
        put("type", "user_answer")
        put("question_id", questionId)
        put("answer", answer)
    }
    
    // 通过 WebSocket 发送
    websocket.send(answerMessage.toString())
    
    Log.d("DroidRun", "Answer sent: $questionId -> $answer")
}
```

---

## ⏱️ 超时处理

### 超时逻辑

如果用户在 `timeout_seconds` 内没有回答：

1. **服务器端**: 
   - 使用 `default_value` 作为答案
   - Agent 继续执行

2. **Android 端**（可选实现）:
   - 自动关闭对话框
   - 发送 `default_value` 作为答案

### 超时实现示例

```kotlin
private fun showTextInputDialogWithTimeout(
    questionId: String,
    questionText: String,
    defaultValue: String,
    timeoutSeconds: Double
) {
    val dialog = AlertDialog.Builder(this)
        .setTitle("Agent 询问")
        .setMessage(questionText)
        // ... 其他设置
        .create()
    
    dialog.show()
    
    // 设置超时
    Handler(Looper.getMainLooper()).postDelayed({
        if (dialog.isShowing) {
            dialog.dismiss()
            sendAnswer(questionId, defaultValue)
            Toast.makeText(this, "自动使用默认值", Toast.LENGTH_SHORT).show()
        }
    }, (timeoutSeconds * 1000).toLong())
}
```

---

## 🔍 测试和调试

### 测试消息

可以在 Android 端模拟接收问题消息：

```kotlin
// 测试文本输入
val testTextQuestion = JSONObject("""
{
    "type": "user_question",
    "question_id": "test-001",
    "question_text": "测试：请输入您的姓名",
    "question_type": "text",
    "default_value": "测试用户",
    "timeout_seconds": 60.0
}
""")
handleUserQuestion(testTextQuestion)

// 测试单选
val testChoiceQuestion = JSONObject("""
{
    "type": "user_question",
    "question_id": "test-002",
    "question_text": "测试：请选择颜色",
    "question_type": "choice",
    "options": ["红色", "绿色", "蓝色"],
    "default_value": "红色",
    "timeout_seconds": 30.0
}
""")
handleUserQuestion(testChoiceQuestion)

// 测试确认
val testConfirmQuestion = JSONObject("""
{
    "type": "user_question",
    "question_id": "test-003",
    "question_text": "测试：确认要继续吗？",
    "question_type": "confirm",
    "default_value": "no",
    "timeout_seconds": 30.0
}
""")
handleUserQuestion(testConfirmQuestion)
```

### 日志记录

建议添加详细的日志：

```kotlin
Log.d("DroidRun", "Question received: $questionId, type: $questionType")
Log.d("DroidRun", "Showing dialog: $questionText")
Log.d("DroidRun", "User answered: $answer")
Log.d("DroidRun", "Answer sent to server")
```

---

## 🎯 最佳实践

### 1. 用户体验

- ✅ 对话框应该清晰易懂
- ✅ 问题文本应该完整显示
- ✅ 提供明确的操作按钮
- ✅ 支持键盘输入（文本类型）
- ✅ 默认值应该合理

### 2. 错误处理

- ✅ 处理 WebSocket 断开的情况
- ✅ 验证消息格式
- ✅ 记录错误日志
- ✅ 提供友好的错误提示

### 3. 性能优化

- ✅ 避免阻塞 UI 线程
- ✅ 及时关闭不需要的对话框
- ✅ 限制对话框数量（最多一个）

### 4. 安全性

- ✅ 验证 `question_id` 的有效性
- ✅ 限制答案长度
- ✅ 过滤敏感信息

---

## 📝 完整集成检查清单

在集成完成后，请检查以下项目：

- [ ] WebSocket 消息监听已实现
- [ ] 能够解析 `user_question` 消息
- [ ] 文本输入对话框已实现
- [ ] 单选对话框已实现
- [ ] 确认对话框已实现
- [ ] 答案消息发送已实现
- [ ] 超时处理已实现（可选）
- [ ] 错误处理已实现
- [ ] 日志记录已添加
- [ ] 已进行基本测试
- [ ] 用户体验良好

---

## 🐛 常见问题

### Q1: 问题对话框没有显示

**可能原因**:
- WebSocket 消息没有正确解析
- 消息类型不匹配
- UI 线程被阻塞

**解决方法**:
- 检查日志，确认消息已接收
- 验证消息格式
- 确保在 UI 线程中显示对话框

### Q2: 答案发送失败

**可能原因**:
- WebSocket 连接已断开
- 消息格式错误
- `question_id` 不匹配

**解决方法**:
- 检查 WebSocket 连接状态
- 验证答案消息格式
- 确保 `question_id` 与接收的一致

### Q3: 对话框无法关闭

**可能原因**:
- 事件处理逻辑错误
- 对话框设置为不可取消

**解决方法**:
- 检查按钮点击事件
- 设置适当的 `setCancelable()` 值

---

## 📞 支持

如有问题，请查看：
- 服务器端文档: `docs/interaction_phase5_completion.md`
- API 文档: `droidrun/agent/prompts/ask_user_guide.md`
- 问题反馈: GitHub Issues

---

**文档版本**: 1.0  
**更新时间**: 2025-12-05  
**适用版本**: DroidRun v2.0+
