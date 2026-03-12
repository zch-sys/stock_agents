"""
工具基类模块

本模块定义了工具系统的核心抽象，所有Agent可使用的工具都继承自BaseTool。
工具是Agent与外部世界交互的桥梁，包括数据查询、计算、分析等功能。

设计原则:
    - 统一接口: 所有工具实现相同的execute方法
    - 参数验证: 执行前验证参数合法性
    - 结果封装: ToolResult统一返回格式
    - LLM友好: description和parameters供LLM理解调用方式
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
import logging
import time

logger = logging.getLogger(__name__)


class ToolStatus(Enum):
    """工具执行状态"""
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    INVALID_PARAMS = "invalid_params"


@dataclass
class ToolResult:
    """
    工具执行结果
    
    封装工具执行的返回数据，包含状态、数据、错误信息等。
    
    Attributes:
        status: 执行状态
        data: 返回数据
        error: 错误信息（失败时）
        execution_time: 执行耗时（秒）
        metadata: 额外元数据
    """
    status: ToolStatus
    data: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_success(self) -> bool:
        """是否执行成功"""
        return self.status == ToolStatus.SUCCESS
    
    @property
    def is_failure(self) -> bool:
        """是否执行失败"""
        return self.status != ToolStatus.SUCCESS
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "status": self.status.value,
            "data": self.data,
            "error": self.error,
            "execution_time": self.execution_time,
            "metadata": self.metadata,
        }
    
    @classmethod
    def success(cls, data: Any, execution_time: float = 0.0, **metadata) -> "ToolResult":
        """创建成功结果"""
        return cls(
            status=ToolStatus.SUCCESS,
            data=data,
            execution_time=execution_time,
            metadata=metadata,
        )
    
    @classmethod
    def failure(cls, error: str, execution_time: float = 0.0, **metadata) -> "ToolResult":
        """创建失败结果"""
        return cls(
            status=ToolStatus.FAILURE,
            error=error,
            execution_time=execution_time,
            metadata=metadata,
        )
    
    @classmethod
    def timeout(cls, error: str = "执行超时", execution_time: float = 0.0) -> "ToolResult":
        """创建超时结果"""
        return cls(
            status=ToolStatus.TIMEOUT,
            error=error,
            execution_time=execution_time,
        )
    
    @classmethod
    def invalid_params(cls, error: str) -> "ToolResult":
        """创建参数无效结果"""
        return cls(
            status=ToolStatus.INVALID_PARAMS,
            error=error,
        )


@dataclass
class ToolParameter:
    """
    工具参数定义
    
    用于描述工具参数的名称、类型、是否必需、默认值等信息。
    支持生成JSON Schema格式的参数定义。
    
    Attributes:
        name: 参数名称
        param_type: 参数类型（string, number, integer, boolean, array, object）
        description: 参数描述
        required: 是否必需
        default: 默认值
        enum: 枚举值列表（可选）
        items: 数组元素类型（当param_type为array时）
        properties: 对象属性定义（当param_type为object时）
    """
    name: str
    param_type: str
    description: str = ""
    required: bool = True
    default: Any = None
    enum: Optional[List[Any]] = None
    items: Optional[Dict[str, Any]] = None
    properties: Optional[Dict[str, Any]] = None
    
    def to_json_schema(self) -> Dict[str, Any]:
        """生成JSON Schema格式的参数定义"""
        schema: Dict[str, Any] = {
            "type": self.param_type,
        }
        
        if self.description:
            schema["description"] = self.description
        
        if self.enum:
            schema["enum"] = self.enum
        
        if self.default is not None:
            schema["default"] = self.default
        
        if self.param_type == "array" and self.items:
            schema["items"] = self.items
        
        if self.param_type == "object" and self.properties:
            schema["properties"] = self.properties
        
        return schema


class BaseTool(ABC):
    """
    工具抽象基类
    
    所有Agent可使用的工具都继承自此类。工具是Agent与外部世界交互的桥梁，
    包括数据查询、计算、分析等功能。
    
    子类必须实现:
        - execute(): 执行工具逻辑
        
    子类可选实现:
        - validate_parameters(): 参数验证逻辑
        
    使用示例:
        class GetStockDataTool(BaseTool):
            name = "get_stock_data"
            description = "获取股票行情数据"
            
            def __init__(self):
                super().__init__()
                self._parameters = {
                    "stock_code": ToolParameter(
                        name="stock_code",
                        param_type="string",
                        description="股票代码，如 000001.SZ",
                        required=True,
                    ),
                    "start_date": ToolParameter(
                        name="start_date",
                        param_type="string",
                        description="开始日期，格式 YYYY-MM-DD",
                        required=True,
                    ),
                }
            
            def execute(self, stock_code: str, start_date: str, end_date: str = None) -> ToolResult:
                # 实现具体逻辑
                data = query_stock_data(stock_code, start_date, end_date)
                return ToolResult.success(data=data)
    """
    
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    timeout: float = 30.0
    
    def __init__(self):
        self._parameters: Dict[str, ToolParameter] = {}
        self._setup_parameters()
    
    def _setup_parameters(self) -> None:
        """
        设置参数定义（子类可重写）
        
        子类在此方法中定义工具的参数列表。
        """
        pass
    
    @property
    def parameters(self) -> Dict[str, ToolParameter]:
        """获取参数定义"""
        return self._parameters
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        """
        获取JSON Schema格式的参数定义
        
        用于LLM理解工具的调用方式。
        
        Returns:
            JSON Schema格式的参数定义
        """
        properties = {}
        required = []
        
        for param_name, param in self._parameters.items():
            properties[param_name] = param.to_json_schema()
            if param.required:
                required.append(param_name)
        
        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }
    
    def get_tool_info(self) -> Dict[str, Any]:
        """
        获取工具完整信息
        
        用于LLM理解工具的功能和调用方式。
        
        Returns:
            工具信息字典
        """
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "parameters": self.get_parameters_schema(),
            "timeout": self.timeout,
        }
    
    def validate_parameters(self, **kwargs) -> Optional[str]:
        """
        验证参数合法性
        
        检查必需参数是否存在，参数类型是否正确。
        
        Args:
            **kwargs: 传入的参数
            
        Returns:
            错误信息字符串，如果验证通过则返回None
        """
        for param_name, param in self._parameters.items():
            if param.required and param_name not in kwargs:
                return f"缺少必需参数: {param_name}"
            
            if param_name in kwargs:
                value = kwargs[param_name]
                error = self._validate_param_type(param_name, param, value)
                if error:
                    return error
        
        return None
    
    def _validate_param_type(self, param_name: str, param: ToolParameter, value: Any) -> Optional[str]:
        """
        验证单个参数的类型
        
        Args:
            param_name: 参数名
            param: 参数定义
            value: 参数值
            
        Returns:
            错误信息，验证通过返回None
        """
        if value is None:
            if param.required:
                return f"参数 {param_name} 不能为None"
            return None
        
        type_validators = {
            "string": lambda v: isinstance(v, str),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
            "array": lambda v: isinstance(v, list),
            "object": lambda v: isinstance(v, dict),
        }
        
        validator = type_validators.get(param.param_type)
        if validator and not validator(value):
            return f"参数 {param_name} 类型错误: 期望 {param.param_type}, 实际 {type(value).__name__}"
        
        if param.enum and value not in param.enum:
            return f"参数 {param_name} 值无效: 期望 {param.enum}, 实际 {value}"
        
        return None
    
    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """
        执行工具（抽象方法，子类必须实现）
        
        Args:
            **kwargs: 工具参数
            
        Returns:
            ToolResult: 工具执行结果
        """
        pass
    
    def run(self, **kwargs) -> ToolResult:
        """
        运行工具（包含参数验证和执行时间统计）
        
        这是工具的主入口方法，包含完整的执行流程：
        1. 参数验证
        2. 执行工具
        3. 统计执行时间
        4. 记录日志
        
        Args:
            **kwargs: 工具参数
            
        Returns:
            ToolResult: 工具执行结果
        """
        start_time = time.time()
        
        validation_error = self.validate_parameters(**kwargs)
        if validation_error:
            logger.warning(f"[{self.name}] 参数验证失败: {validation_error}")
            return ToolResult.invalid_params(validation_error)
        
        logger.debug(f"[{self.name}] 开始执行 | 参数: {kwargs}")
        
        try:
            result = self.execute(**kwargs)
            result.execution_time = time.time() - start_time
            
            if result.is_success:
                logger.info(
                    f"[{self.name}] 执行成功 | 耗时: {result.execution_time:.3f}s"
                )
            else:
                logger.warning(
                    f"[{self.name}] 执行失败 | 错误: {result.error} | 耗时: {result.execution_time:.3f}s"
                )
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"执行异常: {str(e)}"
            logger.error(f"[{self.name}] {error_msg}", exc_info=True)
            return ToolResult.failure(error_msg, execution_time=execution_time)
    
    def __repr__(self) -> str:
        return f"Tool(name='{self.name}', description='{self.description[:30]}...')"
