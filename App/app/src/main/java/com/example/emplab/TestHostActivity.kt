package com.example.emplab

import android.os.Bundle
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/**
 * 固定静态的测试宿主 Activity：提供稳定可控的原生控件用于自动化测试
 * 包含：Button（点击/长按）、EditText（输入）、ScrollView（滚动）、状态 TextView
 */
class TestHostActivity : AppCompatActivity() {
    /**
     * Activity 创建回调：构建固定的测试 UI
     */
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildStaticUI())
    }

    /**
     * 构建测试所需的静态 UI 视图树
     */
    private fun buildStaticUI(): LinearLayout {
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }

        // 状态文本：用于脏页面干扰与验证
        val statusText = TextView(this).apply {
            id = 1004 // TEXT_ID
            text = "Status: Idle"
        }

        // 测试按钮：点击改变文本，长按改变为 LongPressed
        val button = Button(this).apply {
            id = 1001 // BTN_ID
            text = "Test Button"
            setOnClickListener { text = "Clicked" }
            setOnLongClickListener {
                text = "LongPressed"
                true
            }
        }

        // 中性按钮：可点击但不改变任何文本，用于负面验证
        val neutralButton = Button(this).apply {
            id = 1005 // NEUTRAL_ID
            text = "Neutral"
            setOnClickListener { /* no-op */ }
        }

        // 导航按钮：跳转到第二个测试页面，用于 activity_switch 验证
        val goNextButton = Button(this).apply {
            id = 1006 // GO_NEXT_ID
            text = "Go Next"
            setOnClickListener {
                startActivity(android.content.Intent(this@TestHostActivity, TestSecondActivity::class.java))
            }
        }

        // 动态添加项按钮：点击后向 ScrollView 内容中增加一条项，用于布局变化验证
        val addItemButton = Button(this).apply {
            id = 1007 // ADD_ITEM_ID
            text = "Add Item"
        }

        // 输入框：用于 input_text 测试
        val editText = EditText(this).apply {
            id = 1002 // EDIT_ID
            hint = "Input Here"
            setText("Seed")
        }

        // 可滚动区域：用于 swipe 测试
        val scrollView = ScrollView(this).apply {
            id = 1003 // SCROLL_ID
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                500
            )
        }
        val scrollContent = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        for (i in 1..20) {
            scrollContent.addView(TextView(this).apply {
                text = "Item $i"
                setPadding(20, 20, 20, 20)
            })
        }
        scrollView.addView(scrollContent)

        // 绑定“动态添加项”行为
        addItemButton.setOnClickListener {
            val count = scrollContent.childCount + 1
            scrollContent.addView(TextView(this).apply {
                text = "AddedItem $count"
                setPadding(20, 20, 20, 20)
            })
        }

        container.addView(button)
        container.addView(neutralButton)
        container.addView(goNextButton)
        container.addView(addItemButton)
        container.addView(editText)
        container.addView(scrollView)
        container.addView(statusText)
        return container
    }
}
