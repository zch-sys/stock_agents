"""
板块分析师增强测试脚本

测试 SectorAnalyst 的完整分析流程：
1. 捕获完整的 prompt 构建过程
2. 调用真实 LLM 进行分析
3. 输出 prompt txt 文件和分析结果 txt 文件
4. 记录所有 LLM 调用和 prompt 构建过程

测试日期：2026-03-06
"""

import sys
import os
import time
import json
import re
import functools
from datetime import datetime
from typing import List, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.basic_data.database import init_db, get_session
from data.basic_data.config_manager import load_config
from core.llm.llm_client import LLMClient
from core.memory.memory_manager import MemoryManager
from agents.analysis.sector.sector_analyst import SectorAnalyst
from agents.analysis.sector.sector_prompts import (
    SYSTEM_PROMPT_SECTOR_ANALYST,

)

# 获取项目根目录和报告输出目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(PROJECT_ROOT, "test_report")

# 确保报告目录存在
os.makedirs(REPORT_DIR, exist_ok=True)

# 测试配置
TEST_DATE = "2026-03-11"
REPORT_FILE = os.path.join(REPORT_DIR, f"sector_report_{TEST_DATE.replace('-', '')}.txt")
PROMPT_FILE = os.path.join(REPORT_DIR, f"sector_prompts_{TEST_DATE.replace('-', '')}.txt")

# 存储所有提示词构建记录
ALL_PROMPT_BUILDS = []


def clear_files():
    """清空报告文件和提示词文件"""
    for filename in [REPORT_FILE, PROMPT_FILE]:
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("")
            print(f"[OK] 已清空文件: {filename}")
        except Exception as e:
            print(f"[WARNING] 清空文件失败 {filename}: {e}")


def append_to_prompt(content: str):
    """追加内容到提示词文件"""
    try:
        with open(PROMPT_FILE, 'a', encoding='utf-8') as f:
            f.write(content + "\n")
    except Exception as e:
        print(f"[ERROR] 写入提示词文件失败: {e}")


def append_to_report(content: str):
    """追加内容到报告文件"""
    # Windows控制台可能无法显示某些Unicode字符，使用安全打印
    try:
        print(content)
    except UnicodeEncodeError:
        # 替换无法编码的字符
        safe_content = content.encode('gbk', errors='replace').decode('gbk')
        print(safe_content)
    try:
        with open(REPORT_FILE, 'a', encoding='utf-8') as f:
            f.write(content + "\n")
    except Exception as e:
        print(f"[ERROR] 写入报告文件失败: {e}")


def format_sector_report(report) -> str:
    """
    格式化板块分析报告
    
    输出顺序：
    1. 基本信息
    2. 市场广度
    3. 热门板块
    4. 资金流入板块
    5. 风险板块
    6. 板块轮动
    7. 热门分析
    8. 资金分析
    9. 风险分析
    10. 轮动信号
    11. 综合总结
    12. 明日展望
    """
    lines = []
    
    # 1. 基本信息
    lines.append("=" * 60)
    lines.append("【板块分析报告】")
    lines.append("=" * 60)
    lines.append(f"分析日期: {report.date}")
    lines.append(f"置信度: {report.confidence:.2f}%")
    lines.append(f"分析板块总数: {report.total_sectors_analyzed}")
    lines.append(f"重点板块数量: {report.focus_sectors_count}")
    
    # 2. 市场广度
    if report.market_breadth:
        lines.append("\n" + "=" * 60)
        lines.append("【市场广度】")
        lines.append("=" * 60)
        lines.append(f"板块总数: {report.market_breadth.total_sectors}")
        lines.append(f"上涨板块: {report.market_breadth.adv_sector_count}")
        lines.append(f"下跌板块: {report.market_breadth.dec_sector_count}")
        lines.append(f"平均涨跌幅: {report.market_breadth.avg_pct_chg:.2f}%")
        lines.append(f"市场状态: {report.market_breadth.market_breadth_state}")
    
    # 3. 热门板块
    if report.hot_sectors:
        lines.append("\n" + "=" * 60)
        lines.append("【热门板块 TOP 10】")
        lines.append("=" * 60)
        for i, sector in enumerate(report.hot_sectors[:10], 1):
            lines.append(f"{i}. {sector.sector_name}")
            lines.append(f"   代码: {sector.sector_code}")
            lines.append(f"   排名: {sector.rank} (变化: {'+' if sector.rank_change > 0 else ''}{sector.rank_change})")
            lines.append(f"   涨跌幅: {sector.pct_chg:.2f}%")
            lines.append(f"   成交额: {sector.amount/100000000:.2f}亿")
            if sector.fund_inflow:
                lines.append(f"   资金净流入: {sector.fund_inflow/100000000:.2f}亿")
            if sector.continuous_strong_days > 0:
                lines.append(f"   连续强势: {sector.continuous_strong_days}天")
            lines.append("")
    
    # 4. 资金流入板块
    if report.capital_flow_sectors:
        lines.append("\n" + "=" * 60)
        lines.append("【资金流入板块 TOP 10】")
        lines.append("=" * 60)
        for i, sector in enumerate(report.capital_flow_sectors[:10], 1):
            lines.append(f"{i}. {sector.sector_name}")
            lines.append(f"   代码: {sector.sector_code}")
            if sector.fund_inflow:
                lines.append(f"   资金净流入: {sector.fund_inflow/100000000:.2f}亿")
            lines.append(f"   涨跌幅: {sector.pct_chg:.2f}%")
            lines.append("")
    
    # 5. 风险板块
    if report.risk_sectors:
        lines.append("\n" + "=" * 60)
        lines.append("【风险板块 TOP 10】")
        lines.append("=" * 60)
        for i, sector in enumerate(report.risk_sectors[:10], 1):
            lines.append(f"{i}. {sector.sector_name}")
            lines.append(f"   代码: {sector.sector_code}")
            lines.append(f"   排名: {sector.rank}")
            lines.append(f"   涨跌幅: {sector.pct_chg:.2f}%")
            lines.append("")
    
    # 6. 板块轮动
    if report.sector_rotation:
        lines.append("\n" + "=" * 60)
        lines.append("【板块轮动】")
        lines.append("=" * 60)
        if report.sector_rotation.new_hot_sectors:
            lines.append(f"新晋热门: {', '.join(report.sector_rotation.new_hot_sectors)}")
        if report.sector_rotation.persistent_hot_sectors:
            lines.append(f"持续强势: {', '.join(report.sector_rotation.persistent_hot_sectors)}")
        if report.sector_rotation.cooling_sectors:
            lines.append(f"降温板块: {', '.join(report.sector_rotation.cooling_sectors)}")
    
    # 6.5 30日趋势分析
    if hasattr(report, 'trends_30d') and report.trends_30d:
        lines.append("\n" + "=" * 60)
        lines.append("【30日趋势分析】")
        lines.append("=" * 60)
        
        # 近30日热门板块
        hot_30d = report.trends_30d.get('hot_30d', [])
        if hot_30d:
            lines.append("\n>>> 近30日热门板块 TOP 10（累计涨幅排名）")
            lines.append("-" * 50)
            for i, s in enumerate(hot_30d[:10], 1):
                name = s.sector_name
                pct_30d = s.pct_chg_30d
                fund_30d = s.fund_inflow_30d / 1e8  # 转亿
                strong_days = s.strong_days_30d
                trend_cn = s.trend_type_cn
                lines.append(f"{i}. {name}: 30日涨幅 {pct_30d:+.1f}%, 资金 {fund_30d:+.1f}亿, 强势{strong_days}天 [{trend_cn}]")
        
        # 近30日风险板块
        risk_30d = report.trends_30d.get('risk_30d', [])
        if risk_30d:
            lines.append("\n>>> 近30日风险板块 TOP 10（累计跌幅排名）")
            lines.append("-" * 50)
            for i, s in enumerate(risk_30d[:10], 1):
                name = s.sector_name
                pct_30d = s.pct_chg_30d
                fund_30d = s.fund_inflow_30d / 1e8
                trend_cn = s.trend_type_cn
                lines.append(f"{i}. {name}: 30日跌幅 {pct_30d:.1f}%, 资金 {fund_30d:.1f}亿 [{trend_cn}]")
    
    # 7. 热门分析
    if report.hot_analysis:
        lines.append("\n" + "=" * 60)
        lines.append("【热门板块分析】")
        lines.append("=" * 60)
        lines.append(f"总结: {report.hot_analysis.hot_sectors_summary}")
        if report.hot_analysis.hot_reasons:
            lines.append("\n强势原因:")
            for reason in report.hot_analysis.hot_reasons:
                lines.append(f"  • {reason}")
        lines.append(f"\n持续性判断: {report.hot_analysis.sustainability}")
        # 明日热门预测
        if hasattr(report.hot_analysis, 'predicted_hot_sectors') and report.hot_analysis.predicted_hot_sectors:
            lines.append(f"\n明日热门预测: {', '.join(report.hot_analysis.predicted_hot_sectors)}")
        if hasattr(report.hot_analysis, 'predicted_reason') and report.hot_analysis.predicted_reason:
            lines.append(f"预测理由: {report.hot_analysis.predicted_reason}")
    
    # 8. 资金分析
    if report.capital_analysis:
        lines.append("\n" + "=" * 60)
        lines.append("【资金流向分析】")
        lines.append("=" * 60)
        lines.append(f"总结: {report.capital_analysis.capital_flow_summary}")
        if report.capital_analysis.main_focus:
            lines.append("\n主力关注:")
            for focus in report.capital_analysis.main_focus:
                lines.append(f"  • {focus}")
        lines.append(f"\n资金轮动: {report.capital_analysis.capital_rotation}")
    
    # 9. 风险分析
    if report.risk_analysis:
        lines.append("\n" + "=" * 60)
        lines.append("【风险分析】")
        lines.append("=" * 60)
        lines.append(f"总结: {report.risk_analysis.risk_sectors_summary}")
        if report.risk_analysis.risk_reasons:
            lines.append("\n风险原因:")
            for reason in report.risk_analysis.risk_reasons:
                lines.append(f"  • {reason}")
        lines.append(f"\n规避建议: {report.risk_analysis.avoid_advice}")
    
    # 10. 轮动信号
    if report.rotation_signal:
        lines.append("\n" + "=" * 60)
        lines.append("【轮动信号】")
        lines.append("=" * 60)
        lines.append(report.rotation_signal)
    
    # 11. 综合总结
    if report.summary:
        lines.append("\n" + "=" * 60)
        lines.append("【综合总结】")
        lines.append("=" * 60)
        lines.append(report.summary)
    
    # 12. 明日展望
    if report.tomorrow_outlook:
        lines.append("\n" + "=" * 60)
        lines.append("【明日展望】")
        lines.append("=" * 60)
        lines.append(report.tomorrow_outlook)
    
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


def hook_sector_prompts():
    """
    Hook sector_prompts.py中的prompt构建函数
    以记录完整的prompt构建过程
    """
    try:
        import agents.analysis.sector.sector_prompts as sector_prompts
        
        # 需要hook的函数列表
        functions_to_hook = [
            'build_sector_analysis_prompt',
            'build_sector_review_prompt',
            'format_sector_overview',
            'format_hot_sectors_data',
            'format_capital_flow_data',
            'format_risk_sectors_data',
            'format_rotation_data',
            'format_market_breadth_data',
            'format_30d_trend_data',
        ]
        
        # 应用hook
        hooked_functions = {}
        for func_name in functions_to_hook:
            if hasattr(sector_prompts, func_name):
                original_func = getattr(sector_prompts, func_name)
                hooked_func = PromptBuildLogger.wrap_function(original_func)
                setattr(sector_prompts, func_name, hooked_func)
                hooked_functions[func_name] = original_func
        
        print(f"[HOOK] 已hook {len(hooked_functions)} 个sector prompt构建函数")
        return hooked_functions
    
    except ImportError as e:
        print(f"[WARNING] 无法导入sector_prompts: {e}")
        return {}
    except Exception as e:
        print(f"[ERROR] Hook sector_prompts失败: {e}")
        return {}


def save_prompt_build_logs():
    """保存所有prompt构建日志到文件"""
    if not ALL_PROMPT_BUILDS:
        print("[INFO] 没有prompt构建日志可保存")
        return
    
    append_to_prompt("=" * 80)
    append_to_prompt(f"[PROMPT BUILD LOGS] Sector Prompt构建过程记录 - {TEST_DATE}")
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
    append_to_prompt(f"[LLM CALL LOGS] Sector LLM调用记录 - {TEST_DATE}")
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


def run_sector_analysis(trade_date: str, llm_client, memory_manager) -> dict:
    """
    运行板块分析并输出完整信息
    
    Args:
        trade_date: 交易日期
        llm_client: LLM客户端
        memory_manager: 记忆管理器
    """
    print(f"\n{'='*80}")
    print(f"[SECTOR ANALYSIS] 板块分析日期: {trade_date}")
    print(f"{'='*80}")

    append_to_report(f"\n{'='*80}")
    append_to_report(f"[SECTOR ANALYSIS] 板块分析日期: {trade_date}")
    append_to_report(f"{'='*80}\n")

    # 创建分析师实例
    analyst = SectorAnalyst(llm_client=llm_client, memory_manager=memory_manager)

    # 构建输入数据
    # 注：大盘新闻分析由 sector_analyst 自动从记忆中获取，无需手动传入
    input_data = {'trade_date': trade_date, 'mode': 'normal'}

    # 执行分析
    result = analyst.execute(input_data=input_data)

    if result and result.success:
        report = result.data

        # 获取 execute 内部创建的会话 ID
        session_id = analyst._session_id

        if session_id and memory_manager:
            # 从工作记忆中读取原始数据
            try:
                hot_sectors = memory_manager.working_memory.get(session_id, "hot_sectors")
                if hot_sectors:
                    print(f"[工作记忆] 获取到 {len(hot_sectors)} 个热门板块数据")
                    append_to_report(f"[工作记忆] 获取到 {len(hot_sectors)} 个热门板块数据")
            except Exception as e:
                print(f"[工作记忆] 读取热门板块数据失败: {e}")

        # 输出分析报告
        print("\n" + "="*80)
        print("[SECTOR REPORT] 板块分析结果")
        print("="*80)
        append_to_report("\n[SECTOR REPORT] 板块分析结果")

        report_text = format_sector_report(report)
        append_to_report(f"\n[REPORT] 完整板块分析报告:")
        append_to_report(report_text)

        print(report_text[:500] + "..." if len(report_text) > 500 else report_text)
        print(f"\n[OK] 板块分析完成: {trade_date}")
        append_to_report(f"\n[OK] 板块分析完成: {trade_date}")

        return {'success': True, 'date': trade_date, 'report': report}
    else:
        error_msg = result.error if result else "未知错误"
        append_to_report(f"[ERROR] 板块分析失败: {error_msg}")
        print(f"[ERROR] 板块分析失败: {error_msg}")
        return {'success': False, 'date': trade_date, 'error': error_msg}


def main():
    """主函数"""
    print("\n" + "="*80)
    print(f"[ENHANCED SECTOR TEST] 板块分析师增强测试脚本 - {TEST_DATE}")
    print("="*80)
    
    # 清空报告文件和提示词文件
    clear_files()
    
    # Hook sector_prompts函数
    hooked_functions = hook_sector_prompts()
    
    # 初始化
    print("\n[INIT] 初始化LLM和记忆管理器...")
    try:
        base_llm_client = LLMClient()
        llm_client = EnhancedPromptCaptureLLMClient(base_llm_client)
        memory_manager = MemoryManager()
    except Exception as e:
        print(f"[ERROR] 初始化失败: {e}")
        return
    
    # 写入报告头部
    append_to_report("="*80)
    append_to_report(f"[ENHANCED SECTOR REPORT] 板块分析完整测试报告 - {TEST_DATE}")
    append_to_report("="*80)
    append_to_report(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    append_to_report(f"测试脚本: test_sector_analyst_enhanced.py")
    append_to_report("")
    
    # 写入提示词头部
    append_to_prompt("="*80)
    append_to_prompt(f"[ENHANCED SECTOR PROMPTS] 板块分析完整提示词记录 - {TEST_DATE}")
    append_to_prompt("="*80)
    append_to_prompt(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    append_to_prompt(f"测试脚本: test_sector_analyst_enhanced.py")
    append_to_prompt("")
    
    # 记录系统提示词
    try:
        append_to_prompt("\n[SYSTEM PROMPT - SECTOR ANALYST]")
        append_to_prompt("="*80)
        append_to_prompt(SYSTEM_PROMPT_SECTOR_ANALYST)
    except Exception as e:
        append_to_prompt(f"\n[WARNING] 无法获取系统提示词: {e}")
    
    # 初始化数据库
    print("\n[INFO] 初始化数据库连接...")
    try:
        config = load_config()
        db_url = config.get('data_collector', {}).get('db_url')
        if db_url:
            init_db(db_url)
            print(f"[DB] 数据库连接初始化成功")
    except Exception as e:
        print(f"[WARNING] 数据库初始化失败，可能影响数据获取: {e}")
    
    # 执行板块分析
    print("\n[INFO] 开始执行板块分析...")
    result = run_sector_analysis(TEST_DATE, llm_client, memory_manager)
    
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