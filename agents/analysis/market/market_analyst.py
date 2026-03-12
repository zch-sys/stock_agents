"""
大盘分析师Agent

MarketAnalyst: 分析大盘指数，输出MarketReport

支持两种分析模式：
- NORMAL: 正常分析模式，DB优先数据获取，加载短期记忆验证预测
- REVIEW: 复盘模式，10个交易日报告聚合，经验提取存储到长期记忆
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
from data.schemas.market_schema import (
    MarketReport, IndexSummary, TechnicalAnalysis, CapitalAnalysis,
    SentimentAnalysis, ValuationAnalysis, CycleAnalysis, RiskAssessment,
    NewsAnalysis, IndexPrediction,
)
from agents.analysis.market.market_prompts import (
    INDEX_NAMES, SYSTEM_PROMPT_MARKET_ANALYST,
    build_technical_analysis_prompt, build_capital_analysis_prompt, build_sentiment_analysis_prompt,
    build_valuation_cycle_analysis_prompt, build_news_analysis_prompt, build_synthesis_prompt,
    build_review_prompt
)
from data.basic_data.database import MarketIndex, get_session
from data.transformers.market_transformer import MarketTransformer

logger = logging.getLogger(__name__)


class AnalysisMode(Enum):
    """分析模式枚举"""
    NORMAL = "normal"
    REVIEW = "review"


@AgentRegistry.register
class MarketAnalyst(BaseAgent):
    """
    大盘分析师
    
    分析A股主要指数（上证、深证、创业板），输出市场分析报告。
    
    支持两种分析模式：
    - NORMAL: 正常分析模式
        - DB优先数据获取，缺失时调用Tushare工具
        - 加载最近3天短期记忆用于验证预测和上下文参考
        - 验证结果存储到工作记忆
    - REVIEW: 复盘模式
        - 聚合最近一周的分析报告
        - 验证预测与实际走势
        - 提取经验教训存储到长期记忆
    
    输入数据格式：
    {
        "trade_date": "2026-02-13",
        "mode": "normal",  # 可选，默认 normal
        "index_data": {
            "000001.SH": MarketAnalysisData,
            "399001.SZ": MarketAnalysisData,
            "399006.SZ": MarketAnalysisData,
        }
    }
    
    输出：MarketReport
    """
    
    agent_type = AgentType.MARKET
    
    INDEX_CODES = ['000001.SH', '399001.SZ', '399006.SZ']
    CAPITAL_SOURCE_CODE = '000001.SH'
    
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
        settings = agent_config.get_market_analyst_settings()
        
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
        self._transformer = MarketTransformer()
        self._db_session = get_session()
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
        
        # 3. 验证 index_data（可选）
        index_data = input_data.get('index_data')
        if index_data is not None:
            if not isinstance(index_data, dict):
                return "index_data 必须是字典类型"
            
            valid_codes = set(self.INDEX_CODES)
            for code in index_data.keys():
                if code not in valid_codes:
                    return f"无效的指数代码: {code}，应为 {valid_codes}"
        
        return None  # 验证通过
    
    def _ensure_tools_registered(self) -> None:
        """确保Tushare工具已注册"""
        if self._tool_registry is None:
            return
        
        if not self._tool_registry.get("tushare_market_data"):
            try:
                from core.tools import register_all_tools
                register_all_tools(self._tool_registry)
                logger.info("Tushare工具自动注册完成")
            except Exception as e:
                logger.warning(f"工具自动注册失败: {e}")
    
    def set_mode(self, mode: AnalysisMode) -> None:
        """设置分析模式"""
        self.mode = mode
        logger.info(f"切换分析模式: {mode.value}")
    
    def _data_retrieval_workflow(self, trade_date: str, session_id: str = None) -> Optional[Dict[str, Any]]:
        """
        数据获取工作流：DB优先，数据完整性检查与补全，Tushare工具回退
        
        Args:
            trade_date: 交易日期 (YYYY-MM-DD)
            session_id: 工作记忆会话ID
            
        Returns:
            指数数据字典，失败返回None
        """
        index_data = {}
        missing_codes = []
        
        trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d').date()
        
        for code in self.INDEX_CODES:
            db_data = self._query_from_database(code, trade_date_obj)
            if db_data:
                self._check_and_complete_data(code, trade_date, session_id)
                self._db_session.refresh(db_data)
                
                if self._validate_data_completeness(db_data):
                    history_data = self._query_history_from_database(code, trade_date_obj, days=30, valuation_days=600)
                    transformed = self._transformer.transform_with_history(db_data, history_data)
                    index_data[code] = transformed
                    if session_id and self._memory_manager:
                        self._memory_manager.working_memory.set(
                            session_id, f"data_source_{code}", "database"
                        )
                    logger.info(f"[{code}] 从数据库获取数据成功（含历史数据）")
                else:
                    logger.warning(f"[{code}] 数据完整性验证失败，尝试Tushare回退")
                    missing_codes.append(code)
            else:
                missing_codes.append(code)
        
        if missing_codes:
            logger.warning(f"以下指数数据缺失，尝试Tushare工具: {missing_codes}")
            for code in missing_codes:
                tushare_data = self._fetch_from_tushare(code, trade_date)
                if tushare_data:
                    self._save_to_database(code, trade_date_obj, tushare_data)
                    transformed = self._transformer.transform(tushare_data)
                    index_data[code] = transformed
                    if session_id and self._memory_manager:
                        self._memory_manager.working_memory.set(
                            session_id, f"data_source_{code}", "tushare_fallback"
                        )
                    logger.info(f"[{code}] Tushare回退获取成功")
        
        return index_data if index_data else None
    
    def _query_from_database(self, ts_code: str, trade_date: date) -> Optional[MarketIndex]:
        """从数据库查询指数数据"""
        try:
            record = self._db_session.query(MarketIndex).filter(
                MarketIndex.ts_code == ts_code,
                MarketIndex.trade_date == trade_date
            ).first()
            return record
        except Exception as e:
            logger.error(f"数据库查询失败 [{ts_code}]: {e}")
            return None
    
    def _query_history_from_database(
        self, 
        ts_code: str, 
        trade_date: date, 
        days: int = 30,
        valuation_days: int = 600
    ) -> List[MarketIndex]:
        """
        从数据库查询历史指数数据
        
        Args:
            ts_code: 指数代码
            trade_date: 当前交易日期
            days: 技术分析历史天数（默认30天）
            valuation_days: 估值分析历史天数（默认600天）
            
        Returns:
            历史记录列表（包含估值分析所需数据），最多 valuation_days 条
        """
        try:
            # 查询 max(days, valuation_days) 天的数据
            total_days = max(days, valuation_days)
            records = self._db_session.query(MarketIndex).filter(
                MarketIndex.ts_code == ts_code,
                MarketIndex.trade_date < trade_date
            ).order_by(MarketIndex.trade_date.desc()).limit(total_days).all()
            return list(reversed(records))
        except Exception as e:
            logger.error(f"历史数据查询失败 [{ts_code}]: {e}")
            return []
    
    def _validate_data_completeness(self, data: MarketIndex) -> bool:
        """
        验证数据完整性
        
        通用字段（所有指数）：
        - 基础行情：open, close, high, low, pct_chg, vol, amount
        - 技术指标：ma5, ma10, ma20, ma60, macd, macd_signal, macd_hist, adx
        - 估值指标：pe, pb
        - 情绪指标：adv_issues, dec_issues, adv_decline_ratio, market_width, ad_line, turnover_concentration
        
        上证指数额外字段：
        - 北向资金：north_money_total
        - 两融数据：margin_balance, margin_buy, short_balance
        - 资金流向：net_amount, net_amount_rate, buy_elg_amount, buy_lg_amount, buy_md_amount, buy_sm_amount
        
        注意：资金流向字段需要额外检查 0.0 值（API失败时会存储0.0而非None）
        """
        # 通用必需字段
        common_required = [
            # 基础行情
            'open', 'close', 'high', 'low', 'pct_chg', 'vol', 'amount',
            # 技术指标
            'ma5', 'ma10', 'ma20', 'ma60',
            'macd', 'macd_signal', 'macd_hist', 'adx',
            # 估值指标
            'pe', 'pb',
            # 情绪指标
            'adv_issues', 'dec_issues', 'adv_decline_ratio', 'market_width', 'ad_line', 'turnover_concentration'
        ]
        
        for field in common_required:
            value = getattr(data, field, None)
            if value is None:
                logger.warning(f"[{data.ts_code}] 通用字段缺失: {field}")
                return False
        
        # 上证指数额外检查
        if data.ts_code == '000001.SH':
            # 北向资金：检查 None 和 0.0（API失败时存储0.0）
            north_value = getattr(data, 'north_money_total', None)
            if north_value is None:
                logger.warning(f"[{data.ts_code}] 北向资金字段缺失: north_money_total")
                return False
            if north_value == 0.0:
                logger.warning(f"[{data.ts_code}] 北向资金字段无效(值为0): north_money_total")
                return False
            
            # 两融数据：检查 None 和 0.0（API失败时存储0.0）
            margin_fields = ['margin_balance', 'margin_buy', 'short_balance']
            for field in margin_fields:
                value = getattr(data, field, None)
                if value is None:
                    logger.warning(f"[{data.ts_code}] 两融数据字段缺失: {field}")
                    return False
                # 两融数据值为0.0也视为无效（API获取失败时的占位符）
                if value == 0.0:
                    logger.warning(f"[{data.ts_code}] 两融数据字段无效(值为0): {field}")
                    return False
            
            # 资金流向字段：检查 None 和 0.0（API失败时存储0.0）
            flow_fields = [
                'net_amount', 'net_amount_rate',
                'buy_elg_amount', 'buy_elg_amount_rate',
                'buy_lg_amount', 'buy_lg_amount_rate',
                'buy_md_amount', 'buy_md_amount_rate',
                'buy_sm_amount', 'buy_sm_amount_rate'
            ]
            
            for field in flow_fields:
                value = getattr(data, field, None)
                if value is None:
                    logger.warning(f"[{data.ts_code}] 资金流向字段缺失: {field}")
                    return False
                # 资金流向字段值为0.0也视为无效（API获取失败时的占位符）
                if value == 0.0:
                    logger.warning(f"[{data.ts_code}] 资金流向字段无效(值为0): {field}")
                    return False
        
        return True
    
    def _check_and_complete_data(self, ts_code: str, trade_date: str, session_id: str = None) -> bool:
        """
        使用数据完整性工具检查并补全缺失字段
        
        Args:
            ts_code: 指数代码
            trade_date: 交易日期
            session_id: 工作记忆会话ID
            
        Returns:
            是否成功补全
        """
        try:
            data = self.call_tool("tushare_data_completeness", ts_code=ts_code, trade_date=trade_date)
            status = data.get('status', 'unknown')
            if status == 'complete':
                logger.info(f"[{ts_code}] 数据完整性检查通过，无缺失字段")
            else:
                missing = data.get('missing_fields', {})
                collected = data.get('collected_fields', [])
                logger.info(f"[{ts_code}] 数据补全完成，缺失: {missing}，已补全: {collected}")
                
                if session_id and self._memory_manager:
                    self._memory_manager.working_memory.set(
                        session_id, f"completeness_check_{ts_code}", {
                            'status': status,
                            'missing_fields': missing,
                            'collected_fields': collected
                        }
                    )
            return True
        except ValueError as e:
            if "未注册" in str(e):
                logger.debug(f"数据完整性工具未注册，跳过自动补全")
            else:
                logger.warning(f"[{ts_code}] 数据完整性检查失败: {e}")
            return False
        except Exception as e:
            logger.error(f"[{ts_code}] 数据完整性检查异常: {e}")
            return False
    
    def _fetch_from_tushare(self, ts_code: str, trade_date: str) -> Optional[Dict[str, Any]]:
        """
        通过Tushare工具获取完整数据
        
        当数据库不可用时，依次调用所有必要的数据工具：
        1. 基础行情（所有指数）
        2. 技术指标（所有指数）
        3. 估值数据（所有指数）
        4. 上证指数特有：北向资金、两融数据、资金流向
        
        Args:
            ts_code: 指数代码
            trade_date: 交易日期
            
        Returns:
            合并后的完整数据字典
        """
        all_data = {'ts_code': ts_code, 'trade_date': trade_date}
        
        # 1. 基础行情（所有指数必需）
        try:
            basic = self.call_tool("tushare_market_data", ts_code=ts_code, trade_date=trade_date)
            if basic:
                all_data.update(basic)
                logger.info(f"[{ts_code}] Tushare获取基础行情成功")
        except ValueError as e:
            if "未注册" in str(e):
                logger.warning(f"Tushare工具未注册，无法获取 {ts_code} 基础行情")
                return None  # 基础行情是必需的
            else:
                logger.error(f"获取基础行情失败: {e}")
        except Exception as e:
            logger.error(f"获取基础行情异常: {e}")
        
        # 2. 技术指标（所有指数必需）
        try:
            tech = self.call_tool("tushare_technical_indicator", ts_code=ts_code, trade_date=trade_date)
            if tech:
                all_data.update(tech)
                logger.info(f"[{ts_code}] Tushare获取技术指标成功")
        except ValueError as e:
            if "未注册" in str(e):
                logger.warning(f"技术指标工具未注册")
            else:
                logger.error(f"获取技术指标失败: {e}")
        except Exception as e:
            logger.error(f"获取技术指标异常: {e}")
        
        # 3. 估值数据（所有指数）
        try:
            val = self.call_tool("tushare_valuation", ts_code=ts_code, trade_date=trade_date)
            if val:
                all_data.update(val)
                logger.info(f"[{ts_code}] Tushare获取估值数据成功")
        except ValueError as e:
            if "未注册" in str(e):
                logger.debug(f"估值工具未注册")
            else:
                logger.warning(f"获取估值数据失败: {e}")
        except Exception as e:
            logger.warning(f"获取估值数据异常: {e}")
        
        # 4. 上证指数特有数据
        if ts_code == '000001.SH':
            # 4.1 北向资金
            try:
                north = self.call_tool("tushare_north_money", trade_date=trade_date)
                if north:
                    all_data.update(north)
                    logger.info(f"[{ts_code}] Tushare获取北向资金成功")
            except ValueError as e:
                if "未注册" in str(e):
                    logger.debug(f"北向资金工具未注册")
                else:
                    logger.warning(f"获取北向资金失败: {e}")
            except Exception as e:
                logger.warning(f"获取北向资金异常: {e}")
            
            # 4.2 两融数据
            try:
                margin = self.call_tool("tushare_margin", trade_date=trade_date)
                if margin:
                    all_data.update(margin)
                    logger.info(f"[{ts_code}] Tushare获取两融数据成功")
            except ValueError as e:
                if "未注册" in str(e):
                    logger.debug(f"两融数据工具未注册")
                else:
                    logger.warning(f"获取两融数据失败: {e}")
            except Exception as e:
                logger.warning(f"获取两融数据异常: {e}")
            
            # 4.3 资金流向
            try:
                flow = self.call_tool("tushare_money_flow", trade_date=trade_date)
                if flow:
                    all_data.update(flow)
                    logger.info(f"[{ts_code}] Tushare获取资金流向成功")
            except ValueError as e:
                if "未注册" in str(e):
                    logger.debug(f"资金流向工具未注册")
                else:
                    logger.warning(f"获取资金流向失败: {e}")
            except Exception as e:
                logger.warning(f"获取资金流向异常: {e}")
        
        # 检查是否至少获取到了基础数据
        if 'close' not in all_data or all_data.get('close') is None:
            logger.error(f"[{ts_code}] 未能获取到有效数据")
            return None
        
        logger.info(f"[{ts_code}] Tushare数据获取完成，共 {len(all_data)} 个字段")
        return all_data
    
    def _save_to_database(self, ts_code: str, trade_date: date, data: Dict[str, Any]) -> bool:
        """保存数据到数据库"""
        try:
            existing = self._db_session.query(MarketIndex).filter(
                MarketIndex.ts_code == ts_code,
                MarketIndex.trade_date == trade_date
            ).first()
            
            if existing:
                for key, value in data.items():
                    if hasattr(existing, key) and value is not None:
                        setattr(existing, key, value)
            else:
                # 移除 data 中可能存在的 ts_code 和 trade_date，避免重复参数
                clean_data = {k: v for k, v in data.items() if k not in ('ts_code', 'trade_date')}
                record = MarketIndex(ts_code=ts_code, trade_date=trade_date, **clean_data)
                self._db_session.add(record)
            
            self._db_session.commit()
            return True
        except Exception as e:
            self._db_session.rollback()
            logger.error(f"保存数据库失败: {e}")
            return False
    
    def _run_review_mode(self, trade_date: str, context: Dict[str, Any] = None) -> AgentResult:
        """
        复盘模式：10个交易日报告聚合与经验提取
        
        Args:
            trade_date: 复盘日期
            context: 上下文数据（包含 session_id）
            
        Returns:
            复盘结果
        """
        context = context or {}
        session_id = context.get('session_id')
        
        if not self._memory_manager:
            return AgentResult.failure_result("复盘模式需要记忆管理器")
        
        from datetime import datetime as dt
        ref_date = dt.strptime(trade_date, "%Y-%m-%d").date()
        
        recent_reports = self._memory_manager.get_recent_reports(
            self.agent_id, n=self._settings.memory.review_days, reference_date=ref_date
        )
        
        if not recent_reports:
            return AgentResult.failure_result(f"无最近{self._settings.memory.review_days}个交易日的分析报告")
        
        verification_results = []
        for i, report in enumerate(recent_reports):
            if i < len(recent_reports) - 1:
                next_report = recent_reports[i + 1]
                verification = self._validate_single_prediction(report, next_report)
                verification_results.append(verification)
        
        review_prompt = build_review_prompt(recent_reports, verification_results)
        
        try:
            response = self.call_llm(
                prompt=review_prompt,
                system_prompt=SYSTEM_PROMPT_MARKET_ANALYST
            )
            
            insights = self._extract_insights(response)
            
            if insights and self._memory_manager:
                for insight in insights:
                    self._memory_manager.save_experience(self.agent_id, insight)
                logger.info(f"复盘经验已保存到长期记忆: {len(insights)} 条")
            
            validated_dates = [r.get("trade_date") for r in recent_reports if r.get("trade_date")]
            if validated_dates and self._memory_manager:
                self._memory_manager.mark_reports_validated(self.agent_id, validated_dates)
            
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
    
    def _validate_single_prediction(
        self, 
        report: Dict[str, Any], 
        next_day_report: Dict[str, Any],
        output_format: str = "dict"
    ) -> Union[Dict[str, Any], str]:
        """分指数验证单日预测"""
        threshold = self._settings.review.validation_threshold
        
        # 提取预测数据（直接从 data 层级获取）
        report_content = report.get("content", {})
        report_data = report_content.get("data", {})
        index_predictions = report_data.get("index_predictions", [])
        
        # 提取次日实际涨跌幅（直接从 data 层级获取）
        next_day_content = next_day_report.get("content", {})
        next_day_data = next_day_content.get("data", {})
        next_day_summaries = next_day_data.get("index_summaries", [])
        
        # 构建涨跌幅映射
        actual_pct_map = {s.get("ts_code", ""): s.get("pct_chg", 0) for s in next_day_summaries}
        
        # 如果没有分指数预测，无法验证，返回空结果
        if not index_predictions:
            logger.warning(f"[{self.agent_id}] 报告缺少 index_predictions 字段，跳过验证")
            return {
                "date": report.get("trade_date"),
                "index_results": [],
                "correct_count": 0,
                "total_count": 0,
                "accuracy": 0.0
            }
        
        # 分指数验证
        index_results = []
        correct_count = 0
        
        for pred in index_predictions:
            ts_code = pred.get("ts_code", "")
            name = pred.get("name", ts_code)
            predicted = pred.get("trend_direction", "SIDEWAYS")
            
            # 标准化预测值
            if isinstance(predicted, str):
                predicted = predicted.split('(')[0].strip().upper()
                if predicted not in ['UP', 'DOWN', 'SIDEWAYS']:
                    predicted = 'SIDEWAYS'
            else:
                predicted = 'SIDEWAYS'
            
            actual_pct = actual_pct_map.get(ts_code, 0)
            actual = "UP" if actual_pct > threshold else ("DOWN" if actual_pct < -threshold else "SIDEWAYS")
            is_correct = predicted == actual
            if is_correct:
                correct_count += 1
            
            index_results.append({
                "ts_code": ts_code, "name": name, "predicted": predicted,
                "actual": actual, "actual_pct_chg": actual_pct, "correct": is_correct
            })
        
        total_count = len(index_results)
        accuracy = correct_count / total_count if total_count > 0 else 0.0
        result = {
            "date": report.get("trade_date"), "index_results": index_results,
            "correct_count": correct_count, "total_count": total_count, "accuracy": round(accuracy, 3)
        }
        
        return self._format_prediction_verification_text(result) if output_format == "text" else result
    
    def _format_prediction_verification_text(self, verification: Dict[str, Any]) -> str:
        """
        将验证结果格式化为prompt文本
        
        Args:
            verification: 验证结果字典
            
        Returns:
            格式化后的文本
        """
        lines = ["### 昨日预测验证\n"]
        lines.append("> 以下是昨日对今日走势的预测，请参考预测准确性来调整今日预测的置信度：\n")
        
        for idx_result in verification.get('index_results', []):
            name = idx_result.get('name', '')
            predicted = idx_result.get('predicted', 'SIDEWAYS')
            actual = idx_result.get('actual', 'SIDEWAYS')
            actual_pct = idx_result.get('actual_pct_chg', 0)
            correct = idx_result.get('correct', False)
            
            status = "✓ 正确" if correct else "✗ 失误"
            
            lines.append(f"**{name}**")
            lines.append(f"- 预测: {predicted} | 实际: {actual} ({actual_pct:+.2f}%)")
            lines.append(f"结果: {status}")
            lines.append("")
        
        accuracy = verification.get('accuracy', 0)
        lines.append(f"**预测准确率**: {accuracy:.1%}")
        
        return "\n".join(lines)
    
    def _extract_insights(self, response: str) -> List[str]:
        """
        从复盘响应中提取经验教训
        
        Args:
            response: LLM 响应文本（JSON 格式）
            
        Returns:
            经验教训列表
        """
        insights = []
        parsed = self.parse_response(response)
        
        if parsed and 'lessons' in parsed:
            lessons = parsed.get('lessons', [])
            for lesson in lessons:
                # 去除 "经验:" 前缀（如果有）
                if lesson.startswith("经验:"):
                    lesson = lesson[3:].strip()
                if lesson:
                    insights.append(lesson)
        
        return insights

    def _get_news_data(self, hours: int = 24, session_id: str = None) -> List[Dict[str, Any]]:
        """
        获取大盘新闻数据并存储到工作记忆
        
        Args:
            hours: 获取最近N小时的新闻
            session_id: 工作记忆会话ID
            
        Returns:
            新闻列表
        """
        news_data = []
        # 直接从数据库查询
        try: 
            news_data = self.call_tool("market_news_data", max_pages=1, hours=hours)
            logger.info(f"获取大盘新闻成功: {len(news_data)} 条")
        except ValueError as e:
            if "未注册" in str(e):
                logger.debug("新闻工具未注册，尝试从数据库获取")
            else:
                logger.warning(f"获取大盘新闻失败: {e}")
        except Exception as e:
            logger.error(f"新闻工具调用异常: {e}")

        if not news_data:
            try:
                from data.basic_data.market_news_collector import MarketNewsCollector
                collector = MarketNewsCollector()
                news_data = collector.get_recent_news(hours=hours, limit=100)
                logger.info(f"从数据库获取新闻: {len(news_data)} 条")
            except Exception as e:
                logger.error(f"数据库查询新闻失败: {e}")
            # 尝试使用 call_tool 调用新闻工具 
            

                
        # 存储到工作记忆
        if session_id and self._memory_manager and news_data:
            try:
                self._memory_manager.working_memory.set(
                    session_id, "news_data", {
                        "count": len(news_data),
                        "hours": hours,
                        "fetched_at": datetime.now().isoformat()
                    }
                )
                # 存储完整数据供后续查询
                self._memory_manager.working_memory.set(
                    session_id, "news_full_data", news_data
                )
                logger.info(f"新闻数据已存储到工作记忆: {len(news_data)} 条")
            except Exception as e:
                logger.warning(f"存储新闻到工作记忆失败: {e}")
        
        return news_data
    
    # ==================== 分维度分析方法 ====================
    
    def _run_analysis_with_retry(
        self,
        dimension_name: str,
        prompt_builder,
        session_id: str,
        max_retries: int = 2,
        **prompt_kwargs
    ) -> Dict[str, Any]:
        """
        带重试机制的分析执行器
        
        Args:
            dimension_name: 维度名称（用于日志）
            prompt_builder: prompt 构建函数
            session_id: 工作记忆会话ID
            max_retries: 最大重试次数（默认2次）
            **prompt_kwargs: 传递给 prompt_builder 的参数
            
        Returns:
            解析后的分析结果字典
        """
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                prompt = prompt_builder(**prompt_kwargs)
                response = self.call_llm(prompt=prompt, system_prompt=SYSTEM_PROMPT_MARKET_ANALYST)
                result = self.parse_response(response)
                
                # 检查解析结果是否有效（非空字典）
                if result and isinstance(result, dict) and len(result) > 0:
                    # 存储到工作记忆
                    if self._memory_manager:
                        self._memory_manager.working_memory.set(session_id, f"{dimension_name}_result", result)
                    
                    if attempt > 0:
                        logger.info(f"[{self.agent_id}] {dimension_name}分析重试成功 (第{attempt + 1}次)")
                    return result
                else:
                    last_error = "解析结果为空"
                    logger.warning(f"[{self.agent_id}] {dimension_name}分析解析失败 (结果为空)，尝试 {attempt + 1}/{max_retries + 1}")
                    
            except Exception as e:
                last_error = str(e)
                logger.warning(f"[{self.agent_id}] {dimension_name}分析异常: {e}，尝试 {attempt + 1}/{max_retries + 1}")
        
        # 所有重试都失败
        logger.error(f"[{self.agent_id}] {dimension_name}分析最终失败: {last_error}")
        return {}
    
    def _run_dimensional_analysis(
        self,
        trade_date: str,
        index_data: Dict[str, Any],
        recent_reports: List[Dict[str, Any]],
        news_data: List[Dict[str, Any]],
        session_id: str,
        max_retries: int = 2
    ) -> Dict[str, Any]:
        """
        执行分维度分析（带重试机制）
        """
        results = {}
        
        # 定义维度配置：(名称, prompt构建函数, 额外参数)
        dimensions = [
            ('technical', build_technical_analysis_prompt, {'index_data': index_data, 'recent_reports': recent_reports}),
            ('capital', build_capital_analysis_prompt, {'index_data': index_data, 'recent_reports': recent_reports}),
            ('sentiment', build_sentiment_analysis_prompt, {'index_data': index_data, 'recent_reports': recent_reports}),
            ('valuation_cycle', build_valuation_cycle_analysis_prompt, {'index_data': index_data, 'recent_reports': recent_reports}),
            ('news', build_news_analysis_prompt, {'news_data': news_data}),
        ]
        
        for dim_name, prompt_builder, extra_kwargs in dimensions:
            logger.info(f"[{self.agent_id}] 开始{dim_name}分析...")
            results[dim_name] = self._run_analysis_with_retry(
                dimension_name=dim_name,
                prompt_builder=prompt_builder,
                session_id=session_id,
                max_retries=max_retries,
                trade_date=trade_date,
                **extra_kwargs
            )
            if results[dim_name]:
                logger.info(f"[{self.agent_id}] {dim_name}分析完成")
        
        return results
    
    def _run_synthesis_analysis(
        self,
        dimensional_results: Dict[str, Any],
        long_term_memory: List[Dict[str, Any]],
        trade_date: str,
        session_id: str,
        yesterday_report: Dict[str, Any] = None,
        index_data: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        执行综合判断（唯一预测点）
        
        Args:
            dimensional_results: 各维度分析结果
            long_term_memory: 长期记忆
            trade_date: 交易日期
            session_id: 工作记忆会话ID
            yesterday_report: 昨日分析报告（用于预测验证）
            index_data: 今日指数数据（用于预测验证）
            
        Returns:
            综合判断结果
        """
        logger.info(f"[{self.agent_id}] 开始综合判断...")
        
        # 🆕 生成昨日预测验证文本
        prediction_verification = ""
        if yesterday_report and index_data:
            try:
                # 构建今日指数摘要（用于验证）
                today_summaries = self._build_index_summaries(index_data)
                today_report_mock = {
                    "content": {
                        "data": {
                            "index_summaries": [s.to_dict() for s in today_summaries]
                        }
                    }
                }
                prediction_verification = self._validate_single_prediction(
                    yesterday_report, 
                    today_report_mock,
                    output_format="text"
                )
                logger.info(f"[{self.agent_id}] 昨日预测验证完成")
            except Exception as e:
                logger.warning(f"预测验证失败: {e}")
        
        synthesis_prompt = build_synthesis_prompt(
            technical_result=dimensional_results.get('technical', {}),
            capital_result=dimensional_results.get('capital', {}),
            sentiment_result=dimensional_results.get('sentiment', {}),
            valuation_cycle_result=dimensional_results.get('valuation_cycle', {}),
            news_result=dimensional_results.get('news', {}),
            long_term_memory=long_term_memory,
            trade_date=trade_date,
            prediction_verification=prediction_verification
        )
        
        try:
            response = self.call_llm(prompt=synthesis_prompt, system_prompt=SYSTEM_PROMPT_MARKET_ANALYST)
            result = self.parse_response(response)
            self._memory_manager.working_memory.set(session_id, "synthesis_result", result)
            logger.info(f"[{self.agent_id}] 综合判断完成")
            return result
        except Exception as e:
            logger.error(f"综合判断失败: {e}")
            return {}
    
    def _run_normal_mode(
        self, 
        input_data: Dict[str, Any], 
        context: Dict[str, Any] = None
    ) -> AgentResult:
        """
        正常分析模式（分维度分析）
        
        由 execute() 模板方法调用，Session 由基类创建。
        
        流程：
        1️⃣ 加载结构化数据（一次性）
        2️⃣ 分维度分析（各维度独立）
        3️⃣ 综合判断
        
        Args:
            input_data: 输入数据
                - trade_date: 交易日期
                - index_data: 指数数据（可选，未提供时自动获取）
            context: 上下文数据（包含 session_id）
            
        Returns:
            AgentResult(data=MarketReport)
        """
        context = context or {}
        session_id = context.get('session_id')
        trade_date = input_data.get('trade_date', '')
        
        # Session 由 execute() 创建，此处仅记录
        if session_id:
            logger.info(f"[{self.agent_id}] 使用工作记忆会话: {session_id}")
        
        # 2️⃣ 加载结构化数据
        index_data = input_data.get('index_data')
        if not index_data:
            index_data = self._data_retrieval_workflow(trade_date, session_id)
            if not index_data:
                return AgentResult.failure_result(f"无法获取 {trade_date} 的市场数据")
        
        # 存储指数数据到工作记忆
        if self._memory_manager:
            for code, data in index_data.items():
                if hasattr(data, 'to_dict'):
                    self._memory_manager.working_memory.set(session_id, f"index_{code}", data.to_dict())
        
        # 获取新闻数据
        news_data = self._get_news_data(hours=24, session_id=session_id)
        
        # 加载最近3天短期记忆（分维度分析需要）
        recent_reports = []
        if self._memory_manager:
            try:
                ref_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
                recent_reports = self._memory_manager.get_recent_reports(
                    self.agent_id, n=3, reference_date=ref_date
                )
                logger.info(f"[{self.agent_id}] 加载最近3天短期记忆: {len(recent_reports)} 条")
            except Exception as e:
                logger.warning(f"加载短期记忆失败: {e}")
        
        # 3️⃣ 分维度分析
        dimensional_results = self._run_dimensional_analysis(
            trade_date=trade_date,
            index_data=index_data,
            recent_reports=recent_reports,
            news_data=news_data,
            session_id=session_id
        )
        
        # 4️⃣ 使用分维度结果构建查询，加载长期记忆
        long_term_memory = []
        if self._memory_manager:
            try:
                query_context = self._build_memory_query(dimensional_results, index_data)
                long_term_memory = self._memory_manager.search_long_term(
                    query=query_context,
                    agent_type="MARKET",
                    k=3
                )
                logger.info(f"[{self.agent_id}] 加载长期记忆: {len(long_term_memory)} 条")
            except Exception as e:
                logger.warning(f"加载长期记忆失败: {e}")
        
        # 5️⃣ 综合判断（传入昨日报告用于预测验证）
        yesterday_report = recent_reports[0] if recent_reports else None
        synthesis_result = self._run_synthesis_analysis(
            dimensional_results=dimensional_results,
            long_term_memory=long_term_memory,
            trade_date=trade_date,
            session_id=session_id,
            yesterday_report=yesterday_report,
            index_data=index_data
        )
        
        # 构建 MarketReport
        try:
            index_summaries = self._build_index_summaries(index_data)
            
            # 构建分指数预测列表
            index_predictions = self._build_index_predictions(synthesis_result)
            
            # 合并分维度结果到最终报告
            technical_data = dimensional_results.get('technical', {})
            capital_data = dimensional_results.get('capital', {})
            sentiment_data = dimensional_results.get('sentiment', {})
            val_cycle_data = dimensional_results.get('valuation_cycle', {})
            news_analysis_data = dimensional_results.get('news', {})
            
            report = MarketReport(
                date=trade_date,
                index_summaries=index_summaries,
                market_state=synthesis_result.get('market_state', 'SHOCK'),
                index_predictions=index_predictions,
                technical=self._build_technical_analysis(technical_data),
                capital=self._build_capital_analysis(capital_data, index_data),
                sentiment=self._build_sentiment_analysis(sentiment_data, index_data),
                valuation=self._build_valuation_analysis(val_cycle_data.get('valuation', {}), index_data),
                cycle=self._build_cycle_analysis(val_cycle_data.get('cycle', {})),
                risk=self._build_risk_assessment({
                    'risk_factors': synthesis_result.get('risk_factors', []),
                    'opportunity_factors': synthesis_result.get('opportunity_factors', []),
                    'risk_level': self._infer_risk_level(synthesis_result.get('risk_factors', []))
                }),
                news_analysis=self._build_news_analysis(news_analysis_data),
                summary=synthesis_result.get('summary', ''),
                position_advice=synthesis_result.get('position_advice', ''),
                confidence=synthesis_result.get('confidence', 50.0)
            )
            
            logger.info(f"[{self.agent_id}] 分维度分析完成: {trade_date}")
            return AgentResult.success_result(report)
            
        except Exception as e:
            logger.error(f"[{self.agent_id}] 构建报告失败: {e}")
            return AgentResult.failure_result(f"构建报告失败: {str(e)}")
    
    def _infer_risk_level(self, risk_factors: List[str]) -> str:
        """根据风险因素数量推断风险等级"""
        count = len(risk_factors)
        if count >= 5:
            return 'HIGH'
        elif count >= 2:
            return 'MEDIUM'
        else:
            return 'LOW'
    
    def _build_memory_query(
        self, 
        dimensional_results: Dict[str, Any], 
        index_data: Dict[str, Any]
    ) -> str:
        """
        使用分维度分析结果构建长期记忆查询
        
        Args:
            dimensional_results: 各维度分析结果
            index_data: 指数数据
            
        Returns:
            查询文本
        """
        parts = []
        
        # 技术面
        tech = dimensional_results.get('technical', {})
        if tech.get('trend_analysis'):
            parts.append(f"技术面：{tech.get('trend_analysis', '')[:100]}")
        elif tech.get('ma_status'):
            parts.append(f"技术面：{tech.get('ma_status', '')[:100]}")
        
        # 资金面
        capital = dimensional_results.get('capital', {})
        if capital.get('capital_summary'):
            parts.append(f"资金面：{capital.get('capital_summary', '')[:100]}")
        elif capital.get('north_flow_analysis'):
            parts.append(f"资金面：{capital.get('north_flow_analysis', '')[:100]}")
        
        # 情绪面
        sentiment = dimensional_results.get('sentiment', {})
        if sentiment.get('sentiment_analysis'):
            parts.append(f"情绪面：{sentiment.get('sentiment_analysis', '')[:100]}")
        
        # 如果分维度结果为空，使用指数数据构建简单查询
        if not parts:
            sh_data = index_data.get('000001.SH')
            if sh_data:
                if hasattr(sh_data, 'to_dict'):
                    data_dict = sh_data.to_dict()
                else:
                    data_dict = sh_data
                
                price_data = data_dict.get('price_data', {})
                ma_alignment = data_dict.get('ma_alignment', {})
                
                pct_chg = price_data.get('pct_chg', 0)
                ma_desc = ma_alignment.get('description', '')
                
                trend = "上涨" if pct_chg > 0 else "下跌"
                return f"大盘{trend}{abs(pct_chg):.2f}%，{ma_desc}"
            
            return "大盘走势分析"
        
        return "\n".join(parts)

    def analyze(self, input_data: Dict[str, Any], context: Dict[str, Any] = None) -> AgentResult:
        """
        执行大盘分析（由 execute() 模板方法调用）
        
        支持两种模式：
        - NORMAL: 正常分析模式，分维度分析 + 综合判断
        - REVIEW: 复盘模式，周度报告聚合，经验提取存储到长期记忆
        
        Args:
            input_data: 输入数据
                - trade_date: 交易日期
                - mode: 分析模式（可选，默认normal）
                - index_data: 指数数据（可选，未提供时自动获取）
            context: 上下文数据（由 execute() 传入，包含 session_id）
            
        Returns:
            AgentResult(data=MarketReport 或 复盘结果)
        """
        context = context or {}
        mode_str = input_data.get('mode', 'normal')
        
        # 复盘模式
        if mode_str.lower() == 'review':
            self.set_mode(AnalysisMode.REVIEW)
            trade_date = input_data.get('trade_date', '')
            return self._run_review_mode(trade_date, context)
        
        # 正常模式：使用分维度分析
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
    
    def _build_index_summaries(self, index_data: Dict[str, Any]) -> List[IndexSummary]:
        """构建指数摘要列表"""
        summaries = []
        
        for code in self.INDEX_CODES:
            if code not in index_data:
                continue
            
            data = index_data[code]
            if hasattr(data, 'to_dict'):
                data_dict = data.to_dict()
            else:
                data_dict = data
            
            price_data = data_dict.get('price_data', {})
            ma_alignment = data_dict.get('ma_alignment', {})
            macd_signal = data_dict.get('macd_signal', {})
            support_resistance = data_dict.get('support_resistance', {})
            
            support_levels = []
            resistance_levels = []
            if support_resistance:
                support_levels = support_resistance.get('support', [])
                resistance_levels = support_resistance.get('resistance', [])
            
            summary = IndexSummary(
                ts_code=code,
                name=INDEX_NAMES.get(code, code),
                open=price_data.get('open', 0),
                high=price_data.get('high', 0),
                low=price_data.get('low', 0),
                close=price_data.get('close', 0),
                pct_chg=price_data.get('pct_chg', 0),
                amount=price_data.get('amount', 0),
                ma_status=ma_alignment.get('description', ''),
                macd_signal=macd_signal.get('description', ''),
                support_levels=support_levels if isinstance(support_levels, list) else [],
                resistance_levels=resistance_levels if isinstance(resistance_levels, list) else []
            )
            summaries.append(summary)
        
        return summaries
    
    def _build_technical_analysis(self, data: Dict[str, Any]) -> TechnicalAnalysis:
        """构建技术分析结果"""
        support_levels = self._extract_price_levels(data.get('support_levels', []))
        resistance_levels = self._extract_price_levels(data.get('resistance_levels', []))

        return TechnicalAnalysis(
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            trend_analysis=data.get('trend_analysis', ''),
            ma_status=data.get('ma_status', ''),
            macd_signal=data.get('macd_signal', ''),
            adx_analysis=data.get('adx_analysis', ''),
            volume_analysis = data.get('volume_analysis', '')
        )
    
    def _extract_price_levels(self, items: List[Any]) -> List[float]:
        """从LLM输出中提取价格水平（支持数字和字符串描述）"""
        levels = []
        for item in items:
            item_str = str(item).replace(',', '').replace('，', '')
            numbers = re.findall(r'[\d.]+', item_str)
            for num in numbers:
                try:
                    val = float(num)
                    if val > 100:
                        levels.append(val)
                except ValueError:
                    pass
        return levels
    
    def _build_capital_analysis(self, data: Dict[str, Any], index_data: Dict[str, Any] = None) -> CapitalAnalysis:
        """构建资金分析结果"""
        fund_flow_analysis = None
        
        if index_data:
            sh_data = index_data.get(self.CAPITAL_SOURCE_CODE)
            if sh_data:
                if hasattr(sh_data, 'capital_data'):
                    capital_data = sh_data.capital_data
                    if capital_data:
                        north_flow_value = capital_data.north_money_total / 100000000 if capital_data.north_money_total else 0
                        margin_balance = capital_data.margin_balance / 100000000 if capital_data.margin_balance else 0
                        
                if hasattr(sh_data, 'fund_flow_data') and hasattr(sh_data, 'fund_flow_analysis'):
                    ff_data = sh_data.fund_flow_data
                    ff_indicator = sh_data.fund_flow_analysis
                    
                    if ff_data:
                        from data.schemas.market_schema import FundFlowAnalysis
                        fund_flow_analysis = FundFlowAnalysis(
                            net_inflow=ff_data.net_amount / 100000000 if ff_data.net_amount else 0,
                            net_inflow_rate=ff_data.net_amount_rate if ff_data.net_amount_rate else 0,
                            super_large_flow=ff_data.buy_elg_amount / 100000000 if ff_data.buy_elg_amount else 0,
                            large_flow=ff_data.buy_lg_amount / 100000000 if ff_data.buy_lg_amount else 0,
                            medium_flow=ff_data.buy_md_amount / 100000000 if ff_data.buy_md_amount else 0,
                            small_flow=ff_data.buy_sm_amount / 100000000 if ff_data.buy_sm_amount else 0,
                            main_signal=ff_indicator.signal if ff_indicator else "",
                            description=ff_indicator.description if ff_indicator else ""
                        )
        
        return CapitalAnalysis(
            north_flow_analysis=data.get('north_flow_analysis', ''),
            north_flow_value=north_flow_value,     
            margin_analysis=data.get('margin_analysis', ''),
            margin_balance=margin_balance,    
            fund_flow_analysis=fund_flow_analysis,
            main_flow_analysis=data.get('main_flow_analysis', ''),
            capital_summary=data.get('capital_summary', '')
        )
    
    def _build_news_analysis(self, data: Dict[str, Any]) -> NewsAnalysis:
        """构建新闻分析结果"""
        return NewsAnalysis(
            key_news=data.get('key_news', []),
            positive_factors=data.get('positive_factors', []),
            negative_factors=data.get('negative_factors', []),
            market_impact=data.get('market_impact', ''),
            sector_focus=data.get('sector_focus', []),
            summary=data.get('summary', '')
        )

    def _build_sentiment_analysis(self, data: Dict[str, Any], index_data: Dict[str, Any] = None) -> SentimentAnalysis:
        """构建情绪分析结果"""
        sh_data = index_data.get(self.CAPITAL_SOURCE_CODE)
        adv_issues = 0
        dec_issues = 0
        market_width = 0.0
        sentiment_score = 50.0

        if sh_data and hasattr(sh_data, 'sentiment'):
            sent = sh_data.sentiment
            adv_issues = sent.adv_issues
            dec_issues = sent.dec_issues
            market_width = sent.market_width
            sentiment_score = sent.sentiment_score
            adv_decline_ratio = sent.adv_decline_ratio
            ad_line = sent.ad_line
            turnover_concentration = sent.turnover_concentration
        description = data.get('sentiment_analysis', '')
        breadth = data.get('market_breadth', '')
        emotion_state =  data.get('emotion_state ', '')
        summary = data.get('summary', '')
            
        return SentimentAnalysis(
            market_width=market_width,
            adv_issues=adv_issues,
            dec_issues=dec_issues,
            sentiment_score= sentiment_score,
            adv_decline_ratio=adv_decline_ratio,
            ad_line=ad_line,
            turnover_concentration = turnover_concentration,
            description=description,
            breadth = breadth,
            emotion_state = emotion_state,
            summary = summary
        )
    
    def _build_valuation_analysis(self, data: Dict[str, Any],index_data: Dict[str, Any]) -> ValuationAnalysis:
        """构建估值分析结果"""
        sh_data = index_data.get(self.CAPITAL_SOURCE_CODE)
        pe_value = 0.0
        pb_value = 0.0
        if sh_data and hasattr(sh_data, 'valuation'):
            val = sh_data.valuation
            if val:
                pe_value = val.pe
                pb_value = val.pb

        return ValuationAnalysis(
            graham_index=data.get('graham_index', None),
            pe_value=pe_value,
            pb_value=pb_value,
            valuation_level=data.get('valuation_level', 'MEDIUM'),
            valuation_analysis=data.get('valuation_analysis', '')
    )
    
    def _build_cycle_analysis(self, data: Dict[str, Any]) -> CycleAnalysis:
        """构建周期分析结果"""
        return CycleAnalysis(
            cycle_phase=data.get('cycle_phase', 'SHOCK'),
            cycle_analysis=data.get('cycle_analysis', '')
        )
    
    def _build_risk_assessment(self, data: Dict[str, Any]) -> RiskAssessment:
        """构建风险评估结果"""
        return RiskAssessment(
            risk_level=data.get('risk_level', 'MEDIUM'),
            risk_factors=data.get('risk_factors', []),
            opportunity_factors=data.get('opportunity_factors', [])
        )
    
    def _build_index_predictions(self, synthesis_result: Dict[str, Any]) -> List[IndexPrediction]:
        """
        构建分指数预测列表
        
        Args:
            synthesis_result: 综合判断结果
            
        Returns:
            分指数预测列表
        """
        predictions = []
        index_predictions_data = synthesis_result.get('index_predictions', [])
        
        # 如果 LLM 返回了分指数预测数据
        if index_predictions_data:
            for i, pred_data in enumerate(index_predictions_data):
                
                # 验证并标准化 trend_direction
                trend_direction = pred_data.get('trend_direction', 'SIDEWAYS')
                if isinstance(trend_direction, str):
                    trend_direction = trend_direction.split('(')[0].strip().upper()
                    if trend_direction not in ['UP', 'DOWN', 'SIDEWAYS']:
                        logger.warning(f"  - 无效的 trend_direction: {pred_data.get('trend_direction')}，重置为 SIDEWAYS")
                        trend_direction = 'SIDEWAYS'
                else:
                    logger.warning(f"  - trend_direction 不是字符串: {type(trend_direction)}，重置为 SIDEWAYS")
                    trend_direction = 'SIDEWAYS'
                
                prediction = IndexPrediction(
                    ts_code=pred_data.get('ts_code', ''),
                    name=pred_data.get('name', ''),
                    trend_direction=trend_direction,
                    prediction_reason=pred_data.get('prediction_reason', '')
                )
                predictions.append(prediction)
                logger.info(f"  - 添加预测: {prediction.ts_code} -> {prediction.trend_direction}")
        
        # 如果没有返回数据，创建默认的空预测
        if not predictions:
            logger.warning(f"[{self.agent_id}] index_predictions 为空！使用默认 SIDEWAYS 预测")
            logger.warning(f"  - synthesis_result 完整内容: {synthesis_result}")
            
            for code in self.INDEX_CODES:
                predictions.append(IndexPrediction(
                    ts_code=code,
                    name=INDEX_NAMES.get(code, code),
                    trend_direction='SIDEWAYS',
                    prediction_reason=''
                ))
        
        logger.info(f"[{self.agent_id}] 最终预测结果: {[(p.ts_code, p.trend_direction) for p in predictions]}")
        return predictions
    