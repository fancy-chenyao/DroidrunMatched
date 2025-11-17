package Agent

import android.util.Log
import controller.GenericElement
import java.util.concurrent.ConcurrentHashMap

/**
 * 增量索引管理器
 * 维护元素的持久化索引，确保同一元素在页面变化后保持相同索引
 */
object IncrementalIndexManager {
    private const val TAG = "IncrementalIndexManager"
    
    // 控制是否打印调试信息
    private var isDebugEnabled = false
    
    // 元素唯一ID到索引的映射
    private val elementIdToIndex = ConcurrentHashMap<String, Int>()
    
    // 索引到元素ID的反向映射（用于调试和验证）
    private val indexToElementId = ConcurrentHashMap<Int, String>()
    
    // 下一个可用的索引值
    private var nextAvailableIndex = 1
    
    // 已隐藏元素的索引集合（保留不被重用）
    private val reservedIndexes = mutableSetOf<Int>()
    
    /**
     * 调试日志输出函数
     */
    private fun debugLog(message: String) {
        if (isDebugEnabled) {
            Log.d(TAG, message)
        }
    }
    
    /**
     * 设置调试模式
     */
    fun setDebugEnabled(enabled: Boolean) {
        isDebugEnabled = enabled
    }
    
    /**
     * 为元素树分配增量索引
     * @param elements 当前页面的所有元素列表
     * @return 元素到索引的映射
     */
    fun assignIncrementalIndexes(elements: List<GenericElement>): Map<GenericElement, Int> {
        val result = mutableMapOf<GenericElement, Int>()
        val currentElementIds = mutableSetOf<String>()
        
        debugLog("开始分配增量索引，当前元素数量: ${elements.size}")
        
        // 为每个元素分配索引
        elements.forEach { element ->
            val elementId = generateElementId(element)
            currentElementIds.add(elementId)
            
            val index = getOrAssignIndex(elementId, element)
            result[element] = index
        }
        
        // 标记不再存在的元素为隐藏状态
        markHiddenElements(currentElementIds)
        
        debugLog("索引分配完成，活跃元素: ${elements.size}, 保留索引: ${reservedIndexes.size}, 下一个索引: $nextAvailableIndex")
        
        return result
    }
    
    /**
     * 生成元素的唯一标识
     * 使用稳定属性组合，排除动态变化的resourceId
     */
    private fun generateElementId(element: GenericElement): String {
        val stableProps = listOf(
            element.className,
            element.text,
            element.contentDesc,
            "${element.bounds.left},${element.bounds.top},${element.bounds.right},${element.bounds.bottom}",
            element.clickable.toString(),
            element.enabled.toString(),
            element.checkable.toString(),
            element.scrollable.toString()
        ).joinToString("|")
        
        // 使用哈希值作为唯一ID，但保持可读性
        val hash = stableProps.hashCode()
        return "elem_${Math.abs(hash)}"
    }
    
    /**
     * 获取或分配元素索引
     */
    private fun getOrAssignIndex(elementId: String, element: GenericElement): Int {
        // 检查是否已有索引
        val existingIndex = elementIdToIndex[elementId]
        if (existingIndex != null) {
            // 元素重新出现，从保留索引中移除
            reservedIndexes.remove(existingIndex)
            debugLog("元素重新出现: $elementId -> 索引 $existingIndex")
            return existingIndex
        }
        
        // 分配新索引
        val newIndex = allocateNewIndex()
        elementIdToIndex[elementId] = newIndex
        indexToElementId[newIndex] = elementId
        
        debugLog("新元素分配索引: [${element.className}:${element.text}:${element.contentDesc}] -> 索引 $newIndex")
        return newIndex
    }
    
    /**
     * 分配新的索引值
     */
    private fun allocateNewIndex(): Int {
        // 跳过已保留的索引
        while (reservedIndexes.contains(nextAvailableIndex) || 
               indexToElementId.containsKey(nextAvailableIndex)) {
            nextAvailableIndex++
        }
        
        val index = nextAvailableIndex
        nextAvailableIndex++
        return index
    }
    
    /**
     * 标记不再存在的元素为隐藏状态
     */
    private fun markHiddenElements(currentElementIds: Set<String>) {
        val hiddenElements = elementIdToIndex.keys - currentElementIds
        
        hiddenElements.forEach { elementId ->
            val index = elementIdToIndex[elementId]
            if (index != null) {
                reservedIndexes.add(index)
                debugLog("元素隐藏，保留索引: $elementId -> 索引 $index")
            }
        }
        
        if (hiddenElements.isNotEmpty()) {
            debugLog("标记 ${hiddenElements.size} 个元素为隐藏状态")
        }
    }
    
    /**
     * 清理长期未使用的索引（可选的垃圾回收机制）
     * @param maxReservedCount 最大保留索引数量
     */
    fun cleanupOldIndexes(maxReservedCount: Int = 100) {
        if (reservedIndexes.size > maxReservedCount) {
            val sortedReserved = reservedIndexes.sorted()
            val toRemove = sortedReserved.take(reservedIndexes.size - maxReservedCount)
            
            toRemove.forEach { index ->
                reservedIndexes.remove(index)
                val elementId = indexToElementId.remove(index)
                elementIdToIndex.remove(elementId)
            }
            
            debugLog("清理了 ${toRemove.size} 个长期未使用的索引")
        }
    }
    
    /**
     * 重置索引管理器（用于测试或特殊场景）
     */
    fun reset() {
        elementIdToIndex.clear()
        indexToElementId.clear()
        reservedIndexes.clear()
        nextAvailableIndex = 1
        debugLog("索引管理器已重置")
    }
    
    /**
     * 获取当前状态信息（用于调试）
     */
    fun getStatusInfo(): String {
        return "活跃映射: ${elementIdToIndex.size}, 保留索引: ${reservedIndexes.size}, 下一个索引: $nextAvailableIndex"
    }
}
