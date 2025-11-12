package utlis

import android.app.Activity
import android.os.Handler
import android.util.Log
import android.view.View
import android.view.ViewGroup
import android.widget.TextView

/**
 * 页面变化动作执行验证工具
 * 以Activity变化与视图树哈希变化作为证据，验证一次UI动作是否引发页面变化。
 */
object PageChangeVerifier {
    private const val TAG = "PageChangeVerifier"

    /**
     * 页面变化动作执行验证函数。
     * 通过对比动作前后 Activity 与视图树哈希，判断是否发生页面变化，并给出页面变化类型。
     *
     * 防抖与延迟策略：
     * - 计算并比较视图树哈希在开始验证后至少延迟2秒进行（避免瞬时抖动导致误判）。
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
     *   2) pageChangeType: 页面变化类型，取值为 "activity_switch_and_view_hash_change" | "activity_switch" | "view_hash_change" | "none"
     */
    fun verifyActionWithPageChange(
        handler: Handler,
        getCurrentActivity: () -> Activity?,
        preActivity: Activity?,
        preViewTreeHash: Int?,
        timeoutMs: Long = 3000L,
        intervalMs: Long = 100L,
        callback: (Boolean, String) -> Unit
    ) {
        var verificationCompleted = false
        val startTime = System.currentTimeMillis()

        val initialActivity = preActivity
        val initialViewTreeHash = preViewTreeHash

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
                            // 延迟两秒后再计算并比较哈希，避免瞬时抖动造成误判
                            if (elapsed >= 2000L) {
                                val currentViewTreeHash = calculateViewTreeHash(rootView)
                                hasViewTreeChange = currentViewTreeHash != initialViewTreeHash
                            } else {
                                // 未到2秒延迟，本次循环不进行哈希比较
                            }
                        }
                    } catch (e: Exception) {
                        Log.w(TAG, "计算视图树哈希时发生异常", e)
                    }
                }

                val hasPageChange = hasActivityChange || hasViewTreeChange
                val changeType = when {
                    hasActivityChange && hasViewTreeChange -> "activity_switch_and_view_hash_change"
                    hasActivityChange -> "activity_switch"
                    hasViewTreeChange -> "view_hash_change"
                    else -> "none"
                }
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
     * 递归计算视图树的哈希值
     * @param view 根视图
     * @return 视图树哈希
     */
    private fun calculateViewTreeHash(view: View): Int {
        var hash = view.javaClass.simpleName.hashCode()
        hash = hash * 31 + view.visibility
        hash = hash * 31 + view.isEnabled.hashCode()

        if (view is TextView) {
            hash = hash * 31 + (view.text?.toString()?.hashCode() ?: 0)
        }

        if (view is ViewGroup) {
            for (i in 0 until view.childCount) {
                hash = hash * 31 + calculateViewTreeHash(view.getChildAt(i))
            }
        }

        return hash
    }
}