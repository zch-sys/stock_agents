#!/usr/bin/env python3
"""
增强版选股分析师调试脚本
详细记录整个选股过程，包括每个步骤、working_memory、所有工具调用等
输出到test_report目录下的txt文件
"""

import sys
import os
import logging
import json
from datetime import date, datetime
from datetime import datetime as dt
import time

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 输出文件路径
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_report")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 全局日志内容
debug_log = []

# 需要过滤掉的冗余字段
REDUNDANT_FIELDS = [
    'continuous_strong_days', 'rank_change', 'adv_issues', 'dec_issues',
    'rise_fall_ratio', 'leading_stocks', 'internal_analysis', 'strength_reason',
    'fund_inflow_rate', 'filter_source', 'emotion_state', 'market_impact',
    'smart_money_signal', 'main_signal'
]

def filter_redundant_fields(data, depth=0):
    """递归过滤掉冗余的空值字段"""
    if depth > 5:  # 防止无限递归
        return data
    
    if isinstance(data, dict):
        filtered = {}
        for key, value in data.items():
            # 跳过冗余字段
            if key in REDUNDANT_FIELDS:
                continue
            # 跳过空值
            if value in [None, '', [], {}]:
                continue
            if isinstance(value, (int, float)) and value == 0:
                continue
            # 递归处理
            filtered[key] = filter_redundant_fields(value, depth + 1)
        return filtered
    elif isinstance(data, list):
        return [filter_redundant_fields(item, depth + 1) for item in data]
    else:
        return data

def log_section(title):
    """记录章节标题"""
    line = "=" * 80
    log(f"\n{line}")
    log(f" {title}")
    log(f"{line}")

def log(message):
    """记录日志"""
    print(message)
    debug_log.append(message)

def save_log_to_file():
    """保存日志到文件"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"selection_debug_{timestamp}.txt"
    filepath = os.path.join(OUTPUT_DIR, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(debug_log))
    
    print(f"\n[保存] 调试日志已保存到: {filepath}")
    return filepath

def setup_dependencies():
    """初始化依赖组件"""
    from core.llm.llm_client import LLMClient
    from core.memory.memory_manager import MemoryManager
    from core.tools.tool_registry import ToolRegistry
    from core.tools.selection_tools import register_selection_tools
    
    # 1. LLM 客户端
    llm_client = LLMClient()
    
    # 2. 记忆管理器
    memory_manager = MemoryManager()
    
    # 3. 工具注册中心
    tool_registry = ToolRegistry()
    register_selection_tools(tool_registry)
    
    log("[OK] 依赖组件初始化完成")
    
    return llm_client, memory_manager, tool_registry


def test_stock_selection_agent_detailed():
    """详细测试选股分析师Agent - 增强版"""
    log_section("4. 选股分析师Agent完整流程测试")
    
    # 初始化依赖
    try:
        llm_client, memory_manager, tool_registry = setup_dependencies()
    except Exception as e:
        log(f"[ERROR] 依赖初始化失败: {e}")
        return False
    
    # 创建选股分析师
    try:
        from agents.analysis.selection import StockSelectionAgent
        
        agent = StockSelectionAgent(
            memory_manager=memory_manager,
            llm_client=llm_client,
            tool_registry=tool_registry
        )
        
        log(f"[OK] Agent创建成功: {agent.agent_id}")
        
        # 测试输入验证
        log("\n### 4.1 输入验证")
        valid_input = {
            "trade_date": date.today().isoformat(),
            "pool_types": ["SHORT", "MID", "LONG", "WHITE_HORSE"]
        }
        
        validation_error = agent.validate_input(valid_input)
        if validation_error:
            log(f"[ERROR] 输入验证失败: {validation_error}")
            return False
        else:
            log("[OK] 输入验证通过")
        
        # 执行选股分析
        log("\n### 4.2 执行选股分析")
        log(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        start_time = time.time()
        
        try:
            # 修复: 移除context参数，BaseAgent.execute只接受input_data和task_id
            result = agent.execute(valid_input)
            end_time = time.time()
            
            log(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            log(f"总耗时: {end_time - start_time:.1f}秒")
            
            # 获取session_id (在execute内部自动创建)
            session_id = agent._session_id
            
            # 输出Agent内部状态
            log("\n### 4.3 Agent内部状态")
            log(f"轨迹步数: {len(agent._trajectory)}")
            log(f"思考记录数: {len(agent._thoughts)}")
            log(f"候选池大小: {len(agent._candidate_pool)}")
            log(f"已分析股票数: {len(agent._stock_analyses)}")
            
            # 输出完整轨迹
            log("\n### 4.4 完整ReAct轨迹")
            for i, step in enumerate(agent._trajectory):
                log(f"\n--- Step {i+1} ---")
                log(f"Thought: {step.get('thought', 'N/A')}")
                log(f"Action: {step.get('action', 'N/A')}")
                log(f"Params: {json.dumps(step.get('params', {}), ensure_ascii=False, indent=2)}")
                observation = step.get('observation', '')
                if len(observation) > 2000:
                    observation = observation[:2000] + "\n... (截断)"
                log(f"Observation:\n{observation}")
            
            # 输出思考记录
            log("\n### 4.5 思考记录")
            for thought in agent._thoughts:
                log(f"Step {thought.step} [{thought.category}]: {thought.thought}")
            
            # 输出候选池
            log("\n### 4.6 候选股票池")
            log(f"共 {len(agent._candidate_pool)} 支股票:")
            for ts_code in sorted(agent._candidate_pool):
                log(f"  {ts_code}")
            
            # 输出股票分析结果
            log("\n### 4.7 股票详细分析结果")
            for ts_code, analysis in agent._stock_analyses.items():
                log(f"\n--- {ts_code}: {analysis.get('name', 'N/A')} ---")
                log(f"行业: {analysis.get('industry', 'N/A')}")
                log(f"市值: {analysis.get('total_mv', 0):.2f}亿")
                log(f"PE: {analysis.get('pe', 0):.2f}")
                log(f"PB: {analysis.get('pb', 0):.2f}")
                
                tech = analysis.get('technical', {})
                if tech:
                    log(f"技术指标: MA5={tech.get('ma5', 0):.2f}, MA10={tech.get('ma10', 0):.2f}, MA20={tech.get('ma20', 0):.2f}")
                    log(f"MACD: {tech.get('macd', 0):.4f}, RSI6: {tech.get('rsi6', 0):.2f}")
                
                price_history = analysis.get('price_history', [])
                if price_history:
                    log(f"3日价格:")
                    for p in price_history:
                        log(f"  {p['trade_date']}: 收{p['close']:.2f} 涨幅{p['pct_chg']:.2f}%")
            
            # 输出Working Memory内容
            log("\n### 4.8 Working Memory内容")
            if memory_manager and session_id:
                wm_data = memory_manager.working_memory.get_all(session_id)
                log(f"Working Memory键数: {len(wm_data)}")
                for key, value in wm_data.items():
                    log(f"\n--- {key} ---")
                    if isinstance(value, dict):
                        log(json.dumps(value, ensure_ascii=False, indent=2))
                    else:
                        log(str(value))
            else:
                log(f"session_id: {session_id}")
            
            # 输出选股结果
            log("\n### 4.9 最终选股结果")
            if result.success:
                report = result.data
                log(f"[OK] 选股成功！")
                
                log(f"\n交易日期: {report.trade_date}")
                log(f"置信度: {report.confidence}%")
                log(f"\n市场观点:\n{report.market_view}")
                
                log(f"\n关注板块 ({len(report.sector_focus)} 个):")
                for sector in report.sector_focus:
                    log(f"  - {sector.sector_name} ({sector.sector_code}): {sector.reason}")
                
                log(f"\n候选股票 ({len(report.candidate_stocks)} 支):")
                for stock in report.candidate_stocks:
                    log(f"  - {stock.ts_code} ({stock.name}): 池={stock.pool_type}, 排名={stock.model_rank}, 板块={stock.sector}")
                
                log(f"\n最终选股 ({len(report.selected_stocks)} 支):")
                pool_counts = {}
                for stock in report.selected_stocks:
                    pool_type = stock.pool_type
                    pool_counts[pool_type] = pool_counts.get(pool_type, 0) + 1
                    log(f"  - {stock.ts_code} ({stock.name}): 池={stock.pool_type}")
                    log(f"    选中理由: {stock.selection_reason}")
                
                log(f"\n选股池分布: {pool_counts}")
                
                return True
            else:
                log(f"[ERROR] 选股失败: {result.error}")
                return False
                
        except Exception as e:
            log(f"[ERROR] Agent执行异常: {e}")
            import traceback
            log(traceback.format_exc())
            return False
            
    except Exception as e:
        log(f"[ERROR] Agent创建失败: {e}")
        import traceback
        log(traceback.format_exc())
        return False

def main():
    """主函数"""
    log("=" * 80)
    log(" 增强版选股分析师完整调试工具")
    log(f" 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 80)
    
    tests = [
        ("选股分析师Agent", test_stock_selection_agent_detailed),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            log(f"\n[ERROR] {test_name}: 异常 - {e}")
            import traceback
            log(traceback.format_exc())
            results.append((test_name, False))
    
    # 总结
    log_section("5. 测试总结")
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    log(f"通过: {passed}/{total}")
    log(f"失败: {total - passed}/{total}")
    
    for test_name, success in results:
        status = "通过" if success else "失败"
        log(f"  {test_name}: {status}")
    
    # 保存日志
    log_section("6. 保存调试日志")
    filepath = save_log_to_file()
    
    log(f"\n调试完成！日志已保存到: {filepath}")

if __name__ == "__main__":
    main()