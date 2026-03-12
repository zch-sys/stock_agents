"""
Agent注册中心

本模块提供Agent的注册、发现和实例化功能。
支持装饰器方式注册Agent，便于管理和扩展。

设计原则:
    - 单例模式: 全局唯一的注册中心
    - 装饰器注册: 简洁的注册方式
    - 延迟实例化: 按需创建Agent实例
    - 配置驱动: 支持从配置文件加载Agent配置
"""

from typing import Any, Dict, List, Optional, Type, Callable
import logging

from .base_agent import BaseAgent, AgentConfig, AgentType

logger = logging.getLogger(__name__)


class AgentRegistry:
    """
    Agent注册中心
    
    管理所有Agent类型的注册、发现和实例化。
    支持装饰器方式注册，便于扩展。
    
    使用示例:
        # 装饰器方式注册
        @AgentRegistry.register
        class MarketAnalyst(BaseAgent):
            agent_type = AgentType.MARKET
            ...
        
        # 获取Agent实例
        agent = AgentRegistry.get("MarketAnalyst", config=my_config)
        
        # 列出所有已注册Agent
        names = AgentRegistry.list_all()
    """
    
    _agents: Dict[str, Type[BaseAgent]] = {}
    _configs: Dict[str, AgentConfig] = {}
    _instances: Dict[str, BaseAgent] = {}
    _type_mapping: Dict[AgentType, List[str]] = {}
    
    @classmethod
    def register(cls, agent_class: Type[BaseAgent] = None, *, name: str = None) -> Callable:
        """
        注册Agent类（支持装饰器方式）
        
        可以作为装饰器使用:
            @AgentRegistry.register
            class MyAgent(BaseAgent):
                ...
        
        或者带名称注册:
            @AgentRegistry.register(name="custom_name")
            class MyAgent(BaseAgent):
                ...
        
        Args:
            agent_class: Agent类（装饰器模式自动传入）
            name: 自定义名称（可选）
            
        Returns:
            装饰器函数或原类
        """
        def decorator(agent_cls: Type[BaseAgent]) -> Type[BaseAgent]:
            agent_name = name or agent_cls.__name__
            
            if agent_name in cls._agents:
                logger.warning(f"Agent已存在，将覆盖: {agent_name}")
            
            cls._agents[agent_name] = agent_cls
            
            agent_type = getattr(agent_cls, 'agent_type', AgentType.MARKET)
            if agent_type not in cls._type_mapping:
                cls._type_mapping[agent_type] = []
            cls._type_mapping[agent_type].append(agent_name)
            
            logger.info(f"注册Agent: {agent_name} | 类型: {agent_type.value}")
            
            return agent_cls
        
        if agent_class is not None:
            return decorator(agent_class)
        
        return decorator
    
    @classmethod
    def register_config(cls, name: str, config: AgentConfig) -> None:
        """
        注册Agent配置
        
        Args:
            name: Agent名称
            config: Agent配置
        """
        cls._configs[name] = config
        logger.debug(f"注册Agent配置: {name}")
    
    @classmethod
    def get(
        cls,
        name: str,
        config: AgentConfig = None,
        memory_manager: Any = None,
        llm_client: Any = None,
        tool_registry: Any = None,
        reuse_instance: bool = False,
    ) -> BaseAgent:
        """
        获取Agent实例
        
        Args:
            name: Agent名称
            config: Agent配置（可选，使用注册的配置或默认配置）
            memory_manager: 记忆管理器（依赖注入）
            llm_client: LLM客户端（依赖注入）
            tool_registry: 工具注册中心（依赖注入）
            reuse_instance: 是否复用已有实例
            
        Returns:
            Agent实例
            
        Raises:
            KeyError: Agent未注册
        """
        if name not in cls._agents:
            raise KeyError(f"Agent未注册: {name}")
        
        if reuse_instance and name in cls._instances:
            return cls._instances[name]
        
        agent_class = cls._agents[name]
        
        if config is None:
            config = cls._configs.get(name, AgentConfig(name=name))
        
        instance = agent_class(
            config=config,
            memory_manager=memory_manager,
            llm_client=llm_client,
            tool_registry=tool_registry,
        )
        
        if reuse_instance:
            cls._instances[name] = instance
        
        logger.debug(f"创建Agent实例: {name} | ID: {instance.agent_id}")
        
        return instance
    
    @classmethod
    def get_by_type(
        cls,
        agent_type: AgentType,
        memory_manager: Any = None,
        llm_client: Any = None,
        tool_registry: Any = None,
    ) -> List[BaseAgent]:
        """
        根据类型获取所有Agent实例
        
        Args:
            agent_type: Agent类型
            memory_manager: 记忆管理器
            llm_client: LLM客户端
            tool_registry: 工具注册中心
            
        Returns:
            该类型的所有Agent实例列表
        """
        names = cls._type_mapping.get(agent_type, [])
        return [
            cls.get(name, memory_manager=memory_manager, llm_client=llm_client, tool_registry=tool_registry)
            for name in names
        ]
    
    @classmethod
    def list_all(cls) -> List[str]:
        """
        列出所有已注册Agent名称
        
        Returns:
            Agent名称列表
        """
        return list(cls._agents.keys())
    
    @classmethod
    def list_by_type(cls, agent_type: AgentType) -> List[str]:
        """
        列出指定类型的Agent名称
        
        Args:
            agent_type: Agent类型
            
        Returns:
            该类型的Agent名称列表
        """
        return cls._type_mapping.get(agent_type, []).copy()
    
    @classmethod
    def get_class(cls, name: str) -> Type[BaseAgent]:
        """
        获取Agent类（不实例化）
        
        Args:
            name: Agent名称
            
        Returns:
            Agent类
            
        Raises:
            KeyError: Agent未注册
        """
        if name not in cls._agents:
            raise KeyError(f"Agent未注册: {name}")
        return cls._agents[name]
    
    @classmethod
    def unregister(cls, name: str) -> bool:
        """
        注销Agent
        
        Args:
            name: Agent名称
            
        Returns:
            是否注销成功
        """
        if name not in cls._agents:
            return False
        
        agent_class = cls._agents[name]
        agent_type = getattr(agent_class, 'agent_type', AgentType.MARKET)
        
        del cls._agents[name]
        
        if agent_type in cls._type_mapping:
            if name in cls._type_mapping[agent_type]:
                cls._type_mapping[agent_type].remove(name)
        
        if name in cls._instances:
            del cls._instances[name]
        
        if name in cls._configs:
            del cls._configs[name]
        
        logger.info(f"注销Agent: {name}")
        
        return True
    
    @classmethod
    def clear_instances(cls) -> None:
        """
        清除所有缓存的实例
        """
        cls._instances.clear()
        logger.info("清除所有Agent实例缓存")
    
    @classmethod
    def clear_all(cls) -> None:
        """
        清除所有注册信息
        """
        cls._agents.clear()
        cls._configs.clear()
        cls._instances.clear()
        cls._type_mapping.clear()
        logger.warning("清除所有Agent注册信息")
    
    @classmethod
    def get_info(cls, name: str) -> Dict[str, Any]:
        """
        获取Agent注册信息
        
        Args:
            name: Agent名称
            
        Returns:
            Agent信息字典
        """
        if name not in cls._agents:
            return {"registered": False, "name": name}
        
        agent_class = cls._agents[name]
        agent_type = getattr(agent_class, 'agent_type', AgentType.MARKET)
        config = cls._configs.get(name)
        
        return {
            "registered": True,
            "name": name,
            "type": agent_type.value,
            "class": agent_class.__name__,
            "has_config": config is not None,
            "has_instance": name in cls._instances,
        }
    
    @classmethod
    def get_all_info(cls) -> Dict[str, Any]:
        """
        获取所有Agent注册信息
        
        Returns:
            所有Agent信息字典
        """
        return {
            "total_count": len(cls._agents),
            "agents": {name: cls.get_info(name) for name in cls._agents},
            "type_mapping": {
                t.value: names for t, names in cls._type_mapping.items()
            },
        }
    
    @classmethod
    def count(cls) -> int:
        """
        获取已注册Agent数量
        
        Returns:
            Agent数量
        """
        return len(cls._agents)
    
    @classmethod
    def __contains__(cls, name: str) -> bool:
        """支持 `name in AgentRegistry` 语法"""
        return name in cls._agents
    
    @classmethod
    def __len__(cls) -> int:
        """支持 `len(AgentRegistry)` 语法"""
        return len(cls._agents)
    
    @classmethod
    def __repr__(cls) -> str:
        return f"AgentRegistry(agents={len(cls._agents)}, instances={len(cls._instances)})"


def register_agent(name: str = None) -> Callable:
    """
    便捷注册装饰器函数
    
    使用示例:
        @register_agent("market_analyst")
        class MarketAnalyst(BaseAgent):
            ...
    
    Args:
        name: Agent名称（可选）
        
    Returns:
        装饰器函数
    """
    return AgentRegistry.register(name=name)
