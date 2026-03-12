"""
全流程测试脚本：先执行数据收集调度器 (scheduler.py)，再执行选股调度器 (Selection_scheduler.py)
配置文件位置：
- 数据收集配置：E:\tradingagents\config\settings.yaml
- 选股配置：E:\tradingagents\config\factor.yaml
"""

import sys
import os
import logging
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(r"E:\tradingagents")
sys.path.insert(0, str(PROJECT_ROOT))  # 只需要这一行即可

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("test_pipeline")


def run_data_scheduler():
    """执行数据收集调度器 (DataScheduler)"""
    logger.info("=" * 60)
    logger.info("开始执行数据收集调度器 (DataScheduler)")
    logger.info("=" * 60)

    from data.basic_data.scheduler import DataScheduler

    settings_path = PROJECT_ROOT / "config" / "settings.yaml"
    if not settings_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {settings_path}")

    scheduler = DataScheduler(config_path=str(settings_path))
    try:
        # run() 会根据数据库状态自动选择首次全量或日常更新
        result = scheduler.run()
        logger.info(f"数据收集调度器执行完成，结果类型: {result.get('type')}")
        return result
    except Exception as e:
        logger.error(f"数据收集调度器执行失败: {e}", exc_info=True)
        raise
    finally:
        scheduler.close()


def run_selection_scheduler():
    """执行选股调度器 (Scheduler)，包含大白马筛选"""
    logger.info("=" * 60)
    logger.info("开始执行选股调度器 (SelectionScheduler)")
    logger.info("=" * 60)

    from core.stock_selection.Selection_scheduler import Scheduler

    factor_path = PROJECT_ROOT / "config" / "factor.yaml"
    if not factor_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {factor_path}")

    # 初始化选股调度器（传入因子配置文件路径，ConfigManager 会自动读取 settings.yaml）
    scheduler = Scheduler(config_path=str(factor_path))
    try:
        # 执行完整选股流程（包含因子更新、因子筛选、股票筛选、大白马筛选）
        summary = scheduler.run_with_white_horse()
        logger.info("选股调度器执行完成")
        return summary
    except Exception as e:
        logger.error(f"选股调度器执行失败: {e}", exc_info=True)
        raise
    finally:
        scheduler.close()


def main():
    """主流程：先数据收集，后选股"""
    try:
        # 步骤1：数据收集
        run_data_scheduler()

        # 步骤2：选股（依赖数据收集的结果）
        run_selection_scheduler()

        logger.info("=" * 60)
        logger.info("全流程执行成功！")
        logger.info("=" * 60)


    except Exception as e:
        import traceback
        logger.critical(f"测试流程异常终止: {e}")
        logger.critical(traceback.format_exc())  # 打印详细堆栈
        sys.exit(1)


if __name__ == "__main__":
    main()