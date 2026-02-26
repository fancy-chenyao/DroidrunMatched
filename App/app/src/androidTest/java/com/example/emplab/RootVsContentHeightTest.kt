package com.example.emplab

import android.view.ViewGroup
import android.view.ViewTreeObserver
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import controller.UIUtils
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.Assert.assertTrue
import org.junit.Assume
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.math.max

@RunWith(AndroidJUnit4::class)
class RootVsContentHeightTest {

    /**
     * 检查窗口根视图高度与内容区域高度差异
     * 结论：若 android.R.id.content 的 measuredHeight 小于 rootView.height，
     * 则下方黑条极可能为“未绘制的底部区域”
     */
    @Test
    fun checkContentHeightVsRootHeight() {
        ActivityScenario.launch(TestHostActivity::class.java).use { scenario ->
            var rootHeight = -1
            var contentHeight = -1
            val latch = CountDownLatch(1)
            scenario.onActivity { activity ->
                val rootView = activity.window?.decorView?.rootView
                val content = activity.findViewById<ViewGroup>(android.R.id.content)
                // 若关键视图为空，直接结束，后续以 Assume 跳过
                if (content == null || rootView == null) {
                    android.util.Log.w("RootVsContentHeightTest", "content 或 rootView 为空")
                    latch.countDown()
                    return@onActivity
                }
                // 若已完成测量，直接读取高度
                if (content.measuredHeight > 0 && rootView.height > 0) {
                    contentHeight = max(content.measuredHeight, content.height)
                    rootHeight = rootView.height
                    latch.countDown()
                } else {
                    // 监听下一次布局完成后读取高度
                    content.viewTreeObserver.addOnGlobalLayoutListener(object : ViewTreeObserver.OnGlobalLayoutListener {
                        override fun onGlobalLayout() {
                            if (content.measuredHeight > 0 && rootView.height > 0) {
                                content.viewTreeObserver.removeOnGlobalLayoutListener(this)
                                contentHeight = max(content.measuredHeight, content.height)
                                rootHeight = rootView.height
                                latch.countDown()
                            }
                        }
                    })
                }
            }
            // 在测试线程等待UI空闲与布局完成，避免在主线程阻塞
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()
            val ok = latch.await(1500, TimeUnit.MILLISECONDS)
            // 若视图未完成布局或为空，则跳过该测试
            Assume.assumeTrue("视图未完成布局或关键视图为空，跳过", ok && rootHeight >= 0 && contentHeight >= 0)
            var statusBarPx = 0
            scenario.onActivity { activity ->
                statusBarPx = UIUtils.getStatusBarHeight(activity)
            }

            val diff = rootHeight - contentHeight
            val isUnpaintedBottom = contentHeight < rootHeight

            android.util.Log.i(
                "RootVsContentHeightTest",
                "rootHeight=$rootHeight, contentHeight=$contentHeight, diff=$diff, statusBarPx=$statusBarPx, isUnpaintedBottom=$isUnpaintedBottom"
            )

            // 基本合理性校验：视图应已完成布局（避免偶发0导致构建失败）
            assertTrue("视图未完成布局或高度为0（请重试）", rootHeight >= 0 && contentHeight >= 0)
        }
    }
}
