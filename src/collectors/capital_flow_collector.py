"""资金流向采集器 - 基于东方财富 API"""
import logging
from dataclasses import dataclass

import httpx

from src.core.cn_symbol import is_cn_sh
from src.models.market import MarketCode

logger = logging.getLogger(__name__)

# 东方财富资金流向 API（使用 delay 版本更稳定）
EASTMONEY_FLOW_URL = "https://push2delay.eastmoney.com/api/qt/stock/get"


@dataclass
class CapitalFlow:
    """资金流向数据"""
    symbol: str
    name: str

    # 今日资金流（单位：元）
    main_net_inflow: float      # 主力净流入
    main_net_inflow_pct: float  # 主力净流入占比
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

        params = {
            "secid": secid,
            "fields": "f57,f58,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f64,f65,f70,f71,f76,f77,f82,f83,f164,f166,f168,f170,f172,f252,f253,f254,f255,f256",
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/",
        }

        try:
            with httpx.Client(follow_redirects=True, timeout=8) as client:
                resp = client.get(EASTMONEY_FLOW_URL, params=params, headers=headers)
                data = resp.json()

            if data.get("data") is None:
                logger.warning(f"获取 {symbol} 资金流向失败: 无数据")
                return None

            d = data["data"]

            return CapitalFlow(
                symbol=str(d.get("f57", symbol)),
                name=str(d.get("f58", "")),
                main_net_inflow=float(d.get("f62", 0)),        # 主力净流入
                main_net_inflow_pct=float(d.get("f184", 0)),   # 主力净流入占比
                super_net_inflow=float(d.get("f66", 0)),       # 超大单净流入
                big_net_inflow=float(d.get("f72", 0)),         # 大单净流入
                mid_net_inflow=float(d.get("f78", 0)),         # 中单净流入
                small_net_inflow=float(d.get("f84", 0)),       # 小单净流入
                main_net_5d=float(d.get("f164", 0)) if d.get("f164") else None,
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
