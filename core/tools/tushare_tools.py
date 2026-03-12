"""
Tushare数据工具

提供从Tushare API获取市场数据的能力，作为数据库数据缺失时的回退方案。
支持多种数据类型的获取：
- 基础行情数据
- 技术指标数据（需要历史数据计算）
- 北向资金数据
- 两融数据
- 市场资金流向数据
- 估值数据
"""

import tushare as ts
import pandas as pd
import numpy as np
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, List

from .base_tool import BaseTool, ToolResult, ToolParameter

logger = logging.getLogger(__name__)


def _get_tool_config():
    try:
        from agents.agent_config import get_agent_config
        agent_config = get_agent_config()
        default_settings = agent_config._get_default_settings()
        return default_settings.get('tools', {})
    except Exception:
        return {}


class TushareBaseMixin:
    """Tushare工具基类Mixin，提供通用初始化和配置加载"""
    
    _token: str = None
    _pro: ts.pro_api = None
    
    def _init_pro(self) -> bool:
        """初始化Tushare Pro API"""
        if self._pro is not None:
            return True
            
        if self._token is None:
            try:
                from data.basic_data.config_manager import load_config
                config = load_config()
                self._token = config.get('data_collector', {}).get('tushare_token')
            except Exception as e:
                logger.error(f"加载Tushare配置失败: {e}")
                return False
        
        if not self._token:
            logger.error("Tushare Token未配置")
            return False
            
        try:
            self._pro = ts.pro_api(self._token)
            logger.info("Tushare Pro API初始化成功")
            return True
        except Exception as e:
            logger.error(f"Tushare Pro API初始化失败: {e}")
            return False
    
    def _safe_float(self, value) -> float:
        """安全转换为浮点数"""
        if value is None or pd.isna(value):
            return 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0
    
    def _to_python_type(self, value):
        """将NumPy类型转换为Python原生类型"""
        if isinstance(value, (np.integer, np.int64, np.int32)):
            return int(value)
        elif isinstance(value, (np.floating, np.float64, np.float32)):
            return float(value)
        elif isinstance(value, np.bool_):
            return bool(value)
        elif value == np.inf or value == float('inf'):
            return 0.0
        elif pd.isna(value) or value is None:
            return 0.0
        else:
            return value


class TushareMarketDataTool(BaseTool, TushareBaseMixin):
    """
    Tushare市场数据获取工具
    
    用于从Tushare API获取指数行情数据，作为数据库数据缺失时的回退方案。
    """
    
    name = "tushare_market_data"
    description = "从Tushare API获取指数行情数据，包括开盘价、收盘价、最高价、最低价、涨跌幅、成交额等"
    version = "2.0.0"
    
    def __init__(self, token: str = None):
        BaseTool.__init__(self)
        TushareBaseMixin.__init__(self)
        self._token = token
        tool_config = _get_tool_config()
        tushare_config = tool_config.get('tushare', {})
        self.timeout = tushare_config.get('default_timeout', 30.0)
    
    def _setup_parameters(self) -> None:
        self._parameters = {
            "ts_code": ToolParameter(
                name="ts_code",
                param_type="string",
                description="指数代码，如 000001.SH（上证）、399001.SZ（深证）、399006.SZ（创业板）",
                required=True,
            ),
            "trade_date": ToolParameter(
                name="trade_date",
                param_type="string",
                description="交易日期，格式 YYYY-MM-DD 或 YYYYMMDD",
                required=True,
            ),
        }
    
    def execute(self, ts_code: str, trade_date: str) -> ToolResult:
        if not self._init_pro():
            return ToolResult.failure("Tushare API初始化失败")
        
        date_str = trade_date.replace('-', '')
        
        try:
            df = self._pro.index_daily(ts_code=ts_code, trade_date=date_str)
            
            if df.empty:
                return ToolResult.failure(f"未找到数据: {ts_code} {trade_date}")
            
            row = df.iloc[0]
            
            data = {
                'ts_code': row.get('ts_code'),
                'trade_date': trade_date,
                'open': self._safe_float(row.get('open')),
                'close': self._safe_float(row.get('close')),
                'high': self._safe_float(row.get('high')),
                'low': self._safe_float(row.get('low')),
                'pre_close': self._safe_float(row.get('pre_close')),
                'pct_chg': self._safe_float(row.get('pct_chg')),
                'vol': self._safe_float(row.get('vol')),
                'amount': self._safe_float(row.get('amount')),
            }
            
            logger.info(f"Tushare获取基础行情成功: {ts_code} {trade_date}")
            return ToolResult.success(data=data)
            
        except Exception as e:
            logger.error(f"Tushare API调用失败: {e}")
            return ToolResult.failure(f"API调用失败: {str(e)}")


class TushareTechnicalIndicatorTool(BaseTool, TushareBaseMixin):
    """
    Tushare技术指标计算工具
    
    获取历史数据并计算技术指标（MA, MACD, ADX等）
    """
    
    name = "tushare_technical_indicator"
    description = "获取指数历史数据并计算技术指标，包括MA5/10/20、MACD、ADX等"
    version = "1.0.0"
    
    def __init__(self, token: str = None):
        BaseTool.__init__(self)
        TushareBaseMixin.__init__(self)
        self._token = token
        tool_config = _get_tool_config()
        tushare_config = tool_config.get('tushare', {})
        technical_config = tool_config.get('technical', {})
        
        self.timeout = tushare_config.get('long_timeout', 60.0)
        self.MA_PERIODS = technical_config.get('ma_periods', [5, 10, 20, 60])
        self.MACD_FAST = technical_config.get('macd_fast', 12)
        self.MACD_SLOW = technical_config.get('macd_slow', 26)
        self.MACD_SIGNAL = technical_config.get('macd_signal', 9)
        self.ADX_PERIOD = technical_config.get('adx_period', 14)
    
    def _setup_parameters(self) -> None:
        self._parameters = {
            "ts_code": ToolParameter(
                name="ts_code",
                param_type="string",
                description="指数代码",
                required=True,
            ),
            "trade_date": ToolParameter(
                name="trade_date",
                param_type="string",
                description="交易日期，格式 YYYY-MM-DD",
                required=True,
            ),
        }
    
    def _calculate_ma(self, close_prices: List[float], periods: List[int]) -> Dict[str, float]:
        """计算移动平均线"""
        ma_values = {}
        for period in periods:
            if len(close_prices) >= period:
                ma_values[f'ma{period}'] = self._to_python_type(np.mean(close_prices[-period:]))
            else:
                ma_values[f'ma{period}'] = 0.0
        return ma_values
    
    def _calculate_macd(self, close_prices: List[float]) -> Dict[str, float]:
        """计算MACD指标"""
        if len(close_prices) < self.MACD_SLOW:
            return {'macd': 0.0, 'macd_signal': 0.0, 'macd_hist': 0.0}
        
        closes = pd.Series(close_prices)
        ema_fast = closes.ewm(span=self.MACD_FAST, adjust=False).mean()
        ema_slow = closes.ewm(span=self.MACD_SLOW, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=self.MACD_SIGNAL, adjust=False).mean()
        macd_hist = 2 * (dif - dea)
        
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
            df = pd.DataFrame({
                'high': high_prices,
                'low': low_prices,
                'close': close_prices
            })
            
            df['tr'] = np.maximum(
                df['high'] - df['low'],
                np.maximum(
                    abs(df['high'] - df['close'].shift(1)),
                    abs(df['low'] - df['close'].shift(1))
                )
            )
            
            df['up_move'] = df['high'] - df['high'].shift(1)
            df['down_move'] = df['low'].shift(1) - df['low']
            
            df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
            df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)
            
            df['tr_smooth'] = df['tr'].rolling(window=self.ADX_PERIOD).mean()
            df['plus_dm_smooth'] = df['plus_dm'].rolling(window=self.ADX_PERIOD).mean()
            df['minus_dm_smooth'] = df['minus_dm'].rolling(window=self.ADX_PERIOD).mean()
            
            df['plus_di'] = 100 * (df['plus_dm_smooth'] / df['tr_smooth'])
            df['minus_di'] = 100 * (df['minus_dm_smooth'] / df['tr_smooth'])
            
            df['dx'] = 100 * abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'])
            
            adx = df['dx'].rolling(window=self.ADX_PERIOD).mean().iloc[-1]
            
            return self._to_python_type(adx)
        except Exception as e:
            logger.warning(f"计算ADX失败: {e}")
            return 0.0
    
    def execute(self, ts_code: str, trade_date: str) -> ToolResult:
        if not self._init_pro():
            return ToolResult.failure("Tushare API初始化失败")
        
        try:
            trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d').date()
            start_date = (trade_date_obj - timedelta(days=120)).strftime('%Y%m%d')
            end_date = trade_date.replace('-', '')
            
            df = self._pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            
            if df.empty:
                return ToolResult.failure(f"未找到历史数据: {ts_code}")
            
            df = df.sort_values('trade_date')
            
            close_prices = [self._safe_float(x) for x in df['close'].tolist()]
            high_prices = [self._safe_float(x) for x in df['high'].tolist()]
            low_prices = [self._safe_float(x) for x in df['low'].tolist()]
            
            ma_data = self._calculate_ma(close_prices, self.MA_PERIODS)
            macd_data = self._calculate_macd(close_prices)
            adx_value = self._calculate_adx(high_prices, low_prices, close_prices)
            
            data = {
                'ts_code': ts_code,
                'trade_date': trade_date,
                'ma5': ma_data.get('ma5', 0.0),
                'ma10': ma_data.get('ma10', 0.0),
                'ma20': ma_data.get('ma20', 0.0),
                'ma60': ma_data.get('ma60', 0.0),
                'macd': macd_data.get('macd', 0.0),
                'macd_signal': macd_data.get('macd_signal', 0.0),
                'macd_hist': macd_data.get('macd_hist', 0.0),
                'adx': adx_value,
            }
            
            logger.info(f"Tushare计算技术指标成功: {ts_code} {trade_date}")
            return ToolResult.success(data=data)
            
        except Exception as e:
            logger.error(f"技术指标计算失败: {e}")
            return ToolResult.failure(f"计算失败: {str(e)}")


class TushareNorthMoneyTool(BaseTool, TushareBaseMixin):
    """
    北向资金数据获取工具
    """
    
    name = "tushare_north_money"
    description = "获取北向资金数据（沪深港通资金流向）"
    version = "1.0.0"
    
    def __init__(self, token: str = None):
        BaseTool.__init__(self)
        TushareBaseMixin.__init__(self)
        self._token = token
        tool_config = _get_tool_config()
        tushare_config = tool_config.get('tushare', {})
        self.timeout = tushare_config.get('default_timeout', 30.0)
    
    def _setup_parameters(self) -> None:
        self._parameters = {
            "trade_date": ToolParameter(
                name="trade_date",
                param_type="string",
                description="交易日期，格式 YYYY-MM-DD",
                required=True,
            ),
        }
    
    def execute(self, trade_date: str) -> ToolResult:
        if not self._init_pro():
            return ToolResult.failure("Tushare API初始化失败")
        
        date_str = trade_date.replace('-', '')
        
        try:
            df = self._pro.moneyflow_hsgt(trade_date=date_str)
            
            if df.empty:
                return ToolResult.failure(f"未找到北向资金数据: {trade_date}")
            
            row = df.iloc[0]
            north_money = self._safe_float(row.get('north_money', 0)) * 1000000
            
            data = {
                'trade_date': trade_date,
                'north_money_total': north_money,
            }
            
            logger.info(f"Tushare获取北向资金成功: {trade_date}")
            return ToolResult.success(data=data)
            
        except Exception as e:
            logger.error(f"获取北向资金失败: {e}")
            return ToolResult.failure(f"API调用失败: {str(e)}")


class TushareMarginTool(BaseTool, TushareBaseMixin):
    """
    两融数据获取工具
    
    注意：Tushare的两融数据，当日数据需要在第二天才能获得，
    所以需要获取"前一个交易日"的两融数据。
    """
    
    name = "tushare_margin"
    description = "获取两融数据（融资融券余额）- 自动获取前一个交易日的数据"
    version = "2.0.0"
    
    def __init__(self, token: str = None):
        BaseTool.__init__(self)
        TushareBaseMixin.__init__(self)
        self._token = token
        tool_config = _get_tool_config()
        tushare_config = tool_config.get('tushare', {})
        self.timeout = tushare_config.get('default_timeout', 30.0)
    
    def _setup_parameters(self) -> None:
        self._parameters = {
            "trade_date": ToolParameter(
                name="trade_date",
                param_type="string",
                description="交易日期，格式 YYYY-MM-DD",
                required=True,
            ),
        }
    
    def _get_previous_trade_date(self, trade_date: str) -> Optional[str]:
        """
        获取前一个交易日（考虑周末和节假日）
        
        Args:
            trade_date: 当前交易日（格式 YYYY-MM-DD）
        
        Returns:
            前一个交易日（格式 YYYYMMDD），如果无法获取则返回None
        """
        if not self._init_pro():
            return None
        
        try:
            current_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
            start_date = (current_date - timedelta(days=10)).strftime('%Y%m%d')
            end_date = (current_date - timedelta(days=1)).strftime('%Y%m%d')
            
            trade_cal = self._pro.trade_cal(
                exchange='SSE',
                start_date=start_date,
                end_date=end_date,
                is_open='1'
            )
            
            if not trade_cal.empty:
                trade_cal = trade_cal.sort_values('cal_date', ascending=False)
                return trade_cal.iloc[0]['cal_date']
            
            logger.warning(f"无法获取 {trade_date} 的前一个交易日")
            return None
            
        except Exception as e:
            logger.error(f"获取前一个交易日失败: {e}")
            return None
    
    def execute(self, trade_date: str) -> ToolResult:
        if not self._init_pro():
            return ToolResult.failure("Tushare API初始化失败")
        
        # 获取前一个交易日的两融数据
        prev_trade_date = self._get_previous_trade_date(trade_date)
        
        if not prev_trade_date:
            logger.warning(f"无法获取前一个交易日，尝试使用当天日期: {trade_date}")
            prev_trade_date = trade_date.replace('-', '')
        else:
            logger.info(f"获取前一个交易日两融数据: {prev_trade_date}")
        
        try:
            margin_sh = self._pro.margin(trade_date=prev_trade_date, exchange_id='SSE')
            margin_sz = self._pro.margin(trade_date=prev_trade_date, exchange_id='SZSE')
            
            total_balance = 0.0
            total_buy = 0.0
            total_short = 0.0
            
            if not margin_sh.empty:
                row = margin_sh.iloc[0]
                total_balance += self._safe_float(row.get('rzye', 0))
                total_buy += self._safe_float(row.get('rzmre', 0))
                total_short += self._safe_float(row.get('rqye', 0))
            
            if not margin_sz.empty:
                row = margin_sz.iloc[0]
                total_balance += self._safe_float(row.get('rzye', 0))
                total_buy += self._safe_float(row.get('rzmre', 0))
                total_short += self._safe_float(row.get('rqye', 0))
            
            data = {
                'trade_date': trade_date,  # 返回的是当前交易日（数据日期是前一个交易日）
                'margin_balance': self._to_python_type(total_balance),
                'margin_buy': self._to_python_type(total_buy),
                'short_balance': self._to_python_type(total_short),
            }
            
            logger.info(f"Tushare获取两融数据成功: 数据日期={prev_trade_date}, 当前日期={trade_date}")
            return ToolResult.success(data=data)
            
        except Exception as e:
            logger.error(f"获取两融数据失败: {e}")
            return ToolResult.failure(f"API调用失败: {str(e)}")


class TushareMoneyFlowTool(BaseTool, TushareBaseMixin):
    """
    市场资金流向数据获取工具
    
    优先使用Tushare API，失败时回退到akshare
    """
    
    name = "tushare_money_flow"
    description = "获取市场资金流向数据（主力、大单、中单、小单净流入）"
    version = "1.0.0"
    
    def __init__(self, token: str = None):
        BaseTool.__init__(self)
        TushareBaseMixin.__init__(self)
        self._token = token
        tool_config = _get_tool_config()
        tushare_config = tool_config.get('tushare', {})
        self.timeout = tushare_config.get('default_timeout', 30.0)
    
    def _setup_parameters(self) -> None:
        self._parameters = {
            "trade_date": ToolParameter(
                name="trade_date",
                param_type="string",
                description="交易日期，格式 YYYY-MM-DD",
                required=True,
            ),
        }
    
    def _fetch_from_tushare(self, trade_date: str) -> Optional[Dict[str, Any]]:
        """从Tushare获取资金流向数据"""
        if not self._init_pro():
            return None
        
        date_str = trade_date.replace('-', '')
        
        try:
            df = self._pro.moneyflow_mkt_dc(start_date=date_str, end_date=date_str)
            
            if df.empty:
                logger.warning(f"Tushare未找到资金流向数据: {trade_date}")
                return None
            
            row = df.iloc[0]
            
            data = {
                'trade_date': trade_date,
                'net_amount': self._safe_float(row.get('net_amount', 0)),
                'net_amount_rate': self._safe_float(row.get('net_amount_rate', 0)),
                'buy_elg_amount': self._safe_float(row.get('buy_elg_amount', 0)),
                'buy_elg_amount_rate': self._safe_float(row.get('buy_elg_amount_rate', 0)),
                'buy_lg_amount': self._safe_float(row.get('buy_lg_amount', 0)),
                'buy_lg_amount_rate': self._safe_float(row.get('buy_lg_amount_rate', 0)),
                'buy_md_amount': self._safe_float(row.get('buy_md_amount', 0)),
                'buy_md_amount_rate': self._safe_float(row.get('buy_md_amount_rate', 0)),
                'buy_sm_amount': self._safe_float(row.get('buy_sm_amount', 0)),
                'buy_sm_amount_rate': self._safe_float(row.get('buy_sm_amount_rate', 0)),
            }
            
            logger.info(f"Tushare获取资金流向成功: {trade_date}")
            return data
            
        except Exception as e:
            logger.warning(f"Tushare获取资金流向失败: {e}")
            return None
    
    def _fetch_from_akshare(self, trade_date: str) -> Optional[Dict[str, Any]]:
        """从akshare获取资金流向数据（备选方案）"""
        try:
            import akshare as ak
            
            df = ak.stock_market_fund_flow()
            
            if df.empty:
                logger.warning(f"akshare未获取到资金流向数据")
                return None
            
            from datetime import datetime as dt
            target_date = dt.strptime(trade_date, '%Y-%m-%d').date()
            row = df[df['日期'] == target_date]
            
            if row.empty:
                logger.warning(f"akshare未找到 {trade_date} 的资金流向数据")
                return None
            
            r = row.iloc[0]
            
            data = {
                'trade_date': trade_date,
                'net_amount': self._safe_float(r.get('主力净流入-净额', 0)),
                'net_amount_rate': self._safe_float(r.get('主力净流入-净占比', 0)),
                'buy_elg_amount': self._safe_float(r.get('超大单净流入-净额', 0)),
                'buy_elg_amount_rate': self._safe_float(r.get('超大单净流入-净占比', 0)),
                'buy_lg_amount': self._safe_float(r.get('大单净流入-净额', 0)),
                'buy_lg_amount_rate': self._safe_float(r.get('大单净流入-净占比', 0)),
                'buy_md_amount': self._safe_float(r.get('中单净流入-净额', 0)),
                'buy_md_amount_rate': self._safe_float(r.get('中单净流入-净占比', 0)),
                'buy_sm_amount': self._safe_float(r.get('小单净流入-净额', 0)),
                'buy_sm_amount_rate': self._safe_float(r.get('小单净流入-净占比', 0)),
            }
            
            logger.info(f"akshare获取资金流向成功: {trade_date}")
            return data
            
        except ImportError:
            logger.warning("akshare未安装，跳过备选方案")
            return None
        except Exception as e:
            logger.warning(f"akshare获取资金流向失败: {e}")
            return None
    
    def execute(self, trade_date: str) -> ToolResult:
        data = self._fetch_from_tushare(trade_date)
        
        if data is None:
            logger.info("Tushare获取失败，尝试akshare备选方案...")
            data = self._fetch_from_akshare(trade_date)
        
        if data is None:
            return ToolResult.failure(f"无法获取资金流向数据: {trade_date}")
        
        return ToolResult.success(data=data)


class TushareValuationTool(BaseTool, TushareBaseMixin):
    """
    指数估值数据获取工具
    """
    
    name = "tushare_valuation"
    description = "获取指数估值数据（PE、PB等）"
    version = "1.0.0"
    
    def __init__(self, token: str = None):
        BaseTool.__init__(self)
        TushareBaseMixin.__init__(self)
        self._token = token
        tool_config = _get_tool_config()
        tushare_config = tool_config.get('tushare', {})
        self.timeout = tushare_config.get('default_timeout', 30.0)
    
    def _setup_parameters(self) -> None:
        self._parameters = {
            "ts_code": ToolParameter(
                name="ts_code",
                param_type="string",
                description="指数代码",
                required=True,
            ),
            "trade_date": ToolParameter(
                name="trade_date",
                param_type="string",
                description="交易日期，格式 YYYY-MM-DD",
                required=True,
            ),
        }
    
    def execute(self, ts_code: str, trade_date: str) -> ToolResult:
        if not self._init_pro():
            return ToolResult.failure("Tushare API初始化失败")
        
        date_str = trade_date.replace('-', '')
        
        try:
            df = self._pro.index_dailybasic(ts_code=ts_code, trade_date=date_str)
            
            if df.empty:
                return ToolResult.failure(f"未找到估值数据: {ts_code} {trade_date}")
            
            row = df.iloc[0]
            
            data = {
                'ts_code': ts_code,
                'trade_date': trade_date,
                'pe': self._safe_float(row.get('pe', 0)),
                'pb': self._safe_float(row.get('pb', 0)),
            }
            
            logger.info(f"Tushare获取估值数据成功: {ts_code} {trade_date}")
            return ToolResult.success(data=data)
            
        except Exception as e:
            logger.error(f"获取估值数据失败: {e}")
            return ToolResult.failure(f"API调用失败: {str(e)}")


class TushareIndexBasicTool(BaseTool, TushareBaseMixin):
    """
    指数基本信息工具
    """
    
    name = "tushare_index_basic"
    description = "获取指数基本信息，包括指数名称、基日、基点等"
    version = "1.0.0"
    
    def __init__(self, token: str = None):
        BaseTool.__init__(self)
        TushareBaseMixin.__init__(self)
        self._token = token
        tool_config = _get_tool_config()
        tushare_config = tool_config.get('tushare', {})
        self.timeout = tushare_config.get('default_timeout', 30.0)
    
    def _setup_parameters(self) -> None:
        self._parameters = {
            "ts_code": ToolParameter(
                name="ts_code",
                param_type="string",
                description="指数代码",
                required=False,
            ),
            "market": ToolParameter(
                name="market",
                param_type="string",
                description="市场代码，SSE上交所 SZSE深交所",
                required=False,
            ),
        }
    
    def execute(self, ts_code: str = None, market: str = None) -> ToolResult:
        if not self._init_pro():
            return ToolResult.failure("Tushare API初始化失败")
        
        try:
            kwargs = {}
            if ts_code:
                kwargs['ts_code'] = ts_code
            if market:
                kwargs['market'] = market
                
            df = self._pro.index_basic(**kwargs)
            
            if df.empty:
                return ToolResult.failure("未找到指数基本信息")
            
            data = df.to_dict('records')
            return ToolResult.success(data=data)
            
        except Exception as e:
            logger.error(f"获取指数基本信息失败: {e}")
            return ToolResult.failure(f"API调用失败: {str(e)}")


class TushareDataCompletenessTool(BaseTool, TushareBaseMixin):
    """
    数据完整性检查和补全工具
    
    检查数据库中缺失的字段，并调用相应工具补全
    """
    
    name = "tushare_data_completeness"
    description = "检查数据完整性并补全缺失字段"
    version = "1.0.0"
    
    FIELD_GROUPS = {
        'basic': ['open', 'close', 'high', 'low', 'pct_chg', 'vol', 'amount'],
        'technical': ['ma5', 'ma10', 'ma20', 'ma60', 'macd', 'macd_signal', 'macd_hist', 'adx'],
        'north_money': ['north_money_total'],
        'margin': ['margin_balance', 'margin_buy', 'short_balance'],
        'money_flow': ['net_amount', 'net_amount_rate', 'buy_elg_amount', 'buy_elg_amount_rate',
                       'buy_lg_amount', 'buy_lg_amount_rate', 'buy_md_amount', 'buy_md_amount_rate',
                       'buy_sm_amount', 'buy_sm_amount_rate'],
        'valuation': ['pe', 'pb'],
        'market_breadth': ['adv_issues', 'dec_issues', 'adv_decline_ratio', 'market_width', 
                          'ad_line', 'turnover_concentration'],
    }
    
    def __init__(self, token: str = None):
        BaseTool.__init__(self)
        TushareBaseMixin.__init__(self)
        self._token = token
        tool_config = _get_tool_config()
        tushare_config = tool_config.get('tushare', {})
        self.timeout = tushare_config.get('extended_timeout', 120.0)
    
    def _setup_parameters(self) -> None:
        self._parameters = {
            "ts_code": ToolParameter(
                name="ts_code",
                param_type="string",
                description="指数代码",
                required=True,
            ),
            "trade_date": ToolParameter(
                name="trade_date",
                param_type="string",
                description="交易日期，格式 YYYY-MM-DD",
                required=True,
            ),
        }
    
    def check_missing_fields(self, record) -> Dict[str, List[str]]:
        """检查缺失字段，按组分类
        
        注意：
        - 两融数据（margin）：检查 None 和 0.0（API失败时存储0.0）
        - 资金流向（money_flow）：检查 None 和 0.0（API失败时存储0.0）
        - 其他字段：只检查 None
        """
        missing = {}
        ts_code = getattr(record, 'ts_code', '')
        
        # 需要检查 0.0 的字段组（API失败时会存储0.0而非None）
        strict_check_groups = {'margin', 'money_flow', 'north_money'}
        
        for group, fields in self.FIELD_GROUPS.items():
            # 资金流向只对上证指数检查
            if group == 'money_flow' and ts_code != '000001.SH':
                continue
            
            # 两融数据只对上证指数检查
            if group == 'margin' and ts_code != '000001.SH':
                continue
            
            group_missing = []
            for field in fields:
                value = getattr(record, field, None)
                
                if value is None:
                    # 所有字段：None 视为缺失
                    group_missing.append(field)
                elif group in strict_check_groups and value == 0.0:
                    # 两融和资金流向：0.0 也视为无效（API失败时的占位符）
                    group_missing.append(field)
                    
            if group_missing:
                missing[group] = group_missing
        return missing
    
    def execute(self, ts_code: str, trade_date: str) -> ToolResult:
        if not self._init_pro():
            return ToolResult.failure("Tushare API初始化失败")
        
        try:
            from data.basic_data.database import get_session, MarketIndex, init_db
            from data.basic_data.config_manager import load_config
            
            config = load_config()
            db_url = config['data_collector']['db_url']
            init_db(db_url)
            session = get_session()
            
            trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d').date()
            record = session.query(MarketIndex).filter(
                MarketIndex.ts_code == ts_code,
                MarketIndex.trade_date == trade_date_obj
            ).first()
            
            if not record:
                session.close()
                return ToolResult.failure(f"未找到记录: {ts_code} {trade_date}")
            
            missing = self.check_missing_fields(record)
            
            if not missing:
                session.close()
                return ToolResult.success(data={
                    'ts_code': ts_code,
                    'trade_date': trade_date,
                    'status': 'complete',
                    'message': '数据完整，无缺失字段'
                })
            
            collected_data = {'ts_code': ts_code, 'trade_date': trade_date}
            
            if 'basic' in missing or 'technical' in missing:
                market_tool = TushareMarketDataTool(self._token)
                tech_tool = TushareTechnicalIndicatorTool(self._token)
                
                result = market_tool.execute(ts_code, trade_date)
                if result.is_success:
                    collected_data.update(result.data)
                
                result = tech_tool.execute(ts_code, trade_date)
                if result.is_success:
                    collected_data.update(result.data)
            
            if ts_code == '000001.SH':
                if 'north_money' in missing:
                    tool = TushareNorthMoneyTool(self._token)
                    result = tool.execute(trade_date)
                    if result.is_success:
                        collected_data.update(result.data)
                
                if 'margin' in missing:
                    tool = TushareMarginTool(self._token)
                    result = tool.execute(trade_date)
                    if result.is_success:
                        collected_data.update(result.data)
                
                if 'money_flow' in missing:
                    tool = TushareMoneyFlowTool(self._token)
                    result = tool.execute(trade_date)
                    if result.is_success:
                        collected_data.update(result.data)
            
            if 'valuation' in missing:
                tool = TushareValuationTool(self._token)
                result = tool.execute(ts_code, trade_date)
                if result.is_success:
                    collected_data.update(result.data)
            
            for field, value in collected_data.items():
                if hasattr(record, field) and value is not None:
                    setattr(record, field, value)
            
            session.commit()
            session.close()
            
            logger.info(f"数据补全完成: {ts_code} {trade_date}")
            return ToolResult.success(data={
                'ts_code': ts_code,
                'trade_date': trade_date,
                'status': 'completed',
                'missing_fields': missing,
                'collected_fields': list(collected_data.keys())
            })
            
        except Exception as e:
            logger.error(f"数据完整性检查失败: {e}")
            return ToolResult.failure(f"检查失败: {str(e)}")


def register_tushare_tools(registry) -> None:
    """
    注册Tushare工具到注册中心
    """
    registry.register(TushareMarketDataTool)
    registry.register(TushareTechnicalIndicatorTool)
    registry.register(TushareNorthMoneyTool)
    registry.register(TushareMarginTool)
    registry.register(TushareMoneyFlowTool)
    registry.register(TushareValuationTool)
    registry.register(TushareIndexBasicTool)
    registry.register(TushareDataCompletenessTool)
    logger.info("Tushare工具注册完成（8个工具）")
