"""测试 akshare 新闻数据接口和数据结构"""
import akshare as ak
import pandas as pd
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 200)
pd.set_option('display.max_colwidth', 100)

print("=" * 80)
print("测试 akshare 新闻相关接口")
print("=" * 80)

# ============ 1. 经济数据日历 ============
print("\n" + "=" * 80)
print("1. 经济数据日历 - ak.news_economic_baidu()")
print("=" * 80)
try:
    df = ak.news_economic_baidu()
    print(f"获取到 {len(df)} 条数据")
    print(f"\n列名: {list(df.columns)}")
    print(f"\n数据类型:\n{df.dtypes}")
    print(f"\n前10条数据:")
    print(df.head(10))
    
    # 查看地区分布
    if '地区' in df.columns:
        print(f"\n地区分布:")
        print(df['地区'].value_counts())
    
    # 查看重要性分布
    if '重要性' in df.columns:
        print(f"\n重要性分布:")
        print(df['重要性'].value_counts().sort_index())
        
except Exception as e:
    print(f"错误: {e}")

# ============ 2. 央视财经新闻 ============
print("\n" + "=" * 80)
print("2. 央视财经新闻 - ak.news_cctv()")
print("=" * 80)
try:
    df = ak.news_cctv()
    print(f"获取到 {len(df)} 条数据")
    print(f"\n列名: {list(df.columns)}")
    print(f"\n数据类型:\n{df.dtypes}")
    print(f"\n前5条数据:")
    print(df.head(5))
    if len(df) > 0:
        print(f"\n第一条完整内容:")
        for col in df.columns:
            print(f"  {col}: {df.iloc[0][col]}")
except Exception as e:
    print(f"错误: {e}")

# ============ 3. 上期所财经快讯 ============
print("\n" + "=" * 80)
print("3. 上期所财经快讯 - ak.futures_news_shmet()")
print("=" * 80)
try:
    df = ak.futures_news_shmet()
    print(f"获取到 {len(df)} 条数据")
    print(f"\n列名: {list(df.columns)}")
    print(f"\n数据类型:\n{df.dtypes}")
    print(f"\n前5条数据:")
    print(df.head(5))
    if len(df) > 0:
        print(f"\n第一条完整内容:")
        for col in df.columns:
            print(f"  {col}: {df.iloc[0][col]}")
except Exception as e:
    print(f"错误: {e}")

# ============ 4. 东方财富财经新闻 ============
print("\n" + "=" * 80)
print("4. 东方财富财经新闻 - ak.stock_news_em()")
print("=" * 80)
try:
    df = ak.stock_news_em(symbol="财经")
    print(f"获取到 {len(df)} 条数据")
    print(f"\n列名: {list(df.columns)}")
    print(f"\n数据类型:\n{df.dtypes}")
    print(f"\n前5条数据:")
    print(df.head(5))
except Exception as e:
    print(f"错误: {e}")

# ============ 5. 财经新闻滚动 ============
print("\n" + "=" * 80)
print("5. 财经新闻滚动 - ak.stock_news_roll()")
print("=" * 80)
try:
    df = ak.stock_news_roll()
    print(f"获取到 {len(df)} 条数据")
    print(f"\n列名: {list(df.columns)}")
    print(f"\n数据类型:\n{df.dtypes}")
    print(f"\n前5条数据:")
    print(df.head(5))
except Exception as e:
    print(f"错误: {e}")

# ============ 6. 金十数据财经快讯 ============
print("\n" + "=" * 80)
print("6. 金十数据财经快讯 - ak.fx_fxjs()")
print("=" * 80)
try:
    df = ak.fx_fxjs()
    print(f"获取到 {len(df)} 条数据")
    print(f"\n列名: {list(df.columns)}")
    print(f"\n数据类型:\n{df.dtypes}")
    print(f"\n前5条数据:")
    print(df.head(5))
except Exception as e:
    print(f"错误: {e}")

# ============ 7. 快讯接口 ============
print("\n" + "=" * 80)
print("7. 24K99财经快讯 - ak.fx24k_news()")
print("=" * 80)
try:
    df = ak.fx24k_news()
    print(f"获取到 {len(df)} 条数据")
    print(f"\n列名: {list(df.columns)}")
    print(f"\n数据类型:\n{df.dtypes}")
    print(f"\n前5条数据:")
    print(df.head(5))
except Exception as e:
    print(f"错误: {e}")

# ============ 8. 股市头条 ============
print("\n" + "=" * 80)
print("8. 股市头条 - ak.stock_toutiao()")
print("=" * 80)
try:
    df = ak.stock_toutiao()
    print(f"获取到 {len(df)} 条数据")
    print(f"\n列名: {list(df.columns)}")
    print(f"\n数据类型:\n{df.dtypes}")
    print(f"\n前5条数据:")
    print(df.head(5))
except Exception as e:
    print(f"错误: {e}")

print("\n" + "=" * 80)
print("测试完成")
print("=" * 80)