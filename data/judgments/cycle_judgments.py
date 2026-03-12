"""
周期判断函数
纯函数，无副作用，用于市场周期分析
"""
from typing import List, Optional, Tuple
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from data.schemas.base_schema import IndicatorValue, CyclePhaseType


def identify_cycle_phase(
    prices: List[float],
    volumes: List[float],
    lookback: int = 250
) -> str:
    """
    识别当前周期阶段
    
    基于威科夫周期理论，识别四个阶段：
    - ACCUMULATION: 筑底阶段
    - RISE: 上涨阶段
    - DISTRIBUTION: 派发阶段
    - DECLINE: 下跌阶段
    
    Args:
        prices: 价格序列（从旧到新）
        volumes: 成交量序列（从旧到新）
        lookback: 分析周期天数（默认250天，约一年交易日）
        
    Returns:
        周期阶段字符串
    """
    if not prices or len(prices) < lookback // 2:
        return CyclePhaseType.ACCUMULATION.value
    
    recent_prices = prices[-lookback:] if len(prices) >= lookback else prices
    recent_volumes = volumes[-lookback:] if volumes and len(volumes) >= lookback else (volumes or [])
    
    current_price = recent_prices[-1]
    
    max_price = max(recent_prices)
    min_price = min(recent_prices)
    price_range = max_price - min_price
    
    if price_range == 0:
        return CyclePhaseType.ACCUMULATION.value
    
    price_position = (current_price - min_price) / price_range
    
    ma_short = sum(recent_prices[-5:]) / 5 if len(recent_prices) >= 5 else current_price
    ma_long = sum(recent_prices[-20:]) / 20 if len(recent_prices) >= 20 else current_price
    
    trend = (recent_prices[-1] - recent_prices[0]) / recent_prices[0] * 100 if recent_prices[0] != 0 else 0
    
    volatility = _calc_volatility(recent_prices)
    
    if price_position < 0.3:
        if volatility < 3 and abs(trend) < 5:
            return CyclePhaseType.ACCUMULATION.value
        elif trend < -10:
            return CyclePhaseType.DECLINE.value
        else:
            return CyclePhaseType.ACCUMULATION.value
    
    elif price_position > 0.7:
        if volatility < 3 and abs(trend) < 5:
            return CyclePhaseType.DISTRIBUTION.value
        elif trend > 10:
            return CyclePhaseType.RISE.value
        else:
            return CyclePhaseType.DISTRIBUTION.value
    
    else:
        if ma_short > ma_long and trend > 0:
            return CyclePhaseType.RISE.value
        elif ma_short < ma_long and trend < 0:
            return CyclePhaseType.DECLINE.value
        else:
            if trend > 0:
                return CyclePhaseType.RISE.value
            else:
                return CyclePhaseType.DECLINE.value


def _calc_volatility(prices: List[float]) -> float:
    """计算价格波动率"""
    if len(prices) < 2:
        return 0
    
    returns = []
    for i in range(1, len(prices)):
        if prices[i-1] != 0:
            returns.append((prices[i] - prices[i-1]) / prices[i-1] * 100)
    
    if not returns:
        return 0
    
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return variance ** 0.5


def get_cycle_description(phase: str) -> str:
    """
    获取周期阶段的特征描述（客观描述，不含操作建议）
    
    Args:
        phase: 周期阶段
        
    Returns:
        特征描述字符串
    """
    descriptions = {
        CyclePhaseType.ACCUMULATION.value: (
            "筑底阶段：价格在低位震荡，成交量相对较低。"
            "特征：波动收窄、量能较低、均线纠缠。"
        ),
        CyclePhaseType.RISE.value: (
            "上涨阶段：价格突破底部区域，成交量增加，趋势向上。"
            "特征：量价齐升、均线多头排列、创新高。"
        ),
        CyclePhaseType.DISTRIBUTION.value: (
            "派发阶段：价格在高位震荡，成交量变化明显。"
            "特征：高位震荡、量价变化、均线走平。"
        ),
        CyclePhaseType.DECLINE.value: (
            "下跌阶段：价格跌破支撑位，成交量变化，趋势向下。"
            "特征：量增价跌、均线空头排列、创新低。"
        )
    }
    
    return descriptions.get(phase, "未知周期阶段")


def judge_cycle_phase_with_signal(
    prices: List[float],
    volumes: List[float],
    lookback: int = 250
) -> IndicatorValue:
    """
    描述周期阶段（客观描述，不作判断）
    
    Args:
        prices: 价格序列
        volumes: 成交量序列
        lookback: 分析周期（默认250天，与周期阶段识别保持一致）
        
    Returns:
        IndicatorValue: 包含周期阶段描述（统一使用neutral信号）
    """
    phase = identify_cycle_phase(prices, volumes, lookback)
    description = get_cycle_description(phase)
    
    # 统一使用 neutral 信号，客观描述周期阶段
    phase_map = {
        CyclePhaseType.ACCUMULATION.value: ("筑底阶段", 0),
        CyclePhaseType.RISE.value: ("上涨阶段", 1),
        CyclePhaseType.DISTRIBUTION.value: ("派发阶段", 2),
        CyclePhaseType.DECLINE.value: ("下跌阶段", 3)
    }
    
    phase_name, phase_value = phase_map.get(phase, ("未知阶段", -1))
    
    return IndicatorValue.neutral(
        value=phase_value,
        description=f"[{phase_name}] {description}"
    )


def calc_cycle_strength(prices: List[float], lookback: int = 60) -> float:
    """
    计算周期强度
    
    基于价格相对于均线的偏离程度和趋势一致性
    
    Args:
        prices: 价格序列
        lookback: 计算周期（默认60天，约一季度交易日）
        
    Returns:
        周期强度值 (-100 到 100)
    """
    if not prices or len(prices) < lookback:
        return 0
    
    recent_prices = prices[-lookback:]
    current_price = recent_prices[-1]
    
    ma = sum(recent_prices) / len(recent_prices)
    
    ma_deviation = (current_price - ma) / ma * 100 if ma != 0 else 0
    
    trend = (recent_prices[-1] - recent_prices[0]) / recent_prices[0] * 100 if recent_prices[0] != 0 else 0
    
    consistency = _calc_trend_consistency(recent_prices)
    
    strength = ma_deviation * 0.4 + trend * 0.4 + consistency * 20
    
    return max(-100, min(100, strength))


def _calc_trend_consistency(prices: List[float]) -> float:
    """计算趋势一致性"""
    if len(prices) < 2:
        return 0
    
    up_days = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i-1])
    down_days = sum(1 for i in range(1, len(prices)) if prices[i] < prices[i-1])
    total = len(prices) - 1
    
    if total == 0:
        return 0
    
    consistency = (up_days - down_days) / total
    return consistency


def identify_support_resistance_levels(
    prices: List[float],
    volumes: List[float] = None,
    lookback: int = 120,
    num_levels: int = 3
) -> Tuple[List[float], List[float]]:
    """
    识别支撑阻力位
    
    基于历史价格高低点和成交量分布
    
    Args:
        prices: 价格序列
        volumes: 成交量序列（可选）
        lookback: 分析周期（默认120天，约半年交易日）
        num_levels: 返回的支撑阻力位数量
        
    Returns:
        (支撑位列表, 阻力位列表)
    """
    if not prices or len(prices) < lookback // 2:
        return [], []
    
    recent_prices = prices[-lookback:] if len(prices) >= lookback else prices
    current_price = recent_prices[-1]
    
    local_highs = []
    local_lows = []
    
    for i in range(1, len(recent_prices) - 1):
        if recent_prices[i] > recent_prices[i-1] and recent_prices[i] > recent_prices[i+1]:
            local_highs.append(recent_prices[i])
        if recent_prices[i] < recent_prices[i-1] and recent_prices[i] < recent_prices[i+1]:
            local_lows.append(recent_prices[i])
    
    support_levels = sorted([l for l in local_lows if l < current_price], reverse=True)[:num_levels]
    resistance_levels = sorted([h for h in local_highs if h > current_price])[:num_levels]
    
    return support_levels, resistance_levels


def judge_market_regime(
    prices: List[float],
    volumes: List[float] = None,
    lookback: int = 250
) -> IndicatorValue:
    """
    描述市场状态（客观描述，不作判断）
    
    综合周期阶段和趋势强度描述市场状态
    
    Args:
        prices: 价格序列
        volumes: 成交量序列
        lookback: 分析周期（默认250天，与周期阶段识别保持一致）
        
    Returns:
        IndicatorValue: 包含市场状态描述（统一使用neutral信号）
    """
    phase = identify_cycle_phase(prices, volumes, lookback)
    strength = calc_cycle_strength(prices, lookback)
    
    # 统一使用 neutral 信号，客观描述市场状态
    phase_map = {
        CyclePhaseType.ACCUMULATION.value: "筑底",
        CyclePhaseType.RISE.value: "上涨",
        CyclePhaseType.DISTRIBUTION.value: "派发",
        CyclePhaseType.DECLINE.value: "下跌"
    }
    
    phase_name = phase_map.get(phase, "未知")
    
    return IndicatorValue.neutral(
        value=strength,
        description=f"周期阶段：{phase_name}，周期强度：{strength:.1f}"
    )
