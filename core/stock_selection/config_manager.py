"""
统一配置管理器

功能说明：
1. 统一管理因子计算、因子筛选、股票筛选的所有配置
2. 支持从YAML文件加载配置
3. 提供属性访问接口，方便各模块使用

使用示例：
    config = ConfigManager(config_path="config.yaml")
    db_url = config.DB_URL
    factor_config = config.get("factor_selection", {})
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 获取项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    统一配置管理器
    
    管理以下模块的配置：
    - Factor_factory.py: 因子计算引擎
    - Factor_selection.py: 因子筛选器
    - stock_selector.py: 股票筛选器
    - scheduler.py: 调度器
    """
    
    # 默认配置
    DEFAULT_CONFIG = {
        # 数据库配置
        "database": {
            "db_url": "postgresql://postgres:z2c2h088QQ@localhost:5432/stock_analysis",
            "chunk_size": 50000,
        },
        
        # 预处理参数
        "preprocess": {
            "winsorize_limit": [0.025, 0.975],
            "list_day_threshold": 120,
            "fill_limit": 5,
            "corr_threshold": 0.8,
        },
        
        # 计算窗口配置
        "windows": {
            "return_windows": [1, 3, 5, 10, 20, 60, 120],
            "volatility_windows": [5, 10, 20, 60, 120],
            "momentum_suffixes": ["5d", "20d", "60d", "120d"],
            "reversal_suffixes": ["1d", "5d", "120d"],
        },
        
        # 常量参数
        "constants": {
            "eps": 1e-12,
            "min_valid_stocks": 20,
            "max_market_dates": 600,
        },
        
        # 增量计算配置
        "incremental": {
            "max_days_gap": 10,
        },
        
        # 因子筛选配置
        "factor_selection": {
            "non_factor_cols": ["id", "ts_code", "trade_date", "updated_at", "industry", "close", "log_circ_mv"],
            "min_valid_stocks": 20,
            "eps": 1e-6,
            "short_term": {
                "windows": [1, 3, 5],
                "lookback_days": 180,
                "update_threshold_days": 30,
                "min_ic_mean": 0.025,
                "min_ir": 0.32,
                "min_hit_rate": 0.54,
                "min_valid_days": 30,
            },
            "medium_term": {
                "windows": [20, 30],
                "lookback_days": 300,
                "update_threshold_days": 90,
                "min_ic_mean": 0.04,
                "min_ir": 0.4,
                "min_hit_rate": 0.56,
                "min_valid_days": 6,
            },
            "long_term": {
                "windows": [60, 120],
                "lookback_days": 600,
                "update_threshold_days": 250,
                "min_ic_mean": 0.06,
                "min_ir": 0.6,
                "min_hit_rate": 0.60,
                "min_valid_days": 3,
            },
            "output": {
                "config_dir": "config",
                "short_term_file": "short_factor.yaml",
                "medium_term_file": "medium_factor.yaml",
                "long_term_file": "long_factor.yaml",
            },
        },
        
        # 股票筛选配置
        "stock_selection": {
            # 选股数量
            "tushare_token": "41bc8be1587c976380a7776cb3d0e74a563aecfbfa1bef98670eb601",
            "top_n": 10,
            
            # 各周期训练窗口（交易日）
            "train_windows": {
                "short_term": 15,     # 短期训练窗口
                "medium_term": 150,   # 中期训练窗口
                "long_term": 300,     # 长期训练窗口
            },
            
            # 各周期预测标签窗口（天数）
            "label_horizons": {
                "short_term": 5,      # 短期预测未来5天收益
                "medium_term": 30,    # 中期预测未来30天收益
                "long_term": 120,     # 长期预测未来120天收益
            },
            
            # 各周期因子有效期（天数）
            "factor_validity_days": {
                "short_term": 30,     # 短期因子有效期30天
                "medium_term": 120,   # 中期因子有效期120天
                "long_term": 250,     # 长期因子有效期250天
            },
            
            # 各周期股票池有效期（天数）
            "stock_validity_days": {
                "short_term": 5,      # 短期股票池有效期5天
                "medium_term": 30,    # 中期股票池有效期30天
                "long_term": 180,     # 长期股票池有效期180天
                "white_horse": 365,   # 大白马股票池有效期365天（一年更新一次）
            },
            
            # 模型配置
            "model": {
                "short_term": "ensemble",  # 短期使用集成模型
                "medium_term": "ridge",    # 中期使用岭回归
                "long_term": "ridge",      # 长期使用岭回归
            },
            
            # 输出配置
            "output": {
                "config_dir": "config",
                "short_term_file": "short_factor.yaml",
                "medium_term_file": "medium_factor.yaml",
                "long_term_file": "long_factor.yaml",
            },
        },
        
        # 大白马股票筛选配置
        "white_horse_selection": {
            # 选股数量
            "top_n": 10,
            
            # 股票池有效期（天数）- 一年更新一次
            "validity_days": 365,
            
            # 筛选条件
            "criteria": {
                # 股息率筛选
                "min_dv_ttm": 2.5,              # 最低股息率%（TTM）
                "good_dv_ttm": 3.0,             # 优秀股息率%
                "excellent_dv_ttm": 4.0,        # 卓越股息率%
                
                # 市值筛选
                "min_total_mv": 500,            # 最低总市值（亿元）
                "large_cap_mv": 1000,           # 大盘股市值（亿元）
                "super_cap_mv": 2000,           # 超大盘市值（亿元）
                
                # 盈利能力
                "min_roe": 10.0,                # 最低ROE%
                "good_roe": 15.0,               # 优秀ROE%
                "excellent_roe": 20.0,          # 卓越ROE%
                
                # 财务稳健
                "max_debt_ratio": 70.0,         # 最高资产负债率%
                "good_debt_ratio": 60.0,        # 良好资产负债率%
                
                # 估值区间
                "min_pe": 0,                    # 最低PE（排除负值）
                "max_pe": 35,                   # 最高PE
                "good_pe_max": 30,              # 良好PE上限
                
                # 增长要求
                "min_revenue_yoy": -10.0,       # 最低营收增长率%（允许小幅下滑）
                "min_profit_yoy": -10.0,        # 最低利润增长率%
            },
            
            # 评分权重配置
            "scoring_weights": {
                "dividend": 25,          # 股息率得分权重
                "market_cap": 15,        # 市值得分权重
                "profitability": 25,     # 盈利能力得分权重
                "financial": 15,         # 财务稳健得分权重
                "valuation": 10,         # 估值吸引力得分权重
                "growth": 10,            # 成长性得分权重
                "leader_bonus": 5,       # 行业龙头加分
            },
        },
        
        # 表结构定义
        "table_columns": {
            "stock": [
                "ts_code", "trade_date", "name", "open", "close", "high", "low",
                "pct_chg", "vol", "amount", "pre_close", "ma5", "ma10", "ma20", "ma60",
                "macd", "macd_signal", "macd_hist", "rsi6", "rsi12", "rsi24",
                "boll_upper", "boll_middle", "boll_lower", "industry", "area", "market",
                "list_date", "pe", "pb", "ps", "total_mv", "circ_mv", "dv_ttm",
                "total_assets", "total_liab", "net_profit", "revenue",
                "debt_to_assets", "current_ratio", "quick_ratio", "cash_ratio",
                "revenue_yoy", "profit_yoy"
            ],
            "sector": [
                "sector_code", "sector_name", "trade_date", "open", "close", "high", "low",
                "pct_chg", "vol", "amount", "total_market_cap", "circ_market_cap",
                "rank", "stock_count", "rise_count", "fall_count", "rise_fall_ratio",
                "fund_inflow", "fund_inflow_rate", "avg_pct_chg"
            ],
            "market": [
                "ts_code", "trade_date", "open", "close", "high", "low",
                "pct_chg", "vol", "amount", "ma5", "ma10", "ma20",
                "macd", "macd_signal", "macd_hist", "adx", "north_money_total",
                "margin_balance", "margin_buy", "short_balance",
                "adv_issues", "dec_issues", "adv_decline_ratio",
                "market_width", "ad_line", "turnover_concentration", "pe", "pb"
            ],
        },
        
        # 因子分类定义
        "factor_categories": {
            "time_series_factors": [
                "price_volume_divergence", "price_volume_strength",
                "volatility_5d", "volatility_10d", "volatility_20d",
                "volatility_60d", "volatility_120d",
                "return_120d", "simple_return_120d", "momentum_120d"
            ],
            "valuation_factors": [
                "ep", "bp", "sp", "value_score", "pe_industry_rank", "pb_industry_rank"
            ],
            "neutralize_factors": [
                # 收益率因子
                "return_1d", "return_3d", "return_5d", "return_10d", "return_20d",
                "return_60d", "return_120d", "simple_return_1d", "simple_return_3d",
                "simple_return_5d", "simple_return_10d", "simple_return_20d",
                "simple_return_60d", "simple_return_120d",
                
                # 动量因子
                "momentum_5d", "momentum_20d", "momentum_60d", "momentum_120d",
                "momentum_acceleration", "reversal_1d", "reversal_5d", "reversal_120d",
                
                # 波动率因子
                "volatility_5d", "volatility_10d", "volatility_20d",
                "volatility_60d", "volatility_120d", "volatility_change",
                "volatility_long_term_dev", "low_volatility", "volatility_anomaly",
                
                # 日内因子
                "overnight_return", "overnight_momentum", "open_gap", "gap_ratio",
                "intraday_return", "intraday_strength", "high_low_ratio", "price_position",
                
                # 量价因子
                "volume_relative_strength", "price_volume_divergence", "price_volume_strength",
                "ma5_slope", "ma10_slope", "ma_slope_diff", "amount_concentration",
                
                # 估值因子（原始值，非排名）
                "ep", "bp", "sp",
                
                # 成长因子
                "revenue_growth", "profit_growth",
                
                # 质量因子
                "roe", "profit_margin", "leverage", "current_ratio_safe",
                
                # 技术因子
                "rsi6_position", "macd_signal_diff", "boll_position",
                "volume_ratio", "amount_ratio",
                
                # 北向资金影响
                "north_flow_impact",
                
                # 复合因子
                "value_momentum", "quality_value", "growth_momentum", "value_score", "growth_score", "quality_score",
            ],
            # 非因子字段
            "non_factor_cols": [
                # ----- 原始股票表列 (来自 TABLE_COLUMNS["stock"]) -----
                "ts_code", "trade_date", "name", "open", "close", "high", "low",
                "pct_chg", "vol", "amount", "pre_close", "ma5", "ma10", "ma20", "ma60",
                "macd", "macd_signal", "macd_hist", "rsi6", "rsi12", "rsi24",
                "boll_upper", "boll_middle", "boll_lower", "industry", "area", "market",
                "list_date", "pe", "pb", "ps", "total_mv", "circ_mv", "dv_ttm",
                "total_assets", "total_liab", "net_profit", "revenue",
                "debt_to_assets", "current_ratio", "quick_ratio", "cash_ratio",
                "revenue_yoy", "profit_yoy",

                # ----- 板块/大盘派生列 -----
                "sector_pct_chg", "sector_amount",
                "market_pct_chg", "market_amount", "market_north_money_total",

                # ----- 辅助计算列 -----
                "log_circ_mv", "log_total_mv",
                "pe_safe", "pb_safe", "ps_safe",

                # ----- 排名结果列 (构建结果，不应再次预处理) -----
                "size_factor", "small_cap_premium",

                # ----- 全局影响因子 (旧版也排除) -----
                "north_flow_impact",

                # ----- 数据库元数据 -----
                "id", "updated_at"
                ],
        }
    }
    
    def __init__(self, config_path: str = None, config_dict: Dict = None):
        """
        初始化配置管理器
        
        Args:
            config_path: YAML配置文件路径
            config_dict: 直接传入的配置字典
        """
        self._config = {}
        
        # 先加载默认配置
        self._deep_update(self._config, self.DEFAULT_CONFIG)
        
        # 如果提供了配置文件路径，加载并合并
        if config_path:
            self._load_from_yaml(config_path)
        
        # 如果直接传入了配置字典，合并
        if config_dict:
            self._deep_update(self._config, config_dict)
        
        # 设置属性访问
        self._setup_properties()
        
        logger.info("配置管理器初始化完成")
    
    def _load_from_yaml(self, config_path: str):
        """从YAML文件加载配置"""
        path = Path(config_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / config_path
        
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                yaml_config = yaml.safe_load(f)
                if yaml_config:
                    self._deep_update(self._config, yaml_config)
                    logger.info(f"从 {path} 加载配置成功")
        else:
            logger.warning(f"配置文件 {path} 不存在，使用默认配置")
    
    def _deep_update(self, target: Dict, source: Dict):
        """深度合并字典"""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value
    
    def _setup_properties(self):
        """设置属性访问"""
        # 数据库配置
        self.DB_URL = self._config.get("database", {}).get("db_url", "sqlite:///quant.db")
        self.CHUNK_SIZE = self._config.get("database", {}).get("chunk_size", 50000)
        
        # 预处理参数
        preprocess = self._config.get("preprocess", {})
        self.WINSORIZE_LIMIT = tuple(preprocess.get("winsorize_limit", [0.025, 0.975]))
        self.LIST_DAY_THRESHOLD = preprocess.get("list_day_threshold", 120)
        self.FILL_LIMIT = preprocess.get("fill_limit", 5)
        self.CORR_THRESHOLD = preprocess.get("corr_threshold", 0.8)
        
        # 窗口配置
        windows = self._config.get("windows", {})
        self.RETURN_WINDOWS = windows.get("return_windows", [1, 3, 5, 10, 20, 60, 120])
        self.VOLATILITY_WINDOWS = windows.get("volatility_windows", [5, 10, 20, 60, 120])
        self.MOMENTUM_SUFFIXES = windows.get("momentum_suffixes", ["5d", "20d", "60d", "120d"])
        self.REVERSAL_SUFFIXES = windows.get("reversal_suffixes", ["1d", "5d", "120d"])
        
        # 常量参数
        constants = self._config.get("constants", {})
        self.EPS = constants.get("eps", 1e-12)
        self.MIN_VALID_STOCKS = constants.get("min_valid_stocks", 20)
        self.MAX_MARKET_DATES = constants.get("max_market_dates", 1000)
        
        # 增量计算配置
        incremental = self._config.get("incremental", {})
        self.MAX_DAYS_GAP = incremental.get("max_days_gap", 10)
        
        # 表结构定义
        self.TABLE_COLUMNS = self._config.get("table_columns", {})
        
        # 因子分类定义
        factor_categories = self._config.get("factor_categories", {})
        self.TIME_SERIES_FACTORS = factor_categories.get("time_series_factors", [])
        self.VALUATION_FACTORS = factor_categories.get("valuation_factors", [])
        self.NEUTRALIZE_FACTORS = factor_categories.get("neutralize_factors", [])
        self.NON_FACTOR_COLS = factor_categories.get("non_factor_cols", [])
        self.NO_WINSORIZE_FACTORS = set(factor_categories.get("no_winsorize_factors", []))
        
        # ============ 新增：股票筛选配置 ============
        stock_selection = self._config.get("stock_selection", {})
        self.TUSHARE_TOKEN = stock_selection.get("tushare_token", None)
        
        # ============ 新增：大白马筛选配置 ============
        white_horse = self._config.get("white_horse_selection", {})
        self.WHITE_HORSE_TOP_N = white_horse.get("top_n", 10)
        self.WHITE_HORSE_VALIDITY_DAYS = white_horse.get("validity_days", 365)
        self.WHITE_HORSE_CRITERIA = white_horse.get("criteria", {})
        self.WHITE_HORSE_SCORING_WEIGHTS = white_horse.get("scoring_weights", {})
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置项（支持点分隔的嵌套访问）
        
        Args:
            key: 配置项键，如 "factor_selection.short_term.windows"
            default: 默认值
        
        Returns:
            配置值
        """
        keys = key.split(".")
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def get_term_config(self, term: str) -> Dict:
        """
        获取指定周期的配置
        
        Args:
            term: 周期类型 "short_term", "medium_term", "long_term"
        
        Returns:
            该周期的配置字典
        """
        return self._config.get("factor_selection", {}).get(term, {})
    
    def get_stock_selection_config(self, term: str = None) -> Dict:
        """
        获取股票筛选配置
        
        Args:
            term: 周期类型，None则返回全部配置
        
        Returns:
            股票筛选配置字典
        """
        config = self._config.get("stock_selection", {})
        if term:
            train_windows = config.get("train_windows", {})
            label_horizons = config.get("label_horizons", {})
            factor_validity = config.get("factor_validity_days", {})
            stock_validity = config.get("stock_validity_days", {})
            models = config.get("model", {})
            
            return {
                "train_window": train_windows.get(term, 100),
                "label_horizon": label_horizons.get(term, 30),
                "factor_validity_days": factor_validity.get(term, 30),
                "stock_validity_days": stock_validity.get(term, 30),
                "model_type": models.get(term, "ridge"),
            }
        return config
    
    def get_white_horse_config(self) -> Dict:
        """
        获取大白马股票筛选配置
        
        Returns:
            大白马筛选配置字典
        """
        return self._config.get("white_horse_selection", {})
    
    def get_white_horse_criteria(self) -> Dict:
        """
        获取大白马筛选条件
        
        Returns:
            筛选条件字典
        """
        return self._config.get("white_horse_selection", {}).get("criteria", {})
    
    def get_white_horse_validity_days(self) -> int:
        """
        获取大白马股票池有效期（天数）
        
        Returns:
            有效期天数（默认365天）
        """
        return self._config.get("white_horse_selection", {}).get("validity_days", 365)
    
    def get_factor_yaml_path(self, term: str) -> Path:
        """
        获取因子配置文件路径
        
        Args:
            term: 周期类型
        
        Returns:
            配置文件完整路径
        """
        output_config = self._config.get("factor_selection", {}).get("output", {})
        config_dir = output_config.get("config_dir", "config")
        
        file_mapping = {
            "short_term": output_config.get("short_term_file", "short_factor.yaml"),
            "medium_term": output_config.get("medium_term_file", "medium_factor.yaml"),
            "long_term": output_config.get("long_term_file", "long_factor.yaml"),
        }
        
        filename = file_mapping.get(term, f"{term}.yaml")
        return PROJECT_ROOT / config_dir / filename
    
    def to_dict(self) -> Dict:
        """返回完整配置字典"""
        return self._config.copy()
    
    def save_to_yaml(self, filepath: str):
        """保存配置到YAML文件"""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(self._config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        
        logger.info(f"配置已保存到 {path}")


# 便捷函数：创建全局配置实例
_global_config: Optional[ConfigManager] = None


def get_config(config_path: str = None, config_dict: Dict = None, reload: bool = False) -> ConfigManager:
    """
    获取全局配置实例（单例模式）
    
    Args:
        config_path: YAML配置文件路径
        config_dict: 直接传入的配置字典
        reload: 是否重新加载
    
    Returns:
        ConfigManager实例
    """
    global _global_config
    
    if _global_config is None or reload:
        _global_config = ConfigManager(config_path, config_dict)
    
    return _global_config


