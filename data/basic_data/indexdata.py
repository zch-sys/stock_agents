import tushare as ts
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple
import time
import hashlib
from sqlalchemy import func, desc
import akshare as ak
from .database import MarketIndex, SectorData, StockDetail, get_session
from .config_manager import load_config, setup_logging

# 日志配置
logger = setup_logging(__name__)


class MarketCollector:
    """大盘和板块数据收集器"""

    # 配置常量（默认值，会被YAML配置覆盖）
    DEFAULT_INDICES = {
        '000001.SH': '上证指数',
        '399001.SZ': '深证成指',
        '399006.SZ': '创业板指'
    }
    DATA_RETENTION_DAYS = 1200         # 数据保留天数
    MIN_STOCK_COUNT = 50              # 板块聚合最小股票数
    MIN_INDUSTRY_STOCKS = 2           # 单个行业最小股票数
    PCT_CHG_RANGE = (-20, 20)         # 涨跌幅合理范围
    REQUEST_INTERVAL = 0.1            # API请求间隔（秒）
    
    # 技术指标计算周期
    MA_PERIODS = [5, 10, 20, 60]       # 均线周期
    MACD_FAST = 12                    # MACD快速EMA周期
    MACD_SLOW = 26                    # MACD慢速EMA周期
    MACD_SIGNAL = 9                   # MACD信号线周期
    ADX_PERIOD = 14                   # ADX计算周期
    
    def __init__(self, token: str = None):
        """初始化收集器"""
        # 加载完整配置
        config = load_config()
        self.tushare_token = token or config['data_collector']['tushare_token']
        
        # 读取market_collector配置（兼容配置不存在的情况，使用默认值）
        market_config = config.get('market_collector', {})
        
        # 覆盖默认配置（优先使用YAML中的值，无则用类默认值）
        self.DEFAULT_INDICES = market_config.get('default_indices', self.DEFAULT_INDICES)
        self.DATA_RETENTION_DAYS = market_config.get('data_retention_days', self.DATA_RETENTION_DAYS)
        self.MIN_STOCK_COUNT = market_config.get('min_stock_count', self.MIN_STOCK_COUNT)
        self.MIN_INDUSTRY_STOCKS = market_config.get('min_industry_stocks', self.MIN_INDUSTRY_STOCKS)
        # 处理列表类型的配置（如pct_chg_range）
        self.PCT_CHG_RANGE = tuple(market_config.get('pct_chg_range', self.PCT_CHG_RANGE))
        self.REQUEST_INTERVAL = market_config.get('request_interval', self.REQUEST_INTERVAL)
        
        # 初始化Tushare和数据库
        self.pro = ts.pro_api(self.tushare_token)
        self.session = get_session()
        logger.info(
            f"MarketCollector 初始化完成\n"
            f"Token: {self.tushare_token[:10]}...\n"
            f"监控指数: {list(self.DEFAULT_INDICES.keys())}\n"
            f"数据保留天数: {self.DATA_RETENTION_DAYS}"
        )

    # ====================== 新增：类型转换工具方法 ======================
    def _to_python_type(self, value):
        """将NumPy类型转换为Python原生类型"""
        if isinstance(value, (np.integer, np.int64, np.int32)):
            return int(value)
        elif isinstance(value, (np.floating, np.float64, np.float32)):
            return float(value)
        elif isinstance(value, np.bool_):
            return bool(value)
        elif value == np.inf or value == float('inf'):
            return 0.0  # 将无穷大转换为0，避免数据库存储问题
        elif pd.isna(value) or value is None:
            return 0.0
        else:
            return value
        
    def _get_previous_trade_date(self, trade_date: str) -> Optional[str]:
        """
        获取前一个交易日（考虑周末和节假日）
        
        用于两融数据获取：由于tushare的两融数据，当日的数据需要在第二天才能获得，
        所以我们需要获取"前一个交易日"的两融数据，而非简单的"前一天"。
        
        场景举例：
        - 周一的交易日，前一个交易日是上周五
        - 节假日后的第一个交易日，前一个交易日是节前最后一个交易日
        
        Args:
            trade_date: 当前交易日（格式YYYYMMDD）
        
        Returns:
            前一个交易日（格式YYYYMMDD），如果无法获取则返回None
        """
        try:
            current_date = self._str_to_date(trade_date)
            
            # 方法1：从数据库查询（优先，效率高）
            # 利用已有的MarketIndex表中的交易日数据
            prev_record = self.session.query(MarketIndex.trade_date).filter(
                MarketIndex.trade_date < current_date,
                MarketIndex.ts_code == '000001.SH'  # 使用上证指数作为参考
            ).order_by(MarketIndex.trade_date.desc()).first()
            
            if prev_record:
                prev_date = prev_record[0]
                if isinstance(prev_date, date):
                    return prev_date.strftime('%Y%m%d')
                return str(prev_date).replace('-', '')
            
            # 方法2：如果数据库没有数据，从API查询交易日历
            # 查询当前日期前10天的交易日历
            start_date = (current_date - timedelta(days=10)).strftime('%Y%m%d')
            end_date = (current_date - timedelta(days=1)).strftime('%Y%m%d')
            
            trade_cal = self._call_tushare_api(
                self.pro.trade_cal,
                exchange='SSE',
                start_date=start_date,
                end_date=end_date,
                is_open='1'
            )
            
            if not trade_cal.empty:
                # 返回最近的交易日
                trade_cal = trade_cal.sort_values('cal_date', ascending=False)
                return trade_cal.iloc[0]['cal_date']
            
            logger.warning(f"无法获取 {trade_date} 的前一个交易日")
            return None
            
        except Exception as e:
            logger.error(f"获取前一个交易日失败: {e}")
            return None
    # ====================== 新增：技术指标计算方法 ======================
    def _calculate_ma(self, close_prices: List[float], periods: List[int]) -> Dict[str, float]:
        """计算移动平均线"""
        ma_values = {}
        for period in periods:
            if len(close_prices) >= period:
                ma_values[f'ma{period}'] = self._to_python_type(
                    np.mean(close_prices[-period:])
                )
            else:
                ma_values[f'ma{period}'] = 0.0
        return ma_values
    
    def _calculate_macd(self, close_prices: List[float]) -> Dict[str, float]:
        """计算MACD指标"""
        if len(close_prices) < self.MACD_SLOW:
            return {'macd': 0.0, 'macd_signal': 0.0, 'macd_hist': 0.0}
        
        # 转换为pandas Series
        closes = pd.Series(close_prices)
        
        # 计算EMA
        ema_fast = closes.ewm(span=self.MACD_FAST, adjust=False).mean()
        ema_slow = closes.ewm(span=self.MACD_SLOW, adjust=False).mean()
        
        # 计算DIF
        dif = ema_fast - ema_slow
        
        # 计算DEA（信号线）
        dea = dif.ewm(span=self.MACD_SIGNAL, adjust=False).mean()
        
        # 计算MACD柱状图
        macd_hist = 2 * (dif - dea)
        
        # 返回最新值
        return {
            'macd': self._to_python_type(dif.iloc[-1]),
            'macd_signal': self._to_python_type(dea.iloc[-1]),
            'macd_hist': self._to_python_type(macd_hist.iloc[-1])
        }
    
    def _calculate_adx(self, high_prices: List[float], low_prices: List[float], 
                      close_prices: List[float]) -> float:
        """计算ADX指标"""
        if len(high_prices) < self.ADX_PERIOD * 2:
            return 0.0
        
        try:
            # 创建DataFrame
            df = pd.DataFrame({
                'high': high_prices,
                'low': low_prices,
                'close': close_prices
            })
            
            # 计算True Range
            df['tr'] = np.maximum(
                df['high'] - df['low'],
                np.maximum(
                    abs(df['high'] - df['close'].shift(1)),
                    abs(df['low'] - df['close'].shift(1))
                )
            )
            
            # 计算方向移动
            df['up_move'] = df['high'] - df['high'].shift(1)
            df['down_move'] = df['low'].shift(1) - df['low']
            
            df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
            df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)
            
            # 计算平滑平均值
            df['tr_smooth'] = df['tr'].rolling(window=self.ADX_PERIOD).mean()
            df['plus_dm_smooth'] = df['plus_dm'].rolling(window=self.ADX_PERIOD).mean()
            df['minus_dm_smooth'] = df['minus_dm'].rolling(window=self.ADX_PERIOD).mean()
            
            # 计算方向指标
            df['plus_di'] = 100 * (df['plus_dm_smooth'] / df['tr_smooth'])
            df['minus_di'] = 100 * (df['minus_dm_smooth'] / df['tr_smooth'])
            
            # 计算方向指数
            df['dx'] = 100 * abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'])
            
            # 计算ADX
            adx = df['dx'].rolling(window=self.ADX_PERIOD).mean().iloc[-1]
            
            return self._to_python_type(adx)
        except Exception as e:
            logger.warning(f"计算ADX失败: {e}")
            return 0.0
    
    def _calculate_market_breadth(self, trade_date_obj: date) -> Dict[str, float]:
        """计算市场宽度指标（基于个股数据）"""
        try:
            # 获取当日所有个股涨跌幅
            stocks = self.session.query(
                StockDetail.pct_chg,
                StockDetail.amount
            ).filter(
                StockDetail.trade_date == trade_date_obj,
                StockDetail.pct_chg.isnot(None),
                StockDetail.amount > 0
            ).all()
            
            if not stocks:
                return {
                    'adv_issues': 0,
                    'dec_issues': 0,
                    'adv_decline_ratio': 0.0,
                    'market_width': 0.0,
                    'ad_line': 0.0,
                    'turnover_concentration': 0.0
                }
            
            # 计算涨跌家数
            pct_chg_list = [s.pct_chg for s in stocks]
            adv_issues = sum(1 for pct in pct_chg_list if pct > 0)
            dec_issues = sum(1 for pct in pct_chg_list if pct < 0)
            
            # 计算涨跌比
            adv_decline_ratio = adv_issues / dec_issues if dec_issues > 0 else adv_issues if adv_issues > 0 else 0
            
            # 计算市场宽度（上涨家数 - 下跌家数）
            market_width = adv_issues - dec_issues
            
            # 计算腾落指数（AD Line） - 简化版本
            ad_line = market_width
            
            # 计算成交额集中度（前20%股票的成交额占比）
            amounts = [s.amount for s in stocks]
            total_amount = sum(amounts)
            
            if total_amount > 0:
                # 按成交额排序
                amounts_sorted = sorted(amounts, reverse=True)
                top_20_count = max(1, int(len(amounts_sorted) * 0.2))
                top_20_amount = sum(amounts_sorted[:top_20_count])
                turnover_concentration = (top_20_amount / total_amount) * 100
            else:
                turnover_concentration = 0.0
            
            return {
                'adv_issues': self._to_python_type(adv_issues),
                'dec_issues': self._to_python_type(dec_issues),
                'adv_decline_ratio': self._to_python_type(adv_decline_ratio),
                'market_width': self._to_python_type(market_width),
                'ad_line': self._to_python_type(ad_line),
                'turnover_concentration': self._to_python_type(turnover_concentration)
            }
            
        except Exception as e:
            logger.error(f"计算市场宽度失败: {e}")
            return {
                'adv_issues': 0,
                'dec_issues': 0,
                'adv_decline_ratio': 0.0,
                'market_width': 0.0,
                'ad_line': 0.0,
                'turnover_concentration': 0.0
            }

    # ====================== 工具方法 ======================
    def get_trade_date(self, date_str: str = None) -> str:
        """获取有效交易日（工具：日期处理）"""
        if date_str:
            return date_str
        
        today = datetime.now().strftime('%Y%m%d')
        trade_cal = self.pro.trade_cal(exchange='', start_date=today, end_date=today)
        
        # 非交易日则取最近一个交易日
        if trade_cal.empty or trade_cal.iloc[0]['is_open'] == 0:
            trade_cal = self.pro.trade_cal(exchange='', start_date='20200101', end_date=today)
            trade_cal = trade_cal[trade_cal['is_open'] == 1]
            return trade_cal.iloc[-1]['cal_date']
        return today

    def _str_to_date(self, date_str: str) -> date:
        """字符串转date对象（工具：日期处理）"""
        try:
            return datetime.strptime(date_str, '%Y%m%d').date()
        except ValueError:
            logger.error(f"日期格式错误: {date_str}")
            return datetime.now().date()

    def _clean_industry_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗行业股票数据（工具：数据清洗）"""
        return df[
            (df['open'] > 0) & 
            (df['close'] > 0) & 
            (df['circ_mv'] > 0) & 
            (df['pct_chg'].between(*self.PCT_CHG_RANGE)) & 
            (df['amount'] > 0) & 
            (df['vol'] > 0)
        ].copy()

    def _generate_sector_code(self, industry_name: str) -> str:
        """生成唯一板块编码（工具：参数校验/编码）"""
        industry_clean = industry_name.strip().replace(' ', '').replace('　', '')
        return f"IND_{hashlib.md5(industry_clean.encode('utf-8')).hexdigest()[:8].upper()}"

    def _call_tushare_api(self, func, max_retry=3, **kwargs):
        """带重试的Tushare API调用（已修复 partial 无 __name__ 问题）"""
        # 安全获取函数名：优先取 __name__，取不到则取 partial 内部函数名，最后兜底用字符串
        func_name = getattr(func, '__name__', 
                            getattr(getattr(func, 'func', None), '__name__', str(func)))
        
        for retry in range(max_retry):
            try:
                result = func(**kwargs)
                if result is not None and not result.empty:
                    return result
                
                # 如果是最后一次尝试且依然为空，记录警告
                if retry == max_retry - 1:
                    logger.warning(f"API [{func_name}] 在第 {max_retry} 次重试后仍返回空数据")
                    return pd.DataFrame()
                    
            except Exception as e:
                logger.warning(f"API [{func_name}] 调用失败 (第 {retry+1} 次重试): {e}")
                time.sleep(1.0) # 建议增加等待时间，避免频繁触发频率限制
                
        return pd.DataFrame()

    def _check_stock_data_quality(self, trade_date: str = None) -> Dict:
        """检查股票数据质量（工具：数据校验）"""
        trade_date_obj = self._str_to_date(self.get_trade_date(trade_date))
        
        # 查询有效股票数量
        total_count = self.session.query(func.count(StockDetail.id)).filter(
            StockDetail.trade_date == trade_date_obj
        ).scalar()
        
        valid_count = self.session.query(func.count(StockDetail.id)).filter(
            StockDetail.trade_date == trade_date_obj,
            StockDetail.industry.isnot(None),
            StockDetail.industry != '',
            StockDetail.close > 0,
            StockDetail.circ_mv > 0
        ).scalar()
        
        valid_rate = (valid_count / total_count) if total_count > 0 else 0
        is_qualified = valid_count >= self.MIN_STOCK_COUNT
        
        return {
            'trade_date': trade_date,
            'total_count': total_count or 0,
            'valid_count': valid_count or 0,
            'valid_rate': round(valid_rate, 2),
            'is_qualified': is_qualified
        }

    # ====================== 核心计算方法（修改类型转换） ======================
    def _calc_sector_pct_chg(self, industry_df: pd.DataFrame) -> float:
        """计算板块加权涨跌幅（核心计算：涨幅计算）"""
        try:
            # 反推昨日流通市值计算涨幅
            industry_df['pre_circ_mv'] = industry_df['circ_mv'] / (1 + industry_df['pct_chg'] / 100)
            total_pre_circ_mv = industry_df['pre_circ_mv'].sum()
            total_circ_mv = industry_df['circ_mv'].sum()
            
            if total_pre_circ_mv <= 0:
                return 0.0
            # 转换为Python原生float
            return self._to_python_type((total_circ_mv - total_pre_circ_mv) / total_pre_circ_mv * 100)
        except Exception as e:
            logger.error(f"计算板块涨幅失败: {e}")
            return 0.0

    def _calc_weighted_kline(self, industry_df: pd.DataFrame, total_circ_mv: float) -> Dict:
        """计算板块加权K线数据（核心计算：K线计算）"""
        weights = industry_df['circ_mv'] / total_circ_mv
        pct_chg = self._calc_sector_pct_chg(industry_df)
        
        weighted_close = (industry_df['close'] * weights).sum()
        
        # 所有数值转换为Python原生类型
        return {
            'open': self._to_python_type((industry_df['open'] * weights).sum()),
            'high': self._to_python_type((industry_df['high'] * weights).sum()),
            'low': self._to_python_type((industry_df['low'] * weights).sum()),
            'close': self._to_python_type(weighted_close),
            'pre_close': self._to_python_type(weighted_close / (1 + pct_chg / 100) if pct_chg != 0 else weighted_close)
        }

    def _calc_sector_stat(self, industry_df: pd.DataFrame) -> Dict:
        """计算板块统计指标（核心计算：资金流/涨跌家数）"""
        # 涨跌家数统计
        rise_mask = industry_df['pct_chg'] > 0
        fall_mask = industry_df['pct_chg'] < 0
        unchanged_mask = industry_df['pct_chg'] == 0
        
        # 转换为Python原生int
        rise_count = self._to_python_type(rise_mask.sum())
        fall_count = self._to_python_type(fall_mask.sum())
        unchanged_count = self._to_python_type(unchanged_mask.sum())
        
        # 资金流统计
        rise_amount = self._to_python_type(industry_df.loc[rise_mask, 'amount'].sum())
        fall_amount = self._to_python_type(industry_df.loc[fall_mask, 'amount'].sum())
        total_amount = self._to_python_type(industry_df['amount'].sum())
        total_vol = self._to_python_type(industry_df['vol'].sum())
        
        # 计算衍生指标
        rise_fall_ratio = rise_count / fall_count if fall_count > 0 else (float('inf') if rise_count > 0 else 1.0)
        fund_inflow = self._to_python_type(rise_amount - fall_amount)
        fund_inflow_rate = self._to_python_type((fund_inflow / total_amount * 100) if total_amount > 0 else 0)
        
        # 涨跌幅统计（转换为Python类型）
        stat = {
            'avg_pct_chg': self._to_python_type(round(industry_df['pct_chg'].mean(), 2)),
            'max_pct_chg': self._to_python_type(round(industry_df['pct_chg'].max(), 2)),
            'min_pct_chg': self._to_python_type(round(industry_df['pct_chg'].min(), 2)),
            'median_pct_chg': self._to_python_type(round(industry_df['pct_chg'].median(), 2)),
            'std_pct_chg': self._to_python_type(round(industry_df['pct_chg'].std(), 2))
        }
        
        return {
            'rise_count': rise_count,
            'fall_count': fall_count,
            'unchanged_count': unchanged_count,
            'rise_fall_ratio': self._to_python_type(round(rise_fall_ratio, 2)),
            'total_amount': total_amount,
            'total_vol': total_vol,
            'rise_amount': rise_amount,
            'fall_amount': fall_amount,
            'fund_inflow': fund_inflow,
            'fund_inflow_rate': fund_inflow_rate,
            **stat
        }

    # ====================== 新增：获取历史数据用于技术指标计算 ======================
    def _get_index_history_data(self, ts_code: str, trade_date: date, days: int = 60) -> pd.DataFrame:
        """获取指数的历史数据用于技术指标计算"""
        try:
            # 首先尝试从数据库获取
            history_records = self.session.query(MarketIndex).filter(
                MarketIndex.ts_code == ts_code,
                MarketIndex.trade_date < trade_date
            ).order_by(desc(MarketIndex.trade_date)).limit(days).all()
            
            if history_records:
                # 将数据库记录转换为DataFrame
                history_data = []
                for record in reversed(history_records):  # 反转顺序，使时间从早到晚
                    history_data.append({
                        'trade_date': record.trade_date,
                        'open': record.open,
                        'close': record.close,
                        'high': record.high,
                        'low': record.low,
                        'vol': record.vol,
                        'amount': record.amount
                    })
                
                return pd.DataFrame(history_data)
            else:
                # 如果数据库中没有足够的历史数据，从API获取
                end_date = (trade_date - timedelta(days=1)).strftime('%Y%m%d')
                start_date = (trade_date - timedelta(days=days*2)).strftime('%Y%m%d')
                
                df_history = self._call_tushare_api(
                    self.pro.index_daily,
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date
                )
                
                if not df_history.empty:
                    # 处理数据
                    df_history['trade_date'] = pd.to_datetime(df_history['trade_date'])
                    df_history = df_history.sort_values('trade_date')
                    
                    return df_history[['trade_date', 'open', 'close', 'high', 'low', 'vol', 'amount']]
                
                return pd.DataFrame()
                
        except Exception as e:
            logger.error(f"获取指数历史数据失败 {ts_code}: {e}")
            return pd.DataFrame()

    # ====================== 新增：获取两融数据的辅助方法 ======================
    def _get_margin_data(self, trade_date: str) -> Dict[str, float]:
        """获取两融数据，分别查询上交所和深交所并相加（市场总的两融数据）"""
        try:
            # 分别获取上交所和深交所的两融数据
            margin_data_sh = self._call_tushare_api(
                self.pro.margin,
                trade_date=trade_date,
                exchange_id='SSE'  # 上交所
            )
            
            margin_data_sz = self._call_tushare_api(
                self.pro.margin,
                trade_date=trade_date,
                exchange_id='SZSE'  # 深交所
            )
            
            # 初始化合并数据
            total_margin_balance = 0.0
            total_margin_buy = 0.0
            total_short_balance = 0.0
            
            # 处理上交所数据
            if not margin_data_sh.empty:
                sh_data = margin_data_sh.iloc[0]
                total_margin_balance += float(sh_data.get('rzye', 0))
                total_margin_buy += float(sh_data.get('rzmre', 0))
                total_short_balance += float(sh_data.get('rqye', 0))
    
            # 处理深交所数据
            if not margin_data_sz.empty:
                sz_data = margin_data_sz.iloc[0]
                total_margin_balance += float(sz_data.get('rzye', 0))
                total_margin_buy += float(sz_data.get('rzmre', 0))
                total_short_balance += float(sz_data.get('rqye', 0))
              
            
            # 如果都没有数据，返回0
            if margin_data_sh.empty and margin_data_sz.empty:
                logger.warning(f"两融数据为空，交易日{trade_date}可能没有两融数据")
                return {
                    'margin_balance': 0.0,
                    'margin_buy': 0.0,
                    'short_balance': 0.0
                }
            
            
            return {
                'margin_balance': self._to_python_type(total_margin_balance),
                'margin_buy': self._to_python_type(total_margin_buy),
                'short_balance': self._to_python_type(total_short_balance)
            }
            
        except Exception as e:
            logger.error(f"获取两融数据失败: {e}")
            return {
                'margin_balance': 0.0,
                'margin_buy': 0.0,
                'short_balance': 0.0
            }

    def _get_market_fund_flow(self, trade_date: str) -> Dict[str, float]:
        """
        获取全市场资金流向数据（优先Tushare，失败则使用akshare）
        
        Args:
            trade_date: 交易日期 (YYYYMMDD格式)
        
        Returns:
            包含资金流向数据的字典
        """
        try:
            df = self._call_tushare_api(
                self.pro.moneyflow_mkt_dc,
                start_date=trade_date,
                end_date=trade_date
            )
            
            if not df.empty:
                row = df.iloc[0]
                return {
                    'net_amount': self._to_python_type(float(row.get('net_amount', 0))),
                    'net_amount_rate': self._to_python_type(float(row.get('net_amount_rate', 0))),
                    'buy_elg_amount': self._to_python_type(float(row.get('buy_elg_amount', 0))),
                    'buy_elg_amount_rate': self._to_python_type(float(row.get('buy_elg_amount_rate', 0))),
                    'buy_lg_amount': self._to_python_type(float(row.get('buy_lg_amount', 0))),
                    'buy_lg_amount_rate': self._to_python_type(float(row.get('buy_lg_amount_rate', 0))),
                    'buy_md_amount': self._to_python_type(float(row.get('buy_md_amount', 0))),
                    'buy_md_amount_rate': self._to_python_type(float(row.get('buy_md_amount_rate', 0))),
                    'buy_sm_amount': self._to_python_type(float(row.get('buy_sm_amount', 0))),
                    'buy_sm_amount_rate': self._to_python_type(float(row.get('buy_sm_amount_rate', 0)))
                }
            
            logger.warning(f"Tushare资金流向数据为空，尝试使用akshare获取，交易日: {trade_date}")
            return self._get_market_fund_flow_akshare(trade_date)
            
        except Exception as e:
            logger.warning(f"Tushare获取资金流向数据失败: {e}，尝试使用akshare")
            return self._get_market_fund_flow_akshare(trade_date)

    def _get_market_fund_flow_akshare(self, trade_date: str) -> Dict[str, float]:
        """
        使用akshare获取全市场资金流向数据
        
        Args:
            trade_date: 交易日期 (YYYYMMDD格式)
        
        Returns:
            包含资金流向数据的字典
        """
        try:
            df = ak.stock_market_fund_flow()
            
            if df.empty:
                logger.warning(f"akshare资金流向数据为空，交易日: {trade_date}")
                return self._empty_fund_flow()
            
            latest_row = df.iloc[0]
            latest_date = str(latest_row.get('日期', ''))
            trade_date_fmt = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
            
            if latest_date != trade_date_fmt:
                logger.warning(f"akshare最新数据日期 {latest_date} 与目标日期 {trade_date_fmt} 不匹配")
                return self._empty_fund_flow()
            
            def safe_float(value, default=0.0):
                try:
                    if pd.isna(value) or value == '-' or value == '':
                        return default
                    return float(str(value).replace(',', '').replace('%', ''))
                except:
                    return default
            
            return {
                'net_amount': self._to_python_type(safe_float(latest_row.get('主力净流入-净额', 0))),
                'net_amount_rate': self._to_python_type(safe_float(latest_row.get('主力净流入-净占比', 0))),
                'buy_elg_amount': self._to_python_type(safe_float(latest_row.get('超大单净流入-净额', 0))),
                'buy_elg_amount_rate': self._to_python_type(safe_float(latest_row.get('超大单净流入-净占比', 0))),
                'buy_lg_amount': self._to_python_type(safe_float(latest_row.get('大单净流入-净额', 0))),
                'buy_lg_amount_rate': self._to_python_type(safe_float(latest_row.get('大单净流入-净占比', 0))),
                'buy_md_amount': self._to_python_type(safe_float(latest_row.get('中单净流入-净额', 0))),
                'buy_md_amount_rate': self._to_python_type(safe_float(latest_row.get('中单净流入-净占比', 0))),
                'buy_sm_amount': self._to_python_type(safe_float(latest_row.get('小单净流入-净额', 0))),
                'buy_sm_amount_rate': self._to_python_type(safe_float(latest_row.get('小单净流入-净占比', 0)))
            }
            
        except Exception as e:
            logger.error(f"akshare获取资金流向数据失败: {e}")
            return self._empty_fund_flow()

    def _empty_fund_flow(self) -> Dict[str, float]:
        """返回空的资金流向数据"""
        return {
            'net_amount': 0.0,
            'net_amount_rate': 0.0,
            'buy_elg_amount': 0.0,
            'buy_elg_amount_rate': 0.0,
            'buy_lg_amount': 0.0,
            'buy_lg_amount_rate': 0.0,
            'buy_md_amount': 0.0,
            'buy_md_amount_rate': 0.0,
            'buy_sm_amount': 0.0,
            'buy_sm_amount_rate': 0.0
        }

    # ====================== 修改后的批量收集方法 ======================
    def collect_market_indices(self, trade_date: str = None) -> bool:
        """批量收集大盘指数数据（优化版：删除无法获取字段，添加技术指标）"""
        try:
            trade_date = self.get_trade_date(trade_date)
            trade_date_obj = self._str_to_date(trade_date)
            logger.info(f"开始收集大盘指数数据，交易日: {trade_date}")
            
            # 计算市场宽度指标（一次性计算，所有指数共用）
            market_breadth_data = self._calculate_market_breadth(trade_date_obj)
            
            # 获取两融数据（上证指数专用）
            margin_data = None
            
            # 获取市场资金流向数据（全市场数据，只获取一次）
            fund_flow_data = None
            
            for ts_code, name in self.DEFAULT_INDICES.items():
                logger.info(f"处理指数: {name} ({ts_code})")
                
                # 获取基础行情数据
                df_daily = self._call_tushare_api(
                    self.pro.index_daily, 
                    ts_code=ts_code, 
                    start_date=trade_date, 
                    end_date=trade_date
                )
                
                if df_daily.empty:
                    logger.warning(f"指数 {name} 无日线数据")
                    continue
                
                daily_data = df_daily.iloc[0]
                
                # 获取估值数据（需要400积分）
                df_basic = pd.DataFrame()
                try:
                    df_basic = self._call_tushare_api(
                        self.pro.index_dailybasic,
                        trade_date=trade_date,
                        ts_code=ts_code
                    )
                except Exception as e:
                    logger.warning(f"获取指数估值数据失败 {ts_code}: {e}")
                
                # 初始化extra_data（不再存储重复数据）
                extra_data = {}
                
                # 北向资金、两融数据和市场资金流向数据（只在上证指数中获取）
                north_money_total = 0.0
                margin_balance = 0.0
                margin_buy = 0.0
                short_balance = 0.0
                
                # 资金流向数据（全市场数据，只在上证指数中存储）
                net_amount = None
                net_amount_rate = None
                buy_elg_amount = None
                buy_elg_amount_rate = None
                buy_lg_amount = None
                buy_lg_amount_rate = None
                buy_md_amount = None
                buy_md_amount_rate = None
                buy_sm_amount = None
                buy_sm_amount_rate = None
                
                if ts_code == '000001.SH':
                    # 北向资金（2000积分可用）- 注意单位是百万元，需要转换为元
                    north_df = self._call_tushare_api(
                        self.pro.moneyflow_hsgt,
                        trade_date=trade_date
                    )
                    if not north_df.empty:
                        north_data = north_df.iloc[0]
                        # 注意：moneyflow_hsgt返回的是百万元，转换为元
                        north_money_total = float(north_data.get('north_money', 0)) * 1000000

                    
                    # ====================== 修复：查询前一个交易日的两融数据 ======================
                    # 注意：tushare的两融数据，当日的数据需要在第二天才能获得
                    # 所以我们需要获取"前一个交易日"的两融数据，而非简单的"前一天"
                    # 需要考虑周末和节假日（例如周一的前一个交易日是上周五）
                    prev_trade_date = self._get_previous_trade_date(trade_date)
                    if prev_trade_date:
                        margin_data = self._get_margin_data(prev_trade_date)
                        logger.info(f"已查询前一个交易日两融数据，日期: {prev_trade_date}")
                    else:
                        margin_data = None
                        logger.warning(f"无法获取前一个交易日，跳过两融数据")
                    
                    if margin_data:
                        margin_balance = margin_data.get('margin_balance', 0.0)
                        margin_buy = margin_data.get('margin_buy', 0.0)
                        short_balance = margin_data.get('short_balance', 0.0)
                    
                    # 获取市场资金流向数据（全市场数据，只获取一次）
                    # 注意：资金流向数据当日即可获取（与两融数据不同）
                    if fund_flow_data is None:
                        fund_flow_data = self._get_market_fund_flow(trade_date)
                        logger.info(f"已查询当日资金流向数据，日期: {trade_date}")
                    
                    # 使用获取到的资金流向数据
                    if fund_flow_data:
                        net_amount = fund_flow_data['net_amount']
                        net_amount_rate = fund_flow_data['net_amount_rate']
                        buy_elg_amount = fund_flow_data['buy_elg_amount']
                        buy_elg_amount_rate = fund_flow_data['buy_elg_amount_rate']
                        buy_lg_amount = fund_flow_data['buy_lg_amount']
                        buy_lg_amount_rate = fund_flow_data['buy_lg_amount_rate']
                        buy_md_amount = fund_flow_data['buy_md_amount']
                        buy_md_amount_rate = fund_flow_data['buy_md_amount_rate']
                        buy_sm_amount = fund_flow_data['buy_sm_amount']
                        buy_sm_amount_rate = fund_flow_data['buy_sm_amount_rate']
                
                # ====================== 计算技术指标 ======================
                # 获取历史数据（最多60天，用于计算技术指标）
                history_df = self._get_index_history_data(ts_code, trade_date_obj, days=60)
                
                # 准备当前日数据
                current_open = float(daily_data.get('open', 0))
                current_close = float(daily_data.get('close', 0))
                current_high = float(daily_data.get('high', 0))
                current_low = float(daily_data.get('low', 0))
                current_vol = float(daily_data.get('vol', 0))
                current_amount = float(daily_data.get('amount', 0))
                
                # 合并历史数据和当前数据
                if not history_df.empty:
                    # 将历史数据转换为列表
                    close_prices = list(history_df['close'].values)
                    high_prices = list(history_df['high'].values)
                    low_prices = list(history_df['low'].values)
                    
                    # 添加当前数据
                    close_prices.append(current_close)
                    high_prices.append(current_high)
                    low_prices.append(current_low)
                    
                else:
                    # 如果没有历史数据，只使用当前数据
                    close_prices = [current_close]
                    high_prices = [current_high]
                    low_prices = [current_low]
                    logger.warning(f"历史数据不足，技术指标可能不准确")
                
                # 计算技术指标
                ma_data = self._calculate_ma(close_prices, self.MA_PERIODS)
                macd_data = self._calculate_macd(close_prices)
                adx_value = self._calculate_adx(high_prices, low_prices, close_prices)
                

                # 构建数据库对象
                market_index = MarketIndex(
                    ts_code=ts_code,
                    trade_date=trade_date_obj,
                    # 基础行情数据
                    open=self._to_python_type(current_open),
                    close=self._to_python_type(current_close),
                    high=self._to_python_type(current_high),
                    low=self._to_python_type(current_low),
                    pct_chg=self._to_python_type(float(daily_data.get('pct_chg', 0))),
                    vol=self._to_python_type(current_vol),
                    amount=self._to_python_type(current_amount),
                    
                    # 技术指标数据
                    ma5=ma_data.get('ma5', 0.0),
                    ma10=ma_data.get('ma10', 0.0),
                    ma20=ma_data.get('ma20', 0.0),
                    ma60=ma_data.get('ma60', 0.0),
                    macd=macd_data.get('macd', 0.0),
                    macd_signal=macd_data.get('macd_signal', 0.0),
                    macd_hist=macd_data.get('macd_hist', 0.0),
                    adx=self._to_python_type(adx_value),
                    
                    # 北向资金数据（只保留能获取的字段）
                    north_money_total=self._to_python_type(north_money_total),
                    # 两融数据
                    margin_balance=self._to_python_type(margin_balance),
                    margin_buy=self._to_python_type(margin_buy),
                    short_balance=self._to_python_type(short_balance),
                    
                    # 市场资金流向数据（全市场数据，仅存储在上证指数中）
                    net_amount=self._to_python_type(net_amount),
                    net_amount_rate=self._to_python_type(net_amount_rate),
                    buy_elg_amount=self._to_python_type(buy_elg_amount),
                    buy_elg_amount_rate=self._to_python_type(buy_elg_amount_rate),
                    buy_lg_amount=self._to_python_type(buy_lg_amount),
                    buy_lg_amount_rate=self._to_python_type(buy_lg_amount_rate),
                    buy_md_amount=self._to_python_type(buy_md_amount),
                    buy_md_amount_rate=self._to_python_type(buy_md_amount_rate),
                    buy_sm_amount=self._to_python_type(buy_sm_amount),
                    buy_sm_amount_rate=self._to_python_type(buy_sm_amount_rate),
                    
                    # 市场情绪与宽度数据（从个股数据计算）
                    adv_issues=market_breadth_data['adv_issues'],
                    dec_issues=market_breadth_data['dec_issues'],
                    adv_decline_ratio=market_breadth_data['adv_decline_ratio'],
                    market_width=market_breadth_data['market_width'],
                    ad_line=market_breadth_data['ad_line'],
                    turnover_concentration=market_breadth_data['turnover_concentration'],
                    
                    # 估值指标
                    pe=self._to_python_type(float(df_basic.iloc[0].get('pe', 0)) if not df_basic.empty else 0),
                    pe_ttm=self._to_python_type(float(df_basic.iloc[0].get('pe_ttm', 0)) if not df_basic.empty else 0),
                    pb=self._to_python_type(float(df_basic.iloc[0].get('pb', 0)) if not df_basic.empty else 0),
                    
                    # 扩展数据（不再存储重复数据）
                    extra_data=extra_data
                )
                
                # 写入数据库
                self.session.merge(market_index)
                logger.info(f"指数 {name} 数据保存成功")
                time.sleep(self.REQUEST_INTERVAL)
            
            # 提交并清理旧数据
            self.session.commit()
            self._clean_old_data(MarketIndex)
            logger.info("大盘指数数据收集完成")
            return True
            
        except Exception as e:
            logger.error(f"收集大盘指数数据失败: {e}", exc_info=True)
            self.session.rollback()
            return False

    def collect_sector_data(self, trade_date: str = None) -> bool:
        """批量收集板块数据（批量收集：板块）"""
        try:
            trade_date = self.get_trade_date(trade_date)
            trade_date_obj = self._str_to_date(trade_date)
            logger.info(f"开始收集板块数据，交易日: {trade_date}")
            
            # 1. 读取并清洗股票数据
            stock_details = self.session.query(
                StockDetail.ts_code, StockDetail.name, StockDetail.industry,
                StockDetail.open, StockDetail.close, StockDetail.high, StockDetail.low,
                StockDetail.pct_chg, StockDetail.vol, StockDetail.amount,
                StockDetail.total_mv, StockDetail.circ_mv, StockDetail.pre_close
            ).filter(
                StockDetail.trade_date == trade_date_obj,
                StockDetail.industry.isnot(None),
                StockDetail.industry != '',
                StockDetail.close > 0,
                StockDetail.circ_mv > 0
            ).all()
            
            if not stock_details:
                logger.error("无有效股票数据")
                return False
            
            # 转换为DataFrame并二次清洗
            df_stocks = pd.DataFrame([{
                'ts_code': s.ts_code, 'name': s.name, 'industry': s.industry,
                'open': s.open, 'close': s.close, 'high': s.high, 'low': s.low,
                'pct_chg': s.pct_chg, 'vol': s.vol, 'amount': s.amount,
                'total_mv': s.total_mv, 'circ_mv': s.circ_mv, 'pre_close': s.pre_close
            } for s in stock_details])
            
            df_stocks = self._clean_industry_data(df_stocks)
            if len(df_stocks) < self.MIN_STOCK_COUNT:
                logger.error(f"有效股票不足（{len(df_stocks)}/{self.MIN_STOCK_COUNT}）")
                return False
            
            # 2. 按行业聚合计算
            sector_data_list = []
            for industry_name, industry_df in df_stocks.groupby('industry'):
                try:
                    industry_df = self._clean_industry_data(industry_df)
                    if len(industry_df) < self.MIN_INDUSTRY_STOCKS:
                        continue
                    
                    # 核心计算
                    total_circ_mv = self._to_python_type(industry_df['circ_mv'].sum())
                    total_total_mv = self._to_python_type(industry_df['total_mv'].sum())
                    pct_chg_weighted = self._calc_sector_pct_chg(industry_df)
                    kline_data = self._calc_weighted_kline(industry_df, total_circ_mv)
                    stat_data = self._calc_sector_stat(industry_df)
                    
                    # 处理成分股数据（确保所有数值都是Python类型）
                    constituent_stocks = []
                    for _, row in industry_df[['ts_code','name','pct_chg','total_mv','circ_mv']].iterrows():
                        constituent_stocks.append({
                            'ts_code': row['ts_code'],
                            'name': row['name'],
                            'pct_chg': self._to_python_type(row['pct_chg']),
                            'total_mv': self._to_python_type(row['total_mv']),
                            'circ_mv': self._to_python_type(row['circ_mv'])
                        })
                    
                    # 构建板块数据对象（所有数值转换为Python类型）
                    sector_data = SectorData(
                        sector_code=self._generate_sector_code(industry_name),
                        sector_name=industry_name,
                        trade_date=trade_date_obj,
                        open=kline_data['open'],
                        high=kline_data['high'],
                        low=kline_data['low'],
                        close=kline_data['close'],
                        pre_close=kline_data['pre_close'],
                        pct_chg=pct_chg_weighted,
                        vol=stat_data['total_vol'],
                        amount=stat_data['total_amount'],
                        total_market_cap=total_total_mv,
                        circ_market_cap=total_circ_mv,
                        rank=0,
                        stock_count=self._to_python_type(len(industry_df)),
                        rise_count=stat_data['rise_count'],
                        fall_count=stat_data['fall_count'],
                        unchanged_count=stat_data['unchanged_count'],
                        rise_fall_ratio=stat_data['rise_fall_ratio'],
                        fund_inflow=stat_data['fund_inflow'],
                        fund_inflow_rate=stat_data['fund_inflow_rate'],
                        rise_amount=stat_data['rise_amount'],
                        fall_amount=stat_data['fall_amount'],
                        avg_pct_chg=stat_data['avg_pct_chg'],
                        max_pct_chg=stat_data['max_pct_chg'],
                        min_pct_chg=stat_data['min_pct_chg'],
                        median_pct_chg=stat_data['median_pct_chg'],
                        std_pct_chg=stat_data['std_pct_chg'],
                        constituent_stocks=constituent_stocks
                    )
                    sector_data_list.append(sector_data)
                    
                except Exception as e:
                    logger.warning(f"处理行业 {industry_name} 失败: {e}", exc_info=True)
                    continue
            
            if not sector_data_list:
                logger.warning("未生成有效板块数据")
                return False
            
            # 3. 计算板块排名并入库
            sorted_sectors = sorted(sector_data_list, key=lambda x: x.pct_chg, reverse=True)
            for rank, sector in enumerate(sorted_sectors, 1):
                sector.rank = self._to_python_type(rank)
                self.session.merge(sector)
            
            # 提交并清理旧数据
            self.session.commit()
            self._clean_old_data(SectorData)
            
            # 输出统计信息
            avg_pct = sum(s.pct_chg for s in sector_data_list) / len(sector_data_list)
            logger.info(f"板块数据收集完成 - 共{len(sector_data_list)}个行业，平均涨幅{avg_pct:.2f}%")
            logger.info(f"最强板块: {sorted_sectors[0].sector_name} ({sorted_sectors[0].pct_chg:.2f}%)")
            logger.info(f"最弱板块: {sorted_sectors[-1].sector_name} ({sorted_sectors[-1].pct_chg:.2f}%)")
            
            return True
            
        except Exception as e:
            logger.error(f"收集板块数据失败: {e}", exc_info=True)
            self.session.rollback()
            return False

    # ====================== 数据清理方法 ======================
    def _clean_old_data(self, model, days: int = None):
        """统一清理旧数据（支持指数/板块）"""
        try:
            days = days or self.DATA_RETENTION_DAYS
            
            # 获取保留的截止日期
            cutoff_date = self.session.query(model.trade_date)\
                .distinct()\
                .order_by(model.trade_date.desc())\
                .offset(days - 1)\
                .limit(1)\
                .scalar()
            
            if cutoff_date:
                deleted_count = self.session.query(model)\
                    .filter(model.trade_date <= cutoff_date)\
                    .delete()
                
                self.session.commit()
                logger.info(f"清理{model.__tablename__}数据：删除{deleted_count}条，保留日期>{cutoff_date}")
        
        except Exception as e:
            logger.error(f"清理{model.__tablename__}数据失败: {e}")
            self.session.rollback()

    # ====================== 任务编排方法 ======================
    def batch_collect_sector_data(self, trade_date: str = None, force_update: bool = False) -> Dict:
        """板块数据批量收集入口"""
        try:
            trade_date = self.get_trade_date(trade_date)
            trade_date_obj = self._str_to_date(trade_date)
            
            # 检查是否已有数据
            if not force_update:
                existing_count = self.session.query(SectorData).filter(
                    SectorData.trade_date == trade_date_obj
                ).count()
                if existing_count > 0:
                    return {
                        'trade_date': trade_date,
                        'status': 'skipped',
                        'reason': 'data_already_exists',
                        'existing_count': existing_count
                    }
            
            # 执行收集
            success = self.collect_sector_data(trade_date)
            return {
                'trade_date': trade_date,
                'status': 'success' if success else 'failed',
                'success': success
            }
            
        except Exception as e:
            logger.error(f"批量收集板块数据失败: {e}")
            return {
                'trade_date': trade_date,
                'status': 'error',
                'error': str(e)
            }

    def run_sector_collection(self, trade_date: str = None) -> Dict:
        """执行板块数据收集任务"""
        logger.info("开始执行板块数据收集任务")
        result = self.batch_collect_sector_data(trade_date)
        
        if result['status'] == 'success':
            logger.info("板块数据收集任务成功完成")
        elif result['status'] == 'skipped':
            logger.info(f"板块数据收集任务跳过: {result['reason']}")
        else:
            logger.error(f"板块数据收集任务失败: {result}")
        
        return result

    def run_daily_collection(self, trade_date: str = None) -> Dict:
        """每日数据收集主入口（仅负责任务编排）"""
        logger.info("开始执行每日大盘/板块数据收集任务")
        result = {
            'trade_date': self.get_trade_date(trade_date),
            'market_indices': {'status': 'failed', 'error': ''},
            'stock_data_check': {},
            'sector_data': {'status': 'failed', 'error': ''},
            'overall_status': 'failed'
        }
        
        try:
            # 1. 收集大盘指数
            try:
                market_success = self.collect_market_indices(trade_date)
                result['market_indices'] = {'status': 'success' if market_success else 'failed'}
            except Exception as e:
                result['market_indices']['error'] = str(e)
            
            # 2. 检查股票数据质量
            result['stock_data_check'] = self._check_stock_data_quality(trade_date)
            if not result['stock_data_check']['is_qualified']:
                result['sector_data']['error'] = f"股票数据质量不达标（有效数{result['stock_data_check']['valid_count']}）"
                return result
            
            # 3. 收集板块数据
            try:
                sector_result = self.batch_collect_sector_data(trade_date, force_update=True)
                result['sector_data'] = sector_result
            except Exception as e:
                result['sector_data']['error'] = str(e)
            
            # 4. 整体状态判断
            result['overall_status'] = 'success' if (
                result['market_indices']['status'] == 'success' and
                result['sector_data']['status'] == 'success'
            ) else 'partial_failed' if (
                result['market_indices']['status'] == 'success' or result['sector_data']['status'] == 'success'
            ) else 'failed'
            
        except Exception as e:
            logger.error(f"每日数据收集任务执行失败: {e}")
            result['overall_status'] = 'failed'
        
        logger.info(f"每日数据收集任务完成 - 整体状态: {result['overall_status']}")
        return result