# data/basic_data/__init__.py
"""
基础数据模块 - 包含个股、指数、新闻等基础数据的收集与管理
"""

from pathlib import Path
from .config_manager import setup_logging

# 设置日志
logger = setup_logging(__name__)

# 模块信息
__version__ = "1.0.0"


def get_basic_data_dir() -> Path:
    """获取当前 basic_data 目录的绝对路径"""
    return Path(__file__).parent.resolve()


# ========== 导入子模块的公开类/函数 ==========
# 尽量在顶层导入，方便外部直接使用
try:
    # 数据库模型和工具
    from .database import (
        Base,
        MarketIndex,
        SectorData,
        StockDetail,
        StockFactor,
        StockNews,
        StockPool,
        MarketNews,
        init_db,
        get_session,
    )

    # 股票收集器
    from .stock import StockCollector

    # 指数/板块收集器
    from .indexdata import MarketCollector

    # 新闻爬取器
    from .newsdata import StockNewsCrawler

    # 大盘新闻收集器
    from .market_news_collector import MarketNewsCollector

    # 数据调度器
    from .scheduler import DataScheduler

    # 定义公开接口
    __all__ = [
        # 数据库模型
        "Base",
        "MarketIndex",
        "SectorData",
        "StockDetail",
        "StockFactor",
        "StockNews",
        "StockPool",
        "MarketNews",
        "init_db",
        "get_session",
        "StockCollector",
        "MarketCollector",
        "StockNewsCrawler",
        "MarketNewsCollector",
        "DataScheduler",
    ]

except ImportError as e:
    logger.debug(f"子模块导入延迟或失败: {e}")
    __all__ = []

# ========== 初始化日志 ==========
logger.info(f"初始化 basic_data 模块 v{__version__}")