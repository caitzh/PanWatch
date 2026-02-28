"""基本面数据采集器 - 使用 AKShare stock_financial_abstract 获取季报关键指标"""
import logging
import time
from typing import ClassVar

logger = logging.getLogger(__name__)

# 报告期月份 -> 季度标签
_QUARTER_MAP = {"03": "Q1", "06": "Q2", "09": "Q3", "12": "Q4"}


def _date_to_period_label(date_str: str) -> str:
    """将 20250930 格式转换为 2025Q3"""
    if len(date_str) != 8:
        return date_str
    year = date_str[:4]
    month = date_str[4:6]
    quarter = _QUARTER_MAP.get(month, f"M{month}")
    return f"{year}{quarter}"


def _safe_float(value) -> float | None:
    """安全转换为 float，失败返回 None"""
    try:
        v = float(value)
        if v != v:  # NaN check
            return None
        return v
    except (TypeError, ValueError):
        return None


def _yoy_growth(latest, prev_year) -> float | None:
    """计算同比增速（%）"""
    a = _safe_float(latest)
    b = _safe_float(prev_year)
    if a is None or b is None or b == 0:
        return None
    return (a - b) / abs(b) * 100


class FundamentalCollector:
    """基本面数据采集器（AKShare stock_financial_abstract）

    使用进程级 TTL 缓存（24 小时），季报数据无需频繁刷新。
    """

    # 进程级 TTL 缓存：symbol -> (timestamp, data_dict)
    _cache: ClassVar[dict[str, tuple[float, dict]]] = {}
    _TTL: ClassVar[int] = 86400  # 24 小时

    def get_fundamental_summary(self, symbol: str) -> dict:
        """
        获取最新季报关键指标。

        返回格式：
        {
            "report_date": "20250930",
            "period_label": "2025Q3",
            "revenue": 5.12e9,          # 营业总收入（元）
            "revenue_yoy": -45.7,        # 同比增速（%）
            "net_profit": -1.55e8,       # 归母净利润（元）
            "net_profit_yoy": -33.2,     # 同比增速（%）
            "roe": -2.93,                # 净资产收益率（%）
            "gross_margin": 11.1,        # 毛利率（%）
            "debt_ratio": 69.7,          # 资产负债率（%）
            "eps": -0.097,               # 基本每股收益（元）
        }

        失败时返回 {"error": "..."} 。
        """
        # 检查缓存
        now = time.time()
        if symbol in self._cache:
            ts, data = self._cache[symbol]
            if now - ts < self._TTL:
                return data

        try:
            import akshare as ak

            df = ak.stock_financial_abstract(symbol=symbol)
            result = self._parse_df(df)
            self._cache[symbol] = (now, result)
            return result
        except Exception as e:
            # ETF/指数没有财报数据属正常情况，降为 DEBUG 级别
            logger.debug(f"FundamentalCollector {symbol} 获取失败: {e}")
            return {"error": str(e)}

    @staticmethod
    def _parse_df(df) -> dict:
        """从 DataFrame 中提取关键指标"""
        if df is None or not hasattr(df, "columns") or df.empty:
            return {"error": "无财务数据（可能是 ETF/指数）"}

        # 指标名称 -> 行索引的映射
        indicator_to_idx: dict[str, int] = {}
        for i, row in df.iterrows():
            name = str(row.get("指标", "")).strip()
            if name:
                indicator_to_idx[name] = i

        # 日期列：从第 3 列开始（索引 2），去掉前两列（选项/指标）
        date_cols = [c for c in df.columns if c not in ("选项", "指标")]
        if len(date_cols) < 5:
            return {"error": "数据列不足"}

        latest_col = date_cols[0]    # 最新季
        prev_year_col = date_cols[4] if len(date_cols) > 4 else None  # 去年同季（相差 4 季）

        def get_val(indicator: str, col: str) -> float | None:
            idx = indicator_to_idx.get(indicator)
            if idx is None:
                return None
            return _safe_float(df.at[idx, col])

        # 最新季数据
        revenue = get_val("营业总收入", latest_col)
        net_profit = get_val("归母净利润", latest_col)
        roe = get_val("净资产收益率(ROE)", latest_col)
        gross_margin = get_val("毛利率", latest_col)
        debt_ratio = get_val("资产负债率", latest_col)
        eps = get_val("基本每股收益", latest_col)

        # 同比增速
        revenue_yoy = None
        net_profit_yoy = None
        if prev_year_col:
            revenue_yoy = _yoy_growth(revenue, get_val("营业总收入", prev_year_col))
            net_profit_yoy = _yoy_growth(net_profit, get_val("归母净利润", prev_year_col))

        result: dict = {
            "report_date": latest_col,
            "period_label": _date_to_period_label(latest_col),
        }

        if revenue is not None:
            result["revenue"] = revenue
        if revenue_yoy is not None:
            result["revenue_yoy"] = round(revenue_yoy, 1)
        if net_profit is not None:
            result["net_profit"] = net_profit
        if net_profit_yoy is not None:
            result["net_profit_yoy"] = round(net_profit_yoy, 1)
        if roe is not None:
            result["roe"] = round(roe, 2)
        if gross_margin is not None:
            result["gross_margin"] = round(gross_margin, 1)
        if debt_ratio is not None:
            result["debt_ratio"] = round(debt_ratio, 1)
        if eps is not None:
            result["eps"] = eps

        return result
