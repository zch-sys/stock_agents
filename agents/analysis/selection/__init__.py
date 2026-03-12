"""
选股分析师模块

提供基于 ReAct 架构的选股分析师实现。
"""

from .stock_selection_agent import StockSelectionAgent
from .selection_prompts import (
    SYSTEM_PROMPT_SELECTION,
    build_react_prompt,
    format_market_report,
    format_sector_report,
    format_stock_pool_results,
    format_stock_details
)

__all__ = [
    "StockSelectionAgent",
    "SYSTEM_PROMPT_SELECTION",
    "build_react_prompt",
    "format_market_report",
    "format_sector_report",
    "format_stock_pool_results",
    "format_stock_details"
]