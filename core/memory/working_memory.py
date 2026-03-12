# core/memory/working_memory.py

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class WorkingMemory:
    """
    工作记忆
    
    功能：
    1. 纯内存存储，生命周期仅限单次任务
    2. 基于 Session 隔离，支持多 Agent 并发互不干扰
    3. 用于暂存原始数据、中间结果、推理过程
    
    设计模式：
    - Key-Value 存储
    - Session 管理
    """
    
    def __init__(self):
        # 内部存储结构: {session_id: {key: value}}
        self._storage: Dict[str, Dict[str, Any]] = {}
        logger.debug("WorkingMemory 初始化完成")

    def create_session(self, agent_id: str, task_id: str) -> str:
        """
        创建一个新的工作记忆会话
        
        Args:
            agent_id: Agent 唯一标识
            task_id: 任务唯一标识
            
        Returns:
            session_id: 用于后续操作的会话 ID
        """
        session_id = f"{agent_id}_{task_id}"
        
        if session_id in self._storage:
            logger.warning(f"Session {session_id} 已存在，将被重置")
            
        self._storage[session_id] = {}
        logger.info(f"WorkingMemory 会话创建成功: {session_id}")
        return session_id

    def set(self, session_id: str, key: str, value: Any) -> None:
        """
        存储数据到工作记忆
        
        Args:
            session_id: 会话 ID
            key: 数据键 (如 'raw_data', 'analysis_result')
            value: 数据值 (任意 Python 对象)
        """
        if session_id not in self._storage:
            logger.error(f"Session {session_id} 不存在，无法存储数据")
            raise KeyError(f"Session {session_id} not found. Please create session first.")
        
        self._storage[session_id][key] = value
        logger.debug(f"WorkingMemory 写入: [{session_id}] -> {key}")

    def get(self, session_id: str, key: str, default: Any = None) -> Any:
        """
        从工作记忆读取数据
        
        Args:
            session_id: 会话 ID
            key: 数据键
            default: 如果键不存在返回的默认值
            
        Returns:
            存储的数据或默认值
        """
        session = self._storage.get(session_id)
        if not session:
            logger.warning(f"Session {session_id} 不存在")
            return default
        
        value = session.get(key, default)
        logger.debug(f"WorkingMemory 读取: [{session_id}] -> {key}")
        return value

    def get_all(self, session_id: str) -> Dict[str, Any]:
        """
        获取某个会话的所有数据
        """
        return self._storage.get(session_id, {})

    def delete(self, session_id: str, key: str) -> None:
        """
        删除会话中的某个键
        """
        if session_id in self._storage and key in self._storage[session_id]:
            del self._storage[session_id][key]
            logger.debug(f"WorkingMemory 删除: [{session_id}] -> {key}")

    def clear_session(self, session_id: str) -> None:
        """
        清空指定会话的所有数据（销毁草稿纸）
        
        这是生命周期结束时必须调用的方法，防止内存泄漏
        """
        if session_id in self._storage:
            del self._storage[session_id]
            logger.info(f"WorkingMemory 会话已销毁: {session_id}")
        else:
            logger.warning(f"尝试清空不存在的 Session: {session_id}")

    def exists(self, session_id: str) -> bool:
        """检查会话是否存在"""
        return session_id in self._storage

    def list_keys(self, session_id: str) -> list:
        """列出当前会话中的所有 Key"""
        return list(self._storage.get(session_id, {}).keys())

    # ==================== 预留接口：便捷方法 ====================
    # 为了方便 Agent 调用，可以预留一些特定业务场景的快捷方法
    
    def store_context(self, session_id: str, context_data: Dict) -> None:
        """
        批量存储上下文数据
        
        Args:
            context_data: 字典形式的数据，会 merge 到当前会话
        """
        if session_id not in self._storage:
            raise KeyError(f"Session {session_id} not found.")
        
        self._storage[session_id].update(context_data)
        logger.debug(f"WorkingMemory 批量写入: [{session_id}] -> {len(context_data)} items")
    
    def set_many(self, session_id: str, data_dict: Dict[str, Any]) -> None:
        """
        批量设置多个键值对
        
        Args:
            session_id: 会话 ID
            data_dict: 键值对字典
        """
        if session_id not in self._storage:
            raise KeyError(f"Session {session_id} not found.")
        
        self._storage[session_id].update(data_dict)
        logger.debug(f"WorkingMemory 批量设置: [{session_id}] -> {len(data_dict)} items")
    
    def get_many(self, session_id: str, keys: List[str]) -> Dict[str, Any]:
        """
        批量获取多个键的值
        
        Args:
            session_id: 会话 ID
            keys: 要获取的键列表
            
        Returns:
            包含键值对的字典（不存在的键会返回 None）
        """
        session = self._storage.get(session_id, {})
        result = {}
        for key in keys:
            result[key] = session.get(key)
        logger.debug(f"WorkingMemory 批量获取: [{session_id}] -> {len(keys)} keys")
        return result
    
    def list_sessions(self) -> List[str]:
        """
        列出所有活动会话
        
        Returns:
            会话ID列表
        """
        return list(self._storage.keys())


# ==================== 单例模式 ====================
# 工作记忆通常全局唯一，避免多处实例化导致内存不一致
_working_memory_instance = None

def get_working_memory() -> WorkingMemory:
    """获取全局工作记忆单例"""
    global _working_memory_instance
    if _working_memory_instance is None:
        _working_memory_instance = WorkingMemory()
    return _working_memory_instance


# # ==================== 测试代码 ====================
# if __name__ == "__main__":
#     logging.basicConfig(level=logging.INFO)
    
#     # 1. 获取实例
#     wm = get_working_memory()
    
#     # 2. 模拟 Agent A 的任务
#     agent_id = "MarketAnalyst_01"
#     task_id = "task_20231027"
#     session = wm.create_session(agent_id, task_id)
    
#     # 3. 存储中间数据
#     wm.set(session, "raw_data", {"close": 3000, "volume": 1000000})
#     wm.set(session, "step1_result", "趋势向上")
    
#     # 4. 读取数据
#     data = wm.get(session, "raw_data")
#     print(f"读取数据: {data}")
    
#     # 5. 查看所有 Key
#     print(f"当前所有 Key: {wm.list_keys(session)}")
    
#     # 6. 销毁会话
#     wm.clear_session(session)
    
#     # 7. 验证销毁
#     print(f"销毁后尝试读取: {wm.get(session, 'raw_data')}")
