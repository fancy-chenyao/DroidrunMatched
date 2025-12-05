"""WebSocket 消息处理扩展

处理交互式执行的 WebSocket 消息（问题和答案）
"""

import asyncio
import logging
from typing import Dict, Any, Optional

from .manager import InteractionManager

logger = logging.getLogger(__name__)


class InteractionWebSocketHandler:
    """交互式执行的 WebSocket 消息处理器
    
    负责：
    1. 处理发送到 Android 端的问题消息
    2. 处理从 Android 端接收的答案消息
    3. 将答案路由到对应的 InteractionManager
    
    Example:
        >>> handler = InteractionWebSocketHandler(interaction_manager)
        >>> 
        >>> # 处理答案消息
        >>> await handler.handle_answer_message(message)
    """
    
    def __init__(self, interaction_manager: InteractionManager):
        """初始化处理器
        
        Args:
            interaction_manager: InteractionManager 实例
        """
        self.interaction_manager = interaction_manager
        self._pending_questions: Dict[str, Dict[str, Any]] = {}
    
    async def handle_question_message(
        self,
        message: Dict[str, Any],
        websocket_send_callback: callable
    ) -> Dict[str, Any]:
        """处理问题消息（服务器 → Android）
        
        当 LLM 调用 ask_user() 时，这个方法负责：
        1. 验证消息格式
        2. 保存问题信息
        3. 通过 WebSocket 发送到 Android 端
        
        Args:
            message: 问题消息
                {
                    "type": "question",
                    "question_id": "q-abc123",
                    "question_text": "请输入用户名",
                    "question_type": "text|choice|confirm",
                    "options": [...],  # 可选
                    "default_value": "默认值",  # 可选
                    "timeout_seconds": 60.0
                }
            websocket_send_callback: 发送消息到 WebSocket 的回调函数
        
        Returns:
            响应消息
        """
        try:
            # 验证消息
            question_id = message.get("question_id")
            if not question_id:
                return {
                    "status": "error",
                    "error": "Missing question_id"
                }
            
            question_type = message.get("question_type", "text")
            if question_type not in ["text", "choice", "confirm"]:
                return {
                    "status": "error",
                    "error": f"Invalid question_type: {question_type}"
                }
            
            # 保存问题信息（用于后续路由答案）
            self._pending_questions[question_id] = {
                "question_id": question_id,
                "question_text": message.get("question_text"),
                "question_type": question_type,
                "created_at": asyncio.get_event_loop().time()
            }
            
            # 发送到 Android 端
            await websocket_send_callback({
                "type": "user_question",
                "question_id": question_id,
                "question_text": message.get("question_text"),
                "question_type": question_type,
                "options": message.get("options", []),
                "default_value": message.get("default_value"),
                "timeout_seconds": message.get("timeout_seconds", 60.0)
            })
            
            logger.info(f"Question sent to Android: {question_id}")
            
            return {
                "status": "success",
                "question_id": question_id
            }
        
        except Exception as e:
            logger.error(f"Error handling question message: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    async def handle_answer_message(
        self,
        message: Dict[str, Any]
    ) -> Dict[str, Any]:
        """处理答案消息（Android → 服务器）
        
        当用户在 Android 端回答问题后，这个方法负责：
        1. 验证消息格式
        2. 查找对应的问题
        3. 将答案路由到 InteractionManager
        
        Args:
            message: 答案消息
                {
                    "type": "user_answer",
                    "question_id": "q-abc123",
                    "answer": "用户的答案",
                    "additional_data": {...}  # 可选
                }
        
        Returns:
            响应消息
        """
        try:
            # 验证消息
            question_id = message.get("question_id")
            if not question_id:
                return {
                    "status": "error",
                    "error": "Missing question_id"
                }
            
            answer = message.get("answer")
            if answer is None:
                return {
                    "status": "error",
                    "error": "Missing answer"
                }
            
            # 检查问题是否存在
            if question_id not in self._pending_questions:
                logger.warning(f"Answer for unknown question: {question_id}")
                # 仍然尝试提供答案（可能是延迟到达的答案）
            
            # 路由答案到 InteractionManager
            success = await self.interaction_manager.provide_answer(
                question_id=question_id,
                answer=answer,
                additional_data=message.get("additional_data")
            )
            
            if success:
                # 清理已回答的问题
                if question_id in self._pending_questions:
                    del self._pending_questions[question_id]
                
                logger.info(f"Answer received and processed: {question_id}")
                
                return {
                    "status": "success",
                    "question_id": question_id
                }
            else:
                logger.warning(f"Failed to process answer: {question_id}")
                return {
                    "status": "error",
                    "error": "Question not found or already answered"
                }
        
        except Exception as e:
            logger.error(f"Error handling answer message: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    def get_pending_questions(self) -> Dict[str, Dict[str, Any]]:
        """获取所有待回答的问题
        
        Returns:
            问题ID到问题信息的映射
        """
        return self._pending_questions.copy()
    
    def cleanup_old_questions(self, max_age_seconds: float = 300.0):
        """清理超时的问题
        
        Args:
            max_age_seconds: 问题的最大存活时间（秒）
        """
        current_time = asyncio.get_event_loop().time()
        expired_ids = []
        
        for question_id, info in self._pending_questions.items():
            age = current_time - info["created_at"]
            if age > max_age_seconds:
                expired_ids.append(question_id)
        
        for question_id in expired_ids:
            del self._pending_questions[question_id]
            logger.info(f"Cleaned up expired question: {question_id}")
        
        return len(expired_ids)
    
    def __repr__(self) -> str:
        """字符串表示"""
        return (
            f"InteractionWebSocketHandler("
            f"pending_questions={len(self._pending_questions)})"
        )
