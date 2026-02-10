package controller

import android.app.Activity
import android.view.View
import android.view.ViewGroup
import android.util.Log
import java.lang.reflect.Field
import java.lang.reflect.Method

object AccessibilityController {
    
    /**
     * 获取页面的元素树
     */
    fun getElementTree(activity: Activity, callback: (ElementTree) -> Unit) {
        val rootView = activity.window.decorView.findViewById<View>(android.R.id.content)
        val elementTree = scanUIElements(rootView)
        callback(elementTree)
    }
    
    /**
     * 扫描UI元素
     */
    private fun scanUIElements(view: View): ElementTree {
        val elements = mutableListOf<ElementInfo>()
        
        if (isAccessibleView(view)) {
            elements.addAll(extractUIElements(view))
        }
        
        if (view is ViewGroup) {
            for (i in 0 until view.childCount) {
                elements.addAll(scanUIElements(view.getChildAt(i)).elements)
            }
        }
        
        return ElementTree(elements, "UI")
    }
    
    /**
     * 判断是否为可访问的视图
     */
    private fun isAccessibleView(view: View): Boolean {
        val className = view.javaClass.name
        return className.contains("FlutterView", ignoreCase = true) ||
               className.contains("FlutterSurfaceView", ignoreCase = true) ||
               className.contains("FlutterTextureView", ignoreCase = true) ||
               className.contains("PlatformView", ignoreCase = true) ||
               className.contains("FlutterImageView", ignoreCase = true) ||
               isMockUIElement(view)
    }

    /**
     * 检查是否是模拟的UI元素
     */
    private fun isMockUIElement(view: View): Boolean {
        return view.tag is Map<*, *> && (view.tag as Map<*, *>).containsKey("semanticLabel")
    }
    
    /**
     * 提取UI元素信息
     */
    private fun extractUIElements(view: View): List<ElementInfo> {
        val elements = mutableListOf<ElementInfo>()
        
        try {
            // 尝试获取UI元素的属性
            val semanticLabel = getSemanticLabel(view)
            val tooltip = getTooltip(view)
            val accessibilityLabel = getAccessibilityLabel(view)
            val text = getTextContent(view)
            
            if (semanticLabel != null || tooltip != null || accessibilityLabel != null) {
                elements.add(
                    ElementInfo(
                        id = semanticLabel ?: tooltip ?: accessibilityLabel ?: "ui_${view.hashCode()}",
                        type = getElementType(view),
                        text = text,
                        bounds = getViewBounds(view),
                        clickable = view.isClickable,
                        focusable = view.isFocusable,
                        enabled = view.isEnabled,
                        visible = view.visibility == View.VISIBLE
                    )
                )
            }
            
            // 处理模拟的UI元素
            if (isMockUIElement(view)) {
                val mockTag = view.tag as Map<*, *>
                val mockSemanticLabel = mockTag["semanticLabel"] as? String
                val mockTooltip = mockTag["tooltip"] as? String
                
                if (mockSemanticLabel != null || mockTooltip != null) {
                    elements.add(
                        ElementInfo(
                            id = mockSemanticLabel ?: mockTooltip ?: "mock_ui_${view.hashCode()}",
                            type = getElementType(view),
                            text = text,
                            bounds = getViewBounds(view),
                            clickable = view.isClickable,
                            focusable = view.isFocusable,
                            enabled = view.isEnabled,
                            visible = view.visibility == View.VISIBLE
                        )
                    )
                }
            }
        } catch (e: Exception) {
            // 忽略反射异常
        }
        
        return elements
    }
    
    /**
     * 获取语义标签
     */
    private fun getSemanticLabel(view: View): String? {
        return try {
            // 首先尝试通过反射获取真实字段
            val field = view.javaClass.getDeclaredField("mSemanticLabel")
            field.isAccessible = true
            field.get(view) as? String
        } catch (e: Exception) {
            // 如果反射失败，尝试从tag中获取模拟的semanticLabel
            try {
                val tag = view.tag
                if (tag is Map<*, *>) {
                    return tag["semanticLabel"] as? String
                }
            } catch (e2: Exception) {
                // 忽略所有异常
            }
            null
        }
    }
    
    /**
     * 获取工具提示
     */
    private fun getTooltip(view: View): String? {
        return try {
            // 首先尝试通过反射获取真实字段
            val field = view.javaClass.getDeclaredField("mTooltip")
            field.isAccessible = true
            field.get(view) as? String
        } catch (e: Exception) {
            // 如果反射失败，尝试从tag中获取模拟的tooltip
            try {
                val tag = view.tag
                if (tag is Map<*, *>) {
                    return tag["tooltip"] as? String
                }
            } catch (e2: Exception) {
                // 忽略所有异常
            }
            null
        }
    }
    
    /**
     * 获取无障碍标签
     */
    private fun getAccessibilityLabel(view: View): String? {
        return try {
            val field = view.javaClass.getDeclaredField("mAccessibilityLabel")
            field.isAccessible = true
            field.get(view) as? String
        } catch (e: Exception) {
            null
        }
    }
    
    /**
     * 获取文本内容
     */
    private fun getTextContent(view: View): String? {
        return try {
            val method = view.javaClass.getMethod("getText")
            method.invoke(view) as? String
        } catch (e: Exception) {
            null
        }
    }
    
    /**
     * 获取元素类型
     */
    private fun getElementType(view: View): String {
        return when {
            view is android.widget.Button -> "Button"
            view is android.widget.EditText -> "TextInput"
            view is android.widget.TextView -> "Text"
            view is android.widget.ImageView -> "Image"
            view is android.widget.CheckBox -> "CheckBox"
            view is android.widget.Switch -> "Switch"
            else -> "View"
        }
    }
    
    /**
     * 获取视图边界
     */
    private fun getViewBounds(view: View): String {
        return "${view.left},${view.top},${view.right},${view.bottom}"
    }
    
    private const val TAG = "AccessibilityController"

    /**
     * 设置输入值
     */
    fun setInputValue(activity: Activity, elementId: String, value: String, callback: (Boolean) -> Unit) {
        Log.d(TAG, "setInputValue: elementId=$elementId, value='$value'")
        
        // 优先使用无障碍服务
        val accessibilityService = ElementAccessibilityService.getInstance()
        if (accessibilityService != null) {
            Log.d(TAG, "AccessibilityService available, trying to find node...")
            // 通过无障碍服务查找元素
            var nodeInfo = accessibilityService.findElementById(elementId)
            if (nodeInfo == null) {
                nodeInfo = accessibilityService.findElementByDescription(elementId)
            }
            
            if (nodeInfo != null) {
                Log.d(TAG, "Found node via AccessibilityService, setting text...")
                val success = accessibilityService.setText(nodeInfo, value)
                Log.d(TAG, "AccessibilityService setText result: $success")
                callback(success)
                return
            } else {
                Log.d(TAG, "Node not found via AccessibilityService, falling back to reflection")
            }
        } else {
            Log.d(TAG, "AccessibilityService not available, using reflection")
        }
        
        // 如果无障碍服务不可用，回退到反射方式
        val rootView = activity.window.decorView.findViewById<View>(android.R.id.content)
        val targetView = findUIElement(rootView, elementId)
        
        if (targetView != null) {
            Log.d(TAG, "Found target view via findUIElement: $targetView (class=${targetView.javaClass.name})")
            
            // 尝试直接设置文本
            if (trySetTextReflectively(targetView, value)) {
                Log.d(TAG, "Successfully set text reflectively")
                callback(true)
                return
            } else {
                Log.d(TAG, "Failed to set text reflectively")
            }

            // 如果直接设置失败，且是ViewGroup，尝试查找子EditText
            if (targetView is ViewGroup) {
                Log.d(TAG, "Target is ViewGroup, searching for child EditText...")
                val childEditText = findFirstEditText(targetView)
                if (childEditText != null) {
                    Log.d(TAG, "Found child EditText: $childEditText")
                    childEditText.setText(value)
                    Log.d(TAG, "Set text on child EditText")
                    callback(true)
                    return
                } else {
                    Log.d(TAG, "No child EditText found in ViewGroup")
                }
            } else {
                Log.d(TAG, "Target is not ViewGroup, cannot search for children")
            }

            Log.w(TAG, "Failed to set input value on found view")
            callback(false)
        } else {
            Log.e(TAG, "Target view not found for elementId: $elementId")
            callback(false)
        }
    }

    private fun findFirstEditText(view: View): android.widget.EditText? {
        if (view is android.widget.EditText) return view
        if (view is ViewGroup) {
            for (i in 0 until view.childCount) {
                val child = view.getChildAt(i)
                val result = findFirstEditText(child)
                if (result != null) return result
            }
        }
        return null
    }

    private fun trySetTextReflectively(view: View, value: String): Boolean {
        try {
            // 尝试通过反射设置文本
            val method = view.javaClass.getMethod("setText", CharSequence::class.java)
            method.invoke(view, value)
            return true
        } catch (e: Exception) {
            // 如果setText方法不存在，尝试其他方法
            try {
                val method = view.javaClass.getMethod("setContentDescription", CharSequence::class.java)
                method.invoke(view, value)
                return true
            } catch (e2: Exception) {
                return false
            }
        }
    }
    
    /**
     * 点击元素
     */
    fun clickElement(activity: Activity, elementId: String, callback: (Boolean) -> Unit) {
        // 优先使用无障碍服务
        val accessibilityService = ElementAccessibilityService.getInstance()
        if (accessibilityService != null) {
            // 通过无障碍服务查找元素
            var nodeInfo = accessibilityService.findElementById(elementId)
            if (nodeInfo == null) {
                nodeInfo = accessibilityService.findElementByDescription(elementId)
            }
            
            if (nodeInfo != null) {
                val success = accessibilityService.clickElement(nodeInfo)
                callback(success)
                return
            }
        }
        
        // 如果无障碍服务不可用，回退到反射方式
        val rootView = activity.window.decorView.findViewById<View>(android.R.id.content)
        val targetView = findUIElement(rootView, elementId)
        
        if (targetView != null && targetView.isClickable) {
            targetView.performClick()
            callback(true)
        } else {
            callback(false)
        }
    }
    
    /**
     * 模拟长按操作
     */
    fun longClickElement(activity: Activity, elementId: String, callback: (Boolean) -> Unit) {
        // 优先使用无障碍服务
        val accessibilityService = ElementAccessibilityService.getInstance()
        if (accessibilityService != null) {
            // 通过无障碍服务查找元素
            var nodeInfo = accessibilityService.findElementById(elementId)
            if (nodeInfo == null) {
                nodeInfo = accessibilityService.findElementByDescription(elementId)
            }
            
            if (nodeInfo != null) {
                val success = accessibilityService.longClick(nodeInfo)
                callback(success)
                return
            }
        }
        
        // 如果无障碍服务不可用，回退到反射方式
        val rootView = activity.window.decorView.findViewById<View>(android.R.id.content)
        val targetView = findUIElement(rootView, elementId)
        
        if (targetView != null && targetView.isLongClickable) {
            targetView.performLongClick()
            callback(true)
        } else {
            callback(false)
        }
    }
    
    /**
     * 查找UI元素
     */
    private fun findUIElement(view: View, elementId: String): View? {
        // 检查view hash ID
        if (elementId == "ui_${view.hashCode()}") {
            Log.d(TAG, "findUIElement matched by hash ID: $elementId")
            return view
        }

        if (isAccessibleView(view)) {
            val semanticLabel = getSemanticLabel(view)
            val tooltip = getTooltip(view)
            val accessibilityLabel = getAccessibilityLabel(view)
            
            if (elementId == semanticLabel || elementId == tooltip || elementId == accessibilityLabel) {
                Log.d(TAG, "findUIElement matched by label: $elementId (semantic=$semanticLabel, tooltip=$tooltip, accessibility=$accessibilityLabel)")
                return view
            }
        }
        
        // 查找模拟的UI元素
        if (isMockUIElement(view)) {
            val mockTag = view.tag as Map<*, *>
            val mockSemanticLabel = mockTag["semanticLabel"] as? String
            val mockTooltip = mockTag["tooltip"] as? String
            
            if (elementId == mockSemanticLabel || elementId == mockTooltip) {
                Log.d(TAG, "findUIElement matched by mock label: $elementId")
                return view
            }
        }
        
        if (view is ViewGroup) {
            for (i in 0 until view.childCount) {
                val result = findUIElement(view.getChildAt(i), elementId)
                if (result != null) {
                    return result
                }
            }
        }
        
        return null
    }
}