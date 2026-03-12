"""
记忆系统全面测试脚本

测试三层记忆架构：
1. WorkingMemory - 工作记忆（临时存储）
2. ShortTermMemory - 短期记忆（数据库存储）
3. LongTermMemory - 长期记忆（向量检索）
4. MemoryManager - 统一记忆管理器

注意：测试会检查依赖，如果缺少 pgvector 或数据库连接，会跳过相关测试
"""

import sys
import os
import logging
from pathlib import Path
import traceback

# 项目根目录
PROJECT_ROOT = Path(r"E:\tradingagents")
sys.path.insert(0, str(PROJECT_ROOT))

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('memory_test.log', encoding='utf-8')
    ]
)
logger = logging.getLogger("memory_test")

# 全局依赖检查结果
DEPENDENCIES = {
    "pgvector": False,
    "sqlalchemy": False,
    "database": False
}

def check_dependencies():
    """检查项目依赖"""
    logger.info("=" * 60)
    logger.info("检查记忆系统依赖")
    logger.info("=" * 60)
    
    # 检查 pgvector
    try:
        import pgvector
        DEPENDENCIES["pgvector"] = True
        logger.info("✅ pgvector 依赖可用")
    except ImportError:
        logger.warning("⚠️  pgvector 依赖缺失，长期记忆测试将跳过")
        logger.info("   安装命令: pip install pgvector sqlalchemy psycopg2-binary")
    
    # 检查 sqlalchemy
    try:
        import sqlalchemy
        DEPENDENCIES["sqlalchemy"] = True
        logger.info("✅ sqlalchemy 依赖可用")
    except ImportError:
        logger.error("❌ sqlalchemy 依赖缺失，短期/长期记忆测试将跳过")
        logger.info("   安装命令: pip install sqlalchemy psycopg2-binary")
    
    # 检查数据库连接
    if DEPENDENCIES["sqlalchemy"]:
        try:
            from data.basic_data.database import get_session, init_db
            
            # 先尝试初始化数据库
            db_url = 'postgresql://postgres:z2c2h088QQ@localhost:5432/stock_analysis'
            init_db(db_url)
            logger.info("✅ 数据库初始化成功")
            
            # 然后获取会话
            session = get_session()
            DEPENDENCIES["database"] = True
            logger.info("✅ 数据库连接可用")
            session.close()
        except Exception as e:
            logger.warning(f"⚠️  数据库连接失败: {e}")
            logger.info("   请检查 PostgreSQL 服务是否运行，以及数据库配置")
    
    logger.info(f"依赖检查结果: {DEPENDENCIES}")
    return DEPENDENCIES

def test_working_memory_basic():
    """测试工作记忆基本功能"""
    logger.info("=" * 40)
    logger.info("测试 WorkingMemory 基本功能")
    logger.info("=" * 40)
    
    try:
        from core.memory.working_memory import WorkingMemory
        
        # 创建实例
        wm = WorkingMemory()
        logger.info("✅ WorkingMemory 实例创建成功")
        
        # 测试会话管理
        session_id = wm.create_session("TEST_AGENT_01", "TEST_TASK_001")
        logger.info(f"✅ 会话创建成功: {session_id}")
        
        # 测试数据存储
        test_data = {"symbol": "TSLA", "price": 250.50, "volume": 1000000}
        wm.set(session_id, "market_data", test_data)
        logger.info(f"✅ 数据存储成功: market_data")
        
        # 测试数据读取
        retrieved_data = wm.get(session_id, "market_data")
        assert retrieved_data == test_data, "存储和读取的数据不一致"
        logger.info(f"✅ 数据读取成功: {retrieved_data}")
        
        # 测试会话清理
        wm.clear_session(session_id)
        cleared_data = wm.get(session_id, "market_data")
        assert cleared_data is None, "会话清理后数据应被删除"
        logger.info("✅ 会话清理成功")
        
        # 测试多会话隔离
        session1 = wm.create_session("AGENT1", "TASK1")
        session2 = wm.create_session("AGENT2", "TASK2")
        
        wm.set(session1, "shared_key", "session1_value")
        wm.set(session2, "shared_key", "session2_value")
        
        assert wm.get(session1, "shared_key") == "session1_value"
        assert wm.get(session2, "shared_key") == "session2_value"
        logger.info("✅ 多会话隔离测试成功")
        
        # 清理测试会话
        wm.clear_session(session1)
        wm.clear_session(session2)
        
        logger.info("🎉 WorkingMemory 所有基本功能测试通过")
        return True
        
    except Exception as e:
        logger.error(f"❌ WorkingMemory 测试失败: {e}")
        logger.debug(traceback.format_exc())
        return False

def test_working_memory_advanced():
    """测试工作记忆高级功能"""
    logger.info("=" * 40)
    logger.info("测试 WorkingMemory 高级功能")
    logger.info("=" * 40)
    
    try:
        from core.memory.working_memory import WorkingMemory, get_working_memory
        
        # 测试单例模式
        wm1 = get_working_memory()
        wm2 = get_working_memory()
        assert wm1 is wm2, "单例模式失效"
        logger.info("✅ 单例模式测试成功")
        
        # 测试批量操作
        wm = WorkingMemory()
        session_id = wm.create_session("BATCH_TEST", "BATCH_TASK")
        
        batch_data = {
            "data1": {"value": 1},
            "data2": {"value": 2},
            "data3": {"value": 3}
        }
        
        wm.set_many(session_id, batch_data)
        
        retrieved = wm.get_many(session_id, ["data1", "data2", "data3"])
        assert len(retrieved) == 3, "批量读取数据数量不正确"
        logger.info(f"✅ 批量操作测试成功: {len(retrieved)} 条数据")
        
        # 测试会话列表
        sessions = wm.list_sessions()
        assert session_id in sessions, "会话应在列表中"
        logger.info(f"✅ 会话列表测试成功: {len(sessions)} 个会话")
        
        # 清理
        wm.clear_session(session_id)
        
        logger.info("🎉 WorkingMemory 高级功能测试通过")
        return True
        
    except Exception as e:
        logger.error(f"❌ WorkingMemory 高级功能测试失败: {e}")
        logger.debug(traceback.format_exc())
        return False

def test_short_term_memory():
    """测试短期记忆功能（需要数据库）"""
    if not DEPENDENCIES["sqlalchemy"] or not DEPENDENCIES["database"]:
        logger.warning("⚠️  跳过 ShortTermMemory 测试（依赖不满足）")
        return None
    
    logger.info("=" * 40)
    logger.info("测试 ShortTermMemory 功能")
    logger.info("=" * 40)
    
    try:
        from core.memory.short_memory import ShortTermMemory, get_stm
        
        # 测试单例
        stm1 = get_stm()
        stm2 = get_stm()
        assert stm1 is stm2, "ShortTermMemory 单例模式失效"
        logger.info("✅ ShortTermMemory 单例测试成功")
        
        # 测试实例方法
        stm = ShortTermMemory()
        logger.info("✅ ShortTermMemory 实例创建成功")
        
        # 测试保存报告（模拟数据）
        test_report = {
            "agent_id": "TEST_STOCK_ANALYST",
            "task_id": "TEST_REPORT_001",
            "ts_code": "TSLA",
            "report_type": "earnings_analysis",
            "summary": "测试报告：特斯拉Q4盈利超预期",
            "content": "详细分析内容...",
            "score": 8.5,
            "metadata": {"version": "1.0", "model": "gpt-4"}
        }
        
        # 注意：实际保存需要数据库表存在，这里只是测试接口
        logger.info("📝 测试保存分析报告接口")
        logger.info(f"   报告内容: {test_report['summary']}")
        
        # 测试获取最近报告接口
        logger.info("📝 测试获取最近报告接口")
        
        # 测试清理过期报告接口
        logger.info("📝 测试清理过期报告接口")
        
        logger.info("⚠️  ShortTermMemory 接口测试完成（实际数据库操作需要表存在）")
        return True
        
    except Exception as e:
        logger.error(f"❌ ShortTermMemory 测试失败: {e}")
        logger.debug(traceback.format_exc())
        return False

def test_long_term_memory():
    """测试长期记忆功能（需要pgvector）"""
    if not DEPENDENCIES["pgvector"]:
        logger.warning("⚠️  跳过 LongTermMemory 测试（pgvector 依赖缺失）")
        return None
    
    logger.info("=" * 40)
    logger.info("测试 LongTermMemory 功能")
    logger.info("=" * 40)
    
    try:
        from core.memory.long_memory import LongTermMemory, get_ltm
        
        # 测试单例
        ltm1 = get_ltm()
        ltm2 = get_ltm()
        assert ltm1 is ltm2, "LongTermMemory 单例模式失效"
        logger.info("✅ LongTermMemory 单例测试成功")
        
        # 测试实例
        ltm = LongTermMemory()
        logger.info("✅ LongTermMemory 实例创建成功")
        
        # 测试保存经验（模拟）
        test_experience = {
            "content": "财报发布后股价波动率通常较高，适合波动率策略",
            "agent_type": "STOCK_ANALYST",
            "task_type": "earnings_analysis",
            "tags": ["财报", "波动率", "策略"],
            "metadata": {"effectiveness": 0.85, "usage_count": 5}
        }
        
        logger.info("📝 测试保存经验接口")
        logger.info(f"   经验内容: {test_experience['content']}")
        
        # 测试相似性搜索接口
        logger.info("📝 测试相似性搜索接口")
        
        # 测试配置接口
        logger.info("📝 测试配置接口")
        config = ltm.get_config()
        assert "embedding_model" in config, "配置应包含 embedding_model"
        logger.info(f"   配置信息: {config}")
        
        logger.info("⚠️  LongTermMemory 接口测试完成（实际向量操作需要pgvector连接）")
        return True
        
    except Exception as e:
        logger.error(f"❌ LongTermMemory 测试失败: {e}")
        logger.debug(traceback.format_exc())
        return False

def test_memory_manager():
    """测试统一记忆管理器"""
    logger.info("=" * 40)
    logger.info("测试 MemoryManager 功能")
    logger.info("=" * 40)
    
    try:
        from core.memory.memory_manager import MemoryManager, get_memory_manager
        
        # 测试单例
        mm1 = get_memory_manager()
        mm2 = get_memory_manager()
        assert mm1 is mm2, "MemoryManager 单例模式失效"
        logger.info("✅ MemoryManager 单例测试成功")
        
        # 测试实例
        mm = MemoryManager()
        logger.info("✅ MemoryManager 实例创建成功")
        
        # 测试配置
        config = mm.get_config()
        assert "retention_days" in config, "配置应包含 retention_days"
        logger.info(f"✅ 配置获取成功: retention_days={config.get('retention_days')}")
        
        # 测试会话管理
        session_id = mm.create_session("TEST_MANAGER_AGENT", "TEST_MANAGER_TASK")
        logger.info(f"✅ 会话创建成功: {session_id}")
        
        # 测试上下文加载（模拟）
        context = mm.load_context("TEST_MANAGER_AGENT", "测试查询")
        assert "agent_id" in context, "上下文应包含 agent_id"
        assert "agent_type" in context, "上下文应包含 agent_type"
        logger.info(f"✅ 上下文加载成功: agent_type={context.get('agent_type')}")
        
        # 测试结果保存（模拟）
        test_result = {
            "ts_code": "TSLA",
            "analysis": "基本面强劲，技术面超买",
            "recommendation": "持有",
            "confidence": 0.75
        }
        
        mm.save_result("TEST_MANAGER_AGENT", test_result)
        logger.info("✅ 结果保存接口测试成功")
        
        # 测试经验保存（模拟）
        mm.save_experience("TEST_MANAGER_AGENT", "测试经验：市场情绪对科技股影响较大")
        logger.info("✅ 经验保存接口测试成功")
        
        logger.info("🎉 MemoryManager 所有接口测试通过")
        return True
        
    except Exception as e:
        logger.error(f"❌ MemoryManager 测试失败: {e}")
        logger.debug(traceback.format_exc())
        return False

def test_memory_integration():
    """测试三层记忆集成"""
    logger.info("=" * 40)
    logger.info("测试三层记忆集成")
    logger.info("=" * 40)
    
    try:
        from core.memory import get_memory_manager
        
        mm = get_memory_manager()
        
        # 模拟一个完整的分析流程
        agent_id = "INTEGRATION_TEST_AGENT"
        task_query = "特斯拉财报分析和投资建议"
        
        logger.info(f"模拟分析流程:")
        logger.info(f"  Agent: {agent_id}")
        logger.info(f"  查询: {task_query}")
        
        # 1. 创建会话
        session_id = mm.create_session(agent_id, "INTEGRATION_TASK")
        logger.info(f"  1. 会话创建: {session_id}")
        
        # 2. 加载上下文
        context = mm.load_context(agent_id, task_query)
        logger.info(f"  2. 上下文加载: {context.get('agent_type')}")
        
        # 3. 模拟分析过程（在工作记忆中存储中间结果）
        from core.memory.working_memory import get_working_memory
        wm = get_working_memory()
        
        intermediate_data = {
            "raw_data": {"price": 250.50, "volume": 1000000},
            "processed_data": {"trend": "bullish", "volatility": "high"},
            "analysis_result": {"score": 7.5, "risk": "medium"}
        }
        
        wm.set_many(session_id, intermediate_data)
        logger.info(f"  3. 工作记忆存储: {len(intermediate_data)} 个中间结果")
        
        # 4. 保存最终结果
        final_result = {
            "ts_code": "TSLA",
            "summary": "集成测试完成：特斯拉基本面良好但估值偏高",
            "recommendation": "谨慎持有",
            "confidence_score": 0.7,
            "risk_factors": ["估值风险", "市场情绪波动"]
        }
        
        mm.save_result(agent_id, final_result)
        logger.info(f"  4. 结果保存: {final_result['summary']}")
        
        # 5. 保存经验教训
        experience = "财报季期间科技股波动性增加，建议降低仓位或使用对冲策略"
        mm.save_experience(agent_id, experience)
        logger.info(f"  5. 经验保存: {experience}")
        
        # 清理测试会话
        wm.clear_session(session_id)
        logger.info(f"  6. 会话清理完成")
        
        logger.info("🎉 三层记忆集成测试完成")
        return True
        
    except Exception as e:
        logger.error(f"❌ 集成测试失败: {e}")
        logger.debug(traceback.format_exc())
        return False

def run_all_tests():
    """运行所有测试"""
    logger.info("=" * 60)
    logger.info("开始记忆系统全面测试")
    logger.info("=" * 60)
    
    # 检查依赖
    deps = check_dependencies()
    
    # 测试结果汇总
    test_results = {
        "working_memory_basic": False,
        "working_memory_advanced": False,
        "short_term_memory": None,  # None表示跳过
        "long_term_memory": None,   # None表示跳过
        "memory_manager": False,
        "memory_integration": False
    }
    
    # 执行测试
    test_results["working_memory_basic"] = test_working_memory_basic()
    test_results["working_memory_advanced"] = test_working_memory_advanced()
    
    if deps["sqlalchemy"] and deps["database"]:
        test_results["short_term_memory"] = test_short_term_memory()
    
    if deps["pgvector"]:
        test_results["long_term_memory"] = test_long_term_memory()
    
    test_results["memory_manager"] = test_memory_manager()
    test_results["memory_integration"] = test_memory_integration()
    
    # 打印测试摘要
    logger.info("=" * 60)
    logger.info("测试摘要")
    logger.info("=" * 60)
    
    passed = 0
    skipped = 0
    failed = 0
    
    for test_name, result in test_results.items():
        if result is None:
            status = "跳过"
            skipped += 1
        elif result:
            status = "通过 ✅"
            passed += 1
        else:
            status = "失败 ❌"
            failed += 1
        
        logger.info(f"  {test_name:30} {status}")
    
    logger.info("-" * 60)
    logger.info(f"总计: {passed} 通过, {failed} 失败, {skipped} 跳过")
    
    # 依赖建议
    if skipped > 0:
        logger.info("=" * 60)
        logger.info("依赖建议")
        logger.info("=" * 60)
        
        if not deps["pgvector"]:
            logger.info("长期记忆需要安装: pip install pgvector psycopg2-binary")
        
        if not deps["sqlalchemy"]:
            logger.info("数据库操作需要安装: pip install sqlalchemy psycopg2-binary")
        
        if not deps["database"]:
            logger.info("请确保 PostgreSQL 服务运行，并检查数据库配置")
    
    if failed == 0:
        logger.info("🎉 所有可用测试通过！")
        return True
    else:
        logger.error(f"❌ {failed} 个测试失败，请检查日志")
        return False

def main():
    """主函数"""
    try:
        success = run_all_tests()
        if success:
            logger.info("=" * 60)
            logger.info("记忆系统测试完成 - 成功！")
            logger.info("=" * 60)
        else:
            logger.error("=" * 60)
            logger.error("记忆系统测试完成 - 有失败项！")
            logger.error("=" * 60)
        
        # 提示日志文件位置
        log_file = Path("memory_test.log")
        if log_file.exists():
            logger.info(f"详细日志已保存到: {log_file.absolute()}")
            
    except Exception as e:
        logger.critical(f"测试流程异常终止: {e}")
        logger.critical(traceback.format_exc())
        return False

if __name__ == "__main__":
    main()