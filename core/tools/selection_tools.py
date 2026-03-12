"""
选股工具集

提供选股分析师使用的所有工具，包括：
- ReadAnalysisReportTool: 读取大盘/板块分析师报告
- QueryStockPoolTool: 查询股票池
- QueryStocksBySectorTool: 按板块查询股票
- GetStockDetailTool: 获取股票详情
- MatchSectorNameTool: 板块名称匹配
- RecordThoughtTool: 记录思考过程
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import date, datetime
from sqlalchemy import func

from .base_tool import BaseTool, ToolResult, ToolParameter
from core.memory.short_memory import ShortTermMemory

logger = logging.getLogger(__name__)


def _ensure_db_initialized():
    """确保数据库已初始化（模块级函数，供所有工具共享）"""
    from data.basic_data.database import init_db, get_session
    from data.basic_data.config_manager import load_config
    
    # 尝试获取 session，如果失败则初始化
    try:
        get_session()
    except RuntimeError:
        config = load_config()
        db_url = config.get('data_collector', {}).get('db_url')
        if db_url:
            init_db(db_url)
            logger.info("数据库初始化完成")
        else:
            raise RuntimeError("无法获取数据库配置")


class ReadAnalysisReportTool(BaseTool):
    """
    读取大盘/板块分析师的短期记忆（只读）
    
    功能：
    - 从 AnalysisReport 表读取最近 N 天的分析报告
    - 支持 MARKET 和 SECTOR 两种类型
    """
    
    name = "read_analysis_report"
    description = "读取大盘或板块分析师的最近分析报告"
    version = "1.0.0"
    timeout = 30.0
    
    def _setup_parameters(self) -> None:
        self._parameters = {
            "report_type": ToolParameter(
                name="report_type",
                param_type="string",
                description="报告类型：market=大盘报告，sector=板块报告",
                required=True,
                enum=["market", "sector"]
            ),
            "days": ToolParameter(
                name="days",
                param_type="integer",
                description="读取最近N天的报告",
                required=False,
                default=3
            )
        }
    
    def execute(self, report_type: str, days: int = 3) -> ToolResult:
        """执行工具"""
        session = None
        try:
            agent_type = "MARKET" if report_type.lower() == "market" else "SECTOR"
            
            from data.basic_data.database import get_session, AnalysisReport
            import json
            
            _ensure_db_initialized()
            session = get_session()
            
            # 获取所有该类型的报告
            all_reports = session.query(AnalysisReport).filter(
                AnalysisReport.agent_type == agent_type
            ).order_by(
                AnalysisReport.trade_date.desc()
            ).all()
            
            if not all_reports:
                return ToolResult.failure(f"未找到 {agent_type} 类型的分析报告")
            
            # 分组并按日期排序，取最近的days天
            reports_by_date = {}
            for report in all_reports:
                trade_date = report.trade_date
                if trade_date not in reports_by_date:
                    reports_by_date[trade_date] = []
                reports_by_date[trade_date].append(report)
            
            # 获取最近的dates天（按日期降序）
            sorted_dates = sorted(reports_by_date.keys(), reverse=True)
            recent_dates = sorted_dates[:days]
            
            simplified = []
            for trade_date in recent_dates:
                for report in reports_by_date[trade_date]:
                    report_json = report.report_json
                    if isinstance(report_json, str):
                        try:
                            content = json.loads(report_json)
                        except:
                            content = {}
                    else:
                        content = report_json or {}
                    
                    full_content = content
                    
                    # 对于大盘报告，特别处理关注板块
                    focused_sectors = []
                    if agent_type == "MARKET":
                        focused_sectors = full_content.get('focused_sectors', [])
                        if not focused_sectors:
                            focused_sectors = full_content.get('sector_focus', [])
                        if not focused_sectors and isinstance(full_content.get('data'), dict):
                            focused_sectors = full_content['data'].get('sector_focus', [])
                    
                    # 获取市场观点
                    market_view = ""
                    if agent_type == "MARKET":
                        market_view = full_content.get('market_view', '')
                        if not market_view:
                            market_view = full_content.get('market_state', '')
                        if not market_view:
                            market_view = full_content.get('summary', '')
                        if not market_view and isinstance(full_content.get('data'), dict):
                            market_view = full_content['data'].get('market_view', '')
                    
                    confidence = full_content.get('confidence', 50)
                    index_predictions = full_content.get('index_predictions', [])
                    if not index_predictions and isinstance(full_content.get('data'), dict):
                        index_predictions = full_content['data'].get('index_predictions', [])
                    
                    # 板块报告专用字段
                    sector_hot_list = []
                    sector_capital_list = []
                    sector_risk_list = []
                    sector_predictions = []
                    
                    if agent_type == "SECTOR":
                        if isinstance(full_content.get('hot_sectors'), list):
                            for sector in full_content['hot_sectors']:
                                if isinstance(sector, dict) and sector.get('sector_name'):
                                    sector_hot_list.append(sector['sector_name'])
                        
                        if isinstance(full_content.get('capital_flow_sectors'), list):
                            for sector in full_content['capital_flow_sectors']:
                                if isinstance(sector, dict) and sector.get('sector_name'):
                                    sector_capital_list.append(sector['sector_name'])
                        
                        if isinstance(full_content.get('risk_sectors'), list):
                            for sector in full_content['risk_sectors']:
                                if isinstance(sector, dict) and sector.get('sector_name'):
                                    sector_risk_list.append(sector['sector_name'])
                        
                        if isinstance(full_content.get('hot_analysis'), dict):
                            predicted = full_content['hot_analysis'].get('predicted_hot_sectors', [])
                            if isinstance(predicted, list):
                                sector_predictions = predicted
                    
                    simplified.append({
                        "trade_date": str(trade_date),
                        "ts_code": report.ts_code,
                        "market_view": market_view,
                        "index_predictions": index_predictions,
                        "focused_sectors": focused_sectors,
                        "confidence": confidence,
                        "hot_sectors": sector_hot_list,
                        "capital_flow_sectors": sector_capital_list,
                        "risk_sectors": sector_risk_list,
                        "predicted_hot_sectors": sector_predictions,
                        "full_content": full_content
                    })
            
            if not simplified:
                return ToolResult.failure(f"未找到 {agent_type} 类型的最近 {days} 天有效报告")
            
            return ToolResult.success(data={
                "report_type": report_type,
                "count": len(simplified),
                "reports": simplified
            })
            
        except Exception as e:
            logger.error(f"读取分析报告失败: {e}", exc_info=True)
            return ToolResult.failure(f"读取分析报告失败: {str(e)}")
        finally:
            if session:
                session.close()


class QueryStockPoolTool(BaseTool):
    """
    查询股票池
    
    功能：
    - 从 StockPool 表查询各类型的候选股票
    - 按 model_rank 排序，返回前 N 名
    - 默认每个池返回前5名（共20支）
    """
    
    name = "query_stock_pool"
    description = "从股票池查询因子排名靠前的候选股票，默认每个池返回前5名"
    version = "1.0.0"
    timeout = 30.0
    
    def _setup_parameters(self) -> None:
        self._parameters = {
            "pool_types": ToolParameter(
                name="pool_types",
                param_type="array",
                description="股票池类型列表：SHORT/MID/LONG/WHITE_HORSE",
                required=True,
                items={"type": "string"}
            ),
            "top_n": ToolParameter(
                name="top_n",
                param_type="integer",
                description="每个类型返回前N名",
                required=False,
                default=5
            )
        }
    
    def execute(self, pool_types: List[str], top_n: int = 5) -> ToolResult:
        """执行工具"""
        session = None
        try:
            from data.basic_data.database import get_session, StockPool
            
            _ensure_db_initialized()
            session = get_session()
            results = {}
            
            valid_types = {"SHORT", "MID", "LONG", "WHITE_HORSE"}
            
            for pool_type in pool_types:
                if pool_type.upper() not in valid_types:
                    continue
                
                stocks = session.query(StockPool).filter(
                    StockPool.pool_type == pool_type.upper()
                ).order_by(
                    StockPool.model_rank.asc()
                ).limit(top_n).all()
                
                stock_list = []
                for s in stocks:
                    stock_list.append({
                        "ts_code": s.ts_code,
                        "model_rank": s.model_rank,
                        "pool_type": s.pool_type
                    })
                
                results[pool_type] = stock_list
            
            return ToolResult.success(data={
                "pool_types": pool_types,
                "top_n": top_n,
                "results": results,
                "total_count": sum(len(v) for v in results.values())
            })
            
        except Exception as e:
            logger.error(f"查询股票池失败: {e}", exc_info=True)
            return ToolResult.failure(f"查询股票池失败: {str(e)}")
        finally:
            if session:
                session.close()


class QueryStocksBySectorTool(BaseTool):
    """
    按板块查询股票
    
    功能：
    - 根据板块代码/名称查询成分股
    - 与股票池关联，只返回在池中的股票
    - 自动去重
    """
    
    name = "query_stocks_by_sector"
    description = "根据板块代码或名称查询股票池中的成分股"
    version = "2.0.0"
    timeout = 30.0
    
    def _setup_parameters(self) -> None:
        self._parameters = {
            "sector_codes": ToolParameter(
                name="sector_codes",
                param_type="array",
                description="板块代码列表",
                required=False,
                items={"type": "string"}
            ),
            "sector_names": ToolParameter(
                name="sector_names",
                param_type="array",
                description="板块名称列表（自然语言）",
                required=False,
                items={"type": "string"}
            )
        }
    
    def execute(
        self, 
        sector_codes: List[str] = None, 
        sector_names: List[str] = None
    ) -> ToolResult:
        """执行工具"""
        session = None
        try:
            from data.basic_data.database import get_session, StockPool, SectorData, StockDetail
            
            _ensure_db_initialized()
            session = get_session()
            results = []
            seen = set()
            
            # 如果传入的是板块名称，先转换为代码
            if sector_names and not sector_codes:
                from .sector_tools import SectorMatchTool
                matcher = SectorMatchTool()
                match_result = matcher.execute(predicted_names=sector_names)
                
                if not match_result.is_success:
                    return ToolResult.failure(f"板块名称匹配失败: {match_result.error}")
                
                sector_codes = []
                for mapping in match_result.data.get("mapping", []):
                    if mapping.get("matched") and mapping.get("candidates"):
                        sector_code = mapping["candidates"][0].get("sector_code")
                        if sector_code:
                            sector_codes.append(sector_code)
            
            if not sector_codes:
                return ToolResult.success(data={
                    "sector_codes": [],
                    "count": 0,
                    "stocks": []
                })
            
            logger.info(f"开始查询板块股票，板块代码: {sector_codes}")
            
            for sector_code in sector_codes:
                # 获取板块信息
                sector_info = session.query(SectorData).filter(
                    SectorData.sector_code == sector_code
                ).order_by(
                    SectorData.trade_date.desc()
                ).first()
                
                if not sector_info:
                    logger.warning(f"板块代码 {sector_code} 未找到")
                    continue
                
                sector_name = sector_info.sector_name
                constituent_stocks = sector_info.constituent_stocks
                
                # 解析成分股列表
                ts_codes_in_sector = []
                if isinstance(constituent_stocks, list):
                    for stock in constituent_stocks:
                        if isinstance(stock, dict) and "ts_code" in stock:
                            ts_codes_in_sector.append(stock["ts_code"])
                        elif isinstance(stock, str):
                            ts_codes_in_sector.append(stock)
                elif isinstance(constituent_stocks, dict):
                    for key, value in constituent_stocks.items():
                        if isinstance(value, dict) and "ts_code" in value:
                            ts_codes_in_sector.append(value["ts_code"])
                        elif isinstance(value, str):
                            ts_codes_in_sector.append(value)
                
                logger.info(f"板块 {sector_name}({sector_code}) 有 {len(ts_codes_in_sector)} 个成分股")
                
                if not ts_codes_in_sector:
                    continue
                
                # 与股票池关联
                pool_stocks = session.query(StockPool).filter(
                    StockPool.ts_code.in_(ts_codes_in_sector)
                ).all()
                
                logger.info(f"板块 {sector_name} 在股票池中找到 {len(pool_stocks)} 支股票")
                
                for s in pool_stocks:
                    if s.ts_code in seen:
                        continue
                    seen.add(s.ts_code)
                    results.append({
                        "ts_code": s.ts_code,
                        "name": "",
                        "sector_code": sector_code,
                        "sector_name": sector_name,
                        "model_rank": s.model_rank,
                        "pool_type": s.pool_type
                    })
            
            # 获取股票名称
            if results:
                ts_codes = [r["ts_code"] for r in results]
                latest_date = session.query(func.max(StockDetail.trade_date)).scalar()
                if latest_date:
                    details = session.query(StockDetail).filter(
                        StockDetail.ts_code.in_(ts_codes),
                        StockDetail.trade_date == latest_date
                    ).all()
                    
                    detail_map = {d.ts_code: d for d in details}
                    
                    for result in results:
                        detail = detail_map.get(result["ts_code"])
                        if detail:
                            result["name"] = detail.name
                            result["industry"] = detail.industry
                            result["total_mv"] = detail.total_mv
                            result["pe"] = detail.pe
            
            results.sort(key=lambda x: x["model_rank"] or 999)
            
            logger.info(f"查询完成，找到 {len(results)} 支股票")
            
            return ToolResult.success(data={
                "sector_codes": sector_codes,
                "count": len(results),
                "stocks": results
            })
            
        except Exception as e:
            logger.error(f"按板块查询股票失败: {e}", exc_info=True)
            return ToolResult.failure(f"按板块查询股票失败: {str(e)}")
        finally:
            if session:
                session.close()


class GetStockDetailTool(BaseTool):
    """
    获取股票详情（增强版）
    
    功能：
    - 获取股票的基本信息（名称、板块、行业、市值等）
    - 获取技术指标（MA、MACD、RSI、布林带等）
    - 默认获取3日历史价格数据
    """
    
    name = "get_stock_detail"
    description = "获取股票的详细信息，包括基本面、技术指标、3日价格数据。"
    version = "2.1.0"
    timeout = 60.0
    
    DEFAULT_DAYS = 3
    
    def _setup_parameters(self) -> None:
        self._parameters = {
            "ts_codes": ToolParameter(
                name="ts_codes",
                param_type="array",
                description="股票代码列表",
                required=True,
                items={"type": "string"}
            ),
            "trade_date": ToolParameter(
                name="trade_date",
                param_type="string",
                description="交易日期，用于查询当日市值等，默认当天",
                required=False
            )
        }
    
    def execute(
        self, 
        ts_codes: List[str], 
        trade_date: str = None
    ) -> ToolResult:
        """执行工具 - 固定获取3日价格数据"""
        session = None
        try:
            from data.basic_data.database import get_session, StockDetail
            
            _ensure_db_initialized()
            session = get_session()
            results = []
            
            if trade_date:
                query_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
            else:
                query_date = date.today()
            
            for ts_code in ts_codes:
                # 查询最近3天的数据
                details = session.query(StockDetail).filter(
                    StockDetail.ts_code == ts_code
                ).order_by(
                    StockDetail.trade_date.desc()
                ).limit(self.DEFAULT_DAYS).all()
                
                if not details:
                    continue
                
                latest = details[0]
                stock_info = {
                    "ts_code": ts_code,
                    "name": latest.name,
                    "industry": latest.industry,
                    "market": latest.market,
                    "list_date": str(latest.list_date) if latest.list_date else None,
                    "total_mv": latest.total_mv,
                    "circ_mv": latest.circ_mv,
                    "pe": latest.pe,
                    "pb": latest.pb,
                    "ps": latest.ps,
                    "eps": latest.eps,
                    "bvps": latest.bvps,
                    "dv_ttm": latest.dv_ttm,
                    "revenue_yoy": latest.revenue_yoy,
                    "profit_yoy": latest.profit_yoy,
                    "debt_to_assets": latest.debt_to_assets,
                    "current_ratio": latest.current_ratio,
                }
                
                # 技术指标
                stock_info["technical"] = {
                    "ma5": latest.ma5,
                    "ma10": latest.ma10,
                    "ma20": latest.ma20,
                    "ma60": latest.ma60,
                    "macd": latest.macd,
                    "macd_signal": latest.macd_signal,
                    "macd_hist": latest.macd_hist,
                    "rsi6": latest.rsi6,
                    "rsi12": latest.rsi12,
                    "rsi24": latest.rsi24,
                    "boll_upper": latest.boll_upper,
                    "boll_middle": latest.boll_middle,
                    "boll_lower": latest.boll_lower,
                    "volume_ma5": latest.volume_ma5,
                    "volume_ma10": latest.volume_ma10,
                }
                
                # 3日历史价格
                price_history = []
                for d in details:
                    price_history.append({
                        "trade_date": str(d.trade_date),
                        "open": d.open,
                        "high": d.high,
                        "low": d.low,
                        "close": d.close,
                        "pct_chg": d.pct_chg,
                        "vol": d.vol,
                        "amount": d.amount,
                        "pre_close": d.pre_close,
                    })
                stock_info["price_history"] = price_history
                
                results.append(stock_info)
            
            return ToolResult.success(data={
                "trade_date": str(query_date),
                "days": self.DEFAULT_DAYS,
                "count": len(results),
                "stocks": results
            })
            
        except Exception as e:
            logger.error(f"获取股票详情失败: {e}", exc_info=True)
            return ToolResult.failure(f"获取股票详情失败: {str(e)}")
        finally:
            if session:
                session.close()


class MatchSectorNameTool(BaseTool):
    """
    板块名称匹配
    
    功能：
    - 将自然语言板块名映射到数据库标准板块名
    """
    
    name = "match_sector_name"
    description = "将自然语言板块名映射到数据库标准板块代码"
    version = "1.0.0"
    timeout = 60.0
    
    def _setup_parameters(self) -> None:
        self._parameters = {
            "sector_names": ToolParameter(
                name="sector_names",
                param_type="array",
                description="自然语言板块名列表",
                required=True,
                items={"type": "string"}
            )
        }
    
    def execute(self, sector_names: List[str]) -> ToolResult:
        """执行工具"""
        try:
            from .sector_tools import SectorMatchTool
            
            matcher = SectorMatchTool()
            match_result = matcher.execute(predicted_names=sector_names)
            
            if not match_result.is_success:
                return match_result
            
            results = []
            mapping = match_result.data.get("mapping", [])
            
            for m in mapping:
                if m.get("matched"):
                    results.append({
                        "input_name": m["raw"],
                        "matched_code": m["candidates"][0]["sector_code"] if m["candidates"] else "",
                        "matched_name": m["matched"],
                        "confidence": m["confidence"]
                    })
            
            return ToolResult.success(data={
                "count": len(results),
                "matches": results
            })
            
        except Exception as e:
            logger.error(f"板块名称匹配失败: {e}", exc_info=True)
            return ToolResult.failure(f"板块名称匹配失败: {str(e)}")


class RecordThoughtTool(BaseTool):
    """
    记录思考过程
    
    功能：
    - 将 Agent 的思考过程记录到工作记忆
    """
    
    name = "record_thought"
    description = "记录分析过程中的思考和判断"
    version = "1.0.0"
    timeout = 10.0
    
    def _setup_parameters(self) -> None:
        self._parameters = {
            "thought": ToolParameter(
                name="thought",
                param_type="string",
                description="思考内容",
                required=True
            ),
            "category": ToolParameter(
                name="category",
                param_type="string",
                description="思考类别",
                required=False,
                default="analysis",
                enum=["analysis", "decision", "concern"]
            )
        }
    
    def execute(self, thought: str, category: str = "analysis") -> ToolResult:
        """执行工具"""
        return ToolResult.success(data={
            "thought": thought,
            "category": category,
            "recorded": True
        })


def register_selection_tools(registry) -> None:
    """
    注册所有选股工具
    
    Args:
        registry: ToolRegistry实例
    """
    tools = [
        ReadAnalysisReportTool,
        QueryStockPoolTool,
        QueryStocksBySectorTool,
        GetStockDetailTool,
        MatchSectorNameTool,
        RecordThoughtTool
    ]
    
    for tool_class in tools:
        try:
            registry.register(tool_class)
            logger.info(f"[OK] {tool_class.name} 已注册")
        except Exception as e:
            logger.warning(f"[WARN] {tool_class.name} 注册失败: {e}")
    
    logger.info(f"选股工具注册完成，共 {len(tools)} 个")