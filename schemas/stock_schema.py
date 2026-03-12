"""
个股分析数据结构
对应数据库表：StockDetail
用于个股分析团队的输入数据

分析Agent使用的数据：
- 技术面分析师：MA、MACD、RSI、布林带等
- 基本面分析师：PE、PB、EPS、ROE、财务指标等
- 所属板块分析师：industry字段
- 新闻情绪分析师：需配合StockNews表（单独查询）
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.schemas.base_schema import (
    BaseSchema, PriceData, IndicatorValue, SupportResistance, ValuationLevel
)


@dataclass
class TechnicalIndicators:
    """技术指标原始值"""
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    
    rsi6: float = 0.0
    rsi12: float = 0.0
    rsi24: float = 0.0
    
    boll_upper: float = 0.0
    boll_middle: float = 0.0
    boll_lower: float = 0.0
    
    volume_ma5: float = 0.0
    volume_ma10: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'ma5': self.ma5,
            'ma10': self.ma10,
            'ma20': self.ma20,
            'ma60': self.ma60,
            'macd': self.macd,
            'macd_signal': self.macd_signal,
            'macd_hist': self.macd_hist,
            'rsi6': self.rsi6,
            'rsi12': self.rsi12,
            'rsi24': self.rsi24,
            'boll_upper': self.boll_upper,
            'boll_middle': self.boll_middle,
            'boll_lower': self.boll_lower,
            'volume_ma5': self.volume_ma5,
            'volume_ma10': self.volume_ma10
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TechnicalIndicators':
        return cls(
            ma5=data.get('ma5', 0.0),
            ma10=data.get('ma10', 0.0),
            ma20=data.get('ma20', 0.0),
            ma60=data.get('ma60', 0.0),
            macd=data.get('macd', 0.0),
            macd_signal=data.get('macd_signal', 0.0),
            macd_hist=data.get('macd_hist', 0.0),
            rsi6=data.get('rsi6', 0.0),
            rsi12=data.get('rsi12', 0.0),
            rsi24=data.get('rsi24', 0.0),
            boll_upper=data.get('boll_upper', 0.0),
            boll_middle=data.get('boll_middle', 0.0),
            boll_lower=data.get('boll_lower', 0.0),
            volume_ma5=data.get('volume_ma5', 0.0),
            volume_ma10=data.get('volume_ma10', 0.0)
        )


@dataclass
class StockFundamentals:
    """基本面数据"""
    industry: str = ""
    area: str = ""
    market: str = ""
    list_date: str = ""
    
    eps: float = 0.0
    bvps: float = 0.0
    total_assets: float = 0.0
    total_liab: float = 0.0
    net_profit: float = 0.0
    revenue: float = 0.0
    
    debt_to_assets: float = 0.0
    current_ratio: float = 0.0
    quick_ratio: float = 0.0
    
    revenue_yoy: float = 0.0
    profit_yoy: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'industry': self.industry,
            'area': self.area,
            'market': self.market,
            'list_date': self.list_date,
            'eps': self.eps,
            'bvps': self.bvps,
            'total_assets': self.total_assets,
            'total_liab': self.total_liab,
            'net_profit': self.net_profit,
            'revenue': self.revenue,
            'debt_to_assets': self.debt_to_assets,
            'current_ratio': self.current_ratio,
            'quick_ratio': self.quick_ratio,
            'revenue_yoy': self.revenue_yoy,
            'profit_yoy': self.profit_yoy
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StockFundamentals':
        return cls(
            industry=data.get('industry', ''),
            area=data.get('area', ''),
            market=data.get('market', ''),
            list_date=data.get('list_date', ''),
            eps=data.get('eps', 0.0),
            bvps=data.get('bvps', 0.0),
            total_assets=data.get('total_assets', 0.0),
            total_liab=data.get('total_liab', 0.0),
            net_profit=data.get('net_profit', 0.0),
            revenue=data.get('revenue', 0.0),
            debt_to_assets=data.get('debt_to_assets', 0.0),
            current_ratio=data.get('current_ratio', 0.0),
            quick_ratio=data.get('quick_ratio', 0.0),
            revenue_yoy=data.get('revenue_yoy', 0.0),
            profit_yoy=data.get('profit_yoy', 0.0)
        )


@dataclass
class StockValuation:
    """估值数据"""
    pe: float = 0.0
    pb: float = 0.0
    ps: float = 0.0
    dv_ttm: float = 0.0
    
    total_mv: float = 0.0
    circ_mv: float = 0.0
    total_share: float = 0.0
    float_share: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'pe': self.pe,
            'pb': self.pb,
            'ps': self.ps,
            'dv_ttm': self.dv_ttm,
            'total_mv': self.total_mv,
            'circ_mv': self.circ_mv,
            'total_share': self.total_share,
            'float_share': self.float_share
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StockValuation':
        return cls(
            pe=data.get('pe', 0.0),
            pb=data.get('pb', 0.0),
            ps=data.get('ps', 0.0),
            dv_ttm=data.get('dv_ttm', 0.0),
            total_mv=data.get('total_mv', 0.0),
            circ_mv=data.get('circ_mv', 0.0),
            total_share=data.get('total_share', 0.0),
            float_share=data.get('float_share', 0.0)
        )


@dataclass
class StockAnalysisData(BaseSchema):
    """
    个股分析数据结构
    对应数据库表：StockDetail
    
    用于个股分析团队的输入数据
    """
    ts_code: str = ""
    name: str = ""
    
    price_data: PriceData = None
    technical_indicators: TechnicalIndicators = None
    fundamentals: StockFundamentals = None
    valuation: StockValuation = None
    
    ma_alignment: IndicatorValue = None
    macd_signal: IndicatorValue = None
    rsi_signal: IndicatorValue = None
    boll_position: IndicatorValue = None
    support_resistance: SupportResistance = None
    
    volume_price: IndicatorValue = None
    
    valuation_level: ValuationLevel = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.price_data:
            result['price_data'] = self.price_data.to_dict()
        if self.technical_indicators:
            result['technical_indicators'] = self.technical_indicators.to_dict()
        if self.fundamentals:
            result['fundamentals'] = self.fundamentals.to_dict()
        if self.valuation:
            result['valuation'] = self.valuation.to_dict()
        if self.ma_alignment:
            result['ma_alignment'] = self.ma_alignment.to_dict()
        if self.macd_signal:
            result['macd_signal'] = self.macd_signal.to_dict()
        if self.rsi_signal:
            result['rsi_signal'] = self.rsi_signal.to_dict()
        if self.boll_position:
            result['boll_position'] = self.boll_position.to_dict()
        if self.support_resistance:
            result['support_resistance'] = self.support_resistance.to_dict()
        if self.volume_price:
            result['volume_price'] = self.volume_price.to_dict()
        if self.valuation_level:
            result['valuation_level'] = self.valuation_level.to_dict()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StockAnalysisData':
        price_data = PriceData.from_dict(data['price_data']) if data.get('price_data') else None
        technical_indicators = TechnicalIndicators.from_dict(data['technical_indicators']) if data.get('technical_indicators') else None
        fundamentals = StockFundamentals.from_dict(data['fundamentals']) if data.get('fundamentals') else None
        valuation = StockValuation.from_dict(data['valuation']) if data.get('valuation') else None
        ma_alignment = IndicatorValue.from_dict(data['ma_alignment']) if data.get('ma_alignment') else None
        macd_signal = IndicatorValue.from_dict(data['macd_signal']) if data.get('macd_signal') else None
        rsi_signal = IndicatorValue.from_dict(data['rsi_signal']) if data.get('rsi_signal') else None
        boll_position = IndicatorValue.from_dict(data['boll_position']) if data.get('boll_position') else None
        support_resistance = SupportResistance.from_dict(data['support_resistance']) if data.get('support_resistance') else None
        volume_price = IndicatorValue.from_dict(data['volume_price']) if data.get('volume_price') else None
        valuation_level = ValuationLevel.from_dict(data['valuation_level']) if data.get('valuation_level') else None
        
        return cls(
            trade_date=data['trade_date'],
            ts_code=data.get('ts_code', ''),
            name=data.get('name', ''),
            price_data=price_data,
            technical_indicators=technical_indicators,
            fundamentals=fundamentals,
            valuation=valuation,
            ma_alignment=ma_alignment,
            macd_signal=macd_signal,
            rsi_signal=rsi_signal,
            boll_position=boll_position,
            support_resistance=support_resistance,
            volume_price=volume_price,
            valuation_level=valuation_level
        )


@dataclass
class TechnicalReport:
    """技术面分析报告"""
    ts_code: str
    trend_analysis: str
    ma_status: str
    macd_signal: str
    support_resistance: Dict[str, List[float]]
    volume_price: str
    technical_score: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'ts_code': self.ts_code,
            'trend_analysis': self.trend_analysis,
            'ma_status': self.ma_status,
            'macd_signal': self.macd_signal,
            'support_resistance': self.support_resistance,
            'volume_price': self.volume_price,
            'technical_score': self.technical_score
        }


@dataclass
class FundamentalReport:
    """基本面分析报告"""
    ts_code: str
    valuation_level: str
    profit_growth: str
    financial_health: str
    industry_position: str
    fundamental_score: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'ts_code': self.ts_code,
            'valuation_level': self.valuation_level,
            'profit_growth': self.profit_growth,
            'financial_health': self.financial_health,
            'industry_position': self.industry_position,
            'fundamental_score': self.fundamental_score
        }


@dataclass
class SectorBelongReport:
    """所属板块分析报告"""
    ts_code: str
    main_sector: str
    sector_trend: str
    sector_rank: int
    sector_correlation: float
    sector_impact: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'ts_code': self.ts_code,
            'main_sector': self.main_sector,
            'sector_trend': self.sector_trend,
            'sector_rank': self.sector_rank,
            'sector_correlation': self.sector_correlation,
            'sector_impact': self.sector_impact
        }


@dataclass
class NewsSentimentReport:
    """新闻情绪分析报告"""
    ts_code: str
    recent_news: List[str]
    sentiment_score: float
    key_events: List[str]
    risk_alerts: List[str]
    opportunity_signals: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'ts_code': self.ts_code,
            'recent_news': self.recent_news,
            'sentiment_score': self.sentiment_score,
            'key_events': self.key_events,
            'risk_alerts': self.risk_alerts,
            'opportunity_signals': self.opportunity_signals
        }
