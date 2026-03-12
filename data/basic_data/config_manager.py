import os
import yaml
import logging
import sys
from datetime import datetime
from typing import Dict, Any

# 全局单例配置缓存
_CONFIG_CACHE = None
_LOGGER_INITIALIZED = False

def get_project_root() -> str:
    """获取项目根目录"""
    # 当前文件: e:\tradingagents\data\basic_data\config_manager.py
    # 向上3级: e:\tradingagents
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def load_config() -> Dict[str, Any]:
    """
    统一加载配置文件
    路径: {project_root}/config/settings.yaml
    """
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    project_root = get_project_root()
    config_path = os.path.join(project_root, "config", "settings.yaml")

    try:
        if not os.path.exists(config_path):
            # 如果找不到，尝试默认路径或报错
            raise FileNotFoundError(f"配置文件未找到: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            _CONFIG_CACHE = yaml.safe_load(f) or {}
            
        return _CONFIG_CACHE
    except Exception as e:
        # 如果日志已初始化，记录错误；否则打印到stderr
        msg = f"读取配置文件失败: {e}"
        if _LOGGER_INITIALIZED:
            logging.getLogger(__name__).error(msg)
        else:
            sys.stderr.write(msg + "\n")
        raise

def setup_logging(name: str = None, log_file: str = None) -> logging.Logger:
    """
    统一日志配置
    :param name: Logger名称，通常传入 __name__
    :param log_file: 可选的日志文件名，如果不传则默认按日期生成
    :return: 配置好的Logger实例
    """
    global _LOGGER_INITIALIZED
    
    # 获取根Logger配置（确保只配置一次Handlers）
    root_logger = logging.getLogger()
    
    if not _LOGGER_INITIALIZED:
        project_root = get_project_root()
        logs_dir = os.path.join(project_root, "logs")
        os.makedirs(logs_dir, exist_ok=True)

        # 默认格式
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # 1. 文件Handler
        if not log_file:
            log_file = f"{datetime.now().strftime('%Y-%m-%d')}.log"
        
        log_path = os.path.join(logs_dir, log_file)
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        # 2. 控制台Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        root_logger.setLevel(logging.INFO)
        _LOGGER_INITIALIZED = True

    # 返回请求的Logger
    return logging.getLogger(name)

# 方便导入的单例对象
# 注意：在模块导入时不会自动执行耗时操作，要在函数调用时执行
