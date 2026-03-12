"""
选股分析师 Agent

StockSelectionAgent: 基于大盘/板块分析报告，从股票池选出10支股票

特点：
- 使用 ReAct 架构（Thought-Action-Observation）
- 只读大盘/板块分析师的短期记忆
- 使用工作记忆存储中间结果
- 不存储自己的短期/长期记忆
"""
import json
import re
import logging
from datetime import date, datetime
from typing import Dict, Any, Optional, List

from agents.base.base_agent import BaseAgent, AgentConfig, AgentResult, AgentType
from agents.base.agent_registry import AgentRegistry
from agents.agent_config import get_agent_config
from data.schemas.selection_schema import (
    StockSelectionReport, FocusedSector, CandidateStock, 
    SelectedStock, SelectionThought
)

logger = logging.getLogger(__name__)


@AgentRegistry.register
class StockSelectionAgent(BaseAgent):
    """
    选股分析师
    
    基于 ReAct 架构，从股票池中选出10支股票
    
    输入数据格式：
    {
        "trade_date": "2026-03-09",
        "pool_types": ["SHORT", "MID"]  # 可选，默认 ["SHORT"]
    }
    
    输出：StockSelectionReport
    
    注意：选股分析师不需要复盘，因此不存储长期记忆
    """
    
    agent_type = AgentType.SELECTION
    
    # 允许使用的工具白名单
    ALLOWED_TOOLS = {
        "read_analysis_report",
        "query_stock_pool",
        "query_stocks_by_sector",
        "get_stock_detail",
        "match_sector_name",
        "record_thought"
    }
    
    # 工作记忆键名常量
    WM_KEY_PREFIX = "stock_analysis_"  # stock_analysis_<ts_code>
    WM_KEY_CANDIDATES = "candidate_stocks"
    WM_KEY_ANALYSIS_STAGE = "analysis_stage"  # "collecting_candidates", "analyzing_stocks", "comparing_selection"
    WM_KEY_VERIFIED_STOCKS = "verified_stocks"
    
    # 多轮筛选相关键名
    WM_KEY_SHORTLIST = "shortlist_stocks"       # 优选池（通过筛选的股票）
    WM_KEY_ROUND_NUM = "current_round"          # 当前轮次
    WM_KEY_PENDING_POOL = "pending_stocks"      # 待处理股票列表
    WM_KEY_POOL_INFO = "pool_info"              # 股票池信息（记录每支股票的来源）
    WM_KEY_FOCUSED_SECTORS = "focused_sectors"  # 阶段1识别的热点板块列表
    WM_KEY_MARKET_SUMMARY = "market_summary"    # 阶段1生成的市场观点总结
    
    
    def __init__(
        self,
        agent_id: str = None,
        config: AgentConfig = None,
        memory_manager: Any = None,
        llm_client: Any = None,
        tool_registry: Any = None,
    ):
        # 从配置管理器获取选股分析师专属配置
        try:
            agent_settings = get_agent_config().get_selection_analyst_settings()
            selection_config = agent_settings.selection
        except Exception as e:
            logger.warning(f"无法加载选股分析师配置，使用默认值: {e}")
            selection_config = None
        
        # 默认配置 - 注意：选股分析师不需要保存短期记忆，因为这会与复盘逻辑冲突
        if config is None:
            # 从配置文件读取 LLM 设置
            if selection_config and hasattr(agent_settings, 'llm'):
                llm_settings = agent_settings.llm
                config = AgentConfig(
                    name=agent_settings.name or "选股分析师",
                    description=agent_settings.description or "基于大盘/板块分析报告，从股票池选出优质股票",
                    model=llm_settings.model or "deepseek-reasoner",
                    temperature=llm_settings.temperature or 0.3,
                    max_tokens=llm_settings.max_tokens or 4000,
                    memory_enabled=False  # 不保存到短期记忆
                )
            else:
                config = AgentConfig(
                    name="选股分析师",
                    description="基于大盘/板块分析报告，从股票池选出优质股票",
                    model="deepseek-reasoner",
                    temperature=0.3,  # 较低温度，减少随机性
                    max_tokens=4000,
                    memory_enabled=False  # 不保存到短期记忆
                )
        
        super().__init__(agent_id, config, memory_manager, llm_client, tool_registry)
        
        # 从配置文件读取选股参数，如果配置加载失败则使用硬编码默认值
        if selection_config:
            self._max_iterations = selection_config.max_iterations
            self._candidate_pool_threshold = selection_config.candidate_pool_threshold
            self._comparison_batch_size = selection_config.comparison.batch_size
            self._comparison_select_size = selection_config.comparison.select_size
            self._final_selection_threshold = selection_config.comparison.final_threshold
            self._final_selection_size = selection_config.comparison.final_size
            self._max_retries = selection_config.retry.max_retries
            logger.info(f"[{self.agent_id}] 从配置文件加载选股参数: max_iterations={self._max_iterations}, "
                       f"candidate_threshold={self._candidate_pool_threshold}, "
                       f"batch_size={self._comparison_batch_size}, "
                       f"final_size={self._final_selection_size}")
        else:
            # 配置加载失败时的硬编码默认值
            self._max_iterations = 25
            self._candidate_pool_threshold = 25
            self._comparison_batch_size = 5
            self._comparison_select_size = 2
            self._final_selection_threshold = 20
            self._final_selection_size = 10
            self._max_retries = 2
            logger.warning(f"[{self.agent_id}] 使用硬编码默认值")
        
        # 初始化状态
        self._trajectory: List[Dict] = []  # 历史轨迹
        self._thoughts: List[SelectionThought] = []  # 思考记录
        self._candidate_pool: set = set()  # 候选股票池（用于校验，存放所有合法股票代码）
        self._error_feedback: str = ""  # 错误反馈
        
        # 逐股票分析相关状态
        self._stocks_to_analyze: List[str] = []  # 待分析的股票代码列表
        self._current_stock_index: int = 0  # 当前分析的股票索引
        self._stock_analyses: Dict[str, Dict] = {}  # 股票分析结果缓存
        self._analysis_retry_count: Dict[str, int] = {}  # 每个股票的重试次数
        
        # 多轮筛选相关状态
        self._shortlist: List[str] = []  # 优选池（通过筛选的股票代码）
        self._pending_stocks: List[str] = []  # 待筛选的股票代码
        self._current_round: int = 0  # 当前筛选轮次
        self._pool_info: Dict[str, Dict] = {}  # 股票池信息 {ts_code: {pool_type, sector, model_rank}}
        
        # 注册工具（如未注册则自动注册）
        self._ensure_tools_registered()
    
    def _ensure_tools_registered(self) -> None:
        """确保选股工具已注册，若缺失则抛出异常"""
        if self._tool_registry is None:
            return
        
        # 检查关键工具是否存在
        if not self._tool_registry.get("read_analysis_report"):
            try:
                from core.tools.selection_tools import register_selection_tools
                register_selection_tools(self._tool_registry)
                logger.info("选股工具自动注册完成")
            except Exception as e:
                # 自动注册失败，抛出异常避免运行时找不到工具
                raise RuntimeError(f"选股工具自动注册失败: {e}")
    
    def validate_input(self, input_data: Dict[str, Any]) -> Optional[str]:
        """验证输入数据"""
        trade_date = input_data.get('trade_date')
        if not trade_date:
            return "缺少必需参数: trade_date"
        
        try:
            datetime.strptime(trade_date, '%Y-%m-%d')
        except ValueError:
            return f"日期格式错误: {trade_date}，应为 YYYY-MM-DD"
        
        pool_types = input_data.get('pool_types', ['SHORT'])
        valid_types = {'SHORT', 'MID', 'LONG', 'WHITE_HORSE'}
        for pt in pool_types:
            if pt.upper() not in valid_types:
                return f"无效的 pool_type: {pt}，应为 {valid_types}"
        
        return None
    
    def analyze(self, input_data: Dict[str, Any], context: Dict[str, Any] = None) -> AgentResult:
        """
        执行选股分析（三阶段ReAct循环）
        
        阶段1: 收集候选股票
        阶段2: 逐股票详细分析，存储到Working Memory
        阶段3: 比较和最终选股
        
        流程：
        1. 获取当前分析阶段
        2. 构建特定阶段的Prompt
        3. 调用 LLM（JSON Mode）
        4. 解析响应
        5. 检查是否完成
        6. 验证工具名称
        7. 执行工具
        8. 处理工具结果（包括验证和重试）
        9. 更新工作记忆
        """
        context = context or {}
        session_id = context.get('session_id')
        trade_date = input_data.get('trade_date', date.today().isoformat())
        pool_types = input_data.get('pool_types', ['SHORT', 'MID', 'LONG', 'WHITE_HORSE'])
        
        # 初始化工作记忆
        if session_id and self._memory_manager:
            self._memory_manager.working_memory.set(
                session_id, "init", {
                    "trade_date": trade_date,
                    "pool_types": pool_types,
                    "start_time": datetime.now().isoformat()
                }
            )
            # 设置初始分析阶段
            if not self._memory_manager.working_memory.get(session_id, self.WM_KEY_ANALYSIS_STAGE):
                self._memory_manager.working_memory.set(
                    session_id, self.WM_KEY_ANALYSIS_STAGE, "collecting_candidates"
                )
        
        # 获取当前分析阶段
        current_stage = "collecting_candidates"
        if session_id and self._memory_manager:
            current_stage = self._memory_manager.working_memory.get(
                session_id, self.WM_KEY_ANALYSIS_STAGE
            ) or "collecting_candidates"
        
        logger.info(f"[{self.agent_id}] 开始分析，当前阶段: {current_stage}")
        
        # ReAct 循环
        for iteration in range(self._max_iterations):
            logger.info(f"[{self.agent_id}] ReAct 迭代 {iteration + 1}/{self._max_iterations} | 阶段: {current_stage}")
            
            # 检查是否需要初始化逐股票分析阶段
            if current_stage == "collecting_candidates" and len(self._candidate_pool) >= 25:
                logger.info(f"[{self.agent_id}] 候选股票收集完成，共 {len(self._candidate_pool)} 支，切换到逐股票分析阶段")
                self._initialize_stock_analysis_stage(session_id)
                current_stage = "analyzing_stocks"
                if session_id and self._memory_manager:
                    self._memory_manager.working_memory.set(
                        session_id, self.WM_KEY_ANALYSIS_STAGE, current_stage
                    )
            
            # 处理逐股票分析阶段 - 使用独立循环，不消耗主 ReAct 迭代
            if current_stage == "analyzing_stocks":
                logger.info(f"[{self.agent_id}] 进入阶段2独立循环，待分析股票: {len(self._stocks_to_analyze)} 支")
                
                # 阶段2：独立循环处理所有股票，不消耗主迭代次数
                while self._current_stock_index < len(self._stocks_to_analyze):
                    ts_code = self._stocks_to_analyze[self._current_stock_index]
                    thought = f"分析第 {self._current_stock_index + 1}/{len(self._stocks_to_analyze)} 支股票: {ts_code}"
                    logger.info(f"[{self.agent_id}] {thought}")
                    
                    # 检查是否已在工作记忆中（跳过已分析的）
                    if session_id and self._memory_manager:
                        wm_key = f"{self.WM_KEY_PREFIX}{ts_code}"
                        existing_analysis = self._memory_manager.working_memory.get(session_id, wm_key)
                        if existing_analysis:
                            logger.info(f"[{self.agent_id}] 股票 {ts_code} 已有分析结果，跳过")
                            self._stock_analyses[ts_code] = existing_analysis
                            self._current_stock_index += 1
                            continue
                    
                    # 执行工具获取股票详情
                    tool_params = {"ts_codes": [ts_code], "trade_date": trade_date}
                    tool_result = self._execute_tool_strict("get_stock_detail", tool_params)
                    
                    # 处理工具结果
                    success = self._handle_stock_detail_result(ts_code, tool_result, session_id)
                    if success:
                        # 分析成功，检查一致性
                        stock_analysis = self._stock_analyses.get(ts_code, {})
                        candidate_stock_info = self._get_candidate_stock_info(ts_code)
                        verification = self._verify_stock_analysis_consistency(stock_analysis, candidate_stock_info)
                        
                        if not verification["consistent"]:
                            logger.warning(f"[{self.agent_id}] 股票 {ts_code} 分析不一致: {verification['issues']}")
                            
                            if verification["needs_retry"] and self._should_retry_stock_analysis(ts_code):
                                # 需要重试，不递增索引，下次继续分析同一支股票
                                logger.info(f"[{self.agent_id}] 股票 {ts_code} 需要重试")
                                continue
                            else:
                                # 不需要重试或已达到最大重试次数，继续下一支股票
                                logger.warning(f"[{self.agent_id}] 股票 {ts_code} 数据有问题但继续: {verification['issues']}")
                        else:
                            # 分析一致，记录成功
                            logger.debug(f"[{self.agent_id}] 股票 {ts_code} 分析完成")
                    else:
                        # 工具执行失败，检查是否需要重试
                        if self._should_retry_stock_analysis(ts_code):
                            logger.info(f"[{self.agent_id}] 股票 {ts_code} 详情获取失败，重试中")
                            continue
                        else:
                            # 达到最大重试次数，跳过这支股票
                            logger.warning(f"[{self.agent_id}] 股票 {ts_code} 详情获取失败，跳过")
                    
                    # 移动到下一支股票
                    self._current_stock_index += 1
                
                # 阶段2完成，切换到阶段3（多轮筛选）
                logger.info(f"[{self.agent_id}] 阶段2完成，已分析 {len(self._stock_analyses)} 支股票，切换到多轮筛选阶段")
                current_stage = "comparing_selection"
                if session_id and self._memory_manager:
                    self._memory_manager.working_memory.set(
                        session_id, self.WM_KEY_ANALYSIS_STAGE, current_stage
                    )
                
                # 执行多轮筛选
                while True:
                    round_result = self._run_comparison_round(session_id, trade_date)
                    
                    if round_result is None:
                        # 筛选完成，获取最终结果
                        final_selection = None
                        if session_id and self._memory_manager:
                            final_selection = self._memory_manager.working_memory.get(session_id, "final_selection")
                        
                        if final_selection:
                            # 构建最终结果
                            return self._build_final_result_from_selection(trade_date, final_selection, session_id)
                        elif len(self._shortlist) > 0:
                            # 优选池数量合适，直接构建结果
                            return self._build_final_result_from_shortlist(trade_date, session_id)
                        else:
                            logger.error(f"[{self.agent_id}] 多轮筛选完成但没有结果")
                            return self._build_timeout_result(trade_date, session_id)
                    
                    # 检查是否需要继续
                    if not round_result.get("continue"):
                        break
                
                # 如果多轮筛选没有完成，继续主循环
                continue
            
            # 1. 构建 Prompt（包含当前阶段信息）
            prompt = self._build_stage_prompt(trade_date, pool_types, session_id, current_stage)
            
            # 2. 调用 LLM（JSON Mode）
            try:
                response = self._call_llm_json(prompt)
            except Exception as e:
                logger.error(f"LLM 调用失败: {e}")
                self._error_feedback = "LLM 响应解析失败，请确保输出合法 JSON"
                continue
            
            # 3. 解析响应
            parsed = self._parse_response(response)
            if not parsed:
                self._error_feedback = "响应格式错误，请输出合法的 JSON（包含 thought 和 finish/next_action）"
                continue
            
            # 4. 记录思考
            thought = parsed.get("thought", "")
            if thought:
                self._add_thought(trade_date, thought, "analysis")
            
            # 4.5 存储市场观点总结（如果阶段1输出了 market_summary）
            market_summary = parsed.get("market_summary")
            if market_summary and session_id and self._memory_manager:
                self._memory_manager.working_memory.set(
                    session_id, self.WM_KEY_MARKET_SUMMARY, market_summary
                )
                logger.info(f"[{self.agent_id}] 存储市场观点总结到工作记忆（长度: {len(market_summary)}）")
            
            # 5. 检查是否完成
            if parsed.get("finish"):
                return self._build_final_result(trade_date, parsed, session_id)
            
            # 6. 验证并执行工具
            next_action = parsed.get("next_action", {})
            tool_name = next_action.get("tool")
            tool_params = next_action.get("params", {})
            
            # 工具名称校验
            if not self._is_valid_tool(tool_name):
                self._error_feedback = f"工具 '{tool_name}' 不存在，可用工具: {list(self.ALLOWED_TOOLS)}"
                self._add_trajectory(thought, tool_name, tool_params, None, self._error_feedback)
                continue
            
            # 执行工具（并自动传递 trade_date 到工具参数中）
            if "trade_date" not in tool_params and tool_name in ["get_stock_detail"]:
                tool_params["trade_date"] = trade_date
            tool_result = self._execute_tool_strict(tool_name, tool_params)
            
            # 7. 更新候选池（如果工具返回了股票列表）
            if tool_name in ["query_stock_pool", "query_stocks_by_sector"]:
                self._update_candidate_pool(tool_result, session_id)
            
            # 8. 更新轨迹
            observation = json.dumps(tool_result, ensure_ascii=False, indent=2)
            self._add_trajectory(thought, tool_name, tool_params, tool_params, observation)
            
            # 9. 更新工作记忆
            if session_id and self._memory_manager:
                self._memory_manager.working_memory.set(
                    session_id, f"step_{iteration}", {
                        "thought": thought,
                        "action": tool_name,
                        "params": tool_params,
                        "observation": observation
                    }
                )
                # 同时存储候选池到工作记忆
                self._memory_manager.working_memory.set(
                    session_id, "candidate_pool", list(self._candidate_pool)
                )
            
            # 清空错误反馈
            self._error_feedback = ""
        
        # 达到最大迭代次数
        logger.warning(f"[{self.agent_id}] 达到最大迭代次数 {self._max_iterations}")
        return self._build_timeout_result(trade_date, session_id)
    
    def _build_prompt(self, trade_date: str, pool_types: List[str], session_id: str) -> str:
        """构建 Prompt"""
        from agents.analysis.selection.selection_prompts import build_react_prompt
        return build_react_prompt(
            trade_date=trade_date,
            pool_types=pool_types,
            trajectory=self._trajectory,
            error_feedback=self._error_feedback,
            working_memory=self._get_memory_summary(session_id)
        )
    
    def _call_llm_json(self, prompt: str) -> Dict:
        """调用 LLM（强制 JSON 输出）- 增强版解析"""
        from agents.analysis.selection.selection_prompts import SYSTEM_PROMPT_SELECTION
        
        response = self.call_llm(prompt=prompt, system_prompt=SYSTEM_PROMPT_SELECTION)
        
        # 记录原始响应用于调试
        logger.debug(f"[{self.agent_id}] LLM 原始响应 (前500字符): {response[:500] if response else '空'}")
        
        if not response or not response.strip():
            raise ValueError("LLM 返回空响应")
        
        # 多层 JSON 提取策略
        json_str = None
        
        # 策略1: 提取 ```json ... ``` 代码块
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
        if json_match:
            json_str = json_match.group(1).strip()
            logger.debug(f"[{self.agent_id}] 使用策略1 (```json```块) 提取JSON")
        
        # 策略2: 提取 ``` ... ``` 代码块（无json标记）
        if not json_str:
            json_match = re.search(r'```\s*([\s\S]*?)\s*```', response)
            if json_match:
                candidate = json_match.group(1).strip()
                # 检查是否以 { 开头
                if candidate.startswith('{'):
                    json_str = candidate
                    logger.debug(f"[{self.agent_id}] 使用策略2 (```块) 提取JSON")
        
        # 策略3: 查找第一个 { 和最后一个 } 之间的内容
        if not json_str:
            first_brace = response.find('{')
            last_brace = response.rfind('}')
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                json_str = response[first_brace:last_brace + 1].strip()
                logger.debug(f"[{self.agent_id}] 使用策略3 (花括号匹配) 提取JSON")
        
        # 策略4: 直接使用原始响应
        if not json_str:
            json_str = response.strip()
            logger.debug(f"[{self.agent_id}] 使用策略4 (原始响应) 尝试解析JSON")
        
        # 尝试解析 JSON
        try:
            result = json.loads(json_str)
            if not isinstance(result, dict):
                raise ValueError(f"JSON 不是字典类型: {type(result)}")
            return result
        except json.JSONDecodeError as e:
            # 尝试修复常见的 JSON 错误
            try:
                # 修复1: 移除可能的尾部逗号
                fixed_str = re.sub(r',\s*([}\]])', r'\1', json_str)
                result = json.loads(fixed_str)
                logger.info(f"[{self.agent_id}] JSON 修复成功 (移除尾部逗号)")
                return result
            except:
                pass
            
            # 修复2: 尝试替换单引号为双引号
            try:
                fixed_str = json_str.replace("'", '"')
                result = json.loads(fixed_str)
                logger.info(f"[{self.agent_id}] JSON 修复成功 (单引号替换)")
                return result
            except:
                pass
            
            # 修复3: 尝试修复缺少逗号的情况（在 } 和 { 之间，或 ] 和 [ 之间）
            try:
                fixed_str = re.sub(r'(\})\s*(\{)', r'\1,\2', json_str)
                fixed_str = re.sub(r'(\])\s*(\[)', r'\1,\2', fixed_str)
                fixed_str = re.sub(r'(\})\s*(\[)', r'\1,\2', fixed_str)
                fixed_str = re.sub(r'(\])\s*(\{)', r'\1,\2', fixed_str)
                result = json.loads(fixed_str)
                logger.info(f"[{self.agent_id}] JSON 修复成功 (添加缺失逗号)")
                return result
            except:
                pass
            
            # 修复4: 移除控制字符和无效空白
            try:
                import string
                # 移除控制字符（保留换行和制表符）
                fixed_str = ''.join(char for char in json_str if char in string.printable or char in '\n\r\t')
                result = json.loads(fixed_str)
                logger.info(f"[{self.agent_id}] JSON 修复成功 (移除控制字符)")
                return result
            except:
                pass
            
            # 修复5: 尝试修复被截断的JSON（找到最后一个完整的对象）
            try:
                # 尝试找到可以成功解析的最小有效JSON前缀
                for i in range(len(json_str) - 1, 0, -1):
                    if json_str[i] in '}]':
                        try:
                            test_str = json_str[:i+1]
                            # 尝试闭合未完成的JSON
                            open_braces = test_str.count('{') - test_str.count('}')
                            open_brackets = test_str.count('[') - test_str.count(']')
                            if open_braces >= 0 and open_brackets >= 0:
                                closed_str = test_str + ']' * open_brackets + '}' * open_braces
                                result = json.loads(closed_str)
                                logger.info(f"[{self.agent_id}] JSON 修复成功 (截断修复，位置 {i})")
                                return result
                        except:
                            continue
            except:
                pass
            
            logger.error(f"[{self.agent_id}] JSON 解析失败，原始内容长度: {len(json_str)}, 前500字符: {json_str[:500]}")
            raise ValueError(f"LLM 响应不是合法的 JSON: {str(e)}, 内容片段: {json_str[:200]}")
    
    def _parse_response(self, response: Dict) -> Optional[Dict]:
        """解析 LLM 响应 - 增强版验证"""
        if not isinstance(response, dict):
            logger.warning(f"[{self.agent_id}] 响应不是字典类型: {type(response)}")
            return None
        
        # 1. 检查 thought 字段（必需，但可以宽松处理）
        thought = response.get("thought")
        if not thought:
            # 尝试其他可能的字段名
            thought = response.get("thinking") or response.get("reasoning") or response.get("analysis")
            if thought:
                response["thought"] = thought
                logger.debug(f"[{self.agent_id}] 使用备用字段作为 thought")
            else:
                logger.warning(f"[{self.agent_id}] 响应缺少 thought 字段")
                return None
        
        # 2. 检查 finish 标志（宽松处理）
        finish = response.get("finish")
        if finish is None:
            # 尝试其他可能的字段名
            finish = response.get("done") or response.get("completed") or response.get("is_finished")
            if finish is not None:
                response["finish"] = finish
                logger.debug(f"[{self.agent_id}] 使用备用字段作为 finish: {finish}")
        
        # 处理字符串类型的 finish 值
        if isinstance(finish, str):
            finish = finish.lower() in ["true", "yes", "1", "完成"]
            response["finish"] = finish
        
        # 3. 检查 next_action（宽松处理）
        next_action = response.get("next_action")
        if next_action is None:
            # 尝试其他可能的字段名
            next_action = response.get("action") or response.get("tool_call") or response.get("call")
            if next_action:
                response["next_action"] = next_action
                logger.debug(f"[{self.agent_id}] 使用备用字段作为 next_action")
        
        # 4. 验证：必须有 finish=true 或 next_action
        if not response.get("finish") and not response.get("next_action"):
            # 特殊情况：如果有 final_result，认为是完成
            if response.get("final_result"):
                response["finish"] = True
                logger.debug(f"[{self.agent_id}] 检测到 final_result，自动设置 finish=True")
            else:
                logger.warning(f"[{self.agent_id}] 响应缺少 finish 和 next_action 字段")
                return None
        
        # 5. 验证 next_action 结构（如果存在）
        if response.get("next_action"):
            na = response["next_action"]
            if not isinstance(na, dict):
                logger.warning(f"[{self.agent_id}] next_action 不是字典类型: {type(na)}")
                # 尝试修复
                if isinstance(na, str):
                    try:
                        response["next_action"] = json.loads(na)
                    except:
                        return None
                else:
                    return None
            
            # 检查 tool 字段
            if not na.get("tool"):
                logger.warning(f"[{self.agent_id}] next_action 缺少 tool 字段")
                return None
            
            # 确保 params 存在
            if "params" not in na:
                na["params"] = {}
                logger.debug(f"[{self.agent_id}] next_action 缺少 params，已自动补充空字典")
        
        return response
    
    def _is_valid_tool(self, tool_name: str) -> bool:
        """验证工具名称"""
        return tool_name in self.ALLOWED_TOOLS
    
    def _execute_tool_strict(self, tool_name: str, params: Dict) -> Dict:
        """严格模式执行工具"""
        try:
            result = self.call_tool(tool_name, **params)
            
            if hasattr(result, 'is_success'):
                return {
                    "success": result.is_success,
                    "data": result.data,
                    "error": result.error
                }
            else:
                return {"success": True, "data": result}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _update_candidate_pool(self, tool_result: Dict, session_id: str = None) -> None:
        """从工具执行结果中提取股票代码，加入候选池，同时保存股票池信息
        
        同时会将板块查询的热点板块存储到工作记忆中
        """
        if not tool_result.get("success"):
            return
        data = tool_result.get("data", {})
        if "results" in data:  # query_stock_pool 返回格式
            for pool_type, stocks in data["results"].items():
                for s in stocks:
                    ts_code = s["ts_code"]
                    self._candidate_pool.add(ts_code)
                    # 保存股票池信息（pool_type, model_rank）
                    self._pool_info[ts_code] = {
                        "pool_type": pool_type,
                        "model_rank": s.get("model_rank", 0),
                        "sector": "",  # 稍后从股票详情中获取
                        "source": "stock_pool"
                    }
        if "stocks" in data:   # query_stocks_by_sector 返回格式
            # 收集本次查询的热点板块
            queried_sectors = {}
            for s in data["stocks"]:
                ts_code = s["ts_code"]
                self._candidate_pool.add(ts_code)
                # 保存股票池信息（pool_type, model_rank, sector）
                # 如果已存在，保留原有信息；如果不存在，添加新信息
                if ts_code not in self._pool_info:
                    self._pool_info[ts_code] = {
                        "pool_type": s.get("pool_type", "UNKNOWN"),
                        "model_rank": s.get("model_rank", 0),
                        "sector": s.get("sector_name", ""),
                        "source": "sector_query"
                    }
                else:
                    # 更新板块信息（如果原来没有）
                    if not self._pool_info[ts_code].get("sector") and s.get("sector_name"):
                        self._pool_info[ts_code]["sector"] = s.get("sector_name", "")
                
                # 收集板块信息
                sector_name = s.get("sector_name", "")
                sector_code = s.get("sector_code", "")
                if sector_name and sector_name not in queried_sectors:
                    queried_sectors[sector_name] = sector_code
            
            # 存储热点板块到工作记忆
            if session_id and self._memory_manager and queried_sectors:
                existing_sectors = self._memory_manager.working_memory.get(
                    session_id, self.WM_KEY_FOCUSED_SECTORS
                ) or {}
                # 合并新板块
                existing_sectors.update(queried_sectors)
                self._memory_manager.working_memory.set(
                    session_id, self.WM_KEY_FOCUSED_SECTORS, existing_sectors
                )
                logger.info(f"[{self.agent_id}] 存储热点板块到工作记忆: {list(queried_sectors.keys())}")
    
    def _add_trajectory(self, thought: str, action: str, params: Dict, input_data: Any, observation: str) -> None:
        """添加到轨迹"""
        self._trajectory.append({
            "thought": thought,
            "action": action,
            "params": params,
            "observation": observation
        })
    
    def _add_thought(self, trade_date: str, thought: str, category: str) -> None:
        """添加思考记录"""
        self._thoughts.append(SelectionThought(
            trade_date=trade_date,
            step=len(self._thoughts) + 1,
            thought=thought,
            category=category
        ))
    
    def _initialize_stock_analysis_stage(self, session_id: str) -> None:
        """初始化逐股票分析阶段
        
        注意：无论 session_id 是否有效，都要初始化股票分析列表
        - session_id 有效时：同时更新 Working Memory
        - session_id 无效时：只初始化内部状态，不更新 Working Memory
        """
        # 无论 session_id 是否为 None，都要初始化分析列表
        self._stocks_to_analyze = list(self._candidate_pool)
        self._current_stock_index = 0
        self._stock_analyses.clear()
        self._analysis_retry_count.clear()
        
        # 只有 session_id 和 memory_manager 有效时才更新 Working Memory
        if session_id and self._memory_manager:
            self._memory_manager.working_memory.set(
                session_id, self.WM_KEY_ANALYSIS_STAGE, "analyzing_stocks"
            )
        
        logger.info(f"[{self.agent_id}] 初始化逐股票分析阶段，共 {len(self._stocks_to_analyze)} 支待分析股票")
    
    def _process_single_stock_analysis(self, session_id: str, trade_date: str) -> Optional[Dict]:
        """处理单支股票分析
        
        返回 None 表示分析阶段结束，可以继续下一个阶段
        返回 Dict 表示需要调用工具继续分析当前股票
        """
        if self._current_stock_index >= len(self._stocks_to_analyze):
            # 所有股票分析完成，进入下一个阶段
            if session_id and self._memory_manager:
                self._memory_manager.working_memory.set(
                    session_id, self.WM_KEY_ANALYSIS_STAGE, "comparing_selection"
                )
            return None
        
        ts_code = self._stocks_to_analyze[self._current_stock_index]
        
        # 检查是否已在工作记忆中
        if session_id and self._memory_manager:
            wm_key = f"{self.WM_KEY_PREFIX}{ts_code}"
            existing_analysis = self._memory_manager.working_memory.get(session_id, wm_key)
            if existing_analysis:
                logger.info(f"[{self.agent_id}] 股票 {ts_code} 已有分析结果，跳过")
                self._stock_analyses[ts_code] = existing_analysis
                self._current_stock_index += 1
                return self._process_single_stock_analysis(session_id, trade_date)
        
        # 构建获取股票详情的工具调用
        return {
            "tool": "get_stock_detail",
            "params": {
                "ts_codes": [ts_code],
                "trade_date": trade_date
            }
        }
    
    def _handle_stock_detail_result(self, ts_code: str, tool_result: Dict, session_id: str) -> bool:
        """处理股票详情工具结果（增强版）
        
        返回 True 表示分析成功，可以继续下一个股票
        返回 False 表示需要重试
        """
        if not tool_result.get("success"):
            logger.warning(f"[{self.agent_id}] 股票 {ts_code} 详情获取失败: {tool_result.get('error')}")
            return False
        
        data = tool_result.get("data", {})
        stocks = data.get("stocks", [])
        if not stocks:
            logger.warning(f"[{self.agent_id}] 股票 {ts_code} 未找到详情数据")
            return False
        
        stock_data = stocks[0]
        
        # 验证关键字段
        required_fields = ["ts_code", "name", "industry", "total_mv", "pe"]
        missing_fields = [field for field in required_fields if field not in stock_data]
        if missing_fields:
            logger.warning(f"[{self.agent_id}] 股票 {ts_code} 缺少关键字段: {missing_fields}")
            return False
        
        # 获取股票池信息（pool_type 和 model_rank 来自股票池查询，不是 LLM 编造）
        pool_info = self._pool_info.get(ts_code, {})
        
        # 构建增强版分析结果
        analysis = {
            # 基本信息
            "ts_code": stock_data["ts_code"],
            "name": stock_data["name"],
            "industry": stock_data["industry"],
            "market": stock_data.get("market", ""),
            "list_date": stock_data.get("list_date", ""),
            
            # 股票池信息（来自 _pool_info，确保数据真实可靠）
            "pool_type": pool_info.get("pool_type", "UNKNOWN"),
            "model_rank": pool_info.get("model_rank", 0),
            
            # 估值数据
            "total_mv": stock_data["total_mv"],
            "circ_mv": stock_data.get("circ_mv", 0),
            "pe": stock_data["pe"],
            "pb": stock_data.get("pb", 0),
            "ps": stock_data.get("ps", 0),
            
            # 财务指标
            "eps": stock_data.get("eps", 0),
            "bvps": stock_data.get("bvps", 0),
            "dv_ttm": stock_data.get("dv_ttm", 0),
            "revenue_yoy": stock_data.get("revenue_yoy", 0),
            "profit_yoy": stock_data.get("profit_yoy", 0),
            "debt_to_assets": stock_data.get("debt_to_assets", 0),
            "current_ratio": stock_data.get("current_ratio", 0),
            
            # 技术指标
            "technical": stock_data.get("technical", {}),
            
            # 3日价格历史
            "price_history": stock_data.get("price_history", []),
            
            "analysis_time": datetime.now().isoformat()
        }
        
        # 存储到缓存和工作记忆
        self._stock_analyses[ts_code] = analysis
        if session_id and self._memory_manager:
            wm_key = f"{self.WM_KEY_PREFIX}{ts_code}"
            self._memory_manager.working_memory.set(session_id, wm_key, analysis)
        
        logger.info(f"[{self.agent_id}] 股票 {ts_code} 分析完成（含技术指标和3日价格数据）并保存到工作记忆")
        return True
    
    def _get_stock_analyses_from_memory(self, session_id: str) -> Dict[str, Dict]:
        """从工作记忆中获取所有股票分析结果"""
        analyses = {}
        if not session_id or not self._memory_manager:
            return analyses
        
        memory = self._memory_manager.working_memory.get_all(session_id)
        for key, value in memory.items():
            if key.startswith(self.WM_KEY_PREFIX):
                ts_code = key.replace(self.WM_KEY_PREFIX, "")
                analyses[ts_code] = value
        
        return analyses
    
    def _verify_stock_analysis_consistency(self, stock_analysis: Dict, candidate_stock_info: Dict) -> Dict[str, Any]:
        """验证股票分析结果的一致性
        
        返回验证结果字典：
        {
            "consistent": True/False,
            "issues": ["问题描述列表"],
            "needs_retry": True/False
        }
        """
        issues = []
        
        # 获取基本信息
        ts_code = stock_analysis.get("ts_code", "")
        industry = stock_analysis.get("industry", "")
        candidate_sector = candidate_stock_info.get("sector", "")
        
        # 1. 检查行业/板块一致性
        if candidate_sector and industry:
            # 简单检查：如果行业包含板块关键词，或板块包含行业关键词
            if candidate_sector not in industry and industry not in candidate_sector:
                issues.append(f"行业/板块不一致: 数据库行业='{industry}', 候选股票板块='{candidate_sector}'")
        
        # 2. 检查估值数据合理性
        pe = stock_analysis.get("pe", 0)
        # PE为0或负数是正常的（亏损公司），只检查极端正值
        if pe > 1000:  # 极端高估值
            issues.append(f"PE估值异常: {pe}")
        
        pb = stock_analysis.get("pb", 0)
        # PB为负数可能是净资产为负，只检查极端正值
        if pb > 1000:  # 极端市净率
            issues.append(f"PB估值异常: {pb}")
        
        # 3. 检查市值合理性
        total_mv = stock_analysis.get("total_mv", 0)
        if total_mv <= 0:
            issues.append(f"市值异常: {total_mv}亿")
        
        # 判断是否需要重试
        needs_retry = False
        if issues:
            # 如果只是行业/板块不一致，可以继续（可能只是名称格式不同）
            # 如果有估值异常，需要重试
            valuation_issues = [issue for issue in issues if "PE" in issue or "PB" in issue or "市值" in issue]
            if valuation_issues:
                needs_retry = True
        
        return {
            "consistent": len(issues) == 0,
            "issues": issues,
            "needs_retry": needs_retry
        }
    
    def _should_retry_stock_analysis(self, ts_code: str) -> bool:
        """判断是否应该重试股票分析"""
        retry_count = self._analysis_retry_count.get(ts_code, 0)
        if retry_count >= 2:  # 最多重试2次
            logger.warning(f"[{self.agent_id}] 股票 {ts_code} 已达到最大重试次数 ({retry_count})，跳过")
            return False
        
        # 增加重试计数
        self._analysis_retry_count[ts_code] = retry_count + 1
        logger.info(f"[{self.agent_id}] 股票 {ts_code} 第 {retry_count + 1} 次重试")
        return True
    
    def _get_candidate_stock_info(self, ts_code: str) -> Dict[str, Any]:
        """获取候选股票的原始信息（从查询结果中）"""
        # 这个方法需要从工具执行的历史轨迹中提取股票信息
        # 暂时返回一个空字典，实际实现需要从轨迹中解析
        return {
            "ts_code": ts_code,
            "sector": "",  # 暂时留空，需要从轨迹中提取
            "pool_type": "",  # 暂时留空
            "model_rank": 0
        }
    
    def _build_stage_prompt(self, trade_date: str, pool_types: List[str], session_id: str, current_stage: str) -> str:
        """根据当前阶段构建特定的Prompt"""
        from agents.analysis.selection.selection_prompts import build_react_prompt
        
        # 获取阶段特定的工作记忆摘要
        stage_summary = self._get_stage_memory_summary(session_id, current_stage)
        
        # 构建基础Prompt
        base_prompt = build_react_prompt(
            trade_date=trade_date,
            pool_types=pool_types,
            trajectory=self._trajectory,
            error_feedback=self._error_feedback,
            working_memory=stage_summary
        )
        
        # 添加阶段特定说明
        stage_instruction = ""
        if current_stage == "collecting_candidates":
            stage_instruction = """
## 当前阶段：收集候选股票
目标：从四个股票池中获取候选股票（每个池前5名，共20支），并根据板块分析师的推荐查询相关板块的股票。
注意：收集完成后会自动进入逐股票分析阶段。
"""
        elif current_stage == "analyzing_stocks":
            # 逐股票分析阶段，由程序自动处理，不会执行到这里
            stage_instruction = """
## 当前阶段：逐股票详细分析
系统正在自动分析每支候选股票的详细信息。
"""
        elif current_stage == "comparing_selection":
            stock_analyses = self._get_stock_analyses_from_memory(session_id)
            analyzed_count = len(stock_analyses)
            total_candidates = len(self._candidate_pool)
            
            stage_instruction = f"""
## 当前阶段：比较和最终选股
你已经完成了所有候选股票的详细分析：
- 已分析股票: {analyzed_count} / {total_candidates} 支
- 分析结果已存储在工作记忆中（stock_analysis_<ts_code>）

## 选股任务
基于以下信息选择10支最佳股票：
1. 股票池分布：确保从四个股票池（SHORT/MID/LONG/WHITE_HORSE）都选取股票
2. 板块分布：确保包含推荐板块的股票，特别是重点关注板块（目标8-10个板块）的代表性股票
3. 比较分析：基于股票详情（行业、估值、市值等）进行综合比较，优先选择估值合理、成长性好的股票
4. 确保选股覆盖不同板块和股票池类型，实现风险分散

## 可用信息
- 候选股票列表：工作记忆中的 "candidate_pool"
- 每支股票详细分析：工作记忆中的 "stock_analysis_<ts_code>"
- 大盘/板块分析报告：使用 read_analysis_report 工具获取
- 重点关注板块列表：从阶段1中识别的8-10个潜力板块
"""
        
        return stage_instruction + "\n\n" + base_prompt
    
    def _get_stage_memory_summary(self, session_id: str, current_stage: str) -> str:
        """获取特定阶段的工作记忆摘要"""
        if not session_id or not self._memory_manager:
            return "（无）"
        
        memory = self._memory_manager.working_memory.get_all(session_id)
        if not memory:
            return "（无）"
        
        summary = []
        
        if current_stage == "collecting_candidates":
            # 只显示关键信息
            summary.append(f"候选股票数量: {len(self._candidate_pool)} 支")
            
        elif current_stage == "comparing_selection":
            # 显示分析完成的股票数量
            stock_analyses = self._get_stock_analyses_from_memory(session_id)
            summary.append(f"已完成分析: {len(stock_analyses)} / {len(self._candidate_pool)} 支股票")
            
            # 显示每支股票的关键信息（简化）
            for ts_code, analysis in list(stock_analyses.items())[:5]:  # 只显示前5个
                summary.append(f"- {ts_code}: {analysis.get('name', 'N/A')} | 行业: {analysis.get('industry', 'N/A')} | PE: {analysis.get('pe', 0):.1f}")
            
            if len(stock_analyses) > 5:
                summary.append(f"  ... 还有 {len(stock_analyses) - 5} 支股票")
        
        # 显示当前阶段
        summary.insert(0, f"当前阶段: {current_stage}")
        
        return "\n".join(summary) if summary else "（无）"
    
    def _get_memory_summary(self, session_id: str) -> str:
        """获取工作记忆摘要"""
        if not session_id or not self._memory_manager:
            return "（无）"
        
        memory = self._memory_manager.working_memory.get_all(session_id)
        if not memory:
            return "（无）"
        
        # 简化显示
        summary = []
        for key, value in memory.items():
            if key.startswith("step_"):
                continue
            summary.append(f"- {key}: {str(value)[:100]}")
        
        return "\n".join(summary) if summary else "（无）"
    
    def _build_final_result(self, trade_date: str, parsed: Dict, session_id: str) -> AgentResult:
        """构建最终结果"""
        final_data = parsed.get("final_result", {})
        
        # 校验选股结果
        selected_stocks = final_data.get("selected_stocks", [])
        validated_stocks = self._validate_stock_selection(selected_stocks)
        
        # 构建 FocusedSector 列表
        focused_sectors = []
        for fs in final_data.get("focused_sectors", []):
            focused_sectors.append(FocusedSector(
                trade_date=trade_date,
                sector_name=fs.get("sector_name", ""),
                sector_code=fs.get("sector_code", ""),
                reason=fs.get("reason", ""),
                confidence=fs.get("confidence", "medium"),
                capital_flow=fs.get("capital_flow", "")
            ))
        
        # 构建 CandidateStock 列表
        candidate_stocks = []
        for cs in final_data.get("candidate_stocks", []):
            candidate_stocks.append(CandidateStock(
                trade_date=trade_date,
                ts_code=cs.get("ts_code", ""),
                name=cs.get("name", ""),
                pool_type=cs.get("pool_type", ""),
                model_rank=cs.get("model_rank", 0),
                sector=cs.get("sector", ""),
                source=cs.get("source", "")
            ))
        
        # 构建 SelectedStock 列表
        final_selected = []
        for ss in validated_stocks:
            final_selected.append(SelectedStock(
                trade_date=trade_date,
                ts_code=ss.get("ts_code", ""),
                name=ss.get("name", ""),
                pool_type=ss.get("pool_type", ""),
                model_rank=ss.get("model_rank", 0),
                sector=ss.get("sector", ""),
                selection_reason=ss.get("selection_reason", "")
            ))
        
        # 构建报告
        report = StockSelectionReport(
            trade_date=trade_date,
            market_view=final_data.get("market_view", ""),
            sector_focus=focused_sectors,
            candidate_stocks=candidate_stocks,
            selected_stocks=final_selected,
            selection_summary=final_data.get("selection_summary", ""),
            confidence=final_data.get("confidence", 50.0),
            thoughts=self._thoughts
        )
        
        return AgentResult.success_result(report)
    
    def _validate_stock_selection(self, selected_stocks: List[Dict]) -> List[Dict]:
        """验证选股结果，过滤幻觉"""
        validated = []
        
        for stock in selected_stocks:
            ts_code = stock.get("ts_code")
            
            # 1. 检查股票代码格式（仅支持沪深）
            if not re.match(r'^\d{6}\.(SZ|SH)$', ts_code or ""):
                logger.warning(f"无效股票代码格式: {ts_code}")
                continue
            
            # 2. 检查股票是否在候选池中
            if self._candidate_pool and ts_code not in self._candidate_pool:
                logger.warning(f"股票 {ts_code} 不在候选池中，可能是幻觉")
                continue
            
            # 3. 检查必需字段
            required = ["ts_code", "name", "selection_reason"]
            if not all(k in stock for k in required):
                logger.warning(f"股票 {ts_code} 缺少必需字段")
                continue
            
            validated.append(stock)
        
        return validated
    
    def _build_timeout_result(self, trade_date: str, session_id: str) -> AgentResult:
        """构建超时结果"""
        return AgentResult.failure_result(
            f"选股分析超时，已执行 {self._max_iterations} 步"
        )
    
    def _build_final_result_from_selection(self, trade_date: str, selection: Dict, session_id: str) -> AgentResult:
        """从最终选股结果构建AgentResult"""
        stock_analyses = self._get_stock_analyses_from_memory(session_id)
        
        # 构建选中的股票列表
        selected_stocks = []
        for ss in selection.get("selected_stocks", []):
            ts_code = ss.get("ts_code")
            analysis = stock_analyses.get(ts_code, {})
            selected_stocks.append(SelectedStock(
                trade_date=trade_date,
                ts_code=ts_code or "",
                name=analysis.get("name", ss.get("name", "")),
                pool_type=ss.get("pool_type", "UNKNOWN"),
                model_rank=analysis.get("model_rank", 0),
                sector=analysis.get("industry", ""),
                selection_reason=ss.get("reason", "")
            ))
        
        # 获取市场观点和关注板块
        market_view = selection.get("market_view", self._get_market_view_from_memory(session_id))
        focused_sectors = self._build_focused_sectors(trade_date, session_id)
        
        # 构建报告
        report = StockSelectionReport(
            trade_date=trade_date,
            market_view=market_view,
            sector_focus=focused_sectors,
            candidate_stocks=self._build_candidate_stocks(trade_date, session_id),
            selected_stocks=selected_stocks,
            selection_summary=selection.get("summary", "基于多轮筛选完成选股"),
            confidence=selection.get("confidence", 70.0),
            thoughts=self._thoughts
        )
        
        return AgentResult.success_result(report)
    
    def _build_final_result_from_shortlist(self, trade_date: str, session_id: str) -> AgentResult:
        """从优选池直接构建AgentResult（当优选池数量<=10时）"""
        stock_analyses = self._get_stock_analyses_from_memory(session_id)
        
        # 构建选中的股票列表（直接使用优选池）
        selected_stocks = []
        for ts_code in self._shortlist[:self._final_selection_size]:
            analysis = stock_analyses.get(ts_code, {})
            selected_stocks.append(SelectedStock(
                trade_date=trade_date,
                ts_code=ts_code,
                name=analysis.get("name", ""),
                pool_type=self._pool_info.get(ts_code, {}).get("pool_type", "UNKNOWN"),
                model_rank=self._pool_info.get(ts_code, {}).get("model_rank", 0),
                sector=analysis.get("industry", ""),
                selection_reason="通过多轮筛选进入优选池"
            ))
        
        # 获取市场观点和关注板块
        market_view = self._get_market_view_from_memory(session_id)
        focused_sectors = self._build_focused_sectors(trade_date, session_id)
        
        # 构建报告
        report = StockSelectionReport(
            trade_date=trade_date,
            market_view=market_view,
            sector_focus=focused_sectors,
            candidate_stocks=self._build_candidate_stocks(trade_date, session_id),
            selected_stocks=selected_stocks,
            selection_summary=f"通过 {self._current_round} 轮筛选，从 {len(stock_analyses)} 支股票中选出 {len(selected_stocks)} 支",
            confidence=70.0,
            thoughts=self._thoughts
        )
        
        return AgentResult.success_result(report)
    
    def _build_focused_sectors(self, trade_date: str, session_id: str) -> List[FocusedSector]:
        """构建关注板块列表
        
        优先级：
        1. 从工作记忆中获取阶段1存储的热点板块（WM_KEY_FOCUSED_SECTORS）
        2. 从步骤记录中提取板块信息
        3. 使用已覆盖板块（兜底方案）
        """
        focused_sectors = []
        
        if session_id and self._memory_manager:
            # 优先从工作记忆中获取阶段1存储的热点板块
            stored_sectors = self._memory_manager.working_memory.get(
                session_id, self.WM_KEY_FOCUSED_SECTORS
            )
            
            if stored_sectors and isinstance(stored_sectors, dict):
                # 使用存储的热点板块
                for sector_name, sector_code in list(stored_sectors.items())[:10]:
                    focused_sectors.append(FocusedSector(
                        trade_date=trade_date,
                        sector_name=sector_name,
                        sector_code=sector_code,
                        reason="阶段1识别的热点板块",
                        confidence="high",
                        capital_flow=""
                    ))
                logger.info(f"[{self.agent_id}] 使用存储的热点板块: {list(stored_sectors.keys())}")
                return focused_sectors
            
            # 尝试从步骤记录中提取板块信息（旧逻辑，作为备选）
            memory = self._memory_manager.working_memory.get_all(session_id)
            for key, value in memory.items():
                if key.startswith("step_") and isinstance(value, dict):
                    obs = value.get("observation", "")
                    if "sector_name" in obs or "板块" in obs:
                        try:
                            # 尝试解析板块信息
                            data = json.loads(obs) if isinstance(obs, str) and obs.startswith("{") else {}
                            if data.get("focused_sectors"):
                                for fs in data["focused_sectors"][:5]:
                                    focused_sectors.append(FocusedSector(
                                        trade_date=trade_date,
                                        sector_name=fs.get("sector_name", ""),
                                        sector_code=fs.get("sector_code", ""),
                                        reason=fs.get("reason", ""),
                                        confidence=fs.get("confidence", "medium"),
                                        capital_flow=""
                                    ))
                                break
                        except:
                            pass
        
        # 如果没有提取到，使用已覆盖板块（兜底）
        if not focused_sectors:
            stock_analyses = self._get_stock_analyses_from_memory(session_id)
            sectors = self._get_sector_coverage(stock_analyses)
            for sector in sectors[:5]:
                focused_sectors.append(FocusedSector(
                    trade_date=trade_date,
                    sector_name=sector,
                    sector_code="",
                    reason="选股过程中识别的板块",
                    confidence="medium",
                    capital_flow=""
                ))
            if sectors:
                logger.warning(f"[{self.agent_id}] 未找到存储的热点板块，使用候选股票行业作为兜底: {sectors[:5]}")
        
        return focused_sectors
    
    def _build_candidate_stocks(self, trade_date: str, session_id: str) -> List[CandidateStock]:
        """构建候选股票列表"""
        stock_analyses = self._get_stock_analyses_from_memory(session_id)
        candidates = []
        
        for ts_code, analysis in stock_analyses.items():  # 展示所有候选股票
            pool_info = self._pool_info.get(ts_code, {})
            candidates.append(CandidateStock(
                trade_date=trade_date,
                ts_code=ts_code,
                name=analysis.get("name", ""),
                pool_type=pool_info.get("pool_type", "UNKNOWN"),
                model_rank=pool_info.get("model_rank", 0),
                sector=analysis.get("industry", ""),
                source="multi_round_selection"
            ))
        
        return candidates
    
    def _initialize_multi_round_selection(self, session_id: str) -> None:
        """初始化多轮筛选阶段"""
        # 将所有已分析的股票放入待筛选池
        stock_analyses = self._get_stock_analyses_from_memory(session_id)
        self._pending_stocks = list(stock_analyses.keys())
        self._shortlist = []
        self._current_round = 0
        
        # 注意：不要覆盖已有的 _pool_info，因为它们已经在 _update_candidate_pool 中正确设置
        # 只补充缺失的股票信息（例如从其他来源添加的股票）
        for ts_code, analysis in stock_analyses.items():
            if ts_code not in self._pool_info:
                # 只有当 _pool_info 中没有该股票时才添加
                self._pool_info[ts_code] = {
                    "pool_type": analysis.get("pool_type", "UNKNOWN"),
                    "sector": analysis.get("industry", ""),
                    "model_rank": analysis.get("model_rank", 0)
                }
            else:
                # 更新 sector 信息（从股票详情中获取的行业）
                if not self._pool_info[ts_code].get("sector"):
                    self._pool_info[ts_code]["sector"] = analysis.get("industry", "")
        
        logger.info(f"[{self.agent_id}] 初始化多轮筛选，待筛选: {len(self._pending_stocks)} 支")
    
    def _run_comparison_round(self, session_id: str, trade_date: str) -> Optional[Dict]:
        """执行单轮比较筛选
        
        多轮优选逻辑：
        1. 第一轮：从所有候选股票中5选2，直到遍历完所有候选
        2. 如果优选池 > FINAL_SELECTION_THRESHOLD(20)，启动第二轮优选
        3. 第二轮：把优选池股票放回待筛选池，继续5选2
        4. 重复步骤2-3，直到优选池 <= 20
        5. 最终选股：从优选池中选出10支
        
        返回 None 表示筛选阶段完成
        返回 Dict 表示需要继续下一轮
        """
        from agents.analysis.selection.selection_prompts import (
            SYSTEM_PROMPT_COMPARISON, 
            build_comparison_round_prompt,
            build_final_selection_prompt
        )
        
        # 检查是否需要初始化
        if not self._pending_stocks and not self._shortlist:
            self._initialize_multi_round_selection(session_id)
        
        # 计算总轮次（用于提示）
        total_rounds = (len(self._pending_stocks) + self._comparison_batch_size - 1) // self._comparison_batch_size
        
        # 情况1：还有待筛选股票，执行比较轮次
        if self._pending_stocks:
            self._current_round += 1
            
            # 取出本轮要比较的股票
            batch_size = min(self._comparison_batch_size, len(self._pending_stocks))
            stocks_to_compare = []
            
            stock_analyses = self._get_stock_analyses_from_memory(session_id)
            for i in range(batch_size):
                if self._pending_stocks:
                    ts_code = self._pending_stocks.pop(0)
                    if ts_code in stock_analyses:
                        stocks_to_compare.append(stock_analyses[ts_code])
            
            if not stocks_to_compare:
                return None
            
            # 获取当前优选池状态
            pool_distribution = self._get_pool_distribution()
            sector_coverage = self._get_sector_coverage(stock_analyses)
            
            # 从工作记忆中获取阶段1存储的热点板块和市场观点总结
            focused_sectors = []
            market_summary = ""
            if session_id and self._memory_manager:
                stored_sectors = self._memory_manager.working_memory.get(
                    session_id, self.WM_KEY_FOCUSED_SECTORS
                )
                if stored_sectors and isinstance(stored_sectors, dict):
                    focused_sectors = list(stored_sectors.keys())[:10]
                
                # 获取阶段1存储的市场观点总结
                market_summary = self._memory_manager.working_memory.get(
                    session_id, self.WM_KEY_MARKET_SUMMARY
                ) or ""
            
            # 构建比较Prompt
            prompt = build_comparison_round_prompt(
                round_num=self._current_round,
                total_rounds=total_rounds,
                stocks_to_compare=stocks_to_compare,
                already_selected=self._shortlist,
                pool_distribution=pool_distribution,
                sector_coverage=sector_coverage,
                focused_sectors=focused_sectors,
                market_summary=market_summary
            )
            
            # 调用LLM
            try:
                response = self.call_llm(prompt=prompt, system_prompt=SYSTEM_PROMPT_COMPARISON)
                result = self.parse_response(response)  # 使用基类方法
                
                if result:
                    # 验证选中的股票在本轮候选中（原 _parse_comparison_response 的验证逻辑）
                    valid_codes = {s.get("ts_code") for s in stocks_to_compare}
                    selected = result.get("selected", [])
                    result["selected"] = [code for code in selected if code in valid_codes]
                    
                    # 将选中的股票加入优选池
                    for ts_code in result.get("selected", []):
                        if ts_code not in self._shortlist:
                            self._shortlist.append(ts_code)
                            logger.info(f"[{self.agent_id}] 股票 {ts_code} 进入优选池")
                    
                    logger.info(f"[{self.agent_id}] 轮次 {self._current_round} 完成，优选池: {len(self._shortlist)} 支")
                    return {"continue": True, "shortlist_size": len(self._shortlist)}
                    
            except Exception as e:
                logger.error(f"[{self.agent_id}] 比较轮次失败: {e}")
                # 失败时把股票放回待筛选池
                for stock in stocks_to_compare:
                    ts_code = stock.get("ts_code")
                    if ts_code and ts_code not in self._pending_stocks:
                        self._pending_stocks.append(ts_code)
                return {"continue": True, "retry": True}
        
        # 情况2：待筛选池为空，检查优选池数量
        if not self._pending_stocks:
            if len(self._shortlist) <= self._final_selection_threshold:
                # 优选池 <= 20，可以进入最终选股
                if len(self._shortlist) <= self._final_selection_size:
                    # 优选池 <= 10，直接输出
                    logger.info(f"[{self.agent_id}] 筛选完成，优选池 {len(self._shortlist)} 支，直接输出")
                    return None
                else:
                    # 10 < 优选池 <= 20，执行最终选股
                    logger.info(f"[{self.agent_id}] 筛选完成，优选池 {len(self._shortlist)} 支，执行最终选股")
                    return self._run_final_selection(session_id, trade_date)
            else:
                # 优选池 > 20，启动新一轮优选
                logger.info(f"[{self.agent_id}] 优选池 {len(self._shortlist)} 支 > {self._final_selection_threshold}，启动新一轮优选")
                self._start_new_selection_phase()
                return {"continue": True, "new_phase": True, "shortlist_size": len(self._shortlist)}
        
        return {"continue": True}
    
    def _start_new_selection_phase(self) -> None:
        """启动新一轮优选（把优选池股票放回待筛选池）"""
        # 把优选池的股票放回待筛选池
        self._pending_stocks = list(self._shortlist)
        # 清空优选池
        self._shortlist = []
        # 轮次继续增加（不重置）
        logger.info(f"[{self.agent_id}] 新一轮优选开始，待筛选: {len(self._pending_stocks)} 支")
    
    def _run_final_selection(self, session_id: str, trade_date: str) -> Optional[Dict]:
        """执行最终选股（从优选池选10支）"""
        from agents.analysis.selection.selection_prompts import (
            SYSTEM_PROMPT_COMPARISON,
            build_final_selection_prompt
        )
        
        stock_analyses = self._get_stock_analyses_from_memory(session_id)
        shortlist_stocks = [stock_analyses[ts_code] for ts_code in self._shortlist if ts_code in stock_analyses]
        
        if not shortlist_stocks:
            logger.error(f"[{self.agent_id}] 优选池为空，无法执行最终选股")
            return None
        
        # 获取市场观点总结（优先从工作记忆获取阶段1存储的 market_summary）
        market_summary = ""
        if session_id and self._memory_manager:
            market_summary = self._memory_manager.working_memory.get(
                session_id, self.WM_KEY_MARKET_SUMMARY
            ) or ""
        
        # 如果没有存储的市场观点总结，尝试从步骤记录中提取（兜底）
        if not market_summary:
            market_summary = self._get_market_view_from_memory(session_id)
        
        # 获取关注板块：优先从工作记忆中获取阶段1存储的热点板块
        focused_sectors = []
        if session_id and self._memory_manager:
            stored_sectors = self._memory_manager.working_memory.get(
                session_id, self.WM_KEY_FOCUSED_SECTORS
            )
            if stored_sectors and isinstance(stored_sectors, dict):
                focused_sectors = list(stored_sectors.keys())[:10]
                logger.info(f"[{self.agent_id}] 最终选股使用存储的热点板块: {focused_sectors}")
        
        # 如果没有存储的热点板块，使用候选股票的行业作为兜底
        if not focused_sectors:
            focused_sectors = list(set([info.get("sector", "") for info in self._pool_info.values() if info.get("sector")]))[:5]
            if focused_sectors:
                logger.warning(f"[{self.agent_id}] 最终选股使用候选股票行业作为兜底: {focused_sectors}")
        
        prompt = build_final_selection_prompt(
            shortlist=shortlist_stocks,
            market_summary=market_summary,
            focused_sectors=focused_sectors
        )
        
        try:
            response = self.call_llm(prompt=prompt, system_prompt=SYSTEM_PROMPT_COMPARISON)
            result = self.parse_response(response)  # 使用基类方法
            
            if result:
                selected_stocks = result.get("selected_stocks", [])
                
                # 验证选股数量和格式
                if len(selected_stocks) != self._final_selection_size:
                    logger.warning(f"[{self.agent_id}] 最终选股数量不符合要求: {len(selected_stocks)} 支，期望 {self._final_selection_size} 支")
                    # 如果数量不对但>=5支，仍然接受
                    if len(selected_stocks) < 5:
                        logger.error(f"[{self.agent_id}] 选股数量过少，需要重试")
                        return {"continue": True, "retry": True}
                
                # 验证每个股票的格式
                validated_stocks = []
                for ss in selected_stocks:
                    ts_code = ss.get("ts_code")
                    pool_type = ss.get("pool_type")
                    reason = ss.get("reason")
                    
                    # 检查必需字段
                    if not ts_code or not pool_type:
                        logger.warning(f"[{self.agent_id}] 股票缺少必需字段: {ss}")
                        continue
                    
                    # 验证 pool_type 是有效值
                    valid_pool_types = {"SHORT", "MID", "LONG", "WHITE_HORSE"}
                    if pool_type not in valid_pool_types:
                        logger.warning(f"[{self.agent_id}] 无效的 pool_type: {pool_type}")
                        continue
                    
                    validated_stocks.append({
                        "ts_code": ts_code,
                        "pool_type": pool_type,
                        "reason": reason or "综合分析优选"
                    })
                
                # 检查股票池分布
                pool_dist = {}
                for ss in validated_stocks:
                    pt = ss.get("pool_type")
                    pool_dist[pt] = pool_dist.get(pt, 0) + 1
                
                missing_pools = [pt for pt in ["SHORT", "MID", "LONG", "WHITE_HORSE"] if pt not in pool_dist]
                if missing_pools:
                    logger.warning(f"[{self.agent_id}] 最终选股未覆盖股票池: {missing_pools}")
                
                # 存储最终结果到工作记忆
                final_result = {
                    "selected_stocks": validated_stocks,
                    "summary": result.get("summary", "基于多轮筛选完成最终选股"),
                    "confidence": result.get("confidence", 70),
                    "market_view": market_summary,
                    "pool_distribution": pool_dist
                }
                
                if session_id and self._memory_manager:
                    self._memory_manager.working_memory.set(
                        session_id, "final_selection", final_result
                    )
                
                logger.info(f"[{self.agent_id}] 最终选股完成，选中 {len(validated_stocks)} 支，分布: {pool_dist}")
                return None  # 表示完成
                
        except Exception as e:
            logger.error(f"[{self.agent_id}] 最终选股失败: {e}")
        
        return {"continue": True}
    
    def _get_pool_distribution(self) -> Dict[str, int]:
        """获取当前优选池的股票池分布"""
        distribution = {"SHORT": 0, "MID": 0, "LONG": 0, "WHITE_HORSE": 0}
        for ts_code in self._shortlist:
            info = self._pool_info.get(ts_code, {})
            pool_type = info.get("pool_type", "UNKNOWN")
            if pool_type in distribution:
                distribution[pool_type] += 1
        return distribution
    
    def _get_sector_coverage(self, stock_analyses: Dict) -> List[str]:
        """获取当前优选池已覆盖的板块"""
        sectors = []
        for ts_code in self._shortlist:
            if ts_code in stock_analyses:
                sector = stock_analyses[ts_code].get("industry", "")
                if sector and sector not in sectors:
                    sectors.append(sector)
        return sectors
    
    def _get_market_view_from_memory(self, session_id: str) -> str:
        """从工作记忆获取市场观点"""
        if not session_id or not self._memory_manager:
            return ""
        # 尝试从步骤记录中提取
        memory = self._memory_manager.working_memory.get_all(session_id)
        for key, value in memory.items():
            if key.startswith("step_") and isinstance(value, dict):
                obs = value.get("observation", "")
                if "market_state" in obs or "大盘" in obs:
                    return obs[:500]
        return ""

    def parse_response(self, response: str) -> Dict[str, Any]:
        """解析 LLM 响应（实现基类抽象方法）
        
        通用JSON解析，支持多种格式：
        - ```json ... ``` 代码块
        - ``` ... ``` 代码块  
        - 裸JSON对象
        
        此方法合并了原先的 _parse_comparison_response 和 _parse_final_selection_response
        """
        if not response or not response.strip():
            return {}
        
        try:
            # 策略1: 提取 ```json ... ``` 代码块
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
            if json_match:
                return json.loads(json_match.group(1))
            
            # 策略2: 提取 ``` ... ``` 代码块（无json标记）
            json_match = re.search(r'```\s*([\s\S]*?)\s*```', response)
            if json_match:
                candidate = json_match.group(1).strip()
                if candidate.startswith('{'):
                    return json.loads(candidate)
            
            # 策略3: 花括号匹配
            first_brace = response.find('{')
            last_brace = response.rfind('}')
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                return json.loads(response[first_brace:last_brace + 1])
            
            # 策略4: 直接解析
            return json.loads(response)
            
        except json.JSONDecodeError as e:
            logger.error(f"[{self.agent_id}] JSON解析失败: {e}")
            return {}
        except Exception as e:
            logger.error(f"[{self.agent_id}] 响应解析异常: {e}")
            return {}
