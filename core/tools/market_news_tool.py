"""
大盘新闻数据获取工具（简化版）

直接触发爬虫获取最新大盘新闻，不再查询数据库。
"""

import logging
from typing import Dict, Any, List, Optional

from core.tools.base_tool import BaseTool, ToolResult, ToolParameter

logger = logging.getLogger(__name__)


class MarketNewsTool(BaseTool):
    """
    大盘新闻数据获取工具（简化版）
    
    直接触发爬虫获取最新大盘新闻，不再依赖数据库查询。
    
    返回数据格式:
    [
        {
            "title": "新闻标题",
            "content": "新闻内容",
            "publish_time": "2026-02-22 12:48",
            "source": "eastmoney"
        },
        ...
    ]
    """
    
    name = "market_news_data"
    description = "获取大盘财经新闻数据（直接爬取最新数据）"
    version = "1.0.0"
    timeout = 60.0  # 爬虫可能需要时间
    
    def _setup_parameters(self) -> None:
        """设置参数定义"""
        self._parameters = {
            "max_pages": ToolParameter(
                name="max_pages",
                param_type="integer",
                description="最大爬取页数（每页约20条），默认5页",
                required=False,
                default=10,
            ),
            "hours": ToolParameter(
                name="hours",
                param_type="integer",
                description="（仅供参考）爬虫会自动过滤最近N小时的新闻，默认24",
                required=False,
                default=24,
            ),
        }
    
    def execute(
        self, 
        max_pages: int = 1,
        hours: int = 24
    ) -> ToolResult:
        """
        执行新闻爬取
        
        Args:
            max_pages: 最大爬取页数
            hours: 时间过滤范围（爬虫内部会根据发布时间过滤）
            
        Returns:
            ToolResult: 包含新闻列表
        """
        try:
            # 直接触发爬虫获取新闻
            news_list = self._fetch_news_directly(max_pages, hours)
            
            # 格式化返回数据
            formatted_news = self._format_news(news_list)
            
            logger.info(f"爬取大盘新闻成功: {len(formatted_news)} 条")
            return ToolResult.success(
                data=formatted_news,
                max_pages=max_pages,
                hours=hours,
                count=len(formatted_news)
            )
            
        except Exception as e:
            error_msg = f"获取大盘新闻失败: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return ToolResult.failure(error=error_msg)
    
    def _fetch_news_directly(self, max_pages: int, hours: int) -> List[Dict[str, Any]]:
        """
        直接爬取新闻，不查询数据库
        
        Args:
            max_pages: 最大爬取页数
            hours: 时间过滤（传递给爬虫内部的时间检查）
            
        Returns:
            原始新闻列表
        """
        try:
            from data.basic_data.market_news_collector import MarketNewsCollector
            
            collector = MarketNewsCollector()
            # crawl_market_news 返回 (news_list, saved_count)
            news_list, saved_count = collector.crawl_market_news(max_pages=max_pages)
            
            logger.info(f"爬虫返回 {len(news_list)} 条新闻，保存 {saved_count} 条到数据库")
            return news_list
            
        except Exception as e:
            logger.error(f"直接爬取新闻失败: {e}")
            return []
    
    def _format_news(self, news_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        格式化新闻数据，确保包含所需字段
        
        Args:
            news_list: 原始新闻列表
            
        Returns:
            格式化后的新闻列表
        """
        formatted = []
        for news in news_list:
            formatted.append({
                "title": news.get("title", ""),
                "content": news.get("content", ""),
                "publish_time": news.get("publish_time", ""),
                "source": news.get("source", ""),
            })
        return formatted


# 工具注册函数
def register_market_news_tool(registry) -> None:
    """注册大盘新闻工具到注册表"""
    registry.register(MarketNewsTool)
    logger.info(f"已注册工具: {MarketNewsTool.name}")