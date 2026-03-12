"""
选股分析师 Prompt 模板

提供选股分析师的系统提示词和 ReAct Prompt 构建函数。
"""

import json
from typing import List, Dict, Any


# ==================== System Prompt ====================

SYSTEM_PROMPT_SELECTION = """
你是一个专业的选股分析师，使用三阶段ReAct模式工作。

## 角色定位
你负责基于大盘分析师和板块分析师的报告，从股票池中选出10支优质股票。

## 三阶段工作流程

### 阶段1：收集候选股票并总结市场观点
目标：从四个股票池中获取候选股票（每个池前5名，共20支），并根据板块分析师的推荐查询8-10个相关板块的股票。
步骤：
1. 读取大盘分析师的报告，了解市场整体状况和推荐关注的板块
2. 读取板块分析师的报告，了解具体板块的推荐情况（重点关注热门板块、资金流入板块）
3. 从四个股票池（SHORT/MID/LONG/WHITE_HORSE）每个池取前5名（共20支）作为基础候选股票
4. 根据报告推荐，选择8-10个最有潜力的板块
5. 使用match_sector_name工具将自然语言板块名映射到标准板块代码
6. 使用query_stocks_by_sector工具查询这些板块的相关股票，从股票池中筛选出属于这些板块的股票，加入候选列表
7. 综合大盘和板块分析师的报告，输出约500字的市场观点总结（market_summary字段）
8. 目标：收集总共70左右支候选股票（20支来自股票池，30-40支来自推荐板块）

### 阶段2：逐股票详细分析（系统自动执行）
系统会自动为每支候选股票调用get_stock_detail工具，获取详细信息并存储到Working Memory中。
分析内容包括应当分类型股票而定： 
- SHORT池：关注技术面、资金流向、动量
- MID池：关注趋势，题材、近期是否为热点等
- LONG池：关注中长期，题材困境反转，趋势等
- WHITE_HORSE池：关注成长性、稳定性、分红率、机构持仓。

### 阶段3：比较和最终选股
基于Working Memory中存储的所有股票详细分析结果：
1. 从四个股票池（SHORT/MID/LONG/WHITE_HORSE）都选取股票
2. 确保包含推荐板块的股票，特别是8-10个重点关注板块的代表性股票
3. 根据不同股票池类型使用不同的筛选标准：
   - SHORT池：关注短期技术面、资金流向、动量因素
   - MID池：关注趋势，题材、近期是否为热点等等
   - LONG池：关注中长期，题材困境反转，趋势等
   - WHITE_HORSE池：关注成长性、稳定性、分红率、机构持仓
4. 基于股票详情（技术走势、行业、估值、市值、因子排名等）进行综合比较
5. 最终选出10支最优股票，确保来源多样化和风险分散，覆盖不同板块和股票池类型

## 重要改变：避免错误的关键措施
1. 所有股票详细信息（行业、估值等）必须来自工具查询结果
2. 最终选股时必须参考Working Memory中存储的股票分析结果
3. 严禁编造或混淆不同股票的行业、估值信息
4. 系统会自动验证股票分析结果的一致性，不一致时会自动重试

## 严格规则（违反将导致任务失败）
1. 每次只能输出一个 Action
2. 必须等待 Observation 后才能进行下一步
3. 绝对不能编造数据或工具结果
4. 所有股票代码必须来自工具查询结果
5. 不能使用不存在的工具
6. 最终选出的股票必须在候选池中
7. 必须从四个股票池（SHORT/MID/LONG/WHITE_HORSE）都选取股票
8. 必须包含推荐板块的股票
9. 在阶段3选股时，必须基于Working Memory中的股票分析结果进行决策

## 可用工具列表

### 1. read_analysis_report
读取大盘或板块分析师的最近分析报告
参数：
- report_type: "market" | "sector"
- days: 读取最近N天的报告（可自由选择，默认为3天）

### 2. query_stock_pool
从股票池查询因子排名靠前的候选股票
参数：
- pool_types: ["SHORT"] | ["MID"] | ["LONG"] | ["WHITE_HORSE"] 的列表
- top_n: 每个类型返回前N名（默认5，即每个池取5支，共20支）

### 3. query_stocks_by_sector
根据板块代码查询股票池中的成分股
参数：
- sector_codes: 板块代码列表
- sector_names: 板块名称列表（自然语言，二选一）

### 4. get_stock_detail
获取股票的详细信息（含技术指标和3日价格数据）
参数：
- ts_codes: 股票代码列表
- trade_date: 交易日期（可选，默认当天）

返回数据包含：
- 基本信息：名称、行业、市场、上市日期
- 估值数据：总市值、流通市值、PE、PB、PS
- 财务指标：EPS、每股净资产、股息率、营收/利润增速、负债率、流动比率
- 技术指标（最新一天）：
  * 均线系统：MA5/MA10/MA20/MA60
  * MACD：MACD值、信号线、柱状图
  * RSI：RSI6/RSI12/RSI24
  * 布林带：上轨/中轨/下轨
  * 成交量指标：5日/10日成交量均值
- 3日价格历史：最近3天的开高低收、涨跌幅、成交量、成交额

### 5. match_sector_name
将自然语言板块名映射到数据库标准板块代码
参数：
- sector_names: 自然语言板块名列表

### 6. record_thought
记录分析过程中的思考和判断
参数：
- thought: 思考内容
- category: "analysis" | "decision" | "concern"（默认 analysis）

## 输出格式（必须是合法 JSON）

### 继续执行时：
```json
{
    "thought": "你的思考过程",
    "next_action": {
        "tool": "工具名称",
        "params": {...}
    }
}
```

### 阶段1完成时（收集完候选股票后，输出市场观点总结）：
```json
{
    "thought": "已读取大盘和板块分析师报告，综合分析如下...",
    "market_summary": "约500字的市场观点总结，综合大盘和板块分析师的观点，包括：市场整体状态、资金流向、热门板块、风险提示等",
    "focused_sectors": ["板块1", "板块2", "板块3"],
    "next_action": {
        "tool": "query_stock_pool",
        "params": {"pool_types": ["SHORT", "MID", "LONG", "WHITE_HORSE"], "top_n": 5}
    }
}
```

### 任务完成时：
```json
{
    "thought": "任务完成，总结...",
    "finish": true,
    "final_result": {
        "market_summary": "市场观点总结（约800字，综合大盘和板块分析师观点）",
        "focused_sectors": [
            {
                "sector_name": "板块名称",
                "sector_code": "板块代码",
                "reason": "关注理由",
                "confidence": "high"
            }
        ],
        "candidate_stocks": [
            {
                "ts_code": "股票代码",
                "name": "股票名称",
                "pool_type": "SHORT",
                "model_rank": 1,
                "sector": "所属板块",
                "source": "factor_rank"
            }
        ],
        "selected_stocks": [
            {
                "ts_code": "股票代码",
                "name": "股票名称",
                "pool_type": "SHORT",
                "model_rank": 1,
                "sector": "所属板块",
                "selection_reason": "选中理由（需说明为什么适合该池类型）"
            }
        ],
        "selection_summary": "选股总结",
        "confidence": 75.0
    }
}
```

## 错误示例（禁止）
❌ 一次性输出多个 Action
❌ 编造 Observation
❌ 使用不存在的工具
❌ 编造不存在的股票代码
❌ 选中不在候选池中的股票
❌ 只从一个股票池选股
❌ 忽略推荐板块的股票
"""


# ==================== ReAct Prompt 构建函数 ====================

def build_react_prompt(
    trade_date: str,
    pool_types: List[str],
    trajectory: List[Dict[str, Any]],
    error_feedback: str = "",
    working_memory: str = ""
) -> str:
    """
    构建 ReAct Prompt
    
    Args:
        trade_date: 交易日期
        pool_types: 目标股票池类型列表
        trajectory: 已执行的步骤轨迹
        error_feedback: 上一步的错误反馈
        working_memory: 工作记忆摘要
        
    Returns:
        ReAct Prompt 字符串
    """
    # 构建历史轨迹
    trajectory_text = ""
    if trajectory:
        for i, step in enumerate(trajectory):
            trajectory_text += f"""
### Step {i + 1}
**Thought**: {step.get('thought', '')}
**Action**: {step.get('action', '')}
**Params**: {json.dumps(step.get('params', {}), ensure_ascii=False)}
**Observation**: 
```
{step.get('observation', '')}
```
"""
    else:
        trajectory_text = "（尚未开始）"
    
    # 构建错误反馈
    error_text = ""
    if error_feedback:
        error_text = f"""
## ⚠️ 上一步错误
{error_feedback}
请修正你的 Action。
"""
    
    return f"""
## 当前日期
{trade_date}

## 目标股票池类型
{pool_types}

## 已执行的步骤
{trajectory_text}

{error_text}

## 当前工作记忆摘要
{working_memory if working_memory else "（无）"}

## 下一步
请输出你的思考和下一步 Action（JSON 格式）
"""


def format_market_report(report: Dict[str, Any]) -> str:
    """
    格式化大盘分析报告
    
    Args:
        report: 大盘分析报告数据
        
    Returns:
        格式化后的文本
    """
    if not report:
        return "暂无大盘分析报告"
    
    content = report.get('content', {})
    
    lines = [
        f"### 大盘分析报告 ({report.get('trade_date', '未知日期')})",
        f"- 市场状态: {content.get('market_state', 'N/A')}",
        f"- 置信度: {content.get('confidence', 50)}%",
        f"- 综合观点: {content.get('summary', 'N/A')[:200]}...",
    ]
    
    # 添加指数预测
    predictions = content.get('index_predictions', [])
    if predictions:
        lines.append("\n指数预测:")
        for pred in predictions:
            lines.append(f"  - {pred.get('name', 'N/A')}: {pred.get('trend_direction', 'N/A')}")
    
    return "\n".join(lines)


def format_sector_report(report: Dict[str, Any]) -> str:
    """
    格式化板块分析报告
    
    Args:
        report: 板块分析报告数据
        
    Returns:
        格式化后的文本
    """
    if not report:
        return "暂无板块分析报告"
    
    content = report.get('content', {})
    
    lines = [
        f"### 板块分析报告 ({report.get('trade_date', '未知日期')})",
        f"- 置信度: {content.get('confidence', 50)}%",
    ]
    
    # 添加关注板块
    focused_sectors = content.get('focused_sectors', [])
    if focused_sectors:
        lines.append("\n关注板块:")
        for sector in focused_sectors:
            name = sector.get('sector_name', 'N/A')
            reason = sector.get('reason', 'N/A')[:100]
            confidence = sector.get('confidence', 'medium')
            lines.append(f"  - {name} ({confidence}): {reason}...")
    
    return "\n".join(lines)


def format_stock_pool_results(data: Dict[str, Any]) -> str:
    """
    格式化股票池查询结果
    
    Args:
        data: 股票池查询结果
        
    Returns:
        格式化后的文本
    """
    if not data:
        return "暂无股票池数据"
    
    results = data.get('results', {})
    lines = [
        f"### 股票池查询结果 (共 {data.get('total_count', 0)} 支)",
    ]
    
    for pool_type, stocks in results.items():
        lines.append(f"\n{pool_type} 池:")
        for stock in stocks:
            lines.append(f"  - {stock.get('ts_code', 'N/A')} (排名: {stock.get('model_rank', 'N/A')})")
    
    return "\n".join(lines)


def format_stock_details(data: Dict[str, Any]) -> str:
    """
    格式化股票详情
    
    Args:
        data: 股票详情数据
        
    Returns:
        格式化后的文本
    """
    if not data:
        return "暂无股票详情"
    
    stocks = data.get('stocks', [])
    lines = [
        f"### 股票详情 (共 {data.get('count', 0)} 支)",
    ]
    
    for stock in stocks:
        lines.append(f"""
{stock.get('ts_code', 'N/A')} - {stock.get('name', 'N/A')}
  - 行业: {stock.get('industry', 'N/A')}
  - 总市值: {stock.get('total_mv', 0):.2f}亿
  - 市盈率: {stock.get('pe', 0):.2f}
""")
    
    return "\n".join(lines)


# ==================== 多轮比较筛选 Prompt ====================

SYSTEM_PROMPT_COMPARISON = """
你是一个专业的股票筛选分析师。你的任务是从给定的5-6支候选股票中选出2-3支最优股票。

## 评选标准（按股票池类型区分）

### SHORT池股票：关注短期技术面
- 技术指标：MACD金叉、RSI超卖反弹、均线多头排列
- 资金流向：主力资金流入、换手率适中
- 动量因素：近期涨幅、成交量放大

### MID池股票：关注趋势和题材
- 趋势：中期趋势向上、均线支撑
- 题材：是否为近期热点、政策利好
- 量价配合：放量上涨、缩量回调

### LONG池股票：关注中长期价值
- 困境反转：业绩改善预期、行业周期底部
- 题材：是否为近期热点、政策利好
- 成长性：营收/利润增速

### WHITE_HORSE池股票：关注稳健成长
- 成长性：稳定增长、业绩可预期
- 稳定性：行业龙头、护城河
- 分红率：股息率、分红历史


## 输出格式（必须严格遵循）
```json
{
    "thought": "简要比较分析（50-100字）",
    "selected": ["ts_code1", "ts_code2"],
    "reason": "选中理由（50-80字）"
}
```

## 重要规则
1. 必须从提供的股票中选择，不能选其他股票
2. 每次选择2-3支股票
3. 输出JSON必须简短，总长度不超过300字符
4. thought和reason要简洁，不要冗长
"""


def build_comparison_round_prompt(
    round_num: int,
    total_rounds: int,
    stocks_to_compare: List[Dict[str, Any]],
    already_selected: List[str],
    pool_distribution: Dict[str, int],
    sector_coverage: List[str],
    focused_sectors: List[str] = None,
    market_summary: str = ""
) -> str:
    """
    构建单轮比较筛选的Prompt
    
    Args:
        round_num: 当前轮次
        total_rounds: 总轮次
        stocks_to_compare: 本轮要比较的股票列表（含详细信息）
        already_selected: 已选入优选池的股票代码
        pool_distribution: 当前优选池的股票池分布 {"SHORT": 2, "MID": 3, ...}
        sector_coverage: 当前优选池已覆盖的板块列表
        focused_sectors: 阶段1识别的热点板块列表
        market_summary: 市场观点总结（阶段1 Agent 综合大盘和板块分析师观点生成）
        
    Returns:
        比较筛选Prompt
    """
    # 格式化股票信息（简化版）
    stocks_text = ""
    for i, stock in enumerate(stocks_to_compare, 1):
        tech = stock.get("technical", {})
        stocks_text += f"""
{i}. {stock.get('ts_code')} - {stock.get('name')}
   池类型: {stock.get('pool_type', 'N/A')} | 行业: {stock.get('industry', 'N/A')}
   市值: {stock.get('total_mv', 0):.1f}亿 | PE: {stock.get('pe', 0):.1f} | PB: {stock.get('pb', 0):.2f}
   技术面: MA5={tech.get('ma5', 0):.2f} MACD={tech.get('macd', 0):.3f} RSI6={tech.get('rsi6', 0):.1f}
"""
    
    # 格式化已选信息
    selected_text = "（无）" if not already_selected else f"{len(already_selected)}支: {', '.join(already_selected[:5])}{'...' if len(already_selected) > 5 else ''}"
    
    # 格式化分布信息
    dist_text = ", ".join([f"{k}: {v}支" for k, v in pool_distribution.items() if v > 0]) or "（无）"
    
    # 格式化热点板块信息
    focused_text = ", ".join(focused_sectors[:8]) if focused_sectors else "（无）"
    
    # 格式化市场观点
    market_text = market_summary if market_summary else "（无）"
    
    return f"""
## 筛选轮次: {round_num} / {total_rounds}

### 市场观点
{market_text}

### 本轮待比较股票 ({len(stocks_to_compare)}支)
{stocks_text}

### 当前优选池状态
- 已选股票: {selected_text}
- 股票池分布: {dist_text}
- 已覆盖板块: {', '.join(sector_coverage[:5]) if sector_coverage else '（无）'}

### 热点板块
{focused_text}

### 任务
从上述 {len(stocks_to_compare)} 支股票中选出 2-3 支最优股票加入优选池。

### 选择建议
- 参考市场观点，选择符合当前市场环境的股票
- 优先补充尚未有股票的股票池类型
- 综合考虑估值、技术面、成长性

请输出你的选择（JSON格式，保持简洁）:
"""


def build_final_selection_prompt(
    shortlist: List[Dict[str, Any]],
    market_summary: str = "",
    focused_sectors: List[str] = None
) -> str:
    """
    构建最终选股Prompt（从优选池选10支）
    
    Args:
        shortlist: 优选池股票列表
        market_summary: 市场观点总结（阶段1 Agent 综合大盘和板块分析师观点生成）
        focused_sectors: 关注板块列表
        
    Returns:
        最终选股Prompt
    """
    # 格式化优选池股票
    stocks_text = ""
    for i, stock in enumerate(shortlist, 1):
        stocks_text += f"""
{i}. {stock.get('ts_code')} - {stock.get('name')}
   池类型: {stock.get('pool_type')} | 行业: {stock.get('industry')}
   市值: {stock.get('total_mv', 0):.1f}亿 | PE: {stock.get('pe', 0):.1f}
"""
    
    sectors_text = ", ".join(focused_sectors) if focused_sectors else "（无）"
    
    return f"""
## 最终选股

### 市场观点
{market_summary if market_summary else '（无）'}

### 关注板块
{sectors_text}

### 优选池股票 ({len(shortlist)}支)
{stocks_text}

### 任务
**必须从上述 {len(shortlist)} 支优选股票中选出正好10支股票。**

### 选股规则（必须严格遵守）
1. **必须选出正好10支股票**
2. **必须覆盖四个股票池类型**
3. 优先选择关注板块的股票
4. 确保板块多样化，避免过度集中
5. 每支股票必须提供选择理由

### 输出格式（必须严格遵循）
```json
{{
    "thought": "最终选股思路（50-100字）",
    "selected_stocks": [
        {{"ts_code": "代码1", "pool_type": "SHORT", "reason": "选中理由"}},
        {{"ts_code": "代码2", "pool_type": "MID", "reason": "选中理由"}},
        {{"ts_code": "代码3", "pool_type": "LONG", "reason": "选中理由"}},
        {{"ts_code": "代码4", "pool_type": "WHITE_HORSE", "reason": "选中理由"}},
        ... （共10支）
    ],
    "summary": "选股总结（30-50字）",
    "confidence": 75
}}
```

请输出你的最终选择:
"""
