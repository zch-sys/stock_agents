"""
大盘分析师增强测试脚本

测试 MarketAnalyst 的完整分析流程：
1. 捕获完整的 prompt 构建过程
2. 调用真实 LLM 进行分析
3. 输出 prompt txt 文件和分析结果 txt 文件
4. 记录所有 LLM 调用和 prompt 构建过程
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime
from typing import List, Dict
import time

import functools

from data.basic_data.database import init_db, get_session, AnalysisReport, KnowledgeMemory
from data.basic_data.config_manager import load_config
from core.llm.llm_client import LLMClient
from core.memory.memory_manager import MemoryManager
from agents.analysis.market.market_analyst import MarketAnalyst

# 获取项目根目录和报告输出目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(PROJECT_ROOT, "test_report")

# 确保报告目录存在
os.makedirs(REPORT_DIR, exist_ok=True)

# 测试日期 - 使用今天的日期
TEST_DATE = "2026-03-11"
REPORT_FILE = os.path.join(REPORT_DIR, f"market_report_{TEST_DATE.replace('-', '')}.txt")
PROMPT_FILE = os.path.join(REPORT_DIR, f"market_prompts_{TEST_DATE.replace('-', '')}.txt")

# 存储所有提示词构建记录
ALL_PROMPT_BUILDS = []


def clear_files():
    """清空报告文件和提示词文件"""
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write("")
    with open(PROMPT_FILE, 'w', encoding='utf-8') as f:
        f.write("")
    print(f"[OK] 已清空报告文件: {REPORT_FILE}")
    print(f"[OK] 已清空提示词文件: {PROMPT_FILE}")


def append_to_prompt(content: str):
    """追加内容到提示词文件"""
    with open(PROMPT_FILE, 'a', encoding='utf-8') as f:
        f.write(content + "\n")


def append_to_report(content: str):
    """追加内容到报告文件"""
    with open(REPORT_FILE, 'a', encoding='utf-8') as f:
        f.write(content + "\n")
    print(content)

def format_report(report) -> str:
    """
    格式化分析报告
    
    适配 MarketReport Schema (market_schema.py)
    输出顺序：
    1. 基本信息（日期、状态、置信度）
    2. 指数概览
    3. 分指数预测（替代原趋势方向）
    4. 技术分析
    5. 资金分析
    6. 新闻分析
    7. 情绪分析
    8. 估值分析
    9. 周期分析
    10. 风险评估
    11. 仓位建议
    12. 综合总结
    """
    lines = []
    
    # ========== 1. 基本信息 ==========
    lines.append("=" * 60)
    lines.append("【基本信息】")
    lines.append("=" * 60)
    lines.append(f"分析日期: {report.date}")
    lines.append(f"市场状态: {report.market_state}")
    lines.append(f"置信度: {report.confidence:.2f}%")
    
    # ========== 2. 指数概览 ==========
    if report.index_summaries:
        lines.append(f"\n" + "=" * 60)
        lines.append("【指数概览】")
        lines.append("=" * 60)
        for s in report.index_summaries:
            lines.append(f"\n▸ {s.name}")
            lines.append(f"  收盘价: {s.close:.2f}  |  涨跌幅: {s.pct_chg:.2f}%")
            if s.support_levels:
                lines.append(f"  关键支撑位: {', '.join([f'{v:.2f}' for v in s.support_levels])}")
            if s.resistance_levels:
                lines.append(f"  关键阻力位: {', '.join([f'{v:.2f}' for v in s.resistance_levels])}")
    
    # ========== 3. 分指数预测（新增，替代原趋势方向） ==========
    if report.index_predictions:
        lines.append(f"\n" + "=" * 60)
        lines.append("【分指数预测】")
        lines.append("=" * 60)
        for pred in report.index_predictions:
            trend_cn = getattr(pred, 'trend_direction_cn', pred.trend_direction)
            lines.append(f"\n▸ {pred.name} ({pred.ts_code})")
            lines.append(f"  预测方向: {trend_cn}")
            if pred.prediction_reason:
                lines.append(f"  理由: {pred.prediction_reason}")
    
    # ========== 4. 技术分析 ==========
    tech = report.technical
    if tech:
        lines.append(f"\n" + "=" * 60)
        lines.append("【技术分析】")
        lines.append("=" * 60)
        lines.append(f"\n▸ 趋势预测")
        lines.append(f"  {tech.trend_analysis}")
        lines.append(f"\n▸ 均线状态")
        lines.append(f"  {tech.ma_status}")
        lines.append(f"\n▸ MACD信号")
        lines.append(f"  {tech.macd_signal}")
        lines.append(f"\n▸ ADX趋势强度")
        lines.append(f"  {tech.adx_analysis}")
        lines. append(f"\n▸ 成交量分析")
        lines.append(f"  {tech.volume_analysis}")
        if tech.support_levels:
            lines.append(f"\n▸ 关键支撑位")
            lines.append(f"  {tech.support_levels}")
        if tech.resistance_levels:
            lines.append(f"\n▸ 关键阻力位")
            lines.append(f"  {tech.resistance_levels}")
    
    # ========== 5. 资金分析 ==========
    capital = report.capital
    if capital:
        lines.append(f"\n" + "=" * 60)
        lines.append("【资金分析】")
        lines.append("=" * 60)
        lines.append(f"\n▸ 北向资金")
        lines.append(f"  {capital.north_flow_analysis}")
        lines.append(f"\n▸ 两融数据（前一交易日）")
        lines.append(f"  {capital.margin_analysis}")

        # ---- 新增：原始资金流向数据 ----
        if capital.fund_flow_analysis:
            ff = capital.fund_flow_analysis
            lines.append(f"\n▸ 主力资金数据")
            lines.append(f"  主力净流入: {ff.net_inflow:.2f}亿 (净流入率: {ff.net_inflow_rate:.2f}%)")
            lines.append(f"  超大单: {ff.super_large_flow:.2f}亿")
            lines.append(f"  大单: {ff.large_flow:.2f}亿")
            lines.append(f"  中单: {ff.medium_flow:.2f}亿")
            lines.append(f"  小单: {ff.small_flow:.2f}亿")

        # ---- 主力资金分析文本 ----
        if capital.main_flow_analysis:
            lines.append(f"\n▸ 主力资金分析")
            lines.append(f"  {capital.main_flow_analysis}")

        lines.append(f"\n▸ 市场资金流向")
        lines.append(f"  {capital.capital_summary}")
    
    # ========== 6. 新闻分析 ==========
    news = report.news_analysis
    if news:
        lines.append(f"\n" + "=" * 60)
        lines.append("【新闻分析】")
        lines.append("=" * 60)
        
        if news.key_news:
            lines.append(f"\n▸ 重点新闻解读")
            for i, item in enumerate(news.key_news[:10], 1):
                lines.append(f"  {i}. {item}")
        
        if news.positive_factors:
            lines.append(f"\n▸ 利好因素")
            for factor in news.positive_factors[:10]:
                lines.append(f"  ✓ {factor}")
        
        if news.negative_factors:
            lines.append(f"\n▸ 利空因素")
            for factor in news.negative_factors[:10]:
                lines.append(f"  ✗ {factor}")
        
        if news.market_impact:
            lines.append(f"\n▸ 对市场的影响")
            lines.append(f"  {news.market_impact}")
        
        if news.sector_focus:
            lines.append(f"\n▸ 值得关注的板块")
            lines.append(f"  {', '.join(news.sector_focus[:10])}")
        
        if news.summary:
            lines.append(f"\n▸ 新闻面总结")
            lines.append(f"  {news.summary}")
    
    # ========== 7. 情绪分析 ==========
    sentiment = report.sentiment
    if sentiment:
        lines.append(f"\n" + "=" * 60)
        lines.append("【市场情绪】")
        lines.append("=" * 60)
        
        # 原始数据
        lines.append(f"\n▸ 市场广度")
        lines.append(f"  上涨家数: {sentiment.adv_issues}  |  下跌家数: {sentiment.dec_issues}")
        lines.append(f"  市场宽度: {sentiment.market_width:.2f}")
        lines.append(f"  涨跌比: {getattr(sentiment, 'adv_decline_ratio', 0):.2f}")
        lines.append(f"  腾落指数: {getattr(sentiment, 'ad_line', 0):.2f}")
        lines.append(f"  成交额集中度: {getattr(sentiment, 'turnover_concentration', 0):.2f}%")
        
        lines.append(f"\n▸ 情绪评分")
        lines.append(f"  综合得分: {sentiment.sentiment_score:.2f}/100")
        
        # LLM 分析文本
        if sentiment.description:
            lines.append(f"\n▸ 情绪解读")
            lines.append(f"  {sentiment.description}")
        if sentiment.breadth:
            lines.append(f"\n▸ 市场广度分析")
            lines.append(f"  {sentiment.breadth}")
        if sentiment.emotion_state:
            lines.append(f"\n▸ 情绪状态")
            lines.append(f"  {sentiment.emotion_state}")
        if sentiment.summary:
            lines.append(f"\n▸ 情绪总结")
            lines.append(f"  {sentiment.summary}")

    
    # ========== 8. 估值分析 ==========
    valuation = report.valuation
    if valuation:
        lines.append(f"\n" + "=" * 60)
        lines.append("【估值分析】")
        lines.append("=" * 60)
        lines.append(f"\n▸ 估值水平: {valuation.valuation_level}")
        lines.append(f"  市盈率(PE): {valuation.pe_value:.2f}")
        lines.append(f"  市净率(PB): {valuation.pb_value:.2f}")
        if valuation.graham_index is not None:
            lines.append(f"  格雷厄姆指数: {valuation.graham_index:.2f}")
        lines.append(f"\n▸ 估值解读")
        lines.append(f"  {valuation.valuation_analysis}")
    
    # ========== 9. 周期分析 ==========
    cycle = report.cycle
    if cycle:
        lines.append(f"\n" + "=" * 60)
        lines.append("【周期分析】")
        lines.append("=" * 60)
        lines.append(f"\n▸ 当前周期阶段: {cycle.cycle_phase}")
        lines.append(f"\n▸ 周期解读")
        lines.append(f"  {cycle.cycle_analysis}")
    
    # ========== 10. 风险评估 ==========
    risk = report.risk
    if risk:
        lines.append(f"\n" + "=" * 60)
        lines.append("【风险评估】")
        lines.append("=" * 60)
        lines.append(f"\n▸ 风险等级: {risk.risk_level}")
        if risk.risk_factors:
            lines.append(f"\n▸ 风险因素")
            for factor in risk.risk_factors:
                lines.append(f"  ⚠ {factor}")
        if risk.opportunity_factors:
            lines.append(f"\n▸ 机会因素")
            for factor in risk.opportunity_factors:
                lines.append(f"  ★ {factor}")
    
    # ========== 11. 仓位建议 ==========
    lines.append(f"\n" + "=" * 60)
    lines.append("【仓位建议】")
    lines.append("=" * 60)
    lines.append(f"\n{report.position_advice}")
    
    # ========== 13. 综合总结 ==========
    lines.append(f"\n" + "=" * 60)
    lines.append("【综合总结】")
    lines.append("=" * 60)
    lines.append(f"\n{report.summary}")
    
    return "\n".join(lines)

class PromptBuildLogger:
    """Prompt构建过程记录器"""
    
    @staticmethod
    def log_build(function_name: str, args: tuple, kwargs: dict, result: str):
        """记录prompt构建过程"""
        record = {
            'timestamp': datetime.now().isoformat(),
            'function': function_name,
            'args': args,
            'kwargs': kwargs,
            'result_length': len(result) if result else 0,
            'result_preview': result[:500] + "..." if result and len(result) > 500 else result
        }
        ALL_PROMPT_BUILDS.append(record)
        return result
    
    @staticmethod
    def wrap_function(func):
        """装饰函数以记录调用"""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            PromptBuildLogger.log_build(func.__name__, args, kwargs, result)
            return result
        return wrapper


class EnhancedPromptCaptureLLMClient:
    """
    LLM客户端包装器，用于捕获所有提示词
    
    增强功能：
    1. 捕获系统prompt和用户prompt
    2. 记录完整的调用参数
    3. 记录调用时间戳
    4. 记录响应结果
    """
    
    def __init__(self, base_client):
        self.base_client = base_client
        self.prompts = []  # 存储所有prompt记录
        self.responses = []  # 存储所有响应
    
    def chat(self, messages: List[Dict[str, str]], model: str = None, max_retries: int = None, **kwargs):
        """基础对话补全（带重试机制）"""
        # 记录调用信息
        call_info = {
            'timestamp': datetime.now().isoformat(),
            'messages': messages,
            'model': model,
            'max_retries': max_retries,
            'kwargs': kwargs,
            'prompt_length': sum(len(msg.get('content', '')) for msg in messages if msg.get('content'))
        }
        self.prompts.append(call_info)
        
        # 调用原始客户端
        start_time = time.time()
        try:
            response = self.base_client.chat(messages, model, max_retries, **kwargs)
            call_info['response'] = response
            call_info['response_length'] = len(response) if response else 0
            call_info['response_time'] = time.time() - start_time
            self.responses.append(response)
            return response
        except Exception as e:
            call_info['error'] = str(e)
            call_info['response_time'] = time.time() - start_time
            raise
    
    def chat_with_system(self, system_prompt: str, user_prompt: str, model: str = None, **kwargs):
        """带系统提示的快捷对话方法（包装器）"""
        # 记录调用信息
        call_info = {
            'timestamp': datetime.now().isoformat(),
            'system_prompt': system_prompt,
            'user_prompt': user_prompt,
            'model': model,
            'kwargs': kwargs,
            'prompt_length': len(user_prompt) if user_prompt else 0,
            'system_prompt_length': len(system_prompt) if system_prompt else 0
        }
        self.prompts.append(call_info)
        
        # 调用原始客户端
        start_time = time.time()
        try:
            response = self.base_client.chat_with_system(system_prompt, user_prompt, model, **kwargs)
            call_info['response'] = response
            call_info['response_length'] = len(response) if response else 0
            call_info['response_time'] = time.time() - start_time
            self.responses.append(response)
            return response
        except Exception as e:
            call_info['error'] = str(e)
            call_info['response_time'] = time.time() - start_time
            raise
    
    def __getattr__(self, name):
        """代理其他属性到原始客户端"""
        return getattr(self.base_client, name)


def hook_market_prompts():
    """
    Hook market_prompts.py中的prompt构建函数
    以记录完整的prompt构建过程
    """
    try:
        from agents.analysis.market import market_prompts
        
        # 需要hook的函数列表
        functions_to_hook = [
            'build_technical_analysis_prompt',
            'build_capital_analysis_prompt',
            'build_sentiment_analysis_prompt',
            'build_valuation_cycle_analysis_prompt',
            'build_news_analysis_prompt',
            'build_synthesis_prompt',
            'build_review_prompt',
            'format_news_data',
            'format_history_analysis',
            'format_review_reports',
            'format_verification_results'
        ]
        
        # 应用hook
        hooked_functions = {}
        for func_name in functions_to_hook:
            if hasattr(market_prompts, func_name):
                original_func = getattr(market_prompts, func_name)
                hooked_func = PromptBuildLogger.wrap_function(original_func)
                setattr(market_prompts, func_name, hooked_func)
                hooked_functions[func_name] = original_func
        
        print(f"[HOOK] 已hook {len(hooked_functions)} 个prompt构建函数")
        return hooked_functions
    
    except ImportError as e:
        print(f"[WARNING] 无法导入market_prompts: {e}")
        return {}
    except Exception as e:
        print(f"[ERROR] Hook market_prompts失败: {e}")
        return {}


def save_prompt_build_logs():
    """保存所有prompt构建日志到文件"""
    if not ALL_PROMPT_BUILDS:
        print("[INFO] 没有prompt构建日志可保存")
        return
    
    append_to_prompt("=" * 80)
    append_to_prompt(f"[PROMPT BUILD LOGS] Prompt构建过程记录 - {TEST_DATE}")
    append_to_prompt("=" * 80)
    
    for i, log in enumerate(ALL_PROMPT_BUILDS, 1):
        append_to_prompt(f"\n{'='*80}")
        append_to_prompt(f"[PROMPT BUILD {i}] {log['function']}")
        append_to_prompt(f"{'='*80}")
        
        append_to_prompt(f"\n[时间戳] {log['timestamp']}")
        append_to_prompt(f"[函数名称] {log['function']}")
        append_to_prompt(f"[结果长度] {log['result_length']} 字符")
        
        # 显示参数信息
        if log['args']:
            append_to_prompt(f"\n[位置参数]")
            for j, arg in enumerate(log['args']):
                arg_str = str(arg)
                if len(arg_str) > 200:
                    arg_str = arg_str[:200] + "..."
                append_to_prompt(f"  arg{j}: {arg_str}")
        
        if log['kwargs']:
            append_to_prompt(f"\n[关键字参数]")
            for key, value in log['kwargs'].items():
                val_str = str(value)
                if len(val_str) > 200:
                    val_str = val_str[:200] + "..."
                append_to_prompt(f"  {key}: {val_str}")
        
        # 显示结果预览
        if log['result_preview']:
            append_to_prompt(f"\n[结果预览]")
            append_to_prompt(log['result_preview'])
    
    append_to_prompt(f"\n{'='*80}")
    append_to_prompt(f"[TOTAL] 共记录 {len(ALL_PROMPT_BUILDS)} 个prompt构建过程")
    append_to_prompt("=" * 80)


def save_llm_call_logs(llm_client: EnhancedPromptCaptureLLMClient):
    """保存所有LLM调用日志到文件"""
    if not llm_client.prompts:
        print("[INFO] 没有LLM调用日志可保存")
        return
    
    append_to_prompt("=" * 80)
    append_to_prompt(f"[LLM CALL LOGS] LLM调用记录 - {TEST_DATE}")
    append_to_prompt("=" * 80)
    
    for i, call in enumerate(llm_client.prompts, 1):
        append_to_prompt(f"\n{'='*80}")
        append_to_prompt(f"[LLM CALL {i}]")
        append_to_prompt("=" * 80)
        
        append_to_prompt(f"\n[时间戳] {call['timestamp']}")
        if 'response_time' in call:
            append_to_prompt(f"[响应时间] {call['response_time']:.2f}秒")
        
        # 系统prompt
        if call.get('system_prompt'):
            append_to_prompt("\n[SYSTEM PROMPT]")
            append_to_prompt("-" * 40)
            append_to_prompt(call['system_prompt'])
            append_to_prompt(f"[长度] {call['system_prompt_length']} 字符")
        
        # 用户prompt
        if call.get('user_prompt'):
            append_to_prompt("\n[USER PROMPT]")
            append_to_prompt("-" * 40)
            append_to_prompt(call['user_prompt'])
            append_to_prompt(f"[长度] {call['prompt_length']} 字符")
        
        # 响应
        if call.get('response'):
            append_to_prompt("\n[RESPONSE]")
            append_to_prompt("-" * 40)
            response_preview = call['response']
            if len(response_preview) > 1000:
                response_preview = response_preview[:1000] + "..."
            append_to_prompt(response_preview)
            append_to_prompt(f"[长度] {call['response_length']} 字符")
        
        # 错误
        if call.get('error'):
            append_to_prompt(f"\n[ERROR] {call['error']}")
    
    append_to_prompt(f"\n{'='*80}")
    append_to_prompt(f"[TOTAL] 共记录 {len(llm_client.prompts)} 次LLM调用")
    append_to_prompt("=" * 80)


def run_analysis_with_full_output(trade_date: str, llm_client, memory_manager) -> dict:
    print(f"\n{'='*80}")
    print(f"[ANALYSIS] 分析日期: {trade_date}")
    print(f"{'='*80}")

    append_to_report(f"\n{'='*80}")
    append_to_report(f"[ANALYSIS] 分析日期: {trade_date}")
    append_to_report(f"{'='*80}\n")

    # 创建分析师实例（llm_client 和 memory_manager 由外部传入）
    analyst = MarketAnalyst(llm_client=llm_client, memory_manager=memory_manager)

    # 执行分析（execute 会自动创建会话、管理状态）
    result = analyst.execute(input_data={'trade_date': trade_date})

    if result and result.success:
        report = result.data

        # 获取 execute 内部创建的会话 ID
        session_id = analyst._session_id
        news_raw = None
        index_raw = {}

        if session_id and memory_manager:
            # 从工作记忆中读取原始新闻数据（由 _get_news_data 存储）
            try:
                news_raw = memory_manager.working_memory.get(session_id, "news_full_data")
                if news_raw:
                    print(f"\n[工作记忆] 获取到 {len(news_raw)} 条原始新闻数据")
                    append_to_report(f"\n[工作记忆] 获取到 {len(news_raw)} 条原始新闻数据")
            except Exception as e:
                print(f"[工作记忆] 读取新闻数据失败: {e}")

            # 从工作记忆中读取原始指数数据（由 _run_normal_mode 存储）
            for code in MarketAnalyst.INDEX_CODES:
                try:
                    data = memory_manager.working_memory.get(session_id, f"index_{code}")
                    if data:
                        index_raw[code] = data
                except:
                    pass
            if index_raw:
                print(f"\n[工作记忆] 获取到 {len(index_raw)} 个指数原始数据")
                append_to_report(f"\n[工作记忆] 获取到 {len(index_raw)} 个指数原始数据")

        # 打印原始新闻数据（如果存在）
        if news_raw:
            print("\n" + "="*80)
            print("[STEP 2] 原始新闻数据")
            print("="*80)
            append_to_report("\n[STEP 2] 原始新闻数据")
            for i, news in enumerate(news_raw[:10], 1):
                title = news.get('title', 'N/A')
                time_str = news.get('publish_time', 'N/A')
                print(f"  {i}. [{time_str}] {title[:80]}...")
                append_to_report(f"  {i}. [{time_str}] {title}")
            if len(news_raw) > 10:
                print(f"  ... 还有 {len(news_raw) - 10} 条新闻")
                append_to_report(f"  ... 还有 {len(news_raw) - 10} 条新闻")

        # 打印原始指数数据（可选，这里仅示意打印收盘价）
        if index_raw:
            print("\n" + "="*80)
            print("[STEP 1] 原始指数数据")
            print("="*80)
            append_to_report("\n[STEP 1] 原始指数数据")
            for code, data in index_raw.items():
                price = data.get('price_data', {})
                close = price.get('close', 0)
                pct = price.get('pct_chg', 0)
                print(f"  - {code}: 收盘 {close:.2f} 涨跌 {pct:.2f}%")
                append_to_report(f"  - {code}: 收盘 {close:.2f} 涨跌 {pct:.2f}%")

        # 输出分析报告
        print("\n" + "="*80)
        print("[STEP 4] 分析结果")
        print("="*80)
        append_to_report("\n[STEP 4] 分析结果")

        report_text = format_report(report)
        append_to_report(f"\n[REPORT] 完整分析报告:")
        append_to_report(report_text)

        print(report_text[:500] + "..." if len(report_text) > 500 else report_text)
        print(f"\n[OK] 分析完成: {trade_date}")
        append_to_report(f"\n[OK] 分析完成: {trade_date}")

        return {'success': True, 'date': trade_date, 'report': report}
    else:
        error_msg = result.error if result else "未知错误"
        append_to_report(f"[ERROR] 分析失败: {error_msg}")
        print(f"[ERROR] 分析失败: {error_msg}")
        return {'success': False, 'date': trade_date, 'error': error_msg}


def main():
    print("\n" + "="*80)
    print(f"[ENHANCED TEST] 增强版单日分析测试脚本 - {TEST_DATE}")
    print("="*80)
    
    # 清空报告文件和提示词文件
    clear_files()
    
    # Hook market_prompts函数
    hooked_functions = hook_market_prompts()
    
    # 初始化
    print("\n[INIT] 初始化LLM和记忆管理器...")
    base_llm_client = LLMClient()
    llm_client = EnhancedPromptCaptureLLMClient(base_llm_client)
    memory_manager = MemoryManager()
    
    # 写入报告头部
    append_to_report("="*80)
    append_to_report(f"[ENHANCED REPORT] 大盘分析完整测试报告 - {TEST_DATE}")
    append_to_report("="*80)
    append_to_report(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    append_to_report(f"测试脚本: test_tool/test_market_analyst_enhanced.py")
    append_to_report("")
    
    # 写入提示词头部
    append_to_prompt("="*80)
    append_to_prompt(f"[ENHANCED PROMPTS] 大盘分析完整提示词记录 - {TEST_DATE}")
    append_to_prompt("="*80)
    append_to_prompt(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    append_to_prompt(f"测试脚本: test_tool/test_market_analyst_enhanced.py")
    append_to_prompt("")
    
    # 记录系统提示词
    try:
        from agents.analysis.market.market_prompts import SYSTEM_PROMPT_MARKET_ANALYST
        append_to_prompt("\n[SYSTEM PROMPT - MARKET ANALYST]")
        append_to_prompt("="*80)
        append_to_prompt(SYSTEM_PROMPT_MARKET_ANALYST)
    except ImportError:
        append_to_prompt("\n[WARNING] 无法导入系统提示词")
    
    # 执行分析
    print("\n[INFO] 开始执行大盘分析...")
    result = run_analysis_with_full_output(TEST_DATE, llm_client, memory_manager)
    
    # 保存所有提示词记录
    print("\n[INFO] 保存提示词记录...")
    save_prompt_build_logs()
    save_llm_call_logs(llm_client)
    
    # 输出汇总
    print("\n" + "="*80)
    print("[SUMMARY] 测试汇总")
    print("="*80)
    append_to_report(f"\n{'='*80}")
    append_to_report("[SUMMARY] 测试汇总")
    append_to_report("="*80)
    
    if result.get('success'):
        print(f"[OK] 测试成功: {TEST_DATE}")
        append_to_report(f"[OK] 测试成功: {TEST_DATE}")
        
        # 输出统计信息
        print(f"[STATS] 捕获 {len(ALL_PROMPT_BUILDS)} 个prompt构建过程")
        print(f"[STATS] 记录 {len(llm_client.prompts)} 次LLM调用")
        append_to_report(f"[STATS] 捕获 {len(ALL_PROMPT_BUILDS)} 个prompt构建过程")
        append_to_report(f"[STATS] 记录 {len(llm_client.prompts)} 次LLM调用")
    else:
        print(f"[ERROR] 测试失败: {result.get('error', '未知错误')}")
        append_to_report(f"[ERROR] 测试失败: {result.get('error', '未知错误')}")
    
    print(f"\n报告已保存到: {os.path.abspath(REPORT_FILE)}")
    print(f"提示词已保存到: {os.path.abspath(PROMPT_FILE)}")
    append_to_report(f"\n报告文件: {os.path.abspath(REPORT_FILE)}")
    append_to_report(f"提示词文件: {os.path.abspath(PROMPT_FILE)}")
    
    # 显示文件大小
    try:
        report_size = os.path.getsize(REPORT_FILE)
        prompt_size = os.path.getsize(PROMPT_FILE)
        print(f"[INFO] 报告文件大小: {report_size/1024:.2f} KB")
        print(f"[INFO] 提示词文件大小: {prompt_size/1024:.2f} KB")
    except OSError:
        pass


if __name__ == "__main__":
    main()