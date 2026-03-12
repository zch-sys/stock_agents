"""
技术面判断函数
纯函数，无副作用，用于技术指标分析
"""
from typing import List, Optional, Tuple
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from data.schemas.base_schema import (
    IndicatorValue, SupportResistance, SignalType, PositionType
)


def judge_ma_alignment(
    ma5: float, 
    ma10: float, 
    ma20: float, 
    ma60: float,
    close: float
) -> IndicatorValue:
    """
    描述均线排列状态（客观描述，不作判断）
    
    多头排列: ma5 > ma10 > ma20 > ma60
    空头排列: ma5 < ma10 < ma20 < ma60
    纠缠: 均线相互交叉，无明显排列
    
    Args:
        ma5: 5日均线
        ma10: 10日均线
        ma20: 20日均线
        ma60: 60日均线
        close: 收盘价
        
    Returns:
        IndicatorValue: 包含排列状态描述（统一使用neutral信号）
    """
    if None in [ma5, ma10, ma20, ma60, close]:
        return IndicatorValue.neutral(0, "均线数据不完整")
    
    bullish_alignment = ma5 > ma10 > ma20 > ma60
    bearish_alignment = ma5 < ma10 < ma20 < ma60
    
    above_all = close > ma5 and close > ma10 and close > ma20 and close > ma60
    below_all = close < ma5 and close < ma10 and close < ma20 and close < ma60
    
    spread_value = (ma5 - ma60) / ma60 * 100 if ma60 != 0 else 0
    
    if bullish_alignment and above_all:
        return IndicatorValue.neutral(
            value=spread_value,
            description=f"均线多头排列：MA5({ma5:.2f})>MA10({ma10:.2f})>MA20({ma20:.2f})>MA60({ma60:.2f})，收盘价({close:.2f})位于所有均线上方"
        )
    elif bullish_alignment:
        return IndicatorValue.neutral(
            value=spread_value,
            description=f"均线多头排列：MA5({ma5:.2f})>MA10({ma10:.2f})>MA20({ma20:.2f})>MA60({ma60:.2f})"
        )
    elif bearish_alignment and below_all:
        return IndicatorValue.neutral(
            value=-spread_value,
            description=f"均线空头排列：MA5({ma5:.2f})<MA10({ma10:.2f})<MA20({ma20:.2f})<MA60({ma60:.2f})，收盘价({close:.2f})位于所有均线下方"
        )
    elif bearish_alignment:
        return IndicatorValue.neutral(
            value=-spread_value,
            description=f"均线空头排列：MA5({ma5:.2f})<MA10({ma10:.2f})<MA20({ma20:.2f})<MA60({ma60:.2f})"
        )
    else:
        ma_spread = max(ma5, ma10, ma20, ma60) - min(ma5, ma10, ma20, ma60)
        ma_avg = (ma5 + ma10 + ma20 + ma60) / 4
        spread_ratio = ma_spread / ma_avg * 100 if ma_avg != 0 else 0
        
        return IndicatorValue.neutral(
            value=spread_ratio,
            description=f"均线纠缠：MA5={ma5:.2f}，MA10={ma10:.2f}，MA20={ma20:.2f}，MA60={ma60:.2f}，均线间距{spread_ratio:.2f}%"
        )


def judge_macd_signal(
    macd: float, 
    macd_signal: float, 
    macd_hist: float
) -> IndicatorValue:
    """
    描述MACD状态（客观描述，不作判断）
    
    金叉: MACD线上穿信号线，柱状图由负转正
    死叉: MACD线下穿信号线，柱状图由正转负
    零轴位置表示当前价格与长期均价的关系
    
    Args:
        macd: MACD值（DIF）
        macd_signal: MACD信号线（DEA）
        macd_hist: MACD柱状图（MACD柱）
        
    Returns:
        IndicatorValue: 包含状态描述（统一使用neutral信号）
    """
    if None in [macd, macd_signal, macd_hist]:
        return IndicatorValue.neutral(0, "MACD数据不完整")
    
    diff = macd - macd_signal
    
    if macd > macd_signal and macd_hist > 0:
        if macd > 0 and macd_signal > 0:
            return IndicatorValue.neutral(
                value=macd_hist,
                description=f"MACD金叉且位于零轴上方：DIF={macd:.4f}，DEA={macd_signal:.4f}，柱状图={macd_hist:.4f}(正值)"
            )
        else:
            return IndicatorValue.neutral(
                value=macd_hist,
                description=f"MACD金叉：DIF={macd:.4f}上穿DEA={macd_signal:.4f}，柱状图={macd_hist:.4f}(正值)"
            )
    elif macd < macd_signal and macd_hist < 0:
        if macd < 0 and macd_signal < 0:
            return IndicatorValue.neutral(
                value=macd_hist,
                description=f"MACD死叉且位于零轴下方：DIF={macd:.4f}，DEA={macd_signal:.4f}，柱状图={macd_hist:.4f}(负值)"
            )
        else:
            return IndicatorValue.neutral(
                value=macd_hist,
                description=f"MACD死叉：DIF={macd:.4f}下穿DEA={macd_signal:.4f}，柱状图={macd_hist:.4f}(负值)"
            )
    elif macd > 0 and macd_signal > 0:
        return IndicatorValue.neutral(
            value=macd_hist,
            description=f"MACD位于零轴上方：DIF={macd:.4f}，DEA={macd_signal:.4f}，柱状图={macd_hist:.4f}"
        )
    elif macd < 0 and macd_signal < 0:
        return IndicatorValue.neutral(
            value=macd_hist,
            description=f"MACD位于零轴下方：DIF={macd:.4f}，DEA={macd_signal:.4f}，柱状图={macd_hist:.4f}"
        )
    else:
        return IndicatorValue.neutral(
            value=macd_hist,
            description=f"MACD状态：DIF={macd:.4f}，DEA={macd_signal:.4f}，柱状图={macd_hist:.4f}"
        )


def judge_adx_strength(adx: float) -> IndicatorValue:
    """
    描述ADX趋势强度（客观描述，不作判断）
    
    ADX数值含义:
    - < 20: 趋势不明显
    - 20-25: 趋势形成中
    - 25-50: 趋势明显
    - > 50: 趋势非常明显
    
    Args:
        adx: ADX指标值
        
    Returns:
        IndicatorValue: 包含数值描述（统一使用neutral信号）
    """
    if adx is None:
        return IndicatorValue.neutral(0, "ADX数据缺失")
    
    if adx < 20:
        return IndicatorValue.neutral(
            value=adx,
            description=f"ADX={adx:.2f}，趋势强度指标，数值<20表示趋势不明显"
        )
    elif adx < 25:
        return IndicatorValue.neutral(
            value=adx,
            description=f"ADX={adx:.2f}，趋势强度指标，数值20-25表示趋势形成中"
        )
    elif adx < 50:
        return IndicatorValue.neutral(
            value=adx,
            description=f"ADX={adx:.2f}，趋势强度指标，数值25-50表示趋势明显"
        )
    else:
        return IndicatorValue.neutral(
            value=adx,
            description=f"ADX={adx:.2f}，趋势强度指标，数值>50表示趋势非常明显"
        )


def calc_support_resistance(
    highs: List[float], 
    lows: List[float], 
    closes: List[float],
    current_price: float,
    ma20: Optional[float] = None,
    ma60: Optional[float] = None,
    lookback: int = 60
) -> SupportResistance:
    """
    计算支撑阻力位
    
    方法:
    - 支撑位: 近期低点、均线位置
    - 阻力位: 近期高点、均线位置
    - 当前位置判断
    
    Args:
        highs: 近期最高价列表
        lows: 近期最低价列表
        closes: 近期收盘价列表
        current_price: 当前价格
        ma20: 20日均线（可选）
        ma60: 60日均线（可选）
        lookback: 回看天数
        
    Returns:
        SupportResistance: 支撑阻力位数据
    """
    if not highs or not lows or not closes:
        return SupportResistance()
    
    recent_highs = sorted(highs[-lookback:], reverse=True)[:3]
    recent_lows = sorted(lows[-lookback:])[:3]
    
    support_levels = []
    resistance_levels = []
    
    for low in recent_lows:
        if low < current_price:
            support_levels.append(round(low, 2))
    
    for high in recent_highs:
        if high > current_price:
            resistance_levels.append(round(high, 2))
    
    if ma20 is not None:
        if ma20 < current_price:
            support_levels.append(round(ma20, 2))
        else:
            resistance_levels.append(round(ma20, 2))
    
    if ma60 is not None:
        if ma60 < current_price:
            support_levels.append(round(ma60, 2))
        else:
            resistance_levels.append(round(ma60, 2))
    
    support_levels = sorted(list(set(support_levels)), reverse=True)[:3]
    resistance_levels = sorted(list(set(resistance_levels)))[:3]
    
    position = _determine_position(current_price, support_levels, resistance_levels)
    
    return SupportResistance(
        support=support_levels,
        resistance=resistance_levels,
        current_position=position
    )


def _determine_position(
    current_price: float,
    support_levels: List[float],
    resistance_levels: List[float]
) -> str:
    """判断当前价格位置"""
    if not support_levels and not resistance_levels:
        return PositionType.MIDDLE.value
    
    nearest_support = max(support_levels) if support_levels else None
    nearest_resistance = min(resistance_levels) if resistance_levels else None
    
    if nearest_support and nearest_resistance:
        support_distance = (current_price - nearest_support) / current_price * 100
        resistance_distance = (nearest_resistance - current_price) / current_price * 100
        
        if support_distance < 2:
            return PositionType.NEAR_SUPPORT.value
        elif resistance_distance < 2:
            return PositionType.NEAR_RESISTANCE.value
    elif nearest_support:
        support_distance = (current_price - nearest_support) / current_price * 100
        if support_distance < 2:
            return PositionType.NEAR_SUPPORT.value
        elif current_price > nearest_support * 1.05:
            return PositionType.ABOVE_MA.value
    elif nearest_resistance:
        resistance_distance = (nearest_resistance - current_price) / current_price * 100
        if resistance_distance < 2:
            return PositionType.NEAR_RESISTANCE.value
        elif current_price < nearest_resistance * 0.95:
            return PositionType.BELOW_MA.value
    
    return PositionType.MIDDLE.value


def judge_rsi_signal(rsi: float, overbought: float = 70, oversold: float = 30) -> IndicatorValue:
    """
    描述RSI位置（客观描述，不作判断）
    
    Args:
        rsi: RSI值
        overbought: 超买阈值，默认70
        oversold: 超卖阈值，默认30
        
    Returns:
        IndicatorValue: 包含数值描述（统一使用neutral信号）
    """
    if rsi is None:
        return IndicatorValue.neutral(0, "RSI数据缺失")
    
    if rsi >= overbought:
        return IndicatorValue.neutral(
            value=rsi,
            description=f"RSI={rsi:.2f}，位于超买区(>{overbought})"
        )
    elif rsi <= oversold:
        return IndicatorValue.neutral(
            value=rsi,
            description=f"RSI={rsi:.2f}，位于超卖区(<{oversold})"
        )
    elif rsi > 50:
        return IndicatorValue.neutral(
            value=rsi,
            description=f"RSI={rsi:.2f}，位于中轴上方(50-70)"
        )
    else:
        return IndicatorValue.neutral(
            value=rsi,
            description=f"RSI={rsi:.2f}，位于中轴下方(30-50)"
        )


def judge_boll_position(
    close: float,
    boll_upper: float,
    boll_middle: float,
    boll_lower: float
) -> IndicatorValue:
    """
    描述布林带位置（客观描述，不作判断）
    
    Args:
        close: 收盘价
        boll_upper: 布林上轨
        boll_middle: 布林中轨
        boll_lower: 布林下轨
        
    Returns:
        IndicatorValue: 包含位置描述（统一使用neutral信号）
    """
    if None in [close, boll_upper, boll_middle, boll_lower]:
        return IndicatorValue.neutral(0, "布林带数据不完整")
    
    bandwidth = (boll_upper - boll_lower) / boll_middle * 100
    position = (close - boll_lower) / (boll_upper - boll_lower) * 100
    
    if close >= boll_upper:
        return IndicatorValue.neutral(
            value=position,
            description=f"价格位于布林上轨上方，上轨={boll_upper:.2f}，带宽{bandwidth:.2f}%"
        )
    elif close <= boll_lower:
        return IndicatorValue.neutral(
            value=position,
            description=f"价格位于布林下轨下方，下轨={boll_lower:.2f}，带宽{bandwidth:.2f}%"
        )
    elif close > boll_middle:
        return IndicatorValue.neutral(
            value=position,
            description=f"价格位于布林带上半区，位置{position:.1f}%，中轨={boll_middle:.2f}，带宽{bandwidth:.2f}%"
        )
    else:
        return IndicatorValue.neutral(
            value=position,
            description=f"价格位于布林带下半区，位置{position:.1f}%，中轨={boll_middle:.2f}，带宽{bandwidth:.2f}%"
        )


def analyze_volume_trend(
    volumes: List[float],
    current_vol: float,
    lookback: int = 10
) -> IndicatorValue:
    """
    分析成交量趋势（客观描述）
    
    趋势判断:
    - 放量趋势: 近N日成交量逐步放大
    - 缩量趋势: 近N日成交量逐步萎缩
    - 量能平稳: 成交量无明显变化
    
    Args:
        volumes: 历史成交量列表
        current_vol: 当前成交量
        lookback: 回看天数（默认10天，约两周交易日）
        
    Returns:
        IndicatorValue: 包含趋势描述
    """
    if not volumes or len(volumes) < lookback:
        return IndicatorValue.neutral(0, "成交量数据不足，无法分析趋势")
    
    if current_vol is None or current_vol <= 0:
        return IndicatorValue.neutral(0, "当前成交量数据无效")
    
    recent_vols = volumes[-lookback:]
    avg_vol = sum(recent_vols) / len(recent_vols)
    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1
    
    # 计算成交量变化趋势（线性回归斜率简化版）
    changes = []
    for i in range(1, len(recent_vols)):
        if recent_vols[i-1] > 0:
            changes.append((recent_vols[i] - recent_vols[i-1]) / recent_vols[i-1] * 100)
    
    avg_change = sum(changes) / len(changes) if changes else 0
    
    if vol_ratio > 1.5 and avg_change > 10:
        return IndicatorValue.neutral(
            value=vol_ratio,
            description=f"成交量明显放大，量比{vol_ratio:.2f}，近{lookback}日量能递增{avg_change:.1f}%"
        )
    elif vol_ratio < 0.7 and avg_change < -10:
        return IndicatorValue.neutral(
            value=vol_ratio,
            description=f"成交量明显萎缩，量比{vol_ratio:.2f}，近{lookback}日量能递减{abs(avg_change):.1f}%"
        )
    elif vol_ratio > 1.2:
        return IndicatorValue.neutral(
            value=vol_ratio,
            description=f"成交量温和放大，量比{vol_ratio:.2f}"
        )
    elif vol_ratio < 0.8:
        return IndicatorValue.neutral(
            value=vol_ratio,
            description=f"成交量温和萎缩，量比{vol_ratio:.2f}"
        )
    else:
        return IndicatorValue.neutral(
            value=vol_ratio,
            description=f"成交量平稳，量比{vol_ratio:.2f}"
        )

def judge_volume_price(
    close: float,
    pct_chg: float,
    vol: float,
    vol_ma5: float,
    pct_chg_prev: float = None
) -> IndicatorValue:
    """
    分析量价关系（客观描述）

    描述方式：仅陈述价格变动幅度、成交量与5日均量的比值，
    以及（如果提供前一日涨跌幅）连续两日的价格方向。

    Args:
        close: 收盘价
        pct_chg: 当日涨跌幅（%）
        vol: 当日成交量
        vol_ma5: 5日均量
        pct_chg_prev: 前一日涨跌幅（可选，用于描述连续趋势）

    Returns:
        IndicatorValue: 包含量价状态描述，信号始终为中性
    """
    if None in [close, pct_chg, vol, vol_ma5]:
        return IndicatorValue.neutral(0, "量价数据不完整")

    if vol_ma5 is None or vol_ma5 <= 0:
        return IndicatorValue.neutral(0, "均量数据无效")

    vol_ratio = vol / vol_ma5

    # 根据涨跌幅幅度分类描述
    if pct_chg > 0.5:
        direction = "上涨"
    elif pct_chg < -0.5:
        direction = "下跌"
    else:
        direction = "窄幅波动"

    # 量比描述
    if vol_ratio > 1.3:
        vol_desc = f"量比{vol_ratio:.2f}，高于1.3"
    elif vol_ratio < 0.8:
        vol_desc = f"量比{vol_ratio:.2f}，低于0.8"
    else:
        vol_desc = f"量比{vol_ratio:.2f}，处于0.8-1.3区间"

    # 构建基础描述
    base_desc = f"当日{direction}{abs(pct_chg):.2f}%，{vol_desc}"

    # 如果提供了前一日涨跌幅，添加连续趋势信息
    if pct_chg_prev is not None:
        if pct_chg_prev > 0.5:
            prev_direction = "上涨"
        elif pct_chg_prev < -0.5:
            prev_direction = "下跌"
        else:
            prev_direction = "窄幅波动"
        base_desc += f"；前一日{prev_direction}{abs(pct_chg_prev):.2f}%"

    return IndicatorValue.neutral(value=vol_ratio, description=base_desc)