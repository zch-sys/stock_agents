import os
import logging
import sqlite3
import hashlib
from datetime import datetime, date
import pandas as pd
from sqlalchemy import create_engine, Column, String, Float, Integer, Date, JSON, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# ====================== 基础配置 ======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('sector_test.log', encoding='utf-8')
    ]
)
logger = logging.getLogger('SectorTest')

# 你的本地数据库路径
DB_PATH = r'F:\tradingagents\test_tool\sector_calc_test.db'
TEST_TRADE_DATE = '20260129'

# ====================== 新增：原生SQLite排查（绕开ORM） ======================
def check_database_raw():
    """用原生SQLite连接数据库，排查核心问题（绕开ORM）"""
    logger.info("="*50 + " 原生SQLite数据库排查 " + "="*50)
    
    # 1. 验证文件路径和基本信息
    logger.info(f"1. 数据库文件信息：")
    if not os.path.exists(DB_PATH):
        logger.error(f"   ❌ 文件不存在：{DB_PATH}")
        return False
    else:
        file_size = os.path.getsize(DB_PATH) / 1024 / 1024  # 转MB
        logger.info(f"   ✅ 文件存在：{DB_PATH}")
        logger.info(f"   ✅ 文件大小：{file_size:.2f} MB")
    
    # 2. 用原生sqlite3连接，查询所有表名
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 查询数据库中所有表名
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        table_names = [t[0] for t in tables]
        
        logger.info(f"\n2. 数据库中所有表名：")
        if not table_names:
            logger.error(f"   ❌ 数据库中无任何表！")
        else:
            logger.info(f"   表列表：{table_names}")
            # 检查是否有StockDetail相关表（不区分大小写）
            stock_detail_exists = any('stockdetail' in t.lower() for t in table_names)
            if stock_detail_exists:
                # 找到实际的表名（可能大小写不同）
                actual_table_name = [t for t in table_names if 'stockdetail' in t.lower()][0]
                logger.info(f"   ✅ 找到StockDetail相关表，实际表名：{actual_table_name}")
                
                # 3. 查询该表的前5条数据（原生SQL）
                logger.info(f"\n3. {actual_table_name} 表前5条数据（原生SQL查询）：")
                cursor.execute(f"SELECT * FROM {actual_table_name} LIMIT 5;")
                rows = cursor.fetchall()
                # 获取列名
                cursor.execute(f"PRAGMA table_info({actual_table_name});")
                columns = [col[1] for col in cursor.fetchall()]
                logger.info(f"   表列名：{columns}")
                
                if rows:
                    for i, row in enumerate(rows):
                        logger.info(f"   第{i+1}条：{dict(zip(columns, row))}")
                else:
                    logger.warning(f"   ⚠️ {actual_table_name} 表为空！")
                
                # 4. 查询该表的交易日字段（如果有）
                if 'trade_date' in [c.lower() for c in columns]:
                    logger.info(f"\n4. 查询该表的交易日数据：")
                    cursor.execute(f"SELECT DISTINCT trade_date FROM {actual_table_name} LIMIT 10;")
                    dates = cursor.fetchall()
                    if dates:
                        logger.info(f"   表中前10个交易日：{[d[0] for d in dates]}")
                    else:
                        logger.warning(f"   ⚠️ 表中无trade_date数据！")
            else:
                logger.error(f"   ❌ 数据库中无StockDetail表（或表名不是StockDetail）！")
        
        conn.commit()
    except Exception as e:
        logger.error(f"   ❌ 原生SQL查询失败：{e}")
        return False
    finally:
        if conn:
            conn.close()
    
    logger.info("="*108 + "\n")
    return True

# ====================== 原有ORM相关代码（不变） ======================
Base = declarative_base()

class StockDetail(Base):
    __tablename__ = 'stock_detail'
    
    ts_code = Column(String(20), primary_key=True)
    name = Column(String(50))
    industry = Column(String(50))
    trade_date = Column(Date, primary_key=True)
    open = Column(Float)
    close = Column(Float)
    high = Column(Float)
    low = Column(Float)
    pct_chg = Column(Float)
    vol = Column(Float)
    amount = Column(Float)
    total_mv = Column(Float)
    circ_mv = Column(Float)
    pre_close = Column(Float)

class SectorData(Base):
    __tablename__ = 'SectorData'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    sector_code = Column(String(20))
    sector_name = Column(String(50))
    trade_date = Column(Date)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    pre_close = Column(Float)
    pct_chg = Column(Float)
    vol = Column(Float)
    amount = Column(Float)
    total_market_cap = Column(Float)
    circ_market_cap = Column(Float)
    rank = Column(Integer)
    stock_count = Column(Integer)
    rise_count = Column(Integer)
    fall_count = Column(Integer)
    unchanged_count = Column(Integer)
    rise_fall_ratio = Column(Float)
    fund_inflow = Column(Float)
    fund_inflow_rate = Column(Float)
    rise_amount = Column(Float)
    fall_amount = Column(Float)
    avg_pct_chg = Column(Float)
    max_pct_chg = Column(Float)
    min_pct_chg = Column(Float)
    median_pct_chg = Column(Float)
    std_pct_chg = Column(Float)
    constituent_stocks = Column(JSON)
import hashlib
import pandas as pd
from datetime import datetime
from sqlalchemy import func

class SectorDataCollector:
    def __init__(self, db_path):
        # 保持原样
        self.engine = create_engine(f'sqlite:///{db_path}', echo=False)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()
        Base.metadata.create_all(self.engine)
    
    def get_trade_date(self, trade_date: str = None) -> str:
        # 保持原样
        if trade_date:
            return trade_date
        latest_date = self.session.query(func.max(StockDetail.trade_date)).scalar()
        if latest_date:
            return latest_date.strftime('%Y%m%d')
        return TEST_TRADE_DATE
    
    def _clean_old_sector_data_v2(self, days: int = 20):
        # 保持原样
        logger.info(f"【测试模式】清理{days}天前旧数据，不实际删除")
        return True
    
    def collect_sector_data_v2(self, trade_date: str = None) -> bool:
        try:
            trade_date = self.get_trade_date(trade_date)
            trade_date_obj = datetime.strptime(trade_date, '%Y%m%d').date()
            logger.info(f"开始测试收集板块数据，交易日: {trade_date}")

            stock_details = self.session.query(
                StockDetail.ts_code, StockDetail.name, StockDetail.industry,
                StockDetail.open, StockDetail.close, StockDetail.high, StockDetail.low,
                StockDetail.pct_chg, StockDetail.vol, StockDetail.amount,
                StockDetail.total_mv, StockDetail.circ_mv, StockDetail.pre_close
            ).filter(
                StockDetail.trade_date == trade_date_obj,
                StockDetail.industry.isnot(None),
                StockDetail.industry != '',
                StockDetail.close > 0,
                StockDetail.pre_close > 0,
                StockDetail.circ_mv > 0
            ).all()
            
            if not stock_details:
                logger.error(f"数据库中无 {trade_date} 有效个股数据")
                return False
            
            df_stocks = pd.DataFrame([
                {
                    'ts_code': s.ts_code, 'name': s.name, 'industry': s.industry,
                    'open': s.open, 'close': s.close, 'high': s.high, 'low': s.low,
                    'pct_chg': s.pct_chg, 'vol': s.vol, 'amount': s.amount,
                    'total_mv': s.total_mv, 'circ_mv': s.circ_mv, 'pre_close': s.pre_close
                } for s in stock_details
            ])
            
            # 基础过滤逻辑
            df_stocks = df_stocks[df_stocks['pct_chg'].notna() & df_stocks['vol'].notna() & df_stocks['amount'].notna()]
            if len(df_stocks) < 10:
                logger.error(f"有效股票不足，仅{len(df_stocks)}只")
                return False
            
            logger.info("按行业分组聚合计算...")
            industry_groups = df_stocks.groupby('industry')
            sector_data_list = []
            
            for industry_name, industry_df in industry_groups:
                try:
                    if len(industry_df) < 2: continue
                    
                    # -------------------------------------------------------
                    # 1. 数据清洗：保留有效交易股
                    # -------------------------------------------------------
                    industry_df = industry_df[
                        (industry_df['open'] > 0) & (industry_df['close'] > 0) & (industry_df['circ_mv'] > 0)
                    ].copy() # 使用copy避免赋值警告
                    
                    if len(industry_df) < 2: continue
                    
                    # -------------------------------------------------------
                    # 2. 核心逻辑修改：计算板块涨跌幅 (采用总市值预算法)
                    # -------------------------------------------------------
                    total_circ_mv = industry_df['circ_mv'].sum()
                    total_total_mv = industry_df['total_mv'].sum()
                    
                    # 反推昨日板块总流通市值 (昨日市值 = 今日市值 / (1+涨幅))
                    # 这样计算出的 pct_chg_weighted 能够完美匹配券商的 1.29%
                    industry_df['pre_circ_mv'] = industry_df['circ_mv'] / (1 + industry_df['pct_chg'] / 100)
                    total_pre_circ_mv = industry_df['pre_circ_mv'].sum()
                    
                    if total_pre_circ_mv > 0:
                        pct_chg_weighted = (total_circ_mv - total_pre_circ_mv) / total_pre_circ_mv * 100
                    else:
                        pct_chg_weighted = 0

                    # -------------------------------------------------------
                    # 3. K线数据计算：使用市值权重
                    # -------------------------------------------------------
                    weights = industry_df['circ_mv'] / total_circ_mv
                    weighted_open = (industry_df['open'] * weights).sum()
                    weighted_close = (industry_df['close'] * weights).sum()
                    weighted_high = (industry_df['high'] * weights).sum()
                    weighted_low = (industry_df['low'] * weights).sum()
                    
                    # 为了保证 K线数据在 UI 上自洽 (即 (close-pre_close)/pre_close = pct_chg)
                    # 我们通过涨幅反推加权昨收价
                    weighted_pre_close = weighted_close / (1 + pct_chg_weighted / 100)
                    
                    # -------------------------------------------------------
                    # 4. 统计指标 (保持原功能)
                    # -------------------------------------------------------
                    avg_pct_chg     = industry_df['pct_chg'].mean()
                    max_pct_chg     = industry_df['pct_chg'].max()
                    min_pct_chg     = industry_df['pct_chg'].min()
                    median_pct_chg  = industry_df['pct_chg'].median()
                    std_pct_chg     = industry_df['pct_chg'].std()
                    
                    # -------------------------------------------------------
                    # 5. 资金流与涨跌家数 (保持原功能)
                    # -------------------------------------------------------
                    rise_mask = industry_df['pct_chg'] > 0
                    fall_mask = industry_df['pct_chg'] < 0
                    unchanged_mask = industry_df['pct_chg'] == 0
                    
                    rise_count = int(rise_mask.sum())
                    fall_count = int(fall_mask.sum())
                    unchanged_count = int(unchanged_mask.sum())
                    rise_fall_ratio = rise_count / fall_count if fall_count > 0 else (float('inf') if rise_count > 0 else 1.0)
                    
                    rise_amount = industry_df.loc[rise_mask, 'amount'].sum()
                    fall_amount = industry_df.loc[fall_mask, 'amount'].sum()
                    total_amount = industry_df['amount'].sum()
                    total_vol = industry_df['vol'].sum()
                    fund_inflow = rise_amount - fall_amount
                    fund_inflow_rate = (fund_inflow / total_amount * 100) if total_amount > 0 else 0
                    
                    # -------------------------------------------------------
                    # 6. 构造 SectorData 对象 (保持原字段)
                    # -------------------------------------------------------
                    industry_clean = industry_name.strip().replace(' ', '').replace('　', '')
                    sector_code = f"IND_{hashlib.md5(industry_clean.encode('utf-8')).hexdigest()[:8].upper()}"
                    
                    constituent_stocks = industry_df[
                        ['ts_code','name','pct_chg','total_mv','circ_mv']
                    ].to_dict('records')
                    
                    sector_data = SectorData(
                        sector_code        = sector_code,
                        sector_name        = industry_name,
                        trade_date         = trade_date_obj,
                        open               = weighted_open,
                        high               = weighted_high,
                        low                = weighted_low,
                        close              = weighted_close,
                        pre_close          = weighted_pre_close,
                        pct_chg            = pct_chg_weighted, # 修正后的涨幅
                        vol                = total_vol,
                        amount             = total_amount,
                        total_market_cap   = total_total_mv,
                        circ_market_cap    = total_circ_mv,
                        rank               = 0,
                        stock_count        = len(industry_df),
                        rise_count         = rise_count,
                        fall_count         = fall_count,
                        unchanged_count    = unchanged_count,
                        rise_fall_ratio    = rise_fall_ratio,
                        fund_inflow        = fund_inflow,
                        fund_inflow_rate   = fund_inflow_rate,
                        rise_amount        = rise_amount,
                        fall_amount        = fall_amount,
                        avg_pct_chg        = avg_pct_chg,
                        max_pct_chg        = max_pct_chg,
                        min_pct_chg        = min_pct_chg,
                        median_pct_chg     = median_pct_chg,
                        std_pct_chg        = std_pct_chg,
                        constituent_stocks = constituent_stocks
                    )
                    
                    sector_data_list.append(sector_data)
                    logger.debug(f"{industry_name} | 股票数:{len(industry_df)} | 加权涨幅:{pct_chg_weighted:.2f}%")
                    
                except Exception as e:
                    logger.warning(f"行业{industry_name}处理失败: {e}", exc_info=True)
                    continue
            
            # 后续排序、清理、入库逻辑 (保持原样)
            if not sector_data_list:
                return False
            
            sorted_sectors = sorted(sector_data_list, key=lambda x: x.pct_chg, reverse=True)
            for rank, sec in enumerate(sorted_sectors, 1):
                sec.rank = rank
            
            for sec in sector_data_list:
                self.session.add(sec)
            
            self._clean_old_sector_data_v2(20)
            
            # 日志打印部分
            logger.info("="*50 + f" {trade_date} 板块聚类测试结果 " + "="*50)
            for i, sec in enumerate(sorted_sectors[:15]):
                logger.info(f"Rank{i+1:2d} | {sec.sector_name:<12} | 成分股:{sec.stock_count:3d} | 加权涨幅:{sec.pct_chg:6.2f}%")
            
            logger.info("="*110)
            return True
            
        except Exception as e:
            logger.error("板块收集失败", exc_info=True)
            self.session.rollback()
            return False
# ====================== 主运行（先原生排查，再ORM测试） ======================
def run_test():
    # 第一步：先执行原生SQLite排查（关键！）
    check_database_raw()
    
    # 第二步：如果文件存在，再执行ORM测试
    if os.path.exists(DB_PATH):
        collector = SectorDataCollector(DB_PATH)
        success = collector.collect_sector_data_v2(trade_date=TEST_TRADE_DATE)
        collector.session.close()
        
        if success:
            logger.info("✅ 2026-01-29 板块聚类测试：全部逻辑正常运行")
        else:
            logger.info("❌ 测试失败")
    else:
        logger.error("数据库文件不存在，跳过ORM测试")

if __name__ == '__main__':
    run_test()