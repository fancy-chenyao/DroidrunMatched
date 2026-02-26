package com.example.emplab

import Agent.CommandHandler
import android.content.Intent
import android.util.Log
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ScrollView
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * 自动化动作回归测试：覆盖 CommandHandler.kt 中所有已实现的命令
 * 每个命令测试10次，打印详细的单次与汇总报告
 */
@RunWith(AndroidJUnit4::class)
class AutoReportAgentTest {
    companion object {
        private const val TAG = "AutoReportAgentTest"
        private const val DEFAULT_TIMEOUT_SECONDS = 10L
        private const val RUNS_PER_ACTION = 10
        // TestHostActivity 中的视图ID常量
        private const val BTN_ID = 1001
        private const val EDIT_ID = 1002
        private const val SCROLL_ID = 1003
        private const val TEXT_ID = 1004
        private const val NEUTRAL_ID = 1005
        private const val GO_NEXT_ID = 1006
        private const val ADD_ITEM_ID = 1007
    }

    // ActivityScenario 引导宿主测试Activity，避免因测试包名导致的无法解析Activity问题
    private lateinit var scenario: ActivityScenario<TestHostActivity>

    /**
     * 测试前置初始化：使用 targetContext 显式启动 TestHostActivity
     */
    @Before
    fun setUp() {
        val targetContext = InstrumentationRegistry.getInstrumentation().targetContext
        val intent = Intent(targetContext, TestHostActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        scenario = ActivityScenario.launch(intent)
    }

    /**
     * 测试后清理：关闭 ActivityScenario
     */
    @After
    fun tearDown() {
        try {
            scenario.close()
        } catch (_: Exception) {
        }
    }

    /**
     * 执行动作命令并返回响应，同时打印单次报告
     * 返回 Pair<响应JSON, 单次耗时毫秒>
     */
    private fun execAndReport(cmd: String, params: JSONObject, label: String): Pair<JSONObject, Long> {
        val latch = CountDownLatch(1)
        val resultRef = AtomicReference<JSONObject>()
        var durationMs = 0L
        val t0 = System.currentTimeMillis()
        scenario.onActivity { activity ->
            CommandHandler.handleCommand(cmd, params, "req_$label", activity) { response ->
                durationMs = System.currentTimeMillis() - t0
                val status = response.optString("status")
                val changeType = response.optString("page_change_type", "")
                val legacyType = response.optString("change_type", "")
                val uiChanged = response.optBoolean("ui_changed", false)
                val ct = if (changeType.isNotEmpty()) changeType else if (legacyType.isNotEmpty()) legacyType else if (uiChanged) "ui_changed" else "none"
                System.out.println("[AgentReport] Action=$label Status=$status ChangeType=$ct Duration=${durationMs}ms Response=${response}")
                resultRef.set(response)
                latch.countDown()
            }
        }
        val ok = latch.await(DEFAULT_TIMEOUT_SECONDS, TimeUnit.SECONDS)
        assertTrue("命令超时: $cmd", ok)
        val resp = resultRef.get()
        assertNotNull("响应为空: $cmd", resp)
        return Pair(resp!!, durationMs)
    }

    /**
     * 计算视图中心坐标（dp单位）
     */
    private fun getViewCenterDp(viewId: Int): Pair<Int, Int> {
        var cx = 0
        var cy = 0
        scenario.onActivity {
            val v = it.findViewById<View>(viewId)
            val loc = IntArray(2)
            v.getLocationOnScreen(loc)
            val density = it.resources.displayMetrics.density
            cx = ((loc[0] + v.width / 2) / density).toInt()
            cy = ((loc[1] + v.height / 2) / density).toInt()
        }
        return Pair(cx, cy)
    }

    /**
     * 获取视图的标签描述（类型与文本），用于报告目标信息
     */
    private fun getViewLabel(viewId: Int): String {
        var label = ""
        scenario.onActivity {
            val v = it.findViewById<View>(viewId)
            label = when (v) {
                is Button -> "Button '${v.text}'"
                is EditText -> "EditText"
                is ScrollView -> "ScrollView"
                is TextView -> "TextView '${v.text}'"
                else -> v.javaClass.simpleName
            }
        }
        return label
    }

    /**
     * 获取当前页面状态（get_state）并返回 a11y_tree
     */
    private fun getA11yTree(): JSONArray {
        val (_, _) = execAndReport("get_state", JSONObject(), "GET_STATE_PROBE")
        // 再次取一次以确保缓存完整
        val (resp, _) = execAndReport("get_state", JSONObject(), "GET_STATE_CACHE")
        val tree = resp.optJSONArray("a11y_tree") ?: JSONArray()
        return tree
    }

    /**
     * 在 a11y_tree 中根据 text 查找稳定 index（递归）
     */
    private fun findIndexByText(tree: JSONArray, text: String): Int? {
        fun search(arr: JSONArray): Int? {
            for (i in 0 until arr.length()) {
                val obj = arr.optJSONObject(i) ?: continue
                val nodeText = obj.optString("text", "")
                if (nodeText == text) {
                    return obj.optInt("index", -1).takeIf { it >= 0 }
                }
                val children = obj.optJSONArray("children")
                if (children != null) {
                    val found = search(children)
                    if (found != null) return found
                }
            }
            return null
        }
        return search(tree)
    }

    /**
     * 单动作循环测试执行器：执行 runs 次并打印汇总报告
     */
    private fun repeatActionWithSummary(
        label: String,
        runs: Int = RUNS_PER_ACTION,
        buildParams: (Int) -> JSONObject,
        executor: (JSONObject, String) -> Pair<JSONObject, Long>,
        postAssert: ((JSONObject) -> Unit)? = null,
        targetDesc: String
    ) {
        val recorder = ReportAggregator()
        var success = 0
        var error = 0
        var totalMs = 0L
        val changeTypeCounts = mutableMapOf<String, Int>()
        for (i in 1..runs) {
            val actionName = "${label}_RUN_$i"
            val params = buildParams(i)
            System.out.println("[AgentTarget] Action=$actionName Target=$targetDesc")
            val (resp, ms) = executor(params, actionName)
            totalMs += ms
            val status = resp.optString("status")
            if (status == "success") success++ else error++
            val ct = resp.optString("page_change_type", "").ifEmpty {
                resp.optString("change_type", "").ifEmpty {
                    if (resp.optBoolean("ui_changed", false)) "ui_changed" else "none"
                }
            }
            changeTypeCounts[ct] = (changeTypeCounts[ct] ?: 0) + 1
            recorder.note(label, ms, status, ct)
            postAssert?.invoke(resp)
        }
        val avgMs = if (runs > 0) totalMs / runs else 0
        System.out.println("[AgentSummary] Action=$label Runs=$runs Success=$success Error=$error AvgDuration=${avgMs}ms ChangeTypeCounts=$changeTypeCounts")
        recorder.printTableFor(label)
    }

    /**
     * 详细测试报告聚合器：按动作类型统计耗时、成功率与变化类型分布
     */
    private class ReportAggregator {
        private val durationsMap = HashMap<String, ArrayList<Long>>()
        private val successMap = HashMap<String, Int>()
        private val errorMap = HashMap<String, Int>()
        private val changeTypes = HashMap<String, HashMap<String, Int>>()

        /**
         * 记录一次动作结果
         */
        fun note(label: String, durationMs: Long, status: String, changeType: String) {
            durationsMap.getOrPut(label) { ArrayList() }.add(durationMs)
            if (status == "success") {
                successMap[label] = (successMap[label] ?: 0) + 1
            } else {
                errorMap[label] = (errorMap[label] ?: 0) + 1
            }
            val ctMap = changeTypes.getOrPut(label) { HashMap() }
            ctMap[changeType] = (ctMap[changeType] ?: 0) + 1
        }

        /**
         * 打印指定动作的详细测试报告（参考 FullAgentTest 风格）
         */
        fun printTableFor(label: String) {
            val durations = durationsMap[label] ?: return
            if (durations.isEmpty()) return
            val avg = durations.map { it }.average().toLong()
            val min = durations.minOrNull() ?: 0L
            val max = durations.maxOrNull() ?: 0L
            val count = durations.size
            val succ = successMap[label] ?: 0
            val err = errorMap[label] ?: 0
            val successRate = if (count > 0) (succ * 100 / count) else 0
            val types = changeTypes[label]?.entries?.joinToString { "${it.key}:${it.value}" } ?: "None"

            System.out.println("[AgentReport] ============================================")
            System.out.println("[AgentReport] 动作执行性能报告 (单位: ms)")
            System.out.println("[AgentReport] ============================================")
            System.out.println(String.format("[AgentReport] | %-10s | %-6s | %-6s | %-8s | %-8s | %-8s |", "动作类型", "总次数", "成功率", "平均耗时", "最大耗时", "最小耗时"))
            System.out.println(String.format("[AgentReport] | %-10s | %-6d | %-5d%% | %-7dms | %-7dms | %-7dms |", label, count, successRate, avg, max, min))
            System.out.println("[AgentReport] Types " + label + " = " + types)
            System.out.println("[AgentReport] --------------------------------------------")
        }
    }
    /**
     * 测试 take_screenshot：10次执行与报告
     */
    @Test
    fun testTakeScreenshot() {
        repeatActionWithSummary(
            label = "TAKE_SCREENSHOT",
            buildParams = { JSONObject() },
            executor = { params, name -> execAndReport("take_screenshot", params, name) },
            targetDesc = "Activity=TestHostActivity full-window screenshot"
        )
    }

    /**
     * 测试 get_state：10次执行与报告
     */
    @Test
    fun testGetState() {
        repeatActionWithSummary(
            label = "GET_STATE",
            buildParams = { JSONObject() },
            executor = { params, name -> execAndReport("get_state", params, name) },
            postAssert = { resp ->
                assertTrue(resp.has("phone_state"))
                assertTrue(resp.has("a11y_tree"))
            },
            targetDesc = "Activity=TestHostActivity UI tree and phone_state"
        )
    }

    /**
     * 测试 tap：10次执行与报告（点击 Test Button）
     */
    @Test
    fun testTap() {
        val center = getViewCenterDp(BTN_ID)
        val viewLabel = getViewLabel(BTN_ID)
        val targetDesc = "$viewLabel id=$BTN_ID center=(${center.first}, ${center.second}) Activity=TestHostActivity"
        repeatActionWithSummary(
            label = "TAP",
            buildParams = { JSONObject().apply { put("x", center.first); put("y", center.second) } },
            executor = { params, name -> execAndReport("tap", params, name) },
            postAssert = {
                scenario.onActivity { act ->
                    val btn = act.findViewById<Button>(BTN_ID)
                    assertNotNull(btn)
                }
            },
            targetDesc = targetDesc
        )
    }

    /**
     * 测试 tap_by_index：10次执行与报告（点击 Go Next）
     */
    @Test
    fun testTapByIndex() {
        // 先获取稳定索引
        val tree = getA11yTree()
        val idx = findIndexByText(tree, "Go Next")
        assertTrue("未找到 Go Next 的稳定索引", idx != null)
        val targetDesc = "ByIndex text='Go Next' index=${idx!!} Activity=TestHostActivity"
        repeatActionWithSummary(
            label = "TAP_BY_INDEX",
            buildParams = { JSONObject().apply { put("index", idx!!) } },
            executor = { params, name -> execAndReport("tap_by_index", params, name) },
            targetDesc = targetDesc
        )
    }

    /**
     * 测试 swipe：10次执行与报告（在 ScrollView 内部向上滚动）
     */
    @Test
    fun testSwipe() {
        var start: Pair<Int, Int> = Pair(0, 0)
        var end: Pair<Int, Int> = Pair(0, 0)
        scenario.onActivity {
            val sv = it.findViewById<ScrollView>(SCROLL_ID)
            val loc = IntArray(2)
            sv.getLocationOnScreen(loc)
            val density = it.resources.displayMetrics.density
            val leftDp = (loc[0] / density).toInt()
            val topDp = (loc[1] / density).toInt()
            val widthDp = (sv.width / density).toInt()
            val heightDp = (sv.height / density).toInt()
            start = Pair(leftDp + widthDp / 2, topDp + heightDp * 3 / 4)
            end = Pair(leftDp + widthDp / 2, topDp + heightDp / 4)
        }
        val targetDesc = "ScrollView id=$SCROLL_ID start=(${start.first}, ${start.second}) end=(${end.first}, ${end.second}) Activity=TestHostActivity"
        repeatActionWithSummary(
            label = "SWIPE",
            buildParams = {
                JSONObject().apply {
                    put("start_x", start.first); put("start_y", start.second)
                    put("end_x", end.first); put("end_y", end.second)
                    put("duration_ms", 300)
                }
            },
            executor = { params, name -> execAndReport("swipe", params, name) },
            targetDesc = targetDesc
        )
    }

    /**
     * 测试 input_text：10次执行与报告（向 EditText 输入不同内容）
     */
    @Test
    fun testInputText() {
        val tree = getA11yTree()
        val idx = findIndexByText(tree, "Seed")
        assertTrue("未找到 EditText 的稳定索引（文本 Seed）", idx != null)
        val targetDesc = "EditText text='Seed' index=${idx!!} Activity=TestHostActivity"
        repeatActionWithSummary(
            label = "INPUT_TEXT",
            buildParams = { i ->
                JSONObject().apply {
                    put("index", idx!!)
                    put("text", "Hello_$i")
                }
            },
            executor = { params, name -> execAndReport("input_text", params, name) },
            postAssert = {
                scenario.onActivity { act ->
                    val et = act.findViewById<EditText>(EDIT_ID)
                    assertNotNull(et)
                }
            },
            targetDesc = targetDesc
        )
    }

    /**
     * 测试 back：10次执行与报告（先导航到第二页，再返回）
     */
    @Test
    fun testBack() {
        // 导航到第二页
        val nextCenter = getViewCenterDp(GO_NEXT_ID)
        execAndReport("tap", JSONObject().apply { put("x", nextCenter.first); put("y", nextCenter.second) }, "PRE_NAV_TAP")
        repeatActionWithSummary(
            label = "BACK",
            buildParams = { JSONObject() },
            executor = { params, name -> execAndReport("back", params, name) },
            targetDesc = "Back on Second Screen Activity=TestSecondActivity"
        )
    }

}
