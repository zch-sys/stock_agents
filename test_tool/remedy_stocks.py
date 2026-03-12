import os
import sys
import traceback

# 定义要监控的目标路径
target_path = r"E:\tradingagents\data\basic_data\basic_data"
original_makedirs = os.makedirs

def traced_makedirs(name, mode=0o777, exist_ok=False):
    # 检查创建的路径是否包含我们要找的目标
    if target_path in name or 'basic_data\\basic_data' in name:
        print("="*60)
        print(f"⚠️  检测到试图创建可疑目录: {name}")
        print("="*60)
        print("调用堆栈如下：")
        traceback.print_stack()
        print("="*60)
        # 如果你想阻止它创建，取消下面这行的注释：
        # raise Exception("Stop here!")
    
    # 调用原始的 makedirs
    return original_makedirs(name, mode, exist_ok)

# 钩子替换
os.makedirs = traced_makedirs



import os
import sys
import logging

# ==========================================
# 1. 修正路径逻辑：关键修改部分
# ==========================================
# 获取当前脚本所在目录 (E:\tradingagents\test_tool)
script_dir = os.path.dirname(os.path.abspath(__file__))
# 获取项目根目录 (E:\tradingagents) -> 向上找一级
project_root = os.path.dirname(script_dir) 
# 将项目根目录加入 sys.path，这样才能找到 'data' 模块
sys.path.insert(0, project_root)

# 2. 导入项目模块
from data.basic_data.stock import StockCollector
from data.basic_data.database import init_db, get_session, StockDetail
import yaml

# 3. 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def load_config():
    """读取配置文件"""
    config_path = os.path.join(project_root, "config", "settings.yaml")
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"读取配置文件失败，请确认路径: {config_path}")
        raise e

def main():
    logger.info("="*60)
    logger.info("股票数据补救脚本启动 (已修复路径)")
    logger.info(f"项目根目录识别为: {project_root}")
    logger.info("="*60)

    # --- 初始化 ---
    config = load_config()
    db_url = config['data_collector']['db_url']
    tushare_token = config['data_collector']['tushare_token']

    init_db(db_url)
    session = get_session()
    collector = StockCollector(token=tushare_token)

    # --- 比对 ---
    logger.info(">>> 正在比对股票列表...")
    
    # 1. Tushare 列表
    full_list = collector.get_stock_list()
    
    # 2. 数据库列表
    from sqlalchemy import distinct
    existing_codes = [
        r[0] for r in session.query(distinct(StockDetail.ts_code)).all()
    ]
    
    logger.info(f"Tushare总数: {len(full_list)} | 数据库已有: {len(existing_codes)}")

    # 3. 计算缺失
    missing_codes = list(set(full_list) - set(existing_codes))
    
    # -------------------------------------------------------------------------
    # 【重点】如果你只是想重试之前报错的那几只，请注释掉上面一行，取消下面这行的注释：
    # missing_codes = ['301376.SZ', '301377.SZ'] 
    # -------------------------------------------------------------------------

    if not missing_codes:
        logger.info("🎉 没有缺失数据，程序退出。")
        return

    logger.warning(f"待补救数量: {len(missing_codes)}")
    logger.warning(f"列表预览: {missing_codes[:20]}")

    # --- 执行补救 ---
    logger.info(">>> 开始补采...")
    result = collector.batch_collect_all_stocks_full(ts_codes=missing_codes)

    # --- 结束 ---
    logger.info("="*60)
    logger.info(f"任务结束。成功: {result.get('success')}, 失败: {result.get('failed')}")
    if result.get('failed_codes'):
        logger.error(f"最终失败列表: {result.get('failed_codes')}")
    logger.info("="*60)
    session.close()
    collector.session.close()

if __name__ == "__main__":
    main()