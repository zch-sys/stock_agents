import sys
from pathlib import Path
import logging
from datetime import date
from typing import List, Dict, Any, Optional
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.llm.llm_client import LLMClient
from data.basic_data.database import get_session, KnowledgeMemory, init_db
from agents.agent_config import get_agent_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class LongTermMemory:
    """
    长期记忆系统
    
    职责：
    1. 将“复盘总结”转化为向量永久存储
    2. 根据当前情景，检索相似的历史经验 (RAG)
    """
    
    def __init__(self, session=None, llm_client=None, config: Dict[str, Any] = None):
        self.session = session if session else get_session()
        self.llm = llm_client if llm_client else LLMClient()
        self.config = config or {}
        logger.debug("LongTermMemory 初始化完成")

    def save_experience(
        self, 
        agent_type: str,
        insight_text: str, 
        event_type: str = "PATTERN",
        ts_code: str = "SYSTEM",
        trade_date: date = None
    ) -> bool:
        """
        保存一条经验到长期记忆库
        
        Args:
            agent_type: 来源 Agent (用于过滤检索)
            insight_text: 经验描述 (将被向量化)
            event_type: PATTERN(模式), MISTAKE(教训), RULE(规则)
            ts_code: 关联标的
            trade_date: 发生日期
        """
        if trade_date is None:
            trade_date = date.today()
            
        try:
            # 1. 调用 LLM Client 生成向量
            # embed 返回的是 List[List[float]]，取第一个
            logger.info(f"正在向量化经验 [{agent_type}]: {insight_text[:30]}...")
            embedding_vector = self.llm.embed(insight_text)
            
            if not embedding_vector:
                logger.error("Embedding 生成结果为空")
                return False
                
            # 2. 存入数据库
            new_memory = KnowledgeMemory(
                agent_type=agent_type,
                ts_code=ts_code,
                trade_date=trade_date,
                insight_text=insight_text,
                embedding=embedding_vector[0],
                event_type=event_type
            )
            
            self.session.add(new_memory)
            self.session.commit()
            
            logger.info(f"✅ 长期记忆已保存: [{event_type}]")
            return True
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"保存长期记忆失败: {e}", exc_info=True)
            return False

    def search_similar(
        self, 
        query_text: str, 
        agent_type: str = None,
        top_k: int = None,           # 改为 None
        distance_threshold: float = None  # 改为 None
    ) -> List[Dict[str, Any]]:
        # 优先级：参数 > config > 默认值
        threshold = distance_threshold or self.config.get("distance_threshold", 0.35)
        k = top_k or self.config.get("top_k", 3)
        logger.info(f"检索参数: top_k={k}, distance_threshold={threshold} (Agent: {agent_type or '通用'})")
        try:
            # 1. 生成查询向量
            query_vector = self.llm.embed(query_text)[0]

            sql_str = """
                SELECT 
                    id, agent_type, ts_code, trade_date, insight_text, event_type,
                    (embedding <=> :vec) as distance
                FROM knowledge_memory
                WHERE (embedding <=> :vec) < :threshold
            """ 
            # 如果指定了 Agent 类型，添加过滤
            params = {
                'vec': str(query_vector), 
                'threshold': threshold,  # ✅ 使用处理后的变量
                'limit': k               # ✅ 使用处理后的变量
            }
            
            if agent_type:
                sql_str += " AND agent_type = :agent_type"
                params['agent_type'] = agent_type
                
            sql_str += " ORDER BY distance ASC LIMIT :limit"
            
            # 执行查询
            sql = text(sql_str)
            results = self.session.execute(sql, params).fetchall()
            
            # 3. 格式化结果
            memories = []
            for row in results:
                memories.append({
                    "id": row.id,
                    "agent": row.agent_type,
                    "date": str(row.trade_date),
                    "insight": row.insight_text,
                    "type": row.event_type,
                    "similarity": 1 - row.distance # 将距离转化为相似度供参考
                })
            
            logger.info(f"🔍 检索到 {len(memories)} 条相关历史经验")
            return memories
            
        except Exception as e:
            logger.error(f"检索长期记忆失败: {e}", exc_info=True)
            # 如果向量索引报错，可能是第一次运行，返回空列表
            return []

    def get_config(self) -> Dict[str, Any]:
        config = self.config.copy() if self.config else {}
        try:
            agent_config = get_agent_config()
            default_settings = agent_config._get_default_settings()
            memory_settings = default_settings.get('memory', {})
            
            if "embedding_model" not in config:
                config["embedding_model"] = memory_settings.get('embedding_model', 'Qwen/Qwen3-Embedding-8B')
            if "distance_threshold" not in config:
                config["distance_threshold"] = memory_settings.get('distance_threshold', 0.35)
            if "top_k" not in config:
                config["top_k"] = memory_settings.get('top_k', 3)
        except Exception:
            config.setdefault("embedding_model", "Qwen/Qwen3-Embedding-8B")
            config.setdefault("distance_threshold", 0.35)
            config.setdefault("top_k", 3)
        
        return config

    def close(self):
        if self.session:
            self.session.close()
            logger.info("数据库连接已关闭")

# ==================== 单例 ====================
_ltm_instance = None

def get_ltm() -> LongTermMemory:
    global _ltm_instance
    if _ltm_instance is None:
        _ltm_instance = LongTermMemory()
    return _ltm_instance

# ==================== 测试代码 ====================
if __name__ == "__main__":
    # 核心修复：先初始化数据库！
    try:
        # 替换为你的数据库连接 URL
        DB_URL = 'postgresql://postgres:z2c2h088QQ@localhost:5432/stock_analysis'
        init_db(DB_URL)
        logger.info("✅ 数据库初始化成功")
        
        # 创建长期记忆实例
        ltm = get_ltm()
        
        # 1. 模拟复盘后存入一条教训
        print("\n--- 测试存入教训 ---")
        insight = "教训：当北向资金连续3天大幅流出，且跌破30日线时，不要轻易抄底，容易接飞刀。"
        save_result = ltm.save_experience(
            agent_type="RISK_ANALYST",
            insight_text=insight,
            event_type="MISTAKE",
            ts_code="INDEX"
        )
        print(f"保存结果: {'成功' if save_result else '失败'}")
        
        # 2. 模拟今日分析师检索经验
        print("\n--- 测试检索相似经验 ---")
        current_situation = "外资今天又流出50亿，指数快跌破30日线了，我在想是不是该买入了？"
        
        # 检索 RISK_ANALYST 的经验
        related = ltm.search_similar(
            query_text=current_situation,
            agent_type="RISK_ANALYST", 
            top_k=2
        )
        
        if related:
            print(">>> 检索到的历史经验：")
            for item in related:
                print(f"[{item['type']}] {item['insight']} (相似度: {item['similarity']:.2f})")
        else:
            print(">>> 暂无相关经验")
            
    except Exception as e:
        logger.error(f"❌ 测试过程出错: {e}", exc_info=True)
    finally:
        # 确保关闭数据库连接
        if 'ltm' in locals():
            ltm.close()