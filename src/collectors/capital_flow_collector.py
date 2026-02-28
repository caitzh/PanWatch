"""资金流向采集器 - 基于东方财富 API"""
import logging
from dataclasses import dataclass

import httpx

from src.core.cn_symbol import is_cn_sh
from src.models.market import MarketCode

logger = logging.getLogger(__name__)

# 东方财富资金流向 API（fflow 接口）
# push2: 实时数据（仅当日），push2his: 历史数据（含当日）
EASTMONEY_FLOW_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/kline/get"


@dataclass
class CapitalFlow:
    """资金流向数据"""
    symbol: str
    name: str

    # 今日资金流（单位：元）
    main_net_inflow: float      # 主力净流入（大单+超大单）
    main_net_inflow_pct: float  # 主力净流入占比（估算）
    super_net_inflow: float     # 超大单净流入
    big_net_inflow: float       # 大单净流入
    mid_net_inflow: float       # 中单净流入
    small_net_inflow: float     # 小单净流入

    # 5日资金流
    main_net_5d: float | None = None  # 5日主力净流入


def _get_eastmoney_secid(symbol: str, market: MarketCode) -> str:
    """转换为东方财富的 secid 格式"""
    if market == MarketCode.HK:
        return f"116.{symbol}"
    if market == MarketCode.US:
        return f"105.{symbol}"
    prefix = "1" if is_cn_sh(symbol) else "0"
    return f"{prefix}.{symbol}"


class CapitalFlowCollector:
    """资金流向采集器"""

    def __init__(self, market: MarketCode):
        self.market = market

    def get_capital_flow(self, symbol: str) -> CapitalFlow | None:
        """获取单只股票的资金流向"""
        secid = _get_eastmoney_secid(symbol, self.market)

        # 使用 fflow API 获取资金流向
        # klt=101 表示日线，lmt=5 表示最近5天
        params = {
            "secid": secid,
            "klt": "101",
            "lmt": "5",
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/",
        }

        try:
            with httpx.Client(follow_redirects=True, timeout=4) as client:
                resp = client.get(EASTMONEY_FLOW_URL, params=params, headers=headers)
                data = resp.json()

            if data.get("data") is None or data["data"].get("klines") is None:
                logger.warning(f"获取 {symbol} 资金流向失败: 无数据")
                return None

            klines = data["data"]["klines"]
            if not klines:
                logger.warning(f"获取 {symbol} 资金流向失败: klines 为空")
                return None

            name = data["data"].get("name", "")

            # 解析最近一天的数据（klines 按时间从旧到新排序，取最后一条）
            # 格式: 日期,主力净流入,小单净流入,中单净流入,大单净流入,超大单净流入
            today_parts = klines[-1].split(",")
            if len(today_parts) < 6:
                logger.warning(f"获取 {symbol} 资金流向失败: 数据格式错误")
                return None

            main_net_inflow = float(today_parts[1])      # 主力净流入
            small_net_inflow = float(today_parts[2])     # 小单净流入
            mid_net_inflow = float(today_parts[3])       # 中单净流入
            big_net_inflow = float(today_parts[4])       # 大单净流入
            super_net_inflow = float(today_parts[5])     # 超大单净流入

            # 计算主力净流入占比（基于总成交额的估算）
            # 主力净流入占比 = 主力净流入 / (|主力净流入| + |中单净流入| + |小单净流入|) * 100
            total_flow = abs(main_net_inflow) + abs(mid_net_inflow) + abs(small_net_inflow)
            if total_flow > 0:
                main_net_inflow_pct = main_net_inflow / total_flow * 100
            else:
                main_net_inflow_pct = 0

            # 计算5日主力净流入
            main_net_5d = None
            if len(klines) >= 1:
                main_net_5d = sum(float(k.split(",")[1]) for k in klines)

            return CapitalFlow(
                symbol=symbol,
                name=name,
                main_net_inflow=main_net_inflow,
                main_net_inflow_pct=main_net_inflow_pct,
                super_net_inflow=super_net_inflow,
                big_net_inflow=big_net_inflow,
                mid_net_inflow=mid_net_inflow,
                small_net_inflow=small_net_inflow,
                main_net_5d=main_net_5d,
            )

        except Exception as e:
            logger.error(f"获取 {symbol} 资金流向失败: {e}")
            return None

    def get_capital_flow_summary(self, symbol: str) -> dict:
        """获取资金流向摘要（用于 prompt）"""
        flow = self.get_capital_flow(symbol)

        if not flow:
            return {"error": "无资金流向数据"}

        # 判断资金状态
        if flow.main_net_inflow > 0:
            if flow.main_net_inflow_pct > 10:
                status = "主力大幅流入"
            elif flow.main_net_inflow_pct > 5:
                status = "主力明显流入"
            else:
                status = "主力小幅流入"
        elif flow.main_net_inflow < 0:
            if flow.main_net_inflow_pct < -10:
                status = "主力大幅流出"
            elif flow.main_net_inflow_pct < -5:
                status = "主力明显流出"
            else:
                status = "主力小幅流出"
        else:
            status = "主力资金平衡"

        # 5日趋势
        trend_5d = "无数据"
        if flow.main_net_5d is not None:
            if flow.main_net_5d > 0:
                trend_5d = f"5日净流入{flow.main_net_5d/1e8:.2f}亿"
            else:
                trend_5d = f"5日净流出{abs(flow.main_net_5d)/1e8:.2f}亿"

        return {
            "status": status,
            "main_net_inflow": flow.main_net_inflow,
            "main_net_inflow_pct": flow.main_net_inflow_pct,
            "super_net_inflow": flow.super_net_inflow,
            "big_net_inflow": flow.big_net_inflow,
            "mid_net_inflow": flow.mid_net_inflow,
            "small_net_inflow": flow.small_net_inflow,
            "trend_5d": trend_5d,
        }
