package com.example.emplab

import Agent.CommandHandler
import android.os.Build
import android.view.View
import android.widget.Button
import android.widget.ScrollView
import android.util.Log
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.rules.ActivityScenarioRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONArray
import org.json.JSONObject
import org.junit.*
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.rules.TestWatcher
import org.junit.runner.Description
import org.junit.runner.RunWith
import org.junit.Assume
import com.example.emplab.BuildConfig
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * NOV-only 测试套件：禁用 PageChangeVerifier，对各动作重复执行10次并断言成功
 */
@RunWith(AndroidJUnit4::class)
class NovOnlyAgentTest {

    @get:Rule
    val activityRule = ActivityScenarioRule(TestHostActivity::class.java)

    private lateinit var scenario: ActivityScenario<TestHostActivity>
    private lateinit var recorder: PerformanceRecorder
    private val TAG = "NovOnlyAgentTest"
    private val debug = DebugLogger(TAG)

    /**
     * 测试事件监听：统一记录开始/成功/失败，便于在 Logcat 观察
     */
    @get:Rule
    val testWatcher: TestWatcher = object : TestWatcher() {
        override fun starting(description: Description) {
            Log.i(TAG, "TEST START: ${description.className}.${description.methodName}")
        }
        override fun succeeded(description: Description) {
            Log.i(TAG, "TEST OK: ${description.className}.${description.methodName}")
        }
        override fun failed(e: Throwable, description: Description) {
            Log.e(TAG, "TEST FAIL: ${description.className}.${description.methodName} -> ${e.message}", e)
        }
        override fun skipped(e: org.junit.AssumptionViolatedException, description: Description) {
            Log.w(TAG, "TEST SKIP: ${description.className}.${description.methodName} -> ${e.message}")
        }
    }

    // 测试用的 View ID（与 TestHostActivity 保持一致）
    private val BTN_ID = 1001
    private val EDIT_ID = 1002
    private val SCROLL_ID = 1003
    private val NEUTRAL_ID = 1005

    // 统一超时与重复次数
    private val DEFAULT_TIMEOUT_SECONDS = 20L
    private val RUNS_PER_ACTION = 10

    /**
     * 测试前置初始化：获取场景、清理命令处理器缓存并预热元素树
     */
    @Before
    fun setUp() {
        /**
         * 若未显式启用端到端测试，则跳过本类所有用例
         */
        Assume.assumeTrue("跳过：未启用 E2E 测试", BuildConfig.ENABLE_AGENT_E2E_TESTS)
        debug.step("setUp.start")
        scenario = activityRule.scenario
        recorder = PerformanceRecorder()
        CommandHandler.clearCache()
        primeElementTree()
        debug.step("setUp.done")
    }

    /**
     * 测试结束：关闭场景
     */
    @After
    fun tearDown() {
        debug.step("tearDown.start")
        recorder.printReport()
        try {
            scenario.close()
        } catch (_: Exception) {
        }
        debug.step("tearDown.done")
    }

    /**
     * 预热元素树：调用一次 get_state 以保证后续按坐标解析目标控件
     */
    private fun primeElementTree() {
        debug.step("primeElementTree.start")
        val latch = CountDownLatch(1)
        scenario.onActivity { activity ->
            val params = JSONObject().apply {
                put("stabilize_timeout_ms", 1000)
                put("stable_window_ms", 300)
            }
            CommandHandler.handleCommand("get_state", params, "req_prime_nov", activity) {
                latch.countDown()
            }
        }
        latch.await(5, TimeUnit.SECONDS)
        debug.step("primeElementTree.end")
    }

    /**
     * 重置至初始场景：重建 Activity、清理缓存并重新预热元素树
     */
    private fun resetActivityToInitialState() {
        debug.step("resetActivityToInitialState.start")
        try {
            scenario.recreate()
        } catch (_: Exception) {
        }
        CommandHandler.clearCache()
        primeElementTree()
        debug.step("resetActivityToInitialState.end")
    }

    /**
     * 计算指定控件中心的屏幕坐标并转换为 dp
     */
    private fun getViewCenterDp(viewId: Int): Pair<Int, Int> {
        var xDp = 0
        var yDp = 0
        scenario.onActivity {
            val v = it.findViewById<View>(viewId)
            val loc = IntArray(2)
            v.getLocationOnScreen(loc)
            val d = it.resources.displayMetrics.density
            val cxPx = loc[0] + v.width / 2
            val cyPx = loc[1] + v.height / 2
            xDp = (cxPx / d).toInt()
            yDp = (cyPx / d).toInt()
        }
        return Pair(xDp, yDp)
    }

    /**
     * 执行命令并返回响应：在主线程调用 CommandHandler.handleCommand
     */
    private fun executeCommand(cmd: String, params: JSONObject, requestId: String, onResponse: (JSONObject) -> Unit) {
        val latch = CountDownLatch(1)
        val respRef = AtomicReference<JSONObject>()
        scenario.onActivity { activity ->
            CommandHandler.handleCommand(cmd, params, requestId, activity) { resp ->
                respRef.set(resp)
                latch.countDown()
            }
        }
        assertTrue(latch.await(DEFAULT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
        val resp = respRef.get()
        assertNotNull(resp)
        onResponse(resp!!)
    }

    /**
     * NOV-only：禁用验证的 tap，重复10次并断言成功
     */
    @Test
    fun testTapNovOnlyRepeated() {
        val actionName = "TAP_NOV_ONLY"
        for (i in 1..RUNS_PER_ACTION) {
            resetActivityToInitialState()
            val center = getViewCenterDp(BTN_ID)
            val params = JSONObject().apply {
                put("x", center.first)
                put("y", center.second)
                put("verify_page_change", false)
            }
            recorder.start(actionName)
            executeCommand("tap", params, "TAP_NOV_$i") { resp ->
                val ok = (resp.optString("status") == "success")
                assertTrue(ok)
                recorder.stopWithOutcome(actionName, ok)
            }
        }
    }

    /**
     * NOV-only：禁用验证的 input_text，重复10次并断言成功
     */
    @Test
    fun testInputTextNovOnlyRepeated() {
        val actionName = "INPUT_NOV_ONLY"
        for (i in 1..RUNS_PER_ACTION) {
            resetActivityToInitialState()
            val center = getViewCenterDp(EDIT_ID)
            val text = "NOV ${System.currentTimeMillis() % 1000}"
            val params = JSONObject().apply {
                put("text", text)
                put("element", JSONArray().apply {
                    put(center.first); put(center.second)
                })
                put("verify_page_change", false)
            }
            recorder.start(actionName)
            executeCommand("input_text", params, "INPUT_NOV_$i") { resp ->
                val ok = (resp.optString("status") == "success")
                assertTrue(ok)
                recorder.stopWithOutcome(actionName, ok)
            }
        }
    }

    /**
     * NOV-only：禁用验证的 swipe，重复10次并断言成功
     */
    @Test
    fun testSwipeNovOnlyRepeated() {
        val actionName = "SWIPE_NOV_ONLY"
        for (i in 1..RUNS_PER_ACTION) {
            resetActivityToInitialState()
            var startXDp = 0; var startYDp = 0; var endXDp = 0; var endYDp = 0
            scenario.onActivity {
                val scroll = it.findViewById<View>(SCROLL_ID)
                val loc = IntArray(2); scroll.getLocationOnScreen(loc)
                val d = it.resources.displayMetrics.density
                val sx = loc[0] + scroll.width / 2
                val sy = loc[1] + scroll.height - 50
                val ex = sx
                val ey = loc[1] + 50
                startXDp = (sx / d).toInt(); startYDp = (sy / d).toInt()
                endXDp = (ex / d).toInt(); endYDp = (ey / d).toInt()
            }
            val params = JSONObject().apply {
                put("start_x", startXDp); put("start_y", startYDp)
                put("end_x", endXDp); put("end_y", endYDp)
                put("duration_ms", 500)
                put("verify_page_change", false)
            }
            recorder.start(actionName)
            executeCommand("swipe", params, "SWIPE_NOV_$i") { resp ->
                val ok = (resp.optString("status") == "success")
                assertTrue(ok)
                // 额外校验：滚动确实发生
                scenario.onActivity {
                    val scroll = it.findViewById<ScrollView>(SCROLL_ID)
                    assertTrue(scroll.scrollY > 0)
                }
                recorder.stopWithOutcome(actionName, ok)
            }
        }
    }

    /**
     * NOV-only：禁用验证的 double tap，重复10次并断言成功
     */
    @Test
    fun testDoubleTapNovOnlyRepeated() {
        val actionName = "DOUBLE_NOV_ONLY"
        for (i in 1..RUNS_PER_ACTION) {
            resetActivityToInitialState()
            val center = getViewCenterDp(BTN_ID)
            val params = JSONObject().apply {
                put("element", JSONArray().apply {
                    put(center.first); put(center.second)
                })
                put("verify_page_change", false)
            }
            recorder.start(actionName)
            executeCommand("double tap", params, "DOUBLE_NOV_$i") { resp ->
                val ok = (resp.optString("status") == "success")
                assertTrue(ok)
                recorder.stopWithOutcome(actionName, ok)
            }
        }
    }

    /**
     * NOV-only：禁用验证的 long press，重复10次并断言成功
     */
    @Test
    fun testLongPressNovOnlyRepeated() {
        val actionName = "LONG_NOV_ONLY"
        for (i in 1..RUNS_PER_ACTION) {
            resetActivityToInitialState()
            val center = getViewCenterDp(BTN_ID)
            val params = JSONObject().apply {
                put("element", JSONArray().apply {
                    put(center.first); put(center.second)
                })
                put("verify_page_change", false)
            }
            recorder.start(actionName)
            executeCommand("long press", params, "LONG_NOV_$i") { resp ->
                val ok = (resp.optString("status") == "success")
                assertTrue(ok)
                // 额外校验：长按后的文本为 LongPressed
                var okText = false
                scenario.onActivity {
                    val btn = it.findViewById<Button>(BTN_ID)
                    okText = (btn.text?.toString() == "LongPressed")
                }
                assertTrue(okText)
                recorder.stopWithOutcome(actionName, ok && okText)
            }
        }
    }

    /**
     * 动作性能记录器：记录开始/结束时间与成功标记，输出汇总报告
     */
    class PerformanceRecorder {
        private val startTimes = HashMap<String, Long>()
        private val durations = ArrayList<Record>()

        /**
         * 单条记录结构
         */
        data class Record(
            val name: String,
            val durationMs: Long,
            val success: Boolean = true,
            val startMs: Long = 0L,
            val endMs: Long = 0L
        )

        /**
         * 开始记录某动作
         */
        fun start(name: String) {
            startTimes[name] = System.currentTimeMillis()
        }

        /**
         * 停止记录并写入成功标记
         */
        fun stopWithOutcome(name: String, success: Boolean) {
            val start = startTimes[name] ?: return
            val end = System.currentTimeMillis()
            val duration = end - start
            durations.add(Record(name, duration, success, start, end))
            Log.i("Performance", "Action [$name] took ${duration}ms (start=$start, end=$end), success=$success")
            System.out.println("[AgentReport] ActionRecord name=" + name + " start=" + start + " end=" + end + " duration=" + duration + "ms success=" + success)
        }

        /**
         * 输出性能汇总报告
         */
        fun printReport() {
            Log.i("AgentTest", "============================================")
            Log.i("AgentTest", "NOV-only 动作执行性能报告 (单位: ms)")
            Log.i("AgentTest", "============================================")
            Log.i("AgentTest", String.format("| %-14s | %-6s | %-6s | %-8s | %-8s | %-8s |", "动作类型", "总次数", "成功率", "平均耗时", "最大耗时", "最小耗时"))
            Log.i("AgentTest", "--------------------------------------------")
            System.out.println("[AgentReport] ============================================")
            System.out.println("[AgentReport] NOV-only 动作执行性能报告 (单位: ms)")
            System.out.println("[AgentReport] ============================================")
            System.out.println(String.format("[AgentReport] | %-14s | %-6s | %-6s | %-8s | %-8s | %-8s |", "动作类型", "总次数", "成功率", "平均耗时", "最大耗时", "最小耗时"))

            val grouped = durations.groupBy { it.name }
            grouped.forEach { (name, records) ->
                val avg = records.map { it.durationMs }.average().toLong()
                val min = records.minOf { it.durationMs }
                val max = records.maxOf { it.durationMs }
                val count = records.size
                val successCount = records.count { it.success }
                val successRate = if (count > 0) (successCount * 100 / count) else 0
                Log.i("AgentTest", String.format("| %-14s | %-6d | %-5d%% | %-7dms | %-7dms | %-7dms |", name, count, successRate, avg, max, min))
                System.out.println(String.format("[AgentReport] | %-14s | %-6d | %-5d%% | %-7dms | %-7dms | %-7dms |", name, count, successRate, avg, max, min))
            }
            Log.i("AgentTest", "============================================")
            System.out.println("[AgentReport] --------------------------------------------")
            System.out.println("[AgentReport] ============================================")
        }
    }

    /**
     * 测试调试日志工具：统一输出步骤、信息与错误
     */
    class DebugLogger(private val tag: String) {
        fun step(name: String) {
            Log.d(tag, "STEP: $name [thread=${Thread.currentThread().name}]")
        }
        fun info(message: String) {
            Log.i(tag, message)
        }
        fun error(where: String, e: Throwable?) {
            if (e != null) {
                Log.e(tag, "ERROR at $where: ${e.message}", e)
            } else {
                Log.e(tag, "ERROR at $where")
            }
        }
    }
}
