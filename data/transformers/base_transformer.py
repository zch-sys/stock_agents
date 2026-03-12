"""
转换器基类
定义数据转换器的统一接口
"""
from abc import ABC, abstractmethod
from typing import Generic, TypeVar, List, Optional, Dict, Any
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.schemas.base_schema import BaseSchema

InputType = TypeVar('InputType')
OutputType = TypeVar('OutputType', bound=BaseSchema)


class BaseTransformer(ABC, Generic[InputType, OutputType]):
    """
    数据转换器基类
    
    负责将数据库ORM对象转换为分析数据结构
    所有具体转换器都应继承此类
    """
    
    @abstractmethod
    def transform(self, data: InputType) -> OutputType:
        """
        将原始数据转换为分析数据
        
        Args:
            data: 数据库ORM对象
            
        Returns:
            转换后的分析数据结构
        """
        pass
    
    def transform_batch(self, data_list: List[InputType]) -> List[OutputType]:
        """
        批量转换数据
        
        Args:
            data_list: 数据库ORM对象列表
            
        Returns:
            转换后的分析数据结构列表
        """
        return [self.transform(data) for data in data_list]
    
    def validate_input(self, data: InputType) -> bool:
        """
        验证输入数据完整性
        
        Args:
            data: 输入数据
            
        Returns:
            数据是否有效
        """
        return data is not None
    
    def get_missing_fields(self, data: InputType, required_fields: List[str]) -> List[str]:
        """
        获取缺失的必填字段
        
        Args:
            data: 输入数据
            required_fields: 必填字段列表
            
        Returns:
            缺失字段列表
        """
        missing = []
        for field in required_fields:
            value = getattr(data, field, None)
            if value is None:
                missing.append(field)
        return missing
    
    def safe_get(self, data: Any, field: str, default: Any = None) -> Any:
        """
        安全获取属性值
        
        Args:
            data: 数据对象
            field: 属性名
            default: 默认值
            
        Returns:
            属性值或默认值
        """
        if data is None:
            return default
        value = getattr(data, field, None)
        return value if value is not None else default
    
    def safe_float(self, value: Any, default: float = 0.0) -> float:
        """
        安全转换为浮点数
        
        Args:
            value: 输入值
            default: 默认值
            
        Returns:
            浮点数值
        """
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    def safe_int(self, value: Any, default: int = 0) -> int:
        """
        安全转换为整数
        
        Args:
            value: 输入值
            default: 默认值
            
        Returns:
            整数值
        """
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    
    def safe_str(self, value: Any, default: str = "") -> str:
        """
        安全转换为字符串
        
        Args:
            value: 输入值
            default: 默认值
            
        Returns:
            字符串值
        """
        if value is None:
            return default
        return str(value)


class TransformerRegistry:
    """
    转换器注册表
    
    用于管理和获取各类转换器实例
    """
    
    _transformers: Dict[str, type] = {}
    
    @classmethod
    def register(cls, name: str):
        """
        注册转换器装饰器
        
        Args:
            name: 转换器名称
        """
        def decorator(transformer_class: type):
            cls._transformers[name] = transformer_class
            return transformer_class
        return decorator
    
    @classmethod
    def get(cls, name: str) -> Optional[BaseTransformer]:
        """
        获取转换器实例
        
        Args:
            name: 转换器名称
            
        Returns:
            转换器实例
        """
        transformer_class = cls._transformers.get(name)
        if transformer_class:
            return transformer_class()
        return None
    
    @classmethod
    def list_all(cls) -> List[str]:
        """
        列出所有已注册的转换器
        
        Returns:
            转换器名称列表
        """
        return list(cls._transformers.keys())
    
    @classmethod
    def count(cls) -> int:
        """
        获取已注册转换器数量
        
        Returns:
            转换器数量
        """
        return len(cls._transformers)
