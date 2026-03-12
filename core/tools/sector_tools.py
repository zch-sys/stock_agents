"""
板块工具模块

本模块提供板块分析相关的工具，包括：
- SectorMatchTool: 板块名称语义匹配工具（基于嵌入向量）
"""

import logging
from typing import Dict, List, Any, Optional
import numpy as np
from datetime import datetime

from .base_tool import BaseTool, ToolResult, ToolParameter

logger = logging.getLogger(__name__)


class SectorMatchTool(BaseTool):
    """
    板块名称语义匹配工具
    
    功能：
    1. 使用嵌入向量计算板块名称的语义相似度
    2. 将LLM预测的板块名称（如"AI"）匹配到数据库标准名称（如"人工智能"）
    3. 支持批量匹配，返回TOP 3候选
    
    原理：
    - 预计算所有板块名称的嵌入向量并缓存
    - 预测时计算查询向量，通过余弦距离找最相似的板块
    - 语义匹配：AI ≈ 人工智能，芯片 ≈ 半导体
    
    使用示例：
        tool = SectorMatchTool(llm_client=llm_client)
        result = tool.execute(
            predicted_names=["AI", "芯片", "新能源汽车"],
            trade_date="2026-03-02"
        )
        # 返回: {"matched": ["人工智能", "半导体", "新能源汽车"], "mapping": [...]}
    """
    
    name = "sector_match"
    description = "使用语义相似度匹配板块名称，将预测名称标准化为数据库中的准确名称"
    version = "1.0.0"
    timeout = 60.0  # 嵌入计算可能需要较长时间
    
    # 类级别缓存（跨实例共享）
    _sector_embeddings_cache: Dict[str, List[Dict]] = {}
    _cache_date: Optional[str] = None
    
    def __init__(self, llm_client=None):
        """
        初始化板块匹配工具
        
        Args:
            llm_client: LLM客户端实例，用于生成嵌入向量（可选，延迟初始化）
        """
        super().__init__()
        self._llm_client = llm_client
        self._own_llm_client = False  # 标记是否自己创建的客户端
    
    def _ensure_llm_client(self):
        """确保LLM客户端可用（延迟初始化）"""
        if self._llm_client is None:
            try:
                from core.llm.llm_client import LLMClient
                self._llm_client = LLMClient()
                self._own_llm_client = True
                logger.debug("SectorMatchTool 延迟初始化 LLM 客户端")
            except Exception as e:
                logger.error(f"无法初始化 LLM 客户端: {e}")
                return False
        return True
    
    def _setup_parameters(self) -> None:
        """设置参数定义"""
        self._parameters = {
            "predicted_names": ToolParameter(
                name="predicted_names",
                param_type="array",
                description="LLM预测的板块名称列表，如 ['AI', '芯片']",
                required=True,
                items={"type": "string"}
            ),
            "trade_date": ToolParameter(
                name="trade_date",
                param_type="string",
                description="交易日期，格式 YYYY-MM-DD，默认使用最新日期",
                required=False
            ),
            "top_k": ToolParameter(
                name="top_k",
                param_type="integer",
                description="返回的候选数量，默认3",
                required=False,
                default=3
            ),
            "distance_threshold": ToolParameter(
                name="distance_threshold",
                param_type="number",
                description="余弦距离阈值，超过此值不返回，默认0.4",
                required=False,
                default=0.4
            )
        }
    
    def execute(
        self,
        predicted_names: List[str],
        trade_date: str = None,
        top_k: int = 3,
        distance_threshold: float = 0.4
    ) -> ToolResult:
        """
        执行板块名称匹配
        
        Args:
            predicted_names: LLM预测的板块名称列表
            trade_date: 交易日期
            top_k: 返回的候选数量
            distance_threshold: 余弦距离阈值
            
        Returns:
            ToolResult包含:
            - matched: 匹配成功的结果列表 ["人工智能", "半导体"]
            - mapping: 详细映射关系
        """
        try:
            # 0. 确保LLM客户端可用
            if not self._ensure_llm_client():
                return ToolResult.failure("LLM客户端初始化失败")
            
            # 1. 获取板块列表及其嵌入向量
            sectors = self._get_sectors_with_embeddings(trade_date)
            
            if not sectors:
                return ToolResult.failure("无法获取板块数据或板块列表为空")
            
            logger.info(f"正在为 {len(predicted_names)} 个预测名称生成嵌入向量...")
            query_vectors = self._llm_client.embed(predicted_names)
            
            # 3. 对每个预测名称进行匹配
            results = []
            for i, raw_name in enumerate(predicted_names):
                query_vec = query_vectors[i]
                
                # 计算与所有板块的余弦距离
                matches = []
                for sector in sectors:
                    distance = self._cosine_distance(query_vec, sector["embedding"])
                    if distance < distance_threshold:
                        matches.append({
                            "sector_code": sector["sector_code"],
                            "sector_name": sector["sector_name"],
                            "distance": round(distance, 4),
                            "similarity": round(1 - distance, 4)
                        })
                
                # 按距离排序，取TOP K
                matches = sorted(matches, key=lambda x: x["distance"])[:top_k]
                
                # 构建结果
                if matches:
                    best = matches[0]
                    confidence = "high" if best["distance"] < 0.15 else ("medium" if best["distance"] < 0.25 else "low")
                    results.append({
                        "raw": raw_name,
                        "matched": best["sector_name"],
                        "confidence": confidence,
                        "candidates": matches
                    })
                else:
                    results.append({
                        "raw": raw_name,
                        "matched": None,
                        "confidence": "none",
                        "candidates": []
                    })
            
            # 4. 汇总结果
            matched_names = [r["matched"] for r in results if r["matched"]]
            
            logger.info(f"板块匹配完成: {len(matched_names)}/{len(predicted_names)} 匹配成功")
            
            return ToolResult.success(data={
                "matched": matched_names,
                "mapping": results,
                "total_sectors": len(sectors),
                "query_date": trade_date or self._cache_date
            })
            
        except Exception as e:
            logger.error(f"板块匹配失败: {e}", exc_info=True)
            return ToolResult.failure(f"板块匹配失败: {str(e)}")
    
    def _get_sectors_with_embeddings(self, trade_date: str = None) -> List[Dict]:
        """
        获取板块列表及其预计算嵌入向量
        
        使用类级别缓存避免重复计算
        
        Args:
            trade_date: 交易日期
            
        Returns:
            [{"sector_code": "BK0001", "sector_name": "人工智能", "embedding": [...]}, ...]
        """
        # 检查缓存
        if SectorMatchTool._sector_embeddings_cache and SectorMatchTool._cache_date == trade_date:
            logger.debug(f"使用缓存的板块嵌入向量 ({len(SectorMatchTool._sector_embeddings_cache)} 个)")
            return SectorMatchTool._sector_embeddings_cache
        
        # 从数据库获取板块
        try:
            from data.basic_data.database import get_session, SectorData
            
            session = get_session()
            
            # 确定查询日期
            if trade_date:
                query_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
            else:
                # 获取最新交易日期
                latest = session.query(SectorData.trade_date).order_by(
                    SectorData.trade_date.desc()
                ).first()
                if not latest:
                    logger.warning("数据库中没有板块数据")
                    return []
                query_date = latest[0]
            
            # 查询板块
            sectors = session.query(
                SectorData.sector_code,
                SectorData.sector_name
            ).filter(
                SectorData.trade_date == query_date
            ).all()
            
            if not sectors:
                logger.warning(f"日期 {query_date} 没有板块数据")
                return []
            
            logger.info(f"从数据库获取到 {len(sectors)} 个板块，开始生成嵌入向量...")
            
            # 批量计算向量（一次API调用）
            if not self._llm_client:
                logger.error("LLM客户端未初始化")
                return []
            
            names = [s.sector_name for s in sectors]
            embeddings = self._llm_client.embed(names)
            
            # 构建结果并缓存
            SectorMatchTool._sector_embeddings_cache = [
                {
                    "sector_code": s.sector_code,
                    "sector_name": s.sector_name,
                    "embedding": embeddings[i]
                }
                for i, s in enumerate(sectors)
            ]
            SectorMatchTool._cache_date = str(query_date)
            
            logger.info(f"板块嵌入向量已缓存 ({len(SectorMatchTool._sector_embeddings_cache)} 个)")
            
            return SectorMatchTool._sector_embeddings_cache
            
        except Exception as e:
            logger.error(f"获取板块数据失败: {e}", exc_info=True)
            return []
    
    def _cosine_distance(self, vec1: List[float], vec2: List[float]) -> float:
        """
        计算余弦距离
        
        余弦距离 = 1 - 余弦相似度
        pgvector 的 <=> 操作符等价
        
        Args:
            vec1: 向量1
            vec2: 向量2
            
        Returns:
            余弦距离 (0-2之间，0表示完全相同)
        """
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        
        dot_product = np.dot(v1, v2)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        
        if norm1 == 0 or norm2 == 0:
            return 1.0
        
        cosine_similarity = dot_product / (norm1 * norm2)
        return 1 - cosine_similarity
    
    @classmethod
    def clear_cache(cls):
        """清除缓存"""
        cls._sector_embeddings_cache = {}
        cls._cache_date = None
        logger.info("板块嵌入向量缓存已清除")


def register_sector_tools(registry) -> None:
    """
    注册板块相关工具到工具注册中心
    
    Args:
        registry: ToolRegistry实例
    """
    try:
        # 直接注册类（不需要预先创建实例）
        # LLM客户端会在 execute 时延迟初始化
        registry.register(SectorMatchTool)
        logger.info("✅ SectorMatchTool 已注册")
    except Exception as e:
        logger.warning(f"⚠️ SectorMatchTool 注册失败: {e}")
