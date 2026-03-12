"""
工具系统模块

本模块提供Agent可使用的工具基础设施，包括：
- BaseTool: 工具抽象基类
- ToolResult: 工具执行结果封装
- ToolParameter: 工具参数定义
- ToolStatus: 工具执行状态枚举
- ToolRegistry: 工具注册中心
- TushareMarketDataTool: Tushare市场数据工具
- MarketNewsTool: 大盘新闻数据工具
"""

from .base_tool import (
    BaseTool,
    ToolResult,
    ToolParameter,
    ToolStatus,
)

from .tool_registry import (
    ToolRegistry,
    get_tool_registry,
)

from .tushare_tools import (
    TushareMarketDataTool,
    TushareIndexBasicTool,
    register_tushare_tools,
)

from .market_news_tool import (
    MarketNewsTool,
    register_market_news_tool,
)

from .sector_tools import (
    SectorMatchTool,
    register_sector_tools,
)


__all__ = [
    "BaseTool",
    "ToolResult",
    "ToolParameter",
    "ToolStatus",
    "ToolRegistry",
    "get_tool_registry",
    "TushareMarketDataTool",
    "TushareIndexBasicTool",
    "register_tushare_tools",
    "MarketNewsTool",
    "register_market_news_tool",
    "SectorMatchTool",
    "register_sector_tools",

]


def register_all_tools(registry: ToolRegistry = None) -> None:
    """
    注册所有内置工具
    
    Args:
        registry: ToolRegistry实例，如果为None则获取全局实例
    """
    if registry is None:
        registry = get_tool_registry()
    
    register_tushare_tools(registry)
    register_market_news_tool(registry)
    register_sector_tools(registry)
