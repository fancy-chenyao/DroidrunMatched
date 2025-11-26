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
import android.view.ViewTreeObserver
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import Agent.ActivityTracker
import controller.ElementController
import controller.GenericElement
import controller.NativeController
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import utlis.PageChangeVerifier
import utlis.PageStableVerifier

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
    private var cachedStableIndexMap: Map<GenericElement, Int>? = null  // 稳定索引映射
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
                Handler(Looper.getMainLooper()).post {
                    try {
                        val t0 = System.currentTimeMillis()
                        takeScreenshotAsync(activity) { bitmap ->
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
                val handler = Handler(Looper.getMainLooper())
                val stabilizeTimeout = params.optLong("stabilize_timeout_ms", 5000L)
                val stableWindow = params.optLong("stable_window_ms", 500L)
                val waitStart = System.currentTimeMillis()
                PageStableVerifier.waitUntilStable(
                    handler = handler,
                    getCurrentActivity = { ActivityTracker.getCurrentActivity() },
                    timeoutMs = stabilizeTimeout,
                    minStableMs = stableWindow,
                    intervalMs = 100L
                ) {
                    val waitedMs = System.currentTimeMillis() - waitStart
                    Log.d(TAG, "页面稳定等待耗时: ${waitedMs}ms (timeout=${stabilizeTimeout}ms, stable_window=${stableWindow}ms)")
                    handleGetState(requestId, params, activity, protectedCallback)
                }
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
        val startTime = System.currentTimeMillis()
        
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
                    callback(cachedStateResponse!!)
                    return@post
                }
                
                // 缓存无效或不存在，重新获取
                // 1. 获取元素树
                ElementController.getCurrentElementTree(activity) { elementTree ->
                    // 2. 在后台线程生成 a11y_tree
                    Thread {
                        try {
                            // 生成 a11y_tree 和稳定索引映射
                            val result = StateConverter.convertElementTreeToA11yTreePruned(elementTree, activity)
                            val a11yTree = result.a11yTree
                            val stableIndexMap = result.stableIndexMap

                            // 获取截图并转为 Base64（如果需要）
                            var screenshotBase64: String? = null
                            if (params.optBoolean("include_screenshot", false)) {
                                val screenshotLatch = java.util.concurrent.CountDownLatch(1)
                                Handler(Looper.getMainLooper()).post {
                                    takeScreenshotAsync(activity) { screenshot ->
                                        if (screenshot != null && !screenshot.isRecycled) {
                                            screenshotBase64 = StateConverter.bitmapToBase64(screenshot, 30)
                                            screenshot.recycle()
                                        }
                                        screenshotLatch.countDown()
                                    }
                                }
                                // 等待截图完成（最多 2 秒）
                                screenshotLatch.await(2, java.util.concurrent.TimeUnit.SECONDS)
                            }

                            // 构建响应（包含内联数据）
                            val stateResponse = JSONObject()
                            stateResponse.put("phone_state", StateConverter.getPhoneState(activity))
                            stateResponse.put("a11y_tree", a11yTree)
                            if (screenshotBase64 != null) {
                                stateResponse.put("screenshot_base64", screenshotBase64)
                            }

                            // 更新缓存并返回响应
                            Handler(Looper.getMainLooper()).post {
                                // 缓存元素树和稳定索引映射
                                updateCache(elementTree, stateResponse, currentScreenHash, stableIndexMap)
                                callback(stateResponse)
                                
                                // 计算总耗时和数据大小
                            }

                        } catch (e: Exception) {
                            Log.e(TAG, "生成状态响应异常", e)
                            Handler(Looper.getMainLooper()).post {
                                callback(createErrorResponse("Failed to generate state: ${e.message}"))
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
        screenHash: Int?,
        stableIndexMap: Map<GenericElement, Int>? = null
    ) {
        // 释放旧的截图资源
        recycleOldScreenshot()
        
        // 更新缓存
        cachedElementTree = elementTree
        cachedStateResponse = stateResponse
        cachedStableIndexMap = stableIndexMap
        lastScreenHash = screenHash
        lastCacheTime = System.currentTimeMillis()
    }
    
    /**
     * 清理缓存
     */
    fun clearCache() {
        cachedElementTree = null
        cachedStateResponse = null
        cachedStableIndexMap = null
        lastScreenHash = null
        lastCacheTime = 0
        recycleOldScreenshot()
    }
    
    /**
     * 智能缓存清理 - 针对input_text操作的特殊处理
     * 只有在真正需要时才清理稳定索引映射
     */
    private fun smartClearCache(operationType: String) {
        when (operationType) {
            "input_text" -> {
                // input_text操作通常只改变文本内容，不改变元素结构
                // 保留稳定索引映射，只清理截图缓存
                lastScreenHash = null
                recycleOldScreenshot()
            }
            else -> {
                // 其他操作使用完整的缓存清理
                clearCache()
            }
        }
    }
    
    /**
     * 安全地回收旧的截图，防止内存泄漏
     */
    private fun recycleOldScreenshot() {
        try {
            val oldScreenshot = lastScreenshot
            if (oldScreenshot != null && !oldScreenshot.isRecycled) {
                oldScreenshot.recycle()
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
        
        if (activity == null) {
            Log.w(TAG, "tap命令执行失败: Activity为空")
            callback(createErrorResponse("No active activity"))
            return
        }
        
        // 在主线程执行点击
        val tapStartTime = System.currentTimeMillis()
        
        Handler(Looper.getMainLooper()).post {
            try {
                // 根据页面类型分发坐标点击（dp单位）
                ElementController.clickByCoordinateDp(activity, x.toFloat(), y.toFloat()) { success ->
                    
                    if (!success) {
                        Log.w(TAG, "tap命令执行失败: 点击操作返回false")
                        callback(createErrorResponse("Tap action failed"))
                        return@clickByCoordinateDp
                    }
                    
                    val observerStartTime = System.currentTimeMillis()
                    // 使用 ViewTreeObserver 监听 UI 变化
                    val layoutChanged = AtomicBoolean(false)
                    val layoutChangeTime = AtomicLong(0L)
                    val activityChanged = AtomicBoolean(false)
                    val hasReturned = AtomicBoolean(false)  // 防止重复返回
                    val initialActivity = ActivityTracker.getCurrentActivity()
                    
                    // 声明 listener 变量（稍后初始化）
                    var listener: ViewTreeObserver.OnGlobalLayoutListener? = null
                    
                    // 返回结果的通用方法
                    val returnResult = {
                        if (!hasReturned.getAndSet(true)) {
                            try {
                                listener?.let { activity.window?.decorView?.viewTreeObserver?.removeOnGlobalLayoutListener(it) }
                            } catch (e: Exception) {
                                Log.w(TAG, "移除 ViewTreeObserver 失败: ${e.message}")
                            }
                            
                            // 检查 Activity 是否变化
                            val currentActivity = ActivityTracker.getCurrentActivity()
                            if (currentActivity != initialActivity) {
                                activityChanged.set(true)
                            }
                            
                            // 总是清理缓存
                            clearCache()
                            
                            val hasChange = layoutChanged.get() || activityChanged.get()
                            val changeTypes = mutableListOf<String>()
                            if (activityChanged.get()) changeTypes.add("activity_switch")
                            if (layoutChanged.get()) changeTypes.add("layout_change")
                            
                            val data = JSONObject().apply {
                                put("ui_changed", hasChange)
                                if (changeTypes.isNotEmpty()) {
                                    put("change_type", changeTypes.joinToString("_and_"))
                                }
                            }
                            
                            if (!hasChange) {
                                Log.w(TAG, "tap未检测到UI变化: ($x, $y)")
                            }
                            
                            callback(createSuccessResponse(data))
                        }
                    }
                    
                    // 初始化 listener
                    listener = ViewTreeObserver.OnGlobalLayoutListener {
                        if (!layoutChanged.get()) {
                            layoutChanged.set(true)
                            // 检测到变化后，等待 100ms 确认，然后提前返回
                            Handler(Looper.getMainLooper()).postDelayed({
                                returnResult()
                            }, 100L)
                        }
                    }
                    
                    try {
                        activity.window?.decorView?.viewTreeObserver?.addOnGlobalLayoutListener(listener)
                    } catch (e: Exception) {
                        Log.w(TAG, "添加 ViewTreeObserver 失败: ${e.message}")
                    }
                    
                    // 100ms 后检查，如果没有变化则提前返回
                    Handler(Looper.getMainLooper()).postDelayed({
                        if (!layoutChanged.get() && !hasReturned.get()) {
                            returnResult()
                        }
                    }, 100L)
                    
                    // 最多等待 500ms（兜底保障）
                    Handler(Looper.getMainLooper()).postDelayed({
                        if (!hasReturned.get()) {
                            returnResult()
                        }
                    }, 500L)
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
        
        // 在主线程执行点击
        val tapStartTime = System.currentTimeMillis()
        
        Handler(Looper.getMainLooper()).post {
            try {
                // 根据页面类型分发坐标点击（dp单位）
                ElementController.clickByCoordinateDp(activity, centerX, centerY) { success ->
                    
                    if (!success) {
                        Log.w(TAG, "tap_by_index命令执行失败: 点击操作返回false")
                        callback(createErrorResponse("Tap by index action failed"))
                        return@clickByCoordinateDp
                    }
                    
                    val observerStartTime = System.currentTimeMillis()
                    // 使用 ViewTreeObserver 监听 UI 变化
                    val layoutChanged = AtomicBoolean(false)
                    val layoutChangeTime = AtomicLong(0L)
                    val activityChanged = AtomicBoolean(false)
                    val hasReturned = AtomicBoolean(false)  // 防止重复返回
                    val initialActivity = ActivityTracker.getCurrentActivity()
                    
                    // 声明 listener 变量（稍后初始化）
                    var listener: ViewTreeObserver.OnGlobalLayoutListener? = null
                    
                    // 返回结果的通用方法
                    val returnResult = {
                        if (!hasReturned.getAndSet(true)) {
                            try {
                                listener?.let { activity.window?.decorView?.viewTreeObserver?.removeOnGlobalLayoutListener(it) }
                            } catch (e: Exception) {
                                Log.w(TAG, "移除 ViewTreeObserver 失败: ${e.message}")
                            }
                            
                            // 检查 Activity 是否变化
                            val currentActivity = ActivityTracker.getCurrentActivity()
                            if (currentActivity != initialActivity) {
                                activityChanged.set(true)
                            }
                            
                            // 总是清理缓存
                            clearCache()
                            
                            // 构建详细的描述信息
                            val elementDesc = buildElementDescription(targetElement, index)
                            
                            val hasChange = layoutChanged.get() || activityChanged.get()
                            val changeTypes = mutableListOf<String>()
                            if (activityChanged.get()) changeTypes.add("activity_switch")
                            if (layoutChanged.get()) changeTypes.add("layout_change")
                            
                            val data = JSONObject().apply {
                                put("message", elementDesc)
                                put("ui_changed", hasChange)
                                if (changeTypes.isNotEmpty()) {
                                    put("change_type", changeTypes.joinToString("_and_"))
                                }
                            }
                            
                            if (!hasChange) {
                                Log.w(TAG, "tap_by_index未检测到UI变化: index=$index")
                            }
                            
                            callback(createSuccessResponse(data))
                        }
                    }
                    
                    // 初始化 listener
                    listener = ViewTreeObserver.OnGlobalLayoutListener {
                        if (!layoutChanged.get()) {
                            layoutChanged.set(true)
                            // 检测到变化后，等待 100ms 确认，然后提前返回
                            Handler(Looper.getMainLooper()).postDelayed({
                                returnResult()
                            }, 100L)
                        }
                    }
                    
                    try {
                        activity.window?.decorView?.viewTreeObserver?.addOnGlobalLayoutListener(listener)
                    } catch (e: Exception) {
                        Log.w(TAG, "添加 ViewTreeObserver 失败: ${e.message}")
                    }
                    
                    // 100ms 后检查，如果没有变化则提前返回
                    Handler(Looper.getMainLooper()).postDelayed({
                        if (!layoutChanged.get() && !hasReturned.get()) {
                            returnResult()
                        }
                    }, 100L)
                    
                    // 最多等待 500ms（兜底保障）
                    Handler(Looper.getMainLooper()).postDelayed({
                        if (!hasReturned.get()) {
                            returnResult()
                        }
                    }, 500L)
                }
            } catch (e: Exception) {
                Log.e(TAG, "tap_by_index命令执行异常: ${e.message}", e)
                callback(createErrorResponse("Exception: ${e.message}"))
            }
        }
    }
    
    /**
     * 从元素树中查找指定稳定索引的元素
     */
    private fun findElementByIndex(root: GenericElement?, targetIndex: Int): GenericElement? {
        if (root == null) return null
        
        // 优先使用稳定索引映射查找
        val stableIndexMap = cachedStableIndexMap
        if (stableIndexMap != null) {
            // 反向查找：从稳定索引找到对应的元素
            val element = stableIndexMap.entries.find { it.value == targetIndex }?.key
            if (element != null) {
                return element
            }
        }
        
        // 降级方案：使用原始索引查找（兼容旧逻辑）
        Log.w(TAG, "稳定索引映射不可用，使用原始索引: index=$targetIndex")
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
        
        if (activity == null) {
            Log.w(TAG, "swipe命令执行失败: Activity为空")
            callback(createErrorResponse("No active activity"))
            return
        }
        
        Handler(Looper.getMainLooper()).post {
            try {
                // 动作前状态用于页面变化验证
                val preActivity = activity
                val preHash = PageChangeVerifier.computePreViewTreeHash(activity)
                val preWebHash = PageChangeVerifier.computePreWebViewAggHash(activity)
                // 根据页面类型分发滑动
                ElementController.scrollByTouchDp(
                    activity = activity,
                    startXDp = startX.toFloat(),
                    startYDp = startY.toFloat(),
                    endXDp = endX.toFloat(),
                    endYDp = endY.toFloat(),
                    duration = duration.toLong()
                ) { success ->
                    if (success) {
                        // 成功后进行页面变化验证
                        PageChangeVerifier.verifyActionWithPageChange(
                            handler = Handler(Looper.getMainLooper()),
                            getCurrentActivity = { ActivityTracker.getCurrentActivity() },
                            preActivity = preActivity,
                            preViewTreeHash = preHash,
                            preWebViewAggHash = preWebHash
                        ) { changed, changeType ->
                            if (changed) {
                                clearCache()
                                val data = JSONObject().apply { put("page_change_type", changeType) }
                                callback(createSuccessResponse(data))
                            } else {
                                Log.w(TAG, "swipe命令执行后未检测到页面变化")
                                callback(createErrorResponse("Swipe succeeded but page unchanged"))
                            }
                        }
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
    
    // /**
    //  * 处理input_text命令 - 文本输入
    //  */
    // private fun handleInputText(
    //     requestId: String,
    //     params: JSONObject,
    //     activity: Activity?,
    //     callback: (JSONObject) -> Unit
    // ) {
    //     // 参数验证
    //     if (!params.has("text")) {
    //         Log.w(TAG, "input_text命令缺少参数: text")
    //         callback(createErrorResponse("Missing text parameter"))
    //         return
    //     }
        
    //     val text = params.getString("text")
    //     Log.d(TAG, "执行input_text命令: text=\"$text\"")
        
    //     if (activity == null) {
    //         Log.w(TAG, "input_text命令执行失败: Activity为空")
    //         callback(createErrorResponse("No active activity"))
    //         return
    //     }
        
    //     Handler(Looper.getMainLooper()).post {
    //         try {
    //             // 动作前状态用于页面变化验证
    //             val preActivity = activity
    //             val preHash = PageChangeVerifier.computePreViewTreeHash(activity)
    //             // 检查是否提供了坐标参数
    //             if (params.has("x") && params.has("y")) {
    //                 // 使用坐标输入（点击坐标后输入文本）
    //                 val x = params.getInt("x")
    //                 val y = params.getInt("y")
    //                 Log.d(TAG, "使用坐标输入: ($x, $y)")
                    
    //                 NativeController.inputTextByCoordinateDp(
    //                     activity = activity,
    //                     inputXDp = x.toFloat(),
    //                     inputYDp = y.toFloat(),
    //                     inputContent = text,
    //                     clearBeforeInput = true
    //                 ) { success ->
    //                     if (success) {
    //                         // 成功后进行页面变化验证
    //                         PageChangeVerifier.verifyActionWithPageChange(
    //                             handler = Handler(Looper.getMainLooper()),
    //                             getCurrentActivity = { ActivityTracker.getCurrentActivity() },
    //                             preActivity = preActivity,
    //                             preViewTreeHash = preHash
    //                         ) { changed, changeType ->
    //                             if (changed) {
    //                                 smartClearCache("input_text")
    //                                 Log.d(TAG, "input_text命令执行成功且检测到页面变化: 类型=$changeType")
    //                                 val data = JSONObject().apply { put("page_change_type", changeType) }
    //                                 callback(createSuccessResponse(data))
    //                             } else {
    //                                 Log.w(TAG, "input_text命令执行后未检测到页面变化")
    //                                 callback(createErrorResponse("Input text succeeded but page unchanged"))
    //                             }
    //                         }
    //                     } else {
    //                         Log.w(TAG, "input_text命令执行失败: NativeController返回false")
    //                         callback(createErrorResponse("Input text action failed"))
    //                     }
    //                 }
    //             } else {
    //                 // 没有坐标，尝试使用当前焦点视图或第一个EditText
    //                 val rootView = activity.findViewById<View>(android.R.id.content)
    //                 val focusedView = rootView.findFocus()
                    
    //                 if (focusedView is EditText) {
    //                     // 如果已有焦点EditText，直接输入
    //                     Log.d(TAG, "使用焦点EditText输入")
    //                     focusedView.setText(text)
    //                     // 移动光标到末尾
    //                     focusedView.setSelection(text.length)
    //                     // 成功后进行页面变化验证
    //                     PageChangeVerifier.verifyActionWithPageChange(
    //                         handler = Handler(Looper.getMainLooper()),
    //                         getCurrentActivity = { ActivityTracker.getCurrentActivity() },
    //                         preActivity = preActivity,
    //                         preViewTreeHash = preHash
    //                     ) { changed, changeType ->
    //                         if (changed) {
    //                             smartClearCache("input_text")
    //                             val data = JSONObject().apply { put("page_change_type", changeType) }
    //                             Log.d(TAG, "输入文本导致页面变化，类型: $changeType")
    //                             callback(createSuccessResponse(data))
    //                         } else {
    //                             callback(createErrorResponse("输入文本操作成功但页面未变化"))
    //                         }
    //                     }
    //                 } else {
    //                     // 尝试找到第一个EditText并输入
    //                     val editText = findFirstEditText(rootView)
    //                     if (editText != null) {
    //                         Log.d(TAG, "找到EditText，准备输入")
    //                         // 点击EditText获取焦点
    //                         editText.requestFocus()
    //                         // 显示软键盘
    //                         val imm = activity.getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
    //                         imm.showSoftInput(editText, InputMethodManager.SHOW_IMPLICIT)
                            
    //                         // 等待软键盘弹出后输入
    //                         Handler(Looper.getMainLooper()).postDelayed({
    //                             editText.setText(text)
    //                             editText.setSelection(text.length)
    //                             // 成功后进行页面变化验证
    //                             PageChangeVerifier.verifyActionWithPageChange(
    //                                 handler = Handler(Looper.getMainLooper()),
    //                                 getCurrentActivity = { ActivityTracker.getCurrentActivity() },
    //                                 preActivity = preActivity,
    //                                 preViewTreeHash = preHash
    //                             ) { changed, changeType ->
    //                                 if (changed) {
    //                                     smartClearCache("input_text")
    //                                     val data = JSONObject().apply { put("page_change_type", changeType) }
    //                                     callback(createSuccessResponse(data))
    //                                 } else {
    //                                     callback(createErrorResponse("Input text succeeded but page unchanged"))
    //                                 }
    //                             }
    //                         }, 300)
    //                     } else {
    //                         Log.w(TAG, "input_text命令执行失败: 未找到输入框")
    //                         callback(createErrorResponse("No input field found. Please provide coordinates (x, y) for input_text command."))
    //                     }
    //                 }
    //             }
    //         } catch (e: Exception) {
    //             Log.e(TAG, "input_text命令执行异常: ${e.message}", e)
    //             callback(createErrorResponse("Exception: ${e.message}"))
    //         }
    //     }
    // }


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
        val index = params.optInt("index", 0)
        
        if (activity == null) {
            Log.w(TAG, "input_text命令执行失败: Activity为空")
            callback(createErrorResponse("No active activity"))
            return
        }
        
        Handler(Looper.getMainLooper()).post {
            try {
                // 动作前状态用于页面变化验证
                val preActivity = activity
                val preHash = PageChangeVerifier.computePreViewTreeHash(activity)
                val preWebHash = PageChangeVerifier.computePreWebViewAggHash(activity)
                
                // 从缓存中获取元素树
                val elementTree = cachedElementTree
                if (elementTree == null) {
                    Log.w(TAG, "未找到缓存的元素树")
                    callback(createErrorResponse("Element tree not available"))
                    return@post
                }
                
                // 根据索引查找元素
                val targetElement = findElementByIndex(elementTree, index)
                if (targetElement == null) {
                    Log.w(TAG, "未找到索引为 $index 的元素")
                    callback(createErrorResponse("Element with index $index not found"))
                    return@post
                }
                
                // 使用ElementController设置输入值
                ElementController.setInputValue(activity, targetElement.resourceId, text) { success ->
                    if (success) {
                        // 成功后进行页面变化验证
                        PageChangeVerifier.verifyActionWithPageChange(
                            handler = Handler(Looper.getMainLooper()),
                            getCurrentActivity = { ActivityTracker.getCurrentActivity() },
                            preActivity = preActivity,
                            preViewTreeHash = preHash,
                            preWebViewAggHash = preWebHash
                        ) { changed, changeType ->
                            if (changed) {
                                smartClearCache("input_text")
                                
                                // 构建详细的描述信息
                                val elementDesc = buildInputTextDescription(targetElement, index, text)
                                
                                val data = JSONObject().apply { 
                                    put("page_change_type", changeType)
                                    put("element_index", index)
                                    put("message", elementDesc)
                                }
                                callback(createSuccessResponse(data))
                            } else {
                                Log.w(TAG, "input_text命令执行后未检测到页面变化")
                                callback(createErrorResponse("Input text succeeded but page unchanged"))
                            }
                        }
                    } else {
                        Log.w(TAG, "input_text命令执行失败: 设置输入值失败")
                        callback(createErrorResponse("Failed to set input value"))
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
        if (activity == null) {
            Log.w(TAG, "back命令执行失败: Activity为空")
            callback(createErrorResponse("No active activity"))
            return
        }
        
        Handler(Looper.getMainLooper()).post {
            try {
                // 动作前状态用于页面变化验证
                val preActivity = activity
                val preHash = PageChangeVerifier.computePreViewTreeHash(activity)
                val preWebHash = PageChangeVerifier.computePreWebViewAggHash(activity)
                NativeController.goBack(activity) { success ->
                    if (success) {
                        // 成功后进行页面变化验证
                        PageChangeVerifier.verifyActionWithPageChange(
                            handler = Handler(Looper.getMainLooper()),
                            getCurrentActivity = { ActivityTracker.getCurrentActivity() },
                            preActivity = preActivity,
                            preViewTreeHash = preHash,
                            preWebViewAggHash = preWebHash
                        ) { changed, changeType ->
                            if (changed) {
                                clearCache()
                                val data = JSONObject().apply { put("page_change_type", changeType) }
                                callback(createSuccessResponse(data))
                            } else {
                                Log.w(TAG, "back命令执行后未检测到页面变化")
                                callback(createErrorResponse("Back succeeded but page unchanged"))
                            }
                        }
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
                    // 动作前状态用于页面变化验证（按键前已计算）
                    val preActivity = activity
                    val preHash = PageChangeVerifier.computePreViewTreeHash(activity)
                    // 成功后进行页面变化验证
                    PageChangeVerifier.verifyActionWithPageChange(
                        handler = Handler(Looper.getMainLooper()),
                        getCurrentActivity = { ActivityTracker.getCurrentActivity() },
                        preActivity = preActivity,
                        preViewTreeHash = preHash,
                        preWebViewAggHash = PageChangeVerifier.computePreWebViewAggHash(activity)
                    ) { changed, changeType ->
                        if (changed) {
                            clearCache()
                            Log.d(TAG, "press_key命令执行成功且检测到页面变化: keycode=$keycode, 类型=$changeType")
                            val data = JSONObject().apply { put("page_change_type", changeType) }
                            callback(createSuccessResponse(data))
                        } else {
                            Log.w(TAG, "press_key命令执行后未检测到页面变化")
                            callback(createErrorResponse("Press key succeeded but page unchanged"))
                        }
                    }
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
     * 构建元素的详细描述信息（点击动作）
     */
    private fun buildElementDescription(element: GenericElement, index: Int): String {
        val className = element.className.substringAfterLast('.')
        
        // 构建描述信息，优先级：text > contentDesc > resourceId
        // 如果都没有，使用 className 作为描述
        val description = when {
            element.text.isNotEmpty() -> "'${element.text}'"
            element.contentDesc.isNotEmpty() -> "'${element.contentDesc}'"
            element.resourceId.isNotEmpty() -> "'${element.resourceId.substringAfterLast('/')}'"
            else -> "'$className'"  // 使用类名作为兜底描述
        }
        
        val centerX = (element.bounds.left + element.bounds.right) / 2
        val centerY = (element.bounds.top + element.bounds.bottom) / 2
        
        return "Tap element at index $index: $description ($className) at coordinates ($centerX, $centerY)"
    }
    
    /**
     * 构建输入文本的详细描述信息
     */
    private fun buildInputTextDescription(element: GenericElement, index: Int, inputText: String): String {
        val className = element.className.substringAfterLast('.')
        
        // 构建目标元素描述，优先级：resourceId > contentDesc > text
        // 如果都没有，使用 className 作为描述
        val targetDesc = when {
            element.resourceId.isNotEmpty() -> "'${element.resourceId.substringAfterLast('/')}'"
            element.contentDesc.isNotEmpty() -> "'${element.contentDesc}'"
            element.text.isNotEmpty() -> "'${element.text}'"
            else -> "'$className'"  // 使用类名作为兜底描述
        }
        
        val centerX = (element.bounds.left + element.bounds.right) / 2
        val centerY = (element.bounds.top + element.bounds.bottom) / 2
        
        return "Input text at index $index: '$inputText' into $targetDesc ($className) at coordinates ($centerX, $centerY)"
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

