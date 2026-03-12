# database.py - 优化版本
import datetime
from sqlalchemy import create_engine, Column, String, Float, Date, DateTime, Integer, JSON, Text, ForeignKey, Boolean, BigInteger, UniqueConstraint, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pgvector.sqlalchemy import Vector

Base = declarative_base()

# ----------------------------------------------------------------
# 1. 结构化行情类：大盘、板块、个股
# ----------------------------------------------------------------


class MarketIndex(Base):
    """大盘指数表：存储1200日数据，包含技术、资金流、情绪、估值等多维度数据"""
    __tablename__ = 'market_index'
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(20), index=True, comment='指数代码')
    trade_date = Column(Date, index=True, comment='交易日期')
    
    # 技术分析数据
    open = Column(Float, comment='开盘价')
    close = Column(Float, comment='收盘价')
    high = Column(Float, comment='最高价')
    low = Column(Float, comment='最低价')
    pct_chg = Column(Float, comment='涨跌幅%')
    vol = Column(Float, comment='成交量(手)')
    amount = Column(Float, comment='成交额(千元)')
    
    # 新增：技术指标
    ma5 = Column(Float, comment='5日均价')
    ma10 = Column(Float, comment='10日均价')
    ma20 = Column(Float, comment='20日均价')
    ma60 = Column(Float, comment='60日均价')

    macd = Column(Float, comment='MACD值')
    macd_signal = Column(Float, comment='MACD信号线')
    macd_hist = Column(Float, comment='MACD柱状图')
    adx = Column(Float, comment='ADX指标')
    
    # 北向资金数据（注意：moneyflow_hsgt返回的是总交易额，不是净流入）
    north_money_total = Column(Float, comment='北向资金总交易额(元)')
    
    # 两融数据
    margin_balance = Column(Float, comment='昨日融资余额')
    margin_buy = Column(Float, comment='昨日融资买入额')
    short_balance = Column(Float, comment='昨日融券余额')
    
    # 市场资金流向数据（全市场数据，仅存储在上证指数中）
    net_amount = Column(Float, comment='今日主力净流入净额(元)')
    net_amount_rate = Column(Float, comment='今日主力净流入净占比%')
    buy_elg_amount = Column(Float, comment='今日超大单净流入净额(元)')
    buy_elg_amount_rate = Column(Float, comment='今日超大单净流入净占比%')
    buy_lg_amount = Column(Float, comment='今日大单净流入净额(元)')
    buy_lg_amount_rate = Column(Float, comment='今日大单净流入净占比%')
    buy_md_amount = Column(Float, comment='今日中单净流入净额(元)')
    buy_md_amount_rate = Column(Float, comment='今日中单净流入净占比%')
    buy_sm_amount = Column(Float, comment='今日小单净流入净额(元)')
    buy_sm_amount_rate = Column(Float, comment='今日小单净流入净占比%')

    # 市场情绪与广度（从个股数据计算）
    adv_issues = Column(Integer, comment='上涨家数')
    dec_issues = Column(Integer, comment='下跌家数')
    adv_decline_ratio = Column(Float, comment='涨跌比')
    market_width = Column(Float, comment='市场宽度')
    ad_line = Column(Float, comment='腾落指数')
    turnover_concentration = Column(Float, comment='成交额集中度%')
    
    # 估值指标
    pe = Column(Float, comment='市盈率')
    pe_ttm = Column(Float, comment='市盈率TTM') 
    pb = Column(Float, comment='市净率')
    
    # 扩展数据
    extra_data = Column(JSON, comment='其他扩展数据')
    created_at = Column(DateTime, default=datetime.datetime.now)
    
    __table_args__ = (
        {'comment': '大盘指数日频数据表 - 保留1200日'},
    )
class SectorData(Base):

    """板块行情表：存储1200日数据"""

    __tablename__ = 'sector_data'
    id = Column(Integer, primary_key=True, autoincrement=True)
    sector_code = Column(String(20), index=True, comment='板块代码')
    sector_name = Column(String(100), index=True, comment='板块名称')
    trade_date = Column(Date, index=True, comment='交易日期')
    
    # 行情数据
    open = Column(Float, comment='开盘价（流通市值加权）')
    high = Column(Float, comment='最高价（流通市值加权）')
    low = Column(Float, comment='最低价（流通市值加权）')
    close = Column(Float, comment='收盘价（流通市值加权）')
    pre_close = Column(Float, comment='前收盘价（流通市值加权）')
    pct_chg = Column(Float, comment='板块指数涨跌幅%（基于加权价格计算）')
    
    # 成交量金额
    vol = Column(Float, comment='板块总成交量')
    amount = Column(Float, comment='板块总成交额')
    
    # 市值统计
    total_market_cap = Column(Float, comment='板块总市值')
    circ_market_cap = Column(Float, comment='板块流通市值')
    
    # 板块分析
    rank = Column(Integer, comment='涨幅排名')
    stock_count = Column(Integer, comment='成分股数量')
    rise_count = Column(Integer, comment='上涨家数')
    fall_count = Column(Integer, comment='下跌家数')
    unchanged_count = Column(Integer, comment='平盘家数')
    rise_fall_ratio = Column(Float, comment='涨跌家数比')
    
    # 资金流向
    fund_inflow = Column(Float, comment='资金净流入')
    fund_inflow_rate = Column(Float, comment='资金流入率%')
    rise_amount = Column(Float, comment='上涨股票总成交额')
    fall_amount = Column(Float, comment='下跌股票总成交额')
    
    # 统计指标
    avg_pct_chg = Column(Float, comment='成分股平均涨跌幅%')
    max_pct_chg = Column(Float, comment='成分股最大涨幅%')
    min_pct_chg = Column(Float, comment='成分股最小涨幅%')
    median_pct_chg = Column(Float, comment='成分股涨幅中位数%')
    std_pct_chg = Column(Float, comment='成分股涨幅标准差%')
    
    # 成分股数据
    constituent_stocks = Column(JSON, comment='成分股列表')
    
    # 系统字段
    created_at = Column(DateTime, default=datetime.datetime.now)
    
    __table_args__ = (
        UniqueConstraint('sector_code', 'trade_date', name='uq_sector_date'),
        {'comment': '板块日频数据表 - 保留1200日'},
    )

class StockDetail(Base):
    """个股全量数据表：包含行情、基本面、技术指标"""
    __tablename__ = 'stock_detail'
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(20), index=True, comment='股票代码')
    trade_date = Column(Date, index=True, comment='交易日期')
    name = Column(String(100), comment='股票名称')
    
    # 基础行情
    open = Column(Float, comment='开盘价')
    close = Column(Float, comment='收盘价')
    high = Column(Float, comment='最高价')
    low = Column(Float, comment='最低价')
    pct_chg = Column(Float, comment='涨跌幅%')
    vol = Column(BigInteger, comment='成交量(手)')
    amount = Column(Float, comment='成交额(千元)')
    pre_close = Column(Float, comment='前收盘价')
    change = Column(Float, comment='涨跌额')
    
    # 量价指标
    volume_ma5 = Column(Float, comment='5日成交量均值')
    volume_ma10 = Column(Float, comment='10日成交量均值')

    # 技术指标 - 计算得出
    ma5 = Column(Float, comment='5日均价')
    ma10 = Column(Float, comment='10日均价')
    ma20 = Column(Float, comment='20日均价')
    ma60 = Column(Float, comment='60日均价')
    
    # MACD指标
    macd = Column(Float, comment='MACD值')
    macd_signal = Column(Float, comment='MACD信号线')
    macd_hist = Column(Float, comment='MACD柱状图')
    
    # RSI指标
    rsi6 = Column(Float, comment='RSI6')
    rsi12 = Column(Float, comment='RSI12')
    rsi24 = Column(Float, comment='RSI24')
    
    # 布林带
    boll_upper = Column(Float, comment='布林上轨')
    boll_middle = Column(Float, comment='布林中轨')
    boll_lower = Column(Float, comment='布林下轨')
    
    # 基本面数据
    industry = Column(String(100), comment='所属行业')
    area = Column(String(50), comment='地区')
    market = Column(String(20), comment='市场类型')
    list_date = Column(Date, comment='上市日期')
    
    # 财务指标
    eps = Column(Float, comment='每股收益')
    bvps = Column(Float, comment='每股净资产')
    total_assets = Column(Float, comment='总资产')
    total_liab = Column(Float, comment='总负债')
    net_profit = Column(Float, comment='净利润')
    revenue = Column(Float, comment='营业收入')
    dv_ttm = Column(Float, comment='股息率（TTM）')
    # 估值指标
    pe = Column(Float, comment='市盈率')
    pb = Column(Float, comment='市净率')
    ps = Column(Float, comment='市销率')
    
    # 新增：市值相关字段
    total_mv = Column(Float, comment='总市值(万元)')
    circ_mv = Column(Float, comment='流通市值(万元)')
    total_share = Column(Float, comment='总股本(万股)')
    float_share = Column(Float, comment='流通股本(万股)')

    # 偿债能力
    debt_to_assets = Column(Float, comment='资产负债率%')
    current_ratio = Column(Float, comment='流动比率')
    quick_ratio = Column(Float, comment='速动比率')
    cash_ratio = Column(Float, comment='现金比率')
    
    # 增长指标
    revenue_yoy = Column(Float, comment='营收同比增长%')
    profit_yoy = Column(Float, comment='利润同比增长%')
    
    
    # 系统字段
    low_freq_update_date = Column(Date, comment='低频数据（基本面/财务/估值）上次更新日期')
    
    created_at = Column(DateTime, default=datetime.datetime.now)
    
    __table_args__ = (
        {'comment': '个股全维度日频数据表'},
    )

class StockFactor(Base):
    """个股因子数据表：宽表格式，每行代表一个股票在特定日期的所有因子"""
    __tablename__ = 'stock_factor'
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    ts_code = Column(String(20), index=True, comment='股票代码')
    trade_date = Column(Date, index=True, comment='交易日期')
    
    # 动量因子
    momentum_5d = Column(Float, comment='5日动量')
    momentum_20d = Column(Float, comment='20日动量')
    momentum_60d = Column(Float, comment='60日动量')
    momentum_120d = Column(Float, comment='120日动量')
    momentum_acceleration = Column(Float, comment='动量加速度')
    momentum_rank_20d = Column(Float, comment='20日动量行业排名')
    momentum_rank_120d = Column(Float, comment='120日动量行业排名')
    
    # 反转因子
    reversal_1d = Column(Float, comment='1日反转')
    reversal_5d = Column(Float, comment='5日反转')
    reversal_120d = Column(Float, comment='120日反转')
    
    # 波动率因子
    volatility_5d = Column(Float, comment='5日波动率')
    volatility_10d = Column(Float, comment='10日波动率')
    volatility_20d = Column(Float, comment='20日波动率')
    volatility_60d = Column(Float, comment='60日波动率')
    volatility_120d = Column(Float, comment='120日波动率')
    volatility_change = Column(Float, comment='波动率变化')
    volatility_long_term_dev = Column(Float, comment='长短期波动率偏离')
    low_volatility = Column(Float, comment='低波动率')
    volatility_anomaly = Column(Float, comment='波动率异常')
    
    # 量价因子
    overnight_return = Column(Float, comment='隔夜收益')
    overnight_momentum = Column(Float, comment='隔夜动量')
    open_gap = Column(Float, comment='开盘缺口')
    gap_ratio = Column(Float, comment='缺口比率')
    intraday_return = Column(Float, comment='日内收益')
    intraday_strength = Column(Float, comment='日内强度')
    high_low_ratio = Column(Float, comment='高低价比率')
    price_position = Column(Float, comment='价格位置')
    volume_relative_strength = Column(Float, comment='成交量相对强度')
    price_volume_divergence = Column(Float, comment='量价背离')
    price_volume_strength = Column(Float, comment='量价强度')
    volume_ratio = Column(Float, comment='成交量比率')
    amount_ratio = Column(Float, comment='成交额比率')
    
    # 技术指标因子
    ma5_slope = Column(Float, comment='5日均线斜率')
    ma10_slope = Column(Float, comment='10日均线斜率')
    ma_slope_diff = Column(Float, comment='均线斜率差')
    rsi6_position = Column(Float, comment='RSI6位置')
    macd_signal_diff = Column(Float, comment='MACD信号差')
    boll_position = Column(Float, comment='布林带位置')
    
    # 估值因子
    ep = Column(Float, comment='盈利收益率')
    bp = Column(Float, comment='账面市值比')
    sp = Column(Float, comment='销售收入市值比')
    value_score = Column(Float, comment='价值得分')
    pe_industry_rank = Column(Float, comment='PE行业排名')
    pb_industry_rank = Column(Float, comment='PB行业排名')
    
    # 成长因子
    revenue_growth = Column(Float, comment='营收增长')
    profit_growth = Column(Float, comment='利润增长')
    growth_score = Column(Float, comment='成长得分')
    
    # 质量因子
    roe = Column(Float, comment='净资产收益率')
    profit_margin = Column(Float, comment='利润率')
    leverage = Column(Float, comment='杠杆率')
    current_ratio_safe = Column(Float, comment='流动比率')
    quality_score = Column(Float, comment='质量得分')
    
    # 相对强弱因子
    industry_relative_strength = Column(Float, comment='行业相对强弱')
    amount_concentration = Column(Float, comment='成交额集中度')
    sector_relative = Column(Float, comment='板块相对收益')
    market_relative = Column(Float, comment='大盘相对收益')
    
    # 北向资金因子
    north_flow_impact = Column(Float, comment='北向资金影响')
    
    # 规模因子
    size_factor = Column(Float, comment='规模因子')
    small_cap_premium = Column(Float, comment='小盘股溢价')
    
    # 复合因子
    value_momentum = Column(Float, comment='价值动量复合')
    quality_value = Column(Float, comment='质量价值复合')
    growth_momentum = Column(Float, comment='成长动量复合')
    
    # 返回因子（用于中性化）
    return_1d = Column(Float, comment='1日收益')
    return_3d = Column(Float, comment='3日收益')
    return_5d = Column(Float, comment='5日收益')
    return_10d = Column(Float, comment='10日收益')
    return_20d = Column(Float, comment='20日收益')
    return_60d = Column(Float, comment='60日收益')
    return_120d = Column(Float, comment='120日收益')
    simple_return_1d = Column(Float, comment='简单1日收益')
    simple_return_5d = Column(Float, comment='简单5日收益')
    simple_return_20d = Column(Float, comment='简单20日收益')
    simple_return_60d = Column(Float, comment='简单60日收益')
    simple_return_120d = Column(Float, comment='简单120日收益')
    
    # ========== 新增因子字段 ==========
    # 趋势因子
    bias_20d = Column(Float, comment='20日乖离率')
    donchian_breakout = Column(Float, comment='唐奇安通道突破位置')
    macd_slope = Column(Float, comment='MACD斜率')
    hurst_exp = Column(Float, comment='Hurst指数(R/S分析法)')
    adam_symmetry = Column(Float, comment='亚当理论对称性')
    
    # 量价因子
    vmom_20d = Column(Float, comment='成交量加权动量')
    vp_coordination = Column(Float, comment='量价配合度')
    
    # 波动因子
    downside_vol_20d = Column(Float, comment='下行波动率')
    
    # 高低价回归因子（20日）
    vrrs_20d = Column(Float, comment='20日波动率调整RSRS')
    hsrs_beta = Column(Float, comment='极值空间结构Beta')
    hsrs_residual_vol = Column(Float, comment='HSRS残差波动率')
    channel_strength = Column(Float, comment='通道强度因子')
    hl_beta_20d = Column(Float, comment='20日高低价Beta')
    hl_correlation_20d = Column(Float, comment='20日高低价相关系数')
    range_extension = Column(Float, comment='区间延伸因子')
    asymmetry_beta = Column(Float, comment='上下不对称因子')
    
    # 多维回归因子
    ohlc_structure = Column(Float, comment='OHLC结构因子')
    trend_structure_coef = Column(Float, comment='趋势结构系数')
    
    # 中长期因子（60日）
    vrrs_60d = Column(Float, comment='60日VRRS')
    hl_beta_60d = Column(Float, comment='60日HL-Beta')
    channel_strength_60d = Column(Float, comment='60日通道强度')
    
    # 长期因子
    long_term_channel_beta = Column(Float, comment='长期通道Beta(120日)')
    
    # 基础数据
    close = Column(Float, comment='收盘价')
    log_circ_mv = Column(Float, comment='对数流通市值')
    industry = Column(String(50), comment='行业')
    
    # 修正后：default传函数对象（不加括号），onupdate同理
    updated_at = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now, comment='计算时间')
    
    __table_args__ = (
        UniqueConstraint('ts_code', 'trade_date', name='uq_stock_date'),
        {'comment': '个股因子数据表 - 宽表格式'}
    )
# ----------------------------------------------------------------
# 2. 系统运行类：状态机、分析报告、计划
# ----------------------------------------------------------------

class StockPool(Base):
    """股票池状态表：管理系统当前的生命周期状态"""
    __tablename__ = 'stock_pool'
    ts_code = Column(String(20), primary_key=True)
    pool_type = Column(String(20))   # SHORT, MID, LONG
    status = Column(String(20))      # WATCHING(观察), HOLDING(持仓), COMPLETED(结束)
    model_rank = Column(Integer, comment='模型排名（1-100）')  # 新增：模型排名
    added_date = Column(Date, default=datetime.date.today)
    update_time = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

class AnalysisReport(Base):
    """分析报告表：短期记忆载体 (建议保留 10 天)"""
    __tablename__ = 'analysis_report'
    id = Column(Integer, primary_key=True)
    
    # 【新增】区分是哪个 Agent 的报告
    agent_type = Column(String(50), index=True, comment='Agent类型: MARKET, STOCK, SECTOR...')
    
    ts_code = Column(String(20), index=True, comment='标的代码，大盘报告可填 000001.SH 或 ALL')
    trade_date = Column(Date, index=True, comment='报告日期')
    
    # 存储完整的分析内容 (JSON格式)，包含  confidence 字段
    report_json = Column(JSON, comment='结构化分析内容')
    
    # 验证字段，方便复盘
    is_validated = Column(Boolean, default=False, comment='是否已进行结果验证')
    created_at = Column(DateTime, default=datetime.datetime.now)


class TradingPlan(Base):
    """计划档案表：系统的运行核心"""
    __tablename__ = 'trading_plan'
    
    # 基础信息
    plan_id = Column(String(50), primary_key=True)
    ts_code = Column(String(20), index=True)
    strategy_type = Column(String(20))   # SHORT, MID, LONG
    parent_plan_id = Column(String(50))     # 父计划ID（中长期计划下的短期子计划）
    plan_purpose = Column(String(50))       # 计划目的：BUILD(建仓), REDUCE(减仓), 做t
    sub_plans = Column(JSON)                # 子计划列表（中长期计划专用）
    
    # 状态管理
    status = Column(String(20), index=True) # PROPOSED, APPROVED, ACTIVE, COMPLETED, TERMINATED
    created_at = Column(DateTime, default=datetime.datetime.now)
    expiry_date = Column(Date)
    
    # 核心参数
    entry_price = Column(Float)          # 计划买入价
    stop_loss_target_1 = Column(Float)   # 第一止损价
    take_profit_target_1 = Column(Float) # 第一止盈目标价
    stop_loss_target_2 = Column(Float)   # 第二止损价
    take_profit_target_2 = Column(Float) # 第二止盈目标价
    # 优先级与置信度
    priority_score = Column(Float)       # 计划优先级 (1-5档)
    confidence_score = Column(Float)     # 置信度分数 (0-100)
    
    # 关联信息
    related_reports = Column(JSON)       # 关联的分析报告ID列表 {"market": "..., "sector": "...", "stock": "..."}
    plan_summary = Column(JSON)          # 计划摘要
    
    # 执行记录
    proposals = Column(JSON)             # { "aggressive": {...}, "conservative": {...} }
    execution_log = Column(JSON)         # [ {"date": "...", "action": "buy", "price": 10.0}, ... ]
    
    # 终止信息
    close_reason = Column(String(50))    # STOP_LOSS, TAKE_PROFIT, EXPIRED, LOGIC_CHANGE
    terminate_reason = Column(Text)      # 终止原因详细说明
    terminated_at = Column(DateTime)     # 终止时间

# ----------------------------------------------------------------
# 3. 记忆类：向量库永久保存
# ----------------------------------------------------------------

class KnowledgeMemory(Base):
    """向量记忆表：永久保存，提供类比参考"""
    __tablename__ = 'knowledge_memory'
    id = Column(Integer, primary_key=True)
    
    # 【建议新增】记录是哪个 Agent 产生的经验
    agent_type = Column(String(50), index=True, comment='来源Agent: MARKET, STOCK, RISK...')
    
    ts_code = Column(String(20), index=True, comment='关联代码')
    trade_date = Column(Date, comment='经验产生日期')
    insight_text = Column(Text, comment='经验总结文本 (用于向量化)')
    embedding = Column(Vector(4096))   
    event_type = Column(String(20), comment='类型: MISTAKE(教训), PATTERN(模式), RULE(规则)')
    created_at = Column(DateTime, default=datetime.datetime.now)

# ----------------------------------------------------------------
# 4. 非结构化数据类：新闻公告等


class StockNews(Base):
    """股票新闻和公告表：存储东方财富股吧的股票相关新闻和公告"""
    __tablename__ = 'stock_news'
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    stock_code = Column(String(20), index=True, comment='股票代码')
    publish_time = Column(DateTime, index=True, comment='发布时间')
    title = Column(String(500), comment='标题')
    content = Column(Text, comment='完整内容')
    content_type = Column(String(20), default='news', comment='内容类型: news=新闻, notice=公告')
    crawl_time = Column(DateTime, default=datetime.datetime.now, comment='爬取时间')
    
    __table_args__ = (
        Index('idx_stock_publish_time', 'stock_code', 'publish_time'),
        Index('idx_content_type', 'content_type'),
        {'comment': '东方财富股吧股票新闻和公告数据表'}
    )


class MarketNews(Base):
    """大盘新闻表：存储东方财富财经新闻"""
    __tablename__ = 'market_news'
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键ID')
    news_type = Column(String(20), index=True, default='market_news', comment='新闻类型: market_news=大盘新闻')
    publish_time = Column(DateTime, index=True, comment='发布时间')
    title = Column(String(500), comment='标题')
    content = Column(Text, comment='内容详情')
    source = Column(String(50), default='eastmoney', comment='数据来源')
    created_at = Column(DateTime, default=datetime.datetime.now, comment='入库时间')
    
    __table_args__ = (
        Index('idx_market_news_time', 'publish_time'),
        {'comment': '大盘新闻数据表 - 东方财富财经新闻'}
    )

# database.py
_engine = None
_SessionLocal = None

from contextlib import contextmanager
from typing import Generator

def init_db(db_url: str):
    global _engine, _SessionLocal
    _engine = create_engine(db_url, pool_pre_ping=True, pool_recycle=3600)
    _SessionLocal = sessionmaker(bind=_engine)
    Base.metadata.create_all(_engine)

def get_session():
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized")
    return _SessionLocal()

@contextmanager
def get_session_context() -> Generator:
    """
    上下文管理器：自动管理数据库连接生命周期
    
    使用方式：
        with get_session_context() as session:
            stm = ShortTermMemory(session)
            # 自动提交/回滚/关闭
    
    特性：
    - 正常退出时自动提交
    - 异常时自动回滚
    - 退出时自动关闭连接
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

class SessionManager:
    """
    数据库会话管理器
    
    提供统一的会话管理，支持：
    1. 上下文管理器模式
    2. 单例模式获取全局会话
    3. 线程安全的会话池
    """
    _instance = None
    _session = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_session(self):
        if self._session is None:
            self._session = get_session()
        return self._session
    
    def close(self):
        if self._session is not None:
            self._session.close()
            self._session = None
    
    def __enter__(self):
        return self.get_session()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._session.rollback()
        else:
            self._session.commit()
        self.close()
        return False

def get_session_manager() -> SessionManager:
    return SessionManager()
