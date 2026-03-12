"""
资金面判断函数
纯函数，无副作用，用于资金流向分析
"""
from typing import List, Optional, Dict, Any
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from data.schemas.base_schema import IndicatorValue, FlowTrendType, MarginTrendType
from data.schemas.market_schema import MarketFundFlowData


def analyze_capital_flow_structure(
    fund_flow: MarketFundFlowData,
    total_turnover: float
) -> IndicatorValue:
    """
    描述资金流向结构（客观描述，不作判断）
    
    描述主力、超大单（机构）、大单、中单、小单（散户）的流向数据
    
    Args:
        fund_flow: 资金流向数据对象
        total_turnover: 总成交额（元）
        
    Returns:
        IndicatorValue: 包含详细数据描述（统一使用neutral信号）
    """
    if not fund_flow or total_turnover == 0:
        return IndicatorValue.neutral(0, "资金流向数据不足")
    
    # 单位转换：元 -> 亿元
    net_inflow_yi = fund_flow.net_amount / 100000000
    super_large_yi = fund_flow.buy_elg_amount / 100000000
    large_yi = fund_flow.buy_lg_amount / 100000000
    medium_yi = fund_flow.buy_md_amount / 100000000
    small_yi = fund_flow.buy_sm_amount / 100000000
    
    # 计算机构资金（超大+大）和散户资金（中+小）
    institutional_flow = super_large_yi + large_yi
    retail_flow = medium_yi + small_yi
    
    # 计算占比
    main_ratio = fund_flow.net_amount_rate  # 主力净流入率
    institutional_ratio = (fund_flow.buy_elg_amount + fund_flow.buy_lg_amount) / total_turnover * 100
    
    # 构建描述（客观描述，不作判断）
    description = []
    
    # 1. 总体流向
    if net_inflow_yi > 0:
        flow_desc = f"主力净流入{net_inflow_yi:.2f}亿元，净流入率{main_ratio:.2f}%"
    else:
        flow_desc = f"主力净流出{abs(net_inflow_yi):.2f}亿元，净流出率{abs(main_ratio):.2f}%"
    description.append(flow_desc)
    
    # 2. 结构分析
    structure_desc = f"超大单{super_large_yi:+.2f}亿，大单{large_yi:+.2f}亿，中单{medium_yi:+.2f}亿，小单{small_yi:+.2f}亿"
    description.append(structure_desc)
    
    # 3. 机构vs散户
    inst_retail_desc = f"机构资金(超大+大){institutional_flow:+.2f}亿，散户资金(中+小){retail_flow:+.2f}亿"
    description.append(inst_retail_desc)
        
    full_description = "；".join([d for d in description if d])
    
    # 统一使用 neutral 信号
    signal_value = main_ratio
    
    return IndicatorValue.neutral(signal_value, full_description)


def judge_flow_trend(flow_values: List[float], lookback: int = 5) -> IndicatorValue:
    """
    描述资金流向趋势（客观描述，不作判断）
    
    统计近N日资金流向数据，描述流入流出情况
    
    Args:
        flow_values: 近N日资金流向数据列表（正数为流入，负数为流出）
        lookback: 分析天数，默认5天
        
    Returns:
        IndicatorValue: 包含统计数据描述（统一使用neutral信号）
    """
    if not flow_values or len(flow_values) < lookback:
        return IndicatorValue.neutral(0, "资金流向数据不足")
    
    recent_flows = flow_values[-lookback:]
    
    positive_days = sum(1 for f in recent_flows if f > 0)
    negative_days = sum(1 for f in recent_flows if f < 0)
    
    total_flow = sum(recent_flows)
    avg_flow = total_flow / len(recent_flows)
    
    return IndicatorValue.neutral(
        value=total_flow,
        description=f"近{lookback}日：{positive_days}日净流入，{negative_days}日净流出，累计{total_flow/1e8:.2f}亿元"
    )


def calc_cumulative_flow(flow_values: List[float]) -> float:
    """
    计算累计资金流向
    
    Args:
        flow_values: 资金流向数据列表
        
    Returns:
        累计净流入金额
    """
    if not flow_values:
        return 0.0
    return sum(flow_values)


def judge_margin_trend(
    margin_balance: List[float], 
    margin_buy: List[float],
    lookback: int = 5
) -> IndicatorValue:
    """
    描述两融趋势（客观描述，不作判断）
    
    描述融资余额和融资买入额的变化数据
    
    Args:
        margin_balance: 近N日融资余额列表
        margin_buy: 近N日融资买入额列表
        lookback: 分析天数
        
    Returns:
        IndicatorValue: 包含数据描述（统一使用neutral信号）
    """
    if not margin_balance or len(margin_balance) < lookback:
        return IndicatorValue.neutral(0, "两融数据不足")
    
    recent_balance = margin_balance[-lookback:]
    
    balance_change = recent_balance[-1] - recent_balance[0]
    balance_change_pct = balance_change / recent_balance[0] * 100 if recent_balance[0] != 0 else 0
    
    increasing_days = sum(1 for i in range(1, len(recent_balance)) 
                         if recent_balance[i] > recent_balance[i-1])
    
    if margin_buy:
        recent_buy = margin_buy[-lookback:] if len(margin_buy) >= lookback else margin_buy
        avg_buy = sum(recent_buy) / len(recent_buy)
        buy_desc = f"，日均融资买入{avg_buy:.2f}亿元"
    else:
        buy_desc = "，日均融资买入额数据缺失"
    
    return IndicatorValue.neutral(
        value=balance_change_pct,
        description=f"融资余额变化{balance_change_pct:+.2f}%，近{lookback}日{increasing_days}日增加{buy_desc}"
    )


def judge_north_trading(
    north_trading_amount: float, 
    history_trading_amounts: List[float] = None,
    lookback_days: int = 10
) -> IndicatorValue:
    """
    描述北向资金交易数据（客观描述，不作判断）
    
    与近期平均水平比较，描述当日外资参与数据
    
    Args:
        north_trading_amount: 当日北向资金总交易额（亿元）
        history_trading_amounts: 历史交易额列表（亿元），按时间正序排列
        lookback_days: 回溯天数，默认10个交易日（约两周）
        
    Returns:
        IndicatorValue: 包含数据描述（统一使用neutral信号）
    """
    if north_trading_amount is None:
        return IndicatorValue.neutral(0, "北向资金数据缺失")
    
    if history_trading_amounts and len(history_trading_amounts) >= 3:
        recent_amounts = history_trading_amounts[-lookback_days:] if len(history_trading_amounts) >= lookback_days else history_trading_amounts
        valid_amounts = [a for a in recent_amounts if a is not None and a > 0]
        
        if valid_amounts:
            avg_trading_amount = sum(valid_amounts) / len(valid_amounts)
            max_amount = max(valid_amounts)
            min_amount = min(valid_amounts)
        else:
            avg_trading_amount = 1000
            max_amount = 1000
            min_amount = 1000
    else:
        avg_trading_amount = 1000
        max_amount = 1000
        min_amount = 1000
    
    if avg_trading_amount == 0:
        return IndicatorValue.neutral(0, "北向资金基准数据无效")
    
    trading_ratio = north_trading_amount / avg_trading_amount * 100
    
    return IndicatorValue.neutral(
        value=trading_ratio,
        description=f"北向资金交易额{north_trading_amount:.2f}亿元，近{lookback_days}日均值{avg_trading_amount:.2f}亿元，比率{trading_ratio:.1f}%"
    )


def judge_sector_fund_flow(
    fund_inflow: float,
    fund_inflow_rate: float
) -> IndicatorValue:
    """
    描述板块资金流向（客观描述，不作判断）
    
    Args:
        fund_inflow: 资金净流入（万元）
        fund_inflow_rate: 资金流入率（%）
        
    Returns:
        IndicatorValue: 包含数据描述（统一使用neutral信号）
    """
    if fund_inflow is None:
        return IndicatorValue.neutral(0, "板块资金数据缺失")
    
    fund_inflow_yi = fund_inflow / 10000
    
    if fund_inflow > 0:
        return IndicatorValue.neutral(
            value=fund_inflow_rate,
            description=f"板块净流入{fund_inflow_yi:.2f}亿元，流入率{fund_inflow_rate:.2f}%"
        )
    elif fund_inflow < 0:
        return IndicatorValue.neutral(
            value=fund_inflow_rate,
            description=f"板块净流出{abs(fund_inflow_yi):.2f}亿元，流出率{abs(fund_inflow_rate):.2f}%"
        )
    else:
        return IndicatorValue.neutral(
            value=fund_inflow_rate,
            description="板块资金流向平衡"
        )


def calc_flow_momentum(flow_values: List[float], short_period: int = 3, long_period: int = 10) -> float:
    """
    计算资金流动量
    
    短期累计流入 / 长期平均流入
    
    Args:
        flow_values: 资金流向数据列表
        short_period: 短期天数
        long_period: 长期天数
        
    Returns:
        资金流动量比率
    """
    if not flow_values or len(flow_values) < long_period:
        return 1.0
    
    short_flow = sum(flow_values[-short_period:])
    long_avg = sum(flow_values[-long_period:]) / long_period
    
    if long_avg == 0:
        return 1.0
    
    return short_flow / (long_avg * short_period)


def judge_market_breadth(
    adv_issues: int,
    dec_issues: int,
    market_width: Optional[float] = None,
    ad_line: Optional[float] = None,
    turnover_concentration: Optional[float] = None
) -> IndicatorValue:
    """
    描述市场广度（客观描述，不作判断）
    
    Args:
        adv_issues: 上涨家数
        dec_issues: 下跌家数
        market_width: 市场宽度指标（可选）
        ad_line: 腾落指数（可选）
        turnover_concentration: 成交额集中度（可选）
        
    Returns:
        IndicatorValue: 包含数据描述（统一使用neutral信号）
    """
    if adv_issues is None or dec_issues is None:
        return IndicatorValue.neutral(0, "市场广度数据缺失")
    
    total = adv_issues + dec_issues
    if total == 0:
        return IndicatorValue.neutral(0, "市场广度数据无效")
    
    adv_ratio = adv_issues / total * 100
    
    desc_parts = []
    
    # 客观描述涨跌家数
    desc_parts.append(f"上涨{adv_issues}家({adv_ratio:.1f}%)，下跌{dec_issues}家({100-adv_ratio:.1f}%)")
    
    # 市场宽度指标
    if market_width is not None and market_width != 0:
        desc_parts.append(f"宽度{market_width:.1f}")
    
    # 腾落指数
    if ad_line is not None:
        desc_parts.append(f"腾落指数{ad_line:.0f}")
    
    # 成交额集中度
    if turnover_concentration is not None:
        desc_parts.append(f"成交集中度{turnover_concentration:.1f}%")

    full_desc = "，".join(desc_parts)

    return IndicatorValue.neutral(adv_ratio, full_desc)
    
    



# 废弃 judge_market_fund_flow，使用 analyze_capital_flow_structure 替代
# 为了兼容性，如果还有调用，可以保留一个简单的包装或者直接删除
# 这里我们选择删除它，因为我们在重构

