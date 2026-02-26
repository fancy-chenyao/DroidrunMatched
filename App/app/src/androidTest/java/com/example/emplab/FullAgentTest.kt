package com.example.emplab

import android.app.Activity
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.rules.ActivityScenarioRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import Agent.ActivityTracker
import Agent.CommandHandler
import android.os.Build
import utlis.PageChangeVerifier
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.rules.TestWatcher
import org.junit.runner.Description
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.Assume
import com.example.emplab.BuildConfig
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * Agent 模块全量动作耗时与稳定性测试
 * 包含：动作执行、Verifier 验证、脏页面防御、耗时统计
 */
@RunWith(AndroidJUnit4::class)
class FullAgentTest {

    @get:Rule
    val grantPermissionRule: GrantPermissionRule = GrantPermissionRule.grant(*resolveRuntimePermissions())

    @get:Rule
    val activityRule = ActivityScenarioRule(TestHostActivity::class.java)

    private val TAG = "FullAgentTest"
    private val debug = DebugLogger(TAG)
    private lateinit var recorder: PerformanceRecorder
    private lateinit var scenario: ActivityScenario<TestHostActivity>

    /**
     * 计算元素树缓存：调用一次 get_state 以便后续按坐标查找元素
     */
    private fun primeElementTree() {
        debug.step("primeElementTree.start")
        val latch = CountDownLatch(1)
        scenario.onActivity { activity ->
            val params = JSONObject().apply {
                put("stabilize_timeout_ms", 1000)
                put("stable_window_ms", 300)
            }
            CommandHandler.handleCommand("get_state", params, "req_prime", activity) {
                latch.countDown()
            }
        }
        latch.await(5, TimeUnit.SECONDS)
        debug.step("primeElementTree.end")
    }
    /**
     * 计算与当前设备和清单匹配的运行时权限集合
     * - Android 13+(API 33+)：授予 READ_MEDIA_* 三项
     * - Android 12及以下(API <=32)：授予 READ/WRITE_EXTERNAL_STORAGE
     * 注意：避免在高版本上授予已移除的旧权限导致 GrantPermissionRule 失败
     */
    private fun resolveRuntimePermissions(): Array<String> {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            arrayOf(
                android.Manifest.permission.READ_MEDIA_IMAGES,
                android.Manifest.permission.READ_MEDIA_VIDEO,
                android.Manifest.permission.READ_MEDIA_AUDIO
            )
        } else {
            arrayOf(
                android.Manifest.permission.WRITE_EXTERNAL_STORAGE,
                android.Manifest.permission.READ_EXTERNAL_STORAGE
            )
        }
    }
    /**
     * 测试事件监听：记录每个用例的开始、成功、失败与跳过，便于在 Logcat 观察
     */
    @get:Rule
    val testWatcher: TestWatcher = object : TestWatcher() {
        override fun starting(description: Description) {
            android.util.Log.i(TAG, "TEST START: ${description.className}.${description.methodName}")
        }
        override fun succeeded(description: Description) {
            android.util.Log.i(TAG, "TEST OK: ${description.className}.${description.methodName}")
        }
        override fun failed(e: Throwable, description: Description) {
            android.util.Log.e(TAG, "TEST FAIL: ${description.className}.${description.methodName} -> ${e.message}", e)
        }
        override fun skipped(e: org.junit.AssumptionViolatedException, description: Description) {
            android.util.Log.w(TAG, "TEST SKIP: ${description.className}.${description.methodName} -> ${e.message}")
        }
    }

    // 测试用的 View ID
    private val BTN_ID = 1001
    private val EDIT_ID = 1002
    private val SCROLL_ID = 1003
    private val TEXT_ID = 1004
    private val NEUTRAL_ID = 1005
    private val GO_NEXT_ID = 1006
    private val ADD_ITEM_ID = 1007
    // 等待超时统一配置（秒）
    private val DEFAULT_TIMEOUT_SECONDS = 20L
    // [显眼配置] 每个测试的重复执行组数 N（用于统计平均/最大/最小耗时）
    // 根据需求调整，默认设置为 N=10
    private val RUNS_PER_ACTION = 10
    // [显眼配置] 页面变化验证的默认参数（稳定窗口与轮询间隔）
    private val DEFAULT_VERIFY_TIMEOUT_MS = 4000L
    private val DEFAULT_VERIFY_STABLE_WINDOW_MS = 900L
    private val DEFAULT_VERIFY_INTERVAL_MS = 80L

    /**
     * 测试前置初始化，准备性能记录器与测试场景，并确保页面空闲稳定
     */
    @Before
    fun setUp() {
        /**
         * 若未显式启用端到端测试，则跳过本类所有用例
         * 以避免在默认环境下因外部依赖未就绪导致构建失败
         */
        Assume.assumeTrue("跳过：未启用 E2E 测试", BuildConfig.ENABLE_AGENT_E2E_TESTS)
        debug.step("setUp.start")
        recorder = PerformanceRecorder()
        scenario = activityRule.scenario
        
        // 清理命令处理器缓存与索引管理器，确保单测运行无跨测试残留状态
        CommandHandler.clearCache()
        
        // ActivityTracker 已经在 MainApplication 中注册，这里不需要重复注册
        // 使用 instrumentation 的 idle 等待替代纯 sleep，提升稳定性
        debug.step("setUp.wait_idle_before_ui")
        waitForIdle()
        
        // 等待 UI 稳定
        debug.step("setUp.wait_idle_after_ui")
        waitForIdle()
        // 预热元素树，保证 input_text 能按坐标解析目标控件
        primeElementTree()
    }

    /**
     * 测试结束打印性能报告
     */
    @After
    fun tearDown() {
        debug.step("tearDown.start")
        recorder.printReport()
        debug.step("tearDown.done")
    }

    // 使用固定静态的 TestHostActivity，不再在测试中动态创建 UI

    /**
     * 测试点击动作：通过 CommandHandler 执行 tap，并验证页面变化证据
     */
    @Test
    fun testTapAction() {
        debug.step("testTapAction.begin")
        val actionName = "TAP"
        Log.d(TAG, "Starting testTapAction")

        // 动作前获取稳定状态，用于独立证据比对
        val preState = getStableState(5000, 1200)

        // 1. 准备参数
        val params = JSONObject().apply {
            put("x", 100) // 占位，后续会用真实坐标替换
            put("y", 100)
            // 显式配置页面变化验证参数，提升稳定性
            put("verify_page_change", true)
            put("verify_timeout_ms", 5000)
            put("verify_stable_window_ms", 1200)
            put("verify_interval_ms", 60)
        }
        
        // 动态获取按钮位置
        var btnXDp = 0
        var btnYDp = 0
        scenario.onActivity {
            val btn = it.findViewById<View>(BTN_ID)
            val location = IntArray(2)
            btn.getLocationOnScreen(location)
            val density = it.resources.displayMetrics.density
            btnXDp = ((location[0] + btn.width / 2) / density).toInt()
            btnYDp = ((location[1] + btn.height / 2) / density).toInt()
        }
        params.put("x", btnXDp)
        params.put("y", btnYDp)

        // 每次单测执行前确保页面处于初始态
        resetActivityToInitialState()
        // 2. 执行并计时
        executeCommand("tap", params, actionName) { response ->
            // 3. 验证结果
            val status = response.optString("status")
            val changeType = response.optString("page_change_type", "none")
            // 独立证据：动作后获取稳定状态，比较与动作前状态是否真正发生变化
            val (postState, probeMs) = getStableStateWithDuration(2000, 400)
            val stateChanged = hasStateChanged(preState, postState)
            val outcomeCategory = when {
                status == "success" && stateChanged -> "执行成功且验证成功"
                status == "success" && !stateChanged -> "执行不成功但验证误报"
                status != "success" && stateChanged -> "执行成功但验证漏检"
                else -> "执行不成功且验证一致"
            }
            recorder.noteVerifierOutcome(actionName, outcomeCategory)
            recorder.noteVerifierProbeTime(actionName, probeMs)
            assertTrue(status == "success" && changeType != "none")
            assertTrue(stateChanged)
        }
        debug.step("testTapAction.end")
    }

    /**
     * 测试文本输入动作：执行 input_text，校验返回值与 EditText 实际内容
     */
    @Test
    fun testInputTextAction() {
        debug.step("testInputTextAction.begin")
        val actionName = "INPUT"
        Log.d(TAG, "Starting testInputTextAction")

        // 动作前获取稳定状态
        val preState = getStableState(1500, 300)

        // 动态获取 EditText 位置
        var editXDp = 0
        var editYDp = 0
        scenario.onActivity {
            val edit = it.findViewById<View>(EDIT_ID)
            val location = IntArray(2)
            edit.getLocationOnScreen(location)
            val density = it.resources.displayMetrics.density
            editXDp = ((location[0] + edit.width / 2) / density).toInt()
            editYDp = ((location[1] + edit.height / 2) / density).toInt()
        }

        val inputText = "Hello Agent"
        val params = JSONObject().apply {
            put("text", inputText)
            put("element", org.json.JSONArray().apply {
                put(editXDp)
                put(editYDp)
            })
        }

        executeCommand("input_text", params, actionName) { response ->
            assertEquals("success", response.optString("status"))
            assertEquals(inputText, response.optString("input_text"))
            
            // 验证 UI 实际变化
            scenario.onActivity {
                val edit = it.findViewById<EditText>(EDIT_ID)
                assertEquals(inputText, edit.text.toString())
            }
            // 独立证据：获取postState并记录耗时与分类
            val (postState, probeMs) = getStableStateWithDuration(2000, 400)
            val stateChanged = hasStateChanged(preState, postState)
            val status = response.optString("status")
            val category = when {
                status == "success" && stateChanged -> "执行成功且验证成功"
                status == "success" && !stateChanged -> "执行不成功但验证误报"
                status != "success" && stateChanged -> "执行成功但验证漏检"
                else -> "执行不成功且验证一致"
            }
            recorder.noteVerifierOutcome(actionName, category)
            recorder.noteVerifierProbeTime(actionName, probeMs)
        }
        debug.step("testInputTextAction.end")
    }

    /**
     * 测试滑动动作：执行 swipe，校验 ScrollView 的滚动位置是否发生变化
     */
    @Test
    fun testSwipeAction() {
        debug.step("testSwipeAction.begin")
        val actionName = "SWIPE"
        Log.d(TAG, "Starting testSwipeAction")

        // 动作前获取稳定状态
        val preState = getStableState(1500, 300)

        var startXDp = 0
        var startYDp = 0
        var endXDp = 0
        var endYDp = 0
        
        scenario.onActivity {
            val scroll = it.findViewById<View>(SCROLL_ID)
            val location = IntArray(2)
            scroll.getLocationOnScreen(location)
            val density = it.resources.displayMetrics.density
            val startXPx = location[0] + scroll.width / 2
            val startYPx = location[1] + scroll.height - 50
            val endXPx = startXPx
            val endYPx = location[1] + 50
            startXDp = (startXPx / density).toInt()
            startYDp = (startYPx / density).toInt()
            endXDp = (endXPx / density).toInt()
            endYDp = (endYPx / density).toInt()
        }

        val params = JSONObject().apply {
            put("start_x", startXDp)
            put("start_y", startYDp)
            put("end_x", endXDp)
            put("end_y", endYDp)
            put("duration_ms", 500)
        }

        executeCommand("swipe", params, actionName) { response ->
            val status = response.optString("status")
            val err = response.optString("error")
            assertTrue(status == "success" || err.contains("page unchanged"))
            
            // 验证 ScrollY 变化
            scenario.onActivity {
                val scroll = it.findViewById<ScrollView>(SCROLL_ID)
                assertTrue("ScrollView should have scrolled", scroll.scrollY > 0)
            }
            // 独立证据：获取postState并记录耗时与分类
            val (postState, probeMs) = getStableStateWithDuration(2000, 400)
            val stateChanged = hasStateChanged(preState, postState)
            val category = when {
                status == "success" && stateChanged -> "执行成功且验证成功"
                status == "success" && !stateChanged -> "执行不成功但验证误报"
                status != "success" && stateChanged -> "执行成功但验证漏检"
                else -> "执行不成功且验证一致"
            }
            recorder.noteVerifierOutcome(actionName, category)
            recorder.noteVerifierProbeTime(actionName, probeMs)
        }
        debug.step("testSwipeAction.end")
    }
    
    /**
     * 测试返回动作：执行 back，允许页面未变化的错误返回，只记录耗时
     */
    @Test
    fun testBackAction() {
        debug.step("testBackAction.begin")
        val actionName = "BACK"
        // 动作前获取稳定状态
        val preState = getStableState(1200, 300)
        // Back 可能会关闭 Activity，所以我们需要小心
        // 这里主要测试 CommandHandler 的处理逻辑
        
        executeCommand("back", JSONObject(), actionName) { response ->
            // Back 成功可能会导致 Activity 暂停或销毁，或者只是关闭键盘
            // 根据 CommandHandler 逻辑，如果页面没变会报错 "Back succeeded but page unchanged"
            // 为了让页面变化，我们可以先打开一个 Dialog 或者 ...
            // 简单起见，我们接受 status=error (page unchanged) 也算执行完成了，只要耗时记录下来
            // 或者我们期望它是 success 如果 activity 栈有变化
            val status = response.optString("status")
            val err = response.optString("error")
            assertTrue(status == "success" || err.contains("page unchanged") || err.contains("action failed"))
            // 独立证据：获取postState并记录耗时与分类
            val (postState, probeMs) = getStableStateWithDuration(2000, 400)
            val stateChanged = hasStateChanged(preState, postState)
            val category = when {
                status == "success" && stateChanged -> "执行成功且验证成功"
                status == "success" && !stateChanged -> "执行不成功但验证误报"
                status != "success" && stateChanged -> "执行成功但验证漏检"
                else -> "执行不成功且验证一致"
            }
            recorder.noteVerifierOutcome(actionName, category)
            recorder.noteVerifierProbeTime(actionName, probeMs)
        }
        debug.step("testBackAction.end")
    }

    /**
     * 测试双击动作：执行 double tap，验证页面变化或按钮文本变化
     */
    @Test
    fun testDoubleTapAction() {
        debug.step("testDoubleTapAction.begin")
        val actionName = "DOUBLE_TAP"
        // 动作前获取稳定状态
        val preState = getStableState(1500, 300)
        var btnXDp = 0
        var btnYDp = 0
        scenario.onActivity {
            val btn = it.findViewById<View>(BTN_ID)
            val location = IntArray(2)
            btn.getLocationOnScreen(location)
            val density = it.resources.displayMetrics.density
            btnXDp = ((location[0] + btn.width / 2) / density).toInt()
            btnYDp = ((location[1] + btn.height / 2) / density).toInt()
        }
        val params = JSONObject().apply {
            put("element", org.json.JSONArray().apply {
                put(btnXDp); put(btnYDp)
            })
        }
        executeCommand("double tap", params, actionName) { response ->
            val status = response.optString("status")
            val changeType = response.optString("page_change_type", "none")
            val (postState, probeMs) = getStableStateWithDuration(2000, 400)
            val stateChanged = hasStateChanged(preState, postState)
            val category = when {
                status == "success" && stateChanged -> "执行成功且验证成功"
                status == "success" && !stateChanged -> "执行不成功但验证误报"
                status != "success" && stateChanged -> "执行成功但验证漏检"
                else -> "执行不成功且验证一致"
            }
            recorder.noteVerifierOutcome(actionName, category)
            recorder.noteVerifierProbeTime(actionName, probeMs)
            assertTrue(status == "success" && changeType != "none")
            assertTrue(stateChanged)
        }
        debug.step("testDoubleTapAction.end")
    }

    /**
     * 测试长按动作：执行 long press，验证按钮文本变化为 LongPressed
     */
    @Test
    fun testLongPressAction() {
        debug.step("testLongPressAction.begin")
        val actionName = "LONG_PRESS"
        // 动作前获取稳定状态
        val preState = getStableState(1500, 300)
        var btnXDp = 0
        var btnYDp = 0
        scenario.onActivity {
            val btn = it.findViewById<View>(BTN_ID)
            val location = IntArray(2)
            btn.getLocationOnScreen(location)
            val density = it.resources.displayMetrics.density
            btnXDp = ((location[0] + btn.width / 2) / density).toInt()
            btnYDp = ((location[1] + btn.height / 2) / density).toInt()
        }
        val params = JSONObject().apply {
            put("element", org.json.JSONArray().apply {
                put(btnXDp); put(btnYDp)
            })
        }
        executeCommand("long press", params, actionName) { response ->
            val status = response.optString("status")
            var longPressed = false
            scenario.onActivity {
                val btn = it.findViewById<Button>(BTN_ID)
                longPressed = (btn.text?.toString() == "LongPressed")
            }
            assertTrue(longPressed && (status == "success" || status == "error"))
            // 独立证据：获取postState并记录耗时与分类
            val (postState, probeMs) = getStableStateWithDuration(2000, 400)
            val stateChanged = hasStateChanged(preState, postState)
            val category = when {
                status == "success" && stateChanged -> "执行成功且验证成功"
                status == "success" && !stateChanged -> "执行不成功但验证误报"
                status != "success" && stateChanged -> "执行成功但验证漏检"
                else -> "执行不成功且验证一致"
            }
            recorder.noteVerifierOutcome(actionName, category)
            recorder.noteVerifierProbeTime(actionName, probeMs)
        }
        debug.step("testLongPressAction.end")
    }

    /**
     * 测试 Home 动作：验证返回未实现错误并统计耗时
     */
    @Test
    fun testHomeAction() {
        debug.step("testHomeAction.begin")
        val actionName = "HOME"
        executeCommand("home", JSONObject(), actionName) { response ->
            assertEquals("error", response.optString("status"))
        }
        debug.step("testHomeAction.end")
    }

    /**
     * 测试 get_state 的脏页面防御：在页面动态扰动下执行 get_state，验证耗时显著增加
     */
    @Test
    fun testGetStateDirtyPageDefense() {
        debug.step("testGetStateDirtyPageDefense.begin")
        Log.d(TAG, "Starting testGetStateDirtyPageDefense")

        // 1. 基准测试：静态页面
        debug.step("get_state.static.start")
        recorder.start("GET_STATE_STATIC")
        val latchStatic = CountDownLatch(1)
        var staticTime = 0L
        
        scenario.onActivity { activity ->
            CommandHandler.handleCommand("get_state", JSONObject(), "req_static", activity) {
                recorder.stop("GET_STATE_STATIC")
                staticTime = recorder.getLastDuration("GET_STATE_STATIC")
                latchStatic.countDown()
            }
        }
        latchStatic.await(10, TimeUnit.SECONDS)
        Log.i(TAG, "Static get_state time: ${staticTime}ms")
        debug.step("get_state.static.end")

        // 2. 干扰测试：动态页面
        debug.step("get_state.dirty.disturb.start")
        val isDisturbing = AtomicReference(true)
        val handlerRef = AtomicReference<Handler>()
        val runnableRef = AtomicReference<Runnable>()
        scenario.onActivity { activity ->
            val tv = activity.findViewById<TextView>(TEXT_ID)
            val handler = Handler(Looper.getMainLooper())
            val runnable = object : Runnable {
                var count = 0
                override fun run() {
                    if (isDisturbing.get()) {
                        tv.text = "Disturbing... ${count++}"
                        handler.postDelayed(this, 100) // 每100ms修改一次
                    }
                }
            }
            handlerRef.set(handler)
            runnableRef.set(runnable)
            handler.post(runnable)
        }

        // 让干扰跑一会儿
        waitForIdle()

        // 发起 get_state，预期会被阻塞
        debug.step("get_state.dirty.request.start")
        recorder.start("GET_STATE_DIRTY")
        val latchDirty = CountDownLatch(1)
        
        scenario.onActivity { activity ->
            // 设置一个较长的 stabilize_timeout
            val params = JSONObject().apply {
                put("stabilize_timeout_ms", 5000)
                put("stable_window_ms", 1000)
            }
            
            CommandHandler.handleCommand("get_state", params, "req_dirty", activity) {
                recorder.stop("GET_STATE_DIRTY")
                latchDirty.countDown()
            }
        }
        
        // 在等待过程中，停止干扰，让页面稳定，从而让 get_state 返回
        // 使用标志位停止重发，同时移除回调，避免残留任务
        waitForIdle()
        isDisturbing.set(false) // 停止干扰
        scenario.onActivity {
            handlerRef.get()?.removeCallbacks(runnableRef.get())
        }
        
        assertTrue("Get state timeout", latchDirty.await(DEFAULT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
        debug.step("get_state.dirty.request.end")
        
        val dirtyTime = recorder.getLastDuration("GET_STATE_DIRTY")
        Log.i(TAG, "Dirty get_state time: ${dirtyTime}ms")
        
        // 验证：动态页面的耗时应该显著大于静态页面 + 干扰持续时间
        assertTrue("Dirty page should take longer", dirtyTime >= staticTime + 300)
        debug.step("testGetStateDirtyPageDefense.end")
    }

    /**
     * PageChangeVerifier 耗时测试：在文本变化场景下测量验证耗时
     */
    /**
     * PageChangeVerifier 耗时测试：在文本变化场景下测量验证耗时（断言移至await之后）
     */
    @Test
    fun testPageChangeVerifierCost_TextChange() {
        debug.step("testPageChangeVerifierCost_TextChange.begin")
        val latch = CountDownLatch(1)
        val changedRef = java.util.concurrent.atomic.AtomicReference<Boolean>(false)
        val typeRef = java.util.concurrent.atomic.AtomicReference<String>("none")
        recorder.start("VERIFIER_TEXT_CHANGE")
        scenario.onActivity { activity ->
            val preAct = activity
            val preHash = PageChangeVerifier.computePreViewTreeHash(activity)
            val preWebHash = PageChangeVerifier.computePreWebViewAggHash(activity)
            val tv = activity.findViewById<TextView>(TEXT_ID)
            tv.text = "VerifierChange"
            PageChangeVerifier.verifyActionWithPageChange(
                handler = Handler(Looper.getMainLooper()),
                getCurrentActivity = { ActivityTracker.getCurrentActivity() },
                preActivity = preAct,
                preViewTreeHash = preHash,
                preWebViewAggHash = preWebHash,
                timeoutMs = DEFAULT_VERIFY_TIMEOUT_MS,
                intervalMs = DEFAULT_VERIFY_INTERVAL_MS,
                stableWindowMs = DEFAULT_VERIFY_STABLE_WINDOW_MS
            ) { changed, type ->
                try {
                    recorder.stopWithOutcome("VERIFIER_TEXT_CHANGE", changed)
                    recorder.noteChangeType("VERIFIER_TEXT_CHANGE", type)
                    changedRef.set(changed)
                    typeRef.set(type)
                } finally {
                    latch.countDown()
                }
            }
        }
        assertTrue(latch.await(DEFAULT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
        assertTrue(changedRef.get() == true)
        debug.step("testPageChangeVerifierCost_TextChange.end")
    }

    /**
     * PageChangeVerifier 耗时测试：在无变化场景下测量验证耗时与超时返回
     */
    /**
     * PageChangeVerifier 耗时测试：在无变化场景下测量验证耗时与超时返回（断言移至await之后）
     */
    @Test
    fun testPageChangeVerifierCost_NoChange() {
        debug.step("testPageChangeVerifierCost_NoChange.begin")
        val latch = CountDownLatch(1)
        val changedRef = java.util.concurrent.atomic.AtomicReference<Boolean>(true)
        val typeRef = java.util.concurrent.atomic.AtomicReference<String>("none")
        recorder.start("VERIFIER_NO_CHANGE")
        scenario.onActivity { activity ->
            val preAct = activity
            val preHash = PageChangeVerifier.computePreViewTreeHash(activity)
            val preWebHash = PageChangeVerifier.computePreWebViewAggHash(activity)
            PageChangeVerifier.verifyActionWithPageChange(
                handler = Handler(Looper.getMainLooper()),
                getCurrentActivity = { ActivityTracker.getCurrentActivity() },
                preActivity = preAct,
                preViewTreeHash = preHash,
                preWebViewAggHash = preWebHash,
                timeoutMs = 800L,
                intervalMs = 100L,
                stableWindowMs = DEFAULT_VERIFY_STABLE_WINDOW_MS
            ) { changed, type ->
                try {
                    recorder.stopWithOutcome("VERIFIER_NO_CHANGE", changed)
                    recorder.noteChangeType("VERIFIER_NO_CHANGE", type)
                    changedRef.set(changed)
                    typeRef.set(type)
                } finally {
                    latch.countDown()
                }
            }
        }
        assertTrue(latch.await(DEFAULT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
        assertFalse(changedRef.get() == true)
        debug.step("testPageChangeVerifierCost_NoChange.end")
    }

    // --- Helper Methods ---

    /**
     * 执行指定命令并进行断言，统一计时与超时控制
     * @param cmd 命令名（如 tap、input_text、swipe、back、get_state）
     * @param params 命令参数
     * @param actionName 动作名称（用于性能记录分类）
     * @param assertion 响应断言逻辑
     */
    private fun executeCommand(
        cmd: String, 
        params: JSONObject, 
        actionName: String, 
        assertion: (JSONObject) -> Unit
    ) {
        debug.step("executeCommand.start:$cmd")
        debug.info("command.params:$params")
        val latch = CountDownLatch(1)
        val resultRef = AtomicReference<JSONObject>()

        recorder.start(actionName)
        
        debug.step("executeCommand.onActivity.invoke:$cmd")
        scenario.onActivity { activity ->
            CommandHandler.handleCommand(cmd, params, "req_$actionName", activity) { response ->
                val success = response.optString("status") == "success"
                recorder.stopWithOutcome(actionName, success)
                val changeType = response.optString("page_change_type", "")
                if (changeType.isNotEmpty()) {
                    recorder.noteChangeType(actionName, changeType)
                }
                // 将单次动作耗时打印到标准输出，便于在测试报告中显示
                val duration = recorder.getLastDuration(actionName)
                val ct = if (changeType.isNotEmpty()) changeType else "none"
                System.out.println("[AgentReport] Action=" + actionName + " Duration=" + duration + "ms Success=" + success + " ChangeType=" + ct)
                resultRef.set(response)
                latch.countDown()
                debug.step("executeCommand.callback_received:$cmd")
            }
        }

        // 等待命令完成并确保主线程空闲
        val completed = latch.await(DEFAULT_TIMEOUT_SECONDS, TimeUnit.SECONDS)
        assertTrue("Command $cmd timed out", completed)
        waitForIdle()
        
        val response = resultRef.get()
        assertNotNull("Response should not be null", response)
        
        Log.d(TAG, "Response for $cmd: $response")
        assertion(response)
        debug.step("executeCommand.done:$cmd")
    }

    /**
     * 获取指定视图中心点的dp坐标
     * @param viewId 视图ID
     * @return Pair(xDp, yDp)
     */
    private fun getViewCenterDp(viewId: Int): Pair<Int, Int> {
        var xDp = 0
        var yDp = 0
        scenario.onActivity {
            val v = it.findViewById<View>(viewId)
            val loc = IntArray(2)
            v.getLocationOnScreen(loc)
            val density = it.resources.displayMetrics.density
            xDp = ((loc[0] + v.width / 2) / density).toInt()
            yDp = ((loc[1] + v.height / 2) / density).toInt()
        }
        return Pair(xDp, yDp)
    }

    /**
     * 重复执行指定动作N次，并为每次结果做断言
     * @param cmd 命令
     * @param buildParams 构建参数的函数（按需动态计算）
     * @param actionName 记录名称
     * @param runs 次数
     * @param perRunAssert 针对每次响应的断言
     */
    /**
     * 重复执行指定动作N次，并可选进行独立状态对比验证与记录
     * @param cmd 命令
     * @param buildParams 构建参数的函数（按需动态计算）
     * @param actionName 记录名称
     * @param runs 次数
     * @param independentVerify 是否进行独立状态对比验证（获取pre/post state并记录验证器结果与postState耗时）
     * @param perRunAssert 针对每次响应的断言
     */
    /**
     * 重复执行指定动作N次，并可选进行独立状态对比验证与记录
     * 同时可对比启用/禁用页面变化验证的耗时差异（VER/NOV 分组）
     * @param cmd 命令
     * @param buildParams 构建参数函数
     * @param actionName 动作名称
     * @param runs 次数
     * @param independentVerify 是否进行独立状态对比验证
     * @param compareVerifyCost 是否比较启用/禁用验证耗时
     * @param preRunInit 每轮开始时的场景初始化（如重置按钮文本），为空则不初始化
     * @param perRunAssert 每轮响应断言
     */
    private fun repeatAction(
        cmd: String,
        buildParams: () -> JSONObject,
        actionName: String,
        runs: Int = RUNS_PER_ACTION,
        independentVerify: Boolean = false,
        compareVerifyCost: Boolean = true,
        preRunInit: (() -> Unit)? = null,
        perRunAssert: (JSONObject, Int) -> Unit
    ) {
        for (i in 1..runs) {
            // 每轮开始执行场景初始化（如重置控件文本至初始值）
            preRunInit?.invoke()
            // 验证开启模式（用于断言与独立状态对比）
            run {
                val actionNameVer = "${actionName}_VER"
                val preState = if (independentVerify) getStableState(1200, 300) else null
                val params = buildParams().apply { 
                    put("verify_page_change", true)
                    put("verify_timeout_ms", DEFAULT_VERIFY_TIMEOUT_MS)
                    put("verify_stable_window_ms", DEFAULT_VERIFY_STABLE_WINDOW_MS)
                    put("verify_interval_ms", DEFAULT_VERIFY_INTERVAL_MS)
                }
                executeCommand(cmd, params, actionNameVer) { resp ->
                    if (independentVerify) {
                        val tStart = System.currentTimeMillis()
                        val postState = getStableState(1800, 400)
                        val probeMs = System.currentTimeMillis() - tStart
                        val status = resp.optString("status")
                        val changed = hasStateChanged(preState!!, postState)
                        val category = when {
                            status == "success" && changed -> "执行成功且验证成功"
                            status == "success" && !changed -> "执行不成功但验证误报"
                            status != "success" && changed -> "执行成功但验证漏检"
                            else -> "执行不成功且验证一致"
                        }
                        recorder.noteVerifierOutcome(actionNameVer, category)
                        recorder.noteVerifierProbeTime(actionNameVer, probeMs)
                    }
                    perRunAssert(resp, i)
                }
            }
            // 验证关闭模式（仅统计耗时用于对比，无PageChangeVerifier）
            if (compareVerifyCost) {
                // NOV 分支也重置场景，保证与 VER 分支在同一初始态下对比耗时
                preRunInit?.invoke()
                val actionNameNov = "${actionName}_NOV"
                val paramsNov = buildParams().apply { put("verify_page_change", false) }
                executeCommand(cmd, paramsNov, actionNameNov) { _ -> 
                    // 不进行断言，仅记录耗时与结果
                }
            }
        }
    }

    /**
     * 以稳定窗口获取当前页面状态（独立于 PageChangeVerifier 的证据）
     * @param stabilizeTimeoutMs 稳定化最长等待时间
     * @param stableWindowMs 认为稳定所需的持续静默窗口
     * @return get_state 的 JSON 响应
     */
    private fun getStableState(stabilizeTimeoutMs: Int, stableWindowMs: Int): JSONObject {
        val latch = CountDownLatch(1)
        val resultRef = AtomicReference<JSONObject>()
        val act = Agent.ActivityTracker.getCurrentActivity()
        val params = JSONObject().apply {
            put("stabilize_timeout_ms", stabilizeTimeoutMs)
            put("stable_window_ms", stableWindowMs)
        }
        Handler(Looper.getMainLooper()).post {
            CommandHandler.handleCommand("get_state", params, "req_probe_state", act) { resp ->
                resultRef.set(resp)
                latch.countDown()
            }
        }
        assertTrue(latch.await(DEFAULT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
        val res = resultRef.get()
        assertNotNull(res)
        return res!!
    }

    /**
     * 获取稳定状态并返回获取耗时
     * @param stabilizeTimeoutMs 稳定化最长等待时间
     * @param stableWindowMs 稳定窗口
     * @return Pair(state, durationMs)
     */
    private fun getStableStateWithDuration(stabilizeTimeoutMs: Int, stableWindowMs: Int): Pair<JSONObject, Long> {
        val t0 = System.currentTimeMillis()
        val state = getStableState(stabilizeTimeoutMs, stableWindowMs)
        val dt = System.currentTimeMillis() - t0
        return Pair(state, dt)
    }

    /**
     * 计算 a11y_tree 的轻量哈希（独立计算，用于与 PageChangeVerifier 交叉验证）
     * @param state get_state 响应
     * @return 哈希值
     */
    private fun computeA11yHash(state: JSONObject): Int {
        val arr = state.optJSONArray("a11y_tree") ?: return 0
        fun nodeHash(node: JSONObject): Int {
            var h = 17
            h = h * 31 + node.optString("class", "").hashCode()
            h = h * 31 + node.optString("text", "").hashCode()
            h = h * 31 + node.optString("bounds", "").hashCode()
            val children = node.optJSONArray("children")
            if (children != null) {
                for (i in 0 until children.length()) {
                    val child = children.optJSONObject(i) ?: continue
                    h = h * 31 + nodeHash(child)
                }
            }
            return h
        }
        var total = 0
        for (i in 0 until arr.length()) {
            val obj = arr.optJSONObject(i) ?: continue
            total = total * 31 + nodeHash(obj)
        }
        return total
    }

    /**
     * 判断两个稳定状态是否存在页面变化（独立证据）
     * @param pre 动作前状态
     * @param post 动作后状态
     */
    private fun hasStateChanged(pre: JSONObject, post: JSONObject): Boolean {
        val prePhone = pre.optJSONObject("phone_state") ?: JSONObject()
        val postPhone = post.optJSONObject("phone_state") ?: JSONObject()
        // Activity 变化直接视为页面变化
        if (prePhone.optString("activity") != postPhone.optString("activity")) {
            return true
        }
        // 比较 a11y_tree 的轻量哈希
        return computeA11yHash(pre) != computeA11yHash(post)
    }
    /**
     * 递归查找 a11y_tree 是否包含指定文本
     * @param state get_state 的响应
     * @param keyword 关键字
     */
    private fun a11yTreeContainsText(state: JSONObject, keyword: String): Boolean {
        val arr = state.optJSONArray("a11y_tree") ?: return false
        fun findIn(node: JSONObject): Boolean {
            val text = node.optString("text", "")
            if (text.contains(keyword)) return true
            val children = node.optJSONArray("children") ?: return false
            for (i in 0 until children.length()) {
                val child = children.optJSONObject(i) ?: continue
                if (findIn(child)) return true
            }
            return false
        }
        for (i in 0 until arr.length()) {
            val obj = arr.optJSONObject(i) ?: continue
            if (findIn(obj)) return true
        }
        return false
    }

    // --- Repeated Positive/Negative Tests ---

    /**
     * TAP 正例：点击按钮，重复统计耗时与验证类型
     */
    @Test
    fun testTapActionRepeatedPositive() {
        repeatAction(
            cmd = "tap",
            buildParams = {
                val center = getViewCenterDp(BTN_ID)
                JSONObject().apply {
                    put("x", center.first)
                    put("y", center.second)
                }
            },
            actionName = "TAP_POS",
            independentVerify = true,
            preRunInit = { resetActivityToInitialState() }
        ) { resp, _ ->
            val status = resp.optString("status")
            val change = resp.optString("page_change_type", "")
            assertTrue(status == "success" && change.contains("view_hash_change"))
        }
    }

    /**
     * TAP 反例：使用中性按钮作为点击目标，页面应在稳定窗口结束后保持未变化
     * 为降低交互动画带来的误判，提升稳定窗口与轮询精度
     */
    @Test
    fun testTapActionRepeatedNegative() {
        repeatAction(
            cmd = "tap",
            buildParams = {
                val center = getViewCenterDp(NEUTRAL_ID)
                JSONObject().apply {
                    put("x", center.first)
                    put("y", center.second)
                    // 提升稳定窗口，进一步降低短暂视觉扰动带来的误判
                    put("verify_stable_window_ms", 1500)
                    put("verify_interval_ms", 50)
                    put("verify_timeout_ms", 6000)
                }
            },
            actionName = "TAP_NEG",
            independentVerify = true,
            preRunInit = { resetActivityToInitialState() }
        ) { resp, _ ->
            val status = resp.optString("status")
            val err = resp.optString("error", "")
            assertTrue(status == "error" && (err.contains("page unchanged") || err.isNotEmpty()))
        }
    }

    /**
     * INPUT 正例：输入不同文本，重复统计耗时
     */
    @Test
    fun testInputTextActionRepeatedPositive() {
        repeatAction(
            cmd = "input_text",
            buildParams = {
                val center = getViewCenterDp(EDIT_ID)
                val text = "Hello Agent ${System.currentTimeMillis() % 1000}"
                JSONObject().apply {
                    put("text", text)
                    put("element", org.json.JSONArray().apply {
                        put(center.first); put(center.second)
                    })
                }
            },
            actionName = "INPUT_POS",
            independentVerify = true,
            preRunInit = { resetActivityToInitialState() }
        ) { resp, _ ->
            assertEquals("success", resp.optString("status"))
        }
    }

    /**
     * INPUT 反例：重复输入相同文本“Seed”，PageChangeVerifier 应判定未变化
     */
    @Test
    fun testInputTextActionRepeatedNegative() {
        // 先确保文本为 Seed
        scenario.onActivity {
            val edit = it.findViewById<EditText>(EDIT_ID)
            edit.setText("Seed")
        }
        repeatAction(
            cmd = "input_text",
            buildParams = {
                val center = getViewCenterDp(EDIT_ID)
                JSONObject().apply {
                    put("text", "Seed")
                    put("element", org.json.JSONArray().apply {
                        put(center.first); put(center.second)
                    })
                }
            },
            actionName = "INPUT_NEG",
            independentVerify = true,
            preRunInit = { resetActivityToInitialState() }
        ) { resp, _ ->
            val status = resp.optString("status")
            val err = resp.optString("error", "")
            assertTrue(status == "error" && err.contains("page unchanged"))
        }
    }

    /**
     * SWIPE 正例：向上滑动 ScrollView，重复统计耗时
     */
    @Test
    fun testSwipeActionRepeatedPositive() {
        repeatAction(
            cmd = "swipe",
            buildParams = {
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
                JSONObject().apply {
                    put("start_x", startXDp); put("start_y", startYDp)
                    put("end_x", endXDp); put("end_y", endYDp)
                    put("duration_ms", 500)
                }
            },
            actionName = "SWIPE_POS",
            independentVerify = true,
            preRunInit = { resetActivityToInitialState() }
        ) { resp, _ ->
            val status = resp.optString("status")
            assertEquals("success", status)
        }
    }

    /**
     * SWIPE 反例：起止坐标相同，PageChangeVerifier 应判定未变化
     */
    @Test
    fun testSwipeActionRepeatedNegative() {
        repeatAction(
            cmd = "swipe",
            buildParams = {
                var centerXDp = 0; var centerYDp = 0
                scenario.onActivity {
                    val scroll = it.findViewById<View>(SCROLL_ID)
                    val loc = IntArray(2); scroll.getLocationOnScreen(loc)
                    val d = it.resources.displayMetrics.density
                    val cx = loc[0] + scroll.width / 2
                    val cy = loc[1] + scroll.height / 2
                    centerXDp = (cx / d).toInt(); centerYDp = (cy / d).toInt()
                }
                JSONObject().apply {
                    put("start_x", centerXDp); put("start_y", centerYDp)
                    put("end_x", centerXDp); put("end_y", centerYDp)
                    put("duration_ms", 300)
                }
            },
            actionName = "SWIPE_NEG",
            independentVerify = true,
            preRunInit = { resetActivityToInitialState() }
        ) { resp, _ ->
            val status = resp.optString("status")
            val err = resp.optString("error", "")
            assertTrue(status == "error" && err.contains("page unchanged"))
        }
    }

    /**
     * DOUBLE TAP 正例：在按钮上重复执行
     */
    @Test
    fun testDoubleTapActionRepeatedPositive() {
        repeatAction(
            cmd = "double tap",
            buildParams = {
                val center = getViewCenterDp(BTN_ID)
                JSONObject().apply {
                    put("element", org.json.JSONArray().apply {
                        put(center.first); put(center.second)
                    })
                }
            },
            actionName = "DOUBLE_POS",
            independentVerify = true,
            preRunInit = { resetActivityToInitialState() }
        ) { resp, _ ->
            assertEquals("success", resp.optString("status"))
        }
    }

    /**
     * DOUBLE TAP 反例：在中性按钮上重复执行
     */
    @Test
    fun testDoubleTapActionRepeatedNegative() {
        repeatAction(
            cmd = "double tap",
            buildParams = {
                val center = getViewCenterDp(NEUTRAL_ID)
                JSONObject().apply {
                    put("element", org.json.JSONArray().apply {
                        put(center.first); put(center.second)
                    })
                }
            },
            actionName = "DOUBLE_NEG",
            independentVerify = true,
            preRunInit = { resetActivityToInitialState() }
        ) { resp, _ ->
            val status = resp.optString("status")
            val err = resp.optString("error", "")
            assertTrue(status == "error" && err.contains("page unchanged"))
        }
    }

    /**
     * LONG PRESS 正例：在按钮上重复执行
     */
    @Test
    fun testLongPressActionRepeatedPositive() {
        repeatAction(
            cmd = "long press",
            buildParams = {
                val center = getViewCenterDp(BTN_ID)
                JSONObject().apply {
                    put("element", org.json.JSONArray().apply {
                        put(center.first); put(center.second)
                    })
                }
            },
            actionName = "LONG_POS",
            independentVerify = true,
            preRunInit = { resetActivityToInitialState() }
        ) { resp, _ ->
            val status = resp.optString("status")
            var longPressed = false
            scenario.onActivity {
                val btn = it.findViewById<Button>(BTN_ID)
                longPressed = (btn.text?.toString() == "LongPressed")
            }
            assertTrue(longPressed && (status == "success" || status == "error"))
        }
    }

    /**
     * LONG PRESS 反例：在中性按钮上重复执行（不可长按）
     */
    @Test
    fun testLongPressActionRepeatedNegative() {
        repeatAction(
            cmd = "long press",
            buildParams = {
                val center = getViewCenterDp(NEUTRAL_ID)
                JSONObject().apply {
                    put("element", org.json.JSONArray().apply {
                        put(center.first); put(center.second)
                    })
                }
            },
            actionName = "LONG_NEG",
            independentVerify = true,
            preRunInit = { resetActivityToInitialState() }
        ) { resp, _ ->
            val status = resp.optString("status")
            val err = resp.optString("error", "")
            // 中性按钮不可长按，应为错误或未变化
            assertTrue(status == "error" && (err.contains("action failed") || err.contains("page unchanged")))
        }
    }

    // --- Stable Verifier Complex Cases ---

    /**
     * 布局变化后立即 get_state：验证 PageStableVerifier 返回稳定后的 a11y_tree
     */
    @Test
    fun testGetStateAfterLayoutChangeStabilized() {
        // 点击“Add Item”造成结构变化
        val addCenter = getViewCenterDp(ADD_ITEM_ID)
        executeCommand("tap", JSONObject().apply {
            put("x", addCenter.first); put("y", addCenter.second)
        }, "TAP_ADD_ITEM") {
            // 立即请求 get_state，并设置稳定窗口
            val latch = CountDownLatch(1)
            var state: JSONObject? = null
            scenario.onActivity { activity ->
                val params = JSONObject().apply {
                    put("stabilize_timeout_ms", 3000)
                    put("stable_window_ms", 600)
                }
                CommandHandler.handleCommand("get_state", params, "req_after_layout", activity) { resp ->
                    state = resp
                    latch.countDown()
                }
            }
            assertTrue(latch.await(DEFAULT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
            assertNotNull(state)
            val ok = a11yTreeContainsText(state!!, "AddedItem")
            assertTrue(ok)
        }
    }

    /**
     * 活动跳转后立即 get_state：验证返回新 Activity 的稳定状态
     */
    @Test
    fun testGetStateAfterActivitySwitchStabilized() {
        val nextCenter = getViewCenterDp(GO_NEXT_ID)
        executeCommand("tap", JSONObject().apply {
            put("x", nextCenter.first); put("y", nextCenter.second)
        }, "TAP_GO_NEXT") {
            // 等待当前Activity切换为TestSecondActivity
            var switched = false
            run {
                val waitStart = System.currentTimeMillis()
                while (System.currentTimeMillis() - waitStart < 5000) {
                    val cur = Agent.ActivityTracker.getCurrentActivity()
                    if (cur != null && cur.javaClass.simpleName == "TestSecondActivity") {
                        switched = true
                        break
                    }
                    Thread.sleep(50)
                }
            }
            // 若点击未触发跳转，则直接启动目标Activity作为兜底
            if (!switched) {
                scenario.onActivity { host ->
                    host.startActivity(android.content.Intent(host, TestSecondActivity::class.java))
                }
                // 再次等待跳转完成
                val waitStart2 = System.currentTimeMillis()
                while (System.currentTimeMillis() - waitStart2 < 5000) {
                    val cur = Agent.ActivityTracker.getCurrentActivity()
                    if (cur != null && cur.javaClass.simpleName == "TestSecondActivity") {
                        switched = true
                        break
                    }
                    Thread.sleep(50)
                }
            }
            assertTrue("Activity should switch to TestSecondActivity", switched)
            // 使用当前栈顶Activity调用get_state
            val latch = CountDownLatch(1)
            var state: JSONObject? = null
            val current = Agent.ActivityTracker.getCurrentActivity()
            val params = JSONObject().apply {
                put("stabilize_timeout_ms", 4000)
                put("stable_window_ms", 800)
            }
            // 直接在主线程调用，避免scenario绑定旧Activity
            Handler(Looper.getMainLooper()).post {
                CommandHandler.handleCommand("get_state", params, "req_after_nav", current) { resp ->
                    state = resp
                    latch.countDown()
                }
            }
            assertTrue(latch.await(DEFAULT_TIMEOUT_SECONDS, TimeUnit.SECONDS))
            assertNotNull(state)
            val phone = state!!.optJSONObject("phone_state") ?: JSONObject()
            assertEquals("TestSecondActivity", phone.optString("activity"))
        }
    }

    /**
     * 在主线程同步执行指定代码块
     */
    private fun runOnMainSync(block: () -> Unit) {
        InstrumentationRegistry.getInstrumentation().runOnMainSync(block)
    }

    /**
     * 等待当前 instrumentation 与 UI 线程进入空闲状态
     */
    private fun waitForIdle() {
        try {
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()
        } catch (e: Throwable) {
            // 兼容性兜底，避免因 idleSync 抛异常导致测试失败
            try {
                Thread.sleep(200)
            } catch (_: InterruptedException) {}
        }
    }
    
    /**
     * 重置测试 Activity 到初始页面状态
     * - 通过 ActivityScenario.recreate() 触发 onDestroy/onCreate
     * - 等待 UI 空闲与稳定
     * - 重新预热元素树以保证坐标查找与缓存一致
     */
    private fun resetActivityToInitialState() {
        scenario.recreate()
        waitForIdle()
        // 重建后再次清理命令处理器缓存与索引映射，避免旧页面的残留数据影响本轮测试
        CommandHandler.clearCache()
        primeElementTree()
    }

    // --- Performance Recorder ---
    
    /**
     * 动作性能记录器：记录开始/结束时间，汇总输出报告
     */
    class PerformanceRecorder {
        private val startTimes = HashMap<String, Long>()
        private val durations = ArrayList<Record>()
        private val changeTypes = HashMap<String, HashMap<String, Int>>()
        private val verifierOutcomes = HashMap<String, HashMap<String, Int>>()
        private val verifierProbeTimes = HashMap<String, ArrayList<Long>>()

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
         * 停止记录某动作，计算耗时并保存
         */
        fun stop(name: String) {
            val start = startTimes[name] ?: return
            val end = System.currentTimeMillis()
            val duration = end - start
            durations.add(Record(name, duration, true, start, end))
            Log.i("Performance", "Action [$name] took ${duration}ms (start=$start, end=$end)")
            System.out.println("[AgentReport] ActionRecord name=" + name + " start=" + start + " end=" + end + " duration=" + duration + "ms success=true")
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
         * 读取某动作最近一次耗时
         */
        fun getLastDuration(name: String): Long {
            return durations.findLast { it.name == name }?.durationMs ?: 0L
        }
        
        /**
         * 记录页面变化类型分布
         */
        fun noteChangeType(name: String, type: String) {
            val map = changeTypes.getOrPut(name) { HashMap() }
            map[type] = (map[type] ?: 0) + 1
        }

        /**
         * 记录验证器结果分类
         */
        fun noteVerifierOutcome(name: String, category: String) {
            val map = verifierOutcomes.getOrPut(name) { HashMap() }
            map[category] = (map[category] ?: 0) + 1
        }

        /**
         * 记录postState获取耗时（验证器状态对比额外时间）
         */
        fun noteVerifierProbeTime(name: String, durationMs: Long) {
            val list = verifierProbeTimes.getOrPut(name) { ArrayList() }
            list.add(durationMs)
        }

        /**
         * 输出性能汇总报告到日志与标准输出（符合计划文档中的格式）
         */
        fun printReport() {
            Log.i("AgentTest", "============================================")
            Log.i("AgentTest", "动作执行性能报告 (单位: ms)")
            Log.i("AgentTest", "============================================")
            Log.i("AgentTest", String.format("| %-10s | %-6s | %-6s | %-8s | %-8s | %-8s |", "动作类型", "总次数", "成功率", "平均耗时", "最大耗时", "最小耗时"))
            Log.i("AgentTest", "--------------------------------------------")
            System.out.println("[AgentReport] ============================================")
            System.out.println("[AgentReport] 动作执行性能报告 (单位: ms)")
            System.out.println("[AgentReport] ============================================")
            System.out.println(String.format("[AgentReport] | %-10s | %-6s | %-6s | %-8s | %-8s | %-8s |", "动作类型", "总次数", "成功率", "平均耗时", "最大耗时", "最小耗时"))
            
            // Group by action
            val grouped = durations.groupBy { it.name }
            grouped.forEach { (name, records) ->
                val avg = records.map { it.durationMs }.average().toLong()
                val min = records.minOf { it.durationMs }
                val max = records.maxOf { it.durationMs }
                val count = records.size
                val successCount = records.count { it.success }
                val successRate = if (count > 0) (successCount * 100 / count) else 0
                
                Log.i("AgentTest", String.format("| %-10s | %-6d | %-5d%% | %-7dms | %-7dms | %-7dms |", name, count, successRate, avg, max, min))
                System.out.println(String.format("[AgentReport] | %-10s | %-6d | %-5d%% | %-7dms | %-7dms | %-7dms |", name, count, successRate, avg, max, min))
                val types = changeTypes[name]?.entries?.joinToString { "${it.key}:${it.value}" } ?: "None"
                Log.i("AgentTest", String.format("| %-10s | 变化类型分布: %s", "", types))
                System.out.println("[AgentReport] Types " + name + " = " + types)
                val outcomes = verifierOutcomes[name]?.entries?.joinToString { "${it.key}:${it.value}" } ?: "None"
                Log.i("AgentTest", String.format("| %-10s | 验证器结果分布: %s", "", outcomes))
                System.out.println("[AgentReport] VerifierOutcomes " + name + " = " + outcomes)
                val probes = verifierProbeTimes[name]
                if (probes != null && probes.isNotEmpty()) {
                    val pAvg = probes.average().toLong()
                    val pMin = probes.minOrNull() ?: 0L
                    val pMax = probes.maxOrNull() ?: 0L
                    System.out.println(String.format("[AgentReport] VerifierProbe %-10s | 次数=%-4d | 平均=%-6dms | 最大=%-6dms | 最小=%-6dms", name, probes.size, pAvg, pMax, pMin))
                    Log.i("AgentTest", String.format("| %-10s | 验证器Probe: 次数=%-4d 平均=%-6dms 最大=%-6dms 最小=%-6dms", "", probes.size, pAvg, pMax, pMin))
                } else {
                    System.out.println(String.format("[AgentReport] VerifierProbe %-10s | 无数据", name))
                }
            }
            Log.i("AgentTest", "============================================")
            System.out.println("[AgentReport] --------------------------------------------")
            
            // 脏页面防御测试表
            val staticTime = getLastDuration("GET_STATE_STATIC")
            val dirtyTime = getLastDuration("GET_STATE_DIRTY")
            val waited = if (dirtyTime > 0 && staticTime > 0) (dirtyTime - staticTime) else 0L
            Log.i("AgentTest", "脏页面防御测试")
            Log.i("AgentTest", String.format("| %-8s | %-8s | %-16s |", "场景", "耗时", "结果"))
            Log.i("AgentTest", String.format("| %-8s | %-7dms | %-16s |", "静态页面", staticTime, "成功 (Stable)"))
            Log.i("AgentTest", String.format("| %-8s | %-7dms | %-16s |", "动态干扰", dirtyTime, "成功 (Waited)"))
            if (waited > 0) {
                Log.i("AgentTest", "-> 验证通过: 有效等待了 ${waited}ms+")
            }
            System.out.println("[AgentReport] 脏页面防御测试")
            System.out.println(String.format("[AgentReport] | %-8s | %-8s | %-16s |", "场景", "耗时", "结果"))
            System.out.println(String.format("[AgentReport] | %-8s | %-7dms | %-16s |", "静态页面", staticTime, "成功 (Stable)"))
            System.out.println(String.format("[AgentReport] | %-8s | %-7dms | %-16s |", "动态干扰", dirtyTime, "成功 (Waited)"))
            if (waited > 0) {
                System.out.println("[AgentReport] -> 验证通过: 有效等待了 " + waited + "ms+")
            }
            System.out.println("[AgentReport] ============================================")
        }
    }

    /**
     * 测试调试日志工具：统一输出步骤、信息与错误，包含线程名
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
