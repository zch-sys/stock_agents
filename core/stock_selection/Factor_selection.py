"""
因子筛选器

功能说明：
1. 智能更新判断：自动检测首次运行 vs 增量更新
2. 单一入口：通过 FactorSelector 类的 run() 方法统一调度
3. 配置由外部调度器传入，不在此文件内部管理

筛选模式说明：
- 首次运行：无因子配置文件时，执行完整筛选并输出配置文件
- 增量更新：检查配置文件日期，超过阈值时重新筛选对应周期因子
"""

import gc
import sys
import yaml
import logging
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, date
from enum import Enum

# 获取项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
from sqlalchemy import select, inspect, func
from tqdm import tqdm

# 导入数据库模型
try:
    from data.basic_data.database import StockFactor, init_db, get_session
except ImportError as e:
    print(f"请确保 database.py 在项目路径中。错误: {e}")
    sys.exit(1)

warnings.filterwarnings("ignore", category=RuntimeWarning, module="numpy")

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ===================== 筛选模式枚举 =====================
class SelectionMode(Enum):
    """筛选模式枚举"""
    FULL = "full"           # 全量筛选（首次）
    UPDATE = "update"       # 增量更新（部分周期）
    SKIP = "skip"           # 跳过（无需更新）


# ===================== 工具函数 =====================
def numpy_to_python(obj):
    """递归将numpy标量转换为Python原生类型"""
    if isinstance(obj, dict):
        return {k: numpy_to_python(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [numpy_to_python(i) for i in obj]
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, (pd.Timestamp, datetime)):
        return obj.strftime('%Y-%m-%d %H:%M:%S') if hasattr(obj, 'hour') else obj.strftime('%Y-%m-%d')
    elif isinstance(obj, date):
        return obj.strftime('%Y-%m-%d')
    else:
        return obj


# ===================== 因子筛选器 =====================
class FactorSelector:
    """
    因子筛选器

    核心功能：
    1. 自动检测筛选模式（首次全量/增量更新）
    2. 统一入口执行因子筛选流程
    3. 配置由外部传入
    """

    # 周期类型
    TERM_SHORT = "short_term"
    TERM_MEDIUM = "medium_term"
    TERM_LONG = "long_term"

    def __init__(self, config, db_url: str = None):
        """
        初始化因子筛选器

        Args:
            config: 配置对象，必须包含以下属性/方法：
                    - DB_URL: 数据库连接URL
                    - CORR_THRESHOLD: 相关性阈值
                    - get(key, default): 获取配置项的方法
                    因子筛选配置通过 config.get("factor_selection", {}) 获取
            db_url: 数据库连接URL，默认从配置读取
        """
        self.config = config
        self.selection_cfg = config.get("factor_selection", {})

        # 初始化数据库
        self.db_url = db_url or config.DB_URL
        init_db(self.db_url)
        self.session = get_session()
        self.engine = self.session.get_bind()

        # 非因子字段
        self.non_factor_cols = self.selection_cfg.get(
            "non_factor_cols",
            ["id", "ts_code", "trade_date", "updated_at", "industry", "close", "log_circ_mv"]
        )

        # 计算参数
        self.min_valid_stocks = self.selection_cfg.get("min_valid_stocks", 20)
        self.eps = self.selection_cfg.get("eps", 1e-6)

        # 数据存储
        self.available_factor_cols: List[str] = []
        self.merged_df: Optional[pd.DataFrame] = None
        self.all_dates: Optional[List[date]] = None
        self._close_wide: Optional[pd.DataFrame] = None

        # IC计算缓存
        self.future_ret_rank: Dict[int, pd.DataFrame] = {}
        self.factor_rank: Dict[str, pd.DataFrame] = {}
        self.daily_ic: Dict[Tuple[str, int], pd.Series] = {}

        # 筛选状态
        self.selection_mode: Dict[str, SelectionMode] = {}
        self.update_required: Dict[str, bool] = {}

        # 输出路径
        output_cfg = self.selection_cfg.get("output", {})
        self.config_dir = PROJECT_ROOT / output_cfg.get("config_dir", "config")
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self.output_files = {
            self.TERM_SHORT: self.config_dir / output_cfg.get("short_term_file", "short_factor.yaml"),
            self.TERM_MEDIUM: self.config_dir / output_cfg.get("medium_term_file", "medium_factor.yaml"),
            self.TERM_LONG: self.config_dir / output_cfg.get("long_term_file", "long_factor.yaml"),
        }

        # 验证数据库结构
        self._validate_database()

    def _validate_database(self):
        """验证数据库结构"""
        try:
            inspector = inspect(self.engine)
            tables = inspector.get_table_names()
            logger.info(f"数据库连接成功，现有表: {tables}")

            if "stock_factor" not in tables:
                raise ValueError("数据库中不存在 stock_factor 表！")

            columns = inspector.get_columns("stock_factor")
            column_names = [col["name"] for col in columns]

            required_base = ["ts_code", "trade_date", "close"]
            missing = [c for c in required_base if c not in column_names]
            if missing:
                raise ValueError(f"stock_factor 表缺少必要字段: {missing}")

            factor_cols = [col for col in column_names if col not in self.non_factor_cols]
            logger.info(f"识别到因子字段数量: {len(factor_cols)}")
            self.available_factor_cols = factor_cols

        except Exception as e:
            logger.error(f"数据库验证失败: {str(e)}")
            raise

    def _get_term_config(self, term: str) -> dict:
        """获取指定周期的配置"""
        return self.selection_cfg.get(term, {})

    def _check_update_required(self) -> Dict[str, bool]:
        """检查各周期因子是否需要更新"""
        logger.info("=== 检查因子文件更新状态 ===")
        now = datetime.now().date()
        update_required = {}

        for term, file_path in self.output_files.items():
            term_cfg = self._get_term_config(term)
            threshold_days = term_cfg.get("update_threshold_days", 30)

            if not file_path.exists():
                logger.info(f"{term}: 配置文件不存在，需要新建")
                update_required[term] = True
                self.selection_mode[term] = SelectionMode.FULL
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    existing_data = yaml.safe_load(f)

                if not existing_data:
                    logger.info(f"{term}: 配置文件为空，需要重新筛选")
                    update_required[term] = True
                    self.selection_mode[term] = SelectionMode.FULL
                    continue

                update_date_str = existing_data.get("update_date")
                if update_date_str:
                    update_date = datetime.strptime(update_date_str, "%Y-%m-%d").date()
                    days_gap = (now - update_date).days

                    if days_gap > threshold_days:
                        logger.info(f"{term}: 距上次更新 {days_gap} 天 > 阈值 {threshold_days} 天，需要更新")
                        update_required[term] = True
                        self.selection_mode[term] = SelectionMode.UPDATE
                    else:
                        logger.info(f"{term}: 距上次更新 {days_gap} 天 <= 阈值 {threshold_days} 天，无需更新")
                        update_required[term] = False
                        self.selection_mode[term] = SelectionMode.SKIP
                else:
                    logger.info(f"{term}: 无法获取更新日期，需要重新筛选")
                    update_required[term] = True
                    self.selection_mode[term] = SelectionMode.FULL

            except Exception as e:
                logger.warning(f"{term}: 读取配置文件失败 ({e})，需要重新筛选")
                update_required[term] = True
                self.selection_mode[term] = SelectionMode.FULL

        self.update_required = update_required
        return update_required

    def load_data(self, lookback_days: int) -> bool:
        """加载指定天数的因子数据"""
        logger.info(f"=== 加载因子数据（回看 {lookback_days} 天）===")

        if not self.available_factor_cols:
            logger.error("无可用因子列，请检查数据库")
            return False

        max_date = self.session.query(func.max(StockFactor.trade_date)).scalar()
        if max_date is None:
            logger.error("数据库中无数据")
            return False

        if isinstance(max_date, datetime):
            max_date = max_date.date()
        elif isinstance(max_date, str):
            max_date = datetime.strptime(max_date, "%Y-%m-%d").date()

        start_date = max_date - timedelta(days=lookback_days)
        logger.info(f"数据时间范围: {start_date} ~ {max_date}")

        select_cols = ["ts_code", "trade_date", "close"] + self.available_factor_cols
        col_objs = [getattr(StockFactor, col) for col in select_cols]
        query = select(*col_objs).where(StockFactor.trade_date >= start_date)

        df_factor = pd.read_sql(query, self.engine)
        logger.info(f"查询到数据行数: {len(df_factor)}")

        if df_factor.empty:
            logger.error("数据库中没有符合条件的因子数据")
            return False

        df_factor["trade_date"] = pd.to_datetime(df_factor["trade_date"]).dt.date
        df_factor = df_factor.drop_duplicates(subset=["ts_code", "trade_date"])

        logger.info(f"时间范围: {df_factor['trade_date'].min()} ~ {df_factor['trade_date'].max()}")
        logger.info(f"股票数量: {df_factor['ts_code'].nunique()}")
        logger.info(f"因子数量: {len(self.available_factor_cols)}")

        self.merged_df = df_factor.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
        self.all_dates = sorted(self.merged_df["trade_date"].unique())
        logger.info(f"数据加载完成，形状: {self.merged_df.shape}, 有效交易日: {len(self.all_dates)}")

        return True

    def remove_collinearity(self) -> List[str]:
        """去除高相关性因子"""
        logger.info("=== 去除共线性 ===")
        exclude = ["ts_code", "trade_date", "close"]
        factor_cols = [c for c in self.merged_df.columns if c not in exclude]
        logger.info(f"待去重因子数量: {len(factor_cols)}")

        corr_df = self.merged_df[factor_cols].fillna(self.merged_df[factor_cols].median())
        corr_matrix = corr_df.corr().abs()

        keep = []
        drop = []
        corr_threshold = self.config.CORR_THRESHOLD

        for col in factor_cols:
            if col in drop:
                continue
            keep.append(col)
            high_corr = corr_matrix.loc[col][corr_matrix.loc[col] > corr_threshold].index.tolist()
            drop.extend([c for c in high_corr if c not in keep and c not in drop])

        keep = list(set(keep))
        logger.info(f"去共线性后保留因子数: {len(keep)} (原始: {len(factor_cols)})")

        base = ["ts_code", "trade_date", "close"]
        self.merged_df = self.merged_df[base + keep]
        return keep

    def _prepare_future_returns(self, windows: List[int]):
        """预计算未来收益率排名"""
        logger.info("预计算未来收益率排名...")

        if self._close_wide is None:
            close_wide = (
                self.merged_df.set_index(["trade_date", "ts_code"])["close"]
                .unstack("ts_code")
                .sort_index()
            )
            self._close_wide = close_wide
            logger.info(f"收盘价宽表形状: {self._close_wide.shape}")
        else:
            close_wide = self._close_wide

        for w in tqdm(windows, desc="计算收益率"):
            ret_wide = np.log(close_wide.shift(-w) / close_wide)
            ret_wide = ret_wide.iloc[:-w] if w < len(ret_wide) else pd.DataFrame()
            if ret_wide.empty:
                logger.warning(f"窗口 {w} 天收益率为空，跳过")
                continue
            self.future_ret_rank[w] = ret_wide.rank(axis=1, pct=True, numeric_only=True)

    def _prepare_factor_ranks(self, factor_list: List[str]):
        """预计算因子排名"""
        logger.info("预计算因子排名...")
        for factor in tqdm(factor_list, desc="因子排名"):
            factor_wide = self.merged_df.pivot(
                index="trade_date", columns="ts_code", values=factor
            ).sort_index()
            factor_wide = factor_wide.ffill(axis=0)
            self.factor_rank[factor] = factor_wide.rank(axis=1, pct=True, numeric_only=True)

    def _compute_daily_ic_series(self, factor: str, windows: List[int]) -> Dict[int, pd.Series]:
        """计算因子IC序列"""
        ic_dict = {}
        factor_rank = self.factor_rank.get(factor)
        if factor_rank is None:
            return ic_dict

        for w in windows:
            ret_rank = self.future_ret_rank.get(w)
            if ret_rank is None:
                continue

            common_dates = factor_rank.index.intersection(ret_rank.index)
            if len(common_dates) == 0:
                continue

            if w > 10:
                step = max(5, w // 5)
            else:
                step = 1
            selected_dates = common_dates[::step]

            f_mat = factor_rank.loc[selected_dates].values
            r_mat = ret_rank.loc[selected_dates].values
            ic_list = []

            for i in range(len(selected_dates)):
                f_vec = f_mat[i]
                r_vec = r_mat[i]
                mask = ~np.isnan(f_vec) & ~np.isnan(r_vec)
                if mask.sum() < self.min_valid_stocks:
                    ic_list.append(np.nan)
                else:
                    corr = np.corrcoef(f_vec[mask], r_vec[mask])[0, 1]
                    ic_list.append(corr if not np.isnan(corr) else np.nan)

            ic_series = pd.Series(ic_list, index=selected_dates, name=f"{factor}_IC_{w}d")
            ic_dict[w] = ic_series

        return ic_dict

    def _precompute_all_ic(self, factor_list: List[str], windows: List[int]):
        """预计算所有IC序列"""
        logger.info("=== 预计算IC序列 ===")
        for factor in tqdm(factor_list, desc="预计算IC"):
            for w in windows:
                key = (factor, w)
                if key not in self.daily_ic:
                    ic_dict = self._compute_daily_ic_series(factor, [w])
                    if w in ic_dict:
                        self.daily_ic[key] = ic_dict[w]

    def _select_factors_for_term(self, factor_list: List[str], term: str) -> List[dict]:
        """筛选指定周期的因子"""
        term_cfg = self._get_term_config(term)
        windows = term_cfg.get("windows", [])
        min_ic_mean = term_cfg.get("min_ic_mean", 0.02)
        min_ir = term_cfg.get("min_ir", 0.3)
        min_hit_rate = term_cfg.get("min_hit_rate", 0.54)
        min_valid_days = term_cfg.get("min_valid_days", 10)

        logger.info(f"筛选 {term} 因子，窗口: {windows}，最小IC: {min_ic_mean}，最小IR: {min_ir}")

        results = []
        for factor in tqdm(factor_list, desc=f"筛选-{term}"):
            factor_passed = False
            stats_for_windows = {}

            for w in windows:
                key = (factor, w)
                ic_series = self.daily_ic.get(key)
                if ic_series is None or len(ic_series.dropna()) < min_valid_days:
                    continue

                ic_window = ic_series.dropna()
                mean_ic = ic_window.mean()
                std_ic = ic_window.std() if ic_window.std() > self.eps else self.eps
                ir = mean_ic / std_ic
                hit_rate = (ic_window > 0).mean()

                if abs(mean_ic) >= min_ic_mean and abs(ir) >= min_ir:
                    if mean_ic > 0 and hit_rate >= min_hit_rate:
                        factor_passed = True
                    elif mean_ic < 0 and hit_rate <= (1 - min_hit_rate):
                        factor_passed = True

                    stats_for_windows[w] = {
                        "ic_mean": float(mean_ic),
                        "ic_std": float(std_ic),
                        "ir": float(ir),
                        "hit_rate": float(hit_rate),
                        "n_days": int(len(ic_window)),
                    }

            if factor_passed:
                results.append({
                    "factor_name": factor,
                    "windows": windows,
                    "window_stats": stats_for_windows,
                })

        logger.info(f"{term} 筛选完成，通过因子数: {len(results)}")
        return results

    def _save_factor_config(self, term: str, factors: List[dict]):
        """保存因子配置文件"""
        file_path = self.output_files[term]
        now = datetime.now()

        output_data = {
            "update_date": now.strftime("%Y-%m-%d"),
            "update_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "term": term,
            "factor_count": len(factors),
            "factors": factors,
        }

        clean_data = numpy_to_python(output_data)
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(clean_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        logger.info(f"{term} 因子配置已保存: {file_path}，因子数: {len(factors)}")

    def _run_selection_for_term(self, term: str):
        """执行指定周期的因子筛选"""
        term_cfg = self._get_term_config(term)
        lookback_days = term_cfg.get("lookback_days", 180)
        windows = term_cfg.get("windows", [])

        if not self.load_data(lookback_days):
            logger.error(f"{term}: 数据加载失败，跳过筛选")
            return

        factor_list = self.remove_collinearity()

        self._prepare_future_returns(windows)
        self._prepare_factor_ranks(factor_list)
        self._precompute_all_ic(factor_list, windows)

        selected_factors = self._select_factors_for_term(factor_list, term)
        self._save_factor_config(term, selected_factors)

        self._clear_cache()

    def _clear_cache(self):
        """清理计算缓存"""
        self.merged_df = None
        self.all_dates = None
        self._close_wide = None
        self.future_ret_rank.clear()
        self.factor_rank.clear()
        self.daily_ic.clear()
        gc.collect()

    def run(self, force: bool = False):
        """
        执行因子筛选的主入口方法

        Args:
            force: 是否强制全量筛选所有周期

        Returns:
            FactorSelector: 返回自身以支持链式调用
        """
        logger.info("=" * 60)
        logger.info("因子筛选器启动")
        logger.info("=" * 60)

        try:
            if force:
                logger.info("强制模式：全量筛选所有周期")
                for term in [self.TERM_SHORT, self.TERM_MEDIUM, self.TERM_LONG]:
                    self.update_required[term] = True
                    self.selection_mode[term] = SelectionMode.FULL
            else:
                self._check_update_required()

            for term in [self.TERM_SHORT, self.TERM_MEDIUM, self.TERM_LONG]:
                mode = self.selection_mode.get(term, SelectionMode.FULL)

                if mode == SelectionMode.SKIP:
                    logger.info(f"{term}: 无需更新，跳过")
                    continue

                logger.info(f"--- 开始筛选 {term} 因子 (模式: {mode.value}) ---")
                self._run_selection_for_term(term)

            logger.info("=" * 60)
            logger.info("因子筛选完成")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"筛选流程出错: {e}", exc_info=True)
            raise
        finally:
            self.session.close()

        return self

    def get_status(self) -> dict:
        """获取筛选器状态信息"""
        return {
            "selection_mode": {k: v.value for k, v in self.selection_mode.items()},
            "update_required": self.update_required,
            "output_files": {k: str(v) for k, v in self.output_files.items()},
            "available_factors": len(self.available_factor_cols),
        }

    def get_selected_factors(self, term: str) -> List[str]:
        """获取已筛选的因子列表"""
        file_path = self.output_files.get(term)
        if not file_path or not file_path.exists():
            return []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return [f["factor_name"] for f in data.get("factors", [])]
        except:
            return []
