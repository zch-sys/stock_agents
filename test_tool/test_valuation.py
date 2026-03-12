"""
测试估值客观数据计算
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.judgments.valuation_judgments import (
    calc_graham_index,
    interpret_graham_index,
    calc_percentile_rank,
    calc_valuation_data
)

def test_graham_index():
    """测试格雷厄姆指数计算"""
    print("=" * 60)
    print("测试格雷厄姆指数计算")
    print("=" * 60)
    
    test_cases = [
        {"pe": 8, "desc": "低PE（低估）"},
        {"pe": 12, "desc": "中等PE"},
        {"pe": 14.5, "desc": "上证指数典型PE"},
        {"pe": 20, "desc": "较高PE"},
        {"pe": 30, "desc": "高PE（高估）"},
        {"pe": 50, "desc": "极高PE"},
        {"pe": None, "desc": "无效PE"},
        {"pe": -5, "desc": "负PE（亏损）"},
    ]
    
    for case in test_cases:
        pe = case["pe"]
        desc = case["desc"]
        
        graham_index = calc_graham_index(pe)
        interpretation = interpret_graham_index(graham_index)
        
        print(f"\n{desc}: PE={pe}")
        print(f"  格雷厄姆指数: {graham_index if graham_index else 'N/A'}")
        print(f"  解读: {interpretation}")

def test_valuation_data():
    """测试估值客观数据计算"""
    print("\n" + "=" * 60)
    print("测试估值客观数据计算")
    print("=" * 60)
    
    test_cases = [
        {"pe": 10, "pb": 1.0, "pe_pct": 10, "pb_pct": 15, "desc": "低估值"},
        {"pe": 14.5, "pb": 1.25, "pe_pct": 40, "pb_pct": 45, "desc": "合理估值"},
        {"pe": 25, "pb": 2.0, "pe_pct": 80, "pb_pct": 75, "desc": "高估值"},
    ]
    
    for case in test_cases:
        pe = case["pe"]
        pb = case["pb"]
        pe_pct = case["pe_pct"]
        pb_pct = case["pb_pct"]
        desc = case["desc"]
        
        result = calc_valuation_data(
            pe_ttm=pe,
            pb=pb,
            pe_percentile=pe_pct,
            pb_percentile=pb_pct
        )
        
        print(f"\n{desc}: PE={pe}, PB={pb}, PE百分位={pe_pct}%, PB百分位={pb_pct}%")
        print(f"  PE: {result.pe:.2f}")
        print(f"  PB: {result.pb:.2f}")
        print(f"  PE百分位: {result.pe_percentile:.1f}%")
        print(f"  PB百分位: {result.pb_percentile:.1f}%")
        print(f"  格雷厄姆指数: {result.graham_index if result.graham_index else 'N/A'}")
        print(f"  格雷厄姆解读: {result.graham_interpretation}")

def test_percentile_rank():
    """测试百分位计算"""
    print("\n" + "=" * 60)
    print("测试百分位计算")
    print("=" * 60)
    
    history = list(range(10, 31))  # 10-30 的历史PE数据
    print(f"历史数据范围: {min(history)} - {max(history)}")
    
    test_values = [10, 12, 15, 20, 25, 28, 30]
    for val in test_values:
        pct = calc_percentile_rank(val, history)
        print(f"  PE={val} -> 百分位={pct:.1f}%")

if __name__ == "__main__":
    test_graham_index()
    test_valuation_data()
    test_percentile_rank()
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)