import sys
import os
import logging
import time
from datetime import datetime, timedelta
import shutil

from sqlalchemy import func
# 添加项目根目录到sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 配置日志（修复✅符号的编码问题）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        # 指定UTF-8编码，避免✅符号的编码错误
        logging.FileHandler(os.path.join(current_dir, 'news_crawler_test.log'), encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# 导入ORM相关模块
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from data.basic_data.newsdata import StockNews  # 导入你的StockNews模型
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

def create_temp_database():
    """创建临时SQLite数据库并初始化表结构"""
    temp_db_file = os.path.join(current_dir, 'test_news_enhanced.db')
    
    # 删除已存在的数据库文件
    if os.path.exists(temp_db_file):
        try:
            os.remove(temp_db_file)
            logger.info(f"删除旧数据库文件: {temp_db_file}")
        except Exception as e:
            logger.warning(f"删除旧数据库失败: {e}")
    
    # 创建SQLite引擎（临时数据库）
    temp_db_url = f"sqlite:///{temp_db_file}"
    engine = create_engine(temp_db_url, echo=False)
    
    # 使用StockNews模型创建表结构（关键：确保包含content_type字段）
    StockNews.metadata.create_all(engine)
    logger.info(f"✅ 临时数据库表创建成功，包含content_type字段")
    
    # 创建会话工厂
    Session = sessionmaker(bind=engine)
    
    return temp_db_file, engine, Session

def run_enhanced_test():
    """运行增强版新闻爬虫测试（使用临时ORM表）"""
    # 测试股票代码列表
    test_stocks = ["002468"]  

    print("\n" + "="*70)
    print("🚀 增强版东方财富股吧新闻爬虫测试工具")
    print("="*70)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"测试股票: {', '.join(test_stocks)}")
    print("="*70)
    
    # 创建临时数据库（含表结构）
    temp_db_file, engine, Session = create_temp_database()
    
    try:
        # 动态导入爬虫类
        try:
            from data.basic_data.newsdata import StockNewsCrawler
            logger.info("✅ 成功导入StockNewsCrawler")
        except ImportError as e:
            logger.error(f"导入失败: {e}")
            return False
        
        # 修改爬虫配置：使用临时数据库
        # 创建自定义配置，指向临时SQLite数据库
        temp_config = {
            "data_collector": {
                "db_url": f"sqlite:///{temp_db_file}"
            },
            "crawler": {
                "time_range_days": 7,
                "page_load_timeout": 15,
                "wait_time": 10,
                "headless": False  # 测试时关闭无头模式，方便调试
            }
        }
        
        # 创建爬虫实例（使用临时数据库配置）
        crawler = StockNewsCrawler(config_path=None)
        # 替换爬虫的数据库配置为临时库
        crawler.db_url = f"sqlite:///{temp_db_file}"
        crawler.engine = engine
        crawler.SessionLocal = Session
        logger.info("✅ 新闻爬虫初始化成功（使用临时数据库）")
        
        total_news_count = 0
        
        # 测试多个股票
        for stock_code in test_stocks:
            print(f"\n📊 开始测试股票: {stock_code}")
            print("-" * 50)
            
            start_time = time.time()
            
            try:
                # 爬取新闻（会自动保存到临时数据库）
                news_list = crawler.crawl_stock_news(stock_code)
                elapsed_time = time.time() - start_time
                
                if news_list:
                    print(f"✅ 股票 {stock_code}: 爬取 {len(news_list)} 条新闻，耗时 {elapsed_time:.1f} 秒")
                    total_news_count += len(news_list)
                    
                    # 显示最新的几条新闻
                    for i, news in enumerate(news_list[:3]):  # 只显示前3条
                        print(f"   {i+1}. {news['title'][:60]}...")
                else:
                    print(f"⚠️  股票 {stock_code}: 未找到符合时间范围的新闻")
                    
                # 随机延迟，避免请求过于频繁
                if stock_code != test_stocks[-1]:
                    time.sleep(3)
                    
            except Exception as e:
                logger.error(f"股票 {stock_code} 测试失败: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # 统计结果（使用ORM查询临时表）
        print("\n" + "="*70)
        print("📈 测试结果汇总")
        print("="*70)
        
        # 使用ORM会话查询数据
        session = Session()
        try:
            # 检查表是否存在（通过ORM）
            table_exists = engine.dialect.has_table(engine.connect(), 'stock_news')
            if table_exists:
                # 按股票统计
                stock_stats = session.query(
                    StockNews.stock_code, 
                    func.count(StockNews.id)
                ).group_by(StockNews.stock_code).all()
                
                if stock_stats:
                    print("📊 各股票新闻数量:")
                    for stock_code, count in stock_stats:
                        print(f"   {stock_code}: {count} 条")
                    
                    # 按时间统计7天内数据
                    time_threshold = datetime.now() - timedelta(days=7)
                    recent_count = session.query(StockNews).filter(
                        StockNews.publish_time >= time_threshold
                    ).count()
                    
                    print(f"\n📅 7天内新闻总数: {recent_count}")
                    
                    # 显示最新新闻
                    print(f"\n📰 最新新闻示例:")
                    latest_news = session.query(
                        StockNews.stock_code, 
                        StockNews.publish_time, 
                        StockNews.title
                    ).order_by(StockNews.publish_time.desc()).limit(3).all()
                    
                    for i, (code, pub_time, title) in enumerate(latest_news, 1):
                        print(f"   {i}. [{code}] {pub_time.strftime('%Y-%m-%d %H:%M')}: {title[:70]}...")
                        
                else:
                    print("❌ 数据库中无新闻数据")
            else:
                print("❌ 数据库表不存在")
                
        except Exception as e:
            logger.error(f"数据库查询失败: {e}")
            import traceback
            traceback.print_exc()
        finally:
            session.close()
        
        print("="*70)
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # 清理临时文件
        try:
            if os.path.exists(temp_db_file):
                # 先关闭所有可能的连接
                engine.dispose()
                time.sleep(1)
                os.remove(temp_db_file)
                logger.info("✅ 已清理临时数据库文件")
        except Exception as e:
            logger.error(f"清理临时文件失败: {e}")



if __name__ == "__main__":
    print("🚀 增强版新闻爬虫测试开始...")
    print("注意：此测试会爬取多个股票，模拟人类行为，可能需要几分钟时间")
    print("日志将保存到: news_crawler_test.log")
    
    success = run_enhanced_test()
    
    if success:
        print("\n✅ 增强版测试完成！")
    else:
        print("\n❌ 测试失败，请查看日志文件")