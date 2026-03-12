"""
市场分析数据结构

包含两类数据结构：
1. 输入数据结构（从数据库转换后的中间数据）
2. 输出数据结构（LLM分析结果）

对应数据库表：MarketIndex
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.schemas.base_schema import (
    BaseSchema, PriceData, IndicatorValue, SupportResistance, ValuationLevel
)


MARKET_STATE_CN = {
    'STRONG': '强势',
    'SHOCK': '震荡',
    'WEAK': '弱势'
}

TREND_DIRECTION_CN = {
    'UP': '上涨',
    'SIDEWAYS': '横盘',
    'DOWN': '下跌'
}

VALUATION_LEVEL_CN = {
    'LOW': '低估',
    'MEDIUM': '合理',
    'HIGH': '高估'
}

CYCLE_PHASE_CN = {
    'ACCUMULATION': '筑底',
    'RISING': '上涨',
    'DISTRIBUTION': '筑顶',
    'FALLING': '下跌',
    'SHOCK': '震荡'
}

RISK_LEVEL_CN = {
    'LOW': '低风险',
    'MEDIUM': '中等风险',
    'HIGH': '高风险'
}


@dataclass
class MarketSentiment:
    """市场情绪数据（输入数据结构）"""
    adv_issues: int = 0
    dec_issues: int = 0
    adv_decline_ratio: float = 0.0
    market_width: float = 0.0
    ad_line: float = 0.0
    turnover_concentration: float = 0.0
    sentiment_score: float = 50.0
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'adv_issues': self.adv_issues,
            'dec_issues': self.dec_issues,
            'adv_decline_ratio': self.adv_decline_ratio,
            'market_width': self.market_width,
            'ad_line': self.ad_line,
            'turnover_concentration': self.turnover_concentration,
            'sentiment_score': self.sentiment_score,
            'description': self.description
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MarketSentiment':
        return cls(
            adv_issues=data.get('adv_issues', 0),
            dec_issues=data.get('dec_issues', 0),
            adv_decline_ratio=data.get('adv_decline_ratio', 0.0),
            market_width=data.get('market_width', 0.0),
            ad_line=data.get('ad_line', 0.0),
            turnover_concentration=data.get('turnover_concentration', 0.0),
            sentiment_score=data.get('sentiment_score', 50.0),
            description=data.get('description', "")
        )


@dataclass
class MarketTechnicalData:
    """市场技术指标数据（输入数据结构）"""
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    adx: float = 0.0
    # 成交量相关字段
    vol: float = 0.0           # 当日成交量
    vol_ma5: float = 0.0       # 5日均量
    vol_ratio: float = 1.0     # 量比
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'ma5': self.ma5,
            'ma10': self.ma10,
            'ma20': self.ma20,
            'ma60': self.ma60,
            'macd': self.macd,
            'macd_signal': self.macd_signal,
            'macd_hist': self.macd_hist,
            'adx': self.adx,
            'vol': self.vol,
            'vol_ma5': self.vol_ma5,
            'vol_ratio': self.vol_ratio
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MarketTechnicalData':
        return cls(
            ma5=data.get('ma5', 0.0),
            ma10=data.get('ma10', 0.0),
            ma20=data.get('ma20', 0.0),
            ma60=data.get('ma60', 0.0),
            macd=data.get('macd', 0.0),
            macd_signal=data.get('macd_signal', 0.0),
            macd_hist=data.get('macd_hist', 0.0),
            adx=data.get('adx', 0.0),
            vol=data.get('vol', 0.0),
            vol_ma5=data.get('vol_ma5', 0.0),
            vol_ratio=data.get('vol_ratio', 1.0)
        )


@dataclass
class MarketCapitalData:
    """市场资金数据（输入数据结构）"""
    north_money_total: float = 0.0
    margin_balance: float = 0.0
    margin_buy: float = 0.0
    short_balance: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'north_money_total': self.north_money_total,
            'margin_balance': self.margin_balance,
            'margin_buy': self.margin_buy,
            'short_balance': self.short_balance
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MarketCapitalData':
        return cls(
            north_money_total=data.get('north_money_total', 0.0),
            margin_balance=data.get('margin_balance', 0.0),
            margin_buy=data.get('margin_buy', 0.0),
            short_balance=data.get('short_balance', 0.0)
        )


@dataclass
class MarketFundFlowData:
    """市场资金流向数据（输入数据结构）"""
    net_amount: float = 0.0
    net_amount_rate: float = 0.0
    buy_elg_amount: float = 0.0
    buy_elg_amount_rate: float = 0.0
    buy_lg_amount: float = 0.0
    buy_lg_amount_rate: float = 0.0
    buy_md_amount: float = 0.0
    buy_md_amount_rate: float = 0.0
    buy_sm_amount: float = 0.0
    buy_sm_amount_rate: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'net_amount': self.net_amount,
            'net_amount_rate': self.net_amount_rate,
            'buy_elg_amount': self.buy_elg_amount,
            'buy_elg_amount_rate': self.buy_elg_amount_rate,
            'buy_lg_amount': self.buy_lg_amount,
            'buy_lg_amount_rate': self.buy_lg_amount_rate,
            'buy_md_amount': self.buy_md_amount,
            'buy_md_amount_rate': self.buy_md_amount_rate,
            'buy_sm_amount': self.buy_sm_amount,
            'buy_sm_amount_rate': self.buy_sm_amount_rate
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MarketFundFlowData':
        return cls(
            net_amount=data.get('net_amount', 0.0),
            net_amount_rate=data.get('net_amount_rate', 0.0),
            buy_elg_amount=data.get('buy_elg_amount', 0.0),
            buy_elg_amount_rate=data.get('buy_elg_amount_rate', 0.0),
            buy_lg_amount=data.get('buy_lg_amount', 0.0),
            buy_lg_amount_rate=data.get('buy_lg_amount_rate', 0.0),
            buy_md_amount=data.get('buy_md_amount', 0.0),
            buy_md_amount_rate=data.get('buy_md_amount_rate', 0.0),
            buy_sm_amount=data.get('buy_sm_amount', 0.0),
            buy_sm_amount_rate=data.get('buy_sm_amount_rate', 0.0)
        )


@dataclass
class MarketAnalysisData(BaseSchema):
    """
    市场分析数据结构（输入数据结构）
    对应数据库表：MarketIndex
    
    用于MarketAnalyst的输入数据
    """
    ts_code: str = ""
    
    price_data: PriceData = None
    technical_data: MarketTechnicalData = None
    capital_data: MarketCapitalData = None
    fund_flow_data: MarketFundFlowData = None
    sentiment: MarketSentiment = None
    
    ma_alignment: IndicatorValue = None
    macd_signal: IndicatorValue = None
    adx_strength: IndicatorValue = None
    support_resistance: SupportResistance = None
    
    # 成交量分析结果
    volume_analysis: IndicatorValue = None   # 量价关系分析
    volume_trend: IndicatorValue = None      # 成交量趋势分析
    
    north_flow: IndicatorValue = None
    margin_trend: IndicatorValue = None
    fund_flow_analysis: IndicatorValue = None
    
    valuation: ValuationLevel = None
    
    # 周期分析字段
    cycle_phase: str = "SHOCK"                    # 周期阶段: ACCUMULATION/RISING/DISTRIBUTION/FALLING/SHOCK
    cycle_strength: float = 0.0                   # 周期强度 (0-100)
    market_regime: IndicatorValue = None          # 市场状态描述
    
    market_state: str = "NEUTRAL"
    trend_direction: str = "SIDEWAYS"
    summary: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.price_data:
            result['price_data'] = self.price_data.to_dict()
        if self.technical_data:
            result['technical_data'] = self.technical_data.to_dict()
        if self.capital_data:
            result['capital_data'] = self.capital_data.to_dict()
        if self.sentiment:
            result['sentiment'] = self.sentiment.to_dict()
        if self.fund_flow_data:
            result['fund_flow_data'] = self.fund_flow_data.to_dict()
        if self.ma_alignment:
            result['ma_alignment'] = self.ma_alignment.to_dict()
        if self.macd_signal:
            result['macd_signal'] = self.macd_signal.to_dict()
        if self.adx_strength:
            result['adx_strength'] = self.adx_strength.to_dict()
        if self.support_resistance:
            result['support_resistance'] = self.support_resistance.to_dict()
        if self.volume_analysis:
            result['volume_analysis'] = self.volume_analysis.to_dict()
        if self.volume_trend:
            result['volume_trend'] = self.volume_trend.to_dict()
        if self.north_flow:
            result['north_flow'] = self.north_flow.to_dict()
        if self.margin_trend:
            result['margin_trend'] = self.margin_trend.to_dict()
        if self.fund_flow_analysis:
            result['fund_flow_analysis'] = self.fund_flow_analysis.to_dict()
        if self.valuation:
            result['valuation'] = self.valuation.to_dict()
        if self.market_regime:
            result['market_regime'] = self.market_regime.to_dict()
        result['cycle_phase'] = self.cycle_phase
        result['cycle_strength'] = self.cycle_strength
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MarketAnalysisData':
        price_data = PriceData.from_dict(data['price_data']) if data.get('price_data') else None
        technical_data = MarketTechnicalData.from_dict(data['technical_data']) if data.get('technical_data') else None
        capital_data = MarketCapitalData.from_dict(data['capital_data']) if data.get('capital_data') else None
        sentiment = MarketSentiment.from_dict(data['sentiment']) if data.get('sentiment') else None
        ma_alignment = IndicatorValue.from_dict(data['ma_alignment']) if data.get('ma_alignment') else None
        macd_signal = IndicatorValue.from_dict(data['macd_signal']) if data.get('macd_signal') else None
        adx_strength = IndicatorValue.from_dict(data['adx_strength']) if data.get('adx_strength') else None
        support_resistance = SupportResistance.from_dict(data['support_resistance']) if data.get('support_resistance') else None
        volume_analysis = IndicatorValue.from_dict(data['volume_analysis']) if data.get('volume_analysis') else None
        volume_trend = IndicatorValue.from_dict(data['volume_trend']) if data.get('volume_trend') else None
        north_flow = IndicatorValue.from_dict(data['north_flow']) if data.get('north_flow') else None
        margin_trend = IndicatorValue.from_dict(data['margin_trend']) if data.get('margin_trend') else None
        fund_flow_analysis = IndicatorValue.from_dict(data['fund_flow_analysis']) if data.get('fund_flow_analysis') else None
        valuation = ValuationLevel.from_dict(data['valuation']) if data.get('valuation') else None
        
        return cls(
            trade_date=data['trade_date'],
            ts_code=data.get('ts_code', ''),
            price_data=price_data,
            technical_data=technical_data,
            capital_data=capital_data,
            fund_flow_data=MarketFundFlowData.from_dict(data['fund_flow_data']) if data.get('fund_flow_data') else None,
            sentiment=sentiment,
            ma_alignment=ma_alignment,
            macd_signal=macd_signal,
            adx_strength=adx_strength,
            support_resistance=support_resistance,
            volume_analysis=volume_analysis,
            volume_trend=volume_trend,
            north_flow=north_flow,
            margin_trend=margin_trend,
            fund_flow_analysis=fund_flow_analysis,
            valuation=valuation,
            market_state=data.get('market_state', 'NEUTRAL'),
            trend_direction=data.get('trend_direction', 'SIDEWAYS'),
            summary=data.get('summary', '')
        )


@dataclass
class IndexSummary:
    """单个指数摘要（输出数据结构）"""
    ts_code: str = ""
    name: str = ""
    open: float = 0.0        # 开盘价
    high: float = 0.0        # 最高价
    low: float = 0.0         # 最低价
    close: float = 0.0
    pct_chg: float = 0.0
    amount: float = 0.0
    ma_status: str = ""
    macd_signal: str = ""
    support_levels: List[float] = field(default_factory=list)
    resistance_levels: List[float] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'ts_code': self.ts_code,
            'name': self.name,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'pct_chg': self.pct_chg,
            'amount': self.amount,
            'ma_status': self.ma_status,
            'macd_signal': self.macd_signal,
            'support_levels': self.support_levels,
            'resistance_levels': self.resistance_levels
        }


@dataclass
class TechnicalAnalysis:
    """技术面分析结果（输出数据结构）"""
    trend_analysis: str = ""
    ma_status: str = ""
    macd_signal: str = ""
    support_levels: List[float] = field(default_factory=list)
    resistance_levels: List[float] = field(default_factory=list)
    adx_analysis: str = ""
    volume_analysis: str = ""
    def to_dict(self) -> Dict[str, Any]:
        return {
            'trend_analysis': self.trend_analysis,
            'ma_status': self.ma_status,
            'macd_signal': self.macd_signal,
            'support_levels': self.support_levels,
            'resistance_levels': self.resistance_levels,
            'adx_analysis': self.adx_analysis,
            'volume_analysis': self.volume_analysis
        }


@dataclass
class FundFlowAnalysis:
    """资金流向分析结果（输出数据结构）"""
    net_inflow: float = 0.0
    net_inflow_rate: float = 0.0
    super_large_flow: float = 0.0
    large_flow: float = 0.0
    medium_flow: float = 0.0
    small_flow: float = 0.0
    main_signal: str = ""
    smart_money_signal: str = ""
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'net_inflow': self.net_inflow,
            'net_inflow_rate': self.net_inflow_rate,
            'super_large_flow': self.super_large_flow,
            'large_flow': self.large_flow,
            'medium_flow': self.medium_flow,
            'small_flow': self.small_flow,
            'main_signal': self.main_signal,
            'smart_money_signal': self.smart_money_signal,
            'description': self.description
        }


@dataclass
class CapitalAnalysis:
    """资金面分析结果（输出数据结构）"""
    north_flow_analysis: str = ""
    north_flow_value: float = 0.0
    margin_analysis: str = ""
    margin_balance: float = 0.0
    fund_flow_analysis: FundFlowAnalysis = None   # 新增：原始资金流数据对象
    main_flow_analysis: str = ""                  # 新增：主力资金分析文本
    capital_summary: str = ""
    
    def __post_init__(self):
        if self.fund_flow_analysis is None:
            self.fund_flow_analysis = FundFlowAnalysis()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'north_flow_analysis': self.north_flow_analysis,
            'north_flow_value': self.north_flow_value,
            'margin_analysis': self.margin_analysis,
            'margin_balance': self.margin_balance,
            'fund_flow_analysis': self.fund_flow_analysis.to_dict() if self.fund_flow_analysis else {},
            'main_flow_analysis': self.main_flow_analysis,  
            'capital_summary': self.capital_summary
        }


@dataclass
class SentimentAnalysis:
    """情绪面分析结果（输出数据结构）"""
    adv_issues: int = 0
    dec_issues: int = 0
    market_width: float = 0.0
    sentiment_score: float = 50.0
    description: str = ""
    # 新增字段
    adv_decline_ratio: float = 0.0          # 涨跌比
    ad_line: float = 0.0                    # 腾落指数
    turnover_concentration: float = 0.0      # 成交额集中度
    breadth: str = ""                        # 市场广度分析（LLM生成）
    emotion_state: str = ""                  # 情绪状态（极度贪婪/恐惧等）
    summary: str = ""                         # 情绪面总结（LLM生成）

    def to_dict(self) -> Dict[str, Any]:
        return {
            'adv_issues': self.adv_issues,
            'dec_issues': self.dec_issues,
            'market_width': self.market_width,
            'sentiment_score': self.sentiment_score,
            'description': self.description,
            'adv_decline_ratio': self.adv_decline_ratio,
            'ad_line': self.ad_line,
            'turnover_concentration': self.turnover_concentration,
            'breadth': self.breadth,
            'emotion_state': self.emotion_state,
            'summary': self.summary
        }

@dataclass
class ValuationAnalysis:
    """估值分析结果（输出数据结构）"""
    valuation_level: str = "MEDIUM"
    pe_value: float = 0.0
    pb_value: float = 0.0
    graham_index: Optional[float] = None  # 改良版格雷厄姆指数
    valuation_analysis: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'graham_index': self.graham_index,
            'pe_value': self.pe_value,
            'pb_value': self.pb_value,
            'valuation_level': self.valuation_level,
            'valuation_analysis': self.valuation_analysis
        }


@dataclass
class CycleAnalysis:
    """周期分析结果（输出数据结构）"""
    cycle_phase: str = "SHOCK"
    cycle_analysis: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'cycle_phase': self.cycle_phase,
            'cycle_analysis': self.cycle_analysis
        }


@dataclass
class RiskAssessment:
    """风险评估结果（输出数据结构）"""
    risk_level: str = "MEDIUM"
    risk_factors: List[str] = field(default_factory=list)
    opportunity_factors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'risk_level': self.risk_level,
            'risk_factors': self.risk_factors,
            'opportunity_factors': self.opportunity_factors
        }


@dataclass
class NewsItem:
    """新闻条目（输入数据结构）"""
    title: str = ""
    content: str = ""
    publish_time: str = ""
    source: str = ""
    url: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'title': self.title,
            'content': self.content,
            'publish_time': self.publish_time,
            'source': self.source,
            'url': self.url
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NewsItem':
        return cls(
            title=data.get('title', ''),
            content=data.get('content', ''),
            publish_time=data.get('publish_time', ''),
            source=data.get('source', ''),
            url=data.get('url', '')
        )


@dataclass
class NewsAnalysis:
    """新闻分析结果（输出数据结构）"""
    key_news: List[str] = field(default_factory=list)  # 关键新闻摘要
    positive_factors: List[str] = field(default_factory=list)  # 利好因素
    negative_factors: List[str] = field(default_factory=list)  # 利空因素
    market_impact: str = ""  # 对市场的影响
    sector_focus: List[str] = field(default_factory=list)  # 关注板块
    summary: str = ""  # 新闻分析总结
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'key_news': self.key_news,
            'positive_factors': self.positive_factors,
            'negative_factors': self.negative_factors,
            'market_impact': self.market_impact,
            'sector_focus': self.sector_focus,
            'summary': self.summary
        }


@dataclass
class IndexPrediction:
    """
    单个指数的预测（输出数据结构）
    
    用于分指数预测下一交易日走势
    """
    ts_code: str = ""                    # 指数代码，如 '000001.SH'
    name: str = ""                       # 指数名称，如 '上证指数'
    trend_direction: str = "SIDEWAYS"    # UP/SIDEWAYS/DOWN
    prediction_reason: str = ""          # 预测理由（100-150字）
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'ts_code': self.ts_code,
            'name': self.name,
            'trend_direction': self.trend_direction,
            'prediction_reason': self.prediction_reason
        }
    
    @property
    def trend_direction_cn(self) -> str:
        """趋势方向中文"""
        return TREND_DIRECTION_CN.get(self.trend_direction, self.trend_direction)


@dataclass
class MarketReport:
    """
    大盘分析报告（输出数据结构）
    
    大盘分析师的输出结构，包含市场各维度的分析结果
    """
    
    date: str = ""
    
    index_summaries: List[IndexSummary] = field(default_factory=list)
    
    market_state: str = "SHOCK"
    
    # 分指数预测（替代原来的单一 trend_direction）
    index_predictions: List[IndexPrediction] = field(default_factory=list)
    
    technical: TechnicalAnalysis = None
    capital: CapitalAnalysis = None
    sentiment: SentimentAnalysis = None
    valuation: ValuationAnalysis = None
    cycle: CycleAnalysis = None
    risk: RiskAssessment = None
    news_analysis: NewsAnalysis = None  # 新闻分析
    
    summary: str = ""  # 市场综合概述与总结（400字左右）
    position_advice: str = ""
    
    confidence: float = 50.0
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.technical is None:
            self.technical = TechnicalAnalysis()
        if self.capital is None:
            self.capital = CapitalAnalysis()
        if self.sentiment is None:
            self.sentiment = SentimentAnalysis()
        if self.valuation is None:
            self.valuation = ValuationAnalysis()
        if self.cycle is None:
            self.cycle = CycleAnalysis()
        if self.risk is None:
            self.risk = RiskAssessment()
        if self.news_analysis is None:
            self.news_analysis = NewsAnalysis()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'date': self.date,
            'index_summaries': [s.to_dict() for s in self.index_summaries],
            'market_state': self.market_state,
            'index_predictions': [p.to_dict() for p in self.index_predictions],
            'technical': self.technical.to_dict() if self.technical else {},
            'capital': self.capital.to_dict() if self.capital else {},
            'sentiment': self.sentiment.to_dict() if self.sentiment else {},
            'valuation': self.valuation.to_dict() if self.valuation else {},
            'cycle': self.cycle.to_dict() if self.cycle else {},
            'risk': self.risk.to_dict() if self.risk else {},
            'news_analysis': self.news_analysis.to_dict() if self.news_analysis else {},
            'summary': self.summary,
            'position_advice': self.position_advice,
            'confidence': self.confidence,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MarketReport':
        index_summaries = [
            IndexSummary(**s) for s in data.get('index_summaries', [])
        ]
        
        # 解析 index_predictions
        index_predictions = [
            IndexPrediction(**p) for p in data.get('index_predictions', [])
        ]
        
        # 解析 news_analysis
        news_data = data.get('news_analysis', {})
        news_analysis = NewsAnalysis(
            key_news=news_data.get('key_news', []),
            positive_factors=news_data.get('positive_factors', []),
            negative_factors=news_data.get('negative_factors', []),
            market_impact=news_data.get('market_impact', ''),
            sector_focus=news_data.get('sector_focus', []),
            summary=news_data.get('summary', '')
        )
        
        return cls(
            date=data.get('date', ''),
            index_summaries=index_summaries,
            market_state=data.get('market_state', 'SHOCK'),
            index_predictions=index_predictions,
            technical=TechnicalAnalysis(**data.get('technical', {})),
            capital=CapitalAnalysis(**data.get('capital', {})),
            sentiment=SentimentAnalysis(**data.get('sentiment', {})),
            valuation=ValuationAnalysis(**data.get('valuation', {})),
            cycle=CycleAnalysis(**data.get('cycle', {})),
            risk=RiskAssessment(**data.get('risk', {})),
            news_analysis=news_analysis,
            summary=data.get('summary', ''),
            position_advice=data.get('position_advice', ''),
            confidence=data.get('confidence', 50.0)
        )
    
    def get_index_summary(self, ts_code: str) -> Optional[IndexSummary]:
        """获取指定指数的摘要"""
        for s in self.index_summaries:
            if s.ts_code == ts_code:
                return s
        return None
    
    @property
    def market_state_cn(self) -> str:
        """市场状态中文"""
        return MARKET_STATE_CN.get(self.market_state, self.market_state)
    
    @property
    def valuation_level_cn(self) -> str:
        """估值水平中文"""
        if self.valuation:
            return VALUATION_LEVEL_CN.get(self.valuation.valuation_level, self.valuation.valuation_level)
        return ''
    
    @property
    def cycle_phase_cn(self) -> str:
        """周期阶段中文"""
        if self.cycle:
            return CYCLE_PHASE_CN.get(self.cycle.cycle_phase, self.cycle.cycle_phase)
        return ''
    
    @property
    def risk_level_cn(self) -> str:
        """风险等级中文"""
        if self.risk:
            return RISK_LEVEL_CN.get(self.risk.risk_level, self.risk.risk_level)
        return ''
    
    @property
    def risk_factors_text(self) -> str:
        """风险因素文本（换行分隔）"""
        if self.risk and self.risk.risk_factors:
            return '\n'.join(f"  - {f}" for f in self.risk.risk_factors)
        return ''
    
    @property
    def opportunity_factors_text(self) -> str:
        """机会因素文本（换行分隔）"""
        if self.risk and self.risk.opportunity_factors:
            return '\n'.join(f"  - {f}" for f in self.risk.opportunity_factors)
        return ''
