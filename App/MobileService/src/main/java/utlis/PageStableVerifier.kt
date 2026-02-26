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

object PageStableVerifier {
    private const val TAG = "PageStableVerifier"

    /**
     * 等待页面达到稳定状态（无 Activity、视图树哈希、WebView 视觉哈希变化，且持续稳定一段时间）
     * @param handler 主线程 Handler，用于定时轮询
     * @param getCurrentActivity 获取当前 Activity 的方法
     * @param timeoutMs 总超时时间（毫秒），到期仍未稳定则回调 false
     * @param minStableMs 最小稳定窗口（毫秒），从最后一次变化起持续稳定达到该窗口视为稳定
     * @param intervalMs 轮询间隔（毫秒）
     * @param callback 稳定结果回调；true 表示在超时前达到稳定，false 表示超时未稳定
     */
    fun waitUntilStable(
        handler: Handler,
        getCurrentActivity: () -> Activity?,
        timeoutMs: Long = 5000L,
        minStableMs: Long = 800L,
        intervalMs: Long = 100L,
        callback: (Boolean) -> Unit
    ) {
        val startTime = System.currentTimeMillis()
        var lastActivity: Activity? = null
        var lastViewTreeHash: Int? = null
        var lastWebViewAggHash: String? = null
        var lastChangeTime = startTime

        val checkRunnable = object : Runnable {
            override fun run() {
                val now = System.currentTimeMillis()
                val elapsed = now - startTime

                val currentActivity = try {
                    getCurrentActivity()
                } catch (e: Exception) {
                    Log.w(TAG, "获取当前Activity异常: ${e.message}")
                    null
                }

                var changed = false

                // Activity 变化
                if (currentActivity != lastActivity) {
                    changed = true
                }

                // 视图树哈希变化
                if (currentActivity != null) {
                    try {
                        val root = currentActivity.window?.decorView?.rootView
                        if (root != null) {
                            val curHash = calculateViewTreeHash(root)
                            if (lastViewTreeHash == null || curHash != lastViewTreeHash) {
                                changed = true
                            }
                            lastViewTreeHash = curHash
                        }
                    } catch (e: Exception) {
                        Log.w(TAG, "计算视图树哈希异常: ${e.message}")
                    }

                    // WebView 聚合视觉哈希变化
                    try {
                        val curAgg = calculateAggregateWebViewHash(currentActivity)
                        // null 与 null 视为未变化，其余均按变化判断
                        if (!(lastWebViewAggHash == null && curAgg == null)) {
                            if (curAgg != lastWebViewAggHash) {
                                changed = true
                            }
                        }
                        lastWebViewAggHash = curAgg
                    } catch (e: Exception) {
                        Log.w(TAG, "计算WebView聚合哈希异常: ${e.message}")
                    }
                }

                if (changed) {
                    lastChangeTime = now
                    lastActivity = currentActivity
                }

                val stableDuration = now - lastChangeTime
                if (stableDuration >= minStableMs) {
                    callback(true)
                } else if (elapsed >= timeoutMs) {
                    callback(false)
                } else {
                    handler.postDelayed(this, intervalMs)
                }
            }
        }

        handler.postDelayed(checkRunnable, intervalMs)
    }

    /**
     * 递归计算视图树哈希
     * @param view 根视图
     * @return 视图树哈希值
     */
    /**
     * 递归计算视图树哈希（包含尺寸、滚动与子树结构）
     * 增强稳定状态识别，对滚动与轻动画引起的变化更敏感
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
     * 计算当前 Activity 下所有 WebView 的视觉哈希聚合值
     * @param activity 当前 Activity
     * @return 十六进制 MD5 聚合哈希（可能为 null）
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
            Log.w(TAG, "计算聚合WebView哈希失败: ${e.message}")
            null
        }
    }

    /**
     * 查找当前 Activity 根视图下的所有 WebView
     * @param activity 当前 Activity
     * @return WebView 列表（可能为空）
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
     * 计算单个 WebView 的视觉内容哈希（缩略绘制 + MD5）
     * @param webView 目标 WebView
     * @param thumbWidth 缩略宽度（默认160）
     * @param thumbHeight 缩略高度（默认160）
     * @return 十六进制 MD5 字符串，失败返回 null
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
            Log.w(TAG, "计算WebView视觉哈希失败: ${e.message}")
            null
        }
    }
}

