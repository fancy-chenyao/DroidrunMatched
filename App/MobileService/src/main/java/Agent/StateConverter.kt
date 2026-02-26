package Agent

import android.app.Activity
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.util.Base64
import android.util.Log
import controller.GenericElement
import controller.UIUtils
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 返回a11y_tree和稳定索引映射的数据类
 */
data class A11yTreeResult(
    val a11yTree: JSONArray,
    val stableIndexMap: Map<GenericElement, Int>
)

/**
 * 数据格式转换工具
 * 用于将APP端的数据格式转换为服务端期望的格式
 */
object StateConverter {
    
    private const val TAG = "StateConverter"
    
    // 调试开关：是否保存原始元素树和XML文件
    private const val SAVE_DEBUG_FILES = true
    
    /**
     * 保存原始元素树到本地文件（调试用）
     */
    private fun saveOriginalElementTree(element: GenericElement, context: Context?) {
        if (!SAVE_DEBUG_FILES) return  // 开关控制
        
        try {
            if (context == null) return
            
            // 使用指定的外部存储路径
            val outputDir = File("/storage/0000-0000/Android/data/com.example.emplab/files/xml")
            if (!outputDir.exists()) {
                outputDir.mkdirs()
            }
            
            // 生成文件名
            val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(Date())
            val originalFile = File(outputDir, "original_element_tree_${timestamp}.txt")
            
            // 保存原始元素树的可读格式
            val originalContent = element.toFormattedString()
            originalFile.writeText(originalContent, Charsets.UTF_8)
            
            Log.d(TAG, "原始元素树已保存: ${originalFile.absolutePath}")
            
        } catch (e: Exception) {
            Log.e(TAG, "保存原始元素树失败", e)
        }
    }
    
    /**
     * 将GenericElement转换为XML字符串并保存到本地文件（调试用）
     */
    private fun saveElementTreeAsXml(element: GenericElement, context: Context?) {
        if (!SAVE_DEBUG_FILES) return  // 开关控制
        
        try {
            if (context == null) return
            
            // 使用指定的外部存储路径
            val outputDir = File("/storage/0000-0000/Android/data/com.example.emplab/files/xml")
            if (!outputDir.exists()) {
                outputDir.mkdirs()
            }
            
            // 生成文件名
            val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(Date())
            val xmlFile = File(outputDir, "element_tree_${timestamp}.xml")
            
            // 转换为XML格式
            val xmlContent = convertGenericElementToXmlString(element)
            xmlFile.writeText(xmlContent, Charsets.UTF_8)
            
            Log.d(TAG, "XML元素树已保存: ${xmlFile.absolutePath}")
            
        } catch (e: Exception) {
            Log.e(TAG, "保存XML元素树失败", e)
        }
    }
    
    /**
     * 保存JSON数组到本地文件（调试用）
     */
    private fun saveJsonArray(jsonArray: JSONArray, context: Context?) {
        if (!SAVE_DEBUG_FILES) return  // 开关控制
        
        try {
            if (context == null) return
            
            // 使用指定的外部存储路径
            val outputDir = File("/storage/0000-0000/Android/data/com.example.emplab/files/xml")
            if (!outputDir.exists()) {
                outputDir.mkdirs()
            }
            
            // 生成文件名
            val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(Date())
            val jsonFile = File(outputDir, "a11y_tree_${timestamp}.json")
            
            // 保存JSON格式
            val jsonContent = jsonArray.toString(2) // 缩进2个空格，便于阅读
            jsonFile.writeText(jsonContent, Charsets.UTF_8)
            
            Log.d(TAG, "JSON数组已保存: ${jsonFile.absolutePath}")
            
        } catch (e: Exception) {
            Log.e(TAG, "保存JSON数组失败", e)
        }
    }
    
    /**
     * 将GenericElement转换为XML字符串
     */
    private fun convertGenericElementToXmlString(element: GenericElement): String {
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<hierarchy>
${element.children.joinToString("") { it.toXmlString(1) }}
</hierarchy>"""
    }
    
    /**
     * 计算元素的稳定哈希值，用于生成稳定索引
     */
    private fun calculateStableHash(element: GenericElement): String {
        // 使用稳定属性组合生成哈希，排除动态生成的resource-id
        val stableProps = listOf(
            element.className,
            element.text,
            element.contentDesc,
            "${element.bounds.left},${element.bounds.top},${element.bounds.right},${element.bounds.bottom}",
            element.clickable.toString(),
            element.enabled.toString()
        ).joinToString("|")
        
        return stableProps.hashCode().toString()
    }
    
    /**
     * 收集所有元素并生成稳定索引映射
     */
    private fun collectElementsWithStableIndex(element: GenericElement): List<Pair<GenericElement, Int>> {
        val allElements = mutableListOf<GenericElement>()
        
        // 递归收集所有元素
        fun collectElements(e: GenericElement) {
            allElements.add(e)
            e.children.forEach { child ->
                collectElements(child)
            }
        }
        
        collectElements(element)
        
        // 使用稳定索引管理器分配索引
        val indexMap = StableIndexManager.assignStableIndexes(allElements)
        
        // 转换为List<Pair>格式
        return allElements.map { elem -> elem to indexMap[elem]!! }
    }
    
    /**
     * 计算元素在树中的路径，用于处理哈希冲突
     */
    private fun calculateElementPath(root: GenericElement, target: GenericElement): String {
        fun findPath(current: GenericElement, path: String): String? {
            if (current === target) return path
            
            current.children.forEachIndexed { index, child ->
                val childPath = findPath(child, "$path/$index")
                if (childPath != null) return childPath
            }
            return null
        }
        
        return findPath(root, "") ?: ""
    }
    
    /**
     * 获取稳定索引映射（公共方法）
     */
    fun getStableIndexMap(element: GenericElement): Map<GenericElement, Int> {
        return collectElementsWithStableIndex(element).toMap()
    }
    
    /**
     * 将GenericElement树转换为a11y_tree格式（使用稳定索引）
     * @return A11yTreeResult 包含a11y_tree和稳定索引映射
     */
    fun convertElementTreeToA11yTreePruned(element: GenericElement, context: Context? = null): A11yTreeResult {
        // 保存原始元素树和XML到本地文件
        saveOriginalElementTree(element, context)
        saveElementTreeAsXml(element, context)
        
        // 生成稳定索引映射
        val stableIndexMap = collectElementsWithStableIndex(element).toMap()
        
        // 调试日志：输出索引映射信息
        Log.d(TAG, "生成稳定索引映射，共${stableIndexMap.size}个元素")
        Log.d(TAG, "索引管理器状态: ${StableIndexManager.getStatusInfo()}")
        
        if (SAVE_DEBUG_FILES) {
            stableIndexMap.entries.take(5).forEach { (elem, stableIndex) ->
                Log.d(TAG, "元素[${elem.className}:${elem.text}:${elem.contentDesc}] 原索引=${elem.index} 稳定索引=$stableIndex")
            }
            
            // 特别关注"请休假"相关元素
            stableIndexMap.entries.filter { 
                it.key.text.contains("请休假") || it.key.contentDesc.contains("请休假") 
            }.forEach { (elem, stableIndex) ->
                Log.d(TAG, "🎯请休假元素: [${elem.className}:${elem.text}:${elem.contentDesc}] 稳定索引=$stableIndex bounds=${elem.bounds}")
            }
        }
        
        val result = JSONArray()
        
        fun recurse(e: GenericElement, parent: JSONArray) {
            val obj = JSONObject()
            // 使用稳定索引替代原始index
            obj.put("index", stableIndexMap[e] ?: e.index)
            
            // 优先使用additionalProps中的resourceName，构造完整的resourceId
            val resourceName = e.additionalProps["resourceName"]
            val finalResourceId = if (!resourceName.isNullOrEmpty()) {
                "com.example.emplab:id/$resourceName"
            } else {
                e.resourceId
            }
            obj.put("resourceId", finalResourceId)
            
            obj.put("className", e.className)
            
            // text字段：对于表单输入元素（INPUT、TEXTAREA、SELECT），优先使用text（实际输入值）
            // 对于其他元素，优先使用contentDesc，如果为空则使用text
            val isFormInput = e.className.equals("INPUT", ignoreCase = true) || 
                             e.className.equals("TEXTAREA", ignoreCase = true) || 
                             e.className.equals("SELECT", ignoreCase = true)
            
            val displayText = when {
                isFormInput && e.text.isNotEmpty() -> e.text  // 表单元素：优先text（实际值）
                e.contentDesc.isNotEmpty() -> e.contentDesc   // 其他元素：优先contentDesc
                e.text.isNotEmpty() -> e.text                 // 回退到text
                else -> e.className                           // 最后回退到className
            }
            obj.put("text", displayText)
            
            // bounds格式：转为字符串 "left, top, right, bottom"
            obj.put("bounds", "${e.bounds.left}, ${e.bounds.top}, ${e.bounds.right}, ${e.bounds.bottom}")
            
            // 添加无障碍属性，让JSON更贴合无障碍树
            obj.put("clickable", e.clickable)
            obj.put("enabled", e.enabled)
            obj.put("checkable", e.checkable)
            obj.put("checked", e.checked)
            obj.put("scrollable", e.scrollable)
            obj.put("longClickable", e.longClickable)
            obj.put("selected", e.selected)
            
            // 递归处理所有子节点，无深度和数量限制
            if (e.children.isNotEmpty()) {
                val arr = JSONArray()
                for (child in e.children) {
                    recurse(child, arr)
                }
                obj.put("children", arr)
            } else {
                // 叶子节点也添加空的children数组
                obj.put("children", JSONArray())
            }
            
            parent.put(obj)
        }
        
        recurse(element, result)
        
        // 保存JSON数组到本地文件
        saveJsonArray(result, context)
        
        return A11yTreeResult(result, stableIndexMap)
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
            // 转换元素树（使用无限制版本）
            val a11yTree = convertElementTreeToA11yTreePruned(elementTree, activity)
            response.put("a11y_tree", a11yTree as Any)
            
            // 获取设备状态
            val phoneState = getPhoneState(activity)
            response.put("phone_state", phoneState as Any)
            
            // 不在此处执行网络上传，避免主线程网络。截图引用由调用方负责上传并注入。
            
        } catch (e: Exception) {
            Log.e(TAG, "构建状态响应时发生异常", e)
            // 返回空的数据结构
            response.put("a11y_tree", JSONArray() as Any)
            response.put("phone_state", getPhoneState(null) as Any)
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

