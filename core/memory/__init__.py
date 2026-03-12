# core/memory/__init__.py
"""
记忆系统模块

提供三层记忆架构：
1. 工作记忆 (WorkingMemory) - 单次任务生命周期内的临时存储
2. 短期记忆 (ShortTermMemory) - 7天内分析报告的数据库存储
3. 长期记忆 (LongTermMemory) - 历史经验教训的向量化检索
4. 记忆管理器 (MemoryManager) - 统一协调三层记忆的入口

三层记忆设计：
├── WorkingMemory: 会话隔离的临时存储，任务结束后自动清理
├── ShortTermMemory: PostgreSQL存储最近分析报告，支持时间窗口检索
└── LongTermMemory: pgvector存储历史经验向量，支持相似性检索

使用示例：
    # 方式1：使用统一记忆管理器（推荐）
    from core.memory import get_memory_manager, MemoryManager
    
    # 获取全局记忆管理器
    mm = get_memory_manager()
    
    # 创建会话
    session_id = mm.create_session("STOCK_ANALYST_01", "TSLA_20250216")
    
    # 加载上下文
    context = mm.load_context("STOCK_ANALYST_01", "特斯拉Q4财报分析")
    
    # 保存结果
    result = {"ts_code": "TSLA", "summary": "盈利超预期", "score": 8.5}
    mm.save_result("STOCK_ANALYST_01", result)
    
    # 方式2：直接使用各层记忆
    from core.memory import WorkingMemory, get_working_memory
    from core.memory import ShortTermMemory, get_stm
    from core.memory import LongTermMemory, get_ltm
    
    wm = WorkingMemory()
    stm = get_stm()
    ltm = get_ltm()
    
    # 工作记忆操作
    wm.create_session("agent1", "task1")
    wm.set("agent1_task1", "raw_data", {...})
    
    # 短期记忆操作
    reports = stm.get_recent_reports("STOCK_ANALYST", "TSLA", days=3)
    
    # 长期记忆操作
    experiences = ltm.search_similar("财报分析", agent_type="STOCK_ANALYST")
"""

import logging

# 模块版本
__version__ = "1.0.0"

# 模块日志
logger = logging.getLogger(__name__)

from .working_memory import WorkingMemory, get_working_memory
from .short_memory import ShortTermMemory, get_stm
from .long_memory import LongTermMemory, get_ltm
from .memory_manager import MemoryManager, get_memory_manager

__all__ = [
    # 工作记忆
    "WorkingMemory",
    "get_working_memory",
    
    # 短期记忆
    "ShortTermMemory",
    "get_stm",
    
    # 长期记忆
    "LongTermMemory",
    "get_ltm",
    
    # 记忆管理器
    "MemoryManager",
    "get_memory_manager",
]