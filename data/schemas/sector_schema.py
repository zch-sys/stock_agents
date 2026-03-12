"""
板块分析数据结构

包含板块分析师的输入和输出数据结构：
1. 输入数据结构（从数据库转换后的中间数据）
2. 输出数据结构（LLM分析结果）

对应数据库表：SectorData
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any, Optional
from data.schemas.base_schema import BaseSchema, IndicatorValue


# ==================== 枚举映射 ====================

SECTOR_TREND_30D_CN = {
    'ACCELERATING': '趋势加强',      # 近30日强于前30日
    'PERSISTENT': '持续强势',        # 近30日和前30日都强
    'WEAKENING': '趋势转弱',         # 近30日弱于前30日
    'CONSISTENTLY_WEAK': '持续弱势',  # 近30日和前30日都弱
    'REBOUNDING': '触底反弹',        # 前30日弱，近30日转强
    'CORRECTING': '高位回调'         # 前30日强，近30日转弱
}

SECTOR_TREND_CN = {
    'STRONG': '强势',
    'WEAK': '弱势',
    'NEUTRAL': '中性'
}

ROTATION_DIRECTION_CN = {
    'FORWARD': '正向轮动（题材→权重）',
    'BACKWARD': '逆向轮动（权重→题材）',
    'DIVERGENT': '分化轮动',
    'ACCUMULATION': '蓄势待发'
}

MARKET_BREADTH_CN = {
    'STRONG': '市场活跃',
    'NORMAL': '市场平稳',
    'WEAK': '市场低迷'
}


# ==================== 输入数据结构 ====================

@dataclass
class SectorBasicInfo:
    """
    单个板块基础信息（输入数据结构）
    
    对应数据库 SectorData 表的单条记录
    """
    sector_code: str = ""           # 板块代码（如 "BK0428"）
    sector_name: str = ""           # 板块名称（如 "半导体"）
    trade_date: str = ""            # 交易日期
    
    # 行情数据
    rank: int = 0                   # 涨幅排名（1-110）
    pct_chg: float = 0.0            # 涨跌幅%
    close: float = 0.0              # 收盘价
    high: float = 0.0               # 最高价
    low: float = 0.0                # 最低价
    open: float = 0.0               # 开盘价
    
    # 成交数据
    amount: float = 0.0             # 成交额（元）
    vol: float = 0.0                # 成交量（手）
    turnover_rate: float = 0.0      # 换手率%
    
    # 资金数据
    fund_inflow: float = 0.0        # 资金净流入（元）
    fund_inflow_rate: float = 0.0   # 资金流入率%
    
    # 市值数据
    circ_market_cap: float = 0.0    # 流通市值（元）
    total_market_cap: float = 0.0   # 总市值（元）
    
    # 涨跌家数
    adv_issues: int = 0             # 上涨家数
    dec_issues: int = 0             # 下跌家数
    rise_fall_ratio: float = 0.0    # 涨跌比
    
    # 领涨股信息（存储为JSON）
    leading_stock_code: str = ""    # 领涨股代码
    leading_stock_name: str = ""    # 领涨股名称
    leading_stock_pct_chg: float = 0.0  # 领涨股涨幅
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SectorBasicInfo':
        return cls(
            sector_code=data.get('sector_code', ''),
            sector_name=data.get('sector_name', ''),
            trade_date=data.get('trade_date', ''),
            rank=data.get('rank', 0),
            pct_chg=data.get('pct_chg', 0.0),
            close=data.get('close', 0.0),
            high=data.get('high', 0.0),
            low=data.get('low', 0.0),
            open=data.get('open', 0.0),
            amount=data.get('amount', 0.0),
            vol=data.get('vol', 0.0),
            turnover_rate=data.get('turnover_rate', 0.0),
            fund_inflow=data.get('fund_inflow', 0.0),
            fund_inflow_rate=data.get('fund_inflow_rate', 0.0),
            circ_market_cap=data.get('circ_market_cap', 0.0),
            total_market_cap=data.get('total_market_cap', 0.0),
            adv_issues=data.get('adv_issues', 0),
            dec_issues=data.get('dec_issues', 0),
            rise_fall_ratio=data.get('rise_fall_ratio', 0.0),
            leading_stock_code=data.get('leading_stock_code', ''),
            leading_stock_name=data.get('leading_stock_name', ''),
            leading_stock_pct_chg=data.get('leading_stock_pct_chg', 0.0)
        )


@dataclass
class SectorAnalysisData(BaseSchema):
    """
    板块分析数据结构（输入数据结构）
    
    包含单个板块的完整分析数据，用于 SectorAnalyst 的输入
    """
    sector_code: str = ""
    sector_name: str = ""
    
    # 基础信息
    basic_info: SectorBasicInfo = None
    
    # 技术指标（可选，后续扩展）
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    
    # 历史排名（用于连续性分析）
    rank_history: List[int] = field(default_factory=list)  # 最近N日排名
    
    # 成分股信息
    constituent_count: int = 0      # 成分股数量
    leading_stocks: List[Dict] = field(default_factory=list)  # 领涨股列表
    
    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.basic_info:
            result['basic_info'] = self.basic_info.to_dict()
        result['rank_history'] = self.rank_history
        result['leading_stocks'] = self.leading_stocks
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SectorAnalysisData':
        basic_info = SectorBasicInfo.from_dict(data['basic_info']) if data.get('basic_info') else None
        return cls(
            trade_date=data.get('trade_date', ''),
            sector_code=data.get('sector_code', ''),
            sector_name=data.get('sector_name', ''),
            basic_info=basic_info,
            ma5=data.get('ma5', 0.0),
            ma10=data.get('ma10', 0.0),
            ma20=data.get('ma20', 0.0),
            macd=data.get('macd', 0.0),
            macd_signal=data.get('macd_signal', 0.0),
            macd_hist=data.get('macd_hist', 0.0),
            rank_history=data.get('rank_history', []),
            constituent_count=data.get('constituent_count', 0),
            leading_stocks=data.get('leading_stocks', [])
        )


# ==================== 输出数据结构 ====================

@dataclass
class LeadingStock:
    """领涨股信息（输出数据结构）"""
    stock_code: str = ""            # 股票代码
    stock_name: str = ""            # 股票名称
    pct_chg: float = 0.0            # 涨幅%
    amount: float = 0.0             # 成交额
    fund_inflow: float = 0.0        # 资金净流入
    is_limit_up: bool = False       # 是否涨停
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'pct_chg': self.pct_chg,
            'amount': self.amount,
            'fund_inflow': self.fund_inflow,
            'is_limit_up': self.is_limit_up
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LeadingStock':
        return cls(
            stock_code=data.get('stock_code', ''),
            stock_name=data.get('stock_name', ''),
            pct_chg=data.get('pct_chg', 0.0),
            amount=data.get('amount', 0.0),
            fund_inflow=data.get('fund_inflow', 0.0),
            is_limit_up=data.get('is_limit_up', False)
        )


@dataclass
class HotSectorDetail:
    """
    热门板块详情（输出数据结构）
    
    用于存储筛选后的重点板块详细信息
    """
    sector_code: str = ""
    sector_name: str = ""
    
    # 基础行情
    rank: int = 0
    pct_chg: float = 0.0
    amount: float = 0.0
    fund_inflow: float = 0.0
    fund_inflow_rate: float = 0.0
    
    # 连续性分析
    continuous_strong_days: int = 0     # 连续强势天数
    rank_change: int = 0                # 排名变化（正数上升，负数下降）
    
    # 内部结构
    adv_issues: int = 0
    dec_issues: int = 0
    rise_fall_ratio: float = 0.0
    
    # 领涨股
    leading_stocks: List[LeadingStock] = field(default_factory=list)
    
    # 分析结果
    internal_analysis: str = ""         # 内部结构分析
    strength_reason: str = ""           # 强势原因
    
    # 筛选来源标记
    filter_source: str = ""             # hot/capital_flow/risk/continuous
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'sector_code': self.sector_code,
            'sector_name': self.sector_name,
            'rank': self.rank,
            'pct_chg': self.pct_chg,
            'amount': self.amount,
            'fund_inflow': self.fund_inflow,
            'fund_inflow_rate': self.fund_inflow_rate,
            'continuous_strong_days': self.continuous_strong_days,
            'rank_change': self.rank_change,
            'adv_issues': self.adv_issues,
            'dec_issues': self.dec_issues,
            'rise_fall_ratio': self.rise_fall_ratio,
            'leading_stocks': [s.to_dict() for s in self.leading_stocks],
            'internal_analysis': self.internal_analysis,
            'strength_reason': self.strength_reason,
            'filter_source': self.filter_source
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'HotSectorDetail':
        leading_stocks = [
            LeadingStock.from_dict(s) for s in data.get('leading_stocks', [])
        ]
        return cls(
            sector_code=data.get('sector_code', ''),
            sector_name=data.get('sector_name', ''),
            rank=data.get('rank', 0),
            pct_chg=data.get('pct_chg', 0.0),
            amount=data.get('amount', 0.0),
            fund_inflow=data.get('fund_inflow', 0.0),
            fund_inflow_rate=data.get('fund_inflow_rate', 0.0),
            continuous_strong_days=data.get('continuous_strong_days', 0),
            rank_change=data.get('rank_change', 0),
            adv_issues=data.get('adv_issues', 0),
            dec_issues=data.get('dec_issues', 0),
            rise_fall_ratio=data.get('rise_fall_ratio', 0.0),
            leading_stocks=leading_stocks,
            internal_analysis=data.get('internal_analysis', ''),
            strength_reason=data.get('strength_reason', ''),
            filter_source=data.get('filter_source', '')
        )


@dataclass
class SectorRotation:
    """
    板块轮动分析（输出数据结构）
    
    对比今日热门 vs 昨日热门，识别轮动规律
    """
    new_hot_sectors: List[str] = field(default_factory=list)        # 新晋热门板块
    cooling_sectors: List[str] = field(default_factory=list)        # 降温板块
    persistent_hot_sectors: List[str] = field(default_factory=list)  # 持续强势板块
    
    rotation_direction: str = ""         # 轮动方向: FORWARD/BACKWARD/DIVERGENT/ACCUMULATION
    rotation_description: str = ""       # 轮动描述
    
    # 资金流向变化
    capital_rotation: str = ""           # 资金轮动描述
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'new_hot_sectors': self.new_hot_sectors,
            'cooling_sectors': self.cooling_sectors,
            'persistent_hot_sectors': self.persistent_hot_sectors,
            'rotation_direction': self.rotation_direction,
            'rotation_description': self.rotation_description,
            'capital_rotation': self.capital_rotation
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SectorRotation':
        return cls(
            new_hot_sectors=data.get('new_hot_sectors', []),
            cooling_sectors=data.get('cooling_sectors', []),
            persistent_hot_sectors=data.get('persistent_hot_sectors', []),
            rotation_direction=data.get('rotation_direction', ''),
            rotation_description=data.get('rotation_description', ''),
            capital_rotation=data.get('capital_rotation', '')
        )
    
    @property
    def rotation_direction_cn(self) -> str:
        """轮动方向中文"""
        return ROTATION_DIRECTION_CN.get(self.rotation_direction, self.rotation_direction)


@dataclass
class MarketBreadth:
    """
    市场广度分析（输出数据结构）
    
    整体板块市场的广度指标
    """
    total_sectors: int = 0               # 板块总数
    adv_sector_count: int = 0            # 上涨板块数
    dec_sector_count: int = 0            # 下跌板块数
    flat_sector_count: int = 0           # 平盘板块数
    
    avg_pct_chg: float = 0.0             # 平均涨跌幅
    median_pct_chg: float = 0.0          # 中位数涨跌幅
    
    strong_sector_ratio: float = 0.0     # 强势板块占比（涨幅>2%）
    weak_sector_ratio: float = 0.0       # 弱势板块占比（跌幅>2%）
    
    market_breadth_state: str = "NORMAL"  # 市场广度状态: STRONG/NORMAL/WEAK
    description: str = ""                 # 市场广度描述
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'total_sectors': self.total_sectors,
            'adv_sector_count': self.adv_sector_count,
            'dec_sector_count': self.dec_sector_count,
            'flat_sector_count': self.flat_sector_count,
            'avg_pct_chg': self.avg_pct_chg,
            'median_pct_chg': self.median_pct_chg,
            'strong_sector_ratio': self.strong_sector_ratio,
            'weak_sector_ratio': self.weak_sector_ratio,
            'market_breadth_state': self.market_breadth_state,
            'description': self.description
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MarketBreadth':
        return cls(
            total_sectors=data.get('total_sectors', 0),
            adv_sector_count=data.get('adv_sector_count', 0),
            dec_sector_count=data.get('dec_sector_count', 0),
            flat_sector_count=data.get('flat_sector_count', 0),
            avg_pct_chg=data.get('avg_pct_chg', 0.0),
            median_pct_chg=data.get('median_pct_chg', 0.0),
            strong_sector_ratio=data.get('strong_sector_ratio', 0.0),
            weak_sector_ratio=data.get('weak_sector_ratio', 0.0),
            market_breadth_state=data.get('market_breadth_state', 'NORMAL'),
            description=data.get('description', '')
        )
    
    @property
    def market_breadth_state_cn(self) -> str:
        """市场广度状态中文"""
        return MARKET_BREADTH_CN.get(self.market_breadth_state, self.market_breadth_state)


@dataclass
class SectorStatistics:
    """
    板块统计数据（输入/输出数据结构）
    
    板块内部成分股的统计信息
    """
    stock_count: int = 0               # 成分股数量
    rise_count: int = 0                # 上涨家数
    fall_count: int = 0                # 下跌家数
    unchanged_count: int = 0           # 平盘家数
    rise_fall_ratio: float = 0.0       # 涨跌比
    avg_pct_chg: float = 0.0           # 平均涨跌幅
    max_pct_chg: float = 0.0           # 最大涨幅
    min_pct_chg: float = 0.0           # 最小涨幅
    median_pct_chg: float = 0.0        # 中位数涨跌幅
    std_pct_chg: float = 0.0           # 涨跌幅标准差
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'stock_count': self.stock_count,
            'rise_count': self.rise_count,
            'fall_count': self.fall_count,
            'unchanged_count': self.unchanged_count,
            'rise_fall_ratio': self.rise_fall_ratio,
            'avg_pct_chg': self.avg_pct_chg,
            'max_pct_chg': self.max_pct_chg,
            'min_pct_chg': self.min_pct_chg,
            'median_pct_chg': self.median_pct_chg,
            'std_pct_chg': self.std_pct_chg
        }


@dataclass
class SectorCapitalFlow:
    """
    板块资金流向（输入/输出数据结构）
    
    板块级别的资金流向数据
    """
    fund_inflow: float = 0.0           # 资金净流入（元）
    fund_inflow_rate: float = 0.0      # 资金流入率%
    rise_amount: float = 0.0           # 上涨成交额
    fall_amount: float = 0.0           # 下跌成交额
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'fund_inflow': self.fund_inflow,
            'fund_inflow_rate': self.fund_inflow_rate,
            'rise_amount': self.rise_amount,
            'fall_amount': self.fall_amount
        }


@dataclass
class SectorTrend30D:
    """
    板块30日趋势数据（输出数据结构）
    
    用于展示板块的中期趋势，对比近30日 vs 前30日
    """
    sector_code: str = ""
    sector_name: str = ""
    
    # 近30日数据
    pct_chg_30d: float = 0.0           # 近30日累计涨跌幅%
    fund_inflow_30d: float = 0.0       # 近30日累计资金流入（元）
    avg_rank_30d: float = 0.0          # 近30日平均排名
    strong_days_30d: int = 0           # 近30日强势天数（排名<=20）
    
    # 前30日数据（用于对比，31-60天前）
    pct_chg_prev_30d: float = 0.0      # 前30日累计涨跌幅%
    fund_inflow_prev_30d: float = 0.0  # 前30日累计资金流入（元）
    avg_rank_prev_30d: float = 0.0     # 前30日平均排名
    strong_days_prev_30d: int = 0      # 前30日强势天数
    
    # 趋势判断
    trend_type: str = ""               # ACCELERATING/PERSISTENT/WEAKENING/CONSISTENTLY_WEAK/REBOUNDING/CORRECTING
    trend_description: str = ""        # 趋势描述
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'sector_code': self.sector_code,
            'sector_name': self.sector_name,
            'pct_chg_30d': self.pct_chg_30d,
            'fund_inflow_30d': self.fund_inflow_30d,
            'avg_rank_30d': self.avg_rank_30d,
            'strong_days_30d': self.strong_days_30d,
            'pct_chg_prev_30d': self.pct_chg_prev_30d,
            'fund_inflow_prev_30d': self.fund_inflow_prev_30d,
            'avg_rank_prev_30d': self.avg_rank_prev_30d,
            'strong_days_prev_30d': self.strong_days_prev_30d,
            'trend_type': self.trend_type,
            'trend_description': self.trend_description
        }
    
    @property
    def trend_type_cn(self) -> str:
        """趋势类型中文"""
        return SECTOR_TREND_30D_CN.get(self.trend_type, self.trend_type)


@dataclass
class SectorHotAnalysis:
    """
    板块热度分析（输出数据结构）
    
    LLM分析结果：热门板块分析
    """
    hot_sectors_summary: str = ""        # 热门板块总结
    hot_reasons: List[str] = field(default_factory=list)  # 热门原因列表
    sustainability: str = ""             # 持续性判断
    
    # 预测明日热门板块
    predicted_hot_sectors: List[str] = field(default_factory=list)  # 预测明日热门板块（1-3个）
    predicted_reason: str = ""           # 预测理由
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'hot_sectors_summary': self.hot_sectors_summary,
            'hot_reasons': self.hot_reasons,
            'sustainability': self.sustainability,
            'predicted_hot_sectors': self.predicted_hot_sectors,
            'predicted_reason': self.predicted_reason
        }


@dataclass
class SectorCapitalAnalysis:
    """
    板块资金分析（输出数据结构）
    
    LLM分析结果：资金流向分析
    """
    capital_flow_summary: str = ""       # 资金流向总结
    main_focus: List[str] = field(default_factory=list)  # 主力关注板块
    capital_rotation: str = ""           # 资金轮动描述
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'capital_flow_summary': self.capital_flow_summary,
            'main_focus': self.main_focus,
            'capital_rotation': self.capital_rotation
        }


@dataclass
class SectorRiskAnalysis:
    """
    板块风险分析（输出数据结构）
    
    LLM分析结果：风险警示分析
    """
    risk_sectors_summary: str = ""       # 风险板块总结
    risk_reasons: List[str] = field(default_factory=list)  # 风险原因
    avoid_advice: str = ""               # 规避建议
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'risk_sectors_summary': self.risk_sectors_summary,
            'risk_reasons': self.risk_reasons,
            'avoid_advice': self.avoid_advice
        }


@dataclass
class SectorReport:
    """
    板块分析报告（主输出数据结构）
    
    板块分析师的输出结构，包含板块各维度的分析结果
    """
    
    date: str = ""                       # 交易日期
    
    # 市场广度
    market_breadth: MarketBreadth = None
    
    # 筛选结果
    hot_sectors: List[HotSectorDetail] = field(default_factory=list)           # 热门板块TOP N
    capital_flow_sectors: List[HotSectorDetail] = field(default_factory=list)  # 资金流入TOP N
    risk_sectors: List[HotSectorDetail] = field(default_factory=list)          # 风险板块TOP N
    
    # 30日趋势分析
    trends_30d: Dict[str, List[SectorTrend30D]] = field(default_factory=dict)  # 30日趋势数据
    
    # 轮动分析
    sector_rotation: SectorRotation = None
    
    # LLM分析结果
    hot_analysis: SectorHotAnalysis = None        # 热度分析
    capital_analysis: SectorCapitalAnalysis = None  # 资金分析
    risk_analysis: SectorRiskAnalysis = None      # 风险分析
    
    # 综合分析
    rotation_signal: str = ""            # 板块轮动信号（简短）
    summary: str = ""                    # 综合总结（200-400字）
    tomorrow_outlook: str = ""           # 明日展望
    
    # 元数据
    total_sectors_analyzed: int = 0      # 分析的板块总数
    focus_sectors_count: int = 0         # 重点板块数量
    confidence: float = 50.0             # 置信度
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.market_breadth is None:
            self.market_breadth = MarketBreadth()
        if self.sector_rotation is None:
            self.sector_rotation = SectorRotation()
        if self.hot_analysis is None:
            self.hot_analysis = SectorHotAnalysis()
        if self.capital_analysis is None:
            self.capital_analysis = SectorCapitalAnalysis()
        if self.risk_analysis is None:
            self.risk_analysis = SectorRiskAnalysis()
    
    def to_dict(self) -> Dict[str, Any]:
        # 序列化30日趋势数据
        trends_30d_dict = {}
        if self.trends_30d:
            for key, trends in self.trends_30d.items():
                trends_30d_dict[key] = [t.to_dict() for t in trends] if trends else []
        
        return {
            'date': self.date,
            'market_breadth': self.market_breadth.to_dict() if self.market_breadth else {},
            'hot_sectors': [s.to_dict() for s in self.hot_sectors],
            'capital_flow_sectors': [s.to_dict() for s in self.capital_flow_sectors],
            'risk_sectors': [s.to_dict() for s in self.risk_sectors],
            'trends_30d': trends_30d_dict,
            'sector_rotation': self.sector_rotation.to_dict() if self.sector_rotation else {},
            'hot_analysis': self.hot_analysis.to_dict() if self.hot_analysis else {},
            'capital_analysis': self.capital_analysis.to_dict() if self.capital_analysis else {},
            'risk_analysis': self.risk_analysis.to_dict() if self.risk_analysis else {},
            'rotation_signal': self.rotation_signal,
            'summary': self.summary,
            'tomorrow_outlook': self.tomorrow_outlook,
            'total_sectors_analyzed': self.total_sectors_analyzed,
            'focus_sectors_count': self.focus_sectors_count,
            'confidence': self.confidence,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SectorReport':
        market_breadth = MarketBreadth.from_dict(data['market_breadth']) if data.get('market_breadth') else None
        sector_rotation = SectorRotation.from_dict(data['sector_rotation']) if data.get('sector_rotation') else None
        hot_analysis = SectorHotAnalysis(**data['hot_analysis']) if data.get('hot_analysis') else None
        capital_analysis = SectorCapitalAnalysis(**data['capital_analysis']) if data.get('capital_analysis') else None
        risk_analysis = SectorRiskAnalysis(**data['risk_analysis']) if data.get('risk_analysis') else None
        
        hot_sectors = [HotSectorDetail.from_dict(s) for s in data.get('hot_sectors', [])]
        capital_flow_sectors = [HotSectorDetail.from_dict(s) for s in data.get('capital_flow_sectors', [])]
        risk_sectors = [HotSectorDetail.from_dict(s) for s in data.get('risk_sectors', [])]
        
        # 反序列化30日趋势数据
        trends_30d = {}
        if data.get('trends_30d'):
            for key, trends in data['trends_30d'].items():
                trends_30d[key] = [SectorTrend30D(**t) for t in trends] if trends else []
        
        return cls(
            date=data.get('date', ''),
            market_breadth=market_breadth,
            hot_sectors=hot_sectors,
            capital_flow_sectors=capital_flow_sectors,
            risk_sectors=risk_sectors,
            trends_30d=trends_30d,
            sector_rotation=sector_rotation,
            hot_analysis=hot_analysis,
            capital_analysis=capital_analysis,
            risk_analysis=risk_analysis,
            rotation_signal=data.get('rotation_signal', ''),
            summary=data.get('summary', ''),
            tomorrow_outlook=data.get('tomorrow_outlook', ''),
            total_sectors_analyzed=data.get('total_sectors_analyzed', 0),
            focus_sectors_count=data.get('focus_sectors_count', 0),
            confidence=data.get('confidence', 50.0)
        )
    
    def get_hot_sector_names(self) -> List[str]:
        """获取热门板块名称列表"""
        return [s.sector_name for s in self.hot_sectors]
    
    def get_capital_sector_names(self) -> List[str]:
        """获取资金流入板块名称列表"""
        return [s.sector_name for s in self.capital_flow_sectors]
    
    def get_risk_sector_names(self) -> List[str]:
        """获取风险板块名称列表"""
        return [s.sector_name for s in self.risk_sectors]