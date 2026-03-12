"""
市场数据转换器
MarketIndex → MarketAnalysisData
"""
from typing import List, Optional, Union, Dict, Any
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.transformers.base_transformer import BaseTransformer, TransformerRegistry
from data.schemas.market_schema import (
    MarketAnalysisData, MarketSentiment, MarketTechnicalData, MarketCapitalData, MarketFundFlowData
)
from data.schemas.base_schema import PriceData, IndicatorValue, SupportResistance, ValuationLevel
from data.judgments.technical_judgments import (
    judge_ma_alignment, judge_macd_signal, judge_adx_strength, calc_support_resistance,
    judge_volume_price, analyze_volume_trend
)
from data.judgments.capital_judgments import (
    analyze_capital_flow_structure, judge_margin_trend, judge_market_breadth, judge_north_trading
)
from data.judgments.valuation_judgments import (
    calc_percentile_rank, calc_valuation_data
)
from data.judgments.cycle_judgments import (
    identify_cycle_phase, calc_cycle_strength, judge_market_regime
)
# 导入配置管理器
from agents.agent_config import get_agent_config



@TransformerRegistry.register('market')
class MarketTransformer(BaseTransformer):
    """
    市场数据转换器
    
    将MarketIndex ORM对象或字典转换为MarketAnalysisData
    """
    
    def _get_value(self, data, key: str, default=None):
        """
        统一获取数据值，支持字典和对象两种格式
        
        Args:
            data: 字典或对象
            key: 键名
            default: 默认值
            
        Returns:
            对应的值
        """
        if data is None:
            return default
        
        if isinstance(data, dict):
            return data.get(key, default)
        else:
            return getattr(data, key, default)
    
    def transform(self, data) -> MarketAnalysisData:
        """
        转换单条市场数据
        
        Args:
            data: MarketIndex ORM对象
            
        Returns:
            MarketAnalysisData
        """
        if not self.validate_input(data):
            return self._create_empty_result(data)
        
        price_data = self._extract_price_data(data)
        technical_data = self._extract_technical_data(data)
        capital_data = self._extract_capital_data(data)
        fund_flow_data = self._extract_fund_flow_data(data)
        sentiment = self._extract_sentiment(data)
        
        ma_alignment = judge_ma_alignment(
            ma5=self.safe_float(self._get_value(data, 'ma5')),
            ma10=self.safe_float(self._get_value(data, 'ma10')),
            ma20=self.safe_float(self._get_value(data, 'ma20')),
            ma60=self.safe_float(self._get_value(data, 'ma60')),
            close=self.safe_float(self._get_value(data, 'close'))
        )
        
        macd_signal = judge_macd_signal(
            macd=self.safe_float(self._get_value(data, 'macd')),
            macd_signal=self.safe_float(self._get_value(data, 'macd_signal')),
            macd_hist=self.safe_float(self._get_value(data, 'macd_hist'))
        )
        
        adx_strength = judge_adx_strength(self.safe_float(self._get_value(data, 'adx')))
        
        # 成交量分析（量价关系）
        volume_analysis = judge_volume_price(
            close=self.safe_float(self._get_value(data, 'close')),
            pct_chg=self.safe_float(self._get_value(data, 'pct_chg')),
            vol=self.safe_float(self._get_value(data, 'vol')),
            vol_ma5=self.safe_float(self._get_value(data, 'vol_ma5'))
        )
        
        # 北向资金数据单位转换：数据库存储的是元，判断函数期望亿元
        north_money_total = self._get_value(data, 'north_money_total')
        north_money_total_yi = self.safe_float(north_money_total) / 100000000 if north_money_total else 0
        north_flow = judge_north_trading(north_money_total_yi)
        
        # 两融数据单位转换：数据库存储的是元，判断函数期望亿元
        margin_balance = self._get_value(data, 'margin_balance')
        margin_buy = self._get_value(data, 'margin_buy')
        margin_balance_yi = self.safe_float(margin_balance) / 100000000 if margin_balance else 0
        margin_buy_yi = self.safe_float(margin_buy) / 100000000 if margin_buy else 0
        margin_trend = judge_margin_trend(
            margin_balance=[margin_balance_yi] if margin_balance else [],
            margin_buy=[margin_buy_yi] if margin_buy else []
        )
        
        valuation = calc_valuation_data(
            pe_ttm=self.safe_float(self._get_value(data, 'pe')),
            pb=self.safe_float(self._get_value(data, 'pb')),
            pe_percentile=50.0,
            pb_percentile=50.0
        )
        
        # 资金流向分析：使用新的综合分析函数
        fund_flow_analysis = analyze_capital_flow_structure(
            fund_flow=fund_flow_data,
            total_turnover=self.safe_float(self._get_value(data, 'amount')) * 1000  # 数据库amount单位是千元，转为元
        )
        
        # 市场广度分析（使用完整的情绪指标）
        sentiment_analysis = judge_market_breadth(
            adv_issues=self.safe_int(self._get_value(data, 'adv_issues')),
            dec_issues=self.safe_int(self._get_value(data, 'dec_issues')),
            market_width=self.safe_float(self._get_value(data, 'market_width')),
            ad_line=self.safe_float(self._get_value(data, 'ad_line')),
            turnover_concentration=self.safe_float(self._get_value(data, 'turnover_concentration'))
        )
        sentiment.description = sentiment_analysis.description

        market_state = self._determine_market_state(ma_alignment, macd_signal, adx_strength)
        trend_direction = self._determine_trend_direction(ma_alignment, macd_signal)
        summary = self._generate_summary(market_state, ma_alignment, macd_signal, north_flow)
        
        # 补充：将资金流向和广度分析添加到 summary
        if fund_flow_analysis.description:
            summary += f" 资金面：{fund_flow_analysis.description}。"
        if sentiment_analysis.description:
            summary += f" 情绪面：{sentiment_analysis.description}。"

        return MarketAnalysisData(
            trade_date=str(self._get_value(data, 'trade_date')) if self._get_value(data, 'trade_date') else "",
            ts_code=self.safe_str(self._get_value(data, 'ts_code')),
            price_data=price_data,
            technical_data=technical_data,
            capital_data=capital_data,
            fund_flow_data=fund_flow_data,
            sentiment=sentiment,
            ma_alignment=ma_alignment,
            macd_signal=macd_signal,
            adx_strength=adx_strength,
            support_resistance=None,
            volume_analysis=volume_analysis,
            north_flow=north_flow,
            margin_trend=margin_trend,
            fund_flow_analysis=fund_flow_analysis,
            valuation=valuation,
            market_state=market_state,
            trend_direction=trend_direction,
            summary=summary
        )
    
    def transform_with_history(
        self, 
        current, 
        history: List
    ) -> MarketAnalysisData:
        """
        结合历史数据进行转换
        
        Args:
            current: 当前MarketIndex对象
            history: 历史MarketIndex对象列表（包含技术分析30天+估值分析600天数据）
            
        Returns:
            MarketAnalysisData
        """
        result = self.transform(current)
        
        if history and len(history) >= 5:
            # 技术分析：使用最近20天数据
            highs = [self.safe_float(h.high) for h in history[-20:]]
            lows = [self.safe_float(h.low) for h in history[-20:]]
            closes = [self.safe_float(h.close) for h in history[-20:]]
            
            result.support_resistance = calc_support_resistance(
                highs=highs,
                lows=lows,
                closes=closes,
                current_price=self.safe_float(current.close),
                ma20=self.safe_float(current.ma20),
                ma60=self.safe_float(getattr(current, 'ma60', None))
            )
            
            # 两融趋势：使用最近5天数据
            margin_balances = [self.safe_float(h.margin_balance) / 100000000 for h in history[-5:]]
            margin_buys = [self.safe_float(h.margin_buy) / 100000000 for h in history[-5:]]
            result.margin_trend = judge_margin_trend(margin_balances, margin_buys)
            
            # 北向资金：使用最近10天数据
            north_history = [self.safe_float(h.north_money_total) / 100000000 for h in history[-10:]]
            current_north = self.safe_float(current.north_money_total) / 100000000 if current.north_money_total else 0
            result.north_flow = judge_north_trading(current_north, north_history, lookback_days=10)
            
            # 估值百分位：使用全部历史数据（最多600天）
            # 优先使用 PE_TTM，如果没有则回退到 PE
            pe_ttm_history = [self.safe_float(getattr(h, 'pe_ttm', None)) for h in history if hasattr(h, 'pe_ttm') and self.safe_float(getattr(h, 'pe_ttm', None)) and self.safe_float(getattr(h, 'pe_ttm', None)) > 0]
            pe_history = [self.safe_float(h.pe) for h in history if h.pe and self.safe_float(h.pe) > 0]
            pb_history = [self.safe_float(h.pb) for h in history if h.pb and self.safe_float(h.pb) > 0]
            
            # 优先使用 PE_TTM
            current_pe_ttm = self.safe_float(getattr(current, 'pe_ttm', None))
            current_pe = self.safe_float(current.pe)
            current_pb = self.safe_float(current.pb)
            
            # 如果有 PE_TTM 则使用，否则回退到 PE
            pe_for_valuation = current_pe_ttm if current_pe_ttm and current_pe_ttm > 0 else current_pe
            pe_history_for_valuation = pe_ttm_history if pe_ttm_history and len(pe_ttm_history) >= 100 else pe_history
            
            # 至少需要100个有效数据点才计算百分位
            pe_percentile = 50.0
            pb_percentile = 50.0
            
            if pe_history_for_valuation and len(pe_history_for_valuation) >= 100:
                pe_percentile = calc_percentile_rank(pe_for_valuation, pe_history_for_valuation)
            
            if pb_history and len(pb_history) >= 100:
                pb_percentile = calc_percentile_rank(current_pb, pb_history)
            
            # 获取配置
            config = get_agent_config().get_market_analyst_settings().market_analysis
            
            # 计算估值客观数据（PE、PB百分位 + 格雷厄姆指数）
            result.valuation = calc_valuation_data(
                pe_ttm=pe_for_valuation,
                pb=current_pb,
                pe_percentile=pe_percentile,
                pb_percentile=pb_percentile,
                risk_free_rate=config.valuation.risk_free_rate
            )
            
            # 成交量趋势分析：使用最近10天数据
            volumes = [self.safe_float(h.vol) for h in history[-10:]]
            current_vol = self.safe_float(current.vol)
            result.volume_trend = analyze_volume_trend(volumes, current_vol, lookback=5)
            
            # ========== 周期分析（新增）==========
            
            # 准备价格和成交量数据
            all_prices = [self.safe_float(h.close) for h in history]
            all_volumes = [self.safe_float(h.vol) for h in history]
            
            # 周期阶段识别（需要250天数据）
            if len(all_prices) >= config.cycle.phase_days:
                result.cycle_phase = identify_cycle_phase(
                    prices=all_prices,
                    volumes=all_volumes,
                    lookback=config.cycle.phase_days
                )
            
            # 周期强度计算（需要60天数据）
            if len(all_prices) >= config.cycle.strength_days:
                result.cycle_strength = calc_cycle_strength(
                    prices=all_prices,
                    lookback=config.cycle.strength_days
                )
            
            # 市场状态判断（需要250天数据）
            if len(all_prices) >= config.cycle.regime_days:
                result.market_regime = judge_market_regime(
                    prices=all_prices,
                    volumes=all_volumes,
                    lookback=config.cycle.regime_days
                )

            recent_vols = [self.safe_float(h.vol) for h in history[-5:]]
            if len(recent_vols) == 5 and all(v > 0 for v in recent_vols):
                vol_ma5_computed = sum(recent_vols) / 5
            else:
                vol_ma5_computed = None

            # 获取前一日涨跌幅
            prev_pct_chg = None
            if len(history) >= 1:
                prev = history[-1]
                prev_pct_chg = self.safe_float(prev.pct_chg)

            # 重新调用量价分析函数
            if vol_ma5_computed is not None:
                result.volume_analysis = judge_volume_price(
                    close=self.safe_float(current.close),
                    pct_chg=self.safe_float(current.pct_chg),
                    vol=self.safe_float(current.vol),
                    vol_ma5=vol_ma5_computed,
                    pct_chg_prev=prev_pct_chg
                )
                # 【新增】同步更新 technical_data.vol_ratio
                if result.technical_data:
                    result.technical_data.vol_ratio = self.safe_float(current.vol) / vol_ma5_computed
            
            # ========== 情绪分数计算（复用 calc_percentile_rank 标准化）==========
            # 使用配置的情绪标准化天数
            sentiment_days = config.sentiment.normalization_days
            if len(history) >= sentiment_days:
                sentiment_history = history[-sentiment_days:]
                
                # 提取历史数据
                adv_decline_ratio_history = [self.safe_float(h.adv_decline_ratio) for h in sentiment_history]
                market_width_history = [self.safe_float(h.market_width) for h in sentiment_history]
                ad_line_history = [self.safe_float(h.ad_line) for h in sentiment_history]
                turnover_concentration_history = [self.safe_float(h.turnover_concentration) for h in sentiment_history]
                
                # 当前值
                current_adv_decline_ratio = self.safe_float(current.adv_decline_ratio)
                current_market_width = self.safe_float(current.market_width)
                current_ad_line = self.safe_float(current.ad_line)
                current_turnover_concentration = self.safe_float(current.turnover_concentration)
                
                # 使用 calc_percentile_rank 标准化各因子（结果为0-100）
                # 注意：turnover_concentration 是反向指标（越高越悲观），需要反转
                adv_decline_score = calc_percentile_rank(current_adv_decline_ratio, adv_decline_ratio_history)
                market_width_score = calc_percentile_rank(current_market_width, market_width_history)
                ad_line_score = calc_percentile_rank(current_ad_line, ad_line_history)
                # 成交额集中度反向：高的百分位意味着集中度高（悲观），所以用 100 - percentile
                turnover_score = 100 - calc_percentile_rank(current_turnover_concentration, turnover_concentration_history)
                
                # 获取权重配置
                weights = config.sentiment.weights
                
                # 加权计算综合情绪分数
                sentiment_score = (
                    adv_decline_score * weights.get('adv_decline_ratio', 0.30) +
                    market_width_score * weights.get('market_width', 0.20) +
                    ad_line_score * weights.get('ad_line', 0.20) +
                    turnover_score * weights.get('turnover_concentration', 0.30)
                )
                
                # 更新情绪分数
                if result.sentiment:
                    result.sentiment.sentiment_score = round(sentiment_score, 2)
            # ========== 情绪分数计算结束 ==========
    
        return result
    
    def _extract_price_data(self, data) -> PriceData:
        """提取价格数据 - 支持字典和对象"""
        return PriceData(
            open=self.safe_float(self._get_value(data, 'open')),
            close=self.safe_float(self._get_value(data, 'close')),
            high=self.safe_float(self._get_value(data, 'high')),
            low=self.safe_float(self._get_value(data, 'low')),
            pct_chg=self.safe_float(self._get_value(data, 'pct_chg')),
            vol=self.safe_float(self._get_value(data, 'vol')),
            amount=self.safe_float(self._get_value(data, 'amount')),
            pre_close=self.safe_float(self._get_value(data, 'pre_close'))
        )
    
    def _extract_technical_data(self, data) -> MarketTechnicalData:
        """提取技术指标数据 - 支持字典和对象"""
        vol = self.safe_float(self._get_value(data, 'vol'))
        vol_ma5 = self.safe_float(self._get_value(data, 'vol_ma5'))
        vol_ratio = vol / vol_ma5 if vol_ma5 and vol_ma5 > 0 else 1.0
        
        return MarketTechnicalData(
            ma5=self.safe_float(self._get_value(data, 'ma5')),
            ma10=self.safe_float(self._get_value(data, 'ma10')),
            ma20=self.safe_float(self._get_value(data, 'ma20')),
            ma60=self.safe_float(self._get_value(data, 'ma60')),
            macd=self.safe_float(self._get_value(data, 'macd')),
            macd_signal=self.safe_float(self._get_value(data, 'macd_signal')),
            macd_hist=self.safe_float(self._get_value(data, 'macd_hist')),
            adx=self.safe_float(self._get_value(data, 'adx')),
            vol=vol,
            vol_ma5=vol_ma5 if vol_ma5 else 0.0,
            vol_ratio=vol_ratio
        )
    
    def _extract_capital_data(self, data) -> MarketCapitalData:
        """提取资金数据 - 支持字典和对象"""
        return MarketCapitalData(
            north_money_total=self.safe_float(self._get_value(data, 'north_money_total')),
            margin_balance=self.safe_float(self._get_value(data, 'margin_balance')),
            margin_buy=self.safe_float(self._get_value(data, 'margin_buy')),
            short_balance=self.safe_float(self._get_value(data, 'short_balance'))
        )
    
    def _extract_sentiment(self, data) -> MarketSentiment:
        """提取市场情绪数据 - 支持字典和对象"""
        adv_issues = self.safe_int(self._get_value(data, 'adv_issues'))
        dec_issues = self.safe_int(self._get_value(data, 'dec_issues'))
        
        # 优先使用数据库中的涨跌比（adv_decline_ratio），否则回退计算
        adv_decline_ratio = self.safe_float(self._get_value(data, 'adv_decline_ratio'))
        if adv_decline_ratio and adv_decline_ratio > 0:
            # adv_decline_ratio 是小数形式（如0.6表示60%），转换为0-100分
            sentiment_score = adv_decline_ratio * 100
        else:
            # 回退计算
            if adv_issues and dec_issues and (adv_issues + dec_issues) > 0:
                sentiment_score = adv_issues / (adv_issues + dec_issues) * 100
            else:
                sentiment_score = 50.0
        
        return MarketSentiment(
            adv_issues=adv_issues,
            dec_issues=dec_issues,
            adv_decline_ratio=adv_decline_ratio,
            market_width=self.safe_float(self._get_value(data, 'market_width')),
            ad_line=self.safe_float(self._get_value(data, 'ad_line')),
            turnover_concentration=self.safe_float(self._get_value(data, 'turnover_concentration')),
            sentiment_score=sentiment_score
        )
    
    def _extract_fund_flow_data(self, data) -> MarketFundFlowData:
        """提取资金流向数据 - 支持字典和对象"""
        return MarketFundFlowData(
            net_amount=self.safe_float(self._get_value(data, 'net_amount')),
            net_amount_rate=self.safe_float(self._get_value(data, 'net_amount_rate')),
            buy_elg_amount=self.safe_float(self._get_value(data, 'buy_elg_amount')),
            buy_elg_amount_rate=self.safe_float(self._get_value(data, 'buy_elg_amount_rate')),
            buy_lg_amount=self.safe_float(self._get_value(data, 'buy_lg_amount')),
            buy_lg_amount_rate=self.safe_float(self._get_value(data, 'buy_lg_amount_rate')),
            buy_md_amount=self.safe_float(self._get_value(data, 'buy_md_amount')),
            buy_md_amount_rate=self.safe_float(self._get_value(data, 'buy_md_amount_rate')),
            buy_sm_amount=self.safe_float(self._get_value(data, 'buy_sm_amount')),
            buy_sm_amount_rate=self.safe_float(self._get_value(data, 'buy_sm_amount_rate'))
        )
    
    def _determine_market_state(
        self, 
        ma_alignment: IndicatorValue, 
        macd_signal: IndicatorValue,
        adx_strength: IndicatorValue
    ) -> str:
        """判断市场状态"""
        bullish_count = 0
        bearish_count = 0
        
        if ma_alignment and ma_alignment.signal == 'BULLISH':
            bullish_count += 1
        elif ma_alignment and ma_alignment.signal == 'BEARISH':
            bearish_count += 1
        
        if macd_signal and macd_signal.signal == 'BULLISH':
            bullish_count += 1
        elif macd_signal and macd_signal.signal == 'BEARISH':
            bearish_count += 1
        
        if bullish_count >= 2:
            return 'BULLISH'
        elif bearish_count >= 2:
            return 'BEARISH'
        else:
            return 'NEUTRAL'
    
    def _determine_trend_direction(
        self,
        ma_alignment: IndicatorValue,
        macd_signal: IndicatorValue
    ) -> str:
        """判断趋势方向"""
        if ma_alignment and ma_alignment.signal == 'BULLISH':
            return 'UP'
        elif ma_alignment and ma_alignment.signal == 'BEARISH':
            return 'DOWN'
        else:
            return 'SIDEWAYS'
    
    def _generate_summary(
        self,
        market_state: str,
        ma_alignment: IndicatorValue,
        macd_signal: IndicatorValue,
        north_flow: IndicatorValue
    ) -> str:
        """生成市场摘要"""
        state_desc_map = {
            'BULLISH': '市场偏多',
            'BEARISH': '市场偏空',
            'NEUTRAL': '市场震荡'
        }
        
        parts = [state_desc_map.get(market_state, '市场状态不明')]
        
        if ma_alignment:
            parts.append(f"均线{ma_alignment.description}")
        if macd_signal:
            parts.append(f"MACD{macd_signal.description}")
        if north_flow:
            parts.append(f"北向资金{north_flow.description}")
        
        return "；".join(parts)
    
    def _create_empty_result(self, data) -> MarketAnalysisData:
        """创建空结果 - 支持字典和对象"""
        return MarketAnalysisData(
            trade_date=str(self._get_value(data, 'trade_date')) if data and self._get_value(data, 'trade_date') else "",
            ts_code=self.safe_str(self._get_value(data, 'ts_code'), '')
        )
