import sys
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, List
from pathlib import Path

# 设置项目根路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 导入数据库模型和初始化函数
# 注意：这里需要确保 database.py 中有 init_database 初始化函数
from data.basic_data.database import (
    get_session, 
    AnalysisReport,
    init_db  
)

logger = logging.getLogger(__name__)

class ShortTermMemory:
    """
    短期记忆系统
    
    设计理念：
    1. 默认窗口：只看昨天 (验证逻辑)
    2. 扩展窗口：看最近 N 天 (趋势分析、危机复盘)
    3. 自动过期清理：保留 7 天
    
    存储介质：PostgreSQL (AnalysisReport 表)
    """
    
    RETENTION_DAYS = 7  # 短期记忆有效期
    
    def __init__(self, session=None):
        """
        Args:
            session: SQLAlchemy Session。如果不传，自动获取。
        """
        self.session = session if session else get_session()
        logger.debug("ShortTermMemory 初始化完成")

    # ==================== 存储接口 ====================
    
    def save_report(
        self, 
        agent_type: str, 
        report_content: Dict[str, Any], 
        ts_code: str = "INDEX",
        trade_date: date = None
    ) -> AnalysisReport:
        """
        保存分析报告到短期记忆
        
        Args:
            agent_type: Agent 类型 (如 'MARKET_ANALYST', 'STOCK_ANALYST')
            report_content: 报告内容字典（包含 summary 和 confidence 字段）
            ts_code: 标的代码
            trade_date: 日期 (默认今天)
        """
        if trade_date is None:
            trade_date = date.today()
            
        try:
            # 检查是否已存在，存在则更新 (防止重复运行产生重复记录)
            existing = self.session.query(AnalysisReport).filter(
                AnalysisReport.agent_type == agent_type,
                AnalysisReport.ts_code == ts_code,
                AnalysisReport.trade_date == trade_date
            ).first()
            
            if existing:
                logger.info(f"更新已存在的记忆: [{agent_type}] {trade_date}")
                existing.report_json = report_content
                existing.created_at = datetime.now() # 刷新时间
            else:
                new_report = AnalysisReport(
                    agent_type=agent_type,
                    ts_code=ts_code,
                    trade_date=trade_date,
                    report_json=report_content
                )
                self.session.add(new_report)
                
            self.session.commit()
            logger.info(f"短期记忆保存成功: [{agent_type}] {trade_date} {ts_code}")
            return existing if existing else new_report
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"保存短期记忆失败: {e}")
            raise

    # ==================== 核心检索接口 ====================

    def get_latest_report(
        self, 
        agent_type: str, 
        ts_code: str = "INDEX",
        before_date: date = None
    ) -> Optional[Dict[str, Any]]:
        """
        获取最近一份报告
        
        Args:
            agent_type: Agent 类型
            ts_code: 标的代码
            before_date: 在此日期之前查找（默认今天之前）
            
        Returns:
            单个报告字典，没有则返回 None
        """
        if before_date is None:
            before_date = date.today()
            
        logger.info(f"获取最近报告: [{agent_type}] {ts_code} (before {before_date})")
        
        try:
            record = self.session.query(AnalysisReport).filter(
                AnalysisReport.agent_type == agent_type,
                AnalysisReport.ts_code == ts_code,
                AnalysisReport.trade_date < before_date
            ).order_by(
                AnalysisReport.trade_date.desc()
            ).first()
            
            if not record:
                return None
            
            report_json = record.report_json or {}
            return {
                "trade_date": str(record.trade_date),
                "summary": report_json.get("summary", ""),
                "content": report_json,
                "score": report_json.get("confidence")
            }
            
        except Exception as e:
            logger.error(f"获取最近报告失败: {e}")
            return None

    def get_recent_reports(
        self, 
        agent_type: str, 
        ts_code: str, 
        limit: int = 3,
        reference_date: date = None
    ) -> List[Dict[str, Any]]:
        """
        获取最近 N 份报告（不连续日期）
        
        相比旧版按"日期范围"查询，新版直接取最近的N份报告，
        解决非交易日/周末导致的断层问题。
        
        Args:
            agent_type: Agent 类型
            ts_code: 标的代码
            limit: 要获取的报告数量（默认3份）
            reference_date: 参考日期（查找此日期之前的报告，默认今天）
            
        Returns:
            报告列表，按时间正序排列 (旧 -> 新)，方便 LLM 理解时间线
        """
        if reference_date is None:
            reference_date = date.today()
        
        logger.info(f"获取最近 {limit} 份报告: [{agent_type}] {ts_code} (before {reference_date})")
        
        try:
            # 直接取 reference_date 及之前的最近 limit 份报告
            records = self.session.query(AnalysisReport).filter(
                AnalysisReport.agent_type == agent_type,
                AnalysisReport.ts_code == ts_code,
                AnalysisReport.trade_date < reference_date
            ).order_by(
                AnalysisReport.trade_date.desc()  # 倒序取最近的
            ).limit(limit).all()
            
            # 转换为字典列表，按日期正序排列（旧→新）
            results = []
            for r in reversed(records):  # 反转为正序
                report_json = r.report_json or {}
                results.append({
                    "trade_date": str(r.trade_date),
                    "summary": report_json.get("summary", ""),
                    "content": report_json,
                    "score": report_json.get("confidence")
                })
            
            logger.info(f"检索到 {len(results)} 份报告: {[r['trade_date'] for r in results]}")
            return results
            
        except Exception as e:
            logger.error(f"检索报告失败: {e}")
            return []

    # ==================== 维护接口 ====================
    
    def cleanup_expired(self) -> int:
        """
        清理过期记忆
        
        Returns:
            删除的记录数
        """
        expired_date = date.today() - timedelta(days=self.RETENTION_DAYS)
        
        try:
            deleted = self.session.query(AnalysisReport).filter(
                AnalysisReport.trade_date < expired_date
            ).delete()
            
            self.session.commit()
            logger.info(f"清理过期短期记忆: {deleted} 条")
            return deleted
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"清理失败: {e}")
            return 0

    def close(self):
        """关闭数据库连接"""
        if self.session:
            self.session.close()

# ==================== 全局单例 ====================

_stm_instance = None

def get_stm() -> ShortTermMemory:
    global _stm_instance
    if _stm_instance is None:
        _stm_instance = ShortTermMemory()
    return _stm_instance

