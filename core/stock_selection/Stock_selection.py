"""
股票筛选器
功能说明：
1. 读取YAML配置文件，提取不同周期的有效因子
2. 从数据库读取训练数据进行模型训练
3. 短期使用集成模型（RidgeCV + LGBM + XGBoost）
4. 中期/长期使用RidgeCV
5. 筛选股票存入stockpool表
6. 大白马股票筛选：基于股息率、市值、ROE、财务稳健等多维度综合评分

大白马筛选标准：
- 股息率：dv_ttm >= 2%（稳定分红）
- 市值：总市值 >= 500亿（大盘蓝筹）
- 盈利能力：ROE >= 10%
- 财务稳健：资产负债率 <= 70%
- 估值合理：PE在合理区间
- 行业龙头：行业内市值排名靠前加分

使用示例：
    selector = StockSelector(config=my_config)
    selector.select_short_term()      # 短期选股
    selector.select_medium_term()     # 中期选股
    selector.select_long_term()       # 长期选股
    selector.select_white_horse(10)   # 大白马选股，选出10只
"""

import gc
import sys
import logging
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, date

# 获取项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import yaml
from sqlalchemy import select, func, delete
from sqlalchemy import inspect as sa_inspect
from sklearn.linear_model import RidgeCV
from sklearn.impute import SimpleImputer

# 模型导入
try:
    from lightgbm import LGBMRegressor
    from xgboost import XGBRegressor
    HAS_TREE_MODELS = True
except ImportError:
    HAS_TREE_MODELS = False
    logging.warning("lightgbm或xgboost未安装，短期选股将使用RidgeCV")

# Tushare导入
try:
    import tushare as ts
    HAS_TUSHARE = True
except ImportError:
    HAS_TUSHARE = False
    logging.warning("tushare未安装，无法获取沪深300数据")

# 导入数据库模型
try:
    from data.basic_data.database import (
        init_db, get_session, StockDetail, StockFactor, StockPool
    )
except ImportError as e:
    print(f"请确保 database.py 在项目路径中。错误: {e}")
    sys.exit(1)

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")


class StockSelector:
    """
    股票筛选器
    
    核心功能：
    1. 短期选股：集成模型，训练窗口短
    2. 中期选股：RidgeCV，训练窗口中等
    3. 长期选股：RidgeCV，训练窗口长
    4. 大白马选股：多维度综合评分，筛选高股息大市值蓝筹股
    
    大白马筛选维度（满分100+5）：
    - 股息率得分（25分）：高分红是白马核心特征
    - 市值得分（15分）：行业龙头大市值
    - 盈利能力得分（25分）：ROE和质量得分
    - 财务稳健得分（15分）：资产负债率
    - 估值吸引力得分（10分）：PE/PB合理性
    - 成长性得分（10分）：营收利润增长
    - 行业龙头加分（额外5分）：行业内市值排名前三
    
    注意：大白马筛选条件从 config_manager 读取，避免硬编码冗余
    """
    
    # 周期类型常量
    TERM_SHORT = "short_term"
    TERM_MEDIUM = "medium_term"
    TERM_LONG = "long_term"
    TERM_WHITE_HORSE = "white_horse"
    
    # pool_type映射
    POOL_TYPE_MAP = {
        "short_term": "SHORT",
        "medium_term": "MID",
        "long_term": "LONG",
        "white_horse": "WHITE_HORSE",
    }
    
    # ST股票关键词（风险警示股票）
    ST_KEYWORDS = ['ST', '*ST', 'S*ST', 'SST', 'S', 'PT']
    
    def __init__(self, config, db_url: str = None):
        """
        初始化股票筛选器
        
        Args:
            config: ConfigManager配置对象（包含tushare_token和大白马筛选配置）
            db_url: 数据库连接URL，默认从配置读取
        """
        self.config = config
        self.selection_cfg = config.get("stock_selection", {})
        
        # 从config获取tushare_token
        self.tushare_token = config.TUSHARE_TOKEN
        
        # 从config获取大白马筛选配置（避免硬编码冗余）
        self.white_horse_criteria = config.get_white_horse_criteria()
        self.white_horse_weights = config.WHITE_HORSE_SCORING_WEIGHTS
        
        # 初始化数据库
        self.db_url = db_url or config.DB_URL
        init_db(self.db_url)
        self.session = get_session()
        self.engine = self.session.get_bind()
        
        # 模型配置
        self.imputer = SimpleImputer(strategy='median')
        
        logger.info("股票筛选器初始化完成")
    
    def _get_term_params(self, term: str) -> Dict:
        """获取指定周期的参数"""
        return self.config.get_stock_selection_config(term)
    def _parse_config_float(self, value, default=0.0):
        """
        将配置值安全转换为浮点数，支持字符串中的逗号、空格等。
        """
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # 去除逗号和空格
            cleaned = value.replace(',', '').replace(' ', '')
            try:
                return float(cleaned)
            except ValueError:
                logger.warning(f"无法将字符串 '{value}' 转换为浮点数，使用默认值 {default}")
                return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
        
    def _is_st_stock(self, name: str) -> bool:
        """
        判断是否为ST股票
        
        Args:
            name: 股票名称
        
        Returns:
            是否为ST股票
        """
        if pd.isna(name):
            return False
        name = str(name).upper()
        # 检查是否包含ST关键词
        for keyword in self.ST_KEYWORDS:
            if keyword in name:
                return True
        return False
    
    def _is_valid_market(self, ts_code: str) -> bool:
        """
        判断是否为有效市场（仅SH和SZ，排除北交所BJ）
        
        Args:
            ts_code: 股票代码
        
        Returns:
            是否为有效市场
        """
        if pd.isna(ts_code):
            return False
        return ts_code.endswith('.SH') or ts_code.endswith('.SZ')
    
    def _filter_invalid_stocks(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        过滤无效股票（ST股票、北交所股票）
        
        Args:
            df: 包含ts_code和name列的DataFrame
        
        Returns:
            过滤后的DataFrame
        """
        initial_len = len(df)
        
        # 过滤北交所股票（BJ结尾）
        if 'ts_code' in df.columns:
            df = df[df['ts_code'].apply(self._is_valid_market)]
        
        # 过滤ST股票
        if 'name' in df.columns:
            df = df[~df['name'].apply(self._is_st_stock)]
        
        filtered_count = initial_len - len(df)
        if filtered_count > 0:
            logger.info(f"过滤无效股票: ST股票和北交所股票共 {filtered_count} 只")
        
        return df
    
    def _load_factor_yaml(self, term: str) -> List[str]:
        """加载因子配置文件，返回因子列表"""
        yaml_path = self.config.get_factor_yaml_path(term)
        
        if not yaml_path.exists():
            logger.warning(f"因子配置文件不存在: {yaml_path}")
            return []
        
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        if not data:
            logger.warning(f"因子配置文件为空: {yaml_path}")
            return []
        
        # 提取因子名称列表
        factors = data.get("factors", [])
        factor_names = [f.get("factor_name") for f in factors if f.get("factor_name")]
        
        logger.info(f"从 {yaml_path.name} 加载 {len(factor_names)} 个因子")
        return factor_names
    
    def _load_factor_data(self, lookback_days: int) -> pd.DataFrame:
        """从数据库加载因子数据"""
        logger.info(f"加载因子数据，回看天数: {lookback_days}")
        
        # 获取最新日期
        max_date = self.session.query(func.max(StockFactor.trade_date)).scalar()
        if max_date is None:
            logger.error("因子数据库为空")
            return pd.DataFrame()
        
        if isinstance(max_date, datetime):
            max_date = max_date.date()
        elif isinstance(max_date, str):
            max_date = datetime.strptime(max_date, "%Y-%m-%d").date()
        
        start_date = max_date - timedelta(days=lookback_days * 1.5)
        
        # 动态获取所有列
        mapper = sa_inspect(StockFactor)
        all_columns = [c.key for c in mapper.attrs]
        select_cols = [getattr(StockFactor, col) for col in all_columns if col not in ['id', 'updated_at']]
        
        query = select(*select_cols).where(
            StockFactor.trade_date >= start_date.strftime('%Y%m%d')
        )
        
        chunks = []
        chunk_size = self.config.CHUNK_SIZE
        for chunk in pd.read_sql(query, self.engine, chunksize=chunk_size):
            for col in chunk.select_dtypes(include=['float64']).columns:
                chunk[col] = chunk[col].astype(np.float32)
            chunks.append(chunk)
        
        df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
        
        if not df.empty:
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            df = df.sort_values(['trade_date', 'ts_code']).reset_index(drop=True)
        
        logger.info(f"因子数据加载完成: {len(df)} 行, {df['trade_date'].nunique()} 交易日")
        return df
    
    def _load_price_data(self, lookback_days: int) -> pd.DataFrame:
        """从数据库加载行情数据"""
        logger.info(f"加载行情数据，回看天数: {lookback_days}")
        
        max_date = self.session.query(func.max(StockDetail.trade_date)).scalar()
        if max_date is None:
            logger.error("行情数据库为空")
            return pd.DataFrame()
        
        if isinstance(max_date, datetime):
            max_date = max_date.date()
        elif isinstance(max_date, str):
            max_date = datetime.strptime(max_date, "%Y%m%d").date()
        
        start_date = max_date - timedelta(days=lookback_days * 1.5)
        
        query = select(
            StockDetail.ts_code,
            StockDetail.trade_date,
            StockDetail.close,
            StockDetail.open,
            StockDetail.pct_chg,
            StockDetail.vol,
            StockDetail.pre_close,
            StockDetail.name,
        ).where(
            StockDetail.trade_date >= start_date.strftime('%Y%m%d')
        )
        
        chunks = []
        chunk_size = self.config.CHUNK_SIZE
        for chunk in pd.read_sql(query, self.engine, chunksize=chunk_size):
            for col in chunk.select_dtypes(include=['float64']).columns:
                chunk[col] = chunk[col].astype(np.float32)
            chunks.append(chunk)
        
        df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
        
        if not df.empty:
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            df = df.sort_values(['trade_date', 'ts_code']).reset_index(drop=True)
        
        logger.info(f"行情数据加载完成: {len(df)} 行")
        return df
    
    def _load_hs300_data(self, start_date: date, end_date: date) -> pd.DataFrame:
        """
        加载沪深300数据（修复版：增加开盘价字段）
        
        用于计算超额收益标签：
        - T日信号产生后
        - T+1开盘买入（使用T+1的开盘价）
        - T+horizon收盘卖出（使用T+horizon的收盘价）
        """
        logger.info("加载沪深300数据...")
        
        if HAS_TUSHARE and self.tushare_token:
            try:
                ts.set_token(self.tushare_token)
                pro = ts.pro_api()
                
                hs300 = pro.index_daily(
                    ts_code='000300.SH',
                    start_date=start_date.strftime('%Y%m%d'),
                    end_date=end_date.strftime('%Y%m%d')
                )
                
                if not hs300.empty:
                    # 修复：增加open字段，用于计算T+1开盘买入的收益
                    hs300 = hs300[['trade_date', 'close', 'open']]
                    hs300['trade_date'] = pd.to_datetime(hs300['trade_date'])
                    hs300 = hs300.sort_values('trade_date').reset_index(drop=True)
                    logger.info(f"从Tushare加载沪深300数据: {len(hs300)} 交易日（含开盘价）")
                    return hs300
            except Exception as e:
                logger.warning(f"从Tushare获取沪深300失败: {e}")
        
        logger.warning("无法获取沪深300数据，将使用个股收益率作为标签（不计算超额收益）")
        return pd.DataFrame()
   
    def _merge_data(self, factor_df: pd.DataFrame, price_df: pd.DataFrame) -> pd.DataFrame:
        """合并因子和行情数据"""
        if price_df.empty:
            return factor_df
        
        price_cols = ['ts_code', 'trade_date', 'close', 'open', 'vol', 'pre_close', 'name']
        merged = pd.merge(
            factor_df,
            price_df[price_cols],
            on=['ts_code', 'trade_date'],
            how='left',
            suffixes=('', '_price')
        )
        
        # 使用行情表的close和open
        if 'close_price' in merged.columns:
            merged['close'] = merged['close_price'].fillna(merged['close'])
            merged.drop(columns=['close_price'], inplace=True)
        
        return merged
    
    def _calculate_labels(self, df: pd.DataFrame, hs300_df: pd.DataFrame, 
                        horizon: int) -> pd.DataFrame:
        """
        计算超额收益标签（修复版：T+1开盘买入，T+horizon收盘卖出）
        
        交易逻辑：
        - T日：收盘后产生选股信号
        - T+1日：开盘时买入（使用T+1的开盘价）
        - T+horizon日：收盘时卖出（使用T+horizon的收盘价）
        """
        logger.info(f"计算未来{horizon}天超额收益标签...")
        
        df = df.copy().sort_values(['ts_code', 'trade_date'])
        
        if 'close' not in df.columns or 'open' not in df.columns:
            raise ValueError("数据缺少close或open列")
        
        # 个股未来收益（T+1开盘买入，T+horizon收盘卖出）
        # 正确逻辑：T日信号 → shift(-1)获取T+1的open作为买入价 → shift(-horizon)获取T+horizon的close作为卖出价
        df[f'future_{horizon}d_return'] = (
            df.groupby('ts_code')['close'].shift(-horizon) /
            df.groupby('ts_code')['open'].shift(-1) - 1
        )
        
        # 沪深300未来收益（修复：使用开盘价作为买入价）
        if not hs300_df.empty:
            hs300_df = hs300_df.copy()
            
            if 'open' in hs300_df.columns:
                # 修复后的正确计算方式：T+1开盘买入，T+horizon收盘卖出
                # 与个股计算逻辑保持一致
                hs300_df[f'future_{horizon}d_return'] = (
                    hs300_df['close'].shift(-horizon) / hs300_df['open'].shift(-1) - 1
                )
                logger.info("沪深300收益计算：使用T+1开盘价买入，T+horizon收盘价卖出")
            else:
                # 兼容旧数据：如果没有开盘价，使用收盘价近似（会有偏差）
                logger.warning("沪深300缺少开盘价数据，使用收盘价近似（可能引入偏差）")
                hs300_df[f'future_{horizon}d_return'] = (
                    hs300_df['close'].shift(-horizon) / hs300_df['close'].shift(-1) - 1
                )
            
            date_mapping = hs300_df.set_index('trade_date')[f'future_{horizon}d_return'].to_dict()
            df[f'hs300_future_{horizon}d_return'] = df['trade_date'].map(date_mapping)
            df['label'] = df[f'future_{horizon}d_return'] - df[f'hs300_future_{horizon}d_return']
            df.drop(columns=[f'future_{horizon}d_return', f'hs300_future_{horizon}d_return'], 
                inplace=True, errors='ignore')
            logger.info("使用个股收益减去沪深300收益作为标签（超额收益）")
        else:
            df['label'] = df[f'future_{horizon}d_return']
            df.drop(columns=[f'future_{horizon}d_return'], inplace=True, errors='ignore')
            logger.info("无沪深300数据，使用个股收益率作为标签")
        
        initial_len = len(df)
        df = df.dropna(subset=['label'])
        logger.info(f"删除缺失标签数据: {initial_len - len(df)} 行")
        
        return df
    
    def _prepare_features(self, df: pd.DataFrame, factor_names: List[str]) -> Tuple[np.ndarray, List[str]]:
        """准备特征矩阵"""
        feature_cols = [col for col in factor_names if col in df.columns]
        missing = set(factor_names) - set(feature_cols)
        if missing:
            logger.warning(f"以下因子在数据中不存在: {missing}")
        
        if 'log_circ_mv' in df.columns and 'log_circ_mv' not in feature_cols:
            feature_cols.append('log_circ_mv')
        
        logger.info(f"使用特征数量: {len(feature_cols)}")
        return df[feature_cols].values, feature_cols
    
    def _train_ensemble_model(self, X_train: np.ndarray, y_train: np.ndarray) -> Dict:
        """训练集成模型（短期使用）"""
        models = {}
        
        try:
            ridge = RidgeCV(alphas=[0.1, 1.0, 10.0], cv=5)
            ridge.fit(X_train, y_train)
            models['ridge'] = ridge
        except Exception as e:
            logger.warning(f"RidgeCV训练失败: {e}")
        
        if HAS_TREE_MODELS:
            try:
                lgbm = LGBMRegressor(
                    n_estimators=100, learning_rate=0.05, max_depth=5,
                    random_state=42, verbosity=-1, n_jobs=-1
                )
                lgbm.fit(X_train, y_train)
                models['lgbm'] = lgbm
            except Exception as e:
                logger.warning(f"LGBM训练失败: {e}")
            
            try:
                xgb = XGBRegressor(
                    n_estimators=100, learning_rate=0.05, max_depth=5,
                    random_state=42, verbosity=0, n_jobs=-1
                )
                xgb.fit(X_train, y_train)
                models['xgb'] = xgb
            except Exception as e:
                logger.warning(f"XGBoost训练失败: {e}")
        
        return models
    
    def _train_ridge_model(self, X_train: np.ndarray, y_train: np.ndarray) -> RidgeCV:
        """训练RidgeCV模型（中期/长期使用）"""
        model = RidgeCV(alphas=[0.1, 1.0, 10.0], cv=5)
        model.fit(X_train, y_train)
        return model
    
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
    
    def _filter_for_backtest(self, df: pd.DataFrame, selected_codes: List[str], 
                             signal_date: pd.Timestamp) -> List[str]:
        """
        回测阶段过滤：基于下一交易日的涨跌停情况过滤
        （训练/回测时可以使用历史数据）
        
        Args:
            df: 数据DataFrame
            selected_codes: 候选股票代码列表
            signal_date: 信号日
        
        Returns:
            可交易的股票代码列表
        """
        next_date = df[df['trade_date'] > signal_date]['trade_date'].min()
        
        if pd.isna(next_date):
            logger.warning("无法获取下一交易日数据")
            return selected_codes
        
        next_day_data = df[df['trade_date'] == next_date]
        signal_day_data = df[df['trade_date'] == signal_date]
        
        tradable_stocks = []
        for code in selected_codes:
            # 检查下一日数据
            stock_next = next_day_data[next_day_data['ts_code'] == code]
            stock_signal = signal_day_data[signal_day_data['ts_code'] == code]
            
            if stock_next.empty or stock_signal.empty:
                continue
            
            # 下一日停牌检查
            is_suspended = (stock_next['vol'].iloc[0] <= 0) or pd.isna(stock_next['open'].iloc[0])
            
            # 下一日涨停检查（开盘即涨停，无法买入）
            pre_close = stock_signal['close'].iloc[0]  # 使用信号日收盘价
            open_price = stock_next['open'].iloc[0]
            is_limit_up = (open_price >= round(pre_close * 1.098, 2)) if pre_close > 0 else False
            
            if not is_suspended and not is_limit_up:
                tradable_stocks.append(code)
        
        return tradable_stocks
    
    def _filter_for_production(self, df: pd.DataFrame, selected_codes: List[str], 
                           signal_date: pd.Timestamp) -> List[str]:
        """
        生产阶段过滤：仅基于信号日当天的数据判断
        
        过滤逻辑：
        1. 信号日停牌的股票
        2. ST股票和北交所股票（已在数据加载时过滤）
        
        Args:
            df: 数据DataFrame
            selected_codes: 候选股票代码列表
            signal_date: 信号日
        
        Returns:
            可交易的股票代码列表
        """
        signal_day_data = df[df['trade_date'] == signal_date]
        
        tradable_stocks = []
        for code in selected_codes:
            stock_info = signal_day_data[signal_day_data['ts_code'] == code]
            
            if stock_info.empty:
                continue
            
            # 信号日停牌检查（成交量为0或开盘价为空）
            vol = stock_info['vol'].iloc[0]
            open_price = stock_info['open'].iloc[0]
            is_suspended = (vol <= 0) or pd.isna(open_price)
            
            if is_suspended:
                logger.debug(f"股票 {code} 信号日停牌，排除")
                continue
            
            tradable_stocks.append(code)
        
        return tradable_stocks
    
    def _save_to_stockpool(self, selected_stocks: List[str], term: str, rankings: Dict[str, int] = None):
        """
        保存选中的股票到stockpool表
        
        Args:
            selected_stocks: 选中的股票代码列表
            term: 周期类型
            rankings: 股票排名字典 {ts_code: rank}，可选
        """
        if not selected_stocks:
            logger.warning("没有选中股票，跳过保存")
            return
        
        pool_type = self.POOL_TYPE_MAP.get(term, "SHORT")
        now = datetime.now()
        today = now.date()
        
        # 先删除这些股票的旧记录
        try:
            stmt = delete(StockPool).where(StockPool.ts_code.in_(selected_stocks))
            self.session.execute(stmt)
            self.session.commit()
            logger.info(f"已清除 {len(selected_stocks)} 只股票的旧记录")
        except Exception as e:
            logger.error(f"清除旧股票记录失败: {e}")
            self.session.rollback()
        
        # 插入新股票
        success_count = 0
        for code in selected_stocks:
            try:
                # 获取该股票的排名，如果rankings中没有则使用None
                rank = rankings.get(code) if rankings else None
                stock = StockPool(
                    ts_code=code,
                    pool_type=pool_type,
                    status="WATCHING",
                    model_rank=rank,
                    added_date=today,
                    update_time=now,
                )
                self.session.add(stock)
                success_count += 1
            except Exception as e:
                logger.warning(f"插入股票 {code} 失败: {e}")
        
        try:
            self.session.commit()
            logger.info(f"成功保存 {success_count} 只股票到 {pool_type} 股票池")
        except Exception as e:
            logger.error(f"保存股票池失败: {e}")
            self.session.rollback()
    
    def _run_selection(self, term: str, top_n: int = None) -> List[str]:
        """
        通用的股票筛选流程
        
        Args:
            term: 周期类型
            top_n: 选股数量
        
        Returns:
            选中的股票代码列表
        """
        logger.info("=" * 60)
        logger.info(f"开始{term}股票筛选")
        logger.info("=" * 60)
        
        # 获取参数
        params = self._get_term_params(term)
        train_window = params.get("train_window", 100)
        horizon = params.get("label_horizon", 30)
        top_n = top_n or self.selection_cfg.get("top_n", 10)
        
        # 加载因子列表
        factor_names = self._load_factor_yaml(term)
        if not factor_names:
            logger.error(f"{term}因子列表为空，无法筛选")
            return []
        
        # 加载数据
        lookback_days = train_window + horizon + 50
        factor_df = self._load_factor_data(lookback_days)
        if factor_df.empty:
            return []
        
        price_df = self._load_price_data(lookback_days)
        
        # 获取日期范围
        all_dates = sorted(factor_df['trade_date'].unique())
        if len(all_dates) < train_window + horizon:
            logger.error(f"交易日不足: {len(all_dates)} < {train_window + horizon}")
            return []
        
        start_date = all_dates[0].date() if hasattr(all_dates[0], 'date') else all_dates[0]
        end_date = all_dates[-1].date() if hasattr(all_dates[-1], 'date') else all_dates[-1]
        hs300_df = self._load_hs300_data(start_date, end_date)
        
        # 合并数据
        merged_df = self._merge_data(factor_df, price_df)
        
        # 过滤ST股票和北交所股票（关键步骤）
        merged_df = self._filter_invalid_stocks(merged_df)
        
        # 计算标签
        merged_df = self._calculate_labels(merged_df, hs300_df, horizon)
        
        # 构建训练和测试数据
        unique_dates = sorted(merged_df['trade_date'].unique())
        if len(unique_dates) <= horizon:
            logger.error("数据不足以构建训练集")
            return []
        
        train_end_date = unique_dates[-(horizon + 1)]
        train_start_idx = max(0, len(unique_dates) - train_window - horizon - 1)
        train_start_date = unique_dates[train_start_idx]
        signal_date = unique_dates[-1]
        
        # 准备特征
        X_all, feature_cols = self._prepare_features(merged_df, factor_names)
        
        # 训练数据
        train_mask = (merged_df['trade_date'] >= train_start_date) & (merged_df['trade_date'] <= train_end_date)
        train_data = merged_df[train_mask]
        
        X_train = self.imputer.fit_transform(train_data[feature_cols].values)
        y_train = train_data['label'].values
        
        # 测试数据（信号日）
        test_data = merged_df[merged_df['trade_date'] == signal_date]
        X_test = self.imputer.transform(test_data[feature_cols].values)
        test_stocks = test_data['ts_code'].values
        
        logger.info(f"训练样本数: {len(X_train)}, 测试样本数: {len(X_test)}")
        
        # 训练模型
        if term == self.TERM_SHORT:
            models = self._train_ensemble_model(X_train, y_train)
        else:
            models = {'ridge': self._train_ridge_model(X_train, y_train)}
        
        # 预测
        predictions = self._predict(models, X_test)
        
        # 选股
        pred_df = pd.DataFrame({'ts_code': test_stocks, 'pred_score': predictions})
        pred_df = pred_df.sort_values('pred_score', ascending=False)
        
        # 候选股票（多选一些用于过滤）
        candidate_stocks = pred_df.head(top_n * 3)['ts_code'].tolist()
        
        # 生产阶段过滤：基于信号日当天的数据判断可交易性
        selected_stocks = self._filter_for_production(merged_df, candidate_stocks, signal_date)
        selected_stocks = selected_stocks[:top_n]
        
        # 构建排名字典：基于最终选中股票的顺序分配排名（1到N）
        rankings = {code: rank for rank, code in enumerate(selected_stocks, 1)}
        
        logger.info(f"{term}选股完成，选中 {len(selected_stocks)} 只股票")
        for i, code in enumerate(selected_stocks, 1):
            score = pred_df[pred_df['ts_code'] == code]['pred_score'].values[0]
            logger.info(f"  第{i}名: {code} (得分: {score:.6f})")
        
        # 保存到数据库（带排名信息）
        self._save_to_stockpool(selected_stocks, term, rankings)
        
        # 清理内存
        del factor_df, price_df, merged_df, hs300_df
        gc.collect()
        
        return selected_stocks
    
    def select_short_term(self, top_n: int = None) -> List[str]:
        """短期股票筛选"""
        return self._run_selection(self.TERM_SHORT, top_n)
    
    def select_medium_term(self, top_n: int = None) -> List[str]:
        """中期股票筛选"""
        return self._run_selection(self.TERM_MEDIUM, top_n)
    
    def select_long_term(self, top_n: int = None) -> List[str]:
        """长期股票筛选"""
        return self._run_selection(self.TERM_LONG, top_n)
    
    # ====================== 大白马股票筛选 ======================
    
    def _load_white_horse_data(self) -> pd.DataFrame:
        """
        加载大白马筛选所需的全部数据
        
        整合 StockDetail 和 StockFactor 表数据，
        获取筛选和评分所需的全部字段
        """
        logger.info("加载大白马筛选数据...")
        
        # 获取最新交易日
        max_date_detail = self.session.query(func.max(StockDetail.trade_date)).scalar()
        max_date_factor = self.session.query(func.max(StockFactor.trade_date)).scalar()
        
        if max_date_detail is None:
            logger.error("StockDetail表数据为空")
            return pd.DataFrame()
        
        # 使用较近的日期作为信号日
        if max_date_factor and max_date_factor > max_date_detail:
            signal_date = max_date_detail
        else:
            signal_date = max_date_detail
        
        if isinstance(signal_date, datetime):
            signal_date = signal_date.date()
        elif isinstance(signal_date, str):
            signal_date = datetime.strptime(signal_date, "%Y%m%d").date()
        
        logger.info(f"大白马筛选信号日: {signal_date}")
        
        # 从StockDetail获取基础数据
        # 修改查询，添加 total_assets 和 total_liab
        detail_query = select(
            StockDetail.ts_code,
            StockDetail.trade_date,
            StockDetail.name,
            StockDetail.industry,
            StockDetail.close,
            StockDetail.total_mv,
            StockDetail.circ_mv,
            StockDetail.pe,
            StockDetail.pb,
            StockDetail.dv_ttm,
            StockDetail.debt_to_assets,
            StockDetail.revenue_yoy,
            StockDetail.profit_yoy,
            StockDetail.net_profit,
            StockDetail.revenue,
            StockDetail.eps,
            StockDetail.bvps,
            StockDetail.total_assets,
            StockDetail.total_liab,
        ).where(
            StockDetail.trade_date == signal_date
        )
        
        detail_df = pd.read_sql(detail_query, self.engine)
        
        if detail_df.empty:
            logger.error("StockDetail当日数据为空")
            return pd.DataFrame()
        
        # 计算原始 ROE（百分比）
        equity = detail_df['total_assets'] - detail_df['total_liab']
        # 防止除零或负净资产
        detail_df['roe_raw'] = detail_df['net_profit'] / equity.replace(0, np.nan) * 100
        detail_df['roe_raw'] = detail_df['roe_raw'].clip(-100, 100)  # 限制极端值
        
        # 合并因子表（可选，但不再依赖因子表的 roe）
        factor_query = select(
            StockFactor.ts_code,
            StockFactor.trade_date,
            StockFactor.profit_margin,
            StockFactor.quality_score,
            StockFactor.value_score,
            StockFactor.growth_score,
        ).where(
            StockFactor.trade_date == signal_date
        )
        factor_df = pd.read_sql(factor_query, self.engine)
        
        if not factor_df.empty:
            merged_df = pd.merge(
                detail_df,
                factor_df.drop(columns=['trade_date']),
                on='ts_code',
                how='left'
            )
        else:
            merged_df = detail_df
            for col in ['profit_margin', 'quality_score', 'value_score', 'growth_score']:
                merged_df[col] = np.nan
        
        logger.info(f"大白马数据加载完成: {len(merged_df)} 只股票")
        return merged_df
    
    def _apply_white_horse_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        logger.info("应用大白马硬性筛选条件...")
        initial_count = len(df)
        cfg = self.white_horse_criteria
        numeric_cols = [
            'total_mv', 'circ_mv', 'pe', 'pb', 'dv_ttm', 
            'debt_to_assets', 'revenue_yoy', 'profit_yoy', 
            'roe_raw', 'eps', 'bvps'
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 从配置读取数值，使用 _parse_config_float 清洗（关键修复）
        min_mv = self._parse_config_float(cfg.get('min_total_mv', 300))
        min_dv = self._parse_config_float(cfg.get('min_dv_ttm', 2.0))
        max_pe = self._parse_config_float(cfg.get('max_pe', 30))
        max_debt = self._parse_config_float(cfg.get('max_debt_ratio', 70.0))
        min_roe = self._parse_config_float(cfg.get('min_roe', 10.0))
        min_rev_yoy = self._parse_config_float(cfg.get('min_revenue_yoy', -10.0))
        min_profit_yoy = self._parse_config_float(cfg.get('min_profit_yoy', -10.0))
        
        # 1. 过滤ST和北交所
        df = self._filter_invalid_stocks(df)
        
        # 2. 市值筛选：总市值 >= min_total_mv 亿
        df = df[df['total_mv'] >= min_mv * 10000]
        logger.info(f"  市值筛选(>= {min_mv}亿): 剩余 {len(df)} 只")
        
        # 3. 股息率筛选：dv_ttm >= min_dv_ttm%
        df = df[(df['dv_ttm'] >= min_dv) | (df['dv_ttm'].isna())]
        df_has_dv = df[df['dv_ttm'].notna()]
        df_no_dv = df[df['dv_ttm'].isna()]
        logger.info(f"  股息率筛选(>= {min_dv}%): 有数据 {len(df_has_dv)} 只, 无数据 {len(df_no_dv)} 只")
        
        # 4. 估值筛选：min_pe < PE <= max_pe
        df = df[((df['pe'] > 0) & (df['pe'] <= max_pe)) | (df['pe'].isna())]
        logger.info(f"  估值筛选(PE 0-{max_pe}): 剩余 {len(df)} 只")
        
        # 5. 财务稳健：资产负债率 <= max_debt_ratio%
        df = df[(df['debt_to_assets'] <= max_debt) | (df['debt_to_assets'].isna())]
        logger.info(f"  资产负债率筛选(<= {max_debt}%): 剩余 {len(df)} 只")
        
        # 6. 盈利能力：ROE >= min_roe%
        df['roe_calc'] = df['roe_raw']
        df = df[(df['roe_calc'] >= min_roe) | (df['roe_calc'].isna())]
        logger.info(f"  ROE筛选(>= {min_roe}%): 剩余 {len(df)} 只")
        
        # 7. 增长筛选：允许一定程度的下滑
        df = df[(df['revenue_yoy'] >= min_rev_yoy) | (df['revenue_yoy'].isna())]
        df = df[(df['profit_yoy'] >= min_profit_yoy) | (df['profit_yoy'].isna())]
        logger.info(f"  增长筛选: 剩余 {len(df)} 只")
        
        filtered_count = initial_count - len(df)
        logger.info(f"硬性筛选完成: 过滤 {filtered_count} 只，剩余 {len(df)} 只候选股票")
        
        return df
    
    def _calculate_white_horse_scores(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算大白马综合评分
        
        评分维度和权重从 config_manager 读取：
        1. 股息率得分（dividend权重）：高分红是白马核心特征
        2. 市值得分（market_cap权重）：行业龙头大市值
        3. 盈利能力得分（profitability权重）：ROE和质量得分
        4. 财务稳健得分（financial权重）：资产负债率
        5. 估值吸引力得分（valuation权重）：PE/PB合理性
        6. 成长性得分（growth权重）：营收利润增长
        """
        logger.info("计算大白马综合评分...")
        df = df.copy()
        cfg = self.white_horse_criteria
        weights = self.white_horse_weights
        
        # ========== 1. 股息率得分 ==========
        div_weight = weights.get('dividend', 25)
        excellent_dv = self._parse_config_float(cfg.get('excellent_dv_ttm', 4.0))
        good_dv = self._parse_config_float(cfg.get('good_dv_ttm', 3.0))
        min_dv = self._parse_config_float(cfg.get('min_dv_ttm', 2.0))
        
        def score_dividend(dv_ttm):
            if pd.isna(dv_ttm):
                return 0
            if dv_ttm >= excellent_dv:
                return div_weight
            elif dv_ttm >= good_dv:
                return div_weight * 0.8
            elif dv_ttm >= min_dv:
                return div_weight * 0.6
            else:
                return max(0, dv_ttm / min_dv * div_weight * 0.6)
        
        df['score_dividend'] = df['dv_ttm'].apply(score_dividend)
        
        # ========== 2. 市值得分 ==========
        mv_weight = weights.get('market_cap', 15)
        super_mv = cfg.get('super_cap_mv', 2000)
        large_mv = cfg.get('large_cap_mv', 1000)
        min_mv = cfg.get('min_total_mv', 500)
        
        def score_market_cap(total_mv):
            if pd.isna(total_mv):
                return 0
            mv_yi = total_mv / 10000
            if mv_yi >= super_mv:
                return mv_weight
            elif mv_yi >= large_mv:
                return mv_weight * 0.8
            elif mv_yi >= min_mv:
                return mv_weight * 0.67
            else:
                return max(0, mv_yi / min_mv * mv_weight * 0.67)
        
        df['score_market_cap'] = df['total_mv'].apply(score_market_cap)
        
        # ========== 3. 盈利能力得分 ==========
        profit_weight = weights.get('profitability', 25)
        excellent_roe = cfg.get('excellent_roe', 20.0)
        good_roe = cfg.get('good_roe', 15.0)
        min_roe = cfg.get('min_roe', 10.0)
        
        def score_profitability(row):
            roe = row.get('roe_calc')
            quality_score = row.get('quality_score')
            score = 0
            
            # ROE得分（权重60%）
            roe_points = profit_weight * 0.6
            if pd.notna(roe):
                if roe >= excellent_roe:
                    score += roe_points
                elif roe >= good_roe:
                    score += roe_points * 0.8
                elif roe >= min_roe:
                    score += roe_points * 0.67
                else:
                    score += max(0, roe / min_roe * roe_points * 0.67)
            
            # 质量得分（权重40%）
            quality_points = profit_weight * 0.4
            if pd.notna(quality_score):
                if quality_score > 1:
                    score += min(quality_points, quality_score / 10)
                else:
                    score += quality_score * quality_points
            
            return score
        
        df['score_profitability'] = df.apply(score_profitability, axis=1)
        
        # ========== 4. 财务稳健得分 ==========
        fin_weight = weights.get('financial', 15)
        good_debt = cfg.get('good_debt_ratio', 60.0)
        max_debt = cfg.get('max_debt_ratio', 70.0)
        
        def score_financial_health(debt_ratio):
            if pd.isna(debt_ratio):
                return fin_weight * 0.5
            if debt_ratio <= good_debt:
                return fin_weight
            elif debt_ratio <= max_debt:
                return fin_weight * 0.67
            else:
                return max(0, fin_weight - (debt_ratio - good_debt))
        
        df['score_financial'] = df['debt_to_assets'].apply(score_financial_health)
        
        # ========== 5. 估值吸引力得分 ==========
        val_weight = weights.get('valuation', 10)
        good_pe = cfg.get('good_pe_max', 20)
        max_pe = cfg.get('max_pe', 30)
        
        def score_valuation(row):
            pe = row.get('pe')
            pb = row.get('pb')
            score = 0
            
            # PE得分（60%）
            pe_points = val_weight * 0.6
            if pd.notna(pe) and pe > 0:
                if pe <= good_pe:
                    score += pe_points
                elif pe <= max_pe:
                    score += pe_points * 0.67
                else:
                    score += max(0, pe_points - (pe - good_pe) / 2)
            
            # PB得分（40%）：PB合理区间1-3
            pb_points = val_weight * 0.4
            if pd.notna(pb) and pb > 0:
                if 1 <= pb <= 3:
                    score += pb_points
                elif pb < 1:
                    score += pb_points * 0.5
                else:
                    score += max(0, pb_points - (pb - 3))
            
            return score
        
        df['score_valuation'] = df.apply(score_valuation, axis=1)
        
        # ========== 6. 成长性得分 ==========
        growth_weight = weights.get('growth', 10)
        
        def score_growth(row):
            revenue_yoy = row.get('revenue_yoy')
            profit_yoy = row.get('profit_yoy')
            score = 0
            
            # 营收增长（50%）
            rev_points = growth_weight * 0.5
            if pd.notna(revenue_yoy):
                if revenue_yoy >= 20:
                    score += rev_points
                elif revenue_yoy >= 10:
                    score += rev_points * 0.8
                elif revenue_yoy >= 0:
                    score += rev_points * 0.6
                else:
                    score += max(0, rev_points + revenue_yoy / 10)
            
            # 利润增长（50%）
            profit_points = growth_weight * 0.5
            if pd.notna(profit_yoy):
                if profit_yoy >= 20:
                    score += profit_points
                elif profit_yoy >= 10:
                    score += profit_points * 0.8
                elif profit_yoy >= 0:
                    score += profit_points * 0.6
                else:
                    score += max(0, profit_points + profit_yoy / 10)
            
            return score
        
        df['score_growth'] = df.apply(score_growth, axis=1)
        
        # ========== 计算综合得分 ==========
        df['total_score'] = (
            df['score_dividend'] +
            df['score_market_cap'] +
            df['score_profitability'] +
            df['score_financial'] +
            df['score_valuation'] +
            df['score_growth']
        )
        
        # 记录评分详情
        logger.info("评分维度统计:")
        logger.info(f"  股息率得分: 平均 {df['score_dividend'].mean():.2f}, 最高 {df['score_dividend'].max():.2f}")
        logger.info(f"  市值得分: 平均 {df['score_market_cap'].mean():.2f}, 最高 {df['score_market_cap'].max():.2f}")
        logger.info(f"  盈利能力得分: 平均 {df['score_profitability'].mean():.2f}, 最高 {df['score_profitability'].max():.2f}")
        logger.info(f"  财务稳健得分: 平均 {df['score_financial'].mean():.2f}, 最高 {df['score_financial'].max():.2f}")
        logger.info(f"  估值吸引力得分: 平均 {df['score_valuation'].mean():.2f}, 最高 {df['score_valuation'].max():.2f}")
        logger.info(f"  成长性得分: 平均 {df['score_growth'].mean():.2f}, 最高 {df['score_growth'].max():.2f}")
        logger.info(f"  综合得分: 平均 {df['total_score'].mean():.2f}, 最高 {df['total_score'].max():.2f}")
        
        return df
    
    def _add_industry_leader_bonus(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        添加行业龙头加分
        
        在每个行业内，市值排名前三的股票获得额外加分
        """
        logger.info("计算行业龙头加分...")
        df = df.copy()
        
        leader_bonus = self.white_horse_weights.get('leader_bonus', 5)
        
        # 按行业分组，计算市值排名
        df['industry_mv_rank'] = df.groupby('industry')['total_mv'].rank(
            ascending=False, method='min'
        )
        
        # 行业龙头加分
        def get_leader_bonus(rank):
            if pd.isna(rank):
                return 0
            if rank == 1:
                return leader_bonus
            elif rank == 2:
                return leader_bonus * 0.6
            elif rank == 3:
                return leader_bonus * 0.2
            return 0
        
        df['leader_bonus'] = df['industry_mv_rank'].apply(get_leader_bonus)
        df['total_score'] = df['total_score'] + df['leader_bonus']
        
        # 统计龙头加分
        leaders = df[df['leader_bonus'] > 0]
        logger.info(f"  行业龙头加分: {len(leaders)} 只股票获得加分")
        
        return df
    
    def select_white_horse(self, top_n: int = None) -> List[str]:
        """
        大白马股票筛选
        
        筛选标准从 config_manager 读取：
        1. 高股息率：稳定分红（dv_ttm >= min_dv_ttm%）
        2. 大市值：总市值 >= min_total_mv 亿
        3. 高盈利能力：ROE >= min_roe%
        4. 财务稳健：资产负债率 <= max_debt_ratio%
        5. 估值合理：PE在合理区间
        6. 行业龙头：行业内市值排名靠前加分
        
        综合评分选出最优质的大白马股票
        
        Args:
            top_n: 选股数量，默认从配置读取
        
        Returns:
            选中的股票代码列表
        """
        logger.info("=" * 60)
        logger.info("开始大白马股票筛选")
        logger.info("=" * 60)
        
        # 从配置获取选股数量
        top_n = top_n or self.config.WHITE_HORSE_TOP_N
        
        # 1. 加载数据
        df = self._load_white_horse_data()
        if df.empty:
            logger.error("大白马数据加载失败")
            return []
        
        # 2. 应用硬性筛选条件
        df = self._apply_white_horse_filters(df)
        if df.empty:
            logger.warning("没有股票通过硬性筛选条件")
            return []
        
        # 3. 计算综合评分
        df = self._calculate_white_horse_scores(df)
        
        # 4. 添加行业龙头加分
        df = self._add_industry_leader_bonus(df)
        
        # 5. 按综合得分排序选股
        df = df.sort_values('total_score', ascending=False)
        
        # 确保有足够的候选股票
        candidate_count = min(len(df), top_n * 2)
        selected_df = df.head(candidate_count)
        
        # 6. 输出筛选结果
        logger.info("=" * 60)
        logger.info(f"大白马选股结果（前{top_n}名）:")
        logger.info("-" * 60)
        
        selected_stocks = []
        for i, (idx, row) in enumerate(selected_df.iterrows()):
            if i >= top_n:
                break
            
            ts_code = row['ts_code']
            name = row.get('name', 'N/A')
            total_score = row['total_score']
            dv_ttm = row.get('dv_ttm', 0) or 0
            total_mv = (row.get('total_mv', 0) or 0) / 10000
            roe = row.get('roe_calc', 0) or 0
            pe = row.get('pe', 0) or 0
            industry = row.get('industry', 'N/A')
            
            logger.info(
                f"  第{i+1}名: {ts_code} {name}\n"
                f"         综合得分: {total_score:.1f} | "
                f"股息率: {dv_ttm:.2f}% | "
                f"市值: {total_mv:.0f}亿 | "
                f"ROE: {roe:.1f}% | "
                f"PE: {pe:.1f} | "
                f"行业: {industry}"
            )
            
            selected_stocks.append(ts_code)
        
        # 构建排名字典：基于最终选中股票的顺序分配排名（1到N）
        rankings = {code: rank for rank, code in enumerate(selected_stocks, 1)}
        
        # 7. 保存到股票池（带排名信息）
        if selected_stocks:
            self._save_white_horse_to_pool(selected_stocks, rankings)
        
        logger.info("=" * 60)
        logger.info(f"大白马选股完成，共选中 {len(selected_stocks)} 只股票")
        
        return selected_stocks
    
    def _save_white_horse_to_pool(self, selected_stocks: List[str], rankings: Dict[str, int] = None):
        """
        保存大白马股票到股票池
        
        Args:
            selected_stocks: 选中的股票代码列表
            rankings: 股票排名字典 {ts_code: rank}，可选
        
        大白马股票使用特殊的 pool_type = "WHITE_HORSE"
        """
        if not selected_stocks:
            logger.warning("没有选中大白马股票，跳过保存")
            return
        
        pool_type = self.POOL_TYPE_MAP.get(self.TERM_WHITE_HORSE, "WHITE_HORSE")
        now = datetime.now()
        today = now.date()
        
        # 先删除大白马类型的旧记录
        try:
            stmt = delete(StockPool).where(StockPool.pool_type == pool_type)
            self.session.execute(stmt)
            self.session.commit()
            logger.info(f"已清除旧的大白马股票记录")
        except Exception as e:
            logger.error(f"清除旧大白马记录失败: {e}")
            self.session.rollback()
        
        # 插入新股票
        success_count = 0
        for code in selected_stocks:
            try:
                # 获取该股票的排名，如果rankings中没有则使用None
                rank = rankings.get(code) if rankings else None
                stock = StockPool(
                    ts_code=code,
                    pool_type=pool_type,
                    status="WATCHING",
                    model_rank=rank,
                    added_date=today,
                    update_time=now,
                )
                self.session.add(stock)
                success_count += 1
            except Exception as e:
                logger.warning(f"插入大白马股票 {code} 失败: {e}")
        
        try:
            self.session.commit()
            logger.info(f"成功保存 {success_count} 只大白马股票到股票池")
        except Exception as e:
            logger.error(f"保存大白马股票池失败: {e}")
            self.session.rollback()
    
    def close(self):
        """关闭数据库连接"""
        if self.session:
            self.session.close()