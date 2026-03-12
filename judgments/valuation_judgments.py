"""
估值数据计算函数
纯函数，无副作用，只计算客观数据，不作判断
"""
from typing import List, Optional
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from data.schemas.base_schema import ValuationLevel


def calc_percentile_rank(current_value: float, historical_values: List[float]) -> float:
    """
    计算当前值在历史数据中的百分位
    
    Args:
        current_value: 当前值
        historical_values: 历史数据列表
        
    Returns:
        0-100的百分位值
    """
    if not historical_values or current_value is None:
        return 50.0
    
    valid_values = [v for v in historical_values if v is not None and v > 0]
    if not valid_values:
        return 50.0
    
    count_below = sum(1 for v in valid_values if v < current_value)
    count_equal = sum(1 for v in valid_values if v == current_value)
    
    percentile = (count_below + 0.5 * count_equal) / len(valid_values) * 100
    
    return round(percentile, 2)


def calc_graham_index(pe_ttm: float, risk_free_rate: float = 0.025) -> Optional[float]:
    """
    计算改良版格雷厄姆指数
    
    公式：格雷厄姆指数 = PE_TTM的倒数 / (无风险利率 × 2)
    
    其中：
    - PE_TTM倒数 = 盈利收益率（E/P）
    - 无风险利率 = 10年期国债收益率（默认2.5%）
    - 乘数2代表投资者要求的风险溢价
    
    参考标准：
    - > 1.0: 盈利收益率高于债券收益率2倍
    - 0.5-1.0: 盈利收益率适中
    - < 0.5: 盈利收益率偏低
    
    Args:
        pe_ttm: 市盈率TTM
        risk_free_rate: 无风险利率（默认2.5%）
        
    Returns:
        格雷厄姆指数，如果无法计算返回None
    """
    if pe_ttm is None or pe_ttm <= 0:
        return None
    
    if risk_free_rate is None or risk_free_rate <= 0:
        risk_free_rate = 0.025  # 默认2.5%
    
    # 盈利收益率 = 1 / PE_TTM
    earnings_yield = 1.0 / pe_ttm
    
    # 格雷厄姆指数 = 盈利收益率 / (无风险利率 × 2)
    graham_index = earnings_yield / (risk_free_rate * 2)
    
    return round(graham_index, 3)


def interpret_graham_index(graham_index: float) -> str:
    """
    生成格雷厄姆指数的解读文本
    
    Args:
        graham_index: 格雷厄姆指数
        
    Returns:
        解读文本
    """
    if graham_index is None:
        return "格雷厄姆指数无法计算"
    
    if graham_index > 1.0:
        return f"格雷厄姆指数={graham_index:.2f}(>1.0)，盈利收益率高于债券收益率2倍，安全边际较高"
    elif graham_index < 0.5:
        return f"格雷厄姆指数={graham_index:.2f}(<0.5)，盈利收益率偏低，估值较高"
    else:
        return f"格雷厄姆指数={graham_index:.2f}(0.5-1.0)，盈利收益率适中，估值合理"


def calc_valuation_data(
    pe_ttm: float,
    pb: float,
    pe_percentile: float,
    pb_percentile: float,
    risk_free_rate: float = 0.025
) -> ValuationLevel:
    """
    计算估值客观数据
    
    只计算和返回客观数据，不作估值等级判断：
    - PE、PB及其百分位
    - 格雷厄姆指数及其解读
    
    Args:
        pe_ttm: 市盈率TTM
        pb: 市净率
        pe_percentile: PE百分位
        pb_percentile: PB百分位
        risk_free_rate: 无风险利率（默认2.5%）
        
    Returns:
        ValuationLevel: 估值客观数据
    """
    # 计算格雷厄姆指数
    graham_index = calc_graham_index(pe_ttm, risk_free_rate)
    graham_desc = interpret_graham_index(graham_index)
    
    return ValuationLevel(
        pe=pe_ttm or 0,
        pb=pb or 0,
        pe_percentile=pe_percentile,
        pb_percentile=pb_percentile,
        graham_index=graham_index,
        graham_desc=graham_desc
    )