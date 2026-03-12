"""
大盘分析师Prompt工具函数

包含格式化数据的辅助函数和分维度分析Prompt模板。
用于支持 MarketAnalyst 的分维度分析流程。
"""

from typing import Dict, Any, List, Optional

# ==================== System Prompt ====================

SYSTEM_PROMPT_MARKET_ANALYST = """你是资深A股大盘分析师，具备以下专业能力：

角色定位
- **技术分析专家**：精通均线、MACD、ADX等技术指标
- **资金分析专家**：熟悉北向资金、两融、主力资金流向
- **情绪分析专家**：把握市场情绪、涨跌家数、市场广度
- **估值周期专家**：掌握PE/PB估值、市场周期判断
- **新闻分析专家**：解读财经新闻对市场的影响
- **复盘专家**：擅长从过去的分析报告中提取有效经验

A股市场特征
- **交易制度**：T+1交易，主板涨跌停10%，创业板/科创板20%
- **投资者结构**：散户为主，机构占比提升中，国家资金对市场影响重大
- **市场特点**：政策敏感度高，情绪波动大，板块轮动快
- **资金特征**：北向资金影响显著，两融反映杠杆情绪，主力与散户行为差异大
- **指数构成**：上证指数代表大盘蓝筹，深证成指代表中盘成长，创业板指代表新兴科技

分析原则
1. **客观中立**：基于数据事实分析，不带主观偏见
2. **多维验证**：综合多个维度交叉验证结论
3. **风险优先**：始终关注风险因素，保护资金安全
4. **逻辑清晰**：分析结论有理有据，推理过程透明

输出规范
- **严格按照 JSON 格式输出**
- **文字描述简洁专业，避免模糊表述**
- **数值保留2位小数**

分析框架
根据任务类型，运用相应的专业知识和分析方法，
给出结构化、可量化的分析结论。"""

INDEX_NAMES = {
    '000001.SH': '上证指数',
    '399001.SZ': '深证成指',
    '399006.SZ': '创业板指'
}

def format_news_data(news_list: list) -> str:
    """
    格式化新闻数据（包含标题和内容）
    
    Args:
        news_list: 新闻列表，每条包含 title, content, publish_time, source
        
    Returns:
        格式化后的文本
    """
    if not news_list:
        return "暂无最近24小时新闻数据"
    
    lines = ["近期财经新闻\n"]
    for i, news in enumerate(news_list, 1):
        time_str = news.get('publish_time', '')
        title = news.get('title', '')
        content = news.get('content', '')
        
        lines.append(f"{i}. {title}")
        lines.append(f"时间: {time_str}")
        if content:
            lines.append(f"内容: {content}")
        lines.append("")  # 空行分隔
    
    return "\n".join(lines)
# ==================== 分维度分析Prompt模板 ====================

def format_history_analysis(recent_reports: List[Dict[str, Any]], dimension: str) -> str:
    """
    格式化历史分析记录（从已保存的MarketReport中提取分析结论）
    
    Args:
        recent_reports: 最近报告列表（来自短期记忆，结构为 MarketReport.to_dict()）
        dimension: 维度名称 (technical/capital/sentiment/valuation/cycle)
        
    Returns:
        格式化后的历史分析文本
    """
    if not recent_reports:
        return "暂无历史分析记录"
    
    dimension_map = {
        'technical': 'technical',
        'capital': 'capital',
        'sentiment': 'sentiment',
        'valuation': 'valuation',
        'cycle': 'cycle'
    }
    
    # 维度对应的关键字段（用于提取核心分析内容）
    dimension_key_fields = {
        'technical': ['trend_analysis', 'ma_status', 'macd_signal', 'adx_analysis', 'volume_analysis', 'summary'],
        'capital': ['north_flow_analysis', 'margin_analysis', 'main_flow_analysis', 'capital_summary'],
        'sentiment': ['breadth', 'description', 'emotion_state', 'summary'],
        'valuation': ['valuation_analysis', 'safety_margin', 'graham_index', 'valuation_level'],
        'cycle': ['cycle_analysis', 'cycle_phase', 'cycle_features']
    }
    
    # 过滤掉 None 和空字典
    valid_reports = [r for r in recent_reports if r and isinstance(r, dict)]
    if not valid_reports:
        return "暂无历史分析记录"
    
    lines = [f"过去{len(valid_reports)}个交易日{dimension}分析记录\n"]
    
    for report in valid_reports:
        trade_date = report.get('trade_date', '未知日期')
        content = report.get('content', {})
        
        # 直接从 content.data 获取报告数据
        data = content.get('data', {})
        
        # 从 MarketReport 结构中获取对应维度的分析结果
        dim_key = dimension_map.get(dimension, dimension)
        dim_data = data.get(dim_key, {})
        
        # 获取当日指数摘要数据（用于展示原始行情）
        index_summaries = data.get('index_summaries', [])
        
        lines.append(f"**{trade_date}**:")
        
        # 展示当日基础价格数据（从 index_summaries 提取，仅保留开盘/最高/最低/收盘/涨跌幅）
        if index_summaries and isinstance(index_summaries, list):
            lines.append("  当日行情:")
            for idx in index_summaries:
                name = idx.get('name', idx.get('ts_code', ''))
                open_val = idx.get('open', 0)
                high_val = idx.get('high', 0)
                low_val = idx.get('low', 0)
                close = idx.get('close', 0)
                pct_chg = idx.get('pct_chg', 0)
                lines.append(f"    {name}: 开盘{open_val:.2f}, 最高{high_val:.2f}, 最低{low_val:.2f}, 收盘{close:.2f}, 涨跌{pct_chg:+.2f}%")
        
        # 展示该维度的核心分析结论
        key_fields = dimension_key_fields.get(dimension, [])
        if isinstance(dim_data, dict) and dim_data:
            lines.append(f"  {dimension}分析结论:")
            
            # 优先展示关键字段
            for key in key_fields:
                value = dim_data.get(key)
                if value is None:
                    continue
                if isinstance(value, str):
                    if len(value) > 10:
                        display_val = value[:200] + "..." if len(value) > 200 else value
                        lines.append(f"    - {key}: {display_val}")
                elif isinstance(value, list):
                    if value:
                        display_items = [str(v) for v in value[:3] if v]
                        if display_items:
                            lines.append(f"    - {key}: {', '.join(display_items)}")
                elif isinstance(value, (int, float)) and value != 0:
                    lines.append(f"    - {key}: {value}")
            
            # 展示其他字段（如果有）
            for key, value in dim_data.items():
                if key in key_fields:
                    continue  # 跳过已展示的字段
                if value is None:
                    continue
                if isinstance(value, str):
                    if len(value) > 10:
                        display_val = value[:150] + "..." if len(value) > 150 else value
                        lines.append(f"    - {key}: {display_val}")
                elif isinstance(value, list):
                    if value:
                        display_items = [str(v) for v in value[:2] if v]
                        if display_items:
                            lines.append(f"    - {key}: {', '.join(display_items)}")
        
        # 添加综合总结（如果存在）
        summary = data.get('summary', '') or content.get('summary', '')
        if summary and len(summary) > 10:
            lines.append(f"  综合总结: {summary[:150]}...")
        
        lines.append("")
    
    return "\n".join(lines)




def build_technical_analysis_prompt(
    index_data: Dict[str, Any],
    recent_reports: List[Dict[str, Any]],
    trade_date: str = ""
) -> str:
    """
    构建技术分析Prompt
    
    Args:
        index_data: 指数数据
        recent_reports: 最近报告列表
        trade_date: 交易日期
        
    Returns:
        技术分析Prompt
    """
    # 格式化当日技术数据
    tech_parts = []
    for code in ['000001.SH', '399001.SZ', '399006.SZ']:
        if code in index_data:
            data = index_data[code]
            if hasattr(data, 'to_dict'):
                data_dict = data.to_dict()
            else:
                data_dict = data
            
            name = INDEX_NAMES.get(code, code)
            price_data = data_dict.get('price_data', {})
            technical_data = data_dict.get('technical_data', {})
            ma_alignment = data_dict.get('ma_alignment', {})
            macd_signal = data_dict.get('macd_signal', {})
            adx_strength = data_dict.get('adx_strength',{})
            support_resistance = data_dict.get('support_resistance', {})
            volume_analysis = data_dict.get('volume_analysis', {})
            volume_trend = data_dict.get('volume_trend', {})
            
            tech_parts.append(f"""
{name} ({code})

价格数据:
- 开盘价: {price_data.get('open', 0):.2f}
- 最高价: {price_data.get('high', 0):.2f}
- 最低价: {price_data.get('low', 0):.2f}
- 收盘价: {price_data.get('close', 0):.2f}
- 涨跌幅: {price_data.get('pct_chg', 0):.2f}%
- 成交额: {price_data.get('amount', 0)/1000000000:,.2f} 万亿元

技术指标:
- 均线: MA5={technical_data.get('ma5', 0):.2f}, MA10={technical_data.get('ma10', 0):.2f}, MA20={technical_data.get('ma20', 0):.2f}, MA60={technical_data.get('ma60', 0):.2f}
- MACD: DIF={technical_data.get('macd', 0):.2f}, DEA={technical_data.get('macd_signal', 0):.2f}, 柱={technical_data.get('macd_hist', 0):.2f}
- ADX: {technical_data.get('adx', 0):.2f}

成交量分析:
- 量价关系: {volume_analysis.get('description', 'N/A')}
- 量能趋势: {volume_trend.get('description', 'N/A')}
- 量比: {technical_data.get('vol_ratio', 1):.2f}

初步信号:
- 均线状态: {ma_alignment.get('description', 'N/A')}
- MACD信号: {macd_signal.get('description', 'N/A')}
- ADX强度：{adx_strength.get('description','N/A')}

支撑阻力位:
- 支撑位: {support_resistance.get('support', [])}
- 阻力位: {support_resistance.get('resistance', [])}
- 当前位置: {support_resistance.get('current_position', 'N/A')}
""")
    
    # 格式化历史分析
    history_text = format_history_analysis(recent_reports, 'technical')
    
    prompt = f"""技术分析任务

分析日期: {trade_date}

你现在的任务是，基于以下数据进行**技术面**分析。

当日技术数据

{''.join(tech_parts)}

---
以下是过去几天的技术分析记录，作为重要的历史依据，供参考：
{history_text}

---
分析要求

请分析技术面情况，分析当前状态。

分析内容:
1. **趋势分析**: 当前趋势方向、趋势强度
2. **均线状态**: 均线排列情况、支撑/压力位置
3. **MACD信号**: 金叉/死叉、零轴位置、柱状图变化
4. **ADX分析**: 趋势强度判断
5. **成交量分析**: 量价关系、量能趋势
6. **关键位置**: 重要的支撑位和阻力位

---

输出格式

请严格按照以下JSON格式输出：

```json
{{
    "trend_analysis": "趋势分析文本（100-150字）",
    "ma_status": "均线状态描述（80-100字）",
    "macd_signal": "MACD信号描述（80-100字）",
    "adx_analysis": "ADX分析（60-80字）",
    "volume_analysis": "成交量分析：量价关系与趋势（80-120字）",
    "key_observations": ["关键观察点1", "关键观察点2", "关键观察点3"],
    "summary": "技术面总结（100-150字）"
}}
```
"""
    return prompt


def build_capital_analysis_prompt(
    index_data: Dict[str, Any],
    recent_reports: List[Dict[str, Any]],
    trade_date: str = ""
) -> str:
    """
    构建资金分析Prompt
    
    Args:
        index_data: 指数数据
        recent_reports: 最近报告列表
        trade_date: 交易日期
        
    Returns:
        资金分析Prompt
    """
    sh_data = index_data.get('000001.SH', {})
    if hasattr(sh_data, 'to_dict'):
        sh_data_dict = sh_data.to_dict()
    else:
        sh_data_dict = sh_data
    
    capital_data = sh_data_dict.get('capital_data', {})
    fund_flow_data = sh_data_dict.get('fund_flow_data', {})
    north_flow = sh_data_dict.get('north_flow', {})
    margin_trend = sh_data_dict.get('margin_trend', {})

    # 单位转换
    north_yi = capital_data.get('north_money_total', 0) / 100000000 if capital_data.get('north_money_total') else 0
    margin_yi = capital_data.get('margin_balance', 0) / 100000000 if capital_data.get('margin_balance') else 0
    net_yi = fund_flow_data.get('net_amount', 0) / 100000000 if fund_flow_data.get('net_amount') else 0
    
    history_text = format_history_analysis(recent_reports, 'capital')
    
    prompt = f"""资金分析任务

分析日期: {trade_date}

你现在的任务是，基于以下数据进行**资金面**分析。

当日资金数据

北向资金:
- 总交易额: {north_yi:.2f}亿
- 活跃度: {north_flow.get('description', 'N/A')}

两融数据:
- 融资余额: {margin_yi:.2f}亿
- 趋势: {margin_trend.get('description', 'N/A')}

资金流向:
- 主力净流入: {net_yi:.2f}亿 (净流入率: {fund_flow_data.get('net_amount_rate', 0):.2f}%)
- 超大单: {fund_flow_data.get('buy_elg_amount', 0) / 100000000 if fund_flow_data.get('buy_elg_amount') else 0:.2f}亿
- 大单: {fund_flow_data.get('buy_lg_amount', 0) / 100000000 if fund_flow_data.get('buy_lg_amount') else 0:.2f}亿
- 中单: {fund_flow_data.get('buy_md_amount', 0) / 100000000 if fund_flow_data.get('buy_md_amount') else 0:.2f}亿
- 小单: {fund_flow_data.get('buy_sm_amount', 0) / 100000000 if fund_flow_data.get('buy_sm_amount') else 0:.2f}亿

---
以下是过去几天的资金分析记录，作为重要的历史依据，供参考：
{history_text}

---

分析要求

请分析资金面情况，分析当前状态。

分析内容:
1. **北向资金分析**: 外资活跃度、流入流出趋势
2. **两融分析**: 融资余额变化、杠杆资金意愿
3. **主力资金动向**：判断当前市场资金是流入还是流出，幅度如何
4. **大单与小单情况**：分析是否存在主力吸筹或派发行为
5. **资金流向与指数走势的关系**：是否出现背离

---

输出格式

请严格按照以下JSON格式输出：

```json
{{ 
    "north_flow_analysis": "北向资金分析（100-150字）",
    "margin_analysis": "两融分析（100-120字）",
    "main_flow_analysis": "主力资金分析（100-150字）",
    "capital_summary": "资金面总结（100-150字）"
}}
```
"""
    return prompt


def build_sentiment_analysis_prompt(
    index_data: Dict[str, Any],
    recent_reports: List[Dict[str, Any]],
    trade_date: str = ""
) -> str:
    """
    构建情绪分析Prompt
    
    Args:
        index_data: 指数数据
        recent_reports: 最近报告列表
        trade_date: 交易日期
        
    Returns:
        情绪分析Prompt
    """
    sh_data = index_data.get('000001.SH', {})
    if hasattr(sh_data, 'to_dict'):
        sh_data_dict = sh_data.to_dict()
    else:
        sh_data_dict = sh_data
    
    sentiment = sh_data_dict.get('sentiment', {})
    
    history_text = format_history_analysis(recent_reports, 'sentiment')
    
    prompt = f"""情绪分析任务

分析日期: {trade_date}

你现在的任务是，请基于以下数据进行**情绪面**分析。

当日情绪数据

市场广度:
- 上涨家数: {sentiment.get('adv_issues', 0)}
- 下跌家数: {sentiment.get('dec_issues', 0)}
- 市场宽度: {sentiment.get('market_width', 0):.1f}%
- 涨跌比: {sentiment.get('adv_decline_ratio', 0):.2f}
- 腾落指数: {sentiment.get('ad_line', 0):.2f}
- 成交额集中度: {sentiment.get('turnover_concentration', 0):.2f}%  
- 情绪分数: {sentiment.get('sentiment_score', 50):.1f} （情绪分数是一个综合反映市场情绪的指标，范围为0-100分）

---
以下是过去几天的情绪分析记录，作为重要的历史依据，供参考：
{history_text}

---

分析要求

请分析市场情绪情况，分析当前状态。

分析内容:
1. **市场广度分析**: 涨跌家数、市场参与度
2. **情绪评分**: 当前情绪水平、极端程度
3. **情绪特征**: 极度恐惧-恐惧-中性-贪婪-极度贪婪

---

输出格式

请严格按照以下JSON格式输出：

```json
{{
    "market_breadth": "市场广度分析（80-100字）",
    "sentiment_analysis": "情绪分析（80-120字）",
    "emotion_state": "极度贪婪/恐惧/中性/贪婪/极度贪婪",
    "summary": "情绪面总结（80-100字）"
}}
```
"""
    return prompt


def build_valuation_cycle_analysis_prompt(
    index_data: Dict[str, Any],
    recent_reports: List[Dict[str, Any]],
    trade_date: str = ""
) -> str:
    """
    构建估值与周期分析Prompt（包含三个指数的估值数据和结构化周期数据）
    
    Args:
        index_data: 指数数据
        recent_reports: 最近报告列表
        trade_date: 交易日期
        
    Returns:
        估值与周期分析Prompt
    """
    # 格式化三个指数的估值数据
    valuation_parts = []
    for code in ['000001.SH', '399001.SZ', '399006.SZ']:
        if code in index_data:
            data = index_data[code]
            if hasattr(data, 'to_dict'):
                data_dict = data.to_dict()
            else:
                data_dict = data
            
            name = INDEX_NAMES.get(code, code)
            valuation = data_dict.get('valuation', {})
            
            # 计算格雷厄姆指数（如果PE有效）
            pe_val = valuation.get('pe', 0)
            import sys
            import os
            judgments_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            sys.path.insert(0, judgments_path)
            from data.judgments.valuation_judgments import calc_graham_index, interpret_graham_index
            
            graham_index = calc_graham_index(pe_val) if pe_val and pe_val > 0 else None
            if graham_index is not None:
                graham_desc = interpret_graham_index(graham_index)
            else:
                graham_desc = None, "无法计算"
            
            valuation_parts.append(f"""
{name} ({code})
- PE: {valuation.get('pe', 0):.2f}
- PB: {valuation.get('pb', 0):.2f}
- PE百分位: {valuation.get('pe_percentile', 50):.1f}%
- PB百分位: {valuation.get('pb_percentile', 50):.1f}%
- 格雷厄姆指数: {graham_index if graham_index else 'N/A'}
- 格雷厄姆解读: {graham_desc}
""")
    
    # 提取结构化周期数据（从上证指数）
    sh_data = index_data.get('000001.SH', {})
    if hasattr(sh_data, 'to_dict'):
        sh_data_dict = sh_data.to_dict()
    else:
        sh_data_dict = sh_data
    
    # 获取周期分析数据
    cycle_phase = sh_data_dict.get('cycle_phase', 'SHOCK')
    cycle_strength = sh_data_dict.get('cycle_strength', 0)
    market_regime = sh_data_dict.get('market_regime', {})
    
    # 周期阶段中文映射
    cycle_phase_cn = {
        'ACCUMULATION': '筑底',
        'RISING': '上涨',
        'DISTRIBUTION': '筑顶',
        'FALLING': '下跌',
        'SHOCK': '震荡'
    }
    
    cycle_data_section = f"""
结构化周期分析（基于250日数据计算，仅供参考）:
- 周期阶段: {cycle_phase_cn.get(cycle_phase, cycle_phase)} ({cycle_phase})
- 周期强度: {cycle_strength:.1f}/100
- 市场状态: {market_regime.get('description', 'N/A') if isinstance(market_regime, dict) else 'N/A'}
"""
    
    history_val = format_history_analysis(recent_reports, 'valuation')
    history_cycle = format_history_analysis(recent_reports, 'cycle')
    
    prompt = f"""估值与周期分析任务

分析日期: {trade_date}

你现在的任务是，请基于以下数据进行**估值水平**和**市场周期**分析。

当日估值数据（三大指数）

{''.join(valuation_parts)}

---

{cycle_data_section}

---
以下是过去几天的估值分析和周期分析记录，作为重要的历史依据，供参考：

估值历史
{history_val}

周期历史
{history_cycle}

---

分析要求

请分析估值与周期情况，分析当前状态。

分析内容:

估值分析:
1. **综合三个指数的PE/PB百分位，以及格雷厄姆指数判断整体估值水平**
2. **估值的安全边际**
3. **投资价值判断**

周期分析:
1. **结合结构化周期数据判断当前市场周期阶段**（筑底/上涨/筑顶/下跌/震荡）
2. **周期特征**
3. **周期持续性判断**
4. **注意：结构化周期数据仅供参考，请结合技术面综合判断**

---

输出格式

请严格按照以下JSON格式输出：

```json
{{
    "valuation": {{
        "graham_index": {graham_index:.2f},
        "valuation_level": "LOW/MEDIUM/HIGH",
        "valuation_analysis": "估值分析（80-120字，综合三个指数分析）",
        "safety_margin": "安全边际评估（60-80字）"
    }},
    "cycle": {{
        "cycle_phase": "ACCUMULATION/RISING/DISTRIBUTION/FALLING/SHOCK",
        "cycle_analysis": "周期分析（80-120字）",
        "cycle_features": ["周期特征1", "周期特征2"]
    }},
    "summary": "估值与周期综合总结（80-120字）"
}}
```
"""
    return prompt


def build_news_analysis_prompt(news_data: List[Dict[str, Any]], trade_date: str = "") -> str:
    """
    构建新闻分析Prompt
    
    Args:
        news_data: 新闻数据列表
        trade_date: 交易日期
        
    Returns:
        新闻分析Prompt
    """
    news_text = format_news_data(news_data)
    
    prompt = f"""新闻分析任务

分析日期: {trade_date}

你现在的任务是，请基于以下**新闻数据**进行分析。

{news_text}

---

分析要求

请分析新闻对市场的影响。

分析内容:
1. **关键新闻**: 最重要的3-5条新闻要点
2. **利好因素**: 从新闻中提炼的利好因素
3. **利空因素**: 从新闻中提炼的利空因素
4. **关注板块**: 新闻中涉及的热点板块

---

输出格式

请严格按照以下JSON格式输出：

```json
{{
    "key_news": ["关键新闻1", "关键新闻2", "关键新闻3"],
    "positive_factors": ["利好因素1", "利好因素2"],
    "negative_factors": ["利空因素1", "利空因素2"],
    "sector_focus": ["关注板块1", "关注板块2"],
    "news_summary": "新闻分析总结（100-150字，不包含预测）"
}}
```
"""
    return prompt


def build_review_prompt(
    reports: List[Dict[str, Any]], 
    verifications: List[Dict[str, Any]]
) -> str:
    """
    构建复盘模式 Prompt
    
    Args:
        reports: 近期分析报告列表
        verifications: 预测验证结果列表
        
    Returns:
        复盘 Prompt 字符串
    """
    # 内联格式化报告
    if not reports:
        reports_text = "暂无近期分析报告"
    else:
        report_lines = []
        for i, report in enumerate(reports, 1):
            trade_date = report.get('trade_date', '未知')
            content = report.get('content', {})
            trend = content.get('trend_direction', '未知')
            confidence = content.get('confidence', 50)
            report_lines.append(f"### 第{i}天 ({trade_date})\n- 预测方向: {trend}\n- 置信度: {confidence}\n")
        reports_text = "\n".join(report_lines)
    
    # 内联格式化验证结果
    if not verifications:
        verification_text = "暂无验证结果"
    else:
        correct_count = sum(1 for v in verifications if v.get("correct"))
        total = len(verifications)
        accuracy = correct_count / total * 100 if total > 0 else 0
        ver_lines = [f"准确率: {correct_count}/{total} ({accuracy:.1f}%)\n"]
        for v in verifications:
            status = "✓" if v.get("correct") else "✗"
            ver_lines.append(f"- [{v.get('date', '未知')}] 预测: {v.get('predicted', 'N/A')} | 实际: {v.get('actual', 'N/A')} {status}")
        verification_text = "\n".join(ver_lines)
    
    prompt = f"""复盘分析任务

你现在的任务是，基于以下近期分析报告和预测验证结果进行**复盘分析**。

近期分析报告汇总

{reports_text}

---

预测验证结果

{verification_text}

---

分析要求

请进行复盘分析，提取可复用的经验教训。

分析内容:
1. **市场走势回顾**: 近期市场整体走势特点
2. **预测归因分析**: 预测准确/失误的原因分析
3. **经验提炼**: 提取可复用的经验教训

---

输出格式

请严格按照以下JSON格式输出：

```json
{{
    "market_review": "市场走势回顾（150-200字）",
    "prediction_analysis": "预测归因分析（150-200字）",
    "success_factors": ["预测成功的关键因素1", "预测成功的关键因素2"],
    "failure_factors": ["预测失误的主要原因1", "预测失误的主要原因2"],
    "lessons": ["经验:教训1", "经验:教训2", "经验:教训3"],
    "summary": "复盘总结（100-150字）"
}}
```

注意: `lessons` 字段中的每条经验必须以 "经验:" 开头。
"""
    return prompt


def build_synthesis_prompt(
    technical_result: Dict[str, Any],
    capital_result: Dict[str, Any],
    sentiment_result: Dict[str, Any],
    valuation_cycle_result: Dict[str, Any],
    news_result: Dict[str, Any],
    long_term_memory: List[Dict[str, Any]],
    trade_date: str,
    prediction_verification: str = ""
) -> str:
    """
    构建综合判断Prompt
    
    Args:
        technical_result: 技术分析结果
        capital_result: 资金分析结果
        sentiment_result: 情绪分析结果
        valuation_cycle_result: 估值周期分析结果
        news_result: 新闻分析结果
        long_term_memory: 长期记忆
        trade_date: 交易日期
        prediction_verification: 昨日预测验证文本（分析时使用）
        
    Returns:
        综合判断Prompt
    """
    # 格式化长期记忆
    if long_term_memory:
        ltm_text = ""
        for i, mem in enumerate(long_term_memory[:3], 1):
            ltm_text += f"{i}. {mem.get('content', '')}\n"
    else:
        ltm_text = "暂无历史经验记录"
    
    # 🆕 构建预测验证部分
    if prediction_verification:
        verification_section = f"""
---

{prediction_verification}

"""
    else:
        verification_section = """
---

### 昨日预测验证

暂无昨日预测验证

"""
    
    prompt = f"""综合分析任务

你现在的任务是，请基于以下各维度分析结果进行**综合判断**。

分析日期: {trade_date}

---

技术面分析

- 趋势分析: {technical_result.get('trend_analysis', 'N/A')}
- 均线状态: {technical_result.get('ma_status', 'N/A')}
- MACD信号: {technical_result.get('macd_signal', 'N/A')}
- ADX分析: {technical_result.get('adx_analysis', 'N/A')}
- 技术总结: {technical_result.get('summary', 'N/A')}

---

资金面分析

- 北向资金: {capital_result.get('north_flow_analysis', 'N/A')}
- 两融分析: {capital_result.get('margin_analysis', 'N/A')}
- 主力资金: {capital_result.get('main_flow_analysis', 'N/A')}
- 资金总结: {capital_result.get('capital_summary', 'N/A')}

---

情绪面分析

- 市场广度: {sentiment_result.get('market_breadth', 'N/A')}
- 情绪状态: {sentiment_result.get('emotion_state', 'N/A')}
- 情绪总结: {sentiment_result.get('summary', 'N/A')}

---

估值与周期分析

- 估值水平: {valuation_cycle_result.get('valuation', {}).get('valuation_level', 'N/A')}
- 估值分析: {valuation_cycle_result.get('valuation', {}).get('valuation_analysis', 'N/A')}
- 周期阶段: {valuation_cycle_result.get('cycle', {}).get('cycle_phase', 'N/A')}
- 周期分析: {valuation_cycle_result.get('cycle', {}).get('cycle_analysis', 'N/A')}
- 综合总结: {valuation_cycle_result.get('summary', 'N/A')}

---

新闻分析

- 关键新闻: {news_result.get('key_news', [])}
- 利好因素: {news_result.get('positive_factors', [])}
- 利空因素: {news_result.get('negative_factors', [])}
- 关注板块: {news_result.get('sector_focus', [])}
- 新闻总结: {news_result.get('news_summary', 'N/A')}

---

以下是相关的历史经验，供参考：
{ltm_text}
{verification_section}
分析要求

请进行综合判断。

输出内容:

1. **市场状态判断**: STRONG（强势）/ SHOCK（震荡）/ WEAK（弱势）
2. **分指数预测**: 分别预测上证指数、深证成指、创业板指下一交易日的走势
   - 上证指数 (000001.SH): UP/SIDEWAYS/DOWN（涨幅大于0.5%视为up，跌幅大于0.5%视为DOWN，否则为SIDEWAYS）
   - 深证成指 (399001.SZ): UP/SIDEWAYS/DOWN（涨幅大于0.5%视为up，跌幅大于0.5%视为DOWN，否则为SIDEWAYS）
   - 创业板指 (399006.SZ): UP/SIDEWAYS/DOWN（涨幅大于0.5%视为up，跌幅大于0.5%视为DOWN，否则为SIDEWAYS）
   - 每个指数需要给出100-150字的预测理由
3. **风险因素**: 列出具体风险点
4. **机会因素**: 列出具体机会点
5. **仓位建议**: 给出具体仓位建议
6. **综合总结**: 400字左右的市场概述与总结
7. **置信度**: 0-100的置信度评分

---

输出格式

请严格按照以下JSON格式输出：

```json
{{
    "market_state": "STRONG/SHOCK/WEAK",
    "index_predictions": [
        {{
            "ts_code": "000001.SH",
            "name": "上证指数",
            "trend_direction": "UP/SIDEWAYS/DOWN",
            "prediction_reason": "预测理由（100-150字）"
        }},
        {{
            "ts_code": "399001.SZ",
            "name": "深证成指",
            "trend_direction": "UP/SIDEWAYS/DOWN",
            "prediction_reason": "预测理由（100-150字）"
        }},
        {{
            "ts_code": "399006.SZ",
            "name": "创业板指",
            "trend_direction": "UP/SIDEWAYS/DOWN",
            "prediction_reason": "预测理由（100-150字）"
        }}
    ],
    "risk_factors": ["风险因素1", "风险因素2", "风险因素3"],
    "opportunity_factors": ["机会因素1", "机会因素2", "机会因素3"],
    "position_advice": "仓位建议（具体百分比和理由）",
    "summary": "市场综合概述与总结（400字左右，包含：今日市场整体表现、资金面情况、技术面信号、新闻面影响、下一交易日关键点位和风险信号、综合结论）",
    "confidence": 75.0
}}
```
"""
    return prompt


