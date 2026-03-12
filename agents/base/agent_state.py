"""
Agent状态定义与状态机

本模块定义了Agent的生命周期状态和状态转换规则。
所有Agent在执行过程中都会经历这些状态，状态机确保状态转换的合法性。

状态流转图:
    IDLE -> INITIALIZING -> LOADING_DATA -> ANALYZING -> GENERATING_OUTPUT -> COMPLETED
      |         |              |              |                |
      v         v              v              v                v
    ERROR <---- ERROR <------- ERROR <------- ERROR <--------- ERROR
"""

from enum import Enum
from typing import Optional, Set, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """
    Agent状态枚举
    
    状态说明:
        IDLE: 空闲状态，Agent已创建但未开始执行任务
        INITIALIZING: 初始化中，正在加载配置、建立连接
        LOADING_DATA: 加载数据中，正在从数据库或API获取数据
        ANALYZING: 分析中，正在执行核心分析逻辑
        GENERATING_OUTPUT: 生成输出中，正在整理结果、写入数据库
        COMPLETED: 已完成，任务执行完毕
        ERROR: 错误状态，执行过程中发生异常
    """
    IDLE = "idle"
    INITIALIZING = "initializing"
    LOADING_DATA = "loading_data"
    ANALYZING = "analyzing"
    GENERATING_OUTPUT = "generating_output"
    COMPLETED = "completed"
    ERROR = "error"
    
    def __str__(self) -> str:
        return self.value


VALID_TRANSITIONS: Dict[AgentState, Set[AgentState]] = {
    AgentState.IDLE: {
        AgentState.INITIALIZING,
        AgentState.ERROR,
    },
    AgentState.INITIALIZING: {
        AgentState.LOADING_DATA,
        AgentState.ERROR,
        AgentState.IDLE,
    },
    AgentState.LOADING_DATA: {
        AgentState.ANALYZING,
        AgentState.ERROR,
        AgentState.IDLE,
    },
    AgentState.ANALYZING: {
        AgentState.GENERATING_OUTPUT,
        AgentState.ERROR,
        AgentState.IDLE,
    },
    AgentState.GENERATING_OUTPUT: {
        AgentState.COMPLETED,
        AgentState.ERROR,
        AgentState.IDLE,
    },
    AgentState.COMPLETED: {
        AgentState.IDLE,
    },
    AgentState.ERROR: {
        AgentState.IDLE,
        AgentState.INITIALIZING,
    },
}


class StateTransitionError(Exception):
    """状态转换异常"""
    def __init__(self, from_state: AgentState, to_state: AgentState, message: str = ""):
        self.from_state = from_state
        self.to_state = to_state
        self.message = message or f"非法状态转换: {from_state} -> {to_state}"
        super().__init__(self.message)


class AgentStateMachine:
    """
    Agent状态机
    
    管理Agent的状态转换，确保状态变更符合预定义的规则。
    提供状态历史记录和转换日志功能。
    
    使用示例:
        state_machine = AgentStateMachine(agent_id="market_analyst_001")
        
        state_machine.transition(AgentState.INITIALIZING)
        state_machine.transition(AgentState.LOADING_DATA)
        state_machine.transition(AgentState.ANALYZING)
        state_machine.transition(AgentState.GENERATING_OUTPUT)
        state_machine.transition(AgentState.COMPLETED)
        
        state_machine.reset()
    """
    
    def __init__(self, agent_id: str, initial_state: AgentState = AgentState.IDLE):
        """
        初始化状态机
        
        Args:
            agent_id: Agent唯一标识，用于日志追踪
            initial_state: 初始状态，默认为IDLE
        """
        self._agent_id = agent_id
        self._current_state = initial_state
        self._previous_state: Optional[AgentState] = None
        self._state_history: list = []
        self._last_transition_time: Optional[datetime] = None
        self._error_message: Optional[str] = None
        
        self._record_transition(initial_state, "初始化")
        logger.debug(f"[{self._agent_id}] 状态机初始化完成，当前状态: {self._current_state}")
    
    @property
    def current_state(self) -> AgentState:
        """获取当前状态"""
        return self._current_state
    
    @property
    def previous_state(self) -> Optional[AgentState]:
        """获取前一状态"""
        return self._previous_state
    
    @property
    def state_history(self) -> list:
        """获取状态历史记录"""
        return self._state_history.copy()
    
    @property
    def error_message(self) -> Optional[str]:
        """获取错误信息（仅在ERROR状态时有值）"""
        return self._error_message
    
    def can_transition_to(self, target_state: AgentState) -> bool:
        """
        检查是否可以转换到目标状态
        
        Args:
            target_state: 目标状态
            
        Returns:
            是否可以转换
        """
        valid_targets = VALID_TRANSITIONS.get(self._current_state, set())
        return target_state in valid_targets
    
    def transition(self, target_state: AgentState, reason: str = "") -> AgentState:
        """
        执行状态转换
        
        Args:
            target_state: 目标状态
            reason: 转换原因（可选）
            
        Returns:
            转换后的状态
            
        Raises:
            StateTransitionError: 非法状态转换时抛出
        """
        if not self.can_transition_to(target_state):
            raise StateTransitionError(
                self._current_state, 
                target_state,
                f"[{self._agent_id}] 非法状态转换: {self._current_state} -> {target_state}"
            )
        
        old_state = self._current_state
        self._previous_state = old_state
        self._current_state = target_state
        self._last_transition_time = datetime.now()
        
        if target_state != AgentState.ERROR:
            self._error_message = None
        
        self._record_transition(target_state, reason)
        
        logger.info(
            f"[{self._agent_id}] 状态转换: {old_state} -> {target_state}"
            + (f" | 原因: {reason}" if reason else "")
        )
        
        return self._current_state
    
    def transition_to_error(self, error_message: str) -> AgentState:
        """
        转换到错误状态
        
        Args:
            error_message: 错误信息
            
        Returns:
            转换后的状态（ERROR）
        """
        self._error_message = error_message
        try:
            return self.transition(AgentState.ERROR, error_message)
        except StateTransitionError:
            logger.warning(
                f"[{self._agent_id}] 强制转换到ERROR状态: {self._current_state} -> ERROR"
            )
            self._previous_state = self._current_state
            self._current_state = AgentState.ERROR
            self._last_transition_time = datetime.now()
            self._record_transition(AgentState.ERROR, f"强制转换: {error_message}")
            return self._current_state
    
    def reset(self) -> AgentState:
        """
        重置状态机到IDLE状态
        
        Returns:
            重置后的状态（IDLE）
        """
        old_state = self._current_state
        self._previous_state = old_state
        self._current_state = AgentState.IDLE
        self._last_transition_time = datetime.now()
        self._error_message = None
        self._record_transition(AgentState.IDLE, "重置")
        
        logger.info(f"[{self._agent_id}] 状态机重置: {old_state} -> IDLE")
        
        return self._current_state
    
    def _record_transition(self, state: AgentState, reason: str = ""):
        """
        记录状态转换历史
        
        Args:
            state: 新状态
            reason: 转换原因
        """
        self._state_history.append({
            "state": state,
            "timestamp": datetime.now().isoformat(),
            "reason": reason,
        })
        
        if len(self._state_history) > 100:
            self._state_history = self._state_history[-100:]
    
    def get_state_duration(self) -> Optional[float]:
        """
        获取当前状态持续时间（秒）
        
        Returns:
            持续时间（秒），如果尚未进行过状态转换则返回None
        """
        if self._last_transition_time is None:
            return None
        return (datetime.now() - self._last_transition_time).total_seconds()
    
    def is_busy(self) -> bool:
        """
        检查Agent是否处于忙碌状态
        
        Returns:
            是否忙碌（非IDLE且非COMPLETED）
        """
        return self._current_state not in {
            AgentState.IDLE, 
            AgentState.COMPLETED,
        }
    
    def is_error(self) -> bool:
        """
        检查Agent是否处于错误状态
        
        Returns:
            是否处于错误状态
        """
        return self._current_state == AgentState.ERROR
    
    def is_completed(self) -> bool:
        """
        检查Agent是否已完成任务
        
        Returns:
            是否已完成
        """
        return self._current_state == AgentState.COMPLETED
    
    def to_dict(self) -> Dict[str, Any]:
        """
        将状态机信息导出为字典
        
        Returns:
            包含状态机信息的字典
        """
        return {
            "agent_id": self._agent_id,
            "current_state": self._current_state.value,
            "previous_state": self._previous_state.value if self._previous_state else None,
            "error_message": self._error_message,
            "last_transition_time": self._last_transition_time.isoformat() if self._last_transition_time else None,
            "state_duration": self.get_state_duration(),
            "is_busy": self.is_busy(),
            "is_error": self.is_error(),
            "is_completed": self.is_completed(),
        }
    
    def __repr__(self) -> str:
        return (
            f"AgentStateMachine(agent_id='{self._agent_id}', "
            f"current_state={self._current_state.value}, "
            f"previous_state={self._previous_state.value if self._previous_state else None})"
        )


def get_valid_transitions(state: AgentState) -> Set[AgentState]:
    """
    获取指定状态的所有合法转换目标
    
    Args:
        state: 当前状态
        
    Returns:
        合法转换目标状态集合
    """
    return VALID_TRANSITIONS.get(state, set()).copy()
