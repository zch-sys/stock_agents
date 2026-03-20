# TI (Trade Intelligence) 
### —— 基于多智能体协作与计划驱动的 A 股自动化交易系统

TI 是一个高度工程化的 AI 投资系统。它不仅仅是量化选股，而是模拟了一个“基金经理+研究团队”的工作流。系统通过 **PostgreSQL** 承载核心状态，利用 **LLM Agents** 进行多维度辩论，并最终生成具备连贯性的作战计划。

---

## 🛠 系统架构与设计哲学

### 1. 漏斗式核心流程
- **Stage 1: 量化初筛 (The Filter)**：脚本每日自动扫描全市场，根据爆发力、趋势、价值三个维度初步筛选 30 只标的。
- **Stage 2: 专家辩论 (The Debate)**：针对入选标的，启动五大分析师 Agent（基本面、技术面、大盘、板块、情绪）进行深度研判，并由经理生成综合报告。
- **Stage 3: 计划架构 (The Planning)**：系统围绕“计划”运行。根据标的类型生成短/中/长嵌套计划，包含双重止盈止损位。
- **Stage 4: 自动化执行 (The Execution)**：账户管家根据仓位优先级，将计划转化为次日可执行的 API 指令。
- **Stage 5: 向量复盘 (The Memory)**：成交后或计划结束时，系统对比逻辑与现实，提取“经验向量”永久存入 pgvector。

### 2. 存储策略
- **结构化数据**：行情、指标、资金流。
- **半结构化 (JSONB)**：股票档案、运行状态机、多级计划参数。
- **非结构化 (Vector)**：历史复盘经验、新闻语义特征。

---

## 📂 文件夹结构说明

```text
GTI_System/
├── app/                        # 核心业务代码
│   ├── agents/                 # 智能体定义层
│   │   ├── base_agent.py       # Agent 基类，处理 LLM 连接与工具调用
│   │   ├── researchers/        # 研究团队：处理五大维度分析 (Fundamental, Tech, etc.)
│   │   ├── planners/           # 计划团队：PlanArchitect (生成计划), PlanArbiter (更新计划)
│   │   ├── execution/          # 交易团队：AccountManager (计算仓位), OrderGenerator (生成指令)
│   │   └── reviewers/          # 复盘团队：执行复盘、逻辑归因、经验提取
│   ├── core/                   # 系统中枢
│   │   ├── orchestrator.py     # 每日任务总调度：控制工作流时序
│   │   ├── state_machine.py    # 计划状态机：判定股票处于哪个计划阶段
│   │   └── llm_bridge.py       # LLM 统一接口（OpenAI/Claude/Local）
│   ├── data/                   # 数据层
│   │   ├── basic_data          # 数据采取
│   │   │   ├── indexdata.py    # 指数板块数据采集
│   │   │   ├── stock.py        # 个股数据采集
│   │   │   ├── newsdata.py     # 个股新闻数据采集
│   │   ├── scheduler.py        # 数据调度器
│   │   └── database.py         # 数据库定义与 SQLAlchemy ORM 模型
│   └── trading/                # 执行层
│       ├── api_connector.py    # 券商 API 桥接器
│       └── risk_control.py     # 盘中硬风控（回撤检查、异常熔断）
├── config/                     # 配置中心
│   ├── settings.yaml           # API Keys, 数据库 URL, 交易阈值
│   └── prompts.yaml            # 统一管理各 Agent 的系统提示词
├── storage/                    # 存储层 (非 DB)
│   ├── logs/                   # 运行日志s
│   └── reports/                # 每日生成的 PDF/JSON 报告备份
├── test_tool/                  # 测试工具
│   ├── collectdata.py          # 全量数据收集测试
│   └── testconnection.py       # 数据库连接测试
│   └── newtest.py              # 新闻爬虫测试
├── main.py                     # 入口脚本：收盘后一键运行
└── requirements.txt            # 项目依赖
