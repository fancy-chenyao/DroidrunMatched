package Agent

import android.util.Log
import controller.GenericElement

/**
 * 稳定索引管理器
 * 使用 DFS 遍历顺序为元素分配稳定的索引，模拟 Android Accessibility Service 的行为
 * 
 * 核心原则：
 * 1. 索引基于自然 View 树顺序（DFS 遍历）
 * 2. 不使用坐标排序
 * 3. 每次调用 assignStableIndexes 时从 0 开始
 * 4. 索引在页面不变的情况下保持稳定
 */
object StableIndexManager {
    
    private const val TAG = "StableIndexManager"
    
    /**
     * 为元素列表分配稳定索引
     * 
     * @param elements 元素列表（已按 DFS 顺序收集）
     * @return 元素到索引的映射
     */
    fun assignStableIndexes(elements: List<GenericElement>): Map<GenericElement, Int> {
        val indexMap = mutableMapOf<GenericElement, Int>()
        
        // 直接按照 DFS 遍历顺序分配索引（从 0 开始）
        elements.forEachIndexed { index, element ->
            indexMap[element] = index
        }
        
        Log.d(TAG, "分配稳定索引完成，共 ${elements.size} 个元素，索引范围: 0-${elements.size - 1}")
        
        return indexMap
    }
    
    /**
     * 获取状态信息（用于调试）
     */
    fun getStatusInfo(): String {
        return "StableIndexManager: 使用 DFS 遍历顺序，无坐标排序"
    }
}
