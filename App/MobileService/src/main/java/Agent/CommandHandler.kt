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
import android.widget.TextView
import android.view.ViewGroup
import android.webkit.WebView
import Agent.ActivityTracker
import controller.ElementController
import controller.GenericElement
import controller.NativeController
import controller.UIUtils
import controller.PageSniffer
import controller.WebViewController
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import utlis.PageChangeVerifier
import utlis.PageStableVerifier
import utlis.HttpUploader

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
        // 添加重试机制，当activity为null时尝试获取
        val handler = Handler(Looper.getMainLooper())
        val maxRetries = 3
        var retryCount = 0
        
        fun attemptHandleCommand() {
            val currentActivity = ActivityTracker.getCurrentActivity() ?: activity
            if (currentActivity != null) {
                // 为回调添加超时保护
                val protectedCallback = createTimeoutProtectedCallback(
                    timeoutMs = MobileGPTGlobal.COMMAND_TIMEOUT,
                    originalCallback = callback
                )
                
                when (command) {
                    "take_screenshot" -> {
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
                            Log.d(TAG, "截图前页面稳定等待耗时: ${waitedMs}ms (timeout=${stabilizeTimeout}ms, stable_window=${stableWindow}ms)")
                            val current = ActivityTracker.getCurrentActivity() ?: currentActivity
                            handleTakeScreenshot(requestId, params, current) { resp ->
                                try {
                                    if (resp.optString("status") == "success") {
                                        resp.put("wait_stable_ms", waitedMs)
                                    }
                                } finally {
                                    protectedCallback(resp)
                                }
                            }
                        }
                    }
                    "get_state" -> {
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
                            val current = ActivityTracker.getCurrentActivity() ?: currentActivity
                            if (current == null) {
                                protectedCallback(createErrorResponse("No active activity"))
                                return@waitUntilStable
                            }
                            handleGetState(requestId, params, current, protectedCallback)
                        }
                    }
                    "tap" -> {
                        handleTap(requestId, params, currentActivity, protectedCallback)
                    }
                    "tap_by_index" -> {
                        handleTap(requestId, params, currentActivity, protectedCallback)
                    }
                    "swipe" -> {
                        handleSwipe(requestId, params, currentActivity, protectedCallback)
                    }
                    "input_text" -> {
                        handleInputText(requestId, params, currentActivity, protectedCallback)
                    }
                    "back" -> {
                        handleBack(requestId, params, currentActivity, protectedCallback)
                    }
                    "home" -> {
                        handleHome(requestId, params, currentActivity, protectedCallback)
                    }

                    "double tap" -> {
                        handleDoubleTap(requestId, params, currentActivity, protectedCallback)
                    }
                    "long press" -> {
                        handleLongPress(requestId, params, currentActivity, protectedCallback)
                    }
                    "press_key" -> {
                        handlePressKey(requestId, params, activity, protectedCallback)
                    }
                    "type" -> {
                        handlePressKey(requestId, params, activity, protectedCallback)
                    }
                    "wait" -> {
                        handleWait(requestId, params, currentActivity, protectedCallback)
                    }
                    "take_over" -> {
                        handleTakeOver(requestId, params, currentActivity, protectedCallback)
                    }
                    "note" -> {
                        handleNote(requestId, params, currentActivity, protectedCallback)
                    }
                    "call_api" -> {
                        handleCallApi(requestId, params, currentActivity, protectedCallback)
                    }
                    "interact" -> {
                        handleInteract(requestId, params, currentActivity, protectedCallback)
                    }
                    "finish" -> {
                        handleFinish(requestId, params, currentActivity, protectedCallback)
                    }
                    else -> {
                        Log.w(TAG, "未知命令: $command")
                        protectedCallback(createErrorResponse("Unknown command: $command"))
                    }
                }
            } else {
                retryCount++
                if (retryCount <= maxRetries) {
                    Log.d(TAG, "未找到活动Activity，${retryCount}次后重试，延迟100ms...")
                    handler.postDelayed({ attemptHandleCommand() }, 100)
                } else {
                    Log.w(TAG, "重试${maxRetries}次后仍未找到活动Activity")
                    callback(createErrorResponse("No active activity"))
                }
            }
        }
        
        attemptHandleCommand()
    }
    
    /**
     * 获取截图（纯截图上传版）
     * 仅负责截取当前页面并上传，页面稳定验证由调用方在函数外执行。
     * 参数：
     * - requestId: 请求ID
     * - params: 调用参数（保留扩展，如 include_meta）
     * - activity: 当前Activity（若为空则返回错误）
     * - callback: 结果回调（status=success 时返回 screenshot_ref）
     */
    private fun handleTakeScreenshot(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        if (activity == null) {
            callback(createErrorResponse("No active activity"))
            return
        }
        val current = ActivityTracker.getCurrentActivity() ?: activity
        Handler(Looper.getMainLooper()).post {
            try {
                takeScreenshotAsync(current) { bitmap ->
                    if (bitmap != null && !bitmap.isRecycled) {
                        Thread {
                            val uploadResp = HttpUploader.uploadBitmap(current, bitmap, requestId)
                            Handler(Looper.getMainLooper()).post {
                                if (uploadResp != null && uploadResp.optString("status") == "success") {
                                    val ref = JSONObject().apply {
                                        put("file_id", uploadResp.optString("file_id"))
                                        put("path", uploadResp.optString("path"))
                                        put("url", uploadResp.optString("url"))
                                        put("mime", uploadResp.optString("mime"))
                                        put("size", uploadResp.optInt("size"))
                                    }
                                    val data = JSONObject().apply { 
                                        put("screenshot_ref", ref)
                                    }
                                    callback(createSuccessResponse(data))
                                } else {
                                    callback(createErrorResponse("Upload screenshot failed"))
                                }
                            }
                        }.start()
                    } else {
                        callback(createErrorResponse("Failed to take screenshot"))
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "处理截图命令异常", e)
                callback(createErrorResponse("Exception: ${e.message}"))
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
    /**
     * 处理tap命令 - 点击操作（支持 element 或 index 参数，兼容 x/y）
     * 新增参数：
     * - verify_page_change: 是否启用页面变化验证（默认true），为false时跳过PageChangeVerifier
     * - verify_timeout_ms: 页面变化验证的最大等待时长（默认3000ms）
     * - verify_stable_window_ms: 页面变化验证的稳定窗口（默认800ms）
     * - verify_interval_ms: 页面变化验证的轮询间隔（默认100ms）
     */
    private fun handleTap(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        var x: Int? = null
        var y: Int? = null
        var fromIndex = false
        val hasElementArray = params.has("element")
        val hasIndex = params.has("index")
        
        if (hasElementArray) {
            val arr = params.optJSONArray("element")
            if (arr == null || arr.length() < 2) {
                callback(createErrorResponse("Invalid element array"))
                return
            }
            x = arr.optInt(0)
            y = arr.optInt(1)
        } else if (hasIndex) {
            fromIndex = true
        } else {
            if (!params.has("x") || !params.has("y")) {
                Log.w(TAG, "tap命令缺少参数: x=${params.has("x")}, y=${params.has("y")}")
                callback(createErrorResponse("Missing x or y parameter"))
                return
            }
            x = params.getInt("x")
            y = params.getInt("y")
        }
        
        if (activity == null) {
            Log.w(TAG, "tap命令执行失败: Activity为空")
            callback(createErrorResponse("No active activity"))
            return
        }
        
        Handler(Looper.getMainLooper()).post {
            try {
                // 动作前状态用于页面变化验证
                val preActivity = activity
                val preHash = PageChangeVerifier.computePreViewTreeHash(activity)
                val preWebHash = PageChangeVerifier.computePreWebViewAggHash(activity)
                
                var tapX = x
                var tapY = y
                
                if (fromIndex) {
                    val elementTree = cachedElementTree
                    if (elementTree == null) {
                        callback(createErrorResponse("Element tree not available"))
                        return@post
                    }
                    val index = params.optInt("index", 0)
                    val targetElement = findElementByIndex(elementTree, index)
                    if (targetElement == null) {
                        callback(createErrorResponse("Element with index $index not found"))
                        return@post
                    }
                    tapX = ((targetElement.bounds.left + targetElement.bounds.right) / 2f).toInt()
                    tapY = ((targetElement.bounds.top + targetElement.bounds.bottom) / 2f).toInt()
                }
                
                if (tapX == null || tapY == null) {
                    callback(createErrorResponse("Tap coordinates not resolved"))
                    return@post
                }
                // 归一化坐标转换为DP坐标（仅当来源为坐标参数时）
                val (tapXDp, tapYDp) = if (fromIndex) {
                    Pair(tapX!!.toFloat(), tapY!!.toFloat())
                } else {
                    normalizedToDp(activity, tapX!!, tapY!!)
                }
                // 执行坐标点击（dp单位）
                ElementController.clickByCoordinateDp(activity, tapXDp, tapYDp) { success ->
                    if (!success) {
                        Log.w(TAG, "tap命令执行失败: 点击操作返回false")
                        callback(createErrorResponse("Tap action failed"))
                        return@clickByCoordinateDp
                    }
                    // 验证开关与参数
                    val verifyPageChange = params.optBoolean("verify_page_change", false)
                    val verifyTimeoutMs = params.optLong("verify_timeout_ms", 3000L)
                    val verifyStableWindowMs = params.optLong("verify_stable_window_ms", 800L)
                    val verifyIntervalMs = params.optLong("verify_interval_ms", 100L)
                    if (!verifyPageChange) {
                        val data = JSONObject().apply { put("page_change_type", "verification_skipped") }
                        callback(createSuccessResponse(data))
                        return@clickByCoordinateDp
                    }
                    // 使用 PageChangeVerifier 验证页面变化（稳定窗口版）
                    PageChangeVerifier.verifyActionWithPageChange(
                        handler = Handler(Looper.getMainLooper()),
                        getCurrentActivity = { activity },
                        preActivity = preActivity,
                        preViewTreeHash = preHash,
                        preWebViewAggHash = preWebHash,
                        timeoutMs = verifyTimeoutMs,
                        intervalMs = verifyIntervalMs,
                        stableWindowMs = verifyStableWindowMs
                    ) { changed, changeType ->
                        if (changed) {
                            clearCache()
                            val data = JSONObject().apply { put("page_change_type", changeType) }
                            callback(createSuccessResponse(data))
                        } else {
                            Log.w(TAG, "tap命令执行后未检测到页面变化: ($tapX, $tapY)")
                            callback(createErrorResponse("Tap succeeded but page unchanged"))
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "tap命令执行异常: ${e.message}", e)
                callback(createErrorResponse("Exception: ${e.message}"))
            }
        }
    }
    
    
    // proceedWithUIChangeDetection 已移除；统一改为 PageChangeVerifier 验证页面变化
    
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
     * 根据坐标查找最匹配的元素（选取包含该点且面积最小的元素）
     */
    private fun findElementByCoordinate(root: GenericElement?, x: Int, y: Int): GenericElement? {
        if (root == null) return null
        var best: GenericElement? = null
        var bestArea = Int.MAX_VALUE
        
        fun traverse(e: GenericElement) {
            val b = e.bounds
            val contains = x >= b.left && x <= b.right && y >= b.top && y <= b.bottom
            if (contains) {
                val area = (b.right - b.left) * (b.bottom - b.top)
                if (area in 1 until bestArea) {
                    bestArea = area
                    best = e
                }
            }
            e.children.forEach { traverse(it) }
        }
        
        traverse(root)
        return best
    }
    
    /**
     * 将归一化坐标转换为DP坐标（基于rootView尺寸）
     * 说明：
     * - 以 decorView.rootView 的 width/height 作为归一化基准，保持与截图坐标体系一致
     * - 为兼容窗口坐标，y 叠加状态栏高度，使触控注入与窗口坐标对齐
     */
    private fun normalizedToDp(activity: Activity, xNorm: Int, yNorm: Int): Pair<Float, Float> {
        val density = activity.resources.displayMetrics.density
        val rootView = activity.window?.decorView?.rootView
            ?: throw IllegalStateException("rootView为空")
        if (rootView.width <= 0 || rootView.height <= 0) {
            throw IllegalStateException("rootView尚未完成布局，width/height=0")
        }
        val rootWidthDp = rootView.width / density
        val rootHeightDp = rootView.height / density
        val xDp = (xNorm.toFloat() / 1000f) * rootWidthDp
        var yDp = (yNorm.toFloat() / 1000f) * rootHeightDp
        // val statusBarDp = UIUtils.getStatusBarHeight(activity) / density
        // yDp += statusBarDp
        return Pair(xDp, yDp)
    }
    
    /**
     * 处理swipe命令 - 滑动操作
     */
    /**
     * 处理swipe命令 - 滑动操作（支持 start/end 数组，兼容旧参数）
     * 新增参数：
     * - verify_page_change: 是否启用页面变化验证（默认true），为false时跳过PageChangeVerifier
     * - verify_timeout_ms: 页面变化验证的最大等待时长（默认3000ms）
     * - verify_stable_window_ms: 页面变化验证的稳定窗口（默认800ms）
     * - verify_interval_ms: 页面变化验证的轮询间隔（默认100ms）
     */
    private fun handleSwipe(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        var startX: Int? = null
        var startY: Int? = null
        var endX: Int? = null
        var endY: Int? = null
        
        val startArr = params.optJSONArray("start")
        val endArr = params.optJSONArray("end")
        if (startArr != null && startArr.length() >= 2 && endArr != null && endArr.length() >= 2) {
            startX = startArr.optInt(0)
            startY = startArr.optInt(1)
            endX = endArr.optInt(0)
            endY = endArr.optInt(1)
        } else {
            val requiredParams = listOf("start_x", "start_y", "end_x", "end_y")
            for (param in requiredParams) {
                if (!params.has(param)) {
                    Log.w(TAG, "swipe命令缺少参数: $param")
                    callback(createErrorResponse("Missing parameter: $param"))
                    return
                }
            }
            startX = params.getInt("start_x")
            startY = params.getInt("start_y")
            endX = params.getInt("end_x")
            endY = params.getInt("end_y")
        }
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
                // 将归一化坐标转换为DP坐标
                val (startXDpConv, startYDpConv) = normalizedToDp(activity, startX!!, startY!!)
                val (endXDpConv, endYDpConv) = normalizedToDp(activity, endX!!, endY!!)
                ElementController.scrollByTouchDp(
                    activity = activity,
                    startXDp = startXDpConv,
                    startYDp = startYDpConv,
                    endXDp = endXDpConv,
                    endYDp = endYDpConv,
                    duration = duration.toLong()
                ) { success ->
                    if (success) {
                        // 验证开关与参数
                        val verifyPageChange = params.optBoolean("verify_page_change", false)
                        val verifyTimeoutMs = params.optLong("verify_timeout_ms", 3000L)
                        val verifyStableWindowMs = params.optLong("verify_stable_window_ms", 800L)
                        val verifyIntervalMs = params.optLong("verify_interval_ms", 100L)
                        if (!verifyPageChange) {
                            val data = JSONObject().apply { put("page_change_type", "verification_skipped") }
                            callback(createSuccessResponse(data))
                            return@scrollByTouchDp
                        }
                        // 成功后进行页面变化验证（稳定窗口版）
                        PageChangeVerifier.verifyActionWithPageChange(
                            handler = Handler(Looper.getMainLooper()),
                            getCurrentActivity = { ActivityTracker.getCurrentActivity() },
                            preActivity = preActivity,
                            preViewTreeHash = preHash,
                            preWebViewAggHash = preWebHash,
                            timeoutMs = verifyTimeoutMs,
                            intervalMs = verifyIntervalMs,
                            stableWindowMs = verifyStableWindowMs
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


    /**
     * 处理input_text/type命令 - 文本输入（支持 element 或 index）
     * 新增参数：
     * - verify_page_change: 是否启用页面变化验证（默认true），为false时跳过PageChangeVerifier
     * - verify_timeout_ms: 页面变化验证的最大等待时长（默认3000ms）
     * - verify_stable_window_ms: 页面变化验证的稳定窗口（默认800ms）
     * - verify_interval_ms: 页面变化验证的轮询间隔（默认100ms）
     */
    private fun handleInputText(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        if (!params.has("text")) {
            Log.w(TAG, "input_text命令缺少参数: text")
            callback(createErrorResponse("Missing text parameter"))
            return
        }
        val text = params.getString("text")
        val hasElementArray = params.has("element")
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
                
                // 根据元素或索引查找目标
                val targetElement = if (hasElementArray) {
                    val arr = params.optJSONArray("element")
                    if (arr == null || arr.length() < 2) {
                        callback(createErrorResponse("Invalid element array"))
                        return@post
                    }
                    val xNorm = arr.optInt(0)
                    val yNorm = arr.optInt(1)
                    val (xDp, yDp) = normalizedToDp(activity, xNorm, yNorm)
                    findElementByCoordinate(elementTree, xDp.toInt(), yDp.toInt())
                } else {
                    findElementByIndex(elementTree, index)
                }
                if (targetElement == null) {
                    if (hasElementArray) {
                        callback(createErrorResponse("Element at coordinate not found"))
                    } else {
                        Log.w(TAG, "未找到索引为 $index 的元素")
                        callback(createErrorResponse("Element with index $index not found"))
                    }
                    return@post
                }
                
                // 使用ElementController设置输入值
                ElementController.setInputValue(activity, targetElement.resourceId, text) { success ->
                    if (success) {
                        // 验证开关与参数
                        val verifyPageChange = params.optBoolean("verify_page_change", false)
                        val verifyTimeoutMs = params.optLong("verify_timeout_ms", 3000L)
                        val verifyStableWindowMs = params.optLong("verify_stable_window_ms", 800L)
                        val verifyIntervalMs = params.optLong("verify_interval_ms", 100L)
                        if (!verifyPageChange) {
                            val targetIndexFinal = if (hasElementArray) {
                                val stableMap = cachedStableIndexMap
                                stableMap?.get(targetElement) ?: targetElement.index
                            } else index
                            val elementDesc = buildInputTextDescription(targetElement, targetIndexFinal, text)
                            val data = JSONObject().apply { 
                                put("page_change_type", "verification_skipped")
                                put("element_index", targetIndexFinal)
                                put("message", elementDesc)
                                put("input_text", text)
                            }
                            callback(createSuccessResponse(data))
                            return@setInputValue
                        }
                        // 使用 PageChangeVerifier 验证页面变化（稳定窗口版）
                        PageChangeVerifier.verifyActionWithPageChange(
                            handler = Handler(Looper.getMainLooper()),
                            getCurrentActivity = { ActivityTracker.getCurrentActivity() },
                            preActivity = preActivity,
                            preViewTreeHash = preHash,
                            preWebViewAggHash = preWebHash,
                            timeoutMs = verifyTimeoutMs,
                            intervalMs = verifyIntervalMs,
                            stableWindowMs = verifyStableWindowMs
                        ) { changed, changeType ->
                            if (changed) {
                                smartClearCache("input_text")
                                val targetIndexFinal = if (hasElementArray) {
                                    val stableMap = cachedStableIndexMap
                                    stableMap?.get(targetElement) ?: targetElement.index
                                } else index
                                val elementDesc = buildInputTextDescription(targetElement, targetIndexFinal, text)
                                val data = JSONObject().apply { 
                                    put("page_change_type", changeType)
                                    put("element_index", targetIndexFinal)
                                    put("message", elementDesc)
                                    put("input_text", text)
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
     * 处理home命令 - 返回主页（占位）
     */
    private fun handleHome(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        callback(createErrorResponse("Home action not implemented"))
    }
    
    /**
     * 处理double tap命令 - 双击操作（支持element或index）
     * 新增参数：
     * - verify_page_change: 是否启用页面变化验证（默认true），为false时跳过PageChangeVerifier
     * - verify_timeout_ms: 页面变化验证的最大等待时长（默认3000ms）
     * - verify_stable_window_ms: 页面变化验证的稳定窗口（默认800ms）
     * - verify_interval_ms: 页面变化验证的轮询间隔（默认100ms）
     */
    private fun handleDoubleTap(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        if (activity == null) {
            callback(createErrorResponse("No active activity"))
            return
        }
        Handler(Looper.getMainLooper()).post {
            try {
                val preActivity = activity
                val preHash = PageChangeVerifier.computePreViewTreeHash(activity)
                val preWebHash = PageChangeVerifier.computePreWebViewAggHash(activity)
                
                var x: Int? = null
                var y: Int? = null
                val elementTree = cachedElementTree
                val hasElementArray = params.has("element")
                val hasIndex = params.has("index")
                if (hasElementArray) {
                    val arr = params.optJSONArray("element")
                    if (arr == null || arr.length() < 2) {
                        callback(createErrorResponse("Invalid element array"))
                        return@post
                    }
                    x = arr.optInt(0)
                    y = arr.optInt(1)
                } else if (hasIndex) {
                    if (elementTree == null) {
                        callback(createErrorResponse("Element tree not available"))
                        return@post
                    }
                    val index = params.optInt("index", 0)
                    val targetElement = findElementByIndex(elementTree, index)
                    if (targetElement == null) {
                        callback(createErrorResponse("Element with index $index not found"))
                        return@post
                    }
                    x = ((targetElement.bounds.left + targetElement.bounds.right) / 2f).toInt()
                    y = ((targetElement.bounds.top + targetElement.bounds.bottom) / 2f).toInt()
                } else {
                    callback(createErrorResponse("Missing element or index parameter"))
                    return@post
                }
                // 归一化坐标转换为DP坐标（当来源为坐标参数时）
                val (xDp, yDp) = if (hasElementArray) {
                    normalizedToDp(activity, x!!, y!!)
                } else {
                    Pair(x!!.toFloat(), y!!.toFloat())
                }
                ElementController.clickByCoordinateDp(activity, xDp, yDp) { first ->
                    if (!first) {
                        callback(createErrorResponse("First tap failed"))
                        return@clickByCoordinateDp
                    }
                    Handler(Looper.getMainLooper()).postDelayed({
                        ElementController.clickByCoordinateDp(activity, xDp, yDp) { second ->
                            if (!second) {
                                callback(createErrorResponse("Second tap failed"))
                                return@clickByCoordinateDp
                            }
                            // 验证开关与参数
                            val verifyPageChange = params.optBoolean("verify_page_change", false)
                            val verifyTimeoutMs = params.optLong("verify_timeout_ms", 3000L)
                            val verifyStableWindowMs = params.optLong("verify_stable_window_ms", 800L)
                            val verifyIntervalMs = params.optLong("verify_interval_ms", 100L)
                            if (!verifyPageChange) {
                                val data = JSONObject().apply { put("page_change_type", "verification_skipped") }
                                callback(createSuccessResponse(data))
                                return@clickByCoordinateDp
                            }
                            PageChangeVerifier.verifyActionWithPageChange(
                                handler = Handler(Looper.getMainLooper()),
                                getCurrentActivity = { ActivityTracker.getCurrentActivity() },
                                preActivity = preActivity,
                                preViewTreeHash = preHash,
                                preWebViewAggHash = preWebHash,
                                timeoutMs = verifyTimeoutMs,
                                intervalMs = verifyIntervalMs,
                                stableWindowMs = verifyStableWindowMs
                            ) { changed, changeType ->
                                if (changed) {
                                    clearCache()
                                    val data = JSONObject().apply { put("page_change_type", changeType) }
                                    callback(createSuccessResponse(data))
                                } else {
                                    callback(createErrorResponse("Double tap succeeded but page unchanged"))
                                }
                            }
                        }
                    }, 120L)
                }
            } catch (e: Exception) {
                Log.e(TAG, "double tap命令执行异常: ${e.message}", e)
                callback(createErrorResponse("Exception: ${e.message}"))
            }
        }
    }
    
    /**
     * 处理long press命令 - 长按操作（支持element或index）
     * 新增参数：
     * - verify_page_change: 是否启用页面变化验证（默认true），为false时跳过PageChangeVerifier
     * - verify_timeout_ms: 页面变化验证的最大等待时长（默认3000ms）
     * - verify_stable_window_ms: 页面变化验证的稳定窗口（默认800ms）
     * - verify_interval_ms: 页面变化验证的轮询间隔（默认100ms）
     */
    private fun handleLongPress(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        if (activity == null) {
            callback(createErrorResponse("No active activity"))
            return
        }
        Handler(Looper.getMainLooper()).post {
            try {
                val preActivity = activity
                val preHash = PageChangeVerifier.computePreViewTreeHash(activity)
                val preWebHash = PageChangeVerifier.computePreWebViewAggHash(activity)
                
                var x: Int? = null
                var y: Int? = null
                val elementTree = cachedElementTree
                val hasElementArray = params.has("element")
                val hasIndex = params.has("index")
                if (hasElementArray) {
                    val arr = params.optJSONArray("element")
                    if (arr == null || arr.length() < 2) {
                        callback(createErrorResponse("Invalid element array"))
                        return@post
                    }
                    x = arr.optInt(0)
                    y = arr.optInt(1)
                } else if (hasIndex) {
                    if (elementTree == null) {
                        callback(createErrorResponse("Element tree not available"))
                        return@post
                    }
                    val index = params.optInt("index", 0)
                    val targetElement = findElementByIndex(elementTree, index)
                    if (targetElement == null) {
                        callback(createErrorResponse("Element with index $index not found"))
                        return@post
                    }
                    x = ((targetElement.bounds.left + targetElement.bounds.right) / 2f).toInt()
                    y = ((targetElement.bounds.top + targetElement.bounds.bottom) / 2f).toInt()
                } else {
                    callback(createErrorResponse("Missing element or index parameter"))
                    return@post
                }
                // 归一化坐标转换为DP坐标（当来源为坐标参数时）
                val (xDp, yDp) = if (hasElementArray) {
                    normalizedToDp(activity, x!!, y!!)
                } else {
                    Pair(x!!.toFloat(), y!!.toFloat())
                }
                ElementController.longClickByCoordinateDp(activity, xDp, yDp) { success ->
                    if (!success) {
                        callback(createErrorResponse("Long press action failed"))
                        return@longClickByCoordinateDp
                    }
                    // 验证开关与参数
                    val verifyPageChange = params.optBoolean("verify_page_change", false)
                    val verifyTimeoutMs = params.optLong("verify_timeout_ms", 3000L)
                    val verifyStableWindowMs = params.optLong("verify_stable_window_ms", 800L)
                    val verifyIntervalMs = params.optLong("verify_interval_ms", 100L)
                    if (!verifyPageChange) {
                        val data = JSONObject().apply { put("page_change_type", "verification_skipped") }
                        callback(createSuccessResponse(data))
                        return@longClickByCoordinateDp
                    }
                    PageChangeVerifier.verifyActionWithPageChange(
                        handler = Handler(Looper.getMainLooper()),
                        getCurrentActivity = { ActivityTracker.getCurrentActivity() },
                        preActivity = preActivity,
                        preViewTreeHash = preHash,
                        preWebViewAggHash = preWebHash,
                        timeoutMs = verifyTimeoutMs,
                        intervalMs = verifyIntervalMs,
                        stableWindowMs = verifyStableWindowMs
                    ) { changed, changeType ->
                        if (changed) {
                            clearCache()
                            val data = JSONObject().apply { put("page_change_type", changeType) }
                            callback(createSuccessResponse(data))
                        } else {
                            callback(createErrorResponse("Long press succeeded but page unchanged"))
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "long press命令执行异常: ${e.message}", e)
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
     * 处理wait命令 - 等待一段时间（占位）
     */
    private fun handleWait(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        val durationStr = params.optString("duration", "0 seconds")
        val seconds = Regex("(\\d+)\\s*seconds").find(durationStr)?.groupValues?.getOrNull(1)?.toIntOrNull() ?: 0
        Handler(Looper.getMainLooper()).postDelayed({
            val data = JSONObject().apply { put("waited_seconds", seconds) }
            callback(createSuccessResponse(data))
        }, (seconds * 1000L))
    }
    
    /**
     * 处理take_over命令 - 接管（占位）
     */
    private fun handleTakeOver(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        val msg = params.optString("message", "")
        val data = JSONObject().apply { put("message", msg) }
        callback(createSuccessResponse(data))
    }
    
    /**
     * 处理note命令 - 备注（占位）
     */
    private fun handleNote(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        val msg = params.optString("message", "")
        val data = JSONObject().apply { put("message", msg) }
        callback(createSuccessResponse(data))
    }
    
    /**
     * 处理call_api命令 - 调用API（占位）
     */
    private fun handleCallApi(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        callback(createErrorResponse("Call_API not implemented"))
    }
    
    /**
     * 处理interact命令 - 交互（占位）
     */
    private fun handleInteract(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        callback(createSuccessResponse())
    }
    
    /**
     * 处理finish命令 - 结束（占位）
     */
    private fun handleFinish(
        requestId: String,
        params: JSONObject,
        activity: Activity?,
        callback: (JSONObject) -> Unit
    ) {
        val data = JSONObject().apply { 
            val msg = params.optString("message", "")
            if (msg.isNotEmpty()) put("message", msg)
        }
        callback(createSuccessResponse(data))
    }

    
    /**
     * 处理back命令 - 返回键
     * 新增参数：
     * - verify_page_change: 是否启用页面变化验证（默认true），为false时跳过PageChangeVerifier
     * - verify_timeout_ms: 页面变化验证的最大等待时长（默认3000ms）
     * - verify_stable_window_ms: 页面变化验证的稳定窗口（默认800ms）
     * - verify_interval_ms: 页面变化验证的轮询间隔（默认100ms）
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
                        // 验证开关与参数
                        val verifyPageChange = params.optBoolean("verify_page_change", false)
                        val verifyTimeoutMs = params.optLong("verify_timeout_ms", 3000L)
                        val verifyStableWindowMs = params.optLong("verify_stable_window_ms", 800L)
                        val verifyIntervalMs = params.optLong("verify_interval_ms", 100L)
                        if (!verifyPageChange) {
                            val data = JSONObject().apply { put("page_change_type", "verification_skipped") }
                            callback(createSuccessResponse(data))
                            return@goBack
                        }
                        // 成功后进行页面变化验证（稳定窗口版）
                        PageChangeVerifier.verifyActionWithPageChange(
                            handler = Handler(Looper.getMainLooper()),
                            getCurrentActivity = { ActivityTracker.getCurrentActivity() },
                            preActivity = preActivity,
                            preViewTreeHash = preHash,
                            preWebViewAggHash = preWebHash,
                            timeoutMs = verifyTimeoutMs,
                            intervalMs = verifyIntervalMs,
                            stableWindowMs = verifyStableWindowMs
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
     * 异步截图功能（统一使用rootView尺寸）
     * 说明：使用 decorView.rootView 的 width/height 与其在 Window 中的位置作为截图范围，
     * 可包含对话框/弹窗等位于内容视图之外的窗口装饰或覆盖层
     */
    private fun takeScreenshotAsync(activity: Activity, callback: (Bitmap?) -> Unit) {
        try {
            val rootView = activity.window?.decorView?.rootView
            if (rootView == null) {
                Log.w(TAG, "无法获取根视图")
                callback(null)
                return
            }
            if (rootView.width <= 0 || rootView.height <= 0) {
                Log.w(TAG, "根视图尚未完成布局，width/height=0")
                callback(null)
                return
            }
            
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                // Android 8.0+ 使用PixelCopy，截取rootView所在矩形
                val captureWidth = rootView.width
                val captureHeight = rootView.height
                val bitmap = Bitmap.createBitmap(captureWidth, captureHeight, Bitmap.Config.ARGB_8888)
                val loc = IntArray(2)
                rootView.getLocationInWindow(loc)
                val rect = android.graphics.Rect(loc[0], loc[1], loc[0] + captureWidth, loc[1] + captureHeight)
                
                PixelCopy.request(
                    activity.window,
                    rect,
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
                // Android 7.x：直接将rootView绘制到 Bitmap（避免 DrawingCache 兼容性问题）
                try {
                    val bmp = Bitmap.createBitmap(rootView.width, rootView.height, Bitmap.Config.ARGB_8888)
                    val canvas = android.graphics.Canvas(bmp)
                    rootView.draw(canvas)
                    
                    // 保存截图引用用于后续资源管理
                    recycleOldScreenshot()
                    lastScreenshot = bmp
                    
                    callback(bmp)
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

