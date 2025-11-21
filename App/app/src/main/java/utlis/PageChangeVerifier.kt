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
     * 页面变化动作执行验证函数。
     * 通过对比动作前后 Activity、原生视图树哈希与 WebView 可视内容哈希，判断是否发生页面变化，并给出页面变化类型。
     *
     * 防抖与延迟策略：
     * - 计算并比较视图树哈希与 WebView 哈希均在开始验证后至少延迟2秒进行（避免瞬时抖动导致误判）。
     * - 建议将总超时时间设置到3秒，以便在2秒延迟之后仍有1秒的判断窗口。
     *
     * 参数说明：
     * - handler: 主线程 Handler，用于定时轮询页面状态
     * - getCurrentActivity: 提供当前 Activity 的函数
     * - preActivity: 动作前的 Activity
     * - preViewTreeHash: 动作前视图树哈希（可为 null）
     * - timeoutMs: 超时时间（毫秒，默认 3000ms）
     * - intervalMs: 轮询间隔（毫秒，默认 100ms）
     * - callback: 验证结果回调，返回两个参数：
     *   1) changed: 是否检测到页面变化
     *   2) pageChangeType: 页面变化类型，可能为 "activity_switch"、"view_hash_change"、"webview_hash_change" 及其组合（以 _and_ 连接），或 "none"
     */
    fun verifyActionWithPageChange(
        handler: Handler,
        getCurrentActivity: () -> Activity?,
        preActivity: Activity?,
        preViewTreeHash: Int?,
        preWebViewAggHash: String?,
        timeoutMs: Long = 3000L,
        intervalMs: Long = 100L,
        callback: (Boolean, String) -> Unit
    ) {
        var verificationCompleted = false
        val startTime = System.currentTimeMillis()

        val initialActivity = preActivity
        val initialViewTreeHash = preViewTreeHash
        val initialWebViewAggHash = preWebViewAggHash

        val checkRunnable = object : Runnable {
            override fun run() {
                if (verificationCompleted) return

                val currentTime = System.currentTimeMillis()
                val elapsed = currentTime - startTime

                val currentActivity = try {
                    getCurrentActivity()
                } catch (e: Exception) {
                    Log.w(TAG, "获取当前Activity异常: ${e.message}")
                    null
                }

                val hasActivityChange = currentActivity != initialActivity

                var hasViewTreeChange = false
                if (initialViewTreeHash != null && currentActivity != null) {
                    try {
                        val rootView = currentActivity.window?.decorView?.rootView
                        if (rootView != null) {
                            // 延迟500ms后再计算并比较哈希，快速检测UI变化
                            if (elapsed >= 500L) {
                                val currentViewTreeHash = calculateViewTreeHash(rootView)
                                hasViewTreeChange = currentViewTreeHash != initialViewTreeHash
                            } else {
                                // 未到500ms延迟，本次循环不进行哈希比较
                            }
                        }
                    } catch (e: Exception) {
                        Log.w(TAG, "计算视图树哈希时发生异常", e)
                    }
                }

                var hasWebViewChange = false
                if (currentActivity != null && elapsed >= 500L) {
                    try {
                        val currentWebViewAggHash = calculateAggregateWebViewHash(currentActivity)
                        hasWebViewChange = currentWebViewAggHash != initialWebViewAggHash
                    } catch (e: Exception) {
                        Log.w(TAG, "计算WebView哈希时发生异常", e)
                    }
                }

                val hasPageChange = hasActivityChange || hasViewTreeChange || hasWebViewChange
                val types = mutableListOf<String>()
                if (hasActivityChange) types.add("activity_switch")
                if (hasViewTreeChange) types.add("view_hash_change")
                if (hasWebViewChange) types.add("webview_hash_change")
                val changeType = if (types.isEmpty()) "none" else types.joinToString("_and_")
                if (hasPageChange) {
                    verificationCompleted = true
                    callback(true, changeType)
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
    private fun calculateViewTreeHash(view: View): Int {
        var hash = view.javaClass.simpleName.hashCode()
        hash = hash * 31 + view.visibility
        hash = hash * 31 + view.isEnabled.hashCode()
        
        // 添加位置和大小信息，使哈希更敏感
        hash = hash * 31 + view.width
        hash = hash * 31 + view.height

        if (view is TextView) {
            hash = hash * 31 + (view.text?.toString()?.hashCode() ?: 0)
        }

        if (view is ViewGroup) {
            // 包含子元素数量，使结构变化更明显
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