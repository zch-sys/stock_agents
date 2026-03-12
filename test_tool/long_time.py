"""
长期因子有效性测试脚本（单窗口·长期持有）
功能：
- 从数据库加载因子及行情数据
- 读取 long_term_factors.yaml 获取固定长期因子列表
- 用前350个交易日训练 RidgeCV 模型（标签：未来30天超额收益）
- 在训练期结束后第一个交易日（信号日）用模型预测，选得分最高的10只股票
- 下一交易日开盘买入，持有至数据最后一天收盘卖出
- 计算组合收益、同期沪深300收益及超额收益
- 输出累计收益、年化收益等统计
"""
import os
import tushare as ts
import pandas as pd
import numpy as np
import yaml
from pathlib import Path
import sys
import warnings
warnings.filterwarnings('ignore')

# -------------------- 项目路径 --------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# -------------------- 数据库导入 --------------------
try:
    from data.database import init_db, get_session, StockDetail, StockFactor
    from sqlalchemy import select
except ImportError as e:
    print(f"导入 database 模块失败: {e}")
    sys.exit(1)

# -------------------- 因子工程工具 --------------------
try:
    from factor_engineering import ConfigManager, QuantUtils
    CFG = ConfigManager()
except ImportError:
    print("因子工程模块未找到，使用默认配置")
    CFG = None
    QuantUtils = None

# -------------------- 机器学习 --------------------
from sklearn.linear_model import RidgeCV
from sklearn.impute import SimpleImputer
import matplotlib.pyplot as plt

# ==================== 数据加载类（完全复用） ====================
class StockDataLoader:
    """从数据库加载因子、行情及沪深300数据，合并并计算标签"""
    def __init__(self, hs300_token=None):
        self.hs300_token = hs300_token

    def load_factor_data_from_db(self, start_date=None, end_date=None):
        """从 stock_factor 表加载因子数据（宽表格式）"""
        print("从数据库加载因子数据 (stock_factor)...")
        try:
            if CFG is None:
                db_url = os.getenv('DB_URL', 'postgresql://postgres:z2c2h088QQ@localhost:5432/stock_analysis')
            else:
                db_url = CFG.DB_URL

            init_db(db_url)
            session = get_session()

            from sqlalchemy import inspect
            mapper = inspect(StockFactor)
            all_columns = [c.key for c in mapper.attrs]
            select_cols = [getattr(StockFactor, col) for col in all_columns
                           if col not in ['id', 'updated_at']]
            query = select(*select_cols)

            if start_date and end_date:
                query = query.where(
                    StockFactor.trade_date.between(
                        start_date.strftime('%Y%m%d'),
                        end_date.strftime('%Y%m%d')
                    )
                )

            chunks = []
            chunk_size = 50000
            for chunk in pd.read_sql(query, session.get_bind(), chunksize=chunk_size):
                if QuantUtils:
                    chunk = QuantUtils.optimize_dtypes(chunk)
                chunks.append(chunk)

            df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
            if 'trade_date' in df.columns and not df.empty:
                df['trade_date'] = pd.to_datetime(df['trade_date'])
            df = df.sort_values(['trade_date', 'ts_code']).reset_index(drop=True)
            session.close()
            print(f"因子数据加载成功: {df.shape[0]} 行, {df['trade_date'].nunique()} 交易日, {df['ts_code'].nunique()} 股票")
            return df
        except Exception as e:
            print(f"从数据库加载因子数据失败: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()

    def load_stock_price_data(self, start_date=None, end_date=None):
        """从 StockDetail 表加载行情数据"""
        print("从数据库加载行情数据 (StockDetail)...")
        try:
            if CFG is None:
                db_url = os.getenv('DB_URL', 'postgresql://postgres:z2c2h088QQ@localhost:5432/stock_analysis')
            else:
                db_url = CFG.DB_URL
            init_db(db_url)
            session = get_session()

            query = select(
                StockDetail.ts_code,
                StockDetail.trade_date,
                StockDetail.close,
                StockDetail.pct_chg,
                StockDetail.industry,
                StockDetail.name,
                StockDetail.open,
                StockDetail.high,
                StockDetail.low,
                StockDetail.vol,
                StockDetail.amount,
                StockDetail.pre_close
            )
            if start_date and end_date:
                query = query.where(
                    StockDetail.trade_date.between(
                        start_date.strftime('%Y%m%d'),
                        end_date.strftime('%Y%m%d')
                    )
                )

            chunks = []
            chunk_size = 50000
            for chunk in pd.read_sql(query, session.get_bind(), chunksize=chunk_size):
                if QuantUtils:
                    chunk = QuantUtils.optimize_dtypes(chunk)
                chunks.append(chunk)

            df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
            if 'trade_date' in df.columns and not df.empty:
                df['trade_date'] = pd.to_datetime(df['trade_date'])
            df = df.sort_values(['trade_date', 'ts_code']).reset_index(drop=True)
            session.close()
            print(f"行情数据加载成功: {df.shape[0]} 行, {df['trade_date'].nunique()} 交易日")
            return df
        except Exception as e:
            print(f"加载行情数据失败: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()

    def load_hs300_data(self, start_date, end_date):
        """获取沪深300日线数据（Tushare）"""
        print("获取沪深300数据...")
        try:
            if self.hs300_token:
                ts.set_token(self.hs300_token)
            pro = ts.pro_api()
            hs300 = pro.index_daily(
                ts_code='000300.SH',
                start_date=start_date.strftime('%Y%m%d'),
                end_date=end_date.strftime('%Y%m%d')
            )
            hs300['trade_date'] = pd.to_datetime(hs300['trade_date'])
            hs300 = hs300.sort_values('trade_date')
            hs300['hs300_return'] = hs300['close'].pct_change()
            hs300['hs300_cum_return'] = (1 + hs300['hs300_return']).cumprod() - 1
            print(f"沪深300数据加载成功: {hs300.shape[0]} 交易日")
            return hs300
        except Exception as e:
            print(f"获取沪深300数据失败: {e}")
            return pd.DataFrame(columns=['trade_date', 'close', 'hs300_return', 'hs300_cum_return'])

    def merge_factor_with_price(self, factor_df, price_df):
        """合并因子与行情数据"""
        if price_df.empty:
            return factor_df
        factor_df = factor_df.copy()
        price_df = price_df.copy()
        price_cols = ['ts_code', 'trade_date', 'close', 'pct_chg', 'open', 'vol', 'pre_close']
        merged = pd.merge(
            factor_df,
            price_df[price_cols],
            on=['ts_code', 'trade_date'],
            how='left',
            suffixes=('', '_price')
        )
        if 'close_price' in merged.columns:
            merged['close'] = merged['close_price'].fillna(merged['close'])
            merged.drop(columns=['close_price'], inplace=True)
        if 'pct_chg_price' in merged.columns:
            merged['pct_chg'] = merged['pct_chg_price'].fillna(merged['pct_chg'])
            merged.drop(columns=['pct_chg_price'], inplace=True)
        return merged

    def calculate_labels(self, factor_df, hs300_df, horizon=30):
        """计算未来 horizon 天超额收益标签（T+1开盘买入）"""
        print(f"计算未来{horizon}天超额收益标签...")
        df = factor_df.copy().sort_values(['ts_code', 'trade_date'])
        if 'close' not in df.columns or 'open' not in df.columns:
            raise ValueError("数据缺少 close 或 open 列，无法计算收益率")
        # 个股未来 horizon 天收益率（T+1开盘买入，T+horizon收盘卖出）
        df[f'future_{horizon}d_return'] = (
            df.groupby('ts_code')['close'].shift(-horizon) /
            df.groupby('ts_code')['open'].shift(-1) - 1
        )
        if len(hs300_df) > 0:
            hs300_df = hs300_df.sort_values('trade_date')
            hs300_df[f'future_{horizon}d_return'] = (
                hs300_df['close'].shift(-horizon) / hs300_df['close'].shift(-1) - 1
            )
            date_mapping = hs300_df.set_index('trade_date')[f'future_{horizon}d_return'].to_dict()
            df[f'hs300_future_{horizon}d_return'] = df['trade_date'].map(date_mapping)
            df['label'] = df[f'future_{horizon}d_return'] - df[f'hs300_future_{horizon}d_return']
            df.drop(columns=[f'future_{horizon}d_return', f'hs300_future_{horizon}d_return'], inplace=True)
        else:
            print("警告: 无沪深300数据，仅使用个股收益率")
            df['label'] = df[f'future_{horizon}d_return']
            df.drop(columns=[f'future_{horizon}d_return'], inplace=True)
        initial_len = len(df)
        df = df.dropna(subset=['label'])
        print(f"删除缺失标签数据: {initial_len - len(df)} 行")
        print(f"标签统计 - 均值: {df['label'].mean():.4f}, 标准差: {df['label'].std():.4f}")
        return df

# ==================== 回测类（修改以支持变长持仓）====================
class RollingWindowTester:
    """单次训练、单次选股、长期持有回测"""
    def __init__(self):
        self.model = RidgeCV(alphas=[0.1, 1.0, 10.0], cv=5)
        self.imputer = SimpleImputer(strategy='median')
        self.results = []

    def run_single_window(self, data, feature_cols, window_config, hs300_data, top_n=10):
        """
        执行单个窗口的训练、预测、选股、回测
        参数:
            window_config: 包含 train_start, train_end, test_date, test_start, test_end
        返回:
            result dict，新增 'holding_days' 字段
        """
        horizon = 30  # 与标签周期一致，但持仓期可以更长

        # 1. 训练数据（剔除最后 horizon 天以避免未来信息）
        train_mask_raw = (data['trade_date'] >= window_config['train_start']) & \
                         (data['trade_date'] <= window_config['train_end'])
        train_data_raw = data[train_mask_raw].copy()
        unique_train_dates = sorted(train_data_raw['trade_date'].unique())
        if len(unique_train_dates) > horizon:
            cutoff_date = unique_train_dates[-horizon]
            train_data = train_data_raw[train_data_raw['trade_date'] < cutoff_date].copy()
        else:
            raise ValueError(f"训练数据不足以剔除 {horizon} 天盲期")

        # 2. 测试数据（信号日）
        test_data = data[data['trade_date'] == window_config['test_date']].copy()
        if len(test_data) == 0:
            raise ValueError(f"测试日期 {window_config['test_date']} 无数据")

        # 3. 特征处理
        X_train_raw = train_data[feature_cols].values
        y_train = train_data['label'].values
        X_test_raw = test_data[feature_cols].values

        X_train = self.imputer.fit_transform(X_train_raw)
        X_test = self.imputer.transform(X_test_raw)
        test_stocks = test_data['ts_code'].values

        # 4. 训练并预测
        try:
            self.model.fit(X_train, y_train)
            pred = self.model.predict(X_test)
        except Exception as e:
            print(f"  模型训练失败: {e}")
            pred = np.zeros(len(X_test))

        # 5. 选股（剔除 T+1 无法买入的股票）
        next_day_data = data[data['trade_date'] == window_config['test_start']]
        pred_df = pd.DataFrame({'ts_code': test_stocks, 'pred_score': pred})
        pred_df = pred_df.sort_values('pred_score', ascending=False)

        selected_stocks = []
        selected_scores = []
        stock_details = []
        for _, row in pred_df.iterrows():
            if len(selected_stocks) >= top_n:
                break
            code = row['ts_code']
            m_info = next_day_data[next_day_data['ts_code'] == code]
            if m_info.empty:
                continue
            # 停牌检查
            is_suspended = (m_info['vol'].iloc[0] <= 0) or pd.isna(m_info['open'].iloc[0])
            # 涨停检查（近似）
            pre_close = m_info['pre_close'].iloc[0]
            open_price = m_info['open'].iloc[0]
            is_limit_up = (open_price >= round(pre_close * 1.098, 2)) if pre_close > 0 else False
            if is_suspended or is_limit_up:
                continue
            selected_stocks.append(code)
            selected_scores.append(row['pred_score'])
            stock_details.append({'ts_code': code, 'pred_score': row['pred_score']})

        # 6. 计算测试期收益（持仓期长度不固定）
        test_period_mask = (data['trade_date'] >= window_config['test_start']) & \
                           (data['trade_date'] <= window_config['test_end'])
        test_period_data = data[test_period_mask].copy()
        portfolio_data = test_period_data[test_period_data['ts_code'].isin(selected_stocks)]

        if len(portfolio_data) == 0:
            portfolio_return = 0.0
            holding_days = 0
        else:
            unique_dates = sorted(portfolio_data['trade_date'].unique())
            holding_days = len(unique_dates)
            daily_returns = []
            for i, date in enumerate(unique_dates):
                day_data = portfolio_data[portfolio_data['trade_date'] == date]
                if i == 0:
                    # 开盘买入，计算当日收益
                    day_return = ((day_data['close'] - day_data['open']) / day_data['open']).mean()
                else:
                    day_return = day_data['pct_chg'].mean() / 100
                # 交易成本：买入0.15%，卖出0.15%
                if i == 0:
                    day_return -= 0.0015
                if i == len(unique_dates) - 1:
                    day_return -= 0.0015
                daily_returns.append(day_return)
            portfolio_return = np.prod([1 + r for r in daily_returns]) - 1

        # 7. 沪深300同期收益
        if len(hs300_data) > 0:
            hs300_test = hs300_data[
                (hs300_data['trade_date'] >= window_config['test_start']) &
                (hs300_data['trade_date'] <= window_config['test_end'])
            ]
            if len(hs300_test) > 0:
                hs300_return = hs300_test['close'].iloc[-1] / hs300_test['close'].iloc[0] - 1
            else:
                hs300_return = 0.0
        else:
            hs300_return = 0.0

        excess_return = portfolio_return - hs300_return

        result = {
            'window_id': None,
            'train_period': f"{window_config['train_start'].date()} 到 {window_config['train_end'].date()}",
            'test_period': f"{window_config['test_start'].date()} 到 {window_config['test_end'].date()}",
            'selected_stocks': selected_stocks,
            'portfolio_return': portfolio_return,
            'hs300_return': hs300_return,
            'excess_return': excess_return,
            'stock_details': stock_details,
            'feature_cols': feature_cols,
            'holding_days': holding_days   # 新增：实际持仓交易日天数
        }
        return result

    def analyze_results(self):
        """分析回测结果（适配变长持仓）"""
        if not self.results:
            print("没有测试结果")
            return None

        print("\n" + "=" * 60)
        print("测试结果分析")
        print("=" * 60)

        portfolio_returns = [r['portfolio_return'] for r in self.results]
        hs300_returns = [r['hs300_return'] for r in self.results]
        excess_returns = [r['excess_return'] for r in self.results]
        holding_days_list = [r['holding_days'] for r in self.results]

        total_portfolio_return = np.prod([1 + r for r in portfolio_returns]) - 1
        total_hs300_return = np.prod([1 + r for r in hs300_returns]) - 1
        total_excess_return = np.prod([1 + r for r in excess_returns]) - 1

        total_days = sum(holding_days_list)
        if total_days > 0:
            annualized_portfolio = (1 + total_portfolio_return) ** (252 / total_days) - 1
            annualized_hs300 = (1 + total_hs300_return) ** (252 / total_days) - 1
            annualized_excess = (1 + total_excess_return) ** (252 / total_days) - 1
        else:
            annualized_portfolio = annualized_hs300 = annualized_excess = 0.0

        win_rate = sum(1 for r in excess_returns if r > 0) / len(excess_returns) if excess_returns else 0.0

        print(f"测试窗口数: {len(self.results)}")
        print(f"总持仓交易日数: {total_days}")
        print(f"\n累计收益:")
        print(f"  组合累计收益: {total_portfolio_return:.2%}")
        print(f"  沪深300累计收益: {total_hs300_return:.2%}")
        print(f"  累计超额收益: {total_excess_return:.2%}")
        print(f"\n年化收益:")
        print(f"  组合年化收益: {annualized_portfolio:.2%}")
        print(f"  沪深300年化收益: {annualized_hs300:.2%}")
        print(f"  年化超额收益: {annualized_excess:.2%}")
        if len(excess_returns) > 0:
            print(f"\n胜率: {win_rate:.2%}")
            print(f"平均窗口超额收益: {np.mean(excess_returns):.2%}")
            print(f"超额收益标准差: {np.std(excess_returns):.2%}")

        # 绘图（仅当有多个窗口时才有意义，这里保留但可能只显示一个柱子）
        self.plot_results(portfolio_returns, hs300_returns, excess_returns)

        return {
            'total_portfolio_return': total_portfolio_return,
            'total_hs300_return': total_hs300_return,
            'total_excess_return': total_excess_return,
            'annualized_portfolio': annualized_portfolio,
            'annualized_hs300': annualized_hs300,
            'annualized_excess': annualized_excess,
            'win_rate': win_rate,
            'mean_excess': np.mean(excess_returns) if excess_returns else 0.0,
            'std_excess': np.std(excess_returns) if excess_returns else 0.0,
            'n_windows': len(self.results),
            'total_holding_days': total_days
        }

    def plot_results(self, portfolio_returns, hs300_returns, excess_returns):
        """绘制收益对比图"""
        fig, axes = plt.subplots(2, 1, figsize=(12, 8))
        x = range(1, len(portfolio_returns) + 1)
        axes[0].bar(x, portfolio_returns, alpha=0.7, label='组合收益')
        axes[0].bar(x, hs300_returns, alpha=0.7, label='沪深300收益')
        axes[0].set_xlabel('窗口')
        axes[0].set_ylabel('收益率')
        axes[0].set_title('各窗口收益率对比')
        axes[0].legend()
        axes[0].grid(True, alpha=0.3)
        axes[1].bar(x, excess_returns, color=['green' if r > 0 else 'red' for r in excess_returns])
        axes[1].axhline(y=0, color='black', linestyle='-', alpha=0.3)
        axes[1].set_xlabel('窗口')
        axes[1].set_ylabel('超额收益率')
        axes[1].set_title('各窗口超额收益率')
        axes[1].grid(True, alpha=0.3)
        plt.tight_layout()
        plt.show()

# ==================== 长期因子专用测试函数（单窗口）====================
def test_long_term_single_window(yaml_path, hs300_token, train_window_len=300,
                                 horizon=120, top_n=20):
    """
    单窗口长期因子回测
    训练：前 train_window_len 个交易日
    测试：从训练结束下一个交易日开始，至数据最后一天结束
    """
    # ---------- 1. 加载数据 ----------
    loader = StockDataLoader(hs300_token)
    print("=" * 60)
    print("开始加载数据...")
    factor_df = loader.load_factor_data_from_db()
    if factor_df.empty:
        print("因子数据为空，程序终止")
        return None, None
    price_df = loader.load_stock_price_data()
    if price_df.empty:
        print("行情数据为空，程序终止")
        return None, None
    full_data = loader.merge_factor_with_price(factor_df, price_df)
    if full_data.empty:
        print("合并后数据为空，程序终止")
        return None, None

    # 全局交易日列表
    all_dates = sorted(full_data['trade_date'].unique())
    if len(all_dates) <= train_window_len + 1:  # 至少需要训练窗口+1个交易日（信号日）
        print(f"数据总交易日不足（{len(all_dates)}），无法完成回测")
        return None, None

    start_date = all_dates[0]
    end_date = all_dates[-1]
    hs300_data = loader.load_hs300_data(start_date, end_date)

    # ---------- 2. 计算标签（未来 horizon 天超额收益）----------
    print("\n计算超额收益标签...")
    try:
        data_with_label = loader.calculate_labels(full_data, hs300_data, horizon=horizon)
    except Exception as e:
        print(f"计算标签失败: {e}")
        import traceback
        traceback.print_exc()
        return None, None

    # ---------- 3. 读取长期因子列表 ----------
    print("\n读取长期因子配置...")
    with open(yaml_path, 'r', encoding='utf-8') as f:
        yaml_data = yaml.safe_load(f)
    long_term_factors = yaml_data.get('long_term', [])
    if not long_term_factors:
        print("错误: YAML 中未找到 long_term 节点或因子列表为空")
        return None, None

    factor_names = [item['factor_name'] for item in long_term_factors]
    print(f"共加载 {len(factor_names)} 个长期因子: {factor_names}")

    feature_cols = [col for col in factor_names if col in data_with_label.columns]
    missing = set(factor_names) - set(feature_cols)
    if missing:
        print(f"警告: 以下因子在数据中不存在: {missing}")
    if not feature_cols:
        print("错误: 所有因子均不在数据中，无法回测")
        return None, None

    if 'log_circ_mv' in data_with_label.columns:
        feature_cols.append('log_circ_mv')
        print("已添加市值因子 'log_circ_mv'")
    print(f"最终使用的特征数量: {len(feature_cols)}")

    # ---------- 4. 构建唯一窗口 ----------
    date_to_idx = {d: i for i, d in enumerate(all_dates)}
    total_dates = len(all_dates)

    # 训练窗口：索引 0 ~ train_window_len-1
    train_start_idx = 0
    train_end_idx = train_window_len - 1
    # 信号日：训练窗口结束的下一个交易日
    signal_idx = train_window_len
    # 测试期（持仓期）：信号日的下一个交易日开始，到最后一天
    hold_start_idx = signal_idx + 1
    hold_end_idx = total_dates - 1

    if hold_start_idx > hold_end_idx:
        print("错误: 无足够交易日作为持仓期")
        return None, None

    window_config = {
        'train_start': all_dates[train_start_idx],
        'train_end': all_dates[train_end_idx],
        'test_date': all_dates[signal_idx],
        'test_start': all_dates[hold_start_idx],
        'test_end': all_dates[hold_end_idx]
    }

    print("\n" + "=" * 60)
    print("构建唯一测试窗口")
    print(f"  训练期: {window_config['train_start'].date()} 至 {window_config['train_end'].date()} (共{train_window_len}个交易日)")
    print(f"  信号日: {window_config['test_date'].date()}")
    print(f"  持仓期: {window_config['test_start'].date()} 至 {window_config['test_end'].date()} (共{hold_end_idx-hold_start_idx+1}个交易日)")

    # ---------- 5. 执行回测 ----------
    tester = RollingWindowTester()
    try:
        result = tester.run_single_window(
            data=data_with_label,
            feature_cols=feature_cols,
            window_config=window_config,
            hs300_data=hs300_data,
            top_n=top_n
        )
        result['window_id'] = 1
        tester.results = [result]

        print(f"\n回测结果:")
        print(f"  组合收益: {result['portfolio_return']:.2%}")
        print(f"  沪深300收益: {result['hs300_return']:.2%}")
        print(f"  超额收益: {result['excess_return']:.2%}")
        print(f"  持仓天数: {result['holding_days']} 交易日")
        print(f"  选股数量: {len(result['selected_stocks'])}")
        print(f"  选股列表: {result['selected_stocks']}")

    except Exception as e:
        print(f"  回测执行失败: {e}")
        import traceback
        traceback.print_exc()
        return None, None

    # ---------- 6. 分析结果 ----------
    final_stats = tester.analyze_results()
    return tester.results, final_stats

# ==================== 主入口 ====================
if __name__ == "__main__":
    LONG_TERM_YAML = r"E:\tradingagents\core\stock_selection\long_term_factors.yaml"
    HS300_TOKEN = "41bc8be1587c976380a7776cb3d0e74a563aecfbfa1bef98670eb601"  # 请替换

    # 执行单窗口长期回测
    results, stats = test_long_term_single_window(
        yaml_path=LONG_TERM_YAML,
        hs300_token=HS300_TOKEN,
        train_window_len=300,   # 训练窗口3500个交易日
        horizon=120,             # 标签周期（未来120天超额收益）
        top_n=10               # 选10只股票
    )

    if stats:
        print("\n" + "=" * 60)
        print("长期因子回测最终统计摘要")
        print("=" * 60)
        for k, v in stats.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.2%}")
            else:
                print(f"  {k}: {v}")