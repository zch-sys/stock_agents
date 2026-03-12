"""
板块数据转换器
SectorData → SectorAnalysisData
"""
from typing import List, Optional
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.transformers.base_transformer import BaseTransformer, TransformerRegistry
from data.schemas.sector_schema import (
    SectorAnalysisData, SectorStatistics, SectorCapitalFlow
)
from data.schemas.base_schema import PriceData, IndicatorValue
from data.judgments.capital_judgments import judge_sector_fund_flow


@TransformerRegistry.register('sector')
class SectorTransformer(BaseTransformer):
    """
    板块数据转换器
    
    将SectorData ORM对象转换为SectorAnalysisData
    """
    
    def transform(self, data) -> SectorAnalysisData:
        """
        转换单条板块数据
        
        Args:
            data: SectorData ORM对象
            
        Returns:
            SectorAnalysisData
        """
        if not self.validate_input(data):
            return self._create_empty_result(data)
        
        price_data = self._extract_price_data(data)
        statistics = self._extract_statistics(data)
        capital_flow = self._extract_capital_flow(data)
        
        capital_flow_signal = judge_sector_fund_flow(
            fund_inflow=self.safe_float(data.fund_inflow),
            fund_inflow_rate=self.safe_float(data.fund_inflow_rate)
        )
        
        sector_strength = self._calc_sector_strength(data)
        
        constituent_stocks = []
        if data.constituent_stocks:
            if isinstance(data.constituent_stocks, list):
                constituent_stocks = data.constituent_stocks
            elif isinstance(data.constituent_stocks, str):
                constituent_stocks = [s.strip() for s in data.constituent_stocks.split(',') if s.strip()]
        
        return SectorAnalysisData(
            trade_date=str(data.trade_date) if data.trade_date else "",
            sector_code=self.safe_str(data.sector_code),
            sector_name=self.safe_str(data.sector_name),
            price_data=price_data,
            statistics=statistics,
            capital_flow=capital_flow,
            rank=self.safe_int(data.rank),
            total_market_cap=self.safe_float(data.total_market_cap),
            circ_market_cap=self.safe_float(data.circ_market_cap),
            constituent_stocks=constituent_stocks,
            capital_flow_signal=capital_flow_signal,
            sector_strength=sector_strength
        )
    
    def transform_batch(self, data_list: List) -> List[SectorAnalysisData]:
        """
        批量转换板块数据，并计算相对排名
        
        Args:
            data_list: SectorData对象列表
            
        Returns:
            SectorAnalysisData列表
        """
        results = [self.transform(data) for data in data_list]
        
        if results:
            sorted_by_inflow = sorted(
                results, 
                key=lambda x: x.capital_flow.fund_inflow if x.capital_flow else 0,
                reverse=True
            )
            for i, item in enumerate(sorted_by_inflow):
                item.rank = i + 1
        
        return results
    
    def _extract_price_data(self, data) -> PriceData:
        """提取价格数据"""
        return PriceData(
            open=self.safe_float(data.open),
            close=self.safe_float(data.close),
            high=self.safe_float(data.high),
            low=self.safe_float(data.low),
            pct_chg=self.safe_float(data.pct_chg),
            vol=self.safe_float(data.vol),
            amount=self.safe_float(data.amount),
            pre_close=self.safe_float(data.pre_close)
        )
    
    def _extract_statistics(self, data) -> SectorStatistics:
        """提取板块统计数据"""
        return SectorStatistics(
            stock_count=self.safe_int(data.stock_count),
            rise_count=self.safe_int(data.rise_count),
            fall_count=self.safe_int(data.fall_count),
            unchanged_count=self.safe_int(getattr(data, 'unchanged_count', 0)),
            rise_fall_ratio=self.safe_float(data.rise_fall_ratio),
            avg_pct_chg=self.safe_float(data.avg_pct_chg),
            max_pct_chg=self.safe_float(data.max_pct_chg),
            min_pct_chg=self.safe_float(data.min_pct_chg),
            median_pct_chg=self.safe_float(data.median_pct_chg),
            std_pct_chg=self.safe_float(data.std_pct_chg)
        )
    
    def _extract_capital_flow(self, data) -> SectorCapitalFlow:
        """提取资金流向数据"""
        return SectorCapitalFlow(
            fund_inflow=self.safe_float(data.fund_inflow),
            fund_inflow_rate=self.safe_float(data.fund_inflow_rate),
            rise_amount=self.safe_float(data.rise_amount),
            fall_amount=self.safe_float(data.fall_amount)
        )
    
    def _calc_sector_strength(self, data) -> IndicatorValue:
        """
        计算板块强度
        
        综合涨跌幅、资金流向、涨跌家数比等指标
        """
        score = 0.0
        descriptions = []
        
        pct_chg = self.safe_float(data.pct_chg)
        if pct_chg > 2:
            score += 30
            descriptions.append(f"涨幅{pct_chg:.2f}%")
        elif pct_chg > 0:
            score += 15
            descriptions.append(f"涨幅{pct_chg:.2f}%")
        elif pct_chg < -2:
            score -= 30
            descriptions.append(f"跌幅{abs(pct_chg):.2f}%")
        elif pct_chg < 0:
            score -= 15
            descriptions.append(f"跌幅{abs(pct_chg):.2f}%")
        
        fund_inflow = self.safe_float(data.fund_inflow)
        if fund_inflow > 0:
            score += min(30, fund_inflow / 1e8)
            descriptions.append(f"资金流入{fund_inflow/1e8:.2f}亿")
        else:
            score += max(-30, fund_inflow / 1e8)
            descriptions.append(f"资金流出{abs(fund_inflow)/1e8:.2f}亿")
        
        rise_fall_ratio = self.safe_float(data.rise_fall_ratio)
        if rise_fall_ratio > 2:
            score += 20
            descriptions.append("涨跌比高")
        elif rise_fall_ratio < 0.5:
            score -= 20
            descriptions.append("涨跌比低")
        
        score = max(-100, min(100, score))
        
        if score > 50:
            return IndicatorValue.bullish(score, f"板块强势：{'; '.join(descriptions)}")
        elif score > 20:
            return IndicatorValue.bullish(score, f"板块偏强：{'; '.join(descriptions)}")
        elif score < -50:
            return IndicatorValue.bearish(score, f"板块弱势：{'; '.join(descriptions)}")
        elif score < -20:
            return IndicatorValue.bearish(score, f"板块偏弱：{'; '.join(descriptions)}")
        else:
            return IndicatorValue.neutral(score, f"板块中性：{'; '.join(descriptions)}")
    
    def _create_empty_result(self, data) -> SectorAnalysisData:
        """创建空结果"""
        return SectorAnalysisData(
            trade_date=str(data.trade_date) if data and data.trade_date else "",
            sector_code=self.safe_str(getattr(data, 'sector_code', None), ''),
            sector_name=self.safe_str(getattr(data, 'sector_name', None), '')
        )
