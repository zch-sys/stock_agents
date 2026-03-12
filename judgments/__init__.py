"""
判断函数库模块
"""
from data.judgments.technical_judgments import (
    judge_ma_alignment,
    judge_macd_signal,
    judge_adx_strength,
    calc_support_resistance,
    judge_rsi_signal,
    judge_boll_position,
    judge_volume_price
)
from data.judgments.capital_judgments import (
    judge_flow_trend,
    calc_cumulative_flow,
    judge_margin_trend,
    analyze_capital_flow_structure,
    judge_north_trading,
    calc_flow_momentum,
    judge_market_breadth
)
from data.judgments.valuation_judgments import (
    calc_percentile_rank,
    calc_graham_index,
    interpret_graham_index,
    calc_valuation_data
)
from data.judgments.cycle_judgments import (
    identify_cycle_phase,
    get_cycle_description,
    judge_cycle_phase_with_signal,
    calc_cycle_strength,
    identify_support_resistance_levels,
    judge_market_regime
)

__all__ = [
    'judge_ma_alignment',
    'judge_macd_signal',
    'judge_adx_strength',
    'calc_support_resistance',
    'judge_rsi_signal',
    'judge_boll_position',
    'judge_volume_price',
    'judge_flow_trend',
    'calc_cumulative_flow',
    'judge_margin_trend',
    'judge_north_trading',
    'analyze_capital_flow_structure',
    'calc_flow_momentum',
    'judge_market_breadth',
    'calc_percentile_rank',
    'calc_graham_index',
    'interpret_graham_index',
    'calc_valuation_data',
    'identify_cycle_phase',
    'get_cycle_description',
    'judge_cycle_phase_with_signal',
    'calc_cycle_strength',
    'identify_support_resistance_levels',
    'judge_market_regime'
]
