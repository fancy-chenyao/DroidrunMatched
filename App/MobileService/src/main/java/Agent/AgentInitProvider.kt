package Agent

import android.app.ActivityManager
import android.app.Application
import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.database.Cursor
import android.net.Uri
import android.os.Build
import android.util.Log

class AgentInitProvider : ContentProvider() {

    /**
     * Provider创建时的初始化入口
     * 在进程安装Provider阶段自动调用，注册ActivityTracker并按需自动启动MobileService
     * @return 初始化是否成功
     */
    override fun onCreate(): Boolean {
        return try {
            val ctx = context?.applicationContext ?: return false
            val app = ctx as Application
            ActivityTracker.register(app)
            if (isMainProcess(ctx) && shouldAutoStart(ctx)) {
                tryStartMobileService(ctx)
            }
            Log.i("AgentInitProvider", "Initialized: ActivityTracker registered, autoStart=${shouldAutoStart(ctx)}")
            true
        } catch (e: Exception) {
            Log.e("AgentInitProvider", "Initialization failed: ${e.message}")
            false
        }
    }

    /**
     * 查询方法占位实现
     * 初始化型Provider不提供数据访问能力
     */
    override fun query(
        uri: Uri,
        projection: Array<out String>?,
        selection: String?,
        selectionArgs: Array<out String>?,
        sortOrder: String?
    ): Cursor? = null

    /**
     * 返回MIME类型占位实现
     * 初始化型Provider不暴露数据类型
     */
    override fun getType(uri: Uri): String? = null

    /**
     * 插入方法占位实现
     * 初始化型Provider不支持插入操作
     */
    override fun insert(uri: Uri, values: ContentValues?): Uri? = null

    /**
     * 删除方法占位实现
     * 初始化型Provider不支持删除操作
     */
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0

    /**
     * 更新方法占位实现
     * 初始化型Provider不支持更新操作
     */
    override fun update(
        uri: Uri,
        values: ContentValues?,
        selection: String?,
        selectionArgs: Array<out String>?
    ): Int = 0

    /**
     * 判断当前是否为主进程
     * 避免在远程进程执行初始化或启动服务
     * @param context 上下文
     * @return 是否为主进程
     */
    private fun isMainProcess(context: Context): Boolean {
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val pid = android.os.Process.myPid()
        val processName = am.runningAppProcesses?.firstOrNull { it.pid == pid }?.processName
        return processName == context.packageName
    }

    /**
     * 读取应用清单的meta-data，判断是否自动启动服务
     * 支持宿主通过application节点覆盖该值
     * @param context 上下文
     * @return 是否自动启动服务
     */
    private fun shouldAutoStart(context: Context): Boolean {
        return try {
            val pm = context.packageManager
            val ai = pm.getApplicationInfo(context.packageName, PackageManager.GET_META_DATA)
            val md = ai.metaData
            md?.getBoolean("AgentAutoStart", true) ?: true
        } catch (_: Exception) {
            true
        }
    }

    /**
     * 在前台或后台安全地启动MobileService
     * Android O及以上使用startForegroundService，其余版本使用startService
     * @param context 上下文
     */
    private fun tryStartMobileService(context: Context) {
        try {
            val intent = Intent(context, MobileService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        } catch (e: Exception) {
            Log.e("AgentInitProvider", "Start service failed: ${e.message}")
        }
    }
}
