"""
板块分析师Agent

SectorAnalyst: 分析板块轮动，识别热点和风险，输出SectorReport

支持两种分析模式：
- NORMAL: 正常分析模式，筛选重点板块，LLM聚焦分析
- REVIEW: 复盘模式，聚合近期报告，经验提取存储到长期记忆
"""

import json
import re
import logging
from datetime import date, timedelta, datetime
from typing import Dict, Any, Optional, List, Union
from enum import Enum

from agents.base.base_agent import BaseAgent, AgentConfig, AgentResult, AgentType
from agents.base.agent_registry import AgentRegistry
from core.memory.memory_manager import get_memory_manager
from core.tools.tool_registry import get_tool_registry
from data.schemas.sector_schema import (
    SectorReport, MarketBreadth,
    SectorHotAnalysis, SectorCapitalAnalysis, SectorRiskAnalysis,
    SectorRotation, HotSectorDetail,
)
from agents.analysis.sector.sector_prompts import (
    SYSTEM_PROMPT_SECTOR_ANALYST,
    build_sector_analysis_prompt,
    build_sector_review_prompt,
)


logger = logging.getLogger(__name__)


class AnalysisMode(Enum):
    """分析模式枚举"""
    NORMAL = "normal"
    REVIEW = "review"


@AgentRegistry.register
class SectorAnalyst(BaseAgent):
    """
    板块分析师
    
    分析A股板块轮动，识别热点和风险，输出板块分析报告。
    
    设计理念：
    - 筛选+聚焦：先用规则筛选重点板块，再让LLM聚焦分析
    - 多维度筛选：涨幅、资金流入、连续强势、风险板块
    - 轮动识别：对比历史热门板块，识别轮动方向
    
    支持两种分析模式：
    - NORMAL: 正常分析模式
        - 获取全部板块数据
        - 多维度筛选重点板块
        - LLM聚焦分析筛选后的板块
        - 输出结构化报告
    - REVIEW: 复盘模式
        - 聚合近期的分析报告
        - 验证热点预测
        - 提取经验教训存储到长期记忆
    
    输入数据格式：
    {
        "trade_date": "2026-02-26",
        "mode": "normal",  # 可选，默认 normal
        "sectors_data": [...]  # 可选，未提供时自动获取
    }
    
    输出：SectorReport
    """
    
    agent_type = AgentType.SECTOR  # 需要在 AgentType 中添加
    
    def __init__(
        self,
        agent_id: str = None,
        config: AgentConfig = None,
        memory_manager: Any = None,
        llm_client: Any = None,
        tool_registry: Any = None,
        mode: AnalysisMode = AnalysisMode.NORMAL,
    ):
        from agents.agent_config import get_agent_config
        agent_config = get_agent_config()
        settings = agent_config.get_sector_analyst_settings()
        
        if config is None:
            config = AgentConfig(
                name=settings.name,
                description=settings.description,
                model=settings.llm.model,
                temperature=settings.llm.temperature,
                max_tokens=settings.llm.max_tokens,
            )
        
        memory_manager = memory_manager or get_memory_manager()
        tool_registry = tool_registry or get_tool_registry()
        
        super().__init__(agent_id, config, memory_manager, llm_client, tool_registry)
        
        self.mode = mode
        self._settings = settings
        self._ensure_tools_registered()
    
    def validate_input(self, input_data: Dict[str, Any]) -> Optional[str]:
        """
        验证输入数据（实现基类抽象方法）
        
        Args:
            input_data: 输入数据字典
            
        Returns:
            错误信息字符串，验证通过返回None
        """
        # 1. 验证 trade_date（必需）
        trade_date = input_data.get('trade_date')
        if not trade_date:
            return "缺少必需参数: trade_date"
        
        # 验证日期格式
        try:
            datetime.strptime(trade_date, '%Y-%m-%d')
        except ValueError:
            return f"日期格式错误: {trade_date}，应为 YYYY-MM-DD"
        
        # 2. 验证 mode（可选）
        mode = input_data.get('mode', 'normal')
        valid_modes = ['normal', 'review']
        if isinstance(mode, str) and mode.lower() not in valid_modes:
            return f"无效的 mode 参数: {mode}，应为 {valid_modes}"
        
        # 3. 验证 sectors_data（可选）
        sectors_data = input_data.get('sectors_data')
        if sectors_data is not None:
            if not isinstance(sectors_data, list):
                return "sectors_data 必须是列表类型"
        
        return None  # 验证通过
    
    def _ensure_tools_registered(self) -> None:
        """确保工具已注册"""
        if self._tool_registry is None:
            return
        
        # 检查板块数据工具是否注册
        if not self._tool_registry.get("sector_data"):
            try:
                from core.tools import register_all_tools
                register_all_tools(self._tool_registry)
                logger.info("板块数据工具自动注册完成")
            except Exception as e:
                logger.warning(f"工具自动注册失败: {e}")
    
    def set_mode(self, mode: AnalysisMode) -> None:
        """设置分析模式"""
        self.mode = mode
        logger.info(f"切换分析模式: {mode.value}")
    
    # ==================== 数据获取方法 ====================
    
    def _get_sectors_data(self, trade_date: str, session_id: str = None) -> Optional[List[Dict[str, Any]]]:
        """
        获取板块数据
        
        优先从数据库获取，失败时使用模拟数据
        
        Args:
            trade_date: 交易日期 (YYYY-MM-DD)
            session_id: 工作记忆会话ID
            
        Returns:
            板块数据列表，失败返回None
        """
        # 尝试从数据库获取
        try:
            from data.basic_data.database import get_session, SectorData
            session = get_session()
            trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d').date()
            
            records = session.query(SectorData).filter(
                SectorData.trade_date == trade_date_obj
            ).all()
            
            if records:
                sectors_data = [self._sector_record_to_dict(r) for r in records]
                logger.info(f"从数据库获取板块数据成功: {len(sectors_data)} 条")
                
                if session_id and self._memory_manager:
                    self._memory_manager.working_memory.set(
                        session_id, "data_source", "database"
                    )
                return sectors_data
                
        except Exception as e:
            logger.warning(f"从数据库获取板块数据失败: {e}")
        
        # 尝试使用工具获取
        try:
            if self._tool_registry and self._tool_registry.get("sector_data"):
                sectors_data = self.call_tool("sector_data", trade_date=trade_date)
                if sectors_data:
                    logger.info(f"通过工具获取板块数据成功: {len(sectors_data)} 条")
                    
                    if session_id and self._memory_manager:
                        self._memory_manager.working_memory.set(
                            session_id, "data_source", "tool"
                        )
                    return sectors_data
        except ValueError as e:
            logger.error(f"工具获取板块数据失败: {e}")
        except Exception as e:
            logger.error(f"工具调用异常: {e}")
        
        # 数据获取失败，返回 None
        logger.error(f"无法获取 {trade_date} 的板块数据")
        return None
    
    def _sector_record_to_dict(self, record) -> Dict[str, Any]:
        """将数据库记录转换为字典"""
        return {
            'sector_code': getattr(record, 'sector_code', getattr(record, 'ts_code', '')),
            'sector_name': getattr(record, 'sector_name', getattr(record, 'name', '')),
            'trade_date': str(record.trade_date),
            'open': getattr(record, 'open', 0.0),
            'close': getattr(record, 'close', 0.0),
            'high': getattr(record, 'high', 0.0),
            'low': getattr(record, 'low', 0.0),
            'pct_chg': getattr(record, 'pct_chg', 0.0),
            'vol': getattr(record, 'vol', 0.0),
            'amount': getattr(record, 'amount', 0.0),
            'circ_mv': getattr(record, 'circ_market_cap', getattr(record, 'circ_mv', 0.0)),
            'total_mv': getattr(record, 'total_market_cap', getattr(record, 'total_mv', 0.0)),
            'pe': getattr(record, 'pe', 0.0),
            'pb': getattr(record, 'pb', 0.0),
            'turnover_rate': getattr(record, 'turnover_rate', 0.0),
            'adv_issues': getattr(record, 'adv_issues', getattr(record, 'rise_count', 0)),
            'dec_issues': getattr(record, 'dec_issues', getattr(record, 'fall_count', 0)),
            'fund_inflow': getattr(record, 'fund_inflow', 0.0),
            'fund_inflow_rate': getattr(record, 'fund_inflow_rate', 0.0),
            'rank': getattr(record, 'rank', 0),
        }
    
    def _get_sector_30d_trends(
        self, 
        trade_date: str,
        top_n: int = 10
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        获取板块30日趋势数据
        
        对比近30日 vs 前30日的板块表现，识别中期趋势
        
        Args:
            trade_date: 当前交易日期
            top_n: 返回各类TOP N
            
        Returns:
            {
                'hot_30d': [...],      # 近30日热门板块（按累计涨幅排序）
                'capital_30d': [...],  # 近30日资金流入板块（按累计流入排序）
                'risk_30d': [...]      # 近30日风险板块（按累计跌幅排序）
            }
        """
        from data.schemas.sector_schema import SectorTrend30D, SECTOR_TREND_30D_CN
        
        trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d').date()
        
        # 初始化结果
        trends_result = {
            'hot_30d': [],
            'capital_30d': [],
            'risk_30d': []
        }
        
        try:
            from data.basic_data.database import get_session, SectorData
            session = get_session()
            
            # 1. 获取所有不同的交易日（按日期倒序，取前60个交易日）
            all_trade_dates = session.query(SectorData.trade_date).filter(
                SectorData.trade_date <= trade_date_obj
            ).distinct().order_by(SectorData.trade_date.desc()).limit(60).all()
            
            all_dates = [str(d[0]) for d in all_trade_dates]
            
            if len(all_dates) < 40:  # 数据不足
                logger.warning(f"30日趋势分析: 数据不足，仅{len(all_dates)}个交易日，需要至少40个")
                return trends_result
            
            # 2. 划分近30日和前30日（直接按交易日数量平分）
            recent_30_dates = all_dates[:30]
            prev_30_dates = all_dates[30:60]
            
            logger.info(f"30日趋势分析: 近30日{len(recent_30_dates)}个交易日, 前30日{len(prev_30_dates)}个交易日")
            
            # 3. 获取这些日期的板块数据
            date_objs = [datetime.strptime(d, '%Y-%m-%d').date() for d in all_dates]
            recent_records = session.query(SectorData).filter(
                SectorData.trade_date.in_(date_objs)
            ).all()
            
            # 4. 按日期分组
            recent_by_date = {}
            for r in recent_records:
                date_str = str(r.trade_date)
                if date_str not in recent_by_date:
                    recent_by_date[date_str] = []
                recent_by_date[date_str].append(r)
            
            # 5. 聚合板块数据
            def aggregate_sectors(dates, by_date):
                """聚合指定日期范围的板块数据"""
                sector_stats = {}
                
                for date_str in dates:
                    if date_str not in by_date:
                        continue
                    for r in by_date[date_str]:
                        code = r.sector_code
                        if code not in sector_stats:
                            sector_stats[code] = {
                                'sector_code': code,
                                'sector_name': getattr(r, 'sector_name', ''),
                                'pct_chg_sum': 0.0,
                                'fund_inflow_sum': 0.0,
                                'rank_sum': 0,
                                'strong_days': 0,
                                'days': 0
                            }
                        
                        sector_stats[code]['pct_chg_sum'] += float(getattr(r, 'pct_chg', 0) or 0)
                        sector_stats[code]['fund_inflow_sum'] += float(getattr(r, 'fund_inflow', 0) or 0)
                        sector_stats[code]['rank_sum'] += int(getattr(r, 'rank', 50) or 50)
                        sector_stats[code]['days'] += 1
                        
                        # 强势天数（排名<=20）
                        rank = int(getattr(r, 'rank', 50) or 50)
                        if rank <= 20:
                            sector_stats[code]['strong_days'] += 1
                
                return sector_stats
            
            recent_stats = aggregate_sectors(recent_30_dates, recent_by_date)
            prev_stats = aggregate_sectors(prev_30_dates, recent_by_date)
            
            # 6. 构建趋势数据
            trend_list = []
            for code, stats in recent_stats.items():
                if stats['days'] < 5:  # 数据太少跳过
                    continue
                
                prev_stats_data = prev_stats.get(code, {})
                
                trend = {
                    'sector_code': code,
                    'sector_name': stats['sector_name'],
                    # 近30日数据
                    'pct_chg_30d': stats['pct_chg_sum'],
                    'fund_inflow_30d': stats['fund_inflow_sum'],
                    'avg_rank_30d': stats['rank_sum'] / stats['days'] if stats['days'] > 0 else 50,
                    'strong_days_30d': stats['strong_days'],
                    'days_30d': stats['days'],
                    # 前30日数据
                    'pct_chg_prev_30d': prev_stats_data.get('pct_chg_sum', 0),
                    'fund_inflow_prev_30d': prev_stats_data.get('fund_inflow_sum', 0),
                    'avg_rank_prev_30d': prev_stats_data.get('rank_sum', 2500) / prev_stats_data.get('days', 50) if prev_stats_data.get('days', 0) > 0 else 50,
                    'strong_days_prev_30d': prev_stats_data.get('strong_days', 0),
                    'days_prev_30d': prev_stats_data.get('days', 0)
                }
                
                # 判断趋势类型
                trend['trend_type'] = self._determine_trend_type(trend)
                trend['trend_description'] = self._build_trend_description(trend)
                
                trend_list.append(trend)
            
            # 7. 分类排序
            # 近30日热门（按累计涨幅）
            hot_30d = sorted(trend_list, key=lambda x: x['pct_chg_30d'], reverse=True)[:top_n]
            
            # 近30日风险（按累计跌幅）
            risk_30d = sorted(trend_list, key=lambda x: x['pct_chg_30d'])[:top_n]
            
            trends_result = {
                'hot_30d': hot_30d,
                'risk_30d': risk_30d
            }
            
            logger.info(f"30日趋势分析完成: 热门{len(hot_30d)}个, 风险{len(risk_30d)}个")
            
        except Exception as e:
            logger.error(f"30日趋势分析失败: {e}")
        
        return trends_result
    
    def _determine_trend_type(self, trend: Dict[str, Any]) -> str:
        """
        判断趋势类型
        
        Args:
            trend: 包含近30日和前30日数据的字典
            
        Returns:
            趋势类型: ACCELERATING/PERSISTENT/WEAKENING/CONSISTENTLY_WEAK/REBOUNDING/CORRECTING
        """
        pct_chg_30d = trend.get('pct_chg_30d', 0)
        pct_chg_prev = trend.get('pct_chg_prev_30d', 0)
        avg_rank_30d = trend.get('avg_rank_30d', 50)
        avg_rank_prev = trend.get('avg_rank_prev_30d', 50)
        
        # 判断是否强势：平均排名<=30 或 累计涨幅>0
        is_strong_recent = avg_rank_30d <= 30 or pct_chg_30d > 0
        is_strong_prev = avg_rank_prev <= 30 or pct_chg_prev > 0
        
        if is_strong_recent and is_strong_prev:
            # 两者都强，判断是否加强
            if pct_chg_30d > pct_chg_prev:
                return 'ACCELERATING'  # 趋势加强
            else:
                return 'PERSISTENT'    # 持续强势
        elif is_strong_recent and not is_strong_prev:
            # 近期转强
            return 'REBOUNDING'        # 触底反弹
        elif not is_strong_recent and is_strong_prev:
            # 近期转弱
            return 'CORRECTING'        # 高位回调
        else:
            # 两者都弱
            return 'CONSISTENTLY_WEAK'  # 持续弱势
    
    def _build_trend_description(self, trend: Dict[str, Any]) -> str:
        """
        构建趋势描述
        
        Args:
            trend: 趋势数据
            
        Returns:
            趋势描述文本
        """
        from data.schemas.sector_schema import SECTOR_TREND_30D_CN
        
        trend_type = trend.get('trend_type', '')
        trend_cn = SECTOR_TREND_30D_CN.get(trend_type, trend_type)
        
        name = trend.get('sector_name', '')
        pct_30d = trend.get('pct_chg_30d', 0)
        pct_prev = trend.get('pct_chg_prev_30d', 0)
        fund_30d = trend.get('fund_inflow_30d', 0) / 1e8  # 转亿
        
        parts = [f"{name}：{trend_cn}"]
        
        if pct_30d > 0:
            parts.append(f"近30日+{pct_30d:.1f}%")
        else:
            parts.append(f"近30日{pct_30d:.1f}%")
        
        if fund_30d > 0:
            parts.append(f"资金流入{fund_30d:.1f}亿")
        elif fund_30d < 0:
            parts.append(f"资金流出{abs(fund_30d):.1f}亿")
        
        # 对比前30日
        if pct_prev != 0:
            if pct_30d > pct_prev:
                parts.append(f"强于前30日")
            elif pct_30d < pct_prev:
                parts.append(f"弱于前30日")
        
        return "，".join(parts)
    
    def _get_history_sectors_data(
        self, 
        trade_date: str, 
        days: int = 5
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        获取历史板块数据（用于连续性分析）
        
        Args:
            trade_date: 当前交易日期
            days: 历史天数
            
        Returns:
            {trade_date_str: [sectors_data]}
        """
        history_data = {}
        trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d').date()
        
        try:
            from data.basic_data.database import get_session, SectorData
            session = get_session()
            
            for i in range(1, days + 1):
                prev_date = trade_date_obj - timedelta(days=i)
                records = session.query(SectorData).filter(
                    SectorData.trade_date == prev_date
                ).all()
                
                if records:
                    history_data[str(prev_date)] = [self._sector_record_to_dict(r) for r in records]
            
            logger.info(f"获取历史板块数据: {len(history_data)} 天")
            
        except Exception as e:
            logger.warning(f"获取历史板块数据失败: {e}")
            # 如果获取历史数据失败，创建一个空的模拟历史数据
            for i in range(1, days + 1):
                prev_date = trade_date_obj - timedelta(days=i)
                history_data[str(prev_date)] = []
        
        return history_data
    
    # ==================== 筛选方法 ====================
    
    def _filter_hot_sectors(
        self, 
        sectors: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        筛选热门板块（涨幅TOP N）
        
        Args:
            sectors: 全部板块数据
            
        Returns:
            热门板块列表
        """
        analysis_config = self._settings.analysis if hasattr(self._settings, 'analysis') else {}
        filter_config = analysis_config.get('filter', {}) if isinstance(analysis_config, dict) else {}
        threshold_config = analysis_config.get('threshold', {}) if isinstance(analysis_config, dict) else {}
        
        top_n = filter_config.get('hot_sectors_top_n', 10)
        min_amount = threshold_config.get('min_amount', 1000000000)
        
        # 单位转换：配置中的 min_amount 单位是元，数据库中 amount 单位是千元
        # 需要将元转换为千元进行比较
        min_amount_k = min_amount / 1000  # 元 -> 千元
        
        # 过滤冷门板块（成交额过小）
        filtered = [s for s in sectors if s.get('amount', 0) >= min_amount_k]
        
        # 按涨跌幅排序
        sorted_sectors = sorted(filtered, key=lambda x: x.get('pct_chg', 0), reverse=True)
        
        # 取TOP N
        hot_sectors = sorted_sectors[:top_n]
        
        logger.info(f"筛选热门板块: {len(hot_sectors)} 个（涨幅TOP {top_n}）")
        return hot_sectors
    
    def _filter_risk_sectors(
        self, 
        sectors: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        筛选风险板块（跌幅TOP N）
        
        Args:
            sectors: 全部板块数据
            
        Returns:
            风险板块列表
        """
        analysis_config = self._settings.analysis if hasattr(self._settings, 'analysis') else {}
        filter_config = analysis_config.get('filter', {}) if isinstance(analysis_config, dict) else {}
        threshold_config = analysis_config.get('threshold', {}) if isinstance(analysis_config, dict) else {}
        
        bottom_n = filter_config.get('risk_sectors_bottom_n', 10)
        min_amount = threshold_config.get('min_amount', 1000000000)
        
        # 单位转换：配置中的 min_amount 单位是元，数据库中 amount 单位是千元
        min_amount_k = min_amount / 1000  # 元 -> 千元
        
        # 过滤冷门板块
        filtered = [s for s in sectors if s.get('amount', 0) >= min_amount_k]
        
        # 按涨跌幅排序（升序）
        sorted_sectors = sorted(filtered, key=lambda x: x.get('pct_chg', 0))
        
        # 取BOTTOM N
        risk_sectors = sorted_sectors[:bottom_n]
        
        logger.info(f"筛选风险板块: {len(risk_sectors)} 个（跌幅TOP {bottom_n}）")
        return risk_sectors
    
    def _filter_capital_flow_sectors(
        self, 
        sectors: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        筛选资金流入板块（综合评分：流入占成交额比例 + 流入率）
        
        综合评分解决不同板块成分股数量不同导致的资金流入绝对值差异问题：
        - 大板块：成分股多、市值大，绝对流入额天然较大
        - 小板块：成分股少、市值小，但流入率可能很高
        - 综合评分平衡两者，既关注大资金动向，也捕捉热点早期信号
        
        评分考虑资金流向方向：
        - 资金流入（正值）：评分为正，排在前面
        - 资金流出（负值）：评分为负，排在后面
        
        Args:
            sectors: 全部板块数据
            
        Returns:
            资金流入板块列表（按综合评分排序，只包含资金净流入的板块）
        """
        analysis_config = self._settings.analysis if hasattr(self._settings, 'analysis') else {}
        filter_config = analysis_config.get('filter', {}) if isinstance(analysis_config, dict) else {}
        threshold_config = analysis_config.get('threshold', {}) if isinstance(analysis_config, dict) else {}
        capital_score_config = analysis_config.get('capital_score', {}) if isinstance(analysis_config, dict) else {}
        
        top_n = filter_config.get('capital_flow_top_n', 10)
        min_amount = threshold_config.get('min_amount', 1000000000)
        
        # 综合评分权重（从配置读取，默认各50%）
        inflow_to_amount_weight = capital_score_config.get('inflow_to_amount_weight', 0.5)
        inflow_rate_weight = capital_score_config.get('inflow_rate_weight', 0.5)
        
        # 单位转换：配置中的 min_amount 单位是元，数据库中 amount 单位是千元
        min_amount_k = min_amount / 1000  # 元 -> 千元
        
        # 过滤冷门板块
        filtered = [s for s in sectors if s.get('amount', 0) >= min_amount_k]
        
        # 计算综合评分（考虑资金流向方向）
        for s in filtered:
            fund_inflow = s.get('fund_inflow', 0)
            amount = s.get('amount', 0)
            fund_inflow_rate = s.get('fund_inflow_rate', 0)
            
            # 计算流入占成交额比例（%）
            # 注意：fund_inflow 单位是元，amount 单位是千元，需要统一
            # 🆕 保留正负号：资金流入为正，流出为负
            if amount > 0:
                # 将 amount 从千元转换为元（乘以1000）
                amount_yuan = amount * 1000
                # 保留正负号，不再使用 abs()
                inflow_to_amount = fund_inflow / amount_yuan * 100
            else:
                inflow_to_amount = 0
            
            # 🆕 综合评分考虑资金流向方向
            # 流入率保留正负号：资金流入为正，流出为负
            # 评分 = 权重1 * 流入占成交比例 + 权重2 * 流入率
            # 资金流入时评分为正，流出时评分为负
            capital_score = (
                inflow_to_amount_weight * inflow_to_amount + 
                inflow_rate_weight * fund_inflow_rate  # 不再使用 abs()
            )
            
            s['capital_score'] = capital_score
            s['inflow_to_amount'] = inflow_to_amount  # 保存用于显示（带正负号）
        
        # 按综合评分排序（降序）：资金流入的板块排在前面
        sorted_sectors = sorted(filtered, key=lambda x: x.get('capital_score', 0), reverse=True)
        
        # 🆕 只取评分大于0的板块（即资金净流入的板块）
        capital_sectors = [s for s in sorted_sectors if s.get('capital_score', 0) > 0][:top_n]
        
        inflow_count = len([s for s in filtered if s.get('fund_inflow', 0) > 0])
        logger.info(f"筛选资金流入板块: {len(capital_sectors)} 个（共{inflow_count}个资金净流入板块，综合评分TOP {top_n}）")
        return capital_sectors
    
    def _analyze_continuous_strong(
        self,
        today_sectors: List[Dict[str, Any]],
        history_data: Dict[str, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """
        分析连续强势板块
        
        Args:
            today_sectors: 今日板块数据
            history_data: 历史板块数据
            
        Returns:
            添加了连续强势天数的板块列表
        """
        analysis_config = self._settings.analysis if hasattr(self._settings, 'analysis') else {}
        filter_config = analysis_config.get('filter', {}) if isinstance(analysis_config, dict) else {}
        
        rank_threshold = filter_config.get('continuous_strong_rank', 20)
        min_days = filter_config.get('continuous_strong_days', 3)
        
        # 为今日板块添加连续强势天数
        for sector in today_sectors:
            sector_code = sector.get('sector_code')
            continuous_days = 0
            
            # 检查历史数据
            for prev_date, prev_sectors in history_data.items():
                # 找到该板块在历史数据中的排名
                prev_sorted = sorted(prev_sectors, key=lambda x: x.get('pct_chg', 0), reverse=True)
                for rank, s in enumerate(prev_sorted, 1):
                    if s.get('sector_code') == sector_code:
                        if rank <= rank_threshold:
                            continuous_days += 1
                        else:
                            break
                        break
            
            sector['continuous_strong_days'] = continuous_days
        
        return today_sectors
    
    def _analyze_rank_change(
        self,
        today_sectors: List[Dict[str, Any]],
        yesterday_sectors: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        分析排名变化
        
        Args:
            today_sectors: 今日板块数据
            yesterday_sectors: 昨日板块数据
            
        Returns:
            添加了排名变化的板块列表
        """
        # 构建昨日排名映射
        yesterday_sorted = sorted(yesterday_sectors, key=lambda x: x.get('pct_chg', 0), reverse=True)
        yesterday_rank = {s.get('sector_code'): i + 1 for i, s in enumerate(yesterday_sorted)}
        
        # 计算今日排名和变化
        today_sorted = sorted(today_sectors, key=lambda x: x.get('pct_chg', 0), reverse=True)
        
        for rank, sector in enumerate(today_sorted, 1):
            sector['rank'] = rank
            prev_rank = yesterday_rank.get(sector.get('sector_code'))
            if prev_rank:
                sector['rank_change'] = prev_rank - rank  # 正值表示排名上升
            else:
                sector['rank_change'] = 0
        
        return today_sectors
    
    def _analyze_rotation(
        self,
        today_hot: List[Dict[str, Any]],
        yesterday_hot_names: List[str]
    ) -> Dict[str, Any]:
        """
        分析板块轮动
        
        Args:
            today_hot: 今日热门板块
            yesterday_hot_names: 昨日热门板块名称列表
            
        Returns:
            轮动分析信息
        """
        today_hot_names = [s.get('sector_name', '') for s in today_hot[:10]]
        
        # 新晋热门：今日在榜，昨日不在
        new_hot = [n for n in today_hot_names if n not in yesterday_hot_names]
        
        # 持续强势：今日在榜，昨日也在
        persistent = [n for n in today_hot_names if n in yesterday_hot_names]
        
        # 降温板块：昨日在榜，今日不在
        cooling = [n for n in yesterday_hot_names if n not in today_hot_names]
        
        rotation_info = {
            'new_hot_sectors': new_hot,
            'persistent_hot_sectors': persistent,
            'cooling_sectors': cooling,
        }
        
        logger.info(f"轮动分析: 新晋={len(new_hot)}, 持续={len(persistent)}, 降温={len(cooling)}")
        return rotation_info
    
    def _calculate_market_breadth(
        self, 
        sectors: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        计算市场广度
        
        Args:
            sectors: 全部板块数据
            
        Returns:
            市场广度信息
        """
        total = len(sectors)
        if total == 0:
            return {}
        
        adv_count = sum(1 for s in sectors if s.get('pct_chg', 0) > 0)
        dec_count = sum(1 for s in sectors if s.get('pct_chg', 0) < 0)
        flat_count = total - adv_count - dec_count
        
        avg_chg = sum(s.get('pct_chg', 0) for s in sectors) / total
        
        # 强势/弱势板块占比（涨跌幅超过阈值）
        analysis_config = self._settings.analysis if hasattr(self._settings, 'analysis') else {}
        threshold_config = analysis_config.get('threshold', {}) if isinstance(analysis_config, dict) else {}
        
        strong_threshold = threshold_config.get('strong_pct_chg', 2.0)
        weak_threshold = threshold_config.get('weak_pct_chg', -2.0)
        
        strong_count = sum(1 for s in sectors if s.get('pct_chg', 0) >= strong_threshold)
        weak_count = sum(1 for s in sectors if s.get('pct_chg', 0) <= weak_threshold)
        
        # 判断市场状态
        if adv_count / total > 0.7:
            state = 'STRONG'
        elif dec_count / total > 0.7:
            state = 'WEAK'
        else:
            state = 'NORMAL'
        
        market_breadth = {
            'total_sectors': total,
            'adv_sector_count': adv_count,
            'dec_sector_count': dec_count,
            'flat_sector_count': flat_count,
            'avg_pct_chg': avg_chg,
            'strong_sector_ratio': strong_count / total * 100,
            'weak_sector_ratio': weak_count / total * 100,
            'market_breadth_state': state,
        }
        
        return market_breadth
    
    def _build_memory_query(
        self,
        hot_sectors: List[Dict[str, Any]],
        capital_sectors: List[Dict[str, Any]],
        rotation_info: Dict[str, Any]
    ) -> str:
        """
        使用筛选结果构建长期记忆查询
        
        Args:
            hot_sectors: 热门板块列表
            capital_sectors: 资金流入板块列表
            rotation_info: 轮动分析信息
            
        Returns:
            查询文本
        """
        parts = []
        
        # 热门板块
        if hot_sectors:
            names = [s.get('sector_name', '') for s in hot_sectors[:5]]
            parts.append(f"热门板块：{', '.join(names)}")
        
        # 资金流入
        if capital_sectors:
            names = [s.get('sector_name', '') for s in capital_sectors[:3]]
            parts.append(f"资金流入：{', '.join(names)}")
        
        # 轮动信息
        new_hot = rotation_info.get('new_hot_sectors', [])
        if new_hot:
            parts.append(f"新晋热点：{', '.join(new_hot)}")
        
        cooling = rotation_info.get('cooling_sectors', [])
        if cooling:
            parts.append(f"降温板块：{', '.join(cooling)}")
        
        return "\n".join(parts) if parts else "板块轮动分析"

    def _get_yesterday_hot_sectors(self, trade_date: str) -> List[str]:
        """
        获取昨日热门板块名称列表
        
        Args:
            trade_date: 当前交易日期
            
        Returns:
            昨日热门板块名称列表
        """
        try:
            trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d').date()
            
            if self._memory_manager:
                # 从记忆中获取昨日报告
                # 传入 trade_date 本身，让 get_recent_reports 自动计算 end_date = trade_date - 1
                reports = self._memory_manager.get_recent_reports(
                    self.agent_id, n=1, reference_date=trade_date_obj
                )
                if reports:
                    content = reports[0].get('content', {})
                    data = content.get('data', {})
                    hot_sectors = data.get('hot_sectors', [])
                    if hot_sectors and isinstance(hot_sectors[0], dict):
                        return [s.get('sector_name', '') for s in hot_sectors[:10]]
                    elif hot_sectors:
                        return hot_sectors[:10]
        except Exception as e:
            logger.warning(f"获取昨日热门板块失败: {e}")
        
        return []
    
    # ==================== 分析模式 ====================
    
    def _run_normal_mode(
        self, 
        input_data: Dict[str, Any], 
        context: Dict[str, Any] = None
    ) -> AgentResult:
        """
        正常分析模式
        
        流程：
        1. 获取板块数据
        2. 多维度筛选
        3. LLM分析
        4. 构建报告
        
        Args:
            input_data: 输入数据
            context: 上下文数据
            
        Returns:
            AgentResult(data=SectorReport)
        """
        context = context or {}
        session_id = context.get('session_id')
        trade_date = input_data.get('trade_date', '')
        
        if session_id:
            logger.info(f"[{self.agent_id}] 使用工作记忆会话: {session_id}")
        
        # 1. 获取板块数据
        sectors_data = input_data.get('sectors_data')
        if not sectors_data:
            sectors_data = self._get_sectors_data(trade_date, session_id)
            if not sectors_data:
                return AgentResult.failure_result(f"无法获取 {trade_date} 的板块数据")
        
        # 获取历史数据（用于连续性分析和排名变化）
        history_data = self._get_history_sectors_data(trade_date, days=5)
        yesterday_sectors = list(history_data.values())[0] if history_data else []
        
        # 2. 多维度筛选
        # 分析排名变化
        if yesterday_sectors:
            sectors_data = self._analyze_rank_change(sectors_data, yesterday_sectors)
        
        # 分析连续强势
        if history_data:
            sectors_data = self._analyze_continuous_strong(sectors_data, history_data)
        
        # 筛选各类板块
        hot_sectors = self._filter_hot_sectors(sectors_data)
        risk_sectors = self._filter_risk_sectors(sectors_data)
        capital_sectors = self._filter_capital_flow_sectors(sectors_data)
        
        # 计算市场广度
        market_breadth = self._calculate_market_breadth(sectors_data)
        
        # 分析轮动
        yesterday_hot = self._get_yesterday_hot_sectors(trade_date)
        rotation_info = self._analyze_rotation(hot_sectors, yesterday_hot)
        
        # 存储筛选结果到工作记忆
        if session_id and self._memory_manager:
            self._memory_manager.working_memory.set(session_id, "hot_sectors", hot_sectors)
            self._memory_manager.working_memory.set(session_id, "risk_sectors", risk_sectors)
            self._memory_manager.working_memory.set(session_id, "capital_sectors", capital_sectors)
            self._memory_manager.working_memory.set(session_id, "market_breadth", market_breadth)
            self._memory_manager.working_memory.set(session_id, "rotation_info", rotation_info)
        
        # 3. 加载长期记忆（RAG检索）
        long_term_memory = []
        if self._memory_manager:
            try:
                query_context = self._build_memory_query(hot_sectors, capital_sectors, rotation_info)
                long_term_memory = self._memory_manager.search_long_term(
                    query=query_context,
                    agent_type="SECTOR",
                    k=3
                )
                logger.info(f"[{self.agent_id}] 加载长期记忆: {len(long_term_memory)} 条")
                
                if session_id:
                    self._memory_manager.working_memory.set(session_id, "long_term_memory", long_term_memory)
            except Exception as e:
                logger.warning(f"加载长期记忆失败: {e}")
        
        # 3.5 获取上一个交易日完整分析报告（从短期记忆）
        yesterday_report = None
        if self._memory_manager:
            try:
                # 直接获取最近的报告（n=1），无需计算上一个交易日
                # get_recent_reports 会按日期倒序返回，排除当天
                trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d').date()
                
                recent_reports = self._memory_manager.get_recent_reports(
                    self.agent_id, n=1, reference_date=trade_date_obj
                )
                if recent_reports:
                    yesterday_report = recent_reports[0]
                    prev_date = yesterday_report.get('trade_date', '未知')
                    logger.info(f"[{self.agent_id}] 获取上一交易日分析报告成功: {prev_date}")
                    
                    if session_id:
                        self._memory_manager.working_memory.set(session_id, "yesterday_report", yesterday_report)
            except Exception as e:
                logger.warning(f"获取上一交易日报告失败: {e}")
        
        # 3.6 🆕 生成昨日热点预测验证文本
        prediction_verification = ""
        if yesterday_report and hot_sectors:
            try:
                # 构建今日报告模拟（用于验证）
                today_report_mock = {
                    "content": {
                        "hot_sectors": hot_sectors
                    }
                }
                prediction_verification = self._validate_hot_prediction(
                    yesterday_report,
                    today_report_mock,
                    today_sectors_data=sectors_data,  # 🆕 传入今日板块数据，用于获取排名和涨跌幅
                    output_format="text"
                )
                logger.info(f"[{self.agent_id}] 昨日热点预测验证完成")
            except Exception as e:
                logger.warning(f"热点预测验证失败: {e}")
        
        # 3.7 🆕 获取30日趋势数据
        trends_30d = {}
        try:
            trends_30d = self._get_sector_30d_trends(trade_date, top_n=10)
            logger.info(f"[{self.agent_id}] 30日趋势分析完成")
            
            if session_id:
                self._memory_manager.working_memory.set(session_id, "trends_30d", trends_30d)
        except Exception as e:
            logger.warning(f"30日趋势分析失败: {e}")
        
        # 3.8 🆕 获取大盘新闻分析（从记忆系统获取当日报告）
        market_news_analysis = None
        if self._memory_manager:
            try:
                # 传入下一天的日期，让 get_recent_reports 返回当日的报告
                trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d').date()
                next_day = trade_date_obj + timedelta(days=1)
                reports = self._memory_manager.get_recent_reports(
                    agent_id="MARKET",
                    n=1,
                    reference_date=next_day
                )
                if reports:
                    # 检查报告日期是否为当日
                    report_date = reports[0].get('trade_date', '')
                    if report_date == trade_date:
                        content = reports[0].get('content', {})
                        # 直接从 data 层级获取新闻分析
                        data = content.get('data')
                        if data and isinstance(data, dict):
                            market_news_analysis = data.get('news_analysis')
                            if market_news_analysis:
                                logger.info(f"[{self.agent_id}] 从记忆获取当日({trade_date})大盘新闻分析数据")
                    else:
                        logger.warning(f"[{self.agent_id}] 未找到当日({trade_date})大盘报告，最近报告日期: {report_date}")
            except Exception as e:
                logger.warning(f"从记忆获取大盘新闻分析失败: {e}")
        
        # 4. LLM分析（传入长期记忆、预测验证、30日趋势和大盘新闻分析）
        analysis_prompt = build_sector_analysis_prompt(
            trade_date=trade_date,
            all_sectors=sectors_data,
            hot_sectors=hot_sectors,
            capital_sectors=capital_sectors,
            risk_sectors=risk_sectors,
            market_breadth=market_breadth,
            rotation_info=rotation_info,
            yesterday_hot=yesterday_hot,
            long_term_memory=long_term_memory,
            yesterday_report=yesterday_report,
            prediction_verification=prediction_verification,
            trends_30d=trends_30d,
            market_news_analysis=market_news_analysis
        )
        
        try:
            response = self.call_llm(
                prompt=analysis_prompt,
                system_prompt=SYSTEM_PROMPT_SECTOR_ANALYST
            )
            analysis_result = self.parse_response(response)
            
            # 🆕 标准化预测板块名称（使用嵌入向量语义匹配）
            raw_predictions = analysis_result.get("hot_analysis", {}).get("predicted_hot_sectors", [])
            if raw_predictions:
                try:
                    match_result = self.call_tool(
                        "sector_match",
                        predicted_names=raw_predictions,
                        trade_date=trade_date
                    )
                    if match_result and match_result.get("matched"):
                        # 更新为标准化后的板块名称
                        analysis_result["hot_analysis"]["predicted_hot_sectors"] = match_result["matched"]
                        # 保留映射关系用于调试
                        analysis_result["hot_analysis"]["prediction_mapping"] = match_result.get("mapping")
                        logger.info(f"板块名称标准化: {raw_predictions} → {match_result['matched']}")
                except Exception as e:
                    logger.warning(f"板块名称标准化失败，使用原始预测: {e}")
            
            if session_id and self._memory_manager:
                self._memory_manager.working_memory.set(session_id, "analysis_result", analysis_result)
            
        except Exception as e:
            logger.error(f"LLM分析失败: {e}")
            return AgentResult.failure_result(f"LLM分析失败: {str(e)}")
        
        # 4. 构建报告
        try:
            report = self._build_sector_report(
                trade_date=trade_date,
                sectors_data=sectors_data,
                hot_sectors=hot_sectors,
                risk_sectors=risk_sectors,
                capital_sectors=capital_sectors,
                market_breadth=market_breadth,
                rotation_info=rotation_info,
                analysis_result=analysis_result
            )
            
            logger.info(f"[{self.agent_id}] 板块分析完成: {trade_date}")
            return AgentResult.success_result(report)
            
        except Exception as e:
            logger.error(f"构建报告失败: {e}")
            return AgentResult.failure_result(f"构建报告失败: {str(e)}")
    
    def _run_review_mode(self, trade_date: str, context: Dict[str, Any] = None) -> AgentResult:
        """
        复盘模式：聚合近期报告，提取经验
        
        Args:
            trade_date: 复盘日期
            context: 上下文数据
            
        Returns:
            复盘结果
        """
        context = context or {}
        session_id = context.get('session_id')
        
        if not self._memory_manager:
            return AgentResult.failure_result("复盘模式需要记忆管理器")
        
        from datetime import datetime as dt
        ref_date = dt.strptime(trade_date, "%Y-%m-%d").date()
        
        # 获取近期报告
        recent_reports = self._memory_manager.get_recent_reports(
            self.agent_id, n=self._settings.memory.review_days, reference_date=ref_date
        )
        
        if not recent_reports:
            return AgentResult.failure_result(f"无最近{self._settings.memory.review_days}个交易日的分析报告")
        
        # 验证热点预测
        verification_results = []
        for i, report in enumerate(recent_reports):
            if i < len(recent_reports) - 1:
                next_report = recent_reports[i + 1]
                verification = self._validate_hot_prediction(report, next_report)
                verification_results.append(verification)
        
        # 构建复盘Prompt
        review_prompt = build_sector_review_prompt(recent_reports, verification_results)
        
        try:
            response = self.call_llm(
                prompt=review_prompt,
                system_prompt=SYSTEM_PROMPT_SECTOR_ANALYST
            )
            
            # 提取经验教训
            insights = self._extract_insights(response)
            
            # 保存到长期记忆
            if insights and self._memory_manager:
                for insight in insights:
                    self._memory_manager.save_experience(self.agent_id, insight)
                logger.info(f"复盘经验已保存到长期记忆: {len(insights)} 条")
            
            return AgentResult.success_result({
                "review_date": trade_date,
                "reports_analyzed": len(recent_reports),
                "verification_results": verification_results,
                "insights": insights,
                "raw_response": response
            })
            
        except Exception as e:
            logger.error(f"复盘分析失败: {e}")
            return AgentResult.failure_result(f"复盘分析失败: {str(e)}")
    
    def _validate_hot_prediction(
        self, 
        report: Dict[str, Any], 
        next_day_report: Dict[str, Any],
        today_sectors_data: List[Dict[str, Any]] = None,
        output_format: str = "dict"
    ) -> Union[Dict[str, Any], str]:
        """
        验证热点预测
        
        判断标准：预测的板块在次日热门板块TOP10中即算正确
        
        Args:
            report: 预测日的报告（包含昨日对今日的预测）
            next_day_report: 实际日的报告（包含今日实际热门板块）
            today_sectors_data: 今日全部板块数据（用于获取预测板块的实际排名和涨跌幅）
            output_format: 输出格式
                - 'dict': 返回结构化字典（复盘模式用）
                - 'text': 返回格式化文本（分析时prompt用）
        
        Returns:
            根据 output_format 返回字典或文本
        """
        content = report.get("content", {})
        data = content.get("data", {})
        
        # 获取预测的热门板块（从 hot_analysis.predicted_hot_sectors 获取）
        hot_analysis = data.get("hot_analysis", {})
        predicted_names = hot_analysis.get("predicted_hot_sectors", [])
        
        # 获取次日实际热门板块TOP20
        next_content = next_day_report.get("content", {})
        next_data = next_content.get("data", {})
        actual_hot = next_data.get("hot_sectors", [])
        if actual_hot and isinstance(actual_hot[0], dict):
            actual_names_top20 = [s.get('sector_name', '') for s in actual_hot[:20]]
        else:
            actual_names_top20 = actual_hot[:20] if actual_hot else []
        
        # 🆕 获取预测板块的实际表现（排名和涨跌幅）
        predicted_performance = []
        if today_sectors_data and predicted_names:
            # 按涨跌幅排序，计算排名
            sorted_sectors = sorted(today_sectors_data, key=lambda x: x.get('pct_chg', 0), reverse=True)
            
            for predicted_name in predicted_names:
                # 查找该板块在今日数据中的表现
                for rank, sector in enumerate(sorted_sectors, 1):
                    if sector.get('sector_name', '') == predicted_name:
                        predicted_performance.append({
                            'name': predicted_name,
                            'rank': rank,
                            'pct_chg': sector.get('pct_chg', 0),
                            'in_top20': rank <= 20
                        })
                        break
                else:
                    # 板块名称未匹配，可能名称有变化
                    predicted_performance.append({
                        'name': predicted_name,
                        'rank': None,
                        'pct_chg': None,
                        'in_top20': False
                    })
        
        # 计算命中率：预测板块在次日TOP20中即算命中
        hits = len(set(predicted_names) & set(actual_names_top20))
        total = len(predicted_names) if predicted_names else 0
        
        # 命中率>=50%视为正确
        correct = (hits / total >= 0.5) if total > 0 else False
        
        result = {
            "date": report.get("trade_date"),
            "predicted": predicted_names,
            "actual_top20": actual_names_top20,
            "predicted_performance": predicted_performance,  # 🆕 预测板块的实际表现
            "hits": hits,
            "total": total,
            "correct": correct
        }
        
        # 根据输出格式返回
        if output_format == "text":
            return self._format_hot_prediction_verification_text(result)
        return result
    
    def _format_hot_prediction_verification_text(self, verification: Dict[str, Any]) -> str:
        """
        将热点预测验证结果格式化为prompt文本
        
        Args:
            verification: 验证结果字典
            
        Returns:
            格式化后的文本
        """
        lines = ["### 昨日热点预测验证\n"]
        lines.append("> 以下是昨日对今日热点板块的预测，请参考预测准确性来调整今日预测：\n")
        
        predicted = verification.get('predicted', [])
        actual_top20 = verification.get('actual_top20', [])
        predicted_performance = verification.get('predicted_performance', [])
        hits = verification.get('hits', 0)
        total = verification.get('total', 0)
        correct = verification.get('correct', False)
        
        status = "✓ 成功" if correct else "✗ 失误"
        
        lines.append(f"**预测板块**: {', '.join(predicted) if predicted else '无'}")
        lines.append(f"**实际热门TOP20**: {', '.join(actual_top20[:5])}...")
        
        # 🆕 使用表格展示预测板块的实际表现
        if predicted_performance:
            lines.append("")
            lines.append("| 预测板块 | 当日排名 | 涨跌幅 | 结果 |")
            lines.append("|---------|---------|-------|------|")
            for perf in predicted_performance:
                name = perf.get('name', '')
                rank = perf.get('rank')
                pct_chg = perf.get('pct_chg')
                in_top20 = perf.get('in_top20', False)
                
                # 格式化排名
                rank_str = f"第{rank}名" if rank else "未匹配"
                # 格式化涨跌幅
                if pct_chg is not None:
                    pct_str = f"{pct_chg:+.2f}%"
                else:
                    pct_str = "-"
                # 结果标记
                result_str = "✓ 命中" if in_top20 else "✗ 未入TOP20"
                
                lines.append(f"| {name} | {rank_str} | {pct_str} | {result_str} |")
        
        lines.append("")
        lines.append(f"**命中率**: {hits}/{total} ({hits/total*100 if total > 0 else 0:.0f}%)，命中标准：进入TOP20")
        lines.append(f"**结果**: {status}")
        
        return "\n".join(lines)
    
    
    def _extract_insights(self, response: str) -> List[str]:
        """从复盘响应中提取经验教训"""
        insights = []
        parsed = self.parse_response(response)
        
        if parsed and 'lessons' in parsed:
            lessons = parsed.get('lessons', [])
            for lesson in lessons:
                if lesson.startswith("经验:"):
                    lesson = lesson[3:].strip()
                if lesson:
                    insights.append(lesson)
        
        return insights
    
    # ==================== 报告构建 ====================
    
    def _build_sector_report(
        self,
        trade_date: str,
        sectors_data: List[Dict[str, Any]],
        hot_sectors: List[Dict[str, Any]],
        risk_sectors: List[Dict[str, Any]],
        capital_sectors: List[Dict[str, Any]],
        market_breadth: Dict[str, Any],
        rotation_info: Dict[str, Any],
        analysis_result: Dict[str, Any]
    ) -> SectorReport:
        """构建板块报告"""
        
        # 构建市场广度
        breadth = MarketBreadth(
            total_sectors=market_breadth.get('total_sectors', 0),
            adv_sector_count=market_breadth.get('adv_sector_count', 0),
            dec_sector_count=market_breadth.get('dec_sector_count', 0),
            avg_pct_chg=market_breadth.get('avg_pct_chg', 0),
            market_breadth_state=market_breadth.get('market_breadth_state', 'NORMAL'),
        )
        
        # 构建板块轮动
        sector_rotation = SectorRotation(
            new_hot_sectors=rotation_info.get('new_hot_sectors', []),
            persistent_hot_sectors=rotation_info.get('persistent_hot_sectors', []),
            cooling_sectors=rotation_info.get('cooling_sectors', []),
        )
        
        # 构建热门板块详情列表
        hot_details = []
        for s in hot_sectors:
            detail = HotSectorDetail(
                sector_code=s.get('sector_code', ''),
                sector_name=s.get('sector_name', ''),
                rank=s.get('rank', 0),
                pct_chg=s.get('pct_chg', 0),
                amount=s.get('amount', 0),
                fund_inflow=s.get('fund_inflow', 0),
                continuous_strong_days=s.get('continuous_strong_days', 0),
                rank_change=s.get('rank_change', 0),
                filter_source='hot',
            )
            hot_details.append(detail)
        
        # 构建资金流入板块详情列表
        capital_details = []
        for s in capital_sectors:
            detail = HotSectorDetail(
                sector_code=s.get('sector_code', ''),
                sector_name=s.get('sector_name', ''),
                rank=s.get('rank', 0),
                pct_chg=s.get('pct_chg', 0),
                amount=s.get('amount', 0),
                fund_inflow=s.get('fund_inflow', 0),
                fund_inflow_rate=s.get('fund_inflow_rate', 0),
                filter_source='capital_flow',
            )
            capital_details.append(detail)
        
        # 构建风险板块详情列表
        risk_details = []
        for s in risk_sectors:
            detail = HotSectorDetail(
                sector_code=s.get('sector_code', ''),
                sector_name=s.get('sector_name', ''),
                rank=s.get('rank', 0),
                pct_chg=s.get('pct_chg', 0),
                amount=s.get('amount', 0),
                filter_source='risk',
            )
            risk_details.append(detail)
        
        # 构建热门分析（包含预测字段）
        hot_analysis_data = analysis_result.get('hot_analysis', {})
        hot_analysis = SectorHotAnalysis(
            hot_sectors_summary=hot_analysis_data.get('hot_sectors_summary', ''),
            hot_reasons=hot_analysis_data.get('hot_reasons', []),
            sustainability=hot_analysis_data.get('sustainability', ''),
            predicted_hot_sectors=hot_analysis_data.get('predicted_hot_sectors', []),
            predicted_reason=hot_analysis_data.get('predicted_reason', ''),
        )
        
        # 构建资金分析
        capital_analysis_data = analysis_result.get('capital_analysis', {})
        capital_analysis = SectorCapitalAnalysis(
            capital_flow_summary=capital_analysis_data.get('capital_flow_summary', ''),
            main_focus=capital_analysis_data.get('main_focus', []),
            capital_rotation=capital_analysis_data.get('capital_rotation', ''),
        )
        
        # 构建风险分析
        risk_analysis_data = analysis_result.get('risk_analysis', {})
        risk_analysis = SectorRiskAnalysis(
            risk_sectors_summary=risk_analysis_data.get('risk_sectors_summary', ''),
            risk_reasons=risk_analysis_data.get('risk_reasons', []),
            avoid_advice=risk_analysis_data.get('avoid_advice', ''),
        )
        
        # 构建报告
        report = SectorReport(
            date=trade_date,
            market_breadth=breadth,
            hot_sectors=hot_details,
            capital_flow_sectors=capital_details,
            risk_sectors=risk_details,
            sector_rotation=sector_rotation,
            hot_analysis=hot_analysis,
            capital_analysis=capital_analysis,
            risk_analysis=risk_analysis,
            rotation_signal=analysis_result.get('rotation_signal', ''),
            summary=analysis_result.get('summary', ''),
            tomorrow_outlook=analysis_result.get('tomorrow_outlook', ''),
            total_sectors_analyzed=len(sectors_data),
            focus_sectors_count=len(hot_sectors) + len(capital_sectors) + len(risk_sectors),
            confidence=analysis_result.get('confidence', 50.0),
        )
        
        return report
    
    # ==================== 主入口 ====================
    
    def analyze(self, input_data: Dict[str, Any], context: Dict[str, Any] = None) -> AgentResult:
        """
        执行板块分析（由 execute() 模板方法调用）
        
        支持两种模式：
        - NORMAL: 正常分析模式，筛选+聚焦分析
        - REVIEW: 复盘模式，聚合报告，提取经验
        
        Args:
            input_data: 输入数据
                - trade_date: 交易日期
                - mode: 分析模式（可选，默认normal）
                - sectors_data: 板块数据（可选，未提供时自动获取）
            context: 上下文数据（由 execute() 传入，包含 session_id）
            
        Returns:
            AgentResult(data=SectorReport 或 复盘结果)
        """
        context = context or {}
        mode_str = input_data.get('mode', 'normal')
        
        # 复盘模式
        if mode_str.lower() == 'review':
            self.set_mode(AnalysisMode.REVIEW)
            trade_date = input_data.get('trade_date', '')
            return self._run_review_mode(trade_date, context)
        
        # 正常模式
        self.set_mode(AnalysisMode.NORMAL)
        return self._run_normal_mode(input_data, context)
    
    def parse_response(self, response: str) -> Dict[str, Any]:
        """
        解析LLM响应
        
        Args:
            response: LLM响应文本
            
        Returns:
            解析后的字典
        """
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                json_str = json_match.group(0)
            else:
                logger.warning(f"无法从响应中提取JSON: {response[:200]}")
                return {}
        
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            return {}