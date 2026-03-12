import pandas as pd
import numpy as np
import tushare as ts
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')
import os
from pathlib import Path
import yaml

# 模型
from sklearn.linear_model import RidgeCV
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor

# 评估
import matplotlib.pyplot as plt

# ===================== 正确的导入路径 =====================
import sys
PROJECT_ROOT = Path(__file__).parent.parent.parent  # 假设本文件在 core/stock_selection/ 下
sys.path.insert(0, str(PROJECT_ROOT))

# 1. 导入数据库相关（来自 data.database）
try:
    from data.database import (
        init_db, get_session, StockDetail, StockFactor
    )
    from sqlalchemy import select
except ImportError as e:
    print(f"导入 database 模块失败: {e}")
    print("请确保 data/database.py 存在且包含 StockFactor 表定义")
    sys.exit(1)

# 2. 导入因子工程工具类（来自 core.stock_selection.factor_engineering）
try:
    from core.stock_selection.factor_engineering import (
        ConfigManager, QuantUtils
    )
    CFG = ConfigManager()
except ImportError as e:
    print(f"导入 factor_engineering 模块失败: {e}")
    print("请确保 core/stock_selection/factor_engineering.py 存在且包含 ConfigManager, QuantUtils")
    CFG = None

# ------------------------------------------------------------
# 因子有效时期管理器（解析 YAML，按 eval_date 划分区间）
# ------------------------------------------------------------
class FactorPeriodManager:
    """管理因子有效时期：根据 YAML 定义，获取任意日期应使用的因子列表"""
    def __init__(self, yaml_path: str, last_period_extra_days: int = 45):
        self.periods = []
        self.eval_dates = []
        self.last_extra_days = last_period_extra_days
        self._parse_yaml(yaml_path)
        self._build_periods()

    def _parse_yaml(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        records = []
        for period in data.get('short_term', []):
            eval_date = pd.to_datetime(period['eval_date'])
            factors = [item['factor_name'] for item in period.get('factors', [])]
            records.append({'eval_date': eval_date, 'factors': factors})
        self.raw_records = sorted(records, key=lambda x: x['eval_date'])
        self.eval_dates = [r['eval_date'] for r in self.raw_records]

    def _build_periods(self):
        if not self.raw_records:
            return
        for i, rec in enumerate(self.raw_records):
            start = rec['eval_date']
            if i < len(self.raw_records) - 1:
                end = self.raw_records[i + 1]['eval_date']
            else:
                end = start + pd.Timedelta(days=self.last_extra_days)
            self.periods.append({
                'start': start,
                'end': end,
                'factors': rec['factors']
            })

    def get_factors_for_date(self, date):
        if not self.periods:
            return []
        for p in self.periods:
            if p['start'] <= date < p['end']:
                return p['factors']
        return self.periods[-1]['factors'] if self.periods else []

# ------------------------------------------------------------
# 股票数据加载器（因子从 StockFactor 表读取）
# ------------------------------------------------------------
class StockDataLoader:
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

            # 动态获取所有列，排除 id, updated_at
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

            # 分块读取
            chunks = []
            chunk_size = 50000
            for chunk in pd.read_sql(query, session.get_bind(), chunksize=chunk_size):
                chunk = QuantUtils.optimize_dtypes(chunk) if QuantUtils else chunk
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
        """从 StockDetail 表加载行情数据（用于涨停/停牌检查及收益计算）"""
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
                chunk = QuantUtils.optimize_dtypes(chunk) if QuantUtils else chunk
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
        """合并因子与行情数据，以因子表为准，添加行情字段"""
        print("合并因子数据与行情数据...")
        if price_df.empty:
            print("警告: 行情数据为空，跳过合并")
            return factor_df
        factor_df = factor_df.copy()
        price_df = price_df.copy()
        # 仅保留必要的行情字段
        price_cols = ['ts_code', 'trade_date', 'close', 'pct_chg', 'open', 'vol', 'pre_close']
        merged = pd.merge(
            factor_df,
            price_df[price_cols],
            on=['ts_code', 'trade_date'],
            how='left',
            suffixes=('', '_price')
        )
        # 使用行情表的 close, pct_chg 覆盖因子表中的同名列（因子表中可能也包含这些列，但应以实时行情为准）
        if 'close_price' in merged.columns:
            merged['close'] = merged['close_price'].fillna(merged['close'])
            merged.drop(columns=['close_price'], inplace=True)
        if 'pct_chg_price' in merged.columns:
            merged['pct_chg'] = merged['pct_chg_price'].fillna(merged['pct_chg'])
            merged.drop(columns=['pct_chg_price'], inplace=True)
        # open, vol, pre_close 直接来自行情表，无后缀冲突
        return merged

    def calculate_labels(self, factor_df, hs300_df, horizon=5):
        """计算未来 horizon 天超额收益标签（使用 T+1 开盘价买入）"""
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
            # 沪深300使用收盘价（无开盘价数据）
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

# ------------------------------------------------------------
# 滚动窗口测试器（与原逻辑一致，支持动态特征列）
# ------------------------------------------------------------
class RollingWindowTester:
    def __init__(self, model_config='simple'):
        self.models = self._initialize_models(model_config)
        self.results = []
        from sklearn.impute import SimpleImputer
        self.imputer = SimpleImputer(strategy='median')

    def _initialize_models(self, config):
        if config == 'simple':
            return {
                'ridge': RidgeCV(alphas=[0.1, 1.0, 10.0], cv=5),
                'lgbm': LGBMRegressor(
                    n_estimators=100, learning_rate=0.05, max_depth=5,
                    random_state=42, verbosity=-1, n_jobs=-1
                ),
                'xgb': XGBRegressor(
                    n_estimators=100, learning_rate=0.05, max_depth=5,
                    random_state=42, verbosity=0, n_jobs=-1
                )
            }
        else:
            # 复杂配置（与原代码一致，此处略）
            return {
                'ridge': RidgeCV(alphas=np.logspace(-3, 3, 7), cv=5),
                'lgbm': LGBMRegressor(
                    n_estimators=200, num_leaves=31, learning_rate=0.03,
                    subsample=0.8, colsample_bytree=0.8, reg_alpha=0.1, reg_lambda=0.1,
                    random_state=42, verbosity=-1, n_jobs=-1
                ),
                'xgb': XGBRegressor(
                    n_estimators=150, learning_rate=0.03, max_depth=5,
                    subsample=0.8, colsample_bytree=0.8, reg_alpha=0.1, reg_lambda=1.0,
                    random_state=42, verbosity=0, n_jobs=-1
                )
            }

    def run_single_window(self, data, feature_cols, window_config, hs300_data, top_n=10):
        """
        执行单个窗口的训练、预测、选股、回测
        """
        horizon = 5  # 固定与标签计算一致

        # 1. 训练数据（防泄露）
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

        # 3. 提取特征和标签
        X_train_raw = train_data[feature_cols].values
        y_train = train_data['label'].values
        X_test_raw = test_data[feature_cols].values

        X_train = self.imputer.fit_transform(X_train_raw)
        X_test = self.imputer.transform(X_test_raw)
        test_stocks = test_data['ts_code'].values

        # 4. 训练并预测
        predictions = {}
        for name, model in self.models.items():
            try:
                if name == 'ridge' and (np.isnan(X_train).any() or np.isnan(y_train).any()):
                    # Ridge 存在 NaN 时使用 LGBM 回退
                    lgbm_fallback = LGBMRegressor(
                        n_estimators=100, learning_rate=0.05, max_depth=5,
                        random_state=42, verbosity=-1, n_jobs=-1
                    )
                    lgbm_fallback.fit(X_train, y_train)
                    predictions[name] = lgbm_fallback.predict(X_test)
                else:
                    model.fit(X_train, y_train)
                    predictions[name] = model.predict(X_test)
            except Exception as e:
                print(f"  模型 {name} 失败: {e}")
                predictions[name] = np.zeros(len(X_test))

        final_pred = np.mean(list(predictions.values()), axis=0)

        # 5. 选股（剔除 T+1 无法买入）
        next_day_data = data[data['trade_date'] == window_config['test_start']]
        pred_df = pd.DataFrame({'ts_code': test_stocks, 'pred_score': final_pred})
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
            # 涨停检查
            pre_close = m_info['pre_close'].iloc[0]
            open_price = m_info['open'].iloc[0]
            is_limit_up = (open_price >= round(pre_close * 1.098, 2)) if pre_close > 0 else False
            if is_suspended or is_limit_up:
                continue
            selected_stocks.append(code)
            selected_scores.append(row['pred_score'])
            stock_details.append({'ts_code': code, 'pred_score': row['pred_score']})

        # 6. 计算测试期收益
        test_period_mask = (data['trade_date'] >= window_config['test_start']) & \
                           (data['trade_date'] <= window_config['test_end'])
        test_period_data = data[test_period_mask].copy()
        portfolio_data = test_period_data[test_period_data['ts_code'].isin(selected_stocks)]

        if len(portfolio_data) == 0:
            portfolio_return = 0.0
        else:
            unique_dates = sorted(portfolio_data['trade_date'].unique())
            daily_returns = []
            for i, date in enumerate(unique_dates):
                day_data = portfolio_data[portfolio_data['trade_date'] == date]
                if i == 0:
                    day_return = ((day_data['close'] - day_data['open']) / day_data['open']).mean()
                else:
                    day_return = day_data['pct_chg'].mean() / 100
                # 交易成本
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
            'model_predictions': {k: v.tolist() for k, v in predictions.items()},
            'stock_details': stock_details,
            'feature_cols': feature_cols
        }
        return result

    def analyze_results(self):
        """与原代码完全相同，此处省略以节省篇幅，请复制原analyze_results函数"""
        if not self.results:
            print("没有测试结果")
            return None
        print("\n" + "=" * 60)
        print("测试结果分析")
        print("=" * 60)
        portfolio_returns = [r['portfolio_return'] for r in self.results]
        hs300_returns = [r['hs300_return'] for r in self.results]
        excess_returns = [r['excess_return'] for r in self.results]
        total_portfolio_return = np.prod([1 + r for r in portfolio_returns]) - 1
        total_hs300_return = np.prod([1 + r for r in hs300_returns]) - 1
        total_excess_return = np.prod([1 + r for r in excess_returns]) - 1
        test_days_per_window = 5
        total_days = len(self.results) * test_days_per_window
        if total_days > 0:
            annualized_portfolio = (1 + total_portfolio_return) ** (252 / total_days) - 1
            annualized_hs300 = (1 + total_hs300_return) ** (252 / total_days) - 1
            annualized_excess = (1 + total_excess_return) ** (252 / total_days) - 1
        else:
            annualized_portfolio = annualized_hs300 = annualized_excess = 0.0
        win_rate = sum(1 for r in excess_returns if r > 0) / len(excess_returns) if excess_returns else 0.0
        print(f"测试窗口数: {len(self.results)}")
        print(f"总测试天数: {total_days}")
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
            'n_windows': len(self.results)
        }

    def plot_results(self, portfolio_returns, hs300_returns, excess_returns):
        # 直接复制原代码
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

# ------------------------------------------------------------
# 主函数
def main():
    # ========== 1. 参数配置 ==========
    YAML_PATH = r"E:\tradingagents\core\stock_selection\short_term_factors.yaml"
    HS300_TOKEN = "41bc8be1587c976380a7776cb3d0e74a563aecfbfa1bef98670eb601"

    # ========== 2. 加载数据（不变）==========
    loader = StockDataLoader(HS300_TOKEN)
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

    # 全局交易日列表（排序后）
    all_dates = sorted(full_data['trade_date'].unique())
    start_date = all_dates[0]
    end_date = all_dates[-1]
    hs300_data = loader.load_hs300_data(start_date, end_date)

    # ========== 3. 解析因子有效时期 ==========
    period_manager = FactorPeriodManager(YAML_PATH, last_period_extra_days=45)
    print("\n因子有效时期划分:")
    for i, p in enumerate(period_manager.periods):
        print(f"  区间{i+1}: {p['start'].date()} 至 {p['end'].date()} 因子数: {len(p['factors'])}")

    # ========== 4. 计算标签（未来5天超额收益） ==========
    print("\n计算标签...")
    try:
        data_with_label = loader.calculate_labels(full_data, hs300_data, horizon=5)
    except Exception as e:
        print(f"计算标签失败: {e}")
        traceback.print_exc()
        return None, None

    # ========== 5. 构建窗口（连续滚动，训练窗口可跨区间）==========
    train_window_len = 15         # 训练窗口长度（交易日）
    holding_period = 5           # 持仓周期（交易日）
    step = holding_period       # 滚动步长 = 持仓周期（不重叠）
    window_configs = []         # 存放所有窗口配置

    # 全局交易日索引映射
    date_to_idx = {d: i for i, d in enumerate(all_dates)}
    total_dates = len(all_dates)

    for period_idx, period in enumerate(period_manager.periods):
        period_start = pd.to_datetime(period['start'])
        period_end = pd.to_datetime(period['end'])

        # 获取该区间在全局交易日中的索引范围 [start_idx, end_idx)
        if period_start not in date_to_idx:
            print(f"  区间 {period_idx+1}: 起始日 {period_start.date()} 不是交易日，跳过")
            continue
        start_idx = date_to_idx[period_start]

        # 找到最后一个小于 period_end 的交易日索引
        end_idx = start_idx
        while end_idx < total_dates and all_dates[end_idx] < period_end:
            end_idx += 1
        # end_idx 是第一个 >= period_end 的索引，区间内交易日索引为 [start_idx, end_idx-1]

        if start_idx >= end_idx:
            print(f"  区间 {period_idx+1}: 无交易日，跳过")
            continue

        print(f"\n区间 {period_idx+1}: {period_start.date()} ~ {period_end.date()} 交易日索引: {start_idx}~{end_idx-1}")

        # ---------- 1. 第一个区间：只能从内部开始 ----------
        if period_idx == 0:
            # 需要足够的交易日才能形成第一个训练窗口
            first_signal_idx = start_idx + train_window_len
            if first_signal_idx > end_idx - 1:
                print(f"  第一个区间交易日不足，无法生成任何窗口")
                continue
            cur_idx = first_signal_idx
        else:
            # ---------- 2. 非首个区间：在区间起始日立即生成一个窗口 ----------
            # 训练窗口使用 start_idx 之前的数据（需保证有足够的历史数据）
            if start_idx >= train_window_len:
                train_start_idx = start_idx - train_window_len
                train_end_idx = start_idx - 1
                signal_idx = start_idx
                hold_start_idx = signal_idx + 1
                hold_end_idx = hold_start_idx + holding_period - 1

                # 检查索引是否越界
                if hold_end_idx < total_dates:
                    window_configs.append({
                        'train_start': all_dates[train_start_idx],
                        'train_end': all_dates[train_end_idx],
                        'test_date': all_dates[signal_idx],
                        'test_start': all_dates[hold_start_idx],
                        'test_end': all_dates[hold_end_idx],
                        'period_idx': period_idx
                    })
                    print(f"    添加起始窗口: 信号日 {all_dates[signal_idx].date()}")
                else:
                    print(f"    起始窗口超出全局数据范围，跳过")
            else:
                print(f"    起始日之前无足够训练数据，跳过起始窗口")

            # 后续窗口从 start_idx + step 开始滑动
            cur_idx = start_idx + step

        # ---------- 3. 滚动生成当前区间内的后续窗口 ----------
        while cur_idx <= end_idx - 1:
            # 训练窗口使用 [cur_idx - train_window_len, cur_idx - 1]
            train_start_idx = cur_idx - train_window_len
            train_end_idx = cur_idx - 1

            # 必须保证训练窗口不越界且完全在信号日之前
            if train_start_idx < 0:
                cur_idx += step
                continue

            signal_idx = cur_idx
            hold_start_idx = signal_idx + 1
            hold_end_idx = hold_start_idx + holding_period - 1

            if hold_end_idx >= total_dates:
                # 持仓期超出数据范围，停止当前区间
                break

            window_configs.append({
                'train_start': all_dates[train_start_idx],
                'train_end': all_dates[train_end_idx],
                'test_date': all_dates[signal_idx],
                'test_start': all_dates[hold_start_idx],
                'test_end': all_dates[hold_end_idx],
                'period_idx': period_idx
            })

            cur_idx += step

    print(f"\n共构建 {len(window_configs)} 个测试窗口")

    # ========== 6. 逐个窗口运行回测 ==========
    tester = RollingWindowTester(model_config='simple')
    all_results = []

    for idx, cfg in enumerate(window_configs):
        print(f"\n{'='*50}\n窗口 {idx+1}/{len(window_configs)}")
        print(f"  信号日: {cfg['test_date'].date()} | 训练: {cfg['train_start'].date()} ~ {cfg['train_end'].date()}")
        print(f"  持仓期: {cfg['test_start'].date()} ~ {cfg['test_end'].date()}")

        # 根据信号日获取当期有效因子列表
        signal_date = cfg['test_date']
        factor_names = period_manager.get_factors_for_date(signal_date)
        if not factor_names:
            print(f"  警告: 信号日 {signal_date.date()} 无对应因子，跳过该窗口")
            continue

        # 特征列 = 当期因子名（必须存在于数据中）
        feature_cols = [col for col in factor_names if col in data_with_label.columns]
        missing = set(factor_names) - set(feature_cols)
        if missing:
            print(f"  警告: 以下因子在数据中不存在: {missing}")

        # 可选加入市值对数
        if 'log_circ_mv' in data_with_label.columns:
            feature_cols.append('log_circ_mv')

        print(f"  当期有效因子数: {len(feature_cols)}")

        try:
            result = tester.run_single_window(
                data=data_with_label,
                feature_cols=feature_cols,
                window_config=cfg,
                hs300_data=hs300_data,
                top_n=10
            )
            result['window_id'] = idx + 1
            all_results.append(result)
            print(f"  组合收益: {result['portfolio_return']:.2%} | 沪深300: {result['hs300_return']:.2%} | 超额: {result['excess_return']:.2%}")
            
            # ========== 新增：输出选中的10只股票 ==========
            print(f"  选中的股票列表 (共{len(result['selected_stocks'])}只):")
            for i, stock_info in enumerate(result['stock_details'], 1):
                print(f"    第{i}名: {stock_info['ts_code']} (预测得分: {stock_info['pred_score']:.6f})")
            
        except Exception as e:
            print(f"  窗口执行失败: {e}")
            import traceback
            traceback.print_exc()
            continue
        tester.results = all_results
        final_stats = tester.analyze_results()

    # 输出详细结果（略，与之前相同）
    if all_results:
        print("\n详细窗口结果:")
        for res in all_results:
            print(f"\n窗口 {res['window_id']}:")
            print(f"  训练期: {res['train_period']}")
            print(f"  测试期: {res['test_period']}")
            print(f"  选中股票数: {len(res['selected_stocks'])}")
            print(f"  组合收益: {res['portfolio_return']:.2%}")
            print(f"  沪深300收益: {res['hs300_return']:.2%}")
            print(f"  超额收益: {res['excess_return']:.2%}")
    else:
        print("没有成功执行的窗口")

    return all_results, final_stats

if __name__ == "__main__":
    results, stats = main()
    if stats:
        print("\n最终统计摘要:")
        for k, v in stats.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.2%}")
            else:
                print(f"  {k}: {v}")