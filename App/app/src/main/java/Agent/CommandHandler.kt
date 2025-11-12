package Agent

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.view.KeyEvent
import android.view.PixelCopy
import android.view.View
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import controller.ElementController
import controller.GenericElement
import controller.NativeController
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 命令处理器
 * 负责处理服务端发送的各种命令并执行相应的UI操作
 */
object CommandHandler {
    
    private const val TAG = "CommandHandler"
    
    // UI树缓存相关变量
    @Volatile
    private var cachedElementTree: GenericElement? = null
    @Volatile
    private var cachedStateResponse: JSONObject? = null
    @Volatile
    private var lastScreenHash: Int? = null
    @Volatile
    private var lastCacheTime: Long = 0
    private const val CACHE_VALIDITY_MS = 1000L // 缓存有效期1秒
    
    // 截图资源管理
    @Volatile
    private var lastScreenshot: Bitmap? = null
    
    /**
     * 创建带超时保护的包装回调
     * 确保命令在指定时间内完成，超时后返回错误响应
     */
    private fun createTimeoutProtectedCallback(
        timeoutMs: Long,
        originalCallback: (JSONObject) -> Unit
    ): (JSONObject) -> Unit {
        val isCompleted = AtomicBoolean(false)
        val handler = Handler(Looper.getMainLooper())
        var timeoutRunnable: Runnable? = null
        
        timeoutRunnable = Runnable {
            if (!isCompleted.getAndSet(true)) {
                Log.w(TAG, "命令执行超时（${timeoutMs}ms）")
                originalCallback(createErrorResponse("Command execution timeout after ${timeoutMs}ms"))
            }
        }
        
        // 启动超时检查
        handler.postDelayed(timeoutRunnable!!, timeoutMs)
        
        return { response ->
            if (!isCompleted.getAndSet(true)) {
                // 取消超时任务
                timeoutRunnable?.let { handler.removeCallbacks(it) }
                originalCallback(response)
            }
        }
    }
    
    /**
     * 主处理方法，根据命令类型路由到对应的处理器
     */
    fun handleCommand(
        command: String,
        params: JSONObject,
        requestId: String,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        Log.d(TAG, "处理命令: $command, requestId: $requestId")
        
        if (activity == null) {
            callback(createErrorResponse("No active activity"))
            return
        }
        
        // 为回调添加超时保护
        val protectedCallback = createTimeoutProtectedCallback(
            timeoutMs = MobileGPTGlobal.COMMAND_TIMEOUT,
            originalCallback = callback
        )
        
        when (command) {
            "take_screenshot" -> {
                // 单独截图命令：HTTP上传后通过WS返回引用
                if (activity == null) {
                    protectedCallback(createErrorResponse("No active activity"))
                    return
                }
                Log.d(TAG, "处理单独截图命令")
                Handler(Looper.getMainLooper()).post {
                    try {
                        val t0 = System.currentTimeMillis()
                        takeScreenshotAsync(activity) { bitmap ->
                            val t1 = System.currentTimeMillis()
                            Log.d(TAG, "截图完成: hasBitmap=${bitmap != null && !bitmap.isRecycled}, captureTime=${t1 - t0}ms")
                            if (bitmap != null && !bitmap.isRecycled) {
                                // 在后台线程执行网络上传，避免 NetworkOnMainThreadException
                                Thread {
                                    val uploadResp = HttpUploader.uploadBitmap(activity, bitmap, requestId)
                                    Handler(Looper.getMainLooper()).post {
                                        if (uploadResp != null && uploadResp.optString("status") == "success") {
                                            val ref = JSONObject().apply {
                                                put("file_id", uploadResp.optString("file_id"))
                                                put("path", uploadResp.optString("path"))
                                                put("url", uploadResp.optString("url"))
                                                put("mime", uploadResp.optString("mime"))
                                                put("size", uploadResp.optInt("size"))
                                            }
                                            val data = JSONObject().apply { put("screenshot_ref", ref) }
                                            Log.d(TAG, "截图回包: 使用引用 path=${ref.optString("path")}")
                                            protectedCallback(createSuccessResponse(data))
                                        } else {
                                            protectedCallback(createErrorResponse("Upload screenshot failed"))
                                        }
                                    }
                                }.start()
                            } else {
                                protectedCallback(createErrorResponse("Failed to take screenshot"))
                            }
                        }
                    } catch (e: Exception) {
                        Log.e(TAG, "处理截图命令异常", e)
                        protectedCallback(createErrorResponse("Exception: ${e.message}"))
                    }
                }
            }
            "get_state" -> {
                handleGetState(requestId, params, activity, protectedCallback)
            }
            "tap" -> {
                handleTap(requestId, params, activity, protectedCallback)
            }
            "tap_by_index" -> {
                handleTapByIndex(requestId, params, activity, protectedCallback)
            }
            "swipe" -> {
                handleSwipe(requestId, params, activity, protectedCallback)
            }
            "input_text" -> {
                handleInputText(requestId, params, activity, protectedCallback)
            }
            "back" -> {
                handleBack(requestId, params, activity, protectedCallback)
            }
            "press_key" -> {
                handlePressKey(requestId, params, activity, protectedCallback)
            }
            "start_app" -> {
                handleStartApp(requestId, params, activity, protectedCallback)
            }
            else -> {
                Log.w(TAG, "未知命令: $command")
                protectedCallback(createErrorResponse("Unknown command: $command"))
            }
        }
    }
    
    /**
     * 处理get_state命令 - 获取UI状态
     * 支持UI树缓存优化，如果页面未变化则返回缓存
     */
    private fun handleGetState(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        if (activity == null) {
            callback(createErrorResponse("No active activity"))
            return
        }
        
        // 在主线程执行UI操作
        Handler(Looper.getMainLooper()).post {
            try {
                // 检查缓存是否有效
                val currentScreenHash = calculateScreenHash(activity)
                val cacheValid = isCacheValid(currentScreenHash)
                
                if (cacheValid && cachedStateResponse != null) {
                    Log.d(TAG, "使用缓存的UI状态")
                    callback(cachedStateResponse!!)
                    return@post
                }
                
                // 缓存无效或不存在，重新获取
                // 1. 获取元素树
                ElementController.getCurrentElementTree(activity) { elementTree ->
                    // 2. 异步获取截图（可选，不阻塞主线程），增加2秒降级超时
                    val handler = Handler(Looper.getMainLooper())
                    val completed = AtomicBoolean(false)
                    
                    val finishWith: (org.json.JSONObject?, org.json.JSONObject?, org.json.JSONObject?) -> Unit = { a11yInlineOrRef, a11yRef, screenshotRef ->
                        if (!completed.getAndSet(true)) {
                            val stateResponse = JSONObject()
                            try {
                                if (a11yInlineOrRef != null) {
                                    // 使用内联的完整状态对象（已包含a11y_tree和phone_state）
                                    stateResponse.put("a11y_tree", a11yInlineOrRef.opt("a11y_tree") as Any)
                                    stateResponse.put("phone_state", a11yInlineOrRef.opt("phone_state") as Any)
                                } else {
                                    // 只有phone_state
                                    val phoneState = StateConverter.getPhoneState(activity)
                                    stateResponse.put("phone_state", phoneState as Any)
                                }
                                // 附加引用（若有）
                                if (a11yRef != null) stateResponse.put("a11y_ref", a11yRef)
                                if (screenshotRef != null) stateResponse.put("screenshot_ref", screenshotRef)
                            } catch (e: Exception) {
                                Log.w(TAG, "构建get_state基础响应异常", e)
                            }
                            updateCache(elementTree, stateResponse, currentScreenHash)
                            callback(stateResponse)
                        }
                    }
                    
                    // 降级超时：2秒后若上传仍未完成，返回仅有phone_state（无引用）
                    val fallback = Runnable {
                        Log.w(TAG, "状态构建超时，降级为无引用返回（2s）")
                        finishWith(null, null, null)
                    }
                    handler.postDelayed(fallback, 2000)
                    
                    // 并行任务：生成裁剪的a11y JSON并上传 + 截图并上传
                    Thread {
                        var a11yRef: JSONObject? = null
                        var a11yInline: org.json.JSONObject? = null
                        var screenshotRef: JSONObject? = null
                        try {
                            // 生成完整的状态对象（包含a11y_tree和phone_state）
                            val a11yTree = StateConverter.convertElementTreeToA11yTreePruned(elementTree, activity)
                            val phoneState = StateConverter.getPhoneState(activity)
                            
                            val stateObj = org.json.JSONObject()
                            stateObj.put("a11y_tree", a11yTree as Any)
                            stateObj.put("phone_state", phoneState as Any)
                            
                            val jsonStr = stateObj.toString()
                            val a11yUpload = HttpUploader.uploadJson(activity, jsonStr, "a11y_${System.currentTimeMillis()}", "a11y.json")
                            if (a11yUpload != null && a11yUpload.optString("status") == "success") {
                                a11yRef = JSONObject().apply {
                                    put("file_id", a11yUpload.optString("file_id"))
                                    put("path", a11yUpload.optString("path"))
                                    put("url", a11yUpload.optString("url"))
                                    put("mime", a11yUpload.optString("mime"))
                                    put("size", a11yUpload.optInt("size"))
                                }
                            } else {
                                // 上传失败：降级为内联（受限大小）
                                a11yInline = stateObj
                            }
                        } catch (e: Exception) {
                            Log.w(TAG, "a11y上传异常", e)
                            try {
                                // 异常也尝试内联
                                val a11yTree = StateConverter.convertElementTreeToA11yTreePruned(elementTree, activity)
                                val phoneState = StateConverter.getPhoneState(activity)
                                a11yInline = org.json.JSONObject().apply {
                                    put("a11y_tree", a11yTree as Any)
                                    put("phone_state", phoneState as Any)
                                }
                            } catch (_: Exception) { }
                        }
                        try {
                            takeScreenshotAsync(activity) { screenshot ->
                                if (screenshot != null && !screenshot.isRecycled) {
                                    Thread {
                                        val up = HttpUploader.uploadBitmap(activity, screenshot, "state_${System.currentTimeMillis()}")
                                        if (up != null && up.optString("status") == "success") {
                                            screenshotRef = JSONObject().apply {
                                                put("file_id", up.optString("file_id"))
                                                put("path", up.optString("path"))
                                                put("url", up.optString("url"))
                                                put("mime", up.optString("mime"))
                                                put("size", up.optInt("size"))
                                            }
                                        }
                                        Handler(Looper.getMainLooper()).post {
                                            handler.removeCallbacks(fallback)
                                            finishWith(a11yInline, a11yRef, screenshotRef)
                                        }
                                    }.start()
                                } else {
                                    Handler(Looper.getMainLooper()).post {
                                        handler.removeCallbacks(fallback)
                                        finishWith(a11yInline, a11yRef, null)
                                    }
                                }
                            }
                        } catch (e: Exception) {
                            Handler(Looper.getMainLooper()).post {
                                handler.removeCallbacks(fallback)
                                finishWith(a11yInline, a11yRef, null)
                            }
                        }
                    }.start()
                }
            } catch (e: Exception) {
                Log.e(TAG, "获取状态时发生异常", e)
                callback(createErrorResponse("Failed to get state: ${e.message}"))
            }
        }
    }
    
    /**
     * 计算屏幕哈希值，用于判断页面是否变化
     * @return 屏幕哈希值，如果计算失败返回null
     */
    private fun calculateScreenHash(activity: Activity): Int? {
        return try {
            val rootView = activity.findViewById<View>(android.R.id.content)
            calculateViewHash(rootView)
        } catch (e: Exception) {
            Log.w(TAG, "计算屏幕哈希失败", e)
            null // 计算失败时返回null，让缓存失效
        }
    }
    
    /**
     * 递归计算视图哈希值
     */
    private fun calculateViewHash(view: View): Int {
        var hash = view.javaClass.simpleName.hashCode()
        hash = hash * 31 + view.visibility
        hash = hash * 31 + view.isEnabled.hashCode()
        
        if (view is android.widget.TextView) {
            hash = hash * 31 + (view.text?.toString()?.hashCode() ?: 0)
        }
        
        if (view is android.view.ViewGroup) {
            for (i in 0 until view.childCount) {
                hash = hash * 31 + calculateViewHash(view.getChildAt(i))
            }
        }
        
        return hash
    }
    
    /**
     * 检查缓存是否有效
     */
    private fun isCacheValid(currentScreenHash: Int?): Boolean {
        if (cachedStateResponse == null || lastScreenHash == null) {
            return false
        }
        
        // 检查时间有效性
        val currentTime = System.currentTimeMillis()
        if (currentTime - lastCacheTime > CACHE_VALIDITY_MS) {
            return false
        }
        
        // 检查屏幕哈希是否相同
        return currentScreenHash == lastScreenHash
    }
    
    /**
     * 更新缓存
     */
    private fun updateCache(
        elementTree: GenericElement,
        stateResponse: JSONObject,
        screenHash: Int?
    ) {
        // 释放旧的截图资源
        recycleOldScreenshot()
        
        // 更新缓存
        cachedElementTree = elementTree
        cachedStateResponse = stateResponse
        lastScreenHash = screenHash
        lastCacheTime = System.currentTimeMillis()
        
        Log.d(TAG, "UI状态缓存已更新")
    }
    
    /**
     * 清理缓存
     */
    fun clearCache() {
        cachedElementTree = null
        cachedStateResponse = null
        lastScreenHash = null
        lastCacheTime = 0
        recycleOldScreenshot()
        Log.d(TAG, "UI状态缓存已清理")
    }
    
    /**
     * 安全地回收旧的截图，防止内存泄漏
     */
    private fun recycleOldScreenshot() {
        try {
            val oldScreenshot = lastScreenshot
            if (oldScreenshot != null && !oldScreenshot.isRecycled) {
                oldScreenshot.recycle()
                Log.d(TAG, "已回收旧截图资源")
            }
            lastScreenshot = null
        } catch (e: Exception) {
            Log.e(TAG, "回收旧截图时发生异常", e)
        }
    }
    
    /**
     * 处理tap命令 - 点击操作
     */
    private fun handleTap(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        // 参数验证
        if (!params.has("x") || !params.has("y")) {
            Log.w(TAG, "tap命令缺少参数: x=${params.has("x")}, y=${params.has("y")}")
            callback(createErrorResponse("Missing x or y parameter"))
            return
        }
        
        val x = params.getInt("x")
        val y = params.getInt("y")
        Log.d(TAG, "执行tap命令: ($x, $y)")
        
        if (activity == null) {
            Log.w(TAG, "tap命令执行失败: Activity为空")
            callback(createErrorResponse("No active activity"))
            return
        }
        
        // 在主线程执行点击
        Handler(Looper.getMainLooper()).post {
            try {
                // 使用NativeController执行坐标点击（dp单位）
                NativeController.clickByCoordinateDp(activity, x.toFloat(), y.toFloat()) { success ->
                    if (success) {
                        // UI操作后清理缓存，因为页面可能已变化
                        clearCache()
                        Log.d(TAG, "tap命令执行成功: ($x, $y)")
                        callback(createSuccessResponse())
                    } else {
                        Log.w(TAG, "tap命令执行失败: NativeController返回false")
                        callback(createErrorResponse("Tap action failed"))
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "tap命令执行异常: ${e.message}", e)
                callback(createErrorResponse("Exception: ${e.message}"))
            }
        }
    }
    
    /**
     * 处理tap_by_index命令 - 通过索引点击元素
     */
    private fun handleTapByIndex(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        // 参数验证
        if (!params.has("index")) {
            Log.w(TAG, "tap_by_index命令缺少参数: index")
            callback(createErrorResponse("Missing index parameter"))
            return
        }
        
        val index = params.getInt("index")
        Log.d(TAG, "执行tap_by_index命令: index=$index")
        
        if (activity == null) {
            Log.w(TAG, "tap_by_index命令执行失败: Activity为空")
            callback(createErrorResponse("No active activity"))
            return
        }
        
        // 从缓存的元素树中查找目标元素
        val targetElement = findElementByIndex(cachedElementTree, index)
        if (targetElement == null) {
            Log.w(TAG, "tap_by_index命令执行失败: 未找到索引为 $index 的元素")
            callback(createErrorResponse("Element with index $index not found"))
            return
        }
        
        // 计算元素中心坐标（dp单位）
        val centerX = (targetElement.bounds.left + targetElement.bounds.right) / 2f
        val centerY = (targetElement.bounds.top + targetElement.bounds.bottom) / 2f
        Log.d(TAG, "目标元素中心坐标: ($centerX, $centerY) dp")
        
        // 在主线程执行点击
        Handler(Looper.getMainLooper()).post {
            try {
                // 使用NativeController执行坐标点击（dp单位）
                NativeController.clickByCoordinateDp(activity, centerX, centerY) { success ->
                    if (success) {
                        // UI操作后清理缓存，因为页面可能已变化
                        clearCache()
                        Log.d(TAG, "tap_by_index命令执行成功: index=$index")
                        callback(createSuccessResponse())
                    } else {
                        Log.w(TAG, "tap_by_index命令执行失败: NativeController返回false")
                        callback(createErrorResponse("Tap by index action failed"))
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "tap_by_index命令执行异常: ${e.message}", e)
                callback(createErrorResponse("Exception: ${e.message}"))
            }
        }
    }
    
    /**
     * 从元素树中查找指定索引的元素
     */
    private fun findElementByIndex(root: GenericElement?, targetIndex: Int): GenericElement? {
        if (root == null) return null
        
        // 深度优先搜索
        fun searchElement(element: GenericElement): GenericElement? {
            if (element.index == targetIndex) {
                return element
            }
            
            // 递归搜索子元素
            for (child in element.children) {
                val found = searchElement(child)
                if (found != null) return found
            }
            
            return null
        }
        
        return searchElement(root)
    }
    
    /**
     * 处理swipe命令 - 滑动操作
     */
    private fun handleSwipe(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        // 参数验证
        val requiredParams = listOf("start_x", "start_y", "end_x", "end_y")
        for (param in requiredParams) {
            if (!params.has(param)) {
                Log.w(TAG, "swipe命令缺少参数: $param")
                callback(createErrorResponse("Missing parameter: $param"))
                return
            }
        }
        
        val startX = params.getInt("start_x")
        val startY = params.getInt("start_y")
        val endX = params.getInt("end_x")
        val endY = params.getInt("end_y")
        val duration = params.optInt("duration_ms", 300)
        Log.d(TAG, "执行swipe命令: ($startX, $startY) -> ($endX, $endY), duration=${duration}ms")
        
        if (activity == null) {
            Log.w(TAG, "swipe命令执行失败: Activity为空")
            callback(createErrorResponse("No active activity"))
            return
        }
        
        Handler(Looper.getMainLooper()).post {
            try {
                // 使用NativeController的scrollByTouchDp方法实现滑动
                NativeController.scrollByTouchDp(
                    activity = activity,
                    startXDp = startX.toFloat(),
                    startYDp = startY.toFloat(),
                    endXDp = endX.toFloat(),
                    endYDp = endY.toFloat(),
                    duration = duration.toLong()
                ) { success ->
                    if (success) {
                        // UI操作后清理缓存，因为页面可能已变化
                        clearCache()
                        Log.d(TAG, "swipe命令执行成功")
                        callback(createSuccessResponse())
                    } else {
                        Log.w(TAG, "swipe命令执行失败: NativeController返回false")
                        callback(createErrorResponse("Swipe action failed"))
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "swipe命令执行异常: ${e.message}", e)
                callback(createErrorResponse("Exception: ${e.message}"))
            }
        }
    }
    
    /**
     * 处理input_text命令 - 文本输入
     */
    private fun handleInputText(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        // 参数验证
        if (!params.has("text")) {
            Log.w(TAG, "input_text命令缺少参数: text")
            callback(createErrorResponse("Missing text parameter"))
            return
        }
        
        val text = params.getString("text")
        Log.d(TAG, "执行input_text命令: text=\"$text\"")
        
        if (activity == null) {
            Log.w(TAG, "input_text命令执行失败: Activity为空")
            callback(createErrorResponse("No active activity"))
            return
        }
        
        Handler(Looper.getMainLooper()).post {
            try {
                // 检查是否提供了坐标参数
                if (params.has("x") && params.has("y")) {
                    // 使用坐标输入（点击坐标后输入文本）
                    val x = params.getInt("x")
                    val y = params.getInt("y")
                    Log.d(TAG, "使用坐标输入: ($x, $y)")
                    
                    NativeController.inputTextByCoordinateDp(
                        activity = activity,
                        inputXDp = x.toFloat(),
                        inputYDp = y.toFloat(),
                        inputContent = text,
                        clearBeforeInput = true
                    ) { success ->
                        if (success) {
                            // UI操作后清理缓存，因为页面可能已变化
                            clearCache()
                            Log.d(TAG, "input_text命令执行成功")
                            callback(createSuccessResponse())
                        } else {
                            Log.w(TAG, "input_text命令执行失败: NativeController返回false")
                            callback(createErrorResponse("Input text action failed"))
                        }
                    }
                } else {
                    // 没有坐标，尝试使用当前焦点视图或第一个EditText
                    val rootView = activity.findViewById<View>(android.R.id.content)
                    val focusedView = rootView.findFocus()
                    
                    if (focusedView is EditText) {
                        // 如果已有焦点EditText，直接输入
                        Log.d(TAG, "使用焦点EditText输入")
                        focusedView.setText(text)
                        // 移动光标到末尾
                        focusedView.setSelection(text.length)
                        clearCache()
                        callback(createSuccessResponse())
                    } else {
                        // 尝试找到第一个EditText并输入
                        val editText = findFirstEditText(rootView)
                        if (editText != null) {
                            Log.d(TAG, "找到EditText，准备输入")
                            // 点击EditText获取焦点
                            editText.requestFocus()
                            // 显示软键盘
                            val imm = activity.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
                            imm.showSoftInput(editText, InputMethodManager.SHOW_IMPLICIT)
                            
                            // 等待软键盘弹出后输入
                            Handler(Looper.getMainLooper()).postDelayed({
                                editText.setText(text)
                                editText.setSelection(text.length)
                                clearCache()
                                callback(createSuccessResponse())
                            }, 300)
                        } else {
                            Log.w(TAG, "input_text命令执行失败: 未找到输入框")
                            callback(createErrorResponse("No input field found. Please provide coordinates (x, y) for input_text command."))
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "input_text命令执行异常: ${e.message}", e)
                callback(createErrorResponse("Exception: ${e.message}"))
            }
        }
    }
    
    /**
     * 查找第一个EditText视图
     */
    private fun findFirstEditText(view: View): EditText? {
        if (view is EditText) {
            return view
        }
        if (view is android.view.ViewGroup) {
            for (i in 0 until view.childCount) {
                val child = view.getChildAt(i)
                val result = findFirstEditText(child)
                if (result != null) {
                    return result
                }
            }
        }
        return null
    }
    
    /**
     * 处理back命令 - 返回键
     */
    private fun handleBack(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        Log.d(TAG, "执行back命令")
        
        if (activity == null) {
            Log.w(TAG, "back命令执行失败: Activity为空")
            callback(createErrorResponse("No active activity"))
            return
        }
        
        Handler(Looper.getMainLooper()).post {
            try {
                NativeController.goBack(activity) { success ->
                    if (success) {
                        // UI操作后清理缓存，因为页面可能已变化
                        clearCache()
                        Log.d(TAG, "back命令执行成功")
                        callback(createSuccessResponse())
                    } else {
                        Log.w(TAG, "back命令执行失败: NativeController返回false")
                        callback(createErrorResponse("Back action failed"))
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "back命令执行异常: ${e.message}", e)
                callback(createErrorResponse("Exception: ${e.message}"))
            }
        }
    }
    
    /**
     * 处理press_key命令 - 按键操作
     */
    private fun handlePressKey(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        // 参数验证
        if (!params.has("keycode")) {
            Log.w(TAG, "press_key命令缺少参数: keycode")
            callback(createErrorResponse("Missing keycode parameter"))
            return
        }
        
        val keycode = params.getInt("keycode")
        Log.d(TAG, "执行press_key命令: keycode=$keycode")
        
        if (activity == null) {
            Log.w(TAG, "press_key命令执行失败: Activity为空")
            callback(createErrorResponse("No active activity"))
            return
        }
        
        Handler(Looper.getMainLooper()).post {
            try {
                val rootView = activity.findViewById<View>(android.R.id.content)
                val downTime = SystemClock.uptimeMillis()
                
                // 创建按键按下事件
                val downEvent = KeyEvent(downTime, downTime, KeyEvent.ACTION_DOWN, keycode, 0)
                val downResult = rootView.dispatchKeyEvent(downEvent)
                
                // 创建按键抬起事件
                val upEvent = KeyEvent(downTime, SystemClock.uptimeMillis(), KeyEvent.ACTION_UP, keycode, 0)
                val upResult = rootView.dispatchKeyEvent(upEvent)
                
                if (downResult && upResult) {
                    // UI操作后清理缓存，因为页面可能已变化
                    clearCache()
                    Log.d(TAG, "press_key命令执行成功: keycode=$keycode")
                    callback(createSuccessResponse())
                } else {
                    Log.w(TAG, "press_key命令执行失败: downResult=$downResult, upResult=$upResult")
                    callback(createErrorResponse("Press key action failed"))
                }
            } catch (e: Exception) {
                Log.e(TAG, "press_key命令执行异常: ${e.message}", e)
                callback(createErrorResponse("Exception: ${e.message}"))
            }
        }
    }
    
    /**
     * 处理start_app命令 - 启动应用
     */
    private fun handleStartApp(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        // 参数验证
        if (!params.has("package")) {
            Log.w(TAG, "start_app命令缺少参数: package")
            callback(createErrorResponse("Missing package parameter"))
            return
        }
        
        val packageName = params.getString("package")
        val activityName = params.optString("activity", null)
        Log.d(TAG, "执行start_app命令: package=$packageName, activity=$activityName")
        
        if (activity == null) {
            Log.w(TAG, "start_app命令执行失败: Activity为空")
            callback(createErrorResponse("No active activity"))
            return
        }
        
        Handler(Looper.getMainLooper()).post {
            try {
                val intent = if (activityName != null && activityName.isNotEmpty()) {
                    // 启动指定Activity
                    Log.d(TAG, "启动指定Activity: $packageName/$activityName")
                    Intent().apply {
                        setClassName(packageName, activityName)
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    }
                } else {
                    // 启动应用主Activity
                    val pm = activity.packageManager
                    val launchIntent = pm.getLaunchIntentForPackage(packageName)
                    if (launchIntent != null) {
                        launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        launchIntent
                    } else {
                        Log.w(TAG, "start_app命令执行失败: 无法找到启动Intent, package=$packageName")
                        callback(createErrorResponse("Cannot find launch intent for package: $packageName"))
                        return@post
                    }
                }
                
                activity.startActivity(intent)
                // UI操作后清理缓存，因为页面可能已变化
                clearCache()
                Log.d(TAG, "start_app命令执行成功: package=$packageName")
                callback(createSuccessResponse())
            } catch (e: Exception) {
                Log.e(TAG, "start_app命令执行异常: ${e.message}", e)
                callback(createErrorResponse("Exception: ${e.message}"))
            }
        }
    }
    
    /**
     * 异步截图功能（避免阻塞主线程）
     */
    private fun takeScreenshotAsync(activity: Activity, callback: (Bitmap?) -> Unit) {
        try {
            val rootView = activity.window?.decorView?.rootView
            if (rootView == null) {
                Log.w(TAG, "无法获取根视图")
                callback(null)
                return
            }
            
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                // Android 8.0+ 使用PixelCopy
                val bitmap = Bitmap.createBitmap(
                    rootView.width,
                    rootView.height,
                    Bitmap.Config.ARGB_8888
                )
                
                PixelCopy.request(
                    activity.window,
                    android.graphics.Rect(0, 0, rootView.width, rootView.height),
                    bitmap,
                    { copyResult ->
                        when (copyResult) {
                            PixelCopy.SUCCESS -> {
                                // 保存截图引用用于后续资源管理
                                recycleOldScreenshot()
                                lastScreenshot = bitmap
                                callback(bitmap)
                            }
                            else -> {
                                Log.e(TAG, "截图失败: $copyResult")
                                bitmap.recycle()
                                callback(null)
                            }
                        }
                    },
                    Handler(Looper.getMainLooper())
                )
            } else {
                // Android 7.x 使用DrawingCache（同步操作，但很快）
                try {
                    rootView.isDrawingCacheEnabled = true
                    rootView.buildDrawingCache(true)
                    val bitmap = rootView.drawingCache?.copy(Bitmap.Config.ARGB_8888, false)
                    rootView.isDrawingCacheEnabled = false
                    
                    // 保存截图引用用于后续资源管理
                    if (bitmap != null) {
                        recycleOldScreenshot()
                        lastScreenshot = bitmap
                    }
                    
                    callback(bitmap)
                } catch (e: Exception) {
                    Log.e(TAG, "DrawingCache截图失败", e)
                    callback(null)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "截图异常", e)
            callback(null)
        }
    }
    
    /**
     * 创建成功响应
     */
    private fun createSuccessResponse(data: JSONObject? = null): JSONObject {
        val response = JSONObject()
        response.put("status", "success")
        if (data != null) {
            // 合并data内容到响应中
            val keys = data.keys()
            while (keys.hasNext()) {
                val key = keys.next()
                response.put(key, data.get(key))
            }
        }
        return response
    }
    
    /**
     * 创建错误响应
     */
    private fun createErrorResponse(message: String): JSONObject {
        val response = JSONObject()
        response.put("status", "error")
        response.put("error", message)
        return response
    }
}

