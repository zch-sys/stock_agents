"""
Agent基础模块

本模块提供Agent的基础设施，包括：
- AgentState: Agent状态枚举
- AgentStateMachine: Agent状态机
- BaseAgent: Agent抽象基类
- AgentType: Agent类型枚举
- AgentConfig: Agent配置
- AgentResult: Agent执行结果
- AgentRegistry: Agent注册中心
"""

from .agent_state import (
    AgentState,
    AgentStateMachine,
    StateTransitionError,
    get_valid_transitions,
    VALID_TRANSITIONS,
)

from .base_agent import (
    BaseAgent,
    AgentType,
    AgentConfig,
    AgentResult,
)

from .agent_registry import (
    AgentRegistry,
    register_agent,
)

__all__ = [
    "AgentState",
    "AgentStateMachine",
    "StateTransitionError",
    "get_valid_transitions",
    "VALID_TRANSITIONS",
    "BaseAgent",
    "AgentType",
    "AgentConfig",
    "AgentResult",
    "AgentRegistry",
    "register_agent",
]
