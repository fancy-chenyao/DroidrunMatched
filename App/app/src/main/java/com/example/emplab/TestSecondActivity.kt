package com.example.emplab

import android.os.Bundle
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

class TestSecondActivity : AppCompatActivity() {
    /**
     * 第二测试页面：用于导航跳转后的稳定状态验证
     */
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildUI())
    }

    /**
     * 构建简单的展示页面
     */
    private fun buildUI(): LinearLayout {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }
        val title = TextView(this).apply {
            id = 2001
            text = "Second Screen"
            textSize = 18f
        }
        root.addView(title)
        return root
    }
}
