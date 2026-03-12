"""
板块分析师Prompt工具函数

包含格式化数据的辅助函数和分维度分析Prompt模板。
用于支持 SectorAnalyst 的分析流程。
"""

from typing import Dict, Any, List, Optional


# ==================== System Prompt ====================

SYSTEM_PROMPT_SECTOR_ANALYST = """你是资深A股板块分析师，具备以下专业能力：

角色定位
- **板块轮动专家**：精通板块间资金轮动规律，把握市场热点切换
- **资金跟踪专家**：深入分析主力资金在各板块间的流向
- **情绪分析专家**：识别板块热度变化和市场情绪拐点
- **风险预警专家**：及时发现板块风险信号，提示规避机会

A股板块特征
- **板块数量**：约110个行业/概念板块，涨跌不一
- **轮动规律**：资金在不同板块间轮动，持续性各异
- **强势板块**：涨幅排名靠前，资金持续流入，领涨股活跃
- **弱势板块**：跌幅较大，资金流出，需规避风险
- **领涨股**：板块内涨幅最大的个股，反映板块强度

分析原则
1. **多维度筛选**：综合涨幅、资金、连续性等多维度筛选重点板块
2. **轮动识别**：对比历史热门板块，识别轮动方向
3. **风险优先**：始终关注风险板块，保护资金安全
4. **逻辑清晰**：分析结论有理有据，推理过程透明

输出规范
- **严格按照 JSON 格式输出**
- **文字描述简洁专业，避免模糊表述**
- **数值保留2位小数**

分析框架
根据任务类型，运用相应的专业知识和分析方法，
给出结构化、可量化的分析结论。"""


# ==================== 数据格式化函数 ====================

def format_sector_overview(sectors: List[Dict[str, Any]]) -> str:
    """
    格式化板块概览数据
    
    Args:
        sectors: 所有板块数据列表
        
    Returns:
        格式化后的板块概览文本
    """
    if not sectors:
        return "暂无板块数据"
    
    total = len(sectors)
    adv_count = sum(1 for s in sectors if s.get('pct_chg', 0) > 0)
    dec_count = sum(1 for s in sectors if s.get('pct_chg', 0) < 0)
    
    # 计算平均涨跌幅
    avg_chg = sum(s.get('pct_chg', 0) for s in sectors) / total if total > 0 else 0
    
    lines = [
        f"板块总数: {total}",
        f"上涨板块: {adv_count} ({adv_count/total*100:.1f}%)",
        f"下跌板块: {dec_count} ({dec_count/total*100:.1f}%)",
        f"平均涨跌幅: {avg_chg:.2f}%",
    ]
    
    return "\n".join(lines)


def format_hot_sectors_data(hot_sectors: List[Dict[str, Any]]) -> str:
    """
    格式化热门板块数据
    
    Args:
        hot_sectors: 热门板块列表（涨幅TOP N）
        
    Returns:
        格式化后的热门板块文本
    """
    if not hot_sectors:
        return "暂无热门板块数据"
    
    lines = ["### 热门板块 TOP 10（涨幅排名）\n"]
    
    for i, sector in enumerate(hot_sectors, 1):
        name = sector.get('sector_name', '未知')
        code = sector.get('sector_code', '')
        rank = sector.get('rank', 0)
        pct_chg = sector.get('pct_chg', 0)
        amount = sector.get('amount', 0) / 100000000  # 转换为亿
        fund_inflow = sector.get('fund_inflow', 0) / 100000000  # 转换为亿
        adv = sector.get('adv_issues', 0)
        dec = sector.get('dec_issues', 0)
        continuous_days = sector.get('continuous_strong_days', 0)
        rank_change = sector.get('rank_change', 0)
        
        # 领涨股信息
        leading_stock = sector.get('leading_stock_name', '')
        leading_pct = sector.get('leading_stock_pct_chg', 0)
        
        lines.append(f"**{i}. {name}** ({code})")
        lines.append(f"   - 排名: 第{rank}名 (变化: {'+' if rank_change > 0 else ''}{rank_change})")
        lines.append(f"   - 涨跌幅: {pct_chg:.2f}%")
        lines.append(f"   - 成交额: {amount:.2f}亿")
        lines.append(f"   - 资金净流入: {fund_inflow:.2f}亿")
        lines.append(f"   - 涨跌家数: {adv}涨 / {dec}跌")
        if continuous_days > 0:
            lines.append(f"   - 连续强势: {continuous_days}天")
        if leading_stock:
            lines.append(f"   - 领涨股: {leading_stock} ({leading_pct:.2f}%)")
        lines.append("")
    
    return "\n".join(lines)


def format_capital_flow_data(capital_sectors: List[Dict[str, Any]]) -> str:
    """
    格式化资金流入板块数据
    
    使用综合评分排序，解决不同板块成分股数量不同导致的资金流入绝对值差异问题。
    综合评分 = 权重1 * 流入占成交额比例 + 权重2 * 流入率
    
    Args:
        capital_sectors: 资金流入TOP N板块列表（按综合评分排序）
        
    Returns:
        格式化后的资金流入板块文本
    """
    if not capital_sectors:
        return "暂无资金流向数据"
    
    lines = ["### 资金流入板块 TOP 10（综合评分排序）\n"]
    lines.append("> 综合评分 = 流入占成交额比例×50% + 流入率×50%")
    lines.append("> 解决不同板块成分股数量差异导致的绝对值偏差问题\n")
    
    for i, sector in enumerate(capital_sectors, 1):
        name = sector.get('sector_name', '未知')
        code = sector.get('sector_code', '')
        fund_inflow = sector.get('fund_inflow', 0) / 100000000  # 转换为亿
        fund_inflow_rate = sector.get('fund_inflow_rate', 0)
        pct_chg = sector.get('pct_chg', 0)
        amount = sector.get('amount', 0) / 100000000
        capital_score = sector.get('capital_score', 0)
        inflow_to_amount = sector.get('inflow_to_amount', 0)
        
        lines.append(f"**{i}. {name}** ({code})")
        lines.append(f"   - 综合评分: {capital_score:.2f}")
        lines.append(f"   - 资金净流入: {fund_inflow:.2f}亿 (流入率: {fund_inflow_rate:.2f}%)")
        lines.append(f"   - 流入占成交: {inflow_to_amount:.2f}%")
        lines.append(f"   - 涨跌幅: {pct_chg:.2f}%")
        lines.append(f"   - 成交额: {amount:.2f}亿")
        lines.append("")
    
    return "\n".join(lines)


def format_risk_sectors_data(risk_sectors: List[Dict[str, Any]]) -> str:
    """
    格式化风险板块数据
    
    Args:
        risk_sectors: 风险板块列表（跌幅TOP N）
        
    Returns:
        格式化后的风险板块文本
    """
    if not risk_sectors:
        return "暂无风险板块数据"
    
    lines = ["### 风险板块 TOP 10（跌幅排名）\n"]
    
    for i, sector in enumerate(risk_sectors, 1):
        name = sector.get('sector_name', '未知')
        code = sector.get('sector_code', '')
        rank = sector.get('rank', 0)
        pct_chg = sector.get('pct_chg', 0)
        fund_inflow = sector.get('fund_inflow', 0) / 100000000  # 转换为亿
        adv = sector.get('adv_issues', 0)
        dec = sector.get('dec_issues', 0)
        
        lines.append(f"**{i}. {name}** ({code})")
        lines.append(f"   - 排名: 第{rank}名")
        lines.append(f"   - 涨跌幅: {pct_chg:.2f}%")
        lines.append(f"   - 资金净流入: {fund_inflow:.2f}亿")
        lines.append(f"   - 涨跌家数: {adv}涨 / {dec}跌")
        lines.append("")
    
    return "\n".join(lines)


def format_rotation_data(
    today_hot: List[str],
    yesterday_hot: List[str],
    rotation_info: Dict[str, Any]
) -> str:
    """
    格式化板块轮动数据
    
    Args:
        today_hot: 今日热门板块名称列表
        yesterday_hot: 昨日热门板块名称列表
        rotation_info: 轮动分析信息
        
    Returns:
        格式化后的轮动数据文本
    """
    lines = ["### 板块轮动分析\n"]
    
    # 新晋热门
    new_hot = rotation_info.get('new_hot_sectors', [])
    if new_hot:
        lines.append(f"**新晋热门板块**: {', '.join(new_hot)}")
    
    # 持续强势
    persistent = rotation_info.get('persistent_hot_sectors', [])
    if persistent:
        lines.append(f"**持续强势板块**: {', '.join(persistent)}")
    
    # 降温板块
    cooling = rotation_info.get('cooling_sectors', [])
    if cooling:
        lines.append(f"**降温板块**: {', '.join(cooling)}")
    
    lines.append("")
    lines.append(f"**昨日热门**: {', '.join(yesterday_hot) if yesterday_hot else '无数据'}")
    lines.append(f"**今日热门**: {', '.join(today_hot) if today_hot else '无数据'}")
    
    return "\n".join(lines)


def format_long_term_memory(memories: List[Dict[str, Any]]) -> str:
    """
    格式化长期记忆数据
    
    Args:
        memories: 长期记忆列表
        
    Returns:
        格式化后的长期记忆文本
    """
    if not memories:
        return ""
    
    lines = ["### 历史经验参考\n"]
    lines.append("> 以下是从历史分析中检索到的相关经验，请在分析时参考：\n")
    
    for i, mem in enumerate(memories, 1):
        mem_type = mem.get('type', 'PATTERN')
        insight = mem.get('insight', '')
        date = mem.get('date', '')
        similarity = mem.get('similarity', 0)
        
        type_label = {
            'PATTERN': '模式',
            'MISTAKE': '教训',
            'RULE': '规则'
        }.get(mem_type, mem_type)
        
        lines.append(f"**{i}. [{type_label}]** (相似度: {similarity:.0%})")
        lines.append(f"   {insight}")
        if date:
            lines.append(f"   _来源: {date}_")
        lines.append("")
    
    return "\n".join(lines)


def format_yesterday_report(report: Dict[str, Any]) -> str:
    """
    格式化昨日板块分析报告
    
    提取关键分析内容，供今日分析参考
    
    Args:
        report: 昨日的板块分析报告（从短期记忆获取）
        结构: {'trade_date': ..., 'content': {'task_id': ..., 'data': SectorReport.to_dict()}}
        
    Returns:
        格式化后的昨日报告文本
    """
    if not report:
        return ""
    
    # 直接从 content.data 获取报告数据
    content = report.get('content', {})
    data = content.get('data', {})
    
    lines = ["### 昨日板块分析回顾\n"]
    lines.append("> 以下是昨日的板块分析结果，请在分析今日行情时参考轮动方向和预测准确性：\n")
    
    # 1. 板块轮动
    rotation = data.get('sector_rotation', {})
    if rotation:
        lines.append("**【板块轮动】**")
        new_hot = rotation.get('new_hot_sectors', [])
        persistent = rotation.get('persistent_hot_sectors', [])
        cooling = rotation.get('cooling_sectors', [])
        if new_hot:
            lines.append(f"- 新晋热门: {', '.join(new_hot)}")
        if persistent:
            lines.append(f"- 持续强势: {', '.join(persistent)}")
        if cooling:
            lines.append(f"- 降温板块: {', '.join(cooling)}")
        lines.append("")
    
    # 2. 热门板块分析
    hot_analysis = data.get('hot_analysis', {})
    if hot_analysis:
        lines.append("**【昨日热门分析】**")
        summary = hot_analysis.get('hot_sectors_summary', '')
        if summary:
            lines.append(f"- 总结: {summary[:200]}{'...' if len(summary) > 200 else ''}")
        sustainability = hot_analysis.get('sustainability', '')
        if sustainability:
            lines.append(f"- 持续性判断: {sustainability}")
        # 昨日预测的热门板块（用于验证准确性）
        predicted = hot_analysis.get('predicted_hot_sectors', [])
        if predicted:
            lines.append(f"- **昨日预测热门: {', '.join(predicted)}**")
        predicted_reason = hot_analysis.get('predicted_reason', '')
        if predicted_reason:
            lines.append(f"- 预测理由: {predicted_reason[:150]}{'...' if len(predicted_reason) > 150 else ''}")
        lines.append("")
    
    # 3. 资金流向分析
    capital_analysis = data.get('capital_analysis', {})
    if capital_analysis:
        lines.append("**【昨日资金流向】**")
        summary = capital_analysis.get('capital_flow_summary', '')
        if summary:
            lines.append(f"- 总结: {summary[:200]}{'...' if len(summary) > 200 else ''}")
        main_focus = capital_analysis.get('main_focus', [])
        if main_focus:
            lines.append(f"- 主力关注: {', '.join(main_focus)}")
        rotation = capital_analysis.get('capital_rotation', '')
        if rotation:
            lines.append(f"- 资金轮动: {rotation}")
        lines.append("")
    
    # 4. 风险分析
    risk_analysis = data.get('risk_analysis', {})
    if risk_analysis:
        lines.append("**【昨日风险分析】**")
        summary = risk_analysis.get('risk_sectors_summary', '')
        if summary:
            lines.append(f"- 总结: {summary[:150]}{'...' if len(summary) > 150 else ''}")
        avoid = risk_analysis.get('avoid_advice', '')
        if avoid:
            lines.append(f"- 规避建议: {avoid[:100]}{'...' if len(avoid) > 100 else ''}")
        lines.append("")
    
    # 5. 轮动信号
    rotation_signal = data.get('rotation_signal', '')
    if rotation_signal:
        lines.append(f"**【轮动信号】** {rotation_signal}")
        lines.append("")
    
    # 6. 综合总结
    summary = data.get('summary', '')
    if summary:
        lines.append("**【昨日综合总结】**")
        lines.append(summary[:300] + ('...' if len(summary) > 300 else ''))
        lines.append("")
    
    return "\n".join(lines)


def format_market_breadth_data(market_breadth: Dict[str, Any]) -> str:
    """
    格式化市场广度数据
    
    Args:
        market_breadth: 市场广度信息
        
    Returns:
        格式化后的市场广度文本
    """
    lines = ["### 市场广度\n"]
    
    lines.append(f"板块总数: {market_breadth.get('total_sectors', 0)}")
    lines.append(f"上涨板块: {market_breadth.get('adv_sector_count', 0)}")
    lines.append(f"下跌板块: {market_breadth.get('dec_sector_count', 0)}")
    lines.append(f"平盘板块: {market_breadth.get('flat_sector_count', 0)}")
    lines.append(f"平均涨跌幅: {market_breadth.get('avg_pct_chg', 0):.2f}%")
    lines.append(f"强势板块占比: {market_breadth.get('strong_sector_ratio', 0):.1f}%")
    lines.append(f"弱势板块占比: {market_breadth.get('weak_sector_ratio', 0):.1f}%")
    lines.append(f"市场状态: {market_breadth.get('market_breadth_state', 'NORMAL')}")
    
    return "\n".join(lines)


def format_market_news_analysis(news_analysis: Dict[str, Any]) -> str:
    """
    格式化大盘新闻分析结果
    
    将大盘分析师的新闻分析结果格式化，供板块分析师参考。
    重点展示新闻中提及的关注板块，帮助识别新闻催化机会。
    
    Args:
        news_analysis: 大盘分析师的新闻分析结果（NewsAnalysis.to_dict()）
        
    Returns:
        格式化后的新闻分析文本
    """
    if not news_analysis:
        return ""
    
    lines = ["### 大盘新闻分析（来自大盘分析师）\n"]
    lines.append("> 以下是大盘分析师从新闻维度识别的市场关注点，请在板块分析时参考：\n")
    
    # 关键新闻
    key_news = news_analysis.get('key_news', [])
    if key_news:
        lines.append("**【关键新闻】**")
        for i, news in enumerate(key_news[:5], 1):
            lines.append(f"{i}. {news}")
        lines.append("")
    
    # 利好因素
    positive = news_analysis.get('positive_factors', [])
    if positive:
        lines.append(f"**【利好因素】**: {', '.join(positive[:5])}")
        lines.append("")
    
    # 利空因素
    negative = news_analysis.get('negative_factors', [])
    if negative:
        lines.append(f"**【利空因素】**: {', '.join(negative[:5])}")
        lines.append("")
    
    # 板块关注点（核心）
    sector_focus = news_analysis.get('sector_focus', [])
    if sector_focus:
        lines.append("**【新闻提及的关注板块】**")
        lines.append("> 这些板块可能在新闻催化下有表现机会：")
        for sector in sector_focus:
            lines.append(f"- {sector}")
        lines.append("")
    
    # 市场影响
    market_impact = news_analysis.get('market_impact', '')
    if market_impact:
        lines.append(f"**【对市场的影响】**: {market_impact}")
        lines.append("")
    
    # 总结
    summary = news_analysis.get('summary', '')
    if summary:
        lines.append(f"**【新闻分析总结】**: {summary}")
    
    return "\n".join(lines)


def format_30d_trend_data(trends_30d: Dict[str, List[Dict[str, Any]]]) -> str:
    """
    格式化30日趋势数据
    
    展示板块的中期趋势，对比近30日 vs 前30日
    
    Args:
        trends_30d: {
            'hot_30d': [...],      # 近30日热门板块
            'capital_30d': [...],  # 近30日资金流入板块
            'risk_30d': [...]      # 近30日风险板块
        }
        
    Returns:
        格式化后的30日趋势文本
    """
    if not trends_30d:
        return ""
    
    lines = ["---\n"]
    lines.append("## 板块趋势分析（30日维度）\n")
    lines.append("> 以下是近30日板块趋势分析，对比前30日表现，用于识别中期趋势\n")
    
    # 1. 近30日热门板块
    hot_30d = trends_30d.get('hot_30d', [])
    if hot_30d:
        lines.append("### 近30日热门板块 TOP 10（累计涨幅排名）\n")
        lines.append("| 排名 | 板块 | 30日涨幅 | 30日资金 | 强势天数 | vs前30日 | 趋势 |")
        lines.append("|-----|-----|---------|---------|---------|---------|------|")
        
        for i, s in enumerate(hot_30d, 1):
            name = s.get('sector_name', '')
            pct_30d = s.get('pct_chg_30d', 0)
            fund_30d = s.get('fund_inflow_30d', 0) / 1e8  # 转亿
            strong_days = s.get('strong_days_30d', 0)
            pct_prev = s.get('pct_chg_prev_30d', 0)
            trend_type = s.get('trend_type', '')
            
            # 对比前30日
            if pct_prev != 0:
                vs_prev = f"+{pct_30d - pct_prev:.1f}%" if pct_30d > pct_prev else f"{pct_30d - pct_prev:.1f}%"
            else:
                vs_prev = "-"
            
            # 趋势标记
            trend_icon = {
                'ACCELERATING': '↑↑ 加强',
                'PERSISTENT': '→ 持续',
                'REBOUNDING': '↗ 反弹',
                'CORRECTING': '↘ 回调',
                'WEAKENING': '↓ 转弱',
                'CONSISTENTLY_WEAK': '↓↓ 持弱'
            }.get(trend_type, trend_type)
            
            lines.append(f"| {i} | {name} | {pct_30d:+.1f}% | {fund_30d:+.1f}亿 | {strong_days}天 | {vs_prev} | {trend_icon} |")
        
        lines.append("")
    
    # 2. 近30日风险板块
    risk_30d = trends_30d.get('risk_30d', [])
    if risk_30d:
        lines.append("### 近30日风险板块 TOP 10（累计跌幅排名）\n")
        lines.append("| 排名 | 板块 | 30日跌幅 | 30日资金流出 | 趋势 |")
        lines.append("|-----|-----|---------|------------|------|")
        
        for i, s in enumerate(risk_30d, 1):
            name = s.get('sector_name', '')
            pct_30d = s.get('pct_chg_30d', 0)
            fund_30d = s.get('fund_inflow_30d', 0) / 1e8
            trend_type = s.get('trend_type', '')
            
            trend_icon = {
                'ACCELERATING': '↑↑',
                'PERSISTENT': '→',
                'REBOUNDING': '↗ 反弹',
                'CORRECTING': '↘ 回调',
                'WEAKENING': '↓',
                'CONSISTENTLY_WEAK': '↓↓ 持弱'
            }.get(trend_type, '-')
            
            lines.append(f"| {i} | {name} | {pct_30d:.1f}% | {fund_30d:.1f}亿 | {trend_icon} |")
        
        lines.append("")
    
    return "\n".join(lines)


# ==================== 分析Prompt构建函数 ====================

def build_sector_analysis_prompt(
    trade_date: str,
    all_sectors: List[Dict[str, Any]],
    hot_sectors: List[Dict[str, Any]],
    capital_sectors: List[Dict[str, Any]],
    risk_sectors: List[Dict[str, Any]],
    market_breadth: Dict[str, Any],
    rotation_info: Dict[str, Any],
    yesterday_hot: List[str] = None,
    long_term_memory: List[Dict[str, Any]] = None,
    yesterday_report: Dict[str, Any] = None,
    prediction_verification: str = "",
    trends_30d: Dict[str, List[Dict[str, Any]]] = None,
    market_news_analysis: Dict[str, Any] = None
) -> str:
    """
    构建板块分析Prompt
    
    Args:
        trade_date: 交易日期
        all_sectors: 所有板块数据（用于概览）
        hot_sectors: 热门板块列表
        capital_sectors: 资金流入板块列表
        risk_sectors: 风险板块列表
        market_breadth: 市场广度信息
        rotation_info: 轮动分析信息
        yesterday_hot: 昨日热门板块名称列表
        long_term_memory: 长期记忆（RAG检索结果）
        yesterday_report: 昨日完整分析报告（从短期记忆获取）
        prediction_verification: 昨日热点预测验证文本（分析时使用）
        trends_30d: 30日趋势数据
        market_news_analysis: 大盘分析师的新闻分析结果（NewsAnalysis.to_dict()）
        
    Returns:
        板块分析Prompt
    """
    # 格式化各部分数据
    overview_text = format_sector_overview(all_sectors)
    hot_text = format_hot_sectors_data(hot_sectors)
    capital_text = format_capital_flow_data(capital_sectors)
    risk_text = format_risk_sectors_data(risk_sectors)
    breadth_text = format_market_breadth_data(market_breadth)
    
    today_hot_names = [s.get('sector_name', '') for s in hot_sectors[:5]]
    rotation_text = format_rotation_data(
        today_hot_names,
        yesterday_hot or [],
        rotation_info
    )
    
    # 格式化长期记忆
    memory_text = ""
    if long_term_memory:
        memory_text = format_long_term_memory(long_term_memory)
    
    # 格式化昨日报告
    yesterday_report_text = ""
    if yesterday_report:
        yesterday_report_text = format_yesterday_report(yesterday_report)
    
    # 格式化30日趋势数据
    trends_30d_text = ""
    if trends_30d:
        trends_30d_text = format_30d_trend_data(trends_30d)
    
    # 格式化大盘新闻分析
    news_analysis_text = ""
    if market_news_analysis:
        news_analysis_text = format_market_news_analysis(market_news_analysis)
    
    prompt = f"""板块分析任务

你现在的任务是，基于以下数据进行**板块分析**。

交易日期: {trade_date}

---

## 市场广度

{breadth_text}

---

## 板块概览

{overview_text}

---

## 重点板块数据

{hot_text}

{capital_text}

{risk_text}
{trends_30d_text}
---

## 板块轮动

{rotation_text}
{news_analysis_text}{memory_text}{yesterday_report_text}

{prediction_verification}
---

## 分析要求

请先读取昨日分析，反思和总结预测结果，然后从以下维度进行分析：

### 1. 热门板块分析
- 识别今日最强板块及其强势原因
- 分析热门板块的持续性
- 判断是否有连续强势的板块

### 2. 资金流向分析
- 主力资金在关注哪些板块
- 资金流入与涨幅的关系
- 资金是否在轮动

### 3. 风险警示
- 哪些板块需要规避
- 风险板块的共同特征
- 是否有补跌风险

### 4. 板块轮动
- 资金轮动方向
- 新热点与老热点的关系
- 轮动是否有规律

### 5. 中期趋势分析
- 结合30日趋势数据，识别处于加强、反弹、回调等不同趋势阶段的板块
- 关注中期趋势与短期热点的共振机会
- 规避中期趋势持续弱势的板块

### 6. 明日热门预测
- 预测明日可能成为热门的板块（5个）
- 给出预测理由，结合短期表现和中期趋势综合判断

---

## 输出格式

请严格按照以下JSON格式输出：

```json
{{
    "hot_analysis": {{
        "hot_sectors_summary": "近期热门板块总结（180-200字）",
        "hot_reasons": ["强势原因1", "强势原因2", "强势原因3"],
        "sustainability": "持续性判断（80-100字）",
        "predicted_hot_sectors": ["板块1", "板块2", "板块3", "板块4", "板块5"],
        "predicted_reason": "预测理由（100-150字，解释为什么预测这些板块会成为明日热门）"
    }},
    "capital_analysis": {{
        "capital_flow_summary": "资金流向总结（200-240字）",
        "main_focus": ["主力关注板块1", "主力关注板块2", "主力关注板块3"],
        "capital_rotation": "资金轮动描述（100-120字）"
    }},
    "risk_analysis": {{
        "risk_sectors_summary": "风险板块总结（100-150字）",
        "risk_reasons": ["风险原因1", "风险原因2"],
        "avoid_advice": "规避建议（100-120字）"
    }},
    "rotation_signal": "近期板块轮动信号（简短一句话，如'科技板块持续强势，资金向新能源轮动'）",
    "summary": "综合总结（240-400字，包含：今日板块整体表现、热门板块特征、资金流向特点、风险提示、以及未来重点关注方向）",
    "tomorrow_outlook": "明日展望（160-180字）",
    "confidence": 75.0
}}
```

注意：
- `confidence` 为0-100的置信度评分
- 所有文字描述要简洁专业，避免模糊表述
"""
    return prompt


def build_sector_review_prompt(
    reports: List[Dict[str, Any]],
    verifications: List[Dict[str, Any]]
) -> str:
    """
    构建板块复盘Prompt
    
    Args:
        reports: 近期板块分析报告列表
        verifications: 预测验证结果列表
        
    Returns:
        复盘Prompt
    """
    # 格式化历史报告
    reports_text = ""
    if reports:
        reports_text = "### 近期板块分析报告\n\n"
        for i, report in enumerate(reports, 1):
            date = report.get('trade_date', '未知')
            content = report.get('content', {})
            hot_names = content.get('hot_sectors', [])
            if isinstance(hot_names, list) and hot_names:
                if isinstance(hot_names[0], dict):
                    hot_names = [s.get('sector_name', '') for s in hot_names]
            
            reports_text += f"**{date}**:\n"
            reports_text += f"- 热门板块: {', '.join(hot_names[:5]) if hot_names else '无'}\n"
            reports_text += f"- 轮动信号: {content.get('rotation_signal', '无')}\n"
            reports_text += f"- 总结: {content.get('summary', '无')[:200]}...\n\n"
    
    # 格式化验证结果
    verification_text = ""
    if verifications:
        correct = sum(1 for v in verifications if v.get('correct'))
        total = len(verifications)
        accuracy = correct / total * 100 if total > 0 else 0
        
        verification_text = f"### 预测验证结果\n\n准确率: {correct}/{total} ({accuracy:.1f}%)\n\n"
        for v in verifications:
            status = "✓" if v.get('correct') else "✗"
            verification_text += f"- [{v.get('date')}] 预测热点: {v.get('predicted', 'N/A')} | 实际: {v.get('actual', 'N/A')} {status}\n"
    
    prompt = f"""板块复盘分析任务

你现在的任务是，基于以下近期板块分析报告和预测验证结果进行**复盘分析**。

{reports_text}

{verification_text}

---

## 分析要求

请进行板块复盘分析，提取可复用的经验教训。

### 分析内容:
1. **板块轮动回顾**: 近期板块轮动规律
2. **热点持续性分析**: 热门板块的持续性特征
3. **预测归因**: 预测准确/失误的原因
4. **经验提炼**: 提取可复用的经验

---

## 输出格式

请严格按照以下JSON格式输出：

```json
{{
    "rotation_review": "板块轮动回顾（150-200字）",
    "sustainability_analysis": "热点持续性分析（100-150字）",
    "prediction_analysis": "预测归因分析（100-150字）",
    "success_patterns": ["成功模式1", "成功模式2"],
    "failure_patterns": ["失败模式1", "失败模式2"],
    "lessons": ["经验:教训1", "经验:教训2", "经验:教训3"],
    "summary": "复盘总结（100-150字）"
}}
```

注意: `lessons` 字段中的每条经验必须以 "经验:" 开头。
"""
    return prompt