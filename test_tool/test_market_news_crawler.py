# -*- coding: utf-8 -*-
"""测试大盘新闻爬虫"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.basic_data.market_news_collector import MarketNewsCollector
from data.basic_data.config_manager import setup_logging, load_config
from data.basic_data.database import init_db

logger = setup_logging(__name__)


def test_market_news_crawler():
    """测试大盘新闻爬虫"""
    print("=" * 60)
    print("测试大盘新闻爬虫 - 东方财富财经新闻")
    print("=" * 60)
    
    try:
        # 初始化数据库
        print("\n0. 初始化数据库...")
        config = load_config()
        db_url = config.get('data_collector', {}).get('db_url')
        if db_url:
            init_db(db_url)
            print("   [OK] 数据库初始化成功")
        else:
            print("   [!] 未找到数据库配置，跳过数据库初始化")
        
        # 初始化爬虫
        print("\n1. 初始化爬虫...")
        collector = MarketNewsCollector()
        print("   [OK] 爬虫初始化成功")
        
        # 测试爬取（只爬1页，快速验证）
        print("\n2. 开始爬取（测试模式，只爬1页）...")
        news_list, saved_count = collector.crawl_market_news(max_pages=1)
        
        print(f"\n3. 爬取结果:")
        print(f"   - 获取新闻数: {len(news_list)}")
        print(f"   - 保存成功数: {saved_count}")
        
        # 显示前3条新闻
        if news_list:
            print(f"\n4. 前3条新闻预览:")
            for i, news in enumerate(news_list[:3], 1):
                title_preview = news['title'][:60] if len(news['title']) > 60 else news['title']
                print(f"\n   [{i}] {title_preview}")
                print(f"       时间: {news['publish_time'].strftime('%Y-%m-%d %H:%M')}")
                content = news.get('content', '') or ''
                content_preview = content[:100] if len(content) > 100 else content
                print(f"       内容: {content_preview}...")
        
        # 测试查询功能
        print("\n5. 测试查询功能（获取最近24小时新闻）...")
        recent_news = collector.get_recent_news(hours=24, limit=10)
        print(f"   - 最近24小时新闻数: {len(recent_news)}")
        
        print("\n" + "=" * 60)
        print("测试完成！")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"\n[FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_market_news_crawler()
    sys.exit(0 if success else 1)
