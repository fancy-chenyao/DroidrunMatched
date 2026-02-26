package com.example.emplab

import android.app.Application
import android.content.Context
import android.util.Log
import androidx.test.runner.AndroidJUnitRunner

/**
 * 自定义测试Runner：在测试生命周期关键阶段输出日志，便于定位“未进入用例体”的问题
 */
class TestRunner : AndroidJUnitRunner() {
    /**
     * Runner创建阶段：记录SDK与进程信息
     */
    override fun onCreate(arguments: android.os.Bundle?) {
        Log.i("TestRunner", "onCreate: sdk=${android.os.Build.VERSION.SDK_INT}, args=$arguments, pid=${android.os.Process.myPid()}")
        super.onCreate(arguments)
    }

    /**
     * 应用创建阶段：记录目标Application类名，并调用父类创建
     */
    override fun newApplication(cl: ClassLoader?, className: String?, context: Context?): Application {
        Log.i("TestRunner", "newApplication: className=$className, context=$context")
        // 保持默认应用创建流程，不强制替换Application
        return super.newApplication(cl, className, context)
    }

    /**
     * 测试启动阶段：输出启动日志，确保在Logcat可见
     */
    override fun onStart() {
        Log.i("TestRunner", "onStart: Instrumentation starting, pid=${android.os.Process.myPid()}")
        try {
            super.onStart()
        } catch (e: Throwable) {
            Log.e("TestRunner", "onStart error: ${e.message}", e)
            throw e
        }
    }
}
