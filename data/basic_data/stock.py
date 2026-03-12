import tushare as ts
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple
from sqlalchemy import inspect
import time
from sqlalchemy import and_
# 导入数据库模型
from .database import StockDetail, get_session
from .config_manager import load_config, setup_logging

# 配置日志
logger = setup_logging(__name__)


# 常量定义
ONE_YEAR_DAYS = 1200  # 保留1200日的高频数据（约5年）
FREQ_LOW_UPDATE_FIELD = 'low_freq_update_date'  # 低频更新时间字段
CACHE_CLEAN_SECONDS = 86400  # 缓存自动清理间隔：1天
# 技术指标计算所需最小数据量
MIN_DATA_FOR_INDICATORS = {
    'ma5': 5, 'ma10': 10, 'ma20': 20, 'ma60': 60,
    'rsi6': 6, 'rsi12': 12, 'rsi24': 24,
    'macd': 26, 'bbands': 20,
    'volume_ma5': 5, 'volume_ma10': 10
}


class StockCollector:
    """个股数据收集器（拆分高频/低频，支持全量/增量更新）"""
    
    def __init__(self, token: str = None):
        """初始化收集器"""
        # 读取YAML配置
        config = load_config()
        # 优先使用传入的token，否则用配置文件的
        self.tushare_token = token or config['data_collector']['tushare_token']
        self.pro = ts.pro_api(self.tushare_token)
        
        self.session = get_session()
        # 缓存结构：{ts_code}_{trade_date}: {财报数据}
        self.financial_cache = {}
        # 缓存最后清理时间，用于自动清理
        self.last_cache_clean = datetime.now()
        # 记录每只股票最近一次财报更新日期，避免重复调用接口
        self.last_financial_update = {}
        
        logger.info("StockCollector 初始化完成")

    # ---------------------- 基础工具方法 ----------------------
    def get_trade_date(self, date_str: str = None) -> str:
        """获取交易日（优先传入，否则取最近一个有效交易日）"""
        if date_str:
            return date_str
        
        pro = self.pro
        today = datetime.now().strftime('%Y%m%d') 
        start_date = (datetime.now() - timedelta(days=5)).strftime('%Y%m%d')
        
        try:
            trade_cal_df = pro.trade_cal(exchange='', start_date=start_date, end_date=today)
            # 筛选出开市的日期，并按日期倒序
            trade_dates = trade_cal_df[trade_cal_df['is_open'] == 1]['cal_date'].tolist()
            trade_dates.sort(reverse=True)  # 最近的日期在前
            
            if trade_dates:
                # 返回最近的一个交易日
                latest_trade_date = trade_dates[0]
                logger.info(f"获取到最近交易日：{latest_trade_date} (今天：{today})")
                return latest_trade_date
            else:
                # 极端情况，返回昨天（理论上不会发生）
                logger.warning("未从接口查询到交易日，返回昨天日期")
                yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
                return yesterday
        except Exception as e:
            logger.error(f"获取交易日历时发生异常，返回今天日期 {today}: {e}")
            return today

    def _safe_float(self, value, default=0.0):
        """安全转换为float，处理None值"""
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    def _validate_stock_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """校验并清洗股票数据（过滤停盘/异常数据）"""
        if df.empty:
            return df
        
        # 过滤停盘数据（收盘价为0、成交量为0）
        df = df[(df['close'] > 0) & (df['vol'] > 0)]
        # 按日期排序
        df = df.sort_values('trade_date').reset_index(drop=True)
        # 检查数据连续性（停盘超过12天的标记）
        df['trade_date_dt'] = pd.to_datetime(df['trade_date'])
        df['date_gap'] = df['trade_date_dt'].diff().dt.days
        if df['date_gap'].max() > 12:
            logger.warning(f"股票数据存在超过12天的停盘间隔，指标计算可能不准确")

        return df.drop('trade_date_dt', axis=1) if 'trade_date_dt' in df.columns else df

    def get_stock_list(self, exchange: str = '', list_status: str = 'L') -> List[str]:
        """获取股票列表（上市状态）"""
        try:
            stock_list = self.pro.stock_basic(
                exchange=exchange,
                list_status=list_status,
                fields='ts_code'
            )
            return stock_list['ts_code'].tolist()
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            return []

    # ---------------------- 技术指标计算（核心优化：支持全量批量计算） ----------------------
    def _calculate_indicators_full_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        批量计算所有交易日的技术指标（返回带trade_date的DataFrame）
        核心优化：一次性计算所有行的指标，避免逐行重复计算
        """
        if df.empty:
            return pd.DataFrame()
        
        # 确保数据已清洗和排序
        df = self._validate_stock_data(df)
        close_prices = df['close'].astype(float)
        vol_data = df['vol'].astype(float)
        data_len = len(df)
        
        # 初始化指标DataFrame
        indicators_df = pd.DataFrame(index=df.index)
        indicators_df['trade_date'] = df['trade_date']
        
        # 1. 移动平均线（批量计算所有行）
        for ma_name, min_len in [('ma5',5), ('ma10',10), ('ma20',20), ('ma60',60)]:
            if data_len >= min_len:
                ma_series = ta.sma(close_prices, length=min_len)
                # 处理pandas-ta返回None的情况
                if ma_series is None:
                    indicators_df[ma_name] = 0.0
                else:
                    indicators_df[ma_name] = ma_series.apply(self._safe_float).fillna(0.0)
            else:
                indicators_df[ma_name] = 0.0
                logger.debug(f"数据量不足{min_len}天，无法计算{ma_name}")
        
        # 2. 成交量均线（批量计算所有行）
        for vol_ma_name, min_len in [('volume_ma5',5), ('volume_ma10',10)]:
            if data_len >= min_len:
                vol_ma_series = ta.sma(vol_data, length=min_len)
                if vol_ma_series is None:
                    indicators_df[vol_ma_name] = 0.0
                else:
                    indicators_df[vol_ma_name] = vol_ma_series.apply(self._safe_float).fillna(0.0)
            else:
                indicators_df[vol_ma_name] = 0.0
                logger.debug(f"数据量不足{min_len}天，无法计算{vol_ma_name}")
        
        # 3. MACD (最小26天，批量计算所有行)
        if data_len >= 26:
            macd_result = ta.macd(close_prices, fast=12, slow=26, signal=9)
            if macd_result is not None and not macd_result.empty:
                indicators_df['macd'] = macd_result.iloc[:, 0].apply(self._safe_float).fillna(0.0)
                indicators_df['macd_signal'] = macd_result.iloc[:, 2].apply(self._safe_float).fillna(0.0)
                indicators_df['macd_hist'] = macd_result.iloc[:, 1].apply(self._safe_float).fillna(0.0)
            else:
                indicators_df[['macd', 'macd_signal', 'macd_hist']] = 0.0
        else:
            indicators_df[['macd', 'macd_signal', 'macd_hist']] = 0.0
            logger.debug("数据量不足26天，无法计算MACD")
        
        # 4. RSI（批量计算所有行）
        for rsi_name, min_len in [('rsi6',6), ('rsi12',12), ('rsi24',24)]:
            if data_len >= min_len:
                rsi_series = ta.rsi(close_prices, length=min_len)
                if rsi_series is None:
                    indicators_df[rsi_name] = 0.0
                else:
                    indicators_df[rsi_name] = rsi_series.apply(self._safe_float).fillna(0.0)
            else:
                indicators_df[rsi_name] = 0.0
                logger.debug(f"数据量不足{min_len}天，无法计算{rsi_name}")
        
        # 5. 布林带 (最小20天，批量计算所有行)
        if data_len >= 20:
            boll_result = ta.bbands(close_prices, length=20, std=2)
            if boll_result is not None and not boll_result.empty:
                indicators_df['boll_upper'] = boll_result.iloc[:, 2].apply(self._safe_float).fillna(0.0)
                indicators_df['boll_middle'] = boll_result.iloc[:, 1].apply(self._safe_float).fillna(0.0)
                indicators_df['boll_lower'] = boll_result.iloc[:, 0].apply(self._safe_float).fillna(0.0)
            else:
                indicators_df[['boll_upper', 'boll_middle', 'boll_lower']] = 0.0
        else:
            indicators_df[['boll_upper', 'boll_middle', 'boll_lower']] = 0.0
            logger.debug("数据量不足20天，无法计算布林带")
        
        # 填充所有NaN值为0
        indicators_df = indicators_df.fillna(0.0)
        return indicators_df

    def _calculate_indicators_full(self, df: pd.DataFrame) -> Dict:
        """全量计算最后一个交易日的技术指标（增量更新时用）"""
        indicators = {}
        if df.empty:
            return indicators
        
        # 调用批量计算方法，取最后一行数据
        indicators_df = self._calculate_indicators_full_batch(df)
        if not indicators_df.empty:
            last_indicators = indicators_df.iloc[-1].to_dict()
            # 只保留指标字段
            for key in self._get_empty_indicators().keys():
                indicators[key] = last_indicators.get(key, 0.0)
        
        return indicators

    def _calculate_indicators_incremental(self, df: pd.DataFrame, last_indicators: Dict = None) -> Dict:
        """增量计算技术指标（日频更新时使用）"""
        # 默认使用上次指标值，仅更新可增量计算的部分
        indicators = last_indicators.copy() if last_indicators else {}
        df = self._validate_stock_data(df)
        
        if df.empty or len(df) < 2:
            return indicators
        
        # 仅取最新的N条数据（足够计算增量即可）
        close_prices = df['close'].astype(float)
        vol_data = df['vol'].astype(float)
        data_len = len(df)
        
        # 增量更新移动平均线（公式：新MA = 旧MA*(n-1)/n + 最新价/n）
        for ma_name, n in [('ma5',5), ('ma10',10), ('ma20',20), ('ma60',60)]:
            if data_len >= n and ma_name in indicators:
                new_ma = indicators[ma_name] * (n-1)/n + close_prices.iloc[-1]/n
                indicators[ma_name] = self._safe_float(new_ma)
            elif data_len < n and ma_name not in indicators:
                indicators[ma_name] = 0.0
        
        # 增量更新成交量均线
        for vol_ma_name, n in [('volume_ma5',5), ('volume_ma10',10)]:
            if data_len >= n and vol_ma_name in indicators:
                new_vol_ma = indicators[vol_ma_name] * (n-1)/n + vol_data.iloc[-1]/n
                indicators[vol_ma_name] = self._safe_float(new_vol_ma)
            elif data_len < n and vol_ma_name not in indicators:
                indicators[vol_ma_name] = 0.0
        
        # MACD/RSI/布林带：仍用最近足够数据计算（增量公式复杂，用短窗口全量算更简单）
        if data_len >= 26:
            macd_result = ta.macd(close_prices.tail(60), fast=12, slow=26, signal=9)
            if macd_result is not None and not macd_result.empty:
                indicators['macd'] = self._safe_float(macd_result.iloc[-1, 0])
                indicators['macd_signal'] = self._safe_float(macd_result.iloc[-1, 2])
                indicators['macd_hist'] = self._safe_float(macd_result.iloc[-1, 1])
        
        for rsi_name, min_len in [('rsi6',6), ('rsi12',12), ('rsi24',24)]:
            if data_len >= min_len:
                rsi_series = ta.rsi(close_prices.tail(min_len*2), length=min_len)
                if rsi_series is not None and not rsi_series.empty:
                    indicators[rsi_name] = self._safe_float(rsi_series.iloc[-1])
        
        if data_len >= 20:
            boll_result = ta.bbands(close_prices.tail(60), length=20, std=2)
            if boll_result is not None and not boll_result.empty:
                indicators['boll_upper'] = self._safe_float(boll_result.iloc[-1, 2])
                indicators['boll_middle'] = self._safe_float(boll_result.iloc[-1, 1])
                indicators['boll_lower'] = self._safe_float(boll_result.iloc[-1, 0])
        
        return indicators

    def calculate_technical_indicators(self, df: pd.DataFrame, is_incremental: bool = False, 
                                      last_indicators: Dict = None, return_batch: bool = False) -> Dict | pd.DataFrame:
        """
        统一的技术指标计算入口
        :param df: 股票数据DataFrame
        :param is_incremental: 是否增量计算（日频更新时用）
        :param last_indicators: 上一次的指标值（增量计算时需要）
        :param return_batch: 是否返回批量指标（全量收集时用）
        :return: 技术指标字典（增量）或DataFrame（全量批量）
        """
        try:
            # 清洗数据并检查有效性
            df = self._validate_stock_data(df)
            data_len = len(df)
            logger.debug(f"股票数据字段：{df.columns.tolist()}，数据量：{data_len}")
            
            # 新上市股票（数据量<5天）直接返回空指标
            if data_len < 5:
                logger.warning(f"股票数据仅{data_len}条（新上市/停盘），跳过技术指标计算")
                if return_batch:
                    empty_df = pd.DataFrame([self._get_empty_indicators()]*data_len)
                    empty_df['trade_date'] = df['trade_date'].values
                    return empty_df
                else:
                    return self._get_empty_indicators()
            
            # 选择计算模式
            if return_batch:
                # 批量返回所有交易日指标（全量收集用）
                indicators = self._calculate_indicators_full_batch(df)
            elif is_incremental and last_indicators:
                # 增量计算（返回字典）
                indicators = self._calculate_indicators_incremental(df, last_indicators)
            else:
                # 全量计算最后一条（返回字典）
                indicators = self._calculate_indicators_full(df)
            
            # 补全缺失的指标（确保返回结构完整）
            if isinstance(indicators, dict):
                return self._complete_indicators(indicators)
            return indicators
        except Exception as e:
            logger.error(f"计算技术指标失败: {e}", exc_info=True)
            if return_batch:
                empty_df = pd.DataFrame([self._get_empty_indicators()]*len(df))
                empty_df['trade_date'] = df['trade_date'].values
                return empty_df
            else:
                return self._get_empty_indicators()
    
    def _get_empty_indicators(self) -> Dict:
        """返回空的技术指标字典（结构完整，值为0）"""
        return {
            'volume_ma5': 0.0, 'volume_ma10': 0.0,
            'ma5': 0.0, 'ma10': 0.0, 'ma20': 0.0, 'ma60': 0.0,
            'macd': 0.0, 'macd_signal': 0.0, 'macd_hist': 0.0,
            'rsi6': 0.0, 'rsi12': 0.0, 'rsi24': 0.0,
            'boll_upper': 0.0, 'boll_middle': 0.0, 'boll_lower': 0.0,
        }
    
    def _get_empty_financial_template(self) -> Dict:
        """
        抽离公共空财报数据模板，与全量收集逻辑对齐，全局复用
        """
        return {
            'name': '','industry': '', 'area': '',
            'market': '', 'list_date': '',
            'eps': 0.0,'bvps': 0.0,'total_assets': 0.0,'total_liab': 0.0,'net_profit': 0.0,
            'revenue': 0.0,'debt_to_assets': 0.0,'current_ratio': 0.0,
            'quick_ratio': 0.0,'cash_ratio': 0.0,'revenue_yoy': 0.0,
            'profit_yoy': 0.0, FREQ_LOW_UPDATE_FIELD: '19000101','_disclosure_date': '19000101',
            '_report_period': '19000101'
        }

    def _parse_date(self, date_str: Optional[str], fmt: str = "%Y%m%d") -> Optional[datetime.date]:
        """
        统一日期解析工具方法，封装异常处理，替代重复的strptime代码
        """
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, fmt).date()
        except (ValueError, TypeError):
            return None
    
    def _complete_indicators(self, indicators: Dict) -> Dict:
        """补全指标字典（确保所有字段都存在，避免KeyError）"""
        empty_indicators = self._get_empty_indicators()
        for key in empty_indicators.keys():
            if key not in indicators:
                indicators[key] = empty_indicators[key]
        return indicators

    def _get_latest_disclosed_report(self, ts_code: str, trade_date: str) -> Dict:
        """
        获取交易日前【已实际披露】的最新财报数据
        修复：正确使用disclosure_date接口参数
        """
        # 自动清理过期缓存
        if (datetime.now() - self.last_cache_clean).total_seconds() > CACHE_CLEAN_SECONDS:
            self.financial_cache.clear()
            self.last_cache_clean = datetime.now()
            logger.info("财报缓存已自动清理")
            
        cache_key = f"{ts_code}_{trade_date}"
        
        # 检查缓存
        if cache_key in self.financial_cache:
            return self.financial_cache[cache_key]
        
        try:
            # 方法1：先通过ann_date筛选已披露的财报
            # 查询该股票在交易日之前已实际披露的财报
            # 使用ann_date作为筛选条件，因为这是实际披露日期
            disclosure_df = self.pro.disclosure_date(
                ts_code=ts_code,
                # 我们不传end_date，而是让接口返回所有记录
                # 然后我们在本地筛选 ann_date <= trade_date
                fields='ann_date,end_date,actual_date'
            )
            
            if disclosure_df.empty:
                logger.warning(f"股票 {ts_code} 没有找到任何财报披露记录")
                self.financial_cache[cache_key] = None
                return None
            
            # 修复核心：筛选出在交易日之前已实际披露的财报
            # 使用actual_date优先，如果没有则使用ann_date
            def get_effective_date(row):
                # 优先使用actual_date（实际披露日期），其次用ann_date（公告日期）
                if pd.notna(row.get('actual_date')) and row['actual_date'] != '':
                    return row['actual_date']
                return row['ann_date']
            
            # 计算有效披露日期
            disclosure_df['effective_date'] = disclosure_df.apply(get_effective_date, axis=1)
            
            # 筛选在交易日之前已披露的财报
            disclosed_reports = disclosure_df[disclosure_df['effective_date'] <= trade_date]
            
            if disclosed_reports.empty:
                logger.warning(f"股票 {ts_code} 在 {trade_date} 前无已披露财报")
                self.financial_cache[cache_key] = None
                return None
            
            # 找出截止日期最晚的已披露财报（end_date最大的）
            disclosed_reports = disclosed_reports.sort_values('end_date', ascending=False)
            latest_report = disclosed_reports.iloc[0]
            report_period = latest_report['end_date']
            effective_disclose_date = latest_report['effective_date']
            
            logger.debug(f"股票 {ts_code} 在 {trade_date} 前的最新已披露财报: "
                        f"{report_period} (有效披露日期 {effective_disclose_date})")
            
            # 获取财报详细数据
            financial_data = self._get_low_freq_data(ts_code, report_period)
            
            if not financial_data:
                self.financial_cache[cache_key] = None
                return None
            
            result = {
                'period': report_period,
                'ann_date': effective_disclose_date,
                'data': financial_data
            }
            
            # 存入缓存
            self.financial_cache[cache_key] = result
            return result
            
        except Exception as e:
            logger.error(f"获取股票 {ts_code} 最新披露财报失败: {e}", exc_info=True)
            self.financial_cache[cache_key] = None
            return None

    # ---------------------- 全行业适配版：低频数据获取 -----------------------
    def _get_low_freq_data(self, ts_code: str, period: str) -> Dict:
        try:
            # 1. 获取股票基础信息
            basic_info = self.pro.stock_basic(
                ts_code=ts_code,
                fields='ts_code,name,industry,area,market,list_date'
            )
            if basic_info.empty:
                logger.warning(f"无法获取股票 {ts_code} 基本信息")
                return {}
            basic_data = basic_info.iloc[0]
            industry = str(basic_data.get("industry", "")).strip()

            # 行业类型映射
            industry_type_map = {"银行": 2, "证券": 4, "保险": 3}
            comp_type = 1
            for key, type_val in industry_type_map.items():
                if key in industry:
                    comp_type = type_val
                    break

            # 基础参数
            base_params = {"ts_code": ts_code, "period": period}
            finance_params = {**base_params, "comp_type": comp_type}

            # 2. 财务指标接口
            fina_fields = 'eps,bps,debt_to_assets,current_ratio,quick_ratio,cash_ratio,netprofit_yoy,tr_yoy'
            fina_data = self.pro.fina_indicator(**base_params, fields=fina_fields)
            latest_fina = fina_data.iloc[0] if not fina_data.empty else None

            # 3. 资产负债表接口
            balance_fields = 'total_assets,total_liab'
            balance_data = self.pro.balancesheet(**finance_params, fields=balance_fields)
            latest_balance = balance_data.iloc[0] if not balance_data.empty else None

            # 4. 利润表接口
            income_fields = 'revenue,n_income'
            income_data = self.pro.income(**finance_params, fields=income_fields)
            latest_income = income_data.iloc[0] if not income_data.empty else None

            # 5. 财务数据结构初始化
            financial_data = {
                'eps': 0.0,
                'bvps': 0.0,
                'debt_to_assets': 0.0,
                'current_ratio': 0.0,
                'quick_ratio': 0.0,
                'cash_ratio': 0.0,
                'revenue_yoy': 0.0,
                'profit_yoy': 0.0,
                'total_assets': 0.0,
                'total_liab': 0.0,
                'net_profit': 0.0,
                'revenue': 0.0,
            }

            # 赋值财务指标
            if latest_fina is not None:
                financial_data.update({
                    'eps': self._safe_float(latest_fina.get('eps')),
                    'bvps': self._safe_float(latest_fina.get('bps')),
                    'debt_to_assets': self._safe_float(latest_fina.get('debt_to_assets')),
                    'current_ratio': self._safe_float(latest_fina.get('current_ratio')),
                    'quick_ratio': self._safe_float(latest_fina.get('quick_ratio')),
                    'cash_ratio': self._safe_float(latest_fina.get('cash_ratio')),
                    'revenue_yoy': self._safe_float(latest_fina.get('tr_yoy')),
                    'profit_yoy': self._safe_float(latest_fina.get('netprofit_yoy')),
                })

            # 赋值资产负债数据
            if latest_balance is not None:
                financial_data.update({
                    'total_assets': self._safe_float(latest_balance.get('total_assets')),
                    'total_liab': self._safe_float(latest_balance.get('total_liab')),
                })

            # 赋值利润数据
            if latest_income is not None:
                financial_data.update({
                    'revenue': self._safe_float(latest_income.get('revenue')),
                    'net_profit': self._safe_float(latest_income.get('n_income')),
                })

            # ===== 新增：检查是否全为0（未发布的财报）=====
            # 检查关键财务指标是否全部为0，如果是则视为无效财报（未发布）
            key_fields = ['eps', 'total_assets', 'revenue', 'net_profit']
            all_zero = True
            for field in key_fields:
                if financial_data.get(field, 0) != 0:
                    all_zero = False
                    break
            
            # 如果所有关键指标都为0，说明这是未发布的财报占位数据
            if all_zero:
                return {}
            
            # 6. 整合最终数据
            financial_data_final = {
                'ts_code': basic_data.get('ts_code', ''),
                'name': basic_data.get('name', ''),
                'industry': basic_data.get('industry', ''),
                'area': basic_data.get('area', ''),
                'market': basic_data.get('market', ''),
                'list_date': basic_data.get('list_date', ''),
                **financial_data,
                FREQ_LOW_UPDATE_FIELD: period
            }

            return financial_data_final
        except Exception as e:
            logger.error(f"获取股票 {ts_code} 低频数据失败(period={period}): {e}", exc_info=True)
            return {}

    # ---------------------- 方法1：个股高频数据收集（修复版） ----------------------
    def collect_single_stock_high_freq(self, ts_code: str, trade_date: str = None) -> bool:
        """
        收集单一个股的高频数据（当日）
        修复：财报判断逻辑、类型转换、字段复用逻辑
        """
        try:
            trade_date = self.get_trade_date(trade_date)
            logger.info(f"开始收集个股 {ts_code} 高频数据（交易日：{trade_date}）")
            
            # 1. 获取当日日线数据
            df_daily = self.pro.daily(ts_code=ts_code, start_date=trade_date, end_date=trade_date)
            if df_daily.empty:
                logger.warning(f"个股 {ts_code} 当日日线数据为空")
                return False
            latest_data = df_daily.iloc[0]
            
            # 2. 获取当日估值数据
            daily_basic = self.pro.daily_basic(
                ts_code=ts_code,
                trade_date=trade_date,
                fields='pe,pb,ps,total_mv,circ_mv,total_share,float_share,dv_ttm'
            )
            valuation_data = daily_basic.iloc[0].to_dict() if not daily_basic.empty else {}
            
            # 3. 计算技术指标
            last_record = self.session.query(StockDetail).filter(
                StockDetail.ts_code == ts_code
            ).order_by(StockDetail.trade_date.desc()).first()
            
            if last_record:
                start_date = (datetime.now() - timedelta(days=60)).strftime('%Y%m%d')
                df_history = self.pro.daily(ts_code=ts_code, start_date=start_date, end_date=trade_date)
                last_indicators = {
                    'volume_ma5': last_record.volume_ma5, 'volume_ma10': last_record.volume_ma10,
                    'ma5': last_record.ma5, 'ma10': last_record.ma10, 'ma20': last_record.ma20, 'ma60': last_record.ma60,
                    'macd': last_record.macd, 'macd_signal': last_record.macd_signal, 'macd_hist': last_record.macd_hist,
                    'rsi6': last_record.rsi6, 'rsi12': last_record.rsi12, 'rsi24': last_record.rsi24,
                    'boll_upper': last_record.boll_upper, 'boll_middle': last_record.boll_middle, 'boll_lower': last_record.boll_lower,
                }
                indicators = self.calculate_technical_indicators(df_history, is_incremental=True, last_indicators=last_indicators)
            else:
                start_date = (datetime.now() - timedelta(days=ONE_YEAR_DAYS)).strftime('%Y%m%d')
                df_yearly = self.pro.daily(ts_code=ts_code, start_date=start_date, end_date=trade_date)
                indicators = self.calculate_technical_indicators(df_yearly, is_incremental=False)
            
            # 4. 组装高频数据：修复vol安全类型转换
            high_freq_data = {
                'open': self._safe_float(latest_data.get('open')),
                'close': self._safe_float(latest_data.get('close')),
                'high': self._safe_float(latest_data.get('high')),
                'low': self._safe_float(latest_data.get('low')),
                'pct_chg': self._safe_float(latest_data.get('pct_chg')),
                'vol': int(self._safe_float(latest_data.get('vol', 0))),
                'amount': self._safe_float(latest_data.get('amount')),
                'pre_close': self._safe_float(latest_data.get('pre_close')),
                'change': self._safe_float(latest_data.get('change')),
                **indicators,
                'pe': self._safe_float(valuation_data.get('pe')),
                'pb': self._safe_float(valuation_data.get('pb')),
                'ps': self._safe_float(valuation_data.get('ps')),
                'total_mv': self._safe_float(valuation_data.get('total_mv')),
                'circ_mv': self._safe_float(valuation_data.get('circ_mv')),
                'total_share':self._safe_float(valuation_data.get('total_share')),
                'float_share':self._safe_float(valuation_data.get('float_share')),
                'dv_ttm': self._safe_float(valuation_data.get('dv_ttm')),
                'ts_code': ts_code,
                'trade_date': datetime.strptime(trade_date, '%Y%m%d').date()
            }
            
            # 保留原逻辑：按条数清理一年数据（未修改）
            stock_records = self.session.query(StockDetail).filter(
                StockDetail.ts_code == ts_code
            ).order_by(StockDetail.trade_date).all()
            if len(stock_records) >= ONE_YEAR_DAYS:
                oldest_record = stock_records[0]
                self.session.delete(oldest_record)
            
            # 6. 判断当日记录是否存在
            existing_record = self.session.query(StockDetail).filter(
                and_(StockDetail.ts_code == ts_code, StockDetail.trade_date == high_freq_data['trade_date'])
            ).first()
            
            if existing_record:
                # 更新高频字段，低频字段不变
                for key, value in high_freq_data.items():
                    if hasattr(existing_record, key):
                        setattr(existing_record, key, value)
                logger.info(f"更新个股 {ts_code} 当日高频数据")
            else:
                # 修复核心：重构财报更新判断逻辑，兼容非交易日披露
                need_fetch_financial = False
                if last_record is not None:
                    current_report = self._get_latest_disclosed_report(ts_code, trade_date)
                    last_report_period = last_record.low_freq_update_date.strftime("%Y%m%d") if last_record.low_freq_update_date else ""
                    if current_report and current_report['period'] != last_report_period:
                        need_fetch_financial = True
                        logger.info(f"股票{ts_code}检测到新财报，更新财务数据")
                else:
                    # 新股强制拉取财报
                    need_fetch_financial = True
                
                # 获取财报数据
                if need_fetch_financial:
                    report_info = self._get_latest_disclosed_report(ts_code, trade_date)
                    if report_info:
                        low_freq_data = report_info['data']
                        low_freq_data[FREQ_LOW_UPDATE_FIELD] = report_info['period']
                        logger.info(f"个股 {ts_code} 拉取到最新财报: {report_info['period']}")
                    else:
                        low_freq_data = {}
                        logger.warning(f"个股 {ts_code} 无可用财报数据")
                else:
                    # 修复：替换硬编码字段复制，使用ORM反射自动复制低频字段
                    model_columns = [c.name for c in inspect(StockDetail).columns]
                    exclude_fields = ['trade_date', 'id', 'open', 'close', 'high', 'low', 'vol', 'amount', 'pct_chg', 'change', 'pre_close']
                    low_freq_data = {}
                    for key in model_columns:
                        if key not in exclude_fields and hasattr(last_record, key):
                            low_freq_data[key] = getattr(last_record, key)
                    # 标准化日期格式
                    low_freq_data[FREQ_LOW_UPDATE_FIELD] = last_record.low_freq_update_date.strftime("%Y%m%d") if last_record.low_freq_update_date else trade_date
                
                # 插入新记录
                    # 插入新记录
                    low_freq_data = low_freq_data or {}
                    list_date_val = None
                    if low_freq_data.get('list_date'):
                        try:
                            date_val = low_freq_data.get('list_date')
                            # 兼容字符串/日期对象两种类型
                            if isinstance(date_val, str):
                                list_date_val = datetime.strptime(date_val, '%Y%m%d').date()
                            elif isinstance(date_val, (datetime, date)):
                                list_date_val = date_val.date() if isinstance(date_val, datetime) else date_val
                            else:
                                list_date_val = None
                        except (ValueError, TypeError):
                            list_date_val = None
                    else:
                        list_date_val = None

                    # ========== 修复：提前定义 low_freq_update_date 变量 ==========
                    try:
                        update_date_val = low_freq_data.get(FREQ_LOW_UPDATE_FIELD, trade_date)
                        if isinstance(update_date_val, str):
                            low_freq_update_date = datetime.strptime(update_date_val, '%Y%m%d').date()
                        elif isinstance(update_date_val, (datetime, date)):
                            low_freq_update_date = update_date_val.date() if isinstance(update_date_val, datetime) else update_date_val
                        else:
                            # 兜底逻辑：格式异常时使用当前交易日
                            low_freq_update_date = datetime.strptime(trade_date, '%Y%m%d').date()
                    except (ValueError, TypeError):
                        # 解析失败兜底
                        low_freq_update_date = datetime.strptime(trade_date, '%Y%m%d').date()

                    # 实例化数据模型，变量均已定义，无报错
                    stock_detail = StockDetail(
                        **high_freq_data,
                        # 低频数据
                        name=low_freq_data.get('name', ''),
                        industry=low_freq_data.get('industry', ''),
                        area=low_freq_data.get('area', ''),
                        market=low_freq_data.get('market', ''),
                        list_date=list_date_val,
                        eps=low_freq_data.get('eps', 0),
                        bvps=low_freq_data.get('bvps', 0),
                        total_assets=low_freq_data.get('total_assets', 0),
                        total_liab=low_freq_data.get('total_liab', 0),
                        net_profit=low_freq_data.get('net_profit', 0),
                        revenue=low_freq_data.get('revenue', 0),
                        debt_to_assets=low_freq_data.get('debt_to_assets', 0),
                        current_ratio=low_freq_data.get('current_ratio', 0),
                        quick_ratio=low_freq_data.get('quick_ratio', 0),
                        cash_ratio=low_freq_data.get('cash_ratio', 0),
                        revenue_yoy=low_freq_data.get('revenue_yoy', 0),
                        profit_yoy=low_freq_data.get('profit_yoy', 0),
                        # 变量已定义，可正常赋值
                        low_freq_update_date=low_freq_update_date
                    )
                self.session.add(stock_detail)
                logger.info(f"插入个股 {ts_code} 当日高频数据")
            
            self.session.commit()
            logger.info(f"个股 {ts_code} 高频数据收集完成")
            return True
        except Exception as e:
            logger.error(f"收集个股 {ts_code} 高频数据失败: {e}", exc_info=True)
            self.session.rollback()
            return False

# ---------------------- 方法2：重写个股低频数据收集（对齐全量收集逻辑） ----------------------
    def collect_single_stock_low_freq(self, ts_code: str, trade_date: str = None) -> bool:
        """
        优化重写版：与全量数据收集逻辑完全对齐
        1. 批量拉取时间范围内所有财报披露记录+财报数据
        2. 内存内为每条历史记录匹配对应生效财报
        3. 批量更新数据库存量记录，解决原函数重复调用API问题
        """
        try:
            # 1. 初始化时间范围：基准交易日+回溯一年（与全量收集保持一致）
            end_date = self.get_trade_date(trade_date)
            start_date = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=ONE_YEAR_DAYS)).strftime("%Y%m%d")
            logger.info(f"开始批量更新 {ts_code} 低频财务数据 | 财报时间范围：{start_date} ~ {end_date}")

            # 2. 核心优化：批量获取所有财报数据，构建内存映射表
            financial_data_map: Dict[str, Dict] = {}
            empty_fin_data = self._get_empty_financial_template()

            try:
                # 获取财报披露信息
                disclosure_df = self.pro.disclosure_date(
                    ts_code=ts_code,
                    fields='ann_date,end_date,actual_date'
                )

                if not disclosure_df.empty:
                    # 复用全量函数：计算生效披露日期（优先实际披露日）
                    def get_effective_date(row):
                        if pd.notna(row.get('actual_date')) and row['actual_date'] != '':
                            return row['actual_date']
                        return row['ann_date']

                    disclosure_df['effective_date'] = disclosure_df.apply(get_effective_date, axis=1)

                    # 筛选时间范围内的有效披露记录
                    relevant_disclosures = disclosure_df[
                        (disclosure_df["effective_date"] >= start_date) &
                        (disclosure_df["effective_date"] <= end_date)
                    ].copy()

                    if not relevant_disclosures.empty:
                        # 按披露日期排序，保证匹配最新财报
                        relevant_disclosures = relevant_disclosures.sort_values("effective_date")
                        unique_periods = relevant_disclosures["end_date"].unique()
                        logger.debug(f"股票 {ts_code} 共获取到 {len(unique_periods)} 个有效财报周期")

                        # 批量拉取所有财报数据，缓存至内存
                        for period in unique_periods:
                            try:
                                financial_data = self._get_low_freq_data(ts_code, period)
                                if financial_data:
                                    # 绑定披露日期与周期，用于后续匹配
                                    period_dis = relevant_disclosures[relevant_disclosures['end_date'] == period]
                                    if not period_dis.empty:
                                        latest_dis = period_dis.iloc[-1]
                                        financial_data["_disclosure_date"] = latest_dis["effective_date"]
                                        financial_data["_report_period"] = period
                                        financial_data_map[period] = financial_data
                            except Exception as e:
                                logger.warning(f"获取 {ts_code} 财报周期 {period} 数据失败: {str(e)}")
                                continue
            except Exception as e:
                logger.warning(f"获取 {ts_code} 财报披露记录失败: {str(e)}")

            # 兜底逻辑：无有效财报时使用空模板
            if not financial_data_map:
                logger.warning(f"股票 {ts_code} 无可用财报数据，使用空数据模板")
                financial_data_map["empty"] = empty_fin_data

            # 3. 查询该股票所有存量记录（全量匹配后更新）
            stock_records = self.session.query(StockDetail).filter(
                StockDetail.ts_code == ts_code
            ).all()

            if not stock_records:
                logger.info(f"股票 {ts_code} 无存量记录，无需更新")
                return True

            logger.info(f"股票 {ts_code} 共查询到 {len(stock_records)} 条存量待处理记录")

            # 4. 对齐全量规则：为每条记录匹配【披露日期≤交易日】的最近财报
            update_count = 0
            for record in stock_records:
                # 转换记录交易日为字符串，用于匹配
                record_date_str = record.trade_date.strftime("%Y%m%d")
                applicable_fin = None

                # 遍历内存财报映射表，匹配最优财报
                for period, fin_data in financial_data_map.items():
                    if period == "empty":
                        continue
                    disclose_date = fin_data.get("_disclosure_date", "99999999")
                    if disclose_date <= record_date_str:
                        # 选择披露时间最新的财报
                        if applicable_fin is None or disclose_date > applicable_fin.get("_disclosure_date", "0"):
                            applicable_fin = fin_data

                # 兜底：无匹配财报时使用空模板
                low_freq_data = applicable_fin if applicable_fin is not None else empty_fin_data

                # 5. 统一字段赋值，复用工具方法，兼容格式校验
                list_date_value = self._parse_date(low_freq_data.get("list_date"))
                update_period = low_freq_data.get("_report_period", end_date)

                # 基础静态信息
                record.name = low_freq_data.get('name', record.name)
                record.industry = low_freq_data.get('industry', record.industry)
                record.area = low_freq_data.get('area', record.area)
                record.market = low_freq_data.get('market', record.market)
                record.list_date = list_date_value or record.list_date
                
                # 核心财务指标
                record.eps = self._safe_float(low_freq_data.get('eps', record.eps))
                record.bvps = self._safe_float(low_freq_data.get('bvps', record.bvps))
                record.total_assets = self._safe_float(low_freq_data.get('total_assets', record.total_assets))
                record.total_liab = self._safe_float(low_freq_data.get('total_liab', record.total_liab))
                record.net_profit = self._safe_float(low_freq_data.get('net_profit', record.net_profit))
                record.revenue = self._safe_float(low_freq_data.get('revenue', record.revenue))
                
                # 偿债能力与增长指标
                record.debt_to_assets = self._safe_float(low_freq_data.get('debt_to_assets', record.debt_to_assets))
                record.current_ratio = self._safe_float(low_freq_data.get('current_ratio', record.current_ratio))
                record.quick_ratio = self._safe_float(low_freq_data.get('quick_ratio', record.quick_ratio))
                record.cash_ratio = self._safe_float(low_freq_data.get('cash_ratio', record.cash_ratio))
                record.revenue_yoy = self._safe_float(low_freq_data.get('revenue_yoy', record.revenue_yoy))
                record.profit_yoy = self._safe_float(low_freq_data.get('profit_yoy', record.profit_yoy))
                
                # 更新财报标记日期
                record.low_freq_update_date = self._parse_date(update_period) or record.low_freq_update_date
                update_count += 1

            # 批量提交事务
            self.session.commit()
            logger.info(f"股票 {ts_code} 低频数据更新完成，共更新 {update_count} 条历史记录")
            return True

        except Exception as e:
            logger.error(f"更新股票 {ts_code} 低频数据失败: {str(e)}", exc_info=True)
            self.session.rollback()
            return False

    # ---------------------- 方法3：所有股票高频数据收集 ----------------------
    def batch_collect_all_stocks_high_freq(self, ts_codes: List[str] = None, trade_date: str = None) -> Dict:
        """
        收集所有股票的高频数据（当日）
        :param ts_codes: 股票列表，None则获取所有上市股票
        :return: 收集结果统计
        """
        results = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'failed_codes': []
        }
        
        # 获取股票列表
        ts_codes = ts_codes or self.get_stock_list()
        results['total'] = len(ts_codes)
        logger.info(f"开始批量收集所有股票高频数据（共 {results['total']} 只股票）")
        
        # 逐个收集
        for i, ts_code in enumerate(ts_codes):
            try:
                logger.info(f"处理第 {i+1}/{results['total']} 只股票: {ts_code}")
                success = self.collect_single_stock_high_freq(ts_code, trade_date)
                if success:
                    results['success'] += 1
                else:
                    results['failed'] += 1
                    results['failed_codes'].append(ts_code)
                time.sleep(0.2)  # 控制请求频率
            except Exception as e:
                logger.error(f"批量处理股票 {ts_code} 高频数据失败: {e}", exc_info=True)
                results['failed'] += 1
                results['failed_codes'].append(ts_code)
        
        logger.info(f"批量高频数据收集完成：成功 {results['success']}，失败 {results['failed']}")
        return results

    # ---------------------- 方法4：所有股票低频数据收集 ----------------------
    def batch_collect_all_stocks_low_freq(self, ts_codes: List[str] = None, trade_date: str = None) -> Dict:
        """
        收集所有股票的低频数据（覆写更新）
        :param ts_codes: 股票列表，None则获取所有上市股票
        :return: 收集结果统计
        """
        results = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'failed_codes': []
        }
        
        # 获取股票列表
        ts_codes = ts_codes or self.get_stock_list()
        results['total'] = len(ts_codes)
        logger.info(f"开始批量更新所有股票低频数据（共 {results['total']} 只股票）")
        
        # 逐个更新
        for i, ts_code in enumerate(ts_codes):
            try:
                logger.info(f"处理第 {i+1}/{results['total']} 只股票: {ts_code}")
                success = self.collect_single_stock_low_freq(ts_code, trade_date)
                if success:
                    results['success'] += 1
                else:
                    results['failed'] += 1
                    results['failed_codes'].append(ts_code)
                time.sleep(0.3)  # 低频更新频率可更低
            except Exception as e:
                logger.error(f"批量处理股票 {ts_code} 低频数据失败: {e}", exc_info=True)
                results['failed'] += 1
                results['failed_codes'].append(ts_code)
        
        logger.info(f"批量低频数据更新完成：成功 {results['success']}，失败 {results['failed']}")
        return results

    # ---------------------- 方法5：所有股票全量数据收集（核心优化） ----------------------
    def batch_collect_all_stocks_full(self, ts_codes: List[str] = None, end_date: str = None) -> Dict:
        """
        全量收集所有股票数据（过去一年日频高频+对应财报数据）
        优化：一次性获取所有财报数据，在内存中匹配
        """
        results = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'failed_codes': []
        }
        
        # 初始化参数
        end_date = self.get_trade_date(end_date)
        start_date = (datetime.strptime(end_date, '%Y%m%d') - timedelta(days=ONE_YEAR_DAYS)).strftime('%Y%m%d')
        ts_codes = ts_codes or self.get_stock_list()
        results['total'] = len(ts_codes)
        
        logger.info(f"开始全量收集所有股票数据（时间范围：{start_date} 至 {end_date}，共 {results['total']} 只股票）")
        
        # 清空缓存
        self.financial_cache = {}
        
        for i, ts_code in enumerate(ts_codes):
            try:
                logger.info(f"处理第 {i+1}/{results['total']} 只股票: {ts_code}")
                
                # 1. 获取该股票过去一年的日线数据
                df_daily = self.pro.daily(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date
                )
                
                if df_daily.empty:
                    logger.warning(f"股票 {ts_code} 过去一年日线数据为空")
                    results['failed'] += 1
                    results['failed_codes'].append(ts_code)
                    continue
                
                # 2. 数据清洗
                df_daily = self._validate_stock_data(df_daily)
                if df_daily.empty:
                    logger.warning(f"股票 {ts_code} 清洗后数据为空")
                    results['failed'] += 1
                    results['failed_codes'].append(ts_code)
                    continue
                
                # 3. 批量计算所有交易日的技术指标
                indicators_df = self.calculate_technical_indicators(
                    df_daily, 
                    is_incremental=False, 
                    return_batch=True
                )
                
                # 4. 批量获取估值数据
                trade_dates = df_daily['trade_date'].tolist()
                valuation_dict = {}
                try:
                    daily_basic_df = self.pro.daily_basic(
                        ts_code=ts_code,
                        start_date=start_date,
                        end_date=end_date,
                        fields='trade_date,pe,pb,ps,total_mv,circ_mv,total_share,float_share,dv_ttm'
                    )
                    if not daily_basic_df.empty:
                        for _, row in daily_basic_df.iterrows():
                            valuation_dict[row['trade_date']] = row.to_dict()
                except Exception as e:
                    logger.warning(f"批量获取 {ts_code} 估值数据失败: {e}")

                # 核心优化：一次性获取所有财报数据
                financial_data_map = {}  # {财报周期: 财报数据}
                
                try:
                    # 获取所有财报披露记录
                    disclosure_df = self.pro.disclosure_date(
                        ts_code=ts_code,
                        fields='ann_date,end_date,actual_date'
                    )
                    
                    if not disclosure_df.empty:
                        # 处理实际披露日期
                        def get_effective_date(row):
                            if pd.notna(row.get('actual_date')) and row['actual_date'] != '':
                                return row['actual_date']
                            return row['ann_date']
                        
                        disclosure_df['effective_date'] = disclosure_df.apply(get_effective_date, axis=1)
                        
                        # 只保留在时间范围内的财报披露记录
                        relevant_disclosures = disclosure_df[
                            (disclosure_df['effective_date'] >= start_date) & 
                            (disclosure_df['effective_date'] <= end_date)
                        ].copy()
                        
                        if not relevant_disclosures.empty:
                            # 按披露日期排序
                            relevant_disclosures = relevant_disclosures.sort_values('effective_date')
                            
                            # 获取每个财报周期的数据
                            unique_periods = relevant_disclosures['end_date'].unique()
                            logger.debug(f"股票 {ts_code} 有 {len(unique_periods)} 个财报周期需要获取")
                            
                            # 批量获取财报数据（减少重复调用）
                            for period in unique_periods:
                                try:
                                    financial_data = self._get_low_freq_data(ts_code, period)
                                    if financial_data:
                                        # 添加财报周期和披露日期信息
                                        period_disclosures = relevant_disclosures[relevant_disclosures['end_date'] == period]
                                        if not period_disclosures.empty:
                                            # 获取该财报周期的最新披露日期
                                            latest_disclosure = period_disclosures.iloc[-1]
                                            financial_data['_disclosure_date'] = latest_disclosure['effective_date']
                                            financial_data['_report_period'] = period
                                            
                                            financial_data_map[period] = financial_data
                                            logger.debug(f"获取到财报周期 {period} 数据")
                                except Exception as e:
                                    logger.warning(f"获取 {ts_code} 财报周期 {period} 数据失败: {e}")
                                    continue
                except Exception as e:
                    logger.warning(f"获取 {ts_code} 财报披露记录失败: {e}")
                
                # 5. 处理每个交易日，匹配财报数据
                df_daily = df_daily.sort_values('trade_date')
                
                # 如果没有财报数据，创建一个空数据模板
                empty_financial_data = self._get_empty_financial_template()
                     
                # 如果没有任何财报数据，将空数据模板放入映射表
                if not financial_data_map:
                    logger.warning(f"股票 {ts_code} 无可用财报数据，使用空数据模板")
                    financial_data_map['empty'] = empty_financial_data
                
                # 按交易日匹配财报
                current_financial_data = None
                current_report_period = None
                
                for idx, row in df_daily.iterrows():
                    trade_date = row['trade_date']
                    
                    # 查找适用于该交易日的财报
                    applicable_financial = None
                    applicable_period = None
                    
                    # 规则：使用披露日期 <= 交易日的最近财报
                    for period, fin_data in financial_data_map.items():
                        if period == 'empty':
                            continue  # 空数据模板跳过匹配逻辑
                        
                        disclosure_date = fin_data.get('_disclosure_date', '99999999')
                        if disclosure_date <= trade_date:
                            # 找到符合条件的财报，选择披露日期最新的
                            if applicable_financial is None or disclosure_date > applicable_financial.get('_disclosure_date', '0'):
                                applicable_financial = fin_data
                                applicable_period = period
                    
                    # 如果没有找到符合条件的财报，使用空数据或当前数据
                    if applicable_financial is None:
                        if current_financial_data is None and 'empty' in financial_data_map:
                            applicable_financial = financial_data_map['empty']
                            applicable_period = 'empty'
                        else:
                            applicable_financial = current_financial_data
                            applicable_period = current_report_period
                    else:
                        # 更新当前财报数据
                        current_financial_data = applicable_financial
                        current_report_period = applicable_period
                    
                    # 使用找到的财报数据
                    low_freq_data = applicable_financial or empty_financial_data
                    
                    # 处理上市日期
                    list_date_value = None
                    if low_freq_data.get('list_date'):
                        try:
                            list_date_value = datetime.strptime(low_freq_data.get('list_date'), '%Y%m%d').date()
                        except ValueError:
                            list_date_value = None
                    
                    # 指标数据匹配
                    indicator_row = indicators_df[indicators_df['trade_date'] == trade_date]
                    indicators = indicator_row.iloc[0].to_dict() if not indicator_row.empty else self._get_empty_indicators()
                    valuation_data = valuation_dict.get(trade_date, {})
                    
                    # 财报更新日期转换（优先使用财报周期，其次使用交易日）
                    update_field = low_freq_data.get(FREQ_LOW_UPDATE_FIELD, low_freq_data.get('_report_period', trade_date))
                    low_freq_update_date = datetime.strptime(update_field, '%Y%m%d').date()

                    # 创建数据库记录
                    stock_detail = StockDetail(
                        # 高频数据
                        ts_code=ts_code,
                        trade_date=datetime.strptime(trade_date, '%Y%m%d').date(),
                        open=self._safe_float(row.get('open')),
                        close=self._safe_float(row.get('close')),
                        high=self._safe_float(row.get('high')),
                        low=self._safe_float(row.get('low')),
                        pct_chg=self._safe_float(row.get('pct_chg')),
                        vol=int(self._safe_float(row.get('vol', 0))),
                        amount=self._safe_float(row.get('amount')),
                        pre_close=self._safe_float(row.get('pre_close')),
                        change=self._safe_float(row.get('change')),
                        # 技术指标
                        volume_ma5=indicators.get('volume_ma5', 0),
                        volume_ma10=indicators.get('volume_ma10', 0),
                        ma5=indicators.get('ma5', 0),
                        ma10=indicators.get('ma10', 0),
                        ma20=indicators.get('ma20', 0),
                        ma60=indicators.get('ma60', 0),
                        macd=indicators.get('macd', 0),
                        macd_signal=indicators.get('macd_signal', 0),
                        macd_hist=indicators.get('macd_hist', 0),
                        rsi6=indicators.get('rsi6', 0),
                        rsi12=indicators.get('rsi12', 0),
                        rsi24=indicators.get('rsi24', 0),
                        boll_upper=indicators.get('boll_upper', 0),
                        boll_middle=indicators.get('boll_middle', 0),
                        boll_lower=indicators.get('boll_lower', 0),
                        # 估值数据
                        pe=self._safe_float(valuation_data.get('pe')),
                        pb=self._safe_float(valuation_data.get('pb')),
                        ps=self._safe_float(valuation_data.get('ps')),
                        total_mv=self._safe_float(valuation_data.get('total_mv')),
                        circ_mv=self._safe_float(valuation_data.get('circ_mv')),
                        total_share=self._safe_float(valuation_data.get('total_share')),
                        float_share=self._safe_float(valuation_data.get('float_share')),
                        dv_ttm=self._safe_float(valuation_data.get('dv_ttm')),
                        # 绑定对应交易日的最新财报数据
                        name=low_freq_data.get('name', ''),
                        industry=low_freq_data.get('industry', ''),
                        area=low_freq_data.get('area', ''),
                        market=low_freq_data.get('market', ''),
                        list_date=list_date_value,
                        eps=low_freq_data.get('eps', 0),
                        bvps=low_freq_data.get('bvps', 0),
                        total_assets=low_freq_data.get('total_assets', 0),
                        total_liab=low_freq_data.get('total_liab', 0),
                        net_profit=low_freq_data.get('net_profit', 0),
                        revenue=low_freq_data.get('revenue', 0),
                        debt_to_assets=low_freq_data.get('debt_to_assets', 0),
                        current_ratio=low_freq_data.get('current_ratio', 0),
                        quick_ratio=low_freq_data.get('quick_ratio', 0),
                        cash_ratio=low_freq_data.get('cash_ratio', 0),
                        revenue_yoy=low_freq_data.get('revenue_yoy', 0),
                        profit_yoy=low_freq_data.get('profit_yoy', 0),
                        low_freq_update_date=low_freq_update_date
                    )
                    self.session.add(stock_detail)
                
                # 提交该股票数据
                self.session.commit()
                results['success'] += 1
                logger.info(f"股票 {ts_code} 全量数据收集完成（共 {len(df_daily)} 条日频记录）")
                
                # 控制请求频率
                if (i + 1) % 100 == 0:
                    time.sleep(2)
                else:
                    time.sleep(0.2)
                    
            except Exception as e:
                logger.error(f"全量收集股票 {ts_code} 失败: {e}", exc_info=True)
                self.session.rollback()
                results['failed'] += 1
                results['failed_codes'].append(ts_code)
        
        logger.info(f"全量数据收集完成：成功 {results['success']}，失败 {results['failed']}")
        return results