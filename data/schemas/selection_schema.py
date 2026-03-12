"""
选股报告 Schema

设计原则：
1. 复用 BaseSchema 的 to_dict/from_dict 模式
2. 使用 dataclass 简化定义
3. 所有字段都有默认值，防止解析失败

注意：SelectedStock 不包含 source 字段（仅 CandidateStock 包含）
"""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from data.schemas.base_schema import BaseSchema


@dataclass
class FocusedSector(BaseSchema):
    """关注板块"""
    trade_date: str
    sector_name: str = ""           # 板块名称（自然语言）
    sector_code: str = ""           # 板块代码（数据库标准）
    reason: str = ""                # 关注理由
    confidence: str = "medium"      # high/medium/low
    capital_flow: str = ""          # 资金流向描述
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'trade_date': self.trade_date,
            'sector_name': self.sector_name,
            'sector_code': self.sector_code,
            'reason': self.reason,
            'confidence': self.confidence,
            'capital_flow': self.capital_flow
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FocusedSector':
        return cls(
            trade_date=data.get('trade_date', ''),
            sector_name=data.get('sector_name', ''),
            sector_code=data.get('sector_code', ''),
            reason=data.get('reason', ''),
            confidence=data.get('confidence', 'medium'),
            capital_flow=data.get('capital_flow', '')
        )


@dataclass
class CandidateStock(BaseSchema):
    """候选股票（中间结果）"""
    trade_date: str
    ts_code: str = ""               # 股票代码
    name: str = ""                  # 股票名称
    pool_type: str = ""             # SHORT/MID/LONG/WHITE_HORSE
    model_rank: int = 0             # 模型排名
    sector: str = ""                # 所属板块
    source: str = ""                # "factor_rank" | "sector_match"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'trade_date': self.trade_date,
            'ts_code': self.ts_code,
            'name': self.name,
            'pool_type': self.pool_type,
            'model_rank': self.model_rank,
            'sector': self.sector,
            'source': self.source
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CandidateStock':
        return cls(
            trade_date=data.get('trade_date', ''),
            ts_code=data.get('ts_code', ''),
            name=data.get('name', ''),
            pool_type=data.get('pool_type', ''),
            model_rank=data.get('model_rank', 0),
            sector=data.get('sector', ''),
            source=data.get('source', '')
        )


@dataclass
class SelectedStock(BaseSchema):
    """最终选中的股票（最终输出）
    
    注意：不包含 source 字段，source 仅用于 CandidateStock
    """
    trade_date: str
    ts_code: str = ""               # 股票代码
    name: str = ""                  # 股票名称
    pool_type: str = ""             # 股票池类型
    model_rank: int = 0             # 模型排名
    sector: str = ""                # 所属板块
    selection_reason: str = ""      # 选中理由
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'trade_date': self.trade_date,
            'ts_code': self.ts_code,
            'name': self.name,
            'pool_type': self.pool_type,
            'model_rank': self.model_rank,
            'sector': self.sector,
            'selection_reason': self.selection_reason
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SelectedStock':
        return cls(
            trade_date=data.get('trade_date', ''),
            ts_code=data.get('ts_code', ''),
            name=data.get('name', ''),
            pool_type=data.get('pool_type', ''),
            model_rank=data.get('model_rank', 0),
            sector=data.get('sector', ''),
            selection_reason=data.get('selection_reason', '')
        )


@dataclass
class SelectionThought(BaseSchema):
    """思考记录"""
    trade_date: str
    step: int = 0
    thought: str = ""               # 思考内容
    action: str = ""                # 执行的动作
    observation: str = ""           # 观察到的结果
    category: str = "analysis"      # analysis/decision/concern
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'trade_date': self.trade_date,
            'step': self.step,
            'thought': self.thought,
            'action': self.action,
            'observation': self.observation,
            'category': self.category
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SelectionThought':
        return cls(
            trade_date=data.get('trade_date', ''),
            step=data.get('step', 0),
            thought=data.get('thought', ''),
            action=data.get('action', ''),
            observation=data.get('observation', ''),
            category=data.get('category', 'analysis')
        )


@dataclass
class StockSelectionReport(BaseSchema):
    """选股报告（最终输出）"""
    trade_date: str
    market_view: str = ""                       # 大盘观点（来自 MarketAnalyst）
    sector_focus: List[FocusedSector] = field(default_factory=list)    # 关注板块
    candidate_stocks: List[CandidateStock] = field(default_factory=list)  # 候选股票
    selected_stocks: List[SelectedStock] = field(default_factory=list)    # 最终选中的10支
    selection_summary: str = ""                 # 选股总结
    confidence: float = 50.0                    # 置信度 (0-100)
    thoughts: List[SelectionThought] = field(default_factory=list)  # 思考过程
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'trade_date': self.trade_date,
            'market_view': self.market_view,
            'sector_focus': [s.to_dict() for s in self.sector_focus],
            'candidate_stocks': [s.to_dict() for s in self.candidate_stocks],
            'selected_stocks': [s.to_dict() for s in self.selected_stocks],
            'selection_summary': self.selection_summary,
            'confidence': self.confidence,
            'thoughts': [t.to_dict() for t in self.thoughts]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StockSelectionReport':
        return cls(
            trade_date=data.get('trade_date', ''),
            market_view=data.get('market_view', ''),
            sector_focus=[FocusedSector.from_dict(s) for s in data.get('sector_focus', [])],
            candidate_stocks=[CandidateStock.from_dict(s) for s in data.get('candidate_stocks', [])],
            selected_stocks=[SelectedStock.from_dict(s) for s in data.get('selected_stocks', [])],
            selection_summary=data.get('selection_summary', ''),
            confidence=data.get('confidence', 50.0),
            thoughts=[SelectionThought.from_dict(t) for t in data.get('thoughts', [])]
        )