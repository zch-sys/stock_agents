import sys
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.memory.working_memory import WorkingMemory, get_working_memory
from core.memory.short_memory import ShortTermMemory
from core.memory.long_memory import LongTermMemory
from data.basic_data.database import init_db, get_session
from data.basic_data.config_manager import load_config

logger = logging.getLogger(__name__)

_db_initialized = False

def _ensure_db_initialized():
    global _db_initialized
    if not _db_initialized:
        try:
            config = load_config()
            db_url = config.get('data_collector', {}).get('db_url')
            if db_url:
                init_db(db_url)
                _db_initialized = True
                logger.info("MemoryManager 数据库初始化成功")
            else:
                logger.warning("配置文件中未找到 db_url")
        except Exception as e:
            logger.warning(f"MemoryManager 数据库初始化失败: {e}")

class MemoryManager:
    """
    统一记忆管理器
    
    职责：
    1. 协调三层记忆（工作/短期/长期）
    2. 根据 Agent 类型注入差异化配置
    3. 提供统一的记忆操作接口
    """
    
    def __init__(self, agent_configs: Dict[str, Any] = None):
        _ensure_db_initialized()
        
        self.working_memory = WorkingMemory()
        self.short_term_memory = None
        self.long_term_memory = None
        
        self.agent_configs = agent_configs or {}
        
        logger.debug("MemoryManager 初始化完成")
    
    # ==================== 会话管理 ====================
    
    def create_session(self, agent_id: str, task_id: str) -> str:
        """
        创建工作记忆会话
        
        Args:
            agent_id: Agent 唯一标识
            task_id: 任务唯一标识
            
        Returns:
            session_id: 用于后续操作的会话 ID
        """
        session_id = self.working_memory.create_session(agent_id, task_id)
        logger.info(f"创建记忆会话: {session_id}")
        return session_id
    
    def clear_session(self, agent_id: str, task_id: str) -> None:
        """
        清空工作记忆会话
        
        Args:
            agent_id: Agent 唯一标识
            task_id: 任务唯一标识
        """
        session_id = f"{agent_id}_{task_id}"
        self.working_memory.clear_session(session_id)
        logger.info(f"清空记忆会话: {session_id}")
    
    # ==================== 上下文加载 ====================
    
    def load_context(self, agent_id: str, query: str) -> Dict[str, Any]:
        """
        加载分析上下文
        
        整合：
        1. 短期记忆（最近报告）
        2. 长期记忆（相似历史经验）
        
        Args:
            agent_id: Agent 标识
            query: 当前分析查询
            
        Returns:
            包含短期和长期记忆的上下文字典
        """
        agent_type = self._extract_agent_type(agent_id)
        
        short_term = self.load_short_term(agent_id)
        long_term = self.search_long_term(query, agent_type)  # 🔧 移除硬编码的 k=3，使用配置值
        
        context = {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "short_term_memory": short_term,
            "long_term_memory": long_term,
            "query": query
        }
        
        logger.info(f"为 {agent_id} 加载上下文: {len(short_term)} 条短期记忆, {len(long_term)} 条长期记忆")
        return context
    
    def load_short_term(self, agent_id: str, reference_date: date = None) -> List[Dict[str, Any]]:
        """
        加载短期记忆（最近报告）
        
        Args:
            agent_id: Agent 标识
            reference_date: 参考日期（默认今天）
            
        Returns:
            最近报告列表
        """
        agent_type = self._extract_agent_type(agent_id)
        
        limit = self._get_agent_config(agent_type).get("short_term_days", 3)
        
        stm = self._get_stm(agent_type)
        reports = stm.get_recent_reports(agent_type, "INDEX", limit=limit, reference_date=reference_date)
        
        logger.debug(f"为 {agent_id} 加载 {len(reports)} 条短期记忆")
        return reports
    
    def search_long_term(self, query: str, agent_type: str, k: int = None) -> List[Dict[str, Any]]:
        """
        检索相似的历史经验
        
        Args:
            query: 查询文本
            agent_type: Agent 类型
            k: 返回条数（可选，默认从配置读取）
            
        Returns:
            相似历史经验列表
        """
        ltm = self._get_ltm(agent_type)
        
        # 从配置获取阈值和条数
        config = self._get_agent_config(agent_type)
        distance_threshold = config.get("distance_threshold")
        top_k = k or config.get("top_k", 5)  # 🔧 优先使用传入的 k，否则从配置读取
        
        results = ltm.search_similar(
            query_text=query,
            agent_type=agent_type,
            top_k=top_k,
            distance_threshold=distance_threshold
        )
        
        logger.debug(f"为 {agent_type} 检索到 {len(results)} 条长期记忆")
        return results
    
    # ==================== 结果保存 ====================
    
    def save_result(self, agent_id: str, result: Dict[str, Any], trade_date: date = None) -> None:
        """
        保存分析结果到短期记忆
        
        Args:
            agent_id: Agent 标识
            result: 分析结果字典（包含 summary 和 confidence 字段）
            trade_date: 交易日期（可选，默认从result中提取）
        """
        agent_type = self._extract_agent_type(agent_id)
        
        ts_code = result.get("ts_code", "INDEX")
        
        if trade_date is None:
            for key in ["date", "trade_date"]:
                if key in result:
                    date_str = result.get(key)
                    if isinstance(date_str, str):
                        trade_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                        break
        
        stm = self._get_stm(agent_type)
        
        try:
            stm.save_report(
                agent_type=agent_type,
                report_content=result,
                ts_code=ts_code,
                trade_date=trade_date
            )
            logger.info(f"✅ 保存结果到短期记忆: [{agent_id}] {ts_code}")
        except Exception as e:
            logger.error(f"保存结果失败: {e}")
    
    def save_experience(self, agent_id: str, insight: str) -> bool:
        """
        保存经验教训到长期记忆
        
        Args:
            agent_id: Agent 标识
            insight: 经验文本
            
        Returns:
            保存是否成功
        """
        agent_type = self._extract_agent_type(agent_id)
        
        ltm = self._get_ltm(agent_type)
        
        # 从 insight 中提取可能的标的代码
        ts_code = "SYSTEM"
        event_type = "PATTERN"
        
        success = ltm.save_experience(
            agent_type=agent_type,
            insight_text=insight,
            event_type=event_type,
            ts_code=ts_code
        )
        
        if success:
            logger.info(f"✅ 保存经验到长期记忆: [{agent_id}]")
        else:
            logger.error(f"❌ 保存经验失败: [{agent_id}]")
        
        return success
    
    # ==================== 辅助方法 ====================
    
    def get_recent_reports(self, agent_id: str, n: int = 3, reference_date: date = None) -> List[Dict[str, Any]]:
        """
        获取最近N份报告
        
        Args:
            agent_id: Agent 标识
            n: 报告数量
            reference_date: 参考日期（默认今天）
            
        Returns:
            报告列表
        """
        agent_type = self._extract_agent_type(agent_id)
        
        stm = self._get_stm(agent_type)
        reports = stm.get_recent_reports(agent_type, "INDEX", limit=n, reference_date=reference_date)
        
        return reports
    
    def validate_last_judgment(self, agent_id: str) -> Dict[str, Any]:
        """
        验证上次判断准确性
        
        通过对比昨天预测与今天实际，生成验证报告
        
        Args:
            agent_id: Agent 标识
            
        Returns:
            验证结果字典
        """
        agent_type = self._extract_agent_type(agent_id)
        
        stm = self._get_stm(agent_type)
        latest_report = stm.get_latest_report(agent_type, "INDEX")
        
        if not latest_report:
            return {"valid": False, "reason": "无最近报告"}
        
        validation = {
            "valid": True,
            "agent_id": agent_id,
            "latest_summary": latest_report.get("summary", ""),
            "latest_score": latest_report.get("score"),
            "latest_date": latest_report.get("trade_date"),
            "validation_time": str(datetime.now().date())
        }
        
        logger.info(f"验证 {agent_id} 上次判断")
        return validation
    
    def mark_reports_validated(self, agent_id: str, trade_dates: List[str]) -> int:
        """
        标记报告为已验证
        
        复盘时调用，更新已验证报告的 is_validated 字段
        
        Args:
            agent_id: Agent 标识
            trade_dates: 已验证的交易日期列表
            
        Returns:
            更新的记录数
        """
        agent_type = self._extract_agent_type(agent_id)
        stm = self._get_stm(agent_type)
        
        updated = stm.update_validation_status(
            agent_type=agent_type,
            trade_dates=trade_dates,
            ts_code="INDEX"
        )
        
        logger.info(f"标记 {agent_id} 的 {len(trade_dates)} 条报告为已验证")
        return updated
    
    def cleanup_expired(self) -> int:
        """
        清理过期短期记忆
        
        Returns:
            删除的记录数
        """
        stm = self._get_stm("default")
        deleted = stm.cleanup_expired()
        
        logger.info(f"清理过期短期记忆: {deleted} 条")
        return deleted
    
    def get_config(self, agent_type: str = "default") -> Dict[str, Any]:
        """
        获取指定 Agent 类型的配置
        
        Args:
            agent_type: Agent 类型，默认为 "default"
            
        Returns:
            配置字典，包含 retention_days、distance_threshold、top_k 等参数
        """
        return self._get_agent_config(agent_type)
    
    # ==================== 内部方法 ====================
    
    def _get_agent_config(self, agent_type: str) -> Dict[str, Any]:
        """
        获取 Agent 配置
        
        优先级：Agent特定配置 > agent_config.yaml > 默认配置
        
        Args:
            agent_type: Agent 类型
            
        Returns:
            配置字典
        """
        default_config = {
            "retention_days": 7,
            "distance_threshold": 0.25,  # 🔧 修改为配置文件中的值
            "top_k": 5,                  # 🔧 修改为配置文件中的值
            "short_term_days": 3
        }
        
        try:
            from agents.agent_config import get_agent_config
            agent_config_manager = get_agent_config()
            
            # 先从 default_settings.memory 读取全局默认值
            default_settings = agent_config_manager._get_default_settings()
            memory_settings = default_settings.get('memory', {})
            if memory_settings:
                default_config["distance_threshold"] = memory_settings.get("distance_threshold", default_config["distance_threshold"])
                default_config["top_k"] = memory_settings.get("top_k", default_config["top_k"])
                default_config["embedding_model"] = memory_settings.get("embedding_model", "Qwen/Qwen3-Embedding-8B")
            
            # 再从 Agent 特定配置读取
            agent_type_map = {
                "MARKET": "market_analyst",
                "STOCK": "stock_analyst",
                "SECTOR": "sector_analyst",
            }
            config_key = agent_type_map.get(agent_type, agent_type.lower())
            settings = agent_config_manager.get_agent_settings(config_key)
            yaml_config = {
                "retention_days": settings.memory.retention_days,
                "short_term_days": settings.memory.short_term_days,
                "review_days": settings.memory.review_days,
            }
            default_config = {**default_config, **yaml_config}
            logger.debug(f"Agent {agent_type} 配置: distance_threshold={default_config.get('distance_threshold')}, top_k={default_config.get('top_k')}")
        except Exception as e:
            logger.debug(f"从 agent_config 加载配置失败，使用默认配置: {e}")
        
        agent_specific = self.agent_configs.get(agent_type, {})
        config = {**default_config, **agent_specific}
        
        return config
    
    def _get_stm(self, agent_type: str) -> ShortTermMemory:
        """
        获取短期记忆实例（带配置）
        
        Args:
            agent_type: Agent 类型
            
        Returns:
            ShortTermMemory 实例
        """
        if self.short_term_memory is None:
            config = self._get_agent_config(agent_type)
            self.short_term_memory = ShortTermMemory()  # 不传入 config，使用默认 session
            logger.debug(f"初始化短期记忆: retention_days={config.get('retention_days')}")
        
        return self.short_term_memory
    
    def _get_ltm(self, agent_type: str) -> LongTermMemory:
        """
        获取长期记忆实例（带配置）
        
        Args:
            agent_type: Agent 类型
            
        Returns:
            LongTermMemory 实例
        """
        if self.long_term_memory is None:
            config = self._get_agent_config(agent_type)
            self.long_term_memory = LongTermMemory(config=config)
            logger.debug(f"初始化长期记忆: distance_threshold={config.get('distance_threshold')}")
        
        return self.long_term_memory
    
    def _extract_agent_type(self, agent_id: str) -> str:
        """
        从 agent_id 中提取 agent_type
        
        Args:
            agent_id: Agent 标识（如 "MARKET_a3ffbcc9" 或 "MARKET_ANALYST_01"）
            
        Returns:
            提取的 agent_type（如 "MARKET"）
        """
        if not agent_id:
            return "UNKNOWN"
        parts = agent_id.split('_')
        if parts[0] in ["MARKET", "SECTOR", "STOCK", "RISK", "DECISION", "NEWS"]:
            return parts[0]
        return parts[0] if parts else agent_id


# ==================== 全局单例 ====================
_memory_manager_instance = None

def get_memory_manager(agent_configs: Dict[str, Any] = None) -> MemoryManager:
    """
    获取全局记忆管理器单例
    
    Args:
        agent_configs: Agent 配置字典
        
    Returns:
        MemoryManager 实例
    """
    global _memory_manager_instance
    if _memory_manager_instance is None:
        _memory_manager_instance = MemoryManager(agent_configs)
        logger.info("全局记忆管理器初始化完成")
    
    return _memory_manager_instance