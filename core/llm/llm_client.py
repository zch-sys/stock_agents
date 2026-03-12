# core/llm/llm_client.py

import json
import logging
import time
from typing import Dict, List, Any, Optional, Union
import openai  # 使用 openai 库兼容 DeepSeek API

from .llm_config import get_llm_config

logger = logging.getLogger(__name__)


def _get_retry_config() -> Dict[str, Any]:
    try:
        from agents.agent_config import get_agent_config
        agent_config = get_agent_config()
        default_settings = agent_config._get_default_settings()
        llm_settings = default_settings.get('llm', {})
        return {
            'max_retries': llm_settings.get('max_retries', 3),
            'timeout': llm_settings.get('timeout', 60.0),
        }
    except Exception:
        return {'max_retries': 3, 'timeout': 60.0}


class LLMRetryError(Exception):
    def __init__(self, message: str, attempts: int, last_error: Exception):
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error


class LLMClient:
    """
    统一 LLM 客户端封装
    
    功能：
    1. 统一调用 DeepSeek API (兼容 OpenAI SDK)
    2. 支持结构化输出 (JSON Mode)
    3. 支持向量嵌入
    4. 异常处理与重试
    """
    
    def __init__(self, config=None):
        self.config = config or get_llm_config()
        retry_config = _get_retry_config()
        self.max_retries = retry_config['max_retries']
        self.timeout = retry_config['timeout']
        
        # 创建带精细超时配置的 httpx 客户端
        # connect_timeout: 连接建立超时（30秒足够）
        # read_timeout: 读取响应超时（180秒，因为 LLM 生成长文本需要时间）
        # write_timeout: 发送请求超时
        # pool_timeout: 连接池等待超时
        import httpx
        timeout_config = httpx.Timeout(
            connect=30.0,
            read=180.0,  # 读取超时增加到 180 秒
            write=60.0,
            pool=30.0
        )
        http_client = httpx.Client(timeout=timeout_config)
        
        # 禁用 OpenAI SDK 的自动重试（我们有自己的重试逻辑）
        self.client = openai.OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            http_client=http_client,
            max_retries=0  # 禁用 SDK 内置重试
        )
        logger.info(f"LLM Client 初始化成功 | Base URL: {self.config.base_url} | Max Retries: {self.max_retries} | Read Timeout: 180s")
        
        # 创建独立的 Embedding 客户端（使用不同的 API 配置）
        embedding_api_key = self.config.embedding_api_key
        embedding_base_url = self.config.embedding_base_url
        
        if embedding_api_key != self.config.api_key or embedding_base_url != self.config.base_url:
            # Embedding 使用独立的 API 配置
            self._embedding_client = openai.OpenAI(
                api_key=embedding_api_key,
                base_url=embedding_base_url,
                http_client=httpx.Client(timeout=self.timeout)
            )
            logger.info(f"Embedding Client 初始化成功 | Base URL: {embedding_base_url}")
        else:
            # 使用主客户端
            self._embedding_client = self.client
            logger.info("Embedding 使用主 LLM Client")
    
    def chat(
        self, 
        messages: List[Dict[str, str]], 
        model: str = None,
        max_retries: int = None,
        **kwargs
    ) -> str:
        """
        基础对话补全（带重试机制）
        
        Args:
            messages: OpenAI 格式的消息列表 [{"role": "user", "content": "..."}]
            model: 指定模型，默认使用 default_model
            max_retries: 最大重试次数，默认使用配置值
            **kwargs: 其他参数 (temperature, max_tokens等)
        
        Returns:
            助手的回复文本
        """
        model = model or self.config.default_model
        params = self.config.get_generation_params("default")
        params.update(kwargs)
        
        retries = max_retries if max_retries is not None else self.max_retries
        last_error = None
        
        for attempt in range(1, retries + 1):
            try:
                logger.debug(f"发送 LLM 请求 | Model: {model} | Messages: {len(messages)}条 | 尝试: {attempt}/{retries}")
                
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    **params
                )
                
                content = response.choices[0].message.content
                logger.debug("LLM 响应成功")
                return content
                
            except openai.APIConnectionError as e:
                last_error = e
                logger.warning(f"API 连接失败 (尝试 {attempt}/{retries}): {e}")
                if attempt < retries:
                    wait_time = 2 ** attempt
                    logger.info(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    
            except openai.RateLimitError as e:
                last_error = e
                logger.warning(f"API 限流 (尝试 {attempt}/{retries}): {e}")
                if attempt < retries:
                    wait_time = 60
                    logger.info(f"限流，等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    
            except openai.APITimeoutError as e:
                last_error = e
                logger.warning(f"API 超时 (尝试 {attempt}/{retries}): {e}")
                if attempt < retries:
                    wait_time = 2 ** attempt
                    logger.info(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    
            except Exception as e:
                last_error = e
                logger.error(f"LLM 调用未知错误 (尝试 {attempt}/{retries}): {e}")
                if attempt < retries:
                    wait_time = 2 ** attempt
                    logger.info(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
        
        raise LLMRetryError(
            f"LLM 调用失败，已重试 {retries} 次",
            attempts=retries,
            last_error=last_error
        )
    
    def chat_with_system(
        self, 
        system_prompt: str, 
        user_prompt: str, 
        model: str = None,
        **kwargs
    ) -> str:
        """
        带系统提示的快捷对话方法
        
        Args:
            system_prompt: 系统人设
            user_prompt: 用户问题
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        return self.chat(messages, model=model, **kwargs)
    
    def structured_output(
        self, 
        messages: List[Dict[str, str]], 
        schema: Dict = None,
        model: str = None,
        max_retries: int = None
    ) -> Dict[str, Any]:
        """
        结构化输出 (强制返回 JSON，带重试机制)
        
        Args:
            messages: 消息列表
            schema: (可选) JSON Schema
            model: 指定模型
            max_retries: 最大重试次数
        
        Returns:
            解析后的 Python 字典
        """
        model = model or self.config.analysis_model
        params = self.config.get_generation_params("analysis")
        
        retries = max_retries if max_retries is not None else self.max_retries
        last_error = None
        
        for attempt in range(1, retries + 1):
            try:
                logger.debug(f"结构化输出请求 | Model: {model} | 尝试: {attempt}/{retries}")
                
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    **params
                )
                
                content = response.choices[0].message.content
                
                try:
                    result = json.loads(content)
                    logger.debug("结构化输出成功")
                    return result
                except json.JSONDecodeError as je:
                    logger.warning(f"JSON 解析失败 (尝试 {attempt}/{retries}): {je}")
                    try:
                        cleaned = content.strip().replace("```json", "").replace("```", "")
                        result = json.loads(cleaned)
                        logger.debug("JSON 清洗后解析成功")
                        return result
                    except json.JSONDecodeError:
                        last_error = je
                        if attempt < retries:
                            wait_time = 2 ** attempt
                            logger.info(f"等待 {wait_time} 秒后重试...")
                            time.sleep(wait_time)
                            
            except openai.APIConnectionError as e:
                last_error = e
                logger.warning(f"API 连接失败 (尝试 {attempt}/{retries}): {e}")
                if attempt < retries:
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
                    
            except openai.RateLimitError as e:
                last_error = e
                logger.warning(f"API 限流 (尝试 {attempt}/{retries}): {e}")
                if attempt < retries:
                    time.sleep(60)
                    
            except openai.APITimeoutError as e:
                last_error = e
                logger.warning(f"API 超时 (尝试 {attempt}/{retries}): {e}")
                if attempt < retries:
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
                    
            except Exception as e:
                last_error = e
                logger.error(f"结构化输出未知错误 (尝试 {attempt}/{retries}): {e}")
                if attempt < retries:
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
        
        raise LLMRetryError(
            f"结构化输出失败，已重试 {retries} 次",
            attempts=retries,
            last_error=last_error
        )

    def stream(
        self, 
        messages: List[Dict[str, str]], 
        model: str = None,
        **kwargs
    ):
        """
        流式输出
        
        Yields:
            str: 每次生成的文本片段
        """
        model = model or self.config.default_model
        params = self.config.get_generation_params("default")
        params.update(kwargs)
        
        try:
            stream = self.client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                **params
            )
            
            for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            logger.error(f"流式输出错误: {e}")
            raise
    
    def embed(self, text: Union[str, List[str]]) -> List[List[float]]:
        """
        文本向量化 (用于长期记忆的向量检索)
        
        Args:
            text: 单个文本字符串或文本列表
        
        Returns:
            向量列表
        """
        if isinstance(text, str):
            text = [text]
            
        try:
            logger.debug(f"生成 Embedding | 数量: {len(text)} | Model: {self.config.embedding_model}")
            response = self._embedding_client.embeddings.create(
                model=self.config.embedding_model,
                input=text
            )
            
            # 返回向量列表
            return [item.embedding for item in response.data]
            
        except Exception as e:
            logger.error(f"Embedding 生成失败: {e}")
            raise

# # ================== 测试代码 ==================
# if __name__ == "__main__":
#     # 简单测试
#     try:
#         client = LLMClient()
        
#         # 1. 测试基础对话
#         print("--- 测试基础对话 ---")
#         res = client.chat_with_system(
#             system_prompt="你是一个专业的A股分析师。",
#             user_prompt="请用一句话评价今天的A股市场。"
#         )
#         print(f"回复: {res}")
        
#         # 2. 测试结构化输出
#         print("\n--- 测试结构化输出 ---")
#         json_res = client.structured_output(
#             messages=[
#                 {"role": "system", "content": "请输出JSON格式"},
#                 {"role": "user", "content": "请返回一个包含stock和action字段的字典，股票是平安银行，动作为买入。"}
#             ]
#         )
#         print(f"JSON结果: {json_res}")
        
#         # 3. 测试 Embedding
#         print("\n--- 测试 Embedding ---")
#         vec = client.embed("测试文本")
#         print(f"向量维度: {len(vec[0])}") # DeepSeek embedding 通常是 1536 或更高维度
        
#     except Exception as e:
#         print(f"测试失败: {e}")