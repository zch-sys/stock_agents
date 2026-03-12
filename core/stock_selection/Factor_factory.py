"""
因子计算引擎

功能说明：
1. 智能计算模式：自动判断首次计算 vs 增量计算
2. 单一入口：通过 FactorEngine 类的 run() 方法统一调度
3. 配置由外部调度器传入，不在此文件内部管理

计算模式说明：
- 首次计算：因子数据库无数据时，读取所有数据源，选取最晚的起始日期进行全量计算
- 增量计算：当更新日期距当前日期不超过配置的天数阈值时，仅计算新增日期的因子
- 全量重算：超过阈值或数据异常时，执行全量重新计算
"""

import gc
import sys
import logging
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from functools import wraps
from enum import Enum
import io
from datetime import datetime, timedelta, date
import csv

# 获取项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import psutil
from sqlalchemy import select, delete, inspect, func
from tqdm import tqdm

# 导入数据库模型
try:
    from data.basic_data.database import (
        Base, MarketIndex, SectorData, StockDetail, StockFactor,
        init_db, get_session
    )
except ImportError as e:
    print(f"请确保 database.py 在项目路径中，且包含 StockFactor 模型。错误: {e}")
    sys.exit(1)


# ===================== 计算模式枚举 =====================
class ComputeMode(Enum):
    """计算模式枚举"""
    FULL = "full"              # 全量计算（首次）
    INCREMENTAL = "incremental"  # 增量计算
    REBUILD = "rebuild"        # 强制重建


# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")
pd.set_option("display.max_columns", None)


# ===================== 工具类 =====================
class QuantUtils:
    """量化工具类"""

    @staticmethod
    def clean_inf_nan(df: pd.DataFrame) -> pd.DataFrame:
        """清理无穷值和NaN"""
        return df.replace([np.inf, -np.inf], np.nan)

    @staticmethod
    def optimize_dtypes(df: pd.DataFrame) -> pd.DataFrame:
        """优化数据类型"""
        for col in df.select_dtypes(include=['float64']).columns:
            df[col] = df[col].astype(np.float32)
        for col in df.select_dtypes(include=['int64']).columns:
            df[col] = df[col].astype(np.int32)
        if "industry" in df.columns:
            df["industry"] = df["industry"].astype("category")
        if "ts_code" in df.columns:
            df["ts_code"] = df["ts_code"].astype("category")
        if "trade_date" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["trade_date"]):
            df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df

    @staticmethod
    def batch_winsorize_optimized(df: pd.DataFrame, factor_cols: List[str],
                                  limits: Tuple[float, float],
                                  group_keys: List[str] = ["trade_date", "industry"]) -> pd.DataFrame:
        """批量缩尾处理"""
        if not factor_cols or df.empty:
            return df
        lower_lim, upper_lim = limits
        counts = df.groupby(group_keys)[factor_cols[0]].transform('size')
        mask_valid = counts >= 5
        if not mask_valid.any():
            return df
        try:
            q_low = df.groupby(group_keys)[factor_cols].quantile(lower_lim)
            q_high = df.groupby(group_keys)[factor_cols].quantile(upper_lim)
        except TypeError:
            numeric_cols = df[factor_cols].select_dtypes(include=np.number).columns.tolist()
            q_low = df.groupby(group_keys)[numeric_cols].quantile(lower_lim)
            q_high = df.groupby(group_keys)[numeric_cols].quantile(upper_lim)
            factor_cols = numeric_cols

        df_result = df.copy()
        merged = df[group_keys].merge(q_low, on=group_keys, how='left', suffixes=('', '_low'))
        merged_high = df[group_keys].merge(q_high, on=group_keys, how='left', suffixes=('', '_high'))
        mask_arr = mask_valid.values
        for col in factor_cols:
            data_vals = df_result[col].values
            low_vals = merged[col].values
            high_vals = merged_high[col].values
            clipped = np.maximum(np.minimum(data_vals, high_vals), low_vals)
            df_result[col] = np.where(mask_arr, clipped, data_vals)
        return df_result

    @staticmethod
    def calc_grouped_return(df: pd.DataFrame, price_col: str, windows: List[int], config) -> pd.DataFrame:
        """计算分组收益率"""
        df = df.copy()
        for w in windows:
            df[f"return_{w}d"] = df.groupby("ts_code")[price_col].transform(lambda x: np.log(x / x.shift(w)))
            df[f"simple_return_{w}d"] = df.groupby("ts_code")[price_col].transform(lambda x: x.pct_change(w))
        return df

    @staticmethod
    def fill_missing_by_strategy(df: pd.DataFrame, factor_cols: List[str], config) -> pd.DataFrame:
        """按策略填充缺失值"""
        df = df.sort_values(['ts_code', 'trade_date']).copy()
        if not pd.api.types.is_datetime64_any_dtype(df['trade_date']):
            df['trade_date'] = pd.to_datetime(df['trade_date'])
        for factor in tqdm(factor_cols, desc="填充缺失值"):
            if factor not in df.columns:
                continue
            df[factor] = df.groupby('ts_code')[factor].ffill(limit=config.FILL_LIMIT)
            hist_mean = df.groupby('ts_code')[factor].transform(lambda x: x.expanding(min_periods=20).mean())
            df[factor] = df[factor].fillna(hist_mean)

            daily_ind_mean = df.groupby(['trade_date', 'industry'])[factor].mean().reset_index()
            daily_ind_mean = daily_ind_mean.rename(columns={factor: 'ind_mean_val'})
            df = df.merge(daily_ind_mean, on=['trade_date', 'industry'], how='left')
            df['ind_mean_val_lag'] = df.groupby('ts_code')['ind_mean_val'].shift(1)
            df[factor] = df[factor].fillna(df['ind_mean_val_lag'])
            df.drop(columns=['ind_mean_val', 'ind_mean_val_lag'], inplace=True, errors='ignore')
        return df

    @staticmethod
    def pre_optimize_df(df: pd.DataFrame) -> pd.DataFrame:
        """预优化DataFrame"""
        if "industry" in df.columns:
            df["industry"] = df["industry"].astype("category")
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        float_cols = df.select_dtypes("float64").columns
        df[float_cols] = df[float_cols].astype("float32")
        return df


def memory_optimized(func):
    """内存优化装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        process = psutil.Process()
        start_mem = process.memory_info().rss / 1024 / 1024
        start_time = time.time()
        logger.info(f"{func.__name__} 开始执行，当前内存: {start_mem:.1f}MB")
        result = func(*args, **kwargs)
        gc.collect()
        end_time = time.time()
        end_mem = process.memory_info().rss / 1024 / 1024
        logger.info(f"{func.__name__} 执行完成，耗时: {end_time - start_time:.1f}s, 内存变化: {end_mem - start_mem:+.1f}MB")
        return result
    return wrapper


# ===================== 因子计算引擎 =====================
class FactorEngine:
    """
    因子计算引擎

    核心功能：
    1. 自动检测计算模式（首次全量/增量更新）
    2. 统一入口执行因子计算流程
    3. 配置由外部传入

    使用示例：
        engine = FactorEngine(config=my_config)
        engine.run()  # 自动判断计算模式
    """

    def __init__(self, config, db_url: str = None):
        """
        初始化因子计算引擎

        Args:
            config: 配置对象，必须包含以下属性：
                    - DB_URL, CHUNK_SIZE, WINSORIZE_LIMIT, LIST_DAY_THRESHOLD
                    - FILL_LIMIT, CORR_THRESHOLD, RETURN_WINDOWS, VOLATILITY_WINDOWS
                    - MOMENTUM_SUFFIXES, REVERSAL_SUFFIXES, EPS, MIN_VALID_STOCKS
                    - MAX_MARKET_DATES, MAX_DAYS_GAP, TABLE_COLUMNS
                    - TIME_SERIES_FACTORS, VALUATION_FACTORS, NEUTRALIZE_FACTORS, NON_FACTOR_COLS
            db_url: 数据库连接URL，默认从配置读取
        """
        self.config = config

        # 初始化数据库
        self.db_url = db_url or config.DB_URL
        init_db(self.db_url)
        self.session = get_session()
        self.engine = self.session.get_bind()

        # 数据存储
        self.raw_stock: Optional[pd.DataFrame] = None
        self.raw_sector: Optional[pd.DataFrame] = None
        self.raw_market: Optional[pd.DataFrame] = None
        self.clean_market: Optional[pd.DataFrame] = None
        self.clean_sector: Optional[pd.DataFrame] = None
        self.clean_stock: Optional[pd.DataFrame] = None
        self.merged_data: Optional[pd.DataFrame] = None
        self.processed_factors: Optional[pd.DataFrame] = None
        self.market_dates: Optional[List] = None

        # 计算状态
        self.compute_mode: Optional[ComputeMode] = None
        self.start_date: Optional[date] = None
        self.end_date: Optional[date] = None
        self.factor_dates: Optional[List[date]] = None

    def detect_compute_mode(self) -> ComputeMode:
        """检测计算模式"""
        logger.info("=== 检测计算模式 ===")

        # 检查因子数据库是否有数据
        try:
            factor_count = self.session.query(func.count(StockFactor.id)).scalar()
        except Exception as e:
            logger.warning(f"无法查询因子数据库: {e}")
            factor_count = 0

        if factor_count == 0:
            logger.info("因子数据库为空，判定为【首次计算】模式")
            return ComputeMode.FULL

        # 获取因子数据库的最新更新日期
        try:
            latest_update = self.session.query(func.max(StockFactor.updated_at)).scalar()
            latest_trade_date = self.session.query(func.max(StockFactor.trade_date)).scalar()
        except Exception as e:
            logger.warning(f"无法获取因子更新时间: {e}")
            return ComputeMode.FULL

        if latest_update is None:
            logger.info("无法获取更新时间，判定为【首次计算】模式")
            return ComputeMode.FULL

        # 计算日期差
        now = datetime.now()
        if isinstance(latest_update, datetime):
            days_gap = (now - latest_update).days
        else:
            days_gap = (now.date() - latest_update).days if hasattr(latest_update, 'date') else 999

        logger.info(f"上次更新时间: {latest_update}, 距今天数: {days_gap}")

        if days_gap <= self.config.MAX_DAYS_GAP:
            logger.info(f"日期差 {days_gap} 天 <= 阈值 {self.config.MAX_DAYS_GAP} 天，判定为【增量计算】模式")
            self.start_date = latest_trade_date if latest_trade_date else None
            return ComputeMode.INCREMENTAL
        else:
            logger.info(f"日期差 {days_gap} 天 > 阈值 {self.config.MAX_DAYS_GAP} 天，判定为【全量重建】模式")
            return ComputeMode.REBUILD

    def _get_source_date_range(self) -> Tuple[Optional[date], Optional[date]]:
        """获取各数据源的日期范围"""
        logger.info("=== 获取数据源日期范围 ===")

        dates_info = {}

        # 获取 stock_detail 日期范围
        try:
            stock_min = self.session.query(func.min(StockDetail.trade_date)).scalar()
            stock_max = self.session.query(func.max(StockDetail.trade_date)).scalar()
            dates_info['stock'] = (stock_min, stock_max)
            logger.info(f"Stock: {stock_min} ~ {stock_max}")
        except Exception as e:
            logger.warning(f"无法获取 StockDetail 日期范围: {e}")

        # 获取 market_index 日期范围
        try:
            market_min = self.session.query(func.min(MarketIndex.trade_date)).scalar()
            market_max = self.session.query(func.max(MarketIndex.trade_date)).scalar()
            dates_info['market'] = (market_min, market_max)
            logger.info(f"Market: {market_min} ~ {market_max}")
        except Exception as e:
            logger.warning(f"无法获取 MarketIndex 日期范围: {e}")

        # 获取 sector_data 日期范围
        try:
            sector_min = self.session.query(func.min(SectorData.trade_date)).scalar()
            sector_max = self.session.query(func.max(SectorData.trade_date)).scalar()
            dates_info['sector'] = (sector_min, sector_max)
            logger.info(f"Sector: {sector_min} ~ {sector_max}")
        except Exception as e:
            logger.warning(f"无法获取 SectorData 日期范围: {e}")

        if not dates_info:
            logger.error("无法获取任何数据源的日期范围")
            return None, None

        # 计算最晚的起始日期
        all_min_dates = [v[0] for v in dates_info.values() if v[0] is not None]
        all_max_dates = [v[1] for v in dates_info.values() if v[1] is not None]

        if not all_min_dates or not all_max_dates:
            return None, None

        def ensure_date(d):
            if isinstance(d, datetime):
                return d.date()
            elif isinstance(d, str):
                return datetime.strptime(d, '%Y-%m-%d').date()
            return d

        start_date = max(ensure_date(d) for d in all_min_dates)
        end_date = max(ensure_date(d) for d in all_max_dates)

        logger.info(f"计算起始日期: {start_date}, 结束日期: {end_date}")
        return start_date, end_date

    def _get_incremental_dates(self) -> List[date]:
        """获取增量计算所需的日期列表"""
        logger.info("=== 获取增量计算日期 ===")

        try:
            latest_factor_date = self.session.query(func.max(StockFactor.trade_date)).scalar()
        except Exception as e:
            logger.warning(f"无法获取因子最新日期: {e}")
            latest_factor_date = None

        _, end_date = self._get_source_date_range()
        if end_date is None:
            logger.error("无法获取数据源最新日期")
            return []

        if latest_factor_date is None:
            return None

        def ensure_date(d):
            if isinstance(d, datetime):
                return d.date()
            elif isinstance(d, str):
                return datetime.strptime(d, '%Y-%m-%d').date()
            return d

        latest = ensure_date(latest_factor_date)
        if latest >= end_date:
            logger.info("因子数据已是最新，无需增量计算")
            return []

        try:
            query = select(MarketIndex.trade_date).where(
                MarketIndex.trade_date > latest,
                MarketIndex.ts_code == '000001.SH'
            ).distinct().order_by(MarketIndex.trade_date)
            result = self.session.execute(query).scalars().all()

            dates = [ensure_date(d) for d in result]
            logger.info(f"增量计算日期数量: {len(dates)}, 范围: {dates[0] if dates else 'N/A'} ~ {dates[-1] if dates else 'N/A'}")
            return dates
        except Exception as e:
            logger.error(f"获取增量日期失败: {e}")
            return []

    # ==================== 数据加载方法 ====================

    @memory_optimized
    def load_raw_data(self, start_date: date = None, end_date: date = None, dates: List[date] = None):
        """加载原始数据"""
        logger.info(f"=== 开始加载原始数据 (模式: {'增量' if dates else '全量'}) ===")

        table_mapping = {"stock": StockDetail, "sector": SectorData, "market": MarketIndex}
        results = {}

        for name, model in table_mapping.items():
            logger.info(f"加载{name}数据...")
            cols = self.config.TABLE_COLUMNS.get(name, [])

            col_attrs = [getattr(model, c) for c in cols if hasattr(model, c)]
            query = select(*col_attrs)

            if dates:
                query = query.where(getattr(model, "trade_date").in_(dates))
            elif start_date:
                query = query.where(getattr(model, "trade_date") >= start_date)
            if end_date:
                query = query.where(getattr(model, "trade_date") <= end_date)

            chunks = []
            for chunk in pd.read_sql(query, self.engine, chunksize=self.config.CHUNK_SIZE):
                chunks.append(QuantUtils.optimize_dtypes(chunk))
            results[name] = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()

        self.raw_stock, self.raw_sector, self.raw_market = results["stock"], results["sector"], results["market"]
        logger.info(f"数据加载完成: stock={len(self.raw_stock)}, sector={len(self.raw_sector)}, market={len(self.raw_market)}")
        return self

    @memory_optimized
    def preprocess_market_data(self):
        """处理大盘数据"""
        logger.info("=== 处理大盘数据 ===")
        df = QuantUtils.clean_inf_nan(self.raw_market)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        sh_idx_data = df[df["ts_code"] == "000001.SH"]
        market_dates = sorted(sh_idx_data["trade_date"].unique())

        if len(market_dates) > self.config.MAX_MARKET_DATES:
            market_dates = market_dates[-self.config.MAX_MARKET_DATES:]

        sh_idx_data = sh_idx_data[sh_idx_data["trade_date"].isin(market_dates)]
        num_cols = sh_idx_data.select_dtypes(include=np.number).columns
        sh_idx_data[num_cols] = sh_idx_data[num_cols].fillna(sh_idx_data[num_cols].median())
        self.market_dates = market_dates
        self.clean_market = sh_idx_data
        return self

    @memory_optimized
    def preprocess_sector_data(self):
        """处理板块数据"""
        logger.info("=== 处理板块数据 ===")
        df = QuantUtils.clean_inf_nan(self.raw_sector)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        if self.market_dates:
            df = df[df["trade_date"].isin(self.market_dates)]
        df = df.drop_duplicates(subset=["sector_code", "trade_date"])

        pivot_dfs = {}
        numeric_cols = df.select_dtypes(include=np.number).columns.tolist()
        for col in numeric_cols:
            try:
                pivot_df = df.pivot_table(index="trade_date", columns="sector_code", values=col, aggfunc="first")
                pivot_df = pivot_df.ffill(axis=0).apply(lambda x: x.fillna(x.median()), axis=1)
                pivot_dfs[col] = pivot_df
            except:
                pass

        if pivot_dfs:
            melted_dfs = []
            for col, pivot_df in pivot_dfs.items():
                melted = pivot_df.stack().reset_index()
                melted.columns = ["trade_date", "sector_code", col]
                melted_dfs.append(melted.set_index(["trade_date", "sector_code"])[col])
            result = pd.concat(melted_dfs, axis=1).reset_index()
            sector_names = df[["sector_code", "sector_name"]].drop_duplicates("sector_code").set_index("sector_code")["sector_name"]
            result["sector_name"] = result["sector_code"].map(sector_names)
            df = result
        self.clean_sector = df
        return self

    @memory_optimized
    def preprocess_stock_data(self):
        """处理个股数据"""
        logger.info("=== 处理个股数据 ===")
        df = QuantUtils.clean_inf_nan(self.raw_stock)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        df["list_date"] = pd.to_datetime(df["list_date"]).dt.date
        if self.market_dates:
            df = df[df["trade_date"].isin(self.market_dates)]

        # 计算上市天数，过滤上市不足120天的股票
        df["list_days"] = (pd.to_datetime(df["trade_date"]) - pd.to_datetime(df["list_date"])).dt.days
        df = df[df["list_days"] >= self.config.LIST_DAY_THRESHOLD]

        # ===== 成交额单位转换 =====
        # tushare返回的amount单位是"千元"，转换为"万元"以便统一
        # 转换系数：1千元 = 0.1万元
        df["amount"] *= 0.1
        df["log_circ_mv"] = np.log1p(df["circ_mv"].fillna(1))
        df["log_total_mv"] = np.log1p(df["total_mv"].fillna(1))

        # 技术指标和基本面数据的缺失值填充
        fill_groups = {
            "tech": ["ma5", "ma10", "ma20", "ma60", "macd", "macd_signal", "macd_hist", "rsi6", "rsi12", "rsi24",
                    "boll_upper", "boll_middle", "boll_lower"],
            "fundamental": ["pe", "pb", "ps", "dv_ttm", "debt_to_assets", "current_ratio", "quick_ratio", "cash_ratio",
                            "revenue_yoy", "profit_yoy"]
        }
        for group, cols in fill_groups.items():
            for col in cols:
                if col not in df.columns:
                    continue
                if group == "tech":
                    df[col] = df.groupby("ts_code")[col].ffill()
                else:
                    df[col] = df.groupby("ts_code")[col].ffill()
                    df[col] = df[col].fillna(df.groupby(["industry", "trade_date"])[col].transform("mean"))

        self.clean_stock = df.drop_duplicates(subset=["ts_code", "trade_date"])
        return self

    @memory_optimized
    def merge_multi_level_data(self):
        """融合数据"""
        logger.info("=== 融合数据 ===")
        market_core = self.clean_market[self.clean_market["ts_code"] == "000001.SH"][
            ["trade_date", "pct_chg", "amount", "north_money_total"]].rename(
            columns={"pct_chg": "market_pct_chg", "amount": "market_amount", "north_money_total": "market_north_money_total"})
        sector_core = self.clean_sector[["sector_name", "trade_date", "pct_chg", "amount"]].rename(
            columns={"sector_name": "industry_name", "pct_chg": "sector_pct_chg", "amount": "sector_amount"})
        stock_cols = self.config.TABLE_COLUMNS.get("stock", []) + ["log_circ_mv", "log_total_mv"]
        stock_core = self.clean_stock[stock_cols]

        merged = pd.merge(stock_core, sector_core, left_on=["industry", "trade_date"],
                          right_on=["industry_name", "trade_date"], how="inner")
        merged = pd.merge(merged, market_core, on="trade_date", how="inner").drop(columns=["industry_name"],
                                                                                  errors="ignore")
        self.merged_data = merged.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        return self

    # ==================== 因子构建方法 ====================
    @memory_optimized
    def build_enhanced_factors(self):
        """构建增强因子（深度向量化与性能优化版）"""
        logger.info("=== 构建因子 ===")
        # 1. 基础排序与清洗
        df = self.merged_data.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        df = QuantUtils.clean_inf_nan(df)

        # 2. 收益率计算（必须最先执行，因为后续很多因子依赖它生成的列）
        df = QuantUtils.calc_grouped_return(df, "close", self.config.RETURN_WINDOWS, self.config)

        # 3. 定义 GroupBy 对象（此时 simple_return_1d 等列已存在，g_ts 可以识别它们）
        g_ts = df.groupby("ts_code")
        g_date_ind = df.groupby(["trade_date", "industry"])

        # --- 动量 ---
        for suffix in self.config.MOMENTUM_SUFFIXES:
            df[f"momentum_{suffix}"] = df[f"simple_return_{suffix}"]
        df["momentum_acceleration"] = df["simple_return_5d"] - df["simple_return_20d"]
        
        # 截面排名：新生成的列建议直接用 df.groupby 确保 100% 安全
        df["momentum_rank_20d"] = df.groupby(["trade_date", "industry"])["momentum_20d"].rank(pct=True)
        df["momentum_rank_120d"] = df.groupby(["trade_date", "industry"])["momentum_120d"].rank(pct=True)
        
        for suffix in self.config.REVERSAL_SUFFIXES:
            df[f"reversal_{suffix}"] = -df[f"simple_return_{suffix}"]

        # --- 波动率 ---
        for w in self.config.VOLATILITY_WINDOWS:
            df[f"volatility_{w}d"] = g_ts["simple_return_1d"].rolling(w, min_periods=3).std().reset_index(0, drop=True)
        df["volatility_change"] = df["volatility_10d"] / df["volatility_20d"].clip(lower=self.config.EPS)
        df["volatility_long_term_dev"] = df["volatility_60d"] / df["volatility_120d"].clip(lower=self.config.EPS)
        df["low_volatility"] = -df["volatility_60d"].rank(pct=True)

        # 日内与隔夜
        df["overnight_return"] = (df["open"] / df["pre_close"] - 1)
        df["overnight_momentum"] = g_ts["overnight_return"].rolling(5, min_periods=3).mean().reset_index(0, drop=True)
        df["open_gap"] = (df["open"] - df["pre_close"]) / df["pre_close"].clip(lower=self.config.EPS)
        df["gap_ratio"] = df["open_gap"] / (df["volatility_10d"] + self.config.EPS)
        df["intraday_return"] = (df["close"] / df["open"] - 1)
        df["intraday_strength"] = df["intraday_return"] / (df["volatility_5d"] + self.config.EPS)
        df["high_low_ratio"] = (df["high"] - df["low"]) / df["close"].clip(lower=self.config.EPS)
        df["price_position"] = (df["close"] - df["low"]) / (df["high"] - df["low"]).clip(lower=self.config.EPS)

        # 量价
        vol_ma5 = g_ts["vol"].rolling(5, min_periods=3).mean().reset_index(0, drop=True)
        vol_ma20 = g_ts["vol"].rolling(20, min_periods=3).mean().reset_index(0, drop=True)
        df["volume_relative_strength"] = vol_ma5 / vol_ma20.clip(lower=self.config.EPS)
        pc_5d = g_ts["close"].pct_change(5)
        vc_5d = g_ts["vol"].pct_change(5)
        df["price_volume_divergence"] = -np.abs(pc_5d - vc_5d)
        df["price_volume_strength"] = pc_5d * vc_5d

        # 均线斜率
        df["ma5_slope"] = g_ts["ma5"].pct_change()
        df["ma10_slope"] = g_ts["ma10"].pct_change()
        df["ma_slope_diff"] = df["ma5_slope"] - df["ma10_slope"]

        # 行业相对
        ind_avg = g_date_ind["pct_chg"].transform("mean")
        df["industry_relative_strength"] = df["pct_chg"] - ind_avg
        ind_amount = g_date_ind["amount"].transform("sum").clip(lower=self.config.EPS)
        df["amount_concentration"] = df["amount"] / ind_amount
        df["volatility_anomaly"] = df["volatility_5d"] / df["volatility_20d"].clip(lower=self.config.EPS) - 1

        # 估值
        df = QuantUtils.optimize_dtypes(df)
        df["pe_safe"] = df["pe"].clip(0.5, 300).fillna(self.config.EPS)
        df["pb_safe"] = df["pb"].clip(0.1, 100).fillna(self.config.EPS)
        df["ps_safe"] = df["ps"].clip(0.1, 200).fillna(self.config.EPS)
        df["ep"] = 1.0 / df["pe_safe"]
        df["bp"] = 1.0 / df["pb_safe"]
        df["sp"] = 1.0 / df["ps_safe"]
        val_factors = ["ep", "bp", "sp"]
        
        # 优化分位数计算逻辑
        g_val = df.groupby(["trade_date", "industry"], observed=True)
        for col in val_factors:
            q1 = g_val[col].transform(lambda x: x.quantile(0.01))
            q99 = g_val[col].transform(lambda x: x.quantile(0.99))
            df[col] = df[col].clip(q1, q99)
            
        df["pe_industry_rank"] = g_val["pe_safe"].rank(pct=True, method="min")
        df["pb_industry_rank"] = g_val["pb_safe"].rank(pct=True, method="min")
        df["value_score"] = df[val_factors].rank(pct=True).mean(axis=1)

        # 成长
        df["revenue_growth"] = df["revenue_yoy"].clip(-1000, 1000)
        df["profit_growth"] = df["profit_yoy"].clip(-1000, 1000)
        df["growth_score"] = (df["revenue_growth"].rank(pct=True) + df["profit_growth"].rank(pct=True)) / 2

        # 质量
        equity = df["total_assets"] - df["total_liab"]
        df["roe"] = (df["net_profit"] / equity.mask(equity <= 0, np.nan)).clip(-5, 5)
        df["profit_margin"] = df["net_profit"] / df["revenue"].mask(df["revenue"] <= 0, np.nan)
        df["leverage"] = df["total_liab"] / df["total_assets"].mask(df["total_assets"] <= 0, np.nan)
        df["current_ratio_safe"] = df["current_ratio"].clip(0.01, 100)
        quality_metrics = ["roe", "profit_margin", "current_ratio_safe"]
        df["quality_score"] = sum(df[m].rank(pct=True) for m in quality_metrics) / len(quality_metrics)

        # 技术指标位置
        df["rsi6_position"] = (df["rsi6"] - 50) / 50
        df["macd_signal_diff"] = df["macd"] - df["macd_signal"]
        boll_width = (df["boll_upper"] - df["boll_lower"]).clip(lower=self.config.EPS)
        df["boll_position"] = (df["close"] - df["boll_lower"]) / boll_width

        # 量比
        df["volume_ratio"] = df["vol"] / vol_ma20.clip(lower=self.config.EPS)
        amount_ma20 = g_ts["amount"].rolling(20, min_periods=3).mean().reset_index(0, drop=True)
        df["amount_ratio"] = df["amount"] / amount_ma20.clip(lower=self.config.EPS)

        # 相对强弱
        df["sector_relative"] = df["pct_chg"] - df["sector_pct_chg"]
        df["market_relative"] = df["pct_chg"] - df["market_pct_chg"]
        df["north_flow_impact"] = df["market_north_money_total"] / (df["market_amount"] + self.config.EPS)

        # 市值规模
        df["size_factor"] = df["log_circ_mv"].rank(pct=True)
        df["small_cap_premium"] = 1 - df["size_factor"]

        # 复合因子
        compound_pairs = [
            ("value_momentum", "value_score", "momentum_120d"),
            ("quality_value", "quality_score", "value_score"),
            ("growth_momentum", "growth_score", "momentum_60d")
        ]
        for new_col, f1, f2 in compound_pairs:
            df[new_col] = df[f1].rank(pct=True) * df[f2].rank(pct=True)

        # ========== 新增因子计算 (极速向量化版) ==========
        
        # ----- 1. 趋势因子 -----
        df["bias_20d"] = (df["close"] - df["ma20"]) / df["ma20"].clip(lower=self.config.EPS)
        
        high_20 = g_ts["high"].rolling(20, min_periods=10).max().reset_index(0, drop=True)
        low_20 = g_ts["low"].rolling(20, min_periods=10).min().reset_index(0, drop=True)
        df["donchian_breakout"] = (df["close"] - low_20) / (high_20 - low_20).clip(lower=self.config.EPS)
        df["macd_slope"] = g_ts["macd"].diff(5) / 5
        
        # 优化版 Hurst：底层 Numpy 运算
        def calc_hurst_fast(arr):
            arr = arr[~np.isnan(arr)]
            n = len(arr)
            if n < 30: return np.nan
            mean_val = np.mean(arr)
            cum_dev = np.cumsum(arr - mean_val)
            R = np.max(cum_dev) - np.min(cum_dev)
            S = np.std(arr)
            if S < 1e-10: return 0.5
            H = np.log(R / S + 1e-10) / np.log(n / 2)
            return np.clip(H, 0, 1)

        df["hurst_exp"] = g_ts["close"].rolling(60, min_periods=30).apply(
            calc_hurst_fast, raw=True
        ).reset_index(0, drop=True)
        
        # 优化版 Adam：避免 Python 列表与循环
        def calc_adam_symmetry_fast(arr):
            arr = arr[~np.isnan(arr)]
            if len(arr) < 10: return np.nan
            recent = arr[-20:]
            n = len(recent)
            half = n // 2
            center = recent[half]
            up_moves = np.maximum(0, recent[half:] - center)
            down_moves = np.maximum(0, center - recent[:half])
            up_avg = np.mean(up_moves)
            down_avg = np.mean(down_moves)
            total = up_avg + down_avg
            if total < 1e-10: return 0.0
            return (up_avg - down_avg) / total

        df["adam_symmetry"] = g_ts["close"].rolling(20, min_periods=10).apply(
            calc_adam_symmetry_fast, raw=True
        ).reset_index(0, drop=True)
        
        # ----- 2. 量价因子 -----
        ret_20d = g_ts["close"].pct_change(20)
        vol_ratio_20d = df["vol"] / g_ts["vol"].rolling(20, min_periods=10).mean().reset_index(0, drop=True).clip(lower=self.config.EPS)
        df["vmom_20d"] = ret_20d * vol_ratio_20d
        
        price_change = g_ts["close"].diff()
        vol_change = g_ts["vol"].diff()
        df["vp_coordination"] = np.sign(price_change) * np.sign(vol_change)
        df["vp_coordination"] = g_ts["vp_coordination"].rolling(10, min_periods=5).mean().reset_index(0, drop=True)
        
        # ----- 3. 波动因子 -----
        df["_neg_ret"] = np.where(df["simple_return_1d"] < 0, df["simple_return_1d"], 0)
        df["downside_vol_20d"] = g_ts["_neg_ret"].rolling(20, min_periods=10).std().reset_index(0, drop=True)
        
        # ----- 4 & 6 & 7. 向量化高低价回归因子（性能提升核心） -----
        # 内部闭包用于向量化计算任意窗口的滚动线性回归（替代缓慢的 np.polyfit）
        def calc_rolling_regression_stats(x_col, y_col, window, min_periods):
            x, y = df[x_col], df[y_col]
            mean_x = g_ts[x_col].rolling(window, min_periods=min_periods).mean().reset_index(0, drop=True)
            mean_y = g_ts[y_col].rolling(window, min_periods=min_periods).mean().reset_index(0, drop=True)
            
            # 临时将乘积和平方赋予 df，以利用 g_ts 快速滚动
            df["_xy"], df["_x2"], df["_y2"] = x * y, x ** 2, y ** 2
            mean_xy = g_ts["_xy"].rolling(window, min_periods=min_periods).mean().reset_index(0, drop=True)
            mean_x2 = g_ts["_x2"].rolling(window, min_periods=min_periods).mean().reset_index(0, drop=True)
            mean_y2 = g_ts["_y2"].rolling(window, min_periods=min_periods).mean().reset_index(0, drop=True)
            
            cov_xy = mean_xy - mean_x * mean_y
            var_x = (mean_x2 - mean_x ** 2).replace(0, np.nan).clip(lower=1e-12)
            var_y = (mean_y2 - mean_y ** 2).replace(0, np.nan).clip(lower=1e-12)
            
            beta = cov_xy / var_x
            r2 = (cov_xy ** 2) / (var_x * var_y)
            return beta, r2

        # 批量计算 20日, 60日, 120日 Beta 与 R2
        df["hl_beta_20d"], df["hl_correlation_20d"] = calc_rolling_regression_stats("low", "high", 20, 10)
        df["hl_beta_60d"], _ = calc_rolling_regression_stats("low", "high", 60, 30)
        df["long_term_channel_beta"], _ = calc_rolling_regression_stats("low", "high", 120, 60)
        
        # 20日与60日 VRRS
        residual_vol_20 = g_ts["high"].rolling(20, min_periods=10).std().reset_index(0, drop=True)
        residual_vol_60 = g_ts["high"].rolling(60, min_periods=30).std().reset_index(0, drop=True)
        df["vrrs_20d"] = df["hl_beta_20d"] * df["hl_correlation_20d"] / residual_vol_20.clip(lower=self.config.EPS)
        df["vrrs_60d"] = df["hl_beta_60d"] * df["hl_correlation_20d"] / residual_vol_60.clip(lower=self.config.EPS)
        
        # HSRS
        high_high = g_ts["high"].rolling(20, min_periods=10).max().reset_index(0, drop=True)
        low_low = g_ts["low"].rolling(20, min_periods=10).min().reset_index(0, drop=True)
        mid_price = (high_high + low_low) / 2
        df["hsrs_beta"] = (df["close"] - mid_price) / (high_high - low_low).clip(lower=self.config.EPS)
        
        close_ma20 = g_ts["close"].rolling(20, min_periods=10).mean().reset_index(0, drop=True)
        df["_hsrs_diff"] = df["close"] - close_ma20
        df["hsrs_residual_vol"] = g_ts["_hsrs_diff"].rolling(20, min_periods=10).std().reset_index(0, drop=True)
        
        # 通道与区间
        df["channel_strength"] = (df["close"] - df["boll_middle"]) / (df["boll_upper"] - df["boll_lower"]).clip(lower=self.config.EPS)
        df["range_extension"] = (df["close"] - close_ma20) / (high_20 - low_20).clip(lower=self.config.EPS)
        
        # 涨跌 Beta 不对称性 (向量化取代 where)
        df["_up_ret"] = np.where(df["simple_return_1d"] > 0, df["simple_return_1d"], 0)
        up_vol = g_ts["_up_ret"].rolling(20, min_periods=5).std().reset_index(0, drop=True)
        down_vol = g_ts["_neg_ret"].rolling(20, min_periods=5).std().reset_index(0, drop=True)
        df["asymmetry_beta"] = (up_vol - down_vol) / (up_vol + down_vol).clip(lower=self.config.EPS)
        
        # ----- 5. 多维回归因子 -----
        body = np.abs(df["close"] - df["open"])
        upper_shadow = df["high"] - df[["open", "close"]].max(axis=1)
        lower_shadow = df[["open", "close"]].min(axis=1) - df["low"]
        total_range = (df["high"] - df["low"]).clip(lower=self.config.EPS)
        df["ohlc_structure"] = (body - upper_shadow - lower_shadow) / total_range
        
        # 趋势结构系数
        df["_pos_ret_nan"] = np.where(df["simple_return_1d"] > 0, df["simple_return_1d"], np.nan)
        df["_neg_ret_nan"] = np.where(df["simple_return_1d"] < 0, df["simple_return_1d"], np.nan)
        avg_up = g_ts["_pos_ret_nan"].rolling(20, min_periods=5).mean().reset_index(0, drop=True)
        avg_down = g_ts["_neg_ret_nan"].rolling(20, min_periods=5).mean().reset_index(0, drop=True)
        df["trend_structure_coef"] = avg_up.fillna(0) + avg_down.fillna(0)
        
        # 60日通道强度
        ma60_high = g_ts["high"].rolling(60, min_periods=30).mean().reset_index(0, drop=True)
        ma60_low = g_ts["low"].rolling(60, min_periods=30).mean().reset_index(0, drop=True)
        df["channel_strength_60d"] = (df["close"] - (ma60_high + ma60_low) / 2) / (ma60_high - ma60_low).clip(lower=self.config.EPS)

        # 清理所有的临时字段
        cols_to_drop = ["_neg_ret", "_up_ret", "_xy", "_x2", "_y2", "_hsrs_diff", "_pos_ret_nan", "_neg_ret_nan"]
        df.drop(columns=[c for c in cols_to_drop if c in df.columns], inplace=True)

        # 常数因子净化
        constant_prone_factors = [
            "volatility_change", "volatility_long_term_dev",
            "volume_relative_strength", "volatility_anomaly"
        ]
        
        # 这里也可避免 transform
        for col in constant_prone_factors:
            if col in df.columns:
                std_by_date = df.groupby("trade_date")[col].transform("std")
                df[col] = df[col].where(std_by_date > 1e-12, np.nan)

        df = QuantUtils.pre_optimize_df(df)
        self.merged_data = QuantUtils.clean_inf_nan(df)
        return self

    def _efficient_neutralization(self, df: pd.DataFrame, factor_cols: List[str]) -> pd.DataFrame:
        """高效中性化：去除市值与行业影响"""
        if df['industry'].dtype.name != 'category':
            df['industry'] = df['industry'].astype('category')
        global_categories = df['industry'].cat.categories

        result = pd.DataFrame(index=df.index)
        date_groups = df.groupby('trade_date', observed=True).indices

        for date, idx_pos in tqdm(date_groups.items(), desc="中性化"):
            n = len(idx_pos)
            if n < 2:
                for col in factor_cols:
                    y = df.iloc[idx_pos][col].values
                    not_nan = ~np.isnan(y)
                    if not_nan.any():
                        valid_labels = df.index[idx_pos][not_nan]
                        result.loc[valid_labels, f'{col}_neutral'] = y[not_nan]  # 保留原值
                continue

            log_mv = df.iloc[idx_pos]['log_circ_mv'].values.astype(np.float32)
            industry_series = df.iloc[idx_pos]['industry']

            cat_series = pd.Categorical(industry_series, categories=global_categories)
            ind_dummies = pd.get_dummies(cat_series, prefix='ind', drop_first=True).values.astype(np.float32)

            X_full = np.column_stack([np.ones(n, dtype=np.float32), log_mv, ind_dummies])
            X_simple = X_full[:, :2]

            orig_labels = df.index[idx_pos]

            for col in factor_cols:
                y = df.iloc[idx_pos][col].values.astype(np.float32)
                not_nan = ~np.isnan(y)
                n_valid = not_nan.sum()
                if n_valid == 0:
                    continue

                X_valid_full = X_full[not_nan]
                y_valid = y[not_nan]
                valid_labels = orig_labels[not_nan]

                success = False
                if X_valid_full.shape[1] <= n_valid:
                    try:
                        coef, _, _, _ = np.linalg.lstsq(X_valid_full, y_valid, rcond=None)
                        resid = y_valid - X_valid_full @ coef
                        result.loc[valid_labels, f'{col}_neutral'] = resid
                        success = True
                    except np.linalg.LinAlgError:
                        pass

                if not success:
                    X_valid_simple = X_simple[not_nan]
                    if X_valid_simple.shape[1] <= n_valid:
                        try:
                            coef, _, _, _ = np.linalg.lstsq(X_valid_simple, y_valid, rcond=None)
                            resid = y_valid - X_valid_simple @ coef
                            result.loc[valid_labels, f'{col}_neutral'] = resid
                            success = True
                        except np.linalg.LinAlgError:
                            pass

                if not success:
                    result.loc[valid_labels, f'{col}_neutral'] = y_valid

        return result

    @memory_optimized
    def preprocess_factors(self):
        """因子预处理：去极值 → 中性化 → 标准化"""
        logger.info("=== 执行因子预处理（去极值->中性化->标准化）===")

        df = self.merged_data.copy()
        logger.info(f"初始数据维度: {df.shape}")

        factor_cols = [
            col for col in df.columns
            if col not in self.config.NON_FACTOR_COLS
               and pd.api.types.is_numeric_dtype(df[col])
        ]
        logger.info(f"待处理因子数量: {len(factor_cols)}")

        df = QuantUtils.clean_inf_nan(df)
        df = QuantUtils.pre_optimize_df(df)

        # 从配置读取无需缩尾的因子（极值本身是因子的核心判断依据）
        no_winsorize_factors = getattr(self.config, 'NO_WINSORIZE_FACTORS', set())

        # 过滤掉无需缩尾的因子
        factor_cols_to_winsorize = [col for col in factor_cols if col not in no_winsorize_factors]
        logger.info(f"需要缩尾的因子数量: {len(factor_cols_to_winsorize)}，跳过缩尾的因子: {len(no_winsorize_factors & set(factor_cols))}")

        try:
            df = QuantUtils.batch_winsorize_optimized(
                df, factor_cols_to_winsorize, self.config.WINSORIZE_LIMIT, ["trade_date", "industry"]
            )
            logger.info("去极值完成")
        except Exception as e:
            logger.error(f"去极值失败: {e}")

        # 缺失值填充
        valuation_factor_cols = [col for col in factor_cols if col in self.config.VALUATION_FACTORS]
        time_series_factor_cols = [col for col in factor_cols if col in self.config.TIME_SERIES_FACTORS]
        other_factor_cols = [
            col for col in factor_cols
            if col not in time_series_factor_cols and col not in valuation_factor_cols
        ]

        NO_FILL_FACTORS = {
            "volatility_change", "volatility_long_term_dev",
            "volume_relative_strength", "volatility_anomaly"
        }
        other_factor_cols = [col for col in other_factor_cols if col not in NO_FILL_FACTORS]

        if valuation_factor_cols:
            for col in tqdm(valuation_factor_cols, desc="填充估值因子"):
                median_by_group = df.groupby(['trade_date', 'industry'])[col].transform('median')
                df[col] = df[col].fillna(median_by_group).fillna(df.groupby('trade_date')[col].transform('median'))

        if other_factor_cols:
            df = QuantUtils.fill_missing_by_strategy(df, other_factor_cols, self.config)

        # 中性化
        logger.info("执行中性化并覆盖原始因子...")
        neutralize_cols = [col for col in factor_cols if col in self.config.NEUTRALIZE_FACTORS]
        neutralized_result = self._efficient_neutralization(df, neutralize_cols)

        for col in factor_cols:
            neutral_col_name = f"{col}_neutral"
            if neutral_col_name in neutralized_result.columns:
                df[col] = neutralized_result[neutral_col_name]
        del neutralized_result
        gc.collect()

        # 标准化
        logger.info("执行标准化 (Z-Score)...")
        for col in tqdm(factor_cols, desc="标准化"):
            df[col] = df.groupby("trade_date")[col].transform(
                lambda x: (x - x.mean()) / x.std() if x.std() > self.config.EPS else 0.0
            )

        df['updated_at'] = datetime.now()
        db_columns = [c.name for c in StockFactor.__table__.columns if c.name != 'id']

        missing_cols = set(db_columns) - set(df.columns)
        for col in missing_cols:
            df[col] = np.nan

        final_cols = [col for col in db_columns if col in df.columns]
        self.processed_factors = df[final_cols].copy()

        del df
        gc.collect()
        return self

    @memory_optimized
    def save_to_db_fast(self):
        """PostgreSQL 分块极速导入（解决内存爆炸问题）"""
        if self.processed_factors is None or self.processed_factors.empty:
            logger.warning("无数据可保存")
            return self

        logger.info("=== PostgreSQL 分块 COPY 导入 ===")
        start_time = time.time()

        # 1. 准备基础数据（不立即复制整个DF）
        db_columns = [c.name for c in StockFactor.__table__.columns if c.name != 'id']
        
        # 补全更新时间
        if 'updated_at' not in self.processed_factors.columns:
            self.processed_factors['updated_at'] = datetime.now()

        # 2. 执行一次性清理（保持事务一致性）
        min_date = self.processed_factors['trade_date'].min()
        max_date = self.processed_factors['trade_date'].max()
        logger.info(f"清理 {min_date} 至 {max_date} 的旧数据...")
        try:
            stmt = delete(StockFactor).where(StockFactor.trade_date.between(min_date, max_date))
            self.session.execute(stmt)
            self.session.commit()
        except Exception as e:
            logger.error(f"清理失败: {e}")
            self.session.rollback()
            return self

        # 3. 分块注入逻辑
        chunk_size = 50000  # 每组5万行，可根据服务器内存调整
        total_rows = len(self.processed_factors)
        
        raw_conn = self.engine.raw_connection()
        try:
            with raw_conn.cursor() as cursor:
                columns_str = ', '.join(f'"{col}"' for col in db_columns)
                copy_sql = f"""
                    COPY stock_factor ({columns_str}) 
                    FROM STDIN WITH (FORMAT CSV, DELIMITER '\t', NULL '\\N', ENCODING 'UTF8')
                """
                
                for i in range(0, total_rows, chunk_size):
                    # 取出当前分块并只选择DB需要的列
                    chunk = self.processed_factors.iloc[i : i + chunk_size].reindex(columns=db_columns)
                    
                    # 使用 io.StringIO 作为临时中转
                    output = io.StringIO()
                    # 使用 Pandas 内置的 to_csv，速度比 csv.writer 快得多
                    chunk.to_csv(
                        output, 
                        sep='\t', 
                        index=False, 
                        header=False, 
                        na_rep='\\N', 
                        quoting=csv.QUOTE_MINIMAL,
                        date_format='%Y-%m-%d %H:%M:%S'
                    )
                    output.seek(0)
                    
                    # 执行 COPY
                    cursor.copy_expert(copy_sql, output)
                    
                    # 显式释放当前块的内存
                    output.close()
                    del chunk
                    
                    if (i + chunk_size) < total_rows:
                        logger.info(f"已导入: {i + chunk_size}/{total_rows} 行...")

            raw_conn.commit()
            elapsed = time.time() - start_time
            logger.info(f"分块导入完成！总耗时 {elapsed:.1f} 秒")
            
        except Exception as e:
            logger.error(f"COPY导入失败: {e}")
            raw_conn.rollback()
            raise
        finally:
            raw_conn.close()
            gc.collect() # 强制回收内存
            
        return self

    # ==================== 主入口方法 ====================

    def run(self, mode: ComputeMode = None, start_date: date = None, end_date: date = None):
        """
        执行因子计算的主入口方法

        Args:
            mode: 计算模式，None表示自动检测
            start_date: 起始日期（仅在 mode=FULL 时生效）
            end_date: 结束日期

        Returns:
            FactorEngine: 返回自身以支持链式调用
        """
        logger.info("=" * 60)
        logger.info("因子计算引擎启动")
        logger.info("=" * 60)

        try:
            if mode is None:
                mode = self.detect_compute_mode()
            self.compute_mode = mode
            logger.info(f"计算模式: {mode.value}")

            if mode == ComputeMode.FULL:
                self._run_full_compute(start_date, end_date)
            elif mode == ComputeMode.INCREMENTAL:
                self._run_incremental_compute()
            elif mode == ComputeMode.REBUILD:
                self._run_full_compute(start_date, end_date)
            else:
                raise ValueError(f"未知的计算模式: {mode}")

            logger.info("=" * 60)
            logger.info("因子计算完成")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"流程出错: {e}", exc_info=True)
            raise
        finally:
            self.session.close()

        return self

    def _run_full_compute(self, start_date: date = None, end_date: date = None):
        """执行全量计算"""
        logger.info(">>> 执行全量计算流程")

        if start_date is None or end_date is None:
            auto_start, auto_end = self._get_source_date_range()
            start_date = start_date or auto_start
            end_date = end_date or auto_end

        if start_date is None:
            raise ValueError("无法确定计算起始日期")

        self.start_date = start_date
        self.end_date = end_date
        logger.info(f"计算日期范围: {start_date} ~ {end_date}")

        (self.load_raw_data(start_date=start_date, end_date=end_date)
         .preprocess_market_data()
         .preprocess_sector_data()
         .preprocess_stock_data()
         .merge_multi_level_data()
         .build_enhanced_factors()
         .preprocess_factors()
         .save_to_db_fast())

    def _run_incremental_compute(self):
        """执行增量计算"""
        logger.info(">>> 执行增量计算流程")

        dates = self._get_incremental_dates()

        if not dates:
            logger.info("无需增量计算，数据已是最新")
            return self

        self.factor_dates = dates

        (self.load_raw_data(dates=dates)
         .preprocess_market_data()
         .preprocess_sector_data()
         .preprocess_stock_data()
         .merge_multi_level_data()
         .build_enhanced_factors()
         .preprocess_factors()
         .save_to_db_fast())

        return self

    def get_status(self) -> dict:
        """获取引擎状态信息"""
        return {
            "compute_mode": self.compute_mode.value if self.compute_mode else "未确定",
            "start_date": str(self.start_date) if self.start_date else None,
            "end_date": str(self.end_date) if self.end_date else None,
        }
