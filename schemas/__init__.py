"""
数据结构模块

包含所有分析相关的数据结构定义
"""

from data.schemas.base_schema import (
    BaseSchema,
    IndicatorValue,
    PriceData,
    SupportResistance,
    ValuationLevel,
    SignalType,
    PositionType,
    ValuationLevelType,
    FlowTrendType,
    MarginTrendType,
    CyclePhaseType,
)

from data.schemas.market_schema import (
    MarketSentiment,
    MarketTechnicalData,
    MarketCapitalData,
    MarketFundFlowData,
    MarketAnalysisData,
    IndexSummary,
    TechnicalAnalysis,
    FundFlowAnalysis,
    CapitalAnalysis,
    SentimentAnalysis,
    ValuationAnalysis,
    CycleAnalysis,
    RiskAssessment,
    NewsItem,
    NewsAnalysis,
    IndexPrediction,
    MarketReport,
    MARKET_STATE_CN,
    TREND_DIRECTION_CN,
    VALUATION_LEVEL_CN,
    CYCLE_PHASE_CN,
    RISK_LEVEL_CN,
)

from data.schemas.sector_schema import (
    SectorBasicInfo,
    SectorAnalysisData,
    LeadingStock,
    HotSectorDetail,
    SectorRotation,
    MarketBreadth,
    SectorStatistics,
    SectorCapitalFlow,
    SectorHotAnalysis,
    SectorCapitalAnalysis,
    SectorRiskAnalysis,
    SectorReport,
    SECTOR_TREND_CN,
    ROTATION_DIRECTION_CN,
    MARKET_BREADTH_CN,
)


__all__ = [
    # Base Schema
    'BaseSchema',
    'IndicatorValue',
    'PriceData',
    'SupportResistance',
    'ValuationLevel',
    'SignalType',
    'PositionType',
    'ValuationLevelType',
    'FlowTrendType',
    'MarginTrendType',
    'CyclePhaseType',
    
    # Market Schema
    'MarketSentiment',
    'MarketTechnicalData',
    'MarketCapitalData',
    'MarketFundFlowData',
    'MarketAnalysisData',
    'IndexSummary',
    'TechnicalAnalysis',
    'FundFlowAnalysis',
    'CapitalAnalysis',
    'SentimentAnalysis',
    'ValuationAnalysis',
    'CycleAnalysis',
    'RiskAssessment',
    'NewsItem',
    'NewsAnalysis',
    'IndexPrediction',
    'MarketReport',
    'MARKET_STATE_CN',
    'TREND_DIRECTION_CN',
    'VALUATION_LEVEL_CN',
    'CYCLE_PHASE_CN',
    'RISK_LEVEL_CN',
    
    # Sector Schema
    'SectorBasicInfo',
    'SectorAnalysisData',
    'LeadingStock',
    'HotSectorDetail',
    'SectorRotation',
    'MarketBreadth',
    'SectorStatistics',
    'SectorCapitalFlow',
    'SectorHotAnalysis',
    'SectorCapitalAnalysis',
    'SectorRiskAnalysis',
    'SectorReport',
    'SECTOR_TREND_CN',
    'ROTATION_DIRECTION_CN',
    'MARKET_BREADTH_CN',
    
]
