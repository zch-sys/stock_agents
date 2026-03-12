# core/llm/llm_config.py

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional

class LLMConfig:
    """
    LLM 配置管理器
    
    功能：
    1. 从 settings.yaml 加载配置
    2. 支持环境变量覆盖 (DEEPSEEK_API_KEY)
    3. 提供不同场景的参数配置
    """
    
    def __init__(self, config_path: str = None):
        # 定位配置文件路径
        if config_path is None:
            # 默认取项目根目录下的 config/settings.yaml
            root_path = Path(__file__).resolve().parent.parent.parent
            config_path = root_path / "config" / "settings.yaml"
        
        self.config_path = Path(config_path)
        self._config = self._load_config()
        
    def _load_config(self) -> Dict[str, Any]:
        """加载 YAML 配置文件"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件未找到: {self.config_path}")
            
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    @property
    def api_key(self) -> str:
        """
        获取 API Key
        优先级：环境变量 > 配置文件
        """
        key = os.getenv("DEEPSEEK_API_KEY")
        if key:
            return key
        
        key = self._config.get('llm', {}).get('api_key')
        if not key:
            raise ValueError("未配置 DeepSeek API Key，请在 settings.yaml 或环境变量中设置")
        return key
    
    @property
    def base_url(self) -> str:
        """获取 API Base URL"""
        return self._config.get('llm', {}).get('base_url', 'https://api.deepseek.com')
    
    @property
    def default_model(self) -> str:
        """获取默认模型名称"""
        return self._config.get('llm', {}).get('models', {}).get('default', 'deepseek-chat')
    
    @property
    def analysis_model(self) -> str:
        """获取分析任务专用模型"""
        return self._config.get('llm', {}).get('models', {}).get('analysis', 'deepseek-chat')
    
    @property
    def embedding_model(self) -> str:
        """获取向量嵌入模型"""
        # 优先使用独立的 embedding 配置
        embedding_config = self._config.get('llm', {}).get('embedding', {})
        if embedding_config:
            return embedding_config.get('model', 'Qwen/Qwen3-Embedding-8B')
        return self._config.get('llm', {}).get('models', {}).get('embedding', 'deepseek-embedding')
    
    @property
    def embedding_api_key(self) -> str:
        """获取嵌入模型专用的 API Key"""
        # 优先级：环境变量 > embedding 独立配置 > 主配置
        key = os.getenv("EMBEDDING_API_KEY")
        if key:
            return key
        
        embedding_config = self._config.get('llm', {}).get('embedding', {})
        if embedding_config and 'api_key' in embedding_config:
            return embedding_config['api_key']
        
        # 回退到主 API Key
        return self.api_key
    
    @property
    def embedding_base_url(self) -> str:
        """获取嵌入模型专用的 Base URL"""
        embedding_config = self._config.get('llm', {}).get('embedding', {})
        if embedding_config and 'base_url' in embedding_config:
            return embedding_config['base_url']
        
        # 回退到主 Base URL
        return self.base_url
    
    def get_generation_params(self, mode: str = "default") -> Dict[str, Any]:
        """
        获取生成参数
        
        Args:
            mode: 模式，可选 "default" 或 "analysis"
        """
        if mode == "analysis":
            return self._config.get('llm', {}).get('analysis_params', {"temperature": 0.1, "max_tokens": 8000})
        
        return self._config.get('llm', {}).get('default_params', {"temperature": 0.7, "max_tokens": 4000})

# 全局单例（方便直接调用）
_config_instance = None

def get_llm_config() -> LLMConfig:
    """获取全局配置单例"""
    global _config_instance
    if _config_instance is None:
        _config_instance = LLMConfig()
    return _config_instance