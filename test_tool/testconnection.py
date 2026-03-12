# test_news_data_location.py
"""
验证大盘分析师新闻数据在短期记忆中的存储位置和内容。
"""

import sys
import os
from datetime import datetime
import json

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.memory.memory_manager import get_memory_manager
from data.schemas.market_schema import NewsAnalysis


def inspect_market_report():
    """获取最新大盘分析师报告，检查其结构和新闻分析字段"""
    
    # 初始化记忆管理器
    memory_manager = get_memory_manager()
    
    # 获取最近一份 MarketAnalyst 报告（agent_id 为 "MARKET"）
    # 如果大盘分析师有多个实例，可能需要根据实际 agent_id 调整
    reports = memory_manager.get_recent_reports(
        agent_id="MARKET",
        n=1,
        reference_date=datetime.now().date()  # 获取今天之前的最新报告
    )
    
    if not reports:
        print("❌ 未找到 MarketAnalyst 报告")
        return
    
    report = reports[0]
    print("\n" + "="*60)
    print("【MarketAnalyst 短期记忆报告】")
    print("="*60)
    
    # 打印报告的基本字段
    trade_date = report.get('trade_date')
    task_id = report.get('task_id')
    content = report.get('content', {})
    
    print(f"报告日期: {trade_date}")
    print(f"任务ID: {task_id}")
    print(f"content 顶层 keys: {list(content.keys())}")
    
    # 检查 content 中是否有 'data' 字段
    if 'data' in content:
        print("\n✅ 找到 content['data'] 字段，MarketReport 数据位于此处")
        data = content['data']
        print(f"data 中的 keys: {list(data.keys())}")
        
        # 提取新闻分析字段
        news_analysis = data.get('news_analysis')
        if news_analysis is not None:
            print("\n【news_analysis 字段存在】")
            # 尝试将 NewsAnalysis 对象转为字典
            if hasattr(news_analysis, 'to_dict'):
                news_dict = news_analysis.to_dict()
            elif isinstance(news_analysis, dict):
                news_dict = news_analysis
            else:
                news_dict = str(news_analysis)
            
            print("内容预览:")
            print(json.dumps(news_dict, ensure_ascii=False, indent=2))
        else:
            print("\n❌ data 中未找到 news_analysis 字段")
            
        # 打印 data 中所有字段名，便于确认
        print("\ndata 中所有字段：")
        for key in data.keys():
            print(f"  - {key}")
    else:
        # 如果没有 data 字段，则新闻分析可能直接在 content 根层级（旧格式）
        print("\n⚠️ content 中没有 'data' 字段，尝试从 content 根层级获取 news_analysis")
        news_analysis = content.get('news_analysis')
        if news_analysis is not None:
            print("\n✅ 在 content 根层级找到 news_analysis")
            # 打印内容
            if hasattr(news_analysis, 'to_dict'):
                news_dict = news_analysis.to_dict()
            elif isinstance(news_analysis, dict):
                news_dict = news_analysis
            else:
                news_dict = str(news_analysis)
            print(json.dumps(news_dict, ensure_ascii=False, indent=2))
        else:
            print("\n❌ content 根层级也未找到 news_analysis")


if __name__ == "__main__":
    inspect_market_report()