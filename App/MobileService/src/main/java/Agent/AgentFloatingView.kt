package Agent

import android.animation.AnimatorSet
import android.animation.ObjectAnimator
import android.app.Dialog
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View
import android.view.Window
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast

/**
 * Agent自定义悬浮窗视图
 * 负责悬浮窗的显示和交互
 * 支持指令输入和ask功能
 */
class AgentFloatingView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {
    
    private var isExpanded = false
    private var inputDialog: AgentInputDialog? = null
    
    // 发送命令回调
    var onSendCommand: ((String) -> Unit)? = null
    
    // 拖拽相关
    private var windowManager: WindowManager? = null
    private var layoutParams: WindowManager.LayoutParams? = null
    private var initialX = 0f
    private var initialY = 0f
    private var initialTouchX = 0f
    private var initialTouchY = 0f
    private var isDragging = false
    private var screenWidth = 0
    private var screenHeight = 0
    
    // 绘制相关
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val backgroundPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val iconPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    
    init {
        setupView()
        setupPaints()
    }
    
    /**
     * 设置视图
     */
    private fun setupView() {
        // 设置背景
        setBackgroundResource(android.R.drawable.btn_default)
        
        // 获取屏幕尺寸
        val displayMetrics = context.resources.displayMetrics
        screenWidth = displayMetrics.widthPixels
        screenHeight = displayMetrics.heightPixels
        
        // 调试信息
        println("DEBUG: Screen size - width=$screenWidth, height=$screenHeight")
    }
    
    /**
     * 设置WindowManager和LayoutParams
     */
    fun setWindowManager(windowManager: WindowManager, layoutParams: WindowManager.LayoutParams) {
        this.windowManager = windowManager
        this.layoutParams = layoutParams
        this.initialX = layoutParams.x.toFloat()
        this.initialY = layoutParams.y.toFloat()
        
        // 使用WindowManager获取更准确的屏幕尺寸
        val display = windowManager.defaultDisplay
        val size = android.graphics.Point()
        display.getSize(size)
        screenWidth = size.x
        screenHeight = size.y
        
        println("DEBUG: Updated screen size from WindowManager - width=$screenWidth, height=$screenHeight")
    }
    
    /**
     * 设置画笔
     */
    private fun setupPaints() {
        // 背景画笔
        backgroundPaint.color = Color.parseColor("#4CAF50")
        backgroundPaint.style = Paint.Style.FILL
        
        // 图标画笔
        iconPaint.color = Color.WHITE
        iconPaint.style = Paint.Style.STROKE
        iconPaint.strokeWidth = 6f
        iconPaint.strokeCap = Paint.Cap.ROUND
    }
    
    /**
     * 切换输入对话框
     */
    fun toggleInputDialog() {
        if (isExpanded) {
            hideInputDialog()
        } else {
            showInputDialog()
        }
    }
    
    /**
     * 显示输入对话框
     */
    private fun showInputDialog() {
        try {
            inputDialog = AgentInputDialog(context)
            inputDialog?.setOnDismissListener {
                isExpanded = false
                animateCollapse()
            }
            // 设置发送监听器
            inputDialog?.setOnSendListener { text ->
                onSendCommand?.invoke(text)
            }
            inputDialog?.show()
            isExpanded = true
            animateExpansion()
        } catch (e: Exception) {
            AgentErrorHandler.handleDialogError(context, "显示输入框失败: ${e.message}", e)
        }
    }
    

    
    /**
     * 隐藏输入对话框
     */
    private fun hideInputDialog() {
        inputDialog?.dismiss()
        inputDialog = null
        isExpanded = false
        animateCollapse()
    }
    
    /**
     * 展开动画
     */
    private fun animateExpansion() {
        val scaleX = ObjectAnimator.ofFloat(this, "scaleX", 1f, 1.1f)
        val scaleY = ObjectAnimator.ofFloat(this, "scaleY", 1f, 1.1f)
        val alpha = ObjectAnimator.ofFloat(this, "alpha", 1f, 0.8f)
        
        val animatorSet = AnimatorSet()
        animatorSet.playTogether(scaleX, scaleY, alpha)
        animatorSet.duration = 200
        animatorSet.start()
    }
    
    /**
     * 收起动画
     */
    private fun animateCollapse() {
        val scaleX = ObjectAnimator.ofFloat(this, "scaleX", 1.1f, 1f)
        val scaleY = ObjectAnimator.ofFloat(this, "scaleY", 1.1f, 1f)
        val alpha = ObjectAnimator.ofFloat(this, "alpha", 0.8f, 1f)
        
        val animatorSet = AnimatorSet()
        animatorSet.playTogether(scaleX, scaleY, alpha)
        animatorSet.duration = 200
        animatorSet.start()
    }
    
    /**
     * 绘制悬浮窗
     */
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        
        val centerX = width / 2f
        val centerY = height / 2f
        val radius = (width / 2f) - 10
        
        // 绘制背景圆形
        canvas.drawCircle(centerX, centerY, radius, backgroundPaint)
        
        // 绘制输入框图标
        drawInputIcon(canvas, centerX, centerY, radius)
    }
    
    /**
     * 绘制输入框图标
     */
    private fun drawInputIcon(canvas: Canvas, centerX: Float, centerY: Float, radius: Float) {
        val iconSize = radius * 0.6f
        
        // 绘制输入框外框
        val rect = RectF(
            centerX - iconSize / 2,
            centerY - iconSize / 2,
            centerX + iconSize / 2,
            centerY + iconSize / 2
        )
        canvas.drawRect(rect, iconPaint)
        
        // 绘制输入框内部线条
        val lineY = centerY
        val lineStartX = centerX - iconSize / 2 + 8
        val lineEndX = centerX + iconSize / 2 - 8
        
        canvas.drawLine(lineStartX, lineY, lineEndX, lineY, iconPaint)
        
        // 绘制光标
        val cursorX = centerX
        val cursorTop = centerY - iconSize / 2 + 4
        val cursorBottom = centerY + iconSize / 2 - 4
        
        canvas.drawLine(cursorX, cursorTop, cursorX, cursorBottom, iconPaint)
    }
    
    /**
     * 检查是否已展开
     */
    fun isExpanded(): Boolean {
        return isExpanded
    }
    
    /**
     * 处理触摸事件
     */
    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.action) {
            MotionEvent.ACTION_DOWN -> {
                // 记录初始触摸位置
                initialTouchX = event.rawX
                initialTouchY = event.rawY
                initialX = layoutParams?.x?.toFloat() ?: 0f
                initialY = layoutParams?.y?.toFloat() ?: 0f
                isDragging = false
                
                // 开始拖拽时的视觉反馈
                animateDragStart()
                return true
            }
            
            MotionEvent.ACTION_MOVE -> {
                val deltaX = event.rawX - initialTouchX
                val deltaY = event.rawY - initialTouchY
                
                // 调试信息
                println("DEBUG: MOVE - deltaX=$deltaX, deltaY=$deltaY, initialX=$initialX, initialY=$initialY")
                
                // 判断是否开始拖拽（移动距离超过阈值）
                if (!isDragging && (Math.abs(deltaX) > 10 || Math.abs(deltaY) > 10)) {
                    isDragging = true
                    parent?.requestDisallowInterceptTouchEvent(true)
                    println("DEBUG: Started dragging")
                }
                
                if (isDragging) {
                    // 更新位置
                    val newX = (initialX + deltaX).toInt()
                    val newY = (initialY + deltaY).toInt()
                    
                    println("DEBUG: Calculated newX=$newX, newY=$newY")
                    
                    // 边界限制
                    val constrainedX = constrainX(newX)
                    val constrainedY = constrainY(newY)
                    
                    println("DEBUG: After constraint - constrainedX=$constrainedX, constrainedY=$constrainedY")
                    
                    // 更新布局参数
                    layoutParams?.let { params ->
                        params.x = constrainedX
                        params.y = constrainedY
                        windowManager?.updateViewLayout(this, params)
                        println("DEBUG: Updated position to x=${params.x}, y=${params.y}")
                    }
                }
                return true
            }
            
            MotionEvent.ACTION_UP -> {
                if (isDragging) {
                    // 拖拽结束
                    animateDragEnd()
                    parent?.requestDisallowInterceptTouchEvent(false)
                    
                    // 自动吸附到边缘
                    autoSnapToEdge()
                } else {
                    // 点击事件
                    toggleInputDialog()
                }
                return true
            }
            
            MotionEvent.ACTION_CANCEL -> {
                if (isDragging) {
                    animateDragEnd()
                    parent?.requestDisallowInterceptTouchEvent(false)
                }
                return true
            }
        }
        return super.onTouchEvent(event)
    }
    
    /**
     * X轴边界限制
     */
    private fun constrainX(x: Int): Int {
        val viewWidth = width
        return when {
            x < 0 -> 0
            x > screenWidth - viewWidth -> screenWidth - viewWidth
            else -> x
        }
    }
    
    /**
     * Y轴边界限制
     */
    private fun constrainY(y: Int): Int {
        val viewHeight = height
        
        // 简化的边界限制，只考虑基本的屏幕边界
        val minY = 0
        val maxY = screenHeight - viewHeight
        
        // 调试信息
        println("DEBUG: constrainY - y=$y, viewHeight=$viewHeight, screenHeight=$screenHeight, minY=$minY, maxY=$maxY")
        
        return when {
            y < minY -> {
                println("DEBUG: Y constrained to minY=$minY")
                minY
            }
            y > maxY -> {
                println("DEBUG: Y constrained to maxY=$maxY")
                maxY
            }
            else -> {
                println("DEBUG: Y not constrained, using y=$y")
                y
            }
        }
    }
    
    /**
     * 获取状态栏高度
     */
    private fun getStatusBarHeight(): Int {
        var result = 0
        val resourceId = context.resources.getIdentifier("status_bar_height", "dimen", "android")
        if (resourceId > 0) {
            result = context.resources.getDimensionPixelSize(resourceId)
        }
        return result
    }
    
    /**
     * 获取导航栏高度
     */
    private fun getNavigationBarHeight(): Int {
        var result = 0
        val resourceId = context.resources.getIdentifier("navigation_bar_height", "dimen", "android")
        if (resourceId > 0) {
            result = context.resources.getDimensionPixelSize(resourceId)
        }
        return result
    }
    
    /**
     * 自动吸附到边缘
     */
    private fun autoSnapToEdge() {
        layoutParams?.let { params ->
            val viewWidth = width
            val centerX = params.x + viewWidth / 2
            
            // 判断应该吸附到左边还是右边
            val targetX = if (centerX < screenWidth / 2) {
                30 // 吸附到左边
            } else {
                screenWidth - viewWidth - 30 // 吸附到右边
            }
            
            // 保持Y位置不变，只调整X位置
            animateToPosition(targetX, params.y)
        }
    }
    
    /**
     * 平滑移动到指定位置
     */
    private fun animateToPosition(targetX: Int, targetY: Int) {
        layoutParams?.let { params ->
            val animatorX = ObjectAnimator.ofInt(params.x, targetX)
            val animatorY = ObjectAnimator.ofInt(params.y, targetY)
            
            animatorX.addUpdateListener { animation ->
                params.x = animation.animatedValue as Int
                windowManager?.updateViewLayout(this, params)
            }
            
            animatorY.addUpdateListener { animation ->
                params.y = animation.animatedValue as Int
                windowManager?.updateViewLayout(this, params)
            }
            
            val animatorSet = AnimatorSet()
            animatorSet.playTogether(animatorX, animatorY)
            animatorSet.duration = 300
            animatorSet.start()
        }
    }
    
    /**
     * 拖拽开始动画
     */
    private fun animateDragStart() {
        val scaleX = ObjectAnimator.ofFloat(this, "scaleX", 1f, 1.2f)
        val scaleY = ObjectAnimator.ofFloat(this, "scaleY", 1f, 1.2f)
        val alpha = ObjectAnimator.ofFloat(this, "alpha", 1f, 0.8f)
        
        val animatorSet = AnimatorSet()
        animatorSet.playTogether(scaleX, scaleY, alpha)
        animatorSet.duration = 150
        animatorSet.start()
    }
    
    /**
     * 拖拽结束动画
     */
    private fun animateDragEnd() {
        val scaleX = ObjectAnimator.ofFloat(this, "scaleX", 1.2f, 1f)
        val scaleY = ObjectAnimator.ofFloat(this, "scaleY", 1.2f, 1f)
        val alpha = ObjectAnimator.ofFloat(this, "alpha", 0.8f, 1f)
        
        val animatorSet = AnimatorSet()
        animatorSet.playTogether(scaleX, scaleY, alpha)
        animatorSet.duration = 150
        animatorSet.start()
    }
    
    /**
     * Agent悬浮窗输入对话框
     * 提供快速输入功能
     */
    class AgentInputDialog(context: Context) : Dialog(context) {
        
        private lateinit var editText: EditText
        private lateinit var btnSend: Button
        private lateinit var btnClose: Button
        private lateinit var tvCharCount: TextView
        
        private var maxLength = 200
        private var onSendListener: ((String) -> Unit)? = null
        
        override fun onCreate(savedInstanceState: Bundle?) {
            super.onCreate(savedInstanceState)
            
            // 设置无标题栏
            requestWindowFeature(Window.FEATURE_NO_TITLE)
            
            // 设置布局
            setContentView(context.resources.getIdentifier("dialog_floating_input", "layout", context.packageName).let { 
                if (it != 0) it else android.R.layout.simple_list_item_1 
            })
            
            // 设置对话框样式
            setupDialogStyle()
            
            // 初始化视图
            setupViews()
            
            // 设置监听器
            setupListeners()
        }
        
        /**
         * 设置对话框样式
         */
        private fun setupDialogStyle() {
            window?.let { window ->
                // 设置背景透明
                window.setBackgroundDrawableResource(android.R.color.transparent)
                
                // 设置动画（如果有的话）
                // window.setWindowAnimations(R.style.DialogAnimation)
            }
        }
        
        /**
         * 初始化视图
         */
        private fun setupViews() {
            editText = findViewById(context.resources.getIdentifier("edit_input", "id", context.packageName))
            btnSend = findViewById(context.resources.getIdentifier("btn_send", "id", context.packageName))
            btnClose = findViewById(context.resources.getIdentifier("btn_close", "id", context.packageName))
            tvCharCount = findViewById(context.resources.getIdentifier("tv_char_count", "id", context.packageName))
            
            // 设置初始状态
            updateCharCount(0)
            btnSend.isEnabled = false
        }
        
        /**
         * 设置监听器
         */
        private fun setupListeners() {
            // 输入框文本变化监听
            editText.addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                    val length = s?.length ?: 0
                    updateCharCount(length)
                    btnSend.isEnabled = length > 0
                }
                
                override fun afterTextChanged(s: Editable?) {}
            })
            
            // 发送按钮点击
            btnSend.setOnClickListener {
                val text = editText.text.toString().trim()
                if (text.isNotEmpty()) {
                    handleSend(text)
                } else {
                    Toast.makeText(context, "请输入内容", Toast.LENGTH_SHORT).show()
                }
            }
            
            // 关闭按钮点击
            btnClose.setOnClickListener {
                dismiss()
            }
            
            // 点击外部关闭
            setCanceledOnTouchOutside(true)
        }
        
        /**
         * 更新字符计数
         */
        private fun updateCharCount(count: Int) {
            tvCharCount.text = "$count/$maxLength"
            
            // 根据字符数量改变颜色
            if (count > maxLength * 0.8) {
                tvCharCount.setTextColor(context.getColor(android.R.color.holo_red_dark))
            } else {
                tvCharCount.setTextColor(context.getColor(android.R.color.darker_gray))
            }
        }
        
        /**
         * 处理发送
         */
        private fun handleSend(text: String) {
            try {
                // 调用发送监听器
                onSendListener?.invoke(text)
                
                // 显示发送成功提示
                Toast.makeText(context, "发送成功: $text", Toast.LENGTH_SHORT).show()
                
                // 关闭对话框
                dismiss()
                
            } catch (e: Exception) {
                Toast.makeText(context, "发送失败: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }
        
        /**
         * 设置发送监听器
         */
        fun setOnSendListener(listener: (String) -> Unit) {
            onSendListener = listener
        }
        
        /**
         * 设置最大长度
         */
        fun setMaxLength(length: Int) {
            maxLength = length
            editText.filters = arrayOf(android.text.InputFilter.LengthFilter(maxLength))
        }
        
        /**
         * 设置提示文本
         */
        fun setHint(hint: String) {
            editText.hint = hint
        }
        
        /**
         * 获取输入内容
         */
        fun getInputText(): String {
            return editText.text.toString().trim()
        }
        
        /**
         * 清空输入内容
         */
        fun clearInput() {
            editText.setText("")
        }
        
        /**
         * 设置输入内容
         */
        fun setInputText(text: String) {
            editText.setText(text)
            editText.setSelection(text.length)
        }
    }
}
