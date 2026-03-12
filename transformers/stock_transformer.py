"""
个股数据转换器
StockDetail → StockAnalysisData

只使用StockDetail表，不依赖StockFactor表。
StockFactor是选股流程的输出，不用于分析流程。
"""
from typing import List, Optional
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.transformers.base_transformer import BaseTransformer, TransformerRegistry
from data.schemas.stock_schema import (
    StockAnalysisData, TechnicalIndicators, StockFundamentals, StockValuation
)
from data.schemas.base_schema import PriceData, IndicatorValue, SupportResistance, ValuationLevel
from data.judgments.technical_judgments import (
    judge_ma_alignment, judge_macd_signal, judge_rsi_signal, 
    judge_boll_position, calc_support_resistance, judge_volume_price
)
from data.judgments.valuation_judgments import calc_valuation_data


@TransformerRegistry.register('stock')
class StockTransformer(BaseTransformer):
    """
    个股数据转换器
    
    将StockDetail ORM对象转换为StockAnalysisData
    """
    
    def transform(self, data) -> StockAnalysisData:
        """
        转换单条个股数据
        
        Args:
            data: StockDetail ORM对象
            
        Returns:
            StockAnalysisData
        """
        if not self.validate_input(data):
            return self._create_empty_result(data)
        
        price_data = self._extract_price_data(data)
        technical_indicators = self._extract_technical_indicators(data)
        fundamentals = self._extract_fundamentals(data)
        valuation = self._extract_valuation(data)
        
        ma_alignment = judge_ma_alignment(
            ma5=self.safe_float(data.ma5),
            ma10=self.safe_float(data.ma10),
            ma20=self.safe_float(data.ma20),
            ma60=self.safe_float(data.ma60),
            close=self.safe_float(data.close)
        )
        
        macd_signal = judge_macd_signal(
            macd=self.safe_float(data.macd),
            macd_signal=self.safe_float(data.macd_signal),
            macd_hist=self.safe_float(data.macd_hist)
        )
        
        rsi_signal = judge_rsi_signal(self.safe_float(data.rsi6))
        
        boll_position = judge_boll_position(
            close=self.safe_float(data.close),
            boll_upper=self.safe_float(data.boll_upper),
            boll_middle=self.safe_float(data.boll_middle),
            boll_lower=self.safe_float(data.boll_lower)
        )
        
        volume_price = judge_volume_price(
            close=self.safe_float(data.close),
            pct_chg=self.safe_float(data.pct_chg),
            vol=self.safe_float(data.vol),
            vol_ma5=self.safe_float(data.volume_ma5)
        )
        
        valuation_level = calc_valuation_data(
            pe_ttm=self.safe_float(data.pe),
            pb=self.safe_float(data.pb),
            pe_percentile=50.0,
            pb_percentile=50.0
        )
        
        return StockAnalysisData(
            trade_date=str(data.trade_date) if data.trade_date else "",
            ts_code=self.safe_str(data.ts_code),
            name=self.safe_str(data.name),
            price_data=price_data,
            technical_indicators=technical_indicators,
            fundamentals=fundamentals,
            valuation=valuation,
            ma_alignment=ma_alignment,
            macd_signal=macd_signal,
            rsi_signal=rsi_signal,
            boll_position=boll_position,
            support_resistance=None,
            volume_price=volume_price,
            valuation_level=valuation_level
        )
    
    def transform_with_history(
        self, 
        current, 
        history: List
    ) -> StockAnalysisData:
        """
        结合历史数据进行转换
        
        Args:
            current: 当前StockDetail对象
            history: 历史StockDetail对象列表
            
        Returns:
            StockAnalysisData
        """
        result = self.transform(current)
        
        if history and len(history) >= 5:
            highs = [self.safe_float(h.high) for h in history[-20:]]
            lows = [self.safe_float(h.low) for h in history[-20:]]
            closes = [self.safe_float(h.close) for h in history[-20:]]
            
            result.support_resistance = calc_support_resistance(
                highs=highs,
                lows=lows,
                closes=closes,
                current_price=self.safe_float(current.close),
                ma20=self.safe_float(current.ma20),
                ma60=self.safe_float(current.ma60)
            )
        
        return result
    
    def _extract_price_data(self, data) -> PriceData:
        """提取价格数据"""
        return PriceData(
            open=self.safe_float(data.open),
            close=self.safe_float(data.close),
            high=self.safe_float(data.high),
            low=self.safe_float(data.low),
            pct_chg=self.safe_float(data.pct_chg),
            vol=self.safe_float(data.vol),
            amount=self.safe_float(data.amount),
            pre_close=self.safe_float(data.pre_close)
        )
    
    def _extract_technical_indicators(self, data) -> TechnicalIndicators:
        """提取技术指标数据"""
        return TechnicalIndicators(
            ma5=self.safe_float(data.ma5),
            ma10=self.safe_float(data.ma10),
            ma20=self.safe_float(data.ma20),
            ma60=self.safe_float(data.ma60),
            macd=self.safe_float(data.macd),
            macd_signal=self.safe_float(data.macd_signal),
            macd_hist=self.safe_float(data.macd_hist),
            rsi6=self.safe_float(data.rsi6),
            rsi12=self.safe_float(data.rsi12),
            rsi24=self.safe_float(data.rsi24),
            boll_upper=self.safe_float(data.boll_upper),
            boll_middle=self.safe_float(data.boll_middle),
            boll_lower=self.safe_float(data.boll_lower),
            volume_ma5=self.safe_float(data.volume_ma5),
            volume_ma10=self.safe_float(data.volume_ma10)
        )
    
    def _extract_fundamentals(self, data) -> StockFundamentals:
        """提取基本面数据"""
        list_date = ""
        if data.list_date:
            list_date = str(data.list_date)
        
        return StockFundamentals(
            industry=self.safe_str(data.industry),
            area=self.safe_str(data.area),
            market=self.safe_str(data.market),
            list_date=list_date,
            eps=self.safe_float(data.eps),
            bvps=self.safe_float(data.bvps),
            total_assets=self.safe_float(data.total_assets),
            total_liab=self.safe_float(data.total_liab),
            net_profit=self.safe_float(data.net_profit),
            revenue=self.safe_float(data.revenue),
            debt_to_assets=self.safe_float(data.debt_to_assets),
            current_ratio=self.safe_float(data.current_ratio),
            quick_ratio=self.safe_float(data.quick_ratio),
            revenue_yoy=self.safe_float(data.revenue_yoy),
            profit_yoy=self.safe_float(data.profit_yoy)
        )
    
    def _extract_valuation(self, data) -> StockValuation:
        """提取估值数据"""
        return StockValuation(
            pe=self.safe_float(data.pe),
            pb=self.safe_float(data.pb),
            ps=self.safe_float(data.ps),
            dv_ttm=self.safe_float(data.dv_ttm),
            total_mv=self.safe_float(data.total_mv),
            circ_mv=self.safe_float(data.circ_mv),
            total_share=self.safe_float(data.total_share),
            float_share=self.safe_float(data.float_share)
        )
    
    def _create_empty_result(self, data) -> StockAnalysisData:
        """创建空结果"""
        return StockAnalysisData(
            trade_date=str(data.trade_date) if data and data.trade_date else "",
            ts_code=self.safe_str(getattr(data, 'ts_code', None), ''),
            name=self.safe_str(getattr(data, 'name', None), '')
        )
    
    def calc_technical_score(self, data: StockAnalysisData) -> float:
        """
        计算技术面综合评分
        
        Args:
            data: StockAnalysisData对象
            
        Returns:
            技术面评分 (0-100)
        """
        score = 50.0
        
        if data.ma_alignment:
            if data.ma_alignment.signal == 'BULLISH':
                score += 15
            elif data.ma_alignment.signal == 'BEARISH':
                score -= 15
        
        if data.macd_signal:
            if data.macd_signal.signal == 'BULLISH':
                score += 10
            elif data.macd_signal.signal == 'BEARISH':
                score -= 10
        
        if data.rsi_signal:
            if data.rsi_signal.signal == 'BULLISH':
                score += 5
            elif data.rsi_signal.signal == 'BEARISH':
                score -= 5
        
        if data.boll_position:
            if data.boll_position.signal == 'BULLISH':
                score += 5
            elif data.boll_position.signal == 'BEARISH':
                score -= 5
        
        if data.volume_price:
            if data.volume_price.signal == 'BULLISH':
                score += 10
            elif data.volume_price.signal == 'BEARISH':
                score -= 10
        
        return max(0, min(100, score))
    
    def calc_fundamental_score(self, data: StockAnalysisData) -> float:
        """
        计算基本面综合评分
        
        Args:
            data: StockAnalysisData对象
            
        Returns:
            基本面评分 (0-100)
        """
        score = 50.0
        
        if data.fundamentals:
            if data.fundamentals.revenue_yoy and data.fundamentals.revenue_yoy > 20:
                score += 10
            elif data.fundamentals.revenue_yoy and data.fundamentals.revenue_yoy < -10:
                score -= 10
            
            if data.fundamentals.profit_yoy and data.fundamentals.profit_yoy > 20:
                score += 10
            elif data.fundamentals.profit_yoy and data.fundamentals.profit_yoy < -10:
                score -= 10
            
            if data.fundamentals.debt_to_assets and data.fundamentals.debt_to_assets < 40:
                score += 5
            elif data.fundamentals.debt_to_assets and data.fundamentals.debt_to_assets > 70:
                score -= 10
        
        if data.valuation_level:
            # 使用PE百分位判断估值（低于30%为低估，高于70%为高估）
            if data.valuation_level.pe_percentile < 30:
                score += 10
            elif data.valuation_level.pe_percentile > 70:
                score -= 5
        
        return max(0, min(100, score))
