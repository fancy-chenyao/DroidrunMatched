package com.example.emplab

import android.app.Application

class MainApplication : Application() {
    /**
     * 应用启动入口：输出启动日志，避免重复注册由ContentProvider自动完成的初始化
     */
    override fun onCreate() {
        super.onCreate()
        android.util.Log.i("MainApplication", "App started for instrumentation, sdk=${android.os.Build.VERSION.SDK_INT}")
    }
}
