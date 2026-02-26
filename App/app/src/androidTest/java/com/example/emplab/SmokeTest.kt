package com.example.emplab

import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * 冒烟测试：用于验证测试进程是否能正常启动并输出日志
 */
@RunWith(AndroidJUnit4::class)
class SmokeTest {
    /**
     * 简单断言与日志输出，若能看到日志则说明测试进程正常运行
     */
    @Test
    fun testRunnerIsAlive() {
        Log.i("SmokeTest", "Smoke test is running, pid=${android.os.Process.myPid()}")
        assertTrue(true)
    }
}
