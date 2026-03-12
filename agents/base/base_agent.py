"""
Agent抽象基类

本模块定义了所有Agent的核心抽象接口，采用模板方法模式设计。
所有具体Agent（大盘分析师、板块分析师、个股分析师等）都继承自此类。

设计原则:
    - 依赖注入: Memory、LLM、Tools通过构造函数注入
    - 模板方法: execute()定义执行骨架，子类实现具体逻辑
    - 状态追踪: 使用AgentState状态机管理生命周期
    - 接口抽象: 定义统一接口，确保所有Agent行为一致
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Type
import logging
import uuid

from .agent_state import (
    AgentState,
    AgentStateMachine,
    StateTransitionError,
)

logger = logging.getLogger(__name__)


class AgentType(Enum):
    """
    Agent类型枚举
    
    类型说明:
        MARKET: 大盘分析师
        SECTOR: 板块分析师
        STOCK_TECHNICAL: 个股技术面分析师
        STOCK_SECTOR: 个股所属板块分析师
        STOCK_NEWS: 个股新闻情绪分析师
        STOCK_FUNDAMENTAL: 个股基本面分析师
        BULL: 多头辩论员
        BEAR: 空头辩论员
        SUMMARIZER: 总结员
        SELECTION: 选股Agent
        RISK: 风控Agent
        DECISION: 决策Agent
    """
    MARKET = "market"
    SECTOR = "sector"
    STOCK_TECHNICAL = "stock_technical"
    STOCK_SECTOR = "stock_sector"
    STOCK_NEWS = "stock_news"
    STOCK_FUNDAMENTAL = "stock_fundamental"
    BULL = "bull"
    BEAR = "bear"
    SUMMARIZER = "summarizer"
    SELECTION = "selection"
    RISK = "risk"
    DECISION = "decision"
    
    def __str__(self) -> str:
        return self.value


@dataclass
class AgentConfig:
    """
    Agent配置数据类
    
    Attributes:
        name: Agent名称
        description: Agent描述
        model: 使用的LLM模型
        temperature: 生成温度
        max_tokens: 最大token数
        timeout: 执行超时时间（秒）
        max_retries: 最大重试次数
        memory_enabled: 是否启用记忆
        tools_enabled: 是否启用工具
    """
    name: str = ""
    description: str = ""
    model: str = "deepseek-chat"
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 60.0
    max_retries: int = 3
    memory_enabled: bool = True
    tools_enabled: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def _get_default_llm_settings(cls) -> Dict[str, Any]:
        try:
            from agents.agent_config import get_agent_config
            agent_config = get_agent_config()
            default_settings = agent_config._get_default_settings()
            return default_settings.get('llm', {})
        except Exception:
            return {}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentConfig":
        defaults = cls._get_default_llm_settings()
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            model=data.get("model", defaults.get("model", "deepseek-chat")),
            temperature=data.get("temperature", defaults.get("temperature", 0.7)),
            max_tokens=data.get("max_tokens", defaults.get("max_tokens", 4096)),
            timeout=data.get("timeout", defaults.get("timeout", 60.0)),
            max_retries=data.get("max_retries", defaults.get("max_retries", 3)),
            memory_enabled=data.get("memory_enabled", True),
            tools_enabled=data.get("tools_enabled", True),
            extra=data.get("extra", {}),
        )


@dataclass
class AgentResult:
    """
    Agent执行结果
    
    Attributes:
        success: 是否成功
        data: 返回数据
        error: 错误信息
        execution_time: 执行耗时（秒）
        state_history: 状态历史
        metadata: 额外元数据
    """
    success: bool
    data: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0
    state_history: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def success_result(cls, data: Any, execution_time: float = 0.0, **metadata) -> "AgentResult":
        """创建成功结果"""
        return cls(success=True, data=data, execution_time=execution_time, metadata=metadata)
    
    @classmethod
    def failure_result(cls, error: str, execution_time: float = 0.0, **metadata) -> "AgentResult":
        """创建失败结果"""
        return cls(success=False, error=error, execution_time=execution_time, metadata=metadata)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "execution_time": self.execution_time,
            "state_history": self.state_history,
            "metadata": self.metadata,
        }


class BaseAgent(ABC):
    """
    Agent抽象基类
    
    所有Agent的核心抽象接口，采用模板方法模式设计。
    子类必须实现以下抽象方法:
        - validate_input(): 输入校验规则
        - analyze(): 核心分析逻辑
        - parse_response(): 解析LLM响应
    
    使用示例:
        class MarketAnalyst(BaseAgent):
            agent_type = AgentType.MARKET
            
            def validate_input(self, input_data: Dict) -> Optional[str]:
                if "date" not in input_data:
                    return "缺少日期参数"
                return None
            
            def analyze(self, input_data: Dict, context: Dict = None) -> AgentResult:
                # 实现具体分析逻辑
                pass
            
            def parse_response(self, response: str) -> Dict:
                # 解析LLM响应
                pass
    """
    
    agent_type: AgentType = AgentType.MARKET
    
    def __init__(
        self,
        agent_id: str = None,
        config: AgentConfig = None,
        memory_manager: Any = None,
        llm_client: Any = None,
        tool_registry: Any = None,
    ):
        """
        初始化Agent
        
        Args:
            agent_id: Agent唯一标识，不传则自动生成
            config: Agent配置
            memory_manager: 记忆管理器（依赖注入）
            llm_client: LLM客户端（依赖注入）
            tool_registry: 工具注册中心（依赖注入）
        """
        self.agent_id = agent_id or self._generate_agent_id()
        self.config = config or AgentConfig()
        
        self._memory_manager = memory_manager
        self._llm_client = llm_client
        self._tool_registry = tool_registry
        
        self._state_machine = AgentStateMachine(self.agent_id)
        self._session_id: Optional[str] = None
        self._task_id: Optional[str] = None
        self._start_time: Optional[datetime] = None
        
        logger.debug(f"[{self.agent_id}] Agent初始化完成 | 类型: {self.agent_type}")
    
    def _generate_agent_id(self) -> str:
        """生成唯一Agent ID"""
        type_prefix = self.agent_type.value.upper()
        short_uuid = uuid.uuid4().hex[:8]
        return f"{type_prefix}_{short_uuid}"
    
    @property
    def state(self) -> AgentState:
        """获取当前状态"""
        return self._state_machine.current_state
    
    @property
    def is_busy(self) -> bool:
        """是否处于忙碌状态"""
        return self._state_machine.is_busy()
    
    @property
    def is_error(self) -> bool:
        """是否处于错误状态"""
        return self._state_machine.is_error()
    
    @abstractmethod
    def validate_input(self, input_data: Dict[str, Any]) -> Optional[str]:
        """
        验证输入数据（抽象方法，子类必须实现）
        
        Args:
            input_data: 输入数据字典
            
        Returns:
            错误信息字符串，验证通过返回None
        """
        pass
    
    @abstractmethod
    def analyze(self, input_data: Dict[str, Any], context: Dict[str, Any] = None) -> AgentResult:
        """
        执行核心分析逻辑（抽象方法，子类必须实现）
        
        这是Agent的主要业务逻辑入口。
        
        Args:
            input_data: 输入数据字典
            context: 上下文数据（包含记忆、任务信息等）
            
        Returns:
            AgentResult: 分析结果
        """
        pass
    
    @abstractmethod
    def parse_response(self, response: str) -> Dict[str, Any]:
        """
        解析LLM响应（抽象方法，子类必须实现）
        
        Args:
            response: LLM返回的原始响应文本
            
        Returns:
            解析后的结构化数据字典
        """
        pass
    
    def execute(self, input_data: Dict[str, Any], task_id: str = None) -> AgentResult:
        """
        执行Agent任务（模板方法）
        
        这是Agent的主入口方法，定义了完整的执行流程:
        1. 状态转换到INITIALIZING
        2. 验证输入
        3. 创建Working Memory会话
        4. 执行分析
        5. 保存结果
        6. 状态转换到COMPLETED
        
        Args:
            input_data: 输入数据字典
            task_id: 任务ID，不传则自动生成
            
        Returns:
            AgentResult: 执行结果
        """
        self._start_time = datetime.now()
        self._task_id = task_id or uuid.uuid4().hex[:12]
        
        try:
            # 1. 初始化
            self._state_machine.transition(AgentState.INITIALIZING, "开始执行任务")
            
            # 2. 输入验证
            validation_error = self.validate_input(input_data)
            if validation_error:
                return self._handle_error(f"输入验证失败: {validation_error}")
            
            # 3. 创建 Working Memory Session（无条件创建，Working Memory 和短期记忆分离）
            if self._memory_manager:
                self._session_id = self._memory_manager.create_session(self.agent_id, self._task_id)
                
            self._state_machine.transition(AgentState.LOADING_DATA, "加载数据")
            # 4. 构建上下文
            context = {
                "agent_id": self.agent_id,
                "agent_type": self.agent_type.value,
                "task_id": self._task_id,
                "session_id": self._session_id,
                "input_data": input_data,
                "timestamp": datetime.now().isoformat(),
            }
            
            # 5. 执行分析
            self._state_machine.transition(AgentState.ANALYZING, "执行分析")
            result = self.analyze(input_data, context)
            
            # 6. 保存结果
            self._state_machine.transition(AgentState.GENERATING_OUTPUT, "生成输出")
            self._save_result(result)
            
            # 7. 完成
            self._state_machine.transition(AgentState.COMPLETED, "任务完成")
            
            result.state_history = self._state_machine.state_history
            result.execution_time = (datetime.now() - self._start_time).total_seconds()
            
            logger.info(
                f"[{self.agent_id}] 任务执行完成 | "
                f"耗时: {result.execution_time:.2f}s | "
                f"成功: {result.success}"
            )
            
            return result
            
        except StateTransitionError as e:
            return self._handle_error(f"状态转换错误: {e}")
        except Exception as e:
            return self._handle_error(f"执行异常: {e}")
    
    def _do_analyze(self, input_data: Dict[str, Any], context: Dict[str, Any]) -> AgentResult:
        """
        执行分析（调用子类实现）
        
        Args:
            input_data: 输入数据
            context: 上下文
            
        Returns:
            分析结果
        """
        return self.analyze(input_data, context)
    
    def _save_result(self, result: AgentResult) -> None:
        """
        保存执行结果

        Args:
            result: 执行结果
        """
        if self._memory_manager and self.config.memory_enabled and result.success:
            try:
                # 如果 result.data 有 to_dict 方法，先转换为字典
                data = result.data
                if hasattr(data, 'to_dict') and callable(getattr(data, 'to_dict')):
                    data = data.to_dict()

                # 从 data 中提取日期字段（支持 trade_date 和 date 两种字段名）
                trade_date = None
                if isinstance(data, dict):
                    # 优先使用 trade_date，其次使用 date
                    trade_date = data.get('trade_date') or data.get('date')
                    # 处理空字符串
                    if trade_date == '':
                        trade_date = None

                save_data = {
                    "task_id": self._task_id,
                    "data": data,
                }
                
                self._memory_manager.save_result(self.agent_id, save_data, trade_date=trade_date)
                logger.debug(f"[{self.agent_id}] 保存结果成功 | trade_date: {trade_date}")
            except Exception as e:
                logger.warning(f"[{self.agent_id}] 保存结果失败: {e}")
    
    def _handle_error(self, error_message: str) -> AgentResult:
        """
        处理错误
        
        Args:
            error_message: 错误信息
            
        Returns:
            失败结果
        """
        self._state_machine.transition_to_error(error_message)
        
        execution_time = 0.0
        if self._start_time:
            execution_time = (datetime.now() - self._start_time).total_seconds()
        
        logger.error(f"[{self.agent_id}] 执行失败: {error_message}")
        
        return AgentResult.failure_result(
            error=error_message,
            execution_time=execution_time,
            state_history=self._state_machine.state_history,
        )
    
    def call_tool(self, tool_name: str, **kwargs) -> Any:
        """
        调用工具
        
        Args:
            tool_name: 工具名称
            **kwargs: 工具参数
            
        Returns:
            工具执行结果
            
        Raises:
            ValueError: 工具未注册或工具执行失败
        """
        if not self._tool_registry:
            raise ValueError("工具注册中心未配置")
        
        if not self.config.tools_enabled:
            raise ValueError("Agent未启用工具功能")
        
        tool = self._tool_registry.get(tool_name)
        if tool is None:
            raise ValueError(f"工具未注册: {tool_name}")
        
        logger.debug(f"[{self.agent_id}] 调用工具: {tool_name}")
        result = tool.execute(**kwargs)
        
        if result.is_failure:
            raise ValueError(f"工具执行失败: {result.error}")
        
        return result.data
    
    def call_llm(self, prompt: str, system_prompt: str = None) -> str:
        """
        调用LLM
        
        Args:
            prompt: 用户提示
            system_prompt: 系统提示（可选）
            
        Returns:
            LLM响应文本
            
        Raises:
            ValueError: LLM客户端未配置
        """
        if not self._llm_client:
            raise ValueError("LLM客户端未配置")
        
        logger.debug(f"[{self.agent_id}] 调用LLM | 模型: {self.config.model}")
        
        if system_prompt:
            return self._llm_client.chat_with_system(
                system_prompt=system_prompt,
                user_prompt=prompt,
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
        else:
            return self._llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
    
    def reset(self) -> None:
        """
        重置Agent状态
        """
        self._state_machine.reset()
        self._session_id = None
        self._task_id = None
        self._start_time = None
        logger.info(f"[{self.agent_id}] Agent已重置")
    
    def get_info(self) -> Dict[str, Any]:
        """
        获取Agent信息
        
        Returns:
            Agent信息字典
        """
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type.value,
            "state": self.state.value,
            "config": {
                "name": self.config.name,
                "description": self.config.description,
                "model": self.config.model,
            },
            "is_busy": self.is_busy,
            "is_error": self.is_error,
        }
    
    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"agent_id='{self.agent_id}', "
            f"type={self.agent_type.value}, "
            f"state={self.state.value})"
        )
