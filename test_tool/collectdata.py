import os
import sys
# 关键：添加项目根目录到Python路径，解决跨目录导入问题
# 项目根目录：F:\tradingagents
PROJECT_ROOT = "E:\\tradingagents"
sys.path.insert(0, PROJECT_ROOT)

# 从指定路径导入DataScheduler类
from data.scheduler import DataScheduler



PROJECT_ROOT = "E:\\tradingagents"
sys.path.insert(0, PROJECT_ROOT)

def test_data_scheduler():
    """测试DataScheduler的数据收集功能"""
    # ===================== 配置项（根据你的实际情况修改） =====================
    # 方式1：使用配置文件（推荐，需确保 PROJECT_ROOT/config/settings.yaml 存在）
    USE_CONFIG_FILE = True

    TEST_TRADE_DATE = None

    # ===================== 核心执行逻辑 =====================
    scheduler = None
    try:
        print("="*60)
        print("开始测试DataScheduler数据收集...")
        print(f"项目根目录：{PROJECT_ROOT}")
        print(f"指定交易日：{TEST_TRADE_DATE or '自动获取最新'}")
        print("="*60)

        # 初始化调度器
        if USE_CONFIG_FILE:
            # 从配置文件读取Token和数据库配置（推荐）
            scheduler = DataScheduler()
        # 执行数据收集（主入口）
        result = scheduler.run(trade_date=TEST_TRADE_DATE)

        # ===================== 打印执行结果 =====================
        print("\n" + "="*60)
        print("数据收集执行结果：")
        print("="*60)
        if result["success"]:
            print(f"✅ 执行成功")
            print(f"执行类型：{result['type']}（initial=首次全量，daily=日常更新）")
            
            if result["type"] == "initial":
                # 首次全量收集结果
                data = result["data"]
                print(f"📈 股票数据：成功{data['stock_success']}只 | 失败{data['stock_failed']}只")
                print(f"📊 大盘数据失败日期：{data['market_failed_dates'] or '无'}")
                print(f"🏷️  板块数据失败日期：{data['sector_failed_dates'] or '无'}")
            else:
                # 日常更新结果
                data = result["data"]
                daily = data["daily"]
                print(f"📈 股票日频数据：{'✅ 成功' if daily['stock'] else '❌ 失败'}")
                print(f"📊 大盘当日数据：{'✅ 成功' if daily['market'] else '❌ 失败'}")
                print(f"🏷️  板块当日数据：{'✅ 成功' if daily['sector'] else '❌ 失败'}")
        else:
            print(f"❌ 执行失败：{result['error']}")

    except FileNotFoundError as e:
        print(f"\n❌ 错误：配置文件未找到 - {e}")
        print("请检查 PROJECT_ROOT/config/settings.yaml 是否存在，路径：")
        print(f"   {os.path.join(PROJECT_ROOT, 'config', 'settings.yaml')}")
    except ValueError as e:
        print(f"\n❌ 错误：Token配置问题 - {e}")
        print("解决方案：")
        print("  1. 在settings.yaml中配置tushare_token")
        print("  2. 或直接在test脚本中设置TUSHARE_TOKEN变量")
    except ImportError as e:
        print(f"\n❌ 错误：模块导入失败 - {e}")
        print("解决方案：")
        print(f"  1. 确认 {PROJECT_ROOT}/data/scheduler.py 存在")
        print(f"  2. 确认 scheduler.py 依赖的模块（database、basic_data）已存在")
    except Exception as e:
        print(f"\n❌ 未知错误：{e}")
        # 可选：打印详细报错堆栈（方便调试）
        # import traceback
        # traceback.print_exc()
    finally:
        # 确保数据库会话关闭
        if scheduler:
            scheduler.close()
            print("\n✅ 数据库会话已关闭")
        print("\n测试脚本执行结束")

if __name__ == "__main__":
    test_data_scheduler()