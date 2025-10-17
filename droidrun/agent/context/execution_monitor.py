"""
执行监控系统 - 监控执行过程，检测异常，触发回退
"""
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum
import time
import logging
import json
import re

logger = logging.getLogger("droidrun")

class MonitorStatus(Enum):
    NORMAL = "normal"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

@dataclass
class MonitorResult:
    status: MonitorStatus
    message: str
    confidence: float
    fallback_needed: bool
    fallback_type: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

class ExecutionMonitor:
    """执行监控器"""
    
    def __init__(self, llm=None):
        self.llm = llm
        self.execution_history: List[Dict] = []
        self.performance_metrics: Dict[str, Any] = {}
        self.step_start_time: Optional[float] = None
        self.consecutive_failures: int = 0
        self.max_consecutive_failures: int = 3
        
        logger.info("🔍 ExecutionMonitor initialized")
    
    def start_step_monitoring(self, step_data: Dict):
        """开始监控单个步骤"""
        self.step_start_time = time.time()
        self.execution_history.append({
            "step": len(self.execution_history) + 1,
            "start_time": self.step_start_time,
            "data": step_data
        })
        logger.debug(f"🔍 Started monitoring step {len(self.execution_history)}")
    
    def monitor_step(self, step_data: Dict) -> MonitorResult:
        """监控单个执行步骤"""
        try:
            # 计算执行时间 - 修复：使用当前时间而不是step_start_time
            current_time = time.time()
            execution_time = current_time - self.step_start_time if self.step_start_time else 0
            
            # 如果这是任务完成的情况，不进行超时检查
            if step_data.get("success", False) and step_data.get("steps", 0) > 10:
                logger.info(f"🎯 Task completed successfully with {step_data.get('steps', 0)} steps, skipping timeout check")
                return MonitorResult(
                    status=MonitorStatus.NORMAL,
                    message="Task completed successfully",
                    confidence=1.0,
                    fallback_needed=False
                )
            
            # 基本检查
            basic_result = self._check_basic_metrics(step_data, execution_time)
            if basic_result.fallback_needed:
                return basic_result
            
            # 使用LLM进行深度分析
            if self.llm:
                llm_result = self._llm_analyze_step(step_data, execution_time)
                if llm_result.fallback_needed:
                    return llm_result
            
            # 更新性能指标
            self._update_performance_metrics(step_data, execution_time)
            
            return MonitorResult(
                status=MonitorStatus.NORMAL,
                message="Step execution normal",
                confidence=0.9,
                fallback_needed=False
            )
            
        except Exception as e:
            logger.error(f"Error in step monitoring: {e}")
            return MonitorResult(
                status=MonitorStatus.ERROR,
                message=f"Monitoring error: {str(e)}",
                confidence=0.5,
                fallback_needed=True,
                fallback_type="monitoring_error"
            )
    
    def _check_basic_metrics(self, step_data: Dict, execution_time: float) -> MonitorResult:
        """基本指标检查"""
        # 检查执行时间 - 对于LLM调用，180秒内都是正常的（增加超时时间）
        # 修复：只有在单步执行时间过长时才触发超时，而不是累计时间
        if execution_time > 180:  # 超过180秒认为异常
            return MonitorResult(
                status=MonitorStatus.WARNING,
                message=f"Step execution time too long: {execution_time:.2f}s",
                confidence=0.8,
                fallback_needed=True,
                fallback_type="timeout"
            )
        
        # 检查连续失败
        if step_data.get("success", True) == False:
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.max_consecutive_failures:
                return MonitorResult(
                    status=MonitorStatus.CRITICAL,
                    message=f"Too many consecutive failures: {self.consecutive_failures}",
                    confidence=0.9,
                    fallback_needed=True,
                    fallback_type="consecutive_failures"
                )
        else:
            self.consecutive_failures = 0
        
        # 检查步骤数量
        if len(self.execution_history) > 20:  # 超过20步认为可能有问题
            return MonitorResult(
                status=MonitorStatus.WARNING,
                message=f"Too many steps executed: {len(self.execution_history)}",
                confidence=0.7,
                fallback_needed=True,
                fallback_type="too_many_steps"
            )
        
        return MonitorResult(
            status=MonitorStatus.NORMAL,
            message="Basic checks passed",
            confidence=0.8,
            fallback_needed=False
        )
    
    def _llm_analyze_step(self, step_data: Dict, execution_time: float) -> MonitorResult:
        """使用LLM分析步骤执行"""
        try:
            prompt = f"""
分析以下执行步骤是否存在异常：

步骤数据: {step_data}
执行时间: {execution_time:.2f}秒
历史步骤数: {len(self.execution_history)}

注意：
- 对于移动应用操作，10-20个步骤是正常的
- 只有在步骤数少于3个或超过50个时才考虑异常
- 任务成功完成（如显示"提交成功"）不应被视为异常

请分析并返回JSON格式：
{{
    "has_anomaly": true/false,
    "anomaly_type": "类型",
    "confidence": 0.0-1.0,
    "suggestion": "建议"
}}
"""
            response = self.llm.complete(prompt)
            
            # 解析LLM响应
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if json_match:
                analysis = json.loads(json_match.group())
                
                if analysis.get("has_anomaly", False):
                    return MonitorResult(
                        status=MonitorStatus.WARNING,
                        message=f"LLM detected anomaly: {analysis.get('anomaly_type', 'unknown')}",
                        confidence=analysis.get("confidence", 0.7),
                        fallback_needed=True,
                        fallback_type=analysis.get("anomaly_type", "llm_detected"),
                        details=analysis
                    )
            
            return MonitorResult(
                status=MonitorStatus.NORMAL,
                message="LLM analysis passed",
                confidence=0.8,
                fallback_needed=False
            )
            
        except Exception as e:
            logger.warning(f"LLM analysis failed: {e}")
            return MonitorResult(
                status=MonitorStatus.NORMAL,
                message="LLM analysis skipped",
                confidence=0.5,
                fallback_needed=False
            )
    
    def detect_anomaly(self, execution_log: List[Dict]) -> MonitorResult:
        """检测执行异常"""
        try:
            if not execution_log:
                return MonitorResult(
                    status=MonitorStatus.NORMAL,
                    message="No execution log to analyze",
                    confidence=1.0,
                    fallback_needed=False
                )
            
            # 基本统计检查
            success_count = sum(1 for step in execution_log if step.get("success", False))
            total_steps = len(execution_log)
            success_rate = success_count / total_steps if total_steps > 0 else 0
            
            if success_rate < 0.5:  # 成功率低于50%
                return MonitorResult(
                    status=MonitorStatus.ERROR,
                    message=f"Low success rate: {success_rate:.2%}",
                    confidence=0.9,
                    fallback_needed=True,
                    fallback_type="low_success_rate"
                )
            
            # 使用LLM进行深度分析
            if self.llm:
                return self._llm_analyze_execution(execution_log)
            
            return MonitorResult(
                status=MonitorStatus.NORMAL,
                message="Execution analysis passed",
                confidence=0.8,
                fallback_needed=False
            )
            
        except Exception as e:
            logger.error(f"Error in anomaly detection: {e}")
            return MonitorResult(
                status=MonitorStatus.ERROR,
                message=f"Anomaly detection error: {str(e)}",
                confidence=0.5,
                fallback_needed=True,
                fallback_type="detection_error"
            )
    
    def _llm_analyze_execution(self, execution_log: List[Dict]) -> MonitorResult:
        """使用LLM分析整个执行过程"""
        try:
            prompt = f"""
分析以下执行日志，检测是否存在异常：

执行日志: {execution_log}

请分析并返回JSON格式：
{{
    "has_anomaly": true/false,
    "anomaly_type": "异常类型",
    "confidence": 0.0-1.0,
    "description": "异常描述",
    "suggestion": "建议的回退策略"
}}
"""
            response = self.llm.complete(prompt)
            
            # 解析LLM响应
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if json_match:
                analysis = json.loads(json_match.group())
                
                if analysis.get("has_anomaly", False):
                    return MonitorResult(
                        status=MonitorStatus.ERROR,
                        message=f"LLM detected execution anomaly: {analysis.get('description', 'unknown')}",
                        confidence=analysis.get("confidence", 0.8),
                        fallback_needed=True,
                        fallback_type=analysis.get("anomaly_type", "llm_detected"),
                        details=analysis
                    )
            
            return MonitorResult(
                status=MonitorStatus.NORMAL,
                message="LLM execution analysis passed",
                confidence=0.8,
                fallback_needed=False
            )
            
        except Exception as e:
            logger.warning(f"LLM execution analysis failed: {e}")
            return MonitorResult(
                status=MonitorStatus.NORMAL,
                message="LLM execution analysis skipped",
                confidence=0.5,
                fallback_needed=False
            )
    
    def suggest_fallback(self, anomaly: MonitorResult) -> str:
        """建议回退策略"""
        fallback_strategies = {
            "timeout": "重新开始执行，使用更短的超时时间",
            "consecutive_failures": "回退到冷启动模式，重新规划任务",
            "too_many_steps": "简化任务目标，分解为更小的步骤",
            "low_success_rate": "使用不同的执行策略或工具",
            "llm_detected": anomaly.details.get("suggestion", "根据LLM建议调整执行策略") if anomaly.details else "使用备用执行方案"
        }
        
        strategy = fallback_strategies.get(anomaly.fallback_type, "使用默认回退策略")
        logger.info(f"🔄 Suggested fallback strategy: {strategy}")
        return strategy
    
    def _update_performance_metrics(self, step_data: Dict, execution_time: float):
        """更新性能指标"""
        self.performance_metrics.update({
            "total_steps": len(self.execution_history),
            "avg_execution_time": (self.performance_metrics.get("avg_execution_time", 0) + execution_time) / 2,
            "last_step_time": execution_time,
            "success_rate": self._calculate_success_rate()
        })
    
    def _calculate_success_rate(self) -> float:
        """计算成功率"""
        if not self.execution_history:
            return 1.0
        
        success_count = sum(1 for step in self.execution_history if step.get("data", {}).get("success", True))
        return success_count / len(self.execution_history)
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """获取性能摘要"""
        return {
            "total_steps": len(self.execution_history),
            "consecutive_failures": self.consecutive_failures,
            "success_rate": self._calculate_success_rate(),
            "performance_metrics": self.performance_metrics
        }
    
    def reset(self):
        """重置监控器状态"""
        self.execution_history = []
        self.performance_metrics = {}
        self.step_start_time = None
        self.consecutive_failures = 0
        logger.info("🔄 ExecutionMonitor reset")

