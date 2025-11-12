package Agent

import android.app.Activity
import android.graphics.Bitmap
import android.util.Base64
import android.util.Log
import controller.GenericElement
import controller.UIUtils
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream

/**
 * 数据格式转换工具
 * 用于将APP端的数据格式转换为服务端期望的格式
 */
object StateConverter {
    
    private const val TAG = "StateConverter"
    private const val MAX_A11Y_NODES = 2000
    private const val MAX_A11Y_DEPTH = 6
    private const val MAX_TEXT_LEN = 256
    
    /**
     * 将GenericElement树转换为a11y_tree格式（JSON数组）
     */
    fun convertElementTreeToA11yTree(element: GenericElement): JSONArray {
        val result = JSONArray()
        convertElementRecursive(element, result)
        return result
    }
    
    /**
     * 递归转换元素
     */
    private fun convertElementRecursive(element: GenericElement, parentArray: JSONArray) {
        val elementObj = JSONObject()
        
        // 基本属性
        elementObj.put("index", element.index)
        elementObj.put("resourceId", element.resourceId)
        elementObj.put("className", element.className)
        elementObj.put("text", element.text)
        elementObj.put("contentDesc", truncateText(element.contentDesc))
        
        // 布尔属性
        elementObj.put("clickable", element.clickable)
        elementObj.put("enabled", element.enabled)
        elementObj.put("checked", element.checked)
        elementObj.put("checkable", element.checkable)
        elementObj.put("scrollable", element.scrollable)
        elementObj.put("longClickable", element.longClickable)
        elementObj.put("selected", element.selected)
        elementObj.put("important", element.important)
        elementObj.put("naf", element.naf)
        
        // bounds对象
        val boundsObj = JSONObject()
        boundsObj.put("left", element.bounds.left)
        boundsObj.put("top", element.bounds.top)
        boundsObj.put("right", element.bounds.right)
        boundsObj.put("bottom", element.bounds.bottom)
        elementObj.put("bounds", boundsObj)
        
        // 附加属性
        if (element.additionalProps.isNotEmpty()) {
            val additionalPropsObj = JSONObject()
            element.additionalProps.forEach { (key, value) ->
                additionalPropsObj.put(key, value)
            }
            elementObj.put("additionalProps", additionalPropsObj)
        }
        
        // 递归处理子元素
        if (element.children.isNotEmpty()) {
            val childrenArray = JSONArray()
            element.children.forEach { child ->
                convertElementRecursive(child, childrenArray)
            }
            elementObj.put("children", childrenArray)
        }
        
        parentArray.put(elementObj)
    }
    
    private fun truncateText(s: String?): String {
        if (s == null) return ""
        return if (s.length > MAX_TEXT_LEN) s.substring(0, MAX_TEXT_LEN) else s
    }
    
    /**
     * 受限版本：限制深度、节点数与字符串长度
     */
    fun convertElementTreeToA11yTreePruned(element: GenericElement): JSONArray {
        val result = JSONArray()
        var count = 0
        fun recurse(e: GenericElement, parent: JSONArray, depth: Int) {
            if (depth > MAX_A11Y_DEPTH) return
            if (count >= MAX_A11Y_NODES) return
            val obj = JSONObject()
            obj.put("index", e.index)
            obj.put("resourceId", e.resourceId)
            obj.put("className", e.className)
            obj.put("text", truncateText(e.text))
            obj.put("contentDesc", truncateText(e.contentDesc))
            obj.put("clickable", e.clickable)
            obj.put("enabled", e.enabled)
            obj.put("checked", e.checked)
            obj.put("checkable", e.checkable)
            obj.put("scrollable", e.scrollable)
            obj.put("longClickable", e.longClickable)
            obj.put("selected", e.selected)
            obj.put("important", e.important)
            obj.put("naf", e.naf)
            val boundsObj = JSONObject()
            boundsObj.put("left", e.bounds.left)
            boundsObj.put("top", e.bounds.top)
            boundsObj.put("right", e.bounds.right)
            boundsObj.put("bottom", e.bounds.bottom)
            obj.put("bounds", boundsObj)
            if (e.children.isNotEmpty() && depth < MAX_A11Y_DEPTH) {
                val arr = JSONArray()
                for (child in e.children) {
                    if (count >= MAX_A11Y_NODES) break
                    recurse(child, arr, depth + 1)
                }
                if (arr.length() > 0) {
                    obj.put("children", arr)
                }
            }
            parent.put(obj)
            count++
        }
        recurse(element, result, 1)
        return result
    }
    
    /**
     * 获取设备状态信息
     */
    fun getPhoneState(activity: Activity?): JSONObject {
        val state = JSONObject()
        
        if (activity != null) {
            try {
                // 获取当前包名
                val packageName = activity.packageName
                state.put("package", packageName)
                
                // 获取当前Activity类名
                val activityName = activity.javaClass.simpleName
                state.put("activity", activityName)
                
                // 获取屏幕尺寸（dp单位）
                val displayMetrics = activity.resources.displayMetrics
                val screenWidthDp = UIUtils.pxToDp(activity, displayMetrics.widthPixels.toFloat()).toInt()
                val screenHeightDp = UIUtils.pxToDp(activity, displayMetrics.heightPixels.toFloat()).toInt()
                
                state.put("screen_width", screenWidthDp)
                state.put("screen_height", screenHeightDp)
                
                // 可选：添加更多设备信息
                state.put("density", displayMetrics.density)
                state.put("densityDpi", displayMetrics.densityDpi)
                
            } catch (e: Exception) {
                Log.e(TAG, "获取设备状态时发生异常", e)
                state.put("package", "unknown")
                state.put("activity", "unknown")
                state.put("screen_width", 0)
                state.put("screen_height", 0)
            }
        } else {
            state.put("package", "unknown")
            state.put("activity", "unknown")
            state.put("screen_width", 0)
            state.put("screen_height", 0)
        }
        
        return state
    }
    
    /**
     * 构建完整的get_state响应
     */
    fun buildStateResponse(
        activity: Activity?,
        elementTree: GenericElement,
        screenshot: Bitmap?
    ): JSONObject {
        val response = JSONObject()
        
        try {
            // 转换元素树
            val a11yTree = convertElementTreeToA11yTree(elementTree)
            response.put("a11y_tree", a11yTree)
            
            // 获取设备状态
            val phoneState = getPhoneState(activity)
            response.put("phone_state", phoneState)
            
            // 不在此处执行网络上传，避免主线程网络。截图引用由调用方负责上传并注入。
            
        } catch (e: Exception) {
            Log.e(TAG, "构建状态响应时发生异常", e)
            // 返回空的数据结构
            response.put("a11y_tree", JSONArray())
            response.put("phone_state", getPhoneState(null))
        }
        
        return response
    }
    
    /**
     * 将Bitmap转换为Base64字符串
     */
    fun bitmapToBase64(bitmap: Bitmap, quality: Int = 80): String {
        return try {
            val start = System.currentTimeMillis()
            val width = bitmap.width
            val height = bitmap.height
            val outputStream = ByteArrayOutputStream()
            val compressedOk = bitmap.compress(Bitmap.CompressFormat.JPEG, quality, outputStream)
            val compressedMs = System.currentTimeMillis() - start
            val byteArray = outputStream.toByteArray()
            outputStream.close()
            val bytesLen = byteArray.size
            val b64Start = System.currentTimeMillis()
            val base64 = Base64.encodeToString(byteArray, Base64.NO_WRAP)
            val b64Ms = System.currentTimeMillis() - b64Start
            Log.d(TAG, "截图编码: size=${width}x${height}, jpegQuality=$quality, jpegBytes=${bytesLen}B, jpegTime=${compressedMs}ms, base64Len=${base64.length} chars, base64Time=${b64Ms}ms, total=${System.currentTimeMillis()-start}ms")
            if (!compressedOk) {
                Log.w(TAG, "Bitmap.compress 返回false，可能编码失败")
            }
            base64
        } catch (e: Exception) {
            Log.e(TAG, "Bitmap转Base64失败", e)
            ""
        }
    }
}

