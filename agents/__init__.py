"""
Agent模块

本模块包含所有Agent定义，按团队组织：
- base: Agent基础设施（状态管理、基类、注册中心）
- selection: 选股团队
- analysis: 分析团队
- planning: 计划团队
- execution: 交易团队
- review: 复盘团队
"""

from .base import (
    AgentState,
    AgentStateMachine,
    StateTransitionError,
    BaseAgent,
    AgentType,
    AgentConfig,
    AgentResult,
    AgentRegistry,
    register_agent,
)

__all__ = [
    "AgentState",
    "AgentStateMachine",
    "StateTransitionError",
    "BaseAgent",
    "AgentType",
    "AgentConfig",
    "AgentResult",
    "AgentRegistry",
    "register_agent",
]
