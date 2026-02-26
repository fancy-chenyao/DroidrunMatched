package com.example.emplab

import android.app.AlertDialog
import android.app.DatePickerDialog
import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.view.View
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import java.text.SimpleDateFormat
import java.util.*

class LeaveTimeActivity : AppCompatActivity() {
    
    private lateinit var tvStartDate: TextView
    private lateinit var tvEndDate: TextView
    private lateinit var tvStartTimeType: TextView
    private lateinit var tvEndTimeType: TextView
    private lateinit var btnConfirm: Button
    private lateinit var datePickerContainer: FrameLayout
    private lateinit var timePickerContainer: FrameLayout
    
    // 底层可交互元素的引用
    private lateinit var layoutStartDate: LinearLayout
    private lateinit var layoutEndDate: LinearLayout
    private lateinit var layoutStartTimeType: LinearLayout
    private lateinit var layoutEndTimeType: LinearLayout
    private lateinit var mainScrollView: ScrollView
    
    private var startDate: Date = Date()
    private var endDate: Date = Date()
    private var startTimeType = "全天"
    private var endTimeType = "全天"
    
    private var customDatePicker: CustomDatePickerView? = null
    private var customTimePicker: CustomTimePickerView? = null
    private var isSelectingStartDate = true
    private var isSelectingStartTime = true
    
    private val dateFormat = SimpleDateFormat("yyyy年MM月dd日", Locale.getDefault())
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_leave_time)
        
        initViews()
        setupClickListeners()
        updateDisplay()
    }
    
    private fun initViews() {
        tvStartDate = findViewById(R.id.tvStartDate)
        tvEndDate = findViewById(R.id.tvEndDate)
        tvStartTimeType = findViewById(R.id.tvStartTimeType)
        tvEndTimeType = findViewById(R.id.tvEndTimeType)
        btnConfirm = findViewById(R.id.btnConfirm)
        datePickerContainer = findViewById(R.id.datePickerContainer)
        timePickerContainer = findViewById(R.id.timePickerContainer)
        
        // 初始化底层可交互元素的引用
        layoutStartDate = findViewById(R.id.layoutStartDate)
        layoutEndDate = findViewById(R.id.layoutEndDate)
        layoutStartTimeType = findViewById(R.id.layoutStartTimeType)
        layoutEndTimeType = findViewById(R.id.layoutEndTimeType)
        mainScrollView = findViewById(R.id.mainScrollView)
        
        // 设置遮罩层点击事件，点击遮罩层关闭选择器
        datePickerContainer.setOnClickListener {
            hideCustomDatePicker()
        }
        timePickerContainer.setOnClickListener {
            hideCustomTimePicker()
        }
        
        // 初始化自定义日期选择器
        initCustomDatePicker()
        // 初始化自定义时间选择器
        initCustomTimePicker()
    }
    
    private fun setupClickListeners() {
        // 返回按钮
        findViewById<ImageView>(R.id.iv_back).setOnClickListener {
            finish()
        }
        
        // 开始日期点击
        findViewById<LinearLayout>(R.id.layoutStartDate).setOnClickListener {
            showCustomDatePicker(true)
        }
        
        // 结束日期点击
        findViewById<LinearLayout>(R.id.layoutEndDate).setOnClickListener {
            showCustomDatePicker(false)
        }
        
        // 开始时间类型点击
        findViewById<LinearLayout>(R.id.layoutStartTimeType).setOnClickListener {
            showCustomTimePicker(true)
        }
        
        // 结束时间类型点击
        findViewById<LinearLayout>(R.id.layoutEndTimeType).setOnClickListener {
            showCustomTimePicker(false)
        }
        
        // 确认按钮
        btnConfirm.setOnClickListener {
            // 跳转到请假详情页面
            val intent = Intent(this, LeaveDetailsActivity::class.java)
            startActivity(intent)
        }
    }
    
    private fun showDatePickerDialog(isStartDate: Boolean) {
        val calendar = Calendar.getInstance()
        if (isStartDate) {
            calendar.time = startDate
        } else {
            calendar.time = endDate
        }
        
        val datePickerDialog = DatePickerDialog(
            this,
            { _, year, month, dayOfMonth ->
                val selectedDate = Calendar.getInstance().apply {
                    set(year, month, dayOfMonth)
                }.time
                
                if (isStartDate) {
                    startDate = selectedDate
                    // 如果开始日期晚于结束日期，自动调整结束日期
                    if (startDate.after(endDate)) {
                        endDate = startDate
                    }
                } else {
                    endDate = selectedDate
                    // 如果结束日期早于开始日期，自动调整开始日期
                    if (endDate.before(startDate)) {
                        startDate = endDate
                    }
                }
                updateDisplay()
            },
            calendar.get(Calendar.YEAR),
            calendar.get(Calendar.MONTH),
            calendar.get(Calendar.DAY_OF_MONTH)
        )
        
        datePickerDialog.show()
    }
    
    private fun showTimeTypeDialog(isStartTime: Boolean) {
        val timeOptions = arrayOf("全天", "上午", "下午")
        val currentSelection = if (isStartTime) startTimeType else endTimeType
        val currentIndex = timeOptions.indexOf(currentSelection)
        
        val builder = AlertDialog.Builder(this)
        builder.setTitle(if (isStartTime) "选择开始时间" else "选择结束时间")
        builder.setSingleChoiceItems(timeOptions, currentIndex) { dialog, which ->
            val selectedTimeType = timeOptions[which]
            if (isStartTime) {
                startTimeType = selectedTimeType
            } else {
                endTimeType = selectedTimeType
            }
            updateDisplay()
            dialog.dismiss()
        }
        builder.show()
    }
    
    private fun updateDisplay() {
        tvStartDate.text = dateFormat.format(startDate)
        tvEndDate.text = dateFormat.format(endDate)
        tvStartTimeType.text = startTimeType
        tvEndTimeType.text = endTimeType
        
        val days = calculateLeaveDays()
        btnConfirm.text = "拟请假${days}天, 确认"
    }
    
    private fun calculateLeaveDays(): Int {
        val calendar = Calendar.getInstance()
        calendar.time = startDate
        val start = calendar.get(Calendar.DAY_OF_YEAR)
        
        calendar.time = endDate
        val end = calendar.get(Calendar.DAY_OF_YEAR)
        
        return end - start + 1
    }
    
    /**
     * 初始化自定义日期选择器
     */
    private fun initCustomDatePicker() {
        customDatePicker = CustomDatePickerView(this)
        datePickerContainer.addView(customDatePicker)
        
        // 防止点击选择器本身时触发遮罩层的关闭事件
        customDatePicker?.setOnClickListener {
            // 拦截点击事件，不传递给父容器
        }
        
        // 设置日期选择监听器
        customDatePicker?.setOnDateSelectedListener { selectedDate ->
            if (isSelectingStartDate) {
                startDate = selectedDate
                // 如果开始日期晚于结束日期，自动调整结束日期
                if (startDate.after(endDate)) {
                    endDate = startDate
                }
            } else {
                endDate = selectedDate
                // 如果结束日期早于开始日期，自动调整开始日期
                if (endDate.before(startDate)) {
                    startDate = endDate
                }
            }
            updateDisplay()
        }
        
        // 设置取消监听器
        customDatePicker?.setOnCancelListener {
            hideCustomDatePicker()
        }
    }
    
    /**
     * 显示自定义日期选择器
     */
    private fun showCustomDatePicker(isStartDate: Boolean) {
        isSelectingStartDate = isStartDate
        
        // 禁用底层元素的交互
        disableUnderlyingViews()
        
        // 设置当前选中的日期
        val currentDate = if (isStartDate) startDate else endDate
        customDatePicker?.setSelectedDate(currentDate)
        
        // 显示日期选择器
        customDatePicker?.show()
        datePickerContainer.visibility = View.VISIBLE
        
        Log.d("LeaveTimeActivity", "显示自定义日期选择器 - 等待ViewTreeObserver自动检测")
        // 不再手动触发，依赖ViewTreeObserver自动检测
    }
    
    /**
     * 隐藏自定义日期选择器
     */
    private fun hideCustomDatePicker() {
        customDatePicker?.hide()
        datePickerContainer.visibility = View.GONE
        
        // 恢复底层元素的交互
        enableUnderlyingViews()
        
        Log.d("LeaveTimeActivity", "隐藏自定义日期选择器 - 等待ViewTreeObserver自动检测")
        // 不再手动触发，依赖ViewTreeObserver自动检测
    }
    
    
    
    /**
     * 初始化自定义时间选择器
     */
    private fun initCustomTimePicker() {
        customTimePicker = CustomTimePickerView(this)
        timePickerContainer.addView(customTimePicker)
        
        // 防止点击选择器本身时触发遮罩层的关闭事件
        customTimePicker?.setOnClickListener {
            // 拦截点击事件，不传递给父容器
        }
        
        // 设置时间选择监听器
        customTimePicker?.setOnTimeSelectedListener { selectedTimeType ->
            if (isSelectingStartTime) {
                startTimeType = selectedTimeType
            } else {
                endTimeType = selectedTimeType
            }
            updateDisplay()
        }
        
        // 设置取消监听器
        customTimePicker?.setOnCancelListener {
            hideCustomTimePicker()
        }
    }
    
    /**
     * 显示自定义时间选择器
     */
    private fun showCustomTimePicker(isStartTime: Boolean) {
        isSelectingStartTime = isStartTime
        
        // 禁用底层元素的交互
        disableUnderlyingViews()
        
        // 设置标题
        val title = if (isStartTime) "选择开始时间" else "选择结束时间"
        customTimePicker?.setTitle(title)
        
        // 设置当前选中的时间类型
        val currentTimeType = if (isStartTime) startTimeType else endTimeType
        customTimePicker?.setSelectedTimeType(currentTimeType)
        
        // 显示时间选择器
        customTimePicker?.show()
        timePickerContainer.visibility = View.VISIBLE
        
        Log.d("LeaveTimeActivity", "显示自定义时间选择器 - 等待ViewTreeObserver自动检测")
        // 不再手动触发，依赖ViewTreeObserver自动检测
    }
    
    /**
     * 隐藏自定义时间选择器
     */
    private fun hideCustomTimePicker() {
        customTimePicker?.hide()
        timePickerContainer.visibility = View.GONE
        
        // 恢复底层元素的交互
        enableUnderlyingViews()
        
        Log.d("LeaveTimeActivity", "隐藏自定义时间选择器 - 等待ViewTreeObserver自动检测")
        // 不再手动触发，依赖ViewTreeObserver自动检测
    }
    
    /**
     * 禁用底层可交互元素，防止在选择器弹出时被程序化操作
     */
    private fun disableUnderlyingViews() {
        layoutStartDate.isEnabled = false
        layoutEndDate.isEnabled = false
        layoutStartTimeType.isEnabled = false
        layoutEndTimeType.isEnabled = false
        btnConfirm.isEnabled = false
        mainScrollView.isEnabled = false
        
        // 同时禁用子元素
        tvStartDate.isEnabled = false
        tvEndDate.isEnabled = false
        tvStartTimeType.isEnabled = false
        tvEndTimeType.isEnabled = false
        
        Log.d("LeaveTimeActivity", "已禁用底层可交互元素")
    }
    
    /**
     * 启用底层可交互元素
     */
    private fun enableUnderlyingViews() {
        layoutStartDate.isEnabled = true
        layoutEndDate.isEnabled = true
        layoutStartTimeType.isEnabled = true
        layoutEndTimeType.isEnabled = true
        btnConfirm.isEnabled = true
        mainScrollView.isEnabled = true
        
        // 同时启用子元素
        tvStartDate.isEnabled = true
        tvEndDate.isEnabled = true
        tvStartTimeType.isEnabled = true
        tvEndTimeType.isEnabled = true
        
        Log.d("LeaveTimeActivity", "已启用底层可交互元素")
    }
}
