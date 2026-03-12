"""
短期选股策略回测测试 V2（修正版）

核心改进：
1. 因子筛选窗口：30天一个周期，使用窗口前180天数据筛选因子
2. 因子筛选标准：在预测窗口[1,3,5]中任一满足条件即保留
3. 选股轮换：每个30天窗口内进行6次选股（每5天一次）
4. 模型训练：使用滚动15天数据
5. 数据加载：按需加载，不一次性加载全部数据

时间结构：
├── 因子筛选期(180天) ──┤ ├── 30天操作窗口 ├──┤
                        │                       │
                   Day -180                Day 1            Day 30
                                          │
                                          ├── 选股1(Day1-5):  训练用Day-15到-1
                                          ├── 选股2(Day6-10): 训练用Day-10到5
                                          ├── 选股3(Day11-15):训练用Day-5到10
                                          ├── 选股4(Day16-20):训练用Day 0到15
                                          ├── 选股5(Day21-25):训练用Day 5到20
                                          └── 选股6(Day26-30):训练用Day 10到25
"""

import gc
import sys
import logging
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

# 获取项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import yaml
from sqlalchemy import select, inspect as sa_inspect
from sklearn.linear_model import RidgeCV
from sklearn.impute import SimpleImputer
from scipy import stats
from tqdm import tqdm

# 模型导入
try:
    from lightgbm import LGBMRegressor
    from xgboost import XGBRegressor
    HAS_TREE_MODELS = True
except ImportError:
    HAS_TREE_MODELS = False
    logging.warning("lightgbm或xgboost未安装，将使用RidgeCV")

# 导入数据库模型
from data.basic_data.database import (
    init_db, get_session, StockDetail, StockFactor, MarketIndex
)

# 导入配置管理器
from core.stock_selection.config_manager import ConfigManager

# Tushare导入
try:
    import tushare as ts
    HAS_TUSHARE = True
except ImportError:
    HAS_TUSHARE = False

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")


class MultiHorizonFactorSelector:
    """
    多预测窗口因子筛选器
    
    在预测窗口[1,3,5]中任一满足条件即保留因子
    """
    
    def __init__(self, config_params: dict):
        """初始化因子筛选器"""
        self.horizons = config_params.get('windows', [1, 3, 5])
        self.min_ic_mean = config_params.get('min_ic_mean', 0.025)
        self.min_ir = config_params.get('min_ir', 0.4)
        self.min_hit_rate = config_params.get('min_hit_rate', 0.52)
        self.min_valid_days = config_params.get('min_valid_days', 30)
        self.corr_threshold = config_params.get('corr_threshold', 0.8)
        self.min_valid_stocks = config_params.get('min_valid_stocks', 20)
        self.eps = config_params.get('eps', 1e-6)
        
        logger.info(f"多窗口因子筛选器初始化完成")
        logger.info(f"  预测窗口: {self.horizons}")
        logger.info(f"  IC均值阈值: {self.min_ic_mean}")
        logger.info(f"  IR阈值: {self.min_ir}")
        logger.info(f"  命中率阈值: {self.min_hit_rate}")
    
    def remove_collinearity(self, factor_df: pd.DataFrame, factor_cols: List[str]) -> List[str]:
        """去除高相关性因子"""
        if len(factor_cols) <= 1:
            return factor_cols
        
        try:
            corr_df = factor_df[factor_cols].fillna(factor_df[factor_cols].median())
            corr_matrix = corr_df.corr().abs()
            
            keep = []
            drop = set()
            
            for col in factor_cols:
                if col in drop:
                    continue
                keep.append(col)
                high_corr = corr_matrix.loc[col][corr_matrix.loc[col] > self.corr_threshold].index.tolist()
                for c in high_corr:
                    if c != col and c not in keep:
                        drop.add(c)
            
            return keep
        except Exception as e:
            logger.warning(f"去共线性失败: {e}")
            return factor_cols
    
    def compute_ic_for_factor_single_horizon(
        self, 
        factor_values: pd.Series, 
        future_returns: pd.Series,
        date_group: pd.Series,
        excess_returns: pd.Series = None
    ) -> dict:
        """计算单个因子在单个预测窗口的IC统计量（使用超额收益）"""
        # 使用超额收益（如果有）否则使用原始收益
        ret_values = excess_returns if excess_returns is not None else future_returns
        
        df = pd.DataFrame({
            'factor': factor_values,
            'return': ret_values,
            'date': date_group
        })
        
        df = df.dropna()
        
        if len(df) < self.min_valid_stocks:
            return {}
        
        daily_ic = []
        for trade_date, group in df.groupby('date'):
            if len(group) < self.min_valid_stocks:
                continue
            
            factor_rank = group['factor'].rank(pct=True)
            return_rank = group['return'].rank(pct=True)
            
            try:
                corr = np.corrcoef(factor_rank, return_rank)[0, 1]
                if not np.isnan(corr):
                    daily_ic.append(corr)
            except Exception:
                continue
        
        if len(daily_ic) < self.min_valid_days:
            return {}
        
        ic_series = np.array(daily_ic)
        ic_mean = np.mean(ic_series)
        ic_std = np.std(ic_series)
        ir = ic_mean / ic_std if ic_std > self.eps else 0
        hit_rate = np.sum(ic_series > 0) / len(ic_series)
        
        return {
            'ic_mean': ic_mean,
            'ic_std': ic_std,
            'ir': ir,
            'hit_rate': hit_rate,
            'n_days': len(daily_ic)
        }
    
    def is_factor_valid(self, ic_stats: dict) -> bool:
        """判断因子是否满足条件"""
        if not ic_stats:
            return False
        
        ic_mean = ic_stats['ic_mean']
        ir = ic_stats['ir']
        hit_rate = ic_stats['hit_rate']
        
        # 正向因子：IC > 0, 命中率 >= 阈值
        if ic_mean > 0:
            return (abs(ic_mean) >= self.min_ic_mean and 
                    abs(ir) >= self.min_ir and 
                    hit_rate >= self.min_hit_rate)
        # 负向因子：IC < 0, 命中率 <= 1-阈值
        else:
            return (abs(ic_mean) >= self.min_ic_mean and 
                    abs(ir) >= self.min_ir and 
                    hit_rate <= (1 - self.min_hit_rate))
    
    def select_factors(
        self, 
        train_data: pd.DataFrame,
        all_factor_cols: List[str],
        hs300_df: pd.DataFrame = None
    ) -> List[str]:
        """
        筛选有效因子（使用超额收益）
        
        在预测窗口[1,3,5]中任一满足条件即保留
        """
        if train_data.empty or not all_factor_cols:
            return []
        
        # 准备数据：按股票和日期排序
        train_data = train_data.copy()
        train_data = train_data.sort_values(['ts_code', 'trade_date'])
        
        # 计算不同预测窗口的未来收益
        for horizon in self.horizons:
            train_data[f'future_return_{horizon}'] = (
                train_data.groupby('ts_code')['close'].shift(-horizon) /
                train_data.groupby('ts_code')['open'].shift(-1) - 1
            )
        
        # 计算沪深300未来收益（用于计算超额收益）
        if hs300_df is not None and not hs300_df.empty:
            hs300_df = hs300_df.copy()
            for horizon in self.horizons:
                hs300_df[f'hs300_return_{horizon}'] = (
                    hs300_df['close'].shift(-horizon) /
                    hs300_df['open'].shift(-1) - 1
                )
                # 映射到个股数据
                date_mapping = hs300_df.set_index('trade_date')[f'hs300_return_{horizon}'].to_dict()
                train_data[f'hs300_return_{horizon}'] = train_data['trade_date'].map(date_mapping)
                # 计算超额收益
                train_data[f'excess_return_{horizon}'] = (
                    train_data[f'future_return_{horizon}'] - train_data[f'hs300_return_{horizon}']
                )
            logger.info("  使用超额收益（个股收益 - 沪深300收益）进行因子筛选")
        else:
            # 无沪深300数据，使用原始收益
            for horizon in self.horizons:
                train_data[f'excess_return_{horizon}'] = train_data[f'future_return_{horizon}']
            logger.warning("  无沪深300数据，使用个股收益进行因子筛选")
        
        valid_data = train_data.dropna(subset=[f'excess_return_{h}' for h in self.horizons])
        
        if len(valid_data) < 100:
            logger.warning(f"训练样本不足: {len(valid_data)}")
            return []
        
        # 去共线性
        logger.info(f"  去共线性前: {len(all_factor_cols)} 个因子")
        selected_cols = self.remove_collinearity(valid_data, all_factor_cols)
        logger.info(f"  去共线性后: {len(selected_cols)} 个因子")
        
        valid_factors = []
        
        for factor_col in selected_cols:
            if factor_col not in valid_data.columns:
                continue
            
            factor_mask = ~valid_data[factor_col].isna()
            factor_data = valid_data[factor_mask]
            
            if len(factor_data) < self.min_valid_stocks:
                continue
            
            # 在不同预测窗口中检查因子有效性
            best_horizon = None
            best_ic_stats = None
            
            for horizon in self.horizons:
                ic_stats = self.compute_ic_for_factor_single_horizon(
                    factor_data[factor_col],
                    factor_data[f'future_return_{horizon}'],
                    factor_data['trade_date'],
                    factor_data[f'excess_return_{horizon}']  # 传入超额收益
                )
                
                if ic_stats and self.is_factor_valid(ic_stats):
                    if best_ic_stats is None or abs(ic_stats['ir']) > abs(best_ic_stats['ir']):
                        best_horizon = horizon
                        best_ic_stats = ic_stats
            
            # 任一预测窗口满足条件即保留
            if best_ic_stats is not None:
                valid_factors.append({
                    'factor': factor_col,
                    'ic_mean': best_ic_stats['ic_mean'],
                    'ir': best_ic_stats['ir'],
                    'hit_rate': best_ic_stats['hit_rate'],
                    'best_horizon': best_horizon,
                    'direction': 1 if best_ic_stats['ic_mean'] > 0 else -1
                })
        
        # 按IR绝对值排序
        valid_factors.sort(key=lambda x: abs(x['ir']), reverse=True)
        
        # 统计正向和负向因子数量
        n_positive = sum(1 for f in valid_factors if f['direction'] == 1)
        n_negative = sum(1 for f in valid_factors if f['direction'] == -1)
        logger.info(f"  筛选后: {len(valid_factors)} 个有效因子 (正向: {n_positive}, 负向: {n_negative})")
        
        # 返回因子信息（包含方向）
        return valid_factors


class ShortTermBacktestV2:
    """
    短期选股策略回测器 V2
    
    结构：
    - 外层循环：30天因子窗口
    - 内层循环：6次选股轮换（每5天一次）
    """
    
    ST_KEYWORDS = ['ST', '*ST', 'S*ST', 'SST', 'S', 'PT']
    
    def __init__(self):
        """初始化回测器"""
        self.config = ConfigManager()
        self._load_factor_config()
        
        self.db_url = self.config.DB_URL
        init_db(self.db_url)
        self.session = get_session()
        self.engine = self.session.get_bind()
        
        # 回测参数
        self.factor_window_size = 30       # 因子窗口大小（30天）
        self.factor_selection_lookback = 180  # 因子筛选回看天数
        self.train_window = 15             # 模型训练窗口
        self.hold_days = 5                 # 持有天数
        self.selection_count = 100         # 选股数量
        
        # 因子筛选器
        self.factor_selector = MultiHorizonFactorSelector(self.factor_selection_params)
        self.imputer = SimpleImputer(strategy='median')
        
        # 结果存储
        self.results = []
        
        # 缓存
        self._all_dates = None
        self._hs300_df = None
        self._all_factor_cols = None
        
        logger.info("=" * 60)
        logger.info("短期选股策略回测器 V2 初始化完成")
        logger.info(f"因子窗口大小: {self.factor_window_size}天")
        logger.info(f"因子筛选回看期: {self.factor_selection_lookback}天")
        logger.info(f"模型训练窗口: {self.train_window}天")
        logger.info(f"持有天数: {self.hold_days}天")
        logger.info(f"选股数量: {self.selection_count}只")
        logger.info("=" * 60)
    
    def _load_factor_config(self):
        """加载因子筛选配置"""
        factor_yaml_path = PROJECT_ROOT / "config" / "factor.yaml"
        
        if not factor_yaml_path.exists():
            logger.warning(f"factor.yaml 不存在，使用默认配置")
            self.factor_selection_params = {
                'windows': [1, 3, 5],
                'min_ic_mean': 0.025,
                'min_ir': 0.4,
                'min_hit_rate': 0.52,
                'min_valid_days': 30,
                'corr_threshold': 0.8,
                'min_valid_stocks': 20,
                'lookback_days': 180
            }
            self._non_factor_cols = []
            return
        
        with open(factor_yaml_path, 'r', encoding='utf-8') as f:
            factor_config = yaml.safe_load(f)
        
        selection_config = factor_config.get('factor_selection', {})
        short_term_config = selection_config.get('short_term', {})
        preprocess_config = factor_config.get('preprocess', {})
        
        self.factor_selection_params = {
            'windows': short_term_config.get('windows', [1, 3, 5]),
            'min_ic_mean': short_term_config.get('min_ic_mean', 0.03),
            'min_ir': short_term_config.get('min_ir', 0.4),
            'min_hit_rate': short_term_config.get('min_hit_rate', 0.55),
            'min_valid_days': short_term_config.get('min_valid_days', 30),
            'corr_threshold': preprocess_config.get('corr_threshold', 0.8),
            'min_valid_stocks': factor_config.get('constants', {}).get('min_valid_stocks', 20),
            'lookback_days': short_term_config.get('lookback_days', 180),
            'eps': factor_config.get('constants', {}).get('eps', 1e-6),
            'non_factor_cols': selection_config.get('non_factor_cols', [])
        }
        
        self._non_factor_cols = self.factor_selection_params.get('non_factor_cols', [])
        logger.info(f"从 factor.yaml 加载因子筛选配置")
    
    def _load_backup_factors(self) -> List[Dict]:
        """
        加载备用因子（从 short_factor.yaml）
        
        Returns:
            因子信息列表，包含 factor_name, direction, ic_mean 等
        """
        backup_factor_path = PROJECT_ROOT / "config" / "short_factor.yaml"
        
        if not backup_factor_path.exists():
            logger.warning(f"备用因子文件不存在: {backup_factor_path}")
            return []
        
        try:
            with open(backup_factor_path, 'r', encoding='utf-8') as f:
                backup_config = yaml.safe_load(f)
            
            factors_list = backup_config.get('factors', [])
            if not factors_list:
                logger.warning("short_factor.yaml 中无因子数据")
                return []
            
            backup_factors = []
            for factor_info in factors_list:
                factor_name = factor_info.get('factor_name')
                if not factor_name:
                    continue
                
                # 获取最佳窗口的统计信息
                window_stats = factor_info.get('window_stats', {})
                best_ic_mean = 0
                best_ir = 0
                
                for window, stats in window_stats.items():
                    ic_mean = stats.get('ic_mean', 0)
                    ir = stats.get('ir', 0)
                    if abs(ir) > abs(best_ir):
                        best_ir = ir
                        best_ic_mean = ic_mean
                
                # 根据 ic_mean 判断方向
                direction = 1 if best_ic_mean > 0 else -1
                
                backup_factors.append({
                    'factor': factor_name,
                    'direction': direction,
                    'ic_mean': best_ic_mean,
                    'ir': best_ir,
                    'source': 'backup'  # 标记为备用因子
                })
            
            logger.info(f"从 short_factor.yaml 加载 {len(backup_factors)} 个备用因子")
            return backup_factors
            
        except Exception as e:
            logger.error(f"加载备用因子失败: {e}")
            return []
    
    def _get_all_factor_columns(self) -> List[str]:
        """获取数据库中所有可用的因子列"""
        if self._all_factor_cols is not None:
            return self._all_factor_cols
        
        try:
            inspector = sa_inspect(self.engine)
            columns = inspector.get_columns("stock_factor")
            column_names = [col["name"] for col in columns]
            
            factor_cols = [col for col in column_names if col not in self._non_factor_cols]
            
            exclude_patterns = ['id', 'updated_at', 'log_', 'pe_safe', 'pb_safe', 'ps_safe']
            factor_cols = [col for col in factor_cols 
                          if not any(pat in col.lower() for pat in exclude_patterns)]
            
            self._all_factor_cols = factor_cols
            logger.info(f"数据库中共有 {len(factor_cols)} 个候选因子")
            
            return self._all_factor_cols
        except Exception as e:
            logger.error(f"获取因子列失败: {e}")
            return []
    
    def _get_all_trade_dates(self) -> List:
        """获取所有交易日列表"""
        if self._all_dates is not None:
            return self._all_dates
        
        logger.info("获取交易日列表...")
        
        query = select(StockFactor.trade_date).distinct().order_by(StockFactor.trade_date)
        result = self.session.execute(query)
        dates = [row[0] for row in result.fetchall()]
        
        self._all_dates = sorted(dates)
        logger.info(f"共有 {len(self._all_dates)} 个交易日")
        
        return self._all_dates
    
    def _load_hs300_data(self) -> pd.DataFrame:
        """加载沪深300数据"""
        if self._hs300_df is not None:
            return self._hs300_df
        
        logger.info("加载沪深300数据...")
        
        all_dates = self._get_all_trade_dates()
        start_date = min(all_dates)
        end_date = max(all_dates)
        
        # 尝试从数据库获取
        try:
            query = select(
                MarketIndex.trade_date,
                MarketIndex.close,
                MarketIndex.open
            ).where(
                MarketIndex.ts_code == '000001.SH',
                MarketIndex.trade_date >= start_date,
                MarketIndex.trade_date <= end_date
            )
            
            hs300_df = pd.read_sql(query, self.engine)
            
            if not hs300_df.empty:
                hs300_df['trade_date'] = pd.to_datetime(hs300_df['trade_date'])
                hs300_df = hs300_df.sort_values('trade_date').reset_index(drop=True)
                logger.info(f"从数据库加载上证指数: {len(hs300_df)} 交易日")
                self._hs300_df = hs300_df
                return hs300_df
        except Exception as e:
            logger.warning(f"从数据库获取指数数据失败: {e}")
        
        # 尝试从Tushare获取
        if HAS_TUSHARE and self.config.TUSHARE_TOKEN:
            try:
                ts.set_token(self.config.TUSHARE_TOKEN)
                pro = ts.pro_api()
                
                start_str = start_date.strftime('%Y%m%d') if hasattr(start_date, 'strftime') else str(start_date).replace('-', '')
                end_str = end_date.strftime('%Y%m%d') if hasattr(end_date, 'strftime') else str(end_date).replace('-', '')
                
                hs300 = pro.index_daily(
                    ts_code='000300.SH',
                    start_date=start_str,
                    end_date=end_str
                )
                
                if not hs300.empty:
                    hs300 = hs300[['trade_date', 'close', 'open']]
                    hs300['trade_date'] = pd.to_datetime(hs300['trade_date'])
                    hs300 = hs300.sort_values('trade_date').reset_index(drop=True)
                    logger.info(f"从Tushare加载沪深300: {len(hs300)} 交易日")
                    self._hs300_df = hs300
                    return hs300
            except Exception as e:
                logger.warning(f"从Tushare获取沪深300失败: {e}")
        
        logger.warning("无法获取沪深300数据，将使用个股收益率作为基准")
        return pd.DataFrame()
    
    def _is_st_stock(self, name: str) -> bool:
        """判断是否为ST股票"""
        if pd.isna(name):
            return False
        name = str(name).upper()
        for keyword in self.ST_KEYWORDS:
            if keyword in name:
                return True
        return False
    
    def _is_valid_market(self, ts_code: str) -> bool:
        """判断是否为有效市场（仅SH和SZ）"""
        if pd.isna(ts_code):
            return False
        return ts_code.endswith('.SH') or ts_code.endswith('.SZ')
    
    def _load_data(self, start_date, end_date, factor_names: List[str] = None) -> pd.DataFrame:
        """加载指定日期范围的数据（按需加载）"""
        if factor_names is None:
            factor_names = self._get_all_factor_columns()
        
        # 日期格式转换
        start_str = start_date.strftime('%Y-%m-%d') if hasattr(start_date, 'strftime') else str(start_date)
        end_str = end_date.strftime('%Y-%m-%d') if hasattr(end_date, 'strftime') else str(end_date)
        
        # 获取因子表结构
        mapper = sa_inspect(StockFactor)
        all_factor_cols = [c.key for c in mapper.attrs]
        
        # 选择需要的列
        select_cols = ['ts_code', 'trade_date'] + [col for col in factor_names if col in all_factor_cols]
        for col in ['log_circ_mv', 'circ_mv', 'close']:
            if col in all_factor_cols and col not in select_cols:
                select_cols.append(col)
        
        # 查询因子数据
        cols_str = ', '.join(select_cols)
        factor_sql = f"SELECT {cols_str} FROM stock_factor WHERE trade_date >= '{start_str}' AND trade_date <= '{end_str}'"
        factor_df = pd.read_sql(factor_sql, self.engine)
        
        if factor_df.empty:
            return pd.DataFrame()
        
        factor_df['trade_date'] = pd.to_datetime(factor_df['trade_date'])
        
        # 查询价格数据
        price_sql = f"SELECT ts_code, trade_date, close, open, pct_chg, vol, pre_close, name FROM stock_detail WHERE trade_date >= '{start_str}' AND trade_date <= '{end_str}'"
        price_df = pd.read_sql(price_sql, self.engine)
        
        if price_df.empty:
            return factor_df
        
        price_df['trade_date'] = pd.to_datetime(price_df['trade_date'])
        
        # 合并数据
        if 'close' in factor_df.columns:
            factor_df = factor_df.drop(columns=['close'])
        
        merged = pd.merge(factor_df, price_df, on=['ts_code', 'trade_date'], how='left')
        
        # 过滤ST股票和非主板市场
        merged = merged[merged['ts_code'].apply(self._is_valid_market)]
        if 'name' in merged.columns:
            merged = merged[~merged['name'].apply(self._is_st_stock)]
        
        # 内存优化：转换为float32
        for col in merged.select_dtypes(include=['float64']).columns:
            merged[col] = merged[col].astype(np.float32)
        
        return merged
    
    def _train_ensemble_model(self, X_train: np.ndarray, y_train: np.ndarray) -> Dict:
        """训练集成模型"""
        models = {}
        
        try:
            ridge = RidgeCV(alphas=[0.1, 1.0, 10.0], cv=5)
            ridge.fit(X_train, y_train)
            models['ridge'] = ridge
        except Exception as e:
            logger.warning(f"RidgeCV训练失败: {e}")
        
        if HAS_TREE_MODELS:
            try:
                lgbm = LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, verbosity=-1, n_jobs=-1)
                lgbm.fit(X_train, y_train)
                models['lgbm'] = lgbm
            except Exception as e:
                logger.warning(f"LGBM训练失败: {e}")
            
            try:
                xgb = XGBRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, verbosity=0, n_jobs=-1)
                xgb.fit(X_train, y_train)
                models['xgb'] = xgb
            except Exception as e:
                logger.warning(f"XGBoost训练失败: {e}")
        
        return models
    
    def _predict(self, models: Dict, X_test: np.ndarray) -> np.ndarray:
        """集成预测"""
        predictions = []
        for name, model in models.items():
            try:
                pred = model.predict(X_test)
                predictions.append(pred)
            except Exception as e:
                logger.warning(f"模型 {name} 预测失败: {e}")
        
        if not predictions:
            return np.zeros(len(X_test))
        
        return np.mean(predictions, axis=0)
    
    def run_backtest(self) -> pd.DataFrame:
        """执行回测"""
        logger.info("=" * 60)
        logger.info("开始执行回测（V2）")
        logger.info("=" * 60)
        
        # 获取交易日列表
        all_dates = self._get_all_trade_dates()
        total_dates = len(all_dates)
        
        if total_dates < self.factor_selection_lookback + self.factor_window_size + self.hold_days:
            logger.error("交易日不足")
            return pd.DataFrame()
        
        # 加载沪深300数据
        hs300_df = self._load_hs300_data()
        
        # 获取因子列表
        all_factor_cols = self._get_all_factor_columns()
        if not all_factor_cols:
            logger.error("无法获取因子列表")
            return pd.DataFrame()
        
        logger.info(f"候选因子总数: {len(all_factor_cols)}")
        
        # 计算因子窗口数量
        # 第一个因子窗口从 day 0 开始，需要前面有180天数据用于因子筛选
        min_start_idx = self.factor_selection_lookback
        
        # 计算有多少个30天窗口
        factor_window_starts = list(range(min_start_idx, total_dates - self.factor_window_size, self.factor_window_size))
        total_factor_windows = len(factor_window_starts)
        
        logger.info(f"总交易日数: {total_dates}")
        logger.info(f"因子窗口数: {total_factor_windows}")
        logger.info("-" * 60)
        
        results = []
        
        # 外层循环：30天因子窗口
        for fw_num, fw_start_idx in enumerate(factor_window_starts, 1):
            fw_end_idx = fw_start_idx + self.factor_window_size - 1
            
            if fw_end_idx >= total_dates:
                break
            
            fw_start_date = all_dates[fw_start_idx]
            fw_end_date = all_dates[fw_end_idx]
            
            logger.info(f"\n{'='*60}")
            logger.info(f"因子窗口 {fw_num}/{total_factor_windows}: {fw_start_date} ~ {fw_end_date}")
            logger.info(f"{'='*60}")
            
            # 1. 加载因子筛选数据（窗口前180天）
            factor_selection_start_idx = fw_start_idx - self.factor_selection_lookback
            factor_selection_start = all_dates[factor_selection_start_idx]
            factor_selection_end = all_dates[fw_start_idx - 1] if fw_start_idx > 0 else fw_start_date
            
            logger.info(f"  加载因子筛选数据: {factor_selection_start} ~ {factor_selection_end}")
            
            factor_selection_data = self._load_data(
                factor_selection_start, 
                factor_selection_end, 
                all_factor_cols
            )
            
            if factor_selection_data.empty:
                logger.warning(f"  因子筛选数据为空，跳过此窗口")
                continue
            
            # 2. 动态筛选因子（传入沪深300数据用于计算超额收益）
            logger.info(f"  开始多窗口因子筛选...")
            selected_factor_infos = self.factor_selector.select_factors(
                factor_selection_data, all_factor_cols, hs300_df
            )
            
            # 如果没有筛选出任何因子，使用备用因子
            if not selected_factor_infos:
                logger.warning(f"  动态因子筛选未选出任何因子，使用备用因子...")
                selected_factor_infos = self._load_backup_factors()
                
                if not selected_factor_infos:
                    logger.error(f"  备用因子也为空，跳过此窗口")
                    del factor_selection_data
                    gc.collect()
                    continue
                else:
                    logger.info(f"  使用 {len(selected_factor_infos)} 个备用因子")
            
            # 提取因子名称和方向映射
            selected_factors = [f['factor'] for f in selected_factor_infos]
            factor_directions = {f['factor']: f['direction'] for f in selected_factor_infos}
            
            n_positive = sum(1 for d in factor_directions.values() if d == 1)
            n_negative = sum(1 for d in factor_directions.values() if d == -1)
            source = selected_factor_infos[0].get('source', 'dynamic') if selected_factor_infos else 'unknown'
            logger.info(f"  筛选出 {len(selected_factors)} 个有效因子 (正向: {n_positive}, 负向: {n_negative}, 来源: {source})")
            
            # 释放因子筛选数据
            del factor_selection_data
            gc.collect()
            
            # 内层循环：6次选股轮换
            for round_num in range(6):
                # 计算选股信号日
                signal_idx = fw_start_idx + round_num * self.hold_days
                if signal_idx >= total_dates:
                    break
                
                signal_date = all_dates[signal_idx]
                buy_idx = signal_idx + 1
                sell_idx = signal_idx + self.hold_days
                
                if buy_idx >= total_dates or sell_idx >= total_dates:
                    break
                
                buy_date = all_dates[buy_idx]
                sell_date = all_dates[sell_idx]
                
                # 计算训练数据范围（滚动15天）
                train_start_idx = signal_idx - self.train_window
                if train_start_idx < 0:
                    train_start_idx = 0
                
                train_start = all_dates[train_start_idx]
                train_end = all_dates[signal_idx - 1] if signal_idx > 0 else signal_date
                
                logger.info(f"\n  选股轮次 {round_num + 1}/6:")
                logger.info(f"    信号日: {signal_date}")
                logger.info(f"    买入日: {buy_date}")
                logger.info(f"    卖出日: {sell_date}")
                logger.info(f"    训练数据: {train_start} ~ {train_end}")
                
                # 3. 加载训练数据
                train_data = self._load_data(train_start, sell_date, selected_factors)
                
                if train_data.empty:
                    logger.warning(f"    训练数据为空，跳过")
                    continue
                
                # 准备训练样本（使用超额收益作为标签）
                train_data = train_data.copy()
                train_data = train_data.sort_values(['ts_code', 'trade_date'])
                
                # 计算个股未来收益
                train_data['future_return'] = (
                    train_data.groupby('ts_code')['close'].shift(-self.hold_days) /
                    train_data.groupby('ts_code')['open'].shift(-1) - 1
                )
                
                # 计算沪深300未来收益（用于计算超额收益标签）
                if not hs300_df.empty:
                    hs300_for_label = hs300_df.copy()
                    hs300_for_label['hs300_future_return'] = (
                        hs300_for_label['close'].shift(-self.hold_days) /
                        hs300_for_label['open'].shift(-1) - 1
                    )
                    date_mapping = hs300_for_label.set_index('trade_date')['hs300_future_return'].to_dict()
                    train_data['hs300_future_return'] = train_data['trade_date'].map(date_mapping)
                    # 计算超额收益标签
                    train_data['label'] = train_data['future_return'] - train_data['hs300_future_return']
                    logger.info(f"    使用超额收益（个股收益 - 沪深300收益）作为训练标签")
                else:
                    train_data['label'] = train_data['future_return']
                    logger.warning(f"    无沪深300数据，使用个股收益作为训练标签")
                
                # 只使用信号日之前的数据训练
                signal_date_ts = pd.Timestamp(signal_date)
                train_mask = train_data['trade_date'] < signal_date_ts
                train_samples = train_data[train_mask].dropna(subset=['future_return'])
                
                if len(train_samples) < 100:
                    logger.warning(f"    训练样本不足 ({len(train_samples)})，跳过")
                    del train_data
                    gc.collect()
                    continue
                
                # 4. 准备特征列
                feature_cols = [col for col in selected_factors if col in train_samples.columns]
                if 'log_circ_mv' in train_samples.columns:
                    feature_cols.append('log_circ_mv')
                
                if not feature_cols:
                    logger.warning(f"    无有效特征列，跳过")
                    del train_data
                    gc.collect()
                    continue
                
                # 5. 处理负向因子：翻转负向因子的值
                train_features = train_samples[feature_cols].copy()
                for col in feature_cols:
                    if col in factor_directions and factor_directions[col] == -1:
                        train_features[col] = -train_features[col]
                
                X_train = self.imputer.fit_transform(train_features.values)
                y_train = train_samples['label'].values  # 使用超额收益标签
                
                models = self._train_ensemble_model(X_train, y_train)
                
                if not models:
                    logger.warning(f"    模型训练失败，跳过")
                    del train_data
                    gc.collect()
                    continue
                
                # 6. 选股预测
                test_data = train_data[train_data['trade_date'] == signal_date_ts].copy()
                
                if test_data.empty:
                    logger.warning(f"    信号日无数据，跳过")
                    del train_data
                    gc.collect()
                    continue
                
                # 处理负向因子：翻转负向因子的值（与训练数据一致）
                test_features = test_data[feature_cols].copy()
                for col in feature_cols:
                    if col in factor_directions and factor_directions[col] == -1:
                        test_features[col] = -test_features[col]
                
                X_test = self.imputer.transform(test_features.values)
                predictions = self._predict(models, X_test)
                
                # 按预测得分排序
                pred_df = pd.DataFrame({
                    'ts_code': test_data['ts_code'].values,
                    'pred_score': predictions
                })
                pred_df = pred_df.sort_values('pred_score', ascending=False)
                
                # 获取分组股票
                selected_100 = pred_df.head(self.selection_count)['ts_code'].tolist()
                top20 = pred_df.head(20)['ts_code'].tolist()
                bottom20 = pred_df.iloc[80:100]['ts_code'].tolist()
                
                # 6. 计算收益
                buy_date_ts = pd.Timestamp(buy_date)
                sell_date_ts = pd.Timestamp(sell_date)
                
                def calc_group_return(stock_list):
                    returns = []
                    for code in stock_list:
                        buy_data = train_data[(train_data['ts_code'] == code) & (train_data['trade_date'] == buy_date_ts)]
                        sell_data = train_data[(train_data['ts_code'] == code) & (train_data['trade_date'] == sell_date_ts)]
                        
                        if buy_data.empty or sell_data.empty:
                            continue
                        
                        buy_price = buy_data['open'].iloc[0]
                        sell_price = sell_data['close'].iloc[0]
                        
                        if pd.isna(buy_price) or pd.isna(sell_price) or buy_price <= 0:
                            continue
                        
                        ret = (sell_price / buy_price) - 1
                        returns.append(ret)
                    
                    return np.mean(returns) if returns else np.nan
                
                top20_return = calc_group_return(top20)
                bottom20_return = calc_group_return(bottom20)
                selected_100_return = calc_group_return(selected_100)
                
                # 计算沪深300收益
                if not hs300_df.empty:
                    hs300_buy = hs300_df[hs300_df['trade_date'] == buy_date_ts]
                    hs300_sell = hs300_df[hs300_df['trade_date'] == sell_date_ts]
                    
                    if not hs300_buy.empty and not hs300_sell.empty:
                        hs300_return = (hs300_sell['close'].iloc[0] / hs300_buy['open'].iloc[0] - 1)
                    else:
                        hs300_return = np.nan
                else:
                    hs300_return = np.nan
                
                # 记录结果
                result = {
                    'factor_window': fw_num,
                    'selection_round': round_num + 1,
                    'signal_date': signal_date,
                    'buy_date': buy_date,
                    'sell_date': sell_date,
                    'n_factors': len(selected_factors),
                    'top20_return': top20_return,
                    'bottom20_return': bottom20_return,
                    'selected_100_return': selected_100_return,
                    'hs300_return': hs300_return,
                    'top20_excess': top20_return - hs300_return if not np.isnan(top20_return) and not np.isnan(hs300_return) else np.nan,
                    'bottom20_excess': bottom20_return - hs300_return if not np.isnan(bottom20_return) and not np.isnan(hs300_return) else np.nan,
                }
                results.append(result)
                
                logger.info(f"    Top20收益: {top20_return*100:.2f}% | 80-100名收益: {bottom20_return*100:.2f}% | 沪深300: {hs300_return*100:.2f}%")
                
                # 释放内存
                del train_data, test_data, pred_df
                gc.collect()
        
        results_df = pd.DataFrame(results)
        
        logger.info("\n" + "-" * 60)
        logger.info(f"回测完成，共 {len(results_df)} 次选股")
        
        self.results = results_df
        return results_df
    
    def statistical_test(self) -> Dict:
        """执行统计检验"""
        if self.results.empty:
            logger.error("请先执行回测")
            return {}
        
        results_df = self.results.dropna(subset=['top20_return', 'bottom20_return'])
        
        if len(results_df) < 10:
            logger.error("有效样本不足")
            return {}
        
        top20_returns = results_df['top20_return'].values
        bottom20_returns = results_df['bottom20_return'].values
        
        # 配对t检验
        t_stat, t_pvalue = stats.ttest_rel(top20_returns, bottom20_returns)
        
        # Wilcoxon检验
        try:
            w_stat, w_pvalue = stats.wilcoxon(top20_returns, bottom20_returns)
        except Exception:
            w_stat, w_pvalue = np.nan, np.nan
        
        # Cohen's d
        diff = top20_returns - bottom20_returns
        cohens_d = np.mean(diff) / np.std(diff, ddof=1) if np.std(diff) > 0 else 0
        
        stats_result = {
            'sample_size': len(results_df),
            'avg_factor_count': results_df['n_factors'].mean(),
            'top20': {
                'mean': np.mean(top20_returns),
                'std': np.std(top20_returns),
                'median': np.median(top20_returns),
                'min': np.min(top20_returns),
                'max': np.max(top20_returns),
                'win_rate': np.sum(top20_returns > 0) / len(top20_returns),
            },
            'bottom20': {
                'mean': np.mean(bottom20_returns),
                'std': np.std(bottom20_returns),
                'median': np.median(bottom20_returns),
                'min': np.min(bottom20_returns),
                'max': np.max(bottom20_returns),
                'win_rate': np.sum(bottom20_returns > 0) / len(bottom20_returns),
            },
            'paired_t_test': {
                't_statistic': t_stat,
                'p_value': t_pvalue,
                'significant_005': t_pvalue < 0.05,
            },
            'wilcoxon_test': {
                'statistic': w_stat,
                'p_value': w_pvalue,
                'significant_005': w_pvalue < 0.05 if not np.isnan(w_pvalue) else False,
            },
            'effect_size': {
                'cohens_d': cohens_d,
                'mean_diff': np.mean(diff),
            }
        }
        
        return stats_result
    
    def generate_report(self) -> str:
        """生成回测报告"""
        if self.results.empty:
            return "请先执行回测"
        
        results_df = self.results.dropna()
        stats_result = self.statistical_test()
        
        if not stats_result:
            return "统计数据不足"
        
        report = []
        report.append("=" * 70)
        report.append("短期选股策略回测报告 V2")
        report.append("=" * 70)
        report.append("")
        
        report.append("【一、回测概况】")
        report.append(f"  总选股次数: {stats_result['sample_size']}")
        report.append(f"  因子窗口大小: {self.factor_window_size} 交易日")
        report.append(f"  因子筛选回看期: {self.factor_selection_lookback} 交易日")
        report.append(f"  模型训练窗口: {self.train_window} 交易日")
        report.append(f"  持有天数: {self.hold_days} 天")
        report.append(f"  选股数量: {self.selection_count} 只")
        report.append(f"  平均筛选因子数: {stats_result['avg_factor_count']:.1f}")
        report.append("")
        report.append("  因子筛选标准（在[1,3,5]预测窗口任一满足）:")
        report.append(f"    - IC均值阈值: {self.factor_selection_params['min_ic_mean']}")
        report.append(f"    - IR阈值: {self.factor_selection_params['min_ir']}")
        report.append(f"    - 命中率阈值: {self.factor_selection_params['min_hit_rate']}")
        report.append("")
        
        report.append("【二、整体收益对比】")
        
        # 计算累计收益
        results_df = results_df.copy()
        results_df['top20_cum_return'] = (1 + results_df['top20_return']).cumprod() - 1
        results_df['hs300_cum_return'] = (1 + results_df['hs300_return']).cumprod() - 1
        
        top20_cum = results_df['top20_cum_return'].iloc[-1]
        hs300_cum = results_df['hs300_cum_return'].iloc[-1]
        excess_cum = top20_cum - hs300_cum
        
        report.append(f"  选股策略（Top20）累计收益: {top20_cum*100:.2f}%")
        report.append(f"  沪深300累计收益: {hs300_cum*100:.2f}%")
        report.append(f"  累计超额收益: {excess_cum*100:.2f}%")
        
        avg_top20 = results_df['top20_return'].mean()
        avg_hs300 = results_df['hs300_return'].mean()
        avg_excess = results_df['top20_excess'].mean()
        
        report.append(f"  平均每期收益（Top20）: {avg_top20*100:.4f}%")
        report.append(f"  平均每期沪深300收益: {avg_hs300*100:.4f}%")
        report.append(f"  平均每期超额收益: {avg_excess*100:.4f}%")
        
        win_rate = (results_df['top20_return'] > results_df['hs300_return']).mean()
        report.append(f"  跑赢沪深300的比例（胜率）: {win_rate*100:.2f}%")
        report.append("")
        
        report.append("【三、Top20 vs 80-100名 收益对比】")
        
        top20_stats = stats_result['top20']
        bottom20_stats = stats_result['bottom20']
        
        report.append(f"  Top20 平均收益: {top20_stats['mean']*100:.4f}% (标准差: {top20_stats['std']*100:.4f}%)")
        report.append(f"  80-100名 平均收益: {bottom20_stats['mean']*100:.4f}% (标准差: {bottom20_stats['std']*100:.4f}%)")
        report.append(f"  Top20 盈利比例: {top20_stats['win_rate']*100:.2f}%")
        report.append(f"  80-100名 盈利比例: {bottom20_stats['win_rate']*100:.2f}%")
        report.append(f"  收益差异（Top20 - 80-100名）: {(top20_stats['mean']-bottom20_stats['mean'])*100:.4f}%")
        report.append("")
        
        report.append("【四、假设检验结果】")
        report.append("")
        report.append("  检验目标: Top20与80-100名股票的收益率是否存在显著差异")
        report.append("  原假设 (H0): 两组收益率无显著差异")
        report.append("  备择假设 (H1): 两组收益率存在显著差异")
        report.append("  显著性水平: α = 0.05")
        report.append("")
        
        t_test = stats_result['paired_t_test']
        report.append("  1. 配对t检验:")
        report.append(f"     t统计量: {t_test['t_statistic']:.4f}")
        report.append(f"     p值: {t_test['p_value']:.6f}")
        if t_test['significant_005']:
            report.append(f"     结论: 拒绝原假设，两组收益率存在显著差异 ✓")
        else:
            report.append(f"     结论: 不能拒绝原假设，两组收益率无显著差异")
        report.append("")
        
        w_test = stats_result['wilcoxon_test']
        report.append("  2. Wilcoxon符号秩检验（非参数）:")
        if not np.isnan(w_test['statistic']):
            report.append(f"     统计量: {w_test['statistic']:.4f}")
            report.append(f"     p值: {w_test['p_value']:.6f}")
            if w_test['significant_005']:
                report.append(f"     结论: 拒绝原假设，两组收益率存在显著差异 ✓")
            else:
                report.append(f"     结论: 不能拒绝原假设，两组收益率无显著差异")
        else:
            report.append("     无法计算")
        report.append("")
        
        effect = stats_result['effect_size']
        report.append("【五、效应量分析】")
        report.append(f"  Cohen's d: {effect['cohens_d']:.4f}")
        
        if abs(effect['cohens_d']) < 0.2:
            effect_level = "微小效应"
        elif abs(effect['cohens_d']) < 0.5:
            effect_level = "小效应"
        elif abs(effect['cohens_d']) < 0.8:
            effect_level = "中等效应"
        else:
            effect_level = "大效应"
        
        report.append(f"  效应水平: {effect_level}")
        report.append(f"  平均收益差异: {effect['mean_diff']*100:.4f}%")
        report.append("")
        
        report.append("【六、综合结论】")
        report.append("")
        
        if t_test['significant_005'] and top20_stats['mean'] > bottom20_stats['mean']:
            report.append("  ✓ 选股策略有效：Top20股票收益率显著高于80-100名股票")
            report.append(f"    平均超额收益: {(top20_stats['mean']-bottom20_stats['mean'])*100:.4f}%")
        elif t_test['significant_005'] and top20_stats['mean'] < bottom20_stats['mean']:
            report.append("  ✗ 选股策略反向：Top20股票收益率显著低于80-100名股票")
        else:
            report.append("  - 选股效果不明显：Top20与80-100名股票收益率无显著差异")
        
        report.append("")
        report.append("=" * 70)
        
        return "\n".join(report)
    
    def close(self):
        """关闭数据库连接"""
        if self.session:
            self.session.close()


def main():
    """主函数"""
    print("\n" + "=" * 70)
    print("短期选股策略回测测试 V2")
    print("=" * 70 + "\n")
    
    backtest = ShortTermBacktestV2()
    
    try:
        results_df = backtest.run_backtest()
        
        if results_df.empty:
            print("回测失败，无有效结果")
            return
        
        report = backtest.generate_report()
        print("\n" + report)
        
        # 保存结果
        output_dir = PROJECT_ROOT / "test_report"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        results_file = output_dir / f"backtest_v2_results_{timestamp}.csv"
        results_df.to_csv(results_file, index=False, encoding='utf-8-sig')
        print(f"\n详细结果已保存到: {results_file}")
        
        report_file = output_dir / f"backtest_v2_report_{timestamp}.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"报告已保存到: {report_file}")
        
    except Exception as e:
        logger.error(f"回测执行出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        backtest.close()
    
    print("\n回测完成！")


if __name__ == "__main__":
    main()
