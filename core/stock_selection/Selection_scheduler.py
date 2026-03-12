"""
量化选股调度器

功能说明：
1. 统一调度因子计算、因子筛选、股票筛选的完整流程
2. 自动检测各环节是否需要更新
3. 提供单一入口执行整个工作流
4. 支持大白马股票筛选（一年更新一次）

工作流程：
1. 更新因子库（Factor_factory.py）
2. 检查因子有效期，过期则重新筛选因子（Factor_selection.py）
3. 检查股票池有效期，过期则重新筛选股票（stock_selector.py）
4. 检查大白马股票池有效期，过期则重新筛选（select_white_horse）

使用示例：
    scheduler = Scheduler(config_path="config.yaml")
    scheduler.run()  # 执行完整流程
    scheduler.run_with_white_horse()  # 包含大白马筛选的完整流程
"""

import sys
import logging
import yaml
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta, date
from enum import Enum

# 获取项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import  func

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class UpdateStatus(Enum):
    """更新状态枚举"""
    NOT_NEEDED = "not_needed"   # 无需更新
    NEEDED = "needed"           # 需要更新
    UPDATED = "updated"         # 已更新


class Scheduler:
    """
    量化选股调度器
    
    核心功能：
    1. 协调因子计算、因子筛选、股票筛选的执行顺序
    2. 基于有效期判断是否需要重新执行各环节
    3. 提供完整的执行日志和状态报告
    4. 支持大白马股票筛选（一年更新一次）
    """
    
    # 周期类型
    TERM_SHORT = "short_term"
    TERM_MEDIUM = "medium_term"
    TERM_LONG = "long_term"
    TERM_WHITE_HORSE = "white_horse"  # 大白马股票类型
    
    # 股票池类型映射
    POOL_TYPE_MAP = {
        "short_term": "SHORT",
        "medium_term": "MID",
        "long_term": "LONG",
        "white_horse": "WHITE_HORSE",
    }
    
    def __init__(self, config_path: str = None, config_dict: Dict = None):
        """
        初始化调度器
        
        Args:
            config_path: YAML配置文件路径
            config_dict: 直接传入的配置字典
        """
        # 加载配置
        from .config_manager import ConfigManager
        self.config = ConfigManager(config_path=config_path, config_dict=config_dict)
        
        # 导入各模块
        self._import_modules()
        
        # 初始化数据库
        self._init_database()
        
        # 执行状态
        self.execution_log: List[Dict] = []
        self.update_status: Dict[str, UpdateStatus] = {}
        
        logger.info("=" * 60)
        logger.info("量化选股调度器初始化完成")
        logger.info("=" * 60)
    
    def _import_modules(self):
        """动态导入各模块"""
        try:
            from .Factor_factory import FactorEngine, ComputeMode
            self.FactorEngine = FactorEngine
            self.ComputeMode = ComputeMode
            logger.info("因子计算引擎导入成功")
        except ImportError as e:
            logger.warning(f"因子计算引擎导入失败: {e}")
            self.FactorEngine = None
            self.ComputeMode = None
        
        try:
            from .Factor_selection import FactorSelector
            self.FactorSelector = FactorSelector
            logger.info("因子筛选器导入成功")
        except ImportError as e:
            logger.warning(f"因子筛选器导入失败: {e}")
            self.FactorSelector = None
        
        try:
            from .Stock_selection import StockSelector
            self.StockSelector = StockSelector
            logger.info("股票筛选器导入成功")
        except ImportError as e:
            logger.warning(f"股票筛选器导入失败: {e}")
            self.StockSelector = None
    
    def _init_database(self):
        """初始化数据库连接"""
        try:
            from data.basic_data.database import init_db, get_session, StockPool
            init_db(self.config.DB_URL)
            self.session = get_session()
            self.StockPool = StockPool
            logger.info("数据库连接成功")
        except ImportError as e:
            logger.error(f"数据库模块导入失败: {e}")
            self.session = None
            self.StockPool = None
    
    def _log_execution(self, step: str, status: str, message: str = "", details: Dict = None):
        """记录执行日志"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "step": step,
            "status": status,
            "message": message,
            "details": details or {},
        }
        self.execution_log.append(log_entry)
        logger.info(f"[{step}] {status}: {message}")
    
    # ==================== 因子库更新 ====================
    
    def update_factor_library(self, force: bool = False) -> bool:
        """
        更新因子库
        
        Args:
            force: 是否强制更新
        
        Returns:
            是否成功
        """
        logger.info("\n" + "=" * 60)
        logger.info("步骤1: 更新因子库")
        logger.info("=" * 60)
        
        if self.FactorEngine is None:
            self._log_execution("因子库更新", "失败", "因子计算引擎未导入")
            return False
        
        try:
            engine = self.FactorEngine(config=self.config)
            
            if force:
                engine.run(mode=self.ComputeMode.FULL)
            else:
                engine.run()  # 自动检测模式
            
            self._log_execution("因子库更新", "成功", "因子库已更新")
            self.update_status["factor_library"] = UpdateStatus.UPDATED
            return True
            
        except Exception as e:
            self._log_execution("因子库更新", "失败", str(e))
            logger.error(f"因子库更新失败: {e}", exc_info=True)
            return False
    
    # ==================== 因子筛选 ====================
    
    def _get_factor_update_date(self, term: str) -> Optional[date]:
        """获取因子配置文件的更新日期"""
        yaml_path = self.config.get_factor_yaml_path(term)
        
        if not yaml_path.exists():
            return None
        
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            
            if not data:
                return None
            
            update_date_str = data.get("update_date")
            if update_date_str:
                return datetime.strptime(update_date_str, "%Y-%m-%d").date()
            
            return None
        except Exception as e:
            logger.warning(f"读取因子配置文件失败: {e}")
            return None
    
    def _check_factor_validity(self, term: str) -> UpdateStatus:
        """检查因子是否在有效期内"""
        validity_days = self.config.get(f"stock_selection.factor_validity_days.{term}", 30)
        update_date = self._get_factor_update_date(term)
        
        if update_date is None:
            logger.info(f"{term}: 因子配置文件不存在或无更新日期，需要筛选")
            return UpdateStatus.NEEDED
        
        days_gap = (date.today() - update_date).days
        
        if days_gap > validity_days:
            logger.info(f"{term}: 因子已过期 ({days_gap}天 > {validity_days}天)，需要重新筛选")
            return UpdateStatus.NEEDED
        else:
            logger.info(f"{term}: 因子有效 ({days_gap}天 <= {validity_days}天)，无需更新")
            return UpdateStatus.NOT_NEEDED
    
    def update_factor_selection(self, force: bool = False) -> Dict[str, bool]:
        """
        更新因子筛选
        
        Args:
            force: 是否强制更新所有周期
        
        Returns:
            各周期更新结果
        """
        logger.info("\n" + "=" * 60)
        logger.info("步骤2: 检查因子有效期并更新")
        logger.info("=" * 60)
        
        results = {}
        
        if self.FactorSelector is None:
            self._log_execution("因子筛选", "失败", "因子筛选器未导入")
            return {term: False for term in [self.TERM_SHORT, self.TERM_MEDIUM, self.TERM_LONG]}
        
        for term in [self.TERM_SHORT, self.TERM_MEDIUM, self.TERM_LONG]:
            status = self._check_factor_validity(term)
            
            if force or status == UpdateStatus.NEEDED:
                try:
                    selector = self.FactorSelector(config=self.config)
                    
                    # 只筛选需要更新的周期
                    if not force:
                        # 设置只更新该周期
                        selector.update_required[term] = True
                        selector.selection_mode[term] = type('SelectionMode', (), {'value': 'update'})()
                    
                    selector.run(force=force)
                    
                    self._log_execution(f"{term}因子筛选", "成功", f"因子配置已更新")
                    results[term] = True
                    self.update_status[f"factor_{term}"] = UpdateStatus.UPDATED
                    
                except Exception as e:
                    self._log_execution(f"{term}因子筛选", "失败", str(e))
                    logger.error(f"{term}因子筛选失败: {e}", exc_info=True)
                    results[term] = False
            else:
                self._log_execution(f"{term}因子筛选", "跳过", "因子仍在有效期内")
                results[term] = True
                self.update_status[f"factor_{term}"] = UpdateStatus.NOT_NEEDED
        
        return results
    
    # ==================== 股票池更新 ====================
    
    def _get_stockpool_update_date(self, term: str) -> Optional[date]:
        """获取股票池的最新更新日期"""
        if self.session is None or self.StockPool is None:
            return None
        
        pool_type = self.POOL_TYPE_MAP.get(term)
        if not pool_type:
            return None
        
        try:
            latest_update = self.session.query(
                func.max(self.StockPool.update_time)
            ).filter(
                self.StockPool.pool_type == pool_type
            ).scalar()
            
            if latest_update:
                if isinstance(latest_update, datetime):
                    return latest_update.date()
                return latest_update
            
            return None
        except Exception as e:
            logger.warning(f"查询股票池更新时间失败: {e}")
            return None
    
    def _check_stockpool_validity(self, term: str) -> UpdateStatus:
        """检查股票池是否在有效期内"""
        # 大白马股票使用独立的有效期配置
        if term == self.TERM_WHITE_HORSE:
            validity_days = self.config.get_white_horse_validity_days()
        else:
            validity_days = self.config.get(f"stock_selection.stock_validity_days.{term}", 30)
        
        update_date = self._get_stockpool_update_date(term)
        
        if update_date is None:
            logger.info(f"{term}: 股票池为空或无更新日期，需要筛选")
            return UpdateStatus.NEEDED
        
        days_gap = (date.today() - update_date).days
        
        if days_gap > validity_days:
            logger.info(f"{term}: 股票池已过期 ({days_gap}天 > {validity_days}天)，需要重新筛选")
            return UpdateStatus.NEEDED
        else:
            logger.info(f"{term}: 股票池有效 ({days_gap}天 <= {validity_days}天)，无需更新")
            return UpdateStatus.NOT_NEEDED
    
    def update_stock_selection(self, force: bool = False) -> Dict[str, List[str]]:
        """
        更新股票池
        
        Args:
            force: 是否强制更新所有周期
        
        Returns:
            各周期选中的股票列表
        """
        logger.info("\n" + "=" * 60)
        logger.info("步骤3: 检查股票池有效期并更新")
        logger.info("=" * 60)
        
        results = {}
        
        if self.StockSelector is None:
            self._log_execution("股票筛选", "失败", "股票筛选器未导入")
            return {term: [] for term in [self.TERM_SHORT, self.TERM_MEDIUM, self.TERM_LONG]}
        
        selector = self.StockSelector(config=self.config)
        
        for term in [self.TERM_SHORT, self.TERM_MEDIUM, self.TERM_LONG]:
            status = self._check_stockpool_validity(term)
            
            if force or status == UpdateStatus.NEEDED:
                try:
                    if term == self.TERM_SHORT:
                        stocks = selector.select_short_term()
                    elif term == self.TERM_MEDIUM:
                        stocks = selector.select_medium_term()
                    else:
                        stocks = selector.select_long_term()
                    
                    self._log_execution(f"{term}股票筛选", "成功", f"选中 {len(stocks)} 只股票")
                    results[term] = stocks
                    self.update_status[f"stock_{term}"] = UpdateStatus.UPDATED
                    
                except Exception as e:
                    self._log_execution(f"{term}股票筛选", "失败", str(e))
                    logger.error(f"{term}股票筛选失败: {e}", exc_info=True)
                    results[term] = []
            else:
                self._log_execution(f"{term}股票筛选", "跳过", "股票池仍在有效期内")
                results[term] = []
                self.update_status[f"stock_{term}"] = UpdateStatus.NOT_NEEDED
        
        selector.close()
        return results
    
    # ==================== 大白马股票更新 ====================
    
    def update_white_horse_selection(self, force: bool = False) -> List[str]:
        """
        更新大白马股票池
        
        大白马股票一年更新一次，筛选高股息、大市值、优质蓝筹股
        
        Args:
            force: 是否强制更新
        
        Returns:
            选中的股票列表
        """
        logger.info("\n" + "=" * 60)
        logger.info("步骤4: 检查大白马股票池有效期并更新")
        logger.info("=" * 60)
        
        if self.StockSelector is None:
            self._log_execution("大白马筛选", "失败", "股票筛选器未导入")
            return []
        
        status = self._check_stockpool_validity(self.TERM_WHITE_HORSE)
        
        if force or status == UpdateStatus.NEEDED:
            try:
                selector = self.StockSelector(config=self.config)
                
                # 获取配置的选股数量
                top_n = self.config.WHITE_HORSE_TOP_N
                
                # 执行大白马选股
                stocks = selector.select_white_horse(top_n=top_n)
                
                self._log_execution("大白马筛选", "成功", f"选中 {len(stocks)} 只大白马股票")
                self.update_status["white_horse"] = UpdateStatus.UPDATED
                
                selector.close()
                return stocks
                
            except Exception as e:
                self._log_execution("大白马筛选", "失败", str(e))
                logger.error(f"大白马筛选失败: {e}", exc_info=True)
                return []
        else:
            self._log_execution("大白马筛选", "跳过", "大白马股票池仍在有效期内（一年有效）")
            self.update_status["white_horse"] = UpdateStatus.NOT_NEEDED
            return []
    
    # ==================== 主入口 ====================
    
    def run(self, force_factor_update: bool = False, force_stock_update: bool = False) -> Dict:
        """
        执行完整的调度流程
        
        Args:
            force_factor_update: 是否强制更新因子库
            force_stock_update: 是否强制更新股票池
        
        Returns:
            执行结果摘要
        """
        logger.info("\n" + "=" * 60)
        logger.info("量化选股调度器启动")
        logger.info("=" * 60)
        
        start_time = datetime.now()
        
        # 步骤1: 更新因子库
        factor_lib_success = self.update_factor_library(force=force_factor_update)
        
        # 步骤2: 更新因子筛选
        factor_selection_results = self.update_factor_selection()
        
        # 步骤3: 更新股票池
        stock_selection_results = self.update_stock_selection(force=force_stock_update)
        
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()
        
        # 生成摘要
        summary = {
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "elapsed_seconds": elapsed,
            "factor_library_updated": factor_lib_success,
            "factor_selection": {
                term: ("success" if factor_selection_results.get(term) else "skipped/failed")
                for term in [self.TERM_SHORT, self.TERM_MEDIUM, self.TERM_LONG]
            },
            "stock_selection": {
                term: f"{len(stocks)} stocks" if stocks else "skipped"
                for term, stocks in stock_selection_results.items()
            },
            "execution_log": self.execution_log,
        }
        
        logger.info("\n" + "=" * 60)
        logger.info("调度执行完成")
        logger.info(f"总耗时: {elapsed:.1f}秒")
        logger.info("=" * 60)
        
        return summary
    
    def run_with_white_horse(self, force_factor_update: bool = False, 
                              force_stock_update: bool = False,
                              force_white_horse_update: bool = False) -> Dict:
        """
        执行完整的调度流程（包含大白马股票筛选）
        
        Args:
            force_factor_update: 是否强制更新因子库
            force_stock_update: 是否强制更新股票池
            force_white_horse_update: 是否强制更新大白马股票池
        
        Returns:
            执行结果摘要
        """
        logger.info("\n" + "=" * 60)
        logger.info("量化选股调度器启动（含大白马筛选）")
        logger.info("=" * 60)
        
        start_time = datetime.now()
        
        # 步骤1: 更新因子库
        factor_lib_success = self.update_factor_library(force=force_factor_update)
        
        # 步骤2: 更新因子筛选
        factor_selection_results = self.update_factor_selection()
        
        # 步骤3: 更新股票池
        stock_selection_results = self.update_stock_selection(force=force_stock_update)
        
        # 步骤4: 更新大白马股票池
        white_horse_stocks = self.update_white_horse_selection(force=force_white_horse_update)
        
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()
        
        # 生成摘要
        summary = {
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "elapsed_seconds": elapsed,
            "factor_library_updated": factor_lib_success,
            "factor_selection": {
                term: ("success" if factor_selection_results.get(term) else "skipped/failed")
                for term in [self.TERM_SHORT, self.TERM_MEDIUM, self.TERM_LONG]
            },
            "stock_selection": {
                term: f"{len(stocks)} stocks" if stocks else "skipped"
                for term, stocks in stock_selection_results.items()
            },
            "white_horse_selection": f"{len(white_horse_stocks)} stocks" if white_horse_stocks else "skipped",
            "execution_log": self.execution_log,
        }
        
        logger.info("\n" + "=" * 60)
        logger.info("调度执行完成（含大白马筛选）")
        logger.info(f"总耗时: {elapsed:.1f}秒")
        logger.info("=" * 60)
        
        return summary
    
    def get_status(self) -> Dict:
        """获取当前状态"""
        status = {
            "update_status": {k: v.value for k, v in self.update_status.items()},
            "factor_validity": {},
            "stockpool_validity": {},
        }
        
        for term in [self.TERM_SHORT, self.TERM_MEDIUM, self.TERM_LONG]:
            factor_status = self._check_factor_validity(term)
            stock_status = self._check_stockpool_validity(term)
            
            status["factor_validity"][term] = factor_status.value
            status["stockpool_validity"][term] = stock_status.value
        
        # 添加大白马股票池状态
        white_horse_status = self._check_stockpool_validity(self.TERM_WHITE_HORSE)
        status["stockpool_validity"][self.TERM_WHITE_HORSE] = white_horse_status.value
        
        return status
    
    def get_white_horse_status(self) -> Dict:
        """
        获取大白马股票池状态
        
        Returns:
            大白马股票池状态信息
        """
        update_date = self._get_stockpool_update_date(self.TERM_WHITE_HORSE)
        validity_days = self.config.get_white_horse_validity_days()
        status = self._check_stockpool_validity(self.TERM_WHITE_HORSE)
        
        return {
            "pool_type": "WHITE_HORSE",
            "update_date": update_date.isoformat() if update_date else None,
            "validity_days": validity_days,
            "status": status.value,
            "days_remaining": (validity_days - (date.today() - update_date).days) if update_date else None,
        }
    
    def close(self):
        """关闭资源"""
        if self.session:
            self.session.close()
            logger.info("数据库连接已关闭")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="量化选股调度器")
    parser.add_argument("--config", "-c", type=str, help="配置文件路径")
    parser.add_argument("--force-factor", "-ff", action="store_true", help="强制更新因子库")
    parser.add_argument("--force-stock", "-fs", action="store_true", help="强制更新股票池")
    parser.add_argument("--force-white-horse", "-fw", action="store_true", help="强制更新大白马股票池")
    parser.add_argument("--with-white-horse", "-wh", action="store_true", help="包含大白马股票筛选")
    parser.add_argument("--status", "-s", action="store_true", help="仅显示状态")
    parser.add_argument("--white-horse-status", "-whs", action="store_true", help="显示大白马股票池状态")
    
    args = parser.parse_args()
    
    scheduler = Scheduler(config_path=args.config)
    
    if args.white_horse_status:
        wh_status = scheduler.get_white_horse_status()
        print("\n大白马股票池状态:")
        print("=" * 40)
        print(f"股票池类型: {wh_status['pool_type']}")
        print(f"更新日期: {wh_status['update_date'] or '未更新'}")
        print(f"有效期: {wh_status['validity_days']}天")
        print(f"当前状态: {wh_status['status']}")
        if wh_status['days_remaining']:
            print(f"剩余天数: {wh_status['days_remaining']}天")
    elif args.status:
        status = scheduler.get_status()
        print("\n当前状态:")
        print("=" * 40)
        print(f"因子有效期状态: {status['factor_validity']}")
        print(f"股票池有效期状态: {status['stockpool_validity']}")
    elif args.with_white_horse:
        summary = scheduler.run_with_white_horse(
            force_factor_update=args.force_factor,
            force_stock_update=args.force_stock,
            force_white_horse_update=args.force_white_horse
        )
        print("\n执行摘要:")
        print("=" * 40)
        print(f"因子库更新: {summary['factor_library_updated']}")
        print(f"因子筛选: {summary['factor_selection']}")
        print(f"股票筛选: {summary['stock_selection']}")
        print(f"大白马筛选: {summary['white_horse_selection']}")
        print(f"总耗时: {summary['elapsed_seconds']:.1f}秒")
    else:
        summary = scheduler.run(
            force_factor_update=args.force_factor,
            force_stock_update=args.force_stock
        )
        print("\n执行摘要:")
        print("=" * 40)
        print(f"因子库更新: {summary['factor_library_updated']}")
        print(f"因子筛选: {summary['factor_selection']}")
        print(f"股票筛选: {summary['stock_selection']}")
        print(f"总耗时: {summary['elapsed_seconds']:.1f}秒")
    
    scheduler.close()


if __name__ == "__main__":
    main()