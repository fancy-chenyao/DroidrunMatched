package com.example.emplab

import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {
    
    private lateinit var navHome: LinearLayout
    private lateinit var navPeople: LinearLayout
    private lateinit var navMessage: LinearLayout
    private lateinit var navProfile: LinearLayout
    
    private lateinit var ivNavHome: ImageView
    private lateinit var ivNavPeople: ImageView
    private lateinit var ivNavMessage: ImageView
    private lateinit var ivNavProfile: ImageView
    
    private lateinit var tvNavHome: TextView
    private lateinit var tvNavPeople: TextView
    private lateinit var tvNavMessage: TextView
    private lateinit var tvNavProfile: TextView
    

    
    // 权限请求码
    private val PERMISSION_REQUEST_CODE = 1001
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        
        // 检查并请求必要权限
        checkAndRequestPermissions()
        
        initViews()
        setupNavigation()
        setupFunctionClicks()

    }
    
    /**
     * 检查并请求必要权限
     * 说明：
     * - API 33+ 使用 READ_MEDIA_* 权限
     * - API 32- 使用 READ/WRITE_EXTERNAL_STORAGE 权限
     * - 仅请求在 Manifest 中声明过的权限，避免未声明导致的崩溃
     */
    private fun checkAndRequestPermissions() {
        val declared = getDeclaredPermissions()
        val toRequest = mutableListOf<String>()
        
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val mediaPerms = listOf(
                android.Manifest.permission.READ_MEDIA_IMAGES,
                android.Manifest.permission.READ_MEDIA_VIDEO,
                android.Manifest.permission.READ_MEDIA_AUDIO
            )
            mediaPerms.forEach { perm ->
                if (declared.contains(perm) &&
                    ContextCompat.checkSelfPermission(this, perm) != PackageManager.PERMISSION_GRANTED) {
                    toRequest.add(perm)
                }
            }
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val legacyPerms = listOf(
                android.Manifest.permission.WRITE_EXTERNAL_STORAGE,
                android.Manifest.permission.READ_EXTERNAL_STORAGE
            )
            legacyPerms.forEach { perm ->
                if (declared.contains(perm) &&
                    ContextCompat.checkSelfPermission(this, perm) != PackageManager.PERMISSION_GRANTED) {
                    toRequest.add(perm)
                }
            }
        }
        
        if (toRequest.isNotEmpty()) {
            try {
                ActivityCompat.requestPermissions(
                    this,
                    toRequest.toTypedArray(),
                    PERMISSION_REQUEST_CODE
                )
            } catch (e: Exception) {
                Toast.makeText(this, "权限请求失败: ${e.message}", Toast.LENGTH_LONG).show()
            }
        }
    }
    
    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        
        if (requestCode == PERMISSION_REQUEST_CODE) {
            var allPermissionsGranted = true
            
            for (result in grantResults) {
                if (result != PackageManager.PERMISSION_GRANTED) {
                    allPermissionsGranted = false
                    break
                }
            }
            
            if (allPermissionsGranted) {
                Toast.makeText(this, "权限获取成功", Toast.LENGTH_SHORT).show()
            } else {
                Toast.makeText(this, "部分权限被拒绝，可能影响功能正常使用", Toast.LENGTH_LONG).show()
            }
        }
    }
    
    /**
     * 获取当前应用在 Manifest 中声明的权限集合
     */
    private fun getDeclaredPermissions(): Set<String> {
        return try {
            val pi = packageManager.getPackageInfo(packageName, PackageManager.GET_PERMISSIONS)
            val declared = pi.requestedPermissions ?: emptyArray()
            declared.toSet()
        } catch (_: Exception) {
            emptySet()
        }
    }
    
    
    private fun initViews() {
        // 导航栏
        navHome = findViewById(R.id.nav_home)
        navPeople = findViewById(R.id.nav_people)
        navMessage = findViewById(R.id.nav_message)
        navProfile = findViewById(R.id.nav_profile)
        
        ivNavHome = findViewById(R.id.iv_nav_home)
        ivNavPeople = findViewById(R.id.iv_nav_people)
        ivNavMessage = findViewById(R.id.iv_nav_message)
        ivNavProfile = findViewById(R.id.iv_nav_profile)
        
        tvNavHome = findViewById(R.id.tv_nav_home)
        tvNavPeople = findViewById(R.id.tv_nav_people)
        tvNavMessage = findViewById(R.id.tv_nav_message)
        tvNavProfile = findViewById(R.id.tv_nav_profile)
    }
    
    private fun setupNavigation() {
        navHome.setOnClickListener { switchTab(0) }
        navPeople.setOnClickListener { switchTab(1) }
        navMessage.setOnClickListener { switchTab(2) }
        navProfile.setOnClickListener { switchTab(3) }
        
        // 默认选中首页
        switchTab(0)
    }
    
    private fun switchTab(position: Int) {
        // 重置所有导航项状态
        resetNavigationState()
        
        when (position) {
            0 -> {
                // 首页
                ivNavHome.setImageResource(R.drawable.ic_home)
                tvNavHome.setTextColor(getColor(R.color.selected_blue))
                tvNavHome.isSelected = true
                Toast.makeText(this, "首页", Toast.LENGTH_SHORT).show()
            }
            1 -> {
                // 人员
                ivNavPeople.setImageResource(R.drawable.ic_people)
                tvNavPeople.setTextColor(getColor(R.color.selected_blue))
                tvNavPeople.isSelected = true
                Toast.makeText(this, "人员", Toast.LENGTH_SHORT).show()
            }
            2 -> {
                // 消息
                ivNavMessage.setImageResource(R.drawable.ic_message)
                tvNavMessage.setTextColor(getColor(R.color.selected_blue))
                tvNavMessage.isSelected = true
                Toast.makeText(this, "消息", Toast.LENGTH_SHORT).show()
            }
            3 -> {
                // 我的
                ivNavProfile.setImageResource(R.drawable.ic_profile)
                tvNavProfile.setTextColor(getColor(R.color.selected_blue))
                tvNavProfile.isSelected = true
                Toast.makeText(this, "我的", Toast.LENGTH_SHORT).show()
            }
        }
    }
    
    private fun resetNavigationState() {
        // 重置图标颜色
        ivNavHome.setImageResource(R.drawable.ic_home)
        ivNavPeople.setImageResource(R.drawable.ic_people)
        ivNavMessage.setImageResource(R.drawable.ic_message)
        ivNavProfile.setImageResource(R.drawable.ic_profile)
        
        // 重置文字颜色和选中状态
        tvNavHome.setTextColor(getColor(R.color.unselected_gray))
        tvNavPeople.setTextColor(getColor(R.color.unselected_gray))
        tvNavMessage.setTextColor(getColor(R.color.unselected_gray))
        tvNavProfile.setTextColor(getColor(R.color.unselected_gray))
        
        tvNavHome.isSelected = false
        tvNavPeople.isSelected = false
        tvNavMessage.isSelected = false
        tvNavProfile.isSelected = false
    }
    
    private fun setupFunctionClicks() {
        // 功能图标点击事件
        findViewById<View>(R.id.iv_todo).setOnClickListener {
            Toast.makeText(this, "事务待办", Toast.LENGTH_SHORT).show()
        }
        
        findViewById<View>(R.id.iv_calendar).setOnClickListener {
            Toast.makeText(this, "日程管理", Toast.LENGTH_SHORT).show()
        }
        
        findViewById<View>(R.id.iv_learning).setOnClickListener {
            Toast.makeText(this, "建行学习", Toast.LENGTH_SHORT).show()
        }
        
        findViewById<View>(R.id.iv_knowledge).setOnClickListener {
            Toast.makeText(this, "知识百科", Toast.LENGTH_SHORT).show()
        }
        
        findViewById<View>(R.id.iv_benefits).setOnClickListener {
            Toast.makeText(this, "员工福利", Toast.LENGTH_SHORT).show()
        }
        
        findViewById<View>(R.id.iv_travel).setOnClickListener {
            // 跳转到员工差旅页面
            val intent = Intent(this, TravelActivity::class.java)
            startActivity(intent)
        }
        
        findViewById<View>(R.id.iv_leave).setOnClickListener {
            // 跳转到请假申请页面
            val intent = Intent(this, LeaveApplicationActivity::class.java)
            startActivity(intent)
        }
        
        findViewById<View>(R.id.iv_products).setOnClickListener {
            Toast.makeText(this, "产品服务", Toast.LENGTH_SHORT).show()
        }
        
        findViewById<View>(R.id.iv_hr).setOnClickListener {
            Toast.makeText(this, "人力资源", Toast.LENGTH_SHORT).show()
        }
        
        findViewById<View>(R.id.iv_more).setOnClickListener {
            Toast.makeText(this, "更多功能", Toast.LENGTH_SHORT).show()
        }
        
        // 搜索相关点击事件
        findViewById<View>(R.id.iv_scan).setOnClickListener {
            Toast.makeText(this, "扫描功能", Toast.LENGTH_SHORT).show()
        }
        
        findViewById<View>(R.id.iv_robot).setOnClickListener {
            Toast.makeText(this, "智能助手", Toast.LENGTH_SHORT).show()
        }
    }
    
    
}
