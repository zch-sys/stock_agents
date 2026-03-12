"""
工具注册中心

提供工具的注册、管理和获取功能。
"""

import logging
from typing import Dict, List, Type, Optional, Any

from .base_tool import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    工具注册中心
    
    管理所有可用工具的注册和获取。支持装饰器方式注册工具。
    
    使用示例:
        registry = ToolRegistry()
        
        @registry.register
        class GetStockDataTool(BaseTool):
            ...
        
        tool = registry.get("get_stock_data")
        result = tool.run(stock_code="000001.SZ", start_date="2024-01-01")
    
    属性:
        _tools: 工具类字典 {name: ToolClass}
        _instances: 工具实例字典 {name: tool_instance}
    """
    
    _instance: Optional['ToolRegistry'] = None
    
    def __new__(cls) -> 'ToolRegistry':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}
            cls._instance._instances = {}
        return cls._instance
    
    def register(self, tool_class: Type[BaseTool]) -> Type[BaseTool]:
        """
        注册工具类（装饰器方式）
        
        Args:
            tool_class: 工具类
            
        Returns:
            注册的工具类
            
        Raises:
            ValueError: 工具名称已存在
        """
        instance = tool_class()
        
        # 如果工具已存在，直接跳过（幂等操作）
        if instance.name in self._tools:
            logger.debug(f"工具已存在，跳过注册: {instance.name}")
            return tool_class
        
        self._tools[instance.name] = tool_class
        self._instances[instance.name] = instance
        logger.debug(f"工具注册成功: {instance.name}")
        return tool_class
    
    def unregister(self, name: str) -> bool:
        """
        注销工具
        
        Args:
            name: 工具名称
            
        Returns:
            是否注销成功
        """
        if name in self._tools:
            del self._tools[name]
            del self._instances[name]
            logger.debug(f"工具注销成功: {name}")
            return True
        return False
    
    def get(self, name: str) -> Optional[BaseTool]:
        """
        获取工具实例
        
        Args:
            name: 工具名称
            
        Returns:
            工具实例，不存在则返回None
        """
        return self._instances.get(name)
    
    def get_class(self, name: str) -> Optional[Type[BaseTool]]:
        """
        获取工具类
        
        Args:
            name: 工具名称
            
        Returns:
            工具类，不存在则返回None
        """
        return self._tools.get(name)
    
    def has(self, name: str) -> bool:
        """
        检查工具是否已注册
        
        Args:
            name: 工具名称
            
        Returns:
            是否已注册
        """
        return name in self._tools
    
    def list_tools(self) -> List[str]:
        """
        列出所有已注册工具名称
        
        Returns:
            工具名称列表
        """
        return list(self._tools.keys())
    
    def get_all_tools_info(self) -> List[Dict[str, Any]]:
        """
        获取所有工具的信息
        
        Returns:
            工具信息列表
        """
        return [tool.get_tool_info() for tool in self._instances.values()]
    
    def get_tools_by_category(self, category: str) -> List[BaseTool]:
        """
        按类别获取工具
        
        Args:
            category: 工具类别
            
        Returns:
            该类别的工具实例列表
        """
        tools = []
        for tool in self._instances.values():
            tool_category = tool.metadata.get("category", "")
            if tool_category == category:
                tools.append(tool)
        return tools
    
    def clear(self) -> None:
        """清空所有注册的工具"""
        self._tools.clear()
        self._instances.clear()
        logger.debug("所有工具已清空")
    
    def __len__(self) -> int:
        return len(self._tools)
    
    def __contains__(self, name: str) -> bool:
        return name in self._tools
    
    def __repr__(self) -> str:
        return f"ToolRegistry(tools={self.list_tools()})"


def get_tool_registry() -> ToolRegistry:
    """
    获取全局工具注册中心单例
    
    Returns:
        ToolRegistry实例
    """
    return ToolRegistry()
