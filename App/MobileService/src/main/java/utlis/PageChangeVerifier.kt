package utlis

import android.app.Activity
import android.os.Handler
import android.util.Log
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.webkit.WebView
import android.graphics.Bitmap
import android.graphics.Canvas

/**
 * 页面变化动作执行验证工具
 * 以Activity变化与视图树哈希变化作为证据，验证一次UI动作是否引发页面变化。
 */
object PageChangeVerifier {
    private const val TAG = "PageChangeVerifier"

    /**
     * [显眼提示] 关键参数用途说明
     * - stableWindowMs：稳定窗口时长（毫秒）。从“最后一次检测到变化”开始，页面需连续稳定至少该时长才进行最终对比。
     *   用途：过滤点击高亮、ripple、轻动画等瞬时抖动，确保以“稳定后的页面状态”判定是否真正发生页面变化。
     *   建议：动画较多的页面可设为 800–1000ms；默认 800ms。
     *
     * - timeoutMs：最大等待总时长（毫秒）。若在该时长内始终未达到稳定窗口，则认为“未变化”并返回。
     *   用途：为验证过程设定上限，避免长时间占用轮询与阻塞。
     *   建议：普通场景 3000–5000ms；默认 3000ms。
     *
     * - intervalMs：轮询间隔（毫秒）。用于定时检查当前 Activity、视图树哈希与 WebView 聚合哈希。
     *   用途：控制检测粒度与开销；间隔越小越敏感，但CPU开销更高。
     *   建议：50–150ms；默认 100ms。
     */

    /**
     * 页面变化动作执行验证函数（稳定窗口版）
     * 在动作触发后持续轮询页面状态，若检测到变化则继续等待直至页面进入稳定窗口（minStableMs）；
     * 最终以“稳定后的状态”与动作前初始状态进行对比，判断是否存在语义上的页面变化，避免动画/按压态等瞬时抖动造成误判。
     *
     * 参数说明：
     * - handler: 主线程 Handler，用于定时轮询页面状态
     * - getCurrentActivity: 提供当前 Activity 的函数
     * - preActivity: 动作前的 Activity
     * - preViewTreeHash: 动作前视图树哈希（可为 null）
     * - preWebViewAggHash: 动作前 WebView 聚合视觉哈希（可为 null）
     * - timeoutMs: 总超时时间（毫秒，默认 3000ms）；在该时间内未进入稳定窗口则返回未变化
     * - intervalMs: 轮询间隔（毫秒，默认 100ms）
     * - stableWindowMs: 稳定窗口（毫秒，默认 800ms）；从最后一次检测到变化起持续稳定达到该窗口，视为稳定
     * - callback: 验证结果回调，返回：
     *   1) changed: 是否存在页面变化（以稳定后的状态与初始状态对比）
     *   2) pageChangeType: 页面变化类型："activity_switch"、"view_hash_change"、"webview_hash_change" 或其 _and_ 组合；未变化为 "none"
     */
    fun verifyActionWithPageChange(
        handler: Handler,
        getCurrentActivity: () -> Activity?,
        preActivity: Activity?,
        preViewTreeHash: Int?,
        preWebViewAggHash: String?,
        timeoutMs: Long = 3000L,
        intervalMs: Long = 100L,
        stableWindowMs: Long = 800L,
        callback: (Boolean, String) -> Unit
    ) {
        var verificationCompleted = false
        val startTime = System.currentTimeMillis()
        val initialActivity = preActivity
        val initialViewTreeHash = preViewTreeHash
        val initialWebViewAggHash = preWebViewAggHash

        var lastChangeTime = startTime
        var detectedAnyChange = false

        val checkRunnable = object : Runnable {
            override fun run() {
                if (verificationCompleted) return
                val now = System.currentTimeMillis()
                val elapsed = now - startTime

                val currentActivity = try {
                    getCurrentActivity()
                } catch (e: Exception) {
                    Log.w(TAG, "获取当前Activity异常: ${e.message}")
                    null
                }

                var changedThisLoop = false

                // Activity 变化
                val hasActivityChange = currentActivity != initialActivity
                if (hasActivityChange) {
                    changedThisLoop = true
                }

                // 视图树哈希变化
                var currentViewTreeHash: Int? = null
                if (initialViewTreeHash != null && currentActivity != null) {
                    try {
                        val rootView = currentActivity.window?.decorView?.rootView
                        if (rootView != null) {
                            currentViewTreeHash = calculateViewTreeHash(rootView)
                            if (currentViewTreeHash != initialViewTreeHash) {
                                changedThisLoop = true
                            }
                        }
                    } catch (e: Exception) {
                        Log.w(TAG, "计算视图树哈希时发生异常", e)
                    }
                }

                // WebView 聚合视觉哈希变化
                var currentWebViewAggHash: String? = null
                if (currentActivity != null) {
                    try {
                        currentWebViewAggHash = calculateAggregateWebViewHash(currentActivity)
                        if (!(initialWebViewAggHash == null && currentWebViewAggHash == null)) {
                            if (currentWebViewAggHash != initialWebViewAggHash) {
                                changedThisLoop = true
                            }
                        }
                    } catch (e: Exception) {
                        Log.w(TAG, "计算WebView哈希时发生异常", e)
                    }
                }

                if (changedThisLoop) {
                    detectedAnyChange = true
                    lastChangeTime = now
                }

                val stableDuration = now - lastChangeTime
                val isStable = stableDuration >= stableWindowMs

                if (isStable) {
                    // 稳定后，以当前稳定状态与初始状态进行最终对比
                    val finalTypes = mutableListOf<String>()
                    if (hasActivityChange) finalTypes.add("activity_switch")
                    if (initialViewTreeHash != null && currentViewTreeHash != null && currentViewTreeHash != initialViewTreeHash) {
                        finalTypes.add("view_hash_change")
                    }
                    if (!(initialWebViewAggHash == null && currentWebViewAggHash == null)) {
                        if (currentWebViewAggHash != initialWebViewAggHash) {
                            finalTypes.add("webview_hash_change")
                        }
                    }
                    val typeStr = if (finalTypes.isEmpty()) "none" else finalTypes.joinToString("_and_")
                    verificationCompleted = true
                    if (detectedAnyChange && typeStr != "none") {
                        callback(true, typeStr)
                    } else {
                        callback(false, "none")
                    }
                } else if (elapsed >= timeoutMs) {
                    verificationCompleted = true
                    callback(false, "none")
                } else {
                    handler.postDelayed(this, intervalMs)
                }
            }
        }

        handler.postDelayed(checkRunnable, intervalMs)
    }

    /**
     * 计算动作前的视图树哈希
     * @param activity 当前Activity
     * @return 视图树哈希，可能为null
     */
    fun computePreViewTreeHash(activity: Activity?): Int? {
        return try {
            val rootView = activity?.window?.decorView?.rootView ?: return null
            calculateViewTreeHash(rootView)
        } catch (e: Exception) {
            Log.w(TAG, "获取视图树哈希失败", e)
            null
        }
    }

    /**
     * 计算动作前的WebView聚合视觉哈希
     * @param activity 当前Activity
     * @return 聚合哈希（可能为null）
     */
    fun computePreWebViewAggHash(activity: Activity?): String? {
        return try {
            val act = activity ?: return null
            calculateAggregateWebViewHash(act)
        } catch (e: Exception) {
            Log.w(TAG, "获取WebView聚合哈希失败", e)
            null
        }
    }

    /**
     * 递归计算视图树的哈希值
     * @param view 根视图
     * @return 视图树哈希
     */
    /**
     * 计算视图树哈希（包含尺寸、滚动与子树结构）
     * 引入 scrollX/scrollY 与 translationX/translationY，使滚动与轻动画也被感知
     */
    private fun calculateViewTreeHash(view: View): Int {
        var hash = view.javaClass.simpleName.hashCode()
        hash = hash * 31 + view.visibility
        hash = hash * 31 + view.isEnabled.hashCode()
        hash = hash * 31 + view.width
        hash = hash * 31 + view.height
        hash = hash * 31 + view.scrollX
        hash = hash * 31 + view.scrollY
        hash = hash * 31 + view.translationX.toInt()
        hash = hash * 31 + view.translationY.toInt()

        if (view is TextView) {
            hash = hash * 31 + (view.text?.toString()?.hashCode() ?: 0)
        }

        if (view is ViewGroup) {
            hash = hash * 31 + view.childCount
            for (i in 0 until view.childCount) {
                hash = hash * 31 + calculateViewTreeHash(view.getChildAt(i))
            }
        }
        return hash
    }

    /**
     * 查找当前Activity根视图下的所有WebView实例
     * @param activity 当前Activity
     * @return WebView列表（可能为空）
     */
    private fun findAllWebViews(activity: Activity): List<WebView> {
        val root = activity.window?.decorView?.rootView ?: return emptyList()
        val result = mutableListOf<WebView>()
        fun dfs(v: View) {
            if (v is WebView) {
                result.add(v)
            } else if (v is ViewGroup) {
                for (i in 0 until v.childCount) {
                    dfs(v.getChildAt(i))
                }
            }
        }
        dfs(root)
        return result
    }

    /**
     * 计算单个WebView的视觉内容哈希（缩略绘制 + MD5）
     * @param webView 目标WebView
     * @param thumbWidth 缩略宽度（默认160）
     * @param thumbHeight 缩略高度（默认160）
     * @return 十六进制MD5字符串，失败返回null
     */
    private fun computeWebViewVisualHash(webView: WebView, thumbWidth: Int = 160, thumbHeight: Int = 160): String? {
        return try {
            val w = webView.width
            val h = webView.height
            if (w <= 0 || h <= 0) return null
            val bitmap = Bitmap.createBitmap(thumbWidth, thumbHeight, Bitmap.Config.ARGB_8888)
            val canvas = Canvas(bitmap)
            val scaleX = thumbWidth.toFloat() / w.toFloat()
            val scaleY = thumbHeight.toFloat() / h.toFloat()
            canvas.scale(scaleX, scaleY)
            webView.draw(canvas)
            val md = java.security.MessageDigest.getInstance("MD5")
            val pixels = IntArray(thumbWidth * thumbHeight)
            bitmap.getPixels(pixels, 0, thumbWidth, 0, 0, thumbWidth, thumbHeight)
            for (px in pixels) {
                md.update(px.toByte())
                md.update((px ushr 8).toByte())
                md.update((px ushr 16).toByte())
                md.update((px ushr 24).toByte())
            }
            val digest = md.digest()
            bitmap.recycle()
            val sb = StringBuilder(digest.size * 2)
            for (b in digest) {
                val v = b.toInt() and 0xFF
                if (v < 16) sb.append('0')
                sb.append(v.toString(16))
            }
            sb.toString()
        } catch (e: Exception) {
            Log.w(TAG, "计算WebView视觉哈希失败", e)
            null
        }
    }

    /**
     * 计算当前Activity下所有WebView视觉哈希的聚合值
     * 将各WebView哈希排序后连接，并再次MD5为稳定聚合哈希
     * @param activity 当前Activity
     * @return 聚合哈希（十六进制），无WebView或全失败返回null
     */
    private fun calculateAggregateWebViewHash(activity: Activity): String? {
        val webViews = findAllWebViews(activity)
        if (webViews.isEmpty()) return null
        val hashes = mutableListOf<String>()
        for (wv in webViews) {
            val h = computeWebViewVisualHash(wv)
            if (h != null) hashes.add(h)
        }
        if (hashes.isEmpty()) return null
        hashes.sort()
        return try {
            val md = java.security.MessageDigest.getInstance("MD5")
            val concat = hashes.joinToString(separator = "|")
            val bytes = concat.toByteArray(Charsets.UTF_8)
            val digest = md.digest(bytes)
            val sb = StringBuilder(digest.size * 2)
            for (b in digest) {
                val v = b.toInt() and 0xFF
                if (v < 16) sb.append('0')
                sb.append(v.toString(16))
            }
            sb.toString()
        } catch (e: Exception) {
            Log.w(TAG, "计算聚合WebView哈希失败", e)
            null
        }
    }
}
