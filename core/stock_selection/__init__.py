# core/stock_selection/__init__.py
"""
股票筛选模块统一入口

该模块提供完整的股票筛选功能，包括：
- 配置管理 (ConfigManager)
- 因子计算 (FactorEngine)
- 因子筛选 (FactorSelector)
- 股票筛选 (StockSelector)
- 调度执行 (Scheduler)

使用示例：
    from core.stock_selection import ConfigManager, Scheduler

    config = ConfigManager()
    scheduler = Scheduler(config=config)
    scheduler.run()
"""

from .config_manager import ConfigManager, get_config, PROJECT_ROOT
from .Factor_factory import FactorEngine, ComputeMode
from .Factor_selection import FactorSelector, SelectionMode
from .Selection_scheduler import Scheduler, UpdateStatus
from .Stock_selection import StockSelector

__all__ = [
    # 配置管理
    "ConfigManager",
    "get_config",
    "PROJECT_ROOT",

    # 因子计算
    "FactorEngine",
    "ComputeMode",

    # 因子筛选
    "FactorSelector",
    "SelectionMode",

    # 调度器
    "Scheduler",
    "UpdateStatus",

    # 股票筛选
    "StockSelector",
]