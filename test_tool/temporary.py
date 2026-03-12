# import sys
# import os
# from datetime import datetime, date
# import tushare as ts

# # ========== 配置项（请修改这里的token） ==========
# TUSHARE_TOKEN = "41bc8be1587c976380a7776cb3d0e74a563aecfbfa1bef98670eb601"  # 替换成你的真实token
# START_DATE = "20251219"             # 起始日期（YYYYMMDD）
# END_DATE = "20260201"               # 结束日期（YYYYMMDD）
# # ===============================================

# # 添加项目根目录到Python路径（确保能导入自定义模块）
# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# # 导入你的自定义模块（保持和你项目一致的导入路径）
# from data.scheduler import DataScheduler  # 替换成你实际的DataScheduler所在模块路径

# def get_trade_dates_in_range(start_date: str, end_date: str, token: str) -> list:
#     """获取指定日期区间内的所有交易日"""
#     try:
#         pro = ts.pro_api(token)
#         # 调用tushare的交易日历接口
#         trade_cal = pro.trade_cal(
#             exchange='',
#             start_date=start_date,
#             end_date=end_date,
#             fields='cal_date,is_open'
#         )
#         # 筛选出交易日（is_open=1）并排序
#         trade_dates = trade_cal[trade_cal['is_open'] == 1]['cal_date'].tolist()
#         # 按日期升序排列（从早到晚）
#         trade_dates.sort()
#         print(f"✅ 成功获取区间内交易日：共 {len(trade_dates)} 天")
#         print(f"   日期范围：{trade_dates[0]} ~ {trade_dates[-1]}")
#         return trade_dates
#     except Exception as e:
#         print(f"❌ 获取交易日失败：{e}")
#         sys.exit(1)

# def batch_retry_sector_data(trade_dates: list):
#     """批量重试指定交易日的板块数据"""
#     # 初始化统计结果
#     result = {
#         "total": len(trade_dates),
#         "success": 0,
#         "failed": 0,
#         "failed_dates": []
#     }

#     try:
#         # 初始化调度器
#         scheduler = DataScheduler(tushare_token=TUSHARE_TOKEN)
#         print("\n🚀 开始批量重试板块数据...")
        
#         # 遍历所有交易日，逐个重试
#         for i, trade_date in enumerate(trade_dates, 1):
#             print(f"\n[{i}/{result['total']}] 处理日期：{trade_date}")
#             try:
#                 # 调用单独重试板块数据的方法
#                 retry_result = scheduler.collect_sector_data_single_date(trade_date)
#                 if retry_result['success']:
#                     result["success"] += 1
#                     print(f"   ✅ {trade_date} 板块数据重试成功")
#                 else:
#                     result["failed"] += 1
#                     result["failed_dates"].append(trade_date)
#                     print(f"   ❌ {trade_date} 板块数据重试失败")
#             except Exception as e:
#                 result["failed"] += 1
#                 result["failed_dates"].append(trade_date)
#                 print(f"   ❌ {trade_date} 板块数据重试异常：{str(e)[:100]}")
        
#         # 输出最终统计结果
#         print("\n" + "="*50)
#         print("📊 批量重试板块数据统计结果：")
#         print(f"   总交易日数：{result['total']}")
#         print(f"   成功数：{result['success']}")
#         print(f"   失败数：{result['failed']}")
#         if result['failed_dates']:
#             print(f"   失败日期：{','.join(result['failed_dates'])}")
#         print("="*50)

#     except Exception as e:
#         print(f"\n❌ 批量重试流程异常：{e}")
#     finally:
#         # 确保关闭数据库会话
#         if 'scheduler' in locals():
#             scheduler.close()

# if __name__ == "__main__":
#     # 1. 获取区间内的所有交易日
#     trade_dates = get_trade_dates_in_range(START_DATE, END_DATE, TUSHARE_TOKEN)
    
#     if not trade_dates:
#         print("❌ 未获取到任何交易日，退出脚本")
#         sys.exit(1)
    
#     # 2. 批量重试板块数据
#     batch_retry_sector_data(trade_dates)
    
#     print("\n🎉 脚本执行完成！")



# import os
# import sys
# import time
# import logging
# from datetime import datetime, timedelta
# from typing import List, Dict

# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# # ------------ 导入项目模块 ------------
# from data.scheduler import DataScheduler
# from data.database import StockDetail


# # ------------ 日志配置 ------------
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.FileHandler(f"fast_repair_low_freq_{datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8'),
#         logging.StreamHandler(sys.stdout)
#     ]
# )
# logger = logging.getLogger(__name__)

# # ------------ 常量配置（可根据需求调整）------------
# HISTORY_DAYS = 365
# BATCH_SIZE = 30  # 每批处理股票数，可适当调大
# STOCK_REQUEST_DELAY = 0.2  # 股票间接口限流（秒）
# BATCH_COMMIT = True  # 批量提交事务

# def fast_rewrite_low_freq():
#     # 1. 初始化调度器
#     try:
#         scheduler = DataScheduler()
#         stock_collector = scheduler.stock_collector
#         session = scheduler.session
#         logger.info("DataScheduler 初始化完成，启动高性能覆写模式")
#     except Exception as e:
#         logger.error(f"调度器初始化失败：{str(e)}", exc_info=True)
#         return

#     # 2. 获取全量股票列表
#     try:
#         all_stocks = stock_collector.get_stock_list()
#         total_stocks = len(all_stocks)
#         logger.info(f"获取全量股票：{total_stocks} 只，开始高性能批量覆写")
#     except Exception as e:
#         logger.error(f"获取股票列表失败：{str(e)}", exc_info=True)
#         scheduler.close()
#         return

#     # 3. 统计指标
#     stats = {
#         "total_stocks": total_stocks,
#         "success_stocks": 0,
#         "failed_stocks": 0,
#         "failed_codes": [],
#         "total_records": 0,
#         "rewrite_records": 0,
#         "api_request_count": 0  # 统计接口调用次数，对比优化前
#     }

#     # 4. 分批处理股票
#     for batch_idx, i in enumerate(range(0, total_stocks, BATCH_SIZE), start=1):
#         batch_stocks = all_stocks[i:i + BATCH_SIZE]
#         logger.info(f"\n===== 处理第 {batch_idx} 批股票 | 共计 {len(batch_stocks)} 只 =====")

#         for ts_code in batch_stocks:
#             try:
#                 # 时间范围筛选
#                 end_dt = datetime.now()
#                 start_dt = end_dt - timedelta(days=HISTORY_DAYS)
#                 # 查询该股票过去一年所有记录
#                 records = session.query(StockDetail).filter(
#                     StockDetail.ts_code == ts_code,
#                     StockDetail.trade_date >= start_dt.date(),
#                     StockDetail.trade_date <= end_dt.date()
#                 ).all()

#                 if not records:
#                     logger.info(f"股票 {ts_code} 无历史数据，跳过")
#                     stats["success_stocks"] += 1
#                     time.sleep(STOCK_REQUEST_DELAY)
#                     continue

#                 stats["total_records"] += len(records)
#                 logger.info(f"股票 {ts_code} 待处理记录数：{len(records)}")

#                 # ============== 核心优化：按财报季度分组 + 缓存数据 ==============
#                 # 1. 分组：将所有记录按【财报截止日】分组
#                 record_group: Dict[str, List[StockDetail]] = {}
#                 for record in records:
#                     trade_date_str = record.trade_date.strftime("%Y%m%d")
#                     # 获取当前交易日对应的财报季度
#                     report_date = stock_collector._get_report_period(trade_date_str)
#                     if report_date not in record_group:
#                         record_group[report_date] = []
#                     record_group[report_date].append(record)

#                 # 2. 预拉取所有季度的财报数据（缓存，每个季度仅调用1次接口）
#                 report_cache: Dict[str, Dict] = {}
#                 for report_date in record_group.keys():
#                     # 调用接口获取财报数据
#                     low_freq_data = stock_collector._get_low_freq_data(ts_code, report_date)
#                     stats["api_request_count"] += 1
#                     report_cache[report_date] = low_freq_data

#                 # 3. 批量覆写：从缓存取数据，无额外接口请求
#                 rewrite_count = 0
#                 for report_date, record_list in record_group.items():
#                     cache_data = report_cache[report_date]
#                     if not cache_data:
#                         logger.warning(f"{ts_code} | 季度{report_date} 无财报数据，跳过")
#                         continue

#                     # 遍历该季度所有记录，统一赋值
#                     for record in record_list:
#                         # 基础信息
#                         record.name = cache_data.get('name', record.name)
#                         record.industry = cache_data.get('industry', record.industry)
#                         record.area = cache_data.get('area', record.area)
#                         record.market = cache_data.get('market', record.market)

#                         # 上市日期格式处理
#                         if cache_data.get('list_date'):
#                             try:
#                                 record.list_date = datetime.strptime(cache_data['list_date'], '%Y%m%d').date()
#                             except (ValueError, TypeError):
#                                 pass

#                         # 财务/股本指标全覆盖写
#                         record.total_share = cache_data.get('total_share', 0.0)
#                         record.float_share = cache_data.get('float_share', 0.0)
#                         record.eps = cache_data.get('eps', 0.0)
#                         record.bvps = cache_data.get('bvps', 0.0)
#                         record.total_assets = cache_data.get('total_assets', 0.0)
#                         record.total_liab = cache_data.get('total_liab', 0.0)
#                         record.net_profit = cache_data.get('net_profit', 0.0)
#                         record.revenue = cache_data.get('revenue', 0.0)
#                         record.debt_to_assets = cache_data.get('debt_to_assets', 0.0)
#                         record.current_ratio = cache_data.get('current_ratio', 0.0)
#                         record.quick_ratio = cache_data.get('quick_ratio', 0.0)
#                         record.cash_ratio = cache_data.get('cash_ratio', 0.0)
#                         record.revenue_yoy = cache_data.get('revenue_yoy', 0.0)
#                         record.profit_yoy = cache_data.get('profit_yoy', 0.0)

#                         # 更新财报标记日期
#                         try:
#                             record.low_freq_update_date = datetime.strptime(report_date, '%Y%m%d').date()
#                         except (ValueError, TypeError):
#                             pass

#                         rewrite_count += 1

#                 stats["rewrite_records"] += rewrite_count
#                 # 单只股票完成后提交事务
#                 if BATCH_COMMIT:
#                     session.commit()
#                 stats["success_stocks"] += 1
#                 logger.info(f"股票 {ts_code} 处理完成 | 覆写{rewrite_count}条 | 接口调用{len(record_group)}次")

#             except Exception as e:
#                 logger.error(f"股票 {ts_code} 处理失败：{str(e)}", exc_info=False)
#                 session.rollback()
#                 stats["failed_stocks"] += 1
#                 stats["failed_codes"].append(ts_code)

#             # 股票间限流，遵守Tushare接口规则
#             time.sleep(STOCK_REQUEST_DELAY)

#         # 批次兜底提交
#         session.commit()

#     # 5. 最终统计输出
#     logger.info("\n" + "=" * 60)
#     logger.info("高性能覆写任务全部完成")
#     logger.info(f"总股票数：{stats['total_stocks']}")
#     logger.info(f"成功处理：{stats['success_stocks']}")
#     logger.info(f"处理失败：{stats['failed_stocks']}")
#     logger.info(f"总扫描记录：{stats['total_records']}")
#     logger.info(f"成功覆写记录：{stats['rewrite_records']}")
#     logger.info(f"总接口请求次数：{stats['api_request_count']}")
#     logger.info(f"失败股票列表：{stats['failed_codes']}")
#     logger.info("=" * 60)

#     scheduler.close()

# if __name__ == "__main__":
#     logger.info("启动【高性能版】低频数据全量覆写脚本")
#     fast_rewrite_low_freq()




# import os
# import sys
# import yaml
# import tushare as ts
# from datetime import datetime
# from typing import Optional, Dict

# project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# sys.path.append(project_root)

# def load_tushare_token() -> Optional[str]:
#     """从项目配置读取Token"""
#     config_path = os.path.join(project_root, "config", "settings.yaml")
#     try:
#         with open(config_path, 'r', encoding='utf-8') as f:
#             config = yaml.safe_load(f)
#         return config['data_collector'].get('tushare_token')
#     except Exception as e:
#         print(f"读取配置失败: {e}")
#         return None

# def test_finance_api(ts_code: str, report_date: str):
#     token = load_tushare_token()
#     if not token:
#         print("Token获取失败")
#         return

#     ts.set_token(token)
#     pro = ts.pro_api()
#     print(f"===== 测试股票：{ts_code} | 报告期：{report_date} =====")

#     # --------------------------
#     # 修复点1：使用 period 指定报告期，comp_type=2 标记银行股
#     # --------------------------
#     common_params = {
#         "ts_code": ts_code,
#         "period": report_date,   # 核心修复：报告期专用参数
#         "comp_type": 2           # 核心修复：银行股固定传2
#     }

#     # 1. 利润表接口 income
#     print("\n=== 1. 利润表接口 income ===")
#     try:
#         income_df = pro.income(**common_params)
#         if income_df.empty:
#             print("数据为空")
#         else:
#             row = income_df.iloc[0].to_dict()
#             print(f"营业收入(revenue): {row.get('revenue')}")
#             print(f"净利润(n_income): {row.get('n_income')}")  # Tushare标准字段
#             print(f"报告期(end_date): {row.get('end_date')}")
#     except Exception as e:
#         print(f"调用失败: {str(e)}")

#     # 2. 资产负债表接口 balancesheet
#     print("\n=== 2. 资产负债表接口 balancesheet ===")
#     try:
#         bs_df = pro.balancesheet(**common_params)
#         if bs_df.empty:
#             print("数据为空")
#         else:
#             row = bs_df.iloc[0].to_dict()
#             print(f"总资产(total_assets): {row.get('total_assets')}")
#             print(f"总负债(total_liab): {row.get('total_liab')}")
#     except Exception as e:
#         print(f"调用失败: {str(e)}")

#     # 3. 财务指标接口 fina_indicator
#     print("\n=== 3. 财务指标接口 fina_indicator ===")
#     try:
#         # fina_indicator 无comp_type参数，单独传参
#         fina_df = pro.fina_indicator(ts_code=ts_code, period=report_date)
#         if fina_df.empty:
#             print("数据为空")
#         else:
#             row = fina_df.iloc[0].to_dict()
#             print(f"每股收益(eps): {row.get('eps')}")
#     except Exception as e:
#         print(f"调用失败: {str(e)}")

#     print("\n===== 测试完成 =====\n")

# if __name__ == "__main__":
#     # 测试两个报告期
#     test_cases = [("000001.SZ", "20250930"), ("000001.SZ", "20251231")]
#     for code, date in test_cases:
#         test_finance_api(code, date)


import tushare as ts
import pandas as pd
from datetime import datetime

# 1. 初始化Tushare Pro接口（使用你提供的token）
ts.set_token('41bc8be1587c976380a7776cb3d0e74a563aecfbfa1bef98670eb601')
pro = ts.pro_api()

def test_margin_data():
    """
    测试获取融资融券交易汇总数据
    逻辑：查询最近1个交易日的全市场两融数据，验证权限和接口可用性
    """
    print("="*50)
    print(f"当前测试时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("开始测试两融数据接口(margin)权限与数据获取...")
    print("="*50)

    try:
        # 2. 调用接口：获取最近交易日 上交所+深交所 两融汇总数据
        # 不指定日期默认获取最新数据，exchange_id为空代表查询全交易所
        df = pro.margin(
            start_date='20260204',  # 开始日期，留空默认最新
            end_date='20260204',    # 结束日期，留空默认最新
            exchange_id='', # 留空：SSE上交所+SZSE深交所+BSE北交所全量数据
            fields='trade_date,exchange_id,rzye,rzmre,rqye,rqmcl,rzrqye,rqyl'  # 指定需要的字段
        )

        # 3. 校验返回结果
        if df.empty:
            print("❌ 接口调用成功，但未查询到数据！")
            print("可能原因：")
            print("1. 当日为非交易日，无两融数据")
            print("2. 当日数据尚未更新（建议交易日20:00后/次日9:00后重试）")
            print("3. 日期参数筛选范围无数据")
        else:
            print("✅ 数据获取成功！")
            print(f"获取到数据条数：{len(df)}")
            print("-"*30)
            # 格式化数据展示
            df['rzye'] = df['rzye'].map(lambda x: f"{x:,.2f}")  # 融资余额格式化
            df['rzmre'] = df['rzmre'].map(lambda x: f"{x:,.2f}") # 融资买入额格式化
            df['rzrqye'] = df['rzrqye'].map(lambda x: f"{x:,.2f}") # 两融余额格式化
            print(df.to_string(index=False))  # 打印完整数据

    except Exception as e:
        # 捕获接口调用异常，针对性提示
        error_msg = str(e)
        print("❌ 接口调用失败，错误信息：", error_msg)
        print("\n常见错误解决方案：")
        if "权限" in error_msg or "401" in error_msg:
            print("1. 权限不足：你的2000积分满足该接口权限，检查token是否输入错误")
        elif "404" in error_msg:
            print("2. 接口名称错误：确认接口名为 margin（非margin_mkt）")
        elif "网络" in error_msg or "连接" in error_msg:
            print("3. 网络异常：检查网络连接，或稍后重试")
        else:
            print("4. 其他异常：可查阅Tushare官方文档或社区反馈")

    print("="*50)
    print("测试完成")

# 执行测试函数
if __name__ == '__main__':
    # 安装依赖（首次运行取消注释执行一次即可）
    # import os
    # os.system("pip install tushare -U")
    test_margin_data()