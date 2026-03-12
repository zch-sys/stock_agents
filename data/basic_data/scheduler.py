import os
import sys
import time
from datetime import datetime, timedelta, date
from sqlalchemy import func, and_
from typing import Dict, List, Optional, Union

# 添加项目根目录到路径（保持原有逻辑，确保自定义模块可导入）
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tushare as ts
# 导入自定义模块
from .database import init_db, get_session, StockDetail
from .indexdata import MarketCollector
from .stock import StockCollector
from .market_news_collector import MarketNewsCollector
from .config_manager import load_config, setup_logging

# 全局日志对象
logger = setup_logging(__name__)

class DataScheduler:
    """数据收集调度器（模块化版本，支持精细化单独操作）"""
    
    def __init__(self, tushare_token: str = None, config_path: str = None):
        """
        初始化调度器（适配工作流调用，配置默认内置，仅需传token或自定义配置时传参）
        
        :param tushare_token: Tushare token（可选，若不传则从配置文件读取）
        :param config_path: 配置文件路径（已废弃，统一使用config/settings.yaml）
        """
        # 1. 加载配置文件（完全内置默认路径，用户无需传参）
        self.config = load_config()
        
        # 2. 处理Tushare token（优先传入值，其次配置文件）
        self.tushare_token = tushare_token or self.config['data_collector'].get('tushare_token')
        if not self.tushare_token:
            raise ValueError("Tushare token未配置，请通过参数或配置文件提供")
        
        # 3. 初始化数据库
        self.db_url = self.config['data_collector']['db_url']
        init_db(self.db_url)
        self.session = get_session()
        
        # 4. 初始化收集器
        self.stock_collector = StockCollector(self.tushare_token)
        
        self.market_collector = MarketCollector(self.tushare_token)
        
        self.market_news_collector = MarketNewsCollector()
        
        # 5. 初始化日志（确保日志只初始化一次）
        # 已通过模块级调用完成初始化
        
        # 初始化Tushare
        ts.set_token(self.tushare_token)
        
        logger.info("数据调度器初始化完成（模块化版本，支持精细化操作）")
    
    
    def is_first_run(self) -> bool:
        """
        判断是否需要执行首次全量收集
        返回 True 的条件：
        - 数据库中没有 StockDetail 记录
        - 有记录但最新交易日期距今超过 MAX_DAYS_GAP 天（默认11天）
        """
        try:
            # 检查是否有数据
            count = self.session.query(func.count(StockDetail.id)).scalar()
            if count == 0:
                logger.info("数据库为空，判定为首次运行")
                return True

            # 获取最新交易日期
            latest_date = self.session.query(func.max(StockDetail.trade_date)).scalar()
            if latest_date is None:
                logger.warning("无法获取最新交易日期，判定为首次运行")
                return True

            # 统一转换为 date 对象
            if isinstance(latest_date, str):
                latest_date = datetime.strptime(latest_date, '%Y%m%d').date()
            elif isinstance(latest_date, datetime):
                latest_date = latest_date.date()

            today = datetime.now().date()
            days_gap = (today - latest_date).days

            # 阈值（可从配置读取，这里简单硬编码）
            MAX_DAYS_GAP = 11
            if days_gap > MAX_DAYS_GAP:
                logger.info(f"最新数据日期 {latest_date} 距今 {days_gap} 天 > {MAX_DAYS_GAP}，判定为首次运行（需全量重建）")
                return True

            logger.info(f"数据库状态正常，最新数据日期 {latest_date}，距今天数 {days_gap}，执行日常更新")
            return False

        except Exception as e:
            logger.error(f"检查数据库状态失败: {e}", exc_info=True)
            return True  # 异常时保守返回 True，触发全量收集
    
    def _get_recent_trade_dates(self, days: int, start_date: str = None) -> List[str]:
        """获取最近N个自然日（可以指定起始日期）
        :param days: 要获取的天数
        :param start_date: 起始日期（格式YYYYMMDD），如果不指定则从当前日期开始
        :return: 自然日列表，按从新到旧排序
        """
        # 如果有起始日期，从起始日期开始计算
        if start_date:
            try:
                # 解析起始日期
                start_dt = datetime.strptime(start_date, '%Y%m%d')
                # 生成从起始日期往前推days-1天的日期（包括起始日期）
                natural_dates = [
                    (start_dt - timedelta(days=i)).strftime('%Y%m%d') 
                    for i in range(days)
                ]
                return natural_dates
            except ValueError as e:
                logger.error(f"起始日期格式错误：{start_date}，错误：{e}")
                # 如果日期格式错误，回退到默认逻辑
                pass
        
        # 默认逻辑：从当前日期开始
        current_date = datetime.now()
        natural_dates = [
            (current_date - timedelta(days=i)).strftime('%Y%m%d') 
            for i in range(days)
        ]
        return natural_dates
    # ====================== 新增：精细化单独操作方法 ======================
    def collect_single_stock_high_freq(self, ts_code: str, trade_date: str = None) -> Dict:
        """
        单独收集单只股票的高频数据（精准重试）
        :param ts_code: 股票代码（如 000001.SZ）
        :param trade_date: 交易日（格式YYYYMMDD），默认取最新交易日
        :return: 执行结果 {'success': bool, 'ts_code': str, 'trade_date': str}
        """
        logger.info(f"开始单独收集股票 {ts_code} 高频数据")
        result = {
            'success': False,
            'ts_code': ts_code,
            'trade_date': trade_date or self.market_collector.get_trade_date()
        }
        
        try:
            success = self.stock_collector.collect_single_stock_high_freq(ts_code, result['trade_date'])
            result['success'] = success
            
            if success:
                logger.info(f"股票 {ts_code} 高频数据收集成功（日期：{result['trade_date']}）")
            else:
                logger.warning(f"股票 {ts_code} 高频数据收集失败（日期：{result['trade_date']}）")
            
            return result
        except Exception as e:
            logger.error(f"单独收集股票 {ts_code} 高频数据异常: {e}", exc_info=True)
            result['error'] = str(e)
            return result
    
    def collect_batch_stocks_high_freq(self, ts_codes: List[str] = None, trade_date: str = None) -> Dict:
        """
        单独批量收集指定股票列表的高频数据（可指定股票范围）
        :param ts_codes: 股票列表，None则收集所有股票
        :param trade_date: 交易日（格式YYYYMMDD），默认取最新交易日
        :return: 执行结果 {'total': int, 'success': int, 'failed': int, 'failed_codes': List[str]}
        """
        logger.info(f"开始批量收集股票高频数据（指定列表，共{len(ts_codes) if ts_codes else '所有'}只）")
        return self.stock_collector.batch_collect_all_stocks_high_freq(ts_codes, trade_date)
    
    def collect_single_stock_low_freq(self, ts_code: str, trade_date: str = None) -> Dict:
        """
        单独更新单只股票的低频数据（精准重试）
        :param ts_code: 股票代码（如 000001.SZ）
        :param trade_date: 更新基准日期（格式YYYYMMDD），默认取最新交易日
        :return: 执行结果 {'success': bool, 'ts_code': str}
        """
        logger.info(f"开始单独更新股票 {ts_code} 低频数据")
        result = {
            'success': False,
            'ts_code': ts_code
        }
        
        try:
            success = self.stock_collector.collect_single_stock_low_freq(ts_code, trade_date)
            result['success'] = success
            
            if success:
                logger.info(f"股票 {ts_code} 低频数据更新成功")
            else:
                logger.warning(f"股票 {ts_code} 低频数据更新失败")
            
            return result
        except Exception as e:
            logger.error(f"单独更新股票 {ts_code} 低频数据异常: {e}", exc_info=True)
            result['error'] = str(e)
            return result
    
    def collect_batch_stocks_low_freq(self, ts_codes: List[str] = None, trade_date: str = None) -> Dict:
        """
        单独批量更新指定股票列表的低频数据（可指定股票范围）
        :param ts_codes: 股票列表，None则更新所有股票
        :param trade_date: 更新基准日期（格式YYYYMMDD），默认取最新交易日
        :return: 执行结果 {'total': int, 'success': int, 'failed': int, 'failed_codes': List[str]}
        """
        logger.info(f"开始批量更新股票低频数据（指定列表，共{len(ts_codes) if ts_codes else '所有'}只）")
        return self.stock_collector.batch_collect_all_stocks_low_freq(ts_codes, trade_date)
    
    def collect_market_indices_single_date(self, trade_date: str) -> Dict:
        """
        单独收集指定日期的大盘指数数据（精准重试）
        :param trade_date: 交易日（格式YYYYMMDD）
        :return: 执行结果 {'success': bool, 'trade_date': str}
        """
        logger.info(f"开始单独收集 {trade_date} 大盘指数数据")
        result = {
            'success': False,
            'trade_date': trade_date
        }
        
        try:
            success = self.market_collector.collect_market_indices(trade_date)
            result['success'] = success
            
            if success:
                logger.info(f"{trade_date} 大盘指数数据收集成功")
            else:
                logger.warning(f"{trade_date} 大盘指数数据收集失败")
            
            return result
        except Exception as e:
            logger.error(f"单独收集 {trade_date} 大盘指数数据异常: {e}", exc_info=True)
            result['error'] = str(e)
            return result
    
    def collect_sector_data_single_date(self, trade_date: str) -> Dict:
        """
        单独计算指定日期的板块数据（精准重试）
        :param trade_date: 交易日（格式YYYYMMDD）
        :return: 执行结果 {'success': bool, 'trade_date': str}
        """
        logger.info(f"开始单独计算 {trade_date} 板块数据")
        result = {
            'success': False,
            'trade_date': trade_date
        }
        
        try:
            success = self.market_collector.collect_sector_data(trade_date)
            result['success'] = success
            
            if success:
                logger.info(f"{trade_date} 板块数据计算成功")
            else:
                logger.warning(f"{trade_date} 板块数据计算失败")
            
            return result
        except Exception as e:
            logger.error(f"单独计算 {trade_date} 板块数据异常: {e}", exc_info=True)
            result['error'] = str(e)
            return result
    
    def retry_failed_stocks_high_freq(self, failed_codes: List[str], trade_date: str = None) -> Dict:
        """
        重试失败的股票高频数据收集
        :param failed_codes: 失败的股票代码列表
        :param trade_date: 交易日（格式YYYYMMDD）
        :return: 重试结果统计
        """
        logger.info(f"开始重试 {len(failed_codes)} 只失败股票的高频数据收集")
        result = {
            'total': len(failed_codes),
            'success': 0,
            'failed': 0,
            'failed_codes': []
        }
        
        for ts_code in failed_codes:
            try:
                if self.collect_single_stock_high_freq(ts_code, trade_date)['success']:
                    result['success'] += 1
                else:
                    result['failed'] += 1
                    result['failed_codes'].append(ts_code)
                time.sleep(0.2)
            except Exception as e:
                logger.error(f"重试股票 {ts_code} 失败: {e}")
                result['failed'] += 1
                result['failed_codes'].append(ts_code)
        
        logger.info(f"股票高频数据重试完成：成功 {result['success']}，失败 {result['failed']}")
        return result
    
    def retry_failed_dates(self, failed_dates: List[str], data_type: str = 'sector') -> Dict:
        """
        重试失败的日期数据（大盘/板块）
        :param failed_dates: 失败的日期列表
        :param data_type: 数据类型 'market'（大盘）或 'sector'（板块）
        :return: 重试结果统计
        """
        logger.info(f"开始重试 {len(failed_dates)} 个失败日期的 {data_type} 数据")
        result = {
            'total': len(failed_dates),
            'success': 0,
            'failed': 0,
            'failed_dates': []
        }
        
        for trade_date in failed_dates:
            try:
                if data_type == 'market':
                    success = self.collect_market_indices_single_date(trade_date)['success']
                else:  # sector
                    success = self.collect_sector_data_single_date(trade_date)['success']
                
                if success:
                    result['success'] += 1
                else:
                    result['failed'] += 1
                    result['failed_dates'].append(trade_date)
            except Exception as e:
                logger.error(f"重试日期 {trade_date} 失败: {e}")
                result['failed'] += 1
                result['failed_dates'].append(trade_date)
        
        logger.info(f"{data_type} 数据重试完成：成功 {result['success']}，失败 {result['failed']}")
        return result
    
    # ====================== 原有批量方法（保持不变） ======================
    def run_initial_collection(self) -> Dict[str, int]:
        """
        执行首次全量数据收集（供工作流调用）
        :return: 收集结果统计（成功/失败数）
        """
        logger.info("开始首次全量数据收集...")
        result = {
            "stock_success": 0, 
            "stock_failed": 0, 
            "market_failed_dates": [], 
            "sector_failed_dates": [],
            "market_news": {"fetched": 0, "saved": 0}
        }
        
        # 1. 全量股票数据收集
        logger.info("步骤1/4: 收集全量股票数据...")
        stock_result = self.stock_collector.batch_collect_all_stocks_full()
        result["stock_success"] = stock_result.get('success', 0)
        result["stock_failed"] = stock_result.get('failed', 0)
        logger.info(f"股票数据收集完成: 成功 {result['stock_success']}, 失败 {result['stock_failed']}")
        
        # 2. 近1000日大盘数据收集
        logger.info("步骤2/4: 收集近1000日大盘数据...")
        trade_dates = self._get_recent_trade_dates(1000)
        # 初始化Tushare接口（如果需要校验交易日）
        pro = ts.pro_api(self.tushare_token)

        for i, trade_date in enumerate(trade_dates, 1):
            logger.info(f"收集大盘数据 {i}/1000: {trade_date}")
            # 可选：先校验该日期是否为交易日，非交易日直接跳过
            try:
                cal = pro.trade_cal(exchange='', cal_date=trade_date)
                if not cal.empty and cal.iloc[0]['is_open'] != 1:
                    logger.info(f"非交易日跳过: {trade_date}")
                    continue
            except Exception as e:
                logger.warning(f"校验交易日失败，继续尝试收集数据: {trade_date}, {e}")
    
            if not self.market_collector.collect_market_indices(trade_date):
                result["market_failed_dates"].append(trade_date)
                logger.warning(f"大盘数据收集失败: {trade_date}")

        # 3. 近1000日板块数据计算
        logger.info("步骤3/4: 计算近1000日板块数据...")
        for i, trade_date in enumerate(trade_dates, 1):
            logger.info(f"计算板块数据 {i}/1000: {trade_date}")
            if not self.market_collector.collect_sector_data(trade_date):
                result["sector_failed_dates"].append(trade_date)
                logger.warning(f"板块数据计算失败: {trade_date}")
        
        # 4. 近10日大盘新闻收集（首次收集）
        logger.info("步骤4/4: 收集近10日大盘新闻...")
        try:
            news_result = self.market_news_collector.fetch_initial_news(days=10)
            result["market_news"]["fetched"] = news_result.get("total_fetched", 0)
            result["market_news"]["saved"] = news_result.get("total_saved", 0)
            logger.info(f"大盘新闻收集完成: 获取 {result['market_news']['fetched']} 条, 保存 {result['market_news']['saved']} 条")
        except Exception as e:
            logger.error(f"大盘新闻收集失败: {e}")
            result["market_news"]["error"] = str(e)
        
        logger.info("首次全量数据收集完成!")
        return result
    
    def remedy_missing_stocks(self, failed_codes_from_log: List[str] = None) -> Dict[str, any]:
        """
        【补救方案】比对数据库与Tushare，补采缺失/失败的股票全量数据
        :param failed_codes_from_log: 可选，从之前日志中记录的失败股票代码列表
        :return: 补救结果统计
        """
        logger.info("=" * 50)
        logger.info("开始执行股票数据补救任务")
        logger.info("=" * 50)
        
        result = {
            "action": "remedy",
            "total_checked": 0,
            "in_db": 0,
            "to_remedy": 0,
            "remedy_success": 0,
            "remedy_failed": 0,
            "remedy_codes": [],
            "still_failed_codes": []
        }

        try:
            # 1. 获取 Tushare 端的完整股票列表（最新上市状态）
            logger.info("步骤 1/4: 获取最新股票列表...")
            full_stock_list = self.stock_collector.get_stock_list()
            result["total_checked"] = len(full_stock_list)
            logger.info(f"Tushare 端共有股票: {result['total_checked']} 只")

            # 2. 获取数据库中已有的股票列表
            logger.info("步骤 2/4: 扫描数据库存量...")
            from sqlalchemy import distinct
            db_stock_codes = [
                r[0] for r in self.session.query(distinct(StockDetail.ts_code)).all()
            ]
            result["in_db"] = len(db_stock_codes)
            logger.info(f"数据库中已有股票: {result['in_db']} 只")

            # 3. 确定需要补救的股票清单
            # 3.1 找出完全不在数据库里的股票
            missing_codes = list(set(full_stock_list) - set(db_stock_codes))
            
            # 3.2 合并手动传入的失败代码（如果有）
            remedy_codes = list(set(missing_codes + (failed_codes_from_log or [])))
            result["to_remedy"] = len(remedy_codes)
            result["remedy_codes"] = remedy_codes
            
            if not remedy_codes:
                logger.info("未发现需要补救的股票，任务结束。")
                return result

            logger.warning(f"发现 {result['to_remedy']} 只股票需要补救/重采")
            logger.info(f"待处理列表: {remedy_codes[:10]}...") # 只打印前10个

            # 4. 执行补救性全量收集
            logger.info("步骤 3/4: 开始定向补采...")
            
            # 直接调用 StockCollector 的全量收集方法，但传入指定的 ts_codes 列表
            # 注意：这里我们复用 batch_collect_all_stocks_full，传入 remedy_codes
            remedy_result = self.stock_collector.batch_collect_all_stocks_full(
                ts_codes=remedy_codes
            )

            result["remedy_success"] = remedy_result.get("success", 0)
            result["remedy_failed"] = remedy_result.get("failed", 0)
            result["still_failed_codes"] = remedy_result.get("failed_codes", [])

            logger.info("=" * 50)
            logger.info("补救任务执行完毕")
            logger.info(f"成功补救: {result['remedy_success']}")
            logger.info(f"仍然失败: {result['remedy_failed']}")
            if result["still_failed_codes"]:
                logger.warning(f" persistent failed codes: {result['still_failed_codes']}")
            logger.info("=" * 50)

        except Exception as e:
            logger.error(f"补救任务执行异常: {e}", exc_info=True)
            result["error"] = str(e)
        finally:
            self.session.close()

        return result
    
    def run_daily_update(self, trade_date: str = None) -> Dict[str, bool]:
        """
        执行日常数据更新（供工作流调用，支持指定交易日）
        :param trade_date: 指定交易日（格式YYYYMMDD），默认取最新交易日
        :return: 更新结果（各步骤是否成功）
        """
        logger.info("开始日常数据更新...")
        result = {"stock": False, "market": False, "sector": False, "market_news": False}
        
        # 获取交易日（支持工作流指定，更灵活）
        trade_date = trade_date or self.market_collector.get_trade_date()
        logger.info(f"交易日: {trade_date}")
        
        # 1. 股票日频数据收集
        logger.info("步骤1/4: 收集股票日频数据...")
        stock_result = self.stock_collector.batch_collect_all_stocks_high_freq(trade_date=trade_date)
        result["stock"] = stock_result.get('success', 0) > 0  # 有成功即视为整体成功
        logger.info(f"股票日频数据收集完成: 成功 {stock_result.get('success', 0)}, 失败 {stock_result.get('failed', 0)}")
        
        # 2. 大盘当日数据收集
        logger.info("步骤2/4: 收集大盘当日数据...")
        result["market"] = self.market_collector.collect_market_indices(trade_date)
        logger.info(f"大盘数据收集: {'成功' if result['market'] else '失败'}")
        
        # 3. 板块当日数据计算
        logger.info("步骤3/4: 计算板块当日数据...")
        result["sector"] = self.market_collector.collect_sector_data(trade_date)
        logger.info(f"板块数据计算: {'成功' if result['sector'] else '失败'}")
        
        # 4. 大盘新闻收集
        logger.info("步骤4/4: 收集大盘新闻...")
        try:
            news_result = self.market_news_collector.fetch_all()
            result["market_news"] = news_result.get('total_saved', 0) > 0
            logger.info(f"大盘新闻收集: 保存 {news_result.get('total_saved', 0)} 条")
        except Exception as e:
            logger.error(f"大盘新闻收集失败: {e}")
            result["market_news"] = False
        
        logger.info("日常数据更新完成!")
        return result
    
    def run(self, trade_date: str = None) -> Dict[str, any]:
        """
        调度器主入口（适配工作流的统一调用接口）
        :param trade_date: 指定交易日（日常更新时用）
        :return: 整体执行结果
        """
        logger.info("=" * 50)
        logger.info(f"数据调度器执行启动 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 50)
        
        result = {"type": "", "data": None, "success": True}
        try:
            if self.is_first_run():
                # 首次运行：全量收集
                result["type"] = "initial"
                result["data"] = self.run_initial_collection()
            else:
                # 非首次：日常更新（低频数据已在高频采集时自动更新，移除独立扫描逻辑）
                result["type"] = "daily"
                daily_result = self.run_daily_update(trade_date)
                # 移除 low_freq_count 相关代码，仅保留日常更新结果
                result["data"] = {"daily": daily_result}
            
            logger.info("=" * 50)
            logger.info("数据调度器执行完成")
            logger.info("=" * 50)
        except Exception as e:
            logger.error(f"调度器执行失败: {e}", exc_info=True)
            result["success"] = False
            result["error"] = str(e)
            raise  # 抛出异常，让工作流感知失败
        finally:
            self.session.close()  # 确保数据库会话关闭
        
        return result
    
    def close(self):
        """关闭资源"""
        if hasattr(self, 'stock_collector') and self.stock_collector:
            self.stock_collector.session.close()
        logger.info("DataScheduler 已关闭")