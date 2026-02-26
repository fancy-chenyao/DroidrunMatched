package Agent

import android.content.Context
import android.content.Intent
import android.graphics.PixelFormat
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.view.Gravity
import android.view.WindowManager
import android.widget.Toast

/**
 * Agent悬浮窗管理器
 * 负责管理Agent悬浮窗的显示、隐藏和交互
 * 支持指令发送和ask功能
 */
class AgentFloatingWindowManager(private val context: Context) {
    
    private var windowManager: WindowManager? = null
    private var floatingView: AgentFloatingView? = null
    private var isShowing = false
    
    /**
     * 显示悬浮窗
     */
    fun showFloatingWindow() {
        // 检查是否是Activity上下文，因为应用内悬浮窗需要Activity上下文
        if (context !is android.app.Activity) {
            AgentErrorHandler.handleFloatingWindowError(context, "应用内悬浮窗需要Activity上下文", null)
            return
        }
        
        if (isShowing) {
            Toast.makeText(context, "悬浮窗已显示", Toast.LENGTH_SHORT).show()
            return
        }
        
        try {
            // 获取WindowManager
            windowManager = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager

            // 创建悬浮窗视图
            createFloatingView()
            
            // 设置布局参数
            val layoutParams = createLayoutParams()
            // 为TYPE_APPLICATION设置正确的window token，避免BadTokenException
            val activity = (context as android.app.Activity)
            val token = activity.findViewById<android.view.View>(android.R.id.content)?.windowToken
                ?: activity.window?.decorView?.windowToken
            layoutParams.token = token
            
            // 若窗口尚未附着，延迟到下一帧再尝试添加，避免BadTokenException
            val root = activity.findViewById<android.view.View>(android.R.id.content)
            if (root != null && !root.isAttachedToWindow) {
                root.post { showFloatingWindow() }
                return
            }
            
            // 设置WindowManager和LayoutParams到FloatingView
            floatingView?.setWindowManager(windowManager!!, layoutParams)
            
            // 添加到窗口
            windowManager?.addView(floatingView, layoutParams)
            isShowing = true
            
            Toast.makeText(context, "悬浮窗已显示", Toast.LENGTH_SHORT).show()
            
        } catch (e: Exception) {
            AgentErrorHandler.handleFloatingWindowError(context, "悬浮窗显示失败: ${e.message}", e)
        }
    }
    
    /**
     * 隐藏悬浮窗
     */
    fun hideFloatingWindow() {
        if (!isShowing) return
        
        try {
            windowManager?.removeView(floatingView)
            isShowing = false
            Toast.makeText(context, "悬浮窗已隐藏", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            AgentErrorHandler.handleFloatingWindowError(context, "悬浮窗隐藏失败: ${e.message}", e)
        }
    }
    
    /**
     * 切换悬浮窗显示状态
     */
    fun toggleFloatingWindow() {
        if (isShowing) {
            hideFloatingWindow()
        } else {
            showFloatingWindow()
        }
    }
    

    
    /**
     * 创建悬浮窗视图
     */
    private fun createFloatingView() {
        floatingView = AgentFloatingView(context)
        // 设置发送命令回调
        floatingView?.onSendCommand = { command ->
            sendCommandToServer(command)
        }
    }
    
    /**
     * 创建布局参数
     */
    private fun createLayoutParams(): WindowManager.LayoutParams {
        val params = WindowManager.LayoutParams()
        
        // 设置窗口大小
        params.width = 120
        params.height = 120
        
        // 设置窗口位置（使用绝对坐标，不使用Gravity）
        params.gravity = Gravity.TOP or Gravity.LEFT
        params.x = 30  // 距离左边30dp
        params.y = 100 // 距离顶部100dp
        
        // 设置窗口类型和标志
        // 仅应用内悬浮窗（依附当前Activity窗口的子面板）
        params.type = WindowManager.LayoutParams.TYPE_APPLICATION_PANEL
        params.flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                      WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
        
        // 设置像素格式
        params.format = PixelFormat.TRANSLUCENT
        
        return params
    }

    /**
     * 判断是否可以使用 TYPE_APPLICATION（仅限Activity上下文）
     */
    private fun canUseApplicationWindow(): Boolean {
        return context is android.app.Activity
    }

    /**
     * 是否已拥有悬浮窗权限
     */
    private fun hasOverlayPermission(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            Settings.canDrawOverlays(context)
        } else true
    }

    /**
     * 引导用户开启悬浮窗权限
     */
    private fun requestOverlayPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            try {
                val intent = Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + context.packageName)
                )
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(intent)
            } catch (_: Exception) {}
        }
    }
    
    /**
     * 检查悬浮窗是否正在显示
     */
    fun isFloatingWindowShowing(): Boolean {
        return isShowing
    }
    
    /**
     * 发送命令到服务器
     */
    private fun sendCommandToServer(command: String) {
        try {
            // 创建广播Intent发送命令到MobileService
            val intent = Intent(MobileGPTGlobal.STRING_ACTION)
            intent.putExtra(MobileGPTGlobal.INSTRUCTION_EXTRA, command)
            context.sendBroadcast(intent)
            
            Toast.makeText(context, "命令已发送: $command", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            Toast.makeText(context, "发送命令失败: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }
    

    
    /**
     * 清理资源
     */
    fun cleanup() {
        if (isShowing) {
            hideFloatingWindow()
        }
        floatingView = null
        windowManager = null
    }
}
