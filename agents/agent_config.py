import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from core.llm.llm_config import get_llm_config


@dataclass
class LLMSettings:
    model: str = "default"
    temperature: float = 0.2
    max_tokens: int = 4096
    timeout: float = 60.0
    max_retries: int = 3


@dataclass
class MemorySettings:
    short_term_days: int = 3
    review_days: int = 10
    retention_days: int = 20
    embedding_model: str = "Qwen/Qwen3-Embedding-8B"
    distance_threshold: float = 0.25
    top_k: int = 5


@dataclass
class ReviewSettings:
    system_prompt: str = "你是一位专业的投资复盘分析师。"
    validation_threshold: float = 0.5


@dataclass
class TushareToolSettings:
    default_timeout: float = 30.0
    long_timeout: float = 60.0
    extended_timeout: float = 120.0


@dataclass
class TechnicalSettings:
    ma_periods: list = field(default_factory=lambda: [5, 10, 20, 60])
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    adx_period: int = 14


@dataclass
class ToolSettings:
    tushare: TushareToolSettings = field(default_factory=TushareToolSettings)
    technical: TechnicalSettings = field(default_factory=TechnicalSettings)


# ==================== 大盘分析专属配置 ====================

@dataclass
class MarketTechnicalSettings:
    """大盘技术分析参数"""
    support_resistance_days: int = 60
    volume_trend_days: int = 20
    volume_trend_lookback: int = 10


@dataclass
class MarketCapitalSettings:
    """大盘资金分析参数"""
    margin_trend_days: int = 10
    north_flow_days: int = 20
    north_flow_lookback: int = 10


@dataclass
class MarketValuationSettings:
    """大盘估值分析参数"""
    min_days: int = 100
    max_days: int = 650
    risk_free_rate: float = 0.0177


@dataclass
class MarketCycleSettings:
    """大盘周期分析参数"""
    phase_days: int = 250
    strength_days: int = 60
    regime_days: int = 250


@dataclass
class MarketSentimentSettings:
    """大盘情绪分析参数"""
    normalization_days: int = 60
    weights: Dict[str, float] = field(default_factory=lambda: {
        'market_width': 0.20,
        'adv_decline_ratio': 0.30,
        'ad_line': 0.20,
        'turnover_concentration': 0.30
    })


@dataclass
class MarketDatabaseSettings:
    """大盘数据库查询参数"""
    query_days: int = 650
    min_required_days: int = 100


@dataclass
class MarketAnalysisSettings:
    """大盘分析专属配置"""
    technical: MarketTechnicalSettings = field(default_factory=MarketTechnicalSettings)
    capital: MarketCapitalSettings = field(default_factory=MarketCapitalSettings)
    valuation: MarketValuationSettings = field(default_factory=MarketValuationSettings)
    cycle: MarketCycleSettings = field(default_factory=MarketCycleSettings)
    sentiment: MarketSentimentSettings = field(default_factory=MarketSentimentSettings)
    database: MarketDatabaseSettings = field(default_factory=MarketDatabaseSettings)


# ==================== 选股分析专属配置 ====================

@dataclass
class SelectionComparisonSettings:
    """选股多轮筛选参数"""
    batch_size: int = 5          # 每轮比较的股票数量
    select_size: int = 2         # 每轮选出的股票数量
    final_threshold: int = 20    # 最终选股阈值（优选池<=此值时进行最终选股）
    final_size: int = 10         # 最终选股数量


@dataclass
class SelectionRetrySettings:
    """选股重试参数"""
    max_retries: int = 2         # 单支股票分析最大重试次数


@dataclass
class SelectionSettings:
    """选股分析师专属配置"""
    max_iterations: int = 25              # ReAct循环最大迭代次数
    candidate_pool_threshold: int = 25    # 候选池收集完成阈值
    comparison: SelectionComparisonSettings = field(default_factory=SelectionComparisonSettings)
    retry: SelectionRetrySettings = field(default_factory=SelectionRetrySettings)


@dataclass
class ReActSettings:
    """ReAct Agent 配置参数"""
    max_iterations: int = 15
    timeout_per_step: float = 30.0


@dataclass
class AgentSettings:
    name: str = ""
    description: str = ""
    llm: LLMSettings = field(default_factory=LLMSettings)
    memory: MemorySettings = field(default_factory=MemorySettings)
    review: ReviewSettings = field(default_factory=ReviewSettings)
    tools: ToolSettings = field(default_factory=ToolSettings)
    react: ReActSettings = field(default_factory=ReActSettings)
    analysis: Dict[str, Any] = field(default_factory=dict)
    market_analysis: MarketAnalysisSettings = field(default_factory=MarketAnalysisSettings)
    selection: SelectionSettings = field(default_factory=SelectionSettings)


class AgentConfigManager:
    """
    Agent 配置管理器
    
    功能：
    1. 从 agent_config.yaml 加载各 Agent 配置
    2. 提供类型安全的配置访问
    3. 与 LLMConfig 集成，支持模型别名解析
    """
    
    _instance = None
    
    def __init__(self, config_path: str = None):
        if config_path is None:
            root_path = Path(__file__).resolve().parent.parent
            config_path = root_path / "config" / "agent_config.yaml"
        
        self.config_path = Path(config_path)
        self._config = self._load_config()
        self._llm_config = get_llm_config()
        self._cache: Dict[str, AgentSettings] = {}
    
    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Agent配置文件未找到: {self.config_path}")
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _get_default_settings(self) -> Dict[str, Any]:
        return self._config.get('default_settings', {})
    
    def _resolve_model(self, model_alias: str) -> str:
        if model_alias == "default":
            return self._llm_config.default_model
        elif model_alias == "analysis":
            return self._llm_config.analysis_model
        elif model_alias == "embedding":
            return self._llm_config.embedding_model
        return model_alias
    
    def _parse_llm_settings(self, agent_config: Dict[str, Any]) -> LLMSettings:
        default_llm = self._get_default_settings().get('llm', {})
        agent_llm = agent_config.get('llm', {})
        
        return LLMSettings(
            model=self._resolve_model(agent_llm.get('model', default_llm.get('model', 'default'))),
            temperature=agent_llm.get('temperature', default_llm.get('temperature', 0.3)),
            max_tokens=agent_llm.get('max_tokens', default_llm.get('max_tokens', 4096)),
            timeout=agent_llm.get('timeout', default_llm.get('timeout', 60.0)),
            max_retries=agent_llm.get('max_retries', default_llm.get('max_retries', 3))
        )
    
    def _parse_memory_settings(self, agent_config: Dict[str, Any]) -> MemorySettings:
        default_memory = self._get_default_settings().get('memory', {})
        agent_memory = agent_config.get('memory', {})
        
        return MemorySettings(
            short_term_days=agent_memory.get('short_term_days', default_memory.get('short_term_days', 3)),
            review_days=agent_memory.get('review_days', default_memory.get('review_days', 7)),
            retention_days=agent_memory.get('retention_days', default_memory.get('retention_days', 15)),
            embedding_model=agent_memory.get('embedding_model', default_memory.get('embedding_model', 'Qwen/Qwen3-Embedding-8B')),
            distance_threshold=agent_memory.get('distance_threshold', default_memory.get('distance_threshold', 0.25)),
            top_k=agent_memory.get('top_k', default_memory.get('top_k', 5))
        )
    
    def _parse_review_settings(self, agent_config: Dict[str, Any]) -> ReviewSettings:
        default_review = self._get_default_settings().get('review', {})
        agent_review = agent_config.get('review', {})
        
        return ReviewSettings(
            system_prompt=agent_review.get('system_prompt', default_review.get('system_prompt', '')),
            validation_threshold=agent_review.get('validation_threshold', default_review.get('validation_threshold', 0.5))
        )
    
    def _parse_tool_settings(self, agent_config: Dict[str, Any]) -> ToolSettings:
        default_tools = self._get_default_settings().get('tools', {})
        agent_tools = agent_config.get('tools', {})
        
        default_tushare = default_tools.get('tushare', {})
        agent_tushare = agent_tools.get('tushare', {})
        
        default_technical = default_tools.get('technical', {})
        agent_technical = agent_tools.get('technical', {})
        
        tushare_settings = TushareToolSettings(
            default_timeout=agent_tushare.get('default_timeout', default_tushare.get('default_timeout', 30.0)),
            long_timeout=agent_tushare.get('long_timeout', default_tushare.get('long_timeout', 60.0)),
            extended_timeout=agent_tushare.get('extended_timeout', default_tushare.get('extended_timeout', 120.0))
        )
        
        technical_settings = TechnicalSettings(
            ma_periods=agent_technical.get('ma_periods', default_technical.get('ma_periods', [5, 10, 20, 60])),
            macd_fast=agent_technical.get('macd_fast', default_technical.get('macd_fast', 12)),
            macd_slow=agent_technical.get('macd_slow', default_technical.get('macd_slow', 26)),
            macd_signal=agent_technical.get('macd_signal', default_technical.get('macd_signal', 9)),
            adx_period=agent_technical.get('adx_period', default_technical.get('adx_period', 14))
        )
        
        return ToolSettings(tushare=tushare_settings, technical=technical_settings)
    
    def _parse_market_analysis_settings(self, agent_config: Dict[str, Any]) -> MarketAnalysisSettings:
        """解析大盘分析专属配置"""
        analysis = agent_config.get('analysis', {})
        
        # 技术分析参数
        tech_config = analysis.get('technical', {})
        technical_settings = MarketTechnicalSettings(
            support_resistance_days=tech_config.get('support_resistance_days', 60),
            volume_trend_days=tech_config.get('volume_trend_days', 20),
            volume_trend_lookback=tech_config.get('volume_trend_lookback', 10)
        )
        
        # 资金分析参数
        capital_config = analysis.get('capital', {})
        capital_settings = MarketCapitalSettings(
            margin_trend_days=capital_config.get('margin_trend_days', 10),
            north_flow_days=capital_config.get('north_flow_days', 20),
            north_flow_lookback=capital_config.get('north_flow_lookback', 10)
        )
        
        # 估值分析参数
        valuation_config = analysis.get('valuation', {})
        valuation_settings = MarketValuationSettings(
            min_days=valuation_config.get('min_days', 100),
            max_days=valuation_config.get('max_days', 650),
            risk_free_rate=valuation_config.get('risk_free_rate', 0.0177)
        )
        
        # 周期分析参数
        cycle_config = analysis.get('cycle', {})
        cycle_settings = MarketCycleSettings(
            phase_days=cycle_config.get('phase_days', 250),
            strength_days=cycle_config.get('strength_days', 60),
            regime_days=cycle_config.get('regime_days', 250)
        )
        
        # 情绪分析参数
        sentiment_config = analysis.get('sentiment', {})
        default_weights = {
            'market_width': 0.20,
            'adv_decline_ratio': 0.30,
            'ad_line': 0.20,
            'turnover_concentration': 0.30
        }
        sentiment_settings = MarketSentimentSettings(
            normalization_days=sentiment_config.get('normalization_days', 60),
            weights=sentiment_config.get('weights', default_weights)
        )
        
        # 数据库查询参数
        db_config = analysis.get('database', {})
        database_settings = MarketDatabaseSettings(
            query_days=db_config.get('query_days', 650),
            min_required_days=db_config.get('min_required_days', 100)
        )
        
        return MarketAnalysisSettings(
            technical=technical_settings,
            capital=capital_settings,
            valuation=valuation_settings,
            cycle=cycle_settings,
            sentiment=sentiment_settings,
            database=database_settings
        )
    
    def _parse_selection_settings(self, agent_config: Dict[str, Any]) -> SelectionSettings:
        """解析选股分析师专属配置"""
        selection = agent_config.get('selection', {})
        
        # 多轮筛选参数
        comparison_config = selection.get('comparison', {})
        comparison_settings = SelectionComparisonSettings(
            batch_size=comparison_config.get('batch_size', 5),
            select_size=comparison_config.get('select_size', 2),
            final_threshold=comparison_config.get('final_threshold', 20),
            final_size=comparison_config.get('final_size', 10)
        )
        
        # 重试参数
        retry_config = selection.get('retry', {})
        retry_settings = SelectionRetrySettings(
            max_retries=retry_config.get('max_retries', 2)
        )
        
        return SelectionSettings(
            max_iterations=selection.get('max_iterations', 25),
            candidate_pool_threshold=selection.get('candidate_pool_threshold', 25),
            comparison=comparison_settings,
            retry=retry_settings
        )
    
    def get_agent_settings(self, agent_type: str) -> AgentSettings:
        if agent_type in self._cache:
            return self._cache[agent_type]
        
        agents_config = self._config.get('agents', {})
        agent_config = agents_config.get(agent_type, {})
        
        if not agent_config:
            default_settings = self._get_default_settings()
            settings = AgentSettings(
                name=agent_type,
                description="",
                llm=self._parse_llm_settings(default_settings),
                memory=self._parse_memory_settings(default_settings),
                review=self._parse_review_settings(default_settings),
                tools=self._parse_tool_settings(default_settings)
            )
        else:
            settings = AgentSettings(
                name=agent_config.get('name', agent_type),
                description=agent_config.get('description', ''),
                llm=self._parse_llm_settings(agent_config),
                memory=self._parse_memory_settings(agent_config),
                review=self._parse_review_settings(agent_config),
                tools=self._parse_tool_settings(agent_config),
                analysis=agent_config.get('analysis', {})
            )
        
        self._cache[agent_type] = settings
        return settings
    
    def get_market_analyst_settings(self) -> AgentSettings:
        """获取大盘分析师配置（包含 market_analysis 专属配置）"""
        if 'market_analyst' in self._cache:
            return self._cache['market_analyst']
        
        agents_config = self._config.get('agents', {})
        agent_config = agents_config.get('market_analyst', {})
        
        settings = AgentSettings(
            name=agent_config.get('name', '大盘分析师'),
            description=agent_config.get('description', ''),
            llm=self._parse_llm_settings(agent_config),
            memory=self._parse_memory_settings(agent_config),
            review=self._parse_review_settings(agent_config),
            tools=self._parse_tool_settings(agent_config),
            analysis=agent_config.get('analysis', {}),
            market_analysis=self._parse_market_analysis_settings(agent_config)
        )
        
        self._cache['market_analyst'] = settings
        return settings
    
    def get_stock_analyst_settings(self) -> AgentSettings:
        return self.get_agent_settings('stock_analyst')
    
    def get_sector_analyst_settings(self) -> AgentSettings:
        return self.get_agent_settings('sector_analyst')
    
    def get_selection_analyst_settings(self) -> AgentSettings:
        """获取选股分析师配置（包含 selection 专属配置）"""
        if 'selection_analyst' in self._cache:
            return self._cache['selection_analyst']
        
        agents_config = self._config.get('agents', {})
        agent_config = agents_config.get('selection_analyst', {})
        
        settings = AgentSettings(
            name=agent_config.get('name', '选股分析师'),
            description=agent_config.get('description', ''),
            llm=self._parse_llm_settings(agent_config),
            memory=self._parse_memory_settings(agent_config),
            review=self._parse_review_settings(agent_config),
            tools=self._parse_tool_settings(agent_config),
            analysis=agent_config.get('analysis', {}),
            selection=self._parse_selection_settings(agent_config)
        )
        
        self._cache['selection_analyst'] = settings
        return settings
    
    def get_stock_picker_settings(self) -> AgentSettings:
        """获取选股分析师配置（别名）"""
        return self.get_selection_analyst_settings()
    
    def reload(self):
        self._config = self._load_config()
        self._cache.clear()


_agent_config_instance: Optional[AgentConfigManager] = None


def get_agent_config() -> AgentConfigManager:
    global _agent_config_instance
    if _agent_config_instance is None:
        _agent_config_instance = AgentConfigManager()
    return _agent_config_instance