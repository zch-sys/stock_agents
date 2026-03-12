"""
数据结构基类
提供所有分析数据结构的通用基类和辅助类型
"""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from enum import Enum


class SignalType(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class PositionType(Enum):
    ABOVE_MA = "ABOVE_MA"
    BELOW_MA = "BELOW_MA"
    NEAR_SUPPORT = "NEAR_SUPPORT"
    NEAR_RESISTANCE = "NEAR_RESISTANCE"
    MIDDLE = "MIDDLE"


class ValuationLevelType(Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class FlowTrendType(Enum):
    INFLOW = "INFLOW"
    OUTFLOW = "OUTFLOW"
    FLUCTUATE = "FLUCTUATE"


class MarginTrendType(Enum):
    EXPANDING = "EXPANDING"
    SHRINKING = "SHRINKING"
    STABLE = "STABLE"


class CyclePhaseType(Enum):
    ACCUMULATION = "ACCUMULATION"
    RISE = "RISE"
    DISTRIBUTION = "DISTRIBUTION"
    DECLINE = "DECLINE"


@dataclass
class BaseSchema:
    """所有数据结构的基类"""
    trade_date: str
    
    def to_dict(self) -> Dict[str, Any]:
        result = {}
        for key, value in asdict(self).items():
            if isinstance(value, Enum):
                result[key] = value.value
            elif hasattr(value, 'to_dict'):
                result[key] = value.to_dict()
            elif isinstance(value, list):
                result[key] = [
                    item.to_dict() if hasattr(item, 'to_dict') else
                    item.value if isinstance(item, Enum) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BaseSchema':
        return cls(**data)


@dataclass
class IndicatorValue:
    """指标值封装，包含数值和判断结果"""
    value: float
    signal: str
    description: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'value': self.value,
            'signal': self.signal,
            'description': self.description
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IndicatorValue':
        return cls(
            value=data['value'],
            signal=data['signal'],
            description=data['description']
        )
    
    @classmethod
    def bullish(cls, value: float, description: str) -> 'IndicatorValue':
        return cls(value=value, signal=SignalType.BULLISH.value, description=description)
    
    @classmethod
    def bearish(cls, value: float, description: str) -> 'IndicatorValue':
        return cls(value=value, signal=SignalType.BEARISH.value, description=description)
    
    @classmethod
    def neutral(cls, value: float, description: str) -> 'IndicatorValue':
        return cls(value=value, signal=SignalType.NEUTRAL.value, description=description)


@dataclass
class PriceData:
    """价格数据"""
    open: float
    close: float
    high: float
    low: float
    pct_chg: float
    vol: float
    amount: float
    pre_close: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PriceData':
        return cls(**data)


@dataclass
class SupportResistance:
    """支撑阻力位"""
    support: List[float] = field(default_factory=list)
    resistance: List[float] = field(default_factory=list)
    current_position: str = PositionType.MIDDLE.value
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'support': self.support,
            'resistance': self.resistance,
            'current_position': self.current_position
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SupportResistance':
        return cls(
            support=data.get('support', []),
            resistance=data.get('resistance', []),
            current_position=data.get('current_position', PositionType.MIDDLE.value)
        )


@dataclass
class ValuationLevel:
    """估值水平（客观数据，不含判断）"""
    pe: float
    pb: float
    pe_percentile: float
    pb_percentile: float
    graham_index: Optional[float] = None
    graham_desc: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'pe': self.pe,
            'pb': self.pb,
            'pe_percentile': self.pe_percentile,
            'pb_percentile': self.pb_percentile,
            'graham_index': self.graham_index,
            'graham_desc': self.graham_desc
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ValuationLevel':
        return cls(
            pe=data['pe'],
            pb=data['pb'],
            pe_percentile=data['pe_percentile'],
            pb_percentile=data['pb_percentile'],
            graham_index=data.get('graham_index'),
            graham_interpretation=data.get('graham_interpretation', '')
        )
